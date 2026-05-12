"""Auto-transition sweeps: case archival, posture recomputation, etc.

Run by /_clock/advance and /_sweep/run. Idempotent.
"""

from datetime import timedelta

import clock
import db
import helpers
from services import audit, posture


CASE_ARCHIVE_DAYS = 30


def run_all():
    """Idempotently re-run every auto-transition. Order:
      1) Archive CLOSED cases whose closed_at + 30d <= now.
      2) Recompute posture for all non-archived cases.
    """
    archived = []
    archive_cutoff = clock.now() - timedelta(days=CASE_ARCHIVE_DAYS)

    for case in list(db.cases.values()):
        if case["status"] == "CLOSED":
            ca = case.get("closed_at")
            if ca is not None and ca <= archive_cutoff:
                case["status"] = "ARCHIVED"
                helpers.bump(case)
                archived.append(case["id"])

    for case in db.cases.values():
        if case["status"] in {"ARCHIVED"}:
            continue
        posture.recompute(case)

    return {"archived_case_ids": archived}
