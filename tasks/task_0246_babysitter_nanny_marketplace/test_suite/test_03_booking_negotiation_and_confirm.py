"""Booking negotiation (counter-offer cycle, OCC), confirmation gating
(tier, escrow, validation precedence), escrow reservation conservation, and the
review-eligibility cross-entity dependency.

Translates difficulty instances under non_linear_state_machine (booking cycle),
cross_entity_state_dependency, compensating_invariant (escrow), and
priority_pair_validation_conflict, plus corner validations / cross-cutting /
consistency instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    set_clock, create_family, create_caregiver, create_cleared_available_caregiver,
    create_open_posting, offer_booking, confirm_booking,
    setup_confirmed_one_time_booking,
    make_family_headers, make_caregiver_headers, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


class TestCounterOfferCycle:
    """non_linear_state_machine / booking_counter_offer_cycle_offered_countered_offered."""

    def _offered_booking(self, suffix):
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=100000, num_children=1,
                            required_tier="BASIC", email=f"cyc-{suffix}@x.com")
        cg = create_caregiver(hourly_rate_floor_cents=1500, email=f"cycg-{suffix}@x.com")
        posting = create_open_posting(fam["id"], care_type="ONE_TIME",
                                      family_pay_rate_cents=2000, required_tier="BASIC")
        booking = offer_booking(fam["id"], cg["id"], posting["id"], agreed_rate_cents=2000,
                                scheduled_start="2026-03-20T08:00:00Z",
                                scheduled_end="2026-03-20T12:00:00Z")
        return fam, cg, booking

    def test_cycle_returns_to_offered_with_offer_round_three(self, api):
        """PRD §3.4: "From `OFFERED`, the caregiver may counter, moving the
        booking to `COUNTERED`; from `COUNTERED`, the family may counter back,
        returning it to `OFFERED`, and the two sides may volley indefinitely."
        PRD §3.4: "A successful counter overwrites `agreed_rate_cents` with the
        countered rate, increases `offer_round` by 1, and increments the
        booking's `version` by 1."

        OFFERED(round1) → caregiver counter → COUNTERED(round2) → family counter →
        OFFERED(round3), agreed_rate 2200.

        Design: Difficulty/non_linear_state_machine/booking_counter_offer_cycle_offered_countered_offered
        """
        fam, cg, booking = self._offered_booking("a")
        v0 = booking["version"]
        c1 = validate_success(api.counter_booking(
            booking["id"], {"agreed_rate_cents": 2500, "expected_booking_version": v0},
            make_caregiver_headers(cg["id"])), 200)
        assert c1["status"] == "COUNTERED"
        c2 = validate_success(api.counter_booking(
            booking["id"], {"agreed_rate_cents": 2200, "expected_booking_version": c1["version"]},
            make_family_headers(fam["id"])), 200)
        assert c2["status"] == "OFFERED", "family counter from COUNTERED returns to OFFERED"
        assert c2["agreed_rate_cents"] == 2200
        assert c2["offer_round"] == 3, f"expected offer_round 3, got {c2['offer_round']}"

    def test_each_counter_increments_version(self, api):
        """PRD §3.4: "the request must carry `expected_booking_version` matching
        the booking's current `version` ... A successful counter ... increments
        the booking's `version` by 1."

        Design: Difficulty/non_linear_state_machine/booking_counter_offer_cycle_offered_countered_offered
        """
        fam, cg, booking = self._offered_booking("b")
        v0 = booking["version"]
        c1 = validate_success(api.counter_booking(
            booking["id"], {"agreed_rate_cents": 2500, "expected_booking_version": v0},
            make_caregiver_headers(cg["id"])), 200)
        assert c1["version"] == v0 + 1
        c2 = validate_success(api.counter_booking(
            booking["id"], {"agreed_rate_cents": 2200, "expected_booking_version": c1["version"]},
            make_family_headers(fam["id"])), 200)
        assert c2["version"] == c1["version"] + 1


class TestConfirmRequiresCaregiverCleared:
    """cross_entity_state_dependency / booking_confirm_requires_caregiver_cleared."""

    def test_confirm_blocked_when_caregiver_not_cleared(self, api):
        """PRD §3.5: "The caregiver's `verification_status` must be `CLEAR` and
        their `background_check_tier` must reach the family's `required_tier`
        under the tier order; a tier shortfall is rejected with
        `ERR_TIER_INSUFFICIENT`."

        Caregiver only IN_PROGRESS (verification PENDING, not CLEAR); confirm
        rejected and the booking stays OFFERED.

        Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_caregiver_cleared
        """
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=100000, num_children=1,
                            required_tier="BASIC", email="ce1@x.com")
        cg = create_caregiver(hourly_rate_floor_cents=1500, email="ce1cg@x.com")
        # available but check only started (PENDING), never adjudicated CLEAR.
        get_success_data(api.set_availability(
            cg["id"], {"availability_status": "AVAILABLE"}, make_caregiver_headers(cg["id"])))
        bc = get_success_data(api.create_background_check(
            {"caregiver_id": cg["id"], "requested_tier": "BASIC"}, ADMIN))
        api.start_background_check(bc["id"], ADMIN)
        posting = create_open_posting(fam["id"], care_type="ONE_TIME",
                                      family_pay_rate_cents=2000, required_tier="BASIC")
        booking = offer_booking(fam["id"], cg["id"], posting["id"], agreed_rate_cents=2000,
                                scheduled_start="2026-03-20T08:00:00Z",
                                scheduled_end="2026-03-20T12:00:00Z")
        res = api.confirm_booking(booking["id"], make_caregiver_headers(cg["id"]))
        validate_error(res, "ERR_TIER_INSUFFICIENT")
        after = validate_success(api.get_booking(booking["id"], ADMIN), 200)
        assert after["status"] == "OFFERED", "booking must remain OFFERED after a blocked confirm"

    def test_confirm_blocked_keeps_verification_not_clear(self, api):
        """PRD §3.2: "Starting a check that is currently `INITIATED` advances it to
        `IN_PROGRESS` and sets the subject caregiver's `verification_status` to
        `PENDING`."

        Confirms the precondition holds: the caregiver is PENDING (not CLEAR)
        when the confirm is rejected.

        Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_caregiver_cleared
        """
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=100000, num_children=1,
                            required_tier="BASIC", email="ce2@x.com")
        cg = create_caregiver(hourly_rate_floor_cents=1500, email="ce2cg@x.com")
        get_success_data(api.set_availability(
            cg["id"], {"availability_status": "AVAILABLE"}, make_caregiver_headers(cg["id"])))
        bc = get_success_data(api.create_background_check(
            {"caregiver_id": cg["id"], "requested_tier": "BASIC"}, ADMIN))
        api.start_background_check(bc["id"], ADMIN)
        caregiver = validate_success(api.get_caregiver(cg["id"], ADMIN), 200)
        assert caregiver["verification_status"] == "PENDING"
        posting = create_open_posting(fam["id"], care_type="ONE_TIME",
                                      family_pay_rate_cents=2000, required_tier="BASIC")
        booking = offer_booking(fam["id"], cg["id"], posting["id"], agreed_rate_cents=2000,
                                scheduled_start="2026-03-20T08:00:00Z",
                                scheduled_end="2026-03-20T12:00:00Z")
        res = api.confirm_booking(booking["id"], make_caregiver_headers(cg["id"]))
        validate_error(res, "ERR_TIER_INSUFFICIENT")


class TestReviewRequiresBookingCompleted:
    """cross_entity_state_dependency / review_requires_booking_completed."""

    def test_review_on_confirmed_booking_rejected(self, api):
        """PRD §3.10: "A review may be created only when its booking's status is
        `COMPLETED` and the authoring family owns that booking; a review against
        a booking that is not completed is rejected with
        `ERR_BOOKING_NOT_COMPLETED`."

        Booking confirmed but session not clocked out (still CONFIRMED) → review
        rejected.

        Design: Difficulty/cross_entity_state_dependency/review_requires_booking_completed
        """
        ctx = setup_confirmed_one_time_booking(
            wallet_balance_cents=100000, num_children=1, required_tier="BASIC",
            agreed_rate_cents=2000, scheduled_start="2026-03-22T08:00:00Z",
            scheduled_end="2026-03-22T12:00:00Z", email_suffix="rvreq")
        res = api.create_review(
            {"booking_id": ctx["booking"]["id"], "family_id": ctx["family"]["id"],
             "caregiver_id": ctx["caregiver"]["id"], "rating_value": 5},
            make_family_headers(ctx["family"]["id"]))
        validate_error(res, "ERR_BOOKING_NOT_COMPLETED")

    def test_confirmed_booking_is_not_completed(self, api):
        """PRD §3.5: "The booking itself moves to `CONFIRMED`."

        Confirms the precondition: the booking is CONFIRMED (not COMPLETED) when
        the review is rejected.

        Design: Difficulty/cross_entity_state_dependency/review_requires_booking_completed
        """
        ctx = setup_confirmed_one_time_booking(
            wallet_balance_cents=100000, num_children=1, required_tier="BASIC",
            agreed_rate_cents=2000, scheduled_start="2026-03-22T08:00:00Z",
            scheduled_end="2026-03-22T12:00:00Z", email_suffix="rvreq2")
        assert ctx["booking"]["status"] == "CONFIRMED"
        res = api.create_review(
            {"booking_id": ctx["booking"]["id"], "family_id": ctx["family"]["id"],
             "caregiver_id": ctx["caregiver"]["id"], "rating_value": 4},
            make_family_headers(ctx["family"]["id"]))
        validate_error(res, "ERR_BOOKING_NOT_COMPLETED")


class TestEscrowConservationConfirmCancel:
    """compensating_invariant / escrow_conservation_confirm_then_cancel_restores_wallet."""

    def test_cancel_releases_exact_reservation(self, api):
        """PRD §3.5: "Cancellation moves the booking to `CANCELLED`, releases the
        reservation by subtracting `estimated_pay_cents` from the family's
        `escrow_reserved_cents` and recomputing `escrow_available_cents` (an
        exact reversal of the reservation)".

        Family wallet 100000; confirm reserves 13200; cancel restores reserved 0
        and available 100000.

        Design: Difficulty/compensating_invariant/escrow_conservation_confirm_then_cancel_restores_wallet
        """
        ctx = setup_confirmed_one_time_booking(
            wallet_balance_cents=100000, num_children=2, required_tier="BASIC",
            agreed_rate_cents=2000, scheduled_start="2026-03-26T08:00:00Z",
            scheduled_end="2026-03-26T14:00:00Z", email_suffix="escan")
        booking = validate_success(api.cancel_booking(
            ctx["booking"]["id"], make_family_headers(ctx["family"]["id"])), 200)
        assert booking["status"] == "CANCELLED"
        family = validate_success(api.get_family(ctx["family"]["id"], ADMIN), 200)
        assert family["escrow_reserved_cents"] == 0
        assert family["escrow_available_cents"] == 100000

    def test_wallet_identity_holds_after_cancel(self, api):
        """PRD §2.6: "At all times, `escrow_reserved_cents` (funds held against
        confirmed bookings' estimated pay) plus `escrow_available_cents` (funds
        free to commit) equals `wallet_balance_cents` exactly."

        Design: Difficulty/compensating_invariant/escrow_conservation_confirm_then_cancel_restores_wallet
        """
        ctx = setup_confirmed_one_time_booking(
            wallet_balance_cents=100000, num_children=2, required_tier="BASIC",
            agreed_rate_cents=2000, scheduled_start="2026-03-26T08:00:00Z",
            scheduled_end="2026-03-26T14:00:00Z", email_suffix="escan2")
        validate_success(api.cancel_booking(
            ctx["booking"]["id"], make_family_headers(ctx["family"]["id"])), 200)
        family = validate_success(api.get_family(ctx["family"]["id"], ADMIN), 200)
        assert (family["escrow_reserved_cents"] + family["escrow_available_cents"]
                == family["wallet_balance_cents"])


class TestValidationPrecedence:
    """priority_pair_validation_conflict."""

    def test_state_beats_fiscal_on_cancel_inprogress(self, api):
        """PRD §2.10: "For a state-changing endpoint, the target's eligibility for
        the requested transition comes fourth (`ERR_INVALID_STATE`)."
        PRD §3.5: "A cancellation attempted when the booking is not `CONFIRMED`,
        or when a child session has already started, is rejected with
        `ERR_INVALID_STATE`."

        Confirmed booking with its session IN_PROGRESS, family escrow depleted:
        the state check (priority 4) wins over the fiscal check (priority 15).

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_cancel_inprogress_vs_escrow
        """
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=13200, num_children=2,
                            required_tier="BASIC", email="pri@x.com")
        cg = create_cleared_available_caregiver(tier="BASIC", email="pricg@x.com")
        posting = create_open_posting(fam["id"], care_type="ONE_TIME",
                                      family_pay_rate_cents=2000, required_tier="BASIC")
        booking = offer_booking(fam["id"], cg["id"], posting["id"], agreed_rate_cents=2000,
                                scheduled_start="2026-03-15T08:00:00Z",
                                scheduled_end="2026-03-15T14:00:00Z")
        booking = confirm_booking(booking["id"], cg["id"])
        set_clock("2026-03-15T08:00:00Z")
        data, _ = _sessions(api, booking["id"])
        get_success_data(api.clock_in(data[0]["id"], make_caregiver_headers(cg["id"])))
        res = api.cancel_booking(booking["id"], make_family_headers(fam["id"]))
        validate_error(res, "ERR_INVALID_STATE")

    def test_state_beats_fiscal_returns_invalid_state_not_escrow(self, api):
        """PRD §2.10: "the target's eligibility for the requested transition comes
        fourth (`ERR_INVALID_STATE`)."
        PRD §3.5: "A cancellation attempted when the booking is not `CONFIRMED`,
        or when a child session has already started, is rejected with
        `ERR_INVALID_STATE`."

        The same depleted-escrow + IN_PROGRESS-session cancel surfaces precisely
        ERR_INVALID_STATE (the earlier check) and never the fiscal error.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_cancel_inprogress_vs_escrow
        """
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=13200, num_children=2,
                            required_tier="BASIC", email="pri2@x.com")
        cg = create_cleared_available_caregiver(tier="BASIC", email="pri2cg@x.com")
        posting = create_open_posting(fam["id"], care_type="ONE_TIME",
                                      family_pay_rate_cents=2000, required_tier="BASIC")
        booking = offer_booking(fam["id"], cg["id"], posting["id"], agreed_rate_cents=2000,
                                scheduled_start="2026-03-15T08:00:00Z",
                                scheduled_end="2026-03-15T14:00:00Z")
        booking = confirm_booking(booking["id"], cg["id"])
        set_clock("2026-03-15T08:00:00Z")
        data, _ = _sessions(api, booking["id"])
        get_success_data(api.clock_in(data[0]["id"], make_caregiver_headers(cg["id"])))
        res = api.cancel_booking(booking["id"], make_family_headers(fam["id"]))
        body = res.json()
        assert body["data"]["error_id"] == "ERR_INVALID_STATE", \
            f"state check must win; got {body['data'].get('error_id')}"

    def test_safety_beats_fiscal_on_confirm_tier_vs_escrow(self, api):
        """PRD §2.10: "the target's eligibility for the requested transition comes
        fourth ... Domain-specific business rules — tier sufficiency, suspension,
        posting consistency, rate floors, recurrence shape, scheduling overlaps,
        interval ordering, review eligibility, escrow sufficiency, and payout
        session validity — follow."
        PRD §3.5: "The caregiver's `verification_status` must be `CLEAR` and their
        `background_check_tier` must reach the family's `required_tier` under the
        tier order; a tier shortfall is rejected with `ERR_TIER_INSUFFICIENT`."

        Confirm fails BOTH tier (caregiver only BASIC, family requires STANDARD)
        and escrow (wallet 100 << estimate): tier (earlier in the order) wins.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_confirm_tier_vs_escrow
        """
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=100, num_children=1,
                            required_tier="STANDARD", email="saf@x.com")
        cg = create_cleared_available_caregiver(tier="BASIC", email="safcg@x.com")
        posting = create_open_posting(fam["id"], care_type="ONE_TIME",
                                      family_pay_rate_cents=2000, required_tier="STANDARD")
        booking = offer_booking(fam["id"], cg["id"], posting["id"], agreed_rate_cents=2000,
                                scheduled_start="2026-03-25T08:00:00Z",
                                scheduled_end="2026-03-25T12:00:00Z")
        res = api.confirm_booking(booking["id"], make_caregiver_headers(cg["id"]))
        validate_error(res, "ERR_TIER_INSUFFICIENT")

    def test_safety_beats_fiscal_leaves_booking_offered_no_reservation(self, api):
        """PRD §3.5: "The caregiver's `verification_status` must be `CLEAR` and
        their `background_check_tier` must reach the family's `required_tier`
        under the tier order; a tier shortfall is rejected with
        `ERR_TIER_INSUFFICIENT`."
        PRD §3.5: "When confirmation succeeds, the system performs an atomic
        cascade. ... It reserves that amount by adding it to the family's
        `escrow_reserved_cents`".

        The rejected confirm reserves nothing — booking stays OFFERED and the
        family's escrow_reserved_cents remains 0.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_confirm_tier_vs_escrow
        """
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=100, num_children=1,
                            required_tier="STANDARD", email="saf2@x.com")
        cg = create_cleared_available_caregiver(tier="BASIC", email="saf2cg@x.com")
        posting = create_open_posting(fam["id"], care_type="ONE_TIME",
                                      family_pay_rate_cents=2000, required_tier="STANDARD")
        booking = offer_booking(fam["id"], cg["id"], posting["id"], agreed_rate_cents=2000,
                                scheduled_start="2026-03-25T08:00:00Z",
                                scheduled_end="2026-03-25T12:00:00Z")
        res = api.confirm_booking(booking["id"], make_caregiver_headers(cg["id"]))
        validate_error(res, "ERR_TIER_INSUFFICIENT")
        after = validate_success(api.get_booking(booking["id"], ADMIN), 200)
        assert after["status"] == "OFFERED"
        family = validate_success(api.get_family(fam["id"], ADMIN), 200)
        assert family["escrow_reserved_cents"] == 0


class TestConfirmInsufficientEscrow:
    """Corner validations / confirm_insufficient_escrow_rejected."""

    def test_confirm_rejected_when_escrow_below_estimate(self, api):
        """PRD §3.5: "Finally, the family's `escrow_available_cents` must be at
        least the booking's `estimated_pay_cents`, else `ERR_INSUFFICIENT_ESCROW`."

        Family wallet 5000 < estimate 13200 → rejected, booking stays OFFERED.

        Design: Corner/validations/confirm_insufficient_escrow_rejected
        """
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=5000, num_children=2,
                            required_tier="BASIC", email="es@x.com")
        cg = create_cleared_available_caregiver(tier="BASIC", email="escg@x.com")
        posting = create_open_posting(fam["id"], care_type="ONE_TIME",
                                      family_pay_rate_cents=2000, required_tier="BASIC")
        booking = offer_booking(fam["id"], cg["id"], posting["id"], agreed_rate_cents=2000,
                                scheduled_start="2026-03-20T08:00:00Z",
                                scheduled_end="2026-03-20T14:00:00Z")
        res = api.confirm_booking(booking["id"], make_caregiver_headers(cg["id"]))
        validate_error(res, "ERR_INSUFFICIENT_ESCROW")
        after = validate_success(api.get_booking(booking["id"], ADMIN), 200)
        assert after["status"] == "OFFERED"


class TestEscrowImmediateConsistency:
    """Corner consistency_model / confirm_response_reflects_reservation_immediately."""

    def test_confirm_reserves_escrow_visible_immediately(self, api):
        """PRD §3.5: "It reserves that amount by adding it to the family's
        `escrow_reserved_cents` and recomputing `escrow_available_cents`."

        After confirm reserving 13200, an immediate GET of the family shows
        escrow_reserved 13200 and escrow_available 86800.

        Design: Corner/consistency_model/confirm_response_reflects_reservation_immediately
        """
        ctx = setup_confirmed_one_time_booking(
            wallet_balance_cents=100000, num_children=2, required_tier="BASIC",
            agreed_rate_cents=2000, scheduled_start="2026-03-26T08:00:00Z",
            scheduled_end="2026-03-26T14:00:00Z", email_suffix="imm")
        family = validate_success(api.get_family(
            ctx["family"]["id"], make_family_headers(ctx["family"]["id"])), 200)
        assert family["escrow_reserved_cents"] == 13200
        assert family["escrow_available_cents"] == 86800


class TestDepositRecomputesEscrow:
    """Corner cross_cutting / derived_field_escrow_recompute_on_deposit
    and Corner endpoints / deposit_increases_wallet_and_available."""

    def test_deposit_recomputes_available_keeping_reserved(self, api):
        """PRD §2.6: "When a family deposits funds, the deposited amount is added
        to `wallet_balance_cents` and `escrow_available_cents` is recomputed as
        `wallet_balance_cents` minus `escrow_reserved_cents`."

        After reserving 13200, deposit 10000 → wallet 110000, reserved 13200,
        available 96800.

        Design: Corner/cross_cutting_complexity_layers/derived_field_escrow_recompute_on_deposit
        """
        ctx = setup_confirmed_one_time_booking(
            wallet_balance_cents=100000, num_children=2, required_tier="BASIC",
            agreed_rate_cents=2000, scheduled_start="2026-03-26T08:00:00Z",
            scheduled_end="2026-03-26T14:00:00Z", email_suffix="dep")
        family = validate_success(api.deposit(
            ctx["family"]["id"], {"amount_cents": 10000},
            make_family_headers(ctx["family"]["id"])), 200)
        assert family["wallet_balance_cents"] == 110000
        assert family["escrow_reserved_cents"] == 13200
        assert family["escrow_available_cents"] == 96800

    def test_deposit_raises_wallet_and_available_from_zero(self, api):
        """PRD §3.1: "To add money later, a family deposits an `amount_cents` into
        its wallet, raising `wallet_balance_cents` and recomputing
        `escrow_available_cents` accordingly."

        Deposit 5000 into a fresh wallet → wallet 5000, available 5000.

        Design: Corner/endpoints/deposit_increases_wallet_and_available
        """
        set_clock("2026-03-01T00:00:00Z")
        fam = create_family(wallet_balance_cents=0, num_children=1,
                            required_tier="BASIC", email="dp@x.com")
        family = validate_success(api.deposit(
            fam["id"], {"amount_cents": 5000}, make_family_headers(fam["id"])), 200)
        assert family["wallet_balance_cents"] == 5000
        assert family["escrow_available_cents"] == 5000


def _sessions(api, booking_id):
    body = api.list_sessions(ADMIN, params={"booking_id": booking_id}).json()
    return body.get("data", []), body.get("meta", {})
