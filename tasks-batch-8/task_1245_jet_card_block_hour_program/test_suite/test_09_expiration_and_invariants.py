"""Hour-bank dual variants, expiration sweep, and conservation invariants."""
import pytest

from test_helpers import (
    TEST_USERS,
    approve_refund,
    assert_escrow_conservation,
    assert_hour_bank_conservation,
    create_aircraft,
    create_refund,
    expire_card_via_sweep,
    fly_trip,
    get_card,
    get_card_projection,
    get_escrow,
    run_ops_sweep,
    set_clock,
    setup_active_card,
    settle_refund,
    submit_refund,
)

OPS = TEST_USERS["ops_headers"]


def _expired_card_after_sweep(api, code):
    """25h MIDSIZE card, expiry 12 months; activated at 2026-06-01, swept at 2027-12-01.
    Ledger: PURCHASE_GRANT(+25 @2026-06-01) + EXPIRATION_DEBIT(-25 @2027-06-01)."""
    _, member, card = setup_active_card(
        program_overrides={
            "program_code": code,
            "aircraft_category": "MIDSIZE",
            "purchase_price_cents": 15_000_000,
            "expiry_months": 12,
        },
        clock="2026-06-01T00:00:00Z",
    )
    set_clock("2027-12-01T00:00:00Z")
    run_ops_sweep()
    return card["id"]


def test_hour_bank_persisted_zero_after_expiration_sweep(api):
    """PRD §2.8: "it equals the sum of `hours_delta` across all ledger entries whose
    `effective_at` is at or before the current logical time, replayed in `effective_at`
    ascending order with ties broken by `created_at` ascending. This chronological variant
    is the persisted balance and drives all trip authorization."
    PRD §3.9: "A card whose `hours_remaining` is still positive transitions to `EXPIRED`:
    an `EXPIRATION_DEBIT` ledger entry is inserted for the negative of the remaining
    hours".

    Design: Difficulty/dual_variant_calc/hour_bank_chronological_vs_forward_looking
    """
    card_id = _expired_card_after_sweep(api, "MID_25")
    card = get_card(card_id)
    assert card["card_status"] == "EXPIRED"
    assert card["hours_remaining"] == pytest.approx(0.0, abs=0.005), (
        f"after the expiration debit the persisted balance must be 0, "
        f"got {card['hours_remaining']}"
    )


def test_hour_bank_projection_matches_floor_after_expiry(api):
    """PRD §2.8: "A second, forward-looking variant exists for what-if display: it sums
    entries whose `effective_at` is at or before the earlier of the current time and the
    card's `expires_at`, thereby forecasting the post-expiry floor. The forward-looking
    variant is exposed only through the card projection read; it never authorizes trips."

    Design: Difficulty/dual_variant_calc/hour_bank_chronological_vs_forward_looking
    """
    card_id = _expired_card_after_sweep(api, "MID_25P")
    projection = get_card_projection(card_id)
    assert projection["hours_remaining"] == pytest.approx(0.0, abs=0.005), (
        f"post-sweep forward-looking balance must equal the same floor of 0, "
        f"got {projection['hours_remaining']}"
    )


def _consumed_then_expired_card(api, code):
    """25h card, expiry 1 month; one 5.00-hour trip (288 block + 12 taxi = 300 min);
    clock advanced past expiry; sweep runs. Returns card_id."""
    _, member, card = setup_active_card(
        program_overrides={"program_code": code, "expiry_months": 1},
        clock="2026-06-01T00:00:00Z",
    )
    aircraft = create_aircraft(tail_number="N900LT")
    fly_trip(card["id"], member["id"], aircraft["id"], block_minutes=288,
             trip_overrides={"requested_departure_utc": "2026-06-05T15:00:00Z"})
    set_clock("2026-08-01T00:00:00Z")
    run_ops_sweep()
    return card["id"]


