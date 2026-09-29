"""Calculations, relationship helpers and cascade version bookkeeping.

Every derived value described in PRD section 3 is computed here on demand, so a
read always reflects the current logical clock (PRD section 2.4).
"""
import calendar
from contextlib import contextmanager
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal as D

from db import store

# ------------------------------------------------------------------ enums
ROLE_LIST = (
    "ComplianceOfficer",
    "QualifiedIndividual",
    "EntryFiler",
    "FdaInspector",
    "PlatformAdmin",
)

QI_STATUSES = ("PROPOSED", "ACTIVE", "LAPSED", "REVOKED")
SUPPLIER_STATUSES = (
    "UNEVALUATED",
    "APPROVED",
    "CONDITIONALLY_APPROVED",
    "SUSPENDED_PENDING_REVIEW",
    "DISQUALIFIED",
)
COMPLIANCE_STATUSES = (
    "NO_ADVERSE_FINDINGS",
    "WARNING_LETTER",
    "IMPORT_ALERT",
    "REGISTRATION_SUSPENDED",
)
CONSUMER_GROUPS = ("GENERAL", "ELDERLY", "IMMUNOCOMPROMISED", "INFANT")
PROCESS_CONTROL_CATEGORIES = (
    "NONE",
    "JUICE_HACCP",
    "SEAFOOD_HACCP",
    "LOW_ACID_CANNED",
    "DIETARY_SUPPLEMENT",
    "ALCOHOL_BEVERAGE",
)
VERIFICATION_STATUSES = (
    "DRAFT",
    "HAZARD_ANALYZED",
    "VERIFICATION_APPROVED",
    "REASSESSMENT_REQUIRED",
    "VERIFICATION_LAPSED",
    "RETIRED",
)
ENTRY_ELIGIBILITY_STATUSES = ("PENDING", "ELIGIBLE", "BLOCKED")
EXEMPTION_STATUSES = ("NONE", "CLAIMED", "VERIFIED", "REJECTED", "REVOKED")
EXEMPTION_TYPES = (
    "JUICE_HACCP_CONTROL",
    "SEAFOOD_HACCP_CONTROL",
    "LOW_ACID_CANNED_MICROBIO",
    "DIETARY_SUPPLEMENT_CGMP",
    "ALCOHOL_BEVERAGE",
    "RESEARCH_QUANTITY",
    "US_CUSTOMER_WRITTEN_ASSURANCE",
    "SMALL_IMPORTER_MODIFIED",
)
ANALYSIS_STATUSES = ("DRAFT", "APPROVED", "SUPERSEDED", "WITHDRAWN")
HAZARD_TYPES = ("BIOLOGICAL", "CHEMICAL_INCL_RADIOLOGICAL", "PHYSICAL")
CONTROL_OWNERS = (
    "FOREIGN_SUPPLIER",
    "SUPPLIER_OF_SUPPLIER",
    "IMPORTER",
    "CUSTOMER_DOWNSTREAM",
)
ACTIVITY_TYPES = (
    "ONSITE_AUDIT",
    "SAMPLING_AND_TESTING",
    "RECORDS_REVIEW",
    "OTHER_SUPPLIER_EVALUATION",
)
ACTIVITY_STATUSES = ("PROPOSED", "CHANGES_REQUESTED", "APPROVED", "WITHDRAWN", "RETIRED")
OUTCOMES = ("PASS", "PASS_WITH_FINDINGS", "FAIL")
RECORD_STATUSES = ("RECEIVED", "ATTESTED", "RESCINDED")
ACTION_STATUSES = (
    "OPEN",
    "SUPPLIER_REMEDIATION",
    "IMPORT_SUSPENSION",
    "CLOSED_RESOLVED",
    "CLOSED_SUPPLIER_DISQUALIFIED",
)
ACTION_TRIGGERS = (
    "PERFORMANCE_SCORE_BREACH",
    "REGULATORY_IMPORT_ALERT",
    "ADEQUACY_SHORTFALL",
)
ENTRY_STATUSES = ("SUBMITTED", "ACCEPTED", "HELD", "REJECTED")
HELD_REASONS = ("PAIR_BLOCKED", "SUPPLIER_DISQUALIFIED")
PROGRAM_STATUSES = ("COMPLIANT", "AT_RISK", "NON_COMPLIANT")

