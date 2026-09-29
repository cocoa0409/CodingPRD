"""Actions that undo an earlier action exactly, leaving no residue in the ledgers."""

from test_helpers import (
    CLOCK_T0,
    INTAKE_ADVISOR,
    SECOND_VEHICLE,
    SHOP_ESTIMATOR,
    assert_facility_state,
    assert_money_chain,
    assert_no_warranty_minted,
    assert_rental_exposure,
    assert_staging_counters,
    authorize_vehicle,
    billing_action,
    bring_vehicle_to,
    read_facility,
    read_insurer,
    read_throughput_summary,
    read_vehicle,
    release_vehicle,
    setup_operational_facility,
    validate_error,
    validate_success,
    vehicle_payload,
)

NET_BILLABLE_CENTS = 213030


def _authorized_then_voided(api):
    scenario = setup_operational_facility(api)
    car = bring_vehicle_to(api, scenario, "AUTHORIZED", damage_profile="three_panel")
    assert read_facility(api, scenario["facility_id"])["billable_accrued_cents"] == (
        NET_BILLABLE_CENTS
    )
    voided = billing_action(
        api, car["vehicle_id"], "VOID_AUTHORIZATION", scenario["insurer_id"]
    )
    return scenario, car, voided


def test_voiding_an_authorization_returns_both_ledgers_to_zero(api):
    """PRD §3.9: "`VOID_AUTHORIZATION` is its exact compensating action, moving
    `AUTHORIZED` → `UNBILLED`: it requires the vehicle's `billing_status` to be
    `AUTHORIZED` and its `repair_status` to be anything other than `RELEASED` or
    `TOWED_OUT`, and it subtracts the same `net_billable_cents` from the
    facility's `billable_accrued_cents` and the carrier's
    `outstanding_direct_bill_cents` before incrementing `version`."

    PRD §3.7: "A missing authorization is rejected with
    `ERR_INVALID_VEHICLE_BILLING_STATE`, a frozen site with
    `ERR_FACILITY_POSTURE_BLOCKED`, an uncommissioned site with
    `ERR_FACILITY_NOT_COMMISSIONED`, and a vehicle that has already failed
    inspection more than twice with `ERR_REWORK_LIMIT_EXCEEDED`."

    Design: Difficulty/compensating_invariant/void_authorization_restores_facility_and_insurer_ledgers_to_zero
    """
    scenario, car, voided = _authorized_then_voided(api)

    assert voided["billing_status"] == "UNBILLED"
    # The void touches the ledgers, never the vehicle's own arithmetic.
    assert voided["repair_status"] == "TRIAGED"
    assert_money_chain(
        voided,
        admin_fee_cents=10144,
        gross_billable_cents=NET_BILLABLE_CENTS,
        discount_cents=0,
        net_billable_cents=NET_BILLABLE_CENTS,
    )

    assert read_facility(api, scenario["facility_id"])["billable_accrued_cents"] == 0
    assert read_insurer(api, scenario["insurer_id"])["outstanding_direct_bill_cents"] == 0

    # An unauthorized car cannot go onto the floor.
    response = api.start_vehicle_repair(car["vehicle_id"], SHOP_ESTIMATOR)
    validate_error(response, "ERR_INVALID_VEHICLE_BILLING_STATE", 409)


def test_re_authorizing_after_a_void_adds_the_amount_once(api):
    """PRD §3.9: "Authorization adds the vehicle's `net_billable_cents` to the
    facility's `billable_accrued_cents` and to the carrier's
    `outstanding_direct_bill_cents`, and increments the vehicle's `version`."

    PRD §2.8: "On a carrier, `outstanding_direct_bill_cents` is the sum of
    `net_billable_cents` over that carrier's vehicles whose `billing_status` is
    `AUTHORIZED` or `BILLED`, `settled_cents` is the same sum restricted to
    `billing_status` equal to `PAID`, and `active_rate_agreement_count` is the
    number of that carrier's rate agreements whose `status` is `ACTIVE`."

    Design: Difficulty/compensating_invariant/void_authorization_restores_facility_and_insurer_ledgers_to_zero
    """
    scenario, car, _ = _authorized_then_voided(api)

    again = authorize_vehicle(api, car["vehicle_id"], scenario["insurer_id"])
    assert again["billing_status"] == "AUTHORIZED"

    facility = read_facility(api, scenario["facility_id"])
    insurer = read_insurer(api, scenario["insurer_id"])
    # The aggregates are sums over the current rows, not running tallies, so the
    # second authorization cannot double the exposure.
    assert facility["billable_accrued_cents"] == NET_BILLABLE_CENTS
    assert insurer["outstanding_direct_bill_cents"] == NET_BILLABLE_CENTS
    assert facility["billable_accrued_cents"] != 2 * NET_BILLABLE_CENTS
    assert insurer["settled_cents"] == 0


