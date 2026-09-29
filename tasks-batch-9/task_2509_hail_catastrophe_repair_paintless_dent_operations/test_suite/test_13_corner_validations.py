"""Validations whose scope, timing or cumulative reach is easy to get wrong."""

from test_helpers import (
    CLOCK_T0,
    CREW_COORDINATOR,
    DEFAULT_VEHICLE,
    DIRECTOR,
    INTAKE_ADVISOR,
    SHOP_ESTIMATOR,
    activate_rate_agreement,
    activate_storm_event,
    add_second_facility,
    approve_required_permits,
    assert_money_chain,
    assert_supplement_state,
    assert_technician_pay,
    assert_triage_outcome,
    authorize_vehicle,
    bring_vehicle_to,
    commission_facility,
    create_deployment,
    create_facility,
    create_insurer,
    create_storm_event,
    create_technician,
    crew_deployment_payload,
    draft_rate_agreement,
    estimate_vehicle,
    file_supplement,
    ids_of,
    make_pdr_technician_headers,
    make_quality_inspector_headers,
    open_work_ticket,
    quality_inspection_payload,
    read_deployment,
    read_facility,
    read_insurer,
    read_technician,
    read_vehicle,
    read_vehicle_version,
    read_work_ticket,
    release_vehicle,
    review_supplement,
    set_clock,
    set_deployment_status,
    setup_operational_facility,
    submit_work_ticket,
    supplement_payload,
    target_storm_event,
    tech_id,
    triage_vehicle,
    validate_error,
    validate_paginated,
    validate_success,
    vehicle_payload,
    work_ticket_payload,
)


def test_a_zero_unit_ticket_is_creatable_unsubmittable_and_blocks_the_handover(api):
    """PRD §3.7: "A `PdrTechnician` opens a ticket naming the `vehicle_id`, their
    own `technician_id`, the `labor_units` hour-equivalents claimed (zero or more),
    the `dents_repaired` pushed on that ticket and the `panels_worked` touched (both
    zero or more)."

    PRD §3.7: "The ticket must be `OPEN`, its `labor_units` must be strictly greater
    than zero — a zero-labour submission is rejected with `ERR_ZERO_LABOR_UNITS` —
    and the vehicle must still be `IN_REPAIR`; a ticket in any other state is
    rejected with `ERR_INVALID_LIFECYCLE_STATE`."

    PRD §3.7: "The submission that leaves **no** `OPEN` ticket on the vehicle,
    provided at least one ticket on that vehicle is now `SUBMITTED`, additionally
    drives the vehicle `IN_REPAIR` → `QC_PENDING` with a `version` increment of its
    own."

    Design: Corner/validations/zero_unit_ticket_cannot_submit_and_pins_the_vehicle_in_repair
    """
    scenario = setup_operational_facility(api, technicians=("TA", "TI"))
    car = bring_vehicle_to(
        api,
        scenario,
        "IN_REPAIR",
        damage_profile="single_panel_conventional",
        rental_required=False,
    )
    vehicle_id = car["vehicle_id"]
    worker = tech_id(scenario, "TA")
    inspector = tech_id(scenario, "TI")

    # Zero labour clears the range check, so the ticket is born.
    empty = validate_success(
        api.create_work_ticket(
            work_ticket_payload(
                vehicle_id, worker, labor_units=0, dents_repaired=0, panels_worked=0
            ),
            make_pdr_technician_headers(worker),
        ),
        201,
    )
    assert empty["labor_units"] == 0
    assert empty["status"] == "OPEN"

    refused = api.submit_work_ticket(empty["id"], make_pdr_technician_headers(worker))
    validate_error(refused, "ERR_ZERO_LABOR_UNITS", 422)

    still_open = read_work_ticket(api, empty["id"])
    assert still_open["status"] == "OPEN"
    assert still_open["version"] == empty["version"]

    real = open_work_ticket(api, vehicle_id, worker)
    assert submit_work_ticket(api, real["id"], worker)["status"] == "SUBMITTED"

    # The unsubmittable ticket is still `OPEN`, so the handover never fires.
    assert read_vehicle(api, vehicle_id)["repair_status"] == "IN_REPAIR"

    too_early = api.create_quality_inspection(
        quality_inspection_payload(vehicle_id, inspector, "PASS"),
        make_quality_inspector_headers(inspector),
    )
    validate_error(too_early, "ERR_INVALID_VEHICLE_REPAIR_STATE", 409)

    _, open_meta = validate_paginated(
        api.list_work_tickets(
            SHOP_ESTIMATOR, {"vehicle_id": vehicle_id, "status": "OPEN"}
        )
    )
    _, submitted_meta = validate_paginated(
        api.list_work_tickets(
            SHOP_ESTIMATOR, {"vehicle_id": vehicle_id, "status": "SUBMITTED"}
        )
    )
    assert open_meta["total_count"] == 1
    assert submitted_meta["total_count"] == 1

    assert_technician_pay(
        read_technician(api, worker), accrued_pay_cents=0, approved_ticket_count=0
    )


