"""Refusals around the integration plan and the disclosed book: the scarce onboarding slot,
the offer-ownership guard, the notice period, the compensating rescission, and thin evidence."""

from test_helpers import (
    ApiErrorId,
    ENTRY_A_RECORDS,
    ENTRY_A_SPEC,
    EXPECTED_AB_BOOK,
    MEMBER_1_USER_ID,
    MEMBER_2_USER_ID,
    TEST_USERS,
    add_book_entry,
    api_client,
    append_collection_record,
    assert_instant_equals,
    assert_money_equals,
    block_entry_through_refused_waiver,
    cast_vote,
    clear_conflict_check,
    create_assessment_payload,
    create_integration_plan_payload,
    declinations_for_entry,
    draft_offer,
    finalize_offer,
    open_conflict_check,
    read_assessment,
    read_candidate,
    read_client_book_entry,
    read_conflict_check,
    read_integration_plan,
    read_practice_group,
    read_questionnaire,
    rescind_declination_payload,
    set_logical_clock,
    setup_active_plan,
    setup_cleared_candidate,
    setup_hired_candidate,
    setup_plan_with_introduction,
    setup_questionnaire_in_draft,
    setup_second_assessed_candidate,
    submit_offer,
    validate_error,
    validate_success,
)

COORDINATOR = TEST_USERS["recruiting_coordinator_headers"]
COUNSEL = TEST_USERS["conflicts_counsel_headers"]

HIRE_PACKAGE = {"guaranteed_comp_usd": 400000.00, "signing_bonus_usd": 40000.00}


def test_a_single_onboarding_slot_and_a_borrowed_offer_both_stop_the_second_plan():
    """Three guards apply beyond the candidate's status. The referenced offer must belong to
    that same candidate and its `status` must be `ACCEPTED`; an offer belonging to someone else
    is refused with `ERR_OFFER_CANDIDATE_MISMATCH`.
    Two conditions guard it: the group's `status` must be `OPEN`, or
    `ERR_PRACTICE_GROUP_FROZEN`; and the group's `active_onboarding_count` must be **strictly
    less than** its `onboarding_capacity`, or `ERR_ONBOARDING_CAPACITY_REACHED`. Equality is a
    rejection — a group with a capacity of two that already carries two active plans cannot
    take a third.

    Design: Corner/errors/onboarding_capacity_and_offer_ownership_are_both_enforced_on_plans
    """
    ctx = setup_active_plan(
        "SLIM",
        pg_overrides={"onboarding_capacity": 1},
        offer_overrides=dict(HIRE_PACKAGE),
    )
    group_id = ctx["practice_group"]["id"]
    first_plan_id = ctx["plan"]["id"]
    first_offer_id = ctx["offer"]["id"]

    other = _second_hired_candidate(ctx)
    second_candidate_id = other["candidate"]["id"]

    group = read_practice_group(group_id)
    assert_money_equals(
        group["committed_guarantee_total_usd"], 800000.00, "committed_guarantee_total_usd"
    )
    assert_money_equals(
        group["available_guarantee_budget_usd"], 4200000.00, "available_guarantee_budget_usd"
    )

    borrowed = api_client.create_integration_plan(
        second_candidate_id,
        create_integration_plan_payload(group_id, first_offer_id),
        ctx["leader_headers"],
    )
    validate_error(borrowed, ApiErrorId.ERR_OFFER_CANDIDATE_MISMATCH.value, 422)

    second_plan = validate_success(
        api_client.create_integration_plan(
            second_candidate_id,
            create_integration_plan_payload(group_id, other["offer"]["id"]),
            ctx["leader_headers"],
        ),
        expected_status=201,
    )
    assert second_plan["status"] == "DRAFT"

    full = api_client.activate_integration_plan(
        second_plan["id"], ctx["leader_headers"]
    )
    validate_error(full, ApiErrorId.ERR_ONBOARDING_CAPACITY_REACHED.value)

    assert read_integration_plan(second_plan["id"])["status"] == "DRAFT"
    assert read_integration_plan(first_plan_id)["status"] == "ACTIVE"

    group = read_practice_group(group_id)
    assert group["active_onboarding_count"] == 1
    assert group["onboarding_capacity"] == 1
    assert_money_equals(
        group["committed_guarantee_total_usd"], 800000.00, "committed_guarantee_total_usd"
    )
    assert_money_equals(
        group["reserved_guarantee_budget_usd"], 0.00, "reserved_guarantee_budget_usd"
    )
    assert_money_equals(
        group["available_guarantee_budget_usd"], 4200000.00, "available_guarantee_budget_usd"
    )


