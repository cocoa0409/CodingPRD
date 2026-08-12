"""Distributor, ConsignmentAgreement, ConsignmentStock, ConsumptionReport."""
import re
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request, g

from db import store
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INSUFFICIENT_PERMISSIONS,
    ERR_AGREEMENT_INVALID_STATE, ERR_AGREEMENT_NOT_ACTIVE,
    ERR_AGREEMENT_HAS_OPEN_REPORTS, ERR_CONSIGNMENT_STOCK_REMAINING,
    ERR_CREDIT_LIMIT_EXCEEDED, ERR_REPORT_INVALID_STATE,
    ERR_REPORT_PERIOD_DUPLICATE, ERR_STOCK_NEGATIVE, ERR_STALE_VERSION,
    ERR_RETURN_EXCEEDS_ON_HAND, not_found,
)
from helpers import (
    ALL_ROLES, require_roles, body_json, ok, ok_list, pagination_params,
    f_str, f_int, parse_date,
)
from services import (
    new_entity, touch, get_distributor, get_agreement, get_stock, get_report,
    ser_distributor, ser_agreement, ser_stock, ser_report, sorted_rows,
    stock_rows_of_agreement, total_on_hand, credit_check,
    TIER1_GROSS_CENTS, TIER1_PCT, TIER2_GROSS_CENTS, TIER2_PCT,
)

bp = Blueprint("commercial", __name__)

PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


# ---------------------------------------------------------------------------
# Distributor
# ---------------------------------------------------------------------------

@bp.post("/api/distributors")
@require_roles("CommercialManager")
def create_distributor():
    b = body_json()
    name = f_str(b, "name")
    credit = f_int(b, "credit_limit_cents", lo=0)
    email = f_str(b, "contact_email")
    d = new_entity()
    d.update({"name": name, "credit_limit_cents": credit, "contact_email": email})
    store.distributors[d["id"]] = d
    return ok(ser_distributor(d), 201)


@bp.get("/api/distributors/<did>")
@require_roles(*ALL_ROLES)
def get_one_distributor(did):
    return ok(ser_distributor(get_distributor(did)), 200)


# ---------------------------------------------------------------------------
# ConsignmentAgreement
# ---------------------------------------------------------------------------

@bp.post("/api/consignment-agreements")
@require_roles("CommercialManager")
def create_agreement():
    b = body_json()
    distributor_id = f_str(b, "distributor_id")
    formulation_id = f_str(b, "formulation_id")
    unit_price = f_int(b, "unit_price_cents", lo=0)
    max_value = f_int(b, "max_consigned_value_cents", lo=0)
    threshold = f_int(b, "reorder_threshold_units", lo=0)
    qty = f_int(b, "reorder_qty_units", lo=0)
    min_shelf = b.get("min_remaining_shelf_life_days")
    if min_shelf is not None:
        min_shelf = f_int(b, "min_remaining_shelf_life_days", lo=0)
    if distributor_id not in store.distributors:
        raise not_found("Distributor")
    if formulation_id not in store.formulations:
        raise not_found("Formulation")
    a = new_entity()
    a.update({
        "distributor_id": distributor_id,
        "formulation_id": formulation_id,
        "unit_price_cents": unit_price,
        "max_consigned_value_cents": max_value,
        "reorder_threshold_units": threshold,
        "reorder_qty_units": qty,
        "min_remaining_shelf_life_days": min_shelf,
        "status": "DRAFT",
    })
    store.agreements[a["id"]] = a
    return ok(ser_agreement(a), 201)


@bp.get("/api/consignment-agreements")
@require_roles(*ALL_ROLES)
def list_agreements():
    limit, offset = pagination_params()
    rows = list(store.agreements.values())
    did = request.args.get("distributor_id")
    fid = request.args.get("formulation_id")
    if did is not None:
        rows = [a for a in rows if a["distributor_id"] == did]
    if fid is not None:
        rows = [a for a in rows if a["formulation_id"] == fid]
    return ok_list([ser_agreement(a) for a in sorted_rows(rows)], limit, offset)


@bp.get("/api/consignment-agreements/<aid>")
@require_roles(*ALL_ROLES)
def get_one_agreement(aid):
    return ok(ser_agreement(get_agreement(aid)), 200)


