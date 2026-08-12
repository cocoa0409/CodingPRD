"""Authentication, role authorization, brand segregation, and segregation of duties."""
from test_helpers import (
    ApiErrorId,
    assert_batch,
    create_active_formula,
    create_component,
    create_component_payload,
    create_customer,
    create_formula,
    create_order,
    ipc_passed_batch_ctx,
    make_customer_rep_headers,
    make_qa_manager_headers,
    release_batch,
    open_review,
    submit_formula,
    claim_review,
    validate_error,
    validate_success,
)


class TestAuthentication:
    def test_missing_auth_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request with missing headers, or whose role is not one of
        these six, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        resp = api.list_customers(headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestRoleAuthorization:
    def test_customer_rep_cannot_create_components(self, api):
        """PRD §2.1: "A request whose role is authenticated but not listed among
        the endpoint's permitted roles is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."
        PRD §4: POST /cosmfg/components is authorized for ProductionPlanner only.

        Design: Corner/rbac/customer_rep_cannot_create_components
        """
        customer = create_customer()
        resp = api.create_component(
            create_component_payload(name="Water", kind="RAW_MATERIAL",
                                     supply_mode="MANUFACTURER_SUPPLIED",
                                     standard_cost_per_kg_cents=1000),
            make_customer_rep_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_qa_cannot_approve_review(self, api, qa_manager_headers, regulatory_affairs_headers):
        """PRD §2.1: "A request whose role is authenticated but not listed among
        the endpoint's permitted roles is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."
        PRD §4: POST /cosmfg/reviews/{id}/approve is authorized for
        RegulatoryAffairs only.

        Design: Corner/rbac/qa_cannot_approve_review
        """
        customer = create_customer()
        component = create_component()
        formula = create_formula(customer["id"], component_id=component["id"])
        submit_formula(formula["id"])
        review = open_review(formula["id"], "INCI_LIST")
        claim_review(review["id"])

        resp = api.approve_review(review["id"], qa_manager_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

        fetched = validate_success(api.get_review(review["id"], regulatory_affairs_headers), 200)
        assert fetched["status"] == "UNDER_REVIEW", "failed approve must not mutate the review"


class TestBrandSegregation:
    def test_customer_rep_cannot_read_other_customers_order(self, api):
        """PRD §2.10: "any attempt to access a resource whose `customer_id`
        belongs to a different brand is rejected with
        `ERR_CONFIDENTIALITY_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/customer_rep_cannot_read_other_customers_order
        """
        customer_a = create_customer(name="Brand A")
        customer_b = create_customer(name="Brand B")
        component = create_component()
        formula = create_active_formula(customer_a["id"], component_id=component["id"],
                                        confidentiality="EXCLUSIVE")
        order = create_order(customer_a["id"], formula["id"], 1000)

        resp = api.get_order(order["id"], make_customer_rep_headers(customer_b["id"]))
        validate_error(resp, ApiErrorId.ERR_CONFIDENTIALITY_VIOLATION, 403)


class TestSegregationOfDuties:
    def test_segregation_of_duties_release_same_user_rejected(self, api):
        """PRD §3.6: "A `QAManager` releases an `IPC_PASSED` batch, subject to two
        gates evaluated in this order: segregation of duties — the releasing
        user's identity must differ from the batch's
        `last_ipc_recorded_by_user_id`, failing with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 403) — and study clearance — no stability study of the order's
        formula may stand `COMPLETED_FAIL`, failing with
        `ERR_STUDY_FAILED_BLOCKS_RELEASE` (HTTP 409)."

        Design: Corner/rbac/segregation_of_duties_release_same_user_rejected
        """
        ctx = ipc_passed_batch_ctx()
        batch_id = ctx["batch"]["id"]

        resp = api.release_batch(batch_id, make_qa_manager_headers("qa-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        released = release_batch(batch_id, make_qa_manager_headers("qa-2"))
        assert_batch(released)
        assert released["status"] == "RELEASED_TO_FILLING"