def test_only_the_last_rescission_reverses_the_entry_and_a_replay_is_refused():
    """Two preconditions apply: the declination's `status` must be `ACTIVE`, and the parent
    check's `status` must be `BLOCKED`; rescinding an already-rescinded row is refused with
    `ERR_DECLINATION_INVALID_STATE`, and a parent check in the wrong state is refused with
    `ERR_CONFLICT_CHECK_INVALID_STATE`.
    When — and only when — this was the **last** `ACTIVE` declination on the entry, so that
    zero remain active afterwards, the reversal chain runs: the entry moves `portable_status`
    `DECLINED → VALIDATED` with `validated_portable_amount_usd` restored exactly to
    `baseline_portable_amount_usd` with no drift; the parent check moves `BLOCKED → CLEAR`;
    every assessment on that questionnaire whose `status` is `CURRENT` or `STALE` recomputes
    `validated_portable_total_usd`, `declined_portable_total_usd`, and
    `adjusted_portable_total_usd`; and the candidate's `clearance_status` is recomputed, which
    may return it to `CLEARED`.
    Rescinding one of several active declinations on the same entry moves only that row; the
    entry stays `DECLINED`.

    Design: Corner/errors/declination_rescind_is_refused_once_the_row_is_already_rescinded
    """
    ctx = setup_cleared_candidate("AB")
    block_entry_through_refused_waiver(ctx, "Calder Manufacturing")
    entry_b_id = ctx["entries"]["Calder Manufacturing"]["id"]
    check_b_id = ctx["conflict_checks"]["Calder Manufacturing"]["id"]

    rows = {row["matter_type"]: row for row in declinations_for_entry(entry_b_id)}
    assert set(rows) == {"LITIGATION", "EMPLOYMENT"}
    assert_money_equals(
        rows["LITIGATION"]["foregone_annual_revenue_usd"],
        166056.08,
        "LITIGATION foregone_annual_revenue_usd",
    )
    assert_money_equals(
        rows["EMPLOYMENT"]["foregone_annual_revenue_usd"],
        166056.07,
        "EMPLOYMENT foregone_annual_revenue_usd",
    )

    validate_success(
        api_client.rescind_matter_declination(
            rows["LITIGATION"]["id"],
            rescind_declination_payload(rescission_note="Litigation matter reassigned."),
            COUNSEL,
        )
    )
    assert read_client_book_entry(entry_b_id)["portable_status"] == "DECLINED"

    replay = api_client.rescind_matter_declination(
        rows["LITIGATION"]["id"],
        rescind_declination_payload(rescission_note="Duplicate rescission."),
        COUNSEL,
    )
    validate_error(replay, ApiErrorId.ERR_DECLINATION_INVALID_STATE.value)

    last = validate_success(
        api_client.rescind_matter_declination(
            rows["EMPLOYMENT"]["id"],
            rescind_declination_payload(rescission_note="Employment matter also reassigned."),
            COUNSEL,
        )
    )
    assert last["status"] == "RESCINDED"
    assert_money_equals(
        last["foregone_annual_revenue_usd"], 166056.07, "foregone_annual_revenue_usd"
    )

    assert (
        validate_success(
            api_client.get_matter_declination(rows["LITIGATION"]["id"], COUNSEL)
        )["status"]
        == "RESCINDED"
    )

    entry_b = read_client_book_entry(entry_b_id)
    assert entry_b["portable_status"] == "VALIDATED"
    assert_money_equals(
        entry_b["validated_portable_amount_usd"],
        EXPECTED_AB_BOOK["entry_b_baseline"],
        "validated_portable_amount_usd",
    )
    assert_money_equals(
        entry_b["baseline_portable_amount_usd"],
        EXPECTED_AB_BOOK["entry_b_baseline"],
        "baseline_portable_amount_usd",
    )

    assert read_conflict_check(check_b_id)["status"] == "CLEAR"
    assert read_candidate(ctx["candidate"]["id"])["clearance_status"] == "CLEARED"

    assessment = read_assessment(ctx["assessment"]["id"])
    assert_money_equals(
        assessment["validated_portable_total_usd"],
        EXPECTED_AB_BOOK["validated_portable_total_usd"],
        "validated_portable_total_usd",
    )
    assert_money_equals(
        assessment["declined_portable_total_usd"],
        EXPECTED_AB_BOOK["declined_portable_total_usd"],
        "declined_portable_total_usd",
    )
    assert_money_equals(
        assessment["adjusted_portable_total_usd"],
        EXPECTED_AB_BOOK["adjusted_portable_total_usd"],
        "adjusted_portable_total_usd",
    )


