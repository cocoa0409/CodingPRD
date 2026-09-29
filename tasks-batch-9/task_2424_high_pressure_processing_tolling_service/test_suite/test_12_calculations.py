"""Breadth over the arithmetic: rounding order, tier edges, uplift order, thresholds.

Each of these pins one figure that a plausible alternative implementation would get
wrong by a cent, a tier or a whole slot — a score rounded once instead of three
times, a utilisation sitting exactly on a strict tier boundary, a peak uplift
applied after rather than before the remainder pass, a consumption landing exactly
on the minimum take, and a trailing window that includes its own ninetieth day.
"""

from test_helpers import (
    QM_ALICE,
    api_client,
    book_load,
    capture_cycle_log,
    commission_third_vessel,
    create_qualification_payload,
    define_family,
    disposition_cycle,
    list_chargeback_lines,
    make_customer_headers,
    open_active_contract,
    open_qualification,
    read_contract,
    read_customer,
    read_cycle,
    read_load,
    read_qualification,
    register_customer,
    run_day_close,
    schedule_cycle,
    setup_dispositioned_clean_cycle,
    setup_inspected_load,
    setup_stored_pallet,
    set_clock,
    start_cycle,
    submit_qualification,
    validate_success,
    validation_run_payload,
)
from test_helpers.fixtures import ADMIN, CLOCK_AUG03, QUALITY

SPOT_CONTRACT = {
    "season_code": "FY26-SPOT",
    "committed_slots": 1,
    "slot_take_or_pay_cents": 60000,
    "priority_rank": 2,
}


def test_the_suitability_score_is_rounded_once_on_the_summed_total():
    """A tray-sealed package with an 11.125 MPa burst margin and a 43 micron film
    scores 44.25, which is only reachable by rounding the sum rather than the parts.

    PRD 3.2: "Each component is multiplied by 100 and then weighted — the pressure
    margin at 0.50, the film margin at 0.30, and the format factor at 0.20 — and the
    three weighted terms are added together."
    PRD 3.2: "The components are held at full precision throughout; there is exactly
    one rounding step, applied half up to two decimal places on the summed total, and
    that total is stored as `package_suitability_score`."

    Design: Corner/calculations/corner_suitability_score_rounds_only_the_summed_total
    """
    set_clock(CLOCK_AUG03)
    customer = register_customer()
    family = define_family()

    qualification = validate_success(
        api_client.create_qualification(
            create_qualification_payload(
                customer["id"],
                family["id"],
                sku_code="SOUP-200",
                version_label="REV-A",
                max_water_temp_c=8.0,
                package_format="TRAY_SEALED",
                package_burst_pressure_mpa=611.125,
                film_thickness_micron=43,
                target_log_reduction=5.0,
            ),
            make_customer_headers(customer["id"]),
        ),
        201,
    )

    assert qualification["package_suitability_score"] == 44.25
    assert qualification["package_suitability_score"] != 44.26
    assert qualification["status"] == "DRAFT"
    assert read_qualification(qualification["id"])[
        "package_suitability_score"
    ] == 44.25


def test_utilisation_of_exactly_sixty_percent_takes_the_softer_surcharge_tier():
    """Three of five baskets is 60.00 percent, and because the heavy tier's test is
    strict the chamber is charged 8 percent rather than 20.

    PRD 3.5: "Chamber utilisation, `utilization_pct`, is 100 multiplied by the cycle's
    `baskets_used_total` and divided by the vessel's `basket_count`, rounded half up
    to two decimal places. When utilisation is below 60.00 percent the surcharge rate
    is 0.20; otherwise, when utilisation is below 85.00 percent the rate is 0.08; at
    85.00 percent or above there is no surcharge."
    PRD 3.5: "When the gross charge is at least 12,000 cents the credit rate is 0.05;
    otherwise, when the gross charge is at least 8,000 cents the credit rate is 0.03;
    below 8,000 cents there is no credit."

    Design: Corner/calculations/corner_utilization_exactly_sixty_pct_takes_the_softer_surcharge_tier
    """
    world = setup_stored_pallet()
    five_basket = commission_third_vessel()
    cycle = schedule_cycle(five_basket["id"], world["family"]["id"])

    book_load(
        cycle["id"],
        world["lot"]["id"],
        world["contract"]["id"],
        baskets_used=3,
        units_loaded=1000,
        expected_cycle_version=cycle["version"],
    )
    after = read_cycle(cycle["id"])

    assert after["baskets_used_total"] == 3
    assert after["utilization_pct"] == 60.00
    assert after["estimated_cycle_seconds"] == 472
    assert after["estimated_tolling_fee_cents"] == 10476
    assert after["estimated_tolling_fee_cents"] != 11640