@bp.patch("/api/consignment-agreements/<aid>")
@require_roles("CommercialManager")
def patch_agreement(aid):
    b = body_json()
    expected = f_int(b, "expected_agreement_version", lo=0)
    updates = {}
    if "reorder_threshold_units" in b:
        updates["reorder_threshold_units"] = f_int(b, "reorder_threshold_units", lo=0)
    if "reorder_qty_units" in b:
        updates["reorder_qty_units"] = f_int(b, "reorder_qty_units", lo=0)
    if "max_consigned_value_cents" in b:
        updates["max_consigned_value_cents"] = f_int(b, "max_consigned_value_cents", lo=0)
    if "min_remaining_shelf_life_days" in b:
        v = b.get("min_remaining_shelf_life_days")
        if v is not None:
            v = f_int(b, "min_remaining_shelf_life_days", lo=0)
        updates["min_remaining_shelf_life_days"] = v
    a = get_agreement(aid)
    if expected != a["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_agreement_version does not match the agreement's current version",
            412,
        )
    a.update(updates)
    touch(a)
    return ok(ser_agreement(a), 200)


@bp.post("/api/consignment-agreements/<aid>/activate")
@require_roles("CommercialManager")
def activate_agreement(aid):
    body_json()
    a = get_agreement(aid)
    if a["status"] != "DRAFT":
        raise ApiError(ERR_AGREEMENT_INVALID_STATE, "activate requires DRAFT", 409)
    distributor = store.distributors[a["distributor_id"]]
    if not credit_check(distributor, a):
        raise ApiError(
            ERR_CREDIT_LIMIT_EXCEEDED,
            "Consigned value would exceed the distributor credit limit",
            402,
        )
    a["status"] = "ACTIVE"
    touch(a)
    return ok(ser_agreement(a), 200)


@bp.post("/api/consignment-agreements/<aid>/suspend")
@require_roles("CommercialManager")
def suspend_agreement(aid):
    body_json()
    a = get_agreement(aid)
    if a["status"] != "ACTIVE":
        raise ApiError(ERR_AGREEMENT_INVALID_STATE, "suspend requires ACTIVE", 409)
    a["status"] = "SUSPENDED"
    touch(a)
    return ok(ser_agreement(a), 200)


@bp.post("/api/consignment-agreements/<aid>/resume")
@require_roles("CommercialManager")
def resume_agreement(aid):
    body_json()
    a = get_agreement(aid)
    if a["status"] != "SUSPENDED":
        raise ApiError(ERR_AGREEMENT_INVALID_STATE, "resume requires SUSPENDED", 409)
    distributor = store.distributors[a["distributor_id"]]
    if not credit_check(distributor, a):
        raise ApiError(
            ERR_CREDIT_LIMIT_EXCEEDED,
            "Consigned value would exceed the distributor credit limit",
            402,
        )
    a["status"] = "ACTIVE"
    touch(a)
    return ok(ser_agreement(a), 200)