NON_CLOSED_ACTION_STATUSES = ("OPEN", "SUPPLIER_REMEDIATION", "IMPORT_SUSPENSION")
LIVE_ACTIVITY_STATUSES = ("PROPOSED", "CHANGES_REQUESTED", "APPROVED")

# ------------------------------------------------------------- constants
EXPOSURE_MULTIPLIER = {
    "GENERAL": D("1.0"),
    "ELDERLY": D("1.1"),
    "IMMUNOCOMPROMISED": D("1.25"),
    "INFANT": D("1.4"),
}
CONTROL_FACTOR = {
    "FOREIGN_SUPPLIER": D("1.00"),
    "SUPPLIER_OF_SUPPLIER": D("1.10"),
    "IMPORTER": D("0.70"),
    "CUSTOMER_DOWNSTREAM": D("0.55"),
}
RAC_RELIEF = D("0.85")
RTE_PENALTY = D("1.15")
SIGNIFICANT_HAZARD_THRESHOLD = D("12.00")
HAZARD_FLOOR = D("1.00")
HAZARD_CAP = D("25.00")

SUPPLIER_PENALTY = {
    "NO_ADVERSE_FINDINGS": D("0.00"),
    "WARNING_LETTER": D("6.00"),
    "IMPORT_ALERT": D("15.00"),
    "REGISTRATION_SUSPENDED": D("25.00"),
}
TIER_RELIEF = {"LOW": D("0.00"), "MODERATE": D("4.00"), "HIGH": D("9.00")}
TIER_FREQUENCY = {"LOW": 1, "MODERATE": 2, "HIGH": 4}
COVERAGE_MULTIPLIER = D("1.5")

ACTIVITY_TYPE_WEIGHT = {
    "ONSITE_AUDIT": D("10.0"),
    "SAMPLING_AND_TESTING": D("6.0"),
    "RECORDS_REVIEW": D("3.0"),
    "OTHER_SUPPLIER_EVALUATION": D("2.0"),
}
FREQUENCY_CAP = 4
SHORT_JUSTIFICATION_CHARS = 40
SHORT_JUSTIFICATION_FACTOR = D("0.5")
DENOMINATOR_FLOOR = D("1.00")
ADEQUACY_FLOOR_STANDARD = D("60.00")
ADEQUACY_FLOOR_MODIFIED = D("30.00")

RECORD_TYPE_WEIGHT = {
    "ONSITE_AUDIT": D("3.0"),
    "SAMPLING_AND_TESTING": D("2.0"),
    "RECORDS_REVIEW": D("1.0"),
    "OTHER_SUPPLIER_EVALUATION": D("0.5"),
}
OUTCOME_POINTS = {"PASS": D("100"), "PASS_WITH_FINDINGS": D("75"), "FAIL": D("20")}
FINDINGS_PENALTY_PER = D("5")
FINDINGS_PENALTY_CAP = D("20")
SUSPENSION_THRESHOLD = D("60.00")
RECENCY_FULL_DAYS = 365
RECENCY_HALF_DAYS = 730

REASSESSMENT_CYCLE_MONTHS = 36
TRAINING_VALIDITY_MONTHS = 36
AUDIT_COOL_OFF_DAYS = 30

EXEMPTION_APPLICABILITY = {
    "JUICE_HACCP_CONTROL": ("JUICE_HACCP",),
    "SEAFOOD_HACCP_CONTROL": ("SEAFOOD_HACCP",),
    "LOW_ACID_CANNED_MICROBIO": ("LOW_ACID_CANNED",),
    "DIETARY_SUPPLEMENT_CGMP": ("DIETARY_SUPPLEMENT",),
    "ALCOHOL_BEVERAGE": ("ALCOHOL_BEVERAGE",),
    "RESEARCH_QUANTITY": ("NONE",),
    "US_CUSTOMER_WRITTEN_ASSURANCE": None,
    "SMALL_IMPORTER_MODIFIED": None,
}
MODIFIED_REQUIREMENT_TYPES = ("US_CUSTOMER_WRITTEN_ASSURANCE", "SMALL_IMPORTER_MODIFIED")


