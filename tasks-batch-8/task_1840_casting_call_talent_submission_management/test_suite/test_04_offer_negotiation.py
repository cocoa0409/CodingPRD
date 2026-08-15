"""Offer negotiation: counter rounds, liveness/expiry disciplines, OCC, terms
validation, and gate ordering on acceptance (PRD sections 2.7, 3.7, 3.8)."""
from test_helpers import (
    ApiErrorId,
    counter_offer,
    create_counter_payload,
    create_offer_payload,
    make_agent_headers,
    setup_callback_completed,
    setup_minor_pipeline,
    setup_offer_pending,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]


class TestNegotiationRounds:
    def test_counter_chain_links_rounds(self, api):
        """PRD section 3.7: "A successful counter does not mutate the live offer's
        terms in place; it supersedes it. The live offer's status becomes
        `COUNTERED`, and a brand-new offer row is created with a `round_number`
        one higher than its parent's, a `parent_offer_id` pointing at the
        superseded offer, terms taken from the counter payload, and status
        `EXTENDED`."

        Design: Difficulty/non_linear_state_machine/offer_cyclic_negotiation_rounds
        """
        ctx = setup_offer_pending(agent=True)
        agent_id = ctx["agent"]["id"]
        offer_r1 = ctx["offer"]
        # Agent counters round 1 (talent side), creating round 2.
        offer_r2 = counter_offer(
            offer_r1,
            as_agent_id=agent_id,
            weekly_rate_cents=1_200_000,
            guarantee_cents=900_000,
            expires_at="2026-08-21T00:00:00Z",
        )
        # Office counters round 2, creating round 3.
        offer_r3 = counter_offer(
            offer_r2,
            weekly_rate_cents=1_100_000,
            guarantee_cents=850_000,
            expires_at="2026-08-22T00:00:00Z",
        )
        r1_after = validate_success(api.get_offer(offer_r1["id"], DIRECTOR))
        assert r1_after["status"] == "COUNTERED", "superseded round 1 becomes COUNTERED"
        assert offer_r2["round_number"] == 2, "round_number is one higher than its parent's"
        assert offer_r3["round_number"] == 3
        assert offer_r3["parent_offer_id"] == offer_r2["id"], "parent_offer_id points at the superseded offer"
        assert offer_r2["parent_offer_id"] == offer_r1["id"]
        assert offer_r3["status"] == "EXTENDED", "the new round is the live EXTENDED offer"
        assert offer_r3["weekly_rate_cents"] == 1_100_000, "terms come from the counter payload"

    def test_full_negotiation_history_remains_listable(self, api):
        """PRD section 3.7: "Because each counter creates the next round, the full
        negotiation history remains listable across all rounds."
        PRD section 4: "| GET | `/casting/submissions/{id}/offers` | List offers
        of a submission, all rounds | CastingDirector, CastingAssociate,
        ProductionCoordinator, Agent |".

        Design: Difficulty/non_linear_state_machine/offer_cyclic_negotiation_rounds
        """
        ctx = setup_offer_pending(agent=True)
        offer_r1 = ctx["offer"]
        offer_r2 = counter_offer(offer_r1, as_agent_id=ctx["agent"]["id"])
        offer_r3 = counter_offer(offer_r2)
        resp = api.list_submission_offers(ctx["submission"]["id"], DIRECTOR)
        data, meta = validate_paginated(resp)
        assert len(data) == 3 and meta["total_count"] == 3, "all rounds remain listable"
        by_round = {row["round_number"]: row for row in data}
        assert by_round[1]["id"] == offer_r1["id"] and by_round[1]["status"] == "COUNTERED"
        assert by_round[2]["id"] == offer_r2["id"] and by_round[2]["status"] == "COUNTERED"
        assert by_round[3]["id"] == offer_r3["id"] and by_round[3]["status"] == "EXTENDED"


