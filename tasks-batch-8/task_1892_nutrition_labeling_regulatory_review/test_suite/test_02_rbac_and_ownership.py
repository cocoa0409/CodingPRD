"""Role-based access control: exclusive operations, entity-backed ownership,
and segregation of duties on label approval."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_client,
    create_ingredient,
    create_ingredient_payload,
    create_nutrient_panel_payload,
    create_product,
    create_product_payload,
    create_recipe,
    lock_recipe,
    make_client_rep_headers,
    make_label_analyst_headers,
    make_regulatory_reviewer_headers,
    setup_wafer_workspace,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["label_analyst_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]


class TestExclusiveOperations:
    def test_clientrep_cannot_approve(self, api):
        """PRD §2.1: "Each operation in this document names the roles
        authorized to invoke it; a caller whose role is not authorized, or
        whose entity-backed identity does not own the resource chain being
        touched, is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §4: "Approve a label in review; approver must differ from the
        preparer | RegulatoryReviewer"

        Design: Corner/rbac/rbac_clientrep_cannot_approve
        """
        ws = setup_wafer_workspace(submit=True)
        resp = api.approve_label(ws["label"]["id"], ws["client_rep_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)
        label = validate_success(api.get_label_version(ws["label"]["id"], ADMIN))
        assert label["review_status"] == "IN_REVIEW", (
            "the rejected approval must not move the label"
        )

    def test_analyst_cannot_release(self, api):
        """PRD §2.1: "Each operation in this document names the roles
        authorized to invoke it; a caller whose role is not authorized, or
        whose entity-backed identity does not own the resource chain being
        touched, is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §4: "Release an approved label; supersedes the prior release for
        the product and market | QualityManager"

        Design: Corner/rbac/rbac_analyst_cannot_release
        """
        ws = setup_wafer_workspace(submit=True)
        approve = validate_success(api.approve_label(
            ws["label"]["id"], make_regulatory_reviewer_headers("reviewer-1")))
        assert approve["review_status"] == "APPROVED"
        product = validate_success(api.get_product(ws["product"]["id"], ADMIN))
        resp = api.release_label(
            ws["label"]["id"],
            {"expected_product_version": product["version"]},
            make_label_analyst_headers("analyst-1"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)

    def test_auditor_cannot_create_ingredients(self, api):
        """PRD §2.1: "Each operation in this document names the roles
        authorized to invoke it; a caller whose role is not authorized, or
        whose entity-backed identity does not own the resource chain being
        touched, is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §4: "Create an ingredient with its database nutrient profile |
        ClientRep"

        Design: Corner/rbac/rbac_auditor_cannot_create_ingredients
        """
        client = create_client()
        resp = api.create_ingredient(
            client["id"], create_ingredient_payload(name="Wafers"), AUDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)

    def test_platformadmin_cannot_compute_panels(self, api):
        """PRD §2.1: "Each operation in this document names the roles
        authorized to invoke it; a caller whose role is not authorized, or
        whose entity-backed identity does not own the resource chain being
        touched, is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §4: "Compute a nutrient panel (DATABASE or LAB) for a LOCKED
        recipe | LabelAnalyst"

        Design: Corner/rbac/rbac_platformadmin_cannot_compute_panels
        """
        client = create_client()
        product = create_product(client)
        wafer = create_ingredient(client, name="Wafers")
        recipe = create_recipe(product["id"], client["id"],
                               [{"ingredient_id": wafer["id"], "quantity_g": 100}])
        lock_recipe(recipe["id"], client["id"])
        resp = api.create_nutrient_panel(
            recipe["id"], create_nutrient_panel_payload(method="DATABASE"), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)


class TestEntityBackedOwnership:
    def test_clientrep_cross_client_forbidden(self, api):
        """PRD §2.1: "When `X-User-Role` is `ClientRep`, `X-User-ID` is the
        `id` of the acting `Client`; ownership checks on any resource that
        belongs to a client compare the resource's client chain to `X-User-ID`,
        and a client representative may only register products, ingredients,
        recipes, and lab submissions for their own client."
        PRD §2.1: "Each operation in this document names the roles authorized
        to invoke it; a caller whose role is not authorized, or whose
        entity-backed identity does not own the resource chain being touched,
        is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/rbac/rbac_clientrep_cross_client_forbidden
        """
        client_a = create_client(name="Acme A")
        client_b = create_client(name="Beta B")
        resp = api.create_product(
            client_b["id"],
            create_product_payload(name="Cookie", include_household=False),
            make_client_rep_headers(client_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)


class TestSegregationOfDuties:
    def test_segregation_of_duties_enforced(self, api):
        """PRD §2.1: "One further auth rule is wired to a single workflow:
        segregation of duties requires that the reviewer who approves a label
        be a different person than the analyst who prepared it, so the
        approving request's `X-User-ID` must differ from the label's
        `prepared_by`, failing which the approval is rejected with
        `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."
        PRD §3.6: "Approval stamps `approved_by`, moves `review_status` to
        `APPROVED`, and increments `version`."

        Design: Corner/rbac/rbac_segregation_of_duties_enforced
        """
        ws = setup_wafer_workspace(submit=True)
        assert ws["label"]["prepared_by"] == "analyst-1"

        resp = api.approve_label(
            ws["label"]["id"], make_regulatory_reviewer_headers("analyst-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION,
                       expected_status=403)

        approved = validate_success(
            api.approve_label(ws["label"]["id"],
                              make_regulatory_reviewer_headers("reviewer-1")),
            200,
        )
        assert approved["review_status"] == "APPROVED"
        assert approved["approved_by"] == "reviewer-1"
