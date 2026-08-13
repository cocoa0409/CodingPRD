"""Opportunity pipeline: evaluation scoring, the negotiation cycle band,
artist-approval gating, acceptance, conversion, expiry, and negotiation OCC."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_team_member,
    counter_offer_payload,
    create_evaluated_opportunity,
    create_negotiating_opportunity,
    create_opportunity,
    create_verified_and_settled_event,
    get_success_data,
    list_requests_for_target,
    setup_artist_team,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["firm_admin_headers"]


class TestNegotiationEvaluationCycle:
    def _setup_cycle(self, api):
        """Opportunity at exactly 10000000 (== threshold, so requires_artist_approval
        is false), evaluated and in NEGOTIATING."""
        sc = setup_artist_team(stage_name="Cycle Act")
        opp = create_opportunity(sc, proposed_value_cents=10000000, fit_score=80)
        assert opp["requires_artist_approval"] is False, (
            "The approval rule is strict >; exactly 10000000 does not require it"
        )
        get_success_data(api.evaluate_opportunity(opp["id"], sc["agent_headers"]))
        negotiated = get_success_data(api.negotiate_opportunity(opp["id"],
                                                                sc["agent_headers"]))
        return sc, opp, negotiated

    def test_exactly_ten_percent_counter_stays_negotiating(self, api):
        """PRD: "a change of at most ten percent keeps the opportunity in
        `NEGOTIATING`, while a larger change loops it back to `UNDER_EVALUATION` —
        and exactly ten percent stays in `NEGOTIATING`, because the band boundary
        is inclusive of ten percent on the stay side. Either branch writes
        `current_value_cents` to the new value, adds one to `round_number`, and
        increments the opportunity's `version`; a change that newly crosses the
        approval threshold raises the artist approval request."

        Design: Difficulty/non_linear_state_machine/opportunity_negotiation_evaluation_cycle
        """
        sc, opp, negotiated = self._setup_cycle(api)
        countered = validate_success(api.counter_offer_opportunity(
            opp["id"],
            counter_offer_payload(11000000, negotiated["version"]),
            sc["agent_headers"]))
        assert countered["status"] == "NEGOTIATING", (
            "Exactly 10% stays NEGOTIATING (inclusive boundary)"
        )
        assert countered["current_value_cents"] == 11000000
        assert countered["round_number"] == 1
        assert countered["version"] == negotiated["version"] + 1
        assert countered["requires_artist_approval"] is True

        requests = [r for r in list_requests_for_target(sc, opp["id"])
                    if r["required_approver"] == "ARTIST"]
        assert len(requests) == 1
        assert requests[0]["status"] == "PENDING"
        assert requests[0]["target_type"] == "OPPORTUNITY"
        assert requests[0]["target_id"] == opp["id"]

    def test_over_ten_percent_counter_loops_back_to_evaluation(self, api):
        """PRD: "a change of at most ten percent keeps the opportunity in
        `NEGOTIATING`, while a larger change loops it back to `UNDER_EVALUATION`"
        PRD: "evaluating an opportunity already under evaluation refreshes its
        numbers in place without changing state."

        Design: Difficulty/non_linear_state_machine/opportunity_negotiation_evaluation_cycle
        """
        sc, opp, negotiated = self._setup_cycle(api)
        after_first = validate_success(api.counter_offer_opportunity(
            opp["id"],
            counter_offer_payload(11000000, negotiated["version"]),
            sc["agent_headers"]))
        looped = validate_success(api.counter_offer_opportunity(
            opp["id"],
            counter_offer_payload(12500000, after_first["version"]),
            sc["agent_headers"]))
        assert looped["status"] == "UNDER_EVALUATION", (
            "A delta over 10% loops back to UNDER_EVALUATION"
        )
        assert looped["current_value_cents"] == 12500000
        assert looped["round_number"] == 2

        refreshed = validate_success(api.evaluate_opportunity(opp["id"],
                                                              sc["agent_headers"]))
        assert refreshed["status"] == "UNDER_EVALUATION", "Re-evaluation refreshes in place"
        assert refreshed["evaluation_score"] is not None

        renegotiated = validate_success(api.negotiate_opportunity(opp["id"],
                                                                  sc["agent_headers"]))
        assert renegotiated["status"] == "NEGOTIATING", "One full cycle completed"


class TestEngagementOpportunityGate:
    def _setup_negotiating_with_hold(self, api):
        sc = setup_artist_team(stage_name="Link Act")
        opp = create_negotiating_opportunity(
            sc, proposed_value_cents=5000000, fit_score=60,
            window=("2026-09-10T18:00:00Z", "2026-09-10T23:00:00Z"))
        hold = get_success_data(api.create_engagement(
            {
                "artist_id": sc["artist"]["id"],
                "income_type": "TOURING",
                "counterparty_name": "FestLi",
                "start_datetime": "2026-09-10T18:00:00Z",
                "end_datetime": "2026-09-10T23:00:00Z",
                "guarantee_cents": 5000000,
                "travel_buffer_hours": 0,
                "opportunity_id": opp["id"],
            },
            sc["agent_headers"]))
        return sc, opp, hold

    def test_confirm_blocked_while_opportunity_negotiating(self, api):
        """PRD: "Confirming requires the engagement to be in `HOLD`
        (`ERR_INVALID_STATE` otherwise), its `end_datetime` still in the future
        (`ERR_ENGAGEMENT_WINDOW_PAST`), and — when `opportunity_id` is set — the
        linked opportunity to be `ACCEPTED` or `CONVERTED`
        (`ERR_OPPORTUNITY_NOT_ACCEPTED`)."

        Design: Difficulty/cross_entity_state_dependency/engagement_confirm_gated_on_opportunity_accepted
        """
        sc, opp, hold = self._setup_negotiating_with_hold(api)
        assert get_success_data(api.get_opportunity(opp["id"], ADMIN))["status"] == (
            "NEGOTIATING")

        resp = api.confirm_engagement(hold["id"], sc["agent_headers"])
        validate_error(resp, ApiErrorId.ERR_OPPORTUNITY_NOT_ACCEPTED)

        after = validate_success(api.get_engagement(hold["id"], ADMIN))
        assert after["status"] == "HOLD"

    def test_confirm_succeeds_after_opportunity_accepted(self, api):
        """PRD: "when `opportunity_id` is set — the linked opportunity to be
        `ACCEPTED` or `CONVERTED` (`ERR_OPPORTUNITY_NOT_ACCEPTED`)"

        Design: Difficulty/cross_entity_state_dependency/engagement_confirm_gated_on_opportunity_accepted
        """
        sc, opp, hold = self._setup_negotiating_with_hold(api)
        accepted = validate_success(api.accept_opportunity(opp["id"],
                                                           sc["agent_headers"]))
        assert accepted["status"] == "ACCEPTED"

        confirmed = validate_success(api.confirm_engagement(hold["id"],
                                                            sc["agent_headers"]))
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["opportunity_id"] == opp["id"]


class TestOpportunityEvaluation:
    def test_opportunity_initial_state_received(self, api):
        """PRD: "The opportunity is born `RECEIVED`, with `current_value_cents`
        initialized to `proposed_value_cents` and `round_number` at 0."
        PRD: "`requires_artist_approval` is true exactly when `current_value_cents`
        exceeds 10000000 cents ($100,000)."

        Design: Corner/state_machines/opportunity_initial_state_received
        """
        sc = setup_artist_team(stage_name="Init Act", create_agreement=False,
                                   with_bm=False)
        opp = validate_success(api.create_opportunity(
            {
                "artist_id": sc["artist"]["id"],
                "income_type": "ENDORSEMENT",
                "counterparty_name": "BrandCo",
                "proposed_value_cents": 20000000,
                "offer_expiry_date": "2026-12-31",
                "proposed_window_start": "2026-10-01T00:00:00Z",
                "proposed_window_end": "2026-10-02T00:00:00Z",
                "fit_score": 90,
            },
            sc["agent_headers"]), 201)
        assert opp["status"] == "RECEIVED"
        assert opp["round_number"] == 0
        assert opp["current_value_cents"] == 20000000
        assert opp["evaluation_score"] is None, "Null until the first evaluation"
        assert opp["recommendation"] is None
        assert opp["requires_artist_approval"] is True, "20000000 > 10000000"

    def test_evaluation_score_weighted_with_empty_trailing_set(self, api):
        """PRD: "When no such events exist the average is null and the financial
        component defaults to a neutral 50"
        PRD: "The final score is 0.5 times the financial component plus 0.3 times
        `fit_score` plus 0.2 times the availability component, rounded half up to
        an integer at this final weighted step only. A score of at least 70
        recommends `PURSUE`; a score of at least 40 recommends `CONSIDER`"

        Design: Corner/calculations/evaluation_score_weighted_with_empty_trailing_set
        """
        sc = setup_artist_team(stage_name="Score Act", with_bm=False)
        opp1 = create_opportunity(sc, proposed_value_cents=5000000, fit_score=80)
        opp2 = create_opportunity(sc, proposed_value_cents=5000000, fit_score=100,
                                  counterparty_name="FestB",
                                  window=("2026-11-01T00:00:00Z",
                                          "2026-11-02T00:00:00Z"))

        evaluated1 = validate_success(api.evaluate_opportunity(opp1["id"],
                                                               sc["agent_headers"]))
        assert evaluated1["evaluation_score"] == 69, "0.5*50 + 0.3*80 + 0.2*100"
        assert evaluated1["recommendation"] == "CONSIDER"

        evaluated2 = validate_success(api.evaluate_opportunity(opp2["id"],
                                                               sc["agent_headers"]))
        assert evaluated2["evaluation_score"] == 75, "0.5*50 + 0.3*100 + 0.2*100"
        assert evaluated2["recommendation"] == "PURSUE", "Threshold 70 is >="

    def test_trailing_average_feeds_financial_component_with_rounding(self, api):
        """PRD: "the trailing window is the 365 days ending on the clock date,
        inclusive of both ends, taken over the artist's income events of that
        income type in `SETTLED` or `POSTED` status with `received_date` inside
        the window — verified-but-unsettled events do not count."
        PRD: "otherwise the component is the smaller of 100 and 50 times
        `current_value_cents` divided by that average, with the average computed
        as the sum of `received_amount_cents` over the count, rounded half up, and
        the component's division also rounded half up."

        Design: Corner/calculations/trailing_average_feeds_financial_component_with_rounding
        """
        sc = setup_artist_team(stage_name="Avg Act")
        create_verified_and_settled_event(sc, gross_amount_cents=200000,
                                          recognition_date="2026-02-20",
                                          received_date="2026-03-01",
                                          source_name="PA1")
        create_verified_and_settled_event(sc, gross_amount_cents=400000,
                                          recognition_date="2026-03-20",
                                          received_date="2026-04-01",
                                          source_name="PA2")
        opp = create_opportunity(sc, proposed_value_cents=450000, fit_score=100,
                                 counterparty_name="FestC",
                                 window=("2027-01-05T00:00:00Z",
                                         "2027-01-06T00:00:00Z"))

        evaluated = validate_success(api.evaluate_opportunity(opp["id"],
                                                              sc["agent_headers"]))
        # Trailing average (200000 + 400000) / 2 = 300000; financial component
        # min(100, round_half_up(50 * 450000 / 300000)) = 75; score 87.5 -> 88.
        assert evaluated["evaluation_score"] == 88
        assert evaluated["recommendation"] == "PURSUE"


class TestAcceptanceAndConversion:
    def test_accept_high_value_opportunity_requires_artist_approval(self, api):
        """PRD: "Acceptance, by an `Agent`, is allowed from `UNDER_EVALUATION` or
        `NEGOTIATING` and requires three things: a prior evaluation
        (`evaluation_score` must not be null — accepting unevaluated is rejected
        with `ERR_INVALID_STATE`), an unexpired offer (`ERR_OFFER_EXPIRED`), and,
        when `requires_artist_approval` is true, an existing `APPROVED` approval
        request from the artist (`ERR_ARTIST_APPROVAL_REQUIRED`)."

        Design: Corner/validations/accept_high_value_opportunity_requires_artist_approval
        """
        sc = setup_artist_team(stage_name="Big Act",
                                   income_types=("ENDORSEMENT",), with_bm=False)
        opp = create_opportunity(sc, proposed_value_cents=20000000,
                                 income_type="ENDORSEMENT",
                                 counterparty_name="MegaBrand", fit_score=90)
        get_success_data(api.evaluate_opportunity(opp["id"], sc["agent_headers"]))
        get_success_data(api.negotiate_opportunity(opp["id"], sc["agent_headers"]))

        requests = [r for r in list_requests_for_target(sc, opp["id"])
                    if r["required_approver"] == "ARTIST"]
        assert len(requests) == 1
        artist_request = requests[0]

        resp = api.accept_opportunity(opp["id"], sc["agent_headers"])
        validate_error(resp, ApiErrorId.ERR_ARTIST_APPROVAL_REQUIRED)

        get_success_data(api.approve_request(artist_request["id"],
                                             sc["artist_headers"],
                                             decision_note="worth it"))
        accepted = validate_success(api.accept_opportunity(opp["id"],
                                                           sc["agent_headers"]))
        assert accepted["status"] == "ACCEPTED"

    def test_negotiate_expired_offer_rejected(self, api):
        """PRD: "Opening negotiation moves `UNDER_EVALUATION → NEGOTIATING` and
        requires the offer not to have lapsed — the clock date must be on or
        before `offer_expiry_date`, or the request fails with
        `ERR_OFFER_EXPIRED`."

        Design: Corner/validations/negotiate_expired_offer_rejected
        """
        sc = setup_artist_team(stage_name="Late Off", create_agreement=False,
                                   with_bm=False)
        opp = create_opportunity(sc, offer_expiry_date="2026-07-01")
        get_success_data(api.evaluate_opportunity(opp["id"], sc["agent_headers"]))

        resp = api.negotiate_opportunity(opp["id"], sc["agent_headers"])
        validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED)

        after = validate_success(api.get_opportunity(opp["id"], ADMIN))
        assert after["status"] == "UNDER_EVALUATION"

    def test_convert_creates_confirmed_engagement_from_accepted(self, api):
        """PRD: "Conversion creates the engagement with the proposed window, a
        `travel_buffer_hours` of 24, `guarantee_cents` equal to the negotiated
        `current_value_cents`, `opportunity_id` pointing back at the opportunity,
        and `confirmed_at` stamped from the clock; the opportunity records the
        result in `converted_engagement_id` and moves to `CONVERTED`."
        PRD: "At startup the clock reads exactly 2026-08-01T00:00:00Z."

        Design: Corner/endpoints/convert_creates_confirmed_engagement_from_accepted
        """
        sc = setup_artist_team(stage_name="Conv Act", with_bm=False)
        opp = create_evaluated_opportunity(sc, proposed_value_cents=5000000,
                                           fit_score=70)
        accepted = validate_success(api.accept_opportunity(opp["id"],
                                                           sc["agent_headers"]))
        assert accepted["status"] == "ACCEPTED"

        engagement = validate_success(api.convert_opportunity(opp["id"],
                                                              sc["agent_headers"]), 201)
        assert engagement["status"] == "CONFIRMED"
        assert engagement["guarantee_cents"] == 5000000
        assert engagement["travel_buffer_hours"] == 24
        assert engagement["opportunity_id"] == opp["id"]
        assert engagement["start_datetime"] == "2026-10-01T00:00:00Z"
        assert engagement["end_datetime"] == "2026-10-02T00:00:00Z"
        assert engagement["confirmed_at"].startswith("2026-08-01T00:00:00"), (
            "confirmed_at is stamped from the fixed startup logical clock"
        )

        after = validate_success(api.get_opportunity(opp["id"], ADMIN))
        assert after["status"] == "CONVERTED"
        assert after["converted_engagement_id"] == engagement["id"]

    def test_occ_counter_offer_rejects_stale_opportunity_version(self, api):
        """PRD: "Recording a counter-offer (`POST /opportunities/{id}/counter-offer`)
        requires `expected_opportunity_version`, compared against the
        opportunity's current `version`; a mismatch is rejected with
        `ERR_STALE_OPPORTUNITY_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_counter_offer_rejects_stale_opportunity_version
        """
        sc = setup_artist_team(stage_name="Neg Act", with_bm=False)
        opp = create_negotiating_opportunity(sc, proposed_value_cents=1000000)
        stale_version = opp["version"]

        first = validate_success(api.counter_offer_opportunity(
            opp["id"], counter_offer_payload(1050000, stale_version),
            sc["agent_headers"]))
        assert first["status"] == "NEGOTIATING", "Delta 5% stays NEGOTIATING"
        assert first["round_number"] == 1

        resp = api.counter_offer_opportunity(
            opp["id"], counter_offer_payload(1030000, stale_version),
            sc["agent_headers"])
        validate_error(resp, ApiErrorId.ERR_STALE_OPPORTUNITY_VERSION)

        after = validate_success(api.get_opportunity(opp["id"], ADMIN))
        assert after["current_value_cents"] == 1050000, "The stale write changed nothing"
        assert after["round_number"] == 1
