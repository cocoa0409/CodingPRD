"""Role authorization and BrandCustomerRep ownership scoping (PRD §2.1)."""
from test_helpers import (
    ApiErrorId,
    fixtures,
    make_brand_customer_rep_headers,
    validate_error,
    validate_paginated,
)
from test_helpers import api_client as client
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["plant_admin_headers"]
PP = TEST_USERS["production_planner_headers"]


class TestRoleDenial:
    def test_planner_cannot_create_ingredient(self, api):
        """PRD §2.1: "A request whose role is not on the addressed endpoint's
        authorized-role list is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)."

        Design: Corner/rbac/c_planner_cannot_create_ingredient
        """
        resp = client.create_ingredient({"name": "X", "category": "FAT"}, PP)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

    def test_rep_cannot_approve_revision(self, api):
        """PRD §2.1: "A request whose role is not on the addressed endpoint's
        authorized-role list is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)."
        PRD §2.1: "A `QualityManager` holds quality authority: lot release and
        rejection, nutrition verification, revision approval and reject-back,
        pre-run verification, retain-sample registration, changeover
        validation and failure, lot-release decisions, and claim-review
        adjudication."

        Design: Corner/rbac/c_rep_cannot_approve_revision
        """
        ns = fixtures.setup_formula_with_revision(march_to="CLAIM_REVIEW")
        rep_headers = make_brand_customer_rep_headers(ns.cust["id"])
        resp = client.approve_revision(ns.r1["id"], rep_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)


class TestCustomerRepScope:
    def test_rep_reads_scoped_to_own_customer(self, api):
        """PRD §2.1: "On in-scope list endpoints the caller must pass
        `customer_id` equal to its own identifier; for the production-run
        listing, ownership resolves through the agreement each run belongs to."
        PRD §2.1: "Any access by a `BrandCustomerRep` to a resource owned by a
        different brand customer — or an in-scope listing without that
        self-scoping — is rejected with `ERR_FORBIDDEN_CUSTOMER_SCOPE`
        (HTTP 403)."

        Design: Corner/rbac/c_rep_scoped_reads
        """
        c1 = fixtures.create_customer("C1", "c1@x.com")
        c2 = fixtures.create_customer("C2", "c2@x.com")
        f2 = fixtures.create_formula(c2["id"], "F2", bar_weight_g=60)

        rep_c1 = make_brand_customer_rep_headers(c1["id"])
        own_list, meta = validate_paginated(
            client.list_formulas(rep_c1, params={"customer_id": c1["id"]})
        )
        assert own_list == []
        assert meta["total_count"] == 0

        other_read = client.get_formula(f2["id"], rep_c1)
        validate_error(other_read, ApiErrorId.ERR_FORBIDDEN_CUSTOMER_SCOPE, 403)
