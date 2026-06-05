"""Authentication, authorization (peer-role denial), the duplicate check, and
the FK-existence-beats-body-shape precedence.

Corner instances (errors / rbac / validations sections):
unauthenticated-missing-role, forbidden-role for three peer-role pairs,
duplicate container_number, FK-not-found beats invalid-request.
"""
from test_helpers import (
    validate_error,
    ApiErrorId,
    TEST_USERS,
    headers_missing_role,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["terminal_admin_headers"]
BERTH = TEST_USERS["berth_planner_headers"]
YARD = TEST_USERS["yard_planner_headers"]
GATE = TEST_USERS["gate_operator_headers"]
CUSTOMS = TEST_USERS["customs_officer_headers"]


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #
def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` does not name a
    role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/errors/error_unauthenticated_missing_role_header
    """
    berth = fx.provision_berth(code="B-600", length_m=300, draft_m=14.0)
    resp = api.get_berth(berth["id"], headers_missing_role())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# --------------------------------------------------------------------------- #
# Authorization — peer-role denial
# --------------------------------------------------------------------------- #
def test_yard_planner_cannot_book_gate_appointment(api):
    """PRD §2.1: "When an authenticated operator invokes an endpoint their role is
    not authorized to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/yard_planner_cannot_book_gate_appointment
    """
    _, _, container, _ = fx.setup_grounded_cleared_container(free_time_days=60)
    resp = api.create_gate_appointment(
        {
            "container_id": container["id"],
            "truck_plate": "TRK-700",
            "window_start": "2026-03-01T10:00:00.000Z",
            "window_end": "2026-03-01T11:00:00.000Z",
        },
        YARD,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_berth_planner_cannot_register_berth(api):
    """PRD §2.1: "When an authenticated operator invokes an endpoint their role is
    not authorized to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/berth_planner_cannot_register_berth
    """
    resp = api.create_berth({"code": "B-710", "length_m": 300, "draft_m": 14.0}, BERTH)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_customs_officer_cannot_ground_container(api):
    """PRD §2.1: "When an authenticated operator invokes an endpoint their role is
    not authorized to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/customs_officer_cannot_ground_container
    """
    _, vessel, window = fx.provision_berthed_window()
    container = fx.declare_container(vessel["id"], window["id"], container_number="COFC720720")
    slot = fx.create_yard_slot(block="U")
    resp = api.ground_container(
        container["id"], {"yard_slot_id": slot["id"], "condition": "SOUND"}, CUSTOMS
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# --------------------------------------------------------------------------- #
# Uniqueness
# --------------------------------------------------------------------------- #
def test_duplicate_container_number_returns_duplicate(api):
    """PRD §2.8: "**uniqueness** is enforced for the three naturally unique
    identifiers — a `container_number`, an `imo_number`, or a berth `code` that
    already exists on another record yields `ERR_DUPLICATE` (HTTP 409)."

    Design: Corner/validations/duplicate_container_number_returns_duplicate
    """
    _, vessel, window = fx.provision_berthed_window()
    fx.declare_container(vessel["id"], window["id"], container_number="CNUM500500")
    resp = api.create_container(
        {
            "container_number": "CNUM500500",
            "vessel_id": vessel["id"],
            "berth_window_id": window["id"],
        },
        YARD,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value)


# --------------------------------------------------------------------------- #
# Precedence — FK existence beats body shape
# --------------------------------------------------------------------------- #
def test_fk_not_found_beats_invalid_request_on_gate_appointment(api):
    """PRD §2.8: "It then validates that **every foreign key carried in the request
    body** ... points to a resource that exists; an unresolved body reference yields
    `ERR_FK_NOT_FOUND` (HTTP 404). Once references resolve, the system validates the
    **shape** of the request body".

    Design: Corner/validations/fk_not_found_beats_invalid_request_on_gate_appointment
    """
    # Non-existent container_id AND a bad 90-minute window: FK check (earlier in
    # the precedence) wins -> ERR_FK_NOT_FOUND, not ERR_INVALID_REQUEST.
    resp = api.create_gate_appointment(
        {
            "container_id": "00000000-0000-4000-8000-0000000000bb",
            "truck_plate": "TRK-530",
            "window_start": "2026-03-01T10:00:00.000Z",
            "window_end": "2026-03-01T11:30:00.000Z",
        },
        GATE,
    )
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value)
