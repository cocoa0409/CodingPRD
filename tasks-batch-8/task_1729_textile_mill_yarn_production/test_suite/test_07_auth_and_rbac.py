"""Authentication and role isolation across the six operational roles."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_component,
    create_blend_recipe_payload,
    create_draft_recipe,
    create_fiber_lot,
    create_fiber_lot_payload,
    create_yarn_lot_payload,
    get_success_data,
    setup_approved_recipe,
    validate_error,
)

PLANNER = TEST_USERS["mill_planner_headers"]
OPERATOR = TEST_USERS["dye_house_operator_headers"]
INSPECTOR = TEST_USERS["quality_inspector_headers"]
REP = TEST_USERS["customer_service_rep_headers"]
ADMIN = TEST_USERS["mill_admin_headers"]


class TestAuthentication:
    def test_missing_role_header_unauthenticated(self, api):
        """PRD §2.1: "A request whose `X-User-Role` header is missing or does not map to one of these declared roles is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        # No X-User-Role header at all.
        resp = api.list_fiber_lots({"X-User-ID": "test-op-1"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

        # A role string that maps to none of the six declared roles.
        resp = api.list_fiber_lots(
            {"X-User-ID": "test-op-1", "X-User-Role": "NotARole"}
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestAuthorization:
    def test_forbidden_role_on_fiber_lot_create(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted to invoke the target endpoint is rejected with `ERR_FORBIDDEN`."
        PRD §4: POST /mill/fiber-lots is authorized for MillPlanner only.

        Design: Corner/validations/forbidden_role_on_fiber_lot_create
        """
        resp = api.create_fiber_lot(
            create_fiber_lot_payload(
                fiber_type="COTTON", received_weight_lbs=100.0, unit_cost_per_lb=1.5
            ),
            REP,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_dye_house_operator_cannot_approve_recipe(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted to invoke the target endpoint is rejected with `ERR_FORBIDDEN`."
        PRD §4: POST /mill/blend-recipes/{id}/approve is authorized for MillPlanner only.

        Design: Corner/rbac/dye_house_operator_cannot_approve_recipe
        """
        lot = create_fiber_lot(received_weight_lbs=500.0, unit_cost_per_lb=1.5)
        recipe = create_draft_recipe(target_yarn_count_ne=20.0)
        add_component(recipe["id"], lot["id"], 100.0)

        resp = api.approve_blend_recipe(
            recipe["id"], {"expected_recipe_version": recipe["version"]}, OPERATOR
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_quality_inspector_cannot_create_yarn_lot(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted to invoke the target endpoint is rejected with `ERR_FORBIDDEN`."
        PRD §4: POST /mill/yarn-lots is authorized for SpinningSupervisor only.

        Design: Corner/rbac/quality_inspector_cannot_create_yarn_lot
        """
        base = setup_approved_recipe(component_weight_lbs=100.0)
        resp = api.create_yarn_lot(
            create_yarn_lot_payload(
                base["recipe"]["id"],
                spun_weight_lbs=100.0,
                actual_yarn_count_ne=20.0,
            ),
            INSPECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_mill_admin_cannot_create_fiber_lot(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted to invoke the target endpoint is rejected with `ERR_FORBIDDEN`."
        PRD §4: POST /mill/fiber-lots is authorized for MillPlanner only.

        Design: Corner/rbac/mill_admin_cannot_create_fiber_lot
        """
        resp = api.create_fiber_lot(
            create_fiber_lot_payload(
                fiber_type="COTTON", received_weight_lbs=100.0, unit_cost_per_lb=1.5
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