def test_the_same_vin_is_legal_next_door_and_legal_again_once_the_twin_is_gone(api):
    """PRD §3.5: "Intake also enforces VIN uniqueness within the lot: no other
    vehicle at the same facility may carry the same `vin` while its `repair_status`
    is anything other than `RELEASED` or `TOWED_OUT`, and a duplicate is rejected
    with `ERR_DUPLICATE_VIN_AT_FACILITY`. A car released last week may legitimately
    come back under the same VIN."

    PRD §3.6: "Next the total-loss floor is computed as 75 percent of the vehicle's
    `acv_cents`, rounded half up to whole cents. The candidate cost plus the
    projected rental exposure is compared against that floor, and the comparison is
    **inclusive**: if the sum is greater than or equal to the floor, the vehicle is
    totalled — `triage_disposition` becomes `TOTAL_LOSS` and `approved_repair_cents`
    is set to 0 — and a sum exactly equal to the floor totals the car."

    PRD §3.9: "A repaired car moves `READY` → `RELEASED`; a totalled car moves
    `TOTAL_LOSS_PENDING` → `TOWED_OUT`."

    Design: Corner/validations/duplicate_vin_is_scoped_to_the_facility_and_to_open_vehicles
    """
    scenario = setup_operational_facility(api)
    annex = add_second_facility(
        api,
        scenario,
        name="Salina Annex Lot",
        state_code="KS",
        address="700 E Crawford St",
        staging_slot_count=4,
        pay_model="FLAT",
        technicians=("TC",),
    )
    shared_vin = DEFAULT_VEHICLE["vin"]
    twin = bring_vehicle_to(
        api,
        scenario,
        "MATRIX",
        damage_profile="single_panel_conventional",
        acv_cents=100000,
        rental_required=False,
    )

    duplicate = api.create_vehicle(
        vehicle_payload(
            scenario["facility_id"],
            scenario["insurer_id"],
            acv_cents=100000,
            rental_required=False,
        ),
        INTAKE_ADVISOR,
    )
    validate_error(duplicate, "ERR_DUPLICATE_VIN_AT_FACILITY", 409)

    # The key is scoped to the lot, so the annex may hold the same VIN.
    next_door = validate_success(
        api.create_vehicle(
            vehicle_payload(
                annex["facility_id"],
                scenario["insurer_id"],
                acv_cents=100000,
                rental_required=False,
            ),
            INTAKE_ADVISOR,
        ),
        201,
    )
    assert next_door["vin"] == shared_vin
    assert next_door["facility_id"] == annex["facility_id"]

    # 77,000 conventional against a 75,000 floor writes the twin off.
    estimate_vehicle(api, twin["vehicle_id"])
    totalled = triage_vehicle(api, twin["vehicle_id"])
    assert_triage_outcome(
        totalled,
        triage_disposition="TOTAL_LOSS",
        approved_repair_cents=0,
        repair_status="TOTAL_LOSS_PENDING",
    )

    authorize_vehicle(api, twin["vehicle_id"], scenario["insurer_id"])
    towed = release_vehicle(api, twin["vehicle_id"])
    assert towed["repair_status"] == "TOWED_OUT"

    # With the twin terminal the same VIN is admissible at the first lot again.
    again = validate_success(
        api.create_vehicle(
            vehicle_payload(
                scenario["facility_id"],
                scenario["insurer_id"],
                acv_cents=100000,
                rental_required=False,
            ),
            INTAKE_ADVISOR,
        ),
        201,
    )
    assert again["vin"] == shared_vin
    assert again["id"] != twin["vehicle_id"]

    rows, meta = validate_paginated(
        api.list_vehicles(DIRECTOR, {"facility_id": scenario["facility_id"]})
    )
    assert meta["total_count"] == 2
    assert sorted(ids_of(rows)) == sorted([twin["vehicle_id"], again["id"]])

    # The tow-out freed the slot before the re-intake took one.
    assert read_facility(api, scenario["facility_id"])["staging_slots_occupied"] == 1


