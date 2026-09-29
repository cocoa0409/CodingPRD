"""Grant awards and funding allocations: commitment sizing, the ladder around
allocation creation, release and the conserved money pool."""

import pytest

from test_helpers import (
    GO,
    IC,
    PD,
    ApiErrorId,
    UNUSED_UUIDS,
    api_client,
    assert_funding_allocation,
    assert_grant_money_pool,
    cohort_version,
    confirm_enrollment,
    create_assessed_participant,
    create_cohort,
    create_funding_allocation,
    create_grant_award,
    create_meeting_space,
    create_open_cohort,
    create_remembrance_event,
    enroll,
    grant_award_version,
    read_cohort,
    read_funding_allocation,
    read_grant_award,
    set_clock,
    setup_funded_event,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    withdraw_enrollment,
)


def test_commitment_counts_only_the_seats_that_are_still_live():
    """PRD 3.9: "Note precisely which seats count at this moment: enrollments in
    `HELD`, `CONFIRMED` and `ATTENDING` all contribute, while `EXPIRED` and
    `WITHDRAWN` ones do not. Money is committed for every seat that is held or
    filled right now, whether or not anybody ever turns up."
    PRD 3.9: "For a `GROUP_PROGRAM` allocation, the programme projects how many
    participants the cohort will actually carry: take the number of that cohort's
    seats currently held or filled, which is `seats_filled` plus `seats_held`, and
    cap it at `seats_total`. Multiply the cohort's `program_cost_total_cents` by
    that projected count, divide by `seats_total`, and round half up to a whole
    cent. The allocation's `basis` is recorded as `PROJECTED_ENROLLMENT`."

    Design: Corner/calculations/funding_provisional_input_set_excludes_withdrawn_seats
    """
    set_clock()
    award = create_grant_award(awarded_cents=5_000_000,
                               allowed_categories=["GROUP_PROGRAM"])
    space, cohort = create_open_cohort(name="Filter Group", seats_total=4,
                                       min_viable_enrollment=1,
                                       direct_cost_cents=240_000)
    keeper = create_assessed_participant(loss_type=cohort["loss_type"])
    leaver = create_assessed_participant(loss_type=cohort["loss_type"])

    kept = enroll(keeper["id"], cohort["id"], cohort["version"])
    confirm_enrollment(kept["id"])
    dropped = enroll(leaver["id"], cohort["id"])
    withdraw_enrollment(dropped["id"], "TRANSFERRED")

    mid = read_cohort(cohort["id"])
    assert mid["seats_filled"] == 1
    assert mid["seats_held"] == 0
    assert mid["seats_open"] == 3

    allocation = validate_success(
        api_client.create_funding_allocation(
            {"grant_award_id": award["id"], "category": "GROUP_PROGRAM",
             "cohort_id": cohort["id"],
             "expected_grant_award_version": award["version"]}, PD), 201)
    assert_funding_allocation(allocation)
    assert allocation["provisional_cents"] == 67_200, (
        f"Expected a one-seat projection of 67200, got {allocation['provisional_cents']}")
    assert allocation["provisional_cents"] != 134_400
    assert allocation["basis"] == "PROJECTED_ENROLLMENT"

    refreshed_award = read_grant_award(award["id"])
    assert refreshed_award["committed_cents"] == 67_200
    assert refreshed_award["available_cents"] == 4_932_800
    assert_grant_money_pool(refreshed_award)


