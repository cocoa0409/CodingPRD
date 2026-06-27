"""Session posture lifecycle: creation, locking, capture/gallery/ordering close,
cancellation, and their precondition guards (PRD §3.1, §3.3, §3.4, §3.9).

Queue B corner instances under sections `entities` and `state_machines`.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    assert_session,
    create_session_payload,
    TEST_USERS, make_photographer_headers,
)
from test_helpers.fixtures import (
    create_session, add_student, add_package,
    create_session_capture_open, match_photo_for_student,
    create_session_gallery_open_all_absent, create_submitted_order,
)

COORD = TEST_USERS["coordinator_headers"]
PHOTOG = TEST_USERS["photographer_headers"]


def test_create_session_returns_201_with_initial_ledgers(api, coordinator_headers):
    """PRD §3.1: "A new session begins life in DRAFT. At creation the server
    initializes the derived ledgers: the remaining retouch credit, exposed as
    retouch_credit_balance_cents, starts equal to retouch_budget_cents; the
    school's running commission, exposed as school_commission_balance_cents,
    starts at zero; and the commission gross, exposed as total_merchandise_cents,
    starts at zero."

    Design: Corner/entities/create_session_returns_201_with_defaults
    """
    res = api.create_session(create_session_payload(retouch_budget_cents=7000), coordinator_headers)
    sess = validate_success(res, 201)
    assert_session(sess)
    assert sess["status"] == "DRAFT"
    assert sess["retouch_credit_balance_cents"] == 7000
    assert sess["school_commission_balance_cents"] == 0
    assert sess["total_merchandise_cents"] == 0
    assert sess["version"] == 1


def test_create_session_missing_school_name_invalid(api, coordinator_headers):
    """PRD §2.7: "The same error covers any missing required body field, any field
    of the wrong type, and any enum value outside its declared set."

    Design: Corner/entities/create_session_missing_required_field_422
    """
    payload = create_session_payload()
    del payload["school_name"]
    res = api.create_session(payload, coordinator_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_get_session_not_found(api, coordinator_headers):
    """PRD §2.5: "For requests that name a resource by its id in the path, the
    server validates that the path resource exists before applying any business
    rule; a missing path resource yields the matching not-found error"

    Design: Corner/entities/get_session_not_found_404
    """
    res = api.get_session("00000000-0000-0000-0000-000000000000", coordinator_headers)
    validate_error(res, "ERR_SESSION_NOT_FOUND", expected_status=404)


def test_list_sessions_pagination_envelope(api, coordinator_headers):
    """PRD §2.3: "Each list response carries limit, offset, total_count, and
    has_more inside the meta object of the envelope."

    Design: Corner/entities/list_sessions_pagination_envelope
    """
    api.create_session(create_session_payload(school_name="One"), coordinator_headers)
    from test_helpers import validate_paginated
    data, meta = validate_paginated(api.list_sessions(coordinator_headers))
    assert meta["total_count"] >= 1
    assert isinstance(meta["has_more"], bool)


def test_lock_roster_empty_rejected(api):
    """PRD §3.1: "Once at least one student exists on the roster, the coordinator
    locks it, transitioning the session DRAFT → ROSTER_LOCKED. Locking with an
    empty roster is rejected with ERR_EMPTY_ROSTER."

    Design: Corner/state_machines/lock_roster_empty_returns_empty_roster
    """
    session = create_session()
    res = api.lock_roster(session["id"], COORD)
    validate_error(res, "ERR_EMPTY_ROSTER", expected_status=409)


def test_open_capture_empty_catalog_rejected(api):
    """PRD §3.3: "The transition from ROSTER_LOCKED → CAPTURE_OPEN requires that
    the catalog contain at least one item with active true; opening capture against
    an empty or fully-inactive catalog is rejected with ERR_EMPTY_CATALOG."

    Design: Corner/state_machines/open_capture_no_active_package_empty_catalog
    """
    session = create_session()
    add_student(session["id"])
    api.lock_roster(session["id"], COORD)
    res = api.open_capture(session["id"], PHOTOG)
    validate_error(res, "ERR_EMPTY_CATALOG", expected_status=409)


def test_open_gallery_with_enrolled_student_capture_incomplete(api):
    """PRD §3.4: "First, no student may remain ENROLLED — every roster row must
    have reached PHOTOGRAPHED or ABSENT, or the transition is rejected with
    ERR_CAPTURE_INCOMPLETE."

    Design: Corner/state_machines/open_gallery_with_enrolled_student_capture_incomplete
    """
    session, student, package = create_session_capture_open()
    # student is still ENROLLED (never matched or marked absent)
    res = api.open_gallery(session["id"], COORD)
    validate_error(res, "ERR_CAPTURE_INCOMPLETE", expected_status=409)


def test_open_gallery_with_retake_pending(api):
    """PRD §3.4: "Second, no photo may be sitting in RETAKE_REQUESTED; an
    outstanding retake blocks the gallery with ERR_RETAKE_PENDING."

    Design: Corner/state_machines/open_gallery_with_retake_pending
    """
    session, student, package = create_session_capture_open(retouch_budget_cents=50000)
    photo = match_photo_for_student(session["id"], student)
    # RETAKE creation drives the photo MATCHED -> RETAKE_REQUESTED (PRD §3.5)
    from test_helpers.factories import create_retouch_order_payload
    api.create_retouch_order(create_retouch_order_payload(photo["id"], kind="RETAKE"), PHOTOG)
    res = api.open_gallery(session["id"], COORD)
    validate_error(res, "ERR_RETAKE_PENDING", expected_status=409)


def test_close_ordering_with_submitted_order_rejected(api):
    """PRD §3.9: "This is only legal once no order for the session is still
    SUBMITTED — every submitted order must have reached PAID or REJECTED first —
    and an outstanding submitted order blocks the close with ERR_OPEN_ORDERS_EXIST."

    Design: Corner/state_machines/close_ordering_with_submitted_order
    """
    session, students, package = create_session_gallery_open_all_absent(num_students=1)
    create_submitted_order(session["id"], students[0], package["id"], quantity=1)
    res = api.close_ordering(session["id"], COORD)
    validate_error(res, "ERR_OPEN_ORDERS_EXIST", expected_status=409)


def test_cancel_session_from_gallery_open_invalid_transition(api):
    """PRD §3.9: "A session may be cancelled, but only from DRAFT, ROSTER_LOCKED,
    or CAPTURE_OPEN, and only when no order for the session is PAID or FULFILLED"
    PRD §3.9: "(An attempt to drive any session lifecycle transition from a state
    that does not permit it is reported as ERR_INVALID_SESSION_TRANSITION.)"

    Design: Corner/state_machines/session_cancel_invalid_from_gallery_open
    """
    session, students, package = create_session_gallery_open_all_absent(num_students=1)
    res = api.cancel_session(session["id"], COORD)
    validate_error(res, "ERR_INVALID_SESSION_TRANSITION", expected_status=409)


def test_lock_roster_twice_second_call_invalid(api):
    """PRD §3.9: "(An attempt to drive any session lifecycle transition from a
    state that does not permit it is reported as ERR_INVALID_SESSION_TRANSITION.)"
    PRD §3.1: "Once at least one student exists on the roster, the coordinator
    locks it, transitioning the session DRAFT → ROSTER_LOCKED."

    Design: Corner/state_machines/lock_roster_idempotent_second_call_invalid
    """
    session = create_session()
    add_student(session["id"])
    validate_success(api.lock_roster(session["id"], COORD), 200)
    res = api.lock_roster(session["id"], COORD)
    validate_error(res, "ERR_INVALID_SESSION_TRANSITION", expected_status=409)