class TestOfferTermsAndOcc:
    def test_guarantee_not_multiple_of_100_rejected(self, api):
        """PRD section 3.7: "The terms are validated up front: `weekly_rate_cents`
        must be strictly positive; `guarantee_cents` must be non-negative, no more
        than fifty-two times `weekly_rate_cents`, and a multiple of 100 —
        violations are rejected with `ERR_INVALID_OFFER_TERMS` (HTTP 422), on
        initial offers and counter-offers alike."

        Design: Corner/errors/invalid_offer_terms_error_triggerable
        """
        ctx = setup_callback_completed()
        resp = api.create_offer(
            ctx["submission"]["id"],
            create_offer_payload(guarantee_cents=800_001),
            DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_OFFER_TERMS)

    def test_stale_offer_version_rejected_on_counter(self, api):
        """PRD section 2.7: "Second, the counter-offer write
        `POST /casting/offers/{id}/counter` requires the field
        `expected_offer_version`, carrying the client's last observed `version` of
        the offer being countered. A mismatch — because the other party has just
        countered and created a new round, or the offer was withdrawn in the
        meantime — is rejected with `ERR_STALE_VERSION` (HTTP 412), and no new
        round is created."

        Design: Corner/cross_cutting_layers/stale_offer_version_rejected_on_counter
        """
        ctx = setup_offer_pending(agent=True)
        offer = ctx["offer"]
        # One behind the last observed version; if the server numbers versions
        # from 0, use a far-future value instead — either way it mismatches.
        stale = offer["version"] - 1 if offer["version"] >= 1 else offer["version"] + 1000
        payload = create_counter_payload(stale)
        resp = api.counter_offer(offer["id"], payload, make_agent_headers(ctx["agent"]["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestAcceptGateOrdering:
    def test_accept_withdrawn_offer_state_beats_permit_gate(self, api):
        """PRD section 3.7: "Acceptance evaluates its gates in order:
        state-machine legality, then the minor-permit gate of §3.8
        (`ERR_PERMIT_REQUIRED`), then liveness (`ERR_NOT_LIVE_OFFER`), then expiry
        (`ERR_OFFER_EXPIRED`)."
        PRD section 2.8: "State-machine legality of the requested transition from
        the target resource's current state, including terminal-state lockdown —
        failures produce `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_offer_accept
        """
        # Minor role + minor talent and NO registered permit: the permit gate
        # would fail — but the offer is no longer EXTENDED, so the state check
        # must fire first.
        ctx = setup_minor_pipeline(with_verified_permit=False)
        offer = ctx["offer"]
        validate_success(api.withdraw_offer(offer["id"], DIRECTOR))
        resp = api.accept_offer(
            offer["id"],
            {
                "engagement_start": "2026-08-20T00:00:00Z",
                "engagement_end": "2026-08-22T00:00:00Z",
                "proration_mode": "CALENDAR_SPAN",
            },
            DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_accept_countered_round_state_beats_permit_gate(self, api):
        """PRD section 3.7: "Acceptance evaluates its gates in order:
        state-machine legality, then the minor-permit gate of §3.8
        (`ERR_PERMIT_REQUIRED`), then liveness (`ERR_NOT_LIVE_OFFER`), then expiry
        (`ERR_OFFER_EXPIRED`)."
        PRD section 3.7: "The live offer's status becomes `COUNTERED`, and a
        brand-new offer row is created with a `round_number` one higher than its
        parent's, a `parent_offer_id` pointing at the superseded offer, terms
        taken from the counter payload, and status `EXTENDED`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_offer_accept
        """
        ctx = setup_minor_pipeline(with_verified_permit=False)
        offer_r1 = ctx["offer"]
        # Office counter supersedes round 1 (now COUNTERED, no longer EXTENDED).
        counter_offer(offer_r1)
        resp = api.accept_offer(
            offer_r1["id"],
            {
                "engagement_start": "2026-08-20T00:00:00Z",
                "engagement_end": "2026-08-22T00:00:00Z",
                "proration_mode": "CALENDAR_SPAN",
            },
            DIRECTOR,
        )
        # PRD 3.7 pins the gate order (state-machine legality, then permit gate,
        # then liveness, then expiry) but does not pin whether accepting a
        # superseded (COUNTERED) round trips the state gate itself
        # (ERR_INVALID_STATE, reading the EXTENDED -> ACCEPTED transition
        # strictly) or passes the state gate so the permit gate fires first
        # (ERR_PERMIT_REQUIRED — the liveness sentence claims superseded rounds,
        # but the permit gate outranks liveness in the pinned order). Both
        # readings are PRD-faithful; what is pinned is that the answer comes
        # from one of the two earliest gates, never from liveness or expiry.
        validate_error_is_one_of(resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_PERMIT_REQUIRED])