# ------------------------------------------------------------- primitives
def q2(value):
    return D(value).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def fnum(value):
    return float(str(value))


def clock():
    return store.clock


def add_months(dt, months):
    """Calendar-month arithmetic, clamping to the last day of the target month."""
    if dt is None:
        return None
    total = (dt.year * 12 + (dt.month - 1)) + months
    year = total // 12
    month = total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def sort_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ------------------------------------------------------------- relations
def pairs_of_supplier(supplier_id):
    return [p for p in store.pairs.values() if p["supplier_id"] == supplier_id]


def pairs_of_importer(importer_id):
    return [p for p in store.pairs.values() if p["importer_id"] == importer_id]


def qis_of_importer(importer_id):
    return [q for q in store.qis.values() if q["importer_id"] == importer_id]


def suppliers_of_importer(importer_id):
    return [s for s in store.suppliers.values() if s["importer_id"] == importer_id]


def analyses_of_pair(pair_id):
    return [a for a in store.analyses.values() if a["pair_id"] == pair_id]


def hazards_of_analysis(analysis_id):
    return [h for h in store.hazards.values() if h["hazard_analysis_id"] == analysis_id]


def activities_of_pair(pair_id):
    return [a for a in store.activities.values() if a["pair_id"] == pair_id]


def records_of_activity(activity_id):
    return [r for r in store.records.values() if r["activity_id"] == activity_id]


def entries_of_pair(pair_id):
    return [e for e in store.entries.values() if e["pair_id"] == pair_id]


def actions_of_supplier(supplier_id):
    return [a for a in store.actions.values() if a["supplier_id"] == supplier_id]


def records_of_pair(pair_id):
    out = []
    for activity in activities_of_pair(pair_id):
        out.extend(records_of_activity(activity["id"]))
    return out


def records_of_supplier(supplier_id):
    out = []
    for pair in pairs_of_supplier(supplier_id):
        out.extend(records_of_pair(pair["id"]))
    return out


def records_of_importer(importer_id):
    out = []
    for pair in pairs_of_importer(importer_id):
        out.extend(records_of_pair(pair["id"]))
    return out


def actions_of_importer(importer_id):
    supplier_ids = set(s["id"] for s in suppliers_of_importer(importer_id))
    return [a for a in store.actions.values() if a["supplier_id"] in supplier_ids]


def pair_of_activity(activity):
    return store.pairs.get(activity["pair_id"])


def activity_of_record(record):
    return store.activities.get(record["activity_id"])


def pair_of_record(record):
    activity = activity_of_record(record)
    return store.pairs.get(activity["pair_id"]) if activity else None


def supplier_of_pair(pair):
    return store.suppliers.get(pair["supplier_id"])


def importer_of_pair(pair):
    return store.importers.get(pair["importer_id"])


def food_of_pair(pair):
    return store.foods.get(pair["food_id"])


# ---------------------------------------------- QualifiedIndividual derived
def qi_training_valid_until(qi):
    return add_months(qi["training_completed_at"], TRAINING_VALIDITY_MONTHS)


def qi_active_assignment_count(qi):
    return len(
        [
            a
            for a in store.activities.values()
            if a["assigned_qi_id"] == qi["id"] and a["status"] in LIVE_ACTIVITY_STATUSES
        ]
    )


def qi_is_current(qi):
    if qi is None:
        return False
    if qi["status"] != "ACTIVE":
        return False
    return qi_training_valid_until(qi) >= clock()


