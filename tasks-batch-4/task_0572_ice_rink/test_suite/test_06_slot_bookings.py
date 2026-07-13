"""Private bookings: the tiered rental/broomball quote, the per-guest-rounded
party charge (provisional vs final), the off-peak baseline, and cancel refund."""
from test_helpers import (
    validate_success, TEST_USERS,
    make_skater_headers, setup_rental_booking, setup_party_booking,
)

RM = TEST_USERS["rink_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/rental_quote_tiered_peak_member_broomball
# ---------------------------------------------------------------------------
def test_broomball_peak_member_resurface_quote(api):
    """PRD §3.6: "The quoted charge is then, in this exact order, the base minus
    the discount plus the broomball equipment fee plus the resurfacing surcharge,
    with the base and discount each rounded before the sum is taken."

    Design: Difficulty/combinatorial_formula/rental_quote_tiered_peak_member_broomball
    """
    # Peak rate 20000 * 1.5h = 30000 base; MEMBER discount 3000; +5000 broomball
    # +4000 resurface => 36000.
    setup = setup_rental_booking(api, "BROOMBALL", "BROOMBALL",
                                 "2026-06-10T18:00:00Z", "2026-06-10T19:30:00Z",
                                 membership="MEMBER", includes_resurface=True)
    assert setup["booking"]["quoted_cents"] == 36000, (
        f"expected quoted 36000, got {setup['booking']['quoted_cents']}")


def test_broomball_peak_member_resurface_charges_wallet(api):
    """PRD §3.6: "At booking time the `quoted_cents` is computed, deducted from the
    host's wallet subject to the `ERR_INSUFFICIENT_FUNDS` guard, and stored as
    `captured_cents`."

    Design: Difficulty/combinatorial_formula/rental_quote_tiered_peak_member_broomball
    """
    setup = setup_rental_booking(api, "BROOMBALL", "BROOMBALL",
                                 "2026-06-10T18:00:00Z", "2026-06-10T19:30:00Z",
                                 membership="MEMBER", includes_resurface=True)
    sk = validate_success(api.get_skater(setup["skater"]["id"], RM))
    assert sk["wallet_credit_cents"] == 64000, (
        f"100000 - 36000 quote expected wallet 64000, got {sk['wallet_credit_cents']}")


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/party_charge_provisional_vs_final_diverge
# ---------------------------------------------------------------------------
def test_party_provisional_quote_on_booked_guests(api):
    """PRD §3.6: "At booking, this charge is computed on `guest_count_booked` and
    stored as the provisional `quoted_cents`; at completion it is recomputed on
    `guest_count_final` to yield `final_cents`, which differs from the provisional
    whenever the headcount changed."

    Design: Difficulty/dual_variant_calc/party_charge_provisional_vs_final_diverge
    """
    # per-guest total = 1010 + round_half_up(1010*0.05=50.5)=51 => 1061.
    # quoted(5) = 5000 + 5*1061 = 10305.
    setup = setup_party_booking(api, guest_count_booked=5)
    assert setup["booking"]["quoted_cents"] == 10305, (
        f"expected provisional quote 10305, got {setup['booking']['quoted_cents']}")


def test_party_final_charge_recomputed_on_completion(api):
    """PRD §3.6: "For a party, completion recomputes `final_cents` from the supplied
    `guest_count_final` using the party charge above, and the wallet is adjusted by
    the difference between `final_cents` and the previously captured amount (a
    positive difference charges more, a negative one refunds), after which
    `captured_cents` is set equal to `final_cents`."

    Design: Difficulty/dual_variant_calc/party_charge_provisional_vs_final_diverge
    """
    # final(3) = 5000 + 3*1061 = 8183. Wallet 100000-10305 (booking) + (10305-8183) = 91817.
    setup = setup_party_booking(api, guest_count_booked=5, clock="2026-06-13T00:00:00Z")
    data = validate_success(api.complete_slot_booking(
        setup["booking"]["id"], {"guest_count_final": 3}, RM))
    assert data["final_cents"] == 8183, f"expected final 8183, got {data['final_cents']}"
    assert data["captured_cents"] == 8183, (
        f"captured must equal final 8183, got {data['captured_cents']}")
    sk = validate_success(api.get_skater(setup["skater"]["id"], RM))
    assert sk["wallet_credit_cents"] == 91817, (
        f"expected wallet 91817 after settlement, got {sk['wallet_credit_cents']}")


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/party_per_guest_rounding_order_pinned
# ---------------------------------------------------------------------------
def test_party_tax_rounded_per_guest_then_summed(api):
    """PRD §3.6: "The charge for a given headcount is computed by first taking the
    tax on a single guest — the `per_guest_cents` multiplied by the `tax_rate`,
    rounded half-up to whole cents — and adding it to the `per_guest_cents` to form
    a per-guest total that already includes tax. The charge is then the
    `base_fee_cents` plus that per-guest total multiplied by the headcount."

    Design: Difficulty/combinatorial_formula/party_per_guest_rounding_order_pinned
    """
    # tax_per_guest = round_half_up(1010*0.05=50.5)=51; per-guest total 1061.
    # quoted(3) = 5000 + 3*1061 = 8183 (per-guest rounding, not 8182 sum-then-tax).
    setup = setup_party_booking(api, guest_count_booked=3)
    assert setup["booking"]["quoted_cents"] == 8183, (
        f"per-guest rounding expected 8183, got {setup['booking']['quoted_cents']}")


def test_party_booking_charges_wallet_per_guest_rounded(api):
    """PRD §3.6: "Tax is therefore rounded once per guest line and then summed
    across guests — never summed first and taxed after."

    Design: Difficulty/combinatorial_formula/party_per_guest_rounding_order_pinned
    """
    setup = setup_party_booking(api, guest_count_booked=3)
    sk = validate_success(api.get_skater(setup["skater"]["id"], RM))
    assert sk["wallet_credit_cents"] == 91817, (
        f"100000 - 8183 quote expected wallet 91817, got {sk['wallet_credit_cents']}")


# ---------------------------------------------------------------------------
# Corner/calculations/rental_quote_offpeak_non_member_baseline
# ---------------------------------------------------------------------------
def test_offpeak_non_member_rental_baseline_quote(api):
    """PRD §3.6: "if the slot's `start_utc` hour is at or after the rink's
    `peak_start_hour_utc`, the rate is the peak rate of 20,000 cents per hour (200
    dollars); otherwise it is the off-peak rate of 12,000 cents per hour (120
    dollars). The base charge is that rate multiplied by the number of hours,
    rounded half-up to whole cents."

    Design: Corner/calculations/rental_quote_offpeak_non_member_baseline
    """
    # 09:00 start < peak 16 -> off-peak 12000 * 1h = 12000; non-member, no resurface.
    setup = setup_rental_booking(api, "RENTAL", "PRIVATE_RENTAL",
                                 "2026-06-11T09:00:00Z", "2026-06-11T10:00:00Z")
    assert setup["booking"]["quoted_cents"] == 12000, (
        f"expected off-peak baseline 12000, got {setup['booking']['quoted_cents']}")
    sk = validate_success(api.get_skater(setup["skater"]["id"], RM))
    assert sk["wallet_credit_cents"] == 88000, (
        f"100000 - 12000 expected wallet 88000, got {sk['wallet_credit_cents']}")


# ---------------------------------------------------------------------------
# Corner/consistency_model/booking_cancel_refund_immediate_visibility
# ---------------------------------------------------------------------------
def test_booking_cancel_refunds_captured_immediately(api):
    """PRD §3.6: "Cancelling a booking — a `Skater` or `RinkManager` action from
    `BOOKED` — refunds the full `captured_cents` back to the host's wallet, zeroes
    `captured_cents`, sets `status` to `CANCELLED`, and increments `version`."

    Design: Corner/consistency_model/booking_cancel_refund_immediate_visibility
    """
    setup = setup_rental_booking(api, "RENTAL", "PRIVATE_RENTAL",
                                 "2026-06-11T09:00:00Z", "2026-06-11T10:00:00Z")
    data = validate_success(api.cancel_slot_booking(
        setup["booking"]["id"], make_skater_headers(setup["skater"]["id"])))
    assert data["status"] == "CANCELLED", f"expected CANCELLED, got {data['status']}"
    assert data["captured_cents"] == 0, f"captured must zero, got {data['captured_cents']}"
    sk = validate_success(api.get_skater(setup["skater"]["id"], RM))
    assert sk["wallet_credit_cents"] == 100000, (
        f"full refund expected wallet 100000, got {sk['wallet_credit_cents']}")
