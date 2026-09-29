"""The append-only measurement ledger carries no revision stamps."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    ADMIN_HQ_HEADERS,
    assert_ledger_row_fields,
    make_manufacturer_headers,
)
from test_helpers.factories import lift_measurement_payload
from test_helpers.fixtures import (
    approve,
    assign,
    check_in,
    check_out,
    close_out,
    confirm_assignment,
    event_version,
    file_reconciliation,
    new_baseline,
    new_club,
    new_demo_event,
    new_demonstrator,
    new_manufacturer,
    new_non_food_product,
    receive,
    set_clock,
    ship,
    submit,
)
from test_helpers.types import (
    AssignmentRole,
    DayPart,
    MeasurementStatus,
    MeasurementVariant,
    ProductCategory,
    ReconStatus,
)


def test_a_posted_measurement_carries_no_version_and_no_updated_at(api):
    """PRD §2.4: "It is an **append-only ledger**: a measurement row declares only `id` and `created_at`, and carries neither `updated_at` nor `version`."

    PRD §3.8: "A new measurement opens with `measurement_status` `POSTED`, and posting it retires the event's previous measurement of the *same* variant: any earlier measurement on the same event with the same `measurement_variant` whose `measurement_status` is `POSTED` or `STALE` is moved to `SUPERSEDED`."

    Design: Corner/entities/sales_lift_measurement_is_immutable_with_no_version_and_no_update_path
    """
    vendor = new_manufacturer(api, legal_name="Hollimere Goods", credit_limit_cents=900_000)
    club = new_club(api, club_number="C6007", daily_event_capacity=3, food_station_count=1)
    product = new_non_food_product(
        api,
        vendor["id"],
        sku="HG-KET-007",
        name="Electric Kettle",
        category=ProductCategory.ELECTRONICS,
        unit_cost_cents=3900,
        samples_per_case=2,
        weekly_sample_case_pool=12,
    )
    baseline = new_baseline(
        api,
        club["id"],
        product["id"],
        baseline_weekly_units=70,
        baseline_unit_price_cents=500,
        baseline_week_start_date="2026-09-14",
    )
    worker = new_demonstrator(api, club["id"], full_name="Imre Voss", hourly_rate_cents=2000)
    event = new_demo_event(
        api,
        vendor["id"],
        club["id"],
        product["id"],
        event_date="2026-09-14",
        day_part=DayPart.MORNING,
        requested_sample_cases=2,
    )
    submit(api, event["id"], vendor["id"])
    approve(api, event["id"], club["id"])

    shipment = ship(api, event["id"], vendor["id"], 2, carrier_reference="TRK-66007")
    receive(api, shipment["id"], club["id"], 2)

    assignment = assign(api, event["id"], worker["id"], AssignmentRole.LEAD)
    set_clock(api, "2026-09-14T14:00:00Z")
    confirm_assignment(api, assignment["id"], worker["id"])
    check_in(api, assignment["id"], worker["id"], "2026-09-14T08:15:00Z")
    check_out(api, assignment["id"], worker["id"], "2026-09-14T12:45:00Z")
    close_out(api, event["id"], club["id"])
    reconciliation = file_reconciliation(api, event["id"], club["id"], 4, 0, 0)

    response = api.create_lift_measurement(
        event["id"],
        lift_measurement_payload(
            MeasurementVariant.PROVISIONAL, 40, event_version(api, event["id"])
        ),
        ADMIN_HQ_HEADERS,
    )

    measurement = validate_success(response, 201)
    assert measurement["measurement_status"] == MeasurementStatus.POSTED
    assert_ledger_row_fields(measurement)

    listed = validate_success(
        api.list_lift_measurements(event["id"], make_manufacturer_headers(vendor["id"]))
    )
    assert len(listed) == 1
    assert_ledger_row_fields(listed[0])

    assert reconciliation["recon_status"] == ReconStatus.BALANCED
    stored_baseline = validate_success(api.get_baseline(baseline["id"], ADMIN_HQ_HEADERS))
    assert stored_baseline["restatement_count"] == 0
