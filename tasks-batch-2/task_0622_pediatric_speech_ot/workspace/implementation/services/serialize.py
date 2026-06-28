"""Entity -> public JSON serializers. Field sets follow scaffold §1.1."""

COMMON = ("id", "created_at", "updated_at", "version")


def _base(rec):
    return {k: rec[k] for k in COMMON}


def child(rec):
    out = _base(rec)
    out.update(
        full_name=rec["full_name"],
        date_of_birth=rec["date_of_birth"],
        age_months_at_intake=rec["age_months_at_intake"],
        coordination_program=rec["coordination_program"],
        active_appointment_count=rec["active_appointment_count"],
        status=rec["status"],
    )
    return out


def therapist(rec):
    out = _base(rec)
    out.update(
        full_name=rec["full_name"],
        discipline=rec["discipline"],
        max_caseload=rec["max_caseload"],
        weekly_visit_minutes_cap=rec["weekly_visit_minutes_cap"],
        current_caseload=rec["current_caseload"],
        status=rec["status"],
    )
    return out


def evaluation(rec):
    out = _base(rec)
    out.update(
        child_id=rec["child_id"],
        evaluator_id=rec["evaluator_id"],
        discipline=rec["discipline"],
        severity_score=rec["severity_score"],
        recommended_weekly_minutes=rec["recommended_weekly_minutes"],
        status=rec["status"],
    )
    return out


def plan_of_care(rec):
    out = _base(rec)
    out.update(
        child_id=rec["child_id"],
        evaluation_id=rec["evaluation_id"],
        primary_therapist_id=rec["primary_therapist_id"],
        discipline=rec["discipline"],
        planned_weekly_minutes=rec["planned_weekly_minutes"],
        goal_count=rec["goal_count"],
        overall_progress_pct=rec["overall_progress_pct"],
        status=rec["status"],
    )
    return out


def goal(rec):
    out = _base(rec)
    out.update(
        plan_of_care_id=rec["plan_of_care_id"],
        description=rec["description"],
        weight=rec["weight"],
        baseline_pct=rec["baseline_pct"],
        target_pct=rec["target_pct"],
        latest_progress_pct=rec["latest_progress_pct"],
        status=rec["status"],
    )
    return out


def authorization(rec):
    out = _base(rec)
    out.update(
        child_id=rec["child_id"],
        discipline=rec["discipline"],
        payer_name=rec["payer_name"],
        authorized_visits=rec["authorized_visits"],
        valid_from=rec["valid_from"],
        valid_until=rec["valid_until"],
        reserved_visits=rec["reserved_visits"],
        committed_visits=rec["committed_visits"],
        available_visits=rec["available_visits"],
        status=rec["status"],
    )
    return out


def appointment(rec):
    out = _base(rec)
    out.update(
        child_id=rec["child_id"],
        therapist_id=rec["therapist_id"],
        authorization_id=rec["authorization_id"],
        plan_of_care_id=rec["plan_of_care_id"],
        start_time=rec["start_time"],
        end_time=rec["end_time"],
        duration_minutes=rec["duration_minutes"],
        from_waitlist_entry_id=rec["from_waitlist_entry_id"],
        status=rec["status"],
    )
    return out


def session_note(rec):
    out = _base(rec)
    out.update(
        appointment_id=rec["appointment_id"],
        narrative=rec["narrative"],
        minutes_delivered=rec["minutes_delivered"],
        goal_progress_entries=rec["goal_progress_entries"],
    )
    return out


def goal_progress_entry(rec):
    # PRD §2.4: append-only event-log record; only id + created_at common fields.
    # No updated_at, no version.
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "goal_id": rec["goal_id"],
        "session_note_id": rec["session_note_id"],
        "recorded_pct": rec["recorded_pct"],
        "recorded_session_time": rec["recorded_session_time"],
    }


def coordination_plan(rec):
    out = _base(rec)
    out.update(
        child_id=rec["child_id"],
        plan_type=rec["plan_type"],
        jurisdiction=rec["jurisdiction"],
        review_due_time=rec["review_due_time"],
        status=rec["status"],
    )
    return out


def home_program(rec):
    out = _base(rec)
    out.update(
        plan_of_care_id=rec["plan_of_care_id"],
        assigned_by_therapist_id=rec["assigned_by_therapist_id"],
        title=rec["title"],
        weekly_target_sessions=rec["weekly_target_sessions"],
        parent_training_completed=rec["parent_training_completed"],
        status=rec["status"],
    )
    return out


def waitlist_entry(rec):
    out = _base(rec)
    out.update(
        child_id=rec["child_id"],
        therapist_id=rec["therapist_id"],
        discipline=rec["discipline"],
        evaluation_id=rec["evaluation_id"],
        priority_score=rec["priority_score"],
        requested_minutes=rec["requested_minutes"],
        status=rec["status"],
    )
    return out
