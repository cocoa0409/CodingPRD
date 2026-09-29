"""Gates that only a second attempt can clear: a delinquent award, a blocked
publication gate and an offer carrying donor conditions.

Each scenario runs the refused call, cures the one condition that caused the
refusal, and then repeats the identical call.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    attest_disclosure,
    file_disclosure,
    list_proposal_reports,
    log_influence_contact,
    open_fiscal_period,
    read_coverage_area,
    read_funder,
    read_gift_offer,
    read_proposal,
    read_report,
    record_gift_offer,
    register_coverage_area,
    release_funds,
    review_gift_offer,
    review_report,
    run_daily_sweep,
    set_clock,
    setup_awarded_restricted_proposal,
    setup_cleared_funder,
    submit_offer_for_review,
    submit_report,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import DO_HEADERS, ED_HEADERS, FC_HEADERS
from test_helpers.test_users import USER_IDS

_IRONWOOD_CLIMATE_TEXT = (
    "Ironwood funds climate coverage; the climate desk retains editorial control."
)
_DONOR_CONDITION = (
    "The gift is contingent on a favourable profile of our board chair."
)
_REVIEW_NOTE = "Withdraw the coverage condition and resubmit."


def _setup_swept_delinquent_grant():
    """A PROJECT_RESTRICTED 350001-cent award with 180000 released and the clock
    swept past report 1's 2027-04-14 due date, which suspended the grant."""
    ctx = setup_awarded_restricted_proposal(
        requested_amount_cents=350001,
        award_date="2026-08-01",
        reporting_cadence="SEMIANNUAL",
        restriction_type="PROJECT_RESTRICTED",
        restriction_start_date="2026-09-01",
        restriction_end_date="2027-07-31",
        area_code="HOUSING",
        legal_name="Ironwood Trust",
        title="Housing accountability project",
    )
    ctx["first_report"] = ctx["reports"][0]
    ctx["proposal"] = release_funds(ctx["proposal"]["id"], 180000)
    set_clock("2027-04-15T00:00:00Z")
    ctx["sweep"] = run_daily_sweep()
    ctx["proposal"] = read_proposal(ctx["proposal"]["id"])
    return ctx


def _reinstate(proposal_id):
    return api_client.reinstate_grant_proposal(proposal_id, FC_HEADERS)


