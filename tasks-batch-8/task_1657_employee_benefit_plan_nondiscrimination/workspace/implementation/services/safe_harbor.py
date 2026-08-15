"""Safe harbor election effectiveness evaluation and notice lapse (PRD §3.8)."""

from datetime import date, timedelta

from db import clock, store
from services.common import bump

MIN_NOTICE_DAYS_BEFORE_YEAR_END = 30


def evaluate_election_effectiveness(election):
    """PROPOSED -> EFFECTIVE when the plan year is CENSUS_LOCKED and a linked
    notice is DISTRIBUTED/ACKNOWLEDGED with distributed_at inside the window."""
    if election["status"] != "PROPOSED":
        return False
    py = store.plan_years.get(election["plan_year_id"])
    if py is None or py["status"] != "CENSUS_LOCKED":
        return False
    for notice in store.safe_harbor_notices.values():
        if notice["election_id"] != election["id"]:
            continue
        if notice["status"] not in ("DISTRIBUTED", "ACKNOWLEDGED"):
            continue
        distributed_at = notice.get("distributed_at")
        if not distributed_at:
            continue
        distributed_date = date.fromisoformat(distributed_at[:10])
        start = date.fromisoformat(notice["notice_period_start"])
        end = date.fromisoformat(notice["notice_period_end"])
        if start <= distributed_date <= end:
            election["status"] = "EFFECTIVE"
            bump(election)
            _sync_governing_design(election, py)
            return True
    return False


def _sync_governing_design(election, py):
    """Ledger sync: set the governing PlanVersion.safe_harbor_design."""
    version_id = py.get("adopted_version_id")
    if not version_id:
        return
    version = store.plan_versions.get(version_id)
    if version is None:
        return
    version["safe_harbor_design"] = election["design"]
    bump(version)


def strip_governing_design(py):
    """Suspension: reset the governing PlanVersion.safe_harbor_design to NONE."""
    version_id = py.get("adopted_version_id")
    if not version_id:
        return
    version = store.plan_versions.get(version_id)
    if version is None:
        return
    version["safe_harbor_design"] = "NONE"
    bump(version)


def evaluate_notice_lapse():
    """On every clock set: DRAFT notices whose window has passed -> LAPSED."""
    now_date = clock.now().date()
    for notice in store.safe_harbor_notices.values():
        if notice["status"] != "DRAFT":
            continue
        end = date.fromisoformat(notice["notice_period_end"])
        if now_date > end:
            notice["status"] = "LAPSED"
            bump(notice)


def notice_window_valid(notice, py):
    """Window check per safe_harbor_notice_window_check.

    Initial election: notice_period_end <= year_start - 1 day.
    Mid-year amendment (plan year already CENSUS_COLLECTING):
    notice_period_end <= year_end - 30 days.
    """
    start = date.fromisoformat(notice["notice_period_start"])
    end = date.fromisoformat(notice["notice_period_end"])
    year_start = date.fromisoformat(py["year_start"])
    year_end = date.fromisoformat(py["year_end"])
    now = clock.now()
    now_date = now.date()
    if not (start <= now_date <= end):
        return False
    if py["status"] == "CENSUS_COLLECTING":
        return end <= year_end - timedelta(days=MIN_NOTICE_DAYS_BEFORE_YEAR_END)
    return end <= year_start - timedelta(days=1)
