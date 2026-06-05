"""Entity creation, defaults, system fields, not-found, required fields, immutability."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_account, create_account_payload, create_vehicle_payload,
    assert_account, assert_vehicle, assert_ledger_entry,
    api_client, TEST_USERS, make_account_holder_headers,
)

OP = TEST_USERS["toll_operator_headers"]
HOLDER = TEST_USERS["account_holder_headers"]
ADMIN = TEST_USERS["system_admin_headers"]


def test_create_account_returns_defaults(api):
    """PRD §3.1: "A new account begins in `ACTIVE` status with a `balance_cents` of 0."
    PRD §2.4: "`version`, an integer that begins at 1 and increments by 1 on every
    mutation of the resource."

    Design: Corner/entities/create_account_returns_defaults
    """
    res = api.create_account(create_account_payload(holder_name="Dee", home_state_code="NJ"),
                             HOLDER)
    acct = validate_success(res, 201)
    assert_account(acct)
    assert acct["status"] == "ACTIVE"
    assert acct["balance_cents"] == 0
    assert acct["version"] == 1


def test_account_defaults_applied_when_omitted(api):
    """PRD §3.1: "The `low_balance_threshold_cents` is the balance at or below which
    auto-reload fires; it must be at least 0 and defaults to 1000. The
    `auto_reload_enabled` flag arms the feature and defaults to false. The
    `reload_policy` chooses between two top-up algorithms and is either `FIXED` or
    `RESTORE_TO_TARGET`, defaulting to `FIXED`."

    Design: Corner/entities/account_defaults_applied_when_omitted
    """
    res = api.create_account(create_account_payload(holder_name="Def", home_state_code="NY"),
                             HOLDER)
    acct = validate_success(res, 201)
    assert acct["low_balance_threshold_cents"] == 1000
    assert acct["reload_policy"] == "FIXED"
    assert acct["auto_reload_enabled"] is False


def test_account_get_not_found(api):
    """PRD §2.7: "the first one that does not resolve causes immediate rejection with
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/account_get_not_found
    """
    res = api.get_account("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_account_missing_required_field(api):
    """PRD §2.9: "the structural body check — valid JSON, required fields present, enum
    values legal, numeric constraints satisfied, else `ERR_VALIDATION` (422)."
    PRD §3.1: "An account is opened by supplying a `holder_name` and a two-letter
    `home_state_code`."

    Design: Corner/entities/account_missing_required_field
    """
    res = api.create_account({"home_state_code": "NY"}, HOLDER)
    validate_error(res, "ERR_VALIDATION", expected_status=422)


def test_vehicle_system_fields_generated(api):
    """PRD §3.3: "A new vehicle's `registration_status` is `REGISTERED`."

    Design: Corner/entities/vehicle_system_fields_generated
    """
    account = create_account(holder_name="Veh")
    res = api.create_vehicle(create_vehicle_payload(account["id"], plate_number="ZZ1",
                             plate_state_code="NY"), OP)
    vehicle = validate_success(res, 201)
    assert_vehicle(vehicle)
    assert vehicle["registration_status"] == "REGISTERED"


def test_ledger_entry_immutable_no_version(api):
    """PRD §2.4: "A ledger entry is an append-only event and is never modified after it
    is written, so it carries only `id` and `created_at`; it has neither an `updated_at`
    field nor a `version` field."
    PRD §3.1: "A credit operation supplies an `amount_cents`, adds it to `balance_cents`,
    and appends a `RELOAD_CREDIT` ledger entry recording the new balance."

    Design: Corner/entities/ledger_entry_immutable_no_version
    """
    account = create_account(holder_name="Led")
    api.credit_account(account["id"], {"amount_cents": 500}, OP)
    entries = validate_success(api.list_account_ledger_entries(account["id"], OP), 200)
    credit_entries = [e for e in entries if e["entry_type"] == "RELOAD_CREDIT"]
    assert len(credit_entries) >= 1
    entry = credit_entries[0]
    assert_ledger_entry(entry)
    assert entry["amount_cents"] == 500
    assert entry["balance_after_cents"] == 500
    for e in entries:
        assert "version" not in e, "LedgerEntry must not carry a version field"


def test_vehicle_wrong_parent_account_not_found(api):
    """PRD §2.7: "Every foreign-key identifier supplied in a path or request body must
    resolve to an existing resource. Identifiers are validated left to right in the order
    they appear, and the first one that does not resolve causes immediate rejection with
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/vehicle_wrong_parent_account_not_found
    """
    res = api.create_vehicle(create_vehicle_payload(
        "00000000-0000-4000-8000-000000000000", plate_number="NO1", plate_state_code="NY"), OP)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)
