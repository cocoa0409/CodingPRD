"""Role-based access control: authentication, authorization, and account
ownership.

Covers the corner rbac instances.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_yard, make_contractor_headers,
    setup_returned_pending_inspection,
    create_rate_card_payload, TEST_USERS,
)

YM = TEST_USERS["yard_manager_headers"]
AGENT = TEST_USERS["rental_agent_headers"]


def test_contractor_cannot_create_rate_card(api):
    """PRD §2.1: "When a request carries valid headers but the role is not
    permitted to perform the requested operation per the role matrix in Section 4,
    the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/contractor_cannot_create_rate_card_unauthorized
    """
    acct = validate_success(api.create_contractor_account(
        {"company_name": "Acme", "credit_limit_cents": 1_000_000}, YM), 201)
    res = api.create_rate_card(
        create_rate_card_payload(), make_contractor_headers(acct["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")


def test_contractor_cannot_act_on_other_account(api):
    """PRD §2.1: "when a Contractor creates a reservation, cancels a reservation,
    reads their own account, or pays down a balance, the targeted reservation or
    account must belong to them — its contractor_account_id must equal X-User-ID. A
    mismatch is rejected with ERR_NOT_ACCOUNT_OWNER (HTTP 403)."

    Design: Corner/rbac/contractor_cannot_act_on_other_account_reservation
    """
    ctx = setup_yard()
    acct_a = ctx["account"]
    acct_b = validate_success(api.create_contractor_account(
        {"company_name": "Beta B", "credit_limit_cents": 1_000_000}, YM), 201)
    res = api.create_reservation({
        "contractor_account_id": acct_a["id"],
        "catalog_item_id": ctx["item"]["id"],
        "equipment_unit_id": ctx["unit"]["id"],
        "fulfillment_method": "PICKUP",
        "rental_start_date": "2026-06-01",
        "rental_end_date": "2026-06-10",
        "damage_waiver_opted": False,
    }, make_contractor_headers(acct_b["id"]))
    validate_error(res, "ERR_NOT_ACCOUNT_OWNER")


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "A write request missing or malformed in either header is rejected
    with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_401
    """
    res = api.create_rate_card(create_rate_card_payload(), {})
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_rental_agent_cannot_run_return_inspection(api):
    """PRD §2.1: "When a request carries valid headers but the role is not
    permitted to perform the requested operation per the role matrix in Section 4,
    the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/rental_agent_cannot_run_return_inspection_unauthorized
    """
    ctx = setup_returned_pending_inspection(reservation_overrides={
        "rental_start_date": "2026-06-01", "rental_end_date": "2026-06-10"})
    res = api.create_return_inspection({
        "rental_agreement_id": ctx["agreement"]["id"],
        "return_fuel_level_liters": 40,
        "cleanliness": "CLEAN",
        "damage_assessed_cents": 0,
    }, AGENT)
    validate_error(res, "ERR_UNAUTHORIZED")
