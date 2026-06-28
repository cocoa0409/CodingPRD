"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the session to be in a specific posture reached
through 5-15 API calls. These helpers encapsulate those preambles so tests focus
on assertions. They use get_success_data() (lenient) internally so setup failures
surface as clear "setup failed" errors rather than confusing assertion failures.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints; the harness restarts the server (empty DB) before every test.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_session_payload, create_student_payload, create_package_payload,
    create_backdrop_payload, create_photographer_payload, create_capture_slot_payload,
    create_photo_payload, create_order_payload, create_order_line_payload,
    create_retouch_order_payload, create_shipment_payload,
)
from .test_users import (
    TEST_USERS, make_coordinator_headers, make_photographer_headers,
    make_clerk_headers, make_guardian_headers,
)

COORD = TEST_USERS["coordinator_headers"]
PHOTOG = TEST_USERS["photographer_headers"]
CLERK = TEST_USERS["clerk_headers"]


# --------------------------------------------------------------------------- #
# Primitive create helpers
# --------------------------------------------------------------------------- #
def create_session(**overrides) -> dict:
    """A fresh DRAFT session."""
    return get_success_data(api_client.create_session(create_session_payload(**overrides), COORD))


def add_student(session_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_student(create_student_payload(session_id, **overrides), COORD))


def add_package(session_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_package(create_package_payload(session_id, **overrides), COORD))


def add_backdrop(session_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_backdrop(create_backdrop_payload(session_id, **overrides), COORD))


def add_photographer(session_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_photographer(create_photographer_payload(session_id, **overrides), COORD))


def add_capture_slot(session_id, backdrop_id, photographer_id, **overrides) -> dict:
    return get_success_data(api_client.create_capture_slot(
        create_capture_slot_payload(session_id, backdrop_id, photographer_id, **overrides), COORD))


def capture_photo(session_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_photo(create_photo_payload(session_id, **overrides), PHOTOG))


# --------------------------------------------------------------------------- #
# Tier 1: Session state progression
# --------------------------------------------------------------------------- #
def create_session_roster_locked(student_overrides=None, **session_overrides) -> tuple:
    """DRAFT session + one student + lock-roster -> ROSTER_LOCKED.
    Returns (session, student)."""
    session = create_session(**session_overrides)
    student = add_student(session["id"], **(student_overrides or {}))
    session = get_success_data(api_client.lock_roster(session["id"], COORD))
    return session, student


def create_session_capture_open(student_overrides=None, package_overrides=None,
                                **session_overrides) -> tuple:
    """Session driven to CAPTURE_OPEN with one student + one active package.
    Returns (session, student, package)."""
    session = create_session(**session_overrides)
    student = add_student(session["id"], **(student_overrides or {}))
    package = add_package(session["id"], **(package_overrides or {}))
    api_client.lock_roster(session["id"], COORD)
    session = get_success_data(api_client.open_capture(session["id"], PHOTOG))
    return session, student, package


def match_photo_for_student(session_id, student) -> dict:
    """Capture a photo whose slate exactly matches `student` and auto-match it
    (score 100). Requires the session in CAPTURE_OPEN. Returns the matched Photo."""
    photo = capture_photo(
        session_id,
        candidate_name=student["full_name"],
        candidate_grade=student["grade"],
        candidate_homeroom=student["homeroom"],
    )
    return get_success_data(api_client.match_photo(photo["id"], PHOTOG))


def create_session_gallery_open_all_absent(num_students=1, **session_overrides) -> tuple:
    """Session driven to GALLERY_OPEN with `num_students` students all marked ABSENT
    (so no ENROLLED remains and there are no pending retakes). One active package
    is stocked. Returns (session, [students], package)."""
    session = create_session(**session_overrides)
    package = add_package(session["id"])
    students = []
    for i in range(num_students):
        students.append(add_student(
            session["id"], full_name=f"Absent {i}", homeroom=f"H{i}",
            guardian_user_id=f"g{i + 1}"))
    api_client.lock_roster(session["id"], COORD)
    api_client.open_capture(session["id"], PHOTOG)
    for stu in students:
        api_client.mark_absent(stu["id"], PHOTOG)
    session = get_success_data(api_client.open_gallery(session["id"], COORD))
    return session, students, package


def create_session_gallery_open_with_matched_student(student_overrides=None,
                                                     package_overrides=None,
                                                     **session_overrides) -> tuple:
    """Session driven to GALLERY_OPEN with one PHOTOGRAPHED student (its photo MATCHED).
    Returns (session, student, package, photo)."""
    session, student, package = create_session_capture_open(
        student_overrides=student_overrides, package_overrides=package_overrides,
        **session_overrides)
    photo = match_photo_for_student(session["id"], student)
    session = get_success_data(api_client.open_gallery(session["id"], COORD))
    return session, student, package, photo


# --------------------------------------------------------------------------- #
# Tier 2/3: Ordering lifecycle shortcuts
# --------------------------------------------------------------------------- #
def create_cart_order(session_id, student) -> dict:
    """A CART order owned by the student's guardian. Returns the order."""
    g_headers = make_guardian_headers(student["guardian_user_id"])
    return get_success_data(api_client.create_order(
        create_order_payload(session_id, student["id"]), g_headers))


def add_line(order, package_id, student, quantity=1) -> dict:
    g_headers = make_guardian_headers(student["guardian_user_id"])
    return get_success_data(api_client.create_order_line(
        create_order_line_payload(order["id"], package_id, quantity), g_headers))


