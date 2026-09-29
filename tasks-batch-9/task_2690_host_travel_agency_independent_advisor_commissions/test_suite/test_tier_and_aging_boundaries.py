"""Inclusive boundaries: the tier floor met exactly, and the aging band edge."""
import pytest

from test_helpers import (
    api_client,
    confirm_booking,
    controller,
    new_booking,
    new_client,
    new_split_schedule,
    new_supplier,
    open_run,
    post_run,
    read_advisor,
    read_booking,
    read_supplier,
    record_receipt,
    set_clock,
    setup_active_advisor,
    statements_for_run,
    validate_success,
)

STANDARD_TIERS = [
    {"tier_level": 1, "min_production_cents": 0, "advisor_pct": 0.70},
    {"tier_level": 2, "min_production_cents": 5_000_000, "advisor_pct": 0.80},
]
FLAT_FEE_TIERS = [{"min_share_cents": 0, "fee_pct": 0.05}]

FIRST_REMIT_CLOCK = "2026-10-05T00:00:00Z"
FIRST_REMIT_DATE = "2026-10-05"
FIRST_PERIOD = "2026-10"
SECOND_REMIT_CLOCK = "2026-11-05T00:00:00Z"
SECOND_REMIT_DATE = "2026-11-05"
SECOND_PERIOD = "2026-11"


def _plain_scenario(supplier_overrides):
    schedule = new_split_schedule(
        name="Standard 2026",
        tiers=STANDARD_TIERS,
        platform_fee_tiers=FLAT_FEE_TIERS,
        chargeback_retention_pct=0.10,
    )
    supplier = new_supplier(**supplier_overrides)
    ctx = setup_active_advisor(
        state="NY",
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        schedule=schedule,
        suppliers=[supplier],
    )
    client = new_client(
        ctx["advisor"]["id"],
        full_name="Nadia Okoye",
        home_state_code="NY",
        max_concurrent_trips=4,
    )
    return {"advisor": ctx["advisor"], "client": client, "supplier": supplier}


MERIDIAN = {
    "name": "Meridian Air",
    "accreditation_scheme": "ARC",
    "base_commission_pct": 0.10,
    "preferred_override_commission_pct": 0.12,
    "rate_ceiling_pct": 0.20,
    "max_commission_per_booking_cents": 9_000_000,
    "remit_terms_days": 30,
}

NORTHWIND = {
    "name": "Northwind Tours",
    "accreditation_scheme": "IATA",
    "base_commission_pct": 0.10,
    "preferred_override_commission_pct": 0.12,
    "rate_ceiling_pct": 0.20,
    "max_commission_per_booking_cents": 2_000_000,
    "remit_terms_days": 30,
}


def _confirmed(scenario, gross, start, end):
    booking = new_booking(
        scenario["advisor"]["id"],
        scenario["supplier"]["id"],
        scenario["client"]["id"],
        channel="SUPPLIER_DIRECT",
        payment_method="MERCHANT_DIRECT",
        gross_sale_cents=gross,
        travel_start_date=start,
        travel_end_date=end,
    )
    return confirm_booking(booking["id"], scenario["supplier"]["id"])


def _one_cent_short_of_the_tier_floor():
    """A first period that collects 4,999,999 cents and a second that collects 1."""
    scenario = _plain_scenario(MERIDIAN)
    big = _confirmed(scenario, 49_999_990, "2026-05-01", "2026-05-10")
    small = _confirmed(scenario, 10, "2026-05-11", "2026-05-20")

    set_clock(FIRST_REMIT_CLOCK)
    record_receipt(big["id"], scenario["supplier"]["id"], 4_999_999, FIRST_REMIT_DATE)
    first_run = open_run(FIRST_PERIOD)
    first_run = validate_success(
        api_client.calculate_settlement_run(first_run["id"], controller("ctrl-1"))
    )
    post_run(first_run["id"], "ctrl-2")

    set_clock(SECOND_REMIT_CLOCK)
    record_receipt(small["id"], scenario["supplier"]["id"], 1, SECOND_REMIT_DATE)
    second_run = open_run(SECOND_PERIOD)

    scenario.update(
        {"big": big, "small": small, "first_run": first_run, "second_run": second_run}
    )
    return scenario


