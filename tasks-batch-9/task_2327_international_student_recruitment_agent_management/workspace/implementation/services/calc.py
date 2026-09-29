"""Pure calculation rules (scaffold section 1.3, PRD 2.8/3.5/3.6/3.8/3.9)."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db, today
from validation import parse_date

# --- enum universes ---------------------------------------------------------
VETTING_STATES = ("DRAFT", "SCREENING", "INFO_REQUESTED", "CLEARED", "REJECTED")
POSTURES = ("GOOD_STANDING", "WATCH", "PROBATION", "SUSPENDED", "DEBARRED")
POSTURE_RANK = {name: idx for idx, name in enumerate(POSTURES)}
TIERS = ("PLATINUM", "GOLD", "STANDARD", "WATCH", "UNRATED")
CONTRACT_STATUSES = ("DRAFT", "PENDING_AGENCY_SIGNATURE", "PENDING_COMPLIANCE_REVIEW",
                     "ACTIVE", "SUSPENDED", "TERMINATED", "EXPIRED")
APPLICATION_STATUSES = ("DRAFT", "SUBMITTED", "ADMITTED", "DENIED", "DEPOSIT_PAID",
                        "ENROLLED", "CENSUS_CONFIRMED", "PERSISTED", "WITHDRAWN")
DISCLOSURE_STATES = ("NOT_ISSUED", "ISSUED", "ACKNOWLEDGED", "INVALIDATED")
VERIFICATION_STATES = ("PENDING", "VERIFIED", "FLAGGED", "CONFIRMED_FRAUD", "CLEARED")
DOC_TYPES = ("PASSPORT", "TRANSCRIPT", "FINANCIAL_PROOF", "ENGLISH_TEST", "SPONSOR_LETTER")
DECLARED_SIGNALS = ("ISSUER_UNVERIFIED", "TRANSCRIPT_ANOMALY", "TRANSLATION_MISMATCH",
                    "DATE_INCONSISTENCY")
INCIDENT_CATEGORIES = ("DOCUMENT_FRAUD", "PROHIBITED_CLAIM", "DISCLOSURE_FAILURE",
                       "MISREPRESENTATION")
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
INCIDENT_SOURCES = ("STUDENT_COMPLAINT", "DOCUMENT_REVIEW", "AUDIT", "PARTNER_REPORT")
INCIDENT_STATUSES = ("REPORTED", "CONFIRMED", "DISMISSED")
ENTRY_STATES = ("ACCRUED", "APPROVED", "PAID", "CLAWED_BACK", "FORFEITED", "VOID")
ENTRY_KINDS = ("ACCRUAL", "CLAWBACK")
MILESTONES = ("DEPOSIT_PAID", "ENROLLED", "CENSUS_CONFIRMED", "PERSISTED")
MODULE_CODES = ("PROGRAM_ACCURACY", "PROHIBITED_CLAIMS", "VISA_INTEGRITY")
CERT_STATUSES = ("VALID", "EXPIRED", "REVOKED")
ASSIGNMENT_STATUSES = ("ACTIVE", "RELEASED", "EXPIRED")
EXCLUSIVITIES = ("EXCLUSIVE", "NON_EXCLUSIVE")
EXCLUSIVITY_MODELS = ("EXCLUSIVE_ALLOWED", "NON_EXCLUSIVE_ONLY")
TERMINATION_REASONS = ("FOR_CAUSE", "CONVENIENCE", "NON_RENEWAL")
TRANSITION_REASONS = ("TERMINATION_FOR_CAUSE", "TERMINATION_CONVENIENCE",
                      "TERMINATION_NON_RENEWAL")
PROGRAM_LEVELS = ("UNDERGRADUATE", "POSTGRADUATE")
RECRUITMENT_ORIGINS = ("DOMESTIC", "INTERNATIONAL")

LIVE_CONTRACT_STATUSES = ("DRAFT", "PENDING_AGENCY_SIGNATURE", "PENDING_COMPLIANCE_REVIEW",
                          "ACTIVE", "SUSPENDED")

# --- constants --------------------------------------------------------------
MODULE_VALIDITY_DAYS = {"PROGRAM_ACCURACY": 365, "PROHIBITED_CLAIMS": 180,
                        "VISA_INTEGRITY": 365}
TIER_BONUS_BPS = {"PLATINUM": 150, "GOLD": 75, "STANDARD": 0, "WATCH": -100, "UNRATED": 0}
RATE_FIELD = {
    "DEPOSIT_PAID": "deposit_rate_bps",
    "ENROLLED": "enrollment_rate_bps",
    "CENSUS_CONFIRMED": "census_rate_bps",
    "PERSISTED": "persistence_rate_bps",
}
SIGNAL_WEIGHT = {"HASH_DUPLICATE": 45, "ISSUER_UNVERIFIED": 25, "TRANSCRIPT_ANOMALY": 20,
                 "TRANSLATION_MISMATCH": 15, "DATE_INCONSISTENCY": 10}
FLAG_THRESHOLD = 60
SEVERITY_WEIGHT = {"LOW": 5, "MEDIUM": 15, "HIGH": 30, "CRITICAL": 50}
FRAUD_RATE_WEIGHT = Decimal(40)
ROLLING_WINDOW_DAYS = 365
BAND_WATCH = Decimal("40.00")
BAND_PROBATION = Decimal("65.00")
BAND_SUSPENDED = Decimal("85.00")
EXCLUSIVE_COOLOFF_DAYS = 30
MAX_CONCURRENT_NON_EXCLUSIVE = 3
BPS_DENOMINATOR = Decimal(10000)
WEIGHT_YIELD = Decimal("0.45")
WEIGHT_PERSISTENCE = Decimal("0.35")
WEIGHT_QUALITY = Decimal("0.20")
REVIEWED_STATES = ("VERIFIED", "FLAGGED", "CONFIRMED_FRAUD", "CLEARED")
FLAGGED_STATES = ("FLAGGED", "CONFIRMED_FRAUD")
CLAWBACK_RATIO_THRESHOLD = Decimal("0.25")


def rhu(value, places):
    """Round half up to `places` decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quant = Decimal(1).scaleb(-places)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def as_number(value, places):
    return float(rhu(value, places))


