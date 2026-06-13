"""Catalog and account creation: CRUD, required-field, FK, and creation-gate rules.

Translates queue-B (Corner) instances from the entities and validations sections.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_plan_payload, create_single_wash_plan_payload,
    create_account_payload, create_fleet_account_payload, create_vehicle_payload,
    create_membership_payload,
    assert_account,
    TEST_USERS, make_account_holder_headers,
    create_account, create_vehicle,
    ABSENT_UUID,
)

PA = TEST_USERS["platform_admin_headers"]


def test_create_individual_account_returns_201_with_defaults(api):
    """PRD §3.2: "A new account opens in `status` `ACTIVE` with a `wallet_balance_cents`
    of 0."
    PRD §2.4: "a `version`, an integer that starts at 1 on creation and increases by
    exactly 1 on every mutation, cascades included."

    Design: Corner/entities/create_account_individual_returns_201_with_defaults
    """
    res = api.create_account(
        create_account_payload(contact_email="new@x.com"),
        make_account_holder_headers("ah-create"),
    )
    acct = validate_success(res, 201)
    assert_account(acct)
    assert acct["status"] == "ACTIVE"
    assert acct["wallet_balance_cents"] == 0
    assert acct["version"] == 1


def test_create_fleet_account_without_company_name_rejected(api):
    """PRD §3.2: "a `FLEET` account must supply `company_name`, and an `INDIVIDUAL`
    account must not supply one; either violation is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_account_fleet_missing_company_name_invalid_request
    """
    res = api.create_account(
        {"account_type": "FLEET", "contact_email": "fleet@x.com"}, PA
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_get_nonexistent_account_not_found(api):
    """PRD §2.6: "The same left-to-right existence rule applies to any single-resource
    path: the path-referenced resource must exist or the request is rejected with
    `ERR_NOT_FOUND`."

    Design: Corner/entities/get_account_nonexistent_not_found
    """
    res = api.get_account(ABSENT_UUID, PA)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_membership_unknown_plan_fk_not_found(api):
    """PRD §2.11: "existence of every foreign key supplied in the body, such as
    `account_id`, `plan_id`, `vehicle_id`, `addon_id`, `location_id`, or
    `membership_id` (`ERR_FK_NOT_FOUND`)".

    Design: Corner/entities/create_membership_unknown_plan_fk_not_found
    """
    acct = create_account(contact_email="fk@x.com")
    hdr = make_account_holder_headers(acct["id"])
    veh = create_vehicle(acct["id"], "FKK001", "CA", hdr)
    res = api.create_membership(
        create_membership_payload(acct["id"], veh["id"], ABSENT_UUID), hdr
    )
    validate_error(res, "ERR_FK_NOT_FOUND", expected_status=404)


def test_single_wash_plan_with_nonzero_fee_rejected(api):
    """PRD §3.1: "a `SINGLE_WASH` plan must grant a positive number of `included_credits`,
    must set `monthly_fee_cents` to 0, and must set `wash_cooldown_hours` to 0; an
    `UNLIMITED` plan must set `included_credits` to 0. Any plan whose field combination
    violates these tier rules is rejected with `ERR_PLAN_SHAPE_INVALID`."

    Design: Corner/entities/plan_shape_single_wash_nonzero_fee_rejected
    """
    res = api.create_plan(
        create_single_wash_plan_payload(
            name="BadSingle", monthly_fee_cents=500, included_credits=1
        ),
        PA,
    )
    validate_error(res, "ERR_PLAN_SHAPE_INVALID", expected_status=422)


def test_duplicate_active_plate_rejected(api):
    """PRD §3.2: "A registered plate must be unique among vehicles that are still
    `ACTIVE`: registering a plate already held by an `ACTIVE` vehicle is rejected with
    `ERR_PLATE_TAKEN`."

    Design: Corner/validations/duplicate_active_plate_rejected
    """
    acct = create_account(contact_email="dup@x.com")
    hdr = make_account_holder_headers(acct["id"])
    create_vehicle(acct["id"], "DUP001", "CA", hdr)
    res = api.create_vehicle(acct["id"], create_vehicle_payload("DUP001", "CA"), hdr)
    validate_error(res, "ERR_PLATE_TAKEN", expected_status=409)


def test_vehicle_create_on_suspended_account_rejected(api):
    """PRD §3.2: "Vehicles may only be added under an account whose `status` is `ACTIVE`;
    attempting to register a vehicle (or to enroll a membership, or to run billing)
    against an account that is not `ACTIVE` is rejected with `ERR_ACCOUNT_NOT_ACTIVE`."

    Design: Corner/validations/vehicle_create_on_suspended_account_rejected
    """
    acct = create_account(contact_email="sus@x.com")
    validate_success(api.suspend_account(acct["id"], PA), 200)
    hdr = make_account_holder_headers(acct["id"])
    res = api.create_vehicle(acct["id"], create_vehicle_payload("SUS001", "CA"), hdr)
    validate_error(res, "ERR_ACCOUNT_NOT_ACTIVE", expected_status=409)


def test_membership_on_retired_plan_rejected(api):
    """PRD §3.1: "Newly referencing a `RETIRED` plan or a `RETIRED` add-on when enrolling
    a membership or attaching an add-on is rejected with `ERR_RESOURCE_RETIRED`."

    Design: Corner/validations/membership_on_retired_plan_rejected
    """
    plan = validate_success(api.create_plan(create_plan_payload(name="URet"), PA), 201)
    validate_success(api.retire_plan(plan["id"], PA), 200)
    acct = create_account(contact_email="ret@x.com")
    hdr = make_account_holder_headers(acct["id"])
    veh = create_vehicle(acct["id"], "RET001", "CA", hdr)
    res = api.create_membership(
        create_membership_payload(acct["id"], veh["id"], plan["id"]), hdr
    )
    validate_error(res, "ERR_RESOURCE_RETIRED", expected_status=409)