def test_category_not_allowed_is_reported_ahead_of_a_funding_shortfall():
    """PRD 2.5: "The five matching rules — `ERR_LOSS_TYPE_MISMATCH`,
    `ERR_SPECIALTY_MISMATCH`, `ERR_LOSS_TYPE_NOT_ENDORSED`,
    `ERR_CATEGORY_NOT_ALLOWED` and `ERR_ALLOCATION_SUBJECT_MISMATCH`, all 422 —
    guard exactly four operations: enrollment creation, counselling-referral
    assignment, companion-match creation and funding-allocation creation."
    PRD 2.5: "On funding-allocation creation only, the award's `available_cents` is
    greater than or equal to the `provisional_cents` about to be committed.
    Equality passes. A shortfall yields `ERR_GRANT_FUNDS_INSUFFICIENT` (409)."

    Design: Corner/validations/referential_error_wins_over_fiscal_error_on_funding_allocation_create
    """
    set_clock()
    space = create_meeting_space(name="Hall A", capacity=60,
                                 turnover_buffer_minutes=30)
    award = create_grant_award(funder_name="Small Trust", awarded_cents=5_000,
                               allowed_categories=["COUNSELING"])
    event = create_remembrance_event(space["id"], title="Unfunded Vigil",
                                     direct_cost_cents=10_220)

    error = validate_error(
        api_client.create_funding_allocation(
            {"grant_award_id": award["id"], "category": "REMEMBRANCE_EVENT",
             "event_id": event["id"],
             "expected_grant_award_version": award["version"]}, PD),
        ApiErrorId.ERR_CATEGORY_NOT_ALLOWED.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_GRANT_FUNDS_INSUFFICIENT.value

    refreshed = read_grant_award(award["id"])
    assert refreshed["committed_cents"] == 0
    assert refreshed["version"] == 1


def test_a_one_cent_shortfall_is_refused_while_exact_equality_passes():
    """PRD 3.9: "And finally the award must be able to afford it:
    `available_cents` must be greater than or equal to the `provisional_cents`
    about to be committed, with equality passing, otherwise
    `ERR_GRANT_FUNDS_INSUFFICIENT`."
    PRD 3.9: "For a `REMEMBRANCE_EVENT` allocation there is nothing to project —
    `provisional_cents` is simply the event's `program_cost_total_cents`, and
    `basis` is recorded as `EVENT_PLAN`."

    Design: Corner/validations/funding_allocation_beyond_available_cents_returns_grant_funds_insufficient
    """
    set_clock()
    space = create_meeting_space(name="Hall A", capacity=60,
                                 turnover_buffer_minutes=30)
    short_award = create_grant_award(funder_name="Short Trust",
                                     award_reference="ST-2026-SHORT",
                                     awarded_cents=11_445,
                                     allowed_categories=["REMEMBRANCE_EVENT"])
    exact_award = create_grant_award(funder_name="Exact Trust",
                                     award_reference="ET-2026-EXACT",
                                     awarded_cents=11_446,
                                     allowed_categories=["REMEMBRANCE_EVENT"])
    event = create_remembrance_event(space["id"], title="Boundary Vigil",
                                     direct_cost_cents=10_220)

    validate_error(
        api_client.create_funding_allocation(
            {"grant_award_id": short_award["id"], "category": "REMEMBRANCE_EVENT",
             "event_id": event["id"],
             "expected_grant_award_version": short_award["version"]}, PD),
        ApiErrorId.ERR_GRANT_FUNDS_INSUFFICIENT.value, 409)
    assert read_grant_award(short_award["id"])["committed_cents"] == 0

    allocation = validate_success(
        api_client.create_funding_allocation(
            {"grant_award_id": exact_award["id"], "category": "REMEMBRANCE_EVENT",
             "event_id": event["id"],
             "expected_grant_award_version": exact_award["version"]}, PD), 201)
    assert allocation["provisional_cents"] == 11_446

    refreshed = read_grant_award(exact_award["id"])
    assert refreshed["available_cents"] == 0, "equality must pass and spend the pool"
    assert refreshed["committed_cents"] == 11_446
    assert_grant_money_pool(refreshed)


def test_an_allocation_dated_outside_the_award_window_is_refused():
    """PRD 3.9: "The allocation's effective date — the logical clock date at the
    moment of creation — must fall inside the award's window from `period_start` to
    `period_end`, taken inclusively at both ends, otherwise
    `ERR_OUTSIDE_GRANT_PERIOD`."

    Design: Corner/validations/allocation_dated_outside_the_award_window_returns_outside_grant_period
    """
    set_clock()
    space = create_meeting_space(name="Hall A", capacity=60,
                                 turnover_buffer_minutes=30)
    award = create_grant_award(funder_name="Expired Trust",
                               awarded_cents=500_000,
                               allowed_categories=["REMEMBRANCE_EVENT"],
                               period_start="2026-01-01", period_end="2026-06-30")
    event = create_remembrance_event(space["id"], title="Late Vigil",
                                     direct_cost_cents=10_220)

    validate_error(
        api_client.create_funding_allocation(
            {"grant_award_id": award["id"], "category": "REMEMBRANCE_EVENT",
             "event_id": event["id"],
             "expected_grant_award_version": award["version"]}, PD),
        ApiErrorId.ERR_OUTSIDE_GRANT_PERIOD.value, 422)

    refreshed = read_grant_award(award["id"])
    assert refreshed["committed_cents"] == 0
    assert refreshed["available_cents"] == 500_000


def test_a_forming_cohort_is_not_fundable_until_it_opens_for_enrolment():
    """PRD 3.9: "A group-programme allocation requires its cohort to be in
    `OPEN_ENROLLMENT`, `RUNNING` or `SUSPENDED`, otherwise
    `ERR_COHORT_NOT_FUNDABLE`; an event allocation requires its event to be in
    `PLANNED` or `CONFIRMED`, otherwise `ERR_EVENT_NOT_FUNDABLE`."
    PRD 3.9: "For a `GROUP_PROGRAM` allocation, the programme projects how many
    participants the cohort will actually carry: take the number of that cohort's
    seats currently held or filled, which is `seats_filled` plus `seats_held`, and
    cap it at `seats_total`. Multiply the cohort's `program_cost_total_cents` by
    that projected count, divide by `seats_total`, and round half up to a whole
    cent. The allocation's `basis` is recorded as `PROJECTED_ENROLLMENT`."

    Design: Corner/validations/group_program_allocation_against_a_forming_cohort_returns_cohort_not_fundable
    """
    set_clock()
    space = create_meeting_space(name="Chapel Room", capacity=20,
                                 turnover_buffer_minutes=30)
    award = create_grant_award(awarded_cents=5_000_000,
                               allowed_categories=["GROUP_PROGRAM"])
    cohort = create_cohort(space["id"], name="Not Fundable Yet",
                           direct_cost_cents=240_000)

    payload = {"grant_award_id": award["id"], "category": "GROUP_PROGRAM",
               "cohort_id": cohort["id"],
               "expected_grant_award_version": award["version"]}
    error = validate_error(api_client.create_funding_allocation(payload, PD),
                           ApiErrorId.ERR_COHORT_NOT_FUNDABLE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_GRANT_FUNDS_INSUFFICIENT.value

    validate_success(api_client.open_cohort_enrollment(cohort["id"], PD))
    allocation = validate_success(api_client.create_funding_allocation(payload, PD), 201)
    assert allocation["provisional_cents"] == 0, (
        "an empty cohort projects zero participants")
    assert allocation["basis"] == "PROJECTED_ENROLLMENT"
    assert allocation["status"] == "COMMITTED"

    refreshed = read_grant_award(award["id"])
    assert refreshed["committed_cents"] == 0
    assert refreshed["available_cents"] == 5_000_000


def test_allocating_against_a_closed_award_is_refused():
    """PRD 3.9: "An award may be closed only once nothing is still committed
    against it — `committed_cents` must be exactly zero — moving it
    `ACTIVE → CLOSED`. `CLOSED` is terminal, and thereafter any attempt to allocate
    money from that award or to open a report against it is refused with
    `ERR_GRANT_CLOSED`."

    Design: Corner/errors/allocation_with_grant_closed_returns_grant_closed
    """
    set_clock()
    space = create_meeting_space(name="Hall A", capacity=60,
                                 turnover_buffer_minutes=30)
    event = create_remembrance_event(space["id"], title="Closed Award Vigil",
                                     direct_cost_cents=10_220)
    award = create_grant_award(awarded_cents=500_000,
                               allowed_categories=["REMEMBRANCE_EVENT"])
    closed = validate_success(api_client.close_grant_award(award["id"], PD))
    assert closed["status"] == "CLOSED"

    validate_error(
        api_client.create_funding_allocation(
            {"grant_award_id": award["id"], "category": "REMEMBRANCE_EVENT",
             "event_id": event["id"],
             "expected_grant_award_version": closed["version"]}, PD),
        ApiErrorId.ERR_GRANT_CLOSED.value, 409)

    refreshed = read_grant_award(award["id"])
    assert refreshed["committed_cents"] == 0
    assert refreshed["available_cents"] == 500_000


def test_a_subject_that_disagrees_with_the_category_is_refused():
    """PRD 3.9: "The `category` must be a member of the award's
    `allowed_categories`, otherwise `ERR_CATEGORY_NOT_ALLOWED`; and the subject
    must match the category, meaning `cohort_id` is set for `GROUP_PROGRAM` and
    `event_id` is set for `REMEMBRANCE_EVENT`, with a mismatched or missing subject
    refused as `ERR_ALLOCATION_SUBJECT_MISMATCH`."
    PRD 2.5: "an allocation's `cohort_id` is non-null exactly when its `category`
    is `GROUP_PROGRAM` and its `event_id` is non-null exactly when its `category`
    is `REMEMBRANCE_EVENT`"

    Design: Corner/errors/allocation_subject_mismatch_when_category_and_subject_disagree
    """
    set_clock()
    space = create_meeting_space(name="Hall A", capacity=60,
                                 turnover_buffer_minutes=30)
    award = create_grant_award(
        awarded_cents=5_000_000,
        allowed_categories=["GROUP_PROGRAM", "REMEMBRANCE_EVENT"])
    event = create_remembrance_event(space["id"], title="Subject Mismatch Vigil",
                                     direct_cost_cents=10_220)

    resp = api_client.create_funding_allocation(
        {"grant_award_id": award["id"], "category": "GROUP_PROGRAM",
         "event_id": event["id"],
         "expected_grant_award_version": award["version"]}, PD)
    # The subject/category agreement rule is stated both as a request-shape rule
    # and as a matching rule, so either identifier is a faithful reading.
    assert resp.status_code == 422, (
        f"Expected HTTP 422, got {resp.status_code}: {resp.text}")
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_ALLOCATION_SUBJECT_MISMATCH.value,
               ApiErrorId.ERR_INVALID_REQUEST.value])

    refreshed = read_grant_award(award["id"])
    assert refreshed["committed_cents"] == 0


