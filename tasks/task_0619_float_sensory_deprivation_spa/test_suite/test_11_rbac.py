"""Role-based access control: role-exclusive operations rejected for narrower roles, and the
authentication gate."""
from test_helpers import (
    validate_error,
    setup_member_owned_confirmed_credit_booking, setup_member_and_tank,
    create_tank_payload, make_member_headers,
    set_clock, api_client, TEST_USERS,
)

FRONTDESK = TEST_USERS["frontdesk_headers"]


# ─── Member cannot check-in (member_cannot_check_in_booking) ──────────────
def test_member_cannot_check_in_own_booking(api):
    """PRD §4: endpoint table lists `POST /bookings/{id}/check-in` as authorized for
    `Admin, FrontDesk` only. PRD §2.1: "A syntactically valid request whose role is not
    permitted to perform the requested operation — or a `Member` reaching for a resource it
    does not own — is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/member_cannot_check_in_booking
    """
    ctx = setup_member_owned_confirmed_credit_booking()
    bk, member_headers = ctx["booking"], ctx["member_headers"]
    res = api.check_in_booking(bk["id"], member_headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# ─── Member cannot create tank (member_cannot_create_tank) ────────────────
def test_member_cannot_create_tank(api):
    """PRD §4: endpoint table lists `POST /tanks` as authorized for `Admin` only. PRD §2.1: "A
    syntactically valid request whose role is not permitted to perform the requested operation
    — or a `Member` reaching for a resource it does not own — is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/member_cannot_create_tank
    """
    ctx = setup_member_and_tank()
    member = ctx["member"]
    res = api.create_tank(create_tank_payload(name="Pod-X", capacity_kind="SINGLE"),
                          make_member_headers(member["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# ─── Unauthenticated (unauthenticated_request_rejected) ───────────────────
def test_unauthenticated_request_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a role the server does not
    recognize, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/unauthenticated_request_rejected
    """
    res = api.list_tanks({})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