def test_the_peak_multiplier_lifts_the_allocation_after_the_remainder_pass():
    """An October run's single load takes the whole 12825-cent fee and is then lifted
    by 1.25 to 16031, so the allocated total deliberately overshoots the fee.

    PRD 3.8: "The seasonal peak uplift is applied last, per load, *after* the
    remainder pass — which means the sum of allocated fees deliberately exceeds the
    cycle's `actual_tolling_fee_cents` by exactly the uplift."
    PRD 3.8: "For each load, if the cycle's `scheduled_start` falls within the backing
    contract's inclusive peak sub-window from `peak_window_start` through
    `peak_window_end`, that load's `allocated_fee_cents` becomes its post-remainder
    allocation multiplied by the contract's `peak_multiplier`, rounded half up to a
    whole cent."

    Design: Corner/calculations/corner_peak_multiplier_applied_after_the_remainder_pass
    """
    world = setup_stored_pallet()
    cycle = schedule_cycle(
        world["vessel"]["id"],
        world["family"]["id"],
        scheduled_start="2026-10-15T09:00:00Z",
    )
    load = book_load(
        cycle["id"],
        world["lot"]["id"],
        world["contract"]["id"],
        baskets_used=2,
        units_loaded=1000,
        expected_cycle_version=cycle["version"],
    )
    set_clock("2026-10-15T09:00:00Z")
    start_cycle(cycle["id"])
    capture_cycle_log(cycle["id"], actual_hold_seconds=195, come_up_seconds=104)

    disposition_cycle(cycle["id"])
    dispositioned = read_cycle(cycle["id"])
    allocated = read_load(load["id"])
    contract = read_contract(world["contract"]["id"])

    assert dispositioned["actual_cycle_seconds"] == 491
    assert dispositioned["actual_tolling_fee_cents"] == 12825
    assert allocated["allocated_fee_cents"] == 16031
    assert allocated["disposition_state"] == "ALLOCATED"
    assert contract["consumed_slots"] == 1
    assert contract["available_slots"] == 4


def test_consuming_exactly_the_minimum_take_settles_without_a_shortfall():
    """One committed slot gives a minimum take of one, and the single consumed slot
    lands exactly on it, so settlement mints nothing at all.

    PRD 3.3: "At close, the **minimum take** is `committed_slots` multiplied by 0.80
    and rounded up to the next whole slot."
    PRD 3.3: "When `consumed_slots` equals the minimum take exactly, `shortfall_slots`
    is zero, `take_or_pay_cents` is zero, and **no** chargeback line is created at
    all."

    Design: Corner/calculations/corner_take_or_pay_is_zero_when_consumption_equals_min_take
    """
    world = setup_dispositioned_clean_cycle(contract_overrides=dict(SPOT_CONTRACT))
    assert read_contract(world["contract"]["id"])["consumed_slots"] == 1

    settled = validate_success(
        api_client.close_contract(world["contract"]["id"], ADMIN), 200
    )

    assert settled["status"] == "CLOSED"
    assert settled["consumed_slots"] == 1
    assert settled["shortfall_slots"] == 0
    assert settled["take_or_pay_cents"] == 0
    assert list_chargeback_lines(customer_id=world["customer"]["id"]) == []
    assert read_customer(world["customer"]["id"])["chargeback_balance_cents"] == 0


