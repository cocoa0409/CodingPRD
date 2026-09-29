"""Study creation, the moderator-guide sub-machine and the gates on fielding.

Every test in this module builds its own preconditions: the server is relaunched
with an empty database before each one, and the logical clock starts at exactly
2026-08-01T00:00:00Z.
"""

import pytest

from test_helpers import (
    RESEARCHER_HEADERS,
    RESEARCH_LEAD_HEADERS,
    ApiErrorId,
    approve_guide,
    create_pool,
    create_request,
    create_study,
    create_study_payload,
    read_metrics,
    read_request,
    read_study,
    setup_approved_request,
    setup_guide_approved_study,
    setup_locked_decision_on_dual_findings,
    setup_pool_with_participants,
    setup_scheduled_sessions,
    validate_error,
    validate_paginated,
    validate_success,
    write_guide,
)

FIELDING_START = "2026-08-03T00:00:00Z"
FIELDING_END = "2026-08-21T00:00:00Z"
CLOCK_START = "2026-08-01T00:00:00.000Z"


# ===========================================================================
# The study entity: listing, required fields and declared enums
# ===========================================================================
def test_studies_list_filters_by_execution_status_before_paginating(api):
    """The execution_status filter narrows the set that total_count and has_more describe.

    PRD 2.3: "List responses carry `response_type` of `"array"` and populate
    four pagination fields in `meta`: `limit` (the effective page size actually
    applied), `offset` (the effective starting index), `total_count` (the number
    of rows matching the filters before the page window is applied) and
    `has_more` (true when rows remain beyond the current window)."

    PRD 2.3: "Filters on list endpoints are additive: supplying several narrows
    the result set, and pagination is applied after filtering."

    Design: Corner/entities/studies_list_filters_by_execution_status_and_paginates
    """
    first_intake = setup_approved_request(api, method="INTERVIEW")
    second_intake = setup_approved_request(
        api, method="INTERVIEW", decision=first_intake["decision"]
    )
    pool = create_pool(api, incentive_budget_cents=50000)

    first_study = create_study(
        first_intake["request"]["id"],
        pool["id"],
        api,
        method="INTERVIEW",
        target_participant_count=2,
        incentive_amount_cents=4000,
        fielding_start=FIELDING_START,
        fielding_end="2026-08-10T00:00:00Z",
    )
    second_study = create_study(
        second_intake["request"]["id"],
        pool["id"],
        api,
        method="INTERVIEW",
        target_participant_count=2,
        incentive_amount_cents=4000,
        fielding_start="2026-08-11T00:00:00Z",
        fielding_end="2026-08-18T00:00:00Z",
    )

    planned_page = api.list_studies(
        RESEARCHER_HEADERS,
        {
            "participant_pool_id": pool["id"],
            "execution_status": "PLANNED",
            "limit": 1,
            "offset": 0,
        },
    )
    rows, meta = validate_paginated(planned_page)

    assert len(rows) == 1, f"Expected 1 row on a limit=1 page, got {len(rows)}"
    assert meta["total_count"] == 2, (
        f"Expected total_count 2 for the two PLANNED studies of the pool, "
        f"got {meta['total_count']}"
    )
    assert meta["has_more"] is True, (
        f"Expected has_more true with 2 matching rows on a page of 1, "
        f"got {meta['has_more']}"
    )
    assert meta["limit"] == 1, f"Expected effective limit 1, got {meta['limit']}"
    assert meta["offset"] == 0, f"Expected effective offset 0, got {meta['offset']}"
    assert rows[0]["id"] in {first_study["id"], second_study["id"]}, (
        f"Expected the page to hold one of the two studies of the pool, "
        f"got {rows[0]['id']}"
    )
    assert rows[0]["execution_status"] == "PLANNED", (
        f"Expected the filtered row to be PLANNED, got {rows[0]['execution_status']}"
    )

    fielding_page = api.list_studies(
        RESEARCHER_HEADERS,
        {"participant_pool_id": pool["id"], "execution_status": "FIELDING"},
    )
    fielding_rows, fielding_meta = validate_paginated(fielding_page)

    assert fielding_rows == [], (
        f"Expected no FIELDING studies of the pool, got {len(fielding_rows)} rows"
    )
    assert fielding_meta["total_count"] == 0, (
        f"Expected total_count 0 for the FIELDING filter, "
        f"got {fielding_meta['total_count']}"
    )
    assert fielding_meta["has_more"] is False, (
        f"Expected has_more false on an empty filtered set, "
        f"got {fielding_meta['has_more']}"
    )


