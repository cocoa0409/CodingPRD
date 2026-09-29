"""Calculation rules (SCAFFOLD 1.3 / PRD 3).

Every constant below is read from the PRD/scaffold; nothing is invented and no
entity data is stored here.  Money is integer cents, rates integer basis points,
exposed ratios are 4-decimal figures rounded half up.
"""

from decimal import Decimal

from core import ApiError, db, days, iso3, q4, rhu4, rhu_int

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SIGNAGE_MIN_PCT = Decimal("0.9000")

LOOKBACK_DAYS = 365
BASE_TIER_CENTS = {1: 7500, 2: 15000, 3: 25000}
ASSISTANCE_DISCOUNT_BPS = 5000
PENALTY_CAP_CENTS = 27500
PENALTY_FLOOR_CENTS = 2500

FEE_BAND_1_MAX = 10000
FEE_BAND_2_MAX = 20000

SAMPLE_ADEQUACY_MIN = Decimal("0.8000")

REGULAR_RATE_CENTS_PER_HOUR = 4800
OVERTIME_RATE_CENTS_PER_HOUR = 7200
REGULAR_MINUTES_CAP = 360
ZONE_PREMIUM_BPS = 500

MIN_DOWN_PAYMENT_BPS = 1000
PLAN_MIN_INSTALLMENTS = 2
PLAN_MAX_INSTALLMENTS = 6
INSTALLMENT_INTERVAL_DAYS = 30
PLAN_DEFAULT_MISSED_THRESHOLD = 2

SERVICE_CREDIT_CENTS_PER_HOUR = 1500

CONTEST_WINDOW_DAYS = 30
HEARING_LEAD_DAYS = 14
APPEAL_WINDOW_DAYS = 21
SUPPLEMENT_WINDOW_DAYS = 14
REISSUE_WINDOW_DAYS = 14
APPEAL_MAX_ROUNDS = 2

# ---------------------------------------------------------------------------
# Enum vocabularies
# ---------------------------------------------------------------------------

ZONE_STATUSES = ("DRAFT", "PENDING_SIGNAGE", "DESIGNATED", "SUSPENDED", "REVOKED")
ENFORCEMENT_POLICIES = ("WARNING_FIRST", "CITATION_IMMEDIATE")
SUSPENSION_REASONS = ("SIGNAGE_DEFICIENCY", "ADMINISTRATIVE_HOLD")
LINE_MODES = ("BUS", "LIGHT_RAIL", "COMMUTER_RAIL", "STREETCAR")
INSPECTOR_STATUSES = ("ACTIVE", "SUSPENDED")
DEMOGRAPHIC_BANDS = ("BAND_A", "BAND_B", "BAND_C", "BAND_D", "UNDISCLOSED")
DEPLOYMENT_STATUSES = ("PLANNED", "ACTIVE", "CLOSED", "VOIDED")
SAMPLING_METHODS = ("SYSTEMATIC_INTERVAL", "CLUSTER_RANDOM", "STRATIFIED_TIME")
VOID_REASONS = ("ZONE_SUSPENDED", "PLANNER_CANCELLED")
FARE_MEDIA_TYPES = ("SMARTCARD", "MOBILE_QR", "PAPER_TRANSFER", "CASH_RECEIPT", "NONE")
ELECTRONIC_MEDIA = ("SMARTCARD", "MOBILE_QR")
IDENTITY_METHODS = ("GOVT_ID", "SELF_REPORTED", "REFUSED")
VALIDATION_RESULTS = ("VALID", "EXPIRED", "UNVALIDATED_TAP", "WRONG_ZONE", "NO_PROOF")
NONCOMPLIANT_RESULTS = ("EXPIRED", "UNVALIDATED_TAP", "WRONG_ZONE", "NO_PROOF")
ENCOUNTER_OUTCOMES = ("PENDING", "COMPLIANT", "WARNING_ISSUED", "CITATION_ISSUED",
                      "UNRESOLVED_IDENTITY", "VOIDED")
