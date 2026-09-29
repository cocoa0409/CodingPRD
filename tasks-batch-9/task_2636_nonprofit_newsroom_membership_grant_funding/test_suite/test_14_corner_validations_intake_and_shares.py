"""Validation rules governing intake pairings, the refund freeze, award bounds,
benefit bundles and collaboration share sums.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    acknowledge_contribution,
    add_partner,
    api_client,
    benefit_payload,
    define_tier,
    enrol_member,
    list_proposal_reports,
    open_collaboration,
    open_fiscal_period,
    publish_tier,
    read_collaboration,
    read_contribution,
    read_member,
    read_partner,
    read_proposal,
    record_contribution,
    register_coverage_area,
    register_funder,
    setup_cleared_funder,
    setup_submitted_proposal,
    settle_contribution,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import DO_HEADERS, ED_HEADERS, FC_HEADERS


def _create_contribution(payload):
    """Raw POST so a refusal can be inspected rather than raised."""
    return api_client.create_contribution(payload, DO_HEADERS)


def _contribution_count():
    _, meta = validate_paginated(api_client.list_contributions(FC_HEADERS))
    return meta["total_count"]


def _setup_member_and_prospect_funder():
    """One period, one published tier with an enrolled member, and one PROSPECT
    foundation - every source column the stream rules speak about is available."""
    period = open_fiscal_period()
    tier = define_tier(
        benefits=[],
        tier_code="SUSTAINER",
        name="Sustainer",
        renewal_cadence="MONTHLY",
        contribution_amount_cents=2500,
    )
    publish_tier(tier["id"])
    member = enrol_member(tier["id"], email="ana@example.org", full_name="Ana Ruiz")
    funder = register_funder(legal_name="Ironwood Trust", funder_type="FOUNDATION")
    return {"period": period, "tier": tier, "member": member, "funder": funder}


class TestContributionSourceColumnsMustMatchTheRevenueStream:
    """One rule inspects the pairing of stream and source columns, so a row that
    supplies too much is refused exactly like one that supplies too little."""

    def test_membership_forbids_a_funder_id_even_with_the_member_present(self):
        """The row names the member the stream requires, and is still refused
        because it also names a funder.

        PRD: "Which of those keys is required is decided by the stream:
        `MEMBERSHIP` requires `member_id` and forbids `funder_id`; `MAJOR_GIFT`
        requires `funder_id` and forbids `member_id`; `SYNDICATION` requires
        `collaboration_id`; and `EVENTS` forbids `gift_offer_id`. A mismatch is
        `ERR_STREAM_SOURCE_MISMATCH` (HTTP 422)."

        Design: Corner/Validations/val_contribution_source_columns_must_match_the_revenue_stream
        """
        ctx = _setup_member_and_prospect_funder()

        validate_error(
            _create_contribution(
                {
                    "fiscal_period_id": ctx["period"]["id"],
                    "revenue_stream": "MEMBERSHIP",
                    "amount_cents": 2500,
                    "received_date": "2026-08-01",
                    "member_id": ctx["member"]["id"],
                    "funder_id": ctx["funder"]["id"],
                }
            ),
            ApiErrorId.ERR_STREAM_SOURCE_MISMATCH,
        )
        assert _contribution_count() == 0

    def test_major_gift_forbids_a_member_id_even_with_the_funder_present(self):
        """The mirror image of the same rule: the required funder is there and the
        forbidden member is what offends.

        PRD: "Which of those keys is required is decided by the stream:
        `MEMBERSHIP` requires `member_id` and forbids `funder_id`; `MAJOR_GIFT`
        requires `funder_id` and forbids `member_id`; `SYNDICATION` requires
        `collaboration_id`; and `EVENTS` forbids `gift_offer_id`. A mismatch is
        `ERR_STREAM_SOURCE_MISMATCH` (HTTP 422)."

        Design: Corner/Validations/val_contribution_source_columns_must_match_the_revenue_stream
        """
        ctx = _setup_member_and_prospect_funder()

        validate_error(
            _create_contribution(
                {
                    "fiscal_period_id": ctx["period"]["id"],
                    "revenue_stream": "MAJOR_GIFT",
                    "amount_cents": 250000,
                    "received_date": "2026-08-01",
                    "member_id": ctx["member"]["id"],
                    "funder_id": ctx["funder"]["id"],
                }
            ),
            ApiErrorId.ERR_STREAM_SOURCE_MISMATCH,
        )
        assert _contribution_count() == 0

    def test_syndication_without_a_collaboration_id_is_refused(self):
        """A descriptive `source_label` is no substitute for the collaboration the
        stream requires.

        PRD: "Which of those keys is required is decided by the stream:
        `MEMBERSHIP` requires `member_id` and forbids `funder_id`; `MAJOR_GIFT`
        requires `funder_id` and forbids `member_id`; `SYNDICATION` requires
        `collaboration_id`; and `EVENTS` forbids `gift_offer_id`. A mismatch is
        `ERR_STREAM_SOURCE_MISMATCH` (HTTP 422)."

        Design: Corner/Validations/val_contribution_source_columns_must_match_the_revenue_stream
        """
        ctx = _setup_member_and_prospect_funder()

        validate_error(
            _create_contribution(
                {
                    "fiscal_period_id": ctx["period"]["id"],
                    "revenue_stream": "SYNDICATION",
                    "amount_cents": 5000,
                    "received_date": "2026-08-01",
                    "source_label": "Reprint fee",
                }
            ),
            ApiErrorId.ERR_STREAM_SOURCE_MISMATCH,
        )
        assert _contribution_count() == 0


def _refund(contribution_id):
    """Raw POST so the frozen row's refusal can be inspected."""
    return api_client.refund_contribution(
        contribution_id, {"refund_reason": "Donor requested reversal."}, FC_HEADERS
    )


