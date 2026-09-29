"""Gates on one resource that only a change on a different resource can open."""

from test_helpers import (
    CLOCK_T0,
    DEFAULT_FACILITY,
    DIRECTOR,
    INTAKE_ADVISOR,
    SECOND_VEHICLE,
    SHOP_ESTIMATOR,
    activate_rate_agreement,
    activate_storm_event,
    add_second_insurer,
    assert_facility_state,
    authorize_vehicle,
    billing_payload,
    bring_vehicle_to,
    commission_facility,
    create_deployment,
    create_facility,
    create_insurer,
    create_storm_event,
    create_technician,
    decide_permit,
    draft_rate_agreement,
    file_permit,
    make_insurer_adjuster_headers,
    read_facility,
    read_insurer,
    read_vehicle,
    set_clock,
    set_deployment_status,
    setup_operational_facility,
    start_repair,
    target_storm_event,
    validate_error,
    validate_paginated,
    validate_success,
    vehicle_payload,
)

PERMIT_WINDOW = ("2026-08-01", "2026-09-30")


def _site_awaiting_its_second_permit(api):
    """Everything a lot needs except an approved `ZONING_USE` permit."""
    set_clock(api, CLOCK_T0)
    event = create_storm_event(api)
    target_storm_event(api, event["id"])
    facility = create_facility(api, event["id"])

    licence = file_permit(api, facility["id"], "TEMP_BUSINESS_LICENSE")
    decide_permit(api, licence["id"], "APPROVE", *PERMIT_WINDOW)
    zoning = file_permit(api, facility["id"], "ZONING_USE")

    technician = create_technician(api, "TA")
    deployment = create_deployment(api, technician["id"], facility["id"])
    set_deployment_status(api, deployment["id"], "ON_SITE")

    insurer = create_insurer(api)
    agreement = draft_rate_agreement(api, insurer["id"], event["id"])
    activate_rate_agreement(api, agreement["id"], insurer["id"])

    return {
        "event_id": event["id"],
        "facility_id": facility["id"],
        "insurer_id": insurer["id"],
        "zoning_permit_id": zoning["id"],
    }


def test_a_half_permitted_lot_refuses_commissioning_and_therefore_intake(api):
    """PRD §3.2: "For each of the two required permit types,
    `TEMP_BUSINESS_LICENSE` and `ZONING_USE`, the site must hold a permit that is
    `APPROVED` and whose window contains the current clock date inclusively at
    both ends; a missing, denied, expired or out-of-window permit for either type
    is rejected with `ERR_REQUIRED_PERMIT_MISSING`."

    PRD §2.11: "**Facility must be commissioned** — `ERR_FACILITY_NOT_COMMISSIONED`
    (409), on `POST /hail-ops/vehicles`,
    `POST /hail-ops/vehicles/{id}/start-repair`, `POST /hail-ops/work-tickets`
    and `POST /hail-ops/quality-inspections`."

    PRD §2.11: "**Facility posture gate** — `ERR_FACILITY_POSTURE_BLOCKED` (409),
    on `POST /hail-ops/vehicles`, `POST /hail-ops/vehicles/{id}/start-repair` and
    `POST /hail-ops/work-tickets`."

    Design: Difficulty/cross_entity_state_dependency/vehicle_intake_unlocks_only_after_the_last_permit_commissions_the_facility
    """
    site = _site_awaiting_its_second_permit(api)

    refused = api.commission_facility(site["facility_id"], DIRECTOR)
    validate_error(refused, "ERR_REQUIRED_PERMIT_MISSING", 409)

    # The lot's posture gate would also refuse the car, but the commissioning
    # gate is the one that answers: PRD §2.11 puts `ERR_FACILITY_NOT_COMMISSIONED`
    # at ordinal 12 and `ERR_FACILITY_POSTURE_BLOCKED` at ordinal 20.
    blocked = api.create_vehicle(
        vehicle_payload(site["facility_id"], site["insurer_id"]), INTAKE_ADVISOR
    )
    validate_error(blocked, "ERR_FACILITY_NOT_COMMISSIONED", 409)

    # PRD §2.6 evaluates coverage before the `SETUP` clause: with `ZONING_USE`
    # still `PENDING` coverage does not hold, so posture is `FROZEN`.
    facility = read_facility(api, site["facility_id"])
    assert_facility_state(facility, status="SETUP", posture="FROZEN")
    assert facility["commissioned_at"] is None

    pending, _ = validate_paginated(
        api.list_facility_permits(
            site["facility_id"], DIRECTOR, {"permit_type": "ZONING_USE"}
        )
    )
    assert [p["status"] for p in pending] == ["PENDING"]


