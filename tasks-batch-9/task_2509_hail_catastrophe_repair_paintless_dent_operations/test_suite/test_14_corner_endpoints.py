"""Computed reads, per-action role binding and the permit half of commissioning."""

from test_helpers import (
    BILLING_COORDINATOR,
    CLOCK_T0,
    DIRECTOR,
    PERMIT_OFFICER,
    SHOP_ESTIMATOR,
    assert_permit_decision,
    assert_throughput_values,
    billing_action,
    billing_payload,
    bring_vehicle_to,
    commission_facility,
    create_deployment,
    create_facility,
    create_storm_event,
    create_technician,
    decide_permit,
    file_permit,
    ids_of,
    make_insurer_adjuster_headers,
    permit_decision_payload,
    read_facility,
    read_insurer,
    read_throughput_summary,
    read_vehicle,
    release_vehicle,
    set_clock,
    set_deployment_status,
    setup_operational_facility,
    target_storm_event,
    validate_error,
    validate_paginated,
    validate_success,
)

FOUR_CARS = (
    ("1HGCM82633A004352", "D. Reyes", "INTAKE"),
    ("1HGCM82633A004353", "M. Vasquez", "IN_REPAIR"),
    ("1HGCM82633A004354", "T. Okafor", "READY"),
    ("1HGCM82633A004355", "J. Bergeron", "RELEASED"),
)


def _a_yard_holding_one_car_at_each_stage(api):
    """Four identical cars parked at four different points of the pipeline."""
    scenario = setup_operational_facility(api, technicians=("TA", "TI"))
    cars = {}
    for vin, owner, stage in FOUR_CARS:
        cars[stage] = bring_vehicle_to(
            api,
            scenario,
            stage,
            damage_profile="single_panel_conventional",
            vin=vin,
            owner_name=owner,
            acv_cents=2450000,
            rental_required=False,
        )
    return scenario, cars


def test_the_throughput_read_partitions_the_yard_and_reprojects_every_time(api):
    """PRD §3.2: "It answers with the site's `staging_slot_count`,
    `staging_slots_occupied`, `staging_slots_free`, `staging_occupancy_ratio` and
    current `posture`, together with the queue partition: `open_vehicle_count` is
    the number of the site's vehicles in the eight non-terminal repair states,
    `vehicles_in_repair` counts those whose `repair_status` is exactly `IN_REPAIR`,
    `vehicles_ready` counts those in `READY`, and `released_count` counts those that
    have left in either terminal state, `RELEASED` or `TOWED_OUT`."

    PRD §3.2: "The projection assumes each on-site technician clears one and a half
    vehicles per day: daily capacity is one and a half multiplied by the on-site
    technician count, except that the count is treated as at least one so that an
    unstaffed site still yields a finite projection, and `projected_days_to_clear`
    is `open_vehicle_count` divided by that daily capacity, rounded **up** to a
    whole number of days."

    PRD §2.7: "The only non-integer derived value in the system is
    `staging_occupancy_ratio`, which is rounded half up to four decimal places."

    Design: Corner/endpoints/throughput_summary_partitions_the_yard_and_reprojects_on_every_read
    """
    scenario, cars = _a_yard_holding_one_car_at_each_stage(api)

    before = read_throughput_summary(api, scenario["facility_id"])
    assert_throughput_values(
        before,
        staging_slot_count=6,
        staging_slots_occupied=3,
        staging_slots_free=3,
        staging_occupancy_ratio=0.5,
        posture="OPEN",
        open_vehicle_count=3,
        vehicles_in_repair=1,
        vehicles_ready=1,
        released_count=1,
        on_site_technician_count=2,
        billable_accrued_cents=242550,
        absorbed_rental_cents=0,
    )
    # Two on-site technicians clear three vehicles a day, so the queue is one day.
    assert before["projected_days_to_clear"] == 1

    release_vehicle(api, cars["READY"]["vehicle_id"])

    # The same operation is shared with the estimator, and it reprojects on read.
    after = validate_success(
        api.get_throughput_summary(scenario["facility_id"], SHOP_ESTIMATOR)
    )
    assert_throughput_values(
        after,
        staging_slots_occupied=2,
        staging_slots_free=4,
        staging_occupancy_ratio=0.3333,
        posture="OPEN",
        open_vehicle_count=2,
        vehicles_ready=0,
        released_count=2,
        projected_days_to_clear=1,
    )
    # Freeing a slot never reverses a bill that was already accrued.
    assert after["billable_accrued_cents"] == 242550
    assert read_vehicle(api, cars["INTAKE"]["vehicle_id"])["billing_status"] == "UNBILLED"