def _setup_one_disclosed_and_one_receipted_gift():
    """An ACTIVE member with two settled 2500-cent membership contributions, one
    walked all the way to DISCLOSED and one left at RECEIPTED."""
    period = open_fiscal_period()
    tier = define_tier(
        benefits=[],
        tier_code="SUSTAINER",
        name="Sustainer",
        renewal_cadence="MONTHLY",
        contribution_amount_cents=2500,
    )
    publish_tier(tier["id"])
    member = enrol_member(tier["id"], email="ana@example.org", full_name="Ana Ruiz")

    first = record_contribution(
        period["id"],
        "MEMBERSHIP",
        2500,
        member_id=member["id"],
        received_date="2026-08-01",
    )
    settle_contribution(first["id"])
    acknowledge_contribution(first["id"], disclose_publicly=False)
    first = acknowledge_contribution(first["id"], disclose_publicly=True)

    second = record_contribution(
        period["id"],
        "MEMBERSHIP",
        2500,
        member_id=member["id"],
        received_date="2026-08-02",
    )
    settle_contribution(second["id"])
    second = acknowledge_contribution(second["id"], disclose_publicly=False)

    return {
        "period": period,
        "tier": tier,
        "member": member,
        "disclosed": first,
        "receipted": second,
    }


class TestRefundIsFrozenOnceTheGiftHasBeenPubliclyDisclosed:
    """The refund window is keyed on the acknowledgment dimension, so two rows
    with identical settlement status part company."""

    def test_the_two_rows_reach_their_acknowledgment_statuses_in_receipt_order(self):
        """Both calls on the first row run before the second row is receipted, so
        the counter hands out RCPT-000001 and RCPT-000002 in that order.

        PRD: "With `disclose_publicly` false, an `UNACKNOWLEDGED` contribution
        whose `settlement_status` is anything other than `FAILED` becomes
        `RECEIPTED`: it is assigned a `receipt_number` of the literal `RCPT-`
        followed by a zero-padded six-digit counter that increments once per
        receipt in the `created_at` ascending order of acknowledgment, and its
        `quid_pro_quo_cents` and `deductible_cents` are frozen against later tier
        changes."

        Design: Corner/Validations/val_refund_is_frozen_once_the_gift_has_been_publicly_disclosed
        """
        ctx = _setup_one_disclosed_and_one_receipted_gift()

        assert ctx["disclosed"]["acknowledgment_status"] == "DISCLOSED"
        assert ctx["disclosed"]["receipt_number"] == "RCPT-000001"
        assert ctx["disclosed"]["settlement_status"] == "SETTLED"
        assert ctx["receipted"]["acknowledgment_status"] == "RECEIPTED"
        assert ctx["receipted"]["receipt_number"] == "RCPT-000002"
        assert ctx["receipted"]["settlement_status"] == "SETTLED"

    def test_the_disclosed_row_cannot_be_refunded_and_keeps_both_statuses(self):
        """Public transparency reporting has taken the row, so the compensating
        action is refused outright.

        PRD: "The refund window is bounded by the *other* dimension: a refund is
        permitted only while `acknowledgment_status` is `UNACKNOWLEDGED` or
        `RECEIPTED`, because a `DISCLOSED` contribution has entered public
        transparency reporting and is frozen - the refusal is
        `ERR_REFUND_WINDOW_CLOSED` (HTTP 409)."

        Design: Corner/Validations/val_refund_is_frozen_once_the_gift_has_been_publicly_disclosed
        """
        ctx = _setup_one_disclosed_and_one_receipted_gift()

        validate_error(
            _refund(ctx["disclosed"]["id"]), ApiErrorId.ERR_REFUND_WINDOW_CLOSED
        )

        frozen = read_contribution(ctx["disclosed"]["id"])
        assert frozen["settlement_status"] == "SETTLED"
        assert frozen["acknowledgment_status"] == "DISCLOSED"
        assert frozen["refunded_at"] is None

    def test_the_merely_receipted_twin_of_the_same_amount_refunds_cleanly(self):
        """The same amount from the same member on the same stream is refundable,
        and the receipt it was issued survives the reversal untouched.

        PRD: "`settlement_status` becomes `REFUNDED` and `refunded_at` is stamped
        with the logical clock."

        Design: Corner/Validations/val_refund_is_frozen_once_the_gift_has_been_publicly_disclosed
        """
        ctx = _setup_one_disclosed_and_one_receipted_gift()

        refunded = validate_success(_refund(ctx["receipted"]["id"]))
        assert refunded["settlement_status"] == "REFUNDED"
        assert refunded["acknowledgment_status"] == "RECEIPTED"
        assert refunded["receipt_number"] == "RCPT-000002"
        assert refunded["refunded_at"].startswith("2026-08-01T00:00:00")

    def test_only_the_refunded_row_leaves_the_settled_set(self):
        """Lifetime giving is a sum over the `SETTLED` rows, so returning one of
        the two 2500-cent gifts leaves exactly the other one counted.

        PRD: "`lifetime_giving_cents` is the sum of `amount_cents` over every
        contribution of this member whose settlement status is `SETTLED`, across
        all fiscal periods."

        Design: Corner/Validations/val_refund_is_frozen_once_the_gift_has_been_publicly_disclosed
        """
        ctx = _setup_one_disclosed_and_one_receipted_gift()
        assert read_member(ctx["member"]["id"])["lifetime_giving_cents"] == 5000

        _refund(ctx["receipted"]["id"])

        member = read_member(ctx["member"]["id"])
        assert member["lifetime_giving_cents"] == 2500
        assert member["status"] == "ACTIVE"
        assert member["is_major_donor"] is False


