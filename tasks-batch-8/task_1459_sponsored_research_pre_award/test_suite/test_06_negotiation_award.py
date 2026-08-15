"""Negotiation rounds, offer resolution, and the award cascade (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    assert_negotiation_offer,
    create_offer_payload,
    get_proposal,
    get_success_data,
    get_version,
    make_context,
    make_negotiating_proposal,
    make_proposal,
    make_submitted_proposal,
    reset_clock,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]


class TestNegotiationSupersedeCycle:
    def _setup(self, api):
        reset_clock()
        return make_submitted_proposal(idempotency_key="sub-neg-1")

    def test_rounds_supersede_open_offer(self, api):
        """PRD §3.8: "at most one offer per proposal may be `PROPOSED` at a time,
        so opening a new round voids any prior `PROPOSED` offer on the same
        proposal — supersession, recorded as `VOIDED`."

        Design: Difficulty/non_linear_state_machine/negotiation_round_supersede_cycle
        """
        env = self._setup(api)
        prop_id = env["proposal"]["id"]
        o1 = validate_success(
            api.create_negotiation_offer(
                prop_id,
                create_offer_payload(get_version(prop_id),
                                     offered_total_cents=14_000_000),
                DIRECTOR,
            ),
            201,
        )
        o2 = validate_success(
            api.create_negotiation_offer(
                prop_id,
                create_offer_payload(get_version(prop_id), origin="INSTITUTION",
                                     offered_total_cents=14_800_000),
                DIRECTOR,
            ),
            201,
        )
        o3 = validate_success(
            api.create_negotiation_offer(
                prop_id,
                create_offer_payload(get_version(prop_id),
                                     offered_total_cents=14_600_000),
                DIRECTOR,
            ),
            201,
        )
        offers = get_success_data(api.list_negotiation_offers(prop_id, DIRECTOR))
        by_id = {o["id"]: o for o in offers}
        assert by_id[o1["id"]]["status"] == "VOIDED"
        assert by_id[o2["id"]]["status"] == "VOIDED"
        assert by_id[o3["id"]]["status"] == "PROPOSED"
        # proposal stayed NEGOTIATING as rounds accumulated
        assert get_proposal(prop_id)["status"] == "NEGOTIATING"

    def test_round_index_ascends_per_proposal(self, api):
        """PRD §3.8: "Each **NegotiationOffer** receives a per-proposal
        `round_index` ascending from 1 and starts `PROPOSED`".

        Design: Difficulty/non_linear_state_machine/negotiation_round_supersede_cycle
        """
        env = self._setup(api)
        prop_id = env["proposal"]["id"]
        rounds = []
        for amount in (14_000_000, 14_800_000, 14_600_000):
            offer = validate_success(
                api.create_negotiation_offer(
                    prop_id,
                    create_offer_payload(get_version(prop_id),
                                         offered_total_cents=amount),
                    DIRECTOR,
                ),
                201,
            )
            assert_negotiation_offer(offer)
            rounds.append(offer["round_index"])
        assert rounds == [1, 2, 3]


class TestOfferAcceptCascade:
    def _setup(self, api):
        reset_clock()
        return make_negotiating_proposal(offered_total_cents=14_000_000)

    def test_accept_moves_offer_and_proposal(self, api):
        """PRD §3.8: "Acceptance moves the offer to `ACCEPTED`, the proposal to
        `AWARDED`, records the accepted amount as the proposal's
        `awarded_total_cents` taken from `offered_total_cents`".

        Design: Difficulty/transitive_cascade/award_accept_cascade_creates_handoff
        """
        env = self._setup(api)
        prop_id = env["proposal"]["id"]
        # No handoff exists before the award
        before = get_success_data(api.list_award_handoffs(prop_id, DIRECTOR))
        assert before == []
        accepted = validate_success(
            api.accept_negotiation_offer(env["offer"]["id"], DIRECTOR), 200
        )
        assert accepted["status"] == "ACCEPTED"
        prop = get_proposal(prop_id)
        assert prop["status"] == "AWARDED"
        assert prop["awarded_total_cents"] == 14_000_000

    def test_accept_auto_creates_draft_handoff(self, api):
        """PRD §3.8: "— because an award demands setup — automatically creates
        the proposal's one and only **AwardHandoff**, starting `DRAFT` with
        `budget_verified`, `compliance_verified`, and `subrecipient_verified` all
        false and `final_indirect_cents`, `final_total_cents`, and `handoff_at`
        all null."

        Design: Difficulty/transitive_cascade/award_accept_cascade_creates_handoff
        """
        env = self._setup(api)
        prop_id = env["proposal"]["id"]
        api.accept_negotiation_offer(env["offer"]["id"], DIRECTOR)
        handoffs = get_success_data(api.list_award_handoffs(prop_id, DIRECTOR))
        assert len(handoffs) == 1
        handoff = handoffs[0]
        assert handoff["status"] == "DRAFT"
        assert handoff["budget_verified"] is False
        assert handoff["compliance_verified"] is False
        assert handoff["subrecipient_verified"] is False


class TestOfferDecline:
    def test_decline_drives_proposal_terminal(self, api):
        """PRD §3.8: "Declining requires the same `PROPOSED` offer state, moves
        the offer to `DECLINED`, and moves the proposal to `DECLINED` with the
        terminal cleanup cascade described below".

        Design: Corner/state_machines/offer_decline_terminal_declined
        """
        reset_clock()
        env = make_negotiating_proposal()
        declined = validate_success(
            api.decline_negotiation_offer(env["offer"]["id"], DIRECTOR), 200
        )
        assert declined["status"] == "DECLINED"
        assert get_proposal(env["proposal"]["id"])["status"] == "DECLINED"

    def test_new_offer_after_decline_rejected(self, api):
        """PRD §3.8: "An `OSPDirector` opens a round on a proposal in
        `SUBMITTED`, `JIT_REQUESTED`, or `NEGOTIATING` — any other status is
        `ERR_PROPOSAL_INVALID_STATE`".

        Design: Corner/state_machines/offer_decline_terminal_declined
        """
        reset_clock()
        env = make_negotiating_proposal()
        prop_id = env["proposal"]["id"]
        api.decline_negotiation_offer(env["offer"]["id"], DIRECTOR)
        resp = api.create_negotiation_offer(
            prop_id,
            create_offer_payload(get_version(prop_id),
                                 offered_total_cents=14_500_000),
            DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_PROPOSAL_INVALID_STATE.value)

    def test_accept_accepted_offer_rejected(self, api):
        """PRD §3.8: "Accepting — again an `OSPDirector` action — requires the
        offer to be `PROPOSED` (else `ERR_OFFER_INVALID_STATE`, 409)".

        Design: Corner/errors/accept_accepted_offer_rejected
        """
        reset_clock()
        env = make_negotiating_proposal()
        api.accept_negotiation_offer(env["offer"]["id"], DIRECTOR)
        resp = api.accept_negotiation_offer(env["offer"]["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_OFFER_INVALID_STATE.value)


class TestJitLifecycle:
    def test_jit_notice_and_response(self, api):
        """PRD §3.8: "Recording a JIT notice — an `OSPDirector` action carrying a
        `sponsor_reference` and an optional `due_in_days` that defaults to 14 —
        moves a `SUBMITTED` proposal to `JIT_REQUESTED` and sets `jit_due_at` to
        the notice's clock time plus the given number of days ... Recording the
        JIT response, again with a `sponsor_reference`, returns a `JIT_REQUESTED`
        proposal to `SUBMITTED`."

        Design: Corner/endpoints/jit_notice_and_response_happy_path
        """
        reset_clock()
        env = make_submitted_proposal(idempotency_key="sub-jit-1")
        prop_id = env["proposal"]["id"]
        noticed = validate_success(
            api.create_jit_notice(
                prop_id, {"sponsor_reference": "NIH-JIT-1", "due_in_days": 14},
                DIRECTOR,
            ),
            200,
        )
        assert noticed["status"] == "JIT_REQUESTED"
        # clock pinned at 2026-08-01T00:00:00Z + 14 days
        assert noticed["jit_due_at"] == "2026-08-15T00:00:00Z"
        responded = validate_success(
            api.create_jit_response(
                prop_id, {"sponsor_reference": "NIH-JIT-1"}, DIRECTOR
            ),
            200,
        )
        assert responded["status"] == "SUBMITTED"

    def test_jit_notice_from_draft_rejected(self, api):
        """PRD §3.8: "moves a `SUBMITTED` proposal to `JIT_REQUESTED` ... from
        any other status it is `ERR_PROPOSAL_INVALID_STATE`."

        Design: Corner/validations/jit_notices_from_draft_rejected
        """
        from test_helpers import make_context, make_proposal
        ctx = make_context()
        prop = make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], title="JIT",
                             pi_effort_pct=10.00, fa_base_type="MTDC")
        resp = api.create_jit_notice(
            prop["id"], {"sponsor_reference": "NIH-JIT-9"}, DIRECTOR
        )
        validate_error(resp, ApiErrorId.ERR_PROPOSAL_INVALID_STATE.value)
