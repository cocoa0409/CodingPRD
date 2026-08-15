"""Storage agreements: RESERVED/ACTIVE birth, accrual, close, default (PRD §3.6)."""

from flask import Blueprint, request

from db import current_date, public, sort_by_creation, stamp_new, store, touch
from errors import raise_err
from middleware import get_ctx, require_roles
from response import success
from routes.helpers import check_grower_on_agreement, get_agreement, get_lot
from services.calculations import storage_accrued_days, storage_accrual_cents, storage_baseline_bushels
from validation import get_body, opt_int, opt_num, paginate

bp = Blueprint("storage", __name__)

READ_ROLES = {"ElevatorManager", "Grower"}


def _serialize_agreement(rec):
    """ACTIVE agreements accrue live against the logical clock; CLOSED keep
    the finalized figures."""
    out = public(rec)
    if rec["status"] == "ACTIVE":
        days = storage_accrued_days(rec)
        out["accrued_days"] = days
        out["accrued_storage_cents"] = storage_accrual_cents(rec, days)
    return out


@bp.post("/storage-agreements")
def create_agreement():
    ctx = get_ctx()
    require_roles(ctx, {"ElevatorManager"})
    body = get_body()
    # priority 4: body FK existence
    lot = None
    if body.get("lot_id") is not None:
        lot = get_lot(body["lot_id"])
    # priority 5: shape
    if not isinstance(body.get("lot_id"), str) or not body["lot_id"]:
        raise_err("ERR_INVALID_REQUEST", "Field lot_id is required")
    rate = opt_num(body, "daily_rate_cents_per_bu", default=0.15, minimum=0.0)
    min_days = opt_int(body, "min_days", default=7, minimum=0)
    # priority 6: no second non-terminal agreement per lot
    live = [
        a for a in store.agreements.values()
        if a["lot_id"] == lot["id"] and a["status"] in ("RESERVED", "ACTIVE")
    ]
    if live:
        raise_err("ERR_DUPLICATE_ACTIVE_AGREEMENT", "Lot already has a RESERVED or ACTIVE storage agreement")
    if lot["status"] in ("LOADED_OUT", "BLENDED_OUT"):
        raise_err("ERR_ALREADY_TERMINAL", "Lot is in a terminal state")
    if lot["status"] == "DAMAGE_HOLD":
        raise_err("ERR_INVALID_STATE", "Lot state does not permit a storage agreement")
    if lot["status"] == "STORED":
        raise_err("ERR_INVALID_STATE", "Lot state does not permit a storage agreement")
    rec = stamp_new(
        {
            "lot_id": lot["id"],
            "owner_id": lot["current_owner_id"],
            "daily_rate_cents_per_bu": rate,
            "min_days": min_days,
            "baseline_bushels": None,
            "start_date": None,
            "closed_date": None,
            "accrued_days": 0,
            "accrued_storage_cents": 0,
            "status": "RESERVED",
        }
    )
    # born ACTIVE when the lot is already DRIED; otherwise waits RESERVED
    if lot["status"] == "DRIED":
        rec["status"] = "ACTIVE"
        rec["baseline_bushels"] = storage_baseline_bushels(lot)
        rec["start_date"] = current_date().isoformat()
        lot["status"] = "STORED"
        touch(lot)
    store.agreements[rec["id"]] = rec
    return success(_serialize_agreement(rec), code=201)


@bp.get("/storage-agreements")
def list_agreements():
    ctx = get_ctx()
    require_roles(ctx, READ_ROLES)
    records = list(store.agreements.values())
    if ctx["role"] == "Grower":
        records = [a for a in records if a["owner_id"] == ctx["user_id"]]
    for field in ("lot_id", "owner_id", "status"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r.get(field) == val]
    records = sort_by_creation(records)
    page, meta = paginate(records, request.args)
    return success([_serialize_agreement(r) for r in page], response_type="array", pagination=meta)


@bp.get("/storage-agreements/<aid>")
def get_one_agreement(aid):
    ctx = get_ctx()
    require_roles(ctx, READ_ROLES)
    rec = get_agreement(aid)
    check_grower_on_agreement(ctx, rec)
    return success(_serialize_agreement(rec))


@bp.post("/storage-agreements/<aid>/close")
def close_agreement(aid):
    ctx = get_ctx()
    require_roles(ctx, {"ElevatorManager"})
    rec = get_agreement(aid)
    # against any other state -> ERR_AGREEMENT_NOT_ACTIVE (PRD §3.6)
    if rec["status"] != "ACTIVE":
        raise_err("ERR_AGREEMENT_NOT_ACTIVE", "Close attempted on a non-ACTIVE storage agreement")
    rec["closed_date"] = current_date().isoformat()
    days = storage_accrued_days(rec)
    rec["accrued_days"] = days
    rec["accrued_storage_cents"] = storage_accrual_cents(rec, days)
    rec["status"] = "CLOSED"
    touch(rec)
    lot = store.lots.get(rec["lot_id"])
    if lot is not None and lot["status"] == "STORED":
        lot["status"] = "DRIED"
        touch(lot)
    return success(_serialize_agreement(rec))


@bp.post("/storage-agreements/<aid>/declare-default")
def declare_default(aid):
    ctx = get_ctx()
    require_roles(ctx, {"ElevatorManager"})
    rec = get_agreement(aid)
    if rec["status"] != "ACTIVE":
        raise_err("ERR_AGREEMENT_NOT_ACTIVE", "Default declared on a non-ACTIVE storage agreement")
    rec["status"] = "DEFAULTED"
    touch(rec)
    # title transfer; the lot remains STORED
    lot = store.lots.get(rec["lot_id"])
    if lot is not None:
        lot["ownership"] = "ELEVATOR_HELD"
        lot["current_owner_id"] = None
        touch(lot)
    return success(_serialize_agreement(rec))
