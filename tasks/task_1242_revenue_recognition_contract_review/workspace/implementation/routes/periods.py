from datetime import date
from decimal import Decimal

from flask import Blueprint

from db import STORE, make_rec, mark, sort_created
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND,
                    ERR_INVALID_STATE_TRANSITION, ERR_PERIOD_OVERLAP,
                    ERR_PERIOD_REOPEN_LIMIT, ERR_PACK_PERIOD_NOT_CLOSED,
                    ERR_SOD_VIOLATION)
from response import ok_object, ok_list
import serializers as ser
import services as svc
from validate import require_roles, body, req_str, req_date

bp = Blueprint("periods", __name__)

ALL_READ = ("RevenueAccountant", "RevenueManager", "ContractReviewer", "Controller")


def get_period_or_404(period_id):
    p = STORE.periods.get(period_id)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, 404, "period id does not identify an existing accounting period")
    return p


@bp.post("/revrec/accounting-periods")
def create_period():
    require_roles("Controller")
    data = body()
    period_code = req_str(data, "period_code")
    start = req_date(data, "start_date")
    end = req_date(data, "end_date")
    if end <= start:
        raise ApiError(ERR_INVALID_REQUEST, 400, "end_date must be after start_date")
    for p in STORE.periods.values():
        if p["period_code"] == period_code:
            raise ApiError(ERR_INVALID_REQUEST, 400, "period_code must be unique")
    # Half-open [start, end): overlap iff start < other.end and other.start < end.
    for p in STORE.periods.values():
        os_ = date.fromisoformat(p["start_date"])
        oe = date.fromisoformat(p["end_date"])
        if start < oe and os_ < end:
            raise ApiError(ERR_PERIOD_OVERLAP, 409,
                           "period window overlaps an existing period (adjacency is allowed)")
    rec = make_rec(STORE.periods, {
        "period_code": period_code,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "status": "OPEN",
        "reopened_once": False,
    })
    return ok_object(ser.period(rec), 201)


@bp.get("/revrec/accounting-periods/<period_id>")
def get_period(period_id):
    require_roles(*ALL_READ)
    return ok_object(ser.period(get_period_or_404(period_id)))