def test_approving_the_last_permit_unlocks_commissioning_and_then_intake(api):
    """PRD §3.2: "On success the facility becomes `COMMISSIONED`,
    `commissioned_at` is stamped from the logical clock, posture is recomputed,
    and `version` increments by one."

    PRD §3.5: "The new vehicle begins with `repair_status` of `INTAKE` and
    `billing_status` of `UNBILLED` — two independent dimensions living on one row,
    the first driven by the shop and the second by the carrier."

    Design: Difficulty/cross_entity_state_dependency/vehicle_intake_unlocks_only_after_the_last_permit_commissions_the_facility
    """
    site = _site_awaiting_its_second_permit(api)
    decide_permit(api, site["zoning_permit_id"], "APPROVE", *PERMIT_WINDOW)

    facility = commission_facility(api, site["facility_id"])
    assert facility["status"] == "COMMISSIONED"
    assert facility["commissioned_at"] == CLOCK_T0
    assert facility["posture"] == "OPEN"

    response = api.create_vehicle(
        vehicle_payload(site["facility_id"], site["insurer_id"]), INTAKE_ADVISOR
    )
    vehicle = validate_success(response, 201)
    assert vehicle["repair_status"] == "INTAKE"
    assert vehicle["billing_status"] == "UNBILLED"

    facility = read_facility(api, site["facility_id"])
    assert facility["staging_slots_occupied"] == 1
    assert facility["staging_slots_free"] == DEFAULT_FACILITY["staging_slot_count"] - 1


def _two_carriers_one_of_them_cash_only(api):
    """The default carrier bills directly; the second one refuses to."""
    scenario = setup_operational_facility(api)
    reluctant = add_second_insurer(
        api,
        scenario,
        name="North Basin Indemnity",
        naic_code="30117",
        direct_bill_enabled=False,
    )
    return scenario, reluctant


def test_a_carrier_that_refuses_direct_billing_keeps_its_car_off_the_floor(api):
    """PRD §3.4: "That flag is consequential rather than informational: when it is
    false the carrier refuses direct billing and no vehicle of that carrier may
    ever be authorized."

    PRD §3.9: "It requires the vehicle's `billing_status` to be `UNBILLED`, its
    `repair_status` to be one of `TRIAGED`, `IN_REPAIR`, `QC_PENDING`,
    `QC_FAILED`, `READY` or `TOTAL_LOSS_PENDING` — a car still in intake or
    estimating has no settled number to authorize — and requires the carrier's
    `direct_bill_enabled` flag to be true, else `ERR_DIRECT_BILL_NOT_ENABLED`."

    PRD §3.7: "The vehicle's `repair_status` must be `TRIAGED` or `QC_FAILED`, its
    `triage_disposition` must be `PDR_REPAIR` or `CONVENTIONAL` — a totalled car
    never goes onto the floor — its `billing_status` must be `AUTHORIZED`, the
    site's `posture` must be anything other than `FROZEN`, and the vehicle's
    `rework_count` must be at most 2."

    Design: Difficulty/cross_entity_state_dependency/carrier_direct_bill_flag_decides_authorization_and_repair_start
    """
    scenario, reluctant = _two_carriers_one_of_them_cash_only(api)
    car = bring_vehicle_to(
        api,
        scenario,
        "TRIAGED",
        damage_profile="three_panel",
        insurer_id=reluctant["insurer_id"],
        **SECOND_VEHICLE,
    )

    refused = api.vehicle_billing(
        car["vehicle_id"],
        billing_payload("AUTHORIZE"),
        make_insurer_adjuster_headers(reluctant["insurer_id"]),
    )
    validate_error(refused, "ERR_DIRECT_BILL_NOT_ENABLED", 409)

    # Without an authorization the floor stays closed to that car.
    blocked = api.start_vehicle_repair(car["vehicle_id"], SHOP_ESTIMATOR)
    validate_error(blocked, "ERR_INVALID_VEHICLE_BILLING_STATE", 409)

    assert read_vehicle(api, car["vehicle_id"])["billing_status"] == "UNBILLED"
    assert (
        read_insurer(api, reluctant["insurer_id"])["outstanding_direct_bill_cents"] == 0
    )