def test_a_slot_already_reported_as_held_refuses_a_second_completion():
    """Marking it held moves `PROPOSED → COMPLETED`, which requires that the current logical
    clock has reached or passed the slot's `slot_start_at` — an introduction cannot be reported
    as held before it was due to begin — and sets `completed_at` to the current clock instant
    while incrementing the plan's `completed_introduction_count` by 1. Completing a slot that
    is not `PROPOSED` is refused with `ERR_INTRODUCTION_INVALID_STATE`.

    Design: Corner/errors/introduction_complete_twice_is_rejected
    """
    ctx = setup_plan_with_introduction("SLIM")
    introduction_id = ctx["introduction"]["id"]
    plan_id = ctx["plan"]["id"]

    set_logical_clock("2026-10-05T09:00:00.000Z")

    completed = validate_success(
        api_client.complete_introduction(introduction_id, ctx["leader_headers"])
    )
    assert completed["status"] == "COMPLETED"
    assert_instant_equals(
        completed["completed_at"], "2026-10-05T09:00:00.000Z", "completed_at"
    )

    replay = api_client.complete_introduction(introduction_id, ctx["leader_headers"])
    validate_error(replay, ApiErrorId.ERR_INTRODUCTION_INVALID_STATE.value)

    again = validate_success(
        api_client.get_introduction(introduction_id, ctx["leader_headers"])
    )
    assert again["status"] == "COMPLETED"
    assert_instant_equals(
        again["completed_at"], "2026-10-05T09:00:00.000Z", "completed_at"
    )

    plan = read_integration_plan(plan_id)
    assert plan["introduction_count"] == 1
    assert plan["completed_introduction_count"] == 1
    assert plan["status"] == "ACTIVE"

    assert read_practice_group(ctx["practice_group"]["id"])["active_onboarding_count"] == 1


def test_the_onboarding_window_may_not_open_before_the_notice_period_runs_out():
    """And the `onboarding_start_date` must fall at or after the candidate's
    `earliest_start_date`, which is the notice period the candidate still owes the prior firm;
    an earlier start is refused with `ERR_NOTICE_PERIOD_NOT_ELAPSED`. The new plan lands with
    `status` `DRAFT` and both `introduction_count` and `completed_introduction_count` at `0`.

    Design: Corner/errors/plan_start_before_the_earliest_start_date_is_rejected
    """
    ctx = setup_hired_candidate("SLIM")

    candidate = read_candidate(ctx["candidate"]["id"])
    assert candidate["notice_period_days"] == 45
    assert_instant_equals(
        candidate["earliest_start_date"], "2026-09-15T00:00:00.000Z", "earliest_start_date"
    )

    early = api_client.create_integration_plan(
        ctx["candidate"]["id"],
        create_integration_plan_payload(
            ctx["practice_group"]["id"],
            ctx["offer"]["id"],
            onboarding_start_date="2026-09-01T00:00:00.000Z",
        ),
        ctx["leader_headers"],
    )
    validate_error(early, ApiErrorId.ERR_NOTICE_PERIOD_NOT_ELAPSED.value)

    plan = validate_success(
        api_client.create_integration_plan(
            ctx["candidate"]["id"],
            create_integration_plan_payload(
                ctx["practice_group"]["id"],
                ctx["offer"]["id"],
                onboarding_start_date="2026-09-15T00:00:00.000Z",
            ),
            ctx["leader_headers"],
        ),
        expected_status=201,
    )
    assert_instant_equals(
        plan["onboarding_start_date"],
        "2026-09-15T00:00:00.000Z",
        "onboarding_start_date",
    )
    assert plan["status"] == "DRAFT"
    assert plan["introduction_count"] == 0
    assert plan["completed_introduction_count"] == 0

    assert read_practice_group(ctx["practice_group"]["id"])["active_onboarding_count"] == 0


