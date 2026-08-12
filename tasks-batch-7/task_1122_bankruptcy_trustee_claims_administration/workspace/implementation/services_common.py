"""Shared entity helpers, serializers, and case-level invariants."""
import uuid

import db
from errors import (
    ApiError, ERR_NOT_ASSIGNED_TRUSTEE, ERR_CASE_CLOSED, ERR_INSUFFICIENT_ESTATE_FUNDS,
)
from logical_clock import CLOCK
from util import isoformat, to_seconds

CASE_TERMINAL = ("CLOSED", "CONVERTED_DISMISSED")

PRIORITY_CLASSES = (
    "SECURED", "PRIORITY_TAX", "PRIORITY_WAGE", "PRIORITY_CONSUMER", "GENERAL_UNSECURED",
)

CASE_STATUSES = (
    "OPEN", "ASSET_INVESTIGATION", "CLAIMS_ADMINISTRATION", "LIQUIDATION",
    "DISTRIBUTION", "FINAL_REPORT", "CLOSED", "CONVERTED_DISMISSED",
)


# ---------------------------------------------------------------------------
# Generic entity lifecycle
# ---------------------------------------------------------------------------

def new_entity(fields):
    now = CLOCK.now()
    entity = dict(fields)
    entity["id"] = str(uuid.uuid4())
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    entity["_seq"] = db.next_seq()
    return entity


def touch(entity):
    """Refresh updated_at and increment version (PRD §2.5)."""
    entity["updated_at"] = CLOCK.now()
    entity["version"] += 1


def bump_case(case):
    touch(case)


# ---------------------------------------------------------------------------
# Lookup / guard helpers
# ---------------------------------------------------------------------------

def get_or_404(table, entity_id, what="resource"):
    entity = table.get(entity_id)
    if entity is None:
        from errors import not_found
        raise not_found(what)
    return entity


def get_case(case_id):
    return get_or_404(db.cases, case_id, "case")


def case_of(entity):
    return db.cases[entity["case_id"]]


def ensure_case_open(case):
    if case["status"] in CASE_TERMINAL:
        raise ApiError(ERR_CASE_CLOSED, 409, "The case is closed; no mutation may operate on it.")


def ensure_trustee_binding(case, uid):
    if uid != case["trustee_user_id"]:
        raise ApiError(ERR_NOT_ASSIGNED_TRUSTEE, 403, "X-User-ID is not the case's assigned trustee.")


def check_cash_nonnegative(case):
    if case["estate_cash_on_hand_cents"] < 0:
        raise ApiError(ERR_INSUFFICIENT_ESTATE_FUNDS, 409, "Operation would drive estate cash negative.")


def claim_late(claim, case):
    """PRD §3.2: late iff received_at strictly after claim_bar_date (second granularity)."""
    bar = case.get("claim_bar_date")
    if bar is None:
        return False
    return to_seconds(claim["received_at"]) > to_seconds(bar)


def posted_dividend_for_claim(claim_id):
    for div in db.dividends.values():
        if div["claim_id"] == claim_id and div["status"] == "POSTED":
            return div
    return None


# ---------------------------------------------------------------------------
# Serializers (exact declared fields; internal keys never leak)
# ---------------------------------------------------------------------------

def ser_case(c):
    return {
        "id": c["id"],
        "case_number": c["case_number"],
        "debtor_name": c["debtor_name"],
        "filed_on": isoformat(c["filed_on"]),
        "district": c["district"],
        "status": c["status"],
        "claim_bar_date": isoformat(c["claim_bar_date"]),
        "bar_date_noticed": c["bar_date_noticed"],
        "estate_cash_on_hand_cents": c["estate_cash_on_hand_cents"],
        "allowed_claims_total_cents": c["allowed_claims_total_cents"],
        "scheduled_unsecured_total_cents": c["scheduled_unsecured_total_cents"],
        "no_asset_report_filed": c["no_asset_report_filed"],
        "objection_window_days": c["objection_window_days"],
        "trustee_user_id": c["trustee_user_id"],
        "created_at": isoformat(c["created_at"]),
        "updated_at": isoformat(c["updated_at"]),
        "version": c["version"],
    }


def ser_creditor(c):
    return {
        "id": c["id"],
        "legal_name": c["legal_name"],
        "creditor_ref": c["creditor_ref"],
        "insider": c["insider"],
        "contact_email": c["contact_email"],
        "created_at": isoformat(c["created_at"]),
        "updated_at": isoformat(c["updated_at"]),
        "version": c["version"],
    }


def ser_claim(cl):
    case = db.cases.get(cl["case_id"])
    return {
        "id": cl["id"],
        "case_id": cl["case_id"],
        "creditor_id": cl["creditor_id"],
        "claim_number": cl["claim_number"],
        "received_at": isoformat(cl["received_at"]),
        "filed_amount_cents": cl["filed_amount_cents"],
        "allowed_amount_cents": cl["allowed_amount_cents"],
        "priority_class": cl["priority_class"],
        "secured_by_asset_id": cl["secured_by_asset_id"],
        "reclassified_from_claim_id": cl["reclassified_from_claim_id"],
        "late": claim_late(cl, case) if case else False,
        "status": cl["status"],
        "objection_id": cl["objection_id"],
        "created_at": isoformat(cl["created_at"]),
        "updated_at": isoformat(cl["updated_at"]),
        "version": cl["version"],
    }


