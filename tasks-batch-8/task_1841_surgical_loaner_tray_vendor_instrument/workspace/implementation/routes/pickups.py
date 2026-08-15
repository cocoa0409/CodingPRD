"""PickupRecord routes: creation, reconcile (with auto-claims), dispute."""

from decimal import Decimal

from flask import Blueprint, request as flask_request

import db
from errors import raise_err
from middleware import get_auth, require_role, get_body
from response import success_object, success_list, parse_pagination
from services import core

bp = Blueprint("pickups", __name__)


def _get_pickup_or_404(pickup_id):
    p = db.pickups.get(pickup_id)
    if p is None:
        raise_err("ERR_PICKUP_NOT_FOUND", "Pickup not found")
    return p


def _next_claim_seq(request_id: str) -> int:
    """1-based creation order within request_id."""
    return sum(1 for c in db.claims.values() if c["request_id"] == request_id) + 1


def _create_claim(request_id, tray_id, pickup_id, damage_type, shortage_count, claimed_amount_cents):
    from decimal import ROUND_HALF_UP

    presumptive = {"LOSS": 100, "DAMAGE": 50, "CONTAMINATION": 0}[damage_type]
    provisional = int(
        (Decimal(claimed_amount_cents) * Decimal(presumptive) / Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    claim = {
        "tray_id": tray_id,
        "request_id": request_id,
        "pickup_id": pickup_id,
        "claim_seq": _next_claim_seq(request_id),
        "damage_type": damage_type,
        "shortage_count": shortage_count,
        "claimed_amount_cents": claimed_amount_cents,
        "provisional_vendor_share_cents": provisional,
        "final_vendor_share_cents": None,
        "final_hospital_share_cents": None,
        "status": "FILED",
    }
    core.stamp_new(claim)
    db.claims[claim["id"]] = claim
    return claim


@bp.post("/requests/<id>/pickups")
def create_pickup(id):
    user_id, role = get_auth()
    body = get_body(required=True)

    lines = body.get("lines")
    if not isinstance(lines, list) or not lines:
        raise_err("ERR_VALIDATION", "lines must be a non-empty array")
    for line in lines:
        if not isinstance(line, dict):
            raise_err("ERR_VALIDATION", "each line must be an object")
        if not isinstance(line.get("tray_id"), str):
            raise_err("ERR_VALIDATION", "each line requires a tray_id string")
        count = line.get("instrument_count_returned")
        if count is None or isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise_err("ERR_VALIDATION", "instrument_count_returned must be a non-negative integer")
        if line.get("condition") not in {"OK", "DAMAGED"}:
            raise_err("ERR_VALIDATION", "condition must be OK or DAMAGED")

    require_role(role, ["VendorRep"])

    request = db.requests.get(id)
    if request is None:
        raise_err("ERR_REQUEST_NOT_FOUND", "Loaner request not found")

    if request["status"] != "APPROVED":
        raise_err("ERR_REQUEST_INVALID_STATE", "Pickup requires an APPROVED request")

    # Rep guards: credential ACTIVE + belongs to request's vendor.
    rep = db.reps.get(user_id)
    if rep is None:
        raise_err("ERR_REP_NOT_FOUND", "Representative not found")
    if rep["credential_status"] != "ACTIVE":
        raise_err("ERR_REP_CREDENTIAL_NOT_ACTIVE", "Rep credential is not ACTIVE")
    if rep["vendor_id"] != request["vendor_id"]:
        raise_err("ERR_REP_VENDOR_MISMATCH", "Rep does not belong to the request's vendor")

    seen = set()
    line_trays = []
    for line in lines:
        tray_id = line["tray_id"]
        if tray_id in seen:
            raise_err("ERR_DUPLICATE_TRAY_LINE", "same tray_id appears twice in pickup lines")
        seen.add(tray_id)
        tray = db.trays.get(tray_id)
        if tray is None:
            raise_err("ERR_TRAY_NOT_FOUND", "Tray not found")
        if tray["request_id"] != id:
            raise_err("ERR_TRAY_NOT_IN_REQUEST", "Tray belongs to a different request")
        if tray["status"] != "AWAITING_PICKUP":
            raise_err("ERR_TRAY_INVALID_STATE", "Tray must be AWAITING_PICKUP")
        if line["instrument_count_returned"] > (tray["delivered_instrument_count"] or 0):
            raise_err("ERR_PICKUP_COUNT_EXCEEDS_DELIVERED", "Returned count exceeds delivered count")
        line_trays.append((line, tray))

    pickup = {
        "request_id": id,
        "rep_id": user_id,
        "picked_up_at": db.fmt_ts(db.now_dt()),
        "lines": [
            {
                "tray_id": line["tray_id"],
                "instrument_count_returned": line["instrument_count_returned"],
                "condition": line["condition"],
            }
            for line in lines
        ],
        "status": "SUBMITTED",
        "reconciled_by_user_id": None,
        "discrepancy_count": 0,
    }
    core.stamp_new(pickup)
    db.pickups[pickup["id"]] = pickup

    for line, tray in line_trays:
        tray["status"] = "PICKED_UP"
        tray["returned_instrument_count"] = line["instrument_count_returned"]
        core.recompute_tray_projection(tray)
        core.touch(tray)
    core.recompute_readiness(request)
    core.touch(request)

    return success_object(core.serialize(pickup), status=201)


@bp.get("/pickups")
def list_pickups():
    get_auth()
    request_id = flask_request.args.get("request_id")
    rep_id = flask_request.args.get("rep_id")
    status = flask_request.args.get("status")
    items = sorted(db.pickups.values(), key=lambda p: p["_seq"])
    if request_id:
        items = [p for p in items if p["request_id"] == request_id]
    if rep_id:
        items = [p for p in items if p["rep_id"] == rep_id]
    if status:
        items = [p for p in items if p["status"] == status]
    total = len(items)
    limit, offset = parse_pagination(flask_request.args)
    page = items[offset : offset + limit]
    return success_list([core.serialize(p) for p in page], limit, offset, total)


@bp.get("/pickups/<id>")
def get_pickup(id):
    get_auth()
    pickup = _get_pickup_or_404(id)
    return success_object(core.serialize(pickup))


@bp.post("/pickups/<id>/reconcile")
def reconcile_pickup(id):
    user_id, role = get_auth()
    get_body()
    require_role(role, ["VendorCoordinator"])
    pickup = _get_pickup_or_404(id)

    if pickup["status"] not in {"SUBMITTED", "DISPUTED"}:
        raise_err("ERR_PICKUP_INVALID_STATE", "Pickup must be SUBMITTED or DISPUTED to reconcile")

    request = db.requests.get(pickup["request_id"])

    # Segregation of duties: reconciler must differ from the verifier of
    # every VERIFIED/PARTIALLY_VERIFIED check-in on the request.
    for ci in db.check_ins.values():
        if (
            ci["request_id"] == pickup["request_id"]
            and ci["status"] in {"VERIFIED", "PARTIALLY_VERIFIED"}
            and ci.get("verified_by_user_id") == user_id
        ):
            raise_err(
                "ERR_SEGREGATION_OF_DUTIES",
                "The verifying coordinator may not reconcile pickups of the same request",
            )

    pickup["reconciled_by_user_id"] = user_id
    pickup["status"] = "RECONCILED"

    discrepancy_count = 0
    for line in pickup["lines"]:
        tray = db.trays.get(line["tray_id"])
        if tray is None:
            continue
        delivered = tray["delivered_instrument_count"] or 0
        returned = tray["returned_instrument_count"] or 0
        shortage = delivered - returned
        tray["shortage_count"] = shortage
        tray["status"] = "RECONCILED"
        core.recompute_tray_projection(tray)
        core.touch(tray)

        has_discrepancy = False
        if shortage > 0:
            has_discrepancy = True
            claimed = core.round_half_up_cents(
                Decimal(tray["replacement_value_cents"])
                * Decimal(shortage)
                / Decimal(tray["declared_instrument_count"])
            )
            _create_claim(request["id"], tray["id"], None, "LOSS", shortage, claimed)
        if line["condition"] == "DAMAGED":
            has_discrepancy = True
            _create_claim(request["id"], tray["id"], None, "DAMAGE", 0, tray["replacement_value_cents"])
        if has_discrepancy:
            discrepancy_count += 1

    pickup["discrepancy_count"] = discrepancy_count
    core.touch(pickup)

    if request is not None:
        core.recompute_readiness(request)
        core.request_bubble_up_close(request)

    return success_object(core.serialize(pickup))


@bp.post("/pickups/<id>/dispute")
def dispute_pickup(id):
    user_id, role = get_auth()
    get_body()
    require_role(role, ["VendorRep"])
    pickup = _get_pickup_or_404(id)

    if pickup["status"] != "SUBMITTED":
        raise_err("ERR_PICKUP_INVALID_STATE", "Only a SUBMITTED pickup can be disputed")

    request = db.requests.get(pickup["request_id"])
    rep = db.reps.get(user_id)
    if rep is None or request is None or rep["vendor_id"] != request["vendor_id"]:
        raise_err("ERR_REP_VENDOR_MISMATCH", "Rep does not belong to the request's vendor")

    pickup["status"] = "DISPUTED"
    core.touch(pickup)
    return success_object(core.serialize(pickup))