def _record_award(proposal_id, awarded_amount_cents, award_date):
    """Raw outcome POST so each rejected award can be inspected in turn."""
    return api_client.grant_proposal_record_outcome(
        proposal_id,
        {
            "outcome": "AWARDED",
            "awarded_amount_cents": awarded_amount_cents,
            "award_date": award_date,
        },
        DO_HEADERS,
    )


def _setup_submitted_request_for_350000():
    """A SUBMITTED unrestricted proposal for 350000 cents in a period running
    2026-08-01..2027-07-31."""
    period = open_fiscal_period()
    funder = setup_cleared_funder(legal_name="Ironwood Trust")
    proposal = setup_submitted_proposal(
        funder["id"],
        period["id"],
        title="General operating support",
        requested_amount_cents=350000,
        restriction_type="UNRESTRICTED",
    )
    return {"period": period, "funder": funder, "proposal": proposal}


class TestAwardAmountMustBeWithinTheRequestAndInsideThePeriod:
    """One error code covers both halves of the outcome check."""

    def test_one_cent_above_the_request_is_refused(self):
        """350001 against a 350000-cent request offends the amount half of the
        rule, and the proposal does not move.

        PRD: "The amount must be present, at least 1, and no greater than
        `requested_amount_cents`, and the `award_date` must fall inside the fiscal
        period's inclusive date range; any of those failing is
        `ERR_AWARD_AMOUNT_INVALID` (HTTP 422)."

        Design: Corner/Validations/val_award_amount_must_be_within_the_request_and_inside_the_period
        """
        ctx = _setup_submitted_request_for_350000()

        validate_error(
            _record_award(ctx["proposal"]["id"], 350001, "2026-08-01"),
            ApiErrorId.ERR_AWARD_AMOUNT_INVALID,
        )

        unchanged = read_proposal(ctx["proposal"]["id"])
        assert unchanged["status"] == "SUBMITTED"
        assert unchanged["awarded_amount_cents"] == 0
        assert unchanged["award_date"] is None

    def test_an_award_date_one_day_past_the_period_end_is_refused(self):
        """The amount is now impeccable, so only the date can explain the same
        code: 2027-08-01 sits outside the inclusive 2026-08-01..2027-07-31 range.

        PRD: "The amount must be present, at least 1, and no greater than
        `requested_amount_cents`, and the `award_date` must fall inside the fiscal
        period's inclusive date range; any of those failing is
        `ERR_AWARD_AMOUNT_INVALID` (HTTP 422)."

        Design: Corner/Validations/val_award_amount_must_be_within_the_request_and_inside_the_period
        """
        ctx = _setup_submitted_request_for_350000()

        validate_error(
            _record_award(ctx["proposal"]["id"], 350000, "2027-08-01"),
            ApiErrorId.ERR_AWARD_AMOUNT_INVALID,
        )

        unchanged = read_proposal(ctx["proposal"]["id"])
        assert unchanged["status"] == "SUBMITTED"
        assert unchanged["unreleased_cents"] == 0

    def test_both_halves_fixed_at_once_lands_the_award_on_the_last_legal_day(self):
        """After each refusal the same request with the amount at the request
        ceiling and the date on the period's final day is accepted.

        PRD: "`awarded_amount_cents` and `award_date` are stored,
        `unreleased_cents` is set equal to `awarded_amount_cents`, and
        `released_cents` and `returned_cents` are set to 0"

        Design: Corner/Validations/val_award_amount_must_be_within_the_request_and_inside_the_period
        """
        ctx = _setup_submitted_request_for_350000()
        _record_award(ctx["proposal"]["id"], 350001, "2026-08-01")
        _record_award(ctx["proposal"]["id"], 350000, "2027-08-01")

        awarded = validate_success(
            _record_award(ctx["proposal"]["id"], 350000, "2027-07-31")
        )
        assert awarded["status"] == "AWARDED"
        assert awarded["awarded_amount_cents"] == 350000
        assert awarded["award_date"] == "2027-07-31"
        assert awarded["released_cents"] == 0
        assert awarded["unreleased_cents"] == 350000
        assert awarded["returned_cents"] == 0

    def test_the_award_generates_no_obligations_because_the_cadence_defaulted(self):
        """The draft never named a `reporting_cadence`, so the award produces an
        empty report series.

        PRD: "The reporting obligation the award will generate is declared up front
        as `reporting_cadence`, one of `NONE`, `SEMIANNUAL` or `ANNUAL`, defaulting
        to `NONE`."

        Design: Corner/Validations/val_award_amount_must_be_within_the_request_and_inside_the_period
        """
        ctx = _setup_submitted_request_for_350000()
        awarded = validate_success(
            _record_award(ctx["proposal"]["id"], 350000, "2027-07-31")
        )

        assert awarded["report_count"] == 0
        assert list_proposal_reports(ctx["proposal"]["id"]) == []