def ser_objection(o):
    return {
        "id": o["id"],
        "case_id": o["case_id"],
        "claim_id": o["claim_id"],
        "grounds": o["grounds"],
        "proposed_allowed_amount_cents": o["proposed_allowed_amount_cents"],
        "proposed_priority_class": o["proposed_priority_class"],
        "status": o["status"],
        "resolved_at": isoformat(o["resolved_at"]),
        "created_at": isoformat(o["created_at"]),
        "updated_at": isoformat(o["updated_at"]),
        "version": o["version"],
    }


def ser_asset(a):
    return {
        "id": a["id"],
        "case_id": a["case_id"],
        "description": a["description"],
        "scheduled_value_cents": a["scheduled_value_cents"],
        "exempt": a["exempt"],
        "encumbered_claim_id": a["encumbered_claim_id"],
        "status": a["status"],
        "realized_proceeds_cents": a["realized_proceeds_cents"],
        "created_at": isoformat(a["created_at"]),
        "updated_at": isoformat(a["updated_at"]),
        "version": a["version"],
    }


def ser_sale(s):
    return {
        "id": s["id"],
        "case_id": s["case_id"],
        "asset_id": s["asset_id"],
        "buyer_name": s["buyer_name"],
        "hammer_price_cents": s["hammer_price_cents"],
        "sale_costs_cents": s["sale_costs_cents"],
        "net_proceeds_cents": s["net_proceeds_cents"],
        "sale_approved_on": isoformat(s["sale_approved_on"]),
        "effective_on": isoformat(s["effective_on"]),
        "proceeds_status": s["proceeds_status"],
        "status": s["status"],
        "created_at": isoformat(s["created_at"]),
        "updated_at": isoformat(s["updated_at"]),
        "version": s["version"],
    }


def ser_action(a):
    return {
        "id": a["id"],
        "case_id": a["case_id"],
        "transferee_creditor_id": a["transferee_creditor_id"],
        "transfer_date": isoformat(a["transfer_date"]),
        "transfer_amount_cents": a["transfer_amount_cents"],
        "action_type": a["action_type"],
        "lookback_window_days": a["lookback_window_days"],
        "avoidable": a["avoidable"],
        "demand_amount_cents": a["demand_amount_cents"],
        "recovered_amount_cents": a["recovered_amount_cents"],
        "status": a["status"],
        "created_at": isoformat(a["created_at"]),
        "updated_at": isoformat(a["updated_at"]),
        "version": a["version"],
    }


def ser_deposit(d):
    return {
        "id": d["id"],
        "case_id": d["case_id"],
        "avoidance_action_id": d["avoidance_action_id"],
        "amount_cents": d["amount_cents"],
        "status": d["status"],
        "created_at": isoformat(d["created_at"]),
        "updated_at": isoformat(d["updated_at"]),
        "version": d["version"],
    }


def ser_plan(p):
    return {
        "id": p["id"],
        "case_id": p["case_id"],
        "plan_sequence": p["plan_sequence"],
        "reserve_for_objected_cents": p["reserve_for_objected_cents"],
        "distributable_cents": p["distributable_cents"],
        "status": p["status"],
        "proposed_at": isoformat(p["proposed_at"]),
        "created_at": isoformat(p["created_at"]),
        "updated_at": isoformat(p["updated_at"]),
        "version": p["version"],
    }


def ser_allocation(a):
    return {
        "id": a["id"],
        "plan_id": a["plan_id"],
        "case_id": a["case_id"],
        "priority_class": a["priority_class"],
        "allocated_cents": a["allocated_cents"],
        "paid_total_cents": a["paid_total_cents"],
        "created_at": isoformat(a["created_at"]),
        "updated_at": isoformat(a["updated_at"]),
        "version": a["version"],
    }


def ser_dividend(d):
    return {
        "id": d["id"],
        "plan_id": d["plan_id"],
        "claim_id": d["claim_id"],
        "amount_cents": d["amount_cents"],
        "status": d["status"],
        "created_at": isoformat(d["created_at"]),
        "updated_at": isoformat(d["updated_at"]),
        "version": d["version"],
    }


def ser_fee(f):
    return {
        "id": f["id"],
        "case_id": f["case_id"],
        "applicant_role": f["applicant_role"],
        "requested_amount_cents": f["requested_amount_cents"],
        "commission_basis": f["commission_basis"],
        "computed_commission_cents": f["computed_commission_cents"],
        "status": f["status"],
        "approved_amount_cents": f["approved_amount_cents"],
        "effective_on": isoformat(f["effective_on"]),
        "created_at": isoformat(f["created_at"]),
        "updated_at": isoformat(f["updated_at"]),
        "version": f["version"],
    }


def ser_report(r):
    # FinalReport carries only id and created_at (PRD §2.5 exception).
    return {
        "id": r["id"],
        "case_id": r["case_id"],
        "total_receipts_cents": r["total_receipts_cents"],
        "total_dividends_cents": r["total_dividends_cents"],
        "total_fees_cents": r["total_fees_cents"],
        "unclaimed_funds_cents": r["unclaimed_funds_cents"],
        "status": r["status"],
        "created_at": isoformat(r["created_at"]),
    }


def sorted_rows(table_values):
    """Default list ordering: created_at ascending (PRD §2.3), insertion order breaks ties."""
    return sorted(table_values, key=lambda e: (e["created_at"], e["_seq"]))