def test_study_creation_without_fielding_end_is_an_invalid_request(api):
    """A missing required body field is reported before the method/approved_method join.

    PRD 2.6: "This covers a missing required field, an enum field carrying a
    value outside its declared members, an integer that is negative or zero where
    the constraint demands otherwise, `fielding_end` not strictly after
    `fielding_start`, `scheduled_end` not strictly after `scheduled_start`, a
    `screening_criteria` or `screening_answers` object that does not carry exactly
    its declared keys, a `scopes` array that is empty or contains duplicates or a
    member outside `RECORDING`, `TRANSCRIPT` and `PII_QUOTE`, a `count` below 1 on
    batch invitation, and a `limit` or `offset` outside the ranges in §2.3."

    PRD 2.6: "Because a single request can violate several rules at once, the
    platform evaluates checks in a fixed precedence and returns the **first**
    failure it finds."

    Design: Corner/entities/study_creation_missing_required_fielding_end_returns_invalid_request
    """
    intake = setup_approved_request(api, method="INTERVIEW")
    pool = create_pool(api, incentive_budget_cents=50000)

    payload = create_study_payload(
        intake["request"]["id"],
        pool["id"],
        method="SURVEY",
        target_participant_count=2,
        incentive_amount_cents=4000,
        fielding_start=FIELDING_START,
    )
    del payload["fielding_end"]

    response = api.create_study(payload, RESEARCHER_HEADERS)
    error = validate_error(response, ApiErrorId.INVALID_REQUEST.value)

    assert error["error_id"] != ApiErrorId.METHOD_NOT_APPROVED.value, (
        "The mismatched SURVEY method must not be reported: body validity is "
        f"checked before the method join, got {error['error_id']}"
    )
    assert read_request(intake["request"]["id"], api)["status"] == "APPROVED", (
        "A rejected study creation must leave the request APPROVED, never IN_STUDY"
    )


def test_study_creation_with_an_undeclared_method_or_inverted_window_is_rejected(api):
    """A method outside the declared enum and an inverted fielding window are both 400s.

    PRD 3.3: "The payload names the `research_request_id` of the request being
    executed and the `participant_pool_id` of the single pool the study will
    recruit from; it declares the `method` to be used, one of `INTERVIEW`,
    `USABILITY_TEST`, `DIARY_STUDY` or `SURVEY`; it sets a
    `target_participant_count` of at least 1 as the completed-session goal; it
    carries the `screening_criteria` rubric; it fixes the base per-participant
    `incentive_amount_cents`, which must be zero or greater; and it declares the
    intended fielding window as `fielding_start` and `fielding_end`, where
    `fielding_end` must be strictly after `fielding_start`."

    Design: Corner/entities/study_creation_with_unknown_method_enum_is_rejected
    """
    intake = setup_approved_request(api, method="INTERVIEW")
    pool = create_pool(api, incentive_budget_cents=50000)
    request_id = intake["request"]["id"]

    unknown_method = api.create_study(
        create_study_payload(
            request_id,
            pool["id"],
            method="FOCUS_GROUP",
            target_participant_count=2,
            incentive_amount_cents=4000,
            fielding_start=FIELDING_START,
            fielding_end="2026-08-10T00:00:00Z",
        ),
        RESEARCHER_HEADERS,
    )
    validate_error(unknown_method, ApiErrorId.INVALID_REQUEST.value)

    inverted_window = api.create_study(
        create_study_payload(
            request_id,
            pool["id"],
            method="INTERVIEW",
            target_participant_count=2,
            incentive_amount_cents=4000,
            fielding_start="2026-08-10T00:00:00Z",
            fielding_end=FIELDING_START,
        ),
        RESEARCHER_HEADERS,
    )
    validate_error(inverted_window, ApiErrorId.INVALID_REQUEST.value)

    rows, meta = validate_paginated(
        api.list_studies(RESEARCHER_HEADERS, {"research_request_id": request_id})
    )
    assert meta["total_count"] == 0, (
        f"Expected no study rows for the request after two rejected creations, "
        f"got {meta['total_count']}"
    )
    assert rows == [], f"Expected an empty study list, got {len(rows)} rows"
    assert read_request(request_id, api)["status"] == "APPROVED", (
        "Neither rejected creation may drag the request from APPROVED to IN_STUDY"
    )


