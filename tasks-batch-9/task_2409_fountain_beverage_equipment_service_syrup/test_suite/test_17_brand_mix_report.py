"""The brand-mix read: largest-remainder shares, the 30-day window, promo offers.

Three equal brands sharing an indivisible tenth, a reading sitting exactly on the
lower bound of the reporting period, and the two ways a promotional flavour drops off
the offered list.
"""

import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    add_telemetry,
    create_agreement,
    create_outlet,
    create_supply_item,
    create_unit,
    pin_clock,
    place_compliance_hold,
    read_outlet,
    read_unit,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
PLANNER = TEST_USERS["planner_headers"]
OFFICER = TEST_USERS["officer_headers"]

CLOCK = "2026-08-01T00:00:00Z"


def _outlet_and_unit():
    """Riverside Diner with one IN_SERVICE machine pouring for the report."""
    pin_clock(CLOCK)
    outlet = create_outlet(
        name="Riverside Diner", account_code="OUT-1001", region_code="R-WEST"
    )
    agreement = create_agreement(
        outlet["id"], annual_commitment_gallons=8000, equipment_value_cents=480000
    )
    unit = create_unit(
        outlet["id"], agreement["id"],
        serial_number="SN-9001", installed_at="2025-11-01T00:00:00Z",
    )
    return outlet, unit


def _cartridge(sku_code, brand_name, **overrides):
    return create_supply_item(
        sku_code=sku_code, brand_name=brand_name, supply_form="CARTRIDGE",
        case_pack_units=4, ounces_per_unit=1000, **overrides,
    )


def _line(report, brand_name):
    matches = [line for line in report["lines"] if line["brand_name"] == brand_name]
    assert len(matches) == 1, f"expected exactly one line for {brand_name}"
    return matches[0]


class TestLargestRemainder:
    def test_the_leftover_tenth_goes_to_the_brand_catalogued_first(self, api):
        """PRD §3.9: "Shares are apportioned to one decimal place by the largest-remainder
        method so that the emitted shares total exactly 100.0." Ties are broken by age:
        "Those leftover tenths are then awarded, one tenth each, to the lines with the
        largest remainders, ties being broken in favour of the supply item with the
        earlier `created_at`." The headline brand follows the same tie-break: "The
        `top_brand_name` is the `brand_name` of the line with the largest `total_ounces`,
        ties again broken in favour of the earlier `created_at` of the supply item."

        Design: Corner/calculations/brand_mix_largest_remainder_awards_the_leftover_tenth_by_created_at
        """
        outlet, unit = _outlet_and_unit()
        cola = _cartridge("SKU-COLA", "Cola Classic")
        lemon = _cartridge("SKU-LEMON", "Lemon Fizz")
        root = _cartridge("SKU-ROOT", "Root Beer")
        for item in (cola, lemon, root):
            add_telemetry(unit["id"], item["id"], 100, "2026-07-15T00:00:00Z")

        report = validate_success(api.get_brand_mix_report(outlet["id"], PLANNER))
        assert report["total_ounces"] == pytest.approx(300, abs=0.01)
        assert _line(report, "Cola Classic")["share_pct"] == pytest.approx(33.4, abs=0.01)
        assert _line(report, "Lemon Fizz")["share_pct"] == pytest.approx(33.3, abs=0.01)
        assert _line(report, "Root Beer")["share_pct"] == pytest.approx(33.3, abs=0.01)
        assert sum(line["share_pct"] for line in report["lines"]) == pytest.approx(
            100.0, abs=0.01
        )
        assert report["top_brand_name"] == "Cola Classic"