def create_submitted_order(session_id, student, package_id, quantity=1) -> dict:
    """CART order + one line + submit -> SUBMITTED. Returns the submitted order."""
    g_headers = make_guardian_headers(student["guardian_user_id"])
    order = create_cart_order(session_id, student)
    add_line(order, package_id, student, quantity)
    return get_success_data(api_client.submit_order(order["id"], g_headers))


def create_paid_order(session_id, student, package_id, quantity=1) -> dict:
    """Submit + pay -> PAID. Returns the paid order."""
    order = create_submitted_order(session_id, student, package_id, quantity)
    return get_success_data(api_client.pay_order(order["id"], CLERK))


def create_dispatched_shipment_for_order(order_id, **shipment_overrides) -> dict:
    """Create a shipment (with tracking) for a PAID order and dispatch it ->
    DISPATCHED (and the order -> FULFILLED). Returns the shipment."""
    shipment = get_success_data(api_client.create_shipment(
        create_shipment_payload(order_id, **shipment_overrides), CLERK))
    return get_success_data(api_client.dispatch_shipment(shipment["id"], CLERK))


# --------------------------------------------------------------------------- #
# Tier 4: Commission accumulation scenarios
# --------------------------------------------------------------------------- #
def setup_three_paid_orders_ordering_closed(merch_values=(36000, 45000, 45000),
                                            ship=True, **session_overrides) -> dict:
    """Build the canonical three-PAID-order commission scenario and drive the
    session to ORDERING_CLOSED.

    Each order's merchandise_cents equals the corresponding entry in
    `merch_values` (achieved with a single PREMIUM line priced at that value,
    whose subtotal is below the 5000 discount-tier... note: for these large
    values the 5%/10% discount applies, so callers should pass package prices
    that yield the intended merchandise after discount). For the default
    (36000, 45000, 45000) the values are passed as raw package prices and the
    helper does NOT pre-adjust for discount; see the difficulty-design fixtures
    that hard-code prices instead. This generic helper drives prices directly.

    Returns a dict: {session, students, packages, orders, shipments}.
    """
    session = create_session(**session_overrides)
    students, packages, orders, shipments = [], [], [], []
    # Stock one PREMIUM package per distinct price so each order has a clean merch.
    for i, _ in enumerate(merch_values):
        students.append(add_student(
            session["id"], full_name=f"Stu {i}", homeroom=f"H{i}",
            guardian_user_id=f"g{i + 1}"))
    api_client.lock_roster(session["id"], COORD)
    api_client.open_capture(session["id"], PHOTOG)
    for stu in students:
        api_client.mark_absent(stu["id"], PHOTOG)
    api_client.open_gallery(session["id"], COORD)
    for i, price in enumerate(merch_values):
        pkg = add_package(session["id"], sku=f"PKG{i}", name=f"Pkg {i}",
                          tier="PREMIUM", base_price_cents=price)
        packages.append(pkg)
        order = create_paid_order(session["id"], students[i], pkg["id"], quantity=1)
        orders.append(order)
        if ship:
            shipments.append(create_dispatched_shipment_for_order(
                order["id"], tracking_code=f"T{i}"))
    api_client.close_ordering(session["id"], COORD)
    return {"session": session, "students": students, "packages": packages,
            "orders": orders, "shipments": shipments}


def setup_commission_scenario_126000() -> dict:
    """The exact dual-variant commission scenario used by the difficulty design:
    three PAID orders with merchandise 36000 / 45000 / 45000 (total gross 126000),
    each with a DISPATCHED shipment, session in ORDERING_CLOSED.

    Achieved with PREMIUM packages priced 40000, 50000, 50000 (subtotal == merch
    because no discount changes the chosen values? — see below). For a single
    PREMIUM@40000 line: subtotal 40000 -> 5% disc 2000 -> merch 38000, which is
    NOT 36000. To hit merchandise EXACTLY 36000/45000/45000 the difficulty design
    pins package prices 40000/50000/50000; with the 5% tier applied the merch are
    38000/47500/47500. The difficulty-design instance, however, asserts the
    provisional/final commission for raw merch 36000/45000/45000.

    Because the merch must equal the design's stated 36000/45000/45000 exactly,
    this helper is NOT used by the commission tests directly; those tests build
    the scenario inline with the design's pinned prices. This helper is retained
    only as a convenience wrapper around setup_three_paid_orders_ordering_closed.
    """
    return setup_three_paid_orders_ordering_closed(merch_values=(40000, 50000, 50000))


def read_session(session_id, headers=None) -> dict:
    return get_success_data(api_client.get_session(session_id, headers or COORD))


# --------------------------------------------------------------------------- #
# Tier 4b: Retouch credit reservation
# --------------------------------------------------------------------------- #
def setup_matched_photo_capture_open(budget=50000, student_overrides=None,
                                     **session_overrides) -> tuple:
    """Session CAPTURE_OPEN with one matched photo (its student PHOTOGRAPHED).
    Returns (session, student, package, photo)."""
    session, student, package = create_session_capture_open(
        student_overrides=student_overrides, retouch_budget_cents=budget,
        **session_overrides)
    photo = match_photo_for_student(session["id"], student)
    return session, student, package, photo


def create_retouch_requested(photo_id, kind="RETOUCH", **overrides) -> dict:
    """Create a RetouchOrder in REQUESTED against `photo_id`. Returns the order."""
    return get_success_data(api_client.create_retouch_order(
        create_retouch_order_payload(photo_id, kind=kind, **overrides), PHOTOG))


def create_retouch_approved(photo_id, kind="RETOUCH", **overrides) -> dict:
    """Create + approve a RetouchOrder -> APPROVED (credit reserved). Returns it."""
    rt = create_retouch_requested(photo_id, kind=kind, **overrides)
    return get_success_data(api_client.approve_retouch_order(rt["id"], PHOTOG))