# ------------------------------------------------------------ Hazard derived
def compute_hazard_risk(food, hazard_type, severity, probability, control_owner):
    raw = D(severity) * D(probability) * EXPOSURE_MULTIPLIER[food["intended_consumer_group"]]
    if food["is_raw_agricultural_commodity"] and hazard_type != "BIOLOGICAL":
        raw = raw * RAC_RELIEF
    else:
        raw = raw * D("1.00")
    if food["ready_to_eat"] and hazard_type == "BIOLOGICAL":
        raw = raw * RTE_PENALTY
    else:
        raw = raw * D("1.00")
    raw = raw * CONTROL_FACTOR[control_owner]
    clamped = min(HAZARD_CAP, max(HAZARD_FLOOR, raw))
    risk_score = q2(clamped)
    return risk_score, risk_score >= SIGNIFICANT_HAZARD_THRESHOLD


# ---------------------------------------------------- HazardAnalysis derived
def analysis_hazards(analysis):
    return hazards_of_analysis(analysis["id"])


def analysis_hazard_count(analysis):
    return len(analysis_hazards(analysis))


def analysis_significant_hazard_count(analysis):
    return len([h for h in analysis_hazards(analysis) if h["requires_control"]])


def analysis_risk_total(analysis):
    total = D("0.00")
    for hazard in analysis_hazards(analysis):
        total = total + hazard["risk_score"]
    return q2(total)


# ------------------------------------------------- VerificationRecord derived
def record_points(record):
    penalty = min(FINDINGS_PENALTY_CAP, FINDINGS_PENALTY_PER * D(record["findings_count"]))
    return q2(max(D("0"), OUTCOME_POINTS[record["outcome"]] - penalty))


def record_recency_factor(record, as_of=None):
    moment = as_of or clock()
    delta = moment - record["performed_end"]
    if delta <= timedelta(days=RECENCY_FULL_DAYS):
        return D("1.0")
    if delta <= timedelta(days=RECENCY_HALF_DAYS):
        return D("0.5")
    return D("0.0")


def record_weight(record, as_of=None):
    activity = activity_of_record(record)
    if activity is None:
        return D("0.00")
    base = RECORD_TYPE_WEIGHT[activity["activity_type"]]
    return q2(base * record_recency_factor(record, as_of))


def record_retained_until(record):
    pair = pair_of_record(record)
    importer = store.importers.get(pair["importer_id"]) if pair else None
    months = importer["record_retention_months"] if importer else 24
    return add_months(record["performed_end"], months)


def record_available(record, as_of=None):
    moment = as_of or clock()
    if record["record_status"] == "RESCINDED":
        return False
    return moment <= record_retained_until(record)


# ------------------------------------------------- ForeignSupplier derived
def _performance(records):
    weight_total = D("0.00")
    weighted_sum = D("0.00")
    for record in records:
        weight = record_weight(record)
        weight_total = weight_total + weight
        weighted_sum = weighted_sum + (record_points(record) * weight)
    weight_total = q2(weight_total)
    weighted_sum = q2(weighted_sum)
    if weight_total == D("0.00"):
        return D("100.00"), weight_total
    return q2(weighted_sum / weight_total), weight_total


def supplier_performance_provisional(supplier):
    records = [
        r
        for r in records_of_supplier(supplier["id"])
        if r["record_status"] in ("RECEIVED", "ATTESTED")
    ]
    score, _ = _performance(records)
    return score


def supplier_performance_final(supplier):
    records = [r for r in records_of_supplier(supplier["id"]) if r["record_status"] == "ATTESTED"]
    return _performance(records)


def supplier_open_corrective_action_count(supplier):
    return len(
        [
            a
            for a in actions_of_supplier(supplier["id"])
            if a["status"] in NON_CLOSED_ACTION_STATUSES
        ]
    )


def supplier_has_import_suspension(supplier_id):
    return any(a["status"] == "IMPORT_SUSPENSION" for a in actions_of_supplier(supplier_id))


# ------------------------------------------------ SupplierFoodPair derived
def pair_modified_requirements_only(pair):
    return bool(
        pair["exemption_status"] == "VERIFIED"
        and pair.get("exemption_type") in MODIFIED_REQUIREMENT_TYPES
    )


def pair_adequacy_floor(pair):
    return ADEQUACY_FLOOR_MODIFIED if pair_modified_requirements_only(pair) else ADEQUACY_FLOOR_STANDARD