def _one_slot_lot_holding_a_total_loss(api):
    """A single-slot lot whose only car has been written off and authorized."""
    scenario = setup_operational_facility(api, staging_slot_count=1)
    car = bring_vehicle_to(
        api,
        scenario,
        "AUTHORIZED",
        damage_profile="single_panel_pdr",
        acv_cents=128272,
    )
    assert car["vehicle"]["repair_status"] == "TOTAL_LOSS_PENDING"
    return scenario, car


def test_towing_out_a_total_loss_frees_the_slot_and_mints_no_warranty(api):
    """PRD §3.5: "Intake requires the site's `status` to be `COMMISSIONED` — a
    `SETUP`, `SUSPENDED` or `DEMOBILIZED` site is rejected with
    `ERR_FACILITY_NOT_COMMISSIONED` — and requires the site's `posture` to be
    exactly `OPEN`, since a `RESTRICTED` or `FROZEN` lot must not accept new
    metal; a posture violation is rejected with `ERR_FACILITY_POSTURE_BLOCKED`."

    PRD §3.9: "A towed-out total loss mints nothing — its `warranty_number` stays
    null and the facility's `warranty_counter` is deliberately **not**
    incremented, so warranty numbers stay dense across the site's real repairs."

    PRD §3.9: "Release finally frees the staging slot: the facility's
    `staging_slots_occupied`, `staging_slots_free`, `staging_occupancy_ratio` and
    `absorbed_rental_cents` are all recomputed and its posture is recomputed,
    which is how releasing one car can lift a full lot from `RESTRICTED` back to
    `OPEN` and let the next intake through."

    Design: Difficulty/compensating_invariant/tow_out_release_frees_exactly_one_staging_slot_and_restores_posture
    """
    scenario, car = _one_slot_lot_holding_a_total_loss(api)

    blocked = api.create_vehicle(
        vehicle_payload(scenario["facility_id"], scenario["insurer_id"], **SECOND_VEHICLE),
        INTAKE_ADVISOR,
    )
    validate_error(blocked, "ERR_FACILITY_POSTURE_BLOCKED", 409)

    towed = release_vehicle(api, car["vehicle_id"])
    assert towed["repair_status"] == "TOWED_OUT"
    assert towed["released_at"] == CLOCK_T0
    assert towed["rental_closed_at"] == CLOCK_T0
    assert_rental_exposure(towed, rental_days_billed=1, shop_absorbed_rental_cents=0)
    assert_no_warranty_minted(towed)

    facility = read_facility(api, scenario["facility_id"])
    assert facility["warranty_counter"] == 0
    assert_staging_counters(facility)
    assert facility["staging_slots_occupied"] == 0
    assert facility["staging_slots_free"] == 1
    assert facility["staging_occupancy_ratio"] == 0.0
    assert_facility_state(facility, status="COMMISSIONED", posture="OPEN")
    assert facility["absorbed_rental_cents"] == 0
    assert facility["billable_accrued_cents"] == 0


def test_the_freed_slot_admits_the_next_car_and_the_yard_read_repartitions(api):
    """PRD §3.2: "It answers with the site's `staging_slot_count`,
    `staging_slots_occupied`, `staging_slots_free`, `staging_occupancy_ratio` and
    current `posture`, together with the queue partition: `open_vehicle_count` is
    the number of the site's vehicles in the eight non-terminal repair states,
    `vehicles_in_repair` counts those whose `repair_status` is exactly
    `IN_REPAIR`, `vehicles_ready` counts those in `READY`, and `released_count`
    counts those that have left in either terminal state, `RELEASED` or
    `TOWED_OUT`."

    PRD §3.5: "Intake also refreshes the facility's staging counters, occupancy
    ratio and posture — a car that fills the last slot drives the lot straight to
    `RESTRICTED` and blocks the next intake."

    Design: Difficulty/compensating_invariant/tow_out_release_frees_exactly_one_staging_slot_and_restores_posture
    """
    scenario, car = _one_slot_lot_holding_a_total_loss(api)
    release_vehicle(api, car["vehicle_id"])

    response = api.create_vehicle(
        vehicle_payload(scenario["facility_id"], scenario["insurer_id"], **SECOND_VEHICLE),
        INTAKE_ADVISOR,
    )
    replacement = validate_success(response, 201)
    assert replacement["repair_status"] == "INTAKE"
    assert replacement["billing_status"] == "UNBILLED"

    facility = read_facility(api, scenario["facility_id"])
    assert facility["staging_slots_occupied"] == 1
    assert facility["staging_slots_free"] == 0
    assert_facility_state(facility, status="COMMISSIONED", posture="RESTRICTED")

    summary = read_throughput_summary(api, scenario["facility_id"])
    assert summary["open_vehicle_count"] == 1
    assert summary["released_count"] == 1
    assert summary["vehicles_in_repair"] == 0
    assert summary["vehicles_ready"] == 0
    assert read_vehicle(api, car["vehicle_id"])["repair_status"] == "TOWED_OUT"