def _create_tier(payload):
    """Raw POST so a rejected benefits array can be inspected."""
    return api_client.create_membership_tier(payload, DO_HEADERS)


def _tier_count():
    _, meta = validate_paginated(api_client.list_membership_tiers(DO_HEADERS))
    return meta["total_count"]


def _patron_payload(second_benefit_code):
    """An ANNUAL Patron tier at 30000 cents whose two benefits differ in
    fulfillment type and fair market value, and whose second code is under test."""
    return {
        "tier_code": "PATRON",
        "name": "Patron",
        "renewal_cadence": "ANNUAL",
        "contribution_amount_cents": 30000,
        "benefits": [
            benefit_payload("TOTE", "TOTE_BAG", 1200),
            benefit_payload(second_benefit_code, "MERCH_DISCOUNT", 900),
        ],
    }


class TestDuplicateBenefitCodeWithinOneTierIsRefused:
    """Uniqueness is enforced on `benefit_code` alone."""

    def test_two_entries_sharing_a_code_are_refused_and_no_tier_is_written(self):
        """The two TOTE entries differ in fulfillment type and in value, which does
        not save them.

        PRD: "Within a single tier the `benefit_code` values must all be distinct;
        a repeat is rejected with `ERR_BENEFIT_CODE_DUPLICATE` (HTTP 422)."

        Design: Corner/Validations/val_duplicate_benefit_code_within_one_tier_is_refused
        """
        validate_error(
            _create_tier(_patron_payload("TOTE")),
            ApiErrorId.ERR_BENEFIT_CODE_DUPLICATE,
        )
        assert _tier_count() == 0

    def test_renaming_the_second_code_admits_the_identical_bundle(self):
        """Nothing about the values changes, so both benefits clear the 600-cent
        threshold and the whole 2100 is quid pro quo.

        PRD: "Concretely, `insubstantial_threshold_cents` is the smaller of two
        quantities: the recurring `contribution_amount_cents` multiplied by 200
        basis points and rounded half up to whole cents, and the flat ceiling of
        13000 cents."

        Design: Corner/Validations/val_duplicate_benefit_code_within_one_tier_is_refused
        """
        validate_error(
            _create_tier(_patron_payload("TOTE")),
            ApiErrorId.ERR_BENEFIT_CODE_DUPLICATE,
        )

        created = validate_success(
            _create_tier(_patron_payload("DISCOUNT")), expected_status=201
        )
        assert created["benefit_count"] == 2
        assert created["insubstantial_threshold_cents"] == 600
        assert created["insubstantial_benefit_codes"] == []
        assert created["quid_pro_quo_per_period_cents"] == 2100


