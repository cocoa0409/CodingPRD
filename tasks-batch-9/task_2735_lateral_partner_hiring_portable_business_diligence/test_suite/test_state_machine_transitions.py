"""Single-edge state machine behaviour: the legal edges, the illegal ones, the opening
states and the terminal lockdowns."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_conflict_check_payload,
    create_conflict_waiver_payload,
    create_questionnaire_payload,
    clear_conflict_check_payload,
    read_candidate,
    read_conflict_check,
    read_questionnaire,
    setup_approached_candidate,
    setup_book,
    setup_cleared_candidate,
    setup_questionnaire_in_draft,
    setup_questionnaire_under_review,
    setup_sourced_candidate,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_candidate_payload,
)

COORDINATOR = TEST_USERS["recruiting_coordinator_headers"]
COUNSEL = TEST_USERS["conflicts_counsel_headers"]


def test_recording_the_approach_advances_the_pipeline_and_bumps_the_version():
    """Recording the confidential approach advances `SOURCED → APPROACHED`.
    The `approach_confidential` flag is retained exactly as it was recorded at creation;
    the approach step never rewrites it.
    Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp in the same
    format that is refreshed on every mutation of the row, and `version`, an integer that
    begins at 1 on creation and increments by exactly 1 on every mutation of the row.

    Design: Corner/state_machines/candidate_approach_moves_sourced_to_approached
    """
    ctx = setup_sourced_candidate()
    assert ctx["candidate"]["pipeline_status"] == "SOURCED"
    assert ctx["candidate"]["version"] == 1

    approached = validate_success(
        api_client.approach_candidate(ctx["candidate"]["id"], COORDINATOR)
    )

    assert approached["pipeline_status"] == "APPROACHED"
    assert approached["version"] == 2
    assert approached["clearance_status"] == "NOT_STARTED"
    assert approached["approach_confidential"] is True
    assert approached["open_offer_id"] is None


def test_issuing_the_questionnaire_writes_a_draft_and_moves_the_candidate_to_diligence():
    """Issuing the LPQ writes it with `status` `DRAFT`, `revision_round` `0`,
    `entry_count` `0`, and `latest_assessment_id` null, and — as a side effect on the
    parent — advances the candidate `APPROACHED → DILIGENCE`.

    Design: Corner/state_machines/questionnaire_create_advances_the_candidate_to_diligence
    """
    ctx = setup_approached_candidate()

    questionnaire = validate_success(
        api_client.create_questionnaire(
            ctx["candidate"]["id"],
            create_questionnaire_payload(
                declared_prior_year_billings_usd=1600000.00,
                declared_prior_year_collections_usd=1410000.00,
                declared_realization_rate=0.9500,
                primary_matter_types=["M_AND_A"],
            ),
            COORDINATOR,
        ),
        expected_status=201,
    )

    assert questionnaire["status"] == "DRAFT"
    assert questionnaire["revision_round"] == 0
    assert questionnaire["entry_count"] == 0
    assert questionnaire["latest_assessment_id"] is None
    assert questionnaire["candidate_id"] == ctx["candidate"]["id"]
    assert abs(float(questionnaire["declared_realization_rate"]) - 0.9500) < 5e-5

    candidate = read_candidate(ctx["candidate"]["id"])
    assert candidate["pipeline_status"] == "DILIGENCE"
    assert candidate["clearance_status"] == "NOT_STARTED"


def test_neither_review_nor_acceptance_may_be_reached_straight_from_draft():
    """A coordinator then begins review, moving `SUBMITTED → UNDER_REVIEW`; that step
    takes no payload and has no effect beyond the status write.
    Alternatively the coordinator accepts the LPQ as the diligence of record, moving
    `UNDER_REVIEW → ACCEPTED`, which requires that at least one portability assessment on
    this questionnaire is in `CURRENT` status.
    Failure yields the invalid-state code for that entity:
    `ERR_CANDIDATE_INVALID_STATE`, `ERR_QUESTIONNAIRE_INVALID_STATE`,
    `ERR_ENGAGEMENT_INVALID_STATE`, `ERR_ASSESSMENT_INVALID_STATE`,
    `ERR_CONFLICT_CHECK_INVALID_STATE`, `ERR_WAIVER_INVALID_STATE`,
    `ERR_DECLINATION_INVALID_STATE`, `ERR_OFFER_INVALID_STATE`,
    `ERR_INTEGRATION_PLAN_INVALID_STATE`, or `ERR_INTRODUCTION_INVALID_STATE` (all 409).

    Design: Corner/state_machines/questionnaire_start_review_from_draft_rejected
    """
    ctx = setup_questionnaire_in_draft()
    setup_book(ctx, "SLIM")
    before = read_questionnaire(ctx["questionnaire"]["id"])
    assert before["status"] == "DRAFT"
    assert before["entry_count"] == 1

    start_review = api_client.start_review_questionnaire(
        ctx["questionnaire"]["id"], COORDINATOR
    )
    validate_error(start_review, ApiErrorId.ERR_QUESTIONNAIRE_INVALID_STATE.value)

    accept = api_client.accept_questionnaire(ctx["questionnaire"]["id"], COORDINATOR)
    validate_error(accept, ApiErrorId.ERR_QUESTIONNAIRE_INVALID_STATE.value)

    after = read_questionnaire(ctx["questionnaire"]["id"])
    assert after["status"] == "DRAFT"
    assert after["version"] == before["version"]
    assert after["revision_round"] == 0


def test_the_first_conflict_check_lands_pending_and_opens_the_clearance_dimension():
    """The new check lands with `status` `PENDING` and `resolution_note` null.
    The candidate's very first check moves `clearance_status`
    `NOT_STARTED → IN_PROGRESS`.

    Design: Corner/state_machines/conflict_check_create_starts_pending_and_opens_the_clearance_dimension
    """
    ctx = setup_questionnaire_under_review("SLIM")
    assert read_candidate(ctx["candidate"]["id"])["clearance_status"] == "NOT_STARTED"

    entry = ctx["entries"]["Northwind Holdings"]
    check = validate_success(
        api_client.create_conflict_check(
            entry["id"],
            create_conflict_check_payload(
                adverse_party_name="Vertex Capital",
                affected_matter_types=["SECURITIES"],
                severity="POSITIONAL",
            ),
            COUNSEL,
        ),
        expected_status=201,
    )

    assert check["status"] == "PENDING"
    assert check["severity"] == "POSITIONAL"
    assert check["client_book_entry_id"] == entry["id"]

    candidate = read_candidate(ctx["candidate"]["id"])
    assert candidate["clearance_status"] == "IN_PROGRESS"
    assert candidate["pipeline_status"] == "DILIGENCE"


def test_a_withdrawn_candidate_refuses_both_a_second_withdrawal_and_a_questionnaire():
    """A coordinator may withdraw a candidate from any non-terminal position — that is,
    whenever `pipeline_status` is not already `HIRED`, `DECLINED`, or `WITHDRAWN` —
    supplying a `withdrawal_reason`.
    A `RecruitingCoordinator` issues it against a candidate whose `pipeline_status` is
    `APPROACHED`, and only when that candidate has no questionnaire outstanding — that is,
    no existing questionnaire whose `status` is anything other than `ACCEPTED` or
    `ABANDONED`.

    Design: Corner/state_machines/candidate_second_withdraw_from_terminal_state_rejected
    """
    ctx = setup_approached_candidate()

    withdrawn = validate_success(
        api_client.withdraw_candidate(
            ctx["candidate"]["id"], withdraw_candidate_payload(), COORDINATOR
        )
    )
    assert withdrawn["pipeline_status"] == "WITHDRAWN"

    second = api_client.withdraw_candidate(
        ctx["candidate"]["id"],
        withdraw_candidate_payload(
            withdrawal_reason="Duplicate withdrawal filed by mistake."
        ),
        COORDINATOR,
    )
    validate_error(second, ApiErrorId.ERR_CANDIDATE_INVALID_STATE.value)

    questionnaire = api_client.create_questionnaire(
        ctx["candidate"]["id"], create_questionnaire_payload(), COORDINATOR
    )
    validate_error(questionnaire, ApiErrorId.ERR_CANDIDATE_INVALID_STATE.value)

    candidate = read_candidate(ctx["candidate"]["id"])
    assert candidate["pipeline_status"] == "WITHDRAWN"
    assert candidate["clearance_status"] == "NOT_STARTED"

    _rows, meta = validate_paginated(
        api_client.list_questionnaires(
            COORDINATOR, params={"candidate_id": ctx["candidate"]["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_a_cleared_check_can_be_neither_cleared_again_nor_sent_to_a_waiver():
    """Clearing a check that is not `PENDING` is refused with
    `ERR_CONFLICT_CHECK_INVALID_STATE`.
    A counsel opens a `ConflictWaiver` — a waiver, below — on a `PENDING` check, supplying
    a `waiver_strategy` of `ADVANCE_CONSENT`, `ETHICAL_WALL`, or `MATTER_CARVE_OUT`, a
    `requested_from_client` name of 1 to 120 characters, and a `response_deadline_date`
    that must be strictly later than the current logical clock — a deadline already in the
    past is refused with `ERR_LOOKBACK_WINDOW_INVALID`.

    Design: Corner/state_machines/conflict_check_cleared_twice_rejected
    """
    ctx = setup_cleared_candidate("SLIM")
    check_id = ctx["conflict_checks"]["Northwind Holdings"]["id"]

    again = api_client.clear_conflict_check(
        check_id,
        clear_conflict_check_payload(resolution_note="Second look; still clear."),
        COUNSEL,
    )
    validate_error(again, ApiErrorId.ERR_CONFLICT_CHECK_INVALID_STATE.value)

    waiver = api_client.create_conflict_waiver(
        check_id,
        create_conflict_waiver_payload(requested_from_client="Northwind Holdings"),
        COUNSEL,
    )
    validate_error(waiver, ApiErrorId.ERR_CONFLICT_CHECK_INVALID_STATE.value)

    check = read_conflict_check(check_id)
    assert check["status"] == "CLEAR"
    assert check["resolution_note"] == "Positional only; no substantive adversity."
    assert read_candidate(ctx["candidate"]["id"])["clearance_status"] == "CLEARED"

    _rows, meta = validate_paginated(
        api_client.list_conflict_waivers(COUNSEL, params={"conflict_check_id": check_id})
    )
    assert meta["total_count"] == 0
