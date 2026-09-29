"""What counts as delivered, and what an unaccountable count costs."""

from decimal import Decimal

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    ADMIN_HQ_HEADERS,
    assert_cents,
    make_club_headers,
)
from test_helpers.fixtures import (
    approve,
    assign,
    check_in,
    check_out,
    close_out,
    confirm_assignment,
    new_club,
    new_demo_event,
    new_demonstrator,
    new_manufacturer,
    new_non_food_product,
    set_clock,
    ship,
    receive,
    submit,
)
from test_helpers.types import (
    AssignmentRole,
    DayPart,
    ProductCategory,
    ReconStatus,
    ShipmentStatus,
)


def _decimal2(value):
    """Coerce a two-decimal API value into an exact Decimal for comparison."""
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _completed_event(api, vendor, club, product, requested_sample_cases, worker_name):
    """Drive one non-food booking through its demonstration day to `COMPLETED`."""
    worker = new_demonstrator(
        api, club["id"], full_name=worker_name, hourly_rate_cents=2200
    )
    event = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=requested_sample_cases,
    )
    submit(api, event["id"], vendor["id"])
    approve(api, event["id"], club["id"])
    return event, worker


def _work_the_shift(api, event, club, worker):
    """Staff, execute and close out one already-confirmed demonstration."""
    assignment = assign(api, event["id"], worker["id"], AssignmentRole.LEAD)
    set_clock(api, "2026-09-14T14:00:00Z")
    confirm_assignment(api, assignment["id"], worker["id"])
    check_in(api, assignment["id"], worker["id"], "2026-09-14T08:15:00Z")
    check_out(api, assignment["id"], worker["id"], "2026-09-14T12:45:00Z")
    close_out(api, event["id"], club["id"])


def test_a_load_still_on_the_road_contributes_nothing_to_the_delivered_count(api):
    """PRD §3.7: "`cases_delivered` is the total `cases_received` across the event's shipments whose `shipment_status` is `DELIVERED` or `SHORT`; shipments still `IN_TRANSIT` and shipments `REJECTED` contribute nothing."

    PRD §3.7: "`units_delivered` is `cases_delivered` multiplied by `units_per_case`."

    PRD §3.7: "`units_per_case` is a snapshot of the product's `samples_per_case` taken at the moment the reconciliation is created, so a later change to the SKU never rewrites a filed reconciliation."

    PRD §3.7: "It settles at `BALANCED` when `variance_units` is exactly zero, or when `variance_pct` is at or below a tolerance of 2.00 percent; it settles at `VARIANCE_FLAGGED` when `variance_units` is non-zero **and** `variance_pct` is strictly above 2.00 percent."

    PRD §3.7: "In both cases `write_off_cost_cents` stays at zero."

    Design: Corner/calculations/reconciliation_ignores_shipments_still_in_transit
    """
    vendor = new_manufacturer(api, legal_name="Westerly Provisions", credit_limit_cents=900_000)
    club = new_club(
        api,
        club_number="C6021",
        name="Westerly Club 6021",
        daily_event_capacity=3,
        food_station_count=1,
    )
    product = new_non_food_product(
        api,
        vendor["id"],
        sku="WP-CAN-021",
        name="Canister Set",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=1100,
        samples_per_case=10,
        weekly_sample_case_pool=20,
    )
    event, worker = _completed_event(api, vendor, club, product, 4, "Wren Ashcombe")

    arrived = ship(api, event["id"], vendor["id"], 3, carrier_reference="TRK-66021-A")
    received = receive(api, arrived["id"], club["id"], 3)
    assert received["shipment_status"] == ShipmentStatus.DELIVERED

    on_the_road = ship(api, event["id"], vendor["id"], 1, carrier_reference="TRK-66021-B")
    assert on_the_road["shipment_status"] == ShipmentStatus.IN_TRANSIT

    _work_the_shift(api, event, club, worker)

    reconciliation = validate_success(
        api.create_reconciliation(
            event["id"],
            {"units_sampled": 28, "units_wasted": 1, "units_returned": 1},
            make_club_headers(club["id"]),
        ),
        201,
    )

    assert reconciliation["cases_delivered"] == 3
    assert reconciliation["units_per_case"] == 10
    assert reconciliation["units_delivered"] == 30
    assert reconciliation["variance_units"] == 0
    assert _decimal2(reconciliation["variance_pct"]) == Decimal("0.00")
    assert reconciliation["recon_status"] == ReconStatus.BALANCED
    assert_cents(reconciliation["write_off_cost_cents"], 0, "write_off_cost_cents")
    assert reconciliation["units_sampled"] == 28
    assert reconciliation["units_returned"] == 1