@bp.post("/api/consignment-agreements/<aid>/close")
@require_roles("CommercialManager")
def close_agreement(aid):
    body_json()
    a = get_agreement(aid)
    if a["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_AGREEMENT_INVALID_STATE, "close requires ACTIVE or SUSPENDED", 409)
    if any(r["agreement_id"] == aid and r["status"] in ("DRAFT", "SUBMITTED", "DISPUTED")
           for r in store.reports.values()):
        raise ApiError(
            ERR_AGREEMENT_HAS_OPEN_REPORTS,
            "Agreement has reports in DRAFT, SUBMITTED, or DISPUTED",
            409,
        )
    if any(r["qty_on_hand"] > 0 for r in stock_rows_of_agreement(aid)):
        raise ApiError(
            ERR_CONSIGNMENT_STOCK_REMAINING,
            "Agreement has consignment stock remaining",
            409,
        )
    a["status"] = "CLOSED"
    touch(a)
    return ok(ser_agreement(a), 200)


# ---------------------------------------------------------------------------
# ConsignmentStock
# ---------------------------------------------------------------------------

@bp.get("/api/consignment-stock")
@require_roles(*ALL_ROLES)
def list_stock():
    limit, offset = pagination_params()
    rows = list(store.stock.values())
    aid = request.args.get("agreement_id")
    lid = request.args.get("lot_id")
    if aid is not None:
        rows = [r for r in rows if r["agreement_id"] == aid]
    if lid is not None:
        rows = [r for r in rows if r["lot_id"] == lid]
    return ok_list([ser_stock(r) for r in sorted_rows(rows)], limit, offset)


@bp.get("/api/consignment-stock/<sid>")
@require_roles(*ALL_ROLES)
def get_one_stock(sid):
    return ok(ser_stock(get_stock(sid)), 200)


@bp.post("/api/consignment-stock/<sid>/return")
@require_roles("CommercialManager")
def return_stock(sid):
    b = body_json()
    units = f_int(b, "units", lo=1)
    row = get_stock(sid)
    agreement = store.agreements[row["agreement_id"]]
    if agreement["status"] == "CLOSED":
        raise ApiError(
            ERR_AGREEMENT_INVALID_STATE,
            "Agreement must not be CLOSED",
            409,
        )
    if units > row["qty_on_hand"]:
        raise ApiError(
            ERR_RETURN_EXCEEDS_ON_HAND,
            "Return units exceed qty_on_hand",
            422,
        )
    row["qty_returned"] += units
    row["qty_on_hand"] -= units
    touch(row)
    lot = store.lots.get(row["lot_id"])
    if lot is not None:
        lot["units_shipped"] -= units
        touch(lot)
    return ok(ser_stock(row), 200)


# ---------------------------------------------------------------------------
# ConsumptionReport
# ---------------------------------------------------------------------------

@bp.post("/api/consignment-agreements/<aid>/consumption-reports")
@require_roles("Distributor")
def create_report(aid):
    # schema (priority 3)
    b = body_json()
    period = f_str(b, "period")
    if not PERIOD_RE.match(period):
        raise ApiError(ERR_INVALID_REQUEST, "period must be in YYYY-MM form", 400)
    consumed = f_int(b, "consumed_units", lo=1)
    expected = f_int(b, "expected_agreement_version", lo=0)
    # existence (priority 4), then ownership (Distributor writes)
    a = get_agreement(aid)
    if a["distributor_id"] != g.user_id:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            "Distributor may only create reports against its own agreements",
            403,
        )
    # state gate: agreement must be ACTIVE
    if a["status"] != "ACTIVE":
        raise ApiError(ERR_AGREEMENT_NOT_ACTIVE, "Agreement must be ACTIVE", 409)
    # OCC guard
    if expected != a["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_agreement_version does not match the agreement's current version",
            412,
        )
    # one non-VOID report per (agreement, period)
    prior = [r for r in store.reports.values()
             if r["agreement_id"] == aid and r["period"] == period
             and r["status"] != "VOID"]
    for r in prior:
        if r["status"] != "DRAFT":
            raise ApiError(
                ERR_REPORT_PERIOD_DUPLICATE,
                "A non-DRAFT report already exists for this agreement and period",
                409,
            )
    for r in prior:  # supersede existing DRAFT reports
        r["status"] = "VOID"
        touch(r)
    rep = new_entity()
    rep.update({
        "agreement_id": aid,
        "period": period,
        "consumed_units": consumed,
        "provisional_settlement_cents": None,
        "rebate_tier": None,
        "rebate_cents": None,
        "final_net_settlement_cents": None,
        "dispute_reason": None,
        "status": "DRAFT",
        "_waterfall": None,
        "_auto_shipment_id": None,
    })
    store.reports[rep["id"]] = rep
    touch(a)  # creating a report advances the agreement version
    return ok(ser_report(rep), 201)


@bp.get("/api/consumption-reports")
@require_roles(*ALL_ROLES)
def list_reports():
    limit, offset = pagination_params()
    rows = list(store.reports.values())
    aid = request.args.get("agreement_id")
    if aid is not None:
        rows = [r for r in rows if r["agreement_id"] == aid]
    return ok_list([ser_report(r) for r in sorted_rows(rows)], limit, offset)


@bp.get("/api/consumption-reports/<rid>")
@require_roles(*ALL_ROLES)
def get_one_report(rid):
    return ok(ser_report(get_report(rid)), 200)