# ===========================================================================
# Two state dimensions, the guide sub-machine and the close-fielding guard
# ===========================================================================
def test_study_creation_opens_both_state_dimensions_and_moves_the_request(api):
    """A new study is PLANNED and NOT_STARTED in one row, with no guide written yet.

    PRD 3.3: "On success the study is stamped with `lead_user_id` taken from the
    creating operator's `X-User-ID`, opens with `execution_status` `PLANNED` and
    `recruitment_status` `NOT_STARTED`, has `guide_status` `NONE` with
    `guide_version_label`, `guide_question_count` and `guide_version_pinned` all
    null, has `invited_count`, `screened_in_count` and `completed_count` at 0 and
    `fielded_at` and `fielding_closed_at` null — and it drags its request from
    `APPROVED` to `IN_STUDY`."

    Design: Corner/state_machines/study_creation_starts_in_both_initial_states
    """
    intake = setup_approved_request(api, method="INTERVIEW")
    pool = create_pool(api, incentive_budget_cents=50000)

    response = api.create_study(
        create_study_payload(
            intake["request"]["id"],
            pool["id"],
            method="INTERVIEW",
            target_participant_count=2,
            incentive_amount_cents=5000,
            fielding_start=FIELDING_START,
            fielding_end=FIELDING_END,
        ),
        RESEARCHER_HEADERS,
    )
    study = validate_success(response, expected_status=201)

    assert study["execution_status"] == "PLANNED", (
        f"Expected a new study to open PLANNED, got {study['execution_status']}"
    )
    assert study["recruitment_status"] == "NOT_STARTED", (
        f"Expected a new study to open NOT_STARTED on the recruitment dimension, "
        f"got {study['recruitment_status']}"
    )
    assert study["guide_status"] == "NONE", (
        f"Expected guide_status NONE before any guide is written, "
        f"got {study['guide_status']}"
    )
    assert study["guide_version_label"] is None, (
        f"Expected guide_version_label null at creation, "
        f"got {study['guide_version_label']}"
    )
    assert study["guide_question_count"] is None, (
        f"Expected guide_question_count null at creation, "
        f"got {study['guide_question_count']}"
    )
    assert study["guide_version_pinned"] is None, (
        f"Expected guide_version_pinned null at creation, "
        f"got {study['guide_version_pinned']}"
    )
    for counter in ("invited_count", "screened_in_count", "completed_count"):
        assert study[counter] == 0, (
            f"Expected {counter} 0 at creation, got {study[counter]}"
        )
    assert study["fielded_at"] is None, (
        f"Expected fielded_at null at creation, got {study['fielded_at']}"
    )
    assert study["fielding_closed_at"] is None, (
        f"Expected fielding_closed_at null at creation, "
        f"got {study['fielding_closed_at']}"
    )

    request_after = read_request(intake["request"]["id"], api)
    assert request_after["status"] == "IN_STUDY", (
        f"Expected creating the study to drag its request to IN_STUDY, "
        f"got {request_after['status']}"
    )


