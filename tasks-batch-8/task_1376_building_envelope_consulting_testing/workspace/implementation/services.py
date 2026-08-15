"""Business logic: calculations, posture derivation, risk score, fee events,
entity construction and serialization."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import STORE, clock_now, new_id, next_seq
from errors import ERR_FEE_CAP_EXCEEDED, raise_err
from response import fmt_dt

# ---------------------------------------------------------------------------
# Constants (scaffold calculations table)
# ---------------------------------------------------------------------------
RISK_FLOOR = 0
RISK_CEILING = 100
MOCKUP_FAIL_DELTA = -25
FIELD_TEST_FAIL_DELTA = -25
REMEDIATION_RECOVERY = 10
VERIFY_DELTAS = {"CRITICAL": -15, "HIGH": -10, "MEDIUM": -5, "LOW": -2}

RISK_FREEZE_THRESHOLD = 40
RISK_RESTRICT_THRESHOLD = 70

TIER1_MAX_DRAWINGS = 5
TIER1_BASE_CENTS = 250000
TIER2_MARGINAL_CENTS = 30000
TIER2_MAX_DRAWINGS = 15
TIER3_MARGINAL_CENTS = 20000
EXTRA_BARRIER_CENTS = 40000
REVISION_SURCHARGE_PCT = Decimal("0.10")

SPECIMEN_SURCHARGE_PCT = Decimal("0.05")
REFERENCE_PRESSURE_PA = 75

SEVERITY_COST_CENTS = {
    "LOW": 500000,
    "MEDIUM": 1500000,
    "HIGH": 4000000,
    "CRITICAL": 9000000,
}
CONTINGENCY_PCT = Decimal("1.20")
MOBILIZATION_PER_SECTION_CENTS = 125000

VOLUME_TIER_THRESHOLD_CENTS = 2000000
VOLUME_TIER_MIN_DISCOUNT_PCT = Decimal("10")

MANUFACTURER_RESPONSE_DAYS = 30


def round_half_up_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Entity lifecycle helpers
# ---------------------------------------------------------------------------
def new_common():
    now = clock_now()
    return {
        "id": new_id(),
        "_created_dt": now,
        "_updated_dt": now,
        "_seq": next_seq(),
        "version": 1,
    }


def new_audit():
    """Reduced property set (LitigationHold, Invoice): id + created_at only."""
    now = clock_now()
    return {"id": new_id(), "_created_dt": now, "_seq": next_seq()}


def touch(entity):
    entity["_updated_dt"] = clock_now()
    entity["version"] += 1


def touch_engagement(eng):
    """Engagement updated_at bump WITHOUT a version increment. Engagement.version
    increments only where the PRD/scaffold explicitly say so."""
    eng["_updated_dt"] = clock_now()


def bump_engagement_version(eng):
    eng["version"] += 1
    eng["_updated_dt"] = clock_now()


# ---------------------------------------------------------------------------
# Derived figures (computed on read; equivalent to recomputing after events)
# ---------------------------------------------------------------------------
def engagement_anomalies(engagement_id):
    return [
        a for a in STORE["anomalies"].values() if a["engagement_id"] == engagement_id
    ]


def derive_posture(eng):
    if eng["litigation_hold_active"]:
        return "FROZEN"
    anomalies = engagement_anomalies(eng["id"])
    if eng["risk_score"] < RISK_FREEZE_THRESHOLD or any(
        a["status"] == "VERIFIED" and a["severity"] == "CRITICAL" for a in anomalies
    ):
        return "FROZEN"
    if eng["risk_score"] < RISK_RESTRICT_THRESHOLD or any(
        a["status"] == "OPEN" for a in anomalies
    ):
        return "RESTRICTED"
    return "OPEN"


def invoiced_cents(engagement_id):
    return sum(
        inv["total_cents"]
        for inv in STORE["invoices"].values()
        if inv["engagement_id"] == engagement_id
        and inv["invoice_status"] in ("ISSUED", "PAID")
    )


def fee_headroom_cents(eng):
    return eng["fee_cap_cents"] - eng["recognized_fees_cents"]


def survey_anomaly_count(survey_id):
    return sum(
        1
        for a in STORE["anomalies"].values()
        if a.get("survey_id") == survey_id and a["status"] != "DISMISSED"
    )


# ---------------------------------------------------------------------------
# Risk score and fee accrual
# ---------------------------------------------------------------------------
def apply_risk_delta(eng, delta):
    eng["risk_score"] = max(RISK_FLOOR, min(RISK_CEILING, eng["risk_score"] + delta))
    touch_engagement(eng)


def record_fee_event(eng, delta, kind):
    STORE["fee_events"].append(
        {
            "engagement_id": eng["id"],
            "ts": clock_now(),
            "seq": next_seq(),
            "delta": delta,
            "kind": kind,
        }
    )


def apply_fee_delta(eng, delta, kind):
    """Provisional accrual: running sum floored at 0 after each step."""
    eng["recognized_fees_cents"] = max(0, eng["recognized_fees_cents"] + delta)
    record_fee_event(eng, delta, kind)
    touch_engagement(eng)


def fiscal_gate(eng, delta):
    """Tier 12: reject when applying the event would push fee_headroom below 0."""
    if eng["recognized_fees_cents"] + delta > eng["fee_cap_cents"]:
        raise_err(
            ERR_FEE_CAP_EXCEEDED,
            "Fee event would push recognized fees beyond fee_cap_cents",
        )


def final_fee_accrual(engagement_id):
    """FINAL variant: replay fee-bearing events chronologically (event timestamp
    ASC, ties broken by creation seq ASC), summing only positive fee events.
    Warranty-recovery offsets are excluded; no intermediate floor."""
    events = [
        e for e in STORE["fee_events"] if e["engagement_id"] == engagement_id
    ]
    events.sort(key=lambda e: (e["ts"], e["seq"]))
    return sum(e["delta"] for e in events if e["delta"] > 0)


# ---------------------------------------------------------------------------
# Calculations (scaffold section 1.3)
# ---------------------------------------------------------------------------
def design_review_fee(review):
    dc = review["drawing_count"]
    if dc <= TIER1_MAX_DRAWINGS:
        base = TIER1_BASE_CENTS
    elif dc <= TIER2_MAX_DRAWINGS:
        base = TIER1_BASE_CENTS + (dc - TIER1_MAX_DRAWINGS) * TIER2_MARGINAL_CENTS
    else:
        base = (
            TIER1_BASE_CENTS
            + (TIER2_MAX_DRAWINGS - TIER1_MAX_DRAWINGS) * TIER2_MARGINAL_CENTS
            + (dc - TIER2_MAX_DRAWINGS) * TIER3_MARGINAL_CENTS
        )
    barrier_surcharge = (len(review["barrier_scope"]) - 1) * EXTRA_BARRIER_CENTS
    revision_surcharge = round_half_up_cents(
        Decimal(review["revision_round"]) * REVISION_SURCHARGE_PCT * Decimal(base)
    )
    return base + barrier_surcharge + revision_surcharge


def mockup_testing_fee(mock_up, slot):
    days = (slot["_end_date"] - slot["_start_date"]).days
    daily = Decimal(slot["daily_rate_cents"]) * (
        Decimal(1) + SPECIMEN_SURCHARGE_PCT * (mock_up["specimen_count"] - 1)
    )
    daily_rounded = round_half_up_cents(daily)
    return daily_rounded * days * mock_up["attempt_number"]


def field_test_result(measured, assembly, test_pressure_pa):
    allowable = assembly["required_airtightness_lps_m2"] * (
        Decimal(test_pressure_pa) / Decimal(REFERENCE_PRESSURE_PA)
    )
    return "PASS" if measured <= allowable else "FAIL"


def remediation_estimate(plan, anomalies_by_id):
    subtotal = sum(
        SEVERITY_COST_CENTS[anomalies_by_id[aid]["severity"]]
        for aid in plan["anomaly_ids"]
    )
    return round_half_up_cents(Decimal(subtotal) * CONTINGENCY_PCT)


def remediation_actual(plan, anomalies_by_id):
    subtotal = sum(
        SEVERITY_COST_CENTS[anomalies_by_id[aid]["severity"]]
        for aid in plan["anomaly_ids"]
    )
    mobilization = len(plan["spec_sections"]) * MOBILIZATION_PER_SECTION_CENTS
    return subtotal + mobilization


def warranty_recovery_share(claim):
    covering = [
        p
        for p in STORE["remediation_plans"].values()
        if p["engagement_id"] == claim["engagement_id"]
        and p["plan_status"] == "COMPLETED"
        and claim["anomaly_id"] in p["anomaly_ids"]
    ]
    outlay = sum(p["actual_cost_cents"] for p in covering)
    already = sum(
        c["recovered_amount_cents"]
        for c in STORE["warranty_claims"].values()
        if c["anomaly_id"] == claim["anomaly_id"]
        and c["claim_status"] == "RESOLVED"
        and c["id"] != claim["id"]
    )
    return min(claim["claimed_amount_cents"], max(0, outlay - already))


def invoice_totals(eng, labor_hours, expense_cents, discount_pct):
    subtotal = round_half_up_cents(
        Decimal(labor_hours) * Decimal(eng["labor_rate_cents_per_hour"])
    ) + expense_cents
    if subtotal >= VOLUME_TIER_THRESHOLD_CENTS:
        effective_discount = max(Decimal(discount_pct), VOLUME_TIER_MIN_DISCOUNT_PCT)
    else:
        effective_discount = Decimal(discount_pct)
    total = round_half_up_cents(
        Decimal(subtotal) * (Decimal(1) - effective_discount / Decimal(100))
    )
    return subtotal, total


def response_due_at(filed_at):
    return filed_at + timedelta(days=MANUFACTURER_RESPONSE_DAYS)


# ---------------------------------------------------------------------------
# Serializers (exact scaffold field sets)
# ---------------------------------------------------------------------------
def _num(v):
    return float(v) if isinstance(v, Decimal) else v


def ser_engagement(e):
    return {
        "id": e["id"],
        "name": e["name"],
        "client_name": e["client_name"],
        "fee_cap_cents": e["fee_cap_cents"],
        "labor_rate_cents_per_hour": e["labor_rate_cents_per_hour"],
        "recognized_fees_cents": e["recognized_fees_cents"],
        "invoiced_cents": invoiced_cents(e["id"]),
        "fee_headroom_cents": fee_headroom_cents(e),
        "risk_score": e["risk_score"],
        "posture": derive_posture(e),
        "status": e["status"],
        "litigation_hold_active": e["litigation_hold_active"],
        "created_at": fmt_dt(e["_created_dt"]),
        "updated_at": fmt_dt(e["_updated_dt"]),
        "version": e["version"],
    }


def ser_assembly(a):
    return {
        "id": a["id"],
        "engagement_id": a["engagement_id"],
        "tag": a["tag"],
        "assembly_type": a["assembly_type"],
        "design_u_factor": _num(a["design_u_factor"]),
        "required_airtightness_lps_m2": _num(a["required_airtightness_lps_m2"]),
        "review_status": a["review_status"],
        "created_at": fmt_dt(a["_created_dt"]),
        "updated_at": fmt_dt(a["_updated_dt"]),
        "version": a["version"],
    }


def ser_design_review(r):
    return {
        "id": r["id"],
        "engagement_id": r["engagement_id"],
        "assembly_id": r["assembly_id"],
        "barrier_scope": list(r["barrier_scope"]),
        "drawing_count": r["drawing_count"],
        "revision_round": r["revision_round"],
        "reviewer_id": r["reviewer_id"],
        "review_fee_cents": r["review_fee_cents"],
        "status": r["status"],
        "created_at": fmt_dt(r["_created_dt"]),
        "updated_at": fmt_dt(r["_updated_dt"]),
        "version": r["version"],
    }


def ser_chamber_slot(s):
    return {
        "id": s["id"],
        "engagement_id": s["engagement_id"],
        "chamber_code": s["chamber_code"],
        "start_date": s["start_date"],
        "end_date": s["end_date"],
        "daily_rate_cents": s["daily_rate_cents"],
        "status": s["status"],
        "created_at": fmt_dt(s["_created_dt"]),
        "updated_at": fmt_dt(s["_updated_dt"]),
        "version": s["version"],
    }


def ser_mock_up(m):
    return {
        "id": m["id"],
        "engagement_id": m["engagement_id"],
        "assembly_id": m["assembly_id"],
        "chamber_slot_id": m["chamber_slot_id"],
        "specimen_count": m["specimen_count"],
        "air_leakage_lps_m2": (
            None if m["air_leakage_lps_m2"] is None else _num(m["air_leakage_lps_m2"])
        ),
        "testing_fee_cents": m["testing_fee_cents"],
        "attempt_number": m["attempt_number"],
        "status": m["status"],
        "created_at": fmt_dt(m["_created_dt"]),
        "updated_at": fmt_dt(m["_updated_dt"]),
        "version": m["version"],
    }


def ser_field_test(t):
    return {
        "id": t["id"],
        "engagement_id": t["engagement_id"],
        "assembly_id": t["assembly_id"],
        "test_method": t["test_method"],
        "test_date": t["test_date"],
        "test_pressure_pa": t["test_pressure_pa"],
        "measured_leakage_lps_m2": (
            None
            if t["measured_leakage_lps_m2"] is None
            else _num(t["measured_leakage_lps_m2"])
        ),
        "performed_by": t["performed_by"],
        "certified_by": t["certified_by"],
        "result": t["result"],
        "execution_status": t["execution_status"],
        "diagnosis_status": t["diagnosis_status"],
        "created_at": fmt_dt(t["_created_dt"]),
        "updated_at": fmt_dt(t["_updated_dt"]),
        "version": t["version"],
    }


def ser_survey(s):
    return {
        "id": s["id"],
        "engagement_id": s["engagement_id"],
        "assembly_id": s["assembly_id"],
        "survey_type": s["survey_type"],
        "survey_date": s["survey_date"],
        "ambient_delta_t_c": _num(s["ambient_delta_t_c"]),
        "anomaly_count": survey_anomaly_count(s["id"]),
        "status": s["status"],
        "created_at": fmt_dt(s["_created_dt"]),
        "updated_at": fmt_dt(s["_updated_dt"]),
        "version": s["version"],
    }


def ser_anomaly(a):
    return {
        "id": a["id"],
        "engagement_id": a["engagement_id"],
        "field_test_id": a["field_test_id"],
        "survey_id": a["survey_id"],
        "anomaly_type": a["anomaly_type"],
        "severity": a["severity"],
        "description": a["description"],
        "status": a["status"],
        "created_at": fmt_dt(a["_created_dt"]),
        "updated_at": fmt_dt(a["_updated_dt"]),
        "version": a["version"],
    }


def ser_remediation_plan(p):
    return {
        "id": p["id"],
        "engagement_id": p["engagement_id"],
        "anomaly_ids": list(p["anomaly_ids"]),
        "spec_sections": list(p["spec_sections"]),
        "estimated_cost_cents": p["estimated_cost_cents"],
        "actual_cost_cents": p["actual_cost_cents"],
        "plan_status": p["plan_status"],
        "supersedes_plan_id": p["supersedes_plan_id"],
        "created_at": fmt_dt(p["_created_dt"]),
        "updated_at": fmt_dt(p["_updated_dt"]),
        "version": p["version"],
    }


def ser_warranty_claim(c):
    return {
        "id": c["id"],
        "engagement_id": c["engagement_id"],
        "anomaly_id": c["anomaly_id"],
        "manufacturer_name": c["manufacturer_name"],
        "claimed_amount_cents": c["claimed_amount_cents"],
        "recovered_amount_cents": c["recovered_amount_cents"],
        "filed_at": fmt_dt(c["_filed_at"]),
        "response_due_at": fmt_dt(c["_response_due_at"]),
        "claim_status": c["claim_status"],
        "created_at": fmt_dt(c["_created_dt"]),
        "updated_at": fmt_dt(c["_updated_dt"]),
        "version": c["version"],
    }


def ser_litigation_hold(h):
    return {
        "id": h["id"],
        "engagement_id": h["engagement_id"],
        "matter_reference": h["matter_reference"],
        "hold_status": h["hold_status"],
        "created_at": fmt_dt(h["_created_dt"]),
    }


def ser_maintenance_visit(v):
    return {
        "id": v["id"],
        "engagement_id": v["engagement_id"],
        "visit_label": v["visit_label"],
        "window_start_date": v["window_start_date"],
        "window_end_date": v["window_end_date"],
        "buffer_days": v["buffer_days"],
        "visit_status": v["visit_status"],
        "created_at": fmt_dt(v["_created_dt"]),
        "updated_at": fmt_dt(v["_updated_dt"]),
        "version": v["version"],
    }


def ser_invoice(i):
    return {
        "id": i["id"],
        "engagement_id": i["engagement_id"],
        "labor_hours": _num(i["labor_hours"]),
        "expense_cents": i["expense_cents"],
        "discount_pct": _num(i["discount_pct"]),
        "subtotal_cents": i["subtotal_cents"],
        "total_cents": i["total_cents"],
        "invoice_status": i["invoice_status"],
        "created_at": fmt_dt(i["_created_dt"]),
    }
