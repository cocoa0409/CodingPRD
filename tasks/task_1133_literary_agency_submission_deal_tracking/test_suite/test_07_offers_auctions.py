"""Offers, auction ranking variants, the award cascade, segregation of duties,
and the negotiate/revise loop."""
from test_helpers import (
    ApiErrorId,
    create_editor,
    create_round,
    make_agent_headers,
    make_contracts_manager_headers,
    open_round,
    queue_submission,
    record_offer,
    revise_offer_payload,
    send_submission,
    setup_signed_pipeline,
    validate_error,
    validate_paginated,
    validate_success,
)

# Offer A terms: advance 2,600,000, fractions summing to 0.20, one demanded right.
OFFER_A = dict(advance_cents=2600000, pct_hardcover=0.10, pct_trade=0.05,
               pct_ebook=0.05, includes_film_rights=True)
# Offer B terms: advance 200,000, fractions summing to 0.10, no demanded rights.
OFFER_B = dict(advance_cents=200000, pct_hardcover=0.05, pct_trade=0.025, pct_ebook=0.025)


def _setup_two_editor_round(auction_mode=False, valuation_mode=None, name="Agency AC"):
    """Signed pipeline + round (optionally auction) + two SENT submissions."""
    ctx = setup_signed_pipeline(agency_name=name)
    agent_id = ctx["agent"]["id"]
    ed1 = create_editor(ctx["agency"]["id"], display_name="Ed A")
    ed2 = create_editor(ctx["agency"]["id"], display_name="Ed B", imprint="Imprint B")
    round_data = create_round(
        ctx["manuscript"]["id"], agent_id,
        auction_mode=auction_mode, valuation_mode=valuation_mode,
    )
    s1 = queue_submission(round_data["id"], ed1["id"], agent_id)
    s2 = queue_submission(round_data["id"], ed2["id"], agent_id)
    open_round(round_data, agent_id)
    s1 = send_submission(s1["id"], agent_id)
    s2 = send_submission(s2["id"], agent_id)
    ctx.update({"round": round_data, "s1": s1, "s2": s2, "ed1": ed1, "ed2": ed2})
    return ctx


def _rank(api, offer_id, agent_id):
    return validate_success(api.get_offer(offer_id, make_agent_headers(agent_id)), 200)["auction_rank"]


class TestAuctionRankingVariants:
    def test_frontlist_ranks_low_advance_no_rights_first(self, api):
        """PRD 3.6: "Identical offers can therefore rank differently by mode: consider offer A with advance 2,600,000, royalty fractions summing to 0.20, and one demanded right, against offer B with advance 200,000, fractions summing to 0.10, and no demanded rights — under `FRONTLIST`, B ranks first (210,000 beats 120,000), while under `BACKLIST`, A ranks first (1,612,000 beats 206,000)."

        Design: Difficulty/dual_variant_calc/auction_ranking_frontlist_vs_backlist_rank_flip
        """
        ctx = _setup_two_editor_round(auction_mode=True, valuation_mode="FRONTLIST",
                                      name="Agency AR")
        agent_id = ctx["agent"]["id"]
        offer_a = record_offer(ctx["s1"]["id"], agent_id, **OFFER_A)
        offer_b = record_offer(ctx["s2"]["id"], agent_id, **OFFER_B)

        assert _rank(api, offer_b["id"], agent_id) == 1, "frontlist: 210,000 beats 120,000"
        assert _rank(api, offer_a["id"], agent_id) == 2

    def test_backlist_flips_rank_on_identical_terms(self, api):
        """PRD 3.6: "Identical offers can therefore rank differently by mode: consider offer A with advance 2,600,000, royalty fractions summing to 0.20, and one demanded right, against offer B with advance 200,000, fractions summing to 0.10, and no demanded rights — under `FRONTLIST`, B ranks first (210,000 beats 120,000), while under `BACKLIST`, A ranks first (1,612,000 beats 206,000)."

        Design: Difficulty/dual_variant_calc/auction_ranking_frontlist_vs_backlist_rank_flip
        """
        ctx = _setup_two_editor_round(auction_mode=True, valuation_mode="BACKLIST",
                                      name="Agency AR")
        agent_id = ctx["agent"]["id"]
        offer_a = record_offer(ctx["s1"]["id"], agent_id, **OFFER_A)
        offer_b = record_offer(ctx["s2"]["id"], agent_id, **OFFER_B)

        assert _rank(api, offer_a["id"], agent_id) == 1, "backlist: 1,612,000 beats 206,000"
        assert _rank(api, offer_b["id"], agent_id) == 2

    def test_auction_tie_break_created_at_ascending(self, api):
        """PRD 3.6: "Each offer's value in cents is its `advance_cents`, plus a royalty weight in cents multiplied by the sum of its three royalty fractions, minus a rights penalty in cents multiplied by the count of rights flags the publisher demands."
        PRD 3.6: "Offers sort by value descending, ties broken by earlier `created_at`."

        Design: Corner/calculations/auction_tie_break_created_at_ascending
        """
        ctx = _setup_two_editor_round(auction_mode=True, valuation_mode="FRONTLIST",
                                      name="Agency AT")
        agent_id = ctx["agent"]["id"]
        terms = dict(advance_cents=100000, pct_hardcover=0.20, pct_trade=0.13, pct_ebook=0.10)
        offer_first = record_offer(ctx["s1"]["id"], agent_id, **terms)
        offer_second = record_offer(ctx["s2"]["id"], agent_id, **terms)

        assert _rank(api, offer_first["id"], agent_id) == 1, (
            "identical values tie; the earlier-created offer wins rank 1"
        )
        assert _rank(api, offer_second["id"], agent_id) == 2


