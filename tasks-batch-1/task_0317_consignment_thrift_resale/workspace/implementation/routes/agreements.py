from flask import Blueprint, request

from db import store
from errors import err
from middleware import require
from response import success, paginated
from services.common import (
    base_record, touch, require_body, require_int, parse_pagination, page,
)
from services import serialize

bp = Blueprint("agreements", __name__)

SPLIT_BASIS = {"GROSS", "NET"}
UNSOLD_DISPOSITION = {"RETURN_TO_CONSIGNOR", "DONATE", "STORE_KEEPS"}
PAYOUT_METHOD = {"CASH", "STORE_CREDIT"}


@bp.post("/agreements")
@require("StoreAdmin")
def create_agreement():
    body = require_body()

    # required FK fields must be present and well-typed
    if "consignor_id" not in body or not isinstance(body["consignor_id"], str):
        raise err("ERR_INVALID_REQUEST", "consignor_id required")
    if "markdown_schedule_id" not in body or not isinstance(body["markdown_schedule_id"], str):
        raise err("ERR_INVALID_REQUEST", "markdown_schedule_id required")
    if "split_pct" not in body:
        raise err("ERR_INVALID_REQUEST", "split_pct required")
    split_pct = body["split_pct"]
    if isinstance(split_pct, bool) or not isinstance(split_pct, (int, float)):
        raise err("ERR_INVALID_REQUEST", "split_pct must be a number")
    if not (0 < split_pct < 1):
        raise err("ERR_INVALID_REQUEST", "split_pct must be strictly between 0 and 1")

    split_basis = _enum_or_default(body, "split_basis", SPLIT_BASIS, "GROSS")
    unsold_disposition = _enum_or_default(body, "unsold_disposition", UNSOLD_DISPOSITION, "DONATE")
    payout_method = _enum_or_default(body, "payout_method", PAYOUT_METHOD, "CASH")

    if "return_window_days" in body and body["return_window_days"] is not None:
        return_window_days = require_int(body, "return_window_days", minimum=1)
    else:
        return_window_days = 90

    consignor = store.consignors.get(body["consignor_id"])
    schedule = store.markdown_schedules.get(body["markdown_schedule_id"])
    if consignor is None or schedule is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "Referenced consignor or schedule not found")

    if consignor["status"] != "ACTIVE" or schedule["is_archived"]:
        raise err("ERR_AGREEMENT_PRECONDITION", "Consignor not ACTIVE or schedule archived")

    rec = base_record()
    rec.update({
        "consignor_id": consignor["id"],
        "markdown_schedule_id": schedule["id"],
        "split_pct": split_pct,
        "split_basis": split_basis,
        "unsold_disposition": unsold_disposition,
        "return_window_days": return_window_days,
        "payout_method": payout_method,
        "status": "ACTIVE",
    })
    store.agreements[rec["id"]] = rec
    return success(serialize.agreement_out(rec), 201)


def _enum_or_default(body, key, allowed, default):
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if val not in allowed:
        raise err("ERR_INVALID_REQUEST", "%s invalid" % key)
    return val


@bp.get("/agreements/<aid>")
@require("StoreAdmin", "SettlementManager", "IntakeGrader", "CashierClerk")
def get_agreement(aid):
    a = store.agreements.get(aid)
    if a is None:
        raise err("ERR_NOT_FOUND", "Agreement not found")
    return success(serialize.agreement_out(a), 200)


@bp.get("/agreements")
@require("StoreAdmin", "SettlementManager")
def list_agreements():
    limit, offset = parse_pagination()
    recs = list(store.agreements.values())
    consignor_id = request.args.get("consignor_id")
    schedule_id = request.args.get("markdown_schedule_id")
    status = request.args.get("status")
    if consignor_id is not None:
        recs = [a for a in recs if a["consignor_id"] == consignor_id]
    if schedule_id is not None:
        recs = [a for a in recs if a["markdown_schedule_id"] == schedule_id]
    if status is not None:
        recs = [a for a in recs if a["status"] == status]
    window, total = page(recs, limit, offset)
    return paginated([serialize.agreement_out(a) for a in window], limit, offset, total)


@bp.post("/agreements/<aid>/terminate")
@require("StoreAdmin")
def terminate_agreement(aid):
    a = store.agreements.get(aid)
    if a is None:
        raise err("ERR_NOT_FOUND", "Agreement not found")
    a["status"] = "TERMINATED"
    touch(a)
    return success(serialize.agreement_out(a), 200)


@bp.get("/agreements/<aid>/intake-batches")
@require("StoreAdmin", "SettlementManager", "IntakeGrader")
def agreement_batches(aid):
    if aid not in store.agreements:
        raise err("ERR_NOT_FOUND", "Agreement not found")
    limit, offset = parse_pagination()
    recs = [b for b in store.intake_batches.values() if b["agreement_id"] == aid]
    window, total = page(recs, limit, offset)
    return paginated([serialize.batch_out(b) for b in window], limit, offset, total)
