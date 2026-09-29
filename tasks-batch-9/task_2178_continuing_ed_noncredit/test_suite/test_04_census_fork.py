"""The census decision: locking a section, cancelling it, and the retirement gate."""

from test_helpers import (
    ADMIN,
    COURSE_EXT_101,
    REGISTRAR,
    ApiErrorId,
    add_paid_registration,
    assert_sponsor_ledger_conserved,
    assert_voucher_value_conserved,
    create_offering_payload,
    new_course,
    pay_with_voucher,
    read_account,
    read_contract,
    read_registration,
    read_voucher,
    reset_clock,
    set_clock,
    setup_census_headcount_boundary_scene,
    setup_open_offering,
    setup_voucher_funded_enrollment,
    validate_error,
    validate_success,
)


class TestCensusCancellationCascade:
    """A short section unwinds registration, voucher and sponsor ledger in one call."""

    def test_cancellation_withdraws_and_fully_refunds_the_voucher_registration(self, api):
        """PRD 3.6: "**Hop one**: the section moves `OPEN → CANCELLED` or
        `WAITLIST_ONLY → CANCELLED`, again identically from either starting state, and
        its `cancellation_reason` is set to `MIN_ENROLLMENT_NOT_MET`."
        PRD 3.6: "**Hop two**, caused by hop one: every registration on the section
        whose `enrollment_status` is `PENDING`, `ENROLLED` or `WAITLISTED` moves to
        `WITHDRAWN`, and where its `payment_status` was `PAID`, `VOUCHER_COMMITTED` or
        `PARTIALLY_REFUNDED`, that axis moves to `REFUNDED` with `amount_refunded_cents`
        set to `amount_paid_cents`."

        Design: Difficulty/transitive_cascade/census_cancellation_four_hop_registration_voucher_sponsor_chain
        """
        reset_clock()
        scene = setup_voucher_funded_enrollment()
        pay_with_voucher(scene["registration_id"], scene["voucher_id"], scene["learner_id"])
        set_clock("2026-09-05T00:00:00Z")

        offering = validate_success(api.census_offering(scene["offering_id"], ADMIN))
        assert offering["status"] == "CANCELLED"
        assert offering["cancellation_reason"] == "MIN_ENROLLMENT_NOT_MET"
        assert offering["net_program_revenue_cents"] == 0

        registration = read_registration(scene["registration_id"])
        assert registration["enrollment_status"] == "WITHDRAWN"
        assert registration["payment_status"] == "REFUNDED"
        assert registration["amount_refunded_cents"] == 62400

    def test_cancellation_releases_voucher_value_and_rebalances_the_sponsor_ledger(self, api):
        """PRD 3.6: "**Hop three**, caused by hop two and applying only to registrations
        whose `voucher_id` is not null: the backing voucher releases the registration's
        value, decreasing whichever of `committed_cents` or `consumed_cents` held it by
        `total_due_cents` and increasing `remaining_cents` by the same amount, after
        which the voucher's `status` is re-derived as described below."
        PRD 3.6: "A voucher returns all the way to `ASSIGNED` — from either `EXHAUSTED`
        or `PARTIALLY_REDEEMED` — when the release leaves both `committed_cents` and
        `consumed_cents` at exactly zero; in the `EXHAUSTED` case this coincides with
        `remaining_cents` having been restored to the full `face_value_cents`."
        PRD 3.8: "When the census fork of §3.6 terminates a contract without fault,
        `kill_fee_cents` is computed as `base_stipend_cents` multiplied by a kill-fee
        rate of 25 percent and then by the same credential multiplier — 1.00 for
        `ADJUNCT`, 1.15 for `SENIOR`, 1.30 for `MASTER` — with a single half-up rounding
        to whole cents applied to the fully multiplied product."

        Design: Difficulty/transitive_cascade/census_cancellation_four_hop_registration_voucher_sponsor_chain
        """
        reset_clock()
        scene = setup_voucher_funded_enrollment()
        pay_with_voucher(scene["registration_id"], scene["voucher_id"], scene["learner_id"])
        set_clock("2026-09-05T00:00:00Z")
        api.census_offering(scene["offering_id"], ADMIN)

        voucher = read_voucher(scene["voucher_id"], scene["account_id"])
        assert voucher["remaining_cents"] == 200000
        assert voucher["committed_cents"] == 0
        assert voucher["consumed_cents"] == 0
        assert voucher["status"] == "ASSIGNED"
        assert_voucher_value_conserved(voucher)

        account = read_account(scene["account_id"])
        assert account["funded_cents"] == 500000
        assert account["available_cents"] == 300000
        assert account["unallocated_voucher_cents"] == 200000
        assert account["committed_cents"] == 0
        assert account["consumed_cents"] == 0
        assert_sponsor_ledger_conserved(account)

        contract = read_contract(scene["contract_id"])
        assert contract["status"] == "TERMINATED_NO_FAULT"
        assert contract["kill_fee_cents"] == 71875, (
            f"250000 * 0.25 * 1.15 rounds to 71875, got {contract['kill_fee_cents']}"
        )