LAPSE_CLOCK = "2026-08-20T08:00:00Z"


def _a_lot_whose_only_technician_loses_their_licence(api):
    """A working lot staffed by a `TA` whose Kansas licence lapses on 2026-08-10."""
    set_clock(api, CLOCK_T0)
    event = create_storm_event(api)
    target_storm_event(api, event["id"])
    facility = create_facility(api, event["id"])
    approve_required_permits(api, facility["id"])

    technician = create_technician(api, "TA", license_expires_at="2026-08-10")
    deployment = create_deployment(api, technician["id"], facility["id"])
    deployment = set_deployment_status(api, deployment["id"], "ON_SITE")

    facility = commission_facility(api, facility["id"])
    activate_storm_event(api, event["id"])

    insurer = create_insurer(api)
    agreement = draft_rate_agreement(api, insurer["id"], event["id"])
    activate_rate_agreement(api, agreement["id"], insurer["id"])

    scenario = {
        "event_id": event["id"],
        "facility_id": facility["id"],
        "insurer_id": insurer["id"],
        "technicians": {"TA": technician},
        "deployments": {"TA": deployment},
    }
    car = bring_vehicle_to(
        api,
        scenario,
        "IN_REPAIR",
        damage_profile="single_panel_conventional",
        rental_required=False,
    )
    return scenario, car


def test_the_licence_check_runs_again_at_every_touch_not_once_at_deployment(api):
    """PRD §3.3: "First, the technician must be licensed: `license_expires_at` must
    be no earlier than the current clock date and `license_state_code` must equal
    the destination facility's `state_code`, since work performed under an
    out-of-state licence is unbillable."

    PRD §3.7: "Tickets may only be opened against a vehicle whose `repair_status` is
    `IN_REPAIR`, at a site whose `status` is `COMMISSIONED` and whose `posture` is
    not `FROZEN`, by a technician whose licence is valid — `license_expires_at` no
    earlier than the current clock date and `license_state_code` matching the site's
    `state_code`, else `ERR_TECHNICIAN_LICENSE_INVALID` — and who actually has a
    deployment with `status` of `ON_SITE` at that vehicle's facility, else
    `ERR_INSPECTOR_NOT_DEPLOYED`."

    PRD §2.6: "Otherwise, if the count of on-site licensed technicians is zero,
    posture is `RESTRICTED`."

    Design: Corner/validations/expired_license_blocks_deployment_now_and_the_work_ticket_later
    """
    scenario, car = _a_lot_whose_only_technician_loses_their_licence(api)
    facility_id = scenario["facility_id"]
    lapsing = tech_id(scenario, "TA")

    # An already-expired licence cannot even be deployed today.
    expired = create_technician(api, "TX")
    refused = api.create_crew_deployment(
        crew_deployment_payload(expired["id"], facility_id, "2026-08-05", "2026-09-15"),
        CREW_COORDINATOR,
    )
    validate_error(refused, "ERR_TECHNICIAN_LICENSE_INVALID", 422)
    _, nothing = validate_paginated(
        api.list_crew_deployments(CREW_COORDINATOR, {"technician_id": expired["id"]})
    )
    assert nothing["total_count"] == 0

    set_clock(api, LAPSE_CLOCK)

    # `TA` deployed legally, but the licence is re-read on every claim.
    too_late = api.create_work_ticket(
        work_ticket_payload(car["vehicle_id"], lapsing),
        make_pdr_technician_headers(lapsing),
    )
    validate_error(too_late, "ERR_TECHNICIAN_LICENSE_INVALID", 422)

    # The lazy check reads the licence; it never rewrites the deployment.
    deployment = read_deployment(api, scenario["deployments"]["TA"]["id"])
    assert deployment["status"] == "ON_SITE"
    assert deployment["end_date"] == "2026-09-15"
    assert read_facility(api, facility_id)["posture"] == "RESTRICTED"

    replacement = create_technician(api, "TB")
    fresh = create_deployment(
        api, replacement["id"], facility_id, "2026-08-20", "2026-09-15"
    )
    assert set_deployment_status(api, fresh["id"], "ON_SITE")["status"] == "ON_SITE"

    claimed = open_work_ticket(api, car["vehicle_id"], replacement["id"])
    assert claimed["status"] == "OPEN"

    assert read_facility(api, facility_id)["posture"] == "OPEN"
    assert read_vehicle(api, car["vehicle_id"])["repair_status"] == "IN_REPAIR"

    rows, meta = validate_paginated(
        api.list_work_tickets(SHOP_ESTIMATOR, {"vehicle_id": car["vehicle_id"]})
    )
    assert meta["total_count"] == 1
    assert ids_of(rows) == [claimed["id"]]