def test_an_empty_book_blocks_submission_and_two_records_block_the_valuation():
    """Submitting with an empty book is refused with `ERR_EMPTY_CLIENT_BOOK`; submitting
    through a dead engagement is refused with `ERR_ENGAGEMENT_INVALID_STATE`.
    Its `entry_count` must be at least 1, or the request is refused with
    `ERR_EMPTY_CLIENT_BOOK`. And **every** client book entry on the questionnaire whose
    `status` is `ACTIVE` must have at least three verified historical collection records inside
    that half-open window; an entry short of three is refused with
    `ERR_UNVERIFIED_COLLECTION_DATA`. Three is a floor, not a target: exactly three qualifies.

    Design: Corner/errors/thin_client_book_data_is_rejected_at_submit_and_at_assessment
    """
    ctx = setup_questionnaire_in_draft()
    questionnaire_id = ctx["questionnaire"]["id"]
    assert read_questionnaire(questionnaire_id)["entry_count"] == 0

    empty = api_client.submit_questionnaire(questionnaire_id, ctx["candidate_headers"])
    validate_error(empty, ApiErrorId.ERR_EMPTY_CLIENT_BOOK.value, 422)

    entry = add_book_entry(ctx, ENTRY_A_SPEC, ENTRY_A_RECORDS[:2])

    submitted = validate_success(
        api_client.submit_questionnaire(questionnaire_id, ctx["candidate_headers"])
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["entry_count"] == 1

    under_review = validate_success(
        api_client.start_review_questionnaire(questionnaire_id, COORDINATOR)
    )

    thin = api_client.create_portability_assessment(
        questionnaire_id,
        create_assessment_payload(under_review["version"]),
        COORDINATOR,
    )
    validate_error(thin, ApiErrorId.ERR_UNVERIFIED_COLLECTION_DATA.value, 422)

    period_end_date, amount_usd = ENTRY_A_RECORDS[2]
    append_collection_record(
        ctx["candidate"]["id"],
        entry["id"],
        record_type="HISTORICAL",
        period_end_date=period_end_date,
        amount_usd=amount_usd,
        status="VERIFIED",
    )

    assessment = validate_success(
        api_client.create_portability_assessment(
            questionnaire_id,
            create_assessment_payload(read_questionnaire(questionnaire_id)["version"]),
            COORDINATOR,
        ),
        expected_status=201,
    )
    assert assessment["status"] == "CURRENT"
    assert assessment["entry_count_in_scope"] == 1
    assert_money_equals(
        assessment["gross_baseline_total_usd"], 1269000.00, "gross_baseline_total_usd"
    )

    fresh_entry = read_client_book_entry(entry["id"])
    assert fresh_entry["verified_record_count"] == 3
    assert fresh_entry["portable_status"] == "VALIDATED"
    assert_money_equals(
        fresh_entry["baseline_portable_amount_usd"],
        1269000.00,
        "baseline_portable_amount_usd",
    )

    assert read_questionnaire(questionnaire_id)["entry_count"] == 1


# ----------------------------------------------------------------------
# Local scenario glue
# ----------------------------------------------------------------------


def _second_hired_candidate(ctx):
    """Take a second candidate on the same engagement all the way to HIRED on her own
    accepted offer, so the group carries two committed guarantees."""
    other = setup_second_assessed_candidate(ctx)
    open_conflict_check(other, ENTRY_A_SPEC["client_name"])
    clear_conflict_check(other, ENTRY_A_SPEC["client_name"])
    draft_offer(other, **HIRE_PACKAGE)
    submit_offer(other, eligible_voter_count=3)
    cast_vote(other, MEMBER_1_USER_ID, "APPROVE")
    cast_vote(other, MEMBER_2_USER_ID, "APPROVE")
    finalize_offer(other)
    other["offer"] = validate_success(
        api_client.accept_offer(other["offer"]["id"], other["candidate_headers"])
    )
    other["candidate"] = read_candidate(other["candidate"]["id"])
    return other
