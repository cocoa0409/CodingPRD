"""Auth headers, role authorization, ownership, and shared read access (§2.1)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_customer,
    create_formula,
    create_raw_material,
    make_brandrep_headers,
    make_catalog,
    place_order,
    run_batch,
    schedule_order,
    validate_error,
    validate_success,
)
from test_helpers import WINDOW_DAY1

PLANNER = TEST_USERS["production_planner_headers"]
OPERATOR = TEST_USERS["production_operator_headers"]
CHEMIST = TEST_USERS["qa_chemist_headers"]
QA = TEST_USERS["qa_manager_headers"]
BRAND_REP = TEST_USERS["brand_rep_headers"]


class TestAuthHeaders:
    def test_missing_user_context_headers_rejected_400(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the capacity in
        which they act." and "A request missing either header, or carrying a role
        outside this declared set, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        resp = api.get_customer(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        assert resp.status_code == 400, (
            "header presence is checked before any existence or business rule"
        )


class TestForbiddenRoles:
    def test_brandrep_cannot_create_raw_material(self, api):
        """PRD §2.1: "A request whose role is not authorized for the targeted
        operation is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §3.2: "Raw materials are registered by a `ProductionPlanner` with a
        non-empty `name` and an `allergen_class` from the same ten-value
        enumeration used on formulas."

        Design: Corner/rbac/brandrep_cannot_create_raw_material
        """
        customer = create_customer("Acme")
        resp = api.create_raw_material(
            {"name": "VitC", "allergen_class": "NONE"},
            make_brandrep_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert resp.status_code == 403

    def test_operator_cannot_release_batch(self, api):
        """PRD §2.1: "A request whose role is not authorized for the targeted
        operation is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §2.9: "When several checks could reject the same request, the system
        evaluates them in a fixed priority order so that the surfaced error is
        deterministic" — role authorization (item 2) precedes the target resource's
        state precondition (item 6).

        Design: Corner/rbac/operator_cannot_release_batch
        """
        ctx = make_catalog()
        mo = place_order(ctx["customer"]["id"], ctx["formula"]["id"], 10000)
        batch = schedule_order(mo["id"], ctx["line"]["id"],
                               WINDOW_DAY1[0], WINDOW_DAY1[1])

        resp = api.release_batch(batch["id"], {}, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert resp.status_code == 403

    def test_chemist_cannot_approve_formula(self, api):
        """PRD §2.1: "A request whose role is not authorized for the targeted
        operation is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §3.1: "Approval is the sole preserve of the `QAManager` and is the
        moment a formula becomes manufacturable."

        Design: Corner/rbac/chemist_cannot_approve_formula
        """
        customer = create_customer("Acme")
        material = create_raw_material("VitC", "NONE")
        formula = create_formula(customer["id"], material["id"])

        resp = api.approve_formula(formula["id"], {}, CHEMIST)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert resp.status_code == 403


class TestSharedReads:
    def test_all_roles_can_read_batch(self, api):
        """PRD §2.1: "All read operations (every GET endpoint) accept any of the
        five declared roles."

        Design: Corner/rbac/all_roles_can_read_batch
        """
        ctx = make_catalog()
        run = run_batch(ctx, window=WINDOW_DAY1, stage="SCHEDULED")
        batch_id = run["batch"]["id"]

        resp = api.get_batch(batch_id, make_brandrep_headers(ctx["customer"]["id"]))
        data = validate_success(resp, 200)
        assert data["id"] == batch_id

        for headers in (PLANNER, OPERATOR, CHEMIST, QA):
            ok = api.get_batch(batch_id, headers)
            assert ok.status_code == 200, (
                f"GET endpoints accept every declared role, failed for {headers}"
            )
