"""Pooled MIECHV on-time reporting, the depth-3 disenrollment closure cascade, and
filtered enrollment listing."""
import pytest
from test_helpers import (
    validate_success,
    validate_paginated,
    schedule_visit,
    create_client,
    create_prospect_enrollment,
    get_nurse,
    setup_active_enrollment,
    setup_program_on_time_report,
)


# ─── Difficulty: pooled program on-time rate ────────────
def test_finalize_transitions_report_to_finalized(api, program_admin_headers):
    """PRD 3.9: "Finalizing advances a DRAFT report to FINALIZED and freezes three
    figures as of the current logical clock."

    Design: Difficulty/combinatorial_formula/program_on_time_rate_pooled_not_averaged
    """
    report_id = setup_program_on_time_report()
    finalized = validate_success(
        api.finalize_miechv_report(report_id, program_admin_headers), 200
    )
    assert finalized["status"] == "FINALIZED"


def test_program_on_time_rate_is_pooled_not_averaged(api, program_admin_headers):
    """PRD 3.9: "the numerator and denominator are pooled across all in-scope
    enrollments first and the rate is computed exactly once as 100 multiplied by the
    numerator and divided by the denominator, rounded half-up to two decimal places.
    This pooled-then-rounded order is required; averaging per-enrollment rounded rates
    is not an acceptable substitute."

    Design: Difficulty/combinatorial_formula/program_on_time_rate_pooled_not_averaged
    """
    report_id = setup_program_on_time_report()
    finalized = validate_success(
        api.finalize_miechv_report(report_id, program_admin_headers), 200
    )
    # Pooled 2/3 = 66.67; the forbidden average of (50.00, 100.00) would be 75.00.
    assert finalized["program_on_time_rate_pct"] == pytest.approx(66.67, abs=0.01)
    assert finalized["program_on_time_rate_pct"] != pytest.approx(75.00, abs=0.01)


# ─── Difficulty: disenroll closure cascade (depth 3) ────
def _active_enrollment_with_future_visit():
    ctx = setup_active_enrollment()  # PREGNANCY, weight 1.0
    visit = schedule_visit(
        ctx, target_date="2026-06-10",
        scheduled_start="2026-06-10T09:00:00Z", scheduled_end="2026-06-10T10:00:00Z",
    )
    return ctx, visit


def test_disenroll_exits_enrollment_and_ends_assignment(api, intake_headers):
    """PRD 3.2: "When the enrollment being disenrolled was ACTIVE, disenrollment drives
    the same closure cascade as graduation: its ACTIVE assignments transition to ENDED,
    each ended assignment subtracts its caseload_weight from the nurse's
    current_caseload_weight (which is then recomputed over the nurse's remaining active
    assignments), and every SCHEDULED visit for the enrollment transitions to CANCELED."

    Design: Difficulty/transitive_cascade/disenroll_cascade_release_caseload_and_cancel_visits_depth3
    """
    ctx, _visit = _active_enrollment_with_future_visit()
    exited = validate_success(api.disenroll(ctx.enrollment_id, intake_headers), 200)
    assert exited["status"] == "EXITED"
    assignment = validate_success(
        api.get_assignment(ctx.assignment_id, ctx.supervisor_headers), 200)
    assert assignment["status"] == "ENDED"


def test_disenroll_releases_caseload_and_cancels_visits(api, intake_headers):
    """PRD 3.2: "When the enrollment being disenrolled was ACTIVE, disenrollment drives
    the same closure cascade as graduation: its ACTIVE assignments transition to ENDED,
    each ended assignment subtracts its caseload_weight from the nurse's
    current_caseload_weight (which is then recomputed over the nurse's remaining active
    assignments), and every SCHEDULED visit for the enrollment transitions to CANCELED."

    Design: Difficulty/transitive_cascade/disenroll_cascade_release_caseload_and_cancel_visits_depth3
    """
    ctx, visit = _active_enrollment_with_future_visit()
    validate_success(api.disenroll(ctx.enrollment_id, intake_headers), 200)
    nurse = get_nurse(ctx.nurse_id)
    assert nurse["current_caseload_weight"] == pytest.approx(0.0, abs=0.001)
    canceled = validate_success(api.get_visit(visit["id"], ctx.nurse_headers), 200)
    assert canceled["status"] == "CANCELED"


# ─── Corner: filtered, paginated enrollment listing ─────
def test_enrollments_list_filtered_by_client_is_paginated(api, intake_headers):
    """PRD 2.3: "any additional filters an endpoint offers are applied before
    pagination."
    PRD 2.3: "total_count reports the number of records matching the filters before the
    limit/offset window is applied, and has_more is true when records remain beyond the
    current window."

    Design: Corner/endpoints/enrollments_list_is_paginated
    """
    c1 = create_client(full_name="C L1", gestational_age_weeks=18)
    e1 = create_prospect_enrollment(c1["id"])
    c2 = create_client(full_name="C L2", gestational_age_weeks=19)
    create_prospect_enrollment(c2["id"])

    data, meta = validate_paginated(
        api.list_enrollments(intake_headers, params={"client_id": c1["id"]})
    )
    assert len(data) == 1
    assert data[0]["id"] == e1["id"]
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