def test_settling_a_contract_that_was_never_booked_bills_the_whole_slot():
    """Nothing was consumed against the single committed slot, so the shortfall is one
    slot and the take-or-pay line is the slot price to the cent.

    PRD 3.3: "`shortfall_slots` is then the minimum take minus `consumed_slots`,
    floored at zero, so a customer who took at least the minimum has no shortfall."
    PRD 3.3: "When `take_or_pay_cents` is greater than zero, the close additionally
    mints a chargeback line with `basis` of `TAKE_OR_PAY_SHORTFALL` carrying the
    contract's identifier in `contract_id`, the customer's identifier in
    `customer_id`, `amount_cents` equal to `take_or_pay_cents`, and `status` of
    `PENDING`, and the customer's `chargeback_balance_cents` rises by that amount."

    Design: Corner/calculations/corner_take_or_pay_bills_the_full_slot_when_nothing_was_consumed
    """
    set_clock(CLOCK_AUG03)
    customer = register_customer()
    contract = open_active_contract(customer["id"], **SPOT_CONTRACT)

    settled = validate_success(api_client.close_contract(contract["id"], ADMIN), 200)
    lines = list_chargeback_lines(customer_id=customer["id"])

    assert settled["status"] == "CLOSED"
    assert settled["consumed_slots"] == 0
    assert settled["shortfall_slots"] == 1
    assert settled["take_or_pay_cents"] == 60000
    assert len(lines) == 1
    assert lines[0]["basis"] == "TAKE_OR_PAY_SHORTFALL"
    assert lines[0]["amount_cents"] == 60000
    assert lines[0]["status"] == "PENDING"
    assert lines[0]["contract_id"] == contract["id"]
    assert lines[0]["cycle_load_id"] is None
    assert read_customer(customer["id"])["chargeback_balance_cents"] == 60000


def test_the_trailing_window_keeps_its_ninetieth_day_and_drops_the_next_one():
    """A cycle dispositioned on 3 August is still inside the window swept on
    1 November — exactly ninety days later — and falls out of it one day after that.

    PRD 3.9: "The window runs from 90 days before the current logical clock instant
    through that instant, inclusive at both ends."
    PRD 3.9: "The sweep reports `expired_qualification_count`, the number of
    qualifications it moved to `EXPIRED`; `customers_rescored`, the number of
    customers whose trailing rate it recomputed; and `closed_at`, the logical clock
    instant at which the sweep ran."

    Design: Corner/calculations/corner_trailing_window_includes_the_ninetieth_day_and_drops_the_ninety_first
    """
    world = setup_inspected_load()
    assert world["load"]["leaker_ppm"] == 3000

    set_clock("2026-11-01T08:00:00Z")
    ninetieth_day = run_day_close()
    on_the_boundary = read_customer(world["customer"]["id"])
    set_clock("2026-11-02T08:00:00Z")
    run_day_close()
    past_the_boundary = read_customer(world["customer"]["id"])

    assert on_the_boundary["trailing_leaker_ppm"] == 3000
    assert ninetieth_day["expired_qualification_count"] == 0
    assert ninetieth_day["customers_rescored"] == 1
    assert past_the_boundary["trailing_leaker_ppm"] == 0
    assert read_load(world["load"]["id"])["leaker_ppm"] == 3000


def test_a_marginal_package_result_makes_an_otherwise_perfect_run_unacceptable():
    """Pressure, hold time and log reduction all clear their bars, but package
    integrity must read PASS, so the run earns no acceptable count.

    PRD 3.2: "The service then computes `run_verdict`: it is `ACCEPTABLE` when the
    `package_integrity_result` is `PASS` **and** the measured pressure is at least the
    qualification's `pressure_mpa` **and** the measured hold time is at least the
    qualification's `hold_time_seconds` **and** the achieved log reduction is at least
    the qualification's `target_log_reduction`; if any one of those four fails, the
    verdict is `UNACCEPTABLE`."
    PRD 3.2: "The first run appended to a `SUBMITTED` qualification advances it
    `SUBMITTED → UNDER_VALIDATION`."

    Design: Corner/calculations/corner_marginal_package_integrity_makes_a_run_unacceptable
    """
    set_clock(CLOCK_AUG03)
    customer = register_customer()
    family = define_family()
    qualification = open_qualification(customer["id"], family["id"])
    submit_qualification(qualification["id"], customer["id"])

    run = validate_success(
        api_client.append_validation_run(
            qualification["id"],
            validation_run_payload(
                measured_pressure_mpa=620.0,
                measured_hold_time_seconds=200,
                achieved_log_reduction=6.0,
                package_integrity_result="MARGINAL",
                units_tested=50,
                leaker_count=1,
            ),
            QUALITY,
        ),
        201,
    )
    after = read_qualification(qualification["id"])

    assert run["run_verdict"] == "UNACCEPTABLE"
    assert run["recorded_by_user_id"] == QM_ALICE
    assert after["validation_run_acceptable_count"] == 0
    assert after["status"] == "UNDER_VALIDATION"
