"""Authentication and role-based access control: missing role header, exclusive
operations, and member ownership scoping."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    SLOT_AM_END,
    SLOT_AM_START,
    create_member,
    create_requested_booking,
    make_member_headers,
    setup_world,
    validate_error,
    validate_success,
)


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "A request whose `X-User-Role` header is missing or does not
    match one of the declared role names is rejected with `ERR_UNAUTHENTICATED`
    (401)."
    PRD §2.7: "Authentication comes first: a missing or undeclared `X-User-Role`
    produces `ERR_UNAUTHENTICATED` before anything else is examined."

    Design: Corner/validations/missing_role_header_returns_unauthenticated
    """
    # Only X-User-ID present; the role header is absent. The path id would
    # otherwise produce a 404 — authentication must fire first.
    res = api.get_campaign(NON_EXISTENT_UUID, headers={"X-User-ID": "anon"})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_member_cannot_create_station(api):
    """PRD §2.1: "A request whose role is syntactically valid but not on the
    endpoint's authorized-role list is rejected with `ERR_FORBIDDEN` (403)."
    PRD §4: POST /api/stations is authorized for COOP_ADMIN only.

    Design: Corner/rbac/member_cannot_create_station
    """
    member = create_member()
    res = api.create_station({"name": "ST", "booking_capacity_tons": 100},
                             make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


def test_member_cannot_confirm_booking(api):
    """PRD §2.1: "A request whose role is syntactically valid but not on the
    endpoint's authorized-role list is rejected with `ERR_FORBIDDEN` (403)."
    PRD §3.2: "Confirmation is the `SCHEDULER`'s decision".

    Design: Corner/rbac/member_cannot_confirm_booking
    """
    world = setup_world(with_pile=False)
    booking = create_requested_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_AM_START, SLOT_AM_END, 20)
    res = api.confirm_booking(booking["id"],
                              make_member_headers(world["member"]["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


def test_member_reading_other_members_booking_forbidden(api):
    """PRD §2.1: "When `X-User-Role` is `MEMBER`, `X-User-ID` is the `id` of the
    acting `Member`; ownership checks on any resource that references a `Member`
    — a booking, a load ticket, a settlement statement, a ledger entry — compare
    the resource's `member_id` field to `X-User-ID`, and a `MEMBER` caller
    attempting to read or act on a resource whose `member_id` differs from their
    `X-User-ID` is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/member_reading_other_members_booking_forbidden
    """
    world = setup_world(with_pile=False)
    other = create_member(name="M2", member_code="M-1002", haul_distance_miles=12.0)
    booking = create_requested_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_AM_START, SLOT_AM_END, 20)
    res = api.get_booking(booking["id"], make_member_headers(other["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)
    own = validate_success(
        api.get_booking(booking["id"], make_member_headers(world["member"]["id"])), 200)
    assert own["id"] == booking["id"]