# --- collection helpers -----------------------------------------------------

def agency_applications(agency_id):
    return [a for a in db.applications.values() if a["agency_id"] == agency_id]


def application_documents(application_id):
    return [d for d in db.documents.values() if d["application_id"] == application_id]


def agency_documents(agency_id):
    app_ids = set(a["id"] for a in db.applications.values() if a["agency_id"] == agency_id)
    return [d for d in db.documents.values() if d["application_id"] in app_ids]


def agency_contracts(agency_id):
    return [c for c in db.contracts.values() if c["agency_id"] == agency_id]


def contract_schedules(contract_id):
    return sorted([s for s in db.schedules.values() if s["contract_id"] == contract_id],
                  key=lambda s: s["version_no"])


def contract_assignments(contract_id):
    return [t for t in db.assignments.values() if t["contract_id"] == contract_id]


def application_entries(application_id):
    return [e for e in db.entries.values() if e["application_id"] == application_id]


def contract_entries(contract_id):
    return [e for e in db.entries.values() if e["contract_id"] == contract_id]


def agency_entries(agency_id):
    contract_ids = set(c["id"] for c in db.contracts.values() if c["agency_id"] == agency_id)
    return [e for e in db.entries.values() if e["contract_id"] in contract_ids]


def agency_certifications(agency_id):
    return [c for c in db.certifications.values() if c["agency_id"] == agency_id]


def agency_incidents(agency_id):
    return [i for i in db.incidents.values() if i["agency_id"] == agency_id]


def agency_scorecards(agency_id):
    return [s for s in db.scorecards.values() if s["agency_id"] == agency_id]


def active_contracts(agency_id):
    return [c for c in agency_contracts(agency_id) if c["status"] == "ACTIVE"]


# --- recruitment origin -----------------------------------------------------

def classify_origin(residence_country, us_person):
    if residence_country == "US" or us_person is True:
        return "DOMESTIC"
    return "INTERNATIONAL"


# --- tier resolution --------------------------------------------------------

def resolve_tier(agency_id, event_date):
    """calculations.tier_multiplier_resolution - scorecards closing STRICTLY
    before the event date being priced."""
    candidates = []
    for card in agency_scorecards(agency_id):
        end = parse_date(card["period_end_date"])
        if end is not None and end < event_date:
            candidates.append(card)
    if not candidates:
        return "UNRATED"
    candidates.sort(key=lambda s: (s["period_end_date"], s["_seq"]), reverse=True)
    return candidates[0]["tier"]


def current_tier(agency_id):
    cards = agency_scorecards(agency_id)
    if not cards:
        return "UNRATED"
    cards.sort(key=lambda s: (s["period_end_date"], s["_seq"]), reverse=True)
    return cards[0]["tier"]


# --- milestone pricing ------------------------------------------------------

