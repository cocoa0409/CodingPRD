"""Pinned calculation rules (PRD section 3, scaffold section 1.3).

Every derived number in the platform is produced here, in the order the PRD
pins.  Decimal arithmetic with ROUND_HALF_UP is used wherever a rate is
rounded; no float ever participates in a rounding decision.
"""

import math
from decimal import Decimal, ROUND_HALF_UP, localcontext
from fractions import Fraction

import constants as C
import store

TWOPLACES = Decimal("0.01")


def round2(numerator, denominator):
    """round(numerator / denominator, 2) with ROUND_HALF_UP, exact rationals."""
    with localcontext() as ctx:
        ctx.prec = 60
        value = Decimal(numerator) / Decimal(denominator)
        return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def round2_decimal(value):
    with localcontext() as ctx:
        ctx.prec = 60
        return Decimal(value).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def as_float(dec):
    return float(dec) if dec is not None else None


# ---------------------------------------------------------------------------
# filing_profile_resolution -- PRD 3.1, six pinned steps
# ---------------------------------------------------------------------------

def filing_profile_resolution(inst):
    closed_end = inst["prior_year_closed_end_originations"]
    open_end = inst["prior_year_open_end_originations"]
    volume_exempt = (closed_end < C.CLOSED_END_EXEMPT_THRESHOLD
                     and open_end < C.OPEN_END_EXEMPT_THRESHOLD)
    asset_exempt = inst["asset_size_usd_cents"] <= C.EXEMPT_ASSET_CAP_CENTS
    quarterly_filer = (closed_end + open_end) >= C.QUARTERLY_FILER_THRESHOLD
    partial_exemption_eligible = volume_exempt and asset_exempt and (not quarterly_filer)
    required_field_count = (C.PARTIAL_EXEMPT_FIELD_COUNT if partial_exemption_eligible
                            else C.FULL_FIELD_COUNT)
    inst["quarterly_filer"] = quarterly_filer
    inst["partial_exemption_eligible"] = partial_exemption_eligible
    inst["required_field_count"] = required_field_count
    inst["filing_deadline_at"] = filing_deadline_at(inst["activity_year"])