def _publish(tier_id):
    """Raw publish POST so the blocked tier's refusal can be inspected."""
    return api_client.publish_membership_tier(tier_id, DO_HEADERS)


def _define_benefactor_pair():
    """Two DRAFT annual tiers priced at 30000 cents, one carrying a 30000-cent
    gala benefit and one carrying a 29999-cent gala benefit."""
    blocked = define_tier(
        benefits=[benefit_payload("GALA", "EVENT_ACCESS", 30000)],
        tier_code="BENEFACTOR",
        name="Benefactor",
        renewal_cadence="ANNUAL",
        contribution_amount_cents=30000,
    )
    publishable = define_tier(
        benefits=[benefit_payload("GALA", "EVENT_ACCESS", 29999)],
        tier_code="BENEFACTOR_LITE",
        name="Benefactor Lite",
        renewal_cadence="ANNUAL",
        contribution_amount_cents=30000,
    )
    return blocked, publishable


class TestPublishIsRefusedWhenTheBenefitBundleEqualsTheContribution:
    """The gate is strict, so equality is on the wrong side of it."""

    def test_an_annual_tier_carries_its_benefit_value_through_unchanged(self):
        """Both tiers store the gala's annual figure as the per-period quid pro
        quo, which is the number the publish gate compares.

        PRD: "Walking the `benefits` array in exactly the order the request
        supplied it, an `ANNUAL` tier takes each benefit's
        `annual_fair_market_value_cents` unchanged as that benefit's per-period fair
        market value, while a `MONTHLY` tier divides that annual figure by 12 and
        rounds the result half up to whole cents **for that benefit
        individually**."

        Design: Corner/Validations/val_publish_is_refused_when_the_benefit_bundle_equals_the_contribution
        """
        blocked, publishable = _define_benefactor_pair()

        assert blocked["quid_pro_quo_per_period_cents"] == 30000
        assert blocked["contribution_amount_cents"] == 30000
        assert publishable["quid_pro_quo_per_period_cents"] == 29999
        assert publishable["contribution_amount_cents"] == 30000

    def test_a_bundle_worth_the_whole_contribution_cannot_publish(self):
        """Equality fails a strictly-less-than test, so the tier stays where it
        was drafted.

        PRD: "Publication has one substantive precondition:
        `quid_pro_quo_per_period_cents` must be **strictly less than**
        `contribution_amount_cents`. A benefit bundle worth the entire contribution
        - or more - leaves nothing deductible and makes the tier unpublishable,
        which is reported as `ERR_BENEFIT_VALUE_EXCEEDS_CONTRIBUTION` (HTTP 409)."

        Design: Corner/Validations/val_publish_is_refused_when_the_benefit_bundle_equals_the_contribution
        """
        blocked, _ = _define_benefactor_pair()

        validate_error(
            _publish(blocked["id"]),
            ApiErrorId.ERR_BENEFIT_VALUE_EXCEEDS_CONTRIBUTION,
        )

        unchanged = validate_success(
            api_client.get_membership_tier(blocked["id"], DO_HEADERS)
        )
        assert unchanged["status"] == "DRAFT"
        assert unchanged["published_at"] is None

    def test_one_cent_of_deductible_value_is_enough_to_publish(self):
        """The twin tier differs from the blocked one by a single cent on the same
        benefit, and that cent is what lets it through.

        PRD: "Publishing it is a separate step by a `DevelopmentOfficer` that takes
        the tier `DRAFT -> PUBLISHED` and stamps `published_at` with the logical
        clock."

        Design: Corner/Validations/val_publish_is_refused_when_the_benefit_bundle_equals_the_contribution
        """
        blocked, publishable = _define_benefactor_pair()
        _publish(blocked["id"])

        published = validate_success(_publish(publishable["id"]))
        assert published["status"] == "PUBLISHED"
        assert published["published_at"].startswith("2026-08-01T00:00:00")
        assert published["quid_pro_quo_per_period_cents"] == 29999