def milestone_amount(program, schedule, milestone, tier):
    """calculations.milestone_commission_amount -> (effective_bps, amount_cents)."""
    base_bps = schedule[RATE_FIELD[milestone]]
    bonus_bps = TIER_BONUS_BPS[tier]
    effective_bps = max(0, min(base_bps + bonus_bps,
                               schedule["rate_cap_bps"],
                               program["max_commission_bps"]))
    raw = Decimal(program["annual_tuition_cents"]) * Decimal(effective_bps) / BPS_DENOMINATOR
    amount = int(rhu(raw, 0))
    amount = min(amount, schedule["per_milestone_cap_cents"])
    return effective_bps, amount


def provisional_projection(program, schedule, tier):
    """commission_entitlement variant provisional_forward_looking."""
    total = 0
    for milestone in MILESTONES:
        total += milestone_amount(program, schedule, milestone, tier)[1]
    return total


def application_net_commission(application_id):
    """commission_entitlement variant final_chronological."""
    accrued = 0
    clawed = 0
    for entry in application_entries(application_id):
        if entry["kind"] == "ACCRUAL" and entry["state"] in ("ACCRUED", "APPROVED", "PAID"):
            accrued += entry["amount_cents"]
        elif entry["kind"] == "CLAWBACK" and entry["state"] == "CLAWED_BACK":
            clawed += entry["amount_cents"]
    return accrued - clawed


def agency_ledger_balance(agency_id):
    """calculations.agency_commission_ledger_balance -> (net, clawback liability)."""
    accrued = 0
    clawed = 0
    liability = 0
    for entry in agency_entries(agency_id):
        if entry["kind"] == "ACCRUAL" and entry["state"] in ("ACCRUED", "APPROVED", "PAID"):
            accrued += entry["amount_cents"]
        elif entry["kind"] == "CLAWBACK" and entry["state"] == "CLAWED_BACK":
            clawed += entry["amount_cents"]
            if entry.get("_parent_was_paid"):
                liability += entry["amount_cents"]
    return accrued - clawed, liability


# --- fraud signal index -----------------------------------------------------

def fraud_signals_for(agency_id, application_id, content_hash, declared_signals):
    signals = []
    for signal in declared_signals:
        if signal not in signals:
            signals.append(signal)
    duplicate = False
    for doc in agency_documents(agency_id):
        if doc["application_id"] != application_id and doc["content_hash"] == content_hash:
            duplicate = True
            break
    if duplicate and "HASH_DUPLICATE" not in signals:
        signals.append("HASH_DUPLICATE")
    index = min(100, sum(SIGNAL_WEIGHT[s] for s in signals))
    return signals, index


# --- risk scoring -----------------------------------------------------------

def decay_factor(age_days):
    if age_days <= 90:
        return Decimal("1.00")
    if age_days <= 180:
        return Decimal("0.75")
    return Decimal("0.50")


def risk_scores(agency_id):
    """calculations.agency_integrity_risk_score, both variants."""
    docs = agency_documents(agency_id)
    reviewed = sum(1 for d in docs if d["verification_state"] in REVIEWED_STATES)
    confirmed_fraud = sum(1 for d in docs if d["verification_state"] == "CONFIRMED_FRAUD")
    if reviewed == 0:
        fraud_rate = Decimal(0)
    else:
        fraud_rate = Decimal(confirmed_fraud) / Decimal(reviewed)

    current = today()
    rolling_sum = Decimal(0)
    lifetime_sum = Decimal(0)
    confirmed_count = 0
    for incident in agency_incidents(agency_id):
        if incident["status"] != "CONFIRMED":
            continue
        confirmed_count += 1
        weight = Decimal(SEVERITY_WEIGHT[incident["severity"]])
        lifetime_sum += weight
        occurred = parse_date(incident["occurred_on"])
        if occurred is None:
            continue
        age_days = (current - occurred).days
        if age_days <= ROLLING_WINDOW_DAYS:
            rolling_sum += weight * decay_factor(age_days)

    quality_term = FRAUD_RATE_WEIGHT * fraud_rate
    rolling = min(Decimal("100.00"), rhu(rolling_sum + quality_term, 2))
    lifetime = min(Decimal("100.00"), rhu(lifetime_sum + quality_term, 2))
    return {
        "rolling": rolling,
        "lifetime": lifetime,
        "confirmed_incident_count": confirmed_count,
        "reviewed_document_count": reviewed,
        "confirmed_fraud_document_count": confirmed_fraud,
    }


def posture_band(rolling):
    if rolling >= BAND_SUSPENDED:
        return "SUSPENDED"
    if rolling >= BAND_PROBATION:
        return "PROBATION"
    if rolling >= BAND_WATCH:
        return "WATCH"
    return "GOOD_STANDING"


