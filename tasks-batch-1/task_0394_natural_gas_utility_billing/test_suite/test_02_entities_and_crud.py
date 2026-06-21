"""Entity CRUD tests: creation, retrieval, listing, not-found, required/optional fields,
defaults, computed/system fields, type constraints, immutability, parent FK integrity."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    fixtures as fx,
    assert_account, assert_rate_schedule, assert_meter, assert_meter_read,
    assert_no_version_fields,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
)

ADMIN = TEST_USERS["billing_admin_headers"]
CS = TEST_USERS["customer_service_headers"]
FT = TEST_USERS["field_tech_headers"]


def test_create_rate_schedule_returns_201_with_fields(api):
    """PRD 3.1: "A rate schedule is created with a unique code ..., a customer_class of either
    RESIDENTIAL or COMMERCIAL, a fixed_customer_charge_cents ..., and a
    distribution_rate_cents_per_therm". PRD 3.1: "Each schedule carries a system-managed
    active flag that defaults to true".

    Design: Corner/entities/create_rate_schedule_returns_201_with_fields
    """
    resp = api.create_rate_schedule(
        {"code": "RES-E1", "customer_class": "RESIDENTIAL", "fixed_customer_charge_cents": 1200,
         "distribution_rate_cents_per_therm": 15, "btu_factor": 1.025, "minimum_bill_cents": 0},
        headers=ADMIN)
    data = validate_success(resp, 201)
    assert_rate_schedule(data)
    assert data["code"] == "RES-E1"
    assert data["customer_class"] == "RESIDENTIAL"
    assert data["fixed_customer_charge_cents"] == 1200
    assert data["distribution_rate_cents_per_therm"] == 15
    assert data["active"] is True


def test_rate_schedule_btu_factor_default_applied(api):
    """PRD 3.1: "btu_factor ... defaults to 1.025 ...; and minimum_bill_cents, a floor applied
    to total current charges before credits, which defaults to 0".

    Design: Corner/entities/rate_schedule_btu_factor_default_applied_when_omitted
    """
    resp = api.create_rate_schedule(
        {"code": "RES-E2", "customer_class": "RESIDENTIAL", "fixed_customer_charge_cents": 1200,
         "distribution_rate_cents_per_therm": 15},
        headers=ADMIN)
    data = validate_success(resp, 201)
    assert data["btu_factor"] == 1.025, f"got {data['btu_factor']}"
    assert data["minimum_bill_cents"] == 0, f"got {data['minimum_bill_cents']}"


def test_account_customer_class_copied_from_rate_schedule(api):
    """PRD 3.2: "At creation the account copies its customer_class from the assigned rate
    schedule, comes up with service_status of ACTIVE, and starts every money-derived field ...
    at 0."

    Design: Corner/entities/account_customer_class_copied_from_rate_schedule
    """
    rs = fx.create_rate_schedule(customer_class="COMMERCIAL", fixed_customer_charge_cents=4000,
                                 distribution_rate_cents_per_therm=20)
    resp = api.create_account({"rate_schedule_id": rs["id"], "holder_name": "COM Holder"}, headers=CS)
    data = validate_success(resp, 201)
    assert data["customer_class"] == "COMMERCIAL", f"got {data['customer_class']}"
    assert data["service_status"] == "ACTIVE"
    assert data["balance_cents"] == 0


def test_account_system_defaults_on_open(api):
    """PRD 3.2: "low_income_status is NONE, low_income_tier is NONE, budget_enrolled is false,
    and consecutive_ontime_payments is 0." PRD 2.4: "version, an integer that begins at 1 on
    creation".

    Design: Corner/entities/account_system_defaults_on_open
    """
    rs = fx.create_rate_schedule()
    resp = api.create_account({"rate_schedule_id": rs["id"], "holder_name": "Defaults"}, headers=CS)
    data = validate_success(resp, 201)
    assert data["service_status"] == "ACTIVE"
    assert data["low_income_status"] == "NONE"
    assert data["low_income_tier"] == "NONE"
    assert data["budget_enrolled"] is False
    assert data["consecutive_ontime_payments"] == 0
    assert data["version"] == 1


def test_get_account_returns_stored_entity(api):
    """PRD 2.4: "created_at is fixed at creation". PRD 3.2: "starts every money-derived field —
    balance_cents, past_due_cents, deposit_held_cents — at 0."

    Design: Corner/entities/get_account_returns_stored_entity
    """
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"], holder_name="Readback")
    resp = api.get_account(acct["id"], headers=ADMIN)
    data = validate_success(resp, 200)
    assert_account(data)
    assert data["holder_name"] == "Readback"
    assert data["balance_cents"] == 0


def test_list_accounts_filtered_by_rate_schedule(api):
    """PRD 4 (endpoint): "List accounts, optionally filtered by rate schedule". PRD 2.3: "The
    meta block of a list response carries limit, offset, total_count ... and has_more".

    Design: Corner/entities/list_accounts_filtered_by_rate_schedule_pagination
    """
    rs_x = fx.create_rate_schedule()
    rs_y = fx.create_rate_schedule()
    fx.create_account(rs_x["id"], "X1")
    fx.create_account(rs_x["id"], "X2")
    fx.create_account(rs_y["id"], "Y1")
    resp = api.list_accounts(headers=ADMIN, params={"rate_schedule_id": rs_x["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"got {meta['total_count']}"
    assert all(a["rate_schedule_id"] == rs_x["id"] for a in data)


def test_get_account_nonexistent_returns_not_found(api):
    """PRD 2.5: "the server validates the chain left to right and returns ERR_NOT_FOUND
    (HTTP 404) at the first identifier in the path or body that does not resolve".

    Design: Corner/entities/get_account_nonexistent_returns_not_found
    """
    resp = api.get_account(NON_EXISTENT_UUID, headers=ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_account_missing_holder_name_returns_invalid_request(api):
    """PRD 2.10: "Request well-formedness is fourth: required body fields must be present and
    well-typed ... else ERR_INVALID_REQUEST (400)." PRD 3.2: "A CustomerService operator opens
    an account by supplying a rate_schedule_id and a holder_name."

    Design: Corner/entities/create_account_missing_holder_name_returns_invalid_request
    """
    rs = fx.create_rate_schedule()
    resp = api.create_account({"rate_schedule_id": rs["id"]}, headers=CS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_account_bad_rate_schedule_id_returns_not_found(api):
    """PRD 2.5: "the server validates the chain left to right and returns ERR_NOT_FOUND
    (HTTP 404) at the first identifier in the path or body that does not resolve".

    Design: Corner/entities/create_account_bad_rate_schedule_id_returns_not_found
    """
    resp = api.create_account({"rate_schedule_id": NON_EXISTENT_UUID, "holder_name": "Orphan"},
                              headers=CS)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_low_income_credit_invalid_household_size(api):
    """PRD 2.10: "integers constrained to be non-negative (or strictly positive) must respect
    those bounds, else ERR_INVALID_REQUEST (400)." PRD 3.8: "The application carries a
    household_size (at least 1)".

    Design: Corner/entities/create_low_income_credit_invalid_household_size_returns_invalid_request
    """
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    resp = api.create_low_income_credit(
        acct["id"], {"household_size": 0, "annual_income_cents": 1000000}, headers=CS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_pga_schedule_bad_customer_class_enum(api):
    """PRD 2.10: "enums must be valid ... else ERR_INVALID_REQUEST (400)." PRD 3.1: "It is
    created with an effective_month in YYYY-MM form, a customer_class (RESIDENTIAL or
    COMMERCIAL)".

    Design: Corner/entities/create_pga_schedule_bad_customer_class_enum_returns_invalid_request
    """
    resp = api.create_pga_schedule(
        {"effective_month": "2026-02", "customer_class": "INDUSTRIAL",
         "commodity_rate_cents_per_therm": 40, "supplier_refund_cents_per_therm": 5},
        headers=ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_meter_defaults_uom_and_install_index(api):
    """PRD 3.2: "an optional uom register unit that is CCF or THERM and defaults to CCF, and an
    optional install_index register reading at set time (the baseline), defaulting to 0 ...
    The meter is created with account_id linking it to its account and status of PENDING_SET."

    Design: Corner/entities/meter_read_install_index_default_and_status_posted
    """
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    resp = api.create_meter(acct["id"], {"serial_no": "MD-001"}, headers=FT)
    data = validate_success(resp, 201)
    assert data["uom"] == "CCF", f"got {data['uom']}"
    assert data["install_index"] == 0, f"got {data['install_index']}"
    assert data["status"] == "PENDING_SET", f"got {data['status']}"


def test_meter_read_is_append_only_no_version(api):
    """PRD 2.4: "a MeterRead (a captured register reading) ... carry only id and created_at —
    they have no updated_at and no version".

    Design: Corner/entities/meter_read_immutable_no_version_field
    """
    rs, acct, meter = fx.setup_account_with_set_meter()
    resp = api.post_read(meter["id"],
                         {"reading_index": 1100, "read_date": "2026-02-28T00:00:00.000Z",
                          "read_type": "ACTUAL"}, headers=FT)
    data = validate_success(resp, 201)
    assert_meter_read(data)
    assert data["status"] == "POSTED"
    assert_no_version_fields(data)


def test_meter_read_consumption_computed(api):
    """PRD 3.4: "for a CCF meter, therms_consumed is the raw delta multiplied by the rate
    schedule's btu_factor ... In both cases therms_consumed is rounded half up to one decimal
    place."

    Design: Corner/entities/meter_read_consumption_computed_input_ignored
    """
    rs, acct, meter = fx.setup_account_with_set_meter()
    # install 1000 -> read 1100 -> ccf 100 -> therms 100 * 1.025 = 102.5
    read = fx.post_read(meter["id"], 1100, "2026-02-28T00:00:00.000Z")
    assert read["ccf_consumed"] == 100, f"got {read['ccf_consumed']}"
    assert read["therms_consumed"] == 102.5, f"got {read['therms_consumed']}"