def filing_deadline_at(activity_year):
    from datetime import datetime, timezone
    return datetime(activity_year + 1, 3, 1, 23, 59, 59, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# application_completeness -- PRD 3.2
# ---------------------------------------------------------------------------

CORE_FIELDS = [
    "uli",
    "application_date",
    "application_channel",
    "loan_type",
    "loan_purpose",
    "occupancy_type",
    "lien_status",
    "loan_amount_cents",
    "action_taken",
    "action_taken_date",
]


def applicable_fields(app, inst):
    applicable = list(CORE_FIELDS)
    if not inst["partial_exemption_eligible"]:
        applicable.append("income_thousands")
        action = app["action_taken"]
        if action == "ORIGINATED":
            applicable.append("rate_spread")
            applicable.append("purchaser_type")
        elif action == "PURCHASED_LOAN":
            applicable.append("purchaser_type")
        elif action == "DENIED":
            applicable.append("denial_reason_codes")
    return applicable


def _present(value):
    if value is None:
        return False
    if isinstance(value, list):
        return len(value) > 0
    return True


def application_completeness(app, inst):
    """Rewrites captured_field_count, applicable_field_count, lar_status and
    exclusion_reason on the row, in the pinned order of PRD 3.2."""
    applicable = applicable_fields(app, inst)
    app["applicable_field_count"] = len(applicable)
    app["captured_field_count"] = sum(1 for name in applicable if _present(app.get(name)))

    excluded = (app["business_or_commercial_purpose"] is True
                and app["loan_purpose"] not in C.REGISTER_LOAN_PURPOSES)
    if excluded:
        app["lar_status"] = "EXCLUDED"
        app["exclusion_reason"] = "BUSINESS_PURPOSE"
    elif app["captured_field_count"] == app["applicable_field_count"]:
        app["exclusion_reason"] = "NOT_EXCLUDED"
        # EXCEPTION_FLAGGED and CLEARED belong to the edit battery; this
        # calculation never overwrites them with COMPLETE.
        if app["lar_status"] not in ("EXCEPTION_FLAGGED", "CLEARED"):
            app["lar_status"] = "COMPLETE"
    else:
        app["lar_status"] = "PENDING_FIELDS"
        app["exclusion_reason"] = "NOT_EXCLUDED"


def recompute_institution_counters(inst):
    own = [a for a in store.applications.values() if a["institution_id"] == inst["id"]]
    inst["total_application_count"] = len(own)
    inst["pending_record_count"] = sum(1 for a in own if a["lar_status"] == "PENDING_FIELDS")
    inst["reportable_record_count"] = sum(
        1 for a in own if a["lar_status"] in ("COMPLETE", "EXCEPTION_FLAGGED", "CLEARED"))
    inst["excluded_record_count"] = sum(1 for a in own if a["lar_status"] == "EXCLUDED")
    inst["cleared_record_count"] = sum(1 for a in own if a["lar_status"] == "CLEARED")
    inst["open_register_count"] = sum(1 for a in own if a["stage"] != "ARCHIVED")


# ---------------------------------------------------------------------------
# geocode_match_resolution -- PRD 3.4
# ---------------------------------------------------------------------------

def geocode_match_resolution(assignment):
    tracts = store.ordered(store.census_tracts.values())
    submitted = assignment["submitted_tract_code"]
    if submitted is not None:
        candidates = [t for t in tracts
                      if t["tract_code"] == submitted
                      and t["county_fips"] == assignment["county_fips"]
                      and t["state_code"] == assignment["state_code"]]
    else:
        candidates = [t for t in tracts
                      if t["county_fips"] == assignment["county_fips"]
                      and t["state_code"] == assignment["state_code"]]
    assignment["candidate_count"] = len(candidates)
    if len(candidates) == 1:
        assignment["status"] = "MATCHED"
        assignment["census_tract_id"] = candidates[0]["id"]
        assignment["msa_md_code"] = candidates[0]["msa_md_code"]
    elif len(candidates) == 0:
        assignment["status"] = "NOT_MATCHED"
        assignment["census_tract_id"] = None
        assignment["msa_md_code"] = None
    else:
        assignment["status"] = "AMBIGUOUS"
        assignment["census_tract_id"] = None
        assignment["msa_md_code"] = None


def current_assignment(application_id):
    for row in store.ordered(store.geocode_assignments.values()):
        if row["application_id"] == application_id and row["is_current"]:
            return row
    return None


# ---------------------------------------------------------------------------
# certification_verification_quota -- PRD 3.6
# ---------------------------------------------------------------------------

def certification_verification_quota(snapshot_record_count, quality_count, macro_count):
    quota = math.ceil(Fraction(snapshot_record_count * C.QUALITY_VERIFY_QUOTA_PCT_NUM,
                               C.QUALITY_VERIFY_QUOTA_PCT_DEN))
    return min(quota, quality_count + macro_count)


# ---------------------------------------------------------------------------
# submission_record_count -- PRD 3.7, one base set, two variants
# ---------------------------------------------------------------------------

def _base_set(inst):
    return [a for a in store.ordered(store.applications.values())
            if a["institution_id"] == inst["id"]
            and a["action_taken"] is not None
            and a["action_taken_date"] is not None
            and a["action_taken_date"].year == inst["activity_year"]]


def submission_record_count(inst, variant):
    base = _base_set(inst)
    if variant == "PROVISIONAL":
        return sum(1 for a in base if a["lar_status"] != "EXCLUDED")
    return sum(1 for a in base if a["lar_status"] == "CLEARED" and not a["is_superseded"])


def final_record_set(inst):
    base = _base_set(inst)
    return [a for a in base if a["lar_status"] == "CLEARED" and not a["is_superseded"]]


# ---------------------------------------------------------------------------
# filing_deadline_and_lateness -- PRD 3.7
# ---------------------------------------------------------------------------

def filing_lateness(filed_at, deadline_at):
    is_late = filed_at > deadline_at
    if not is_late:
        return False, 0
    seconds = (filed_at - deadline_at).total_seconds()
    late_by_days = math.ceil(Fraction(int(round(seconds * 1000000)),
                                      C.SECONDS_PER_DAY * 1000000))
    return True, late_by_days


def whole_days_between(start, end):
    """Elapsed seconds divided by 86400, rounded down (PRD 3.6)."""
    seconds = (end - start).total_seconds()
    return math.floor(seconds / C.SECONDS_PER_DAY)


# ---------------------------------------------------------------------------
# audit_sample_sizing_and_selection -- PRD 3.8
# ---------------------------------------------------------------------------

def tier_fraction(population_size):
    if population_size <= 30:
        return Fraction(10, 100)
    if population_size <= 100:
        return Fraction(30, 100)
    if population_size <= 500:
        return Fraction(15, 100)
    return Fraction(5, 100)


def audit_sample_sizing(population_size):
    base = math.ceil(population_size * tier_fraction(population_size))
    sample_size = min(max(base, C.AUDIT_MIN_SAMPLE), C.AUDIT_MAX_SAMPLE, population_size)
    return sample_size


def systematic_selection(candidates, sample_size):
    population_size = len(candidates)
    stride = max(1, population_size // sample_size)
    return [candidates[i * stride]["id"] for i in range(sample_size)]


# ---------------------------------------------------------------------------
# audit_defect_rate -- PRD 3.8, two variants
# ---------------------------------------------------------------------------

def audit_defect_rate(sample, basis):
    if basis == "FIELD_WEIGHTED":
        total_fields_reviewed = sample["sample_size"] * sample["fields_reviewed_per_record"]
        if total_fields_reviewed == 0:
            return Decimal("0.00")
        return round2(sample["defect_count"] * 100, total_fields_reviewed)
    if sample["sample_size"] == 0:
        return Decimal("0.00")
    return round2(sample["records_with_defect_count"] * 100, sample["sample_size"])


# ---------------------------------------------------------------------------
# fair_lending_disparity_index -- PRD 3.9, three pinned roundings
# ---------------------------------------------------------------------------

def fair_lending_index(control_denied, control_total, protected_denied, protected_total):
    control_rate = round2(control_denied * 100, control_total)
    protected_rate = round2(protected_denied * 100, protected_total)
    zero = Decimal("0.00")
    if control_rate == zero and protected_rate == zero:
        index = Decimal("100.00")
    elif control_rate == zero:
        index = Decimal(str(C.DISPARITY_CAP))
    else:
        with localcontext() as ctx:
            ctx.prec = 60
            index = (protected_rate / control_rate * Decimal(100)).quantize(
                TWOPLACES, rounding=ROUND_HALF_UP)
    if index >= Decimal(str(C.SEVERE_THRESHOLD)):
        flag = "SEVERE"
    elif index >= Decimal(str(C.ELEVATED_THRESHOLD)):
        flag = "ELEVATED"
    else:
        flag = "NOT_SIGNIFICANT"
    return control_rate, protected_rate, index, flag


# ---------------------------------------------------------------------------
# disclosure_redaction -- PRD 3.7
# ---------------------------------------------------------------------------

NULL_TRACT = object()


def disclosure_redaction(final_set):
    groups = {}
    for app in final_set:
        assignment = current_assignment(app["id"])
        tract_id = assignment["census_tract_id"] if assignment is not None else None
        key = tract_id if tract_id is not None else NULL_TRACT
        groups.setdefault(key, []).append(app)

    tract_suppression_count = 0
    suppressed_record_count = 0
    for key, members in groups.items():
        if key is NULL_TRACT:
            suppressed = True
        elif len(members) < C.DISCLOSURE_MIN_TRACT_LOANS:
            suppressed = True
        else:
            tract = store.census_tracts.get(key)
            suppressed = (tract is not None
                          and tract["owner_occupied_units"] < C.DISCLOSURE_MIN_OWNER_OCCUPIED)
        if suppressed:
            tract_suppression_count += 1
            suppressed_record_count += len(members)
    return {
        "tract_suppression_count": tract_suppression_count,
        "suppressed_record_count": suppressed_record_count,
        "redacted_field_count": (suppressed_record_count
                                 * C.REDACTED_FIELDS_PER_SUPPRESSED_RECORD),
    }
