"""District provisioning and ParentAccount lifecycle.

PRD §3.1 covers district creation (seeds usda_reimbursement_total_cents
and top_up_outstanding_cents at zero), ParentAccount creation (email
unique within district, initial prepaid_balance_cents=0), and parent
top-up (appends a TOP_UP ledger entry).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_district,
    assert_parent_account,
    create_district,
    create_district_payload,
    create_parent_account,
    create_parent_account_payload,
    make_parent_headers,
    setup_district_with_family,
    top_up_parent_account,
    top_up_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.1 District creation
# ===========================================================================
class TestDistrictCreation:
    """PRD §3.1: An AuditOfficer provisions a district with name and
    school_year_start; seeds the totals at zero."""

    def test_create_district_seeds_totals_at_zero(self, api, audit_headers):
        """PRD §3.1: "the system seeds both usda_reimbursement_total_cents
        and top_up_outstanding_cents at zero."

        Claim: after POST /districts, both computed totals are 0.
        """
        res = api.create_district(
            create_district_payload(name="Springfield USD"),
            audit_headers,
        )
        district = validate_success(res, 201)
        assert_district(district)
        assert district["usda_reimbursement_total_cents"] == 0, (
            f"expected zero seed, got "
            f"{district['usda_reimbursement_total_cents']}"
        )
        assert district["top_up_outstanding_cents"] == 0, (
            f"expected zero seed, got {district['top_up_outstanding_cents']}"
        )

    def test_create_and_get_district(self, api, audit_headers):
        """PRD §3.1 + §4: POST creates a district; GET retrieves it.

        Claim: after POST /districts, GET /districts/{id} returns the
        same resource.
        """
        created = create_district(name="Lincoln District")
        res = api.get_district(created["id"], audit_headers)
        retrieved = validate_success(res, 200)
        assert retrieved["id"] == created["id"]
        assert retrieved["name"] == "Lincoln District"

    def test_district_carries_common_fields(self, api):
        """PRD §2.4: "Every primary, top-level resource ... carries a
        standard set of system-managed fields: id, created_at,
        updated_at, version."

        Claim: District response carries all four common fields with
        valid types.
        """
        district = create_district()
        assert "id" in district
        assert "created_at" in district
        assert "updated_at" in district
        assert "version" in district
        assert isinstance(district["version"], int)
        assert district["version"] >= 1


# ===========================================================================
# §3.1 ParentAccount creation and email uniqueness
# ===========================================================================
class TestParentAccountCreation:
    """PRD §3.1: ParentAccount with parent_email unique within District;
    starts with prepaid_balance_cents=0."""

    def test_parent_account_initial_balance_zero(self, api):
        """PRD §3.1: "A newly-created ParentAccount starts with
        prepaid_balance_cents of zero."

        Claim: POST /parent-accounts → prepaid_balance_cents == 0.
        """
        district = create_district()
        parent = create_parent_account(district=district)
        assert_parent_account(parent)
        assert parent["prepaid_balance_cents"] == 0, (
            f"expected initial balance 0, got "
            f"{parent['prepaid_balance_cents']}"
        )

    def test_duplicate_email_within_district_rejected(
        self, api, audit_headers,
    ):
        """PRD §3.1: "The email must be unique within the district; a
        second account submitted with an email already present on
        another ParentAccount in the same district is rejected with
        ERR_PARENT_EMAIL_TAKEN."

        Claim: a second POST /parent-accounts with the same email in
        the same district → ERR_PARENT_EMAIL_TAKEN.
        """
        district = create_district()
        email = "shared-parent@example.test"
        first = create_parent_account(district=district, parent_email=email)
        assert first["parent_email"] == email
        # Second account with same email in same district.
        res = api.create_parent_account(
            district["id"],
            create_parent_account_payload(parent_email=email),
            audit_headers,
        )
        validate_error(res, "ERR_PARENT_EMAIL_TAKEN")

    def test_same_email_in_different_districts_permitted(
        self, api, audit_headers,
    ):
        """PRD §3.1: "The email must be unique within the district".

        Claim: the same email is permitted in two different districts
        (uniqueness is scoped per-district, not global).
        """
        district_a = create_district(name="District A")
        district_b = create_district(name="District B")
        email = "shared-parent@example.test"
        parent_a = create_parent_account(
            district=district_a, parent_email=email,
        )
        # Same email in a different district should succeed.
        res = api.create_parent_account(
            district_b["id"],
            create_parent_account_payload(parent_email=email),
            audit_headers,
        )
        parent_b = validate_success(res, 201)
        assert parent_a["id"] != parent_b["id"]
        assert parent_a["parent_email"] == parent_b["parent_email"] == email


# ===========================================================================
# §3.1 Top-up
# ===========================================================================
class TestParentTopUp:
    """PRD §3.1: A top-up request carries an amount_cents (positive
    integer); the server appends a PaidLedgerEntry of type TOP_UP."""

    def test_top_up_adds_balance(self, api):
        """PRD §3.1: "the server appends a PaidLedgerEntry of type
        TOP_UP with that amount and reports the updated balance back."

        Claim: POST /top-up by 500 cents on a zero-balance account →
        balance becomes 500.
        """
        district, parent, _ = setup_district_with_family()
        assert parent["prepaid_balance_cents"] == 0
        updated = top_up_parent_account(
            district=district, parent_account=parent,
            amount_cents=500,
        )
        assert updated["prepaid_balance_cents"] == 500, (
            f"expected balance 500 after top-up, got "
            f"{updated['prepaid_balance_cents']}"
        )

    def test_two_top_ups_sum_balance(self, api):
        """PRD §3.6 parent_balance_waterfall: "a TOP_UP adds its
        amount_cents".

        Claim: two top-ups of 500 + 300 cents → balance 800.
        """
        district, parent, _ = setup_district_with_family()
        top_up_parent_account(
            district=district, parent_account=parent, amount_cents=500,
        )
        final = top_up_parent_account(
            district=district, parent_account=parent, amount_cents=300,
        )
        assert final["prepaid_balance_cents"] == 800, (
            f"expected 500+300=800, got {final['prepaid_balance_cents']}"
        )

    def test_top_up_requires_parent_ownership(self, api):
        """PRD §2.1: "any ownership check on a Student, FrlApplication,
        AllergyProfileEntry, or top-up/refund operation compares the
        resource's parent_account_id (directly, or via the student's
        parent_account_id) to the header value."

        Claim: a different Parent (whose X-User-ID is not this account's
        id) attempting to top-up → ERR_FORBIDDEN.
        """
        district, parent_a, _ = setup_district_with_family()
        district2, parent_b, _ = setup_district_with_family()
        # Parent B tries to top-up Parent A's account. The URL points to
        # district A; we need Parent B's headers paired with an existing
        # parent account id in district A. We use parent_b's id (which
        # is a valid Parent X-User-ID, but does not own parent_a).
        # Note: the path is in district A, so we also need parent_a's id
        # in the URL.
        res = api.top_up_parent_account(
            district["id"], parent_a["id"],
            top_up_payload(amount_cents=100),
            make_parent_headers(parent_b["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN")
