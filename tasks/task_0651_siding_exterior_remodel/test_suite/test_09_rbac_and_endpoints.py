"""RBAC enforcement and endpoint cross-reference / not-found behavior."""
from test_helpers import (
    api_client as _ac,
    get_success_data, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    bootstrap_actors, create_baselined_project,
)
from test_helpers.factories import create_staff_payload, create_client_payload
from test_helpers.test_users import make_estimator_headers


class TestRbac:
    def test_estimator_cannot_create_project_returns_forbidden(self, api):
        """PRD §2.1: "When the headers are well-formed but the declared role is not
        permitted to invoke the endpoint under the access-control matrix of §4, the
        request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4 endpoint table: `POST /projects` is authorized for ProjectManager only.

        Design: Corner/rbac/estimator_cannot_create_project_returns_forbidden
        """
        est = get_success_data(_ac.register_staff(create_staff_payload(role_code="ESTIMATOR")))
        client = get_success_data(_ac.register_client(create_client_payload()))
        est_h = make_estimator_headers(est["id"])
        resp = _ac.create_project(
            {"client_id": client["id"], "project_manager_id": est["id"],
             "property_address": "123 Cedar"}, est_h)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "When either header is missing or malformed on a protected
        endpoint, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_auth_header_returns_unauthenticated
        """
        resp = _ac.list_projects(headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


class TestEndpointCrossReference:
    def test_list_change_orders_by_target_line_item(self, api):
        """PRD §3.7: "Change orders may be listed (filtered by `project_id`,
        `target_line_item_id`, or `supersedes_change_order_id`) and fetched."

        Design: Corner/endpoints/fk_reverse_list_changeorders_by_target_line_item
        """
        proj, est, line_map, actors = create_baselined_project()
        line_id = line_map["SIDING"]["id"]
        co = get_success_data(_ac.create_change_order(
            {"project_id": proj["id"], "target_line_item_id": line_id, "delta_cents": 20000},
            actors["pm_h"]))
        data, meta = validate_paginated(
            _ac.list_change_orders(actors["pm_h"], params={"target_line_item_id": line_id}))
        assert meta["total_count"] == 1, f"expected exactly 1 change order, got {meta['total_count']}"
        assert data[0]["id"] == co["id"]
        assert data[0]["target_line_item_id"] == line_id

    def test_create_change_order_nonexistent_target_line_returns_not_found(self, api):
        """PRD §2.7: "The same not-found rule applies to foreign keys supplied in a
        request body: if a referenced resource does not exist, the request is rejected
        with `ERR_NOT_FOUND`."

        Design: Corner/endpoints/create_changeorder_nonexistent_target_line_returns_not_found
        """
        proj, est, line_map, actors = create_baselined_project()
        resp = _ac.create_change_order(
            {"project_id": proj["id"],
             "target_line_item_id": "00000000-0000-4000-8000-000000000999",
             "delta_cents": 20000}, actors["pm_h"])
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
