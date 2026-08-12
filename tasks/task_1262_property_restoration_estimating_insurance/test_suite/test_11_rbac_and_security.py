"""Role-based access control, customer ownership, and segregation of duties.

Covers the endpoint role lists, customer-ownership 404 semantics, the missing
authentication context check, and the invoice-void segregation-of-duties rule
with its issued-void compensation cascade.
"""
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID, ApiErrorId,
    make_carrier, make_customer, make_policy, make_claim, make_claim_ctx,
    setup_draft_estimate, setup_submitted_estimate,
    setup_invoiced_claim, read_claim, read_estimate, list_claim_payments,
    find_payment, create_estimate_payload, create_payment_payload,
    make_customer_headers, make_contractor_admin_headers, TEST_USERS,
)

ADMIN = TEST_USERS["contractor_admin_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]

_ROOF_ENTRY = ({"category_code": "RFR-1", "trade": "ROOFING", "kind": "LABOR",
                "unit": "SF", "unit_price_cents": 200,
                "default_depreciation_pct": 0.20},)


def test_missing_auth_header_returns_401(api):
    """PRD §2.1: "If either header is missing, or the role value is not one of the
    declared roles, the request is rejected with `ERR_MISSING_AUTH_HEADER`
    (HTTP 401)."

    Design: Corner/validations/missing_auth_header_returns_401
    """
    # this call deliberately omits both X-User-ID and X-User-Role
    res = api.get_claim(NON_EXISTENT_UUID, headers={})
    validate_error(res, ApiErrorId.ERR_MISSING_AUTH_HEADER)


def test_adjuster_cannot_create_estimate(api):
    """PRD §2.1: "If the caller's role is not in the endpoint's authorized role
    list, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: `POST /v1/claims/{id}/estimates` is authorized for `Estimator` only.

    Design: Corner/rbac/adjuster_cannot_create_estimate
    """
    ctx = make_claim_ctx(cause_of_loss="WATER",
                         carrier_overrides={"name": "Acme Mutual", "tax_rate": 0.07},
                         policy_overrides={"coverage_a_limit_cents": 100000000,
                                           "flat_deductible_cents": 100000})
    res = api.create_estimate(ctx["claim"]["id"],
                              create_estimate_payload(ctx["claim"]["version"]),
                              ADJUSTER)
    validate_error(res, ApiErrorId.ERR_ROLE_NOT_PERMITTED)


def test_estimator_cannot_approve_estimate(api):
    """PRD §2.1: "If the caller's role is not in the endpoint's authorized role
    list, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: `POST /v1/estimates/{id}/approve` is authorized for `Adjuster` only.

    Design: Corner/rbac/estimator_cannot_approve_estimate
    """
    ctx = setup_submitted_estimate(cause_of_loss="FIRE", line_specs=[(0, 100)])
    res = api.approve_estimate(ctx["estimate"]["id"], ESTIMATOR)
    validate_error(res, ApiErrorId.ERR_ROLE_NOT_PERMITTED)
    assert read_estimate(ctx["estimate"]["id"])["status"] == "SUBMITTED"


def test_customer_cannot_read_anothers_claim_returns_404(api):
    """PRD §2.1: "A `Customer` caller touching a claim-scoped resource whose owning
    claim's `customer_id` does not equal `X-User-ID` receives
    `ERR_RESOURCE_NOT_FOUND` (HTTP 404) — the resource is treated as non-existent
    rather than forbidden."

    Design: Corner/rbac/customer_cannot_read_anothers_claim_returns_404
    """
    carrier = make_carrier(name="Acme Mutual", tax_rate=0.07)
    ann = make_customer(full_name="Ann A", email="ann@example.com")
    bob = make_customer(full_name="Bob B", email="bob@example.com")
    policy = make_policy(ann["id"], carrier["id"], policy_number="POL-A",
                         coverage_a_limit_cents=100000000, deductible_type="FLAT",
                         flat_deductible_cents=100000,
                         recoverable_depreciation=True)
    claim = make_claim(policy["id"], cause_of_loss="WATER",
                       date_of_loss="2026-03-10T00:00:00Z")
    res = api.get_claim(claim["id"], make_customer_headers(bob["id"]))
    validate_error(res, ApiErrorId.ERR_RESOURCE_NOT_FOUND)
    ok = validate_success(
        api.get_claim(claim["id"], make_customer_headers(ann["id"])), 200)
    assert ok["id"] == claim["id"]


def test_sod_invoice_void_by_issuer_returns_403_other_admin_succeeds(api):
    """PRD §3.9: "Voiding an invoice is the compensation path and carries a
    segregation-of-duties rule at priority 2: the caller's `X-User-ID` must differ
    from the invoice's `created_by_user_id`, else `ERR_SOD_VIOLATION` (HTTP 403)."
    PRD §3.9: "Voiding an `ISSUED` invoice compensates fully: any auto-created
    `DEPRECIATION_RECOVERY` payment still in `REQUESTED` is moved to `VOIDED` (a
    system transition that applies only to auto-created payments), the claim
    returns `INVOICED → COMPLETE` with its `version` incremented, its
    `outstanding_balance_cents` reset to zero, and `payment_posture` recomputed —
    leaving the claim ready for a corrected invoice to be created."

    Design: Corner/rbac/sod_invoice_void_by_issuer_returns_403_other_admin_succeeds
    """
    # invoice 200,000 issued by admin-A; recovery payment 40,000 REQUESTED
    ctx = setup_invoiced_claim(
        cause_of_loss="WIND", carrier_overrides={"name": "ZeroTax Mutual",
                                                 "tax_rate": 0},
        policy_overrides={"coverage_a_limit_cents": 5000000,
                          "deductible_type": "FLAT", "flat_deductible_cents": 10000,
                          "recoverable_depreciation": True},
        entry_specs=_ROOF_ENTRY, line_specs=[(0, 1000)],
        direct_pay=True, clear_advance=True, issue=True,
        admin_user_id="admin-A")
    claim_id = ctx["claim"]["id"]
    invoice_id = ctx["invoice"]["id"]
    # the issuer cannot void their own invoice
    res = api.void_invoice(invoice_id, make_contractor_admin_headers("admin-A"))
    validate_error(res, ApiErrorId.ERR_SOD_VIOLATION)
    # a different ContractorAdmin passes the SoD check
    voided = validate_success(
        api.void_invoice(invoice_id, make_contractor_admin_headers("admin-B")), 200)
    assert voided["status"] == "VOIDED"
    recovery = find_payment(claim_id, "DEPRECIATION_RECOVERY")
    assert recovery["status"] == "VOIDED", \
        "compensation: the REQUESTED recovery auto-payment was voided"
    assert read_claim(claim_id)["status"] == "COMPLETE", \
        "claim reverts so a corrected invoice can be issued"
    assert read_claim(claim_id)["outstanding_balance_cents"] == 0


def test_adjuster_cannot_record_payments(api):
    """PRD §2.1: "If the caller's role is not in the endpoint's authorized role
    list, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §3.9: "a `Customer` records `DEDUCTIBLE` payments against their own claim;
    a `ContractorAdmin` records `CUSTOMER_BALANCE` payments."

    Design: Corner/rbac/adjuster_cannot_record_payments
    """
    ctx = make_claim_ctx(cause_of_loss="WATER",
                         carrier_overrides={"name": "Acme Mutual", "tax_rate": 0.07},
                         policy_overrides={"coverage_a_limit_cents": 100000000,
                                           "flat_deductible_cents": 100000})
    # role check fires before the payable-state check (INTAKE claim)
    res = api.create_payment(ctx["claim"]["id"],
                             create_payment_payload("DEDUCTIBLE", 1000), ADJUSTER)
    validate_error(res, ApiErrorId.ERR_ROLE_NOT_PERMITTED)