class TestReportingWindow:
    def test_the_period_opens_on_its_first_instant_and_drops_the_day_before(self, api):
        """PRD §3.9: "Available to a `NetworkAdmin`, a `SupplyPlanner` or the
        `OutletManager` of the outlet in question, this computed read mutates nothing and
        reports over a fixed half-open 30-day period that ends at the logical clock. A
        reading qualifies for the report when its `reading_at` falls inside that period
        and it was produced by a dispenser unit of this outlet whose `status` is
        `IN_SERVICE`, `SERVICE_HOLD` or `RECALL_STAGED`; readings from `RETURNED` units
        are excluded." Excluded volume is still on the odometer, per §3.4: "Each
        ingestion refreshes the receiving machine's `lifetime_dispensed_gallons`, which
        is defined as the total ounces ever reported for that unit divided by 128 and
        then rounded half up to two decimal places."

        Design: Corner/calculations/brand_mix_window_lower_bound_included_and_earlier_reading_excluded
        """
        outlet, unit = _outlet_and_unit()
        cola = _cartridge("SKU-COLA", "Cola Classic")
        add_telemetry(unit["id"], cola["id"], 500, "2026-07-02T00:00:00Z")
        add_telemetry(unit["id"], cola["id"], 700, "2026-07-01T00:00:00Z")

        report = validate_success(api.get_brand_mix_report(outlet["id"], PLANNER))
        assert report["total_ounces"] == pytest.approx(500, abs=0.01)
        assert len(report["lines"]) == 1
        assert report["lines"][0]["brand_name"] == "Cola Classic"
        assert report["lines"][0]["share_pct"] == pytest.approx(100.0, abs=0.01)
        assert report["top_brand_name"] == "Cola Classic"
        assert read_unit(unit["id"])["lifetime_dispensed_gallons"] == pytest.approx(
            9.38, abs=0.01
        )


class TestPromotionalOffers:
    def test_a_frozen_outlet_is_offered_no_promotional_flavours(self, api):
        """PRD §3.9: "`promo_available_skus` lists the `sku_code` of every supply item
        that is `promotional`, whose promotional window currently contains the logical
        clock — at or after `promo_window_start` and strictly before `promo_window_end` —
        and only while the outlet's `service_posture` is not `FROZEN`, ordered by the
        supply item's `created_at` ascending; a frozen outlet is offered no promotional
        flavours at all." What freezes it is §2.10: "Because the frozen clause is tested
        first, an outlet under a compliance hold is `FROZEN` even when it has zero
        overdue tasks."

        Design: Corner/calculations/brand_mix_promo_list_hidden_while_the_posture_is_frozen
        """
        outlet, unit = _outlet_and_unit()
        promo = _cartridge(
            "SKU-PROMO", "Summer Splash",
            promotional=True,
            promo_window_start="2026-07-15T00:00:00Z",
            promo_window_end="2026-09-01T00:00:00Z",
        )
        add_telemetry(unit["id"], promo["id"], 500, "2026-07-20T00:00:00Z")

        offered = validate_success(api.get_brand_mix_report(outlet["id"], PLANNER))
        assert offered["promo_available_skus"] == ["SKU-PROMO"]

        place_compliance_hold(
            outlet["id"], OFFICER, hold_reason_code="SANITATION_LAPSE"
        )
        assert read_outlet(outlet["id"])["service_posture"] == "FROZEN"

        withdrawn = validate_success(api.get_brand_mix_report(outlet["id"], PLANNER))
        assert withdrawn["promo_available_skus"] == []
        assert withdrawn["total_ounces"] == pytest.approx(500, abs=0.01)
        assert withdrawn["top_brand_name"] == "Summer Splash"

    def test_a_promotion_ending_on_the_clock_instant_is_no_longer_offered(self, api):
        """PRD §3.9: "`promo_available_skus` lists the `sku_code` of every supply item
        that is `promotional`, whose promotional window currently contains the logical
        clock — at or after `promo_window_start` and strictly before `promo_window_end` —
        and only while the outlet's `service_posture` is not `FROZEN`, ordered by the
        supply item's `created_at` ascending; a frozen outlet is offered no promotional
        flavours at all." §2.9 says the same thing generally: "Promotional availability
        windows are likewise half-open: a SKU is available when the logical clock is at
        or after `promo_window_start` and strictly before `promo_window_end`."

        Design: Corner/calculations/brand_mix_promo_sku_outside_its_window_absent_from_the_promo_list
        """
        outlet, unit = _outlet_and_unit()
        promo = _cartridge(
            "SKU-PROMO", "Summer Splash",
            promotional=True,
            promo_window_start="2026-07-01T00:00:00Z",
            promo_window_end="2026-08-01T00:00:00Z",
        )
        add_telemetry(unit["id"], promo["id"], 400, "2026-07-20T00:00:00Z")
        assert read_outlet(outlet["id"])["service_posture"] == "OPEN"

        report = validate_success(api.get_brand_mix_report(outlet["id"], PLANNER))
        assert report["promo_available_skus"] == []
        assert report["total_ounces"] == pytest.approx(400, abs=0.01)
        assert len(report["lines"]) == 1
        assert report["lines"][0]["brand_name"] == "Summer Splash"
        assert report["lines"][0]["share_pct"] == pytest.approx(100.0, abs=0.01)
