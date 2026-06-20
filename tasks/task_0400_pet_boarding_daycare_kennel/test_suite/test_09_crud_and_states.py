"""CRUD creation/read invariants and reservation/state-machine basics.

Translates corner (B) entities, state_machines, and the deposit-NONE calculation
instances.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    NON_EXISTENT_UUID,
    create_facility, create_owner, create_pet,
    create_reservation_payload,
    setup_facility_owner_pet, setup_confirmed_reservation,
    TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]


# --------------------------------------------------------------- entities
def test_create_owner_returns_201_with_system_fields(api):
    """PRD §3.2: "The owner's `facility_id` is captured from the facility in the path, its
    `status` is set to `ACTIVE`, and its `wallet_credit_cents` starts at 0."
    PRD §2.4: "The `version` field is an integer that begins at its initial value and
    increments by one on every mutation".

    Design: Corner/entities/create_owner_returns_201_with_system_fields
    """
    facility = create_facility()
    owner = validate_success(api_client.create_owner(
        facility["id"],
        {"full_name": "Cre Owner", "email": "cre-owner@x.com", "phone": "555-1000"}, MGR), 201)
    assert owner["status"] == "ACTIVE"
    assert owner["wallet_credit_cents"] == 0
    assert owner["version"] == 1


def test_get_pet_nonexistent_returns_not_found(api):
    """PRD §2.5: "the system confirms the existence of each in that order and rejects the
    first one that does not exist with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_pet_nonexistent_returns_not_found
    """
    res = api.get_pet(NON_EXISTENT_UUID, MGR)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_pet_missing_weight_invalid_request(api):
    """PRD §3.10: "on every write endpoint the body must have its required fields present,
    its enums in range, its `weight_kg` and `quantity` values strictly greater than zero,
    its dates in `YYYY-MM-DD` form, and its date ordering correct (`end_date` strictly
    after `start_date` for overnight, `end_date` equal to `start_date` for daycare),
    failing as `ERR_INVALID_REQUEST`."

    weight_kg has no default and is a required input -> omitting it is ERR_INVALID_REQUEST.

    Design: Corner/entities/create_pet_missing_required_weight_invalid_request
    """
    facility = create_facility()
    owner = create_owner(facility["id"])
    res = api_client.create_pet(owner["id"], {"name": "NoWeight", "species": "DOG"}, MGR)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_create_pet_nonpositive_weight_invalid_request(api):
    """PRD §3.2: "The weight must be strictly greater than zero."
    PRD §3.10: "on every write endpoint the body must have its required fields present,
    its enums in range, its `weight_kg` and `quantity` values strictly greater than zero,
    its dates in `YYYY-MM-DD` form, and its date ordering correct (`end_date` strictly
    after `start_date` for overnight, `end_date` equal to `start_date` for daycare),
    failing as `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_pet_nonpositive_weight_invalid_request
    """
    facility = create_facility()
    owner = create_owner(facility["id"])
    res = api_client.create_pet(
        owner["id"], {"name": "ZeroW", "species": "DOG", "weight_kg": 0}, MGR)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


# --------------------------------------------------------------- state machines
def test_reservation_initial_state_requested(api):
    """PRD §3.5: "At creation the reservation enters `REQUESTED` status and its deposit is
    estimated."

    Design: Corner/state_machines/reservation_initial_state_requested
    """
    facility, owner, pet = setup_facility_owner_pet(deposit_policy="NONE", vaccinate=False, review=None)
    res = validate_success(api_client.create_reservation(
        facility["id"],
        create_reservation_payload(pet["id"], "DAYCARE", "2026-03-01", "2026-03-01"),
        MGR), 201)
    assert res["status"] == "REQUESTED"


def test_check_in_from_requested_invalid_state(api):
    """PRD §3.8: "Once a reservation is `CONFIRMED`, check-in moves it to `CHECKED_IN`."
    PRD §3.10: "a transition attempted from a state that does not define it fails as
    `ERR_INVALID_STATE`".

    check_in on a REQUESTED (never confirmed) reservation -> ERR_INVALID_STATE.

    Design: Corner/state_machines/check_in_from_requested_invalid_state
    """
    facility, owner, pet = setup_facility_owner_pet(deposit_policy="NONE", vaccinate=False, review=None)
    res = get_success_data(api_client.create_reservation(
        facility["id"],
        create_reservation_payload(pet["id"], "DAYCARE", "2026-03-01", "2026-03-01"),
        MGR))
    out = api.check_in(res["id"], MGR)
    validate_error(out, "ERR_INVALID_STATE")


def test_cancel_from_cancelled_terminal_lockdown(api):
    """PRD §3.8: "A reservation may be cancelled out of either `REQUESTED` or `CONFIRMED`.
    An owner, staff member, or manager may cancel; a cancel from any other state is
    rejected with `ERR_INVALID_STATE`".
    PRD §3.8: "`CLOSED`, `CANCELLED`, and `NO_SHOW` are the three terminal states a
    reservation can reach."

    A second cancel on an already-CANCELLED reservation -> ERR_INVALID_STATE.

    Design: Corner/state_machines/cancel_from_cancelled_terminal_lockdown
    """
    facility, owner, pet = setup_facility_owner_pet(deposit_policy="NONE", vaccinate=False, review=None)
    res = get_success_data(api_client.create_reservation(
        facility["id"],
        create_reservation_payload(pet["id"], "DAYCARE", "2026-03-01", "2026-03-01"),
        MGR))
    validate_success(api.cancel_reservation(res["id"], MGR), 200)
    out = api.cancel_reservation(res["id"], MGR)
    validate_error(out, "ERR_INVALID_STATE")


def test_no_show_too_early_rejected(api):
    """PRD §3.8: "A no-show is the manager-only terminal fork from `CONFIRMED`. It may be
    declared only after the service date has passed — the facility's `current_date` must
    be strictly after the reservation's `start_date`, or it is rejected with
    `ERR_NO_SHOW_TOO_EARLY`".

    A CONFIRMED reservation whose start_date is still in the future cannot be no-showed.

    Design: Corner/state_machines/no_show_too_early_rejected
    """
    ctx = setup_confirmed_reservation(
        service_type="DAYCARE", start_date="2026-06-01", end_date="2026-06-01",
        deposit_policy="NONE", daycare_capacity=5)
    res = ctx["reservation"]
    # current_date is 2026-01-01 (never advanced) < start_date 2026-06-01.
    out = api.mark_no_show(res["id"], MGR)
    validate_error(out, "ERR_NO_SHOW_TOO_EARLY")


# --------------------------------------------------------------- calculations
def test_deposit_policy_none_is_zero(api):
    """PRD §3.5: "That raw product is then multiplied by the policy factor selected by the
    facility's `deposit_policy`: 0.30 for `STANDARD`, 0.50 for `STRICT`, and 0 for `NONE`."

    Under NONE policy the deposit is 0 regardless of service/size/nights.

    Design: Corner/calculations/deposit_policy_none_is_zero
    """
    facility, owner, pet = setup_facility_owner_pet(
        deposit_policy="NONE", weight_kg=35, vaccinate=False, review=None)
    assert pet["size_class"] == "LARGE"
    res = validate_success(api_client.create_reservation(
        facility["id"],
        create_reservation_payload(pet["id"], "OVERNIGHT", "2026-03-01", "2026-03-03"),
        MGR), 201)
    assert res["deposit_cents"] == 0