@bp.post("/revrec/accounting-periods/<period_id>/close")
def close_period(period_id):
    require_roles("Controller")
    p = get_period_or_404(period_id)
    if p["status"] not in ("OPEN", "REOPENED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "close requires the period to be OPEN or REOPENED")
    p["status"] = "CLOSED"
    mark(p)
    for e in STORE.entries.values():
        if e["status"] == "POSTED" and svc.period_contains(p, date.fromisoformat(e["posting_date"])):
            e["status"] = "LOCKED"
    return ok_object(ser.period(p))


@bp.post("/revrec/accounting-periods/<period_id>/reopen")
def reopen_period(period_id):
    require_roles("Controller")
    p = get_period_or_404(period_id)
    if p["status"] != "CLOSED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "reopen requires the period to be CLOSED")
    later_closed = any(
        q["status"] == "CLOSED" and q["start_date"] > p["start_date"]
        for q in STORE.periods.values() if q["id"] != period_id
    )
    if p["reopened_once"] or later_closed:
        raise ApiError(ERR_PERIOD_REOPEN_LIMIT, 409,
                       "a period may be reopened at most once and only while no later period is CLOSED")
    p["status"] = "REOPENED"
    p["reopened_once"] = True
    mark(p)
    superseded = [pk for pk in STORE.packs.values()
                  if pk["accounting_period_id"] == period_id and pk["status"] == "FINALIZED"]
    for pk in sort_created(superseded):
        pk["status"] = "SUPERSEDED"
        mark(pk)
        make_rec(STORE.packs, _blank_pack(period_id))
    return ok_object(ser.period(p))


def _blank_pack(period_id):
    return {
        "accounting_period_id": period_id,
        "status": "DRAFT",
        "rpo_cents": None,
        "period_revenue_cents": None,
        "revenue_by_region": None,
        "revenue_by_product": None,
        "contract_asset_total_cents": None,
        "deferred_revenue_total_cents": None,
        "assembled_by_user_id": None,
        "finalized_by_user_id": None,
    }


@bp.post("/revrec/accounting-periods/<period_id>/disclosure-packs")
def create_pack(period_id):
    require_roles("RevenueAccountant")
    get_period_or_404(period_id)
    rec = make_rec(STORE.packs, _blank_pack(period_id))
    return ok_object(ser.pack(rec), 201)


@bp.get("/revrec/accounting-periods/<period_id>/disclosure-packs")
def list_packs(period_id):
    require_roles(*ALL_READ)
    get_period_or_404(period_id)
    items = sort_created([pk for pk in STORE.packs.values() if pk["accounting_period_id"] == period_id])
    return ok_list([ser.pack(pk) for pk in items], len(items) or 1, 0, len(items))


@bp.post("/revrec/disclosure-packs/<pack_id>/assemble")
def assemble_pack(pack_id):
    uid = require_roles("RevenueAccountant")
    pk = STORE.packs.get(pack_id)
    if pk is None:
        raise ApiError(ERR_NOT_FOUND, 404, "pack_id does not identify an existing disclosure pack")
    if pk["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "assemble requires the pack to be DRAFT")
    period = get_period_or_404(pk["accounting_period_id"])
    p_start = date.fromisoformat(period["start_date"])
    p_end = date.fromisoformat(period["end_date"])

    entry_set = [e for e in STORE.entries.values()
                 if e["status"] in svc.ENTRY_COUNTED
                 and p_start <= date.fromisoformat(e["posting_date"]) < p_end]
    by_region = {}
    by_product = {}
    for e in entry_set:
        pob = STORE.pobs.get(e["pob_id"])
        if pob is None:
            continue
        by_region[pob["region"]] = by_region.get(pob["region"], 0) + e["amount_cents"]
        by_product[pob["product_code"]] = by_product.get(pob["product_code"], 0) + e["amount_cents"]

    rpo = 0
    for pob in STORE.pobs.values():
        if pob["status"] not in ("PENDING", "IN_PROGRESS"):
            continue
        c = STORE.contracts.get(pob["contract_id"])
        if c is None or c["status"] not in ("ACTIVE", "ON_HOLD"):
            continue
        rpo += pob["allocated_amount_cents"] - svc.pob_recognized(pob["id"])

    asset_total = 0
    deferred_total = 0
    for c in STORE.contracts.values():
        if c["status"] in ("ACTIVE", "ON_HOLD", "COMPLETED"):
            _, _, deferred, asset = svc.balances(c)
            asset_total += asset
            deferred_total += deferred

    pk["rpo_cents"] = rpo
    pk["period_revenue_cents"] = sum(e["amount_cents"] for e in entry_set)
    pk["revenue_by_region"] = by_region
    pk["revenue_by_product"] = by_product
    pk["contract_asset_total_cents"] = asset_total
    pk["deferred_revenue_total_cents"] = deferred_total
    pk["assembled_by_user_id"] = uid
    pk["status"] = "ASSEMBLED"
    mark(pk)
    return ok_object(ser.pack(pk))


@bp.post("/revrec/disclosure-packs/<pack_id>/finalize")
def finalize_pack(pack_id):
    uid = require_roles("Controller")
    pk = STORE.packs.get(pack_id)
    if pk is None:
        raise ApiError(ERR_NOT_FOUND, 404, "pack_id does not identify an existing disclosure pack")
    if pk["status"] != "ASSEMBLED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "finalize requires the pack to be ASSEMBLED")
    period = get_period_or_404(pk["accounting_period_id"])
    if period["status"] != "CLOSED":
        raise ApiError(ERR_PACK_PERIOD_NOT_CLOSED, 409,
                       "the pack's accounting period must be CLOSED before finalization")
    if uid == pk["assembled_by_user_id"]:
        raise ApiError(ERR_SOD_VIOLATION, 409, "the finalizer must differ from the assembler")
    pk["status"] = "FINALIZED"
    pk["finalized_by_user_id"] = uid
    mark(pk)
    return ok_object(ser.pack(pk))