class TestAwardCascade:
    def _setup_two_live_offers(self, name="Agency AC"):
        ctx = _setup_two_editor_round(name=name)
        agent_id = ctx["agent"]["id"]
        o1 = record_offer(ctx["s1"]["id"], agent_id, advance_cents=300000)
        o2 = record_offer(ctx["s2"]["id"], agent_id, advance_cents=250000)
        ctx.update({"o1": o1, "o2": o2})
        return ctx

    def test_accept_supersedes_losing_offer(self, api):
        """PRD 3.6: "The second counted link supersedes the losers: every other offer in the round sitting in `RECEIVED` or `UNDER_NEGOTIATION` moves to `SUPERSEDED`, and each superseded offer's submission — still `OFFER_EXTENDED` — cascades to `PASSED`."

        Design: Difficulty/transitive_cascade/offer_accept_award_cascade_supersede_then_pass
        """
        ctx = self._setup_two_live_offers()
        accepted = validate_success(
            api.accept_offer(ctx["o1"]["id"], make_contracts_manager_headers("cm-1")), 200
        )
        assert accepted["status"] == "ACCEPTED"

        loser = validate_success(
            api.get_offer(ctx["o2"]["id"], make_agent_headers(ctx["agent"]["id"])), 200
        )
        assert loser["status"] == "SUPERSEDED", (
            "the accept must cause the losing offer's supersession"
        )

    def test_superseded_offer_passes_its_submission_winner_stays_extended(self, api):
        """PRD 3.6: "each superseded offer's submission — still `OFFER_EXTENDED` — cascades to `PASSED`."
        PRD 3.7: "A successful execution stamps `executed_period_index` with the current `period_index`, increments the deal's `version` by one, moves the winning submission — still `OFFER_EXTENDED` — to `WITHDRAWN`, and cuts the advance payment schedule."

        Design: Difficulty/transitive_cascade/offer_accept_award_cascade_supersede_then_pass
        """
        ctx = self._setup_two_live_offers()
        validate_success(
            api.accept_offer(ctx["o1"]["id"], make_contracts_manager_headers("cm-1")), 200
        )

        loser_sub = validate_success(
            api.get_submission(ctx["s2"]["id"], make_agent_headers(ctx["agent"]["id"])), 200
        )
        assert loser_sub["status"] == "PASSED", (
            "the loser's submission is passed by the supersession, not by the accept directly"
        )
        winner_sub = validate_success(
            api.get_submission(ctx["s1"]["id"], make_agent_headers(ctx["agent"]["id"])), 200
        )
        assert winner_sub["status"] == "OFFER_EXTENDED", (
            "the winner's submission waits OFFER_EXTENDED until deal execution"
        )


