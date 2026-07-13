"""Dosage in two variants, the empty-denominator null case, the depth-4 missed-visit
escalation cascade, the completed_visit_count revert invariant, and supervision-sign
disposition of dosage alerts."""
import pytest
from test_helpers import (
    validate_success,
    ApiErrorId,
    create_supervision_session_payload,
    set_clock,
    schedule_visit,
    complete_visit,
    complete_visit_payload,
    setup_active_enrollment,
    setup_dosage_divergence,
    setup_missed_visit_escalation,
    setup_active_enrollment_with_dosage_alert,
    get_enrollment,
    get_nurse,
    api_client,
    get_success_data,
)


# ─── Difficulty: dosage to-date vs full-program ─────────
def test_dosage_to_date_counts_only_due_dispositioned_visits(api):
    """PRD 3.6: "its denominator counts the enrollment's visits whose status is COMPLETED
    or MISSED and whose target_date is on or before the current logical-clock day, and
    its numerator counts those same due visits whose status is COMPLETED."

    Design: Difficulty/dual_variant_calc/dosage_to_date_vs_full_program_diverge
    """
    ctx = setup_dosage_divergence()
    dosage = validate_success(api.get_dosage(ctx.enrollment_id, ctx.supervisor_headers), 200)
    assert dosage["dosage_to_date_pct"] == pytest.approx(66.67, abs=0.01)
    assert dosage["expected_to_date"] == 3
    assert dosage["completed_to_date"] == 2


def test_dosage_full_program_includes_future_scheduled_visits(api):
    """PRD 3.6: "its denominator counts the enrollment's visits whose status is COMPLETED,
    MISSED, or SCHEDULED regardless of target_date, and its numerator counts those in
    COMPLETED."
    PRD 3.6: "dosage_alert is true exactly when the to-date percentage is non-null and
    strictly below 60 percent."

    Design: Difficulty/dual_variant_calc/dosage_to_date_vs_full_program_diverge
    """
    ctx = setup_dosage_divergence()
    dosage = validate_success(api.get_dosage(ctx.enrollment_id, ctx.supervisor_headers), 200)
    assert dosage["dosage_full_pct"] == pytest.approx(50.00, abs=0.01)
    assert dosage["dosage_alert"] is False


# ─── Difficulty: zero-denominator dosage is null ────────
def test_dosage_to_date_is_null_when_no_visits_are_due(api):
    """PRD 2.6: "Where a calculation is defined as a ratio and its denominator is zero,
    the resulting percentage is null rather than zero."
    PRD 3.6: "The to-date percentage, dosage_to_date_pct, is null when that denominator
    is zero".

    Design: Difficulty/boundary_precision_check/dosage_zero_expected_yields_null_not_error
    """
    ctx = setup_active_enrollment()
    set_clock("2026-06-01T00:00:00Z")
    schedule_visit(
        ctx, target_date="2026-07-01",
        scheduled_start="2026-07-01T09:00:00Z", scheduled_end="2026-07-01T10:00:00Z",
    )
    dosage = validate_success(api.get_dosage(ctx.enrollment_id, ctx.supervisor_headers), 200)
    assert dosage["dosage_to_date_pct"] is None
    assert dosage["expected_to_date"] == 0


def test_zero_due_dosage_raises_no_alert(api):
    """PRD 3.6: "dosage_alert is true exactly when the to-date percentage is non-null and
    strictly below 60 percent."

    Design: Difficulty/boundary_precision_check/dosage_zero_expected_yields_null_not_error
    """
    ctx = setup_active_enrollment()
    set_clock("2026-06-01T00:00:00Z")
    schedule_visit(
        ctx, target_date="2026-07-01",
        scheduled_start="2026-07-01T09:00:00Z", scheduled_end="2026-07-01T10:00:00Z",
    )
    dosage = validate_success(api.get_dosage(ctx.enrollment_id, ctx.supervisor_headers), 200)
    assert dosage["dosage_alert"] is False


# ─── Difficulty: depth-4 missed-visit escalation ────────
def test_missed_visit_drops_dosage_and_raises_alert(api):
    """PRD 3.6: "The first hop marks the visit MISSED and recomputes dosage; because a
    MISSED visit enters the to-date denominator but not the numerator, the to-date
    percentage drops. The second hop fires only if the recomputed dosage_to_date_pct is
    now below 60 percent: it sets the enrollment's dosage_alert to true."

    Design: Difficulty/transitive_cascade/missed_visit_dosage_escalation_cascade_depth4
    """
    ctx, v2_id = setup_missed_visit_escalation()
    validate_success(api.mark_missed(v2_id, ctx.nurse_headers), 200)
    dosage = validate_success(api.get_dosage(ctx.enrollment_id, ctx.supervisor_headers), 200)
    assert dosage["dosage_to_date_pct"] == pytest.approx(50.00, abs=0.01)
    enrollment = get_enrollment(ctx.enrollment_id)
    assert enrollment["dosage_alert"] is True


