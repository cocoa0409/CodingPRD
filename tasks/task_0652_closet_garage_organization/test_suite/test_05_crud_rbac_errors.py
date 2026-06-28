"""Entity creation/CRUD, RBAC denials, error paths, and consistency.

Corner queue: entities, endpoints (list/pagination/FK-reverse), errors
(finance-already-linked, warranty-branch, warranty-not-covered), rbac,
consistency_model.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    api_client, ApiErrorId, NON_EXISTENT_UUID,
    fixtures as fx, factories as f,
    make_customer_headers, TEST_USERS, build_user_headers,
)
from test_helpers.fixtures import DESIGNER, MFG_OPS, ADMIN, MELAMINE_18_UNITS

SHELF_10 = [{"component_type": "SHELF", "quantity": 10, "unit_price_cents": 5000}]


# ===========================================================================
# Corner — entities
# ===========================================================================
class TestEntityCreationAndConstraints:
    def test_customer_creation_returns_fields_and_west_region(self, api):
        """PRD §2.9: "A first digit of 0, 1, or 2 maps to `NORTH`; 3 or 4 maps to `SOUTH`;
        5 or 6 maps to `EAST`; and 7, 8, or 9 maps to `WEST`."
        PRD §2.4: "The `version` begins at its initial value when the resource is
        created"

        Design: Corner/entities/customer_creation_returns_all_fields_and_region
        """
        resp = api.create_customer(f.create_customer_payload(zip_code="90210"))
        data = validate_success(resp, expected_status=201)
        assert data["install_region"] == "WEST"
        assert data["version"] == 1

    def test_customer_region_south_bucket(self, api):
        """PRD §2.9: "A first digit of 0, 1, or 2 maps to `NORTH`; 3 or 4 maps to `SOUTH`;
        5 or 6 maps to `EAST`; and 7, 8, or 9 maps to `WEST`."

        Design: Corner/entities/customer_region_derivation_south_bucket
        """
        data = validate_success(
            api.create_customer(f.create_customer_payload(zip_code="30301")),
            expected_status=201,
        )
        assert data["install_region"] == "SOUTH"

    def test_get_nonexistent_project_returns_404(self, api):
        """PRD §2.6: "The first identifier in the path that does not resolve causes the
        request to fail with `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/project_not_found_returns_404
        """
        resp = api.get_project("00000000-0000-0000-0000-000000000000",
                               TEST_USERS["platform_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)

    def test_project_missing_room_type_rejected(self, api):
        """PRD §3.1: "a project is opened by supplying the `customer_id` of the owning
        customer and a `room_type`, which is one of `REACH_IN_CLOSET`, `WALK_IN_CLOSET`,
        `GARAGE`, `PANTRY`, or `HOME_OFFICE`."
        PRD §2.10: "with malformed-body schema validation (`ERR_VALIDATION`) as the final
        family."

        Design: Corner/entities/project_missing_required_room_type
        """
        customer = fx.create_customer(zip_code="90001")
        resp = api.create_project({"customer_id": customer["id"]}, DESIGNER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_project_invalid_room_type_enum_rejected(self, api):
        """PRD §3.1: "a project is opened by supplying the `customer_id` of the owning
        customer and a `room_type`, which is one of `REACH_IN_CLOSET`, `WALK_IN_CLOSET`,
        `GARAGE`, `PANTRY`, or `HOME_OFFICE`."
        PRD §2.10: "with malformed-body schema validation (`ERR_VALIDATION`) as the final
        family."

        Design: Corner/entities/project_invalid_room_type_enum
        """
        customer = fx.create_customer(zip_code="90001")
        resp = api.create_project({"customer_id": customer["id"], "room_type": "BATHROOM"}, DESIGNER)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_project_initial_status_lead_and_system_fields(self, api):
        """PRD §3.1: "A new project starts in status `LEAD`, copies the customer's region
        into its own `install_region`, and begins with `accepted_quote_id` and
        `financing_application_id` both null and `balance_due_cents` at zero."

        Design: Corner/entities/project_initial_status_lead_and_system_fields
        """
        customer = fx.create_customer(zip_code="70001")  # 7 -> WEST
        project = fx.create_project(customer["id"], room_type="PANTRY")
        assert project["status"] == "LEAD"
        assert project["install_region"] == "WEST"
        assert project["version"] == 1

    def test_project_with_nonexistent_customer_fk_404(self, api):
        """PRD §2.6: "The same existence check applies to foreign-key references supplied
        in a request body; path identifiers are validated before body references."

        Design: Corner/entities/project_wrong_customer_fk_not_found
        """
        resp = api.create_project(
            {"customer_id": "11111111-1111-1111-1111-111111111111", "room_type": "GARAGE"},
            DESIGNER,
        )
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)


# ===========================================================================
# Corner — endpoints (list / pagination / FK-reverse)
# ===========================================================================
class TestListEndpoints:
    def test_list_projects_pagination_envelope(self, api):
        """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/list_projects_pagination_envelope
        """
        customer = fx.create_customer(zip_code="90001")
        fx.create_project(customer["id"], room_type="GARAGE")
        fx.create_project(customer["id"], room_type="PANTRY")
        resp = api.list_projects(DESIGNER, params={"customer_id": customer["id"], "limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert len(data) == 1

    def test_deposits_filtered_by_project_fk_reverse(self, api):
        """PRD §3.5: "Deposits can be fetched individually and listed filtered by
        `project_id` or `quote_id`."

        Design: Corner/endpoints/deposits_filtered_list_by_project_fk_reverse
        """
        ctx = fx.setup_accepted_quote(
            zip_code="50000", room_type="GARAGE",
            material_grade="MELAMINE", line_items=MELAMINE_18_UNITS,
        )
        dep = fx.create_deposit(ctx["project"]["id"], ctx["quote"]["id"], 17820)
        resp = api.list_deposits(ADMIN, params={"project_id": ctx["project"]["id"]})
        data, _ = validate_paginated(resp)
        assert len(data) == 1
        assert data[0]["id"] == dep["id"]


# ===========================================================================
# Corner — errors
# ===========================================================================
class TestErrorPaths:
    def test_finance_already_linked_double_fund(self, api):
        """PRD §3.9: "A project may hold only one funded financing application; attempting
        to fund when the project already carries a funded `financing_application_id` is
        rejected with `ERR_FINANCE_ALREADY_LINKED`."

        Design: Corner/errors/finance_already_linked_double_fund
        """
        ctx = fx.setup_deposit_paid(
            zip_code="50000", room_type="GARAGE",
            material_grade="MELAMINE", line_items=MELAMINE_18_UNITS, deposit_amount=17820,
        )
        proj, quote, customer = ctx["project"], ctx["quote"], ctx["customer"]
        # First financing -> funded.
        app1 = fx.create_financing_application(proj["id"], quote["id"], 30000, 24, customer["id"])
        fx.submit_financing_application(app1["id"], customer["id"])
        fx.financing_decide(app1["id"], "APPROVE")
        fx.fund_financing_application(app1["id"])
        # Second financing -> approved, then fund attempt rejected.
        app2 = fx.create_financing_application(proj["id"], quote["id"], 20000, 24, customer["id"])
        fx.submit_financing_application(app2["id"], customer["id"])
        fx.financing_decide(app2["id"], "APPROVE")
        resp = api.fund_financing_application(app2["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_FINANCE_ALREADY_LINKED.value)

    def test_warranty_branch_mismatch_replacement_for_fit(self, api):
        """PRD §3.10: "The **replacement branch** orders a replacement, moving the claim
        from `APPROVED` to `REPLACEMENT_ORDERED`, and is permitted only when the
        `defect_type` is `HARDWARE` or `STRUCTURAL`. Requesting an adjustment for a defect
        that is not `FIT` or `FINISH`, or a replacement for a defect that is not
        `HARDWARE` or `STRUCTURAL`, is rejected with `ERR_WARRANTY_BRANCH_MISMATCH`."

        Design: Corner/errors/warranty_branch_mismatch_replacement_for_fit
        """
        ctx = fx.setup_approved_warranty_claim(defect_type="FIT")
        resp = api.order_replacement_warranty_claim(ctx["claim"]["id"], MFG_OPS)
        validate_error(resp, ApiErrorId.ERR_WARRANTY_BRANCH_MISMATCH.value)

    def test_warranty_not_covered_out_of_window(self, api):
        """PRD §3.10: "Approving a claim moves it from `FILED` to `APPROVED` and requires
        `covered` to be true; approving a claim whose `covered` flag is false is rejected
        with `ERR_WARRANTY_NOT_COVERED`."
        PRD §3.10: "the claim is covered when it is filed within the warranty window of
        365 days of the install's completion **and** the `defect_type` is among the
        covered defects"

        Design: Corner/errors/warranty_not_covered_out_of_window
        """
        # Install DONE at 2026-05-10; file claim at 2027-06-01 (> 365 days) so covered=false.
        ctx = fx.setup_completed_project(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            window_start="2026-05-10T08:00:00Z", window_end="2026-05-10T16:00:00Z",
            install_clock="2026-05-10T08:00:00Z", crew_name="W-nc",
        )
        fx.set_clock("2027-06-01T00:00:00Z")
        claim = get_success_data(api.create_warranty_claim(
            f.create_warranty_claim_payload(ctx["project"]["id"], ctx["install_job"]["id"], "HARDWARE"),
            make_customer_headers(ctx["customer"]["id"]),
        ))
        assert claim["covered"] is False
        resp = api.approve_warranty_claim(claim["id"], MFG_OPS)
        validate_error(resp, ApiErrorId.ERR_WARRANTY_NOT_COVERED.value)


# ===========================================================================
# Corner — RBAC
# ===========================================================================
class TestRbac:
    def test_customer_cannot_issue_quote(self, api):
        """PRD §2.1: "Once a request is authenticated, the platform checks that the acting
        role is permitted to perform the requested operation; if it is not, the request is
        rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/customer_cannot_issue_quote
        """
        ctx = fx.setup_finalized_config_scenario(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="MELAMINE", line_items=SHELF_10,
        )
        quote = fx.add_quote(ctx["project"]["id"], ctx["config"]["id"])
        resp = api.issue_quote(quote["id"], make_customer_headers(ctx["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_non_owner_customer_cannot_accept_quote(self, api):
        """PRD §2.1: "Ownership checks on any resource that ultimately belongs to a project
        compare the project's `customer_id` to `X-User-ID`; if the acting customer does not
        own the target project, the request is rejected with `ERR_NOT_RESOURCE_OWNER`
        (HTTP 403)."

        Design: Corner/rbac/non_owner_customer_cannot_accept_quote
        """
        ctx = fx.setup_issued_quote(
            zip_code="90001", room_type="WALK_IN_CLOSET",
            material_grade="MELAMINE", line_items=SHELF_10,
        )
        other = fx.create_customer(zip_code="90001")
        resp = api.accept_quote(ctx["quote"]["id"], make_customer_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)

    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of the
        recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_auth_headers_unauthenticated
        """
        resp = api.list_projects(build_user_headers("nobody-1", "Nobody"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# Corner — consistency model
# ===========================================================================
class TestConsistencyModel:
    def test_deposit_capture_makes_manufacture_order_immediately_visible(self, api):
        """PRD §3.5: "a new `ManufactureOrder` in status `QUEUED` is created for that
        project and quote; the project's `balance_due_cents` is recomputed; the project
        advances from `QUOTED` to `DEPOSIT_PAID`"

        Design: Corner/consistency_model/deposit_capture_immediate_manufacture_order_visible
        """
        ctx = fx.setup_accepted_quote(
            zip_code="50000", room_type="GARAGE",
            material_grade="MELAMINE", line_items=MELAMINE_18_UNITS,
        )
        proj, quote = ctx["project"], ctx["quote"]
        dep = fx.create_deposit(proj["id"], quote["id"], 17820)
        fx.capture_deposit(dep["id"], quote["version"])
        resp = api.list_manufacture_orders(MFG_OPS, params={"project_id": proj["id"]})
        data, _ = validate_paginated(resp)
        assert len(data) == 1
        assert data[0]["status"] == "QUEUED"
        proj_after = get_success_data(api.get_project(proj["id"], DESIGNER))
        assert proj_after["status"] == "DEPOSIT_PAID"