RESOLVE_DISPOSITIONS = ("COMPLIANT", "WARNING_ISSUED", "UNRESOLVED_IDENTITY")
ADJUDICATION_STATUSES = ("ISSUED", "CONTESTED", "UPHELD", "REDUCED", "DISMISSED", "VOID")
LIVE_ADJUDICATION = ("ISSUED", "CONTESTED", "UPHELD", "REDUCED")
SETTLEMENT_STATUSES = ("OUTSTANDING", "PLAN_ACTIVE", "SERVICE_ACTIVE", "SATISFIED", "WRITTEN_OFF")
DISMISSAL_REASONS = ("SIGNAGE_DEFICIENT", "VALID_FARE_PRESENTED", "IDENTITY_ERROR",
                     "ZONE_NOT_DESIGNATED", "FIRST_OFFENSE_DIVERSION", "PROCEDURAL_DEFECT")
HEARING_STATUSES = ("SCHEDULED", "HELD", "CANCELLED")
HEARING_DECISIONS = ("PENDING", "UPHOLD", "DISMISS", "REDUCE")
DECIDE_DECISIONS = ("UPHOLD", "REDUCE", "DISMISS")
APPEAL_GROUNDS = ("SIGNAGE_DEFICIENCY", "IDENTITY_ERROR", "VALID_FARE_EVIDENCE",
                  "PROCEDURAL_DEFECT", "HARDSHIP")
APPEAL_STATUSES = ("SUBMITTED", "SUPPLEMENT_REQUESTED", "GRANTED", "DENIED", "WITHDRAWN")
APPEAL_LIVE_STATUSES = ("SUBMITTED", "SUPPLEMENT_REQUESTED")
APPEAL_DECISIONS = ("GRANTED", "DENIED")
PLAN_STATUSES = ("ACTIVE", "COMPLETED", "DEFAULTED", "CANCELLED")
SERVICE_STATUSES = ("ACTIVE", "COMPLETED", "FORFEITED", "CANCELLED")
PAYMENT_SOURCES = ("DOWN_PAYMENT", "PLAN_INSTALLMENT", "DIRECT", "SERVICE_CREDIT",
                   "DISMISSAL_REVERSAL")
CASH_IN_SOURCES = ("DOWN_PAYMENT", "PLAN_INSTALLMENT", "DIRECT")
GROUP_BY_VALUES = ("DEMOGRAPHIC_BAND", "GEO_TRACT")
BASIS_VALUES = ("ACCRUAL", "CASH")


# ---------------------------------------------------------------------------
# zone_signage_compliance_pct
# ---------------------------------------------------------------------------

def zone_audits(zone_id):
    return [a for a in db.audits.values() if a["zone_id"] == zone_id]


def zone_signage(zone):
    """(verified_sign_count, signage_compliance_pct as Decimal(4)) for a zone."""
    audits = zone_audits(zone["id"])
    if not audits:
        return 0, q4(0)
    latest = sorted(audits,
                    key=lambda a: (a["audited_at"], a["created_at"], a["_seq"]))[-1]
    verified = latest["signs_verified_count"]
    pct = rhu4(verified, zone["required_sign_count"])
    if pct > Decimal("1.0000"):
        pct = Decimal("1.0000")
    return verified, pct


# ---------------------------------------------------------------------------
# encounter_validation_result -- branch order is normative
# ---------------------------------------------------------------------------

def encounter_validation_result(media_type, media_validated_at, media_expires_at,
                               media_zone_code, occurred_at, zone_code):
    if media_type == "NONE":
        return "NO_PROOF"
    if media_type in ELECTRONIC_MEDIA:
        if media_validated_at is None:
            return "UNVALIDATED_TAP"
        if media_zone_code != zone_code:
            return "WRONG_ZONE"
        if media_expires_at is None:
            return "NO_PROOF"
        if media_expires_at < occurred_at:
            return "EXPIRED"
        return "VALID"
    # paper classes: expiry BEFORE zone
    if media_expires_at is None:
        return "NO_PROOF"
    if media_expires_at < occurred_at:
        return "EXPIRED"
    if media_zone_code != zone_code:
        return "WRONG_ZONE"
    return "VALID"


