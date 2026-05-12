"""Budget Account creation and Supplier onboarding (PRD §3.1)."""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_budget_account,
    assert_supplier,
    create_budget_account_payload,
    create_supplier_payload,
    create_qualified_supplier,
    create_provisional_supplier,
    validate_error,
    validate_success,
)


# ===========================================================================
# BudgetAccount creation (PRD §3.1)
# ===========================================================================
class TestBudgetAccountCreate:
    def test_create_budget_account_returns_active_zeroed(
        self, api, finance_headers
    ):
        """PRD §3.1: "The account is created in ACTIVE status, with
        committed_amount_cents and spent_amount_cents both initialized
        to 0".

        Claim: a freshly created budget account has status=ACTIVE and
        both ledger counters zeroed.
        """
        payload = create_budget_account_payload(total_amount_cents=5_000_000)
        created = validate_success(
            api.create_budget_account(payload, finance_headers), 201
        )
        assert_budget_account(created)
        assert created["status"] == "ACTIVE"
        assert created["committed_amount_cents"] == 0
        assert created["spent_amount_cents"] == 0
        assert created["total_amount_cents"] == 5_000_000

    @pytest.mark.parametrize("bad_code", [
        "BA-26-IT-CAPEX",          # year too short
        "ba-2026-IT-CAPEX",         # lowercase prefix
        "BA-2026-it-CAPEX",         # lowercase letter group
        "BA-2026_IT_CAPEX",         # wrong separator
        "BA-2026-IT",               # missing trailing group
        "BA-2026-IT-CAPEX-X",       # extra segment
    ])
    def test_invalid_budget_code_pattern_rejected(
        self, api, finance_headers, bad_code
    ):
        """PRD §3.1: "supplying a code that follows the strict pattern of
        the literal prefix BA-, four digits, a hyphen, an uppercase letter
        group, another hyphen, and a final uppercase letter group".

        Claim: codes that do not match the BA-NNNN-LETTERS-LETTERS pattern
        produce ERR_VALIDATION.
        """
        payload = create_budget_account_payload(code=bad_code)
        res = api.create_budget_account(payload, finance_headers)
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    def test_duplicate_budget_code_rejected(self, api, finance_headers):
        """PRD §3.1: "the same code may not appear on two accounts".

        Claim: a second create with the same code produces ERR_VALIDATION.
        """
        payload = create_budget_account_payload()
        validate_success(api.create_budget_account(payload, finance_headers), 201)
        # Second create with identical code (other fields differing where allowed).
        again = create_budget_account_payload(code=payload["code"])
        res = api.create_budget_account(again, finance_headers)
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    def test_negative_total_amount_rejected(self, api, finance_headers):
        """PRD §3.1: "a total_amount_cents that must be at least zero".

        Claim: negative total_amount_cents is rejected with ERR_VALIDATION.
        """
        payload = create_budget_account_payload(total_amount_cents=-1)
        res = api.create_budget_account(payload, finance_headers)
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    def test_zero_total_amount_accepted(self, api, finance_headers):
        """PRD §3.1: "a total_amount_cents that must be at least zero".

        Claim: zero total_amount_cents is accepted (the boundary value).
        """
        payload = create_budget_account_payload(total_amount_cents=0)
        created = validate_success(
            api.create_budget_account(payload, finance_headers), 201
        )
        assert created["total_amount_cents"] == 0


# ===========================================================================
# Supplier onboarding (PRD §3.1)
# ===========================================================================
class TestSupplierOnboarding:
    def test_create_supplier_starts_provisional(self, api, buyer_headers):
        """PRD §3.1: "The supplier is created with qualification_status set
        to PROVISIONAL, and its rating_avg initialized to 0."

        Claim: a freshly registered supplier has qualification_status =
        PROVISIONAL and rating_avg = 0.
        """
        payload = create_supplier_payload()
        created = validate_success(api.create_supplier(payload, buyer_headers), 201)
        assert_supplier(created)
        assert created["qualification_status"] == "PROVISIONAL"
        assert created["rating_avg"] == 0 or created["rating_avg"] == 0.0

    def test_qualify_supplier_promotes_to_qualified(
        self, api, buyer_headers, legal_headers
    ):
        """PRD §3.1: "A LegalApprover later promotes the supplier to
        QUALIFIED after due diligence".

        Claim: POST /suppliers/{id}/qualify by a LegalApprover sets
        qualification_status = QUALIFIED.
        """
        created = create_provisional_supplier()
        promoted = validate_success(
            api.qualify_supplier(created["id"], legal_headers), 200
        )
        assert promoted["qualification_status"] == "QUALIFIED"

    def test_duplicate_legal_name_rejected(self, api, buyer_headers):
        """PRD §3.1: "with its legal_name (unique)".

        Claim: registering two suppliers with the same legal_name produces
        ERR_VALIDATION on the second.
        """
        first = create_supplier_payload()
        validate_success(api.create_supplier(first, buyer_headers), 201)
        dup = create_supplier_payload(legal_name=first["legal_name"])
        res = api.create_supplier(dup, buyer_headers)
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    def test_duplicate_tax_id_rejected(self, api, buyer_headers):
        """PRD §3.1: "tax_id (unique)".

        Claim: registering two suppliers with the same tax_id produces
        ERR_VALIDATION on the second.
        """
        first = create_supplier_payload()
        validate_success(api.create_supplier(first, buyer_headers), 201)
        dup = create_supplier_payload(tax_id=first["tax_id"])
        res = api.create_supplier(dup, buyer_headers)
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    def test_supplier_role_identity_is_entity_backed(
        self, api, buyer_headers
    ):
        """PRD §2.1: "When X-User-Role is Supplier, X-User-ID is the id of
        the acting Supplier entity; ownership checks on any resource that
        references a Supplier (notably an invoice referencing supplier_id,
        or a contract whose purchase_order_id resolves to a PO with a
        particular supplier_id) compare the resource's foreign-key field
        to X-User-ID."

        Claim: a Supplier-role caller whose X-User-ID equals an existing
        Supplier.id passes the role-recognition check; getting a missing
        invoice yields ERR_NOT_FOUND (not ERR_FORBIDDEN), confirming the
        Supplier identity resolved.
        """
        from test_helpers import make_supplier_headers, NON_EXISTENT_UUID
        s = create_qualified_supplier()
        headers = make_supplier_headers(s["id"])
        res = api.get_invoice(NON_EXISTENT_UUID, headers)
        # Path existence is priority 3, before RBAC (priority 4); the
        # Supplier identity already resolved at priority 2.
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)
