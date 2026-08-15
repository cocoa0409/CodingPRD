"""LoanPledge, Settlement, QuotaHistory (PRD 3.7, 3.9, 3.2)."""
from decimal import Decimal

from flask import Blueprint, request

import calc
from authz import (ADMIN, GROWER, CLERK, authenticate, require_roles,
                   check_grower_ownership)
from db import store
from errors import err, invalid_request, invalid_state, stale_version
from respond import success
from serialize import ser_pledge, ser_settlement, ser_quota_history
from store_ops import (get_or_404, json_body, list_response,
                       new_common_fields, req_datetime, req_int, req_str,
                       req_tons, touch)

bp = Blueprint("finance", __name__)


# ---------------------------------------------------------------------------
# LoanPledge
# ---------------------------------------------------------------------------

@bp.post("/buying-points/loan-pledges")
def create_pledge():
    uid, role = authenticate()
    data = json_body()
    grower_id = req_str(data, "grower_id")
    receipt_id = req_str(data, "storage_receipt_id")
    pledged_tons = req_tons(data, "pledged_tons")
    maturity = req_datetime(data, "maturity_date")
    require_roles([ADMIN, GROWER])
    grower = get_or_404(store.growers, grower_id)
    receipt = get_or_404(store.storage_receipts, receipt_id)
    check_grower_ownership(uid, role, grower_id)
    load = store.loads.get(receipt["load_id"])
    if load is None or load["grower_id"] != grower_id:
        raise invalid_request("The receipt's load does not belong to grower_id")
    if receipt["status"] != "OPEN":
        raise invalid_state("Only an OPEN receipt may be pledged")
    # Full-receipt pledge rule: pledged_tons must EQUAL tons_remaining.
    if pledged_tons < receipt["tons_remaining"]:
        raise invalid_request("pledged_tons must equal the receipt's tons_remaining")
    if pledged_tons > receipt["tons_remaining"]:
        raise err("ERR_LOAN_UNDER_COLLATERALIZED", 409,
                  "pledged_tons exceeds the receipt's tons_remaining")
    wh = store.warehouses[receipt["warehouse_id"]]
    bp_rec = store.buying_points[wh["buying_point_id"]]
    quota_part, additional_part, principal = calc.compute_loan_principal(
        pledged_tons, bp_rec, grower_id, load["crop_year"])
    p = new_common_fields()
    p.update({
        "grower_id": grower_id,
        "storage_receipt_id": receipt_id,
        "pledged_tons": calc.r3(pledged_tons),
        "quota_part_tons": quota_part,
        "additional_part_tons": additional_part,
        "principal_cents": principal,
        "outstanding_principal_cents": principal,
        "accrued_balance_cents": 0,
        "accrued_through_days": 0,
        "pledged_at": store.clock,
        "maturity_date": maturity,
        "foreclosure_credit_cents": None,
        "status": "ACTIVE",
    })
    store.loan_pledges[p["id"]] = p
    receipt["status"] = "PLEDGED"
    touch(receipt)
    return success(ser_pledge(p), status=201)


@bp.get("/buying-points/loan-pledges/<p_id>")
def get_pledge(p_id):
    uid, role = require_roles([ADMIN, GROWER, CLERK])
    p = get_or_404(store.loan_pledges, p_id)
    check_grower_ownership(uid, role, p["grower_id"])
    return success(ser_pledge(p))


