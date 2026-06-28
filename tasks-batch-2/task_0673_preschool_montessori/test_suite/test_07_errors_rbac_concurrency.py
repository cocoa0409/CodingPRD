"""Corner cases for the error catalog (OCC, deposit mismatch), RBAC denials, the
optimistic-concurrency version bump, scheduled no-show, and immediate consistency
(corner-design sections: errors, rbac, cross_cutting_complexity_layers, consistency_model).
PRD §2.1, §2.5, §2.6, §2.10, §3.7, §3.10, §3.12.

Each test translates exactly one corner-design instance.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_classroom_payload, create_staff_assignment_payload, create_payment_payload,
    create_application_payload, accept_offer_payload,
    set_clock, create_tier, create_classroom, create_room_with_staff, assign_staff,
    create_student, enroll_child, application_offered, setup_enrolled_child,
    open_slot, book_slot,
    build_user_headers, make_parent_headers, make_guide_headers, NON_EXISTENT_UUID,
    TEST_USERS, api_client,
)

REGISTRAR = TEST_USERS["registrar_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ─── errors ────────────────────────────────────────────

def test_occ_stale_classroom_version_rejected(api):
    """PRD §2.5: "If that value does not equal the classroom's current version — for example
    because another writer has already added or ended an assignment and thereby advanced the
    classroom's version since the caller last read it — the create is rejected with
    ERR_STALE_CLASSROOM_VERSION (HTTP 412), and no assignment is created."

    Design: Corner/errors/occ_stale_classroom_version_on_second_assignment
    """
    room = create_classroom(name="Room", level="PRIMARY", capacity=5)
    v0 = room["version"]
    # First assignment advances the classroom version off v0.
    assign_staff(room["id"], v0, "Maria")
    # Second assignment reusing the now-stale v0 is rejected.
    res = api.create_staff_assignment(
        create_staff_assignment_payload(room["id"], v0, "Tom"), COMPLIANCE)
    validate_error(res, "ERR_STALE_CLASSROOM_VERSION", expected_status=412)


def test_deposit_amount_mismatch_triggerable(api):
    """PRD §3.7: "its amount_cents must equal the enrollment's deposit_cents exactly; a
    deposit posted at the wrong time or for the wrong amount is rejected with
    ERR_DEPOSIT_AMOUNT_MISMATCH."

    Design: Corner/errors/deposit_amount_mismatch_triggerable
    """
    room, tier, student, enr = setup_enrolled_child()  # deposit_cents 100000, DEPOSIT_DUE
    res = api.create_payment(
        create_payment_payload(enr["id"], "DEPOSIT", 50_000), REGISTRAR)
    validate_error(res, "ERR_DEPOSIT_AMOUNT_MISMATCH", expected_status=422)


# ─── rbac ──────────────────────────────────────────────

def test_parent_cannot_create_classroom(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE."

    Design: Corner/rbac/parent_cannot_create_classroom_forbidden
    """
    res = api.create_classroom(
        create_classroom_payload(name="Room", level="PRIMARY", capacity=5),
        make_parent_headers("parent-1"))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_registrar_cannot_record_assessment(api):
    """PRD §2.10: "Next the system confirms the acting role is permitted the operation,
    failing with ERR_FORBIDDEN_ROLE ... Existence of referenced resources is checked next".

    Design: Corner/rbac/registrar_cannot_record_assessment_forbidden
    """
    # Registrar attempts a Guide-exclusive operation; role check precedes existence.
    res = api.create_assessment_record({
        "student_id": NON_EXISTENT_UUID,
        "enrollment_id": "00000000-0000-4000-8000-000000000001",
        "work_area": "MATHEMATICS", "mastery_level": "INTRODUCED",
        "work_cycle_date": "2026-09-15T00:00:00Z",
    }, REGISTRAR)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_parent_not_owner_cannot_accept_offer(api):
    """PRD §2.1: "When a parent attempts to act on a student they do not own, the request is
    rejected with ERR_NOT_RESOURCE_OWNER. This ownership check guards resubmitting an
    application, accepting an offer, declining an offer, and booking a conference slot."

    Design: Corner/rbac/parent_not_owner_cannot_accept_offer
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="STD", level="PRIMARY", base_annual_cents=1_000_000,
                       deposit_pct=0.10, installments=10)
    room, _ = create_room_with_staff(level="PRIMARY", capacity=5, staff=1)
    student = create_student(parent_user_id="parent-1")
    app = application_offered(student["id"], room["id"], tier["id"],
                              parent_user_id="parent-1")
    # parent-2 does not own the student named by the application.
    res = api.accept_offer(app["id"], accept_offer_payload("2026-09-01T00:00:00Z"),
                           make_parent_headers("parent-2"))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role does not name a role the
    system recognizes, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    res = api.list_classrooms(build_user_headers("someone", "NotARole"))
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# ─── cross_cutting_complexity_layers ───────────────────

def test_staff_assignment_increments_classroom_version(api):
    """PRD §3.10: "Creating it increments the classroom's assigned_staff_count, recomputes
    the classroom's compliance_status, and increments the classroom's version by one."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_each_staff_assignment
    """
    room = create_classroom(name="Room", level="PRIMARY", capacity=5)
    assert room["version"] == 1
    assign_staff(room["id"], room["version"], "Maria")
    after = get_success_data(api.get_classroom(room["id"], COMPLIANCE))
    assert after["version"] == 2, f"got version {after['version']}"
    assert after["assigned_staff_count"] == 1, f"got {after['assigned_staff_count']}"


def test_no_show_succeeds_after_clock_advances(api):
    """PRD §3.12: "The guide may mark a booked slot as a no-show, BOOKED → NO_SHOW, but only
    once the current logical clock has reached or passed the slot's end_at."

    Design: Corner/cross_cutting_complexity_layers/scheduled_no_show_after_clock_advances
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="STD", level="PRIMARY", base_annual_cents=1_000_000,
                       deposit_pct=0.10, installments=10)
    room, _ = create_room_with_staff(level="PRIMARY", capacity=5, staff=1)
    student = create_student(parent_user_id="parent-1")
    enroll_child(student["id"], room["id"], tier["id"], parent_user_id="parent-1")
    slot = open_slot(room["id"], guide_user_id="guide-1",
                     start_at="2026-10-01T15:00:00Z", end_at="2026-10-01T15:30:00Z")
    book_slot(slot["id"], student["id"], parent_user_id="parent-1")
    # Advance clock to or beyond end_at.
    set_clock("2026-10-01T16:00:00Z")
    res = api.no_show_slot(slot["id"], make_guide_headers("guide-1"))
    no_show = validate_success(res, 200)
    assert no_show["status"] == "NO_SHOW", f"got {no_show['status']}"


# ─── consistency_model ─────────────────────────────────

def test_immediate_consistency_placed_count_visible(api):
    """PRD §3.4: "increments the room's placed_count by one and recomputes the room's
    compliance_status".
    PRD §2.4: "When a placement or withdrawal causes a classroom's placed_count or
    compliance_status to be recomputed ... that recomputation refreshes the resource's
    updated_at and increments its version".

    Design: Corner/consistency_model/immediate_consistency_counts_visible_same_request
    """
    room, tier, student, enr = setup_enrolled_child(capacity=5)
    # Immediately read the classroom; placed_count must already reflect the new enrollment.
    after = get_success_data(api.get_classroom(room["id"], REGISTRAR))
    assert after["placed_count"] == 1, f"got {after['placed_count']}"
