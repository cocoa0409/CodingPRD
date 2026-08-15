"""P-card program: issuance, limits (OCC), lifecycle, statement-cycle
checkpoint, and limit-elevation windows (PRD 3.7/3.8)."""

from datetime import timedelta

import db
import services as svc
from middleware import authenticate, ROLES
from response import success_obj, success_list
from routes import make_blueprint
from util import (
    body_json,
    check_shape,
    pagination_params,
    paginate,
    apply_filters,
    require_fk,
    parse_dt,
)
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_LIMIT_INCONSISTENT,
    ERR_STALE_VERSION,
    ERR_CARD_STATE_INVALID,
    ERR_CARD_CLOSED,
    ERR_CARD_HAS_OPEN_TRANSACTIONS,
    ERR_ELEVATION_STATE_INVALID,
    ERR_ELEVATION_OVERLAP,
    ERR_ELEVATION_GAP_VIOLATION,
)

bp = make_blueprint("pcards")


def _cancel_elevations(pcard_id):
    svc.cancel_scheduled_elevations(pcard_id)


@bp.post("/pcards")
def create_card():
    authenticate(["ProcurementAdmin"])
    body = body_json()
    if body.get("department_id") is not None and isinstance(body.get("department_id"), str):
        require_fk("departments", body["department_id"])  # p3 before shape
    check_shape(body, {
        "department_id": {"type": "string", "required": True},
        "cardholder_name": {"type": "string", "required": True},
        "single_txn_limit_cents": {"type": "integer", "required": True},
        "monthly_limit_cents": {"type": "integer", "required": True},
        "allowed_mccs": {"type": "array", "items": "string", "required": True},
    })
    # p9 structural: the single-transaction limit may not exceed the monthly.
    if body["single_txn_limit_cents"] > body["monthly_limit_cents"]:
        raise ApiError(ERR_LIMIT_INCONSISTENT, 422, "single_txn_limit_cents may not exceed monthly_limit_cents")
    card = db.new_entity("pcards", {
        "department_id": body["department_id"],
        "cardholder_name": body["cardholder_name"],
        "single_txn_limit_cents": body["single_txn_limit_cents"],
        "monthly_limit_cents": body["monthly_limit_cents"],
        "allowed_mccs": list(body["allowed_mccs"]),
        "status": "ACTIVE",
        "cycle_index": 0,
        "consecutive_unreconciled_cycles": 0,
    })
    return success_obj(svc.card_public(card), 201)


