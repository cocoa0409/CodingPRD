"""Validation surface, money edge: the release gates in their pinned order, the
report submission ladder and the sequencing rule that only acceptance satisfies.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    define_tier,
    enrol_member,
    fiscal_period_action,
    list_proposal_reports,
    open_fiscal_period,
    publish_tier,
    record_board_override,
    member_lifecycle,
    read_fiscal_period,
    read_member,
    read_proposal,
    read_report,
    read_sustainability,
    record_contribution,
    release_funds,
    review_report,
    run_daily_sweep,
    set_clock,
    settle_contribution,
    setup_awarded_restricted_proposal,
    setup_awarded_unrestricted_proposal,
    submit_report,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import BO_HEADERS, DO_HEADERS, FC_HEADERS


def _release(proposal_id, request_amount_cents):
    return api_client.release_restricted_funds(
        proposal_id, {"request_amount_cents": request_amount_cents}, FC_HEADERS
    )


def _submit(report_id, spend_reported_cents):
    return api_client.submit_grant_report(
        report_id, {"spend_reported_cents": spend_reported_cents}, DO_HEADERS
    )


def _setup_award_in_a_period_holding_only_150000():
    """A PROJECT_RESTRICTED 350000-cent award inside a period whose reserve is
    below one month of expenses."""
    return setup_awarded_restricted_proposal(
        requested_amount_cents=350000,
        award_date="2026-08-01",
        reporting_cadence="SEMIANNUAL",
        restriction_type="PROJECT_RESTRICTED",
        restriction_start_date="2026-09-01",
        restriction_end_date="2027-07-31",
        reserve_balance_cents=150000,
        legal_name="Ironwood Trust",
        title="Housing accountability project",
    )


class TestCriticalPostureBlocksAReleaseOfAnySize:
    def test_the_posture_ladder_lands_on_critical_with_a_zero_cap(self):
        """150000 against a 200000 monthly base is below one month of expenses, so
        the first branch of the ladder matches and the cap collapses to 0.

        PRD: "the posture is `CRITICAL` if `reserve_balance_cents` is strictly below
        `monthly_expense_base_cents`"

        Design: Corner/Validations/val_critical_posture_blocks_a_release_of_any_size
        """
        ctx = _setup_award_in_a_period_holding_only_150000()

        picture = read_sustainability(ctx["period"]["id"])
        assert picture["concentration_hhi"] == 10000
        assert picture["top_source_share_bps"] == 10000
        assert picture["reserve_months_target"] == 5
        assert picture["reserve_months_ratio_bps"] == 7500
        assert picture["sustainability_posture"] == "CRITICAL"
        assert picture["restricted_release_cap_pct_bps"] == 0

    def test_even_a_one_cent_release_is_refused_before_the_cap_amount(self):
        """A single cent would satisfy any percentage cap, yet the posture gate runs
        first and reports its own code.

        PRD: "The fiscal period's `restricted_release_cap_pct_bps` must be greater
        than 0 - that is, `sustainability_posture` must not be `CRITICAL`. A
        `CRITICAL` posture blocks a release of any size, which is why this is checked
        before the cap amount. Failure is `ERR_POSTURE_BLOCKS_RELEASE` (HTTP 409)."

        Design: Corner/Validations/val_critical_posture_blocks_a_release_of_any_size
        """
        ctx = _setup_award_in_a_period_holding_only_150000()

        validate_error(
            _release(ctx["proposal"]["id"], 1), ApiErrorId.ERR_POSTURE_BLOCKS_RELEASE
        )

        blocked = read_proposal(ctx["proposal"]["id"])
        assert blocked["released_cents"] == 0
        assert blocked["unreleased_cents"] == 350000
        assert read_fiscal_period(ctx["period"]["id"])["reserve_balance_cents"] == 150000


def _setup_diversified_period_at_a_healthy_posture():
    """A 350000-cent UNRESTRICTED award with no reporting obligations, alongside
    300000 of settled membership and 300000 of settled events revenue, in a period
    holding a fully funded 1000000-cent reserve."""
    ctx = setup_awarded_unrestricted_proposal(
        requested_amount_cents=350000,
        award_date="2026-08-01",
        reporting_cadence="NONE",
        reserve_balance_cents=1000000,
        legal_name="Ironwood Trust",
        title="General operating support",
    )
    tier = publish_tier(
        define_tier(
            benefits=[],
            tier_code="SUSTAINER",
            name="Sustainer",
            renewal_cadence="MONTHLY",
            contribution_amount_cents=2500,
        )["id"]
    )
    member = enrol_member(tier["id"], email="ana@example.org", full_name="Ana Ruiz")
    membership = record_contribution(
        ctx["period"]["id"],
        "MEMBERSHIP",
        300000,
        member_id=member["id"],
        received_date="2026-08-01",
    )
    settle_contribution(membership["id"])
    events = record_contribution(
        ctx["period"]["id"],
        "EVENTS",
        300000,
        received_date="2026-08-01",
        source_label="Annual benefit dinner",
    )
    settle_contribution(events["id"])
    ctx["tier"] = tier
    ctx["member"] = member
    return ctx


class TestReleaseAboveWaterfallCapacityUnderAHealthyPosture:
    def test_three_streams_and_a_full_reserve_produce_a_healthy_posture(self):
        """Membership, events and grant revenue split 3158/3158/3684, which is
        concentrated enough to raise the target to five months and no more.

        PRD: "Third, `reserve_months_target` starts at a base of 3 months and gains
        one month if `concentration_hhi` is at least 3000 and one further month if
        `top_source_share_bps` is at least 3500 - so the target is 3, 4 or 5 months."

        Design: Corner/Validations/val_release_above_waterfall_capacity_under_a_healthy_posture_reports_release_exceeds_award
        """
        ctx = _setup_diversified_period_at_a_healthy_posture()

        picture = read_sustainability(ctx["period"]["id"])
        assert picture["recognized_revenue_cents"] == 950000
        assert picture["membership_share_bps"] == 3158
        assert picture["events_share_bps"] == 3158
        assert picture["grants_share_bps"] == 3684
        assert picture["concentration_hhi"] == 3352
        assert picture["top_source_share_bps"] == 3684
        assert picture["reserve_months_target"] == 5
        assert picture["operating_reserve_target_cents"] == 1000000
        assert picture["sustainability_posture"] == "HEALTHY"
        assert picture["restricted_release_cap_pct_bps"] == 10000

    def test_one_cent_over_the_award_is_caught_by_the_capacity_gate(self):
        """The 10000-bps cap is vacuous and its gate is skipped, so the overflow is
        reported by the waterfall instead.

        PRD: "It is **skipped entirely when the cap is 10000 bps** (a `HEALTHY`
        posture), because the cap then equals the whole unreleased principal and adds
        nothing - an over-large request under a `HEALTHY` posture is reported by the
        next gate instead."

        Design: Corner/Validations/val_release_above_waterfall_capacity_under_a_healthy_posture_reports_release_exceeds_award
        """
        ctx = _setup_diversified_period_at_a_healthy_posture()

        validate_error(
            _release(ctx["proposal"]["id"], 350001),
            ApiErrorId.ERR_RELEASE_EXCEEDS_AWARD,
        )

        blocked = read_proposal(ctx["proposal"]["id"])
        assert blocked["released_cents"] == 0
        assert blocked["unreleased_cents"] == 350000
        assert read_fiscal_period(ctx["period"]["id"])["reserve_balance_cents"] == 1000000

    def test_the_whole_award_releases_against_the_single_implicit_bucket(self):
        """A cadence of NONE leaves one implicit bucket holding the entire
        principal, so exactly 350000 is releasable and no more.

        PRD: "A proposal whose cadence is `NONE` has no reports and therefore behaves
        as though it had a single implicit bucket holding the whole awarded amount,
        releasable subject only to the posture cap."

        Design: Corner/Validations/val_release_above_waterfall_capacity_under_a_healthy_posture_reports_release_exceeds_award
        """
        ctx = _setup_diversified_period_at_a_healthy_posture()
        assert ctx["proposal"]["report_count"] == 0

        released = release_funds(ctx["proposal"]["id"], 350000)
        assert released["released_cents"] == 350000
        assert released["unreleased_cents"] == 0
        assert released["returned_cents"] == 0
        assert read_fiscal_period(ctx["period"]["id"])["reserve_balance_cents"] == 1350000


def _setup_award_with_180000_released():
    """The PROJECT_RESTRICTED 350001-cent award over two semiannual buckets after a
    180000-cent release, so bucket 1 has consumed 175000 and bucket 2 has consumed
    5000."""
    ctx = setup_awarded_restricted_proposal(
        requested_amount_cents=350001,
        award_date="2026-08-01",
        reporting_cadence="SEMIANNUAL",
        restriction_type="PROJECT_RESTRICTED",
        restriction_start_date="2026-09-01",
        restriction_end_date="2027-07-31",
        legal_name="Ironwood Trust",
        title="Housing accountability project",
    )
    release_funds(ctx["proposal"]["id"], 180000)
    ctx["reports"] = list_proposal_reports(ctx["proposal"]["id"])
    return ctx


class TestSpendExceedsReleaseOutranksThePeriodNotElapsedGate:
    def test_reporting_one_cent_more_than_the_bucket_received_is_refused_first(self):
        """The report is doubly offensive - too much spend and too early - and the
        first of the three gates is the one reported.

        PRD: "The declared spend may not exceed the report's own
        `consumed_release_cents`, because a newsroom cannot report spending money it
        never received: `ERR_SPEND_EXCEEDS_RELEASE` (HTTP 422)."

        Design: Corner/Validations/val_spend_exceeds_release_outranks_report_period_not_elapsed
        """
        ctx = _setup_award_with_180000_released()
        first = ctx["reports"][0]
        assert first["consumed_release_cents"] == 175000

        validate_error(
            _submit(first["id"], 175001), ApiErrorId.ERR_SPEND_EXCEEDS_RELEASE
        )

    def test_a_legal_amount_falls_through_to_the_elapsed_period_gate(self):
        """With the spend inside the bucket the same call at the same clock reaches
        the third gate instead.

        PRD: "And the reporting period must have elapsed, meaning the logical clock's
        date must be on or after `period_end`: `ERR_REPORT_PERIOD_NOT_ELAPSED` (HTTP
        409)."

        Design: Corner/Validations/val_spend_exceeds_release_outranks_report_period_not_elapsed
        """
        ctx = _setup_award_with_180000_released()
        first = ctx["reports"][0]
        assert first["period_end"] == "2027-02-28"

        validate_error(
            _submit(first["id"], 175000), ApiErrorId.ERR_REPORT_PERIOD_NOT_ELAPSED
        )

    def test_neither_refusal_writes_anything_to_the_obligation(self):
        """Both attempts leave the report exactly as the award cascade created it.

        PRD: "Every generated report begins in status `SCHEDULED` with
        `consumed_release_cents` at 0 and `spend_reported_cents`, `variance_bps` and
        `submitted_at` all null."

        Design: Corner/Validations/val_spend_exceeds_release_outranks_report_period_not_elapsed
        """
        ctx = _setup_award_with_180000_released()
        first = ctx["reports"][0]
        _submit(first["id"], 175001)
        _submit(first["id"], 175000)

        unchanged = read_report(first["id"])
        assert unchanged["status"] == "SCHEDULED"
        assert unchanged["spend_reported_cents"] is None
        assert unchanged["variance_bps"] is None
        assert unchanged["submitted_at"] is None
        assert unchanged["consumed_release_cents"] == 175000


def _setup_two_elapsed_obligations():
    """The same two-bucket award with the clock moved past both period ends and no
    sweep run, so both reports are still SCHEDULED."""
    ctx = _setup_award_with_180000_released()
    set_clock("2027-08-01T00:00:00Z")
    ctx["reports"] = list_proposal_reports(ctx["proposal"]["id"])
    return ctx


class TestReportSequenceRequiresTheEarlierBucketToBeAccepted:
    def test_the_second_report_is_refused_while_the_first_is_scheduled(self):
        """Sequence 2 cannot go first even though its own period has elapsed and its
        spend is inside its bucket.

        PRD: "Reports must be submitted in order, meaning every report of the same
        proposal with a lower `sequence_no` must already be in `ACCEPTED` or
        `WAIVED`: `ERR_REPORT_SEQUENCE_VIOLATION` (HTTP 409)."

        Design: Corner/Validations/val_report_sequence_requires_the_earlier_bucket_to_be_accepted_not_merely_submitted
        """
        ctx = _setup_two_elapsed_obligations()
        first, second = ctx["reports"]
        assert first["status"] == "SCHEDULED"

        validate_error(
            _submit(second["id"], 5000), ApiErrorId.ERR_REPORT_SEQUENCE_VIOLATION
        )
        assert read_report(second["id"])["status"] == "SCHEDULED"

    def test_a_merely_submitted_predecessor_still_blocks_the_successor(self):
        """Report 1 in SUBMITTED is no longer SCHEDULED and yet the gate refuses
        report 2 again, which is what shows the test is on the accepted set.

        PRD: "Submission stamps `submitted_at` with the logical clock and computes
        `variance_bps` as 10000 times the difference between `spend_reported_cents`
        and `consumed_release_cents`, divided by `consumed_release_cents`, rounded
        half up - a signed figure, negative when the newsroom underspent - and
        defined as 0 when `consumed_release_cents` is 0."

        Design: Corner/Validations/val_report_sequence_requires_the_earlier_bucket_to_be_accepted_not_merely_submitted
        """
        ctx = _setup_two_elapsed_obligations()
        first, second = ctx["reports"]

        submitted = submit_report(first["id"], 175000)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["variance_bps"] == 0

        validate_error(
            _submit(second["id"], 5000), ApiErrorId.ERR_REPORT_SEQUENCE_VIOLATION
        )
        assert read_report(second["id"])["status"] == "SCHEDULED"

    def test_acceptance_of_the_first_report_admits_the_second(self):
        """Only once report 1 is ACCEPTED does the byte-identical submission of
        report 2 succeed.

        PRD: "Acceptance is terminal for the report and recomputes the proposal's
        `compliance_flag`, which is what finally lifts a `DELINQUENT` flag -
        submitting an overdue report is not enough, the flag stays `DELINQUENT` until
        the report is accepted."

        Design: Corner/Validations/val_report_sequence_requires_the_earlier_bucket_to_be_accepted_not_merely_submitted
        """
        ctx = _setup_two_elapsed_obligations()
        first, second = ctx["reports"]
        submit_report(first["id"], 175000)
        _submit(second["id"], 5000)

        accepted = review_report(first["id"], "ACCEPT")
        assert accepted["status"] == "ACCEPTED"

        admitted = submit_report(second["id"], 5000)
        assert admitted["status"] == "SUBMITTED"
        assert admitted["variance_bps"] == 0


def _period_action(period_id, action):
    return api_client.fiscal_period_status_action(
        period_id, {"action": action}, FC_HEADERS
    )


def _setup_single_funder_period():
    """A period whose entire recognized revenue is one unrestricted 350000-cent
    award, so the concentration index sits at its maximum."""
    return setup_awarded_unrestricted_proposal(
        requested_amount_cents=350000,
        award_date="2026-08-01",
        reporting_cadence="NONE",
        legal_name="Ironwood Trust",
        title="General operating support",
    )


_OVERRIDE_JUSTIFICATION = (
    "Board reviewed the single-funder concentration on 2026-08-01 and accepted "
    "the risk."
)


class TestReviewLockIsBlockedByConcentrationUntilTheBoardOverrides:
    def test_a_wholly_concentrated_period_cannot_be_locked(self):
        """One funder means an index of 10000, far past the 4500 board-review line,
        so the lock is refused and the period stays OPEN.

        PRD: "A lock is refused with `ERR_CONCENTRATION_BOARD_REVIEW_REQUIRED` when
        the freshly computed `concentration_hhi` has reached 4500 or more and no board
        override is on file for the period - concentration that severe is a matter for
        the board before the books are frozen for review."

        Design: Corner/Validations/val_review_lock_blocked_by_concentration_until_the_board_records_an_override
        """
        ctx = _setup_single_funder_period()
        assert read_sustainability(ctx["period"]["id"])["concentration_hhi"] == 10000

        validate_error(
            _period_action(ctx["period"]["id"], "LOCK"),
            ApiErrorId.ERR_CONCENTRATION_BOARD_REVIEW_REQUIRED,
        )

        unchanged = read_fiscal_period(ctx["period"]["id"])
        assert unchanged["status"] == "OPEN"
        assert unchanged["locked_at"] is None
        assert unchanged["board_override_active"] is False

    def test_the_override_is_a_self_loop_that_leaves_the_period_open(self):
        """The board's lever records the justification and flips one flag without
        moving the period or its sustainability figures.

        PRD: "The override is a self-loop: it leaves the period's status exactly as it
        found it - it is legal both from `OPEN` and from `REVIEW_LOCKED` - and it sets
        `board_override_active` to true while storing the supplied `justification`
        text into `board_override_justification`."

        Design: Corner/Validations/val_review_lock_blocked_by_concentration_until_the_board_records_an_override
        """
        ctx = _setup_single_funder_period()

        overridden = record_board_override(
            ctx["period"]["id"], _OVERRIDE_JUSTIFICATION
        )
        assert overridden["status"] == "OPEN"
        assert overridden["board_override_active"] is True
        assert overridden["board_override_justification"] == _OVERRIDE_JUSTIFICATION

        picture = read_sustainability(ctx["period"]["id"])
        assert picture["reserve_months_target"] == 5
        assert picture["sustainability_posture"] == "WATCH"

    def test_the_identical_lock_succeeds_once_the_override_is_on_file(self):
        """Nothing about the concentration changes; only the override does.

        PRD: "Once on file, the override is what lets a severely concentrated period
        lock and a reserve-thin period close."

        Design: Corner/Validations/val_review_lock_blocked_by_concentration_until_the_board_records_an_override
        """
        ctx = _setup_single_funder_period()
        _period_action(ctx["period"]["id"], "LOCK")
        record_board_override(ctx["period"]["id"], _OVERRIDE_JUSTIFICATION)

        locked = fiscal_period_action(ctx["period"]["id"], "LOCK")
        assert locked["status"] == "REVIEW_LOCKED"
        assert locked["locked_at"].startswith("2026-08-01T00:00:00")

    def test_a_second_override_is_refused_as_not_warranted(self):
        """The grounds are still there but the override may not be filed twice.

        PRD: "It also may not be filed twice; `board_override_active` must still be
        false."

        Design: Corner/Validations/val_review_lock_blocked_by_concentration_until_the_board_records_an_override
        """
        ctx = _setup_single_funder_period()
        record_board_override(ctx["period"]["id"], _OVERRIDE_JUSTIFICATION)
        fiscal_period_action(ctx["period"]["id"], "LOCK")

        validate_error(
            api_client.fiscal_period_board_override(
                ctx["period"]["id"],
                {"justification": "Duplicate override attempt."},
                BO_HEADERS,
            ),
            ApiErrorId.ERR_BOARD_OVERRIDE_NOT_WARRANTED,
        )

        unchanged = read_fiscal_period(ctx["period"]["id"])
        assert unchanged["status"] == "REVIEW_LOCKED"
        assert unchanged["board_override_justification"] == _OVERRIDE_JUSTIFICATION


def _setup_locked_period_with_one_initiated_receipt():
    """A REVIEW_LOCKED period holding a single INITIATED 300000-cent events
    receipt, in a reserve position that is otherwise healthy."""
    period = open_fiscal_period(reserve_balance_cents=1000000)
    contribution = record_contribution(
        period["id"],
        "EVENTS",
        300000,
        received_date="2026-08-01",
        source_label="Annual benefit dinner",
    )
    period = fiscal_period_action(period["id"], "LOCK")
    return {"period": period, "contribution": contribution}


class TestCloseIsBlockedWhileAContributionIsStillInitiated:
    def test_an_unrecognized_receipt_still_blocks_the_close(self):
        """The INITIATED receipt contributes nothing to recognized revenue and yet
        the first close gate stops the period dead.

        PRD: "First, no contribution of the period may still be sitting in settlement
        status `INITIATED`; if any is, the close fails with
        `ERR_UNSETTLED_CONTRIBUTIONS`."

        Design: Corner/Validations/val_close_is_blocked_while_a_contribution_is_still_initiated
        """
        ctx = _setup_locked_period_with_one_initiated_receipt()
        assert ctx["period"]["status"] == "REVIEW_LOCKED"
        assert read_sustainability(ctx["period"]["id"])["recognized_revenue_cents"] == 0

        validate_error(
            _period_action(ctx["period"]["id"], "CLOSE"),
            ApiErrorId.ERR_UNSETTLED_CONTRIBUTIONS,
        )
        assert read_fiscal_period(ctx["period"]["id"])["status"] == "REVIEW_LOCKED"

    def test_resolving_the_receipt_as_failed_is_enough(self):
        """The money never arrives, so recognized revenue stays at 0, and yet the
        blocking condition is gone.

        PRD: "`FAILED` recognizes nothing and leaves a `PENDING` member `PENDING`."

        Design: Corner/Validations/val_close_is_blocked_while_a_contribution_is_still_initiated
        """
        ctx = _setup_locked_period_with_one_initiated_receipt()
        fiscal_period_action(ctx["period"]["id"], "UNLOCK")

        failed = settle_contribution(ctx["contribution"]["id"], outcome="FAILED")
        assert failed["settlement_status"] == "FAILED"
        assert read_sustainability(ctx["period"]["id"])["recognized_revenue_cents"] == 0

    def test_the_identical_close_succeeds_once_nothing_is_initiated(self):
        """The same LOCK-then-CLOSE pair now freezes the books with the posture the
        period held.

        PRD: "`CLOSE` takes a `REVIEW_LOCKED` period to `CLOSED` and freezes every
        computed sustainability field at the value it then holds."

        Design: Corner/Validations/val_close_is_blocked_while_a_contribution_is_still_initiated
        """
        ctx = _setup_locked_period_with_one_initiated_receipt()
        _period_action(ctx["period"]["id"], "CLOSE")
        fiscal_period_action(ctx["period"]["id"], "UNLOCK")
        settle_contribution(ctx["contribution"]["id"], outcome="FAILED")
        fiscal_period_action(ctx["period"]["id"], "LOCK")

        closed = fiscal_period_action(ctx["period"]["id"], "CLOSE")
        assert closed["status"] == "CLOSED"
        assert read_sustainability(ctx["period"]["id"])["sustainability_posture"] == "HEALTHY"


def _record_events_receipt(period_id):
    return api_client.create_contribution(
        {
            "fiscal_period_id": period_id,
            "revenue_stream": "EVENTS",
            "amount_cents": 1000,
            "received_date": "2026-08-01",
            "source_label": "Trivia night",
        },
        DO_HEADERS,
    )


class TestALockedPeriodRejectsANewContributionUntilItIsUnlocked:
    def test_the_gate_reads_the_period_named_in_the_body(self):
        """The contribution itself is impeccable; it is the referenced period's
        status that refuses the write.

        PRD: "Every financial write bound to a period in `REVIEW_LOCKED` or `CLOSED`
        is rejected with `ERR_PERIOD_LOCKED`, and that covers seven operations:
        recording a contribution, settling a contribution, refunding a contribution,
        accepting a gift offer, recording a grant outcome, releasing restricted grant
        funds, and driving a collaboration's status."

        Design: Corner/Validations/val_locked_period_rejects_a_new_contribution_until_it_is_unlocked
        """
        period = open_fiscal_period()
        fiscal_period_action(period["id"], "LOCK")

        validate_error(
            _record_events_receipt(period["id"]), ApiErrorId.ERR_PERIOD_LOCKED
        )

    def test_unlocking_is_the_revert_edge_back_to_open(self):
        """UNLOCK returns the period to OPEN and clears the lock stamp, which is what
        makes the refusal recoverable.

        PRD: "`UNLOCK` is the revert edge: it returns a `REVIEW_LOCKED` period to
        `OPEN` and clears `locked_at` back to null, which is what makes period
        governance a branching machine with a way back rather than a one-way
        pipeline."

        Design: Corner/Validations/val_locked_period_rejects_a_new_contribution_until_it_is_unlocked
        """
        period = open_fiscal_period()
        fiscal_period_action(period["id"], "LOCK")

        unlocked = fiscal_period_action(period["id"], "UNLOCK")
        assert unlocked["status"] == "OPEN"
        assert unlocked["locked_at"] is None

    def test_the_identical_contribution_is_accepted_once_the_period_is_open(self):
        """The same payload now creates a row on both dimensions' initial states.

        PRD: "`EVENTS` and `SYNDICATION` are earned revenue and never deductible:
        both fields are 0."

        Design: Corner/Validations/val_locked_period_rejects_a_new_contribution_until_it_is_unlocked
        """
        period = open_fiscal_period()
        fiscal_period_action(period["id"], "LOCK")
        _record_events_receipt(period["id"])
        fiscal_period_action(period["id"], "UNLOCK")

        created = validate_success(
            _record_events_receipt(period["id"]), expected_status=201
        )
        assert created["settlement_status"] == "INITIATED"
        assert created["acknowledgment_status"] == "UNACKNOWLEDGED"
        assert created["quid_pro_quo_cents"] == 0
        assert created["deductible_cents"] == 0


def _setup_lapsed_member():
    """A member activated on 2026-08-01 whose renewal and grace expiry have both
    been swept past, leaving them LAPSED."""
    period = open_fiscal_period()
    tier = publish_tier(
        define_tier(
            benefits=[],
            tier_code="SUSTAINER",
            name="Sustainer",
            renewal_cadence="MONTHLY",
            contribution_amount_cents=2500,
        )["id"]
    )
    member = enrol_member(tier["id"], email="ana@example.org", full_name="Ana Ruiz")
    contribution = record_contribution(
        period["id"],
        "MEMBERSHIP",
        2500,
        member_id=member["id"],
        received_date="2026-08-01",
    )
    settle_contribution(contribution["id"])
    set_clock("2026-09-02T00:00:00Z")
    grace_sweep = run_daily_sweep()
    set_clock("2026-10-02T00:00:00Z")
    lapse_sweep = run_daily_sweep()
    return {
        "period": period,
        "tier": tier,
        "member": member,
        "grace_sweep": grace_sweep,
        "lapse_sweep": lapse_sweep,
    }


def _membership_payment(period_id, member_id):
    return api_client.create_contribution(
        {
            "fiscal_period_id": period_id,
            "revenue_stream": "MEMBERSHIP",
            "amount_cents": 2500,
            "received_date": "2026-10-02",
            "member_id": member_id,
        },
        DO_HEADERS,
    )


class TestAMembershipContributionForALapsedMemberIsRefused:
    def test_two_sweeps_carry_the_member_through_grace_into_lapsed(self):
        """Each sweep reports the one member it moved, and the lapse leaves the
        lifetime figure intact.

        PRD: "A member in `GRACE` whose `grace_expires_at` the logical clock has
        reached or passed moves `GRACE -> LAPSED`, which resets `consecutive_renewals`
        to 0 and clears `grace_expires_at` back to null."

        Design: Corner/Validations/val_membership_contribution_for_a_lapsed_member_is_refused_until_reinstatement
        """
        ctx = _setup_lapsed_member()

        assert ctx["grace_sweep"]["members_moved_to_grace"] == 1
        assert ctx["lapse_sweep"]["members_moved_to_lapsed"] == 1

        lapsed = read_member(ctx["member"]["id"])
        assert lapsed["status"] == "LAPSED"
        assert lapsed["lifetime_giving_cents"] == 2500
        assert lapsed["is_major_donor"] is False
        assert lapsed["cultivation_locked"] is False

    def test_the_full_tier_price_does_not_buy_its_way_past_the_status_gate(self):
        """The payment is exactly the tier price and is still refused, because the
        gate is on the member's status.

        PRD: "A `MEMBERSHIP` contribution requires its member to be in `PENDING` (the
        enrolment payment that drives activation), `ACTIVE` or `GRACE` - `LAPSED` and
        `CANCELLED` members reject it with `ERR_MEMBER_NOT_ACTIVE`"

        Design: Corner/Validations/val_membership_contribution_for_a_lapsed_member_is_refused_until_reinstatement
        """
        ctx = _setup_lapsed_member()

        validate_error(
            _membership_payment(ctx["period"]["id"], ctx["member"]["id"]),
            ApiErrorId.ERR_MEMBER_NOT_ACTIVE,
        )

    def test_only_the_explicit_reinstatement_restores_the_member(self):
        """REINSTATE restarts the renewal streak from the clock's date, and only then
        does the identical payment land.

        PRD: "`REINSTATE` is legal only from `LAPSED`, requires the tier to still be
        `PUBLISHED`, and requires `cultivation_locked` to be false; it sets
        `cycle_start_date` to the logical clock's date, derives `next_renewal_date`
        from that, and leaves `consecutive_renewals` at 0 - a reinstated member starts
        their renewal streak over."

        Design: Corner/Validations/val_membership_contribution_for_a_lapsed_member_is_refused_until_reinstatement
        """
        ctx = _setup_lapsed_member()
        _membership_payment(ctx["period"]["id"], ctx["member"]["id"])

        reinstated = member_lifecycle(ctx["member"]["id"], "REINSTATE")
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["cycle_start_date"] == "2026-10-02"
        assert reinstated["next_renewal_date"] == "2026-11-02"
        assert reinstated["consecutive_renewals"] == 0

        accepted = validate_success(
            _membership_payment(ctx["period"]["id"], ctx["member"]["id"]),
            expected_status=201,
        )
        assert accepted["settlement_status"] == "INITIATED"


def _enrol(tier_id):
    return api_client.create_member(
        {"tier_id": tier_id, "email": "ana@example.org", "full_name": "Ana Ruiz"},
        DO_HEADERS,
    )


def _membership_amount(period_id, member_id, amount_cents):
    return api_client.create_contribution(
        {
            "fiscal_period_id": period_id,
            "revenue_stream": "MEMBERSHIP",
            "amount_cents": amount_cents,
            "received_date": "2026-08-01",
            "member_id": member_id,
        },
        DO_HEADERS,
    )


class TestMembershipWritesRequireAPublishedTierAndAtLeastItsPrice:
    def test_a_draft_tier_cannot_back_an_enrolment(self):
        """The tier exists and is well formed; it simply has not been published.

        PRD: "The referenced tier must already be `PUBLISHED`; enrolling against a
        `DRAFT` tier is rejected with `ERR_TIER_NOT_PUBLISHED` (HTTP 409)."

        Design: Corner/Validations/val_membership_writes_require_a_published_tier_and_at_least_the_tier_price
        """
        open_fiscal_period()
        tier = define_tier(
            benefits=[],
            tier_code="SUSTAINER",
            name="Sustainer",
            renewal_cadence="MONTHLY",
            contribution_amount_cents=2500,
        )
        assert tier["status"] == "DRAFT"

        validate_error(_enrol(tier["id"]), ApiErrorId.ERR_TIER_NOT_PUBLISHED)

    def test_one_cent_below_the_tier_price_is_refused(self):
        """2499 against a 2500-cent tier fails the minimum, so the comparison is
        at-least rather than strictly-greater.

        PRD: "and its `amount_cents` must be at least the member's tier
        `contribution_amount_cents`, otherwise `ERR_CONTRIBUTION_BELOW_TIER_MINIMUM`
        (HTTP 422)."

        Design: Corner/Validations/val_membership_writes_require_a_published_tier_and_at_least_the_tier_price
        """
        period = open_fiscal_period()
        tier = define_tier(
            benefits=[],
            tier_code="SUSTAINER",
            name="Sustainer",
            renewal_cadence="MONTHLY",
            contribution_amount_cents=2500,
        )
        _enrol(tier["id"])
        published = publish_tier(tier["id"])
        assert published["status"] == "PUBLISHED"
        assert published["quid_pro_quo_per_period_cents"] == 0
        assert published["benefit_count"] == 0

        member = validate_success(_enrol(tier["id"]), expected_status=201)
        assert member["status"] == "PENDING"

        validate_error(
            _membership_amount(period["id"], member["id"], 2499),
            ApiErrorId.ERR_CONTRIBUTION_BELOW_TIER_MINIMUM,
        )

    def test_exactly_the_tier_price_is_accepted_and_leaves_the_member_pending(self):
        """The enrolment payment is recorded but activation waits on settlement.

        PRD: "PENDING->ACTIVE is not an action - it happens when the member's first
        MEMBERSHIP contribution settles"

        Design: Corner/Validations/val_membership_writes_require_a_published_tier_and_at_least_the_tier_price
        """
        period = open_fiscal_period()
        tier = publish_tier(
            define_tier(
                benefits=[],
                tier_code="SUSTAINER",
                name="Sustainer",
                renewal_cadence="MONTHLY",
                contribution_amount_cents=2500,
            )["id"]
        )
        member = validate_success(_enrol(tier["id"]), expected_status=201)
        _membership_amount(period["id"], member["id"], 2499)

        accepted = validate_success(
            _membership_amount(period["id"], member["id"], 2500), expected_status=201
        )
        assert accepted["amount_cents"] == 2500
        assert accepted["settlement_status"] == "INITIATED"
        assert read_member(member["id"])["status"] == "PENDING"
