"""The examination cycle: scheduling window rules, composite rating bands,
appeal loop, performance-context narrative, finalization and its cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    assign_ratings,
    create_active_area,
    create_complete_public_file,
    create_draft_application,
    create_exam_at_preliminary_rating,
    create_exam_cycle_payload,
    create_finalized_exam,
    create_scheduled_exam,
    create_submitted_branch_opening,
    get_application,
    get_branch,
    get_exam,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)


def _setup_fieldwork_ready_exam(api, bank_examiner_headers, window=("2024-01-01", "2024-12-31")):
    """Public file COMPLETE + exam driven to FIELDWORK."""
    create_active_area(area_code=f"AA-FW-{window[0][:4]}", census_tracts=["T1"])
    create_complete_public_file("Fieldwork Bank")
    exam = create_scheduled_exam(*window)
    validate_success(api.begin_data_collection(exam["id"], bank_examiner_headers))
    validate_success(api.begin_fieldwork(exam["id"], bank_examiner_headers))
    return exam


# ---------------------------------------------------------------------------
# Queue B — Corner/state_machines
# ---------------------------------------------------------------------------

def test_exam_appeal_cycle_recomputes_composite(
    api, cra_officer_headers, bank_examiner_headers,
):
    """PRD §3.7: "The appeal cycle `PRELIMINARY_RATING → APPEALED → FIELDWORK →
    PRELIMINARY_RATING` may repeat, and each fresh rating assignment recomputes
    the composite from the newly supplied test ratings."
    PRD §3.7: "a `CRAOfficer` moves the exam from `PRELIMINARY_RATING` to
    `APPEALED` with a recorded `appeal_reason`".

    Design: Corner/state_machines/exam_appeal_cycle_recomputes_composite
    """
    exam = _setup_fieldwork_ready_exam(api, bank_examiner_headers)
    first = assign_ratings(exam["id"], "SATISFACTORY", "SATISFACTORY", "NEEDS_TO_IMPROVE")
    assert first["composite_points"] == pytest.approx(5.0, abs=1e-9)
    assert first["composite_rating"] == "SATISFACTORY"

    appealed = validate_success(
        api.appeal_exam(exam["id"], {"appeal_reason": "new CD evidence submitted"},
                        cra_officer_headers)
    )
    assert appealed["status"] == "APPEALED"
    validate_success(api.reopen_fieldwork(exam["id"], bank_examiner_headers))

    second = assign_ratings(exam["id"], "OUTSTANDING", "OUTSTANDING", "SATISFACTORY")
    # 0.5*10 + 0.25*10 + 0.25*6 = 5 + 2.5 + 1.5 = 9.0
    assert second["composite_points"] == pytest.approx(9.0, abs=1e-9)
    assert second["composite_rating"] == "OUTSTANDING"
    assert second["status"] == "PRELIMINARY_RATING"
    assert second["appeal_reason"] == "new CD evidence submitted"


def test_finalized_exam_is_terminal(api, cra_officer_headers, bank_examiner_headers):
    """PRD §3.7: "Finalization moves `PRELIMINARY_RATING → FINALIZED`, the
    terminal state."
    PRD §2.11: "State legality — a trigger that does not match the resource's
    current state, or any action on a terminal-state resource, yields
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/finalized_exam_is_terminal
    """
    create_active_area(area_code="AA-SM5", msa_code="19100", state_code="TX",
                       census_tracts=["T1"])
    create_complete_public_file("Final Bank")
    exam = create_finalized_exam(
        "SATISFACTORY", "SATISFACTORY", "SATISFACTORY", "2024-01-01", "2024-12-31"
    )
    assert exam["status"] == "FINALIZED"

    resp = api.appeal_exam(exam["id"], {"appeal_reason": "too late"}, cra_officer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_exam(exam["id"])["status"] == "FINALIZED"


# ---------------------------------------------------------------------------
# Queue B — Corner/calculations
# ---------------------------------------------------------------------------

def test_composite_outstanding_band_and_finalize_without_cascade(
    api, bank_examiner_headers,
):
    """PRD §3.7: "The `composite_rating` bands are inclusive at their lower
    boundaries: at least 8.50 is `OUTSTANDING`, at least 5.00 is `SATISFACTORY`,
    at least 2.50 is `NEEDS_TO_IMPROVE`, and anything below is
    `SUBSTANTIAL_NONCOMPLIANCE`."
    PRD §3.7: "Favorable ratings finalize with no cascade."

    Design: Corner/calculations/composite_outstanding_band_and_finalize_without_cascade
    """
    create_active_area(area_code="AA-C3", census_tracts=["T1"])
    create_complete_public_file("Outstanding Bank")
    exam = create_exam_at_preliminary_rating(
        "OUTSTANDING", "OUTSTANDING", "SATISFACTORY", "2024-01-01", "2024-12-31"
    )
    # 0.5*10 + 0.25*10 + 0.25*6 = 9.0 >= 8.50
    assert exam["composite_points"] == pytest.approx(9.0, abs=1e-9)
    assert exam["composite_rating"] == "OUTSTANDING"

    finalized = validate_success(api.finalize_exam(exam["id"], bank_examiner_headers))
    assert finalized["status"] == "FINALIZED"


# ---------------------------------------------------------------------------
# Queue B — Corner/validations
# ---------------------------------------------------------------------------

def test_exam_window_end_before_start_invalid(api, bank_examiner_headers):
    """PRD §3.7: "Independently, `evaluation_window_end` must be on or after
    `evaluation_window_start`, else `ERR_INVALID_WINDOW`."

    Design: Corner/validations/exam_window_end_before_start_invalid
    """
    resp = api.create_exam_cycle(
        create_exam_cycle_payload(
            evaluation_window_start="2024-12-31", evaluation_window_end="2024-01-01"
        ),
        bank_examiner_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)


# ---------------------------------------------------------------------------
# Queue B — Corner/endpoints
# ---------------------------------------------------------------------------

def test_performance_context_editable_only_before_rating(
    api, cra_officer_headers, bank_examiner_headers,
):
    """PRD §3.7: "The narrative stays editable through the early phases: while
    the exam is `SCHEDULED`, `DATA_COLLECTION`, or `FIELDWORK`, a `CRAOfficer`
    may replace the `performance_context_narrative`, incrementing the exam's
    `version`; once the exam has moved past fieldwork the edit is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/endpoints/performance_context_editable_only_before_rating
    """
    exam = _setup_fieldwork_ready_exam(api, bank_examiner_headers)

    edited = validate_success(
        api.patch_performance_context(
            exam["id"],
            {"performance_context_narrative": "Tight deposit competition in the MSA."},
            cra_officer_headers,
        )
    )
    assert edited["performance_context_narrative"] == (
        "Tight deposit competition in the MSA."
    )

    assign_ratings(exam["id"], "SATISFACTORY", "SATISFACTORY", "SATISFACTORY")
    late = api.patch_performance_context(
        exam["id"], {"performance_context_narrative": "Late edit attempt."},
        cra_officer_headers,
    )
    validate_error(late, ApiErrorId.ERR_INVALID_STATE)
    assert get_exam(exam["id"])["performance_context_narrative"] == (
        "Tight deposit competition in the MSA."
    )


# ---------------------------------------------------------------------------
# Queue A — Difficulty/boundary_precision_check/composite_points_exactly_5_maps_satisfactory
# ---------------------------------------------------------------------------

def test_composite_points_exactly_5_maps_satisfactory(
    api, bank_examiner_headers, bank_executive_headers,
):
    """PRD §3.7: "The `composite_rating` bands are inclusive at their lower
    boundaries: at least 8.50 is `OUTSTANDING`, at least 5.00 is `SATISFACTORY`,
    at least 2.50 is `NEEDS_TO_IMPROVE`, and anything below is
    `SUBSTANTIAL_NONCOMPLIANCE`."
    PRD §3.7: "The composite maps ratings to points — `OUTSTANDING` 10,
    `SATISFACTORY` 6, `NEEDS_TO_IMPROVE` 2, `SUBSTANTIAL_NONCOMPLIANCE` 0 — and
    weights lending at one half with investment and service at one quarter
    each".

    Design: Difficulty/boundary_precision_check/composite_points_exactly_5_maps_satisfactory
    """
    area = create_active_area(area_code="AA-BP1", msa_code="12060", state_code="GA",
                              census_tracts=["T1"])
    create_complete_public_file("Boundary Bank")
    exam = create_exam_at_preliminary_rating(
        "SATISFACTORY", "SATISFACTORY", "NEEDS_TO_IMPROVE",
        "2024-01-01", "2024-12-31",
    )
    # 0.5*6 + 0.25*6 + 0.25*2 = 3 + 1.5 + 0.5 = 5.0 -> SATISFACTORY (inclusive).
    assert exam["composite_points"] == pytest.approx(5.0, abs=1e-9)
    assert exam["composite_rating"] == "SATISFACTORY"

    # PRD §3.8: a latest finalized rating of SATISFACTORY passes the guard —
    # the finalized exam "must carry a `composite_rating` of `OUTSTANDING` or
    # `SATISFACTORY`".
    validate_success(api.finalize_exam(exam["id"], bank_examiner_headers))
    app = create_draft_application(area["id"], "MERGER")
    submitted = submit_application(app["id"])
    assert submitted["status"] == "SUBMITTED"


def test_composite_points_exactly_2_5_maps_needs_to_improve(api, bank_examiner_headers):
    """PRD §3.7: "The `composite_rating` bands are inclusive at their lower
    boundaries: at least 8.50 is `OUTSTANDING`, at least 5.00 is `SATISFACTORY`,
    at least 2.50 is `NEEDS_TO_IMPROVE`, and anything below is
    `SUBSTANTIAL_NONCOMPLIANCE`."

    Design: Difficulty/boundary_precision_check/composite_points_exactly_5_maps_satisfactory
    """
    create_active_area(area_code="AA-BP1B", msa_code="12060", state_code="GA",
                       census_tracts=["T1"])
    create_complete_public_file("Boundary Bank Two")
    exam = create_exam_at_preliminary_rating(
        "NEEDS_TO_IMPROVE", "SATISFACTORY", "SUBSTANTIAL_NONCOMPLIANCE",
        "2024-01-01", "2024-12-31",
    )
    # 0.5*2 + 0.25*6 + 0.25*0 = 1 + 1.5 + 0 = 2.5 -> NEEDS_TO_IMPROVE (inclusive).
    assert exam["composite_points"] == pytest.approx(2.5, abs=1e-9)
    assert exam["composite_rating"] == "NEEDS_TO_IMPROVE"


# ---------------------------------------------------------------------------
# Queue A — Difficulty/transitive_cascade/exam_finalize_cascade_denies_application_withdraws_branch
# ---------------------------------------------------------------------------

def test_exam_finalize_cascade_denies_application_withdraws_branch(
    api, bank_examiner_headers,
):
    """PRD §3.7: "When the finalized `composite_rating` is `NEEDS_TO_IMPROVE` or
    `SUBSTANTIAL_NONCOMPLIANCE`, the rating cascades outward in a three-deep
    chain: every expansion application sitting in `SUBMITTED` flips to `DENIED`
    with `decision_reason` recorded as `RATING_BLOCK`, and each such application
    whose `linked_branch_id` is non-null drags its staged branch from `PROPOSED`
    to `WITHDRAWN`."

    Design: Difficulty/transitive_cascade/exam_finalize_cascade_denies_application_withdraws_branch
    """
    area = create_active_area(
        area_code="AA-TC1", census_tracts=["T1", "T2"], annual_cd_budget_cents=10000000,
    )
    app, branch_id = create_submitted_branch_opening(
        area["id"], branch_code="BR-NEW", branch_census_tract="T1",
        branch_tract_income_level="MODERATE",
    )
    create_complete_public_file("First Test Bank")
    exam = create_exam_at_preliminary_rating(
        "NEEDS_TO_IMPROVE", "SATISFACTORY", "SATISFACTORY",
        "2024-01-01", "2024-12-31",
    )
    # 0.5*2 + 0.25*6 + 0.25*6 = 4.0 -> NEEDS_TO_IMPROVE.
    assert exam["composite_points"] == pytest.approx(4.0, abs=1e-9)
    assert exam["composite_rating"] == "NEEDS_TO_IMPROVE"

    finalized = validate_success(api.finalize_exam(exam["id"], bank_examiner_headers))
    assert finalized["status"] == "FINALIZED"

    app_after = get_application(app["id"])
    assert app_after["status"] == "DENIED"
    assert app_after["decision_reason"] == "RATING_BLOCK"

    branches, meta = validate_paginated(
        api.list_application_branches(app["id"], bank_examiner_headers)
    )
    assert meta["total_count"] == 1
    assert branches[0]["id"] == branch_id
    assert branches[0]["status"] == "WITHDRAWN"
    assert get_branch(branch_id)["status"] == "WITHDRAWN"


def test_exam_finalize_substantial_noncompliance_also_cascades(
    api, bank_examiner_headers,
):
    """PRD §3.7: "When the finalized `composite_rating` is `NEEDS_TO_IMPROVE` or
    `SUBSTANTIAL_NONCOMPLIANCE`, the rating cascades outward in a three-deep
    chain: every expansion application sitting in `SUBMITTED` flips to `DENIED`
    with `decision_reason` recorded as `RATING_BLOCK`, and each such application
    whose `linked_branch_id` is non-null drags its staged branch from `PROPOSED`
    to `WITHDRAWN`."

    Design: Difficulty/transitive_cascade/exam_finalize_cascade_denies_application_withdraws_branch
    """
    area = create_active_area(
        area_code="AA-TC1B", census_tracts=["T1"], annual_cd_budget_cents=10000000,
    )
    submitted_app = create_draft_application(area["id"], "MERGER")
    submit_application(submitted_app["id"])
    draft_app = create_draft_application(area["id"], "BRANCH_CLOSURE")

    create_complete_public_file("Cascade Bank")
    exam = create_exam_at_preliminary_rating(
        "SUBSTANTIAL_NONCOMPLIANCE", "SUBSTANTIAL_NONCOMPLIANCE",
        "SUBSTANTIAL_NONCOMPLIANCE", "2024-01-01", "2024-12-31",
    )
    assert exam["composite_points"] == pytest.approx(0.0, abs=1e-9)
    assert exam["composite_rating"] == "SUBSTANTIAL_NONCOMPLIANCE"

    validate_success(api.finalize_exam(exam["id"], bank_examiner_headers))

    # Only applications sitting in SUBMITTED are caught by the cascade.
    denied = get_application(submitted_app["id"])
    assert denied["status"] == "DENIED"
    assert denied["decision_reason"] == "RATING_BLOCK"
    assert get_application(draft_app["id"])["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Queue A — Difficulty/resource_temporal_overlap/exam_window_closed_interval_date_sharing
# ---------------------------------------------------------------------------

def test_exam_window_closed_interval_date_sharing(api, bank_examiner_headers):
    """PRD §3.7: "Evaluation windows are closed intervals, so no exam's window
    may share even a single calendar date with any other exam's window
    regardless of that exam's status; touching endpoints conflict, and a
    violation is `ERR_EXAM_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/exam_window_closed_interval_date_sharing
    """
    first = create_scheduled_exam("2024-01-01", "2024-12-31")
    assert first["status"] == "SCHEDULED"

    # Sharing the single calendar date 2024-12-31 conflicts (closed interval).
    overlap = api.create_exam_cycle(
        create_exam_cycle_payload(
            evaluation_window_start="2024-12-31", evaluation_window_end="2025-12-31"
        ),
        bank_examiner_headers,
    )
    validate_error(overlap, ApiErrorId.ERR_EXAM_WINDOW_OVERLAP)

    # Starting the day after shares no date and succeeds.
    adjacent = validate_success(
        api.create_exam_cycle(
            create_exam_cycle_payload(
                evaluation_window_start="2025-01-01", evaluation_window_end="2025-12-31"
            ),
            bank_examiner_headers,
        ),
        201,
    )
    assert adjacent["status"] == "SCHEDULED"


def test_exam_window_overlap_regardless_of_other_exam_status(api, bank_examiner_headers):
    """PRD §3.7: "Evaluation windows are closed intervals, so no exam's window
    may share even a single calendar date with any other exam's window
    regardless of that exam's status; touching endpoints conflict, and a
    violation is `ERR_EXAM_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/exam_window_closed_interval_date_sharing
    """
    first = create_scheduled_exam("2024-01-01", "2024-12-31")
    validate_success(api.begin_data_collection(first["id"], bank_examiner_headers))

    overlap = api.create_exam_cycle(
        create_exam_cycle_payload(
            evaluation_window_start="2024-06-01", evaluation_window_end="2025-05-31"
        ),
        bank_examiner_headers,
    )
    validate_error(overlap, ApiErrorId.ERR_EXAM_WINDOW_OVERLAP)
