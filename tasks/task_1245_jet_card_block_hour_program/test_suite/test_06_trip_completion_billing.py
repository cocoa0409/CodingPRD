"""Trip completion: per-leg billing, swap ratios, ledger/escrow/invoice cascade."""
import pytest

from test_helpers import (
    TEST_USERS,
    assert_escrow_conservation,
    complete_trip,
    confirm_trip,
    create_aircraft,
    create_trip,
    depart_trip,
    dispatch_trip,
    fly_trip,
    get_aircraft,
    get_card,
    get_escrow,
    get_ledger_entries,
    get_trip_invoice,
    get_trip_legs,
    setup_active_card,
)

OPS = TEST_USERS["ops_headers"]


def _flown_setup(program_code="CALC1", tail="N333LT", **program_overrides):
    """Active card + aircraft + confirmed/dispatched/departed one-way trip.
    Returns (member, card, aircraft, trip_dict)."""
    _, member, card = setup_active_card(program_overrides={
        "program_code": program_code, **program_overrides
    })
    aircraft = create_aircraft(tail_number=tail,
                               category=program_overrides.get("_aircraft_category", "LIGHT"))
    trip = create_trip(card["id"], member["id"],
                       requested_category=program_overrides.get("_requested_category", "LIGHT"))
    confirm_trip(trip["id"], member["id"])
    dispatch_trip(trip["id"], aircraft["id"])
    depart_trip(trip["id"])
    return member, card, aircraft, trip


def test_billable_hours_taxi_addition(api):
    """PRD §3.7: "The raw minutes for a leg are its `actual_block_minutes` plus the
    program's `taxi_minutes_per_leg`. The leg's `billable_minutes` is that raw figure
    floored at the program's `min_billable_minutes_per_leg` — a leg whose block-plus-taxi
    falls short of the floor bills at the floor. `billable_hours` is `billable_minutes`
    divided by 60, rounded half-up to 2 decimal places."

    Design: Corner/calculations/billable_hours_taxi_addition_correct
    """
    _, _, _, trip = _flown_setup()
    complete_trip(trip["id"], 108)
    leg = get_trip_legs(trip["id"])[0]
    assert leg["billable_minutes"] == 120, (
        f"108 block + 12 taxi must bill 120 minutes, got {leg['billable_minutes']}"
    )
    assert leg["billable_hours"] == pytest.approx(2.00, abs=0.005), (
        f"120 minutes must be 2.00 hours, got {leg['billable_hours']}"
    )


def test_downgrade_swap_reduces_debit(api):
    """PRD §3.7: "When the dispatched category is a lower tier than requested — a
    downgrade swap — the multiplier is the program's `swap_ratio_to_lower`, which is
    below 1.0, so the member is debited fewer hours than flown. ... Each leg's
    `debited_hours` is its `billable_hours` times its `swap_multiplier`, rounded half-up
    to 2 decimal places."
    PRD §3.6: "`swap_applied` records whether the dispatched aircraft's category differs
    from `requested_category`".

    Design: Corner/calculations/downgrade_swap_reduces_debit
    """
    _, member, card = setup_active_card(program_overrides={
        "program_code": "CALC2",
        "aircraft_category": "MIDSIZE",
        "hours_purchased": 25,
        "purchase_price_cents": 15_000_000,
        "swap_ratio_to_lower": 0.85,
        "swap_ratio_to_higher": 1.30,
    })
    aircraft = create_aircraft(tail_number="N444LT", category="LIGHT")
    trip = create_trip(card["id"], member["id"], requested_category="MIDSIZE")
    confirm_trip(trip["id"], member["id"])
    dispatch_trip(trip["id"], aircraft["id"])
    depart_trip(trip["id"])
    completed = complete_trip(trip["id"], 108)
    assert completed["swap_applied"] is True, (
        "LIGHT dispatch against a MIDSIZE request must set swap_applied"
    )
    leg = get_trip_legs(trip["id"])[0]
    assert leg["billable_hours"] == pytest.approx(2.00, abs=0.005)
    assert leg["swap_multiplier"] == pytest.approx(0.85, abs=0.0001), (
        f"downgrade swap must apply swap_ratio_to_lower 0.85, got {leg['swap_multiplier']}"
    )
    assert leg["debited_hours"] == pytest.approx(1.70, abs=0.005), (
        f"2.00 hours x 0.85 must debit 1.70 hours, got {leg['debited_hours']}"
    )


