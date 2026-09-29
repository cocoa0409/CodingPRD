"""Generating the evidence calendar, scheduling single periods, and the submit /
review loop that runs inside the observation window."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_evidence_request,
    create_control,
    create_engagement,
    lead_engagement_action,
    make_control_owner_headers,
    make_evidence_reviewer_headers,
    read_control,
    read_engagement,
    run_readiness_assessment,
    schedule_evidence,
    set_clock,
    setup_engagement_at,
    submit_evidence,
    validate_error,
    validate_paginated,
    validate_success,
)

CL_HEADERS = TEST_USERS["compliance_lead_headers"]
AUD_HEADERS = TEST_USERS["auditor_headers"]


def test_monthly_calendar_tiles_three_half_open_thirty_day_periods(api):
    """PRD 3.4: "Every other frequency has a period length in days — one day for `DAILY`,
    seven for `WEEKLY`, thirty for `MONTHLY`, ninety-one for `QUARTERLY` and three hundred
    sixty-five for `ANNUAL`."
    PRD 3.4: "The number of periods generated is the observation span in days divided by
    that period length, truncated downward to a whole number, so **a trailing partial
    period is not scheduled**."
    PRD 3.4: "Each generated row records that ordinal as `period_index`, its window as
    `period_start` and `period_end`, and a `due_date` of exactly five days after its
    `period_end`."
    PRD 3.4: "All generated rows are created in `SCHEDULED`, and the control's
    `evidence_scheduled_count` is set to the number of rows created."

    Design: Corner/calculations/corner_monthly_evidence_calendar_tiles_three_half_open_periods
    """
    engagement = create_engagement(client_name="Calendar")
    control = create_control(
        engagement["id"],
        control_ref="M-01",
        title="Monthly access review",
        frequency="MONTHLY",
        automation="MANUAL",
        risk_rating="MODERATE",
        population_size=12,
    )

    rows = validate_success(api.generate_evidence_calendar(control["id"], CL_HEADERS), 201)
    assert len(rows) == 3, f"floor(90 / 30) is 3 generated periods, got {len(rows)}"

    expected = [
        (0, "2026-09-01T00:00:00.000Z", "2026-10-01T00:00:00.000Z", "2026-10-06T00:00:00.000Z"),
        (1, "2026-10-01T00:00:00.000Z", "2026-10-31T00:00:00.000Z", "2026-11-05T00:00:00.000Z"),
        (2, "2026-10-31T00:00:00.000Z", "2026-11-30T00:00:00.000Z", "2026-12-05T00:00:00.000Z"),
    ]
    by_index = {row["period_index"]: row for row in rows}
    for index, start, end, due in expected:
        row = by_index[index]
        assert_evidence_request(row)
        assert row["period_start"] == start, f"period {index} start"
        assert row["period_end"] == end, f"period {index} end"
        assert row["due_date"] == due, f"period {index} due_date"
        assert row["status"] == "SCHEDULED"

    assert read_control(control["id"])["evidence_scheduled_count"] == 3


def test_adhoc_calendar_yields_a_single_full_window_period(api):
    """PRD 3.4: "A control whose frequency is `ADHOC` receives exactly one period spanning
    the entire observation window, from `observation_period_start` to
    `observation_period_end`."
    PRD 3.4: "Each generated row records that ordinal as `period_index`, its window as
    `period_start` and `period_end`, and a `due_date` of exactly five days after its
    `period_end`."

    Design: Corner/calculations/corner_adhoc_evidence_calendar_yields_one_full_window_period
    """
    engagement = create_engagement(client_name="AdHoc")
    control = create_control(
        engagement["id"],
        control_ref="A-01",
        title="Emergency change review",
        frequency="ADHOC",
        automation="MANUAL",
        risk_rating="LOW",
        population_size=3,
    )

    rows = validate_success(api.generate_evidence_calendar(control["id"], CL_HEADERS), 201)
    assert len(rows) == 1, f"An ADHOC control gets exactly one period, got {len(rows)}"
    row = rows[0]
    assert row["period_index"] == 0
    assert row["period_start"] == "2026-09-01T00:00:00.000Z"
    assert row["period_end"] == "2026-11-30T00:00:00.000Z"
    assert row["due_date"] == "2026-12-05T00:00:00.000Z"
    assert read_control(control["id"])["evidence_scheduled_count"] == 1


def test_a_control_may_only_generate_its_calendar_once(api):
    """PRD 3.4: "It requires the control to be in scope and not carved out, else
    `ERR_CONTROL_OUT_OF_SCOPE`, and it requires the control to carry no evidence request
    at all: a control that already has even one is rejected with
    `ERR_CALENDAR_ALREADY_GENERATED`."
    PRD 3.4: "Pre-existing rows are never deleted or merged."

    Design: Corner/validations/corner_evidence_calendar_cannot_be_generated_twice
    """
    engagement = create_engagement(client_name="Once Only")
    control = create_control(
        engagement["id"], control_ref="M-01", title="Monthly access review", frequency="MONTHLY"
    )
    validate_success(api.generate_evidence_calendar(control["id"], CL_HEADERS), 201)

    second = api.generate_evidence_calendar(control["id"], CL_HEADERS)
    validate_error(second, ApiErrorId.ERR_CALENDAR_ALREADY_GENERATED.value, 409)

    _, meta = validate_paginated(
        api.list_evidence_requests(CL_HEADERS, params={"control_id": control["id"]})
    )
    assert meta["total_count"] == 3, "The rejected second run must add no rows"
    assert read_control(control["id"])["evidence_scheduled_count"] == 3


def test_reject_and_resubmit_loop_increments_the_rejection_round(api):
    """PRD 3.4: "`SUBMITTED → REJECTED` increments `rejection_round` by one, stamps
    `reviewed_at` and `reviewed_by_user_id`, and increases the control's
    `evidence_scheduled_count` by one, returning the period to the owner's queue;
    `SUBMITTED → REJECTED → SUBMITTED` is the resubmission cycle and may be walked
    repeatedly."
    PRD 3.4: "The `REJECTED → SUBMITTED` edge stamps the same two operator fields and does
    not touch `evidence_scheduled_count`, which the rejection already restored."

    Design: Corner/state_machines/corner_evidence_reject_then_resubmit_increments_rejection_round
    """
    scenario = setup_engagement_at(phase="OBSERVATION", client_name="Loop")
    request_id = scenario["evidence"]["S-01"]["id"]
    set_clock("2026-10-05T00:00:00.000Z")

    submit_evidence(request_id, "own-1", "art-1")
    first = validate_success(
        api.review_evidence(
            request_id,
            {"action": "REJECT", "review_note": "Screenshot unreadable"},
            make_evidence_reviewer_headers("rev-1"),
        )
    )
    assert first["rejection_round"] == 1

    submit_evidence(request_id, "own-1", "art-2")
    second = validate_success(
        api.review_evidence(
            request_id,
            {"action": "REJECT", "review_note": "Period does not match"},
            make_evidence_reviewer_headers("rev-1"),
        )
    )
    assert second["rejection_round"] == 2

    final = submit_evidence(request_id, "own-1", "art-3")
    assert final["status"] == "SUBMITTED"
    assert final["rejection_round"] == 2
    assert final["artifact_ref"] == "art-3"
    assert final["submitted_by_user_id"] == "own-1"
    assert final["reviewed_by_user_id"] == "rev-1"
    assert final["late"] is False


def test_submitting_evidence_before_observation_opens_is_rejected(api):
    """PRD 3.4: "It is permitted from `SCHEDULED` and from `REJECTED`, and four conditions
    guard it: the engagement is in `OBSERVATION`; the engagement's posture is not
    `FROZEN`; the acting `X-User-ID` equals the control's `owner_user_id`, else
    `ERR_NOT_CONTROL_OWNER`; and the logical clock is at or before the request's
    `due_date`, else `ERR_EVIDENCE_WINDOW_CLOSED`."
    PRD 2.7: "**Engagement phase.** The engagement's `status` is a member of the phase set
    the operation requires, else `ERR_ENGAGEMENT_PHASE_INVALID` (409)."

    Design: Difficulty/cross_entity_state_dependency/evidence_submission_requires_engagement_in_observation_phase
    """
    scenario = setup_engagement_at(phase="READINESS", client_name="Bellevue")
    run_readiness_assessment(scenario["engagement_id"])
    request_id = scenario["evidence"]["S-01"]["id"]

    response = api.submit_evidence(
        request_id, {"artifact_ref": "art-early"}, make_control_owner_headers("own-1")
    )
    validate_error(response, ApiErrorId.ERR_ENGAGEMENT_PHASE_INVALID.value, 409)

    stored = validate_success(api.get_evidence_request(request_id, CL_HEADERS))
    assert stored["status"] == "SCHEDULED", "The rejected submit leaves the row SCHEDULED"
    assert stored["submitted_by_user_id"] is None
    assert read_engagement(scenario["engagement_id"])["status"] == "READINESS"


def test_the_same_submission_succeeds_once_the_engagement_reaches_observation(api):
    """PRD 3.4: "The transition cascades down: every in-scope control of the engagement has
    its `operating_status` set to `IN_OBSERVATION`, while controls that have already moved
    past `NOT_TESTED` are left untouched."
    PRD 3.4: "A successful submit stamps `submitted_at` from the logical clock and
    `submitted_by_user_id` from the header. On the `SCHEDULED → SUBMITTED` edge it also
    decreases the control's `evidence_scheduled_count` by one, and it sets `late` to
    whether `submitted_at` falls strictly after `due_date` — which on this edge is always
    false, since a late submission cannot get past the window check at all."

    Design: Difficulty/cross_entity_state_dependency/evidence_submission_requires_engagement_in_observation_phase
    """
    scenario = setup_engagement_at(phase="READINESS", client_name="Bellevue")
    run_readiness_assessment(scenario["engagement_id"])
    request_id = scenario["evidence"]["S-01"]["id"]
    control_id = scenario["controls"]["S-01"]["id"]

    rejected = api.submit_evidence(
        request_id, {"artifact_ref": "art-early"}, make_control_owner_headers("own-1")
    )
    assert rejected.status_code == 409

    lead_engagement_action(scenario["engagement_id"], "START_OBSERVATION")
    assert read_control(control_id)["operating_status"] == "IN_OBSERVATION"

    submitted = validate_success(
        api.submit_evidence(
            request_id, {"artifact_ref": "art-1"}, make_control_owner_headers("own-1")
        )
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == "own-1"
    assert submitted["late"] is False
    assert read_control(control_id)["evidence_scheduled_count"] == 0


def test_evidence_period_starting_at_the_previous_period_end_is_accepted(api):
    """PRD 3.4: "The half-open window must not intersect the half-open window of any
    existing evidence request on the same control whose `status` is anything other than
    `MISSED`; a collision is `ERR_EVIDENCE_PERIOD_OVERLAP`."
    PRD 3.4: "Touching endpoints — a new `period_start` exactly equal to an existing
    `period_end` — do not intersect and are accepted."
    PRD 3.4: "The row is created in `SCHEDULED`, its `due_date` is set to five days after
    its `period_end`, and the control's `evidence_scheduled_count` rises by one."

    Design: Difficulty/resource_temporal_overlap/evidence_periods_on_a_control_are_half_open_so_adjacency_is_legal
    """
    engagement = create_engagement(client_name="Skyline")
    control = create_control(
        engagement["id"],
        control_ref="E-01",
        title="Monthly log review",
        frequency="MONTHLY",
        automation="MANUAL",
        risk_rating="MODERATE",
        population_size=20,
    )

    first = validate_success(
        api.create_evidence_request(
            {
                "control_id": control["id"],
                "period_index": 0,
                "period_start": "2026-09-01T00:00:00.000Z",
                "period_end": "2026-10-01T00:00:00.000Z",
            },
            CL_HEADERS,
        ),
        201,
    )
    assert first["status"] == "SCHEDULED"
    assert first["due_date"] == "2026-10-06T00:00:00.000Z"

    adjacent = validate_success(
        api.create_evidence_request(
            {
                "control_id": control["id"],
                "period_index": 1,
                "period_start": "2026-10-01T00:00:00.000Z",
                "period_end": "2026-11-01T00:00:00.000Z",
            },
            CL_HEADERS,
        ),
        201,
    )
    assert adjacent["status"] == "SCHEDULED"
    assert adjacent["period_start"] == first["period_end"], (
        "The adjacent period begins exactly where the first one ends"
    )


def test_evidence_period_straddling_an_existing_one_is_rejected(api):
    """PRD 3.4: "The half-open window must not intersect the half-open window of any
    existing evidence request on the same control whose `status` is anything other than
    `MISSED`; a collision is `ERR_EVIDENCE_PERIOD_OVERLAP`."
    PRD 3.4: "The row is created in `SCHEDULED`, its `due_date` is set to five days after
    its `period_end`, and the control's `evidence_scheduled_count` rises by one."

    Design: Difficulty/resource_temporal_overlap/evidence_periods_on_a_control_are_half_open_so_adjacency_is_legal
    """
    engagement = create_engagement(client_name="Skyline")
    control = create_control(
        engagement["id"],
        control_ref="E-01",
        title="Monthly log review",
        frequency="MONTHLY",
        automation="MANUAL",
        risk_rating="MODERATE",
        population_size=20,
    )
    schedule_evidence(
        control["id"], 0, "2026-09-01T00:00:00.000Z", "2026-10-01T00:00:00.000Z"
    )
    schedule_evidence(
        control["id"], 1, "2026-10-01T00:00:00.000Z", "2026-11-01T00:00:00.000Z"
    )

    straddling = api.create_evidence_request(
        {
            "control_id": control["id"],
            "period_index": 2,
            "period_start": "2026-10-15T00:00:00.000Z",
            "period_end": "2026-11-15T00:00:00.000Z",
        },
        CL_HEADERS,
    )
    validate_error(straddling, ApiErrorId.ERR_EVIDENCE_PERIOD_OVERLAP.value, 409)

    _, meta = validate_paginated(
        api.list_evidence_requests(CL_HEADERS, params={"control_id": control["id"]})
    )
    assert meta["total_count"] == 2, "The straddling period must not be stored"
    assert read_control(control["id"])["evidence_scheduled_count"] == 2


def test_off_owner_late_submission_reports_the_ownership_breach(api):
    """PRD 3.4: "It is permitted from `SCHEDULED` and from `REJECTED`, and four conditions
    guard it: the engagement is in `OBSERVATION`; the engagement's posture is not
    `FROZEN`; the acting `X-User-ID` equals the control's `owner_user_id`, else
    `ERR_NOT_CONTROL_OWNER`; and the logical clock is at or before the request's
    `due_date`, else `ERR_EVIDENCE_WINDOW_CLOSED`."
    PRD 2.7: "**Control ownership** on evidence submission, else `ERR_NOT_CONTROL_OWNER`
    (403). This runs *before* the submission-window check at step 25, so an off-owner
    submission made after the due date reports the ownership breach rather than the closed
    window."

    Design: Difficulty/priority_pair_validation_conflict/control_ownership_safety_beats_evidence_window_temporal
    """
    scenario = setup_engagement_at(
        phase="OBSERVATION",
        client_name="Adventure",
        controls=[
            {
                "control_ref": "S-01",
                "evidence_period": ("2026-09-01T00:00:00.000Z", "2026-10-01T00:00:00.000Z"),
            }
        ],
    )
    request_id = scenario["evidence"]["S-01"]["id"]
    set_clock("2026-10-20T00:00:00.000Z")

    response = api.submit_evidence(
        request_id, {"artifact_ref": "art-late"}, make_control_owner_headers("own-9")
    )
    validate_error(response, ApiErrorId.ERR_NOT_CONTROL_OWNER.value, 403)


def test_off_owner_late_submission_leaves_the_request_untouched(api):
    """PRD 3.4: "Because the ownership check runs first, an outsider submitting after the
    deadline is told about the ownership breach and not about the window."
    PRD 3.4: "The row is created in `SCHEDULED`, its `due_date` is set to five days after
    its `period_end`, and the control's `evidence_scheduled_count` rises by one."

    Design: Difficulty/priority_pair_validation_conflict/control_ownership_safety_beats_evidence_window_temporal
    """
    scenario = setup_engagement_at(
        phase="OBSERVATION",
        client_name="Adventure",
        controls=[
            {
                "control_ref": "S-01",
                "evidence_period": ("2026-09-01T00:00:00.000Z", "2026-10-01T00:00:00.000Z"),
            }
        ],
    )
    request_id = scenario["evidence"]["S-01"]["id"]
    control_id = scenario["controls"]["S-01"]["id"]
    set_clock("2026-10-20T00:00:00.000Z")

    rejected = api.submit_evidence(
        request_id, {"artifact_ref": "art-late"}, make_control_owner_headers("own-9")
    )
    assert rejected.status_code == 403

    stored = validate_success(api.get_evidence_request(request_id, CL_HEADERS))
    assert stored["status"] == "SCHEDULED"
    assert stored["submitted_by_user_id"] is None
    assert stored["due_date"] == "2026-10-06T00:00:00.000Z", (
        "due_date is five days after the 2026-10-01 period end"
    )
    assert read_control(control_id)["evidence_scheduled_count"] == 1
