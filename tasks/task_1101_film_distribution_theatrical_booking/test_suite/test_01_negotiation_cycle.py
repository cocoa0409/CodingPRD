"""Cyclic negotiation on the booking deal axis (PRD §3.3)."""
from test_helpers import (
    validate_success,
    setup_distributor_film_theatre_screen,
    setup_proposed_booking,
    TEST_USERS,
)

BOOKER = TEST_USERS["booker_headers"]
EXHIBITOR = TEST_USERS["exhibitor_headers"]


def _terms(pct, decay, floor, per_capita):
    return {
        "week_one_rental_pct": pct,
        "rental_decay_per_week": decay,
        "floor_pct": floor,
        "per_capita_floor_cents": per_capita,
    }


def test_counter_rounds_toggle_deal_status_and_increment_version(api):
    """PRD §3.3: "The **deal axis** runs `PROPOSED` → `COUNTERED` → `ACCEPTED` → `IN_PLAY`
    → `HELD_OVER`, with terminal outcomes `DECLINED`, `CANCELLED`, and `COMPLETED`;
    negotiation is cyclic, so `PROPOSED` and `COUNTERED` toggle back and forth."
    PRD §3.3: "Every counter-offer carries `expected_booking_agreement_version`, is
    rejected with `ERR_STALE_VERSION` when stale, re-validates the fiscal terms against
    `ERR_INVALID_RENTAL_TERMS`, and increments the agreement's `version`."

    Design: Difficulty/non_linear_state_machine/booking_agreement_cyclic_proposed_countered_loop
    """
    env = setup_distributor_film_theatre_screen()
    did = env["distributor"]["id"]
    ba = setup_proposed_booking(
        did, env["film"]["id"], env["theatre"]["id"], env["screen"]["id"]
    )
    v0 = ba["version"]
    assert ba["deal_status"] == "PROPOSED"

    r1 = validate_success(api.counter_booking_agreement(
        did, ba["id"],
        {"expected_booking_agreement_version": v0, **_terms(0.50, 0.04, 0.25, 90)},
        EXHIBITOR,
    ), 200)
    assert r1["deal_status"] == "COUNTERED", f"round 1: got {r1['deal_status']}"
    assert r1["version"] == v0 + 1, f"round 1 version: expected {v0 + 1}, got {r1['version']}"

    r2 = validate_success(api.counter_booking_agreement(
        did, ba["id"],
        {"expected_booking_agreement_version": r1["version"], **_terms(0.55, 0.04, 0.28, 95)},
        BOOKER,
    ), 200)
    assert r2["deal_status"] == "PROPOSED", f"round 2: got {r2['deal_status']}"
    assert r2["version"] == v0 + 2, f"round 2 version: expected {v0 + 2}, got {r2['version']}"

    r3 = validate_success(api.counter_booking_agreement(
        did, ba["id"],
        {"expected_booking_agreement_version": r2["version"], **_terms(0.58, 0.05, 0.30, 100)},
        EXHIBITOR,
    ), 200)
    assert r3["deal_status"] == "COUNTERED", f"round 3: got {r3['deal_status']}"
    assert r3["version"] == v0 + 3, f"round 3 version: expected {v0 + 3}, got {r3['version']}"


def test_counter_offer_terms_are_recorded_on_the_agreement(api):
    """PRD §3.3: "An `Exhibitor` counters a `PROPOSED` agreement, moving it to `COUNTERED`
    with the proposed counter-terms recorded on the agreement; a `Booker` counters a
    `COUNTERED` agreement, returning it to `PROPOSED`."

    Design: Difficulty/non_linear_state_machine/booking_agreement_cyclic_proposed_countered_loop
    """
    env = setup_distributor_film_theatre_screen()
    did = env["distributor"]["id"]
    ba = setup_proposed_booking(
        did, env["film"]["id"], env["theatre"]["id"], env["screen"]["id"]
    )

    r1 = validate_success(api.counter_booking_agreement(
        did, ba["id"],
        {"expected_booking_agreement_version": ba["version"], **_terms(0.50, 0.04, 0.25, 90)},
        EXHIBITOR,
    ), 200)
    assert r1["deal_status"] == "COUNTERED"
    after_exhibitor = validate_success(api.get_booking_agreement(did, ba["id"], BOOKER), 200)
    assert after_exhibitor["week_one_rental_pct"] == 0.50, (
        f"counter-terms not recorded: week_one_rental_pct={after_exhibitor['week_one_rental_pct']}"
    )
    assert after_exhibitor["floor_pct"] == 0.25
    assert after_exhibitor["per_capita_floor_cents"] == 90

    r2 = validate_success(api.counter_booking_agreement(
        did, ba["id"],
        {"expected_booking_agreement_version": r1["version"], **_terms(0.55, 0.03, 0.28, 95)},
        BOOKER,
    ), 200)
    assert r2["deal_status"] == "PROPOSED"
    after_booker = validate_success(api.get_booking_agreement(did, ba["id"], EXHIBITOR), 200)
    assert after_booker["week_one_rental_pct"] == 0.55, (
        f"counter-terms not recorded: week_one_rental_pct={after_booker['week_one_rental_pct']}"
    )
    assert after_booker["floor_pct"] == 0.28
    assert after_booker["per_capita_floor_cents"] == 95
