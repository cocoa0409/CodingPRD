"""
Multi-step money formulas whose evaluation order is pinned.

The early-termination fee rounds per machine before summing, and the
sustainability service-fee tier is read from the pre-credit programme cost.
Both fixtures are built so that the wrong order lands on a different integer.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_cents,
    assert_equipment_ledger,
    assert_axes,
)
from test_helpers.test_users import ACCOUNT_MANAGER_HEADERS
from test_helpers.types import (
    AGREEMENT_TERMINATED,
    CLASS_CONVEYOR,
    CLASS_DOOR_TYPE,
    CLASS_UNDERCOUNTER,
    OP_UP,
    PLACEMENT_PENDING_INSTALL,
    SUSTAINABILITY_BASIS_RATED,
)

# Three book values that each land exactly on a half cent at 33/36 of the term:
# 480006 * 33 / 36 = 440005.5, 360006 -> 330005.5, 240006 -> 220005.5.
HALF_CENT_MODELS = [
    ("DT-88A", CLASS_DOOR_TYPE, 480006, 440006),
    ("UC-40B", CLASS_UNDERCOUNTER, 360006, 330006),
    ("GW-10C", CLASS_CONVEYOR, 240006, 220006),
]
PER_MACHINE_TOTAL = 990018  # 440006 + 330006 + 220006
SUM_THEN_ROUND_TOTAL = 990017  # round_half_up(440005.5 + 330005.5 + 220005.5)
REMAINING_MINIMUM_TOTAL = 396000  # 33 * 20000 * 0.60


def _three_placement_agreement(api):
    """
    One ACTIVE 36-month agreement carrying three PENDING_INSTALL placements, one
    per half-cent machine model, with the clock left at its default.
    """
    base = X.program_base(
        api,
        agreement_overrides={
            "start_date": "2026-08-01",
            "minimum_term_months": 36,
            "monthly_minimum_spend_cents": 20000,
        },
    )

    placements = []
    for index, (model_code, machine_class, value_cents, _rounded) in enumerate(
        HALF_CENT_MODELS
    ):
        model = X.create_machine_model(
            api,
            model_code=model_code,
            machine_class=machine_class,
            equipment_value_cents=value_cents,
            max_cycles_between_calibrations=20000,
        )
        placements.append(
            X.create_placement(
                api,
                base,
                asset_tag=f"AT-10{index + 1}",
                model_id=model["id"],
            )
        )

    base["placements"] = placements
    return base


def test_termination_fee_rounds_each_machine_before_summing(api):
    """
    Three placements whose unamortized values are exactly 440005.5, 330005.5 and
    220005.5 cents. Rounding each first gives 990018; summing the exact
    fractions to 990016.5 and rounding once would give 990017, so the single
    cent of difference falsifies the wrong order.

    PRD §3.2: "The **unamortized-equipment** view instead recovers book value:
    for each placement of this agreement whose `placement_status` is
    `PENDING_INSTALL`, `INSTALLED` or `RETRIEVAL_SCHEDULED`, taken in
    `created_at` ascending order, multiply that machine model's
    `equipment_value_cents` by the remaining-month count, divide by the
    agreement's `minimum_term_months`, and **round that per-machine amount half
    up to whole cents before adding it to the running total**; placements
    already `RETRIEVED` or `CANCELLED` contribute nothing."

    Design: Difficulty/combinatorial_formula/termination_fee_per_placement_rounding_precedes_summation
    """
    base = _three_placement_agreement(api)

    agreement = validate_success(
        api.terminate_service_agreement(
            base["agreement_id"],
            F.terminate_payload("2026-12-01"),
            ACCOUNT_MANAGER_HEADERS,
        )
    )

    assert agreement["term_end_date"] == "2029-08-01"
    assert agreement["termination_effective_date"] == "2026-12-01"
    assert agreement["status"] == AGREEMENT_TERMINATED
    assert_cents(agreement["early_termination_fee_cents"], PER_MACHINE_TOTAL)
    assert agreement["early_termination_fee_cents"] != SUM_THEN_ROUND_TOTAL

    # Cascade alpha schedules INSTALLED placements only, so all three survive.
    for placement in base["placements"]:
        current = get_success_data(
            api.get_machine_placement(placement["id"], ACCOUNT_MANAGER_HEADERS)
        )
        assert_axes(current, placement_status=PLACEMENT_PENDING_INSTALL)


def test_termination_fee_takes_the_larger_of_the_two_recovery_theories(api):
    """
    The same agreement's remaining-minimum view recovers only 33 * 20000 * 0.60
    = 396000 cents, so the 990018-cent equipment view is what gets stamped.

    PRD §3.2: "The **remaining-minimum** view then recovers the unspent
    chemical commitment as the remaining-month count multiplied by
    `monthly_minimum_spend_cents` multiplied by a shortfall rate of 60 percent,
    rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/termination_fee_per_placement_rounding_precedes_summation
    """
    base = _three_placement_agreement(api)

    agreement = validate_success(
        api.terminate_service_agreement(
            base["agreement_id"],
            F.terminate_payload("2026-12-01"),
            ACCOUNT_MANAGER_HEADERS,
        )
    )

    fee = agreement["early_termination_fee_cents"]
    assert_cents(fee, max(REMAINING_MINIMUM_TOTAL, PER_MACHINE_TOTAL))
    assert fee > REMAINING_MINIMUM_TOTAL
    assert fee != REMAINING_MINIMUM_TOTAL

    # The three PENDING_INSTALL placements still hold their book value.
    customer = get_success_data(
        api.get_customer(base["customer_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert_equipment_ledger(customer, 480006 + 360006 + 240006)


def _big_spend_site(api):
    """
    100000 racks of telemetry plus a 20-container delivery, so chemical spend is
    182400 cents and the pre-credit programme cost lands at 207400 — just above
    the 200000-cent tier boundary.
    """
    base = X.program_base(
        api,
        model_overrides={
            "model_code": "DT-88H",
            "max_cycles_between_calibrations": 200000,
        },
    )
    placement = X.installed_placement(api, base, asset_tag="AT-201")

    X.set_clock(api, "2026-08-02T08:00:00Z")
    delivery = X.record_delivery(
        api, base, unit_count=20, delivered_at="2026-08-02T08:00:00Z"
    )

    reading = X.ingest_reading_at_clock(
        api, placement["id"], "2026-08-20T12:00:00Z", 100000
    )
    X.set_clock(api, "2026-09-01T00:00:00Z")

    base.update(
        {
            "placement_id": placement["id"],
            "delivery": delivery,
            "reading": reading,
        }
    )
    return base


def test_delivery_price_rounds_the_unit_before_multiplying_by_the_count(api):
    """
    20 containers earn the 5 percent tier, so the unit price rounds to 9120
    cents first and the delivery totals 9120 * 20 = 182400 cents over 400000 ml.

    PRD §3.7: "The discounted **unit** price is then computed by multiplying the
    product's `unit_price_cents` by one minus that rate and rounding half up to
    whole cents, and `amount_cents` is that rounded unit price multiplied by
    `unit_count`."

    Design: Difficulty/combinatorial_formula/sustainability_fee_tier_read_from_pre_credit_program_cost
    """
    base = _big_spend_site(api)

    assert_cents(base["delivery"]["amount_cents"], 182400)
    assert base["delivery"]["quantity_ml"] == 400000
    assert base["reading"]["cycle_delta"] == 100000


def test_service_fee_tier_is_chosen_from_the_pre_credit_program_cost(api):
    """
    The pre-credit programme cost of 207400 selects the 0.06 band for a
    10944-cent fee. Netting the capped 15000-cent credit out first would give
    192400, cross under the boundary and wrongly select 0.08 for a 14592-cent
    fee, so the reported rate and net cost distinguish the two orders.

    PRD §3.9: "`service_fee_rate` is 0.08 when `gross_program_cost_cents` is
    below 200000, otherwise 0.06 when it is below 500000, otherwise 0.04. The
    tier is chosen from that **pre-credit** figure."

    Design: Difficulty/combinatorial_formula/sustainability_fee_tier_read_from_pre_credit_program_cost
    """
    base = _big_spend_site(api)

    report = validate_success(
        api.get_sustainability_report(
            base["site_id"],
            ACCOUNT_MANAGER_HEADERS,
            F.report_params(
                "2026-08-01T00:00:00Z",
                "2026-09-01T00:00:00Z",
                SUSTAINABILITY_BASIS_RATED,
            ),
        )
    )

    assert report["rack_count"] == 100000
    assert report["water_saved_l"] == pytest.approx(46000.00, abs=0.01)
    assert report["energy_saved_kwh"] == pytest.approx(21000.00, abs=0.01)
    assert_cents(report["water_savings_cents"], 22080)
    assert_cents(report["energy_savings_cents"], 294000)
    assert_cents(report["gross_savings_cents"], 316080)
    assert_cents(report["chemical_spend_cents"], 182400)
    assert_cents(report["gross_program_cost_cents"], 207400)

    assert report["service_fee_rate"] == pytest.approx(0.06, abs=1e-9)
    assert_cents(report["service_fee_cents"], 10944)
    # round_half_up(316080 * 0.05) = 15804, clipped by the 15000-cent cap.
    assert_cents(report["sustainability_credit_cents"], 15000)
    assert_cents(report["net_program_cost_cents"], 203344)

    # Crediting before the tier lookup would produce all three of these.
    assert report["service_fee_rate"] != pytest.approx(0.08, abs=1e-9)
    assert report["service_fee_cents"] != 14592
    assert report["net_program_cost_cents"] != 206992

    # The 100000-cycle sample is healthy and cannot trip HIGH_CYCLE_RATE alone.
    assert X.list_alerts_for_placement(api, base["placement_id"]) == []
    placement = get_success_data(
        api.get_machine_placement(base["placement_id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert_axes(placement, operational_status=OP_UP)
