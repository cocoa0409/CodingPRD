"""Business logic: derived fields (estate ledger), calculations, state cascades.

Implements SCAFFOLD §1.3 calculations:
  - estate_cash_position (cash_on_hand, marshalled_value, allowed_claims_total, posture)
  - claim_priority_determination (class bucketing, WAGE_PRIORITY_CAP_CENTS = 1515000)
  - distribution_waterfall (provisional snapshot + final schedule w/ pro-rata floor + remainder sweep)
  - fee_request_calculation (hourly lodestar per-entry round-half-up; contingent percentage)
  - reporting_calendar (next_report_period_start, report_overdue)
  - engagement_fee_cap (committed <= cap at approve; EXHAUSTED at cap on pay)
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import errors
from db import store, iso_out, _parse_iso

WAGE_PRIORITY_CAP_CENTS = 1515000

PRIORITY_CLASS_RANK = {"SECURED": 1, "PRIORITY": 2, "GENERAL": 3, "INVESTOR": 4}


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------

def parse_dt(value, field):
    """Parse an input datetime; raise ERR_INVALID_REQUEST on failure."""
    dt = _parse_iso(value)
    if dt is None:
        raise errors.err_invalid_request(f"Field '{field}' must be an ISO 8601 datetime")
    # normalize to second precision
    return dt.replace(microsecond=0)


# ---------------------------------------------------------------------------
# Derived case fields (estate_cash_position)
# ---------------------------------------------------------------------------

def case_assets(case_id):
    return [a for a in store.assets.values() if a["case_id"] == case_id]


def case_claims(case_id):
    return [c for c in store.claims.values() if c["case_id"] == case_id]


def case_engagements(case_id):
    return [e for e in store.engagements.values() if e["case_id"] == case_id]


def case_reports(case_id):
    return [r for r in store.status_reports.values() if r["case_id"] == case_id]


def case_plans(case_id):
    return [p for p in store.distribution_plans.values() if p["case_id"] == case_id]


def case_fee_applications(case_id):
    eng_ids = {e["id"] for e in case_engagements(case_id)}
    return [f for f in store.fee_applications.values() if f["engagement_id"] in eng_ids]


def case_auth_requests(case_id):
    return [r for r in store.authorization_requests.values() if r["case_id"] == case_id]


def compute_cash_on_hand(case_id):
    total = 0
    for a in case_assets(case_id):
        if a["status"] == "LIQUIDATED" and a["liquidation_value_cents"] is not None:
            total += a["liquidation_value_cents"]
    for f in case_fee_applications(case_id):
        if f["status"] == "PAID" and f["approved_amount_cents"] is not None:
            total -= f["approved_amount_cents"]
    for p in store.distribution_payments.values():
        plan = store.distribution_plans.get(p["plan_id"])
        if plan is None or plan["case_id"] != case_id:
            continue
        if p["status"] == "PAID" and p["paid_amount_cents"] is not None:
            total -= p["paid_amount_cents"]
    for r in case_auth_requests(case_id):
        if r["status"] == "APPROVED" and r["request_type"] == "EXPENDITURE":
            total -= r["amount_cents"]
    return total


def compute_marshalled_value(case_id):
    total = 0
    for a in case_assets(case_id):
        if a["status"] == "ABANDONED":
            continue
        if a["status"] == "LIQUIDATED":
            total += a["liquidation_value_cents"] or 0
        else:
            total += a["estimated_value_cents"]
    return total


def compute_allowed_claims_total(case_id):
    total = 0
    for c in case_claims(case_id):
        if c["status"] == "ALLOWED" and c["allowed_amount_cents"] is not None:
            total += c["allowed_amount_cents"]
    return total


def compute_next_report_period_start(case):
    """Max period_end over non-REJECTED PERIODIC reports, else appointment_effective_at."""
    best = None
    for r in case_reports(case["id"]):
        if r["report_type"] != "PERIODIC" or r["status"] == "REJECTED":
            continue
        pe = r["_period_end"]
        if best is None or pe > best:
            best = pe
    if best is None:
        return case["_appointment_effective_at"]
    return best


def compute_report_overdue(case):
    """True iff logical clock time > next_report_period_start + reporting_interval_days (strict)."""
    start = compute_next_report_period_start(case)
    deadline = start + timedelta(days=case["reporting_interval_days"])
    return store.now() > deadline


def recompute_case_derived(case):
    case["cash_on_hand_cents"] = compute_cash_on_hand(case["id"])
    case["marshalled_value_cents"] = compute_marshalled_value(case["id"])
    case["allowed_claims_total_cents"] = compute_allowed_claims_total(case["id"])
    case["posture"] = (
        "CASH_CONSTRAINED"
        if case["cash_on_hand_cents"] < case["operating_reserve_cents"]
        else "NORMAL"
    )


def touch_case_for_recompute(case, bump_version):
    """Recompute derived fields; refresh updated_at; bump version when directed."""
    recompute_case_derived(case)
    case["updated_at"] = store.now_iso()
    if bump_version:
        case["version"] += 1


def recompute_engagement_fees(engagement):
    total = 0
    for f in store.fee_applications.values():
        if f["engagement_id"] == engagement["id"] and f["status"] == "PAID":
            total += f["approved_amount_cents"] or 0
    engagement["total_fees_paid_cents"] = total


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def serialize_case(case):
    return {
        "id": case["id"],
        "case_number": case["case_number"],
        "court_jurisdiction": case["court_jurisdiction"],
        "debtor_name": case["debtor_name"],
        "appointed_receiver_name": case["appointed_receiver_name"],
        "appointment_effective_at": iso_out(case["_appointment_effective_at"]),
        "authority_limit_cents": case["authority_limit_cents"],
        "business_operation_authorized": case["business_operation_authorized"],
        "bar_date": iso_out(case["_bar_date"]),
        "reporting_interval_days": case["reporting_interval_days"],
        "operating_reserve_cents": case["operating_reserve_cents"],
        "status": case["status"],
        "cash_on_hand_cents": case["cash_on_hand_cents"],
        "marshalled_value_cents": case["marshalled_value_cents"],
        "allowed_claims_total_cents": case["allowed_claims_total_cents"],
        "posture": case["posture"],
        "next_report_period_start": iso_out(compute_next_report_period_start(case)),
        "report_overdue": compute_report_overdue(case),
        "created_at": case["created_at"],
        "updated_at": case["updated_at"],
        "version": case["version"],
    }


def serialize_asset(a):
    return {
        "id": a["id"],
        "case_id": a["case_id"],
        "description": a["description"],
        "asset_class": a["asset_class"],
        "estimated_value_cents": a["estimated_value_cents"],
        "liquidation_value_cents": a["liquidation_value_cents"],
        "liquidated_at": a["liquidated_at"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_claim(c):
    return {
        "id": c["id"],
        "case_id": c["case_id"],
        "creditor_name": c["creditor_name"],
        "creditor_type": c["creditor_type"],
        "filed_amount_cents": c["filed_amount_cents"],
        "collateral_asset_id": c["collateral_asset_id"],
        "filed_at": c["filed_at"],
        "status": c["status"],
        "allowed_amount_cents": c["allowed_amount_cents"],
        "secured_allowed_cents": c["secured_allowed_cents"],
        "priority_allowed_cents": c["priority_allowed_cents"],
        "general_allowed_cents": c["general_allowed_cents"],
        "investor_allowed_cents": c["investor_allowed_cents"],
        "determined_at": c["determined_at"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_engagement(e):
    return {
        "id": e["id"],
        "case_id": e["case_id"],
        "professional_name": e["professional_name"],
        "firm_name": e["firm_name"],
        "role_type": e["role_type"],
        "fee_arrangement": e["fee_arrangement"],
        "hourly_rate_cents": e["hourly_rate_cents"],
        "contingency_pct": e["contingency_pct"],
        "fee_cap_cents": e["fee_cap_cents"],
        "total_fees_paid_cents": e["total_fees_paid_cents"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_fee_application(f):
    return {
        "id": f["id"],
        "engagement_id": f["engagement_id"],
        "period_start": iso_out(f["_period_start"]),
        "period_end": iso_out(f["_period_end"]),
        "time_entries": f["time_entries"],
        "expenses_cents": f["expenses_cents"],
        "recovery_basis_cents": f["recovery_basis_cents"],
        "requested_amount_cents": f["requested_amount_cents"],
        "approved_amount_cents": f["approved_amount_cents"],
        "status": f["status"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def serialize_authorization_request(r):
    return {
        "id": r["id"],
        "case_id": r["case_id"],
        "request_type": r["request_type"],
        "description": r["description"],
        "amount_cents": r["amount_cents"],
        "related_asset_id": r["related_asset_id"],
        "status": r["status"],
        "decided_at": r["decided_at"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_status_report(r):
    return {
        "id": r["id"],
        "case_id": r["case_id"],
        "report_type": r["report_type"],
        "period_start": iso_out(r["_period_start"]),
        "period_end": iso_out(r["_period_end"]),
        "narrative": r["narrative"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_distribution_plan(p):
    return {
        "id": p["id"],
        "case_id": p["case_id"],
        "reserve_cents": p["reserve_cents"],
        "pool_snapshot_cents": p["pool_snapshot_cents"],
        "status": p["status"],
        "approved_at": p["approved_at"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_distribution_payment(p):
    return {
        "id": p["id"],
        "plan_id": p["plan_id"],
        "claim_id": p["claim_id"],
        "priority_class": p["priority_class"],
        "scheduled_amount_cents": p["scheduled_amount_cents"],
        "paid_amount_cents": p["paid_amount_cents"],
        "paid_at": p["paid_at"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

def get_json_body():
    from flask import request
    if not request.is_json:
        raise errors.err_invalid_request("Request body must be JSON")
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise errors.err_invalid_request("Request body must be a JSON object")
    return body


def require_field(body, field):
    if field not in body or body[field] is None:
        raise errors.err_invalid_request(f"Missing required field: {field}")
    return body[field]


def require_int(body, field):
    v = require_field(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.err_invalid_request(f"Field '{field}' must be an integer")
    return v


def require_positive_int(body, field):
    v = require_int(body, field)
    if v <= 0:
        raise errors.err_invalid_request(f"Field '{field}' must be > 0")
    return v


def require_nonnegative_int(body, field):
    v = require_int(body, field)
    if v < 0:
        raise errors.err_invalid_request(f"Field '{field}' must be >= 0")
    return v


def require_string(body, field):
    v = require_field(body, field)
    if not isinstance(v, str) or v == "":
        raise errors.err_invalid_request(f"Field '{field}' must be a non-empty string")
    return v


def require_bool(body, field):
    v = require_field(body, field)
    if not isinstance(v, bool):
        raise errors.err_invalid_request(f"Field '{field}' must be a boolean")
    return v


def require_enum(body, field, allowed):
    v = require_field(body, field)
    if not isinstance(v, str) or v not in allowed:
        raise errors.err_invalid_request(
            f"Field '{field}' must be one of {sorted(allowed)}"
        )
    return v


def forbid_field(body, field):
    if field in body and body[field] is not None:
        raise errors.err_invalid_request(f"Field '{field}' is forbidden here")


def parse_pagination():
    from flask import request
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise errors.err_invalid_request("Query parameter 'limit' must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise errors.err_invalid_request("Query parameter 'offset' must be an integer")
    if limit < 1 or limit > 100:
        raise errors.err_invalid_request("Query parameter 'limit' must be between 1 and 100")
    if offset < 0:
        raise errors.err_invalid_request("Query parameter 'offset' must be >= 0")
    return limit, offset


# ---------------------------------------------------------------------------
# Claim priority determination (claim_priority_determination)
# ---------------------------------------------------------------------------

def determine_claim_buckets(claim):
    """Split allowed_amount_cents into the four class buckets per creditor type."""
    allowed = claim["allowed_amount_cents"]
    ctype = claim["creditor_type"]
    if ctype == "SECURED":
        asset = store.assets.get(claim["collateral_asset_id"])
        if asset is None or asset["status"] == "ABANDONED":
            basis = 0
        elif asset["status"] == "LIQUIDATED":
            basis = asset["liquidation_value_cents"] or 0
        else:  # IDENTIFIED
            basis = asset["estimated_value_cents"]
        secured = min(allowed, basis)
        return secured, 0, allowed - secured, 0
    if ctype == "PRIORITY_WAGE":
        priority = min(allowed, WAGE_PRIORITY_CAP_CENTS)
        return 0, priority, allowed - priority, 0
    if ctype == "PRIORITY_TAX":
        return 0, allowed, 0, 0
    if ctype == "GENERAL_UNSECURED":
        return 0, 0, allowed, 0
    # INVESTOR
    return 0, 0, 0, allowed


def withdraw_filed_plan_if_totals_changed(case):
    """If a DistributionPlan of the case is FILED, move it to WITHDRAWN."""
    for p in case_plans(case["id"]):
        if p["status"] == "FILED":
            p["status"] = "WITHDRAWN"
            p["updated_at"] = store.now_iso()
            p["version"] += 1


# ---------------------------------------------------------------------------
# Distribution waterfall (final variant) — generates payment rows
# ---------------------------------------------------------------------------

def run_final_waterfall(plan, case):
    """Compute the final waterfall over ALLOWED claims and materialize payments."""
    pool = case["cash_on_hand_cents"] - plan["reserve_cents"]
    if pool < 0:
        pool = 0
    allowed_claims = [
        c for c in case_claims(case["id"])
        if c["status"] == "ALLOWED" and c["allowed_amount_cents"] is not None
    ]
    class_bucket_field = {
        "SECURED": "secured_allowed_cents",
        "PRIORITY": "priority_allowed_cents",
        "GENERAL": "general_allowed_cents",
        "INVESTOR": "investor_allowed_cents",
    }
    for cls in ("SECURED", "PRIORITY", "GENERAL", "INVESTOR"):
        if pool <= 0:
            break
        field = class_bucket_field[cls]
        rows = []  # (claim, bucket_amount)
        class_total = 0
        for c in allowed_claims:
            amt = c[field] or 0
            if amt > 0:
                rows.append((c, amt))
                class_total += amt
        if class_total == 0:
            continue
        payments = {}
        if pool >= class_total:
            for c, amt in rows:
                payments[c["id"]] = amt
            pool -= class_total
        else:
            allocated = 0
            for c, amt in rows:
                raw = (pool * amt) // class_total  # floor of pool*bucket/class_total
                payments[c["id"]] = raw
                allocated += raw
            remainder = pool - allocated
            # one cent at a time to buckets ordered by bucket DESC, tie-break claim created_at ASC
            ordered = sorted(rows, key=lambda rc: (-rc[1], rc[0]["_created_dt"]))
            i = 0
            while remainder > 0 and ordered:
                c, _amt = ordered[i % len(ordered)]
                payments[c["id"]] += 1
                remainder -= 1
                i += 1
            pool = 0
        for c, amt in rows:
            scheduled = payments.get(c["id"], 0)
            if scheduled <= 0:
                continue
            now_iso = store.now_iso()
            pay = {
                "id": store.new_id(),
                "plan_id": plan["id"],
                "claim_id": c["id"],
                "priority_class": cls,
                "scheduled_amount_cents": scheduled,
                "paid_amount_cents": None,
                "paid_at": None,
                "status": "SCHEDULED",
                "created_at": now_iso,
                "updated_at": now_iso,
                "version": 1,
                "_created_dt": store.now(),
            }
            store.distribution_payments[pay["id"]] = pay


def maybe_execute_plan(plan):
    """APPROVED plan -> EXECUTED when no SCHEDULED payments remain."""
    if plan["status"] != "APPROVED":
        return
    for p in store.distribution_payments.values():
        if p["plan_id"] == plan["id"] and p["status"] == "SCHEDULED":
            return
    plan["status"] = "EXECUTED"
    plan["updated_at"] = store.now_iso()
    plan["version"] += 1


# ---------------------------------------------------------------------------
# Fee request calculation (fee_request_calculation)
# ---------------------------------------------------------------------------

def round_half_up_cents(value):
    """Round a Decimal to whole cents, ROUND_HALF_UP."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_requested_amount(engagement, time_entries, expenses_cents, recovery_basis_cents):
    if engagement["fee_arrangement"] == "HOURLY":
        total = 0
        for entry in time_entries:
            hours = Decimal(str(entry["hours"]))
            rate = Decimal(str(entry["rate_cents"]))
            total += round_half_up_cents(hours * rate)
        return total + expenses_cents
    # CONTINGENT
    pct = Decimal(str(engagement["contingency_pct"]))
    basis = Decimal(str(recovery_basis_cents))
    return round_half_up_cents(pct * basis) + expenses_cents
