"""Catalog, members, and the store-credit ledger basics.

Covers Corner queue instances in sections: entities, calculations, endpoints.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    assert_member, assert_store_credit_entry, NON_EXISTENT_UUID,
    create_member_payload, create_product_payload, adjustment_payload,
    TEST_USERS, create_member, grant_store_credit,
)

CLERK = TEST_USERS["clerk_headers"]
MANAGER = TEST_USERS["manager_headers"]


def test_create_member_minimal_defaults(api):
    """PRD §3.1: "A new member begins with a store_credit_balance_cents of zero and
    loyalty_points of zero, both of which are computed rather than directly set."
    PRD §3.1: "The tier is one of STANDARD, SILVER, or GOLD, defaulting to STANDARD
    when omitted."

    Design: Corner/entities/create_member_minimal_returns_object
    """
    res = api.create_member(create_member_payload(full_name="Minnie"), CLERK)
    member = validate_success(res, 201)
    assert_member(member)
    assert member["tier"] == "STANDARD"
    assert member["store_credit_balance_cents"] == 0
    assert member["loyalty_points"] == 0


def test_get_member_nonexistent_returns_not_found(api):
    """PRD §2.5: "For any path containing an identifier, the server validates that
    identifier before proceeding." PRD §2.5: "the first one that does not resolve
    produces ERR_NOT_FOUND (HTTP 404) before any deeper lookup or body validation
    is attempted."

    Design: Corner/entities/get_member_nonexistent_returns_not_found
    """
    res = api.get_member(NON_EXISTENT_UUID, CLERK)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_member_missing_email_returns_validation(api):
    """PRD §2.11: "then request-body schema validity — required fields present, enum
    members legal, numbers in range, sale lines non-empty with each qty at least 1
    (ERR_VALIDATION, 400)."

    Design: Corner/entities/create_member_missing_required_email_returns_validation
    """
    res = api.create_member({"full_name": "NoEmail"}, CLERK)
    validate_error(res, "ERR_VALIDATION", expected_status=400)


def test_create_product_invalid_kind_returns_validation(api):
    """PRD §3.1: "A Product is a catalog entry created with a title, a kind that is one
    of GAME, CONSOLE, or ACCESSORY, a base_price_cents that must be greater than zero."

    Design: Corner/entities/create_product_invalid_kind_enum_returns_validation
    """
    payload = create_product_payload(kind="TOY")
    res = api.create_product(payload, CLERK)
    validate_error(res, "ERR_VALIDATION", expected_status=400)


def test_store_credit_entry_is_immutable_no_version(api):
    """PRD §2.4: "A StoreCreditEntry is an append-only ledger event, not a mutable
    resource: it carries only id and created_at. It has no updated_at and no version,
    because once written a ledger entry is never modified."
    PRD §3.8: "This appends a StoreCreditEntry with reason MANUAL_ADJUSTMENT and a
    null related_ref, and recomputes the member's balance."

    Design: Corner/entities/store_credit_entry_is_immutable_no_version
    """
    member = create_member(full_name="Led")
    res = api.adjust_store_credit(member["id"], adjustment_payload(500), MANAGER)
    entry = validate_success(res, 201)
    assert_store_credit_entry(entry)
    assert entry["amount_cents"] == 500
    assert entry["reason"] == "MANUAL_ADJUSTMENT"
    assert "version" not in entry
    assert "updated_at" not in entry


# ─── calculations section ─────────────────────────────────────────────────
def test_manual_adjustment_updates_member_balance(api):
    """PRD §2.8: "It is always the sum of that member's StoreCreditEntry rows."
    PRD §3.8: "A manager may also adjust a member's store credit directly, supplying an
    amount_cents (which may be positive to grant or negative to deduct). This appends a
    StoreCreditEntry with reason MANUAL_ADJUSTMENT and a null related_ref, and recomputes
    the member's balance."

    Design: Corner/calculations/manual_adjustment_updates_member_balance
    """
    member = create_member(full_name="Adj")
    grant_store_credit(member["id"], 500)
    fetched = validate_success(api.get_member(member["id"], CLERK), 200)
    assert fetched["store_credit_balance_cents"] == 500


# ─── endpoints section ────────────────────────────────────────────────────
def test_list_store_credit_entries_by_member(api):
    """PRD §2.5: "Several read endpoints expose a resource's dependents by walking a
    foreign key in reverse — for example listing all pre-order pools of a product ...
    all store-credit entries or sales of a member."
    PRD §3.8: "This appends a StoreCreditEntry with reason MANUAL_ADJUSTMENT and a null
    related_ref, and recomputes the member's balance."

    Design: Corner/endpoints/list_store_credit_entries_by_member
    """
    member = create_member(full_name="Sce")
    grant_store_credit(member["id"], 250)
    res = api.list_member_store_credit_entries(member["id"], CLERK)
    data, meta = validate_paginated(res)
    assert any(e["amount_cents"] == 250 and e["reason"] == "MANUAL_ADJUSTMENT" for e in data)
