"""Premium-estimate computation for a PENDING Redetermination (PRD §3.7)."""

from datetime import timezone

from core.store import STORE
from core.clock import CLOCK
from services.calculations import premium_estimate_total


def _age_at(dob_str: str, now_dt) -> int:
    """Whole-year age computed from YYYY-MM-DD at now_dt (UTC)."""
    from datetime import datetime
    try:
        dob = datetime.strptime(dob_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return 0
    now_utc = now_dt.astimezone(timezone.utc) if now_dt.tzinfo else now_dt.replace(tzinfo=timezone.utc)
    years = now_utc.year - dob.year
    # Subtract one if today is before the birthday
    if (now_utc.month, now_utc.day) < (dob.month, dob.day):
        years -= 1
    return max(0, years)


def premium_estimate_for_pending(redet: dict):
    """Return a 2-decimal float premium for a PENDING redetermination.

    For each non-EXCLUDED applicant in the enrollment's household:
      age_factor = 1.0 if age<18 else 1.0 + (min(age,64) - 18) * 0.02
      share_factor = max(0, (new_snapshot_fpl_percent - 100) / 100)
      per_member = round2(age_factor * share_factor * 30.00)
    total = sum(per_member) then round2 (no-op).

    new_snapshot_fpl_percent is unknown until SUBMIT; for PENDING the
    redetermination has no new_snapshot_fpl_percent so the estimate
    cannot be computed deterministically. Per PRD §3.7 the estimate is
    "what the household would pay if reduced cost-sharing applies after
    renewal" — we use the household's CURRENT fpl_percent as the
    forward-looking projection (the only available snapshot).
    """
    enrollment = STORE.enrollments.get(redet["enrollment_id"])
    if enrollment is None:
        return 0.0
    applicant = STORE.applicants.get(enrollment["applicant_id"])
    if applicant is None:
        return 0.0
    household = STORE.households.get(applicant["household_id"])
    if household is None:
        return 0.0

    from services.projections import household_computed_fields, list_applicants_of_household

    computed = household_computed_fields(household, rule_variant="STATE")
    proj_fpl = computed["fpl_percent"]
    if proj_fpl is None:
        return 0.0

    now = CLOCK.now()
    ages = []
    for a in list_applicants_of_household(household["id"]):
        if a["dependent_status"] == "EXCLUDED":
            continue
        ages.append(_age_at(a["date_of_birth"], now))
    return premium_estimate_total(ages, proj_fpl)