def test_guide_rewrite_unpins_the_version_and_forces_a_second_approval(api):
    """A rewritten guide is an unapproved guide, and fielding waits for the self-loop.

    PRD 3.3: "Every write sets `guide_status` to `DRAFT` and clears
    `guide_version_pinned` back to null — including a rewrite of a guide that had
    already been approved, which is exactly the point: a rewritten guide is an
    unapproved guide."

    PRD 3.3: "From a study already in `GUIDE_APPROVED` whose guide was rewritten
    since the last approval, approval is a self-loop `GUIDE_APPROVED →
    GUIDE_APPROVED`: it sets `guide_status` back to `APPROVED`, re-pins
    `guide_version_pinned` to the current `guide_version_label`, and deliberately
    leaves `execution_status` untouched — this self-loop is the only route back to
    a fieldable guide after a rewrite."

    PRD 3.3: "Fielding does **not** touch `recruitment_status`, which stays at
    `NOT_STARTED` until the study's first invitation is actually created."

    Design: Corner/state_machines/guide_rewrite_unpins_the_version_and_forces_reapproval
    """
    ctx = setup_guide_approved_study(
        api, guide_version_label="G1", guide_question_count=6, participant_count=1
    )
    study_id = ctx["study"]["id"]

    approved = ctx["study"]
    assert approved["execution_status"] == "GUIDE_APPROVED", (
        f"Expected GUIDE_APPROVED after the first approval, "
        f"got {approved['execution_status']}"
    )
    assert approved["guide_status"] == "APPROVED", (
        f"Expected guide_status APPROVED after the first approval, "
        f"got {approved['guide_status']}"
    )
    assert approved["guide_version_pinned"] == "G1", (
        f"Expected the first approval to pin G1, got {approved['guide_version_pinned']}"
    )

    rewrite = api.write_study_guide(
        study_id,
        {"guide_version_label": "G2", "guide_question_count": 8},
        RESEARCHER_HEADERS,
    )
    rewritten = validate_success(rewrite)
    assert rewritten["guide_version_label"] == "G2", (
        f"Expected the rewrite to store G2, got {rewritten['guide_version_label']}"
    )
    assert rewritten["guide_status"] == "DRAFT", (
        f"Expected the rewrite to reset guide_status to DRAFT, "
        f"got {rewritten['guide_status']}"
    )
    assert rewritten["guide_version_pinned"] is None, (
        f"Expected the rewrite to clear guide_version_pinned, "
        f"got {rewritten['guide_version_pinned']}"
    )
    assert rewritten["execution_status"] == "GUIDE_APPROVED", (
        f"Expected execution_status to stay GUIDE_APPROVED across the rewrite, "
        f"got {rewritten['execution_status']}"
    )

    refused = api.field_study(study_id, RESEARCHER_HEADERS)
    validate_error(refused, ApiErrorId.GUIDE_NOT_APPROVED.value)
    after_refusal = read_study(study_id, api)
    assert after_refusal["execution_status"] == "GUIDE_APPROVED", (
        f"Expected the refused fielding to leave GUIDE_APPROVED, "
        f"got {after_refusal['execution_status']}"
    )
    assert after_refusal["fielded_at"] is None, (
        f"Expected fielded_at to stay null after a refused fielding, "
        f"got {after_refusal['fielded_at']}"
    )

    reapproved = validate_success(api.approve_study_guide(study_id, RESEARCH_LEAD_HEADERS))
    assert reapproved["guide_status"] == "APPROVED", (
        f"Expected the self-loop approval to set guide_status APPROVED, "
        f"got {reapproved['guide_status']}"
    )
    assert reapproved["guide_version_pinned"] == "G2", (
        f"Expected the self-loop approval to re-pin G2, "
        f"got {reapproved['guide_version_pinned']}"
    )
    assert reapproved["execution_status"] == "GUIDE_APPROVED", (
        f"Expected the self-loop to leave execution_status untouched, "
        f"got {reapproved['execution_status']}"
    )

    fielded = validate_success(api.field_study(study_id, RESEARCHER_HEADERS))
    assert fielded["execution_status"] == "FIELDING", (
        f"Expected fielding to succeed once the guide is approved again, "
        f"got {fielded['execution_status']}"
    )
    assert fielded["recruitment_status"] == "NOT_STARTED", (
        f"Expected fielding to leave recruitment_status at NOT_STARTED, "
        f"got {fielded['recruitment_status']}"
    )
    assert fielded["fielded_at"] == CLOCK_START, (
        f"Expected fielded_at stamped from the clock at {CLOCK_START}, "
        f"got {fielded['fielded_at']}"
    )