def _activate(collaboration_id):
    """Raw status action so each share-sum refusal can be inspected."""
    return api_client.collaboration_status_action(
        collaboration_id, {"action": "ACTIVATE"}, ED_HEADERS
    )


def _setup_two_short_collaborations():
    """Two DRAFT collaborations on one beat with non-overlapping windows: the
    first has both share sums short at 9300 bps, the second closes credit at
    10000 and leaves cost short."""
    period = open_fiscal_period()
    area = register_coverage_area(area_code="CLIMATE", name="Climate")

    both_short = open_collaboration(
        area["id"],
        period["id"],
        title="Heat island investigation",
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-30T00:00:00Z",
        total_cost_cents=100000,
        lead_credit_bps=6000,
        lead_cost_share_bps=6000,
    )
    both_short_partner = add_partner(
        both_short["id"], "Riverbend Public Media", 3300, 3300
    )

    cost_short = open_collaboration(
        area["id"],
        period["id"],
        title="Flood plain audit",
        window_start="2026-10-01T00:00:00Z",
        window_end="2026-10-31T00:00:00Z",
        total_cost_cents=100000,
        lead_credit_bps=6700,
        lead_cost_share_bps=6000,
    )
    cost_short_partner = add_partner(
        cost_short["id"], "Riverbend Public Media", 3300, 3300
    )

    return {
        "period": period,
        "area": area,
        "both_short": both_short,
        "both_short_partner": both_short_partner,
        "cost_short": cost_short,
        "cost_short_partner": cost_short_partner,
    }