class TestDelinquentGrantCannotBeReinstatedUntilTheOverdueReportClears:
    def test_the_sweep_reports_one_overdue_report_and_one_suspension(self):
        """The semiannual series puts report 1's due date at 2027-04-14, so a clock
        at 2027-04-15 moves exactly one report and suspends exactly one grant.

        PRD: "It reports what it did as `swept_at` plus five counters -
        `members_moved_to_grace`, `members_moved_to_lapsed`,
        `reports_moved_to_overdue`, `proposals_suspended` and `funders_restricted`."

        Design: Corner/Validations/val_delinquent_proposal_cannot_be_reinstated_until_the_overdue_report_clears
        """
        ctx = _setup_swept_delinquent_grant()

        assert ctx["sweep"]["reports_moved_to_overdue"] == 1
        assert ctx["sweep"]["proposals_suspended"] == 1
        assert ctx["sweep"]["members_moved_to_grace"] == 0
        assert ctx["sweep"]["members_moved_to_lapsed"] == 0
        assert ctx["sweep"]["funders_restricted"] == 0

        reports = list_proposal_reports(ctx["proposal"]["id"])
        assert len(reports) == 2
        assert reports[0]["due_date"] == "2027-04-14"
        assert reports[0]["status"] == "OVERDUE"
        assert reports[0]["allocated_release_cents"] == 175000
        assert reports[0]["consumed_release_cents"] == 175000
        assert reports[1]["status"] == "SCHEDULED"
        assert reports[1]["allocated_release_cents"] == 175001
        assert reports[1]["consumed_release_cents"] == 5000

        assert ctx["proposal"]["status"] == "SUSPENDED"
        assert ctx["proposal"]["suspended_reason"] == "REPORT_DELINQUENCY"
        assert ctx["proposal"]["compliance_flag"] == "DELINQUENT"

    def test_reinstatement_is_refused_while_the_overdue_report_is_unaccepted(self):
        """Three of the four reinstatement gates are already satisfied - the
        proposal is SUSPENDED, the funder is CLEARED and the beat's gate is OPEN -
        so only the delinquency stands in the way.

        PRD: "The proposal must be `SUSPENDED`, the funder must be back in status
        `CLEARED`, a restricted proposal's beat must have `publication_gate` `OPEN`,
        and `compliance_flag` must be `COMPLIANT`."

        Design: Corner/Validations/val_delinquent_proposal_cannot_be_reinstated_until_the_overdue_report_clears
        """
        ctx = _setup_swept_delinquent_grant()

        assert read_funder(ctx["funder"]["id"])["status"] == "CLEARED"
        assert read_coverage_area(ctx["area"]["id"])["publication_gate"] == "OPEN"

        validate_error(
            _reinstate(ctx["proposal"]["id"]), ApiErrorId.ERR_PROPOSAL_DELINQUENT
        )

        unchanged = read_proposal(ctx["proposal"]["id"])
        assert unchanged["status"] == "SUSPENDED"
        assert unchanged["compliance_flag"] == "DELINQUENT"
        assert unchanged["released_cents"] == 0
        assert unchanged["unreleased_cents"] == 170001
        assert unchanged["returned_cents"] == 180000

    def test_the_overdue_report_submits_with_a_zero_variance(self):
        """The clawback left the report's own bucket at 175000, and a spend of
        exactly 175000 against it is a variance of zero.

        PRD: "Submission stamps `submitted_at` with the logical clock and computes
        `variance_bps` as 10000 times the difference between `spend_reported_cents`
        and `consumed_release_cents`, divided by `consumed_release_cents`, rounded
        half up - a signed figure, negative when the newsroom underspent - and
        defined as 0 when `consumed_release_cents` is 0."

        Design: Corner/Validations/val_delinquent_proposal_cannot_be_reinstated_until_the_overdue_report_clears
        """
        ctx = _setup_swept_delinquent_grant()

        submitted = submit_report(ctx["first_report"]["id"], 175000)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["spend_reported_cents"] == 175000
        assert submitted["variance_bps"] == 0
        assert submitted["submitted_at"].startswith("2027-04-15T00:00:00")
        assert submitted["consumed_release_cents"] == 175000

    def test_only_acceptance_returns_the_proposal_to_compliant(self):
        """Submission alone leaves the flag DELINQUENT; the review is what clears
        it, and the proposal is still SUSPENDED afterwards.

        PRD: "Acceptance is terminal for the report and recomputes the proposal's
        `compliance_flag`, which is what finally lifts a `DELINQUENT` flag -
        submitting an overdue report is not enough, the flag stays `DELINQUENT`
        until the report is accepted."

        Design: Corner/Validations/val_delinquent_proposal_cannot_be_reinstated_until_the_overdue_report_clears
        """
        ctx = _setup_swept_delinquent_grant()

        submit_report(ctx["first_report"]["id"], 175000)
        assert read_proposal(ctx["proposal"]["id"])["compliance_flag"] == "DELINQUENT"

        accepted = review_report(ctx["first_report"]["id"], "ACCEPT")
        assert accepted["status"] == "ACCEPTED"

        cured = read_proposal(ctx["proposal"]["id"])
        assert cured["compliance_flag"] == "COMPLIANT"
        assert cured["status"] == "SUSPENDED"

    def test_the_identical_reinstate_call_now_restores_the_principal(self):
        """Nothing about the funder or the beat changed between the refusal and the
        success, and the restored money lands in `unreleased_cents` rather than
        back in `released_cents`.

        PRD: "Note the asymmetry with the suspension: suspension moves money from
        `released_cents`, reinstatement returns it to `unreleased_cents`, so a
        reinstated grant must be released again from the beginning."

        Design: Corner/Validations/val_delinquent_proposal_cannot_be_reinstated_until_the_overdue_report_clears
        """
        ctx = _setup_swept_delinquent_grant()
        validate_error(
            _reinstate(ctx["proposal"]["id"]), ApiErrorId.ERR_PROPOSAL_DELINQUENT
        )
        submit_report(ctx["first_report"]["id"], 175000)
        review_report(ctx["first_report"]["id"], "ACCEPT")

        reinstated = validate_success(_reinstate(ctx["proposal"]["id"]))
        assert reinstated["status"] == "AWARDED"
        assert reinstated["suspended_reason"] is None
        assert reinstated["released_cents"] == 0
        assert reinstated["unreleased_cents"] == 350001
        assert reinstated["returned_cents"] == 0
        assert (
            reinstated["released_cents"]
            + reinstated["unreleased_cents"]
            + reinstated["returned_cents"]
            == 350001
        )
        assert read_report(ctx["first_report"]["id"])["consumed_release_cents"] == 0