def test_approving_an_already_approved_guide_is_refused(api):
    """The approve endpoint is not idempotent; its precondition is guide_status DRAFT.

    PRD 3.3: "In both shapes the precondition is the same: `guide_status` must be
    `DRAFT`. Approving a guide that is already `APPROVED`, or one that has never
    been written at all and still reads `NONE`, is refused with
    `ERR_GUIDE_NOT_APPROVED`."

    Design: Corner/state_machines/approving_an_already_approved_guide_is_rejected
    """
    ctx = setup_guide_approved_study(
        api, guide_version_label="G1", guide_question_count=6, participant_count=1
    )
    study_id = ctx["study"]["id"]
    version_before = ctx["study"]["version"]

    second_approval = api.approve_study_guide(study_id, RESEARCH_LEAD_HEADERS)
    validate_error(second_approval, ApiErrorId.GUIDE_NOT_APPROVED.value)

    study = read_study(study_id, api)
    assert study["guide_version_pinned"] == "G1", (
        f"Expected the refused approval to leave G1 pinned, "
        f"got {study['guide_version_pinned']}"
    )
    assert study["guide_status"] == "APPROVED", (
        f"Expected guide_status to stay APPROVED, got {study['guide_status']}"
    )
    assert study["execution_status"] == "GUIDE_APPROVED", (
        f"Expected execution_status to stay GUIDE_APPROVED, "
        f"got {study['execution_status']}"
    )
    assert study["version"] == version_before, (
        f"Expected version {version_before} to be unchanged by a refused call, "
        f"got {study['version']}"
    )