def test_billable_minutes_floored_below_minimum(api):
    """PRD §3.7: "The leg's `billable_minutes` is that raw figure floored at the
    program's `min_billable_minutes_per_leg` — a leg whose block-plus-taxi falls short of
    the floor bills at the floor. `billable_hours` is `billable_minutes` divided by 60,
    rounded half-up to 2 decimal places."

    Design: Difficulty/boundary_precision_check/min_billable_minutes_floor_exact_boundary
    """
    _, _, _, trip = _flown_setup(program_code="BOUND1", tail="N600LT")
    complete_trip(trip["id"], 47)  # 47 + 12 = 59 < 60 floor
    leg = get_trip_legs(trip["id"])[0]
    assert leg["billable_minutes"] == 60, (
        f"59 raw minutes must floor to 60, got {leg['billable_minutes']}"
    )
    assert leg["billable_hours"] == pytest.approx(1.00, abs=0.005)


def test_billable_minutes_at_exact_minimum_boundary(api):
    """PRD §3.7: "The leg's `billable_minutes` is that raw figure floored at the
    program's `min_billable_minutes_per_leg` — a leg whose block-plus-taxi falls short of
    the floor bills at the floor. `billable_hours` is `billable_minutes` divided by 60,
    rounded half-up to 2 decimal places."

    Design: Difficulty/boundary_precision_check/min_billable_minutes_floor_exact_boundary
    """
    _, _, _, trip = _flown_setup(program_code="BOUND1X", tail="N601LT")
    complete_trip(trip["id"], 48)  # 48 + 12 = 60 == floor exactly
    leg = get_trip_legs(trip["id"])[0]
    assert leg["billable_minutes"] == 60, (
        f"60 raw minutes at the floor must bill 60, got {leg['billable_minutes']}"
    )
    assert leg["billable_hours"] == pytest.approx(1.00, abs=0.005)


def test_trip_complete_debits_ledger_and_card(api):
    """PRD §3.7: "The trip's `final_hours` is the sum of its legs' `debited_hours`. A
    `TRIP_DEBIT` ledger entry is inserted for negative `final_hours` with the trip
    recorded in `trip_id`. The card's `hours_consumed` increases by `final_hours` and
    `hours_remaining` decreases by the same amount".

    Design: Difficulty/transitive_cascade/trip_complete_cascades_to_ledger_card_escrow_invoice
    """
    _, member, card = setup_active_card(program_overrides={"program_code": "CASCADE1"})
    aircraft = create_aircraft(tail_number="N400LT")
    trip = create_trip(card["id"], member["id"],
                       requested_departure_utc="2026-06-10T15:00:00Z")
    confirm_trip(trip["id"], member["id"])
    dispatch_trip(trip["id"], aircraft["id"])
    depart_trip(trip["id"])
    completed = complete_trip(trip["id"], 120)  # 132 min -> 2.20 hours
    assert completed["trip_status"] == "COMPLETED"
    assert completed["final_hours"] == pytest.approx(2.20, abs=0.005)

    leg = get_trip_legs(trip["id"])[0]
    assert leg["leg_status"] == "FLOWN"
    assert leg["billable_minutes"] == 132
    assert leg["billable_hours"] == pytest.approx(2.20, abs=0.005)

    card_after = get_card(card["id"])
    assert card_after["hours_consumed"] == pytest.approx(2.20, abs=0.005)
    assert card_after["hours_remaining"] == pytest.approx(22.80, abs=0.005)

    debits = get_ledger_entries(card["id"], entry_kind="TRIP_DEBIT")
    assert len(debits) == 1, f"exactly one TRIP_DEBIT expected, got {len(debits)}"
    assert debits[0]["hours_delta"] == pytest.approx(-2.20, abs=0.005)
    assert debits[0]["trip_id"] == trip["id"]


