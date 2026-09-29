"""Requests that break two rules at once, where only the lower ordinal may speak."""

from test_helpers import (
    CREW_COORDINATOR,
    SHOP_ESTIMATOR,
    assert_technician_pay,
    bring_vehicle_to,
    create_deployment,
    create_technician,
    crew_deployment_payload,
    make_quality_inspector_headers,
    quality_inspection_payload,
    read_deployment,
    read_technician,
    read_vehicle,
    read_vehicle_version,
    read_work_ticket,
    set_deployment_status,
    setup_housed_crew,
    setup_operational_facility,
    supplement_payload,
    tech_id,
    validate_error,
    validate_paginated,
)


def _estimated_vehicle(api):
    """A car that has been priced but never triaged, so nothing is approved yet."""
    scenario = setup_operational_facility(api)
    car = bring_vehicle_to(api, scenario, "ESTIMATED", damage_profile="three_panel")
    return scenario, car


def test_an_untriaged_vehicle_reports_its_repair_state_not_the_supplement_cap(api):
    """PRD §3.8: "Filing requires the vehicle's `repair_status` to be one of
    `TRIAGED`, `IN_REPAIR`, `QC_PENDING`, `QC_FAILED` or `READY` — a car still
    being estimated or already gone has no supplement surface, and other states
    are rejected with `ERR_INVALID_VEHICLE_REPAIR_STATE`."

    PRD §2.11: "When a single request violates several rules at once, the
    response reports the violation with the lowest ordinal in the list below. The
    ordering is contractual: a mid-flight lifecycle problem must not be masked by
    a later fiscal check, and a fiscal check must not be reported for a request
    that was never authorized in the first place."

    Design: Difficulty/priority_pair_validation_conflict/supplement_repair_state_rule_beats_cumulative_cap_on_untriaged_vehicle
    """
    scenario, car = _estimated_vehicle(api)
    vehicle = read_vehicle(api, car["vehicle_id"])
    assert vehicle["repair_status"] == "ESTIMATED"
    # With nothing approved, the cumulative cap is zero, so the requested amount
    # also breaks the fiscal gate.
    assert vehicle["approved_repair_cents"] == 0

    response = api.create_supplement(
        supplement_payload(car["vehicle_id"], 90000, vehicle["version"]),
        SHOP_ESTIMATOR,
    )
    validate_error(response, "ERR_INVALID_VEHICLE_REPAIR_STATE", 409)


