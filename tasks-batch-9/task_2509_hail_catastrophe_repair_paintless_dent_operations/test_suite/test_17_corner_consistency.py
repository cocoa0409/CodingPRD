"""One passing inspection, then every derived figure read back with no second write."""

from test_helpers import (
    CLOCK_T0,
    assert_technician_pay,
    assert_throughput_values,
    assert_ticket_pay,
    bring_vehicle_to,
    make_quality_inspector_headers,
    quality_inspection_payload,
    read_technician,
    read_throughput_summary,
    read_vehicle,
    read_work_ticket,
    setup_operational_facility,
    tech_id,
    validate_success,
)


def test_the_passing_inspection_leaves_nothing_for_a_later_write_to_finish(api):
    """PRD §3.7: "A `PASS` moves the vehicle `QC_PENDING` → `READY` and triggers the
    crew-pay cascade, which runs two hops. Hop one: every work ticket of that vehicle
    whose `status` is `SUBMITTED` moves `SUBMITTED` → `APPROVED`, which is terminal,
    receiving `payable_flat_cents`, `payable_pooled_cents`, `payable_cents` and
    `pay_model_applied` in the process, each with a `version` increment. Hop two,
    caused by hop one: every technician holding one of those newly approved tickets
    recomputes `accrued_pay_cents` and `approved_ticket_count`."

    PRD §3.7: "The pay computation itself is where the two crew-pay models diverge,
    and both variants are always computed and stored so that the site's choice is
    auditable."

    PRD §3.7: "A ticket's work value is the labour pool multiplied by that ticket's
    `labor_units` divided by the total labour units, rounded half up to whole cents;
    the ticket's `payable_flat_cents` is that work value multiplied by the
    technician's own `flat_split_pct`, again rounded half up to whole cents."

    PRD §3.7: "Each approved ticket records `pay_model_applied` as a copy of the
    vehicle's facility `pay_model` at the moment of approval, and `payable_cents` is
    `payable_flat_cents` when that copy is `FLAT` and `payable_pooled_cents` when it
    is `POOLED`. Only `payable_cents` feeds a technician's `accrued_pay_cents`."

    Design: Corner/consistency_model/qc_pass_makes_the_whole_pay_cascade_visible_without_any_re_read_delay
    """
    scenario = setup_operational_facility(api, technicians=("TA", "TI"))
    car = bring_vehicle_to(
        api,
        scenario,
        "QC_PENDING",
        damage_profile="single_panel_conventional",
        rental_required=False,
    )
    vehicle_id = car["vehicle_id"]
    worker = tech_id(scenario, "TA")
    inspector = tech_id(scenario, "TI")
    ticket_id = car["work_tickets"][0]["id"]
    assert car["vehicle"]["approved_repair_cents"] == 77000

    inspection = validate_success(
        api.create_quality_inspection(
            quality_inspection_payload(vehicle_id, inspector, "PASS"),
            make_quality_inspector_headers(inspector),
        ),
        201,
    )
    assert inspection["result"] == "PASS"
    assert inspection["rework_index"] == 0
    assert inspection["defect_panel_codes"] == []
    assert inspection["inspected_at"] == CLOCK_T0

    vehicle = read_vehicle(api, vehicle_id)
    assert vehicle["repair_status"] == "READY"
    assert vehicle["rework_count"] == 0

    # Labour pool 42,350; the lone ticket takes it all, then 45 percent of that.
    assert_ticket_pay(
        read_work_ticket(api, ticket_id),
        payable_flat_cents=19058,
        payable_pooled_cents=21175,
        payable_cents=19058,
        pay_model_applied="FLAT",
        status="APPROVED",
    )

    # First read after the PASS, with no intervening write of any kind.
    assert_technician_pay(
        read_technician(api, worker), accrued_pay_cents=19058, approved_ticket_count=1
    )
    assert_technician_pay(
        read_technician(api, inspector), accrued_pay_cents=0, approved_ticket_count=0
    )

    assert_throughput_values(
        read_throughput_summary(api, scenario["facility_id"]),
        vehicles_ready=1,
        vehicles_in_repair=0,
        released_count=0,
        staging_slots_occupied=1,
        open_vehicle_count=1,
    )