def test_hour_bank_fields_after_trip_and_expiry(api):
    """PRD §3.7: "The card's `hours_consumed` increases by `final_hours` and
    `hours_remaining` decreases by the same amount".
    PRD §3.9: "an `EXPIRATION_DEBIT` ledger entry is inserted for the negative of the
    remaining hours ... and the card's `hours_expired` reflects the lapsed quantity."

    Design: Difficulty/compensating_invariant/hour_bank_conservation_purchase_equals_debits_plus_remaining
    """
    card_id = _consumed_then_expired_card(api, "INV1")
    card = get_card(card_id)
    assert card["hours_total"] == 25
    assert card["hours_consumed"] == pytest.approx(5.00, abs=0.005), (
        f"288 block + 12 taxi = 300 min = 5.00 h consumed, got {card['hours_consumed']}"
    )
    assert card["hours_remaining"] == pytest.approx(0.0, abs=0.005)
    assert card["hours_expired"] == pytest.approx(20.00, abs=0.005), (
        f"20 unconsumed hours must lapse, got {card['hours_expired']}"
    )


def test_hour_bank_conservation_invariant(api):
    """PRD §2.8: "The card's `hours_remaining` is derived, never directly written: it
    equals the sum of `hours_delta` across all ledger entries whose `effective_at` is at
    or before the current logical time". Purchase grants, trip debits, and expiration
    debits must therefore reconcile: hours_total == consumed + remaining + expired.

    Design: Difficulty/compensating_invariant/hour_bank_conservation_purchase_equals_debits_plus_remaining
    """
    card_id = _consumed_then_expired_card(api, "INV1C")
    card = get_card(card_id)
    assert_hour_bank_conservation(card)


def _consumed_then_refunded_card(api, code):
    """25h / $100k card (24-month expiry, 20% penalty); one 5.00-hour trip releases 20%
    of escrow; remaining 20h refunded within the first year and settled.
    Returns card_id."""
    _, member, card = setup_active_card(
        program_overrides={"program_code": code, "expiry_months": 24},
        clock="2026-06-01T00:00:00Z",
    )
    aircraft = create_aircraft(tail_number="N950LT")
    fly_trip(card["id"], member["id"], aircraft["id"], block_minutes=288,
             trip_overrides={"requested_departure_utc": "2026-06-05T15:00:00Z"})
    refund = create_refund(card["id"], member["id"])
    submit_refund(refund["id"], member["id"])
    approve_refund(refund["id"])
    settle_refund(refund["id"])
    return card["id"]


def test_escrow_available_after_release_and_refund(api):
    """PRD §3.7: "The released amount is the proportion of the escrow principal
    corresponding to the hours just consumed: `final_hours` divided by the card's
    `hours_total`, multiplied by `principal_cents`, rounded half-up to whole cents."
    PRD §3.10: "settling an `APPROVED` refund ... reduces the escrow's `available_cents`
    by `net_refund_cents` while `released_cents` increases by the same amount".

    Design: Difficulty/compensating_invariant/escrow_conservation_principal_equals_available_released_forfeited
    """
    card_id = _consumed_then_refunded_card(api, "INV2")
    escrow = get_escrow(card_id)
    assert escrow["principal_cents"] == 10_000_000
    # Trip release: (5.00/25) * 10,000,000 = 2,000,000.
    # Refund: gross (20/25)*10,000,000 = 8,000,000; penalty 20% = 1,600,000;
    # net = 6,400,000. available = 10,000,000 - 2,000,000 - 6,400,000 = 1,600,000.
    assert escrow["available_cents"] == 1_600_000, (
        f"available must be principal minus trip release minus net refund, "
        f"got {escrow['available_cents']}"
    )
    assert escrow["released_cents"] == 8_400_000, (
        f"released = 2,000,000 trip release + 6,400,000 net refund, "
        f"got {escrow['released_cents']}"
    )
    assert escrow["forfeited_cents"] == 0


def test_escrow_conservation_invariant(api):
    """PRD §2.9: "Its `available_cents` decreases on three events: proportional release
    when a trip completes, payout when a refund settles, and forfeiture when the
    expiration sweep runs. `released_cents` accumulates funds paid back to the operator
    or member (consumed hours and refunds paid), while `forfeited_cents` accumulates
    value lapsed through expiration." Escrow principal is therefore conserved:
    principal_cents == available_cents + released_cents + forfeited_cents.

    Design: Difficulty/compensating_invariant/escrow_conservation_principal_equals_available_released_forfeited
    """
    card_id = _consumed_then_refunded_card(api, "INV2C")
    escrow = get_escrow(card_id)
    assert_escrow_conservation(escrow)