def test_missed_visit_sets_review_required_and_pending_supervision(api):
    """PRD 3.6: "The third hop fires only when the second hop actually flipped
    dosage_alert from false to true: it sets review_required to true on every ACTIVE
    assignment of the enrollment. The fourth hop fires only when the third hop fired:
    for each such assignment, it increments that assignment's nurse's
    pending_supervision_count by 1."

    Design: Difficulty/transitive_cascade/missed_visit_dosage_escalation_cascade_depth4
    """
    ctx, v2_id = setup_missed_visit_escalation()
    validate_success(api.mark_missed(v2_id, ctx.nurse_headers), 200)
    data, _meta = _list_assignments(api, ctx)
    assert data[0]["review_required"] is True
    nurse = get_nurse(ctx.nurse_id)
    assert nurse["pending_supervision_count"] == 1


def _list_assignments(api, ctx):
    from test_helpers import validate_paginated
    return validate_paginated(
        api.list_assignments(ctx.supervisor_headers, params={"enrollment_id": ctx.enrollment_id})
    )


# ─── Difficulty: completed_visit_count revert invariant ─
def _active_enrollment_with_completed_visit():
    ctx = setup_active_enrollment()
    set_clock("2026-06-01T00:00:00Z")
    visit = schedule_visit(
        ctx, target_date="2026-05-01",
        scheduled_start="2026-05-01T09:00:00Z", scheduled_end="2026-05-01T10:00:00Z",
    )
    complete_visit(visit["id"], "2026-05-01", ctx.nurse_headers)
    return ctx, visit


def test_completion_increments_then_revert_restores_count(api):
    """PRD 3.6: "As an invariant, an enrollment's completed_visit_count always equals the
    number of its visits currently in COMPLETED status."
    PRD 3.6: "Reversion moves the visit from `COMPLETED` back to `SCHEDULED`, clears `completed_date` and `on_time`, decrements the enrollment's `completed_visit_count` by 1, and recomputes dosage."

    Design: Difficulty/compensating_invariant/completed_visit_count_conserved_on_revert
    """
    ctx, visit = _active_enrollment_with_completed_visit()
    assert get_enrollment(ctx.enrollment_id)["completed_visit_count"] == 1
    validate_success(api.revert_completion(visit["id"], ctx.nurse_headers), 200)
    assert get_enrollment(ctx.enrollment_id)["completed_visit_count"] == 0


def test_revert_returns_visit_to_scheduled_and_clears_completed_date(api):
    """PRD 3.6: "Reversion moves the visit from `COMPLETED` back to `SCHEDULED`, clears `completed_date` and `on_time`, decrements the enrollment's `completed_visit_count` by 1, and recomputes dosage."

    Design: Difficulty/compensating_invariant/completed_visit_count_conserved_on_revert
    """
    ctx, visit = _active_enrollment_with_completed_visit()
    reverted = validate_success(api.revert_completion(visit["id"], ctx.nurse_headers), 200)
    assert reverted["status"] == "SCHEDULED"
    assert reverted["completed_date"] is None


# ─── Corner: supervision sign dispositions the alert ────
def test_signing_session_clears_review_and_pending_count(api):
    """PRD 3.9: "Signing advances the session from DRAFT to SIGNED and dispositions
    alerts: for each enrollment id in reviewed_enrollment_ids that currently carries a
    dosage_alert and has an ACTIVE assignment to this session's nurse, the system clears
    that assignment's review_required and decrements the nurse's
    pending_supervision_count by 1, never dropping it below 0."

    Design: Corner/state_machines/supervision_sign_clears_review_and_pending_count
    """
    ctx = setup_active_enrollment_with_dosage_alert()
    assert get_nurse(ctx.nurse_id)["pending_supervision_count"] == 1
    session = get_success_data(api_client.create_supervision_session(
        create_supervision_session_payload(
            ctx.nurse_id, ctx.supervisor_id, "2026-05-01", "2026-06-30",
            [ctx.enrollment_id],
        ),
        ctx.supervisor_headers,
    ))
    signed = validate_success(
        api.sign_supervision_session(session["id"], ctx.supervisor_headers), 200
    )
    assert signed["status"] == "SIGNED"
    assert get_nurse(ctx.nurse_id)["pending_supervision_count"] == 0
