"""CRUD basics, input validation, listing envelope, immutability, and RBAC/auth.

Covers corner instances in the entities and rbac sections (queue B).
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    assert_impound_lot,
    assert_storage_ledger_entry,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_impound_lot_payload,
    create_tow_order_payload,
    set_clock,
    create_lot,
    create_order,
    create_stored_order,
)

OP = TEST_USERS["lot_operator_headers"]
CLAIMANT = TEST_USERS["claimant_headers"]


# ─── Corner: entities / create_impound_lot_returns_201_with_fields ────────────
def test_create_impound_lot_returns_201_with_defaults(api):
    """PRD §3.1: "A new lot begins life with status of OPEN, with its rotation_cursor
    initialized to 0, and with version 1."

    Design: Corner/entities/create_impound_lot_returns_201_with_fields
    """
    res = api.create_impound_lot(create_impound_lot_payload(
        name="Lot CR", daily_storage_rate_cents=5000), OP)
    lot = validate_success(res, 201)
    assert_impound_lot(lot)
    assert lot["status"] == "OPEN"
    assert lot["rotation_cursor"] == 0
    assert lot["version"] == 1
    assert lot["daily_storage_rate_cents"] == 5000


# ─── Corner: entities / get_tow_order_not_found_returns_404 ───────────────────
def test_get_nonexistent_tow_order_returns_404(api):
    """PRD §2.5: "the server validates them in left-to-right order and rejects the request
    with ERR_NOT_FOUND for the first identifier in the path that does not correspond to an
    existing resource."

    Design: Corner/entities/get_tow_order_not_found_returns_404
    """
    res = api.get_tow_order(NON_EXISTENT_UUID, OP)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# ─── Corner: entities / create_tow_order_missing_required_field_returns_422 ───
def test_create_tow_order_missing_vin_returns_422(api):
    """PRD §3.10: "the request body is well-formed — required fields present, enum values
    valid, amounts non-negative where required ... (ERR_INVALID_REQUEST)"

    Design: Corner/entities/create_tow_order_missing_required_field_returns_422
    """
    lot = create_lot(name="Lot RF")
    payload = create_tow_order_payload(lot["id"], tow_type="POLICE")
    del payload["vin"]
    res = api.create_tow_order(payload, OP)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


# ─── Corner: entities / create_tow_order_invalid_enum_tow_type_returns_422 ────
def test_create_tow_order_invalid_tow_type_returns_422(api):
    """PRD §3.3: "the tow_type (one of POLICE, PRIVATE, or ABANDONED)"
    PRD §3.10: "enum values valid ... (ERR_INVALID_REQUEST)"

    Design: Corner/entities/create_tow_order_invalid_enum_tow_type_returns_422
    """
    lot = create_lot(name="Lot EN")
    payload = create_tow_order_payload(lot["id"], tow_type="HELICOPTER")
    res = api.create_tow_order(payload, OP)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


# ─── Corner: entities / tow_order_default_status_and_estimate_computed_at_intake ─
def test_intake_defaults_status_towed_and_computes_estimate(api):
    """PRD §3.3: "A new order is stamped with intake_at ... and begins in status TOWED
    with hold_status NONE. At intake the system fixes the order's estimated_storage_cents,
    a forward-looking ESTIMATE projection computed once and never re-counted: it is the
    lot's daily_storage_rate_cents multiplied by the lot's statutory_hold_days"

    Design: Corner/entities/tow_order_default_status_and_estimate_computed_at_intake
    """
    lot = create_lot(name="Lot CF", daily_storage_rate_cents=5000, statutory_hold_days=30)
    order = get_success_data(api.create_tow_order(
        create_tow_order_payload(lot["id"], tow_type="POLICE"), OP))
    assert order["status"] == "TOWED"
    assert order["estimated_storage_cents"] == 150000, "5000 * 30"


# ─── Corner: entities / tow_order_with_bad_lienholder_id_returns_404 ──────────
def test_intake_with_nonexistent_lienholder_returns_404(api):
    """PRD §2.5: "a named lienholder_id must resolve to an existing lienholder"
    PRD §2.5: "rejects the request with ERR_NOT_FOUND for the first identifier in the path
    that does not correspond to an existing resource."

    Design: Corner/entities/tow_order_with_bad_lienholder_id_returns_404
    """
    lot = create_lot(name="Lot LH")
    payload = create_tow_order_payload(
        lot["id"], tow_type="PRIVATE", lienholder_id="00000000-0000-4000-8000-000000000001")
    res = api.create_tow_order(payload, OP)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# ─── Corner: entities / list_tow_orders_paginated_envelope ────────────────────
def test_list_tow_orders_returns_paginated_array_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the meta object
    of the response envelope: limit, offset, total_count, and has_more."

    Design: Corner/entities/list_tow_orders_paginated_envelope
    """
    lot = create_lot(name="Lot PG")
    create_order(lot["id"], tow_type="POLICE")
    res = api.list_tow_orders(OP, params={"lot_id": lot["id"]})
    body = res.json()
    assert body["response_type"] == "array"
    assert "total_count" in body["meta"]
    assert "has_more" in body["meta"]
    assert body["meta"]["total_count"] == 1


# ─── Corner: entities / immutable_storage_ledger_entry_has_no_version ─────────
def test_storage_ledger_entry_is_immutable(api):
    """PRD §2.4: "The StorageLedgerEntry, which records an individual segment of storage
    accrual, is immutable once written and therefore carries only id and created_at; it
    has neither an updated_at field nor a version field."

    Design: Corner/entities/immutable_storage_ledger_entry_has_no_version
    """
    set_clock("2026-01-01T00:00:00Z")
    lot, order = create_stored_order(order_overrides={"tow_type": "POLICE"})
    res = api.list_ledger_entries(order["id"], OP)
    body = res.json()
    assert body["response_type"] == "array"
    entries = body["data"]
    assert len(entries) >= 1
    first = entries[0]
    assert_storage_ledger_entry(first)
    assert first["kind"] == "ACCRUAL"


# ─── Corner: rbac / claimant_cannot_authorize_release ─────────────────────────
def test_claimant_cannot_authorize_release(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not permitted
    to perform the requested operation, the request is rejected with ERR_FORBIDDEN_FOR_ROLE."

    Design: Corner/rbac/claimant_cannot_authorize_release
    """
    lot, order = create_stored_order(order_overrides={"tow_type": "POLICE"})
    res = api.authorize_release(order["id"], CLAIMANT)
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE", expected_status=403)


# ─── Corner: rbac / missing_user_context_header_returns_400 ───────────────────
def test_missing_user_context_header_returns_400(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is
    rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

    Design: Corner/rbac/missing_user_context_header_returns_400
    """
    res = api.get_tow_order("00000000-0000-4000-8000-000000000002", {})
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", expected_status=400)
