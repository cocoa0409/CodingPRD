"""Public entity serialization (internal keys like _seq excluded).

ReviewRecord and AnalyticsReport are immutable measurements: they expose only
id and created_at (no updated_at / version) per PRD 2.5.
"""

from .util import fmt_dt


def _base(e):
    return {
        "id": e["id"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_staff(s):
    d = _base(s)
    d.update({
        "full_name": s["full_name"],
        "role_capability": s["role_capability"],
        "home_desk": s["home_desk"],
        "employment_status": s["employment_status"],
        "max_concurrent_assignments": s["max_concurrent_assignments"],
        "hourly_rate_cents": s["hourly_rate_cents"],
        "active_assignment_count": s["active_assignment_count"],
    })
    return d


def ser_pitch(p):
    d = _base(p)
    d.update({
        "title": p["title"],
        "summary": p["summary"],
        "desk": p["desk"],
        "urgency": p["urgency"],
        "deadline_at": fmt_dt(p["deadline_at"]),
        "submitting_staff_id": p["submitting_staff_id"],
        "status": p["status"],
        "rework_round": p["rework_round"],
        "greenlit_story_id": p["greenlit_story_id"],
    })
    return d


def ser_story(s):
    d = _base(s)
    d.update({
        "pitch_id": s["pitch_id"],
        "desk": s["desk"],
        "story_type": s["story_type"],
        "author_staff_id": s["author_staff_id"],
        "status": s["status"],
        "word_count": s["word_count"],
        "embargo_until": fmt_dt(s["embargo_until"]),
        "slot_id": s["slot_id"],
        "priority_score": s["priority_score"],
        "correction_count": s["correction_count"],
        "published_at": fmt_dt(s["published_at"]),
        "superseded_by_story_id": s["superseded_by_story_id"],
    })
    return d


def ser_assignment(a):
    d = _base(a)
    d.update({
        "story_id": a["story_id"],
        "staff_id": a["staff_id"],
        "assignment_role": a["assignment_role"],
        "status": a["status"],
        "start_at": fmt_dt(a["start_at"]),
        "end_at": fmt_dt(a["end_at"]),
        "planned_effort_minutes": a["planned_effort_minutes"],
        "actual_effort_minutes": a["actual_effort_minutes"],
        "provisional_cost_cents": a["provisional_cost_cents"],
        "final_cost_cents": a["final_cost_cents"],
        "completed_at": fmt_dt(a["completed_at"]),
        "bumped_by_event_id": a["bumped_by_event_id"],
    })
    return d


def ser_slot(s):
    d = _base(s)
    d.update({
        "channel": s["channel"],
        "window_start": fmt_dt(s["window_start"]),
        "window_end": fmt_dt(s["window_end"]),
        "capacity": s["capacity"],
        "reserved_count": s["reserved_count"],
        "status": s["status"],
    })
    return d


def ser_review(r):
    # Immutable measurement: no updated_at / version
    return {
        "id": r["id"],
        "created_at": fmt_dt(r["created_at"]),
        "story_id": r["story_id"],
        "reviewer_staff_id": r["reviewer_staff_id"],
        "review_type": r["review_type"],
        "verdict": r["verdict"],
        "notes": r["notes"],
        "reviewed_story_version": r["reviewed_story_version"],
        "review_round": r["review_round"],
        "is_current": r["is_current"],
    }


def ser_correction(c):
    d = _base(c)
    d.update({
        "story_id": c["story_id"],
        "proposer_staff_id": c["proposer_staff_id"],
        "severity": c["severity"],
        "correction_text": c["correction_text"],
        "status": c["status"],
        "approver_staff_id": c["approver_staff_id"],
        "correction_number": c["correction_number"],
        "issued_at": fmt_dt(c["issued_at"]),
    })
    return d


def ser_analytics(a):
    # Immutable measurement: no updated_at / version
    return {
        "id": a["id"],
        "created_at": fmt_dt(a["created_at"]),
        "story_id": a["story_id"],
        "variant": a["variant"],
        "window_start": fmt_dt(a["window_start"]),
        "window_end": fmt_dt(a["window_end"]),
        "views": a["views"],
        "engagement_minutes": a["engagement_minutes"],
        "raw_score": a["raw_score"],
        "tier": a["tier"],
        "performance_score": a["performance_score"],
        "status": a["status"],
    }


def ser_event(e):
    d = _base(e)
    d.update({
        "title": e["title"],
        "priority_band": e["priority_band"],
        "window_start": fmt_dt(e["window_start"]),
        "window_end": fmt_dt(e["window_end"]),
        "call_in_pool_size": e["call_in_pool_size"],
        "status": e["status"],
        "declared_by": e["declared_by"],
        "resolved_at": fmt_dt(e["resolved_at"]),
    })
    return d


def ser_call_in(c):
    d = _base(c)
    d.update({
        "event_id": c["event_id"],
        "staff_id": c["staff_id"],
        "status": c["status"],
        "paged_at": fmt_dt(c["paged_at"]),
        "expires_at": fmt_dt(c["expires_at"]),
    })
    return d
