"""RBAC, list endpoints, and dues-invoice terminal-state guard.

Corner design index:
  rbac / member_cannot_create_class_session
  rbac / member_books_for_self_succeeds_as_owner
  rbac / missing_headers_returns_unauthenticated
  endpoints / list_bookings_filtered_by_member_id_paginated
  errors / dues_invoice_void_then_pay_returns_invalid_state
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    setup_active_member, register_member,
    create_plan, create_location, create_session, set_clock,
    make_member_headers,
    PLAN_PLUS,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]


# ===========================================================================
# rbac / member_cannot_create_class_session
# ===========================================================================
def test_member_cannot_create_class_session(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to perform the
    requested operation, or a member attempts to act on a resource that is not theirs, the
    request is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/member_cannot_create_class_session
    """
    setup = setup_active_member(plan_shape=PLAN_PLUS)
    member = setup["member"]
    member_hdrs = make_member_headers(member["id"])
    resp = api.create_class_session(
        {"location_id": setup["location"]["id"], "title": "Hack",
         "starts_at": "2026-06-20T09:00:00Z", "ends_at": "2026-06-20T10:00:00Z",
         "capacity": 5, "waitlist_cap": 5}, member_hdrs
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ===========================================================================
# rbac / member_books_for_self_succeeds_as_owner
# ===========================================================================
def test_member_books_for_self_succeeds(api):
    """PRD §2.1: "Ownership checks on any resource that references a member compare that
    resource's member foreign key (for example, a booking's member_id ...) to X-User-ID"
    PRD §3.5: "Booking a seat is available to a StaffManager or to the owning Member"

    Design: Corner/rbac/member_books_for_self_succeeds_as_owner
    """
    setup = setup_active_member(plan_shape=PLAN_PLUS)
    member = setup["member"]
    member_hdrs = make_member_headers(member["id"])
    session = create_session(setup["location"]["id"], capacity=5, waitlist_cap=5,
                             starts_at="2026-06-21T09:00:00Z", ends_at="2026-06-21T10:00:00Z")
    resp = api.create_booking(
        {"session_id": session["id"], "member_id": member["id"],
         "expected_session_version": session["version"]}, member_hdrs
    )
    data = validate_success(resp, 201)
    assert data["status"] == "BOOKED"


# ===========================================================================
# rbac / missing_headers_returns_unauthenticated
# ===========================================================================
def test_missing_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request must be authenticated through two mandatory HTTP headers ... If
    either header is missing, or X-User-Role is not one of the recognized roles, the request is
    rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    resp = api.get_member(NON_EXISTENT_UUID, {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# endpoints / list_bookings_filtered_by_member_id_paginated
# ===========================================================================
def test_list_bookings_filtered_by_member_id(api):
    """PRD §4: "bookings by session_id, member_id, and status"
    PRD §2.3: "Paginated list responses include the following fields in the meta object of the
    response envelope: limit, offset, total_count, and has_more."

    Design: Corner/endpoints/list_bookings_filtered_by_member_id_paginated
    """
    setup = setup_active_member(plan_shape=PLAN_PLUS)
    member = setup["member"]
    loc = setup["location"]
    s1 = create_session(loc["id"], title="S1", capacity=5, waitlist_cap=5,
                        starts_at="2026-06-14T09:00:00Z", ends_at="2026-06-14T10:00:00Z")
    validate_success(
        api.create_booking({"session_id": s1["id"], "member_id": member["id"],
                            "expected_session_version": s1["version"]}, STAFF), 201
    )
    s2 = create_session(loc["id"], title="S2", capacity=5, waitlist_cap=5,
                        starts_at="2026-06-16T09:00:00Z", ends_at="2026-06-16T10:00:00Z")
    validate_success(
        api.create_booking({"session_id": s2["id"], "member_id": member["id"],
                            "expected_session_version": s2["version"]}, STAFF), 201
    )
    resp = api.list_bookings(STAFF, params={"member_id": member["id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


# ===========================================================================
# errors / dues_invoice_void_then_pay_returns_invalid_state
# ===========================================================================
def test_pay_void_invoice_returns_invalid_state(api):
    """PRD §3.8: "Paying an invoice is open to a StaffManager or the owning Member and is
    permitted only while the invoice is OPEN."
    PRD §3.8: "A StaffManager may instead void an OPEN invoice as a write-off; voiding moves it
    to VOID"

    Design: Corner/errors/dues_invoice_void_then_pay_returns_invalid_state
    """
    plan = create_plan(PLAN_PLUS)
    location = create_location()
    member, joining = register_member(plan["id"], location["id"], clock="2026-06-10T00:00:00Z")
    void_data = validate_success(api.void_dues_invoice(joining["id"], STAFF), 200)
    assert void_data["status"] == "VOID"
    resp = api.pay_dues_invoice(joining["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