def test_a_final_basis_exactly_on_a_tier_floor_selects_the_higher_tier():
    """PRD §3.5: "Tier selection then takes the schedule referenced by the advisor's
    `ACTIVE` agreement, keeps every tier whose `min_production_cents` is at or below the
    basis — the boundary is inclusive, so a basis exactly equal to a tier's floor selects
    that tier — and picks the surviving tier with the greatest floor, which is unique
    because floors increase strictly."

    Design: Difficulty/boundary_precision_check/split_tier_boundary_exact_five_million_final_production
    """
    scenario = _one_cent_short_of_the_tier_floor()

    validate_success(
        api_client.calculate_settlement_run(
            scenario["second_run"]["id"], controller("ctrl-1")
        )
    )

    advisor = read_advisor(scenario["advisor"]["id"])
    assert advisor["production_ytd_final_cents"] == 5_000_000
    assert advisor["split_tier_final"] == 2

    small = read_booking(scenario["small"]["id"])
    assert small["settled_tier_level"] == 2
    assert small["settled_share_cents"] == 1


def test_the_period_one_cent_below_the_floor_settled_at_the_lower_tier():
    """PRD §3.8: "The statement also records `tier_level_applied` as the advisor's
    `split_tier_final` as observed at calculate time and `advisor_pct_applied` as the
    `advisor_pct` of the tier that same final basis selects."

    Design: Difficulty/boundary_precision_check/split_tier_boundary_exact_five_million_final_production
    """
    scenario = _one_cent_short_of_the_tier_floor()
    assert scenario["first_run"]["advisor_share_total_cents"] == 3_499_999

    big = read_booking(scenario["big"]["id"])
    assert big["received_commission_cents"] == 4_999_999
    assert big["settled_tier_level"] == 1
    assert big["settled_share_cents"] == 3_499_999

    second = validate_success(
        api_client.calculate_settlement_run(
            scenario["second_run"]["id"], controller("ctrl-1")
        )
    )
    assert second["gross_commission_cents"] == 1

    statement = statements_for_run(second["id"])[0]
    assert statement["tier_level_applied"] == 2
    assert statement["advisor_pct_applied"] == pytest.approx(0.80)


def _uncollected_receivable():
    """A confirmed booking the supplier never paid, due on 2026-07-15."""
    scenario = _plain_scenario(NORTHWIND)
    booking = _confirmed(scenario, 1_000_150, "2026-06-05", "2026-06-15")
    scenario["booking"] = booking
    return scenario


def test_an_age_of_exactly_thirty_days_stays_in_the_first_bucket():
    """PRD §3.7: "An age of 0 through 30 days inclusive accumulates into
    `aging_0_30_cents`; 31 through 60 inclusive into `aging_31_60_cents`; 61 through 90
    inclusive into `aging_61_90_cents`; and 91 days or more into `aging_over_90_cents`."

    Design: Difficulty/boundary_precision_check/aging_bucket_edge_thirty_versus_thirty_one_days
    """
    scenario = _uncollected_receivable()
    assert scenario["booking"]["expected_commission_cents"] == 100_015
    assert scenario["booking"]["commission_status"] == "EXPECTED"

    set_clock("2026-08-14T00:00:00Z")

    supplier = read_supplier(scenario["supplier"]["id"])
    assert supplier["aging_0_30_cents"] == 100_015
    assert supplier["aging_31_60_cents"] == 0
    assert supplier["total_outstanding_cents"] == 100_015


def test_the_thirty_first_day_moves_the_receivable_into_the_second_bucket():
    """PRD §3.7: "Both edges of every band are inclusive, so an age of exactly 30 lands
    in the first bucket and exactly 31 in the second."

    Design: Difficulty/boundary_precision_check/aging_bucket_edge_thirty_versus_thirty_one_days
    """
    scenario = _uncollected_receivable()
    set_clock("2026-08-14T00:00:00Z")
    assert read_supplier(scenario["supplier"]["id"])["aging_0_30_cents"] == 100_015

    set_clock("2026-08-15T00:00:00Z")

    supplier = read_supplier(scenario["supplier"]["id"])
    assert supplier["aging_0_30_cents"] == 0
    assert supplier["aging_31_60_cents"] == 100_015
    assert supplier["aging_61_90_cents"] == 0
    assert supplier["aging_over_90_cents"] == 0
    assert supplier["total_outstanding_cents"] == 100_015