def test_trip_complete_releases_escrow_and_creates_invoice(api):
    """PRD §3.7: "The released amount is the proportion of the escrow principal
    corresponding to the hours just consumed: `final_hours` divided by the card's
    `hours_total`, multiplied by `principal_cents`, rounded half-up to whole cents. The
    escrow's `available_cents` decreases by that amount and `released_cents` increases by
    it".
    PRD §3.7: "The aircraft returns from `IN_SERVICE` to `AVAILABLE`, every leg's
    `leg_status` moves from `PLANNED` to `FLOWN`, and an `Invoice` is created for the
    trip (§3.8)."

    Design: Difficulty/transitive_cascade/trip_complete_cascades_to_ledger_card_escrow_invoice
    """
    _, member, card = setup_active_card(program_overrides={"program_code": "CASCADE1B"})
    aircraft = create_aircraft(tail_number="N401LT")
    escrow_before = get_escrow(card["id"])
    assert escrow_before["available_cents"] == 10_000_000
    trip = create_trip(card["id"], member["id"],
                       requested_departure_utc="2026-06-10T15:00:00Z")
    confirm_trip(trip["id"], member["id"])
    dispatch_trip(trip["id"], aircraft["id"])
    depart_trip(trip["id"])
    complete_trip(trip["id"], 120)  # final_hours = 2.20

    escrow_after = get_escrow(card["id"])
    expected_release = round((2.20 / 25) * 10_000_000)  # 880,000
    assert escrow_after["available_cents"] == 10_000_000 - expected_release
    assert escrow_after["released_cents"] == expected_release
    assert_escrow_conservation(escrow_after)
    card_after = get_card(card["id"])
    assert card_after["escrow_balance_cents"] == escrow_after["available_cents"]

    invoice = get_trip_invoice(trip["id"])
    assert invoice["subtotal_cents"] == 880_000, (
        f"2.20 debited hours at implied rate 400000 cents/hr = 880000, "
        f"got {invoice['subtotal_cents']}"
    )
    ac = get_aircraft(aircraft["id"])
    assert ac["aircraft_status"] == "AVAILABLE"


def test_cascading_side_effects_trip_complete_chain(api):
    """PRD §3.7: "`billable_hours` is `billable_minutes` divided by 60, rounded half-up
    to 2 decimal places."; "The card's `hours_consumed` increases by `final_hours`";
    "The aircraft returns from `IN_SERVICE` to `AVAILABLE`"; "an `Invoice` is created
    for the trip (§3.8)."

    Design: Corner/cross_cutting_layers/cascading_side_effects_trip_complete_chain
    """
    _, member, card = setup_active_card(program_overrides={"program_code": "CC1"})
    aircraft = create_aircraft(tail_number="N777LT")
    trip = create_trip(card["id"], member["id"])
    confirm_trip(trip["id"], member["id"])
    dispatch_trip(trip["id"], aircraft["id"])
    depart_trip(trip["id"])
    complete_trip(trip["id"], 120)
    leg = get_trip_legs(trip["id"])[0]
    assert leg["billable_hours"] == pytest.approx(2.20, abs=0.005)
    assert get_card(card["id"])["hours_consumed"] == pytest.approx(2.20, abs=0.005)
    assert get_aircraft(aircraft["id"])["aircraft_status"] == "AVAILABLE"
    invoice = get_trip_invoice(trip["id"])
    assert invoice["trip_id"] == trip["id"]


def test_hours_remaining_reconciled_after_multiple_trips(api):
    """PRD §2.8: "The card's `hours_remaining` is derived, never directly written: it
    equals the sum of `hours_delta` across all ledger entries whose `effective_at` is at
    or before the current logical time, replayed in `effective_at` ascending order with
    ties broken by `created_at` ascending."
    PRD §3.7: "The card's `hours_consumed` increases by `final_hours` and
    `hours_remaining` decreases by the same amount".

    Design: Corner/cross_cutting_layers/derived_field_hours_remaining_reconciled
    """
    _, member, card = setup_active_card(program_overrides={"program_code": "CC2"})
    aircraft = create_aircraft(tail_number="N888LT")
    fly_trip(card["id"], member["id"], aircraft["id"], block_minutes=108,
             trip_overrides={"requested_departure_utc": "2026-06-10T15:00:00Z"})
    fly_trip(card["id"], member["id"], aircraft["id"], block_minutes=168,
             trip_overrides={"requested_departure_utc": "2026-06-12T15:00:00Z"})
    card_after = get_card(card["id"])
    assert card_after["hours_consumed"] == pytest.approx(5.00, abs=0.005), (
        f"2.00 + 3.00 consumed, got {card_after['hours_consumed']}"
    )
    assert card_after["hours_remaining"] == pytest.approx(20.00, abs=0.005), (
        f"25 - 5.00 remaining, got {card_after['hours_remaining']}"
    )


def test_completion_response_shows_final_hours_immediately(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."
    PRD §3.7: "The trip's `final_hours` is the sum of its legs' `debited_hours`."

    Design: Corner/consistency_model/immediate_consistency_on_trip_complete
    """
    _, member, card = setup_active_card(program_overrides={"program_code": "CM1"})
    aircraft = create_aircraft(tail_number="N998LT")
    trip = create_trip(card["id"], member["id"])
    confirm_trip(trip["id"], member["id"])
    dispatch_trip(trip["id"], aircraft["id"])
    depart_trip(trip["id"])
    completed = complete_trip(trip["id"], 120)
    assert completed["final_hours"] == pytest.approx(2.20, abs=0.005), (
        f"final_hours must be visible immediately in the completion response, "
        f"got {completed['final_hours']}"
    )
