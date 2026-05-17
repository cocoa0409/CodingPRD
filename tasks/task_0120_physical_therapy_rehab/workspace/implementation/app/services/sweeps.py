"""Time-gated sweeps fired by /_clock/advance."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..clock import now
from ..store import store
from .constants import REEVAL_WINDOW_DAYS


def _parse_iso(s: str) -> datetime:
    raw = s
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _date_only(dt: datetime) -> datetime:
    # End-of-day for inclusive valid_through (use end-of-day for date-only comparisons)
    return dt


def _bump(row: dict, current: datetime) -> None:
    row["updated_at"] = current
    row["version"] = row.get("version", 1) + 1


def run_sweeps() -> None:
    """Run all time-gated sweeps in dependency order."""
    db = store()
    current = now()

    # 1) VeteranReferral.ACTIVE -> EXPIRED on valid_through pass
    for ref in db.veteran_referrals.values():
        if ref.get("status") == "ACTIVE":
            vt = _parse_iso(ref["valid_through"])
            # Treat as end-of-day inclusive: anything strictly after the day end expires.
            vt_end = vt.replace(hour=23, minute=59, second=59, microsecond=999999) if vt.hour == 0 and vt.minute == 0 and vt.second == 0 else vt
            if current > vt_end:
                ref["status"] = "EXPIRED"

    # 2) Authorization.APPROVED -> EXPIRED on valid_through pass
    for auth in db.authorizations.values():
        if auth.get("status") == "APPROVED":
            vt = _parse_iso(auth["valid_through"])
            vt_end = vt.replace(hour=23, minute=59, second=59, microsecond=999999) if vt.hour == 0 and vt.minute == 0 and vt.second == 0 else vt
            if current > vt_end:
                auth["status"] = "EXPIRED"
                # Recompute owning Episode.total_authorized_units
                ep = db.episodes.get(auth["episode_id"])
                if ep:
                    _recompute_episode_units(ep)
                    _bump(ep, current)

    # 3) PlanOfCare.ACTIVE -> EXPIRED on cert_period_end pass (cancel scheduled visits)
    for poc in db.plan_of_cares.values():
        if poc.get("status") == "ACTIVE":
            ce = _parse_iso(poc["cert_period_end"])
            ce_end = ce.replace(hour=23, minute=59, second=59, microsecond=999999) if ce.hour == 0 and ce.minute == 0 and ce.second == 0 else ce
            if current > ce_end:
                poc["status"] = "EXPIRED"
                _bump(poc, current)
                # Cancel SCHEDULED visits on this plan
                for v in db.visits.values():
                    if v["plan_of_care_id"] == poc["id"] and v.get("status") == "SCHEDULED":
                        v["status"] = "CANCELLED"
                        _bump(v, current)
                        ep = db.episodes.get(v["episode_id"])
                        if ep:
                            _recompute_episode_units(ep)
                            _bump(ep, current)

    # 4) Episode.ACTIVE -> REEVAL_DUE on 30-day gap
    threshold = timedelta(days=REEVAL_WINDOW_DAYS)
    for ep in db.episodes.values():
        if ep.get("status") == "ACTIVE":
            latest = _latest_finalized_eval(ep["id"])
            if latest and latest.get("finalized_at"):
                fa = latest["finalized_at"]
                if current - fa >= threshold:
                    ep["status"] = "REEVAL_DUE"
                    _bump(ep, current)


def _latest_finalized_eval(episode_id: str) -> dict | None:
    db = store()
    candidates = [
        e for e in db.evaluations.values()
        if e["episode_id"] == episode_id and e.get("status") in ("FINALIZED", "AMENDED")
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda e: e.get("finalized_at") or datetime.min.replace(tzinfo=timezone.utc))


def _recompute_episode_units(ep: dict) -> None:
    db = store()
    eid = ep["id"]
    ep["total_authorized_units"] = sum(
        a["unit_quota"] for a in db.authorizations.values()
        if a["episode_id"] == eid and a.get("status") == "APPROVED"
    )
    ep["total_reserved_units"] = sum(
        v["units_planned"] for v in db.visits.values()
        if v["episode_id"] == eid and v.get("status") in ("SCHEDULED", "IN_SESSION")
    )
    ep["total_committed_units"] = sum(
        v.get("units_billed", 0) for v in db.visits.values()
        if v["episode_id"] == eid and v.get("status") in ("SIGNED", "BILLED")
    )