def test_each_billing_action_answers_only_to_its_own_side_of_the_table(api):
    """PRD §3.9: "The action also decides who may ask: `AUTHORIZE`,
    `VOID_AUTHORIZATION` and `SETTLE` are the carrier's to make and require an
    `InsurerAdjuster`, while `SUBMIT_BILL` is the shop's and requires a
    `BillingCoordinator`. Asking from the wrong side of the table — a coordinator
    authorizing, or an adjuster submitting a bill — is rejected with
    `ERR_BILLING_ACTION_ROLE_MISMATCH`, and an adjuster acting on a vehicle whose
    `insurer_id` is not their own is rejected with `ERR_IDENTITY_MISMATCH`."

    PRD §3.9: "`SETTLE` moves `BILLED` → `PAID`, requiring only that the vehicle be
    `BILLED`; it subtracts `net_billable_cents` from the carrier's
    `outstanding_direct_bill_cents` and adds the same amount to its `settled_cents`,
    while the facility's `billable_accrued_cents` is left untouched because `PAID`
    is still inside the set of statuses that figure contributes from."

    PRD §2.11: "**Billing action to role map** — `ERR_BILLING_ACTION_ROLE_MISMATCH`
    (403), on `POST /hail-ops/vehicles/{id}/billing`."

    Design: Corner/endpoints/billing_actions_are_bound_to_their_own_role_in_both_directions
    """
    scenario = setup_operational_facility(api, technicians=("TA", "TI"))
    car = bring_vehicle_to(
        api,
        scenario,
        "RELEASED",
        damage_profile="single_panel_conventional",
        rental_required=False,
    )
    vehicle_id = car["vehicle_id"]
    insurer_id = scenario["insurer_id"]
    adjuster = make_insurer_adjuster_headers(insurer_id)

    assert car["vehicle"]["net_billable_cents"] == 80850
    assert read_insurer(api, insurer_id)["outstanding_direct_bill_cents"] == 80850
    assert read_insurer(api, insurer_id)["settled_cents"] == 0
    assert read_facility(api, scenario["facility_id"])["billable_accrued_cents"] == 80850
    released_version = car["vehicle"]["version"]

    # The adjuster owns this vehicle, so identity passes and the action map fires.
    wrong_way = api.vehicle_billing(vehicle_id, billing_payload("SUBMIT_BILL"), adjuster)
    validate_error(wrong_way, "ERR_BILLING_ACTION_ROLE_MISMATCH", 403)
    untouched = read_vehicle(api, vehicle_id)
    assert untouched["billing_status"] == "AUTHORIZED"
    assert untouched["version"] == released_version

    billed = billing_action(api, vehicle_id, "SUBMIT_BILL", insurer_id)
    assert billed["billing_status"] == "BILLED"

    # `BillingCoordinator` is declared on the endpoint, yet cannot settle.
    other_way = api.vehicle_billing(
        vehicle_id, billing_payload("SETTLE"), BILLING_COORDINATOR
    )
    validate_error(other_way, "ERR_BILLING_ACTION_ROLE_MISMATCH", 403)

    paid = billing_action(api, vehicle_id, "SETTLE", insurer_id)
    assert paid["billing_status"] == "PAID"

    insurer = read_insurer(api, insurer_id)
    assert insurer["outstanding_direct_bill_cents"] == 0
    assert insurer["settled_cents"] == 80850
    assert read_facility(api, scenario["facility_id"])["billable_accrued_cents"] == 80850

    # Voiding is the adjuster's own action, so the refusal is about state. The car
    # is both `PAID` and `RELEASED`, and PRD §2.11 ranks the repair dimension
    # (ordinal 15) ahead of the billing dimension (ordinal 16).
    too_late = api.vehicle_billing(
        vehicle_id, billing_payload("VOID_AUTHORIZATION"), adjuster
    )
    validate_error(too_late, "ERR_INVALID_VEHICLE_REPAIR_STATE", 409)
    assert read_vehicle(api, vehicle_id)["billing_status"] == "PAID"


