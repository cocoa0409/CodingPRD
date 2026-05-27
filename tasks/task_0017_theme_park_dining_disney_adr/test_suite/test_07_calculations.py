"""Calculation correctness — dual-variant credit math, Lightning Lane fee, no-show
fee. Queue A (Difficulty): each instance receives at least two tests."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    set_clock,
    setup_guest_restaurant_plan_session,
    setup_confirmed_reservation,
    create_pending_reservation,
    confirm_reservation,
    drive_guest_no_show_count,
    fetch_dining_plan,
    fetch_reservation,
    fetch_guest,
    list_credit_ledger_for_reservation,
    list_no_show_assessments_for_reservation,
    list_assessments_for_guest,
    patch_party_size_payload,
    create_lightning_lane_payload,
    allocate_lightning_lane_payload,
    make_guest_headers,
    TEST_USERS,
)


# ─── dual_variant_calc: credit_debit_provisional_vs_final ─────────────────

class TestCreditDebitDivergesOnPartySizePatch:
    """Difficulty/dual_variant_calc/credit_debit_provisional_vs_final_diverges_on_party_size_patch

    Two tests anchor this instance: the canonical asserted outcome (test_a) and a
    direct check that the persisted reservation reflects only the FINAL variant's
    party_size after check-in (test_b).
    """

    def test_provisional_then_final_uses_check_in_party_size(self, api):
        """PRD §3.5: "If a party-size patch (§3.4) reduced the head-count between
        confirm and check-in, credits_debited will be less than credits_held, and
        the difference is exactly what the final-variant CreditLedgerEntry records
        as the actual finalised amount."
        PRD §3.5: "On commit, the platform finalises credits: Reservation.credits_debited
        is set to the restaurant's dining_plan_credit_cost multiplied by the
        reservation's party_size at the moment of check-in"

        Design: Difficulty/dual_variant_calc/credit_debit_provisional_vs_final_diverges_on_party_size_patch
        """
        # Setup: confirmed reservation with party_size=4 at credit_cost=1
        guest, restaurant, dp, ps, reservation = setup_confirmed_reservation(
            party_size=4,
            dining_plan_credit_cost=1,
            table_service_credits_initial=10,
            slot_start_utc="2026-02-15T18:00:00Z",
        )
        assert reservation["credits_held"] == 4
        # Patch party_size down to 2 (still within free-cancel window — clock at 2026-01-15)
        api.patch_party_size(
            reservation["id"],
            patch_party_size_payload(party_size=2),
            make_guest_headers(guest["id"]),
        )
        patched = fetch_reservation(reservation["id"], guest["id"])
        assert patched["credits_held"] == 2
        # Advance to check-in window and activate session.
        set_clock("2026-02-15T17:45:00Z")
        api.activate_park_session(ps["id"], make_guest_headers(guest["id"]))
        # Final-variant check-in.
        api.check_in_reservation(reservation["id"], make_guest_headers(guest["id"]))
        checked = fetch_reservation(reservation["id"], guest["id"])
        assert checked["status"] == "CHECKED_IN"
        assert checked["credits_debited"] == 2
        assert checked["credits_held"] == 0
        plan_after = fetch_dining_plan(dp["id"], guest["id"])
        assert plan_after["table_service_credits_remaining"] == 8
        assert plan_after["table_service_credits_held"] == 0

    def test_debit_ledger_entry_records_final_amount(self, api):
        """PRD §3.4: "appends a CreditLedgerEntry with entry_type HOLD and a
        positive credits_delta equal to the held quantity (the convention is that
        a positive credits_delta on HOLD or DEBIT decreases the plan's
        table_service_credits_remaining or its free pool, and a negative
        credits_delta on RELEASE or REFUND increases it)"
        PRD §3.5: "a CreditLedgerEntry of entry_type DEBIT is appended with a
        positive credits_delta equal to credits_debited"

        Design: Difficulty/dual_variant_calc/credit_debit_provisional_vs_final_diverges_on_party_size_patch
        """
        guest, restaurant, dp, ps, reservation = setup_confirmed_reservation(
            party_size=4,
            dining_plan_credit_cost=1,
            table_service_credits_initial=10,
            slot_start_utc="2026-02-15T18:00:00Z",
        )
        api.patch_party_size(
            reservation["id"],
            patch_party_size_payload(party_size=2),
            make_guest_headers(guest["id"]),
        )
        set_clock("2026-02-15T17:45:00Z")
        api.activate_park_session(ps["id"], make_guest_headers(guest["id"]))
        api.check_in_reservation(reservation["id"], make_guest_headers(guest["id"]))
        entries = list_credit_ledger_for_reservation(reservation["id"])
        debit_entries = [e for e in entries if e["entry_type"] == "DEBIT"]
        assert len(debit_entries) >= 1
        # FINAL variant: credits_delta records the actual finalised amount.
        assert any(e["credits_delta"] == 2 for e in debit_entries), \
            f"Expected DEBIT entry with credits_delta=2, got {debit_entries}"


# ─── dual_variant_calc: ll_per_seat_round_vs_sum_round ────────────────────

class TestLightningLanePerSeatRoundFirst:
    """Difficulty/dual_variant_calc/lightning_lane_fee_per_seat_round_vs_sum_round_diverges"""

    def test_multi_pass_epcot_party_size_3_pinned_ordering(self, api):
        """PRD §3.7: "the platform rounds it to integer cents using the round-half-up
        rule. That single per-seat rounded amount is then multiplied by the integer
        party_size, with no further rounding, to give the fee_cents stored on the
        add-on."
        PRD §3.7: "As with the no-show calculation, the rounding must happen once at
        the per-seat boundary — rounding after the party-size multiply diverges by
        up to (party_size − 1) cents per booking and is the wrong order."

        Design: Difficulty/dual_variant_calc/lightning_lane_fee_per_seat_round_vs_sum_round_diverges
        """
        # MULTI_PASS = 2500, EPCOT mult = 1.075, non-character, party_size = 3.
        # per_seat decimal = 2500 * 1.075 = 2687.5 → round to 2688; fee = 8064.
        guest, restaurant, dp, ps, reservation = setup_confirmed_reservation(
            party_size=3,
            dining_plan_credit_cost=1,
            is_character_dining=False,
            park_code="EPCOT",
            opening_local_time="11:00",
            closing_local_time="22:00",
            table_service_credits_initial=10,
        )
        ll_payload = create_lightning_lane_payload(
            reservation_id=reservation["id"], tier="MULTI_PASS",
        )
        ll_res = api.create_lightning_lane(ll_payload, make_guest_headers(guest["id"]))
        ll = validate_success(ll_res, expected_status=201)
        alloc_res = api.allocate_lightning_lane(
            ll["id"],
            allocate_lightning_lane_payload(reservation["version"]),
            make_guest_headers(guest["id"]),
        )
        allocated = validate_success(alloc_res, expected_status=200)
        assert allocated["status"] == "ALLOCATED"
        assert allocated["fee_cents"] == 8064
        # PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
        assert allocated["redemption_window_end_utc"] == "2026-02-15T19:30:00.000Z"

    def test_per_seat_decimal_with_integer_result_no_divergence(self, api):
        """PRD §3.7: "The platform looks up a per-tier base in integer cents —
        SINGLE_PASS is 1500 cents, MULTI_PASS is 2500 cents — and adds a per-seat
        character uplift of 500 cents when the restaurant is character dining, 0
        otherwise. The sum is multiplied by a park-specific decimal multiplier:
        1.175 at MAGIC_KINGDOM, 1.075 at EPCOT, 1.000 at ANIMAL_KINGDOM, and 1.100
        at HOLLYWOOD_STUDIOS."
        PRD §3.7: "That single per-seat rounded amount is then multiplied by the
        integer party_size, with no further rounding, to give the fee_cents stored
        on the add-on."

        Companion to the divergence test: when the per-seat decimal is already
        integer (SINGLE_PASS MAGIC_KINGDOM character × 4 → 2350.0 per seat), both
        orderings agree, and the persisted fee_cents = 9400. Confirms the formula
        is applied (not just that "rounding works").

        Design: Difficulty/dual_variant_calc/lightning_lane_fee_per_seat_round_vs_sum_round_diverges
        """
        guest, restaurant, dp, ps, reservation = setup_confirmed_reservation(
            party_size=4,
            dining_plan_credit_cost=2,
            is_character_dining=True,
            park_code="MAGIC_KINGDOM",
            opening_local_time="08:00",
            closing_local_time="22:00",
            table_service_credits_initial=20,
            tier="DELUXE",
        )
        ll_payload = create_lightning_lane_payload(
            reservation_id=reservation["id"], tier="SINGLE_PASS",
        )
        ll = validate_success(
            api.create_lightning_lane(ll_payload, make_guest_headers(guest["id"])),
            expected_status=201,
        )
        allocated = validate_success(
            api.allocate_lightning_lane(
                ll["id"],
                allocate_lightning_lane_payload(reservation["version"]),
                make_guest_headers(guest["id"]),
            ),
            expected_status=200,
        )
        assert allocated["fee_cents"] == 9400


# ─── combinatorial_formula: LL fee mode (a) ──────────────────────────────

class TestLightningLaneFeeCombinatorial:
    """Difficulty/combinatorial_formula/lightning_lane_fee_tier_park_character_combinatorial_mode_a"""

    def test_single_pass_magic_kingdom_character_party_4(self, api):
        """PRD §3.7: "The fee calculation takes four inputs: the restaurant's
        is_character_dining flag, the restaurant's park_code, the add-on's tier,
        and the reservation's party_size at the moment of allocation. The platform
        looks up a per-tier base in integer cents — SINGLE_PASS is 1500 cents,
        MULTI_PASS is 2500 cents — and adds a per-seat character uplift of 500
        cents when the restaurant is character dining, 0 otherwise. The sum is
        multiplied by a park-specific decimal multiplier: 1.175 at MAGIC_KINGDOM,
        1.075 at EPCOT, 1.000 at ANIMAL_KINGDOM, and 1.100 at HOLLYWOOD_STUDIOS."

        Design: Difficulty/combinatorial_formula/lightning_lane_fee_tier_park_character_combinatorial_mode_a
        """
        # (1500 + 500) * 1.175 = 2350.0 per seat (integer); × 4 = 9400.
        guest, restaurant, dp, ps, reservation = setup_confirmed_reservation(
            party_size=4,
            dining_plan_credit_cost=2,
            is_character_dining=True,
            park_code="MAGIC_KINGDOM",
            opening_local_time="08:00",
            closing_local_time="22:00",
            table_service_credits_initial=20,
            tier="DELUXE",
        )
        ll = validate_success(
            api.create_lightning_lane(
                create_lightning_lane_payload(reservation_id=reservation["id"], tier="SINGLE_PASS"),
                make_guest_headers(guest["id"]),
            ),
            expected_status=201,
        )
        allocated = validate_success(
            api.allocate_lightning_lane(
                ll["id"],
                allocate_lightning_lane_payload(reservation["version"]),
                make_guest_headers(guest["id"]),
            ),
            expected_status=200,
        )
        assert allocated["fee_cents"] == 9400
        assert allocated["status"] == "ALLOCATED"

    def test_animal_kingdom_non_character_multi_pass_party_2(self, api):
        """PRD §3.7: "The fee calculation takes four inputs: the restaurant's
        is_character_dining flag, the restaurant's park_code, the add-on's tier,
        and the reservation's party_size at the moment of allocation. ... The sum
        is multiplied by a park-specific decimal multiplier: ... 1.000 at
        ANIMAL_KINGDOM"
        PRD §3.7: "That single per-seat rounded amount is then multiplied by the
        integer party_size, with no further rounding, to give the fee_cents stored
        on the add-on."

        Companion combinatorial point: MULTI_PASS / ANIMAL_KINGDOM (mult=1.000) /
        non-character / party_size=2 → (2500 + 0) * 1.000 = 2500 per seat → 5000.

        Design: Difficulty/combinatorial_formula/lightning_lane_fee_tier_park_character_combinatorial_mode_a
        """
        guest, restaurant, dp, ps, reservation = setup_confirmed_reservation(
            party_size=2,
            dining_plan_credit_cost=1,
            is_character_dining=False,
            park_code="ANIMAL_KINGDOM",
            opening_local_time="08:00",
            closing_local_time="22:00",
            table_service_credits_initial=10,
        )
        ll = validate_success(
            api.create_lightning_lane(
                create_lightning_lane_payload(reservation_id=reservation["id"], tier="MULTI_PASS"),
                make_guest_headers(guest["id"]),
            ),
            expected_status=201,
        )
        allocated = validate_success(
            api.allocate_lightning_lane(
                ll["id"],
                allocate_lightning_lane_payload(reservation["version"]),
                make_guest_headers(guest["id"]),
            ),
            expected_status=200,
        )
        assert allocated["fee_cents"] == 5000


# ─── combinatorial_formula: no_show_fee mode (b) ─────────────────────────

class TestNoShowFeeNestedRoundingPerSeatFirst:
    """Difficulty/combinatorial_formula/no_show_fee_nested_rounding_per_seat_first_mode_b"""

    def test_tier2_strike_2_non_character_party_2_yields_5912(self, api):
        """PRD §3.5: "It then selects a repeat-offender multiplier on a tiered
        scale: if the post-increment strike count is 1, the multiplier is 1.0; if
        it is 2 or 3, the multiplier is 1.075; if it is 4 or greater, the
        multiplier is 1.250. The platform multiplies the per-seat-pre-multiplier
        amount by the multiplier — this can produce a fractional-cent decimal —
        and rounds that single per-seat figure to integer cents using the
        round-half-up rule. That rounded per-seat amount is then multiplied by
        the integer party_size, with no further rounding, to obtain
        total_amount_cents. The order matters: rounding happens once per seat and
        the multiplication by party_size is pure integer arithmetic."

        Design: Difficulty/combinatorial_formula/no_show_fee_nested_rounding_per_seat_first_mode_b
        """
        # Build a guest with one prior NO_SHOW (strike_count=1 BEFORE the trigger),
        # then trigger reservation no-show: strike_after=2 → tier2 (×1.075).
        # base=2750 cents, non-character, party=2 → per_seat = 2956.25 → round 2956
        # → total = 2956 * 2 = 5912.
        set_clock("2026-01-15T12:00:00Z")
        guest, restaurant, dp, ps = setup_guest_restaurant_plan_session(
            park_code="MAGIC_KINGDOM",
            no_show_base_fee_cents=2750,
            is_character_dining=False,
            opening_local_time="11:00",
            closing_local_time="22:00",
            table_service_credits_initial=10,
            visit_date="2026-02-14",  # used only for setup_guest_restaurant_plan_session ParkSession; we ignore it
        )
        # Drive guest to one prior no-show using a single visit_date.
        drive_guest_no_show_count(
            guest, restaurant, dp, num_strikes=1,
            park_code="MAGIC_KINGDOM", base_date="2026-02-10",
        )
        guest_after_strikes = fetch_guest(guest["id"])
        assert guest_after_strikes["no_show_strike_count"] == 1
        # Fresh ParkSession + reservation for visit 2026-02-15.
        set_clock("2026-01-15T12:00:00Z")
        from test_helpers import create_park_session
        ps2 = create_park_session(guest["id"], park_code="MAGIC_KINGDOM", visit_date="2026-02-15")
        pending = create_pending_reservation(
            guest, restaurant, ps2, dp,
            slot_start_utc="2026-02-15T18:00:00Z", party_size=2,
        )
        confirm_reservation(pending, guest["id"])
        # Trigger NO_SHOW.
        set_clock("2026-02-15T19:00:00Z")
        marked = validate_success(
            api.mark_no_show_reservation(pending["id"], TEST_USERS["platform_admin_headers"]),
            expected_status=200,
        )
        assert marked["status"] == "NO_SHOW"
        guest_after = fetch_guest(guest["id"])
        assert guest_after["no_show_strike_count"] == 2
        # Find the assessment for this reservation.
        assessments = list_no_show_assessments_for_reservation(pending["id"])
        assert len(assessments) >= 1
        a = [x for x in assessments if x["reservation_id"] == pending["id"]][0]
        assert a["base_amount_cents"] == 5500
        assert a["character_surcharge_cents"] == 0
        assert a["total_amount_cents"] == 5912

    def test_assessment_repeat_offender_multiplier_recorded(self, api):
        """PRD §3.5: "The assessment additionally persists base_amount_cents equal
        to the per-seat base times party_size, character_surcharge_cents equal to
        the per-seat surcharge times party_size, the chosen
        repeat_offender_multiplier stored verbatim as a decimal, and
        total_amount_cents as computed above."

        Design: Difficulty/combinatorial_formula/no_show_fee_nested_rounding_per_seat_first_mode_b
        """
        set_clock("2026-01-15T12:00:00Z")
        guest, restaurant, dp, ps = setup_guest_restaurant_plan_session(
            park_code="MAGIC_KINGDOM",
            no_show_base_fee_cents=2750,
            is_character_dining=False,
            opening_local_time="11:00",
            closing_local_time="22:00",
            table_service_credits_initial=10,
            visit_date="2026-02-14",
        )
        drive_guest_no_show_count(
            guest, restaurant, dp, num_strikes=1,
            park_code="MAGIC_KINGDOM", base_date="2026-02-10",
        )
        set_clock("2026-01-15T12:00:00Z")
        from test_helpers import create_park_session
        ps2 = create_park_session(guest["id"], park_code="MAGIC_KINGDOM", visit_date="2026-02-15")
        pending = create_pending_reservation(
            guest, restaurant, ps2, dp,
            slot_start_utc="2026-02-15T18:00:00Z", party_size=2,
        )
        confirm_reservation(pending, guest["id"])
        set_clock("2026-02-15T19:00:00Z")
        api.mark_no_show_reservation(pending["id"], TEST_USERS["platform_admin_headers"])
        assessments = list_no_show_assessments_for_reservation(pending["id"])
        a = [x for x in assessments if x["reservation_id"] == pending["id"]][0]
        # Decimal multiplier stored verbatim, equal to 1.075 (tier2).
        assert float(a["repeat_offender_multiplier"]) == pytest.approx(1.075, abs=1e-6)
