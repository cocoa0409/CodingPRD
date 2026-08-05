"""Invoice approval / payment (separation of duties), plus creation, defaults,
not-found, listing, computed reads, and role-based access control."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    setup_active_contract, setup_service, setup_approved_invoice,
    new_vendor, new_contract, new_invoice, review,
    create_vendor_payload, create_contract_payload,
    make_finance_approver_headers, TEST_USERS, ANONYMOUS_HEADERS,
)

_SOURCING = TEST_USERS["sourcing_headers"]
_ANALYST = TEST_USERS["analyst_headers"]
_ADMIN = TEST_USERS["system_admin_headers"]


# ---------------------------------------------------------------------------
# Corner: state_machines / pay_before_approve_returns_invoice_not_approved
# ---------------------------------------------------------------------------

def test_pay_before_approve_returns_invoice_not_approved(api):
    """PRD §3.7: "Paying an invoice is allowed only from APPROVED (otherwise
    ERR_INVOICE_NOT_APPROVED)"

    Design: Corner/state_machines/pay_before_approve_returns_invoice_not_approved
    """
    base = setup_active_contract(api)
    invoice = new_invoice(api, base["contract"]["id"])
    review(api, invoice["id"])  # UNDER_REVIEW, not APPROVED
    resp = api.pay_invoice(invoice["id"], make_finance_approver_headers("fa_1"))
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_APPROVED.value)


# ---------------------------------------------------------------------------
# Corner: state_machines / pay_by_same_approver_returns_segregation_of_duties
# ---------------------------------------------------------------------------

def test_pay_by_same_approver_returns_segregation_of_duties(api):
    """PRD §3.7: "the paying FinanceApprover's X-User-ID must differ from the approved_by_user_id
    recorded at approval. If the same person who approved the invoice attempts to pay it, the
    request is rejected with ERR_SEGREGATION_OF_DUTIES."

    Design: Corner/state_machines/pay_by_same_approver_returns_segregation_of_duties
    """
    base = setup_approved_invoice(api, approver_user_id="fa_1")
    resp = api.pay_invoice(base["invoice"]["id"], make_finance_approver_headers("fa_1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# ---------------------------------------------------------------------------
# Corner: state_machines / pay_by_different_approver_succeeds
# ---------------------------------------------------------------------------

def test_pay_by_different_approver_succeeds(api):
    """PRD §3.7: "A successful payment moves the invoice to PAID, sets its balance_due_cents to 0,
    and increments its version."

    Approved by fa_1; paid by a different FinanceApprover fa_2.

    Design: Corner/state_machines/pay_by_different_approver_succeeds
    """
    base = setup_approved_invoice(api, approver_user_id="fa_1")
    invoice = validate_success(api.pay_invoice(base["invoice"]["id"], make_finance_approver_headers("fa_2")))
    assert invoice["status"] == "PAID", f"invoice should be PAID, got {invoice['status']}"
    assert invoice["balance_due_cents"] == 0, f"balance_due_cents should be 0, got {invoice['balance_due_cents']}"


# ---------------------------------------------------------------------------
# Corner: entities / create_vendor_returns_201_with_fields
# ---------------------------------------------------------------------------

def test_create_vendor_returns_201_with_fields(api):
    """PRD §3.1: "A new vendor opens in ACTIVE status."
    PRD §2.4: "an integer version that begins at 1 and increments by exactly one on every mutation
    of that resource."

    Design: Corner/entities/create_vendor_returns_201_with_fields
    """
    vendor = validate_success(api.create_vendor(
        create_vendor_payload(name="Zed Telecom", vendor_type="TELECOM"), _SOURCING), 201)
    assert vendor["status"] == "ACTIVE", f"status should default ACTIVE, got {vendor['status']}"
    assert vendor["version"] == 1, f"version should be 1, got {vendor['version']}"


# ---------------------------------------------------------------------------
# Corner: entities / get_nonexistent_vendor_returns_not_found
# ---------------------------------------------------------------------------

def test_get_nonexistent_vendor_returns_not_found(api):
    """PRD §2.8: "the leftmost identifier is resolved first, and if it names no existing resource
    the request fails with that resource's not-found error before any deeper segment or body field
    is examined."

    Design: Corner/entities/get_nonexistent_vendor_returns_not_found
    """
    resp = api.get_vendor(NON_EXISTENT_UUID, _SOURCING)
    validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Corner: entities / create_service_missing_unit_rate_returns_validation
# ---------------------------------------------------------------------------

def test_create_service_missing_unit_rate_returns_validation(api):
    """PRD §2.9: "Payload validation — required body fields present, enum values legal, numeric
    amounts non-negative, and any weight_pct within 0 to 100 inclusive, else ERR_VALIDATION (422)."
    PRD §3.2: "unit_rate_cents is the contracted monthly rate per unit or seat"

    Design: Corner/entities/create_service_missing_unit_rate_returns_validation
    """
    vendor = new_vendor(api, vendor_type="SAAS")
    contract = new_contract(api, vendor["id"])
    payload = {"contract_id": contract["id"], "service_type": "SAAS_SUBSCRIPTION",
               "license_type": "PER_SEAT", "contracted_quantity": 60}  # no unit_rate_cents
    resp = api.create_service(payload, _SOURCING)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ---------------------------------------------------------------------------
# Corner: entities / create_contract_default_renewal_term_months
# ---------------------------------------------------------------------------

def test_create_contract_default_renewal_term_months(api):
    """PRD §3.1: "renewal_term_months, the number of months the term is extended on each renewal
    (defaulting to 12)"

    Design: Corner/entities/create_contract_default_renewal_term_months
    """
    vendor = new_vendor(api)
    contract = validate_success(api.create_contract(
        create_contract_payload(vendor["id"]), _SOURCING), 201)
    assert contract["renewal_term_months"] == 12, \
        f"renewal_term_months should default to 12, got {contract['renewal_term_months']}"


# ---------------------------------------------------------------------------
# Corner: entities / create_vendor_invalid_type_returns_validation
# ---------------------------------------------------------------------------

def test_create_vendor_invalid_type_returns_validation(api):
    """PRD §3.1: "its vendor_type, which must be either TELECOM or SAAS."
    PRD §2.9: "Payload validation — required body fields present, enum values legal, numeric
    amounts non-negative, and any weight_pct within 0 to 100 inclusive, else ERR_VALIDATION (422)."

    Design: Corner/entities/create_vendor_invalid_type_returns_validation
    """
    resp = api.create_vendor(create_vendor_payload(name="Zed", vendor_type="PHONE"), _SOURCING)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ---------------------------------------------------------------------------
# Corner: endpoints / list_services_by_contract_returns_child
# ---------------------------------------------------------------------------

def test_list_services_by_contract_returns_child(api):
    """PRD §2.8: "Several endpoints address a resource through a nested path (for example, the
    disputes belonging to a particular line item, or the services belonging to a particular
    contract)."
    PRD §2.3: "List results are always ordered by created_at ascending (oldest first)."

    Design: Corner/endpoints/list_services_by_contract_returns_child
    """
    base = setup_service(api)
    data, meta = validate_paginated(api.list_contract_services(base["contract"]["id"], _SOURCING))
    assert data[0]["id"] == base["service"]["id"], "listed service id should match the created service"
    assert "total_count" in meta and "has_more" in meta, "meta must carry total_count and has_more"


# ---------------------------------------------------------------------------
# Corner: endpoints / savings_summary_reports_committed_cost
# ---------------------------------------------------------------------------

def test_savings_summary_reports_committed_cost(api):
    """PRD §3.1: "It returns the contract_id together with total_projected_savings_cents (the sum
    of the projected_savings_cents across the contract's recommendations), total_realized_savings_cents
    (the sum of realized_savings_cents across implemented recommendations), the contract's
    total_recovered_cents, and its current monthly_committed_cost_cents."
    PRD §3.2: "That committed cost is the sum, across all services of the contract whose status is
    either ACTIVE or RIGHTSIZED, of each service's unit_rate_cents multiplied by its
    contracted_quantity."

    One 2000x60 service, no recommendations, no credits -> committed 120000, recovered 0.

    Design: Corner/endpoints/savings_summary_reports_committed_cost
    """
    base = setup_service(api, service_overrides={"unit_rate_cents": 2000, "contracted_quantity": 60,
                                                 "active_quantity": 42})
    summary = validate_success(api.get_savings_summary(base["contract"]["id"], make_finance_approver_headers("fa_1")))
    assert summary["monthly_committed_cost_cents"] == 120000, \
        f"committed should be 120000, got {summary['monthly_committed_cost_cents']}"
    assert summary["total_recovered_cents"] == 0, f"recovered should be 0, got {summary['total_recovered_cents']}"


# ---------------------------------------------------------------------------
# Corner: RBAC / analyst_cannot_approve_invoice_returns_unauthorized
# ---------------------------------------------------------------------------

def test_analyst_cannot_approve_invoice_returns_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to perform
    the requested operation, the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Approve is a FinanceApprover-exclusive operation; an Analyst is rejected.

    Design: Corner/RBAC/analyst_cannot_approve_invoice_returns_unauthorized
    """
    base = setup_active_contract(api)
    invoice = new_invoice(api, base["contract"]["id"])
    review(api, invoice["id"])
    resp = api.approve_invoice(invoice["id"], _ANALYST)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ---------------------------------------------------------------------------
# Corner: RBAC / create_vendor_missing_auth_returns_unauthenticated
# ---------------------------------------------------------------------------

def test_create_vendor_missing_auth_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting an X-User-Role that is not one of
    the six known roles, is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/RBAC/create_vendor_missing_auth_returns_unauthenticated
    """
    resp = api.create_vendor(create_vendor_payload(name="Zed", vendor_type="SAAS"), ANONYMOUS_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
