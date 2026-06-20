"""Confirm-time preconditions: cross-entity gates and precedence ordering.

Translates difficulty (A) cross_entity_state_dependency and
priority_pair_validation_conflict instances, plus corner (B) confirm-gate
validation instances.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    create_assignment_payload,
    setup_held_reservation, setup_facility_owner_pet,
    create_run, create_package, advance_clock, create_assignment,
    create_reservation_payload,
    TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]


# --------------------------------------------------------------- cross-entity gates
def test_confirm_blocked_when_pet_vaccination_missing(api):
    """PRD §3.6: "The pet's `vaccination_status` must be `VALID` at the facility's
    `current_date`, or the confirm is rejected with `ERR_VACCINATION_REQUIRED`."

    A reservation whose pet has no vaccination records (MISSING) cannot confirm.

    Design: Difficulty/cross_entity_state_dependency/confirm_depends_on_pet_vaccination
    """
    ctx = setup_held_reservation(
        service_type="OVERNIGHT", start_date="2026-05-01", end_date="2026-05-03",
        deposit_policy="NONE", vaccinate=False, review="CLEAR")
    assert ctx["pet"]["vaccination_status"] == "MISSING"
    res = api.confirm_reservation(ctx["reservation"]["id"], MGR)
    validate_error(res, "ERR_VACCINATION_REQUIRED")


def test_confirm_blocked_when_pet_vaccination_expired(api):
    """PRD §3.6: "The pet's `vaccination_status` must be `VALID` at the facility's
    `current_date`, or the confirm is rejected with `ERR_VACCINATION_REQUIRED`."
    PRD §3.3: "The reverse flip happens during a clock advance: when the new `current_date`
    moves past the `expires_on` of at least one required vaccine, the pet drops from
    `VALID` to `EXPIRED`."

    A reservation whose pet's vaccines lapsed to EXPIRED (a distinct non-VALID state from
    MISSING) also cannot confirm.

    Design: Difficulty/cross_entity_state_dependency/confirm_depends_on_pet_vaccination
    """
    from test_helpers import vaccinate_cat_valid
    facility, owner, pet = setup_facility_owner_pet(
        deposit_policy="NONE", vaccinate=False, review="CLEAR")
    vaccinate_cat_valid(pet["id"], administered_on="2025-01-01", expires_on="2026-01-15")
    run = create_run(facility["id"], label="Suite-Vx", kind="OVERNIGHT_SUITE", size_class="LARGE")
    res = get_success_data(api_client.create_reservation(
        facility["id"],
        create_reservation_payload(pet["id"], "OVERNIGHT", "2026-05-01", "2026-05-03"),
        MGR,
    ))
    create_assignment(res["id"], run["id"], res["version"])
    advance_clock(facility["id"], "2026-02-01")  # vaccines now EXPIRED
    pet_now = get_success_data(api_client.get_pet(pet["id"], MGR))
    assert pet_now["vaccination_status"] == "EXPIRED"
    out = api.confirm_reservation(res["id"], MGR)
    validate_error(out, "ERR_VACCINATION_REQUIRED")


def test_confirm_blocked_when_package_expired(api):
    """PRD §3.6: "if a `package_id` was supplied, the referenced package's `status` must
    be `ACTIVE`, its `credits_remaining` must be at least 1, and the service must be
    `DAYCARE`, or the confirm is rejected with `ERR_PACKAGE_NOT_REDEEMABLE`."
    PRD §3.7: "During a clock advance, an `ACTIVE` package whose 30-day cycle has lapsed
    — that is, when the facility's `current_date` is more than 30 days after the package's
    `cycle_start_date` — transitions to `EXPIRED`, its `credits_remaining` frozen and no
    further redemptions permitted until it is renewed; the package's `version` increments
    by one."

    A package-funded DAYCARE confirm fails once its package has lapsed to EXPIRED.

    Design: Difficulty/cross_entity_state_dependency/confirm_depends_on_package_status
    """
    facility, owner, pet = setup_facility_owner_pet(deposit_policy="NONE")
    package = create_package(
        owner["id"], tier="DAYCARE_10", cycle_start_date="2026-01-01", auto_renew=False)
    run = create_run(
        facility["id"], label="Pen-N1", kind="DAYCARE_PEN", size_class="LARGE", daycare_capacity=50)
    res = get_success_data(api_client.create_reservation(
        facility["id"],
        create_reservation_payload(
            pet["id"], "DAYCARE", "2026-03-30", "2026-03-30", package_id=package["id"]),
        MGR,
    ))
    create_assignment(res["id"], run["id"], res["version"])
    advance_clock(facility["id"], "2026-02-15")  # lapse the package (cycle started 2026-01-01)
    pkg = validate_success(api.get_package(package["id"], MGR), 200)
    assert pkg["status"] == "EXPIRED"
    out = api.confirm_reservation(res["id"], MGR)
    validate_error(out, "ERR_PACKAGE_NOT_REDEEMABLE")


def test_confirm_succeeds_with_active_package(api):
    """PRD §3.6: "if a `package_id` was supplied, the referenced package's `status` must
    be `ACTIVE`, its `credits_remaining` must be at least 1, and the service must be
    `DAYCARE`, or the confirm is rejected with `ERR_PACKAGE_NOT_REDEEMABLE`."
    PRD §3.6: "If a `package_id` was supplied, the system creates a `PackageRedemption`
    recording `credits_used` of 1 with `reversed` false, sets the reservation's
    `redeemed_credit` to true, and recomputes the package's `credits_remaining`."

    The same confirm passes (and redeems a credit) when the package status IS ACTIVE,
    proving the gate keys specifically on Package.status.

    Design: Difficulty/cross_entity_state_dependency/confirm_depends_on_package_status
    """
    from test_helpers import setup_package_funded_confirmed
    ctx = setup_package_funded_confirmed(tier="DAYCARE_10", start_date="2026-01-10")
    assert ctx["reservation"]["status"] == "CONFIRMED"
    assert ctx["reservation"]["redeemed_credit"] is True
    assert ctx["package"]["status"] == "ACTIVE"
    assert ctx["package"]["credits_remaining"] == 9, "ACTIVE package permitted confirm, credit consumed"


# --------------------------------------------------------------- precedence pairs
def test_vaccination_required_beats_deposit_unpaid(api):
    """PRD §3.6: "The confirm enforces a sequence of preconditions, evaluated in this
    order so that a more fundamental failure surfaces before a downstream one."
    PRD §3.6: "The pet's `vaccination_status` must be `VALID` at the facility's
    `current_date`, or the confirm is rejected with `ERR_VACCINATION_REQUIRED`."
    PRD §3.6: "Unless the facility's `deposit_policy` is `NONE`, the `deposit_paid_cents`
    must be at least the latched `deposit_cents`, or the confirm is rejected with
    `ERR_DEPOSIT_UNPAID`."

    A confirm violating BOTH (EXPIRED vaccine AND unpaid STANDARD deposit) returns the
    earlier-ordered ERR_VACCINATION_REQUIRED.

    Design: Difficulty/priority_pair_validation_conflict/vaccination_safety_beats_deposit_fiscal
    """
    facility, owner, pet = setup_facility_owner_pet(
        deposit_policy="STANDARD", vaccinate=False, review="CLEAR")
    # Vaccinate with records that will be expired by a clock advance.
    from test_helpers import vaccinate_cat_valid
    vaccinate_cat_valid(pet["id"], administered_on="2025-01-01", expires_on="2026-01-15")
    run = create_run(facility["id"], label="Suite-I1", kind="OVERNIGHT_SUITE", size_class="LARGE")
    res = get_success_data(api_client.create_reservation(
        facility["id"],
        create_reservation_payload(pet["id"], "OVERNIGHT", "2026-03-01", "2026-03-03"),
        MGR,
    ))
    create_assignment(res["id"], run["id"], res["version"])
    advance_clock(facility["id"], "2026-02-01")  # vaccines expired; deposit still unpaid
    out = api.confirm_reservation(res["id"], MGR)
    validate_error(out, "ERR_VACCINATION_REQUIRED")


def test_vaccination_required_beats_deposit_unpaid_missing_vaccine(api):
    """PRD §3.6: "The confirm enforces a sequence of preconditions, evaluated in this
    order so that a more fundamental failure surfaces before a downstream one."
    PRD §3.6: "The pet's `vaccination_status` must be `VALID` at the facility's
    `current_date`, or the confirm is rejected with `ERR_VACCINATION_REQUIRED`."
    PRD §3.6: "Unless the facility's `deposit_policy` is `NONE`, the `deposit_paid_cents`
    must be at least the latched `deposit_cents`, or the confirm is rejected with
    `ERR_DEPOSIT_UNPAID`."

    A confirm violating both with a never-vaccinated (MISSING) pet AND an unpaid STANDARD
    deposit still returns the earlier-ordered ERR_VACCINATION_REQUIRED.

    Design: Difficulty/priority_pair_validation_conflict/vaccination_safety_beats_deposit_fiscal
    """
    facility, owner, pet = setup_facility_owner_pet(
        deposit_policy="STANDARD", weight_kg=18, vaccinate=False, review="CLEAR")
    assert pet["vaccination_status"] == "MISSING"
    run = create_run(facility["id"], label="Suite-I2", kind="OVERNIGHT_SUITE", size_class="LARGE")
    res = get_success_data(api_client.create_reservation(
        facility["id"],
        create_reservation_payload(pet["id"], "OVERNIGHT", "2026-03-01", "2026-03-03"),
        MGR,
    ))
    create_assignment(res["id"], run["id"], res["version"])  # deposit left unpaid
    out = api.confirm_reservation(res["id"], MGR)
    validate_error(out, "ERR_VACCINATION_REQUIRED")


def test_invalid_state_beats_run_eligibility(api):
    """PRD §3.10: "Only then are state and business rules evaluated: a transition
    attempted from a state that does not define it fails as `ERR_INVALID_STATE`, and the
    domain-specific checks described in the workflow sections above apply in the orders
    given there."
    PRD §3.6: "A run that fails any of these is rejected with `ERR_RUN_NOT_ELIGIBLE`."

    Creating an assignment on an already-CANCELLED reservation while naming a too-small
    run returns the earlier-ordered ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_run_eligibility
    """
    facility, owner, pet = setup_facility_owner_pet(
        deposit_policy="NONE", weight_kg=35, vaccinate=False, review=None)
    run = create_run(facility["id"], label="Suite-J1", kind="OVERNIGHT_SUITE", size_class="TOY")
    res = get_success_data(api_client.create_reservation(
        facility["id"],
        create_reservation_payload(pet["id"], "OVERNIGHT", "2026-04-01", "2026-04-03"),
        MGR,
    ))
    cancelled = validate_success(api.cancel_reservation(res["id"], MGR), 200)
    assert cancelled["status"] == "CANCELLED"
    out = api.create_assignment(
        res["id"], create_assignment_payload(run["id"], cancelled["version"]), MGR)
    validate_error(out, "ERR_INVALID_STATE")


def test_invalid_state_beats_run_eligibility_retired_run(api):
    """PRD §3.10: "Only then are state and business rules evaluated: a transition
    attempted from a state that does not define it fails as `ERR_INVALID_STATE`, and the
    domain-specific checks described in the workflow sections above apply in the orders
    given there."
    PRD §3.6: "The target run must be eligible: its `status` must be `AVAILABLE`, its
    `size_class` must be at least the pet's `size_class` on the ordering where `TOY` is
    smallest, then `SMALL`, then `MEDIUM`, then `LARGE` is largest, and its `kind` must
    match the service — an `OVERNIGHT` reservation requires an `OVERNIGHT_SUITE` and a
    `DAYCARE` reservation requires a `DAYCARE_PEN`."

    Assignment-create on an already-CANCELLED reservation while naming a RETIRED run (a
    different ERR_RUN_NOT_ELIGIBLE trigger) still returns the earlier ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_run_eligibility
    """
    facility, owner, pet = setup_facility_owner_pet(
        deposit_policy="NONE", weight_kg=6, vaccinate=False, review=None)
    run = create_run(
        facility["id"], label="Suite-J2", kind="OVERNIGHT_SUITE", size_class="LARGE", status="RETIRED")
    res = get_success_data(api_client.create_reservation(
        facility["id"],
        create_reservation_payload(pet["id"], "OVERNIGHT", "2026-04-01", "2026-04-03"),
        MGR,
    ))
    cancelled = validate_success(api.cancel_reservation(res["id"], MGR), 200)
    assert cancelled["status"] == "CANCELLED"
    out = api.create_assignment(
        res["id"], create_assignment_payload(run["id"], cancelled["version"]), MGR)
    validate_error(out, "ERR_INVALID_STATE")


# --------------------------------------------------------------- corner confirm gates
def test_confirm_without_assignment_rejected(api):
    """PRD §3.6: "At least one `RunAssignment` in `HELD` status must exist for the
    reservation, or it is rejected with `ERR_NO_RUN_ASSIGNED`."

    Design: Corner/validations/confirm_without_assignment_rejected
    """
    facility, owner, pet = setup_facility_owner_pet(deposit_policy="NONE")
    res = get_success_data(api_client.create_reservation(
        facility["id"],
        create_reservation_payload(pet["id"], "DAYCARE", "2026-03-01", "2026-03-01"),
        MGR,
    ))
    out = api.confirm_reservation(res["id"], MGR)
    validate_error(out, "ERR_NO_RUN_ASSIGNED")


def test_deposit_unpaid_blocks_confirm(api):
    """PRD §3.6: "Unless the facility's `deposit_policy` is `NONE`, the `deposit_paid_cents`
    must be at least the latched `deposit_cents`, or the confirm is rejected with
    `ERR_DEPOSIT_UNPAID`."

    Design: Corner/validations/deposit_unpaid_blocks_confirm
    """
    ctx = setup_held_reservation(
        service_type="OVERNIGHT", start_date="2026-03-01", end_date="2026-03-04",
        deposit_policy="STANDARD", weight_kg=18)
    assert ctx["reservation"]["deposit_paid_cents"] == 0
    out = api.confirm_reservation(ctx["reservation"]["id"], MGR)
    validate_error(out, "ERR_DEPOSIT_UNPAID")


def test_temperament_flagged_blocks_confirm(api):
    """PRD §3.6: "The pet's `temperament_clearance` must not be `FLAGGED`, or the confirm
    is rejected with `ERR_TEMPERAMENT_NOT_CLEARED`."

    Design: Corner/validations/temperament_flagged_blocks_confirm
    """
    ctx = setup_held_reservation(
        service_type="DAYCARE", start_date="2026-03-01", end_date="2026-03-01",
        deposit_policy="NONE", temperament="REACTIVE", review="FLAG")
    assert ctx["pet"]["temperament_clearance"] == "FLAGGED"
    assert ctx["pet"]["vaccination_status"] == "VALID"
    out = api.confirm_reservation(ctx["reservation"]["id"], MGR)
    validate_error(out, "ERR_TEMPERAMENT_NOT_CLEARED")
