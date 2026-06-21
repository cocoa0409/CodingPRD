"""Resource creation, not-found, RBAC role/ownership denial, authentication, and
list pagination.

All instances here are queue B (corner) coverage.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    setup_activated_loan,
    create_merchant,
    create_borrower,
    create_application,
    assert_merchant,
    make_servicer_headers,
    make_borrower_headers,
    make_merchant_headers,
    build_user_headers,
    create_merchant_payload,
    create_application_payload,
    create_payment_payload,
    decision_payload,
)

SERVICER = make_servicer_headers()


def test_create_merchant_minimal_fields_returns_201(api):
    """PRD §3.1: "A newly registered merchant starts with status ACTIVE, and its computed
    gross_financed_cents and net_settled_cents both begin at zero."
    PRD §3.1: "it must be at least 0 and at most 30, and when omitted it defaults to 2."

    Design: Corner/entities/create_merchant_minimal_fields_returns_201
    """
    resp = api.create_merchant(
        create_merchant_payload(display_name="Acme", mdr_bps=500), SERVICER)
    data = validate_success(resp, 201)
    assert_merchant(data)
    assert data["status"] == "ACTIVE"
    assert data["gross_financed_cents"] == 0
    assert data["net_settled_cents"] == 0
    assert data["settlement_hold_days"] == 2, "omitted settlement_hold_days defaults to 2"
    assert data["version"] == 1


def test_get_nonexistent_loan_returns_not_found(api):
    """PRD §2.8: "every identifier in the path and every foreign-key identifier in the
    body must resolve to an existing resource, validated left-to-right, with the first
    unresolved identifier yielding ERR_NOT_FOUND."

    Design: Corner/entities/get_loan_nonexistent_id_returns_not_found
    """
    resp = api.get_loan(NON_EXISTENT_UUID, SERVICER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_merchant_cannot_submit_application(api):
    """PRD §2.1: "A request whose role is syntactically valid but is not permitted to
    perform the requested operation — or where an ownership-bound actor targets a
    resource it does not own — is rejected with ERR_FORBIDDEN."

    Design: Corner/rbac/merchant_cannot_submit_application
    """
    merchant = create_merchant(mdr_bps=600)
    borrower = create_borrower(email="ba@x.com")
    payload = create_application_payload(borrower["id"], merchant["id"],
                                         cart_amount_cents=100_000, plan_type="PAY_IN_4",
                                         requested_down_payment_cents=0)
    resp = api.create_application(payload, make_merchant_headers(merchant["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_borrower_cannot_decide_own_application(api):
    """PRD §2.1: "A request whose role is syntactically valid but is not permitted to
    perform the requested operation — or where an ownership-bound actor targets a
    resource it does not own — is rejected with ERR_FORBIDDEN."

    Design: Corner/rbac/borrower_cannot_decide_own_application
    """
    merchant = create_merchant(mdr_bps=600)
    borrower = create_borrower(email="ba@x.com")
    application = create_application(borrower["id"], merchant["id"],
                                    cart_amount_cents=100_000, plan_type="PAY_IN_4",
                                    requested_down_payment_cents=0)
    resp = api.decide_application(application["id"], decision_payload("APPROVE"),
                                  make_borrower_headers(borrower["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_borrower_cannot_pay_another_borrowers_loan(api):
    """PRD §2.1: "ownership checks on any resource that references a Borrower compare that
    resource's borrower foreign key to X-User-ID. A borrower may read and act only on its
    own borrower record, applications, loans, installments, payments, and autopay
    mandates."

    Design: Corner/rbac/borrower_cannot_pay_another_borrowers_loan
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                               clock_iso="2026-01-01T00:00:00Z")
    other_borrower = create_borrower(email="be@x.com", full_name="BE")

    resp = api.create_payment(
        create_payment_payload(ctx["loan"]["id"], 25_000, source="MANUAL"),
        make_borrower_headers(other_borrower["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "A request whose X-User-Role is missing or is not one of these three
    declared roles is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    # No X-User-Role header at all.
    resp = api.get_loan(NON_EXISTENT_UUID, headers={"X-User-ID": "anon",
                                                    "Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_list_loans_filtered_by_borrower_with_pagination(api):
    """PRD §3.5: "Loans are readable by the servicer, owning borrower, and merchant, and
    may be listed and filtered by borrower_id, merchant_id, or application_id."
    PRD §2.3: "total_count reflects the full filtered set before the page window is
    applied and has_more indicates whether further items remain beyond the current page."

    Design: Corner/endpoints/list_loans_filtered_by_borrower_pagination
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                               clock_iso="2026-01-01T00:00:00Z")
    borrower_id = ctx["borrower"]["id"]
    resp = api.list_loans(make_borrower_headers(borrower_id),
                          params={"borrower_id": borrower_id, "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert any(loan["id"] == ctx["loan"]["id"] for loan in data)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