def pair_active_hazards(pair):
    analysis_id = pair.get("active_hazard_analysis_id")
    if not analysis_id:
        return []
    return hazards_of_analysis(analysis_id)


def pair_uncontrolled_significant_hazard_count(pair):
    return len(
        [
            h
            for h in pair_active_hazards(pair)
            if h["requires_control"]
            and h["control_owner"] in ("FOREIGN_SUPPLIER", "SUPPLIER_OF_SUPPLIER")
        ]
    )


def pair_risk(pair):
    """calculations.pair_composite_hazard_risk — five pinned steps."""
    # STEP 1
    hazard_load = D("0.00")
    for hazard in pair_active_hazards(pair):
        if hazard["requires_control"]:
            hazard_load = hazard_load + hazard["risk_score"]
    hazard_load = q2(hazard_load)
    supplier = supplier_of_pair(pair)
    penalty = SUPPLIER_PENALTY[supplier["regulatory_compliance_status"]] if supplier else D("0.00")
    gross = q2(hazard_load + penalty)
    # STEP 2 — tier from GROSS only
    if gross >= D("40.00"):
        tier = "HIGH"
    elif gross >= D("18.00"):
        tier = "MODERATE"
    else:
        tier = "LOW"
    # STEP 3
    final_score = supplier_performance_final(supplier)[0] if supplier else D("100.00")
    if final_score >= D("85.00"):
        relief_factor = D("1.0")
    elif final_score >= D("70.00"):
        relief_factor = D("0.5")
    else:
        relief_factor = D("0.0")
    relief = q2(TIER_RELIEF[tier] * relief_factor)
    # STEP 4
    composite = q2(max(D("0.00"), gross - relief))
    # STEP 5 — read off the tier fixed in STEP 2
    return {
        "hazard_load": hazard_load,
        "gross": gross,
        "risk_tier": tier,
        "relief": relief,
        "composite_hazard_risk": composite,
        "required_annual_frequency": TIER_FREQUENCY[tier],
        "required_coverage": q2(composite * COVERAGE_MULTIPLIER),
    }


def activity_coverage_weight(activity):
    factor = (
        D("1.0")
        if len(activity["justification_text"]) >= SHORT_JUSTIFICATION_CHARS
        else SHORT_JUSTIFICATION_FACTOR
    )
    capped = min(activity["frequency_per_year"], FREQUENCY_CAP)
    return q2(ACTIVITY_TYPE_WEIGHT[activity["activity_type"]] * D(capped) * factor)


def _adequacy(pair, activities):
    raw = D("0.00")
    for activity in activities:
        raw = raw + activity_coverage_weight(activity)
    denominator = max(pair_risk(pair)["required_coverage"], DENOMINATOR_FLOOR)
    quotient = D("100.00") * raw / denominator
    return q2(min(D("100.00"), quotient))


def pair_adequacy_planned(pair):
    approved = [a for a in activities_of_pair(pair["id"]) if a["status"] == "APPROVED"]
    return _adequacy(pair, approved)


def pair_adequacy_realized(pair):
    inputs = []
    for activity in activities_of_pair(pair["id"]):
        if activity["status"] != "APPROVED":
            continue
        if any(r["record_status"] == "ATTESTED" for r in records_of_activity(activity["id"])):
            inputs.append(activity)
    return _adequacy(pair, inputs)


def pair_reassessment_due_at(pair):
    if pair.get("last_reassessed_at") is None:
        return None
    return add_months(pair["last_reassessed_at"], REASSESSMENT_CYCLE_MONTHS)


def pair_hazard_analysis_count(pair):
    return len(analyses_of_pair(pair["id"]))


def pair_approved_frequency_sum(pair):
    return sum(
        a["frequency_per_year"] for a in activities_of_pair(pair["id"]) if a["status"] == "APPROVED"
    )


# ------------------------------------------------------- Importer derived
def importer_blocked_pair_count(importer):
    return len(
        [p for p in pairs_of_importer(importer["id"]) if p["entry_eligibility_status"] == "BLOCKED"]
    )


