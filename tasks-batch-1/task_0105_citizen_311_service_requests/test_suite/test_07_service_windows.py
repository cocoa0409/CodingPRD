"""Maintenance and blackout service-window overlap and scope validation.

Queue A (Difficulty): MAINTENANCE closed-interval touching endpoints collide, and
BLACKOUT half-open touching endpoints are allowed. Queue B (Corner): the
MAINTENANCE-with-jurisdiction scope-invalid rejection.
"""
from test_helpers import (
    validate_success,
    validate_error,
    fixtures as fx,
    factories as fac,
    TEST_USERS,
)
from test_helpers.api_errors import ApiErrorId

ADMIN = TEST_USERS["system_admin_headers"]


# ---------------------------------------------------------------------------
# Queue A — Difficulty: MAINTENANCE closed-interval touching collides
# ---------------------------------------------------------------------------
def test_maintenance_touching_endpoint_collides(api):
    """PRD §3.8: "For two maintenance windows on the same department, the test treats
    both intervals as closed: they collide when the first starts at or before the
    second ends and the second starts at or before the first ends — touching endpoints
    therefore do collide. ... A colliding create is rejected with `ERR_WINDOW_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/maintenance_window_closed_interval_touching_collides
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    dept = fx.create_department(backlog_threshold=5)
    validate_success(
        api.create_service_window(
            fac.create_service_window_payload(
                "MAINTENANCE", "2026-06-01T08:00:00Z", "2026-06-01T10:00:00Z",
                department_id=dept["id"],
            ),
            ADMIN,
        ),
        201,
    )
    resp = api.create_service_window(
        fac.create_service_window_payload(
            "MAINTENANCE", "2026-06-01T10:00:00Z", "2026-06-01T12:00:00Z",
            department_id=dept["id"],
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP.value, 409)


def test_maintenance_only_first_window_persists(api):
    """PRD §3.8: "A new window may not overlap an existing window of the same type and
    same scope, and the overlap test depends on the type. ... touching endpoints
    therefore do collide."

    Design: Difficulty/resource_temporal_overlap/maintenance_window_closed_interval_touching_collides
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    dept = fx.create_department(backlog_threshold=5)
    validate_success(
        api.create_service_window(
            fac.create_service_window_payload(
                "MAINTENANCE", "2026-06-01T08:00:00Z", "2026-06-01T10:00:00Z",
                department_id=dept["id"],
            ),
            ADMIN,
        ),
        201,
    )
    api.create_service_window(
        fac.create_service_window_payload(
            "MAINTENANCE", "2026-06-01T10:00:00Z", "2026-06-01T12:00:00Z",
            department_id=dept["id"],
        ),
        ADMIN,
    )
    windows = api.list_department_maintenance_windows(dept["id"], ADMIN).json()["data"]
    assert len(windows) == 1, "the colliding second window must not be created"


# ---------------------------------------------------------------------------
# Queue A — Difficulty: BLACKOUT half-open touching allowed
# ---------------------------------------------------------------------------
def test_blackout_touching_endpoint_allowed(api):
    """PRD §3.8: "For two blackout windows on the same jurisdiction, the test treats
    both intervals as half-open: they collide when the first starts strictly before the
    second ends and the second starts strictly before the first ends — touching
    endpoints do not collide."

    Design: Difficulty/resource_temporal_overlap/blackout_window_half_open_touching_allowed
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    jur = fx.create_jurisdiction(41.80, 41.95, -87.70, -87.55)
    validate_success(
        api.create_service_window(
            fac.create_service_window_payload(
                "BLACKOUT", "2026-06-01T08:00:00Z", "2026-06-01T10:00:00Z",
                jurisdiction_id=jur["id"],
            ),
            ADMIN,
        ),
        201,
    )
    data = validate_success(
        api.create_service_window(
            fac.create_service_window_payload(
                "BLACKOUT", "2026-06-01T10:00:00Z", "2026-06-01T12:00:00Z",
                jurisdiction_id=jur["id"],
            ),
            ADMIN,
        ),
        201,
    )
    assert data["window_type"] == "BLACKOUT"


def test_blackout_both_touching_windows_persist(api):
    """PRD §3.8: "touching endpoints do not collide."

    Design: Difficulty/resource_temporal_overlap/blackout_window_half_open_touching_allowed
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    jur = fx.create_jurisdiction(41.80, 41.95, -87.70, -87.55)
    api.create_service_window(
        fac.create_service_window_payload(
            "BLACKOUT", "2026-06-01T08:00:00Z", "2026-06-01T10:00:00Z",
            jurisdiction_id=jur["id"],
        ),
        ADMIN,
    )
    api.create_service_window(
        fac.create_service_window_payload(
            "BLACKOUT", "2026-06-01T10:00:00Z", "2026-06-01T12:00:00Z",
            jurisdiction_id=jur["id"],
        ),
        ADMIN,
    )
    windows = api.list_jurisdiction_blackout_windows(jur["id"], ADMIN).json()["data"]
    assert len(windows) == 2


# ---------------------------------------------------------------------------
# Queue B — Corner: MAINTENANCE with jurisdiction is scope-invalid
# ---------------------------------------------------------------------------
def test_window_scope_invalid_maintenance_with_jurisdiction(api):
    """PRD §3.8: "A `MAINTENANCE` window attaches to a department: it supplies a
    non-null `department_id` and must leave `jurisdiction_id` null. ... A window whose
    scope is mismatched — a maintenance window missing its department or carrying a
    jurisdiction ... — is rejected with `ERR_WINDOW_SCOPE_INVALID` (HTTP 422)."

    Design: Corner/validations/window_scope_invalid_maintenance_with_jurisdiction
    """
    jur = fx.create_jurisdiction(41.80, 41.95, -87.70, -87.55)
    resp = api.create_service_window(
        fac.create_service_window_payload(
            "MAINTENANCE", "2026-06-01T08:00:00Z", "2026-06-01T10:00:00Z",
            jurisdiction_id=jur["id"],
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_SCOPE_INVALID.value, 422)
