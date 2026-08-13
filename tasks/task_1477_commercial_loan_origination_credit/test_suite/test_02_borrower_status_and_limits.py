"""Borrower status rules and the single-borrower cap (PRD section 3.1),
including the cross-entity gate of application creation on borrower status.
"""
from test_helpers import (
    ApiErrorId, api_client, create_borrower, loan_application_payload, setup_officers,
    validate_error, validate_paginated, validate_success,
)


def test_create_succeeds_active_then_rejected_after_exited():
    """PRD section 3.1: "the borrower's `status` must be `ACTIVE` (otherwise
    `ERR_BORROWER_NOT_ACTIVE`)". PRD section 3.1: a RelationshipManager "may move
    `status` between `ACTIVE` and `EXITED` in either direction".

    Design: Difficulty/cross_entity_state_dependency/application_creation_blocked_by_borrower_status
    """
    o = setup_officers(["rm"])
    bor = create_borrower(o, legal_name="Departing Client Co", relationship_since="2019-06-01")
    assert bor["status"] == "ACTIVE"

    app1 = validate_success(api_client.create_loan_application(
        loan_application_payload(bor["id"], product_type="EQUIPMENT",
                                 requested_amount_cents=5_000_000, term_months=36),
        o["rm"]["headers"]), 201)
    assert app1["status"] == "INTAKE"

    bor_after = validate_success(api_client.update_borrower(
        bor["id"], {"status": "EXITED"}, o["rm"]["headers"]), 200)
    assert bor_after["status"] == "EXITED"

    rejected = api_client.create_loan_application(
        loan_application_payload(bor["id"], product_type="EQUIPMENT",
                                 requested_amount_cents=5_000_000, term_months=36),
        o["rm"]["headers"])
    validate_error(rejected, ApiErrorId.ERR_BORROWER_NOT_ACTIVE)


def test_rejected_create_leaves_no_application_and_reactivation_restores():
    """PRD section 3.1: "the borrower's `status` must be `ACTIVE` (otherwise
    `ERR_BORROWER_NOT_ACTIVE`)" and a borrower's applications "can be listed
    through the borrower" (section 3.1). PRD section 3.1: the manager "may move
    `status` between `ACTIVE` and `EXITED` in either direction".

    Design: Difficulty/cross_entity_state_dependency/application_creation_blocked_by_borrower_status
    """
    o = setup_officers(["rm"])
    bor = create_borrower(o, legal_name="Departing Client Co", relationship_since="2019-06-01")
    app1 = validate_success(api_client.create_loan_application(
        loan_application_payload(bor["id"], product_type="EQUIPMENT",
                                 requested_amount_cents=5_000_000, term_months=36),
        o["rm"]["headers"]), 201)
    validate_success(api_client.update_borrower(bor["id"], {"status": "EXITED"}, o["rm"]["headers"]), 200)

    validate_error(api_client.create_loan_application(
        loan_application_payload(bor["id"], product_type="EQUIPMENT",
                                 requested_amount_cents=5_000_000, term_months=36),
        o["rm"]["headers"]), ApiErrorId.ERR_BORROWER_NOT_ACTIVE)

    apps, meta = validate_paginated(api_client.list_borrower_applications(bor["id"], o["rm"]["headers"]))
    assert [a["id"] for a in apps] == [app1["id"]], "rejected create must leave no row"

    # Reactivation (EXITED -> ACTIVE) restores the front door.
    validate_success(api_client.update_borrower(bor["id"], {"status": "ACTIVE"}, o["rm"]["headers"]), 200)
    app2 = validate_success(api_client.create_loan_application(
        loan_application_payload(bor["id"], product_type="EQUIPMENT",
                                 requested_amount_cents=5_000_000, term_months=36),
        o["rm"]["headers"]), 201)
    assert app2["status"] == "INTAKE"


def test_borrower_status_patch_restricted():
    """PRD section 3.1: a RelationshipManager "may move `status` between `ACTIVE`
    and `EXITED` in either direction — but `SUSPENDED` is never settable through
    an update (an attempt is rejected with `ERR_VALIDATION`), because suspension
    is system-driven".

    Design: Corner/validations/borrower_status_patch_restricted
    """
    o = setup_officers(["rm"])
    bor = create_borrower(o, legal_name="Departing Client Co", relationship_since="2019-06-01")

    r1 = api_client.update_borrower(bor["id"], {"status": "SUSPENDED"}, o["rm"]["headers"])
    validate_error(r1, ApiErrorId.ERR_VALIDATION)

    r2 = api_client.update_borrower(bor["id"], {"status": "EXITED"}, o["rm"]["headers"])
    data = validate_success(r2, 200)
    assert data["status"] == "EXITED"


def test_single_borrower_cap_boundary():
    """PRD section 3.1: "the borrower's `total_exposure_cents` plus the new
    `requested_amount_cents` must not exceed $50,000,000.00 (5,000,000,000 cents)
    — the bank's single-borrower cap — otherwise the request is refused with
    `ERR_SINGLE_BORROWER_LIMIT` (HTTP 402)."

    Design: Corner/validations/single_borrower_cap_boundary
    """
    o = setup_officers(["rm"])
    bor = create_borrower(o, legal_name="Whale Co", naics_code="531120",
                          relationship_since="2010-01-01")

    at_cap = api_client.create_loan_application(
        loan_application_payload(bor["id"], requested_amount_cents=5_000_000_000,
                                 term_months=120), o["rm"]["headers"])
    app1 = validate_success(at_cap, 201)
    assert app1["status"] == "INTAKE"

    over_cap = api_client.create_loan_application(
        loan_application_payload(bor["id"], requested_amount_cents=5_000_000_001,
                                 term_months=120), o["rm"]["headers"])
    validate_error(over_cap, ApiErrorId.ERR_SINGLE_BORROWER_LIMIT)

    apps, meta = validate_paginated(api_client.list_borrower_applications(bor["id"], o["rm"]["headers"]))
    assert meta["total_count"] == 1
    assert apps[0]["id"] == app1["id"]
