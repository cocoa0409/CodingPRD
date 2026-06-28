"""Role-based access control and authentication: peer-role permissions and
entity-backed ownership checks."""
from test_helpers import (
    validate_success, validate_error,
    create_technician_payload,
    TEST_USERS, build_user_headers, make_client_headers, make_technician_headers,
    make_station, make_menu_item, make_technician, make_client,
    book_appointment, confirm, check_in, set_clock,
)

MANAGER = TEST_USERS["salon_manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]


def test_front_desk_cannot_create_technician(api):
    """PRD §2.1: "When a recognized role attempts an operation it is not permitted
    to perform — or when an ownership-scoped role acts on a resource it does not
    own — the request is rejected with `ERR_FORBIDDEN`."
    PRD §4: technician creation is authorized for `SalonManager` only.

    Design: Corner/rbac/front_desk_cannot_create_technician
    """
    station = make_station(requires_autoclave=False)
    payload = create_technician_payload(station["id"])
    res = api.create_technician(payload, FRONT_DESK)
    validate_error(res, "ERR_FORBIDDEN")


def test_client_cannot_cancel_other_clients_appointment(api):
    """PRD §2.1: "When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the
    acting `Client`; ownership checks on any resource that references a `Client`
    compare the resource's client foreign key to `X-User-ID`."
    PRD §2.1: "When a recognized role attempts an operation it is not permitted to
    perform — or when an ownership-scoped role acts on a resource it does not own —
    the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/client_cannot_cancel_other_clients_appointment
    """
    set_clock("2026-07-20T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(requires_sterile_station=False)
    tech = make_technician(station["id"])
    client_a = make_client()
    client_b = make_client()
    appt = book_appointment(client_a["id"], tech["id"], station["id"], menu["id"],
                            origin="APPOINTMENT", start_at="2026-07-20T15:00:00Z")
    confirm(appt["id"])

    res = api.cancel_appointment(appt["id"], make_client_headers(client_b["id"]))
    validate_error(res, "ERR_FORBIDDEN")

    after = validate_success(api.get_appointment(appt["id"], FRONT_DESK))
    assert after["booking_status"] == "CONFIRMED"


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    ghost = build_user_headers("ghost-1", "Ghost")
    res = api.list_appointments(ghost)
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_technician_cannot_start_other_techs_appointment(api):
    """PRD §2.1: "When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of
    the acting `Technician`; ownership checks on any resource that references a
    `Technician` compare the resource's technician foreign key to `X-User-ID`."
    PRD §2.1: "When a recognized role attempts an operation it is not permitted to
    perform — or when an ownership-scoped role acts on a resource it does not own —
    the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/technician_cannot_start_other_techs_appointment
    """
    set_clock("2026-07-21T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(requires_sterile_station=False)
    tech_a = make_technician(station["id"])
    tech_b = make_technician(station["id"])
    client = make_client()
    appt = book_appointment(client["id"], tech_a["id"], station["id"], menu["id"],
                            origin="WALK_IN")
    confirm(appt["id"])
    check_in(appt["id"])

    res = api.start_service(appt["id"], make_technician_headers(tech_b["id"]))
    validate_error(res, "ERR_FORBIDDEN")
