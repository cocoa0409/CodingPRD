"""Shared mutations: version bumps, premium staleness sweeps, recomputes (PRD 2.4, 2.8)."""
from db import db, next_seq
from services import calc
from util import CLOCK

OPEN_COACHING_STATES = ("ASSIGNED", "IN_PROGRESS", "OVERDUE", "ESCALATED")
OPEN_AUDIT_STATES = ("SCHEDULED", "FIELD_WORK", "FINDINGS_ISSUED", "CORRECTIVE_ACTION_PHASE")
OPEN_CHALLENGE_STATES = ("SUBMITTED", "UNDER_REVIEW", "REMANDED")
OPEN_UPGRADE_STATES = ("SUBMITTED", "UNDER_REVIEW")


def stamp_new(rec: dict):
    """Initialize common fields on creation (PRD 2.4)."""
    rec["created_at"] = CLOCK.now_ts()
    rec["updated_at"] = CLOCK.now_ts()
    rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def touch(rec: dict):
    """Version +1 and updated_at refresh on any mutation (incl. cascades)."""
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = CLOCK.now_ts()


def sweep_quoted_premiums(carrier_id: str) -> int:
    """QUOTED -> STALE for the carrier's premium models. Returns count."""
    n = 0
    for m in db["insurance_premium_models"].values():
        if m["carrier_id"] == carrier_id and m["status"] == "QUOTED":
            m["status"] = "STALE"
            touch(m)
            n += 1
    return n


def recompute_posture(carrier: dict) -> str:
    new = calc.compute_posture(carrier)
    carrier["posture"] = new
    return new


def recompute_driver_risk(driver: dict, sweep: bool = True):
    """Refresh risk_score/risk_tier; on tier change sweep carrier QUOTED premiums."""
    old_tier = driver["risk_tier"]
    score, tier = calc.driver_risk(driver, CLOCK.now())
    if score != driver["risk_score"] or tier != old_tier:
        driver["risk_score"] = score
        driver["risk_tier"] = tier
        touch(driver)
    if sweep and tier != old_tier:
        sweep_quoted_premiums(driver["carrier_id"])


def recompute_inspection_total(insp: dict):
    """Sum of weighted_points over ACTIVE/CHALLENGED violations (REMOVED excluded)."""
    total = sum(
        v["weighted_points"]
        for v in db["inspection_violations"].values()
        if v["inspection_id"] == insp["id"] and v["status"] in ("ACTIVE", "CHALLENGED")
    )
    if total != insp["total_weighted_points"]:
        insp["total_weighted_points"] = total
        touch(insp)


def maybe_auto_reinstate(driver: dict):
    """SUSPENDED -> ACTIVE iff zero suspension holds remain (PRD 3.2)."""
    if driver["employment_status"] == "SUSPENDED" and calc.suspension_hold_count(driver) == 0:
        driver["employment_status"] = "ACTIVE"
        touch(driver)


def apply_rating_to_carrier(carrier: dict, new_rating: str):
    """Compliance-review close cascade: write rating, downgrade cooling-off (180d),
    posture recompute, version bump, QUOTED premium sweep."""
    old = carrier["safety_rating"]
    carrier["safety_rating"] = new_rating
    if old in calc.RATING_BADNESS and calc.RATING_BADNESS[new_rating] > calc.RATING_BADNESS[old]:
        carrier["rating_cooling_off_until"] = _clock_plus_days(180)
    recompute_posture(carrier)
    touch(carrier)
    sweep_quoted_premiums(carrier["id"])


def _clock_plus_days(days: int) -> str:
    from util import fmt_datetime, add_days
    return fmt_datetime(add_days(CLOCK.now(), days))


def audit_readiness(carrier: dict) -> dict:
    """Computed audit-readiness summary (PRD 3.8)."""
    cid = carrier["id"]

    def doc_live(doc):
        return doc["status"] != "PURGED"

    missing_dq = 0
    for d in db["drivers"].values():
        if d["carrier_id"] != cid or d["employment_status"] == "TERMINATED":
            continue
        has_dq = any(
            doc["carrier_id"] == cid and doc.get("driver_id") == d["id"]
            and doc["document_type"] == "DQ_FILE" and doc_live(doc)
            for doc in db["document_records"].values()
        )
        if not has_dq:
            missing_dq += 1

    reportable = sum(
        1 for a in db["accident_records"].values()
        if a["carrier_id"] == cid and a["dot_reportable"]
    )
    register_entries = sum(
        1 for doc in db["document_records"].values()
        if doc["carrier_id"] == cid
        and doc["document_type"] == "ACCIDENT_REGISTER_ENTRY"
        and doc_live(doc)
    )
    gap = max(0, reportable - register_entries)

    purge_eligible = sum(
        1 for doc in db["document_records"].values()
        if doc["carrier_id"] == cid and doc["status"] == "PURGE_ELIGIBLE"
    )
    open_audits = sum(
        1 for a in db["compliance_audit_cases"].values()
        if a["carrier_id"] == cid and a["status"] in OPEN_AUDIT_STATES
    )
    return {
        "ready": missing_dq == 0 and gap == 0,
        "missing_dq_driver_count": missing_dq,
        "accident_register_gap": gap,
        "purge_eligible_document_count": purge_eligible,
        "open_audit_case_count": open_audits,
    }
