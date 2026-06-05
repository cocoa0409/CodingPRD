"""Configuration / CRUD: creation, retrieval, not-found, required fields, types,
defaults, system fields, foreign-key resolution, and filtered listing.
"""
import pytest

from test_helpers import (
    api_client,
    assert_seller,
    assert_transaction,
    make_seller_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.constants import CA_JURISDICTION, NONEXISTENT_UUID_V4
from test_helpers.factories import (
    create_line_item_payload,
    create_seller_payload,
    create_tax_jurisdiction_payload,
    create_transaction_payload,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]


def test_create_tax_jurisdiction_returns_201_with_combined_rate(api):
    """PRD §3.1: "On creation the system computes `combined_rate` as the sum of `state_rate` and `local_rate`."
    PRD §2.4: "`version` is an integer that begins at its initial value and increases by exactly one on every mutation of the resource".

    Design: Corner/entities/create_tax_jurisdiction_returns_201_with_combined_rate
    """
    res = api.create_tax_jurisdiction(create_tax_jurisdiction_payload(**CA_JURISDICTION), ADMIN)
    jur = validate_success(res, 201)
    assert jur["combined_rate"] == 0.0825, f"expected combined_rate 0.0825, got {jur['combined_rate']}"
    assert jur["version"] == 1, f"expected version 1, got {jur['version']}"


def test_get_seller_by_id_returns_stored_entity(api):
    """PRD §3.1: "A new seller's `status` begins `ACTIVE`."

    Design: Corner/entities/get_seller_by_id_returns_stored_entity
    """
    created = validate_success(
        api.create_seller(create_seller_payload(legal_name="Acme", origin_state_code="CA"), ADMIN), 201)
    res = api.get_seller(created["id"], ADMIN)
    seller = validate_success(res, 200)
    assert_seller(seller)
    assert seller["status"] == "ACTIVE", f"expected ACTIVE, got {seller['status']}"
    assert seller["legal_name"] == "Acme", f"expected legal_name Acme, got {seller['legal_name']}"


def test_get_transaction_nonexistent_returns_not_found(api):
    """PRD §2.9: "then existence of any path-referenced resource (`ERR_NOT_FOUND`)".

    Design: Corner/entities/get_transaction_nonexistent_returns_not_found
    """
    res = api.get_transaction(NONEXISTENT_UUID_V4, ADMIN)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_tax_jurisdiction_missing_required_field_returns_invalid_request(api):
    """PRD §2.9: "then well-formedness of the request body including required fields, types, enum membership, and numeric bounds (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/create_tax_jurisdiction_missing_required_field_returns_invalid_request
    """
    payload = {
        "state_code": "CA",
        "sourcing_rule": "DESTINATION",
        "economic_nexus_sales_threshold": 100000.00,
    }  # state_rate omitted (required)
    res = api.create_tax_jurisdiction(payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_jurisdiction_invalid_enum_sourcing_rule_returns_invalid_request(api):
    """PRD §3.1: "its `sourcing_rule` of either `ORIGIN` or `DESTINATION`, and its `state_rate`."
    PRD §2.9: "then well-formedness of the request body including required fields, types, enum membership, and numeric bounds (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/create_jurisdiction_invalid_enum_sourcing_rule_returns_invalid_request
    """
    payload = create_tax_jurisdiction_payload(sourcing_rule="HYBRID")
    res = api.create_tax_jurisdiction(payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_transaction_default_customer_exempt_requested_false(api):
    """PRD §3.3: "an optional `customer_exempt_requested` flag that defaults to false."

    Design: Corner/entities/line_item_default_customer_exempt_requested_false
    """
    jur, seller = fx.setup_ca_seller(with_category=False)
    payload = create_transaction_payload(seller["id"], jur["id"], customer_ref="b1")
    res = api.create_transaction(payload, make_seller_headers(seller["id"]))
    txn = validate_success(res, 201)
    assert txn["customer_exempt_requested"] is False, \
        f"expected default false, got {txn['customer_exempt_requested']}"


def test_transaction_system_fields_generated_on_create(api):
    """PRD §3.3: "A new transaction's `settlement_status` is `PENDING` and its `audit_status` is `UNREVIEWED`; its `tax_return_id` is null."
    PRD §2.4: "`version` is an integer that begins at its initial value".

    Design: Corner/entities/transaction_system_fields_generated_on_create
    """
    jur, seller = fx.setup_ca_seller(with_category=False)
    payload = create_transaction_payload(seller["id"], jur["id"], customer_ref="b1",
                                         customer_exempt_requested=False)
    res = api.create_transaction(payload, make_seller_headers(seller["id"]))
    txn = validate_success(res, 201)
    assert_transaction(txn)
    assert txn["settlement_status"] == "PENDING", f"got {txn['settlement_status']}"
    assert txn["audit_status"] == "UNREVIEWED", f"got {txn['audit_status']}"
    assert txn["version"] == 1, f"expected version 1, got {txn['version']}"


def test_create_transaction_with_unknown_jurisdiction_returns_reference_not_found(api):
    """PRD §2.9: "then existence of any body-referenced foreign key such as `jurisdiction_id`, `facilitator_id`, `transaction_id`, `tax_return_id`, or `seller_id` (`ERR_REFERENCE_NOT_FOUND`)".

    Design: Corner/entities/create_transaction_with_unknown_jurisdiction_returns_reference_not_found
    """
    seller = fx.create_seller(origin_state_code="CA")
    payload = create_transaction_payload(seller["id"], NONEXISTENT_UUID_V4,
                                         customer_ref="b1", customer_exempt_requested=False)
    res = api.create_transaction(payload, make_seller_headers(seller["id"]))
    validate_error(res, "ERR_REFERENCE_NOT_FOUND", expected_status=404)


def test_list_transactions_filtered_by_seller_id_reverse_reachability(api):
    """PRD §2.3: "Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_transactions_filtered_by_seller_id_reverse_reachability
    """
    jur, seller = fx.setup_ca_seller(with_category=False)
    txn = fx.create_pending_transaction(seller["id"], jur["id"], customer_ref="b1",
                                        customer_exempt_requested=False)
    res = api.list_transactions(make_seller_headers(seller["id"]),
                                params={"seller_id": seller["id"]})
    data, meta = validate_paginated(res)
    assert any(t["id"] == txn["id"] for t in data), "created transaction must be in the filtered list"
    for t in data:
        assert t["seller_id"] == seller["id"], \
            f"every element must have seller_id {seller['id']}, got {t['seller_id']}"


def test_list_line_items_filtered_by_transaction_id_reverse_reachability(api):
    """PRD §2.3: "Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_line_items_filtered_by_transaction_id_reverse_reachability
    """
    jur, seller = fx.setup_ca_seller(with_category=True)
    txn = fx.create_pending_transaction(seller["id"], jur["id"], customer_ref="b1",
                                        customer_exempt_requested=False)
    line = fx.add_line_item(seller["id"], txn["id"], "TANGIBLE", quantity=2, unit_price=5.00)
    res = api.list_line_items(make_seller_headers(seller["id"]),
                              params={"transaction_id": txn["id"]})
    data, meta = validate_paginated(res)
    assert any(li["id"] == line["id"] for li in data), "created line item must be in the filtered list"
    for li in data:
        assert li["transaction_id"] == txn["id"], \
            f"every element must have transaction_id {txn['id']}, got {li['transaction_id']}"
