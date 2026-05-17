"""Pure calculation algorithms.

These functions never mutate state. They are called from route handlers and
mutation services to derive computed fields and projected next-due dates.

Three calculations are implemented here:

1. cdc_catchup_eligibility_decision — dual variant (routine vs catch-up).
2. school_coverage_evaluation — set arithmetic over required vs covered antigens.
3. provider_reporting_compliance_score — rolling 365-day weighted score with
   round-per-dose-then-round-the-average semantics (round-half-up to 2 dp).
4. vaers_reportable_determination — boundary at 24.0 hours (inclusive).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Optional

from .. import store
from ..clock import parse_iso, now


# -----------------------------------------------------------------------------
# Rounding helpers
# -----------------------------------------------------------------------------
_TWO_DP = Decimal("0.01")


def round_half_up_2dp(value) -> Decimal:
    """Round to two decimal places using ROUND_HALF_UP via Decimal.

    The caller may pass a float, int, str, or Decimal — we route through
    a string conversion of the float to avoid the IEEE-754 surprise where
    e.g. 0.555 stored as 0.55499999... would round down with HALF_UP.
    """
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, (int,)):
        d = Decimal(value)
    elif isinstance(value, float):
        # Convert via repr to preserve the human-intended decimal value.
        d = Decimal(repr(value))
    else:
        d = Decimal(str(value))
    return d.quantize(_TWO_DP, rounding=ROUND_HALF_UP)


# -----------------------------------------------------------------------------
# Age in days
# -----------------------------------------------------------------------------
def patient_age_days(date_of_birth: str, at_instant: datetime) -> int:
    """Floor of the calendar-day difference between at_instant.date() and date_of_birth.

    No time-of-day arithmetic enters the comparison — per PRD §2.8.
    """
    dob = date.fromisoformat(date_of_birth)
    at_date = at_instant.astimezone(timezone.utc).date()
    return (at_date - dob).days


# -----------------------------------------------------------------------------
# CDC catch-up eligibility
# -----------------------------------------------------------------------------
def _prior_administered_doses_for_antigen(patient_id: str, antigen: str) -> list[dict]:
    """Return ADMINISTERED doses for the patient whose product covers the antigen,
    ordered ascending by administered_at, with id as tie-break."""
    relevant = []
    for dose in store.administered_doses.values():
        if dose.get("patient_id") != patient_id:
            continue
        if dose.get("dose_state") != "ADMINISTERED":
            continue
        product = store.vaccine_products.get(dose.get("vaccine_product_id"))
        if not product:
            continue
        if antigen in (product.get("antigens") or []):
            relevant.append(dose)
    relevant.sort(key=lambda d: (d["administered_at"], d["id"]))
    return relevant


def _rule_for_antigen_sequence(antigen: str, seq: int) -> Optional[dict]:
    for rule in store.antigen_schedule_rules.values():
        if rule.get("antigen") == antigen and rule.get("dose_sequence_number") == seq:
            return rule
    return None


def project_next_due(patient: dict, antigen: str) -> Optional[dict]:
    """Project the next-due date for the given antigen series for this patient.

    Returns None if there is no schedule rule for the next slot. Otherwise
    returns {antigen, next_due_date, variant, dose_sequence_number,
    school_enrollment_required}.
    """
    prior = _prior_administered_doses_for_antigen(patient["id"], antigen)
    next_seq = len(prior) + 1
    rule = _rule_for_antigen_sequence(antigen, next_seq)
    if rule is None:
        return None

    dob = date.fromisoformat(patient["date_of_birth"])
    current_age_days = (now().astimezone(timezone.utc).date() - dob).days

    # Determine variant: catch-up if current age exceeds this rule's routine_max,
    # OR if any prior dose was administered after its own rule's routine_max.
    prev_admin_late = False
    for d in prior:
        ds_admin_at = parse_iso(d["administered_at"]).astimezone(timezone.utc).date()
        age_at_prior = (ds_admin_at - dob).days
        prior_rule = _rule_for_antigen_sequence(antigen, prior.index(d) + 1)
        if prior_rule is not None and age_at_prior > prior_rule["routine_max_age_days"]:
            prev_admin_late = True
            break

    use_catchup = current_age_days > rule["routine_max_age_days"] or prev_admin_late

    if not use_catchup:
        next_due_date = dob + timedelta(days=rule["routine_recommended_age_days"])
        return {
            "antigen": antigen,
            "next_due_date": next_due_date.isoformat(),
            "variant": "routine",
            "dose_sequence_number": next_seq,
            "school_enrollment_required": bool(rule.get("school_enrollment_required", False)),
        }

    # Catch-up: max of (dob + routine_min) and (last_admin + catchup_min_interval)
    candidate_min = dob + timedelta(days=rule["routine_min_age_days"])
    if prior:
        last_admin_dt = parse_iso(prior[-1]["administered_at"]).astimezone(timezone.utc).date()
        candidate_interval = last_admin_dt + timedelta(days=rule["catchup_min_interval_days"])
    else:
        candidate_interval = candidate_min
    next_due_date = max(candidate_min, candidate_interval)
    return {
        "antigen": antigen,
        "next_due_date": next_due_date.isoformat(),
        "variant": "catchup",
        "dose_sequence_number": next_seq,
        "school_enrollment_required": bool(rule.get("school_enrollment_required", False)),
    }


def compute_catchup_flag_for_dose(patient: dict, dose: dict) -> bool:
    """Compute whether an AdministeredDose is the 'catch-up' variant.

    Used at administer time: the dose's catchup_flag is true iff the variant
    selected for its position in the series is the catch-up variant.

    "Prior" doses here are doses that were ADMINISTERED before this one (by
    administered_at), excluding the current dose itself.
    """
    product = store.vaccine_products.get(dose["vaccine_product_id"])
    if not product:
        return False
    dob = date.fromisoformat(patient["date_of_birth"])
    new_admin_date = parse_iso(dose["administered_at"]).astimezone(timezone.utc).date()
    age_at_admin = (new_admin_date - dob).days
    # For each antigen the product covers, look at how this dose slots into the series.
    flag = False
    for antigen in product.get("antigens", []):
        # Prior ADMINISTERED doses in this antigen series whose administered_at is
        # strictly earlier than ours, ordered.
        prior = []
        for other in store.administered_doses.values():
            if other["id"] == dose["id"]:
                continue
            if other.get("patient_id") != patient["id"]:
                continue
            if other.get("dose_state") != "ADMINISTERED":
                continue
            other_product = store.vaccine_products.get(other.get("vaccine_product_id"))
            if not other_product or antigen not in (other_product.get("antigens") or []):
                continue
            if other["administered_at"] < dose["administered_at"]:
                prior.append(other)
        prior.sort(key=lambda d: (d["administered_at"], d["id"]))
        seq = len(prior) + 1
        rule = _rule_for_antigen_sequence(antigen, seq)
        if rule is None:
            continue
        # was any prior dose administered after its own rule's routine_max?
        prev_admin_late = False
        for idx, p in enumerate(prior, start=1):
            p_date = parse_iso(p["administered_at"]).astimezone(timezone.utc).date()
            age_then = (p_date - dob).days
            p_rule = _rule_for_antigen_sequence(antigen, idx)
            if p_rule is not None and age_then > p_rule["routine_max_age_days"]:
                prev_admin_late = True
                break
        if age_at_admin > rule["routine_max_age_days"] or prev_admin_late:
            flag = True
            break
    return flag


# -----------------------------------------------------------------------------
# School coverage evaluation
# -----------------------------------------------------------------------------
def evaluate_school_coverage(patient: dict) -> tuple[str, list[str]]:
    """Return (certificate_status, missing_antigens) per the school coverage rule.

    Precedence: medical_exemption_on_file=True wins -> EXEMPTION_GRANTED.
    Otherwise, if missing == empty -> ISSUED, else -> DEFICIENT.
    """
    required = set()
    for rule in store.antigen_schedule_rules.values():
        if rule.get("school_enrollment_required"):
            required.add(rule["antigen"])

    covered = set()
    for dose in store.administered_doses.values():
        if dose.get("patient_id") != patient["id"]:
            continue
        if dose.get("dose_state") != "ADMINISTERED":
            continue
        product = store.vaccine_products.get(dose.get("vaccine_product_id"))
        if not product:
            continue
        for ag in product.get("antigens", []):
            if ag in required:
                covered.add(ag)

    missing = sorted(required - covered)

    if patient.get("medical_exemption_on_file"):
        return "EXEMPTION_GRANTED", []
    if not missing:
        return "ISSUED", []
    return "DEFICIENT", missing


# -----------------------------------------------------------------------------
# Provider reporting compliance score
# -----------------------------------------------------------------------------
def _per_dose_score_raw(lag_hours: float) -> float:
    if lag_hours <= 24:
        return 100.0
    if lag_hours <= 72:
        return 100.0 - (lag_hours - 24.0) * 1.25
    if lag_hours <= 168:
        return 40.0
    return 0.0


def compute_provider_compliance_score(provider_org_id: str) -> Decimal:
    """Recompute reporting_compliance_score for a provider.

    Window: doses with reported_at in (now - 365d, now].
    Doses currently in dose_state == ADMINISTERED only — INVALIDATED rows
    are dropped from the window. SCHEDULED rows have no reported_at yet and
    are excluded.

    Rounding (pinned, non-commutative): each per-dose score is rounded to
    2dp ROUND_HALF_UP first, the rounded values are summed and divided by
    the count, and that average is rounded once more to 2dp ROUND_HALF_UP.
    """
    cur = now()
    window_start = cur - timedelta(days=365)

    doses_in_window: list[dict] = []
    for dose in store.administered_doses.values():
        if dose.get("provider_organization_id") != provider_org_id:
            continue
        if dose.get("dose_state") != "ADMINISTERED":
            continue
        if not dose.get("reported_at") or not dose.get("administered_at"):
            continue
        try:
            rep_at = parse_iso(dose["reported_at"])
        except Exception:
            continue
        if rep_at <= window_start or rep_at > cur:
            continue
        doses_in_window.append(dose)

    if not doses_in_window:
        return Decimal("100.00")

    doses_in_window.sort(key=lambda d: (d["administered_at"], d["id"]))

    per_dose_rounded: list[Decimal] = []
    for d in doses_in_window:
        rep_at = parse_iso(d["reported_at"])
        adm_at = parse_iso(d["administered_at"])
        # PRD §3.6: lag is the wall-clock duration between reported_at
        # and administered_at. In the schedule->administer workflow
        # reported_at is stamped at schedule time, which is at or
        # before administered_at, so the magnitude administered_at -
        # reported_at is the "how late was the report" interval.
        lag_seconds = abs((adm_at - rep_at).total_seconds())
        lag_hours = lag_seconds / 3600.0
        raw = _per_dose_score_raw(lag_hours)
        per_dose_rounded.append(round_half_up_2dp(raw))

    total = sum(per_dose_rounded, Decimal("0"))
    avg = total / Decimal(len(per_dose_rounded))
    return round_half_up_2dp(avg)


# -----------------------------------------------------------------------------
# VAERS reportability determination
# -----------------------------------------------------------------------------
def compute_vaers_required(seriousness: str, onset_at: datetime, dose_administered_at: datetime) -> bool:
    if seriousness in ("SERIOUS", "DEATH"):
        return True
    lag_seconds = (onset_at - dose_administered_at).total_seconds()
    lag_hours = lag_seconds / 3600.0
    return lag_hours <= 24.0
