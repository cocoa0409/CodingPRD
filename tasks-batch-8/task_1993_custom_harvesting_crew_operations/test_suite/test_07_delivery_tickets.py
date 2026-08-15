"""Delivery-ticket write-time computations: moisture shrink boundaries and
cap, and the hauling add-on."""
import pytest

from test_helpers import (
    assert_delivery_ticket,
    setup_cutting_stop,
    validate_success,
)


def test_moisture_at_base_no_shrink(api, crew_boss_headers):
    """PRD section 3.7: "If the moisture percent is at most 15.0, the shrink
    factor is exactly 1.0 — no shrink."
    PRD section 3.7: "`net_bushels` is the gross bushels multiplied by the
    shrink factor, rounded half-up to one decimal place."

    Design: Difficulty/boundary_precision_check/moisture_pct_at_exactly_15_does_not_shrink
    """
    ctx = setup_cutting_stop()
    stop_id = ctx["stop"]["id"]

    at_base = validate_success(api.create_delivery_ticket(
        stop_id,
        {"delivered_at": "2026-08-06T10:00:00Z", "gross_bushels": 1000,
         "moisture_pct": 15.0, "used_our_trucks": False},
        crew_boss_headers,
    ), 201)
    assert_delivery_ticket(at_base)
    assert at_base["net_bushels"] == pytest.approx(1000.0, abs=0.05), (
        f"moisture exactly 15.0 must not shrink, got {at_base['net_bushels']!r}"
    )

    below_base = validate_success(api.create_delivery_ticket(
        stop_id,
        {"delivered_at": "2026-08-06T10:30:00Z", "gross_bushels": 1000,
         "moisture_pct": 14.9, "used_our_trucks": False},
        crew_boss_headers,
    ), 201)
    assert below_base["net_bushels"] == pytest.approx(1000.0, abs=0.05), (
        f"moisture below 15.0 must not shrink, got {below_base['net_bushels']!r}"
    )


def test_moisture_one_tenth_above_base_shrinks(api, crew_boss_headers):
    """PRD section 3.7: "Otherwise, the system counts excess tenths by taking
    the difference between the moisture percent and 15.0, multiplying by ten,
    and rounding half-up to a whole number; the shrink factor is then one
    minus the product of the excess tenths and 0.001".

    Design: Difficulty/boundary_precision_check/moisture_pct_at_exactly_15_does_not_shrink
    """
    ctx = setup_cutting_stop()
    wet = validate_success(api.create_delivery_ticket(
        ctx["stop"]["id"],
        {"delivered_at": "2026-08-06T11:00:00Z", "gross_bushels": 1000,
         "moisture_pct": 15.1, "used_our_trucks": False},
        crew_boss_headers,
    ), 201)
    assert_delivery_ticket(wet)
    # 15.1 -> 1 excess tenth -> factor 0.999 -> 1000 * 0.999 = 999.0
    assert wet["net_bushels"] == pytest.approx(999.0, abs=0.05), (
        f"moisture 15.1 must shrink by 0.001, got {wet['net_bushels']!r}"
    )


def test_moisture_shrink_at_max_shrink_cap(api, crew_boss_headers):
    """PRD section 3.7: "the shrink factor is then one minus the product of
    the excess tenths and 0.001, but never lower than 0.80 — the maximum
    shrink is capped at 0.20."

    Design: Corner/calculations/moisture_shrink_at_max_shrink_cap
    """
    ctx = setup_cutting_stop()
    ticket = validate_success(api.create_delivery_ticket(
        ctx["stop"]["id"],
        {"delivered_at": "2026-08-05T10:00:00Z", "gross_bushels": 1000,
         "moisture_pct": 40.0, "used_our_trucks": False},
        crew_boss_headers,
    ), 201)
    # Uncapped factor would be 1 - 250 * 0.001 = 0.75; the cap pins 0.80.
    assert ticket["net_bushels"] == pytest.approx(800.0, abs=0.05), (
        f"max shrink cap must yield factor 0.80 (net 800.0), got {ticket['net_bushels']!r}"
    )


def test_hauling_add_on_only_when_used_our_trucks(api, crew_boss_headers):
    """PRD section 3.7: "if `used_our_trucks` is true, the add-on is the gross
    bushels multiplied by twelve cents per bushel, rounded half-up to whole
    cents; if the grower hauled the load, the add-on is 0."

    Design: Corner/calculations/hauling_add_on_only_when_used_our_trucks
    """
    ctx = setup_cutting_stop()
    stop_id = ctx["stop"]["id"]

    hauled = validate_success(api.create_delivery_ticket(
        stop_id,
        {"delivered_at": "2026-08-05T10:00:00Z", "gross_bushels": 500,
         "moisture_pct": 14.0, "used_our_trucks": True},
        crew_boss_headers,
    ), 201)
    assert_delivery_ticket(hauled)
    assert hauled["hauling_add_on_cents"] == 6000, (
        f"500 bushels at 12 cents must yield 6000, got {hauled['hauling_add_on_cents']!r}"
    )

    self_hauled = validate_success(api.create_delivery_ticket(
        stop_id,
        {"delivered_at": "2026-08-05T11:00:00Z", "gross_bushels": 500,
         "moisture_pct": 14.0, "used_our_trucks": False},
        crew_boss_headers,
    ), 201)
    assert self_hauled["hauling_add_on_cents"] == 0, (
        f"grower-hauled load must yield 0, got {self_hauled['hauling_add_on_cents']!r}"
    )
