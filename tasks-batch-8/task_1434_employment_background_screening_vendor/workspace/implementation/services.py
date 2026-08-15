"""Shared business logic: cascades, evaluation, accuracy pooling, lazy flips."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from db import bump
from timeutil import (
    now, business_day_add, business_days_span_exclusive_inclusive,
    anniversary_years, subtract_years,
)

SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
OUTCOME_PRECEDENCE = {"CLEAR": 0, "IA_REQUIRED": 1, "ADVERSE_ELIGIBLE": 2}

NON_TERMINAL_FULFILLMENT = ("DRAFT", "CONSENT_CAPTURED", "DISPATCHED",
                            "REPORT_RECEIVED")
CASE_TERMINAL = ("FINAL_NOTICE_SENT", "ABORTED")


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def active_rule_for(code):
    for r in db.rules.values():
        if r["jurisdiction_code"] == code and r["status"] == "ACTIVE":
            return r
    return None


def active_matrix_for(tier):
    for m in db.matrices.values():
        if m["risk_tier"] == tier and m["status"] == "ACTIVE":
            return m
    return None


def report_of_order(order_id):
    for r in db.reports.values():
        if r["order_id"] == order_id:
            return r
    return None


def case_of_order(order_id):
    for c in db.cases.values():
        if c["order_id"] == order_id:
            return c
    return None


def assessments_of_order(order_id):
    return [a for a in db.assessments.values() if a["order_id"] == order_id]


def latest_consent(order_id):
    cons = [c for c in db.consents.values() if c["order_id"] == order_id]
    if not cons:
        return None
    cons.sort(key=lambda c: (c["created_at"], c["_seq"]))
    return cons[-1]


def findings_of_report(report_id):
    rows = [f for f in db.findings.values() if f["report_id"] == report_id]
    rows.sort(key=lambda f: (f["created_at"], f["_seq"]))
    return rows


# ---------------------------------------------------------------------------
# Lazy transitions
# ---------------------------------------------------------------------------

def refresh_case(case):
    """WAITING_PERIOD -> ELIGIBLE_FOR_FINAL once the deadline is reached."""
    if case["status"] == "WAITING_PERIOD" and now() >= case["earliest_final_notice_at"]:
        case["status"] = "ELIGIBLE_FOR_FINAL"
        bump(case)


# ---------------------------------------------------------------------------
# Cancellation compensation chain (order cancel / consent revoke /
# candidate withdraw / vendor decertify share this chain)
# ---------------------------------------------------------------------------

def cancel_order_cascade(order):
    if order["fulfillment_status"] in ("CLOSED", "CANCELLED"):
        return
    if order["fulfillment_status"] == "DISPATCHED":
        vendor = db.vendors.get(order["vendor_id"])
        if vendor is not None:
            vendor["active_order_count"] -= 1
            bump(vendor)
        order["provisional_fee_cents"] = None
    order["fulfillment_status"] = "CANCELLED"
    order["adjudication_status"] = "VOIDED"
    bump(order)
    case = case_of_order(order["id"])
    if case is not None and case["status"] not in CASE_TERMINAL:
        case["status"] = "ABORTED"
        case["hold_started_at"] = None
        bump(case)
    for ia in assessments_of_order(order["id"]):
        if ia["status"] == "DECIDED":
            ia["status"] = "VOID"
            bump(ia)


# ---------------------------------------------------------------------------
# Finding evaluation (considerability + matrix matching)
# ---------------------------------------------------------------------------

def evaluate_finding(finding, rule, position, delivered_at, matrix):
    """Compute considerable + matched_action in place for one finding dict."""
    salary_exempt = (
        rule["lookback_exemption_salary_cents"] > 0
        and position["annual_salary_cents"] >= rule["lookback_exemption_salary_cents"]
    )
    considerable = True
    if (finding["disposition"] == "ARREST_ONLY"
            and not rule["arrest_records_considerable"]):
        considerable = False
    elif finding["disposition"] == "CONVICTION" and not salary_exempt:
        cutoff = subtract_years(delivered_at.date(), rule["lookback_years_limit"])
        if finding["offense_date"].date() < cutoff:
            considerable = False
    finding["considerable"] = considerable
    matched = "CLEAR"
    if considerable:
        recency = anniversary_years(finding["offense_date"].date(),
                                    delivered_at.date())
        for rule_entry in matrix["rules"]:
            if rule_entry["offense_category"] != finding["offense_category"]:
                continue
            if SEVERITY_RANK[finding["severity"]] < SEVERITY_RANK[rule_entry["min_severity"]]:
                continue
            if recency > rule_entry["max_recency_years"]:
                continue
            matched = rule_entry["action"]
            break
    finding["matched_action"] = matched


def recommended_outcome(findings):
    """Worst matched_action across considerable findings; CLEAR if none."""
    worst = "CLEAR"
    for f in findings:
        if not f["considerable"]:
            continue
        if OUTCOME_PRECEDENCE[f["matched_action"]] > OUTCOME_PRECEDENCE[worst]:
            worst = f["matched_action"]
    return worst


# ---------------------------------------------------------------------------
# Vendor accuracy pooling
# ---------------------------------------------------------------------------

def _round_bps(value):
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pooled_accuracy_bps(vendor_id, statuses):
    rows = [a for a in db.audits.values()
            if a["vendor_id"] == vendor_id and a["status"] in statuses]
    if not rows:
        return 10000
    sum_m = sum(a["mismatches_found"] for a in rows)
    sum_s = sum(a["sample_size"] for a in rows)
    if sum_s == 0:
        return 10000
    ratio = Decimal(sum_m) / Decimal(sum_s)
    return _round_bps(Decimal(10000) * (Decimal(1) - ratio))


def mismatch_rate_bps(mismatches, sample_size):
    ratio = Decimal(mismatches) / Decimal(sample_size)
    return _round_bps(ratio * Decimal(10000))


def refresh_vendor_accuracy(vendor_id):
    vendor = db.vendors.get(vendor_id)
    if vendor is None:
        return
    vendor["accuracy_bps_finalized"] = pooled_accuracy_bps(vendor_id, ("FINALIZED",))
    vendor["accuracy_bps_including_draft"] = pooled_accuracy_bps(
        vendor_id, ("DRAFT", "FINALIZED"))
    bump(vendor)


# ---------------------------------------------------------------------------
# Adverse-action case helpers
# ---------------------------------------------------------------------------

def recompute_case_deadline(case):
    case["earliest_final_notice_at"] = business_day_add(
        case["pre_notice_sent_at"],
        case["wait_business_days_required"] + case["total_hold_business_days"])


def close_case_hold(case, closed_at):
    """UPHELD / WITHDRAWN path: accumulate hold days and recompute deadline."""
    if case["hold_started_at"] is not None:
        hold_days = business_days_span_exclusive_inclusive(
            case["hold_started_at"].date(), closed_at.date())
        case["total_hold_business_days"] += hold_days
        case["hold_started_at"] = None
        recompute_case_deadline(case)
    case["status"] = "WAITING_PERIOD"
    bump(case)


def dispute_overdue(filed_at, resolved_at):
    return resolved_at > filed_at + timedelta(days=30)