@bp.post("/api/consumption-reports/<rid>/submit")
@require_roles("Distributor")
def submit_report(rid):
    body_json()
    rep = get_report(rid)
    a = store.agreements[rep["agreement_id"]]
    if a["distributor_id"] != g.user_id:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            "Distributor may only submit its own reports",
            403,
        )
    if rep["status"] != "DRAFT":
        raise ApiError(ERR_REPORT_INVALID_STATE, "submit requires DRAFT", 409)
    if a["status"] != "ACTIVE":
        raise ApiError(ERR_AGREEMENT_NOT_ACTIVE, "Agreement must be ACTIVE", 409)
    # atomic stock sufficiency check before any row is modified
    rows = [r for r in stock_rows_of_agreement(a["id"]) if r["qty_on_hand"] > 0]
    if rep["consumed_units"] > sum(r["qty_on_hand"] for r in rows):
        raise ApiError(
            ERR_STOCK_NEGATIVE,
            "consumed_units exceeds total qty_on_hand; nothing was decremented",
            422,
        )
    # FIFO waterfall by (lot.expiry_date ASC, lot.created_at ASC)
    rows.sort(key=lambda r: (
        store.lots[r["lot_id"]]["expiry_date"],
        store.lots[r["lot_id"]]["created_at"],
        store.lots[r["lot_id"]].get("_seq", 0),
    ))
    remaining = rep["consumed_units"]
    taken = []
    for row in rows:
        if remaining == 0:
            break
        take = min(row["qty_on_hand"], remaining)
        row["qty_consumed"] += take
        row["qty_on_hand"] -= take
        touch(row)
        taken.append((row["id"], take))
        remaining -= take
    rep["_waterfall"] = taken
    rep["provisional_settlement_cents"] = rep["consumed_units"] * a["unit_price_cents"]
    rep["status"] = "SUBMITTED"
    touch(rep)
    # reorder cascade
    if total_on_hand(a["id"]) < a["reorder_threshold_units"]:
        open_auto = any(
            s["agreement_id"] == a["id"] and s["auto_replenishment"]
            and s["status"] in ("DRAFT", "PLANNED", "CONFIRMED")
            for s in store.shipments.values()
        )
        if not open_auto:
            s = new_entity()
            s.update({
                "shipment_kind": "CONSIGNMENT_REPLENISHMENT",
                "distributor_id": a["distributor_id"],
                "agreement_id": a["id"],
                "transport_mode": "ROAD",
                "ship_date": store.clock.date() + timedelta(days=7),
                "lines": [],
                "hazmat_class": None,
                "auto_replenishment": True,
                "proposed_units": a["reorder_qty_units"],
                "status": "DRAFT",
            })
            store.shipments[s["id"]] = s
            rep["_auto_shipment_id"] = s["id"]
    return ok(ser_report(rep), 200)


@bp.post("/api/consumption-reports/<rid>/settle")
@require_roles("CommercialManager")
def settle_report(rid):
    body_json()
    rep = get_report(rid)
    if rep["status"] != "SUBMITTED":
        raise ApiError(ERR_REPORT_INVALID_STATE, "settle requires SUBMITTED", 409)
    a = store.agreements[rep["agreement_id"]]
    gross = rep["consumed_units"] * a["unit_price_cents"]
    if gross >= TIER2_GROSS_CENTS:
        tier, pct = "TIER2", TIER2_PCT
    elif gross >= TIER1_GROSS_CENTS:
        tier, pct = "TIER1", TIER1_PCT
    else:
        tier, pct = "NONE", 0
    rebate = int(
        (Decimal(gross) * Decimal(pct) / Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    rep["rebate_tier"] = tier
    rep["rebate_cents"] = rebate
    rep["final_net_settlement_cents"] = gross - rebate
    rep["status"] = "SETTLED"
    touch(rep)
    return ok(ser_report(rep), 200)


@bp.post("/api/consumption-reports/<rid>/dispute")
@require_roles("CommercialManager")
def dispute_report(rid):
    b = body_json()
    reason = f_str(b, "reason")
    rep = get_report(rid)
    if rep["status"] != "SUBMITTED":
        raise ApiError(ERR_REPORT_INVALID_STATE, "dispute requires SUBMITTED", 409)
    rep["dispute_reason"] = reason
    rep["status"] = "DISPUTED"
    touch(rep)
    return ok(ser_report(rep), 200)


@bp.post("/api/consumption-reports/<rid>/revise")
@require_roles("Distributor")
def revise_report(rid):
    b = body_json()
    new_consumed = None
    if "consumed_units" in b and b.get("consumed_units") is not None:
        new_consumed = f_int(b, "consumed_units", lo=1)
    rep = get_report(rid)
    a = store.agreements[rep["agreement_id"]]
    if a["distributor_id"] != g.user_id:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            "Distributor may only revise its own reports",
            403,
        )
    if rep["status"] != "DISPUTED":
        raise ApiError(ERR_REPORT_INVALID_STATE, "revise requires DISPUTED", 409)
    # compensate the submit waterfall row by row
    for row_id, take in rep.get("_waterfall") or []:
        row = store.stock.get(row_id)
        if row is not None:
            row["qty_consumed"] -= take
            row["qty_on_hand"] += take
            touch(row)
    rep["_waterfall"] = None
    rep["provisional_settlement_cents"] = None
    rep["dispute_reason"] = None
    # cancel the linked auto-replenishment shipment if it is still DRAFT
    auto_id = rep.get("_auto_shipment_id")
    if auto_id is not None:
        auto = store.shipments.get(auto_id)
        if auto is not None and auto["status"] == "DRAFT":
            auto["status"] = "CANCELLED"
            touch(auto)
        rep["_auto_shipment_id"] = None
    if new_consumed is not None:
        rep["consumed_units"] = new_consumed
    rep["status"] = "DRAFT"
    touch(rep)
    return ok(ser_report(rep), 200)