def _setup_blocked_climate_beat_and_a_second_funders_offer():
    """CLIMATE carries a disclosure for Ironwood that went stale when Ironwood was
    restricted after an editorial-direction request; Meridian Trust is separately
    CLEARED with a PROPOSED program-restricted gift on CLIMATE."""
    period = open_fiscal_period()
    area = register_coverage_area(area_code="CLIMATE", name="Climate")
    ironwood = setup_cleared_funder(legal_name="Ironwood Trust")
    disclosure = file_disclosure(
        ironwood["id"],
        area["id"],
        disclosure_text=_IRONWOOD_CLIMATE_TEXT,
    )
    log_influence_contact(
        ironwood["id"],
        contact_type="EDITORIAL_DIRECTION_REQUEST",
        occurred_at="2026-08-01T00:00:00Z",
        summary="Funder asked us to assign a specific reporter to its grantees.",
        coverage_area_id=area["id"],
    )
    meridian = setup_cleared_funder(legal_name="Meridian Trust")
    offer = record_gift_offer(
        meridian["id"],
        period["id"],
        offered_amount_cents=100000,
        designation="PROGRAM_RESTRICTED",
        coverage_area_id=area["id"],
    )
    return {
        "period": period,
        "area": area,
        "ironwood": ironwood,
        "disclosure": disclosure,
        "meridian": meridian,
        "offer": offer,
    }


def _submit_offer(offer_id):
    return api_client.submit_gift_offer_for_review(offer_id, {}, DO_HEADERS)


def _read_disclosure(disclosure_id):
    return validate_success(
        api_client.get_firewall_disclosure(disclosure_id, ED_HEADERS)
    )


