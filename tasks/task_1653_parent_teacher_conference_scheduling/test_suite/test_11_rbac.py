"""Role-based access control: authentication, role gates, entity-backed
ownership scoping, and the SchoolAdmin superset."""
from test_helpers import (
    ApiErrorId,
    NO_AUTH_HEADERS,
    add_family,
    add_interpreter,
    add_student,
    book_slot,
    create_family_payload,
    create_student_payload,
    create_window_payload,
    get_success_data,
    guardian_headers,
    interpreter_headers,
    make_teacher_headers,
    read_window,
    request_for_booking,
    scenario_round_trip,
    set_clock,
    setup_family_with_students,
    setup_in_progress_booking,
    setup_window_at_stage,
    lock_window,
    start_window,
    validate_error,
    validate_success,
)


def test_missing_auth_header_unauthenticated(api):
    """PRD 2.1: "All interactions with the API must be authenticated through a
    pair of mandatory HTTP headers. Each request must include `X-User-ID` to
    identify the acting user and `X-User-Role` to specify their operational
    capacity. The system recognizes exactly five roles: `SchoolAdmin`,
    `FrontOfficeStaff`, `Teacher`, `FamilyGuardian`, and `Interpreter`. A
    request whose headers are missing or whose role is not one of these five is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/missing_auth_header_unauthenticated
    """
    response = api.list_windows(NO_AUTH_HEADERS)
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_family_cannot_create_window_forbidden(api):
    """PRD 2.1: "When the role is recognized but is not listed among the roles
    permitted for the target endpoint, the request is rejected with
    `ERR_FORBIDDEN`."
    PRD 4: "| POST | `/conf/windows` | Create a conference window (status DRAFT) | SchoolAdmin |"

    Design: Corner/rbac/family_cannot_create_window_forbidden
    """
    family = add_family()
    response = api.create_window(create_window_payload(), guardian_headers(family))
    validate_error(response, ApiErrorId.ERR_FORBIDDEN, 403)


def test_family_cannot_book_other_familys_student(api):
    """PRD 3.4: "The booking's `window_id` and `teacher_id` are derived from
    the slot, and its `family_id` is derived from the student's owning family —
    a guardian may only book for a student of their own family, otherwise
    `ERR_FORBIDDEN`."
    PRD 2.1: "An entity-backed caller acting on a resource it does not own is
    rejected with `ERR_FORBIDDEN`, even when the role itself is otherwise
    permitted on that endpoint."

    Design: Corner/rbac/family_cannot_book_other_familys_student
    """
    ctx = setup_window_at_stage("BOOKING_OPEN")
    teacher_id = ctx["teachers"][0]["id"]
    owner = setup_family_with_students(ctx, 1)
    stranger = add_family()
    slot = ctx["teacher_slots"][teacher_id][0]

    response = api.create_booking(
        {"slot_id": slot["id"], "student_id": owner["students"][0]["id"],
         "channel": "IN_PERSON"},
        guardian_headers(stranger),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN, 403)


def test_teacher_cannot_mark_others_attendance_forbidden(api):
    """PRD 3.8: "A `Teacher` marks only their own bookings (the booking's
    `teacher_id` must match the caller), while `FrontOfficeStaff` and
    `SchoolAdmin` mark any booking."
    PRD 2.1: "An entity-backed caller acting on a resource it does not own is
    rejected with `ERR_FORBIDDEN`, even when the role itself is otherwise
    permitted on that endpoint."

    Design: Corner/rbac/teacher_cannot_mark_others_attendance_forbidden
    """
    ctx = setup_window_at_stage("BOOKING_OPEN", teacher_specs=[{}, {}])
    t1, t2 = ctx["teachers"]
    party = setup_family_with_students(ctx, 1, teacher_id=t1["id"])
    slot = ctx["teacher_slots"][t1["id"]][0]
    booking = book_slot(slot["id"], party["students"][0]["id"], party["guardian"])

    set_clock("2026-10-02T00:00:00Z")
    lock_window(ctx["window"]["id"])
    start_window(ctx["window"]["id"])
    set_clock("2026-10-05T15:30:00Z")

    forbidden = api.mark_attendance(
        booking["id"], {"outcome": "ATTENDED"}, make_teacher_headers(t2["id"])
    )
    validate_error(forbidden, ApiErrorId.ERR_FORBIDDEN, 403)

    marked = validate_success(api.mark_attendance(
        booking["id"], {"outcome": "ATTENDED"}, make_teacher_headers(t1["id"])
    ))
    assert marked["status"] == "COMPLETED"


def test_interpreter_cannot_accept_others_request_forbidden(api, front_office_headers):
    """PRD 3.7: "Accepting — `ASSIGNED` to `CONFIRMED` — is permitted only to
    the interpreter whose `id` matches the request's `interpreter_id`
    (otherwise `ERR_FORBIDDEN`) and only from `ASSIGNED` status (otherwise
    `ERR_INVALID_STATE`)."

    Design: Corner/rbac/interpreter_cannot_accept_others_request_forbidden
    """
    ctx = scenario_round_trip()
    other = add_interpreter(full_name="I Two")
    get_success_data(api.assign_interpreter(
        ctx["request"]["id"], {"interpreter_id": ctx["interpreter"]["id"]},
        front_office_headers,
    ))

    forbidden = api.accept_request(ctx["request"]["id"], interpreter_headers(other))
    validate_error(forbidden, ApiErrorId.ERR_FORBIDDEN, 403)

    accepted = validate_success(api.accept_request(
        ctx["request"]["id"], interpreter_headers(ctx["interpreter"])
    ))
    assert accepted["status"] == "CONFIRMED"


def test_family_cannot_read_other_family_record(api):
    """PRD 3.3: "Contact fields — `primary_guardian_name`, `email`, `phone`,
    `preferred_language` — may be updated later; a `FamilyGuardian` caller may
    read and update only their own family record."
    PRD 2.1: "An entity-backed caller acting on a resource it does not own is
    rejected with `ERR_FORBIDDEN`, even when the role itself is otherwise
    permitted on that endpoint."

    Design: Corner/rbac/family_cannot_read_other_family_record
    """
    family_one = add_family(email="g1@x.com")
    family_two = add_family(email="g2@x.com")

    forbidden = api.get_family(family_two["id"], guardian_headers(family_one))
    validate_error(forbidden, ApiErrorId.ERR_FORBIDDEN, 403)

    own = validate_success(api.get_family(family_one["id"], guardian_headers(family_one)))
    assert own["email"] == "g1@x.com"


def test_school_admin_can_perform_staff_operation(api, school_admin_headers):
    """PRD 2.1: "In terms of capability, a `SchoolAdmin` holds a superset of
    `FrontOfficeStaff` operations and additionally drives the window lifecycle,
    teacher and interpreter management, slot generation, ops runs, and the
    logical clock."

    Design: Corner/rbac/school_admin_can_perform_staff_operation
    """
    family = validate_success(
        api.create_family(create_family_payload(), school_admin_headers), 201
    )
    student = validate_success(
        api.create_student(family["id"], create_student_payload(), school_admin_headers),
        201,
    )
    assert student["family_id"] == family["id"]
    assert student["enrollment_status"] == "ENROLLED"