class TestCreditShareSumErrorOutranksTheCostShareSumError:
    """Two sums are wrong on the first collaboration and only one is reported."""

    def test_the_credit_shortfall_is_reported_while_cost_is_equally_short(self):
        """6000 plus 3300 closes at 9300 on both dimensions, and the credit rung of
        the ladder is the one that answers.

        PRD: "credit shares must close at exactly 10000 bps, that is
        `lead_credit_bps` plus the `credit_share_bps` of every `CONFIRMED` partner,
        otherwise `ERR_CREDIT_SHARE_SUM_INVALID` (HTTP 409)"

        Design: Corner/Validations/val_credit_share_sum_error_outranks_the_cost_share_sum_error
        """
        ctx = _setup_two_short_collaborations()

        validate_error(
            _activate(ctx["both_short"]["id"]),
            ApiErrorId.ERR_CREDIT_SHARE_SUM_INVALID,
        )

        blocked = read_collaboration(ctx["both_short"]["id"])
        assert blocked["status"] == "DRAFT"
        assert blocked["lead_credit_bps"] == 6000
        assert blocked["lead_cost_share_bps"] == 6000

    def test_the_cost_shortfall_only_surfaces_once_credit_closes(self):
        """The second collaboration is identical in its cost shares and differs
        only in carrying 6700 lead credit bps, which is what changes the code.

        PRD: "cost shares must likewise close at exactly 10000 bps, otherwise
        `ERR_COST_SHARE_SUM_INVALID` (HTTP 409)"

        Design: Corner/Validations/val_credit_share_sum_error_outranks_the_cost_share_sum_error
        """
        ctx = _setup_two_short_collaborations()

        validate_error(
            _activate(ctx["cost_short"]["id"]),
            ApiErrorId.ERR_COST_SHARE_SUM_INVALID,
        )

        blocked = read_collaboration(ctx["cost_short"]["id"])
        assert blocked["status"] == "DRAFT"
        assert blocked["lead_credit_bps"] == 6700
        assert blocked["lead_cost_share_bps"] == 6000

    def test_neither_refusal_ever_runs_the_cost_split(self):
        """Both collaborations stay in DRAFT with every allocation at zero, so the
        apportionment is downstream of the share-sum gates.

        PRD: "Activation then runs the cost split."

        Design: Corner/Validations/val_credit_share_sum_error_outranks_the_cost_share_sum_error
        """
        ctx = _setup_two_short_collaborations()
        _activate(ctx["both_short"]["id"])
        _activate(ctx["cost_short"]["id"])

        for key, partner_key in (
            ("both_short", "both_short_partner"),
            ("cost_short", "cost_short_partner"),
        ):
            collaboration = read_collaboration(ctx[key]["id"])
            assert collaboration["status"] == "DRAFT"
            assert collaboration["lead_cost_cents"] == 0
            assert collaboration["allocated_cost_cents"] == 0
            assert collaboration["partner_count"] == 1

            partner = read_partner(ctx[partner_key]["id"])
            assert partner["status"] == "CONFIRMED"
            assert partner["cost_owed_cents"] == 0
            assert partner["remainder_rank"] == 0