class TestBlockedPublicationGateStopsAnUnrelatedFundersDesignatedGift:
    def test_the_first_funders_stale_disclosure_blocks_the_whole_beat(self):
        """The consequence of Ironwood's restriction lands on the beat, not on
        Ironwood alone.

        PRD: "The moment any of them needs re-attestation, the beat's
        `disclosure_status` becomes `STALE` and its `publication_gate` becomes
        `BLOCKED`, and a blocked gate suspends new funding activity on that beat
        with `ERR_PUBLICATION_GATE_BLOCKED` (HTTP 409)."

        Design: Corner/Validations/val_blocked_publication_gate_stops_an_unrelated_funders_designated_gift
        """
        ctx = _setup_blocked_climate_beat_and_a_second_funders_offer()

        beat = read_coverage_area(ctx["area"]["id"])
        assert beat["disclosure_status"] == "STALE"
        assert beat["publication_gate"] == "BLOCKED"

        stale = _read_disclosure(ctx["disclosure"]["id"])
        assert stale["status"] == "REATTESTATION_REQUIRED"
        assert stale["reattestation_reason"] == "INFLUENCE_CONTACT"

    def test_the_second_funders_designated_offer_cannot_go_into_review(self):
        """Meridian is CLEARED, its score is nowhere near any bar and it has no part
        in Ironwood's restriction, yet its designated gift is refused.

        PRD: "For a designated gift going in from `PROPOSED`, `coverage_area_id`
        must be non-null and the beat's `publication_gate` must be `OPEN`, or the
        submission is refused with `ERR_PUBLICATION_GATE_BLOCKED`."

        Design: Corner/Validations/val_blocked_publication_gate_stops_an_unrelated_funders_designated_gift
        """
        ctx = _setup_blocked_climate_beat_and_a_second_funders_offer()

        meridian = read_funder(ctx["meridian"]["id"])
        assert meridian["status"] == "CLEARED"
        assert meridian["independence_risk_score"] == 10

        validate_error(
            _submit_offer(ctx["offer"]["id"]),
            ApiErrorId.ERR_PUBLICATION_GATE_BLOCKED,
        )

        untouched = read_gift_offer(ctx["offer"]["id"])
        assert untouched["status"] == "PROPOSED"
        assert untouched["conditions_round_count"] == 0
        assert untouched["acceptance_gate_score"] == 0
        assert untouched["cleared_by_user_id"] is None

    def test_reattesting_the_first_disclosure_reopens_the_gate(self):
        """Nothing about Meridian is touched - the cure is a re-attestation of
        Ironwood's own disclosure.

        PRD: "Once no disclosure of that coverage area remains in
        `REATTESTATION_REQUIRED`, the beat re-derives `disclosure_status` back to
        `CURRENT` and `publication_gate` back to `OPEN`."

        Design: Corner/Validations/val_blocked_publication_gate_stops_an_unrelated_funders_designated_gift
        """
        ctx = _setup_blocked_climate_beat_and_a_second_funders_offer()
        validate_error(
            _submit_offer(ctx["offer"]["id"]),
            ApiErrorId.ERR_PUBLICATION_GATE_BLOCKED,
        )

        reattested = attest_disclosure(ctx["disclosure"]["id"])
        assert reattested["status"] == "ACTIVE"
        assert reattested["reattestation_reason"] is None
        assert reattested["attested_by_user_id"] == USER_IDS["editorial_director"]

        beat = read_coverage_area(ctx["area"]["id"])
        assert beat["disclosure_status"] == "CURRENT"
        assert beat["publication_gate"] == "OPEN"

    def test_the_identical_submission_then_nets_the_gift(self):
        """The same empty submission now succeeds, and a 100000-cent gross is below
        every fee floor and below the ratification floor.

        PRD: "Third, and also keyed on the gross, `board_ratification_required`
        becomes true when either `offered_amount_cents` has reached **2500000
        cents** (25,000 dollars) or the funder's current `independence_risk_score`
        has reached 40; otherwise it is false."

        Design: Corner/Validations/val_blocked_publication_gate_stops_an_unrelated_funders_designated_gift
        """
        ctx = _setup_blocked_climate_beat_and_a_second_funders_offer()
        validate_error(
            _submit_offer(ctx["offer"]["id"]),
            ApiErrorId.ERR_PUBLICATION_GATE_BLOCKED,
        )
        attest_disclosure(ctx["disclosure"]["id"])

        submitted = validate_success(_submit_offer(ctx["offer"]["id"]))
        assert submitted["status"] == "INDEPENDENCE_REVIEW"
        assert submitted["stewardship_fee_cents"] == 0
        assert submitted["net_acceptable_amount_cents"] == 100000
        assert submitted["board_ratification_required"] is False
        assert submitted["donor_conditions"] is None

        assert read_funder(ctx["ironwood"]["id"])["status"] == "RESTRICTED"


def _setup_offer_in_review_with_donor_conditions():
    """One CLEARED foundation and one 100000-cent unrestricted offer carrying donor
    conditions, already in INDEPENDENCE_REVIEW.

    Submission is the operation that rewrites `donor_conditions`: supplying a value
    replaces whatever is stored and omitting it clears them to null. The donor has
    not withdrawn anything here, so the submission restates the same conditions
    verbatim in order to carry them into review."""
    period = open_fiscal_period()
    funder = setup_cleared_funder(legal_name="Ironwood Trust")
    offer = record_gift_offer(
        funder["id"],
        period["id"],
        offered_amount_cents=100000,
        designation="UNRESTRICTED",
        donor_conditions=_DONOR_CONDITION,
    )
    offer = submit_offer_for_review(offer["id"], donor_conditions=_DONOR_CONDITION)
    return {"period": period, "funder": funder, "offer": offer}


def _rule(offer_id, decision, **extra):
    payload = {"decision": decision}
    payload.update(extra)
    return api_client.gift_offer_independence_review(offer_id, payload, ED_HEADERS)