PERMIT_WINDOW = ("2026-08-01", "2026-09-30")


def _a_staffed_lot_awaiting_its_zoning_ruling(api):
    """A `SETUP` lot with a licensed crew on site and zoning still `PENDING`."""
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

    return facility["id"], zoning


def test_a_denied_permit_is_terminal_and_only_a_replacement_commissions_the_lot(api):
    """PRD §3.2: "A `DENY` decision needs no dates, moves `PENDING` → `DENIED`,
    which is terminal, and likewise stamps `decided_at`."

    PRD §3.2: "For each of the two required permit types, `TEMP_BUSINESS_LICENSE`
    and `ZONING_USE`, the site must hold a permit that is `APPROVED` and whose
    window contains the current clock date inclusively at both ends; a missing,
    denied, expired or out-of-window permit for either type is rejected with
    `ERR_REQUIRED_PERMIT_MISSING`."

    PRD §2.6: "Otherwise, if permit coverage does not hold, posture is `FROZEN` —
    and if the facility was `COMMISSIONED`, the same recomputation moves it to
    `SUSPENDED`."

    Design: Corner/endpoints/denied_required_permit_blocks_commissioning_until_a_replacement_is_approved
    """
    facility_id, zoning = _a_staffed_lot_awaiting_its_zoning_ruling(api)

    denied = validate_success(
        api.decide_permit(zoning["id"], permit_decision_payload("DENY"), PERMIT_OFFICER)
    )
    assert_permit_decision(
        denied, status="DENIED", valid_from=None, valid_to=None, decided_at=CLOCK_T0
    )

    refused = api.commission_facility(facility_id, DIRECTOR)
    validate_error(refused, "ERR_REQUIRED_PERMIT_MISSING", 409)
    blocked = read_facility(api, facility_id)
    assert blocked["status"] == "SETUP"
    assert blocked["posture"] == "FROZEN"
    assert blocked["commissioned_at"] is None

    # A denied permit cannot be repaired in place; only a new one covers the type.
    replacement = file_permit(api, facility_id, "ZONING_USE")
    assert replacement["status"] == "PENDING"
    approved = decide_permit(api, replacement["id"], "APPROVE", *PERMIT_WINDOW)
    assert approved["status"] == "APPROVED"

    commissioned = commission_facility(api, facility_id)
    assert commissioned["status"] == "COMMISSIONED"
    assert commissioned["posture"] == "OPEN"
    assert commissioned["commissioned_at"] == CLOCK_T0

    zoning_rows, zoning_meta = validate_paginated(
        api.list_facility_permits(facility_id, DIRECTOR, {"permit_type": "ZONING_USE"})
    )
    assert zoning_meta["total_count"] == 2
    assert sorted(row["status"] for row in zoning_rows) == ["APPROVED", "DENIED"]

    denied_rows, denied_meta = validate_paginated(
        api.list_facility_permits(facility_id, DIRECTOR, {"status": "DENIED"})
    )
    assert denied_meta["total_count"] == 1
    assert ids_of(denied_rows) == [zoning["id"]]