def test_releasing_an_unknown_allocation_is_not_found():
    """PRD 2.5: "Every resource named by a path segment exists, validated from left
    to right, so the leftmost missing segment determines the reported error —
    otherwise the corresponding not-found error (404)."

    Design: Corner/errors/funding_allocation_release_with_unknown_id_returns_allocation_not_found
    """
    set_clock()
    validate_error(
        api_client.release_funding_allocation(UNUSED_UUIDS["allocation"], PD),
        ApiErrorId.ERR_ALLOCATION_NOT_FOUND.value, 404)


def test_a_grant_officer_may_not_commit_programme_money():
    """PRD 2.1: "A `GrantOfficer` is a funder-side reviewer who reads the money
    surface and rules on submitted reports but never writes programme data."
    PRD 2.1: "When the role named in `X-User-Role` does not appear in the
    authorised-role list of the endpoint being addressed (see §4), the request is
    rejected with `ERR_FORBIDDEN_ROLE` and HTTP 403."

    Design: Corner/rbac/grant_officer_cannot_create_a_funding_allocation_returns_forbidden_role
    """
    set_clock()
    space = create_meeting_space(name="Hall A", capacity=60,
                                 turnover_buffer_minutes=30)
    award = create_grant_award(awarded_cents=5_000_000,
                               allowed_categories=["REMEMBRANCE_EVENT"])
    event = create_remembrance_event(space["id"], title="RBAC Vigil",
                                     direct_cost_cents=10_220)

    validate_error(
        api_client.create_funding_allocation(
            {"grant_award_id": award["id"], "category": "REMEMBRANCE_EVENT",
             "event_id": event["id"],
             "expected_grant_award_version": award["version"]}, GO),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    refreshed = read_grant_award(award["id"])
    assert refreshed["committed_cents"] == 0
    assert refreshed["version"] == 1
    rows, meta = validate_paginated(
        api_client.list_funding_allocations(
            PD, params={"grant_award_id": award["id"]}))
    assert meta["total_count"] == 0


def _setup_cancelled_event_against_a_tiny_award():
    """A cancelled event costing 11446 cents against an award holding only 5000."""
    set_clock()
    space = create_meeting_space(name="Hall A", capacity=60,
                                 turnover_buffer_minutes=30)
    award = create_grant_award(funder_name="Small Trust", awarded_cents=5_000,
                               allowed_categories=["REMEMBRANCE_EVENT"])
    event = create_remembrance_event(space["id"], title="Cancelled Vigil",
                                     direct_cost_cents=10_220)
    validate_success(api_client.cancel_remembrance_event(event["id"], PD))
    return award, event


def test_event_not_fundable_is_reported_ahead_of_the_funding_shortfall():
    """PRD 2.5: "This rung carries the generic `ERR_INVALID_STATE` and the specific
    state errors `ERR_ALREADY_TERMINAL`, `ERR_REFERRAL_NOT_SCREENED`,
    `ERR_COHORT_NOT_ENROLLING`, `ERR_COUNSELOR_NOT_ACTIVE`,
    `ERR_COMPANION_NOT_CERTIFIED`, `ERR_EVENT_NOT_CONFIRMED`, `ERR_GRANT_CLOSED`,
    `ERR_COHORT_NOT_FUNDABLE`, `ERR_EVENT_NOT_FUNDABLE`,
    `ERR_PARTICIPANT_WITHDRAWN` and `ERR_OUTREACH_NOT_DUE`, all at HTTP 409."
    PRD 2.5: "On funding-allocation creation only, the award's `available_cents` is
    greater than or equal to the `provisional_cents` about to be committed.
    Equality passes. A shortfall yields `ERR_GRANT_FUNDS_INSUFFICIENT` (409)."

    Design: Difficulty/priority_pair_validation_conflict/state_error_wins_over_fiscal_error_on_funding_allocation_create
    """
    award, event = _setup_cancelled_event_against_a_tiny_award()

    resp = api_client.create_funding_allocation(
        {"grant_award_id": award["id"], "category": "REMEMBRANCE_EVENT",
         "event_id": event["id"],
         "expected_grant_award_version": award["version"]}, PD)
    assert resp.status_code == 409, (
        f"Expected HTTP 409, got {resp.status_code}: {resp.text}")
    error = validate_error(resp, ApiErrorId.ERR_EVENT_NOT_FUNDABLE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_GRANT_FUNDS_INSUFFICIENT.value


def test_the_refused_allocation_leaves_the_award_untouched():
    """PRD 3.9: "A group-programme allocation requires its cohort to be in
    `OPEN_ENROLLMENT`, `RUNNING` or `SUSPENDED`, otherwise
    `ERR_COHORT_NOT_FUNDABLE`; an event allocation requires its event to be in
    `PLANNED` or `CONFIRMED`, otherwise `ERR_EVENT_NOT_FUNDABLE`."
    PRD 2.7: "A grant award's money pool satisfies, at all times, that
    `awarded_cents` equals `available_cents` plus `committed_cents` plus
    `spent_cents`."

    Design: Difficulty/priority_pair_validation_conflict/state_error_wins_over_fiscal_error_on_funding_allocation_create
    """
    award, event = _setup_cancelled_event_against_a_tiny_award()

    validate_error(
        api_client.create_funding_allocation(
            {"grant_award_id": award["id"], "category": "REMEMBRANCE_EVENT",
             "event_id": event["id"],
             "expected_grant_award_version": award["version"]}, PD),
        ApiErrorId.ERR_EVENT_NOT_FUNDABLE.value, 409)

    refreshed = read_grant_award(award["id"])
    assert refreshed["committed_cents"] == 0
    assert refreshed["available_cents"] == 5_000
    assert refreshed["version"] == 1, "a refused allocation must not bump the version"
    assert_grant_money_pool(refreshed)


def test_committing_money_moves_cents_from_available_into_committed():
    """PRD 2.7: "A grant award's money pool satisfies, at all times, that
    `awarded_cents` equals `available_cents` plus `committed_cents` plus
    `spent_cents`. `committed_cents` is the sum of `provisional_cents` over that
    award's allocations in status `COMMITTED`; `spent_cents` is the sum of
    `settled_cents` over that award's allocations in status `SETTLED`;
    `available_cents` is what remains after subtracting both from `awarded_cents`."
    PRD 3.9: "A created allocation lands in status `COMMITTED` with HTTP 201,
    `settled_cents` and `settled_at` null. The award's `committed_cents` increases
    by the `provisional_cents`, `available_cents` is recomputed, and the award's
    `version` increases by one."

    Design: Difficulty/compensating_invariant/grant_cents_conserved_across_allocation_commit_and_release
    """
    set_clock()
    space, event, award, allocation = setup_funded_event(
        awarded_cents=500_000, direct_cost_cents=10_220,
        title="Winter Remembrance", event_date="2026-11-10")

    assert allocation["provisional_cents"] == 11_446
    assert allocation["status"] == "COMMITTED"
    assert award["available_cents"] == 488_554
    assert award["committed_cents"] == 11_446
    assert award["spent_cents"] == 0
    assert_grant_money_pool(award)


def test_releasing_the_commitment_restores_every_cent_to_the_award():
    """PRD 3.9: "Release moves the allocation `COMMITTED → RELEASED`, leaves
    `settled_cents` null, decreases the award's `committed_cents` by the
    `provisional_cents`, recomputes `available_cents`, and increments the award's
    `version`."
    PRD 2.7: "A grant award's money pool satisfies, at all times, that
    `awarded_cents` equals `available_cents` plus `committed_cents` plus
    `spent_cents`."

    Design: Difficulty/compensating_invariant/grant_cents_conserved_across_allocation_commit_and_release
    """
    set_clock()
    space, event, award, allocation = setup_funded_event(
        awarded_cents=500_000, direct_cost_cents=10_220,
        title="Winter Remembrance", event_date="2026-11-10")
    assert award["available_cents"] == 488_554
    assert award["committed_cents"] == 11_446

    validate_success(api_client.release_funding_allocation(allocation["id"], PD))

    released = read_funding_allocation(allocation["id"])
    assert released["status"] == "RELEASED"
    assert released["provisional_cents"] == 11_446
    assert released["settled_cents"] is None

    refreshed = read_grant_award(award["id"])
    assert refreshed["awarded_cents"] == 500_000
    assert refreshed["committed_cents"] == 0
    assert refreshed["spent_cents"] == 0
    assert refreshed["available_cents"] == 500_000
    assert_grant_money_pool(refreshed)
