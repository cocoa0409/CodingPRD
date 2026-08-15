"""Cross-entity mutation helper: every change refreshes updated_at and bumps version
(PRD §2.4), except ItemResponse which carries neither field (PRD §2.4 exception)."""
from util import now_ts


def touch(rec):
    if rec is None:
        return
    if "version" in rec:
        rec["version"] += 1
    if "updated_at" in rec:
        rec["updated_at"] = now_ts()