# ---------------------------------------------------------------------------
# citation_offense_sequence -- two variants
# ---------------------------------------------------------------------------

def offense_sequences(rider_id, issued_at, exclude_citation_id=None):
    lo = issued_at - days(LOOKBACK_DAYS)
    prior_citations = 0
    for c in db.citations.values():
        if c["rider_id"] != rider_id:
            continue
        if exclude_citation_id is not None and c["id"] == exclude_citation_id:
            continue
        if c["adjudication_status"] not in LIVE_ADJUDICATION:
            continue
        if lo < c["issued_at"] <= issued_at:
            prior_citations += 1
    prior_warnings = 0
    for e in db.encounters.values():
        if e["rider_id"] != rider_id:
            continue
        if e["outcome"] != "WARNING_ISSUED":
            continue
        if lo < e["occurred_at"] <= issued_at:
            prior_warnings += 1
    return (1 + prior_warnings + prior_citations, 1 + prior_citations)


# ---------------------------------------------------------------------------
# citation_assessed_penalty_cents
# ---------------------------------------------------------------------------

def assess_penalty(sequence, penalty_multiplier_bps, fare_assistance_enrolled):
    tier_base = BASE_TIER_CENTS[min(max(sequence, 1), 3)]
    scaled = rhu_int(tier_base * penalty_multiplier_bps, 10000)
    if fare_assistance_enrolled:
        discounted = rhu_int(scaled * (10000 - ASSISTANCE_DISCOUNT_BPS), 10000)
    else:
        discounted = scaled
    return max(PENALTY_FLOOR_CENTS, min(PENALTY_CAP_CENTS, discounted))


# ---------------------------------------------------------------------------
# citation_admin_fee_cents -- band keyed on the PRE-fee penalty
# ---------------------------------------------------------------------------

def admin_fee_cents(assessed_penalty_cents):
    if assessed_penalty_cents <= FEE_BAND_1_MAX:
        fee_bps = 800
    elif assessed_penalty_cents <= FEE_BAND_2_MAX:
        fee_bps = 1200
    else:
        fee_bps = 1500
    return rhu_int(assessed_penalty_cents * fee_bps, 10000)


# ---------------------------------------------------------------------------
# citation_outstanding_balance_cents
# ---------------------------------------------------------------------------

def citation_payments(citation_id):
    return [p for p in db.payments.values() if p["citation_id"] == citation_id]


def citation_money(citation):
    rows = citation_payments(citation["id"])
    paid_in = sum(p["amount_cents"] for p in rows if p["source"] in CASH_IN_SOURCES)
    reversed_out = sum(p["amount_cents"] for p in rows if p["source"] == "DISMISSAL_REVERSAL")
    amount_paid = paid_in - reversed_out
    service_credit = sum(p["amount_cents"] for p in rows if p["source"] == "SERVICE_CREDIT")
    if citation["settlement_status"] in ("SATISFIED", "WRITTEN_OFF"):
        outstanding = 0
    else:
        outstanding = max(0, citation["total_due_cents"] - amount_paid - service_credit)
    return amount_paid, service_credit, outstanding


def refresh_citation_money(citation):
    paid, credit, outstanding = citation_money(citation)
    citation["amount_paid_cents"] = paid
    citation["service_credit_cents"] = credit
    citation["outstanding_balance_cents"] = outstanding
    return citation


# ---------------------------------------------------------------------------
# deployment_sample_adequacy_ratio
# ---------------------------------------------------------------------------

def deployment_encounters(deployment_id):
    return [e for e in db.encounters.values() if e["deployment_id"] == deployment_id]


def refresh_deployment_counters(deployment):
    encounters = deployment_encounters(deployment["id"])
    achieved = sum(1 for e in encounters if e["outcome"] != "VOIDED")
    voided = sum(1 for e in encounters if e["outcome"] == "VOIDED")
    deployment["achieved_sample_count"] = achieved
    deployment["voided_encounter_count"] = voided
    deployment["sample_adequacy_ratio"] = rhu4(achieved, deployment["target_sample_size"])
    return deployment


