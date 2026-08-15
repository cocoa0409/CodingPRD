"""Cascading side effects (scaffold state_machines side_effects):

- disqualify_entry: zero the entry's sporting yield for the event
  (points_awarded -> 0 on every result, finish_position unchanged, no
  position compression); event_points derives to 0 on next read.
- apply_time_penalty / reverse_time_penalty: Cascade A — adjust
  penalty_seconds_applied on the incident entry's result, re-rank the session
  by effective total time, rewrite finish_position (changed results
  PROVISIONAL -> AMENDED), recompute points for the whole session.
- cancel_event_cascade: Cascade B — withdraw active entries, refund PAID fees.
"""
from db import db
from services.calculations import recompute_session_points
from services.core import ENTRY_ACTIVE_STATES, touch


def _sessions_with_entry_results(entry_id):
    sess_ids = {
        r["session_id"] for r in db["results"].values() if r["entry_id"] == entry_id
    }
    return [db["sessions"][sid] for sid in sess_ids if sid in db["sessions"]]


def disqualify_entry(entry):
    """Entry -> DISQUALIFIED with the section 3.4 consequences."""
    entry["status"] = "DISQUALIFIED"
    touch(entry)
    for sess in _sessions_with_entry_results(entry["id"]):
        recompute_session_points(sess, rerank=False)


def apply_time_penalty(incident, seconds):
    """Cascade A (UPHELD, TIME_SECONDS): add seconds, re-rank, recompute."""
    session = db["sessions"].get(incident["session_id"])
    if session is None:
        return
    target = None
    for r in db["results"].values():
        if r["session_id"] == session["id"] and r["entry_id"] == incident["entry_id"]:
            target = r
            break
    if target is not None:
        target["penalty_seconds_applied"] = target["penalty_seconds_applied"] + seconds
        touch(target)
    recompute_session_points(session, rerank=True)


def reverse_time_penalty(incident, seconds):
    """Compensation for DISMISSED-after-appeal: subtract the seconds back out,
    then re-rank and recompute exactly as the UPHELD cascade."""
    session = db["sessions"].get(incident["session_id"])
    if session is None:
        return
    target = None
    for r in db["results"].values():
        if r["session_id"] == session["id"] and r["entry_id"] == incident["entry_id"]:
            target = r
            break
    if target is not None:
        target["penalty_seconds_applied"] = max(
            0, target["penalty_seconds_applied"] - seconds
        )
        touch(target)
    recompute_session_points(session, rerank=True)


def cancel_event_cascade(event):
    """Cascade B: every child entry in an active state -> WITHDRAWN; each
    withdrawn entry with fee_status PAID -> REFUNDED (the season treasury
    total is derived on read, so it reflects this immediately)."""
    for en in db["entries"].values():
        if en["event_id"] != event["id"]:
            continue
        if en["status"] not in ENTRY_ACTIVE_STATES:
            continue
        en["status"] = "WITHDRAWN"
        if en["fee_status"] == "PAID":
            en["fee_status"] = "REFUNDED"
        touch(en)