def test_close_fielding_is_refused_while_a_session_is_still_scheduled(api):
    """The FIELDING to ANALYSIS guard scans the study's recruitments for booked sessions.

    PRD 3.3: "Closing fielding carries `execution_status` `FIELDING → ANALYSIS`,
    and it is refused with `ERR_INVALID_STATE` while any recruitment of the study
    is still sitting in `SCHEDULED` — every booked session must be resolved as
    completed, a no-show or a withdrawal before analysis begins."

    PRD 3.3: "Any other study leaves `recruitment_status` exactly where the
    recruitment dimension had already put it — `RECRUITING` or `QUOTA_MET`."

    PRD 3.9: "`recruitment_efficiency` is `completed_count` divided by
    `invited_count`, rounded half-up to four decimal places, and exactly 0.0000
    when `invited_count` is 0."

    Design: Corner/state_machines/close_fielding_is_refused_while_a_session_is_still_scheduled
    """
    ctx = setup_scheduled_sessions(
        api,
        scheduled_start="2026-08-05T10:00:00Z",
        scheduled_end="2026-08-05T11:00:00Z",
        participant_count=1,
        target_participant_count=2,
        pool_overrides={"incentive_budget_cents": 100000},
    )
    study_id = ctx["study"]["id"]
    recruitment_id = ctx["recruitments"][0]["id"]

    refused = api.close_study_fielding(study_id, RESEARCHER_HEADERS)
    validate_error(refused, ApiErrorId.INVALID_STATE.value)
    blocked = read_study(study_id, api)
    assert blocked["execution_status"] == "FIELDING", (
        f"Expected the study to stay FIELDING while a session is SCHEDULED, "
        f"got {blocked['execution_status']}"
    )
    assert blocked["fielding_closed_at"] is None, (
        f"Expected fielding_closed_at to stay null after the refusal, "
        f"got {blocked['fielding_closed_at']}"
    )

    completed = validate_success(
        api.complete_recruitment(
            recruitment_id, {"actual_duration_min": 55}, RESEARCHER_HEADERS
        )
    )
    assert completed["status"] == "COMPLETED", (
        f"Expected the session to move to COMPLETED, got {completed['status']}"
    )
    assert completed["actual_duration_min"] == 55, (
        f"Expected actual_duration_min 55 to be recorded, "
        f"got {completed['actual_duration_min']}"
    )

    closed = validate_success(api.close_study_fielding(study_id, RESEARCHER_HEADERS))
    assert closed["execution_status"] == "ANALYSIS", (
        f"Expected the second close-fielding to reach ANALYSIS, "
        f"got {closed['execution_status']}"
    )
    assert closed["fielding_closed_at"] == CLOCK_START, (
        f"Expected fielding_closed_at stamped at {CLOCK_START}, "
        f"got {closed['fielding_closed_at']}"
    )
    assert closed["recruitment_status"] == "RECRUITING", (
        f"Expected recruitment_status to stay RECRUITING with 1 completed of a "
        f"target of 2, got {closed['recruitment_status']}"
    )

    metrics = read_metrics(study_id, api)
    assert metrics["fielding_days"] == 0, (
        f"Expected fielding_days 0 when fielded_at and fielding_closed_at share "
        f"the clock instant, got {metrics['fielding_days']}"
    )
    assert metrics["recruitment_efficiency"] == pytest.approx(1.0, abs=0.01), (
        f"Expected recruitment_efficiency 1.0000 for 1 completed of 1 invited, "
        f"got {metrics['recruitment_efficiency']}"
    )


# ===========================================================================
# Cross-entity validations on study creation and on fielding
# ===========================================================================
def test_study_method_must_match_the_requests_approved_method(api):
    """Both clauses of one rule fail independently: the method join and the request status.

    PRD 3.3: "Creation is refused with `ERR_METHOD_NOT_APPROVED` unless the
    referenced request is in `status` `APPROVED` *and* the submitted `method` is
    exactly equal to that request's stored `approved_method`."

    PRD 3.1: "The request lands in `status` `SUBMITTED` with `revision_round` at
    0, its `requester_user_id` set to the acting operator's `X-User-ID`, and
    `priority_score`, `recommended_method`, `approved_method`, `triage_reason` and
    `triaged_at` all null."

    Design: Corner/validations/study_method_must_match_the_requests_approved_method
    """
    intake = setup_approved_request(
        api, method="INTERVIEW", question_type="DISCOVERY", evidence_gap="PARTIAL"
    )
    untriaged = create_request(
        intake["decision"]["id"],
        api,
        question="How do teams close tickets?",
        question_type="DISCOVERY",
        evidence_gap="PARTIAL",
    )
    pool = create_pool(api, incentive_budget_cents=100000)

    def study_payload(request_id, method):
        return create_study_payload(
            request_id,
            pool["id"],
            method=method,
            target_participant_count=3,
            incentive_amount_cents=5000,
            fielding_start=FIELDING_START,
            fielding_end=FIELDING_END,
        )

    wrong_method = api.create_study(
        study_payload(intake["request"]["id"], "SURVEY"), RESEARCHER_HEADERS
    )
    validate_error(wrong_method, ApiErrorId.METHOD_NOT_APPROVED.value)

    untriaged_request = api.create_study(
        study_payload(untriaged["id"], "INTERVIEW"), RESEARCHER_HEADERS
    )
    validate_error(untriaged_request, ApiErrorId.METHOD_NOT_APPROVED.value)

    accepted = validate_success(
        api.create_study(
            study_payload(intake["request"]["id"], "INTERVIEW"), RESEARCHER_HEADERS
        ),
        expected_status=201,
    )
    assert accepted["method"] == "INTERVIEW", (
        f"Expected the accepted study to carry INTERVIEW, got {accepted['method']}"
    )

    approved_request = read_request(intake["request"]["id"], api)
    assert approved_request["status"] == "IN_STUDY", (
        f"Expected only the accepted creation to move the request to IN_STUDY, "
        f"got {approved_request['status']}"
    )
    untriaged_after = read_request(untriaged["id"], api)
    assert untriaged_after["status"] == "SUBMITTED", (
        f"Expected the untriaged request to stay SUBMITTED, "
        f"got {untriaged_after['status']}"
    )
    assert untriaged_after["recommended_method"] is None, (
        f"Expected recommended_method null on a request that was never triaged, "
        f"got {untriaged_after['recommended_method']}"
    )
    assert untriaged_after["approved_method"] is None, (
        f"Expected approved_method null on a request that was never triaged, "
        f"got {untriaged_after['approved_method']}"
    )


