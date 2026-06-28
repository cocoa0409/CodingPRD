"""Entity CRUD, creation, not-found, required fields, defaults, system fields,
listing, and foreign-key integrity.

All tests translate corner-design (queue B) instances.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    is_valid_uuid,
    ApiErrorId,
    NON_EXISTENT_UUID,
    set_clock,
    create_creditor,
    create_consumer,
    create_account_payload,
    assert_account,
    TEST_USERS,
)

COLLECTOR = TEST_USERS["collector_headers"]


# ===========================================================================
# entities / create_account_returns_201_with_computed_balance
# ===========================================================================
def test_create_account_returns_201_with_computed_balance():
    """PRD §3.2: "The ledger fields are initialized so that `balance_cents` equals
    `original_principal_cents`, while `amount_collected_cents` and
    `amount_settled_forgiven_cents` both start at 0."

    Design: Corner/entities/create_account_returns_201_with_computed_balance
    """
    set_clock("2026-01-01T00:00:00Z")
    creditor, creditor_headers = create_creditor()
    consumer = create_consumer()
    res = api_client.create_account(
        create_account_payload(creditor["id"], consumer["id"],
                               original_principal_cents=50000),
        creditor_headers,
    )
    acct = validate_success(res, 201)
    assert_account(acct)
    assert acct["balance_cents"] == 50000
    assert acct["work_status"] == "PLACED"
    assert acct["contact_status"] == "PRE_VALIDATION"
    assert acct["amount_collected_cents"] == 0


# ===========================================================================
# entities / get_account_nonexistent_returns_not_found
# ===========================================================================
def test_get_account_nonexistent_returns_not_found():
    """PRD §2.10: "The system then confirms that every referenced resource exists —
    both identifiers carried in the URL path and foreign keys carried in the body —
    validated left to right in the order they appear, with any missing reference
    yielding `ERR_NOT_FOUND`."

    Design: Corner/entities/get_account_nonexistent_returns_not_found
    """
    res = api_client.get_account(NON_EXISTENT_UUID, COLLECTOR)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# entities / create_account_missing_principal_returns_invalid_request
# ===========================================================================
def test_create_account_missing_principal_returns_invalid_request():
    """PRD §2.10: "Only then is the request body checked for well-formedness on write
    endpoints: required fields must be present, enum fields must carry recognized
    values, monetary amounts and the original principal must be greater than zero, a
    settlement offer expressed in basis points must lie between 1 and 10,000
    inclusive, and a commission rate in basis points must lie between 0 and 10,000
    inclusive; a body that fails any of these yields `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_account_missing_principal_returns_invalid_request
    """
    creditor, creditor_headers = create_creditor()
    consumer = create_consumer()
    payload = create_account_payload(creditor["id"], consumer["id"])
    del payload["original_principal_cents"]
    res = api_client.create_account(payload, creditor_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# entities / account_sol_anchor_basis_default_is_charge_off
# ===========================================================================
def test_account_sol_anchor_basis_default_is_charge_off():
    """PRD §3.2: "The `sol_anchor_basis` selects which event starts the statute clock
    and is one of `CHARGE_OFF` or `LAST_PAYMENT`, defaulting to `CHARGE_OFF`."

    Design: Corner/entities/account_sol_anchor_basis_default_is_charge_off
    """
    set_clock("2026-01-01T00:00:00Z")
    creditor, creditor_headers = create_creditor()
    consumer = create_consumer()
    payload = create_account_payload(creditor["id"], consumer["id"],
                                     original_principal_cents=50000)
    # sol_anchor_basis omitted by the factory
    assert "sol_anchor_basis" not in payload
    acct = validate_success(api_client.create_account(payload, creditor_headers), 201)
    assert acct["sol_anchor_basis"] == "CHARGE_OFF"


# ===========================================================================
# entities / account_id_and_version_system_minted_input_ignored
# ===========================================================================
def test_account_id_and_version_system_minted():
    """PRD §2.5: "Every resource in the system carries a server-minted `id` formatted
    as a UUID with no type prefix"
    PRD §2.5: "a `version`, an integer that begins at its initial value on creation
    and increments by one on every mutation of the resource."

    Design: Corner/entities/account_id_and_version_system_minted_input_ignored
    """
    creditor, creditor_headers = create_creditor()
    consumer = create_consumer()
    res = api_client.create_account(
        create_account_payload(creditor["id"], consumer["id"],
                               original_principal_cents=50000),
        creditor_headers,
    )
    acct = validate_success(res, 201)
    assert acct["version"] == 1
    assert is_valid_uuid(acct["id"]), "id must be a UUID with no type prefix"


# ===========================================================================
# entities / list_accounts_paginated_envelope
# ===========================================================================
def test_list_accounts_paginated_envelope():
    """PRD §2.3: "List responses carry the pagination bookkeeping in the `meta` object
    of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_accounts_paginated_envelope
    """
    creditor, creditor_headers = create_creditor()
    consumer = create_consumer()
    get_success_data(api_client.create_account(
        create_account_payload(creditor["id"], consumer["id"],
                               original_principal_cents=50000),
        creditor_headers,
    ))
    data, meta = validate_paginated(
        api_client.list_accounts(COLLECTOR, params={"creditor_id": creditor["id"]})
    )
    assert meta["total_count"] >= 1
    assert "has_more" in meta


# ===========================================================================
# entities / fk_account_creditor_must_exist
# ===========================================================================
def test_fk_account_creditor_must_exist():
    """PRD §2.10: "The system then confirms that every referenced resource exists —
    both identifiers carried in the URL path and foreign keys carried in the body —
    validated left to right in the order they appear, with any missing reference
    yielding `ERR_NOT_FOUND`."

    Design: Corner/entities/fk_account_creditor_must_exist
    """
    consumer = create_consumer()
    # A creditor record is needed only to act as the caller; the body creditor_id is bogus.
    _, creditor_headers = create_creditor()
    res = api_client.create_account(
        create_account_payload(NON_EXISTENT_UUID, consumer["id"],
                               original_principal_cents=50000),
        creditor_headers,
    )
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)
