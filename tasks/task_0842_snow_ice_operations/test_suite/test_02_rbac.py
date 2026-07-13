"""Authentication, authorization, and entity-backed resource ownership.

Corner queue: rbac section.
"""
from test_helpers import (
    validate_error, ApiErrorId, TEST_USERS,
    new_operator, setup_started_assignment, setup_recorded_application,
    make_operator_headers,
)

YARD = TEST_USERS["yard_headers"]


def test_operator_cannot_create_storm(api):
    """PRD §2.1: "If both headers are present but the named role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)." PRD §2.1: "A `DispatchSupervisor` orchestrates storms — declaring,
    activating, closing, and finalizing them".

    Design: Corner/rbac/operator_cannot_create_storm
    """
    op = new_operator()
    resp = api.create_storm_event(
        {"name": "S", "severity": "LIGHT", "forecast_start_at": "2026-02-10T00:00:00Z",
         "forecast_end_at": "2026-02-11T00:00:00Z"},
        make_operator_headers(op["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_yardmanager_cannot_void_application(api):
    """PRD §2.1: "If both headers are present but the named role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)." PRD §3.6: "A recorded application may be voided by a
    `DispatchSupervisor`."

    Design: Corner/rbac/yardmanager_cannot_void_application
    """
    scene = setup_recorded_application(salt_tons=5.0)
    resp = api.void_application(scene["application"]["id"], YARD)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_operator_cannot_record_on_foreign_assignment(api):
    """PRD §2.1: "when an operator records a material application or an AVL ping against
    an assignment, the acting `X-User-ID` must equal that assignment's `operator_id`".
    PRD §2.1: "If an entity-backed operator acts on a resource it does not own, the
    request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/operator_cannot_record_on_foreign_assignment
    """
    scene = setup_started_assignment(planned_material_tons=5.0)  # owned by scene['operator'] (A)
    op_b = new_operator(full_name="Op B", badge_number="B3")
    resp = api.create_application(scene["assignment"]["id"],
                                  {"depot_id": scene["depot"]["id"], "material_type": "SALT",
                                   "salt_tons": 1.0, "lane_miles_treated": 2.0, "pavement_temp_f": 15},
                                  make_operator_headers(op_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)


def test_create_route_without_auth_headers_rejected(api):
    """PRD §2.1: "Every request must carry two headers identifying the caller: `X-User-ID`
    and `X-User-Role`. If either header is absent, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing."

    Design: Corner/rbac/create_route_missing_auth_header
    """
    resp = api.create_route({"name": "Main St", "tier": "ARTERIAL", "lane_miles": 2.0,
                             "zone": "Z1"}, {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