def importer_open_corrective_action_count(importer):
    return len(
        [
            a
            for a in actions_of_importer(importer["id"])
            if a["status"] in NON_CLOSED_ACTION_STATUSES
        ]
    )


def importer_qi_designated(importer):
    for qi in qis_of_importer(importer["id"]):
        if qi["status"] == "ACTIVE" and qi_training_valid_until(qi) >= clock():
            return True
    return False


def importer_program_status(importer):
    blocked = importer_blocked_pair_count(importer)
    designated = importer_qi_designated(importer)
    pairs = pairs_of_importer(importer["id"])
    if blocked > 0 or not designated:
        return "NON_COMPLIANT"
    if any(p["verification_status"] == "VERIFICATION_LAPSED" for p in pairs):
        return "NON_COMPLIANT"
    if importer_open_corrective_action_count(importer) > 0:
        return "AT_RISK"
    if any(p["verification_status"] == "REASSESSMENT_REQUIRED" for p in pairs):
        return "AT_RISK"
    now = clock()
    for pair in pairs:
        due = pair_reassessment_due_at(pair)
        if due is not None and due < now:
            return "AT_RISK"
    return "COMPLIANT"


def importer_rollup(importer):
    return {
        "blocked_pair_count": importer_blocked_pair_count(importer),
        "open_corrective_action_count": importer_open_corrective_action_count(importer),
        "qualified_individual_designated": importer_qi_designated(importer),
        "program_status": importer_program_status(importer),
    }


# -------------------------------------------- cascade version bookkeeping
def _computed_state():
    """Snapshot of every derived value that a cascade can move.

    PRD section 2.7: when a write changes a value another row depends on, that
    dependent row is updated in the same request and its updated_at / version
    move accordingly.
    """
    state = {}
    for importer in store.importers.values():
        state[("importer", importer["id"])] = importer_rollup(importer)
    for qi in store.qis.values():
        state[("qi", qi["id"])] = {
            "training_valid_until": qi_training_valid_until(qi),
            "active_assignment_count": qi_active_assignment_count(qi),
        }
    for supplier in store.suppliers.values():
        final, weight_total = supplier_performance_final(supplier)
        state[("supplier", supplier["id"])] = {
            "provisional": supplier_performance_provisional(supplier),
            "final": final,
            "weight_total": weight_total,
            "open_corrective_action_count": supplier_open_corrective_action_count(supplier),
        }
    for pair in store.pairs.values():
        risk = pair_risk(pair)
        state[("pair", pair["id"])] = {
            "risk": risk,
            "modified_requirements_only": pair_modified_requirements_only(pair),
            "hazard_analysis_count": pair_hazard_analysis_count(pair),
            "uncontrolled": pair_uncontrolled_significant_hazard_count(pair),
            "planned": pair_adequacy_planned(pair),
            "realized": pair_adequacy_realized(pair),
            "reassessment_due_at": pair_reassessment_due_at(pair),
        }
    for analysis in store.analyses.values():
        state[("analysis", analysis["id"])] = {
            "hazard_count": analysis_hazard_count(analysis),
            "significant_hazard_count": analysis_significant_hazard_count(analysis),
            "risk_total": analysis_risk_total(analysis),
        }
    for activity in store.activities.values():
        state[("activity", activity["id"])] = {
            "coverage_weight": activity_coverage_weight(activity)
        }
    for record in store.records.values():
        state[("record", record["id"])] = {
            "weight": record_weight(record),
            "record_points": record_points(record),
            "retained_until": record_retained_until(record),
        }
    return state


def _settle(before):
    after = _computed_state()
    for key, value in after.items():
        if key in store.touched:
            continue
        if key not in before:
            continue
        if before[key] != value:
            kind, row_id = key
            row = store.collection(kind).get(row_id)
            if row is not None:
                store.touch(row)


@contextmanager
def write_txn():
    """Wrap the mutating phase of a write so derived-roll-up owners get bumped."""
    before = _computed_state()
    store.touched = set()
    yield
    _settle(before)