def risk_target_posture(rolling):
    """None means 'leave the standing as it is'."""
    if rolling >= BAND_SUSPENDED:
        return "SUSPENDED"
    if rolling >= BAND_PROBATION:
        return "PROBATION"
    if rolling >= BAND_WATCH:
        return "WATCH"
    return None


# --- territory geometry -----------------------------------------------------

def _interval(assignment):
    return parse_date(assignment["start_date"]), parse_date(assignment["end_date"])


def cooloff_end(assignment):
    end = parse_date(assignment["end_date"])
    if assignment["exclusivity"] == "EXCLUSIVE":
        return end + timedelta(days=EXCLUSIVE_COOLOFF_DAYS)
    return end


def country_active_assignments(country_code):
    return [t for t in db.assignments.values()
            if t["country_code"] == country_code and t["status"] == "ACTIVE"]


def occupies(assignment, instant):
    start, end = _interval(assignment)
    return assignment["status"] == "ACTIVE" and start <= instant < end


def occupancy_snapshot(country_code, at_date):
    """calculations.territory_exclusive_occupancy."""
    actives = country_active_assignments(country_code)
    exclusive_active = sum(1 for a in actives
                           if a["exclusivity"] == "EXCLUSIVE" and occupies(a, at_date))
    non_exclusive_active = sum(1 for a in actives
                               if a["exclusivity"] == "NON_EXCLUSIVE" and occupies(a, at_date))
    cooloffs = [cooloff_end(a) for a in actives if a["exclusivity"] == "EXCLUSIVE"]
    cooloff_until = max(cooloffs) if cooloffs else None
    available = (exclusive_active == 0 and non_exclusive_active == 0
                 and (cooloff_until is None or at_date >= cooloff_until))
    return {
        "exclusive_active_count": exclusive_active,
        "non_exclusive_active_count": non_exclusive_active,
        "exclusive_cooloff_until": cooloff_until,
        "exclusive_slot_available": available,
    }


def intervals_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


# --- performance scorecard --------------------------------------------------

def scorecard_figures(agency_id, period_start, period_end):
    """calculations.performance_scorecard_composite."""
    cohort = []
    for app in agency_applications(agency_id):
        submitted = parse_date(app["submitted_on"]) if app.get("submitted_on") else None
        if submitted is None:
            continue
        if period_start <= submitted <= period_end:
            cohort.append(app)

    submitted_count = len(cohort)
    enrolled_count = sum(1 for a in cohort if a.get("enrolled_on"))
    persisted_count = sum(1 for a in cohort if a.get("persisted_on"))

    cohort_ids = set(a["id"] for a in cohort)
    docs = [d for d in db.documents.values() if d["application_id"] in cohort_ids]
    reviewed_document_count = sum(1 for d in docs if d["verification_state"] in REVIEWED_STATES)
    flagged_document_count = sum(1 for d in docs if d["verification_state"] in FLAGGED_STATES)

    if submitted_count == 0:
        yield_rate = Decimal("0.0000")
    else:
        yield_rate = rhu(Decimal(enrolled_count) / Decimal(submitted_count), 4)
    if enrolled_count == 0:
        persistence_rate = Decimal("0.0000")
    else:
        persistence_rate = rhu(Decimal(persisted_count) / Decimal(enrolled_count), 4)
    if reviewed_document_count == 0:
        quality_index = Decimal("1.0000")
    else:
        quality_index = rhu(
            Decimal(1) - Decimal(flagged_document_count) / Decimal(reviewed_document_count), 4)

    composite = rhu(WEIGHT_YIELD * yield_rate
                    + WEIGHT_PERSISTENCE * persistence_rate
                    + WEIGHT_QUALITY * quality_index, 4)

    if submitted_count == 0:
        tier = "UNRATED"
    elif composite >= Decimal("0.8500"):
        tier = "PLATINUM"
    elif composite >= Decimal("0.7000"):
        tier = "GOLD"
    elif composite >= Decimal("0.5000"):
        tier = "STANDARD"
    else:
        tier = "WATCH"

    return {
        "submitted_count": submitted_count,
        "enrolled_count": enrolled_count,
        "persisted_count": persisted_count,
        "reviewed_document_count": reviewed_document_count,
        "flagged_document_count": flagged_document_count,
        "yield_rate": yield_rate,
        "persistence_rate": persistence_rate,
        "quality_index": quality_index,
        "composite_score": composite,
        "tier": tier,
    }