def test_accounting_for_more_units_than_arrived_is_charged_at_absolute_value(api):
    """PRD §3.7: "`variance_units` is `units_delivered` less the sum of `units_sampled`, `units_wasted` and `units_returned`; a positive figure means units nobody can account for, a negative figure means more units were accounted for than were ever delivered."

    PRD §3.7: "`variance_pct` reads 0.00 whenever `units_delivered` is zero — that zero-denominator guard is part of the contract, not an implementation nicety — and otherwise is the absolute value of `variance_units` divided by `units_delivered`, multiplied by 100, rounded half-up to two decimal places."

    PRD §3.7: "The conservation identity that must hold on every row is that `units_delivered` equals `units_sampled` plus `units_wasted` plus `units_returned` plus `variance_units`."

    PRD §3.7: "It moves `recon_status` to `WRITTEN_OFF`, sets `write_off_cost_cents` to the absolute value of `variance_units` multiplied by the product's `unit_cost_cents`, rounded half-up to whole cents, and increments the reconciliation's `version` by 1."

    Design: Corner/calculations/over_consumption_yields_a_negative_variance_and_an_absolute_value_write_off
    """
    vendor = new_manufacturer(api, legal_name="Yardley Mercantile", credit_limit_cents=900_000)
    club = new_club(
        api,
        club_number="C6022",
        name="Yardley Club 6022",
        daily_event_capacity=3,
        food_station_count=1,
    )
    product = new_non_food_product(
        api,
        vendor["id"],
        sku="YM-SOP-022",
        name="Hand Soap Refill",
        category=ProductCategory.HOUSEHOLD,
        unit_cost_cents=137,
        samples_per_case=10,
        weekly_sample_case_pool=20,
    )
    event, worker = _completed_event(api, vendor, club, product, 2, "Yusuf Karam")

    shipment = ship(api, event["id"], vendor["id"], 2, carrier_reference="TRK-66022")
    receive(api, shipment["id"], club["id"], 2)
    _work_the_shift(api, event, club, worker)

    reconciliation = validate_success(
        api.create_reconciliation(
            event["id"],
            {"units_sampled": 25, "units_wasted": 0, "units_returned": 0},
            make_club_headers(club["id"]),
        ),
        201,
    )

    assert reconciliation["units_delivered"] == 20
    assert reconciliation["variance_units"] == -5
    assert _decimal2(reconciliation["variance_pct"]) == Decimal("25.00")
    assert reconciliation["recon_status"] == ReconStatus.VARIANCE_FLAGGED
    assert reconciliation["units_delivered"] == (
        reconciliation["units_sampled"]
        + reconciliation["units_wasted"]
        + reconciliation["units_returned"]
        + reconciliation["variance_units"]
    )

    written_off = validate_success(
        api.write_off_reconciliation(
            reconciliation["id"],
            {"note": "over-sampled beyond delivery"},
            ADMIN_HQ_HEADERS,
        )
    )

    assert written_off["recon_status"] == ReconStatus.WRITTEN_OFF
    assert_cents(written_off["write_off_cost_cents"], 685, "write_off_cost_cents")
    assert written_off["version"] == reconciliation["version"] + 1
    assert written_off["units_sampled"] == 25
    assert written_off["units_returned"] == 0