def test_fielding_a_study_under_a_locked_decision_is_refused(api):
    """Fielding reads the state of the decision three hops away from the study.

    PRD 3.3: "The governing roadmap decision — reached from the study's
    `research_request_id` to that request's `roadmap_decision_id` — must be
    `OPEN`, else `ERR_DECISION_LOCKED`; a decision that has already been locked on
    existing evidence does not get more studies fielded against it."

    PRD 3.1: "A `LOCKED` decision is frozen against further fielding: no study
    whose research request points at it may be put into the field, and no readout
    naming it may be responded to — both are refused with `ERR_DECISION_LOCKED`."

    Design: Corner/validations/fielding_a_study_under_a_locked_decision_is_rejected
    """
    ctx = setup_locked_decision_on_dual_findings(api)
    decision = ctx["decision"]
    assert decision["status"] == "LOCKED", (
        f"Expected the decision to be LOCKED before the second study is fielded, "
        f"got {decision['status']}"
    )
    assert decision["locked_at"] == CLOCK_START, (
        f"Expected locked_at stamped from the clock at {CLOCK_START}, "
        f"got {decision['locked_at']}"
    )

    second_intake = setup_approved_request(api, method="INTERVIEW", decision=decision)
    panel = setup_pool_with_participants(api, participant_count=1)
    second_study = create_study(
        second_intake["request"]["id"],
        panel["pool"]["id"],
        api,
        method="INTERVIEW",
        fielding_start=FIELDING_START,
        fielding_end=FIELDING_END,
    )
    write_guide(second_study["id"], api, guide_version_label="GB", guide_question_count=6)
    prepared = approve_guide(second_study["id"], api)
    version_before = prepared["version"]

    refused = api.field_study(second_study["id"], RESEARCHER_HEADERS)
    validate_error(refused, ApiErrorId.DECISION_LOCKED.value)

    after = read_study(second_study["id"], api)
    assert after["execution_status"] == "GUIDE_APPROVED", (
        f"Expected the refused study to stay GUIDE_APPROVED, "
        f"got {after['execution_status']}"
    )
    assert after["guide_status"] == "APPROVED", (
        f"Expected the guide gate to have been satisfied before the lock refused "
        f"the call, got guide_status {after['guide_status']}"
    )
    assert after["fielded_at"] is None, (
        f"Expected fielded_at to stay null, got {after['fielded_at']}"
    )
    assert after["version"] == version_before, (
        f"Expected version {version_before} to be unchanged by the refused "
        f"fielding, got {after['version']}"
    )
    assert read_request(second_intake["request"]["id"], api)["status"] == "IN_STUDY", (
        "The second request stays IN_STUDY: it moved when its study was created"
    )
