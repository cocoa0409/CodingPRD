"""Fee schedule postures, selectors, tier ladder rules and guideline lookups
(PRD 3.3, 3.4)."""

import db
from validation import dec, whole_days_between


# --------------------------------------------------------------------------- #
# poverty guidelines
# --------------------------------------------------------------------------- #


def guideline_for_year(year):
    for row in db.db.poverty_guidelines.values():
        if row["guideline_year"] == year:
            return row
    return None


def latest_guideline_year():
    years = [row["guideline_year"] for row in db.db.poverty_guidelines.values()]
    return max(years) if years else None


def guideline_amount_cents(guideline, household_size):
    """base_amount_cents + increment_cents * (household_size - 1)."""
    return guideline["base_amount_cents"] + guideline["increment_cents"] * (household_size - 1)


# --------------------------------------------------------------------------- #
# review posture (PRD 3.3 rules R1..R3) — recomputed on every read
# --------------------------------------------------------------------------- #


def review_status(schedule):
    latest = latest_guideline_year()
    if latest is not None and schedule["fpg_year"] < latest:
        return "OUT_OF_DATE"
    last_reviewed = schedule.get("last_reviewed_at")
    if last_reviewed is not None:
        elapsed = whole_days_between(last_reviewed, db.now())
        if elapsed > 365:
            return "REVIEW_DUE"
    return "CURRENT"


# --------------------------------------------------------------------------- #
# selectors (PRD 3.5)
# --------------------------------------------------------------------------- #


def covers(schedule, moment):
    """Half-open period [effective_start, effective_end)."""
    return schedule["effective_start"] <= moment < schedule["effective_end"]


def _rank_schedules(candidates):
    return sorted(
        candidates,
        key=lambda s: (s["effective_start"], s["created_at"], s["_seq"]),
        reverse=True,
    )


def select_schedule_for_health_center(hc_id, moment):
    candidates = [
        s
        for s in db.db.fee_schedules.values()
        if s["health_center_id"] == hc_id and s["status"] == "ADOPTED" and covers(s, moment)
    ]
    ranked = _rank_schedules(candidates)
    return ranked[0] if ranked else None


def select_schedule_for_patient(patient_id, moment):
    """The adopted schedule covering `moment` "for that patient's grantee".  The
    patient's grantee is the grantee (or grantees) at which the patient has been
    seen; when the patient has no encounter yet, every adopted schedule covering
    the instant is a candidate."""
    hc_ids = set()
    for enc in db.db.encounters.values():
        if enc["patient_id"] != patient_id or enc["pps_claim_status"] == "VOID":
            continue
        site = db.db.service_sites.get(enc["service_site_id"])
        if site is not None:
            hc_ids.add(site["health_center_id"])

    candidates = [
        s
        for s in db.db.fee_schedules.values()
        if s["status"] == "ADOPTED" and covers(s, moment)
    ]
    if hc_ids:
        scoped = [s for s in candidates if s["health_center_id"] in hc_ids]
        if scoped:
            candidates = scoped
    ranked = _rank_schedules(candidates)
    return ranked[0] if ranked else None


def verification_window_covers(verification, moment):
    """Closed window [effective_date, expires_at]."""
    return verification["effective_date"] <= moment <= verification["expires_at"]


def select_verification(patient_id, moment):
    candidates = [
        v
        for v in db.db.income_verifications.values()
        if v["patient_id"] == patient_id
        and v["status"] == "VERIFIED"
        and verification_window_covers(v, moment)
    ]
    ranked = sorted(
        candidates,
        key=lambda v: (v["effective_date"], v["created_at"], v["_seq"]),
        reverse=True,
    )
    return ranked[0] if ranked else None


# --------------------------------------------------------------------------- #
# tiers
# --------------------------------------------------------------------------- #


def tiers_of(schedule_id):
    rows = [t for t in db.db.discount_tiers.values() if t["fee_schedule_id"] == schedule_id]
    return sorted(rows, key=lambda t: t["sort_order"])


def select_tier(schedule_id, fpg_percent):
    """Half-open band [fpg_min_pct, fpg_max_pct); null max is unbounded above."""
    value = dec(fpg_percent)
    for tier in tiers_of(schedule_id):
        low = dec(tier["fpg_min_pct"])
        high = tier["fpg_max_pct"]
        if value < low:
            continue
        if high is None or value < dec(high):
            return tier
    return None


def ladder_is_well_formed(schedule_id):
    """PRD 3.3 adoption ladder check."""
    tiers = tiers_of(schedule_id)
    if len(tiers) < 2:
        return False
    mins = [dec(t["fpg_min_pct"]) for t in tiers]
    if any(mins[i] >= mins[i + 1] for i in range(len(mins) - 1)):
        return False
    if mins[0] != dec(0):
        return False
    for index in range(len(tiers) - 1):
        upper = tiers[index]["fpg_max_pct"]
        if upper is None:
            return False
        if dec(upper) != mins[index + 1]:
            return False
    if tiers[-1]["fpg_max_pct"] is not None:
        return False
    return True
