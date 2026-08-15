"""Settlement offers: negotiation cycles, expiry, cooling-off, counter-party rules, OCC."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_offer,
    assert_iso_instant,
    assert_settlement,
    assert_settlement_offer,
    complaint_version,
    create_settlement_offer_payload,
    create_settlement_payload,
    get_complaint,
    get_offer,
    make_business_headers,
    make_consumer_headers,
    make_mediator_headers,
    refer_complaint,
    set_clock,
    setup_mediation_active_case,
    tender_offer,
    validate_error,
    validate_success,
)

OFFICER_1 = TEST_USERS["intake_officer_headers"]


class TestOfferNegotiationCycle:
    def _setup_active(self, api):
        return setup_mediation_active_case(
            consumer_overrides={"full_name": "C N", "email": "cn@x.com"},
            business_overrides={"legal_name": "NegoCo"},
            complaint_overrides={"category": "WARRANTY_DENIED", "description": "neg"},
        )

    def test_supersede_chain_links_parent_and_sequence(self, api):
        """PRD §3.5: "If an earlier offer on the same complaint is still `TENDERED`, the new offer supersedes it — the old one becomes `SUPERSEDED`, the new one's `parent_offer_id` points at it, and its `offer_seq` continues the chain — and the complaint's `version` advances by one"
        PRD §3.5: "Each complaint numbers its offers from 1: the first offer carries `offer_seq` 1 and a null `parent_offer_id`."

        Design: Difficulty/non_linear_state_machine/d_offer_negotiation_cycle
        """
        ctx = self._setup_active(api)
        complaint_id = ctx["complaint"]["id"]
        o1 = tender_offer(complaint_id, ctx["business"], "BUSINESS", 5000)
        assert o1["offer_seq"] == 1
        assert o1["parent_offer_id"] is None
        assert o1["offer_status"] == "TENDERED"

        o2 = tender_offer(complaint_id, ctx["consumer"], "CONSUMER", 4500)
        assert o2["offer_seq"] == 2, "offer_seq continues the chain"
        assert o2["parent_offer_id"] == o1["id"], "parent_offer_id points at the superseded offer"

        o1_after = get_offer(o1["id"])
        assert o1_after["offer_status"] == "SUPERSEDED"

    def test_reject_rescind_and_retender_cycle(self, api):
        """PRD §3.5: "Rejection moves the offer to `REJECTED`."
        PRD §3.5: "A valid rescission moves the offer to `RESCINDED`"
        PRD §3.5: "While the current time remains strictly before `cooling_off_until`, the consumer may rescind an `ACCEPTED` offer"

        Design: Difficulty/non_linear_state_machine/d_offer_negotiation_cycle
        """
        ctx = self._setup_active(api)
        complaint_id = ctx["complaint"]["id"]
        o1 = tender_offer(complaint_id, ctx["business"], "BUSINESS", 5000)
        o2 = tender_offer(complaint_id, ctx["consumer"], "CONSUMER", 4500)

        # The counter-party (business) rejects the consumer-tendered offer.
        rejected = validate_success(api.reject_offer(o2["id"], make_business_headers(ctx["business"]["id"])))
        assert rejected["offer_status"] == "REJECTED"

        o3 = tender_offer(complaint_id, ctx["business"], "BUSINESS", 4700)
        assert o3["offer_seq"] == 3
        assert o3["parent_offer_id"] is None, "no TENDERED offer was open when o3 was tendered"

        accepted = accept_offer(o3["id"], ctx["consumer"], "CONSUMER")
        assert accepted["offer_status"] == "ACCEPTED"
        assert_iso_instant(accepted["cooling_off_until"], "2026-08-04T00:00:00Z", "cooling_off_until")

        # Clock is still 2026-08-01: strictly inside the 72-hour cooling-off.
        rescinded = validate_success(
            api.rescind_offer(o3["id"], make_consumer_headers(ctx["consumer"]["id"]))
        )
        assert rescinded["offer_status"] == "RESCINDED"

        o4 = tender_offer(complaint_id, ctx["consumer"], "CONSUMER", 4600)
        assert o4["offer_seq"] == 4
        assert o4["parent_offer_id"] is None
        assert o4["offer_status"] == "TENDERED"
        assert get_complaint(complaint_id)["case_status"] == "MEDIATION_ACTIVE", (
            "negotiation loop never leaves MEDIATION_ACTIVE"
        )


class TestOfferExpiryBoundary:
    def test_offer_open_at_exact_expiry_and_expired_one_second_later(self, api):
        """PRD §3.5: "An offer stays open while the current time is at or before its `expires_at`; the clock sweep marks it `EXPIRED` only once time has strictly passed that instant."
        PRD §3.5: "sets its `expires_at` fourteen days out"

        Design: Corner/calculations/c_calc_offer_expiry_boundary
        """
        ctx = setup_mediation_active_case(
            consumer_overrides={"full_name": "EX", "email": "ex@x.com"},
            business_overrides={"legal_name": "ExCo"},
            complaint_overrides={"category": "OTHER", "description": "ex"},
        )
        complaint_id = ctx["complaint"]["id"]
        o1 = tender_offer(complaint_id, ctx["business"], "BUSINESS", 3000)
        assert_iso_instant(o1["expires_at"], "2026-08-15T00:00:00Z", "expires_at")

        # At exactly expires_at the sweep has not fired (strictly-passed rule).
        set_clock("2026-08-15T00:00:00Z")
        accepted = accept_offer(o1["id"], ctx["consumer"], "CONSUMER")
        assert accepted["offer_status"] == "ACCEPTED", "now <= expires_at is still open"

        o2 = tender_offer(complaint_id, ctx["business"], "BUSINESS", 3100)
        assert_iso_instant(o2["expires_at"], "2026-08-29T00:00:00Z", "expires_at")

        # One second past expiry: the sweep marks the offer EXPIRED.
        set_clock("2026-08-29T00:00:01Z")
        assert get_offer(o2["id"])["offer_status"] == "EXPIRED"
        resp = api.accept_offer(o2["id"], make_consumer_headers(ctx["consumer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestCoolingOffBoundary:
    def test_settlement_execute_waits_out_cooling_off(self, api):
        """PRD §3.6: "the current time must be at or past the source offer's `cooling_off_until`, or the attempt is refused with `ERR_COOLING_OFF_ACTIVE`"
        PRD §3.5: "Acceptance of a `TENDERED` offer stamps `accepted_at` and sets `cooling_off_until` seventy-two hours later"
        PRD §3.5: "at the exact instant the cooling-off ends, or any time after, rescission is refused with `ERR_RESCISSION_WINDOW_EXPIRED` — and that same instant is when settlement execution first becomes permitted, as §3.6 describes."

        Design: Corner/calculations/c_calc_cooling_off_boundary
        """
        ctx = setup_mediation_active_case(
            consumer_overrides={"full_name": "CO", "email": "co2@x.com"},
            business_overrides={"legal_name": "CoolCo"},
            complaint_overrides={"category": "OTHER", "description": "co"},
        )
        complaint_id = ctx["complaint"]["id"]
        offer = tender_offer(complaint_id, ctx["business"], "BUSINESS", 4000)
        accepted = accept_offer(offer["id"], ctx["consumer"], "CONSUMER")
        assert_iso_instant(accepted["cooling_off_until"], "2026-08-04T00:00:00Z", "cooling_off_until")

        # Settlement documented one second before the cooling-off ends.
        set_clock("2026-08-03T23:59:59Z")
        version = complaint_version(complaint_id)
        settlement = validate_success(
            api.create_settlement(
                complaint_id, create_settlement_payload(version),
                make_mediator_headers(ctx["mediator"]["id"]),
            ),
            201,
        )
        assert settlement["settlement_status"] == "DRAFT"

        too_early = api.execute_settlement(
            settlement["id"], make_mediator_headers(ctx["mediator"]["id"])
        )
        validate_error(too_early, ApiErrorId.ERR_COOLING_OFF_ACTIVE)

        # At exactly T+72h execution becomes permitted (boundary on the expired side).
        set_clock("2026-08-04T00:00:00Z")
        executed = validate_success(
            api.execute_settlement(settlement["id"], make_mediator_headers(ctx["mediator"]["id"]))
        )
        assert executed["settlement_status"] == "EXECUTED"


class TestCounterPartyRules:
    def test_tendering_party_cannot_accept_own_offer(self, api):
        """PRD §3.5: "A consumer-tendered offer requires a `Business` caller to answer it, and a business-tendered offer requires the `Consumer`; in both cases the caller must also be a party to the complaint."
        PRD §2.1: "An entity-backed caller acting outside its own scope — a consumer touching another consumer's complaint, a business answering a complaint filed against someone else, a mediator completing a colleague's session — is refused with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
        PRD §3.5: "Acceptance of a `TENDERED` offer stamps `accepted_at` and sets `cooling_off_until` seventy-two hours later"

        Design: Corner/rbac/c_rbac_counterparty_accept_enforced
        """
        ctx = setup_mediation_active_case(
            consumer_overrides={"full_name": "CP", "email": "cpx@x.com"},
            business_overrides={"legal_name": "CpCo"},
            complaint_overrides={"category": "OTHER", "description": "cp"},
        )
        complaint_id = ctx["complaint"]["id"]
        offer = tender_offer(complaint_id, ctx["business"], "BUSINESS", 1200)

        own_accept = api.accept_offer(offer["id"], make_business_headers(ctx["business"]["id"]))
        validate_error(own_accept, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

        accepted = accept_offer(offer["id"], ctx["consumer"], "CONSUMER")
        assert accepted["offer_status"] == "ACCEPTED"
        assert_iso_instant(accepted["cooling_off_until"], "2026-08-04T00:00:00Z", "cooling_off_until")


class TestOfferAcceptRequiresActiveComplaint:
    def _setup_referred_with_tendered_offer(self, api):
        ctx = setup_mediation_active_case(
            consumer_overrides={"full_name": "C H", "email": "ch@x.com"},
            business_overrides={"legal_name": "RefCo"},
            complaint_overrides={"description": "xref"},
        )
        complaint_id = ctx["complaint"]["id"]
        offer = tender_offer(complaint_id, ctx["business"], "BUSINESS", 8000)
        # The mediator refers the case to enforcement mid-negotiation.
        refer_complaint(
            complaint_id, "pattern detected mid-mediation",
            make_mediator_headers(ctx["mediator"]["id"]),
        )
        return ctx, offer

    def test_offer_accept_rejected_once_complaint_referred(self, api):
        """PRD §3.5: "Offers may be tendered or accepted only while the complaint itself remains in `MEDIATION_ACTIVE` or `MEDIATION_IMPASSE`."
        PRD §2.12: "6. State: the target entity sits in a valid from-state for the requested transition, else `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/d_xstate_offer_accept_needs_active_complaint
        """
        ctx, offer = self._setup_referred_with_tendered_offer(api)
        assert get_complaint(ctx["complaint"]["id"])["case_status"] == "REFERRED_ENFORCEMENT"

        resp = api.accept_offer(offer["id"], make_consumer_headers(ctx["consumer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_failed_accept_leaves_tendered_offer_untouched(self, api):
        """PRD §3.5: "Offers may be tendered or accepted only while the complaint itself remains in `MEDIATION_ACTIVE` or `MEDIATION_IMPASSE`."
        PRD §3.8: "The complaint becomes `REFERRED_ENFORCEMENT`, and the closing ritual fires."

        Design: Difficulty/cross_entity_state_dependency/d_xstate_offer_accept_needs_active_complaint
        """
        ctx, offer = self._setup_referred_with_tendered_offer(api)
        resp = api.accept_offer(offer["id"], make_consumer_headers(ctx["consumer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        offer_after = get_offer(offer["id"])
        assert offer_after["offer_status"] == "TENDERED", "offer itself untouched by the failed accept"
        assert get_complaint(ctx["complaint"]["id"])["case_status"] == "REFERRED_ENFORCEMENT"


class TestOfferOptimisticConcurrency:
    def test_offer_create_with_stale_complaint_version_rejected(self, api):
        """PRD §2.8: "Each request must include `expected_complaint_version`, a non-optional field carrying the complaint `version` the client last observed. If the complaint's current `version` has advanced beyond the supplied value, the write is refused with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the complaint before retrying."
        PRD §2.8: "tendering an offer supersedes the complaint's currently open offer and advances the complaint's `version` by one"

        Design: Corner/complexity_layers/c_occ_offer_stale_version_rejected
        """
        ctx = setup_mediation_active_case(
            consumer_overrides={"full_name": "OC", "email": "oc@x.com"},
            business_overrides={"legal_name": "OcCo"},
            complaint_overrides={"category": "OTHER", "description": "oc"},
        )
        complaint_id = ctx["complaint"]["id"]
        stale_version = complaint_version(complaint_id)

        first = validate_success(
            api.create_settlement_offer(
                complaint_id,
                create_settlement_offer_payload("BUSINESS", stale_version,
                                                restitution_amount_cents=1000),
                make_business_headers(ctx["business"]["id"]),
            ),
            201,
        )
        assert_settlement_offer(first)
        assert first["offer_status"] == "TENDERED", "first offer bumps the complaint version"

        replayed = api.create_settlement_offer(
            complaint_id,
            create_settlement_offer_payload("CONSUMER", stale_version,
                                            restitution_amount_cents=900),
            make_consumer_headers(ctx["consumer"]["id"]),
        )
        validate_error(replayed, ApiErrorId.ERR_STALE_VERSION)
