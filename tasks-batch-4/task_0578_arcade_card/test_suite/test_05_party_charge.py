"""Party charge arithmetic: provisional-vs-final divergence, the three-input
non-linear formula, and the confirm/revert/confirm booking cycle."""
from test_helpers import validate_success, TEST_USERS
from test_helpers.fixtures import (
    set_clock, create_room, create_package, create_member, create_booking,
    confirm_booking, revert_booking, check_in_booking, complete_booking,
    get_booking, issue_extra_wristband, setup_confirmed_booking,
)

COORDINATOR = TEST_USERS["coordinator_headers"]


def _charge_scenario_booking(api, guest_count, start_at, end_at, capacity=20,
                             hourly_rate_cents=8_000):
    set_clock(api, "2026-05-01T10:00:00Z")
    room = create_room(api, capacity=capacity, hourly_rate_cents=hourly_rate_cents)
    package = create_package(api, base_price_cents=20_000, included_guests=10,
                             included_hours=2, included_chip_cents=1_000)
    host = create_member(api)
    booking = create_booking(api, room["id"], package["id"], host["id"], start_at, end_at, guest_count)
    return room, package, host, booking


# --- Difficulty: party_charge_provisional_vs_final ---
def test_provisional_total_computed_at_confirm(api):
    """PRD §3.7: "The provisional total is the package's `base_price_cents`, plus the extra
    guests multiplied by the per-extra-guest surcharge of 1,500 cents ($15.00) each, plus the
    overage hours multiplied by the room's `hourly_rate_cents`. The result is written to
    `provisional_total_cents`."

    Design: Difficulty/dual_variant_calc/party_charge_provisional_vs_final
    """
    room, package, host, booking = _charge_scenario_booking(
        api, guest_count=12, start_at="2026-05-01T14:00:00Z", end_at="2026-05-01T16:00:00Z")
    confirmed = validate_success(api.confirm_party_booking(booking["id"], COORDINATOR))
    assert confirmed["provisional_total_cents"] == 23_000


def test_final_total_diverges_from_provisional_on_actuals(api):
    """PRD §3.7: "The final total is the `base_price_cents`, plus the extra guests times 1,500
    cents each, plus the overage hours times the room's `hourly_rate_cents`, written to
    `final_total_cents`. The final total diverges from the provisional whenever the actuals
    differ from the plan — a different head count of wristbands or a shorter or longer occupied
    window."

    Design: Difficulty/dual_variant_calc/party_charge_provisional_vs_final
    """
    room, package, host, booking = _charge_scenario_booking(
        api, guest_count=12, start_at="2026-05-01T14:00:00Z", end_at="2026-05-01T16:00:00Z")
    bid = booking["id"]
    confirm_booking(api, bid)
    set_clock(api, "2026-05-01T14:00:00Z")
    check_in_booking(api, bid)
    bv1 = get_booking(api, bid)["version"]
    issue_extra_wristband(api, bid, bv1)  # 13th wristband -> actual head count 13
    set_clock(api, "2026-05-01T17:00:00Z")  # 3h actual window
    completed = validate_success(api.complete_party_booking(bid, COORDINATOR))
    assert completed["actual_guest_count"] == 13
    assert completed["final_total_cents"] == 32_500
    assert completed["provisional_total_cents"] != completed["final_total_cents"]


# --- Difficulty: party_charge_three_input_nonlinear ---
def test_three_input_charge_combines_guest_and_hour_overage(api):
    """PRD §3.7: "The provisional total is the package's `base_price_cents`, plus the extra
    guests multiplied by the per-extra-guest surcharge of 1,500 cents ($15.00) each, plus the
    overage hours multiplied by the room's `hourly_rate_cents`."

    Design: Difficulty/combinatorial_formula/party_charge_three_input_nonlinear
    """
    room, package, host, booking = _charge_scenario_booking(
        api, guest_count=15, start_at="2026-05-01T13:00:00Z", end_at="2026-05-01T16:00:00Z",
        capacity=30)
    confirmed = validate_success(api.confirm_party_booking(booking["id"], COORDINATOR))
    assert confirmed["provisional_total_cents"] == 35_500


def test_three_input_charge_transitions_to_confirmed(api):
    """PRD §3.5: "Confirming a `DRAFT` booking (moving `DRAFT → CONFIRMED`) is the pivotal
    step". PRD §3.7: "The result is written to `provisional_total_cents`."

    Design: Difficulty/combinatorial_formula/party_charge_three_input_nonlinear
    """
    room, package, host, booking = _charge_scenario_booking(
        api, guest_count=15, start_at="2026-05-01T13:00:00Z", end_at="2026-05-01T16:00:00Z",
        capacity=30)
    confirmed = validate_success(api.confirm_party_booking(booking["id"], COORDINATOR))
    assert confirmed["status"] == "CONFIRMED"


# --- Difficulty: booking_cycle_confirm_revert_confirm ---
def test_revert_resets_provisional_total_to_null(api):
    """PRD §3.5: "each of those voided wristbands' linked cards has the granted promotional
    chips clawed back ... and the booking's `provisional_total_cents` is reset to null."

    Design: Difficulty/non_linear_state_machine/booking_cycle_confirm_revert_confirm
    """
    ctx = setup_confirmed_booking(api, guest_count=2, included_chip_cents=1_000)
    bid = ctx["booking"]["id"]
    reverted = validate_success(api.revert_party_booking(bid, COORDINATOR))
    assert reverted["provisional_total_cents"] is None


def test_second_confirm_recomputes_provisional_total(api):
    """PRD §3.5: "On a successful confirm the provisional charge is computed and written to
    `provisional_total_cents` (the arithmetic is given in §3.7)".

    Design: Difficulty/non_linear_state_machine/booking_cycle_confirm_revert_confirm
    """
    ctx = setup_confirmed_booking(api, guest_count=2, included_chip_cents=1_000)
    bid = ctx["booking"]["id"]
    revert_booking(api, bid)
    reconfirmed = validate_success(api.confirm_party_booking(bid, COORDINATOR))
    assert reconfirmed["status"] == "CONFIRMED"
    assert reconfirmed["provisional_total_cents"] == 20_000