class TestSegregationOfDuties:
    def test_sod_beats_auction_rank_constraint(self, api):
        """PRD 2.9: "Every request is validated against an ordered pipeline; the first failing check determines the error response, so an earlier failure masks later ones."
        PRD 3.6: "the acting `X-User-ID` must differ from the parent round's `agent_id`, on pain of `ERR_SEGREGATION_OF_DUTIES`, because the agent who ran the round may not also award it."
        PRD 3.6: "In an auction-mode round only the offer currently ranked `auction_rank` 1 among live offers may be accepted; any other acceptance fails with `ERR_NOT_TOP_RANKED_OFFER`."

        Design: Difficulty/priority_pair_validation_conflict/offer_accept_sod_beats_auction_rank_constraint
        """
        ctx = _setup_two_editor_round(auction_mode=True, valuation_mode="FRONTLIST",
                                      name="Agency P2")
        agent_id = ctx["agent"]["id"]
        offer_a = record_offer(ctx["s1"]["id"], agent_id, **OFFER_A)
        record_offer(ctx["s2"]["id"], agent_id, **OFFER_B)

        # Accept the rank-2 offer while authenticated with the round agent's id.
        resp = api.accept_offer(offer_a["id"], make_contracts_manager_headers(agent_id))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_sod_rejection_leaves_offer_and_round_untouched(self, api):
        """PRD 3.6: "the acting `X-User-ID` must differ from the parent round's `agent_id`, on pain of `ERR_SEGREGATION_OF_DUTIES`, because the agent who ran the round may not also award it."
        PRD 3.6: "Acceptance (`RECEIVED` or `UNDER_NEGOTIATION` → `ACCEPTED`) fires the award cascade. Its first counted link creates the `Deal` in `NEGOTIATING` status"

        Design: Difficulty/priority_pair_validation_conflict/offer_accept_sod_beats_auction_rank_constraint
        """
        ctx = _setup_two_editor_round(auction_mode=True, valuation_mode="FRONTLIST",
                                      name="Agency P2")
        agent_id = ctx["agent"]["id"]
        offer_a = record_offer(ctx["s1"]["id"], agent_id, **OFFER_A)
        record_offer(ctx["s2"]["id"], agent_id, **OFFER_B)

        resp = api.accept_offer(offer_a["id"], make_contracts_manager_headers(agent_id))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

        offer_now = validate_success(
            api.get_offer(offer_a["id"], make_agent_headers(agent_id)), 200
        )
        assert offer_now["status"] == "RECEIVED", "a rejected accept must not move the offer"
        deals, _meta = validate_paginated(
            api.list_deals(make_contracts_manager_headers("cm-9"),
                           params={"offer_id": offer_a["id"]})
        )
        assert deals == [], "no deal may be created by a rejected accept"

    def test_accept_lower_ranked_offer_in_auction_rejected(self, api):
        """PRD 3.6: "In an auction-mode round only the offer currently ranked `auction_rank` 1 among live offers may be accepted; any other acceptance fails with `ERR_NOT_TOP_RANKED_OFFER`."

        Design: Corner/validations/accept_lower_ranked_offer_in_auction_rejected
        """
        ctx = _setup_two_editor_round(auction_mode=True, valuation_mode="FRONTLIST",
                                      name="Agency NR")
        agent_id = ctx["agent"]["id"]
        offer_a = record_offer(ctx["s1"]["id"], agent_id, **OFFER_A)
        record_offer(ctx["s2"]["id"], agent_id, **OFFER_B)

        # cm-9 differs from the round's agent_id, so only the rank gate can fire.
        resp = api.accept_offer(offer_a["id"], make_contracts_manager_headers("cm-9"))
        validate_error(resp, ApiErrorId.ERR_NOT_TOP_RANKED_OFFER.value)

        offer_now = validate_success(
            api.get_offer(offer_a["id"], make_agent_headers(agent_id)), 200
        )
        assert offer_now["status"] == "RECEIVED"

    def test_agent_cannot_accept_offer_forbidden(self, api):
        """PRD 2.1: "Each endpoint admits a defined subset of these roles (see §4); a caller whose role is not admitted is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
        PRD 3.6: "Accepting an offer — the exclusive power of a `ContractsManager`"

        Design: Corner/validations/agent_cannot_accept_offer_forbidden
        """
        ctx = _setup_two_editor_round(name="Agency FB")
        agent_id = ctx["agent"]["id"]
        offer = record_offer(ctx["s1"]["id"], agent_id, advance_cents=300000)

        resp = api.accept_offer(offer["id"], make_agent_headers(agent_id))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)

        offer_now = validate_success(
            api.get_offer(offer["id"], make_agent_headers(agent_id)), 200
        )
        assert offer_now["status"] == "RECEIVED"