def test_the_direct_billing_carrier_authorizes_and_the_repair_starts(api):
    """PRD §3.9: "Authorization adds the vehicle's `net_billable_cents` to the
    facility's `billable_accrued_cents` and to the carrier's
    `outstanding_direct_bill_cents`, and increments the vehicle's `version`."

    PRD §3.5: "The first row after that ranking is pinned into
    `pinned_rate_agreement_id`, replacing whatever a previous estimate had pinned,
    since a re-estimate re-runs the selector."

    Design: Difficulty/cross_entity_state_dependency/carrier_direct_bill_flag_decides_authorization_and_repair_start
    """
    scenario, reluctant = _two_carriers_one_of_them_cash_only(api)
    reluctant_car = bring_vehicle_to(
        api,
        scenario,
        "TRIAGED",
        damage_profile="three_panel",
        insurer_id=reluctant["insurer_id"],
        **SECOND_VEHICLE,
    )
    willing_car = bring_vehicle_to(
        api, scenario, "TRIAGED", damage_profile="three_panel"
    )

    authorized = authorize_vehicle(
        api, willing_car["vehicle_id"], scenario["insurer_id"]
    )
    assert authorized["billing_status"] == "AUTHORIZED"
    assert authorized["net_billable_cents"] == 213030

    in_repair = start_repair(api, willing_car["vehicle_id"])
    assert in_repair["repair_status"] == "IN_REPAIR"

    assert (
        read_insurer(api, scenario["insurer_id"])["outstanding_direct_bill_cents"]
        == 213030
    )
    assert read_facility(api, scenario["facility_id"])["billable_accrued_cents"] == 213030

    # Each car priced against its own carrier's sheet.
    assert (
        willing_car["vehicle"]["pinned_rate_agreement_id"]
        == scenario["rate_agreement_id"]
    )
    assert (
        reluctant_car["vehicle"]["pinned_rate_agreement_id"]
        == reluctant["rate_agreement_id"]
    )
    assert (
        willing_car["vehicle"]["pinned_rate_agreement_id"]
        != reluctant_car["vehicle"]["pinned_rate_agreement_id"]
    )


EXPIRY_CLOCK = "2026-09-01T09:00:00Z"


def _site_whose_licence_lapses_on_the_first_of_september(api):
    """A working lot whose business licence runs out a month before its zoning."""
    set_clock(api, CLOCK_T0)
    event = create_storm_event(api)
    target_storm_event(api, event["id"])
    facility = create_facility(api, event["id"])

    licence = file_permit(api, facility["id"], "TEMP_BUSINESS_LICENSE")
    decide_permit(api, licence["id"], "APPROVE", "2026-08-01", "2026-08-31")
    zoning = file_permit(api, facility["id"], "ZONING_USE")
    decide_permit(api, zoning["id"], "APPROVE", "2026-08-01", "2026-09-30")

    technician = create_technician(api, "TA")
    deployment = create_deployment(api, technician["id"], facility["id"])
    set_deployment_status(api, deployment["id"], "ON_SITE")

    commissioned = commission_facility(api, facility["id"])
    activate_storm_event(api, event["id"])

    insurer = create_insurer(api)
    agreement = draft_rate_agreement(api, insurer["id"], event["id"])
    activate_rate_agreement(api, agreement["id"], insurer["id"])

    scenario = {
        "event_id": event["id"],
        "facility_id": facility["id"],
        "facility": commissioned,
        "insurer_id": insurer["id"],
        "rate_agreement_id": agreement["id"],
        "technicians": {"TA": technician},
        "deployments": {"TA": deployment},
    }
    car = bring_vehicle_to(api, scenario, "AUTHORIZED", damage_profile="three_panel")
    return scenario, car


