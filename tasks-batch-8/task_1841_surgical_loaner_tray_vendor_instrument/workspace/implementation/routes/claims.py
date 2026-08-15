"""DamageLossClaim routes: manual filing, apportion (OCC), dispute, settle."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request as flask_request

import db
from errors import raise_err
from middleware import get_auth, require_role, get_body, req_str, req_enum, req_int
from response import success_object, success_list, parse_pagination
from services import core

bp = Blueprint("claims", __name__)

DAMAGE_TYPES = {"LOSS", "DAMAGE", "CONTAMINATION"}
CLAIM_ELIGIBLE_TRAY_STATES = {"PICKED_UP", "RECONCILED", "QUARANTINED"}


def _get_claim_or_404(claim_id):
    c = db.claims.get(claim_id)
    if c is None:
        raise_err("ERR_CLAIM_NOT_FOUND", "Claim not found")
    return c


def _next_claim_seq(request_id: str) -> int:
    return sum(1 for c in db.claims.values() if c["request_id"] == request_id) + 1


def _presumptive_percent(damage_type: str) -> int:
    return {"LOSS": 100, "DAMAGE": 50, "CONTAMINATION": 0}[damage_type]


def _final_shares(claimed_amount_cents: int, vendor_share_percent: int):
    vendor_share = int(
        (Decimal(claimed_amount_cents) * Decimal(vendor_share_percent) / Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    return vendor_share, claimed_amount_cents - vendor_share


@bp.post("/claims")
def create_claim():
    _, role = get_auth()
    body = get_body(required=True)
    require_role(role, ["VendorCoordinator"])

    tray_id = req_str(body, "tray_id")
    request_id = req_str(body, "request_id")
    damage_type = req_enum(body, "damage_type", DAMAGE_TYPES)
    claimed_amount_cents = body.get("claimed_amount_cents")
    if claimed_amount_cents is None or isinstance(claimed_amount_cents, bool) or not isinstance(claimed_amount_cents, int):
        raise_err("ERR_VALIDATION", "claimed_amount_cents is required and must be an integer")

    # Existence, body field order: tray_id then request_id.
    tray = db.trays.get(tray_id)
    if tray is None:
        raise_err("ERR_TRAY_NOT_FOUND", "Tray not found")
    request = db.requests.get(request_id)
    if request is None:
        raise_err("ERR_REQUEST_NOT_FOUND", "Loaner request not found")

    # Claim's request linkage is denormalized from its tray: the two must agree.
    if tray["request_id"] != request_id:
        raise_err("ERR_TRAY_NOT_IN_REQUEST", "The tray does not belong to the named request")

    if claimed_amount_cents <= 0:
        raise_err("ERR_CLAIM_AMOUNT_INVALID", "claimed_amount_cents must be > 0")
    if tray["status"] not in CLAIM_ELIGIBLE_TRAY_STATES:
        raise_err("ERR_CLAIM_AMOUNT_INVALID", "Tray is not in a claim-eligible state")

    percent = _presumptive_percent(damage_type)
    provisional = int(
        (Decimal(claimed_amount_cents) * Decimal(percent) / Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )

    claim = {
        "tray_id": tray_id,
        "request_id": request_id,
        "pickup_id": None,
        "claim_seq": _next_claim_seq(request_id),
        "damage_type": damage_type,
        "shortage_count": 0,
        "claimed_amount_cents": claimed_amount_cents,
        "provisional_vendor_share_cents": provisional,
        "final_vendor_share_cents": None,
        "final_hospital_share_cents": None,
        "status": "FILED",
    }
    core.stamp_new(claim)
    db.claims[claim["id"]] = claim
    return success_object(core.serialize(claim), status=201)


@bp.get("/claims")
def list_claims():
    get_auth()
    tray_id = flask_request.args.get("tray_id")
    request_id = flask_request.args.get("request_id")
    pickup_id = flask_request.args.get("pickup_id")
    status = flask_request.args.get("status")
    # Deterministic order: created_at ASC, claim_seq ASC (id never used).
    items = sorted(db.claims.values(), key=lambda c: (c["created_at"], c["claim_seq"]))
    if tray_id:
        items = [c for c in items if c["tray_id"] == tray_id]
    if request_id:
        items = [c for c in items if c["request_id"] == request_id]
    if pickup_id:
        items = [c for c in items if c.get("pickup_id") == pickup_id]
    if status:
        items = [c for c in items if c["status"] == status]
    total = len(items)
    limit, offset = parse_pagination(flask_request.args)
    page = items[offset : offset + limit]
    return success_list([core.serialize(c) for c in page], limit, offset, total)


@bp.get("/claims/<id>")
def get_claim(id):
    get_auth()
    claim = _get_claim_or_404(id)
    return success_object(core.serialize(claim))


@bp.post("/claims/<id>/apportion")
def apportion_claim(id):
    _, role = get_auth()
    body = get_body(required=True)

    vendor_share_percent = body.get("vendor_share_percent")
    if vendor_share_percent is None or isinstance(vendor_share_percent, bool) or not isinstance(vendor_share_percent, int):
        raise_err("ERR_VALIDATION", "vendor_share_percent is required and must be an integer")
    expected = body.get("expected_claim_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise_err("ERR_VALIDATION", "expected_claim_version is required and must be an integer")

    require_role(role, ["VendorCoordinator"])
    claim = _get_claim_or_404(id)

    # OCC
    if expected != claim["version"]:
        raise_err("ERR_STALE_VERSION", "Claim version mismatch")

    if claim["status"] not in {"FILED", "DISPUTED"}:
        raise_err("ERR_CLAIM_INVALID_STATE", "Only a FILED or DISPUTED claim can be apportioned")

    if not (0 <= vendor_share_percent <= 100):
        raise_err("ERR_CLAIM_APPORTION_INVALID", "vendor_share_percent must be within [0, 100]")

    final_vendor, final_hospital = _final_shares(claim["claimed_amount_cents"], vendor_share_percent)
    claim["final_vendor_share_cents"] = final_vendor
    claim["final_hospital_share_cents"] = final_hospital
    claim["status"] = "APPORTIONED"
    core.touch(claim)

    request = db.requests.get(claim["request_id"])
    if request is not None:
        core.recompute_vendor_rollups(request["vendor_id"])

    return success_object(core.serialize(claim))


@bp.post("/claims/<id>/dispute")
def dispute_claim(id):
    user_id, role = get_auth()
    get_body()
    require_role(role, ["VendorRep"])
    claim = _get_claim_or_404(id)

    if claim["status"] != "APPORTIONED":
        raise_err("ERR_CLAIM_INVALID_STATE", "Only an APPORTIONED claim can be disputed")

    request = db.requests.get(claim["request_id"])
    rep = db.reps.get(user_id)
    if rep is None or request is None or rep["vendor_id"] != request["vendor_id"]:
        raise_err("ERR_REP_VENDOR_MISMATCH", "Rep does not belong to the claim request's vendor")

    claim["status"] = "DISPUTED"
    core.touch(claim)
    if request is not None:
        core.recompute_vendor_rollups(request["vendor_id"])
    return success_object(core.serialize(claim))


@bp.post("/claims/<id>/settle")
def settle_claim(id):
    _, role = get_auth()
    get_body()
    require_role(role, ["VendorCoordinator"])
    claim = _get_claim_or_404(id)

    if claim["status"] != "APPORTIONED":
        raise_err("ERR_CLAIM_INVALID_STATE", "Only an APPORTIONED claim can be settled")

    claim["status"] = "SETTLED"
    core.touch(claim)
    request = db.requests.get(claim["request_id"])
    if request is not None:
        core.recompute_vendor_rollups(request["vendor_id"])
    return success_object(core.serialize(claim))
