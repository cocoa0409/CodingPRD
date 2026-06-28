"""Derived-field reconciliation (PRD §2.10).

open_claim_count is always the number of a Job's claims whose status is OPEN or
IN_PROGRESS. assessment_severity mirrors the latest FINALIZED inspection severity.
"""
import db


def recompute_open_claim_count(job):
    """Set job.open_claim_count to the count of its claims in {OPEN, IN_PROGRESS}."""
    count = 0
    for claim in db.claims.items.values():
        if claim["job_id"] == job["id"] and claim["status"] in ("OPEN", "IN_PROGRESS"):
            count += 1
    job["open_claim_count"] = count
    return count
