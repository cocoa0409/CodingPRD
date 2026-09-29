"""Error contracts: the not-found families, the expert independence refusals, the
split quote-answer and delivery-answer status errors, the locator ladder, the
buyout gates, the window settlement re-checks, and the complaint lifecycle.

Every refusal below is driven from a state the PRD reaches through declared
endpoints, so that exactly one validation family can decide the response.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    SPONSOR_USER_ID,
    constants,
    factories,
    fixtures,
    make_expert_headers,
    make_insurer_rep_headers,
    make_participant_headers,
    opaque_headers,
)
from test_helpers.api_errors import (
    ERR_ADDRESS_SEARCH_TIER_EXHAUSTED,
    ERR_AUDIT_NOT_FOUND,
    ERR_COMPLAINT_NOT_FOUND,
    ERR_COMPLAINT_NOT_TRIAGED,
    ERR_COMPLAINT_STATE_INVALID,
    ERR_ELECTION_NOT_FOUND,
    ERR_EXPERT_CONFLICT_DISCLOSED,
    ERR_EXPERT_NOT_ENGAGED,
    ERR_EXPERT_NOT_FOUND,
    ERR_EXPERT_STATE_INVALID,
    ERR_IDENTITY_MISMATCH,
    ERR_INSURER_NOT_FOUND,
    ERR_INSURER_RATING_BELOW_FLOOR,
    ERR_MORTALITY_NOT_CONFIRMED,
    ERR_PARTICIPANT_NOT_FOUND,
    ERR_PARTICIPANT_NOT_TRANSFERRED,
    ERR_PLAN_ASSETS_INSUFFICIENT,
    ERR_PLAN_NOT_FOUND,
    ERR_QUOTE_NOT_FOUND,
    ERR_QUOTE_NOT_REQUESTED,
    ERR_QUOTE_STATE_INVALID,
    ERR_QUOTE_TRANCHE_MISMATCH,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SETTLEMENT_ENTRY_NOT_FOUND,
    ERR_STRATEGY_NOT_APPROVED,
    ERR_STRATEGY_NOT_FOUND,
    ERR_TRANCHE_EMPTY,
    ERR_TRANCHE_NOT_FOUND,
    ERR_TRANCHE_NOT_SELECTED,
    ERR_TRANCHE_NOT_TRANSFERRED,
    ERR_TRANSFER_NOT_FOUND,
    ERR_TRANSFER_NOT_INITIATED,
    ERR_TRANSFER_STATE_INVALID,
    ERR_WINDOW_CAP_EXCEEDED,
    ERR_WINDOW_NOT_FOUND,
    ERR_WINDOW_NOT_OPEN,
)
from test_helpers.assertions import assert_fields, assert_version_unchanged

RETIREE = "RETIREE_IN_PAY"
DEFERRED = "DEFERRED_VESTED"

#: A premium the default carrier capacity comfortably absorbs.
PREMIUM_CENTS = 11800000
#: A cash delivery whose credited value clears `PREMIUM_CENTS` after the wire fee.
CASH_GROSS_CENTS = 12000000


# ---------------------------------------------------------------------------
# Local setup helpers
# ---------------------------------------------------------------------------


def _retiree_spec(monthly_cents=250000):
    return fixtures.ParticipantSpec(
        stated_monthly_benefit_cents=monthly_cents,
        cohort=RETIREE,
        credited_service_months=400,
    )


def _authorized_with_retiree(api, **plan_overrides):
    """A buyout-authorized plan holding one cleansed retiree."""
    return fixtures.build_authorized_plan(
        api, participants=[_retiree_spec()], **plan_overrides
    )


def _quoting_tranche_with_carrier(api, rating_grade="AA", premium_cents=PREMIUM_CENTS):
    """An authorized plan, a tranche out for quote, and one admitted carrier."""
    authorized = _authorized_with_retiree(api)
    quoting = fixtures.build_quoting_tranche(
        api, authorized.plan_id, authorized.participants, RETIREE
    )
    insurer = fixtures.create_insurer(
        api, "Northwall Life Assurance", rating_grade, 4200, 200000000
    )
    return authorized, quoting, insurer, premium_cents


def _lump_sum_plan_with_participant(api, monthly_cents=20000, **plan_overrides):
    """A lump-sum-authorized plan holding one cleansed deferred-vested participant."""
    plan = fixtures.create_plan(api, **plan_overrides)
    fixtures.create_approved_strategy(api, plan["id"], "LUMP_SUM_WINDOW")
    plan = fixtures.adopt_amendment(api, plan["id"], "LUMP_SUM_ONLY")
    participant = fixtures.create_clean_participant(
        api,
        plan["id"],
        cohort=DEFERRED,
        stated_monthly_benefit_cents=monthly_cents,
        credited_service_months=240,
        final_average_monthly_earnings_cents=constants.fame_for_zero_variance(
            monthly_cents, 240
        ),
    )
    return plan, participant


def _settled_buyout(api, insurer_name="Northwall Life Assurance"):
    """A tranche taken all the way to SETTLED, handing its retiree to the carrier."""
    insurer = fixtures.create_insurer(api, insurer_name, "AA", 4200, 200000000)
    authorized = _authorized_with_retiree(api)
    tranche = fixtures.build_settled_tranche(
        api,
        authorized.plan_id,
        authorized.participants,
        [fixtures.QuoteSpec(insurer["id"], PREMIUM_CENTS)],
        insurer["id"],
        CASH_GROSS_CENTS,
        transfer_mode="CASH",
        target_cohort=RETIREE,
    )
    return authorized, insurer, tranche


class TestNotFoundFamilies:
    """Each entity family answers an unknown identifier with its own code."""

    def test_error_every_entity_family_answers_an_unknown_id_with_its_own_code(
        self, api, sponsor, actuary, administrator, regulator
    ):
        """Twelve families each refuse `NON_EXISTENT_UUID` with the code named for that family.

        The full set of not-found errors is `ERR_PLAN_NOT_FOUND`, `ERR_STRATEGY_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_ELECTION_NOT_FOUND`, `ERR_TRANCHE_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_INSURER_NOT_FOUND`, `ERR_EXPERT_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, and `ERR_SETTLEMENT_ENTRY_NOT_FOUND`, each carrying HTTP 404.
        Identifiers embedded in a request path are resolved strictly left to right, and the first identifier that does not resolve decides the error.

        Design: Corner/errors/every_entity_family_has_its_own_not_found_code
        """
        fixtures.reset_clock(api)

        validate_error(api.get_plan(NON_EXISTENT_UUID, sponsor), ERR_PLAN_NOT_FOUND)
        validate_error(
            api.post_strategy_submission(NON_EXISTENT_UUID, {}, actuary),
            ERR_STRATEGY_NOT_FOUND,
        )
        validate_error(
            api.get_participant(NON_EXISTENT_UUID, administrator), ERR_PARTICIPANT_NOT_FOUND
        )
        validate_error(
            api.post_audit_resolution(
                NON_EXISTENT_UUID, factories.audit_resolution_payload(), actuary
            ),
            ERR_AUDIT_NOT_FOUND,
        )
        validate_error(
            api.post_window_closing(NON_EXISTENT_UUID, {}, administrator),
            ERR_WINDOW_NOT_FOUND,
        )
        validate_error(
            api.get_election(NON_EXISTENT_UUID, administrator), ERR_ELECTION_NOT_FOUND
        )
        validate_error(api.get_tranche(NON_EXISTENT_UUID, sponsor), ERR_TRANCHE_NOT_FOUND)
        validate_error(api.get_quote(NON_EXISTENT_UUID, sponsor), ERR_QUOTE_NOT_FOUND)
        validate_error(api.get_insurer(NON_EXISTENT_UUID, regulator), ERR_INSURER_NOT_FOUND)
        validate_error(api.get_expert(NON_EXISTENT_UUID, sponsor), ERR_EXPERT_NOT_FOUND)
        validate_error(
            api.get_complaint(NON_EXISTENT_UUID, administrator), ERR_COMPLAINT_NOT_FOUND
        )
        validate_error(
            api.get_settlement_entry(NON_EXISTENT_UUID, sponsor),
            ERR_SETTLEMENT_ENTRY_NOT_FOUND,
        )

    def test_error_an_unknown_asset_transfer_is_refused_by_the_endpoint_that_names_one(
        self, api
    ):
        """The delivery-review path is the only one naming a transfer id, and it refuses an unknown one.

        The full set of not-found errors is `ERR_PLAN_NOT_FOUND`, `ERR_STRATEGY_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_ELECTION_NOT_FOUND`, `ERR_TRANCHE_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_INSURER_NOT_FOUND`, `ERR_EXPERT_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, and `ERR_SETTLEMENT_ENTRY_NOT_FOUND`, each carrying HTTP 404.
        Either answer requires the acting `X-User-ID` to equal the tranche's `selected_insurer_id`, otherwise `ERR_IDENTITY_MISMATCH`, and requires the delivery to be in `INITIATED`.

        Design: Corner/errors/every_entity_family_has_its_own_not_found_code
        """
        fixtures.reset_clock(api)
        insurer = fixtures.create_insurer(
            api, "Northwall Life Assurance", "AA", 4200, 200000000
        )

        response = api.post_insurer_review(
            NON_EXISTENT_UUID,
            factories.insurer_review_payload("ACCEPT"),
            make_insurer_rep_headers(insurer["id"]),
        )

        validate_error_is_one_of(response, [ERR_TRANSFER_NOT_FOUND, ERR_IDENTITY_MISMATCH])


class TestExpertIndependenceRefusals:
    """The independence review is the gate a conflicted firm cannot pass."""

    def test_error_the_proposer_may_not_review_its_own_proposal(self, api, sponsor):
        """A reviewer whose user id equals `proposed_by_user_id` is refused for segregation of duties.

        The proposal starts in `INDEPENDENCE_REVIEW`, records `proposed_by_user_id` from the acting `X-User-ID`, and leaves `reviewed_by_user_id`, `safest_available_opinion`, and `opinion_issued_at` null.
        Either decision requires the engagement to be in `INDEPENDENCE_REVIEW`, otherwise `ERR_EXPERT_STATE_INVALID`, and requires the reviewing `X-User-ID` to differ from `proposed_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`.

        Design: Corner/errors/expert_with_a_disclosed_conflict_cannot_be_engaged
        """
        fixtures.reset_clock(api)
        plan = fixtures.create_plan(api)
        expert = fixtures.create_expert(api, plan["id"], "Kestrel Fiduciary Advisors LLP")
        assert_fields(
            expert,
            expert_status="INDEPENDENCE_REVIEW",
            proposed_by_user_id=SPONSOR_USER_ID,
            reviewed_by_user_id=None,
            safest_available_opinion=None,
            opinion_issued_at=None,
        )

        validate_error(
            api.post_independence_review(
                expert["id"],
                factories.expert_review_payload("ENGAGE"),
                opaque_headers("PlanFiduciary", SPONSOR_USER_ID),
            ),
            ERR_SEGREGATION_OF_DUTIES,
        )

        after = fixtures.read_expert(api, expert["id"])
        assert after["expert_status"] == "INDEPENDENCE_REVIEW"
        assert after["reviewed_by_user_id"] is None
        assert_version_unchanged(expert, after)

    def test_error_a_firm_that_disclosed_a_conflict_cannot_be_engaged_but_can_be_disqualified(
        self, api, fiduciary
    ):
        """ENGAGE is refused for a disclosed conflict while DISQUALIFY on the same firm succeeds.

        An `ENGAGE` decision additionally requires `conflict_disclosed` to be false; a firm that disclosed a conflict cannot be engaged and is rejected with `ERR_EXPERT_CONFLICT_DISCLOSED`.
        `ENGAGE` moves the engagement `INDEPENDENCE_REVIEW → ENGAGED` and `DISQUALIFY` moves it `INDEPENDENCE_REVIEW → DISQUALIFIED`; both record `reviewed_by_user_id` and bump the `version`, and both `ENGAGED` and `DISQUALIFIED` are reached with equal finality — `DISQUALIFIED` is terminal.

        Design: Corner/errors/expert_with_a_disclosed_conflict_cannot_be_engaged
        """
        fixtures.reset_clock(api)
        plan = fixtures.create_plan(api)
        expert = fixtures.create_expert(
            api, plan["id"], "Bellhaven Actuarial Counsel", conflict_disclosed=True
        )
        assert expert["conflict_disclosed"] is True

        validate_error(
            api.post_independence_review(
                expert["id"], factories.expert_review_payload("ENGAGE"), fiduciary
            ),
            ERR_EXPERT_CONFLICT_DISCLOSED,
        )
        assert fixtures.read_expert(api, expert["id"])["expert_status"] == "INDEPENDENCE_REVIEW"

        disqualified = validate_success(
            api.post_independence_review(
                expert["id"], factories.expert_review_payload("DISQUALIFY"), fiduciary
            )
        )
        assert disqualified["expert_status"] == "DISQUALIFIED"
        assert disqualified["reviewed_by_user_id"] is not None
        assert disqualified["version"] == expert["version"] + 1

    def test_error_a_disqualified_firm_can_neither_be_reviewed_again_nor_opine(
        self, api, fiduciary
    ):
        """A terminal engagement refuses a second review, and only an ENGAGED firm acting as itself may opine.

        Either decision requires the engagement to be in `INDEPENDENCE_REVIEW`, otherwise `ERR_EXPERT_STATE_INVALID`, and requires the reviewing `X-User-ID` to differ from `proposed_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`.
        The engagement must be in `ENGAGED`, otherwise `ERR_EXPERT_NOT_ENGAGED`, and the acting `X-User-ID` must be this engagement's own identifier, otherwise `ERR_IDENTITY_MISMATCH`.

        Design: Corner/errors/expert_with_a_disclosed_conflict_cannot_be_engaged
        """
        fixtures.reset_clock(api)
        plan = fixtures.create_plan(api)
        conflicted = fixtures.create_expert(
            api, plan["id"], "Bellhaven Actuarial Counsel", conflict_disclosed=True
        )
        fixtures.review_expert(api, conflicted["id"], "DISQUALIFY")
        engaged = fixtures.create_expert(api, plan["id"], "Kestrel Fiduciary Advisors LLP")
        engaged = fixtures.review_expert(api, engaged["id"], "ENGAGE")
        assert engaged["expert_status"] == "ENGAGED"

        validate_error(
            api.post_independence_review(
                conflicted["id"], factories.expert_review_payload("DISQUALIFY"), fiduciary
            ),
            ERR_EXPERT_STATE_INVALID,
        )
        validate_error(
            api.post_expert_opinion(
                conflicted["id"],
                factories.expert_opinion_payload("AFFIRMATIVE"),
                make_expert_headers(conflicted["id"]),
            ),
            ERR_EXPERT_NOT_ENGAGED,
        )
        validate_error(
            api.post_expert_opinion(
                engaged["id"],
                factories.expert_opinion_payload("AFFIRMATIVE"),
                make_expert_headers(conflicted["id"]),
            ),
            ERR_IDENTITY_MISMATCH,
        )

        opinion = validate_success(
            api.post_expert_opinion(
                engaged["id"],
                factories.expert_opinion_payload("AFFIRMATIVE"),
                make_expert_headers(engaged["id"]),
            )
        )
        assert_fields(
            opinion, expert_status="OPINION_ISSUED", safest_available_opinion="AFFIRMATIVE"
        )


class TestQuoteAnswerRefusals:
    """Only the soliciting carrier may answer, and the status error is split."""

    def test_error_another_carrier_may_not_answer_a_quote_addressed_to_someone_else(
        self, api
    ):
        """A rep acting for a different carrier is refused with an identity mismatch and the quote stays REQUESTED.

        Either answer requires the acting `X-User-ID` to equal the quote's `insurer_id`, otherwise `ERR_IDENTITY_MISMATCH`, and requires the quote to still be in `REQUESTED`.

        Design: Corner/errors/quote_answer_errors_split_live_from_terminal_and_check_identity
        """
        fixtures.reset_clock(api)
        _authorized, quoting, insurer, premium = _quoting_tranche_with_carrier(api)
        bystander = fixtures.create_insurer(
            api, "Cairnmoor Assurance Company", "AA_MINUS", 3900, 200000000
        )
        quote = fixtures.request_quote(api, quoting.tranche_id, insurer["id"])

        validate_error(
            api.post_quote_submission(
                quote["id"],
                factories.quote_submit_payload(premium, 90, 60),
                make_insurer_rep_headers(bystander["id"]),
            ),
            ERR_IDENTITY_MISMATCH,
        )

        after = fixtures.read_quote(api, quote["id"])
        assert_fields(
            after,
            quote_status="REQUESTED",
            premium_cents=None,
            submitted_at=None,
            rating_at_submission=None,
        )
        assert_version_unchanged(quote, after)

    def test_error_a_live_quote_that_has_moved_on_yields_the_not_requested_code(self, api):
        """Re-answering a SUBMITTED and then a SHORTLISTED quote is refused as no longer awaiting an answer.

        The status error for a quote that has moved on is deliberately split: a quote that is still live but no longer awaiting an answer — `SUBMITTED`, `SHORTLISTED`, or `LOCKED` — yields `ERR_QUOTE_NOT_REQUESTED`, whereas a quote that has already reached a terminal status of `DECLINED`, `INELIGIBLE`, `EXPIRED`, or `BOUND` yields `ERR_QUOTE_STATE_INVALID`.
        Submission stamps `submitted_at` from the logical clock, sets `expires_at` to `submitted_at` plus `quote_valid_days` days, snapshots the carrier's current `rating_grade` into `rating_at_submission` for the fiduciary record, and bumps the quote's `version`.

        Design: Corner/errors/quote_answer_errors_split_live_from_terminal_and_check_identity
        """
        fixtures.reset_clock(api)
        _authorized, quoting, insurer, premium = _quoting_tranche_with_carrier(api)
        rep = make_insurer_rep_headers(insurer["id"])
        submitted = fixtures.request_and_submit_quote(
            api, quoting.tranche_id, insurer["id"], premium
        )
        assert_fields(submitted, quote_status="SUBMITTED", rating_at_submission="AA")

        validate_error(
            api.post_quote_submission(
                submitted["id"], factories.quote_submit_payload(premium - 100000, 90, 60), rep
            ),
            ERR_QUOTE_NOT_REQUESTED,
        )
        assert fixtures.read_quote(api, submitted["id"])["premium_cents"] == premium

        fixtures.select_insurer(api, quoting.tranche_id, "SAFETY_WEIGHTED")
        assert fixtures.read_quote(api, submitted["id"])["quote_status"] == "SHORTLISTED"

        validate_error(
            api.post_quote_submission(
                submitted["id"], factories.quote_submit_payload(premium, 90, 60), rep
            ),
            ERR_QUOTE_NOT_REQUESTED,
        )
        assert fixtures.read_quote(api, submitted["id"])["premium_cents"] == premium

    def test_error_a_terminal_quote_yields_the_state_invalid_code(self, api):
        """A carrier that has already declined cannot answer again, and the refusal names the terminal split.

        A `DECLINE` moves the quote `REQUESTED → DECLINED` instead and requires a non-empty `decline_reason`, whose absence is likewise rejected with `ERR_INVALID_REQUEST`; it records the reason and bumps the `version`.
        The status error for a quote that has moved on is deliberately split: a quote that is still live but no longer awaiting an answer — `SUBMITTED`, `SHORTLISTED`, or `LOCKED` — yields `ERR_QUOTE_NOT_REQUESTED`, whereas a quote that has already reached a terminal status of `DECLINED`, `INELIGIBLE`, `EXPIRED`, or `BOUND` yields `ERR_QUOTE_STATE_INVALID`.

        Design: Corner/errors/quote_answer_errors_split_live_from_terminal_and_check_identity
        """
        fixtures.reset_clock(api)
        _authorized, quoting, insurer, premium = _quoting_tranche_with_carrier(api)
        rep = make_insurer_rep_headers(insurer["id"])
        quote = fixtures.request_quote(api, quoting.tranche_id, insurer["id"])

        declined = validate_success(
            api.post_quote_submission(quote["id"], factories.quote_decline_payload(), rep)
        )
        assert declined["quote_status"] == "DECLINED"
        assert declined["decline_reason"]

        validate_error(
            api.post_quote_submission(
                quote["id"], factories.quote_submit_payload(premium, 90, 60), rep
            ),
            ERR_QUOTE_STATE_INVALID,
        )
        validate_error(
            api.post_quote_submission(quote["id"], factories.quote_decline_payload(), rep),
            ERR_QUOTE_STATE_INVALID,
        )


class TestAddressSearchLadder:
    """The locator ladder holds three attempts and then refuses."""

    def test_error_three_no_match_searches_exhaust_the_ladder_and_land_on_unlocatable(
        self, api
    ):
        """Each recorded miss advances one tier, and the third leaves the record UNLOCATABLE at a derived score.

        Each recorded attempt increments `address_search_attempts` by one and sets `address_search_tier` to the tier corresponding to the new attempt count — `TIER_1` after the first, `TIER_2` after the second, `TIER_3` after the third — reflecting the escalation from cheap batch matching to premium skip tracing.
        A `NO_MATCH` recorded when exactly two attempts already stand is the third and final one: it moves the participant `UNCONFIRMED → UNLOCATABLE`, sets `address_search_attempts` to 3 and `address_search_tier` to `TIER_3`, and recomputes `data_confidence_score` and `data_status`.
        An `address_status` of `UNCONFIRMED` costs 40 points, while an `address_status` of `UNLOCATABLE` costs only 25 — an exhausted search is a documented outcome, an un-started one is not, so a participant whose locator ladder is exhausted can still reach 75 while one who has never been searched sits at 60.

        Design: Corner/errors/participant_cleansing_refuses_a_fourth_address_search
        """
        fixtures.reset_clock(api)
        plan = fixtures.create_plan(api)
        participant = fixtures.create_participant(api, plan["id"])

        first = fixtures.record_address_no_match(api, participant["id"])
        assert_fields(
            first, address_status="UNCONFIRMED", address_search_attempts=1, address_search_tier="TIER_1"
        )
        second = fixtures.record_address_no_match(api, participant["id"])
        assert_fields(
            second, address_status="UNCONFIRMED", address_search_attempts=2, address_search_tier="TIER_2"
        )
        third = fixtures.record_address_no_match(api, participant["id"])
        assert_fields(
            third,
            address_status="UNLOCATABLE",
            address_search_attempts=3,
            address_search_tier="TIER_3",
            data_confidence_score=constants.data_confidence_for(
                "UNLOCATABLE", "UNVERIFIED", "NOT_AUDITED"
            ),
            data_status="NEEDS_REVIEW",
        )
        assert third["data_confidence_score"] == 40

    def test_error_a_fourth_search_is_refused_and_changes_nothing(self, api, administrator):
        """Once three attempts stand, both a further miss and a further match are refused as exhausted.

        Any search attempted once three attempts already stand is rejected with `ERR_ADDRESS_SEARCH_TIER_EXHAUSTED`, and both `CONFIRMED` and `UNLOCATABLE` are terminal for this dimension.

        Design: Corner/errors/participant_cleansing_refuses_a_fourth_address_search
        """
        fixtures.reset_clock(api)
        plan = fixtures.create_plan(api)
        participant = fixtures.create_participant(api, plan["id"])
        for _ in range(3):
            exhausted = fixtures.record_address_no_match(api, participant["id"])

        validate_error(
            api.post_address_search(
                participant["id"], factories.address_search_no_match_payload(), administrator
            ),
            ERR_ADDRESS_SEARCH_TIER_EXHAUSTED,
        )
        validate_error(
            api.post_address_search(
                participant["id"],
                factories.address_search_confirmed_payload(),
                administrator,
            ),
            ERR_ADDRESS_SEARCH_TIER_EXHAUSTED,
        )

        after = fixtures.read_participant(api, participant["id"])
        assert_fields(
            after,
            address_status="UNLOCATABLE",
            address_search_attempts=3,
            address_search_tier="TIER_3",
            confirmed_address_line1=None,
            confirmed_postal_code=None,
        )
        assert_version_unchanged(exhausted, after)


class TestBuyoutGatingErrors:
    """Each gate on the road to quoting refuses with its own code."""

    def test_error_the_amendment_scope_must_be_backed_by_an_approved_strategy(
        self, api, sponsor
    ):
        """A drafted strategy backs no scope, an approved buyout strategy does not back BOTH, and BUYOUT_ONLY then succeeds.

        A scope of `LUMP_SUM_ONLY` is backed by an approved `LUMP_SUM_WINDOW` or `HYBRID_WINDOW_AND_BUYOUT` strategy; a scope of `BUYOUT_ONLY` is backed by an approved `ANNUITY_BUYOUT` or `HYBRID_WINDOW_AND_BUYOUT` strategy; a scope of `BOTH` is backed only by an approved `HYBRID_WINDOW_AND_BUYOUT` strategy.
        If no approved strategy of a compatible type exists, the adoption is rejected with `ERR_STRATEGY_NOT_APPROVED`.

        Design: Corner/errors/buyout_gating_errors_each_have_their_own_code
        """
        fixtures.reset_clock(api)
        plan = fixtures.create_plan(api)
        strategy = fixtures.create_strategy(api, plan["id"], "ANNUITY_BUYOUT")
        assert strategy["strategy_status"] == "DRAFT"

        validate_error(
            api.post_settlement_amendment(
                plan["id"],
                factories.amendment_adopt_payload("BUYOUT_ONLY", "2026-08-15T00:00:00Z"),
                sponsor,
            ),
            ERR_STRATEGY_NOT_APPROVED,
        )
        assert fixtures.read_plan(api, plan["id"])["plan_status"] == "ONGOING"

        fixtures.submit_strategy(api, strategy["id"])
        approved = fixtures.decide_strategy(api, strategy["id"], "APPROVE")
        assert approved["strategy_status"] == "APPROVED"

        validate_error(
            api.post_settlement_amendment(
                plan["id"],
                factories.amendment_adopt_payload("BOTH", "2026-08-15T00:00:00Z"),
                sponsor,
            ),
            ERR_STRATEGY_NOT_APPROVED,
        )

        adopted = validate_success(
            api.post_settlement_amendment(
                plan["id"],
                factories.amendment_adopt_payload("BUYOUT_ONLY", "2026-08-15T00:00:00Z"),
                sponsor,
            )
        )
        assert_fields(
            adopted, plan_status="SETTLEMENT_AUTHORIZED", amendment_scope="BUYOUT_ONLY"
        )

    def test_error_an_empty_tranche_cannot_go_out_for_quote(self, api, fiduciary):
        """A tranche holding nobody is refused with the empty-tranche code and stays in DRAFT.

        The tranche must hold at least one assigned participant, else `ERR_TRANCHE_EMPTY`.
        A drafted tranche starts in `DRAFT` with `data_readiness_flag` `BLOCKED`, `assigned_participant_count` 0, both `accounting_liability_cents` and `settlement_liability_cents` 0, `transfer_expense_cents` 0, and `selection_basis`, `selected_quote_id`, `selected_insurer_id`, `selection_score_bp`, `locked_premium_cents`, `lock_start_at`, `lock_expires_at`, `settlement_gain_loss_cents`, `settled_at`, `abandoned_at`, and `abandonment_reason` all null.

        Design: Corner/errors/buyout_gating_errors_each_have_their_own_code
        """
        fixtures.reset_clock(api)
        authorized = fixtures.build_authorized_plan(api)
        tranche = fixtures.create_tranche(api, authorized.plan_id, RETIREE)
        assert_fields(
            tranche,
            tranche_status="DRAFT",
            assigned_participant_count=0,
            data_readiness_flag="BLOCKED",
        )

        validate_error(
            api.post_tranche_quoting(tranche["id"], {}, fiduciary), ERR_TRANCHE_EMPTY
        )

        after = fixtures.read_tranche(api, tranche["id"])
        assert after["tranche_status"] == "DRAFT"
        assert_version_unchanged(tranche, after)

    def test_error_an_unverified_mortality_blocks_quoting_even_at_a_clean_score(
        self, api, fiduciary
    ):
        """A participant sitting at exactly the clean boundary is still refused for unverified mortality.

        Every assigned participant must have `mortality_status` `ALIVE_CONFIRMED`, else `ERR_MORTALITY_NOT_CONFIRMED`, and `data_status` `CLEAN`, else `ERR_PARTICIPANT_DATA_NOT_CLEAN`.
        A freshly loaded participant therefore scores 25 and is `NEEDS_REVIEW`; a participant who is `CONFIRMED`, `ALIVE_CONFIRMED`, and `PASSED_CLOSED` scores 100; one who is `CONFIRMED`, `ALIVE_CONFIRMED`, and `CORRECTION_REQUIRED` scores 85 and is still `CLEAN`; and one who is `CONFIRMED` but `UNVERIFIED` with a closed audit sits at exactly 80, which is `CLEAN` because the boundary is inclusive.

        Design: Corner/errors/buyout_gating_errors_each_have_their_own_code
        """
        fixtures.reset_clock(api)
        authorized = fixtures.build_authorized_plan(api)
        participant = fixtures.create_participant(
            api, authorized.plan_id, cohort=RETIREE, stated_monthly_benefit_cents=250000
        )
        fixtures.confirm_address(api, participant["id"])
        audit = fixtures.open_benefit_audit(api, participant["id"])
        fixtures.resolve_audit(api, audit["id"], "ACCEPT_AS_IS")
        participant = fixtures.read_participant(api, participant["id"])
        assert_fields(
            participant,
            address_status="CONFIRMED",
            mortality_status="UNVERIFIED",
            benefit_audit_status="PASSED_CLOSED",
            data_confidence_score=80,
            data_status="CLEAN",
        )
        tranche = fixtures.create_tranche(api, authorized.plan_id, RETIREE)
        fixtures.assign_participant(api, tranche["id"], participant["id"])

        validate_error(
            api.post_tranche_quoting(tranche["id"], {}, fiduciary), ERR_MORTALITY_NOT_CONFIRMED
        )
        assert fixtures.read_tranche(api, tranche["id"])["tranche_status"] == "DRAFT"

        fixtures.confirm_alive(api, participant["id"])
        quoting = validate_success(api.post_tranche_quoting(tranche["id"], {}, fiduciary))
        assert_fields(quoting, tranche_status="QUOTING", data_readiness_flag="READY")

    def test_error_a_carrier_below_the_rating_floor_may_not_be_solicited(self, api, fiduciary):
        """A BBB carrier and a carrier under review are both refused, and no quote row is created.

        A carrier whose live `rating_grade` maps below 78 points, or whose `insurer_status` is anything other than `ACTIVE`, may not be solicited at all and is rejected with `ERR_INSURER_RATING_BELOW_FLOOR`.
        `AAA` is worth 100 points, `AA_PLUS` 92, `AA` 85, `AA_MINUS` 78, `A_PLUS` 70, `A` 60, and `BBB` 40.

        Design: Corner/errors/buyout_gating_errors_each_have_their_own_code
        """
        fixtures.reset_clock(api)
        _authorized, quoting, insurer, _premium = _quoting_tranche_with_carrier(api)
        weak = fixtures.create_insurer(
            api, "Ashgate Indemnity Company", "BBB", 3000, 200000000
        )
        assert constants.RATING_POINTS["BBB"] < constants.SAFEST_AVAILABLE_MIN_RATING_POINTS

        validate_error(
            api.create_quote(
                quoting.tranche_id, factories.quote_request_payload(weak["id"]), fiduciary
            ),
            ERR_INSURER_RATING_BELOW_FLOOR,
        )

        fixtures.change_rating(api, insurer["id"], "AA", insurer_status="UNDER_REVIEW")
        validate_error(
            api.create_quote(
                quoting.tranche_id, factories.quote_request_payload(insurer["id"]), fiduciary
            ),
            ERR_INSURER_RATING_BELOW_FLOOR,
        )

        _rows, meta = validate_paginated(
            api.list_quotes(fiduciary, {"tranche_id": quoting.tranche_id})
        )
        assert meta["total_count"] == 0


class TestTrancheSequencingErrors:
    """The lock and the settlement each name the state they require."""

    def test_error_the_lock_and_the_settlement_name_the_state_they_require(
        self, api, fiduciary, sponsor
    ):
        """Locking demands INSURER_SELECTED and recognition demands ASSETS_TRANSFERRED, from each earlier state.

        The tranche must be in `INSURER_SELECTED`, and any other status is rejected with `ERR_TRANCHE_NOT_SELECTED`.
        **Recognising the buyout** is the final sponsor act on a tranche, moving it `ASSETS_TRANSFERRED → SETTLED`. Any other starting status is rejected with `ERR_TRANCHE_NOT_TRANSFERRED`.

        Design: Corner/errors/lock_and_settlement_sequencing_errors_name_the_required_state
        """
        fixtures.reset_clock(api)
        _authorized, quoting, insurer, premium = _quoting_tranche_with_carrier(api)

        validate_error(
            api.post_pricing_lock(quoting.tranche_id, {}, fiduciary), ERR_TRANCHE_NOT_SELECTED
        )
        validate_error(
            api.post_tranche_settlement(quoting.tranche_id, {}, sponsor),
            ERR_TRANCHE_NOT_TRANSFERRED,
        )

        fixtures.request_and_submit_quote(
            api, quoting.tranche_id, insurer["id"], premium
        )
        selected = fixtures.select_insurer(api, quoting.tranche_id, "SAFETY_WEIGHTED")
        assert selected["tranche_status"] == "INSURER_SELECTED"
        validate_error(
            api.post_tranche_settlement(quoting.tranche_id, {}, sponsor),
            ERR_TRANCHE_NOT_TRANSFERRED,
        )

        locked = fixtures.lock_pricing(api, quoting.tranche_id)
        assert_fields(
            locked, tranche_status="PRICING_LOCKED", locked_premium_cents=premium
        )
        validate_error(
            api.post_tranche_settlement(quoting.tranche_id, {}, sponsor),
            ERR_TRANCHE_NOT_TRANSFERRED,
        )

    def test_error_a_superseded_delivery_and_an_answered_delivery_split_the_status_error(
        self, api, sponsor
    ):
        """The delivery a later one displaced is state-invalid while the accepted one becomes not-initiated.

        Any delivery still awaiting the carrier's answer on the same tranche transitions `INITIATED → SUPERSEDED` before the new one is created, bumping its own `version`.
        Here too the status error is split: a delivery that has already been answered, being `SETTLED` or `REJECTED`, yields `ERR_TRANSFER_NOT_INITIATED`, while a delivery that was `SUPERSEDED` by a later delivery on the same tranche yields `ERR_TRANSFER_STATE_INVALID`.
        An `ACCEPT` moves the delivery `INITIATED → SETTLED`, stamps `settled_at` from the logical clock, and cascades: the tranche transitions `PRICING_LOCKED → ASSETS_TRANSFERRED` and copies this delivery's `transfer_expense_cents` onto its own `transfer_expense_cents`, bumping the tranche's `version` as well as the delivery's.

        Design: Corner/errors/lock_and_settlement_sequencing_errors_name_the_required_state
        """
        fixtures.reset_clock(api)
        insurer = fixtures.create_insurer(
            api, "Northwall Life Assurance", "AA", 4200, 200000000
        )
        authorized = _authorized_with_retiree(api)
        locked = fixtures.build_locked_tranche(
            api,
            authorized.plan_id,
            authorized.participants,
            [fixtures.QuoteSpec(insurer["id"], PREMIUM_CENTS)],
            target_cohort=RETIREE,
        )
        rep = make_insurer_rep_headers(insurer["id"])
        first = fixtures.initiate_cash_transfer(api, locked["id"], CASH_GROSS_CENTS)
        second = fixtures.initiate_cash_transfer(api, locked["id"], CASH_GROSS_CENTS)
        assert second["id"] != first["id"]

        validate_error(
            api.post_insurer_review(
                first["id"], factories.insurer_review_payload("ACCEPT"), rep
            ),
            ERR_TRANSFER_STATE_INVALID,
        )

        accepted = validate_success(
            api.post_insurer_review(
                second["id"], factories.insurer_review_payload("ACCEPT"), rep
            )
        )
        assert accepted["transfer_status"] == "SETTLED"
        assert fixtures.read_tranche(api, locked["id"])["tranche_status"] == "ASSETS_TRANSFERRED"

        validate_error(
            api.post_insurer_review(
                second["id"], factories.insurer_review_payload("ACCEPT"), rep
            ),
            ERR_TRANSFER_NOT_INITIATED,
        )

        settled = validate_success(api.post_tranche_settlement(locked["id"], {}, sponsor))
        assert settled["tranche_status"] == "SETTLED"
        assert (
            fixtures.read_quote(api, settled["selected_quote_id"])["quote_status"] == "BOUND"
        )


class TestWindowSettlementRefusals:
    """The window's own interval, the cash cap and the plan's assets each refuse."""

    def test_error_an_election_at_the_closing_instant_is_refused_as_not_open(self, api):
        """The half-open interval excludes `closes_at`, so an election at that instant is refused.

        The election must currently be in `NOTICE_SENT`; the window must be `OPEN` and the logical clock strictly before the window's `closes_at`, with either failure rejected as `ERR_WINDOW_NOT_OPEN`; the participant's `mortality_status` must be `ALIVE_CONFIRMED`, otherwise `ERR_MORTALITY_NOT_CONFIRMED`; and the participant's `benefit_audit_status` must be `PASSED_CLOSED` or `CORRECTED`, otherwise `ERR_PARTICIPANT_DATA_NOT_CLEAN` — nobody elects against an unaudited benefit figure.

        Design: Corner/errors/window_settlement_refuses_an_underfunded_plan_and_a_post_close_correction
        """
        fixtures.reset_clock(api)
        plan, participant = _lump_sum_plan_with_participant(api)
        opened = fixtures.build_open_window(
            api,
            plan["id"],
            [participant],
            "2026-08-01T00:00:00Z",
            "2026-09-15T00:00:00Z",
            lump_sum_cap_cents=5000000,
            eligibility_max_lump_sum_cents=3000000,
        )
        election = opened.election_for(participant["id"])
        assert election["election_status"] == "NOTICE_SENT"

        fixtures.set_clock(api, "2026-09-15T00:00:00Z")
        validate_error(
            api.post_election(
                election["id"],
                factories.election_payload("LUMP_SUM"),
                make_participant_headers(participant["id"]),
            ),
            ERR_WINDOW_NOT_OPEN,
        )

        after = fixtures.read_election(api, election["id"])
        assert_fields(after, election_status="NOTICE_SENT", elected_at=None)
        assert fixtures.list_windows(api, plan["id"])[0]["window_status"] == "OPEN"

    def test_error_a_window_settlement_is_refused_when_the_plan_cannot_fund_it(
        self, api, sponsor
    ):
        """A plan holding less cash than the approved total is refused with the insufficient-assets code.

        The plan must also hold enough cash, with `plan_assets_cents` at least `approved_lump_sum_total_cents`, otherwise `ERR_PLAN_ASSETS_INSUFFICIENT`.
        When the walk finishes, the running total is stored as `approved_lump_sum_total_cents`.

        Design: Corner/errors/window_settlement_refuses_an_underfunded_plan_and_a_post_close_correction
        """
        fixtures.reset_clock(api)
        plan, participant = _lump_sum_plan_with_participant(api, plan_assets_cents=2000000)
        opened = fixtures.build_open_window(
            api,
            plan["id"],
            [participant],
            "2026-08-01T00:00:00Z",
            "2026-09-15T00:00:00Z",
            lump_sum_cap_cents=5000000,
            eligibility_max_lump_sum_cents=3000000,
        )
        election = opened.election_for(participant["id"])
        elected = fixtures.elect(api, election["id"], participant["id"], "LUMP_SUM")
        expected_net = constants.net_lump_sum_cents_for(
            constants.raw_lump_sum_pv(20000, DEFERRED)
        )
        assert elected["net_lump_sum_cents"] == expected_net
        fixtures.set_clock(api, "2026-09-15T00:00:00Z")
        closed = fixtures.close_window(api, opened.window_id)
        assert closed["approved_lump_sum_total_cents"] == expected_net
        assert fixtures.read_plan(api, plan["id"])["plan_assets_cents"] < expected_net

        validate_error(
            api.post_window_settlement(opened.window_id, {}, sponsor),
            ERR_PLAN_ASSETS_INSUFFICIENT,
        )

        after = fixtures.list_windows(api, plan["id"])[0]
        assert_fields(after, window_status="CLOSED", paid_lump_sum_total_cents=0, settled_at=None)
        _rows, meta = validate_paginated(
            api.list_settlement_entries(sponsor, {"plan_id": plan["id"]})
        )
        assert meta["total_count"] == 0

    def test_error_a_post_close_correction_that_breaches_the_cap_is_refused_until_it_is_undone(
        self, api, sponsor
    ):
        """A benefit correction recorded after closing lifts the re-priced total past the cap, and restoring it lets the settlement through.

        The re-verification re-prices every election of the window still in `ELECTED_LUMP_SUM` from each participant's **current** `audited_monthly_benefit_cents`, and the resulting total must be at most `lump_sum_cap_cents`; if it is not, the settlement is rejected with `ERR_WINDOW_CAP_EXCEEDED`.
        This is not a redundant check: a benefit correction recorded after the window closed can lift an elected participant's net lump sum above the total the waterfall approved at closing.
        In the first hop, every election of the window still in `ELECTED_LUMP_SUM` transitions to `PAID`, with `paid_at` stamped from the logical clock and `paid_amount_cents` set to that election's `net_lump_sum_cents`.

        Design: Corner/errors/window_settlement_refuses_an_underfunded_plan_and_a_post_close_correction
        """
        fixtures.reset_clock(api)
        plan, participant = _lump_sum_plan_with_participant(api)
        opened = fixtures.build_open_window(
            api,
            plan["id"],
            [participant],
            "2026-08-01T00:00:00Z",
            "2026-09-15T00:00:00Z",
            lump_sum_cap_cents=5000000,
            eligibility_max_lump_sum_cents=3000000,
        )
        election = opened.election_for(participant["id"])
        elected = fixtures.elect(api, election["id"], participant["id"], "LUMP_SUM")
        expected_net = constants.net_lump_sum_cents_for(
            constants.raw_lump_sum_pv(20000, DEFERRED)
        )
        fixtures.set_clock(api, "2026-09-15T00:00:00Z")
        fixtures.close_window(api, opened.window_id)

        correcting = fixtures.open_benefit_audit(
            api,
            participant["id"],
            final_average_monthly_earnings_cents=525000,
            credited_service_months=240,
        )
        assert correcting["audit_status"] == "CORRECTION_REQUIRED"
        fixtures.resolve_audit(api, correcting["id"], "APPLY_CORRECTION")
        corrected = fixtures.read_participant(api, participant["id"])
        assert corrected["audited_monthly_benefit_cents"] == 157500
        assert (
            constants.net_lump_sum_cents_for(constants.raw_lump_sum_pv(157500, DEFERRED))
            > opened.window["lump_sum_cap_cents"]
        )

        validate_error(
            api.post_window_settlement(opened.window_id, {}, sponsor),
            ERR_WINDOW_CAP_EXCEEDED,
        )

        restoring = fixtures.open_benefit_audit(
            api,
            participant["id"],
            final_average_monthly_earnings_cents=constants.fame_for_zero_variance(20000, 240),
            credited_service_months=240,
        )
        assert restoring["audit_status"] == "PASSED"
        fixtures.resolve_audit(api, restoring["id"], "ACCEPT_AS_IS")
        assert (
            fixtures.read_participant(api, participant["id"])[
                "audited_monthly_benefit_cents"
            ]
            == 20000
        )

        settled = validate_success(api.post_window_settlement(opened.window_id, {}, sponsor))
        assert_fields(
            settled, window_status="SETTLED", paid_lump_sum_total_cents=expected_net
        )
        paid = fixtures.read_election(api, elected["id"])
        assert_fields(paid, election_status="PAID", paid_amount_cents=expected_net)
        assert (
            fixtures.read_participant(api, participant["id"])["participant_status"]
            == "SETTLED_LUMP_SUM"
        )


class TestComplaintLifecycleRefusals:
    """From filing to termination, every complaint refusal names its own code."""

    def test_error_a_participant_still_in_the_plan_cannot_file(self, api):
        """Filing is refused for an IN_PLAN participant and again once they are merely ASSIGNED.

        Filing requires the participant's `participant_status` to be `TRANSFERRED_TO_INSURER`, `SETTLED_LUMP_SUM`, or `RESIDUAL_ANNUITY_PURCHASED`; a complaint about a participant still in the plan is rejected with `ERR_PARTICIPANT_NOT_TRANSFERRED`.

        Design: Corner/errors/complaint_lifecycle_refusals_from_filing_to_termination
        """
        fixtures.reset_clock(api)
        authorized = _authorized_with_retiree(api)
        participant = authorized.participants[0]
        assert participant["participant_status"] == "IN_PLAN"

        validate_error(
            api.create_complaint(
                participant["id"],
                factories.complaint_payload("BENEFIT_AMOUNT"),
                make_participant_headers(participant["id"]),
            ),
            ERR_PARTICIPANT_NOT_TRANSFERRED,
        )

        tranche = fixtures.create_tranche(api, authorized.plan_id, RETIREE)
        fixtures.assign_participant(api, tranche["id"], participant["id"])
        assert (
            fixtures.read_participant(api, participant["id"])["participant_status"]
            == "ASSIGNED"
        )

        validate_error(
            api.create_complaint(
                participant["id"],
                factories.complaint_payload("BENEFIT_AMOUNT"),
                make_participant_headers(participant["id"]),
            ),
            ERR_PARTICIPANT_NOT_TRANSFERRED,
        )

    def test_error_a_complaint_may_only_name_a_tranche_the_participant_was_in(self, api):
        """A foreign tranche is a mismatch, while an omitted one snapshots the tranche the participant left through.

        When a `tranche_id` is supplied it must be a tranche the participant was actually assigned to, and a mismatch is rejected with `ERR_QUOTE_TRANCHE_MISMATCH`; when omitted, the complaint snapshots the participant's `tranche_id` as it stood at filing, which is null for lump-sum and residual participants.
        The `assigned_participant_count` is the size of that population, except that participants who have already moved on to `TRANSFERRED_TO_INSURER` continue to be counted as belonging to the tranche.
        A filed complaint starts in `OPEN` with `triage_count` 0, `remediation_amount_cents` 0, `reversed_amount_cents` 0, and `responsibility_determination`, `determination_rationale`, and `resolved_at` null, and receives a server-minted sequential `complaint_reference` within the plan.

        Design: Corner/errors/complaint_lifecycle_refusals_from_filing_to_termination
        """
        fixtures.reset_clock(api)
        insurer = fixtures.create_insurer(
            api, "Northwall Life Assurance", "AA", 4200, 200000000
        )
        authorized = _authorized_with_retiree(api)
        foreign = fixtures.create_tranche(api, authorized.plan_id, DEFERRED)
        settled = fixtures.build_settled_tranche(
            api,
            authorized.plan_id,
            authorized.participants,
            [fixtures.QuoteSpec(insurer["id"], PREMIUM_CENTS)],
            insurer["id"],
            CASH_GROSS_CENTS,
            transfer_mode="CASH",
            target_cohort=RETIREE,
        )
        participant = authorized.participants[0]
        headers = make_participant_headers(participant["id"])
        assert (
            fixtures.read_participant(api, participant["id"])["participant_status"]
            == "TRANSFERRED_TO_INSURER"
        )

        validate_error(
            api.create_complaint(
                participant["id"],
                factories.complaint_payload("BENEFIT_AMOUNT", tranche_id=foreign["id"]),
                headers,
            ),
            ERR_QUOTE_TRANCHE_MISMATCH,
        )

        complaint = validate_success(
            api.create_complaint(
                participant["id"], factories.complaint_payload("BENEFIT_AMOUNT"), headers
            ),
            201,
        )
        assert_fields(
            complaint,
            complaint_status="OPEN",
            triage_count=0,
            remediation_amount_cents=0,
            reversed_amount_cents=0,
            responsibility_determination=None,
            resolved_at=None,
            tranche_id=settled["id"],
        )
        assert complaint["complaint_reference"]

    def test_error_a_complaint_can_only_be_resolved_while_it_is_triaged(
        self, api, administrator
    ):
        """Resolution is refused before triage and again once the complaint is already resolved.

        The complaint must be `TRIAGED`, otherwise `ERR_COMPLAINT_NOT_TRIAGED`.
        Triage is accepted from `OPEN` and, as a re-triage, from `RESOLVED`; from any other status it is rejected with `ERR_COMPLAINT_NOT_TRIAGED`.
        A triage from `OPEN` moves the complaint `OPEN → TRIAGED`, records the determination and rationale, and increments `triage_count` by one.

        Design: Corner/errors/complaint_lifecycle_refusals_from_filing_to_termination
        """
        fixtures.reset_clock(api)
        authorized, _insurer, _tranche = _settled_buyout(api)
        participant = authorized.participants[0]
        complaint = fixtures.file_complaint(api, participant["id"], "BENEFIT_AMOUNT")
        assert complaint["complaint_status"] == "OPEN"

        validate_error(
            api.post_complaint_resolution(
                complaint["id"], factories.complaint_resolution_payload(0), administrator
            ),
            ERR_COMPLAINT_NOT_TRIAGED,
        )

        triaged = fixtures.triage_complaint(api, complaint["id"], "NO_ERROR")
        assert_fields(triaged, complaint_status="TRIAGED", triage_count=1)

        resolved = fixtures.resolve_complaint(api, complaint["id"], 0)
        assert_fields(resolved, complaint_status="RESOLVED", remediation_amount_cents=0)
        assert resolved["resolved_at"] is not None

        validate_error(
            api.post_complaint_resolution(
                complaint["id"], factories.complaint_resolution_payload(0), administrator
            ),
            ERR_COMPLAINT_NOT_TRIAGED,
        )

    def test_error_an_outstanding_complaint_blocks_the_termination_filing(self, api, sponsor):
        """The filing is refused while a complaint is OPEN and while it is TRIAGED, and admitted once it is RESOLVED.

        The plan must be in `RESIDUAL` or `FILING_DEFICIENT`, and the count of the plan's participant complaints whose `complaint_status` is `OPEN` or `TRIAGED` must be exactly 0; any outstanding complaint is rejected with `ERR_COMPLAINT_STATE_INVALID`.
        Filing moves the plan to `TERMINATION_FILED`, stores `filing_reference`, stamps `filing_submitted_at` from the logical clock, clears any `filing_deficiency_reason`, and bumps the `version`.

        Design: Corner/errors/complaint_lifecycle_refusals_from_filing_to_termination
        """
        fixtures.reset_clock(api)
        authorized, _insurer, _tranche = _settled_buyout(api)
        participant = authorized.participants[0]
        plan = fixtures.read_plan(api, authorized.plan_id)
        assert plan["plan_status"] == "RESIDUAL"
        complaint = fixtures.file_complaint(api, participant["id"], "BENEFIT_AMOUNT")
        filing = factories.termination_filing_payload()

        validate_error(
            api.post_termination_filing(plan["id"], filing, sponsor),
            ERR_COMPLAINT_STATE_INVALID,
        )

        fixtures.triage_complaint(api, complaint["id"], "NO_ERROR")
        validate_error(
            api.post_termination_filing(plan["id"], filing, sponsor),
            ERR_COMPLAINT_STATE_INVALID,
        )
        assert fixtures.read_plan(api, plan["id"])["plan_status"] == "RESIDUAL"

        fixtures.resolve_complaint(api, complaint["id"], 0)
        filed = validate_success(api.post_termination_filing(plan["id"], filing, sponsor))
        assert_fields(
            filed,
            plan_status="TERMINATION_FILED",
            filing_reference=filing["filing_reference"],
            filing_deficiency_reason=None,
        )
        assert filed["filing_submitted_at"].startswith("2026-08-01T00:00:00")