# ---------------------------------------------------------------------------
# deployment_evasion_rate_bps -- two variants
# ---------------------------------------------------------------------------

def evasion_rates(deployment):
    encounters = deployment_encounters(deployment["id"])
    pool_a = [e for e in encounters if e["outcome"] != "VOIDED"]
    num_a = sum(1 for e in pool_a if e["validation_result"] in NONCOMPLIANT_RESULTS)
    measured = 0 if not pool_a else rhu_int(num_a * 10000, len(pool_a))
    pool_b = [e for e in encounters
              if e["outcome"] not in ("VOIDED", "UNRESOLVED_IDENTITY")]
    num_b = sum(1 for e in pool_b if e["validation_result"] in NONCOMPLIANT_RESULTS)
    resolved = 0 if not pool_b else rhu_int(num_b * 10000, len(pool_b))
    return measured, resolved


# ---------------------------------------------------------------------------
# deployment_enforcement_cost_cents -- pinned rounding order
# ---------------------------------------------------------------------------

def enforcement_cost_cents(deployment, zone):
    delta = deployment["window_end"] - deployment["window_start"]
    dur_min = int(delta.total_seconds() // 60)
    reg_min = min(dur_min, REGULAR_MINUTES_CAP)
    ot_min = max(0, dur_min - REGULAR_MINUTES_CAP)
    per_inspector = (rhu_int(reg_min * REGULAR_RATE_CENTS_PER_HOUR, 60)
                     + rhu_int(ot_min * OVERTIME_RATE_CENTS_PER_HOUR, 60))
    labour = per_inspector * deployment["planned_inspector_count"]
    if zone["penalty_multiplier_bps"] > 10000:
        premium = rhu_int(labour * ZONE_PREMIUM_BPS, 10000)
    else:
        premium = 0
    return labour + premium


# ---------------------------------------------------------------------------
# payment_plan_schedule
# ---------------------------------------------------------------------------

def minimum_down_payment_cents(outstanding_balance_cents):
    return rhu_int(outstanding_balance_cents * MIN_DOWN_PAYMENT_BPS, 10000)


def plan_schedule(financed_cents, installment_count):
    base = financed_cents // installment_count
    remainder = financed_cents - base * installment_count
    return base, base + remainder


def plan_installment_rows(plan_id):
    return [p for p in db.payments.values()
            if p["plan_id"] == plan_id and p["source"] == "PLAN_INSTALLMENT"]


def refresh_plan_counters(plan):
    rows = plan_installment_rows(plan["id"])
    plan["installments_paid_count"] = len(rows)
    plan["remaining_balance_cents"] = (plan["financed_cents"]
                                       - sum(r["amount_cents"] for r in rows))
    return plan


def next_installment_amount(plan):
    paid = plan["installments_paid_count"]
    if paid + 1 >= plan["installment_count"]:
        return plan["final_installment_cents"]
    return plan["base_installment_cents"]


# ---------------------------------------------------------------------------
# plan_delinquency_assessment
# ---------------------------------------------------------------------------

def installment_due_at(plan, k):
    return plan["created_at"] + days(INSTALLMENT_INTERVAL_DAYS * k)


def missed_installments(plan, now):
    missed = 0
    for k in range(1, plan["installment_count"] + 1):
        if installment_due_at(plan, k) <= now and plan["installments_paid_count"] < k:
            missed += 1
    return missed


# ---------------------------------------------------------------------------
# service_hours_required
# ---------------------------------------------------------------------------

def required_service_hours(outstanding_balance_cents):
    return -(-outstanding_balance_cents // SERVICE_CREDIT_CENTS_PER_HOUR)


def service_credit_for_hours(hours, outstanding_balance_cents):
    return min(hours * SERVICE_CREDIT_CENTS_PER_HOUR, outstanding_balance_cents)


def service_credit_cents_for_citation(citation_id):
    return sum(p["amount_cents"] for p in db.payments.values()
               if p["citation_id"] == citation_id and p["source"] == "SERVICE_CREDIT")