def test_the_lapsed_licence_suspends_the_lot_on_the_next_request(api):
    """PRD §2.6: "It begins with **lazy permit expiry**: every permit on the
    facility that is currently `APPROVED` and whose `valid_to` is strictly earlier
    than the current clock date is moved to `EXPIRED` before anything else is
    evaluated."

    PRD §2.6: "Otherwise, if permit coverage does not hold, posture is `FROZEN` —
    and if the facility was `COMMISSIONED`, the same recomputation moves it to
    `SUSPENDED`."

    PRD §3.2: "The interesting part of a facility's life is that commissioning is
    not permanent."

    Design: Difficulty/cross_entity_state_dependency/lazy_permit_expiry_suspends_the_facility_then_a_replacement_permit_restores_it
    """
    scenario, car = _site_whose_licence_lapses_on_the_first_of_september(api)
    assert read_facility(api, scenario["facility_id"])["billable_accrued_cents"] == 213030

    set_clock(api, EXPIRY_CLOCK)

    refused = api.start_vehicle_repair(car["vehicle_id"], SHOP_ESTIMATOR)
    validate_error(refused, "ERR_FACILITY_NOT_COMMISSIONED", 409)

    permits, _ = validate_paginated(
        api.list_facility_permits(scenario["facility_id"], DIRECTOR)
    )
    by_type = {p["permit_type"]: p["status"] for p in permits}
    assert by_type["TEMP_BUSINESS_LICENSE"] == "EXPIRED"
    assert by_type["ZONING_USE"] == "APPROVED"

    facility = read_facility(api, scenario["facility_id"])
    assert_facility_state(facility, status="SUSPENDED", posture="FROZEN")
    assert facility["commissioned_at"] == CLOCK_T0
    assert facility["billable_accrued_cents"] == 213030


def test_a_replacement_permit_heals_the_lot_without_rewriting_its_history(api):
    """PRD §2.6: "Suspension is therefore reversible: a facility that lost
    coverage returns to `COMMISSIONED` as soon as a replacement permit restores
    coverage for every required type, and its original `commissioned_at` instant
    is never rewritten by that return."

    PRD §3.2: "Both branches trigger a posture recomputation on the owning
    facility, and the `APPROVE` branch is the one that can heal a site: a
    `SUSPENDED` facility whose coverage becomes complete again returns
    `SUSPENDED` → `COMMISSIONED` inside the very same request."

    Design: Difficulty/cross_entity_state_dependency/lazy_permit_expiry_suspends_the_facility_then_a_replacement_permit_restores_it
    """
    scenario, car = _site_whose_licence_lapses_on_the_first_of_september(api)
    set_clock(api, EXPIRY_CLOCK)
    assert read_facility(api, scenario["facility_id"])["status"] == "SUSPENDED"

    replacement = file_permit(api, scenario["facility_id"], "TEMP_BUSINESS_LICENSE")
    decide_permit(api, replacement["id"], "APPROVE", "2026-09-01", "2026-10-31")

    facility = read_facility(api, scenario["facility_id"])
    assert_facility_state(facility, status="COMMISSIONED", posture="OPEN")
    assert facility["commissioned_at"] == CLOCK_T0
    assert facility["billable_accrued_cents"] == 213030

    resumed = start_repair(api, car["vehicle_id"])
    assert resumed["repair_status"] == "IN_REPAIR"