@bp.get("/buying-points/loan-pledges")
def list_pledges():
    uid, role = require_roles([ADMIN, GROWER, CLERK])
    items = list(store.loan_pledges.values())
    if role == GROWER:
        items = [p for p in items if p["grower_id"] == uid]
    for param, field in (("grower_id", "grower_id"),
                         ("storage_receipt_id", "storage_receipt_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [p for p in items if p[field] == v]
    return list_response(items, ser_pledge)


@bp.post("/buying-points/loan-pledges/<p_id>/repay")
def repay_pledge(p_id):
    uid, role = authenticate()
    data = json_body()
    amount = req_int(data, "amount_cents", minimum=1)
    require_roles([ADMIN, GROWER])
    p = get_or_404(store.loan_pledges, p_id)
    check_grower_ownership(uid, role, p["grower_id"])
    if p["status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE pledge may be repaid")
    calc.fix_accrual(p, store.clock)  # accrued recomputed to the payment date
    accrued = p["accrued_balance_cents"]
    total_due = p["outstanding_principal_cents"] + accrued
    if amount > total_due:
        raise invalid_request("amount_cents exceeds outstanding principal plus interest")
    # Interest-first waterfall.
    interest_part = min(amount, accrued)
    principal_part = amount - interest_part
    p["accrued_balance_cents"] -= interest_part
    p["outstanding_principal_cents"] -= principal_part
    if p["outstanding_principal_cents"] == 0:
        # Full payoff: REPAID, receipt returns to OPEN.
        p["status"] = "REPAID"
        p["accrued_balance_cents"] = 0
        receipt = store.storage_receipts.get(p["storage_receipt_id"])
        if receipt is not None and receipt["status"] == "PLEDGED":
            receipt["status"] = "OPEN"
            touch(receipt)
    touch(p)
    return success(ser_pledge(p))


@bp.post("/buying-points/loan-pledges/<p_id>/foreclose")
def foreclose_pledge(p_id):
    require_roles([ADMIN])
    p = get_or_404(store.loan_pledges, p_id)
    if p["status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE pledge may be foreclosed")
    outstanding = p["outstanding_principal_cents"] + calc.accrued_interest_cents(p, store.clock)
    if outstanding <= 0:
        raise invalid_state("No outstanding exposure remains to foreclose")
    if not store.clock > p["maturity_date"]:
        raise err("ERR_FORECLOSE_NOT_MATURED", 409,
                  "Foreclosure requires the logical clock past maturity_date")
    bp_rec = calc.pledge_bp(p)
    standard, _ = calc.collateral_values(p, bp_rec)
    p["foreclosure_credit_cents"] = max(0, standard - outstanding)
    p["status"] = "FORECLOSED"
    touch(p)
    receipt = store.storage_receipts.get(p["storage_receipt_id"])
    if receipt is not None and receipt["status"] == "PLEDGED":
        receipt["tons_remaining"] = calc.r3(0)
        receipt["status"] = "FORFEITED"
        touch(receipt)
    return success(ser_pledge(p))


# ---------------------------------------------------------------------------
# QuotaHistory
# ---------------------------------------------------------------------------

@bp.post("/buying-points/quota-histories")
def create_quota_history():
    authenticate()
    data = json_body()
    grower_id = req_str(data, "grower_id")
    crop_year = req_int(data, "crop_year")
    quota_tons = req_tons(data, "quota_tons", allow_zero=True)
    require_roles([ADMIN])
    get_or_404(store.growers, grower_id)
    for q in store.quota_histories.values():
        if q["grower_id"] == grower_id and q["crop_year"] == crop_year:
            raise err("ERR_DUPLICATE_QUOTA_HISTORY", 409,
                      "A quota history already exists for this grower and crop year")
    q = new_common_fields()
    q.update({"grower_id": grower_id, "crop_year": crop_year,
              "quota_tons": calc.r3(quota_tons), "used_quota_tons": Decimal(0)})
    store.quota_histories[q["id"]] = q
    return success(ser_quota_history(q), status=201)


@bp.get("/buying-points/quota-histories/<q_id>")
def get_quota_history(q_id):
    uid, role = require_roles([ADMIN, CLERK, GROWER])
    q = get_or_404(store.quota_histories, q_id)
    check_grower_ownership(uid, role, q["grower_id"])
    return success(ser_quota_history(q))


@bp.get("/buying-points/quota-histories")
def list_quota_histories():
    uid, role = require_roles([ADMIN, CLERK, GROWER])
    items = list(store.quota_histories.values())
    if role == GROWER:
        items = [q for q in items if q["grower_id"] == uid]
    v = request.args.get("grower_id")
    if v is not None:
        items = [q for q in items if q["grower_id"] == v]
    v = request.args.get("crop_year")
    if v is not None:
        try:
            v = int(v)
        except (TypeError, ValueError):
            raise invalid_request("crop_year must be an integer")
        items = [q for q in items if q["crop_year"] == v]
    return list_response(items, ser_quota_history)


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------

@bp.post("/buying-points/growers/<grower_id>/settlements")
def compute_settlement(grower_id):
    uid, role = authenticate()
    data = json_body()
    crop_year = req_int(data, "crop_year")
    expected = req_int(data, "expected_grower_version")
    require_roles([CLERK])
    grower = get_or_404(store.growers, grower_id)
    # State (priority 6): the inclusion set must be non-empty.
    included = [l for l in calc.sorted_by_seq(store.loads.values())
                if l["grower_id"] == grower_id and l["crop_year"] == crop_year
                and l["status"] in ("STORED", "DEPLETED")
                and l["settlement_id"] is None]
    if not included:
        raise invalid_state("The grower has no eligible loads for that crop year")
    # OCC (priority 7).
    if expected != grower["version"]:
        raise stale_version()
    bp_rec = calc.bp_for_crop_year(crop_year)
    if bp_rec is None:
        raise err("ERR_NOT_FOUND", 404,
                  "No buying point operates the supplied crop_year")
    qh = calc.quota_history_for(grower_id, crop_year)
    quota_tons = qh["quota_tons"] if qh else Decimal(0)
    used = qh["used_quota_tons"] if qh else Decimal(0)
    # Other COMPUTED settlements do NOT reduce the quota view (deliberate
    # overcommit window; approve re-validates against live used_quota_tons).
    quota_remaining = quota_tons - used
    gross_total = 0
    discount_total = 0
    quota_applied_total = Decimal(0)
    additional_applied_total = Decimal(0)
    drying_total = 0
    for load in included:
        sheet = calc.sheet_of_record(load["id"])
        schedule = store.discount_schedules.get(sheet["schedule_id"]) if sheet else None
        value = calc.load_value(load, sheet, schedule, bp_rec, quota_remaining)
        quota_applied_total += value["quota_tons_applied"]
        additional_applied_total += value["additional_tons_applied"]
        gross_total += value["gross_value_cents"]
        discount_total += value["discount_cents"]
        quota_remaining -= value["quota_tons_applied"]
        for b in store.dryer_bookings.values():
            if b["load_id"] == load["id"] and b["status"] == "COMPLETED":
                drying_total += calc.drying_charge_cents(b, bp_rec)
    offset_pledges = [p for p in calc.sorted_by_seq(store.loan_pledges.values())
                      if p["grower_id"] == grower_id and p["status"] == "ACTIVE"]
    as_of = store.clock
    loan_offset = sum(p["outstanding_principal_cents"]
                      + calc.accrued_interest_cents(p, as_of)
                      for p in offset_pledges)
    hull_credit = calc.hull_credit_cents(bp_rec, grower_id, as_of)
    net = gross_total - discount_total - drying_total - loan_offset + hull_credit
    # Supersede the grower's prior non-terminal settlements for this crop
    # year: DISPUTED/STALE -> SUPERSEDED. COMPUTED coexist; APPROVED/PAID locked.
    supersedes_id = None
    for s in calc.sorted_by_seq(store.settlements.values()):
        if s["grower_id"] == grower_id and s["crop_year"] == crop_year \
                and s["status"] in ("DISPUTED", "STALE"):
            s["status"] = "SUPERSEDED"
            touch(s)
            supersedes_id = s["id"]  # link to the settlement this one replaces
    s = new_common_fields()
    s.update({
        "grower_id": grower_id,
        "crop_year": crop_year,
        "supersedes_settlement_id": supersedes_id,
        "included_load_ids": [l["id"] for l in included],
        "offset_pledge_ids": [p["id"] for p in offset_pledges],
        "quota_tons_applied": quota_applied_total,
        "additional_tons_applied": additional_applied_total,
        "gross_value_cents": gross_total,
        "discount_cents": discount_total,
        "drying_cents": drying_total,
        "loan_offset_cents": loan_offset,
        "hull_credit_cents": hull_credit,
        "net_payment_cents": net,
        "computed_by": uid,
        "approved_by": None,
        "paid_by": None,
        "status": "COMPUTED",
    })
    store.settlements[s["id"]] = s
    touch(grower)  # computing a settlement bumps Grower.version (OCC basis)
    return success(ser_settlement(s), status=201)


@bp.get("/buying-points/settlements/<s_id>")
def get_settlement(s_id):
    uid, role = require_roles([ADMIN, CLERK, GROWER])
    s = get_or_404(store.settlements, s_id)
    check_grower_ownership(uid, role, s["grower_id"])
    return success(ser_settlement(s))


@bp.get("/buying-points/settlements")
def list_settlements():
    uid, role = require_roles([ADMIN, CLERK, GROWER])
    items = list(store.settlements.values())
    if role == GROWER:
        items = [s for s in items if s["grower_id"] == uid]
    for param, field in (("grower_id", "grower_id"), ("status", "status"),
                         ("supersedes_settlement_id", "supersedes_settlement_id")):
        v = request.args.get(param)
        if v is not None:
            items = [s for s in items if s[field] == v]
    return list_response(items, ser_settlement)


@bp.post("/buying-points/settlements/<s_id>/approve")
def approve_settlement(s_id):
    uid, role = require_roles([CLERK])
    s = get_or_404(store.settlements, s_id)
    if s["status"] != "COMPUTED":
        raise invalid_state("Only a COMPUTED settlement may be approved")
    if uid == s["computed_by"]:
        raise err("ERR_SEG_OF_DUTIES", 409,
                  "The computing clerk may not approve the settlement")
    if s["net_payment_cents"] < 0:
        raise err("ERR_SETTLEMENT_NOT_PAYABLE", 409,
                  "The net payment is negative")
    qh = calc.quota_history_for(s["grower_id"], s["crop_year"])
    quota_tons = qh["quota_tons"] if qh else Decimal(0)
    used = qh["used_quota_tons"] if qh else Decimal(0)
    if used + s["quota_tons_applied"] > quota_tons:
        raise err("ERR_QUOTA_EXCEEDED", 409,
                  "Approval would exceed the grower's annual quota")
    s["approved_by"] = uid
    s["status"] = "APPROVED"
    touch(s)
    if qh is not None:
        qh["used_quota_tons"] += s["quota_tons_applied"]
        touch(qh)
    for load_id in s["included_load_ids"]:
        load = store.loads.get(load_id)
        if load is not None:
            load["settlement_id"] = s["id"]
            touch(load)
    return success(ser_settlement(s))


@bp.post("/buying-points/settlements/<s_id>/dispute")
def dispute_settlement(s_id):
    uid, role = require_roles([GROWER])
    s = get_or_404(store.settlements, s_id)
    check_grower_ownership(uid, role, s["grower_id"])
    if s["status"] != "COMPUTED":
        raise invalid_state("Only a COMPUTED settlement may be disputed")
    s["status"] = "DISPUTED"
    touch(s)
    return success(ser_settlement(s))


@bp.post("/buying-points/settlements/<s_id>/pay")
def pay_settlement(s_id):
    uid, role = require_roles([CLERK])
    s = get_or_404(store.settlements, s_id)
    if s["status"] != "APPROVED":
        raise invalid_state("Only an APPROVED settlement may be paid")
    if uid == s["approved_by"]:
        raise err("ERR_SEG_OF_DUTIES", 409,
                  "The approving clerk may not pay the settlement")
    s["paid_by"] = uid
    s["status"] = "PAID"
    touch(s)
    # Loan payoff: every offset pledge still ACTIVE -> REPAID; receipt -> OPEN.
    for pledge_id in s["offset_pledge_ids"]:
        p = store.loan_pledges.get(pledge_id)
        if p is None or p["status"] != "ACTIVE":
            continue
        p["status"] = "REPAID"
        p["outstanding_principal_cents"] = 0
        p["accrued_balance_cents"] = 0
        touch(p)
        receipt = store.storage_receipts.get(p["storage_receipt_id"])
        if receipt is not None and receipt["status"] == "PLEDGED":
            receipt["status"] = "OPEN"
            touch(receipt)
    return success(ser_settlement(s))


@bp.post("/buying-points/settlements/<s_id>/void")
def void_settlement(s_id):
    require_roles([ADMIN])
    s = get_or_404(store.settlements, s_id)
    if s["status"] != "APPROVED":
        raise invalid_state("Only an APPROVED settlement may be voided")
    s["status"] = "VOIDED"
    touch(s)
    # Compensating invariant: release the consumed quota and the load locks.
    qh = calc.quota_history_for(s["grower_id"], s["crop_year"])
    if qh is not None:
        qh["used_quota_tons"] -= s["quota_tons_applied"]
        touch(qh)
    for load_id in s["included_load_ids"]:
        load = store.loads.get(load_id)
        if load is not None and load["settlement_id"] == s["id"]:
            load["settlement_id"] = None
            touch(load)
    return success(ser_settlement(s))