def test_the_rejected_filing_leaves_no_supplement_behind(api):
    """PRD §2.11: "**Vehicle repair dimension** — `ERR_INVALID_VEHICLE_REPAIR_STATE`
    (409), on `POST /hail-ops/vehicles/{id}/estimate`, `/triage`,
    `/start-repair`, `/release` and `/billing`, and on
    `POST /hail-ops/damage-lines`, `POST /hail-ops/work-tickets`,
    `POST /hail-ops/quality-inspections` and `POST /hail-ops/supplements`."

    PRD §2.11: "**Supplement cumulative cap** —
    `ERR_SUPPLEMENT_CUMULATIVE_CAP_EXCEEDED` (422), on
    `POST /hail-ops/supplements` and `POST /hail-ops/supplements/{id}/revise`."

    Design: Difficulty/priority_pair_validation_conflict/supplement_repair_state_rule_beats_cumulative_cap_on_untriaged_vehicle
    """
    scenario, car = _estimated_vehicle(api)
    before = read_vehicle_version(api, car["vehicle_id"])

    response = api.create_supplement(
        supplement_payload(car["vehicle_id"], 90000, before), SHOP_ESTIMATOR
    )
    assert response.status_code == 409

    rows, meta = validate_paginated(
        api.list_supplements(SHOP_ESTIMATOR, {"vehicle_id": car["vehicle_id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []

    vehicle = read_vehicle(api, car["vehicle_id"])
    assert vehicle["version"] == before
    assert vehicle["approved_supplement_cents"] == 0
    assert vehicle["repair_status"] == "ESTIMATED"


def _own_inspector_whose_deployment_has_ended(api):
    """The only technician on the car is also the only candidate inspector."""
    scenario = setup_operational_facility(api, technicians=("TA", "TI"))
    car = bring_vehicle_to(api, scenario, "QC_PENDING", damage_profile="three_panel")
    set_deployment_status(api, scenario["deployments"]["TA"]["id"], "ENDED")
    return scenario, car


def test_holding_a_ticket_outranks_having_left_the_site(api):
    """PRD §3.7: "The vehicle must be `QC_PENDING`; the inspecting technician
    must hold **no** work ticket of any status whatsoever on that vehicle, and
    holding one is rejected with `ERR_SEGREGATION_OF_DUTIES`; the inspector must
    be licensed for the site and must have an `ON_SITE` deployment at the
    vehicle's facility, else `ERR_TECHNICIAN_LICENSE_INVALID` or
    `ERR_INSPECTOR_NOT_DEPLOYED`; and the site must be `COMMISSIONED`."

    PRD §2.11: "**Segregation of duties** — `ERR_SEGREGATION_OF_DUTIES` (403), on
    `POST /hail-ops/quality-inspections`."

    PRD §2.11: "**Inspector deployment** — `ERR_INSPECTOR_NOT_DEPLOYED` (409),
    on `POST /hail-ops/quality-inspections`."

    Design: Difficulty/priority_pair_validation_conflict/qc_segregation_of_duties_beats_inspector_not_deployed
    """
    scenario, car = _own_inspector_whose_deployment_has_ended(api)
    worker_id = tech_id(scenario, "TA")

    response = api.create_quality_inspection(
        quality_inspection_payload(car["vehicle_id"], worker_id, "PASS"),
        make_quality_inspector_headers(worker_id),
    )
    validate_error(response, "ERR_SEGREGATION_OF_DUTIES", 403)
    assert read_deployment(api, scenario["deployments"]["TA"]["id"])["status"] == "ENDED"


def test_the_refused_inspection_leaves_the_car_and_the_pay_untouched(api):
    """PRD §3.7: "A `PASS` moves the vehicle `QC_PENDING` → `READY` and triggers
    the crew-pay cascade, which runs two hops."

    PRD §3.7: "A new ticket lands in `OPEN` with `payable_flat_cents`,
    `payable_pooled_cents` and `payable_cents` all 0 and `pay_model_applied`
    null."

    Design: Difficulty/priority_pair_validation_conflict/qc_segregation_of_duties_beats_inspector_not_deployed
    """
    scenario, car = _own_inspector_whose_deployment_has_ended(api)
    worker_id = tech_id(scenario, "TA")

    response = api.create_quality_inspection(
        quality_inspection_payload(car["vehicle_id"], worker_id, "PASS"),
        make_quality_inspector_headers(worker_id),
    )
    assert response.status_code == 403

    assert read_vehicle(api, car["vehicle_id"])["repair_status"] == "QC_PENDING"

    ticket = read_work_ticket(api, car["work_tickets"][0]["id"])
    assert ticket["status"] == "SUBMITTED"
    assert ticket["payable_cents"] == 0
    assert ticket["pay_model_applied"] is None

    _, meta = validate_paginated(
        api.list_quality_inspections(
            SHOP_ESTIMATOR, {"vehicle_id": car["vehicle_id"]}
        )
    )
    assert meta["total_count"] == 0
    assert_technician_pay(
        read_technician(api, worker_id),
        accrued_pay_cents=0,
        approved_ticket_count=0,
    )


def _single_bed_site_with_a_recently_returned_technician(api):
    """One bed already taken all season, plus a technician just off a stint."""
    scenario = setup_housed_crew(api, bed_count=1)
    unit_id = scenario["housing_unit_id"]

    resident = create_technician(api, "TB")
    create_deployment(
        api,
        resident["id"],
        scenario["facility_id"],
        "2026-08-05",
        "2026-09-15",
        unit_id,
    )

    traveller = create_technician(api, "TA")
    create_deployment(
        api, traveller["id"], scenario["facility_id"], "2026-08-05", "2026-08-20"
    )
    return scenario, traveller["id"], unit_id


def test_the_rest_buffer_is_reported_before_the_bed_shortage(api):
    """PRD §3.3: "A rest buffer of one calendar day is added to both ends of every
    interval before the comparison, so the requested deployment collides with an
    existing `CONFIRMED` or `ON_SITE` deployment of the same technician whenever
    the requested `start_date` is no later than one day after that existing
    deployment's effective end, **and** one day after the requested `end_date` is
    no earlier than that existing deployment's `start_date`."

    PRD §2.11: "**Deployment exclusivity** — `ERR_TECHNICIAN_DEPLOYMENT_OVERLAP`
    (409), on `POST /hail-ops/crew-deployments`."

    Design: Difficulty/priority_pair_validation_conflict/technician_overlap_beats_housing_bed_capacity
    """
    scenario, traveller_id, unit_id = _single_bed_site_with_a_recently_returned_technician(api)

    # 21 August is the buffer day, and the only bed is already taken, so both
    # rules are broken at once.
    response = api.create_crew_deployment(
        crew_deployment_payload(
            traveller_id,
            scenario["facility_id"],
            "2026-08-21",
            "2026-09-05",
            unit_id,
        ),
        CREW_COORDINATOR,
    )
    validate_error(response, "ERR_TECHNICIAN_DEPLOYMENT_OVERLAP", 409)


def test_clearing_the_buffer_finally_surfaces_the_housing_shortage(api):
    """PRD §3.3: "Housing capacity is checked last, and it is an aggregate rather
    than a pairwise rule."

    PRD §3.3: "If any single date would overflow, the whole request is rejected
    with `ERR_HOUSING_CAPACITY_EXCEEDED`."

    PRD §2.11: "**Housing capacity** — `ERR_HOUSING_CAPACITY_EXCEEDED` (409), on
    `POST /hail-ops/crew-deployments`."

    Design: Difficulty/priority_pair_validation_conflict/technician_overlap_beats_housing_bed_capacity
    """
    scenario, traveller_id, unit_id = _single_bed_site_with_a_recently_returned_technician(api)

    response = api.create_crew_deployment(
        crew_deployment_payload(
            traveller_id,
            scenario["facility_id"],
            "2026-08-22",
            "2026-09-05",
            unit_id,
        ),
        CREW_COORDINATOR,
    )
    validate_error(response, "ERR_HOUSING_CAPACITY_EXCEEDED", 409)

    _, meta = validate_paginated(
        api.list_crew_deployments(CREW_COORDINATOR, {"technician_id": traveller_id})
    )
    assert meta["total_count"] == 1
