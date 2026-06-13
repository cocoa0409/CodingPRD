"""RBAC corners: a ReceivingClerk cannot release a lot, a ProductionOperator cannot
issue a hold, and a request without valid auth headers is rejected.

Queue B — Corner/rbac.
"""
import pytest
from test_helpers import (
    api_client, validate_error,
    setup_facility_supplier_ingredient, receive_lot,
    create_facility, create_supplier, create_ingredient, release_lot,
    create_hold_order_payload, ApiErrorId,
    TEST_USERS,
)

QM = TEST_USERS["quality_manager_headers"]
CLERK = TEST_USERS["receiving_clerk_headers"]
OP = TEST_USERS["production_operator_headers"]


def test_receiving_clerk_cannot_release_lot():
    """PRD 2.1: "When the headers are present but the declared role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/receiving_clerk_cannot_release_lot
    """
    facility, supplier, ingredient = setup_facility_supplier_ingredient(coa_required=False)
    lot = receive_lot(facility["id"], ingredient["id"], "L", supplier_id=supplier["id"],
                      received_qty=5)
    # Lot release is a QualityManager action; a ReceivingClerk is not permitted.
    res = api_client.release_lot(lot["id"], CLERK)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_production_operator_cannot_issue_hold():
    """PRD 2.1: "When the headers are present but the declared role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/production_operator_cannot_issue_hold
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    supplier = create_supplier(facility["id"], coa_required=False)
    ingredient = create_ingredient(facility["id"], storage_target_c=4, shelf_life_days=30)
    lot = receive_lot(facility["id"], ingredient["id"], "L", supplier_id=supplier["id"],
                      received_qty=5)
    # Hold issuance is a QualityManager action; a ProductionOperator is not permitted.
    res = api_client.create_hold_order(
        create_hold_order_payload(facility["id"], lot["id"], "OTHER"), OP)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_missing_auth_header_rejected():
    """PRD 2.1: "If either header is missing or malformed, the request is rejected with
    `ERR_MISSING_AUTH`."

    Design: Corner/rbac/missing_auth_header_rejected
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    # No X-User-ID / X-User-Role headers.
    res = api_client.get_facility(facility["id"], headers={})
    validate_error(res, ApiErrorId.ERR_MISSING_AUTH.value)
