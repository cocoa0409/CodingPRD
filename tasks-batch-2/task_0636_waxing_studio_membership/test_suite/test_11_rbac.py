"""RBAC corners: role-exclusive denials, ownership denials, and the
missing-authentication guard."""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_location,
    create_member,
    create_service_type,
    create_room,
    create_technician,
    create_membership,
    book_reservation,
    get_room_version,
    ApiErrorId,
    TEST_USERS,
    make_member_headers,
)

ADMIN = TEST_USERS["studio_admin_headers"]
FRONT = TEST_USERS["front_desk_headers"]


def test_member_cannot_activate_membership(api):
    """PRD 4: "| POST | `/studio/memberships/{id}/activate` | Activate a PENDING
    membership | StudioAdmin, FrontDesk |".
    PRD 2.1: "the request is rejected with `ERR_UNAUTHORIZED`" when "the role is
    not permitted to perform the requested operation".

    A Member calling the activate endpoint (FrontDesk/StudioAdmin only) is
    rejected ERR_UNAUTHORIZED.

    Design: Corner/rbac/member_cannot_activate_membership
    """
    loc = create_location(name="Rb1")
    member = create_member(loc["id"])
    mbr = create_membership(member["id"], tier="PLUS", monthly_credit_grant=4,
                            monthly_fee_cents=6000)
    resp = api.activate_membership(mbr["id"], make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_frontdesk_cannot_waive_strike(api):
    """PRD 4: "| POST | `/studio/no-show-strikes/{id}/waive` | Waive an ACTIVE
    strike | StudioAdmin |".
    PRD 2.1: "the request is rejected with `ERR_UNAUTHORIZED`".

    A FrontDesk operator calling the waive endpoint (StudioAdmin only) is
    rejected ERR_UNAUTHORIZED.

    Design: Corner/rbac/frontdesk_cannot_waive_strike
    """
    set_clock("2026-06-15T12:00:00Z")
    loc = create_location(name="Rb2", deposit_required_cents=1000)
    svc = create_service_type(name="QRb", duration_minutes=15, list_price_cents=1200)
    room = create_room(loc["id"], label="RRb")
    tech = create_technician(loc["id"], certified_service_ids=[svc["id"]], full_name="TRb")
    member = create_member(loc["id"])
    res = book_reservation(member=member, location_id=loc["id"], room_id=room["id"],
                           technician_id=tech["id"], service_type_id=svc["id"],
                           start_utc="2026-06-16T10:00:00Z", payment_method="DEPOSIT",
                           expected_room_version=room["version"], booked_by="frontdesk")
    set_clock("2026-06-16T10:20:00Z")
    api.mark_no_show_reservation(res["id"], FRONT)
    from test_helpers import validate_paginated
    strikes, _ = validate_paginated(api.list_no_show_strikes(FRONT, params={"member_id": member["id"]}))
    resp = api.waive_no_show_strike(strikes[0]["id"], FRONT)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_member_cannot_book_for_other_member(api):
    """PRD 3.4: "a member acting for themselves may only book where `member_id`
    equals their own identifier."

    A Member booking with member_id pointing at a different member is rejected
    ERR_UNAUTHORIZED (ownership check).

    Design: Corner/rbac/member_cannot_book_for_other_member
    """
    set_clock("2026-06-15T12:00:00Z")
    loc = create_location(name="Own")
    svc = create_service_type(name="QO", duration_minutes=30, list_price_cents=2000)
    room = create_room(loc["id"], label="RO")
    tech = create_technician(loc["id"], certified_service_ids=[svc["id"]], full_name="TO")
    m1 = create_member(loc["id"])
    m2 = create_member(loc["id"])
    resp = api.create_reservation({
        "member_id": m2["id"], "location_id": loc["id"], "room_id": room["id"],
        "technician_id": tech["id"], "service_type_id": svc["id"],
        "start_utc": "2026-06-16T10:00:00Z", "payment_method": "WALK_IN",
        "expected_room_version": room["version"],
    }, make_member_headers(m1["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_missing_auth_headers_unauthenticated(api):
    """PRD 2.1: "Every request must be authenticated through two mandatory HTTP
    headers ... If either header is missing, or if `X-User-Role` is not one of
    these four recognized roles, the request is rejected with
    `ERR_UNAUTHENTICATED`."

    A request carrying no auth headers is rejected ERR_UNAUTHENTICATED.

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    resp = api.create_location({"name": "NoAuth", "state_code": "CA"}, {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
