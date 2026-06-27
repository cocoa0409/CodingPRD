"""Shipping/distribution, the dispatch→fulfill cascade, the dispatch-requires-PAID
cross-entity dependency, and settlement under optimistic concurrency
(PRD §3.8, §3.9, §2.9).

Queue A: transitive_cascade, cross_entity_state_dependency.
Queue B: state_machines, cross_cutting_complexity_layers sections.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_shipment_payload,
    TEST_USERS,
)
from test_helpers.fixtures import (
    create_session, add_student, add_package,
    create_session_gallery_open_all_absent, create_paid_order,
    create_submitted_order, read_session,
)
from test_helpers.api_client import api_client

COORD = TEST_USERS["coordinator_headers"]
PHOTOG = TEST_USERS["photographer_headers"]
CLERK = TEST_USERS["clerk_headers"]


# --------------------------------------------------------------------------- #
# transitive_cascade / dispatch_fulfills_order_depth2  (queue A)
# --------------------------------------------------------------------------- #
def test_dispatch_marks_shipment_dispatched(api):
    """PRD §3.8: "Dispatching a shipment carries it PENDING → DISPATCHED and, as a
    cross-entity side effect, drives the linked order PAID → FULFILLED."

    Design: Difficulty/transitive_cascade/dispatch_fulfills_order_depth2
    """
    session, students, _ = create_session_gallery_open_all_absent(num_students=1)
    pkg = add_package(session["id"], sku="K5", name="K5", tier="BASIC", base_price_cents=5000)
    order = create_paid_order(session["id"], students[0], pkg["id"], quantity=1)
    shipment = validate_success(api.create_shipment(
        create_shipment_payload(order["id"], carrier="UPS", tracking_code="TRK1"), CLERK), 201)
    dispatched = validate_success(api.dispatch_shipment(shipment["id"], CLERK), 200)
    assert dispatched["status"] == "DISPATCHED"


def test_dispatch_fulfills_linked_order(api):
    """PRD §3.8: "Dispatching a shipment carries it PENDING → DISPATCHED and, as a
    cross-entity side effect, drives the linked order PAID → FULFILLED."

    Design: Difficulty/transitive_cascade/dispatch_fulfills_order_depth2
    """
    session, students, _ = create_session_gallery_open_all_absent(num_students=1)
    pkg = add_package(session["id"], sku="K5", name="K5", tier="BASIC", base_price_cents=5000)
    order = create_paid_order(session["id"], students[0], pkg["id"], quantity=1)
    shipment = validate_success(api.create_shipment(
        create_shipment_payload(order["id"], carrier="UPS", tracking_code="TRK1"), CLERK), 201)
    api.dispatch_shipment(shipment["id"], CLERK)
    order_after = validate_success(api.get_order(order["id"], CLERK), 200)
    assert order_after["status"] == "FULFILLED"


# --------------------------------------------------------------------------- #
# cross_entity_state_dependency / shipment_dispatch_requires_order_paid (queue A)
# --------------------------------------------------------------------------- #
def test_dispatch_requires_order_paid(api):
    """PRD §3.8: "Dispatch has two preconditions: the linked order must be PAID
    (otherwise ERR_ORDER_NOT_PAID) and the shipment must already carry a
    tracking_code (otherwise ERR_TRACKING_REQUIRED)."

    Design: Difficulty/cross_entity_state_dependency/shipment_dispatch_requires_order_paid
    """
    session, students, _ = create_session_gallery_open_all_absent(num_students=1)
    pkg = add_package(session["id"], sku="K5", name="K5", tier="BASIC", base_price_cents=5000)
    # order only SUBMITTED, not PAID
    order = create_submitted_order(session["id"], students[0], pkg["id"], quantity=1)
    shipment = validate_success(api.create_shipment(
        create_shipment_payload(order["id"], carrier="UPS", tracking_code="TRK"), CLERK), 201)
    res = api.dispatch_shipment(shipment["id"], CLERK)
    validate_error(res, "ERR_ORDER_NOT_PAID", expected_status=409)
    ship_after = validate_success(api.get_shipment(shipment["id"], CLERK), 200)
    assert ship_after["status"] == "PENDING"


def test_dispatch_succeeds_once_order_paid(api):
    """PRD §3.8: "Dispatch has two preconditions: the linked order must be PAID
    (otherwise ERR_ORDER_NOT_PAID) and the shipment must already carry a
    tracking_code (otherwise ERR_TRACKING_REQUIRED)."

    Design: Difficulty/cross_entity_state_dependency/shipment_dispatch_requires_order_paid
    """
    session, students, _ = create_session_gallery_open_all_absent(num_students=1)
    pkg = add_package(session["id"], sku="K5", name="K5", tier="BASIC", base_price_cents=5000)
    order = create_paid_order(session["id"], students[0], pkg["id"], quantity=1)
    shipment = validate_success(api.create_shipment(
        create_shipment_payload(order["id"], carrier="UPS", tracking_code="TRK"), CLERK), 201)
    dispatched = validate_success(api.dispatch_shipment(shipment["id"], CLERK), 200)
    assert dispatched["status"] == "DISPATCHED"


# --------------------------------------------------------------------------- #
# Queue B / state_machines / dispatch_without_tracking_code_rejected
# --------------------------------------------------------------------------- #
def test_dispatch_without_tracking_rejected(api):
    """PRD §3.8: "the shipment must already carry a tracking_code (otherwise
    ERR_TRACKING_REQUIRED)."

    Design: Corner/state_machines/dispatch_without_tracking_code_rejected
    """
    session, students, _ = create_session_gallery_open_all_absent(num_students=1)
    pkg = add_package(session["id"], sku="K", name="K", tier="BASIC", base_price_cents=5000)
    order = create_paid_order(session["id"], students[0], pkg["id"], quantity=1)
    # create shipment WITHOUT a tracking_code
    shipment = validate_success(api.create_shipment(
        {"photo_order_id": order["id"], "carrier": "UPS",
         "distribution_method": "HOME_DELIVERY"}, CLERK), 201)
    res = api.dispatch_shipment(shipment["id"], CLERK)
    validate_error(res, "ERR_TRACKING_REQUIRED", expected_status=409)


# --------------------------------------------------------------------------- #
# Queue B / state_machines / void_dispatched_shipment_rejected
# --------------------------------------------------------------------------- #
def test_void_dispatched_shipment_rejected(api):
    """PRD §3.8: "while a shipment is still PENDING, the clerk may void it,
    advancing it PENDING → VOIDED; voiding a shipment that is not PENDING is
    rejected with ERR_SHIPMENT_NOT_VOIDABLE."

    Design: Corner/state_machines/void_dispatched_shipment_rejected
    """
    session, students, _ = create_session_gallery_open_all_absent(num_students=1)
    pkg = add_package(session["id"], sku="K", name="K", tier="BASIC", base_price_cents=5000)
    order = create_paid_order(session["id"], students[0], pkg["id"], quantity=1)
    shipment = validate_success(api.create_shipment(
        create_shipment_payload(order["id"], carrier="UPS", tracking_code="TR"), CLERK), 201)
    api.dispatch_shipment(shipment["id"], CLERK)  # -> DISPATCHED
    res = api.void_shipment(shipment["id"], CLERK)
    validate_error(res, "ERR_SHIPMENT_NOT_VOIDABLE", expected_status=409)


# --------------------------------------------------------------------------- #
# Queue B / cross_cutting / occ_settle_correct_version_succeeds_and_bumps
# --------------------------------------------------------------------------- #
def _ordering_closed_no_orders():
    session, _students, _pkg = create_session_gallery_open_all_absent(num_students=1)
    api_client.close_ordering(session["id"], COORD)
    return read_session(session["id"])


def test_settle_with_correct_version_succeeds_and_bumps(api):
    """PRD §2.9: "The settle request must carry an expected_picture_day_session_version
    field — it is required, not optional — holding the version of the session the
    client last observed. If that value does not equal the session's current
    version, the settle is rejected with ERR_STALE_SESSION_VERSION (HTTP 412)."
    PRD §3.9: "The coordinator settles a closed session, advancing it
    ORDERING_CLOSED → SETTLED and advancing its version by one."

    Design: Corner/cross_cutting_complexity_layers/occ_settle_correct_version_succeeds_and_bumps
    """
    sess = _ordering_closed_no_orders()
    res = api.settle_session(sess["id"], {"expected_picture_day_session_version": sess["version"]}, COORD)
    settled = validate_success(res, 200)
    assert settled["status"] == "SETTLED"
    assert settled["version"] == sess["version"] + 1
    assert settled["school_commission_balance_cents"] == 0  # no paid orders


def test_settle_with_stale_version_rejected(api):
    """PRD §2.9: "If that value does not equal the session's current version, the
    settle is rejected with ERR_STALE_SESSION_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_settle_stale_version_rejected
    """
    sess = _ordering_closed_no_orders()
    stale_version = sess["version"] - 1
    res = api.settle_session(sess["id"], {"expected_picture_day_session_version": stale_version}, COORD)
    validate_error(res, "ERR_STALE_SESSION_VERSION", expected_status=412)
    after = read_session(sess["id"])
    assert after["status"] == "ORDERING_CLOSED"
