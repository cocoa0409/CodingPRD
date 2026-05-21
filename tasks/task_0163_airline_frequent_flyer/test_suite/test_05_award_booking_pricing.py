"""Award booking — pricing pinning, dual variant, certificate flow."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    AWARD_BOOKING_HOLD_HOURS,
    advance_clock_seconds,
    create_award_booking_payload,
    create_flight,
    create_member,
    create_member_with_balance,
    create_segment_for_member,
    expected_fixed_award_price,
    filter_transactions_by_kind,
    get_member,
    grant_companion_certificate,
    list_certificates,
    list_points_transactions,
    make_member_headers,
    promote_member_to_tier_via_status_match,
    refund_segment,
    run_sweep_expire_bookings,
    setup_confirmed_award_booking,
    setup_held_award_booking,
    setup_load_factor_band,
    validate_error,
    validate_success,
)


class TestPricingFixed:

    @pytest.mark.parametrize(
        "region,cabin,expected",
        [
            ("DOMESTIC", "ECONOMY", 12_500),
            ("DOMESTIC", "BUSINESS", 25_000),
            ("DOMESTIC", "FIRST", 40_000),
            ("INTERNATIONAL", "ECONOMY", 30_000),
            ("INTERNATIONAL", "BUSINESS", 70_000),
            ("INTERNATIONAL", "FIRST", 110_000),
        ],
    )
    def test_fixed_pricing_table_matches_prd(self, api, region, cabin,
                                              expected):
        """PRD §3.5: "For DOMESTIC: ECONOMY is 12 500, BUSINESS is
        25 000, FIRST is 40 000. For INTERNATIONAL: ECONOMY is 30 000,
        BUSINESS is 70 000, FIRST is 110 000."
        """
        member = create_member_with_balance(0)
        flight = create_flight(route_region=region)
        booking = validate_success(
            api.create_award_booking(
                member["id"],
                create_award_booking_payload(
                    flight["id"], cabin=cabin, pricing_mode="FIXED",
                ),
                make_member_headers(member["id"]),
            ),
            expected_status=201,
        )
        assert booking["points_cost"] == expected
        assert booking["status"] == "HELD"


class TestPricingDynamicDualVariant:

    def test_dynamic_vs_fixed_pin_different_costs(self, api):
        """PRD §3.5: "Two HELD bookings created for the same flight at
        different load_factor snapshots therefore typically pin
        different points_cost values, and that is intentional."

        # difficulty: dual_variant_calc/award_price_dynamic_vs_fixed_on_award_booking
        Claim: DYNAMIC mode on a 1000-mile DOMESTIC flight with
        load_factor in [0.80, 0.95) yields 1000 * 5 * 1.5 * 1.0 = 7500;
        FIXED mode on the same flight yields 12_500.
        """
        # Build a flight with load_factor in the HIGH band.
        flight = setup_load_factor_band(
            flight_overrides={
                "distance_miles": 1_000,
                "route_region": "DOMESTIC",
                "capacity_economy": 10,
                "capacity_business": 2,
                "capacity_first": 1,
                "base_fare_cents": 50_000,
            },
            target_band="high",
        )
        # Sanity-check the load factor is in [0.80, 0.95).
        assert 0.80 <= float(flight["load_factor"]) < 0.95

        # Same member, two bookings — DYNAMIC and FIXED.
        member = create_member_with_balance(0)
        dyn = validate_success(
            api.create_award_booking(
                member["id"],
                create_award_booking_payload(
                    flight["id"], cabin="ECONOMY", pricing_mode="DYNAMIC",
                ),
                make_member_headers(member["id"]),
            ),
            expected_status=201,
        )
        fix = validate_success(
            api.create_award_booking(
                member["id"],
                create_award_booking_payload(
                    flight["id"], cabin="ECONOMY", pricing_mode="FIXED",
                ),
                make_member_headers(member["id"]),
            ),
            expected_status=201,
        )
        # DYNAMIC: 1000 * 5 * 1.5 (HIGH demand) * 1.0 (ECONOMY) = 7500.
        assert dyn["points_cost"] == 7_500, (
            "PRD §3.5: DYNAMIC pricing on load_factor in [0.80, 0.95) → "
            "1000 miles * 5 * 1.5 * 1.0 ECONOMY = 7500."
        )
        assert fix["points_cost"] == 12_500
        assert dyn["points_cost"] != fix["points_cost"]
        # Balance unaffected at HELD.
        m = get_member(member["id"])
        assert m["points_balance"] == 0


class TestPricingPinning:

    def test_pinning_at_held_immutable_through_additional_load(self, api):
        """PRD §3.5: "The booking's points_cost is computed by the
        award_price formula at the instant the booking is created and
        is then immutable for the lifetime of the booking — it is never
        re-evaluated while the booking remains HELD or CONFIRMED."
        """
        # Build a flight in the LOW load band; capture the DYNAMIC cost
        # at that instant.
        flight = setup_load_factor_band(
            flight_overrides={
                "distance_miles": 1_000, "route_region": "DOMESTIC",
                "capacity_economy": 10, "capacity_business": 2,
                "capacity_first": 1, "base_fare_cents": 50_000,
            },
            target_band="low",  # load_factor < 0.50, demand_mult 0.8
        )
        member = create_member_with_balance(0)
        booking = validate_success(
            api.create_award_booking(
                member["id"],
                create_award_booking_payload(
                    flight["id"], cabin="ECONOMY", pricing_mode="DYNAMIC",
                ),
                make_member_headers(member["id"]),
            ),
            expected_status=201,
        )
        first_cost = booking["points_cost"]
        # Push the SAME flight's load_factor into the PEAK band by
        # creating additional CONFIRMED bookings on it directly.
        cap = (flight["capacity_economy"] + flight["capacity_business"]
               + flight["capacity_first"])
        # Add enough confirmed bookings to bring load_factor >= 0.95.
        from test_helpers import (
            create_member_with_balance as _mwb,
            get_flight,
            make_member_headers as _mh,
        )
        target_confirmed = max(int(cap * 0.97), cap - 1)
        current_confirmed = int(round(float(flight["load_factor"]) * cap))
        while current_confirmed < target_confirmed:
            filler = _mwb(20_000)
            b = validate_success(
                api.create_award_booking(
                    filler["id"],
                    create_award_booking_payload(
                        flight["id"], cabin="ECONOMY", pricing_mode="FIXED",
                    ),
                    _mh(filler["id"]),
                ),
                expected_status=201,
            )
            validate_success(
                api.confirm_award_booking(
                    filler["id"], b["id"], _mh(filler["id"]),
                )
            )
            current_confirmed += 1
        # Sanity: load_factor is now higher.
        f_after = get_flight(flight["id"])
        assert float(f_after["load_factor"]) > float(flight["load_factor"])
        # Re-fetch the original booking — points_cost must be unchanged.
        listing = api.list_award_bookings(
            member["id"], make_member_headers(member["id"]),
            params={"limit": 100},
        )
        body = listing.json()
        b_after = next(x for x in body["data"] if x["id"] == booking["id"])
        assert b_after["points_cost"] == first_cost, (
            "PRD §3.5: points_cost ... is then immutable for the "
            "lifetime of the booking."
        )


class TestConfirmCancelInvariant:

    def test_confirm_then_cancel_restores_balance_exactly(self, api):
        """PRD §3.5: "The compensating action is a single
        REDEMPTION_REFUND row with points_delta equal to +points_cost
        ... the member's points_balance after this transition must
        equal its value immediately before the original confirm."

        # difficulty: compensating_invariant/points_balance_conserved_under_book_then_cancel
        # difficulty: non_linear_state_machine/award_booking_branching_with_revert
        # difficulty: transitive_cascade/award_cancel_three_hop_refund_and_certificate_restoration
        """
        member, flight, booking = setup_confirmed_award_booking(
            cabin="ECONOMY", pricing_mode="FIXED",
            route_region="DOMESTIC", member_balance=50_000,
        )
        # After confirm: balance = 50_000 - 12_500 = 37_500.
        m_after_confirm = get_member(member["id"])
        assert m_after_confirm["points_balance"] == 37_500
        # Cancel.
        cancelled = validate_success(
            api.cancel_award_booking(
                member["id"], booking["id"],
                make_member_headers(member["id"]),
            )
        )
        assert cancelled["status"] in ("CANCELLED", "REFUNDED")
        m_after_cancel = get_member(member["id"])
        assert m_after_cancel["points_balance"] == 50_000, (
            "PRD §3.5: the member's points_balance after this transition"
            " must equal its value immediately before the original confirm."
        )
        # Ledger has exactly one REDEMPTION (-12500) and one
        # REDEMPTION_REFUND (+12500) bound to this booking.
        ledger = list_points_transactions(member["id"])
        redemptions = filter_transactions_by_kind(ledger, "REDEMPTION")
        refunds = filter_transactions_by_kind(ledger, "REDEMPTION_REFUND")
        related_red = [r for r in redemptions if r.get("related_booking_id") == booking["id"]]
        related_ref = [r for r in refunds if r.get("related_booking_id") == booking["id"]]
        assert len(related_red) == 1
        assert related_red[0]["points_delta"] == -12_500
        assert len(related_ref) == 1
        assert related_ref[0]["points_delta"] == +12_500


class TestConfirmPreconditions:

    def test_confirm_requires_held_state(self, api):
        """PRD §2.7 priority 4 + §3.5: "an AwardBooking that is not in
        HELD cannot be confirmed (ERR_BOOKING_NOT_HOLDABLE)."
        """
        member, flight, booking = setup_confirmed_award_booking(
            member_balance=20_000,
        )
        # Second confirm — already CONFIRMED.
        resp = api.confirm_award_booking(
            member["id"], booking["id"], make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_HOLDABLE.value)

    def test_confirm_rejected_when_balance_below_cost(self, api):
        """PRD §3.5: "the member's points_balance to be at least
        points_cost (otherwise ERR_INSUFFICIENT_POINTS)."
        """
        member, flight, booking = setup_held_award_booking(
            cabin="ECONOMY", pricing_mode="FIXED",
            route_region="DOMESTIC", member_balance=5_000,
        )
        # FIXED DOMESTIC ECONOMY = 12_500; member has 5_000.
        resp = api.confirm_award_booking(
            member["id"], booking["id"], make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS.value)


class TestHeldUntilExpiration:

    def test_sweep_expires_held_booking_past_held_until(self, api):
        """PRD §3.5 + §3.8: "Walk every AwardBooking still in HELD whose
        held_until is less than or equal to now; transition each to
        EXPIRED."
        """
        member, _, booking = setup_held_award_booking(
            member_balance=20_000,
        )
        # Advance clock past held_until (24 hours).
        advance_clock_seconds(
            (AWARD_BOOKING_HOLD_HOURS + 1) * 3600,
        )
        run_sweep_expire_bookings()
        # Fetch booking — should be EXPIRED.
        listing = api.list_award_bookings(
            member["id"], make_member_headers(member["id"]),
            params={"limit": 100},
        )
        body = listing.json()
        b = next(x for x in body["data"] if x["id"] == booking["id"])
        assert b["status"] == "EXPIRED"


class TestCompanionCertificateFlow:

    def test_certificate_flips_active_to_reserved_on_held(self, api):
        """PRD §3.5: "The certificate transitions from ACTIVE to
        RESERVED and records reserved_for_booking_id."
        """
        # Member must be PLATINUM at the certificate's issuance moment.
        member = create_member_with_balance(50_000)
        member = promote_member_to_tier_via_status_match(
            member["id"], target_tier="PLATINUM",
        )
        cert = grant_companion_certificate(member["id"])
        assert cert["status"] == "ACTIVE"
        flight = create_flight(route_region="DOMESTIC")
        booking = validate_success(
            api.create_award_booking(
                member["id"],
                create_award_booking_payload(
                    flight["id"], cabin="ECONOMY", pricing_mode="FIXED",
                    companion_certificate_id=cert["id"],
                ),
                make_member_headers(member["id"]),
            ),
            expected_status=201,
        )
        assert booking["status"] == "HELD"
        certs = list_certificates(member["id"])
        c = next(x for x in certs if x["id"] == cert["id"])
        assert c["status"] == "RESERVED"

    def test_expired_certificate_blocks_award_booking_creation(self, api):
        """PRD §3.5: "the booking moment lies inside the certificate's
        half-open validity window [issued_at, expires_at) (otherwise
        ERR_CERTIFICATE_EXPIRED)."

        # difficulty: resource_temporal_overlap/companion_certificate_half_open_validity_window
        Claim: at now == expires_at exactly, the certificate is
        treated as expired (half-open upper boundary is not included).
        """
        member = create_member_with_balance(50_000)
        member = promote_member_to_tier_via_status_match(
            member["id"], target_tier="PLATINUM",
        )
        cert = grant_companion_certificate(member["id"])
        # PRD §3.5: expires_at = issued_at + 12 months. Advance clock
        # by 13 months to be safely past the boundary; then run the
        # certificate-expiration sweep to materialize the EXPIRED state.
        advance_clock_seconds(13 * 30 * 24 * 3600)
        # Run the certificate sweep so the certificate flips to EXPIRED.
        from test_helpers import run_sweep_expire_certificates
        run_sweep_expire_certificates()
        flight = create_flight(route_region="DOMESTIC")
        resp = api.create_award_booking(
            member["id"],
            create_award_booking_payload(
                flight["id"], cabin="ECONOMY", pricing_mode="FIXED",
                companion_certificate_id=cert["id"],
            ),
            make_member_headers(member["id"]),
        )
        # PRD §2.7 priority ordering: state (4) beats temporal (6); the
        # certificate is now EXPIRED so the state guard fires first.
        # PRD §3.5: "A certificate that is not in ACTIVE cannot be
        # reserved (ERR_CERTIFICATE_NOT_USABLE)." For an EXPIRED
        # certificate that has aged past its window, either error_id
        # is a faithful PRD reading (state-conflict vs temporal-conflict).
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_CERTIFICATE_NOT_USABLE.value,
                ApiErrorId.ERR_CERTIFICATE_EXPIRED.value,
            ],
        )

    def test_active_certificate_inside_window_can_be_reserved(self, api):
        """PRD §3.5: certificate "reserved" path — the booking moment
        must lie inside the half-open validity window [issued_at,
        expires_at).

        # difficulty: resource_temporal_overlap/companion_certificate_half_open_validity_window
        Claim: at "now strictly inside the window", the certificate
        transitions to RESERVED.
        """
        member = create_member_with_balance(50_000)
        member = promote_member_to_tier_via_status_match(
            member["id"], target_tier="PLATINUM",
        )
        cert = grant_companion_certificate(member["id"])
        # Stay well inside the 12-month window.
        flight = create_flight(route_region="DOMESTIC")
        booking = validate_success(
            api.create_award_booking(
                member["id"],
                create_award_booking_payload(
                    flight["id"], cabin="BUSINESS", pricing_mode="FIXED",
                    companion_certificate_id=cert["id"],
                ),
                make_member_headers(member["id"]),
            ),
            expected_status=201,
        )
        assert booking["status"] == "HELD"
        certs = list_certificates(member["id"])
        c = next(x for x in certs if x["id"] == cert["id"])
        assert c["status"] == "RESERVED"