class TestNegotiateReviseRoundtrip:
    def _setup_negotiation_pair(self):
        ctx = _setup_two_editor_round(auction_mode=True, name="Agency C2")
        agent_id = ctx["agent"]["id"]
        o1 = record_offer(ctx["s1"]["id"], agent_id, advance_cents=300000)
        o2 = record_offer(ctx["s2"]["id"], agent_id, advance_cents=250000)
        ctx.update({"o1": o1, "o2": o2})
        return ctx

    def test_negotiate_then_revise_restores_received_with_new_terms(self, api):
        """PRD 3.6: "Negotiation is a loop. Opening negotiation moves the offer from `RECEIVED` to `UNDER_NEGOTIATION`; when the editor returns revised terms, the agent records them, which moves the offer from `UNDER_NEGOTIATION` back to `RECEIVED` and overwrites `advance_cents`, the three royalty fractions, `royalty_basis`, and the three rights flags from the payload"

        Design: Difficulty/compensating_invariant/negotiate_revise_roundtrip_conserves_live_offer_set
        """
        ctx = self._setup_negotiation_pair()
        agent_id = ctx["agent"]["id"]

        mid = validate_success(
            api.negotiate_offer(ctx["o1"]["id"], make_agent_headers(agent_id)), 200
        )
        assert mid["status"] == "UNDER_NEGOTIATION"

        revised = validate_success(
            api.revise_offer(
                ctx["o1"]["id"],
                revise_offer_payload(advance_cents=320000),
                make_agent_headers(agent_id),
            ),
            200,
        )
        assert revised["status"] == "RECEIVED"
        assert revised["advance_cents"] == 320000, "the revised terms must be persisted"

    def test_roundtrip_conserves_live_offer_set_and_submission_states(self, api):
        """PRD 3.6: "Auction ranking, when `auction_mode` is true, assigns every live offer — those in `RECEIVED` or `UNDER_NEGOTIATION` — a 1-based, gapless `auction_rank`, recomputed whenever an offer is created, revised, or leaves the live set through acceptance, supersession, decline, or withdrawal."
        PRD 3.6: "recording the offer flips that submission to `OFFER_EXTENDED`"

        Design: Difficulty/compensating_invariant/negotiate_revise_roundtrip_conserves_live_offer_set
        """
        ctx = self._setup_negotiation_pair()
        agent_id = ctx["agent"]["id"]

        validate_success(api.negotiate_offer(ctx["o1"]["id"], make_agent_headers(agent_id)), 200)
        validate_success(
            api.revise_offer(
                ctx["o1"]["id"],
                revise_offer_payload(advance_cents=320000),
                make_agent_headers(agent_id),
            ),
            200,
        )

        offers, _meta = validate_paginated(
            api.list_offers(make_agent_headers(agent_id),
                            params={"agency_id": ctx["agency"]["id"]})
        )
        live = [o for o in offers if o["status"] in ("RECEIVED", "UNDER_NEGOTIATION")]
        assert len(live) == 2, "the negotiate/revise pair must conserve the live-offer count"

        sibling = validate_success(
            api.get_offer(ctx["o2"]["id"], make_agent_headers(agent_id)), 200
        )
        assert sibling["status"] == "RECEIVED", "the sibling offer is untouched by the pair"

        s1_now = validate_success(
            api.get_submission(ctx["s1"]["id"], make_agent_headers(agent_id)), 200
        )
        s2_now = validate_success(
            api.get_submission(ctx["s2"]["id"], make_agent_headers(agent_id)), 200
        )
        assert s1_now["status"] == "OFFER_EXTENDED"
        assert s2_now["status"] == "OFFER_EXTENDED"