class TestDonorConditionsBlockClearanceUntilTheyAreWithdrawn:
    def test_clearance_is_refused_while_conditions_are_still_attached(self):
        """The three earlier gates pass - the funder is CLEARED, its score is 10 and
        the gift is undesignated - so the conditions are the sole obstacle.

        PRD: "Finally, the offer must carry no non-empty `donor_conditions`: a gift
        with conditions still attached cannot clear, and the refusal is
        `ERR_EDITORIAL_CONDITION_PRESENT`."

        Design: Corner/Validations/val_donor_conditions_block_clearance_until_they_are_withdrawn
        """
        ctx = _setup_offer_in_review_with_donor_conditions()
        assert ctx["offer"]["status"] == "INDEPENDENCE_REVIEW"
        assert ctx["offer"]["donor_conditions"] == _DONOR_CONDITION
        assert read_funder(ctx["funder"]["id"])["independence_risk_score"] == 10

        validate_error(
            _rule(ctx["offer"]["id"], "CLEAR"),
            ApiErrorId.ERR_EDITORIAL_CONDITION_PRESENT,
        )

        unchanged = read_gift_offer(ctx["offer"]["id"])
        assert unchanged["status"] == "INDEPENDENCE_REVIEW"
        assert unchanged["acceptance_gate_score"] == 0
        assert unchanged["cleared_by_user_id"] is None
        assert unchanged["conditions_round_count"] == 0

    def test_requesting_conditions_stores_the_review_note_as_the_conditions(self):
        """The newsroom's own note replaces the donor's text and the round counter
        moves to 1.

        PRD: "`REQUEST_CONDITIONS` moves the offer `INDEPENDENCE_REVIEW ->
        CONDITIONS_REQUESTED`, increments `conditions_round_count` by 1, and stores
        the `review_note` into `donor_conditions` as the conditions the newsroom is
        asking the donor to accept or drop."

        Design: Corner/Validations/val_donor_conditions_block_clearance_until_they_are_withdrawn
        """
        ctx = _setup_offer_in_review_with_donor_conditions()

        requested = review_gift_offer(
            ctx["offer"]["id"], "REQUEST_CONDITIONS", review_note=_REVIEW_NOTE
        )
        assert requested["status"] == "CONDITIONS_REQUESTED"
        assert requested["conditions_round_count"] == 1
        assert requested["donor_conditions"] == _REVIEW_NOTE

    def test_the_resubmission_that_omits_conditions_clears_them_to_null(self):
        """Re-submission out of CONDITIONS_REQUESTED omits `donor_conditions`, which
        is how the donor withdraws them, and the netting is rewritten.

        PRD: "The only field it takes is the optional `donor_conditions`: supplying
        a value replaces whatever conditions are stored, and omitting it clears them
        to null - which is the mechanism by which a donor withdraws conditions."

        Design: Corner/Validations/val_donor_conditions_block_clearance_until_they_are_withdrawn
        """
        ctx = _setup_offer_in_review_with_donor_conditions()
        review_gift_offer(
            ctx["offer"]["id"], "REQUEST_CONDITIONS", review_note=_REVIEW_NOTE
        )

        resubmitted = submit_offer_for_review(ctx["offer"]["id"])
        assert resubmitted["status"] == "INDEPENDENCE_REVIEW"
        assert resubmitted["donor_conditions"] is None
        assert resubmitted["stewardship_fee_cents"] == 0
        assert resubmitted["net_acceptable_amount_cents"] == 100000
        assert resubmitted["conditions_round_count"] == 1

    def test_the_identical_clearance_now_succeeds_on_the_same_round_count(self):
        """The bar was the presence of conditions rather than the round count, which
        is still 1 when the same CLEAR ruling goes through.

        PRD: "On success the funder's `independence_risk_score` is snapshotted into
        `acceptance_gate_score`, `cleared_by_user_id` is set to the ruling
        director's `X-User-ID`, and the offer's `version` increments by 1."

        Design: Corner/Validations/val_donor_conditions_block_clearance_until_they_are_withdrawn
        """
        ctx = _setup_offer_in_review_with_donor_conditions()
        validate_error(
            _rule(ctx["offer"]["id"], "CLEAR"),
            ApiErrorId.ERR_EDITORIAL_CONDITION_PRESENT,
        )
        review_gift_offer(
            ctx["offer"]["id"], "REQUEST_CONDITIONS", review_note=_REVIEW_NOTE
        )
        submit_offer_for_review(ctx["offer"]["id"])

        cleared = validate_success(_rule(ctx["offer"]["id"], "CLEAR"))
        assert cleared["status"] == "CLEARED"
        assert cleared["acceptance_gate_score"] == 10
        assert cleared["cleared_by_user_id"] == USER_IDS["editorial_director"]
        assert cleared["conditions_round_count"] == 1
        assert cleared["donor_conditions"] is None
