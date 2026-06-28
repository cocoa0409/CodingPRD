"""Validation-priority precedence and role-based access control.

Covers difficulty queue A rule `priority_pair_validation_conflict`
(salon-not-open beats member-blocked) and corner queue B `rbac` instances
(member cannot seat, missing user context, front-desk cannot void).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    build_user_headers,
    TEST_USERS,
    make_member_headers,
)
import test_helpers as th

FRONT_DESK = TEST_USERS["front_desk_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ===========================================================================
# Difficulty A: priority_pair_validation_conflict / salon_not_open_beats_member_blocked
# ===========================================================================
def test_salon_not_open_beats_member_blocked(api):
    """PRD §2.7: "Fifth, the salon's open status is enforced where it applies. Sixth,
    the target resource's own state is checked against the transition being requested.
    Only after those structural gates does the system reach the business-safety,
    capacity, fiscal, temporal, referential, concurrency, and uniqueness checks."
    PRD §3.3: "Joining the queue requires the salon to be `OPEN` (otherwise
    `ERR_SALON_NOT_OPEN`) and the member to be `ACTIVE`; a `SUSPENDED` or `BANNED`
    member attempting to join is refused with `ERR_MEMBER_BLOCKED`."

    Design: Difficulty/priority_pair_validation_conflict/salon_not_open_beats_member_blocked
    """
    # Open salon, suspend a member via two no-shows, then close the salon and attempt to
    # rejoin: the salon-open check (priority 5) pre-empts the member-blocked check.
    salon = th.create_and_open_salon()
    svc = th.add_service_item(salon["id"])
    member = th.drive_member_to_strikes(salon["id"], svc["id"], 2)
    assert member["status"] == "SUSPENDED"
    live = validate_success(api.get_salon(salon["id"], MANAGER))
    validate_success(
        api.close_salon(salon["id"], {"expected_salon_version": live["version"]}, MANAGER)
    )
    resp = api.create_queue_ticket(
        th.create_queue_ticket_payload(salon["id"], member["id"], svc["id"]), FRONT_DESK
    )
    validate_error(resp, ApiErrorId.ERR_SALON_NOT_OPEN.value, expected_status=409)


def test_suspended_member_blocked_when_salon_open(api):
    """PRD §3.3: "a `SUSPENDED` or `BANNED` member attempting to join is refused with
    `ERR_MEMBER_BLOCKED`."

    Design: Difficulty/priority_pair_validation_conflict/salon_not_open_beats_member_blocked
    """
    # The complement: with the salon OPEN the higher-priority state gate passes, so the
    # SUSPENDED member instead hits ERR_MEMBER_BLOCKED — confirming the pair is ordered.
    salon = th.create_and_open_salon()
    svc = th.add_service_item(salon["id"])
    member = th.drive_member_to_strikes(salon["id"], svc["id"], 2)
    assert member["status"] == "SUSPENDED"
    resp = api.create_queue_ticket(
        th.create_queue_ticket_payload(salon["id"], member["id"], svc["id"]), FRONT_DESK
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_BLOCKED.value, expected_status=403)


# ===========================================================================
# Corner B: rbac / member_cannot_seat_visit
# ===========================================================================
def test_member_cannot_seat_visit(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."
    PRD §4: "| POST | `/salon-svc/service-visits` | Seat a called member onto a chair
    and technician | FrontDeskAgent |"

    Design: Corner/rbac/member_cannot_seat_visit
    """
    salon = th.create_and_open_salon()
    chair = th.add_chair(salon["id"])
    tech = th.add_technician(salon["id"])
    svc = th.add_service_item(salon["id"])
    member = th.add_member(salon["id"])
    ticket = th.join_and_call(salon["id"], member["id"], svc["id"])
    resp = api.create_service_visit(
        th.create_service_visit_payload(
            salon["id"], ticket["id"], chair["id"], tech["id"], salon["version"]
        ),
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)


# ===========================================================================
# Corner B: rbac / missing_user_context_header_rejected
# ===========================================================================
def test_unrecognized_role_rejected(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the
    recognized role names, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401)."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    ghost = build_user_headers("ghost-1", "GhostRole")
    resp = api.create_salon(th.create_salon_payload(), ghost)
    validate_error(
        resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT.value, expected_status=401
    )


# ===========================================================================
# Corner B: rbac / front_desk_cannot_void_visit
# ===========================================================================
def test_front_desk_cannot_void_visit(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."
    PRD §4: "| POST | `/salon-svc/service-visits/{visitId}/void` | Void a visit and
    compensate | SalonManager |"

    Design: Corner/rbac/front_desk_cannot_void_visit
    """
    s = th.setup_seated_visit()
    resp = api.void_service_visit(s["visit"]["id"], FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)
