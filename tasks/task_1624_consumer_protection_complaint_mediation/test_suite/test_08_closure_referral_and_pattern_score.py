"""Unresolved closure, enforcement referral lifecycle, and the pattern score."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    close_unresolved,
    complete_session,
    drive_to_executed_settlement,
    dual_confirm_session,
    file_complaint,
    get_business,
    get_complaint,
    make_enforcement_attorney_headers,
    notify_business,
    offer_mediation,
    pledge_payment,
    mark_received,
    propose_session,
    refer_complaint,
    register_business,
    register_case_parties,
    register_consumer,
    register_mediation_room,
    register_mediator,
    review_response,
    screen_accept,
    set_clock,
    setup_referred_case,
    submit_response,
    validate_error,
    validate_success,
)

OFFICER_1 = TEST_USERS["intake_officer_headers"]
OFFICER_2 = TEST_USERS["intake_officer_2_headers"]
ATTORNEY_1 = TEST_USERS["enforcement_attorney_headers"]
ATTORNEY_9 = TEST_USERS["enforcement_attorney_2_headers"]
DIRECTOR_1 = TEST_USERS["unit_director_headers"]


class TestUnresolvedClosureSegregation:
    def test_accepting_officer_cannot_close_unresolved(self, api):
        """PRD §3.8: "The segregation rule of §2.7 bars the officer who originally accepted the complaint — the caller's identifier must differ from `accepted_by_officer_id`, else `ERR_SEGREGATION_OF_DUTIES`."
        PRD §2.10: "When a case reaches `SETTLED`, `CLOSED_UNRESOLVED`, or `REFERRED_ENFORCEMENT`, a complaint filed with `publication_consent` moves from `UNPUBLISHED` to `EMBARGOED`"
        PRD §3.8: "The complaint becomes `CLOSED_UNRESOLVED`, `closed_by_officer_id` is stamped, and the closing ritual fires."

        Design: Corner/rbac/c_rbac_sod_close_same_officer_rejected
        """
        parties = register_case_parties(
            with_mediator=False, with_room=False,
            consumer_overrides={"full_name": "SD", "email": "sd@x.com"},
            business_overrides={"legal_name": "SdCo"},
        )
        complaint = file_complaint(parties["consumer"], parties["business"],
                                   category="OTHER", description="sd")
        screen_accept(complaint["id"], OFFICER_1)
        notify_business(complaint["id"], OFFICER_1)
        response = submit_response(complaint["id"], parties["business"])
        review_response(response["id"], "SUFFICIENT", OFFICER_1)

        own_close = api.close_unresolved(
            complaint["id"],
            {"alternative_options": ["BBB"], "closure_summary": "officer-1 tries"},
            OFFICER_1,
        )
        validate_error(own_close, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        closed = close_unresolved(
            complaint["id"], OFFICER_2,
            alternative_options=["SMALL_CLAIMS", "BBB"], closure_summary="officer-2 closes",
        )
        assert closed["case_status"] == "CLOSED_UNRESOLVED"
        assert closed["closed_by_officer_id"] == "officer-2"
        assert closed["publication_status"] == "EMBARGOED", "consent default true -> embargoed"


class TestReferralLifecycle:
    def test_referral_return_reverts_closure_effects(self, api):
        """PRD §3.8: "A `decision` of `RETURN` sends the case back: the referral becomes `RETURNED_TO_MEDIATION`, the complaint reverts to `MEDIATION_IMPASSE`, its `closed_at` is cleared, an embargo that never matured rolls back from `EMBARGOED` to `UNPUBLISHED`, and the pattern score is recomputed with the complaint no longer counting as closed."

        Design: Corner/state_machines/c_sm_referral_return_reopens_mediation
        """
        ctx = setup_referred_case(referral_headers=OFFICER_1)
        complaint = ctx["complaint"]
        assert complaint["case_status"] == "REFERRED_ENFORCEMENT"
        assert complaint["publication_status"] == "EMBARGOED"
        assert complaint["closed_at"] is not None

        reviewed = validate_success(
            api.review_enforcement_referral(ctx["referral"]["id"], {"decision": "RETURN"}, ATTORNEY_1)
        )
        assert reviewed["referral_status"] == "RETURNED_TO_MEDIATION"

        after = get_complaint(complaint["id"])
        assert after["case_status"] == "MEDIATION_IMPASSE"
        assert after["closed_at"] is None, "closure reverted"
        assert after["publication_status"] == "UNPUBLISHED"

    def test_referrer_cannot_review_own_referral(self, api):
        """PRD §3.8: "An `EnforcementAttorney` then reviews the referral — but never one they filed themselves, since a reviewer whose identifier matches `referred_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.8: "A `decision` of `ACCEPT` keeps the case with enforcement: the referral becomes `ACCEPTED`, `reviewed_by_user_id` is stamped, and the complaint remains `REFERRED_ENFORCEMENT`."

        Design: Corner/rbac/c_rbac_sod_referral_review_same_user_rejected
        """
        ctx = setup_referred_case(referral_headers=OFFICER_1)
        referral_id = ctx["referral"]["id"]

        own_review = api.review_enforcement_referral(
            referral_id, {"decision": "ACCEPT"},
            make_enforcement_attorney_headers("officer-1"),
        )
        validate_error(own_review, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        accepted = validate_success(
            api.review_enforcement_referral(referral_id, {"decision": "ACCEPT"}, ATTORNEY_9)
        )
        assert accepted["referral_status"] == "ACCEPTED"
        assert accepted["reviewed_by_user_id"] == "att-9"
        assert get_complaint(ctx["complaint"]["id"])["case_status"] == "REFERRED_ENFORCEMENT"


class TestFlaggedBusinessGate:
    def _setup_flagged_business(self, api):
        """SMALL business with four complaints REFERRED_ENFORCEMENT (4 x 25 = 100);
        a fifth complaint in RESPONSE_RECEIVED with a SUFFICIENT response."""
        consumer = register_consumer(full_name="C I", email="ci@x.com", state_code="OR")
        business = register_business(legal_name="PatternCo", home_state="OR", operates_in_states=["OR"])
        set_clock("2026-08-01T00:00:00Z")
        for day in ("2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04"):
            complaint = file_complaint(
                consumer, business, incident_date=day,
                category="DECEPTIVE_PRACTICE", description=f"pattern {day}",
            )
            screen_accept(complaint["id"], OFFICER_1)
            refer_complaint(complaint["id"], f"pattern {day}", OFFICER_1)

        p5 = file_complaint(
            consumer, business, incident_date="2026-07-05",
            category="DECEPTIVE_PRACTICE", description="p5",
        )
        screen_accept(p5["id"], OFFICER_1)
        notify_business(p5["id"], OFFICER_1)
        r5 = submit_response(p5["id"], business)
        review_response(r5["id"], "SUFFICIENT", OFFICER_1)
        return consumer, business, p5

    def test_flagged_business_bars_mediation_offers(self, api):
        """PRD §2.11: "A score of 100 or more — the boundary is inclusive — marks it `FLAGGED`, and while that band holds, no complaint against the business may be offered mediation at all: the attempt is refused with `ERR_PATTERN_REFERRAL_REQUIRED`, because a pattern violator belongs with enforcement until its score falls back below the band."
        PRD §3.8: "Each eligible complaint contributes a weight by outcome — 10 for `SETTLED`, 15 for `CLOSED_UNRESOLVED`, 25 for `REFERRED_ENFORCEMENT`"

        Design: Difficulty/cross_entity_state_dependency/d_xstate_flagged_business_blocks_mediation
        """
        _, business, p5 = self._setup_flagged_business(api)
        business = get_business(business["id"])
        assert business["pattern_score"] == 100, "4 x 25 referred weight"
        assert business["watch_status"] == "FLAGGED", "exactly 100 flags (inclusive boundary)"

        resp = api.offer_mediation(p5["id"], OFFICER_1)
        validate_error(resp, ApiErrorId.ERR_PATTERN_REFERRAL_REQUIRED)

    def test_referral_snapshots_score_before_closure_recompute(self, api):
        """PRD §3.8: "Referral creates an `EnforcementReferral` in `PENDING_REVIEW`, recording the caller as `referred_by_user_id` with their `referred_by_role` and snapshotting the business's current pattern score into `pattern_score_at_referral`."
        PRD §3.8: "Every terminal closure — and every referral return that un-closes a case — recomputes the respondent's `pattern_score`."

        Design: Difficulty/cross_entity_state_dependency/d_xstate_flagged_business_blocks_mediation
        """
        _, business, p5 = self._setup_flagged_business(api)
        referral = refer_complaint(p5["id"], "mandatory referral at FLAGGED", DIRECTOR_1)
        assert referral["pattern_score_at_referral"] == 100, (
            "snapshot taken before this complaint's own closure recompute"
        )
        assert get_business(business["id"])["pattern_score"] == 125, "5 x 25 after the fifth closure"


class TestPatternScoreMultiplier:
    def _setup_medium_business_case(self, api):
        """MEDIUM business with K1 SETTLED (not overdue) and K2 CLOSED_UNRESOLVED
        after the deadline sweep set ever_response_overdue."""
        parties = register_case_parties(
            consumer_overrides={"full_name": "C P", "email": "cp@x.com"},
            business_overrides={"legal_name": "MidCo", "size_tier": "MEDIUM"},
        )
        consumer, business, mediator, room = (
            parties["consumer"], parties["business"], parties["mediator"], parties["room"],
        )
        set_clock("2026-08-01T00:00:00Z")
        ctx1 = drive_to_executed_settlement(
            consumer, business, mediator, room,
            incident_date="2026-07-01", description="k1", restitution_cents=5000,
            session_starts_at="2026-08-10T10:00:00Z", session_ends_at="2026-08-10T11:00:00Z",
        )
        payment = pledge_payment(business, ctx1["settlement"]["outstanding_cents"])
        mark_received(payment["id"])  # K1 SETTLED at 2026-08-04

        k2 = file_complaint(
            consumer, business, incident_date="2026-07-15",
            category="BILLING_DISPUTE", description="k2", amount_in_dispute_cents=900,
        )
        screen_accept(k2["id"], OFFICER_1)
        notify_business(k2["id"], OFFICER_1)  # deadline 2026-09-03T00:00:00Z
        set_clock("2026-09-04T00:00:00Z")   # strictly past: sweep flips RESPONSE_OVERDUE
        offer_mediation(k2["id"], OFFICER_1)
        s2 = propose_session(
            k2["id"], mediator, room,
            starts_at="2026-09-10T10:00:00Z", ends_at="2026-09-10T11:00:00Z",
        )
        dual_confirm_session(s2["id"], consumer, business)
        complete_session(s2["id"], mediator, {"outcome": "IMPASSE"}, at_clock="2026-09-10T10:30:00Z")
        closed = close_unresolved(
            k2["id"], OFFICER_2,
            alternative_options=["PRIVATE_ATTORNEY"], closure_summary="impasse",
        )
        return parties, k2, closed

    def test_medium_business_multiplier_rounds_half_up_once(self, api):
        """PRD §3.8: "The raw sum is then scaled by the business's `size_tier` — multiplied by 1.0 for `SMALL`, 0.75 for `MEDIUM`, or 0.5 for `LARGE` — and the product is rounded half-up to a whole number, the single rounding point of the computation"
        PRD §3.8: "a raw sum of 30 becomes 30 for a `SMALL` business, 23 for a `MEDIUM` one (22.5 rounding half-up), and 15 for a `LARGE` one"
        PRD §2.11: "A business scoring below 60 sits `CLEAR`."

        Design: Difficulty/combinatorial_formula/d_pattern_score_tiered_multiplier
        """
        parties, k2, closed = self._setup_medium_business_case(api)
        assert closed["case_status"] == "CLOSED_UNRESOLVED"
        # raw = SETTLED 10 + CLOSED_UNRESOLVED 15 + overdue 5 = 30; MEDIUM x0.75 = 22.5 -> 23.
        business = get_business(parties["business"]["id"])
        assert business["pattern_score"] == 23
        assert business["watch_status"] == "CLEAR", "23 < 60"

    def test_overdue_penalty_counted_once_per_complaint(self, api):
        """PRD §3.8: "plus a flat penalty of 5 points if its `ever_response_overdue` flag stands, counted once per complaint"
        PRD §3.3: "The complaint's `ever_response_overdue` flag is set to true, and it is never reset, no matter how the case ends."

        Design: Difficulty/combinatorial_formula/d_pattern_score_tiered_multiplier
        """
        parties, k2, _ = self._setup_medium_business_case(api)
        complaint = get_complaint(k2["id"])
        assert complaint["ever_response_overdue"] is True, (
            "the 2026-09-04 sweep flipped the case past its 2026-09-03 deadline"
        )
        # raw 30 includes exactly one +5 penalty for K2; a second penalty would give
        # round_half_up(35 * 0.75) = 27, not 23.
        assert get_business(parties["business"]["id"])["pattern_score"] == 23