def test_the_cumulative_cap_admits_the_boundary_and_then_refuses_one_cent(api):
    """PRD §3.8: "Two fiscal gates are evaluated at filing, and the **cap is checked
    before auto-approval**. The cumulative cap is 40 percent of the vehicle's
    `approved_repair_cents`, rounded half up to whole cents."

    PRD §3.8: "The vehicle's already-approved supplement total — its
    `approved_supplement_cents`, which counts only supplements whose `status` is
    `AUTO_APPROVED` or `APPROVED` — plus the amount under test must not exceed that
    cap, and the comparison is strict, so an amount that lands the running total
    exactly on the cap passes while one cent more is rejected with
    `ERR_SUPPLEMENT_CUMULATIVE_CAP_EXCEEDED`."

    PRD §3.8: "The auto-approval threshold is the larger of 15,000 cents (150
    dollars) and the pinned sheet's `supplement_auto_approve_pct` multiplied by the
    vehicle's `approved_repair_cents`, rounded half up to whole cents — the floor
    exists so that trivial supplements clear even on cheap repairs."

    Design: Corner/validations/supplement_cumulative_cap_admits_81154_and_rejects_the_next_cent
    """
    scenario = setup_operational_facility(api)
    car = bring_vehicle_to(api, scenario, "AUTHORIZED", rental_required=False)
    vehicle_id = car["vehicle_id"]
    insurer_id = scenario["insurer_id"]
    assert car["vehicle"]["approved_repair_cents"] == 202886
    assert car["vehicle"]["net_billable_cents"] == 213030

    before = read_vehicle_version(api, vehicle_id)

    # 40 percent of 202,886 is 81,154, so one cent more is over the cap.
    over = api.create_supplement(
        supplement_payload(vehicle_id, 81155, before), SHOP_ESTIMATOR
    )
    validate_error(over, "ERR_SUPPLEMENT_CUMULATIVE_CAP_EXCEEDED", 422)
    _, empty = validate_paginated(
        api.list_supplements(SHOP_ESTIMATOR, {"vehicle_id": vehicle_id})
    )
    assert empty["total_count"] == 0

    at_cap = file_supplement(api, vehicle_id, 81154, expected_vehicle_version=before)
    # Far above the 20,289 auto-approve threshold, so the carrier must decide it.
    assert_supplement_state(at_cap, status="UNDER_REVIEW", round_index=1)

    approved = review_supplement(api, at_cap["id"], insurer_id, "APPROVE")
    assert_supplement_state(
        approved, status="APPROVED", approved_amount_cents=81154
    )

    vehicle = read_vehicle(api, vehicle_id)
    assert vehicle["approved_supplement_cents"] == 81154
    assert_money_chain(
        vehicle,
        admin_fee_cents=14202,
        gross_billable_cents=298242,
        discount_cents=5965,
        net_billable_cents=292277,
    )
    assert read_facility(api, scenario["facility_id"])["billable_accrued_cents"] == 292277
    assert read_insurer(api, insurer_id)["outstanding_direct_bill_cents"] == 292277

    after = read_vehicle_version(api, vehicle_id)

    # A single cent would auto-approve on its own, but the cap is checked first.
    one_cent = api.create_supplement(
        supplement_payload(vehicle_id, 1, after, reason_code="ADDITIONAL_PANEL"),
        SHOP_ESTIMATOR,
    )
    validate_error(one_cent, "ERR_SUPPLEMENT_CUMULATIVE_CAP_EXCEEDED", 422)

    unchanged = read_vehicle(api, vehicle_id)
    assert unchanged["version"] == after
    assert unchanged["approved_supplement_cents"] == 81154
    _, only_one = validate_paginated(
        api.list_supplements(SHOP_ESTIMATOR, {"vehicle_id": vehicle_id})
    )
    assert only_one["total_count"] == 1
