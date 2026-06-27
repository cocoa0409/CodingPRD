"""Authentication, role-based authorization, guardian ownership, gallery access
gating, validation-ordering, and remaining create-time field constraints
(PRD §2.1, §2.5, §2.6, §2.7, §3.4).

Queue B: rbac, validations, entities sections.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_session_payload, create_student_payload, create_package_payload,
    create_order_payload,
    TEST_USERS, make_guardian_headers,
)
from test_helpers.fixtures import (
    create_session, add_package, create_session_gallery_open_all_absent,
    create_submitted_order,
)
from test_helpers.api_client import api_client

COORD = TEST_USERS["coordinator_headers"]
PHOTOG = TEST_USERS["photographer_headers"]
CLERK = TEST_USERS["clerk_headers"]


# --------------------------------------------------------------------------- #
# Queue B / rbac
# --------------------------------------------------------------------------- #
def test_missing_user_context_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value,
    is rejected with ERR_MISSING_USER_CONTEXT (HTTP 401)."

    Design: Corner/rbac/missing_user_context_401
    """
    res = api.create_session(create_session_payload(), headers={})
    validate_error(res, "ERR_MISSING_USER_CONTEXT", expected_status=401)


def test_photographer_cannot_create_session(api):
    """PRD §2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE (HTTP 403)."
    PRD §3.1: "A SchoolCoordinator opens the engagement by creating a picture day
    session"

    Design: Corner/rbac/photographer_cannot_create_session_forbidden
    """
    res = api.create_session(create_session_payload(), PHOTOG)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_guardian_cannot_pay_order(api):
    """PRD §2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE (HTTP 403)."
    PRD §3.7: "accrued one order at a time, in payment chronological order, when a
    FulfillmentClerk records payment on a submitted order"

    Design: Corner/rbac/guardian_cannot_pay_order_forbidden
    """
    session, students, _ = create_session_gallery_open_all_absent(num_students=1)
    pkg = add_package(session["id"], sku="K", name="K", tier="BASIC", base_price_cents=5000)
    order = create_submitted_order(session["id"], students[0], pkg["id"], quantity=1)
    g = make_guardian_headers(students[0]["guardian_user_id"])
    res = api.pay_order(order["id"], g)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_guardian_not_owner_of_other_student_order(api):
    """PRD §2.1: "when a guardian creates, submits, cancels, or reads an order, or
    reads their own student record, the server requires that the target student's
    guardian_user_id equals the request's X-User-ID; if it does not, the request is
    rejected with ERR_NOT_OWNER (HTTP 403). A guardian may only ever act on orders
    that belong to a student they own."

    Design: Corner/rbac/guardian_not_owner_of_other_student_order
    """
    session, students, _ = create_session_gallery_open_all_absent(num_students=1)
    # students[0] is owned by guardian "g1"; a different guardian "g2" attempts to order
    other_guardian = make_guardian_headers("g2")
    res = api.create_order(create_order_payload(session["id"], students[0]["id"]), other_guardian)
    validate_error(res, "ERR_NOT_OWNER", expected_status=403)


# --------------------------------------------------------------------------- #
# Queue B / validations
# --------------------------------------------------------------------------- #
def test_gallery_access_wrong_code_denied(api):
    """PRD §3.4: "Access is granted only when the supplied access_code equals the
    session's minted gallery_access_code and the current logical clock is strictly
    before gallery_closes_at. A wrong code, or a request at or after
    gallery_closes_at, is refused with ERR_GALLERY_ACCESS_DENIED."

    Design: Corner/validations/gallery_access_wrong_code_denied
    """
    session, students, _ = create_session_gallery_open_all_absent(num_students=1)
    g = make_guardian_headers(students[0]["guardian_user_id"])
    res = api.get_gallery(session["id"], g, params={"access_code": "WRONGCODE"})
    validate_error(res, "ERR_GALLERY_ACCESS_DENIED", expected_status=403)


def test_gallery_access_expired_code_denied(api):
    """PRD §3.4: "Access is granted only when the supplied access_code equals the
    session's minted gallery_access_code and the current logical clock is strictly
    before gallery_closes_at. A wrong code, or a request at or after
    gallery_closes_at, is refused with ERR_GALLERY_ACCESS_DENIED."
    PRD §2.10: "An operator may advance the clock by supplying a to_iso8601 instant
    to the clock-setting capability; from then on, the supplied instant is "now"
    for the purposes of every server-side time comparison."

    Design: Corner/validations/gallery_access_expired_code_denied
    """
    session, students, _ = create_session_gallery_open_all_absent(
        num_students=1, scheduled_date="2026-01-15T00:00:00Z",
        gallery_closes_at="2026-02-01T00:00:00Z")
    code = session["gallery_access_code"]
    # advance the logical clock past gallery_closes_at
    api_client.set_clock("2026-03-01T00:00:00Z", COORD)
    g = make_guardian_headers(students[0]["guardian_user_id"])
    res = api.get_gallery(session["id"], g, params={"access_code": code})
    validate_error(res, "ERR_GALLERY_ACCESS_DENIED", expected_status=403)


def test_existence_checked_before_state(api):
    """PRD §2.6: "After authentication and authorization, the server confirms that
    any resource named in the path exists, then that any foreign keys in the body
    reference existing rows."
    PRD §2.6: "After body validation, the server enforces session posture (is the
    parent session in the right state for this operation), then the target
    resource's own state"

    Design: Corner/validations/existence_before_state_priority
    """
    res = api.pay_order("00000000-0000-0000-0000-000000000000", CLERK)
    validate_error(res, "ERR_ORDER_NOT_FOUND", expected_status=404)


# --------------------------------------------------------------------------- #
# Queue B / entities (remaining create-time constraints)
# --------------------------------------------------------------------------- #
def test_duplicate_sku_within_session_rejected(api):
    """PRD §2.7: "A package item's sku must be unique within its session; an attempt
    to add a second catalog item with a sku already present in the same session is
    likewise rejected with ERR_INVALID_REQUEST."

    Design: Corner/entities/duplicate_sku_within_session_422
    """
    session = create_session()
    api.create_package(create_package_payload(session["id"], sku="DUP", name="First",
                                              tier="BASIC", base_price_cents=1000), COORD)
    res = api.create_package(create_package_payload(session["id"], sku="DUP", name="Second",
                                                    tier="DELUXE", base_price_cents=2000), COORD)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_package_base_price_zero_rejected(api):
    """PRD §2.7: "A package catalog item's base_price_cents must be strictly greater
    than zero."

    Design: Corner/entities/package_base_price_zero_rejected_422
    """
    session = create_session()
    res = api.create_package(create_package_payload(session["id"], sku="Z", name="Zero",
                                                    tier="BASIC", base_price_cents=0), COORD)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_create_student_with_missing_session_not_found(api):
    """PRD §2.5: "For create operations whose body carries foreign keys, the
    referenced rows must exist as well — a body naming a missing
    picture_day_session_id, student_id, photo_id, photo_order_id, package_item_id,
    backdrop_id, or photographer_id is rejected with the corresponding not-found
    error before any further processing."

    Design: Corner/entities/fk_student_session_not_found_404
    """
    payload = create_student_payload("00000000-0000-0000-0000-000000000000", full_name="Ghost")
    res = api.create_student(payload, COORD)
    validate_error(res, "ERR_SESSION_NOT_FOUND", expected_status=404)
