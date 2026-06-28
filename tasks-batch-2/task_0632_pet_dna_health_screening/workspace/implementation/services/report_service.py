"""Report-related computed helpers: health roll-up and finalized_report_id
recompute (PRD §3.4)."""
from db import db


def compute_at_risk_marker_count(report_id, finalized):
    """report_health_risk_rollup (SCAFFOLD §1.3 / PRD §3.4).

    PRELIMINARY: count AT_RISK markers with review_status == PASS (exclude REVIEWED).
    FINALIZED: count AT_RISK markers with review_status IN {PASS, REVIEWED}.
    """
    count = 0
    for m in db.health_marker_results.values():
        if m["report_id"] != report_id:
            continue
        if m["genotype"] != "AT_RISK":
            continue
        if finalized:
            if m["review_status"] in ("PASS", "REVIEWED"):
                count += 1
        else:
            if m["review_status"] == "PASS":
                count += 1
    return count


def recompute_pet_finalized_report_id(pet_id):
    """finalized_report_id: id of the pet's most recent FINALIZED Report
    (latest by report.created_at ASC, last wins), or null."""
    finalized = [
        r for r in db.reports.values()
        if r["pet_id"] == pet_id and r["status"] == "FINALIZED"
    ]
    if not finalized:
        return None
    finalized.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return finalized[-1]["id"]