class TestCensusHeadcountBoundary:
    """paid_enrollment_count is compared against min_enrollment inclusively."""

    def test_exactly_the_minimum_headcount_locks_the_section(self, api):
        """PRD 3.6: "From there the decision forks on one comparison: whether the
        section's `paid_enrollment_count` is at least its `min_enrollment`."
        PRD 3.6: "Every contract on the section whose `status` is `OFFERED`, `SIGNED`
        or `ACTIVE` has its `census_headcount` frozen to the section's
        `paid_enrollment_count` as of this instant — a number that later withdrawals,
        no-shows and completions will never move."

        Design: Difficulty/boundary_precision_check/census_headcount_boundary_exactly_min_runs_one_short_cancels
        """
        reset_clock()
        scene = setup_census_headcount_boundary_scene()
        offering = validate_success(api.census_offering(scene["at_id"], ADMIN))
        assert offering["paid_enrollment_count"] == 3
        assert offering["status"] == "CENSUS_LOCKED"

        contract = read_contract(scene["at_contract_id"])
        assert contract["census_headcount"] == 3
        first = read_registration(scene["at_registration_ids"][0])
        assert first["enrollment_status"] == "ENROLLED"

    def test_one_short_of_the_minimum_cancels_the_section(self, api):
        """PRD 3.6: "When the paid headcount falls short of `min_enrollment`, the
        section is cancelled and a four-hop cascade unwinds everything hanging off it."
        PRD 3.6: "**Hop one**: the section moves `OPEN → CANCELLED` or `WAITLIST_ONLY →
        CANCELLED`, again identically from either starting state, and its
        `cancellation_reason` is set to `MIN_ENROLLMENT_NOT_MET`."
        PRD 3.6: "Alongside that chain, and caused by hop one rather than being part of
        it, a fan-out runs over teaching staff: every contract on the cancelled section
        whose `status` is `OFFERED`, `SIGNED` or `ACTIVE` moves to
        `TERMINATED_NO_FAULT`, a terminal state, and has its `kill_fee_cents` computed."
        PRD 3.2: "`paid_enrollment_count` is the number whose `enrollment_status` is
        `ENROLLED` **and** whose `payment_status` is either `PAID` or
        `VOUCHER_COMMITTED`" - so the one-short headcount that drives the fork is read
        before the cascade withdraws every seat.

        Design: Difficulty/boundary_precision_check/census_headcount_boundary_exactly_min_runs_one_short_cancels
        """
        reset_clock()
        scene = setup_census_headcount_boundary_scene()
        before = validate_success(api.get_offering(scene["under_id"], ADMIN))
        assert before["paid_enrollment_count"] == 2
        offering = validate_success(api.census_offering(scene["under_id"], ADMIN))
        assert offering["status"] == "CANCELLED"
        assert offering["cancellation_reason"] == "MIN_ENROLLMENT_NOT_MET"

        contract = read_contract(scene["under_contract_id"])
        assert contract["status"] == "TERMINATED_NO_FAULT"
        withdrawn = read_registration(scene["under_registration_ids"][0])
        assert withdrawn["enrollment_status"] == "WITHDRAWN"


