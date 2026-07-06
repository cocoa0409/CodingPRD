"""Role authorization, entity-backed ownership, and geofence field validation."""
from test_helpers import (
    validate_error, ApiErrorId,
    make_coordinator_headers, make_client_headers, make_sitter_headers,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

COORD = make_coordinator_headers()


def test_sitter_cannot_onboard_a_client(api):
    """PRD 2.1: "If the headers are well-formed but the named role is not permitted to perform the
    requested operation, the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/sitter_cannot_create_client_returns_unauthorized
    """
    sitter = fx.create_sitter(api)
    resp = api.create_client(
        f.create_client_payload(full_name="Intruder", email="i@x.com"),
        make_sitter_headers(sitter["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


def test_client_cannot_assign_sitter(api):
    """PRD 2.1: "If the headers are well-formed but the named role is not permitted to perform the
    requested operation, the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/client_cannot_assign_sitter_returns_unauthorized
    """
    ctx = fx.setup_pending_booking(api, onboard_sitter=True, cleared=False, bonded=False)
    resp = api.assign_booking(
        ctx["booking"]["id"], {"sitter_id": ctx["sitter"]["id"]},
        make_client_headers(ctx["client"]["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)
    assert fx.get_booking(api, ctx["booking"]["id"])["status"] == "PENDING_ASSIGNMENT"


def test_client_cannot_cancel_another_clients_booking(api):
    """PRD 2.1: "When a caller acts on a resource it does not own under this rule, the request is
    rejected with ERR_FORBIDDEN_NOT_OWNER (HTTP 403)."
    PRD 2.1: "may book, submit, and cancel only its own bookings, and may pay only its own invoices."

    Design: Corner/validations/client_cancel_other_client_booking_forbidden
    """
    client_a = fx.create_client(api, full_name="Ada A", email="a@x.com")
    client_b = fx.create_client(api, full_name="Bob B", email="b@x.com")
    prop = fx.create_property(api, client_a["id"])
    booking = fx.create_booking(api, prop["id"])
    resp = api.cancel_booking(booking["id"], make_client_headers(client_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_NOT_OWNER.value, expected_status=403)
    assert fx.get_booking(api, booking["id"])["status"] == "DRAFT"


def test_check_in_outside_geofence_rejected(api):
    """PRD 3.6: "the distance from the check-in point to the property centre must be at most
    geofence_radius_m metres, and a check-in outside that radius is rejected with ERR_OUTSIDE_GEOFENCE".

    Design: Corner/validations/checkin_outside_geofence_returns_422
    """
    ctx = fx.setup_active_booking(api, property_overrides={"geofence_radius_m": 150})
    visit = ctx["visits"][0]
    fx.set_clock(api, "2026-06-01T09:00:00Z")
    resp = api.check_in_visit(visit["id"], f.check_in_payload(gps_lat=41.0, gps_lng=-71.0),
                              make_sitter_headers(ctx["sitter"]["id"]))
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_GEOFENCE.value, expected_status=422)
    assert fx.get_visit(api, visit["id"])["status"] == "SCHEDULED"