@bp.get("/pcards")
def list_cards():
    authenticate(ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("pcards"), ["department_id", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([svc.card_public(c) for c in page], limit, offset, total, has_more)


@bp.get("/pcards/<cid>")
def get_card(cid):
    authenticate(ROLES)
    card = require_fk("pcards", cid)
    return success_obj(svc.card_public(card), 200)


@bp.patch("/pcards/<cid>/limits")
def patch_limits(cid):
    """OCC-guarded limits/MCC change (PRD 2.7). CLOSED cards refuse all
    mutation with ERR_CARD_CLOSED."""
    authenticate(["ProcurementAdmin"])
    card = require_fk("pcards", cid)
    body = body_json()
    expected = body.get("expected_pcard_version")
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_pcard_version is required and must be an integer")
    if expected != card["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_pcard_version does not match the current version")
    if card["status"] == "CLOSED":
        raise ApiError(ERR_CARD_CLOSED, 409, "card is CLOSED")
    check_shape(body, {
        "expected_pcard_version": {"type": "integer", "required": True},
        "single_txn_limit_cents": {"type": "integer"},
        "monthly_limit_cents": {"type": "integer"},
        "allowed_mccs": {"type": "array", "items": "string"},
    })
    new_single = body.get("single_txn_limit_cents", card["single_txn_limit_cents"])
    new_monthly = body.get("monthly_limit_cents", card["monthly_limit_cents"])
    if new_single > new_monthly:
        raise ApiError(ERR_LIMIT_INCONSISTENT, 422, "single_txn_limit_cents may not exceed monthly_limit_cents")
    card["single_txn_limit_cents"] = new_single
    card["monthly_limit_cents"] = new_monthly
    if "allowed_mccs" in body and body["allowed_mccs"] is not None:
        card["allowed_mccs"] = list(body["allowed_mccs"])
    db.touch(card)
    return success_obj(svc.card_public(card), 200)


@bp.post("/pcards/<cid>/suspend")
def suspend_card(cid):
    authenticate(["ProcurementAdmin"])
    card = require_fk("pcards", cid)
    if card["status"] != "ACTIVE":
        raise ApiError(ERR_CARD_STATE_INVALID, 409, "suspend requires an ACTIVE card")
    card["status"] = "SUSPENDED"
    db.touch(card)
    _cancel_elevations(card["id"])
    return success_obj(svc.card_public(card), 200)


@bp.post("/pcards/<cid>/reinstate")
def reinstate_card(cid):
    authenticate(["ProcurementAdmin"])
    card = require_fk("pcards", cid)
    if card["status"] != "SUSPENDED":
        raise ApiError(ERR_CARD_STATE_INVALID, 409, "reinstate requires a SUSPENDED card")
    card["status"] = "ACTIVE"
    card["consecutive_unreconciled_cycles"] = 0
    db.touch(card)
    return success_obj(svc.card_public(card), 200)


@bp.post("/pcards/<cid>/close")
def close_card(cid):
    authenticate(["ProcurementAdmin"])
    card = require_fk("pcards", cid)
    if card["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_CARD_STATE_INVALID, 409, "close requires ACTIVE or SUSPENDED")
    open_txns = any(
        t["status"] in ("POSTED", "DISPUTED") for t in svc.txns_of_card(card["id"])
    )
    if open_txns:
        raise ApiError(ERR_CARD_HAS_OPEN_TRANSACTIONS, 409, "card has POSTED or DISPUTED transactions")
    card["status"] = "CLOSED"
    db.touch(card)
    _cancel_elevations(card["id"])
    return success_obj(svc.card_public(card), 200)


@bp.post("/pcards/<cid>/close-cycle")
def close_cycle(cid):
    """reconciliation_aging: count the closing cycle's unreconciled debits
    (POSTED or DISPUTED); a dirty cycle increments the counter, a clean one
    resets it; at >= 2 consecutive (inclusive) the card auto-suspends with the
    elevation cascade; then a new cycle begins."""
    authenticate(["ProcurementAdmin"])
    card = require_fk("pcards", cid)
    if card["status"] == "CLOSED":
        raise ApiError(ERR_CARD_CLOSED, 409, "card is CLOSED")
    cyc = card["cycle_index"]
    unreconciled = sum(
        1
        for t in svc.txns_of_card(card["id"])
        if t["cycle_index"] == cyc and t["entry_type"] == "DEBIT" and t["status"] in ("POSTED", "DISPUTED")
    )
    if unreconciled > 0:
        card["consecutive_unreconciled_cycles"] += 1
    else:
        card["consecutive_unreconciled_cycles"] = 0
    if card["consecutive_unreconciled_cycles"] >= svc.SUSPEND_AFTER_CYCLES:
        if card["status"] != "SUSPENDED":
            card["status"] = "SUSPENDED"
            _cancel_elevations(card["id"])
    card["cycle_index"] += 1
    db.touch(card)
    return success_obj(svc.card_public(card), 200)


# ---------------------------------------------------------------------------
# Limit elevations
# ---------------------------------------------------------------------------

@bp.post("/pcards/<cid>/elevations")
def create_elevation(cid):
    """Schedule a half-open [window_start, window_end) elevation; windows may
    neither overlap an existing SCHEDULED one nor sit within a 7-day gap of an
    adjacent one."""
    authenticate(["ProcurementAdmin"])
    card = require_fk("pcards", cid)
    if card["status"] == "CLOSED":
        raise ApiError(ERR_CARD_CLOSED, 409, "card is CLOSED")
    body = body_json()
    check_shape(body, {
        "elevated_single_txn_limit_cents": {"type": "integer", "required": True},
        "window_start": {"type": "datetime", "required": True},
        "window_end": {"type": "datetime", "required": True},
    })
    start = parse_dt(body["window_start"], "window_start")
    end = parse_dt(body["window_end"], "window_end")
    if not start < end:
        raise ApiError(ERR_INVALID_REQUEST, 400, "window_start must be strictly before window_end")
    gap = timedelta(days=svc.ELEVATION_GAP_DAYS)
    for e in svc.elevations_of_card(card["id"]):
        if e["status"] != "SCHEDULED":
            continue
        e_start = parse_dt(e["window_start"])
        e_end = parse_dt(e["window_end"])
        if start < e_end and e_start < end:
            raise ApiError(ERR_ELEVATION_OVERLAP, 409, "window overlaps an existing SCHEDULED elevation")
        if end <= e_start:
            if e_start - end < gap:
                raise ApiError(ERR_ELEVATION_GAP_VIOLATION, 409, "elevations must keep at least a 7-day gap")
        elif start >= e_end:
            if start - e_end < gap:
                raise ApiError(ERR_ELEVATION_GAP_VIOLATION, 409, "elevations must keep at least a 7-day gap")
    elev = db.new_entity("limit_elevations", {
        "pcard_id": card["id"],
        "elevated_single_txn_limit_cents": body["elevated_single_txn_limit_cents"],
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "status": "SCHEDULED",
    })
    return success_obj(db.public(elev), 201)


@bp.get("/pcards/<cid>/elevations")
def list_elevations(cid):
    authenticate(ROLES)
    card = require_fk("pcards", cid)
    limit, offset = pagination_params()
    page, total, has_more = paginate(svc.elevations_of_card(card["id"]), limit, offset)
    return success_list([db.public(e) for e in page], limit, offset, total, has_more)


@bp.post("/pcard-elevations/<eid>/cancel")
def cancel_elevation(eid):
    authenticate(["ProcurementAdmin"])
    elev = require_fk("limit_elevations", eid)
    if elev["status"] != "SCHEDULED":
        raise ApiError(ERR_ELEVATION_STATE_INVALID, 409, "cancel requires a SCHEDULED elevation")
    elev["status"] = "CANCELLED"
    db.touch(elev)
    return success_obj(db.public(elev), 200)