def test_census_before_census_at_returns_census_too_early(api):
    """PRD 3.6: "It is permitted only while the section is `OPEN` or `WAITLIST_ONLY` —
    anything else is `ERR_INVALID_STATE` — and only once the logical clock has reached
    or passed the section's `census_at`; taking it earlier is refused with
    `ERR_CENSUS_TOO_EARLY` (HTTP 409)."
    PRD 3.2: "A newly offered contract sits in `status` `OFFERED` with
    `census_headcount`, `final_headcount`, `settled_pay_cents` and `kill_fee_cents` all
    null."

    Design: Corner/state_machines/census_before_census_at_returns_census_too_early
    """
    reset_clock()
    scene = setup_open_offering()
    add_paid_registration(scene["offering_id"], learner_index=0)
    set_clock("2026-08-31T23:59:59Z")

    validate_error(
        api.census_offering(scene["offering_id"], ADMIN),
        ApiErrorId.ERR_CENSUS_TOO_EARLY,
        409,
    )
    offering = validate_success(api.get_offering(scene["offering_id"], ADMIN))
    assert offering["status"] == "OPEN"
    assert offering["paid_enrollment_count"] == 1
    contract = read_contract(scene["contract_id"])
    assert contract["census_headcount"] is None


def test_closeout_before_end_date_returns_offering_not_ended(api):
    """PRD 3.8: "Closeout requires the section to be `CENSUS_LOCKED` and requires the
    logical clock to have reached or passed the section's `end_date`; an early attempt
    is refused with `ERR_OFFERING_NOT_ENDED` (HTTP 409)."

    Design: Corner/state_machines/complete_offering_before_end_date_returns_offering_not_ended
    """
    reset_clock()
    scene = setup_open_offering()
    seat = add_paid_registration(scene["offering_id"], learner_index=0)
    set_clock("2026-09-01T00:00:00Z")
    validate_success(api.census_offering(scene["offering_id"], ADMIN))

    validate_error(
        api.complete_offering(scene["offering_id"], ADMIN),
        ApiErrorId.ERR_OFFERING_NOT_ENDED,
        409,
    )
    offering = validate_success(api.get_offering(scene["offering_id"], ADMIN))
    assert offering["status"] == "CENSUS_LOCKED"
    registration = read_registration(seat["registration_id"])
    assert registration["enrollment_status"] == "ENROLLED"


def test_retire_is_blocked_while_a_live_section_references_the_course(api):
    """PRD 3.1: "Retirement, which a `ProgramAdmin` performs, moves the course
    `ACTIVE → RETIRED` and increments the course's `version` by 1, but it is permitted
    only when `active_offering_count` is exactly 0; a retirement attempt while any live
    section still references the course is rejected with `ERR_INVALID_STATE`."
    PRD 3.1: "That counter tracks the number of sections of the course whose own status
    is `DRAFT`, `OPEN`, `WAITLIST_ONLY` or `CENSUS_LOCKED` — in other words, sections
    that are still in play. Sections that have reached `COMPLETED` or `CANCELLED` no
    longer count."

    Design: Corner/endpoints/retire_course_with_live_offering_returns_invalid_state
    """
    reset_clock()
    scene = setup_open_offering(offering_overrides={"min_enrollment": 3})
    set_clock("2026-09-01T00:00:00Z")

    validate_error(
        api.retire_course(scene["course_id"], ADMIN), ApiErrorId.ERR_INVALID_STATE, 409
    )

    cancelled = validate_success(api.census_offering(scene["offering_id"], ADMIN))
    assert cancelled["status"] == "CANCELLED"

    retired = validate_success(api.retire_course(scene["course_id"], ADMIN))
    assert retired["status"] == "RETIRED"
    assert retired["active_offering_count"] == 0
    contract = read_contract(scene["contract_id"])
    assert contract["status"] == "TERMINATED_NO_FAULT"


def test_offering_create_on_retired_course_returns_course_retired(api):
    """PRD 3.1: "`RETIRED` is terminal. A retired course may not back a newly created
    section, may not have a draft section published, and may not be the target of a
    credit-for-prior-learning petition submission; all three are rejected with
    `ERR_COURSE_RETIRED`."
    PRD 2.8: "Course currency — the referenced course is `ACTIVE`; otherwise
    `ERR_COURSE_RETIRED`."

    Design: Corner/errors/offering_create_on_retired_course_returns_course_retired
    """
    reset_clock()
    course = new_course(**COURSE_EXT_101)
    retired = validate_success(api.retire_course(course["id"], ADMIN))
    assert retired["status"] == "RETIRED"

    validate_error(
        api.create_offering(create_offering_payload(course["id"]), ADMIN),
        ApiErrorId.ERR_COURSE_RETIRED,
        422,
    )
    after = validate_success(api.get_course(course["id"], REGISTRAR))
    assert after["active_offering_count"] == 0
