"""Composite setup helpers.

Every test runs against an empty database (the runner restarts the server per
test), so each helper builds its preconditions from scratch using only
endpoints the PRD declares. Setup calls use the lenient `get_success_data`
validator so a broken precondition surfaces as a clear "Setup step failed".
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_CLOSE, CLOCK_CONFERENCE, CLOCK_OPEN
from .factories import (
    create_booking_payload,
    create_family_payload,
    create_interpreter_payload,
    create_student_payload,
    create_teacher_link_payload,
    create_teacher_payload,
    create_waitlist_entry_payload,
    create_window_payload,
)
from .test_users import (
    make_family_guardian_headers,
    make_front_office_headers,
    make_interpreter_headers,
    make_school_admin_headers,
    make_teacher_headers,
)

ADMIN = make_school_admin_headers()
STAFF = make_front_office_headers()


# ---------------------------------------------------------------------------
# Tier 0 — primitive steps
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> Dict[str, Any]:
    """Advance the logical clock (SchoolAdmin only, PRD 2.4)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_window(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_window(create_window_payload(**overrides), ADMIN))


def add_teacher(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_teacher(create_teacher_payload(**overrides), ADMIN))


def add_family(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_family(create_family_payload(**overrides), STAFF))


def add_student(family_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_student(family_id, create_student_payload(**overrides), STAFF)
    )


def add_link(student_id: str, teacher_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_teacher_link(
            student_id, create_teacher_link_payload(teacher_id, **overrides), STAFF
        )
    )


def add_interpreter(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_interpreter(create_interpreter_payload(**overrides), ADMIN)
    )


def publish_window(window_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.publish_window(window_id, ADMIN))


def generate_slots(window_id: str, expected_window_version: int) -> Dict[str, Any]:
    return get_success_data(
        api_client.generate_slots(
            window_id, {"expected_window_version": expected_window_version}, ADMIN
        )
    )


def open_booking(window_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.open_booking(window_id, ADMIN))


def lock_window(window_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.lock_window(window_id, ADMIN))


def start_window(window_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.start_window(window_id, ADMIN))


def complete_window(window_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.complete_window(window_id, ADMIN))


def run_ops(window_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.run_ops(window_id, ADMIN))


def read_window(window_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_window(window_id, ADMIN))


def list_window_slots(window_id: str, **filters) -> List[Dict[str, Any]]:
    return get_success_data(api_client.list_window_slots(window_id, ADMIN, params=filters))


def list_teacher_slots(teacher_id: str, window_id: str) -> List[Dict[str, Any]]:
    return get_success_data(
        api_client.list_teacher_slots(teacher_id, ADMIN, params={"window_id": window_id})
    )


def guardian_headers(family: Dict[str, Any]) -> Dict[str, str]:
    """Identity-threaded guardian headers for an ownership-gated call."""
    return make_family_guardian_headers(family["id"])


def teacher_headers(teacher: Dict[str, Any]) -> Dict[str, str]:
    return make_teacher_headers(teacher["id"])


def interpreter_headers(interpreter: Dict[str, Any]) -> Dict[str, str]:
    return make_interpreter_headers(interpreter["id"])


def book_slot(slot_id: str, student_id: str, headers: Dict[str, str],
              channel: str = "IN_PERSON",
              interpreter_language: Optional[str] = None) -> Dict[str, Any]:
    payload = create_booking_payload(slot_id, student_id, channel)
    if interpreter_language is not None:
        payload["interpreter_language"] = interpreter_language
    return get_success_data(api_client.create_booking(payload, headers))


def request_for_booking(booking_id: str) -> Dict[str, Any]:
    """Fetch the (single) interpreter request attached to a booking."""
    data = get_success_data(
        api_client.list_interpreter_requests(STAFF, params={"booking_id": booking_id})
    )
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one interpreter request for booking {booking_id}"
    )
    return data[0]


# ---------------------------------------------------------------------------
# Tier 1 — window state progression
# ---------------------------------------------------------------------------


def setup_window_at_stage(
    stage: str = "BOOKING_OPEN",
    window_overrides: Optional[Dict[str, Any]] = None,
    teacher_specs: Optional[List[Dict[str, Any]]] = None,
    clock: str = CLOCK_OPEN,
) -> Dict[str, Any]:
    """Create a window plus teachers and walk the lifecycle to `stage`.

    stage is one of DRAFT, PUBLISHED (slots generated), BOOKING_OPEN, LOCKED,
    IN_PROGRESS, COMPLETED. Returns a context dict with the window, teachers,
    per-teacher slots (start_at ascending per PRD 2.3), and the window slot
    list (empty unless generation ran).
    """
    overrides = dict(window_overrides or {})
    set_clock(clock)
    window = create_window(**overrides)
    specs = teacher_specs if teacher_specs is not None else [{}]
    teachers = [add_teacher(**spec) for spec in specs]

    ctx: Dict[str, Any] = {
        "window": window,
        "teachers": teachers,
        "teacher_slots": {},
        "slots": [],
    }
    if stage == "DRAFT":
        return ctx

    published = publish_window(window["id"])
    generated = generate_slots(window["id"], published["version"])
    ctx["window"] = generated
    ctx["slots"] = list_window_slots(window["id"])
    for teacher in teachers:
        ctx["teacher_slots"][teacher["id"]] = list_teacher_slots(teacher["id"], window["id"])
    if stage == "PUBLISHED":
        return ctx

    ctx["window"] = open_booking(window["id"])
    if stage == "BOOKING_OPEN":
        return ctx

    set_clock(CLOCK_CLOSE)
    ctx["window"] = lock_window(window["id"])
    if stage == "LOCKED":
        return ctx

    ctx["window"] = start_window(window["id"])
    if stage == "IN_PROGRESS":
        return ctx

    ctx["window"] = complete_window(window["id"])
    return ctx


def setup_family_with_students(
    ctx: Dict[str, Any],
    count: int,
    teacher_id: Optional[str] = None,
    family_overrides: Optional[Dict[str, Any]] = None,
    link_overrides: Optional[Dict[str, Any]] = None,
    grade_levels: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Register a family plus `count` students, each linked to `teacher_id`
    (default: the context's first teacher). Returns family/students/headers.

    For an ELEMENTARY window the link defaults to `is_homeroom` true, since
    elementary families book a single homeroom conference (PRD 3.1/3.4);
    pass explicit link_overrides to change that."""
    teacher_id = teacher_id or ctx["teachers"][0]["id"]
    is_elementary = ctx["window"].get("format") == "ELEMENTARY"
    effective_link: Dict[str, Any] = {"is_homeroom": True} if is_elementary else {}
    effective_link.update(link_overrides or {})
    family = add_family(**(family_overrides or {}))
    students = []
    for i in range(count):
        grade = grade_levels[i] if grade_levels else i + 1
        student = add_student(family["id"], grade_level=grade)
        add_link(student["id"], teacher_id, **effective_link)
        students.append(student)
    ctx.setdefault("families", []).append(family)
    return {
        "family": family,
        "students": students,
        "guardian": guardian_headers(family),
    }


# ---------------------------------------------------------------------------
# Tier 2 — common composite scenarios
# ---------------------------------------------------------------------------


def setup_booked_slot(window_overrides: Optional[Dict[str, Any]] = None,
                      teacher_specs: Optional[List[Dict[str, Any]]] = None,
                      interpreter_language: Optional[str] = None,
                      channel: str = "IN_PERSON") -> Dict[str, Any]:
    """BOOKING_OPEN window + one family + one linked student + one CONFIRMED
    booking on slot 0. The most common setup in the suite."""
    ctx = setup_window_at_stage("BOOKING_OPEN", window_overrides, teacher_specs)
    party = setup_family_with_students(ctx, 1)
    headers = party["guardian"]
    slot = ctx["teacher_slots"][ctx["teachers"][0]["id"]][0]
    booking = book_slot(slot["id"], party["students"][0]["id"], headers,
                        channel=channel, interpreter_language=interpreter_language)
    ctx.update({
        "family": party["family"],
        "student": party["students"][0],
        "guardian": headers,
        "slot": slot,
        "booking": booking,
    })
    return ctx


def setup_in_progress_booking(clock: str = CLOCK_CONFERENCE) -> Dict[str, Any]:
    """A CONFIRMED booking on slot 0 inside an IN_PROGRESS window, with the
    logical clock already past the slot's start (15:00) so attendance can be
    marked. Slot 0 runs 15:00-15:20; the default clock is 15:30."""
    ctx = setup_booked_slot()
    set_clock(CLOCK_CLOSE)
    lock_window(ctx["window"]["id"])
    start_window(ctx["window"]["id"])
    set_clock(clock)
    ctx["window"] = read_window(ctx["window"]["id"])
    return ctx


def setup_offered_entry(channel_pref: str = "EITHER",
                        offer_clock: str = "2026-09-10T10:00:00Z") -> Dict[str, Any]:
    """A WAITING entry promoted to OFFERED on slot 0 after the incumbent
    family cancels. Returns the entry, the offered slot, and both families."""
    ctx = setup_window_at_stage("BOOKING_OPEN")
    teacher_id = ctx["teachers"][0]["id"]
    slot0 = ctx["teacher_slots"][teacher_id][0]

    first = setup_family_with_students(ctx, 1)
    incumbent = book_slot(slot0["id"], first["students"][0]["id"], first["guardian"])

    second = setup_family_with_students(ctx, 1)
    entry = get_success_data(api_client.create_waitlist_entry(
        create_waitlist_entry_payload(ctx["window"]["id"], second["students"][0]["id"],
                                      teacher_id, channel_pref),
        second["guardian"],
    ))

    set_clock(offer_clock)
    get_success_data(api_client.cancel_booking(incumbent["id"], {}, first["guardian"]))

    ctx.update({
        "slot0": slot0,
        "incumbent": incumbent,
        "first_family": first["family"],
        "first_guardian": first["guardian"],
        "second_family": second["family"],
        "second_student": second["students"][0],
        "second_guardian": second["guardian"],
        "entry": entry,
    })
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 — deep scenario builders (one per heavy targeting-index recipe)
# ---------------------------------------------------------------------------


def scenario_utilization() -> Dict[str, Any]:
    """BOOKING_OPEN window (teacher daily cap 6); one family with six linked
    students; students 1-4 CONFIRMED on slots 0-3; students 5-6 WAITING."""
    ctx = setup_window_at_stage("BOOKING_OPEN")
    teacher_id = ctx["teachers"][0]["id"]
    slots = ctx["teacher_slots"][teacher_id]
    party = setup_family_with_students(ctx, 6, grade_levels=[3, 4, 5, 6, 7, 8])
    bookings = [
        book_slot(slots[i]["id"], party["students"][i]["id"], party["guardian"])
        for i in range(4)
    ]
    entries = [
        get_success_data(api_client.create_waitlist_entry(
            create_waitlist_entry_payload(ctx["window"]["id"], party["students"][i]["id"],
                                          teacher_id, "EITHER"),
            party["guardian"],
        ))
        for i in (4, 5)
    ]
    ctx.update({"party": party, "bookings": bookings, "entries": entries})
    return ctx


def scenario_risk_marks() -> Dict[str, Any]:
    """IN_PROGRESS window (strike threshold 5); one family with three linked
    students and bookings on slots 0-2; marks applied: NO_SHOW, LATE, EXCUSED."""
    ctx = setup_window_at_stage(
        "BOOKING_OPEN", window_overrides={"no_show_strike_threshold": 5}
    )
    teacher_id = ctx["teachers"][0]["id"]
    slots = ctx["teacher_slots"][teacher_id]
    party = setup_family_with_students(ctx, 3, grade_levels=[3, 4, 5])
    bookings = [
        book_slot(slots[i]["id"], party["students"][i]["id"], party["guardian"])
        for i in range(3)
    ]
    set_clock(CLOCK_CLOSE)
    lock_window(ctx["window"]["id"])
    start_window(ctx["window"]["id"])
    set_clock("2026-10-05T15:30:00Z")
    get_success_data(api_client.mark_attendance(bookings[0]["id"], {"outcome": "NO_SHOW"}, STAFF))
    set_clock("2026-10-05T15:50:00Z")
    get_success_data(api_client.mark_attendance(bookings[1]["id"], {"outcome": "LATE"}, STAFF))
    set_clock("2026-10-05T16:15:00Z")
    get_success_data(api_client.mark_attendance(bookings[2]["id"], {"outcome": "EXCUSED"}, STAFF))
    ctx.update({"party": party, "bookings": bookings})
    return ctx


def scenario_compactness() -> Dict[str, Any]:
    """BOOKING_OPEN window; three ELEMENTARY teachers supporting both channels;
    one family whose students A, B, C are homeroom-linked to T1, T2, T3
    respectively. Tests place the bookings as the trigger."""
    ctx = setup_window_at_stage(
        "BOOKING_OPEN",
        teacher_specs=[
            {"supports_in_person": True, "supports_virtual": True},
            {"supports_in_person": True, "supports_virtual": True},
            {"supports_in_person": True, "supports_virtual": True},
        ],
    )
    family = add_family()
    students = [add_student(family["id"], grade_level=g) for g in (2, 4, 6)]
    for student, teacher in zip(students, ctx["teachers"]):
        add_link(student["id"], teacher["id"], is_homeroom=True)
    ctx.update({
        "family": family,
        "students": students,
        "guardian": guardian_headers(family),
    })
    return ctx


def scenario_pay_rounding() -> Dict[str, Any]:
    """Two families each holding a 20-minute booking with interpreter_language
    'es'; both requests ASSIGNED then CONFIRMED by one interpreter (6000
    cents/hour)."""
    ctx = setup_window_at_stage("BOOKING_OPEN")
    teacher_id = ctx["teachers"][0]["id"]
    slots = ctx["teacher_slots"][teacher_id]
    interpreter = add_interpreter()
    requests = []
    for i, slot in enumerate((slots[0], slots[1])):
        party = setup_family_with_students(
            ctx, 1, family_overrides={"preferred_language": "es"}
        )
        booking = book_slot(slot["id"], party["students"][0]["id"], party["guardian"],
                            interpreter_language="es")
        request = request_for_booking(booking["id"])
        get_success_data(api_client.assign_interpreter(
            request["id"], {"interpreter_id": interpreter["id"]}, STAFF))
        get_success_data(api_client.accept_request(
            request["id"], interpreter_headers(interpreter)))
        requests.append(request)
    ctx.update({"interpreter": interpreter, "requests": requests})
    return ctx


def scenario_capacity() -> Dict[str, Any]:
    """Interpreter with base 100 / max_consecutive 30; five 20-minute bookings
    with 'es' requests on slots 0, 2, 4, 6, 7; r1-r4 ASSIGNED (committed 80),
    r5 still REQUESTED."""
    ctx = setup_window_at_stage("BOOKING_OPEN")
    teacher_id = ctx["teachers"][0]["id"]
    slots = ctx["teacher_slots"][teacher_id]
    interpreter = add_interpreter(max_consecutive_minutes=30, base_minutes_per_window=100)
    party = setup_family_with_students(
        ctx, 5, family_overrides={"preferred_language": "es"}, grade_levels=[1, 2, 3, 4, 5]
    )
    requests = []
    for i, slot_idx in enumerate((0, 2, 4, 6, 7)):
        booking = book_slot(slots[slot_idx]["id"], party["students"][i]["id"],
                            party["guardian"], interpreter_language="es")
        requests.append(request_for_booking(booking["id"]))
    for request in requests[:4]:
        get_success_data(api_client.assign_interpreter(
            request["id"], {"interpreter_id": interpreter["id"]}, STAFF))
    ctx.update({"interpreter": interpreter, "requests": requests, "party": party})
    return ctx


def scenario_decline_reassign() -> Dict[str, Any]:
    """Two 'es' interpreters (i1 created before i2) and one booking whose
    request is REQUESTED."""
    ctx = setup_window_at_stage("BOOKING_OPEN")
    interpreter_one = add_interpreter(full_name="I One")
    interpreter_two = add_interpreter(full_name="I Two")
    party = setup_family_with_students(
        ctx, 1, family_overrides={"preferred_language": "es"}
    )
    slot = ctx["teacher_slots"][ctx["teachers"][0]["id"]][0]
    booking = book_slot(slot["id"], party["students"][0]["id"], party["guardian"],
                        interpreter_language="es")
    request = request_for_booking(booking["id"])
    ctx.update({
        "i1": interpreter_one,
        "i2": interpreter_two,
        "booking": booking,
        "request": request,
        "party": party,
    })
    return ctx


def scenario_offer_cycle() -> Dict[str, Any]:
    """Family A holds CONFIRMED bookings on slots 0 and 1; family B's student
    has a WAITING entry for the teacher."""
    ctx = setup_window_at_stage("BOOKING_OPEN")
    teacher_id = ctx["teachers"][0]["id"]
    slots = ctx["teacher_slots"][teacher_id]
    party_a = setup_family_with_students(ctx, 2, grade_levels=[1, 2])
    booking_a1 = book_slot(slots[0]["id"], party_a["students"][0]["id"], party_a["guardian"])
    booking_a2 = book_slot(slots[1]["id"], party_a["students"][1]["id"], party_a["guardian"])
    party_b = setup_family_with_students(ctx, 1, grade_levels=[3])
    entry = get_success_data(api_client.create_waitlist_entry(
        create_waitlist_entry_payload(ctx["window"]["id"], party_b["students"][0]["id"],
                                      teacher_id, "EITHER"),
        party_b["guardian"],
    ))
    ctx.update({
        "party_a": party_a,
        "party_b": party_b,
        "booking_a1": booking_a1,
        "booking_a2": booking_a2,
        "entry": entry,
    })
    return ctx


def scenario_no_show_cascade(threshold: int = 2) -> Dict[str, Any]:
    """IN_PROGRESS window with the given strike threshold. One family with
    three linked students: b1 (slot 0) already marked NO_SHOW at 15:30, b2
    (slot 1) CONFIRMED, b3 (slot 2, starts 15:50) CONFIRMED with a REQUESTED
    interpreter request. Clock is 2026-10-05T15:46:00Z on return."""
    ctx = setup_window_at_stage(
        "BOOKING_OPEN", window_overrides={"no_show_strike_threshold": threshold}
    )
    teacher_id = ctx["teachers"][0]["id"]
    slots = ctx["teacher_slots"][teacher_id]
    party = setup_family_with_students(
        ctx, 3, family_overrides={"preferred_language": "es"}, grade_levels=[1, 2, 3]
    )
    b1 = book_slot(slots[0]["id"], party["students"][0]["id"], party["guardian"])
    b2 = book_slot(slots[1]["id"], party["students"][1]["id"], party["guardian"])
    b3 = book_slot(slots[2]["id"], party["students"][2]["id"], party["guardian"],
                   interpreter_language="es")
    request3 = request_for_booking(b3["id"])
    set_clock(CLOCK_CLOSE)
    lock_window(ctx["window"]["id"])
    start_window(ctx["window"]["id"])
    set_clock("2026-10-05T15:30:00Z")
    get_success_data(api_client.mark_attendance(b1["id"], {"outcome": "NO_SHOW"}, STAFF))
    set_clock("2026-10-05T15:46:00Z")
    ctx.update({
        "party": party, "b1": b1, "b2": b2, "b3": b3, "request3": request3,
        "slots": slots,
    })
    return ctx


def scenario_teacher_deactivation() -> Dict[str, Any]:
    """BOOKING_OPEN window; teacher T2 with bookings from families C (slot 0,
    'es' request ASSIGNED to interpreter I) and D (slot 1); family E's student
    WAITING on the waitlist for T2."""
    ctx = setup_window_at_stage("BOOKING_OPEN", teacher_specs=[{"full_name": "T Two"}])
    teacher = ctx["teachers"][0]
    slots = ctx["teacher_slots"][teacher["id"]]
    interpreter = add_interpreter()
    party_c = setup_family_with_students(
        ctx, 1, family_overrides={"preferred_language": "es"}, grade_levels=[1]
    )
    booking_c = book_slot(slots[0]["id"], party_c["students"][0]["id"],
                          party_c["guardian"], interpreter_language="es")
    request_c = request_for_booking(booking_c["id"])
    get_success_data(api_client.assign_interpreter(
        request_c["id"], {"interpreter_id": interpreter["id"]}, STAFF))
    party_d = setup_family_with_students(ctx, 1, grade_levels=[2])
    booking_d = book_slot(slots[1]["id"], party_d["students"][0]["id"], party_d["guardian"])
    party_e = setup_family_with_students(ctx, 1, grade_levels=[3])
    entry_e = get_success_data(api_client.create_waitlist_entry(
        create_waitlist_entry_payload(ctx["window"]["id"], party_e["students"][0]["id"],
                                      teacher["id"], "EITHER"),
        party_e["guardian"],
    ))
    ctx.update({
        "teacher": teacher,
        "interpreter": interpreter,
        "booking_c": booking_c,
        "booking_d": booking_d,
        "request_c": request_c,
        "entry_e": entry_e,
    })
    return ctx


def scenario_locked_cancel() -> Dict[str, Any]:
    """A CONFIRMED booking on slot 0 inside a LOCKED window; the logical clock
    (2026-10-04T16:00Z) is also past the 24-hour family-cancel cutoff for the
    slot (starts 2026-10-05T15:00Z)."""
    ctx = setup_booked_slot()
    set_clock(CLOCK_CLOSE)
    lock_window(ctx["window"]["id"])
    set_clock("2026-10-04T16:00:00Z")
    ctx["window"] = read_window(ctx["window"]["id"])
    return ctx


def scenario_zero_buffer_secondary(interpreter_overrides: Optional[Dict[str, Any]] = None
                                   ) -> Dict[str, Any]:
    """SECONDARY window with buffer_minutes 0 over 15:00-16:20 (four adjacent
    20-minute slots per teacher) and teachers TA, TB. Returns without any
    bookings; callers place them."""
    ctx = setup_window_at_stage(
        "BOOKING_OPEN",
        window_overrides={
            "name": "ZeroBuf",
            "format": "SECONDARY",
            "buffer_minutes": 0,
            "day_windows": [{
                "date": "2026-10-05",
                "start_at": "2026-10-05T15:00:00Z",
                "end_at": "2026-10-05T16:20:00Z",
            }],
        },
        teacher_specs=[
            {"full_name": "TA", "grade_band": "SECONDARY", "subjects": ["math"]},
            {"full_name": "TB", "grade_band": "SECONDARY", "subjects": ["eng"]},
        ],
    )
    interpreter = add_interpreter(**(interpreter_overrides or {}))
    ctx["interpreter"] = interpreter
    return ctx


def scenario_fatigue() -> Dict[str, Any]:
    """Zero-buffer SECONDARY window; interpreter base 30 / max_consecutive 30.
    r1 (TA slot 0, 15:00-15:20) already ASSIGNED; r2 (TB slot 1, 15:20-15:40)
    still REQUESTED."""
    ctx = scenario_zero_buffer_secondary(
        {"max_consecutive_minutes": 30, "base_minutes_per_window": 30}
    )
    teacher_a, teacher_b = ctx["teachers"]
    slot_a0 = ctx["teacher_slots"][teacher_a["id"]][0]
    slot_b1 = ctx["teacher_slots"][teacher_b["id"]][1]
    party_a = setup_family_with_students(
        ctx, 1, teacher_id=teacher_a["id"],
        family_overrides={"preferred_language": "es"}, grade_levels=[9],
    )
    party_b = setup_family_with_students(
        ctx, 1, teacher_id=teacher_b["id"],
        family_overrides={"preferred_language": "es"}, grade_levels=[10],
    )
    booking_a = book_slot(slot_a0["id"], party_a["students"][0]["id"],
                          party_a["guardian"], interpreter_language="es")
    booking_b = book_slot(slot_b1["id"], party_b["students"][0]["id"],
                          party_b["guardian"], interpreter_language="es")
    r1 = request_for_booking(booking_a["id"])
    r2 = request_for_booking(booking_b["id"])
    get_success_data(api_client.assign_interpreter(
        r1["id"], {"interpreter_id": ctx["interpreter"]["id"]}, STAFF))
    ctx.update({"r1": r1, "r2": r2, "booking_a": booking_a, "booking_b": booking_b})
    return ctx


def scenario_strike_boundary(threshold: int = 2) -> Dict[str, Any]:
    """IN_PROGRESS window with the given strike threshold; one family with two
    linked students holding CONFIRMED bookings on slots 0 and 1; clock 15:30."""
    ctx = setup_window_at_stage(
        "BOOKING_OPEN", window_overrides={"no_show_strike_threshold": threshold}
    )
    teacher_id = ctx["teachers"][0]["id"]
    slots = ctx["teacher_slots"][teacher_id]
    party = setup_family_with_students(ctx, 2, grade_levels=[1, 2])
    b1 = book_slot(slots[0]["id"], party["students"][0]["id"], party["guardian"])
    b2 = book_slot(slots[1]["id"], party["students"][1]["id"], party["guardian"])
    set_clock(CLOCK_CLOSE)
    lock_window(ctx["window"]["id"])
    start_window(ctx["window"]["id"])
    set_clock("2026-10-05T15:30:00Z")
    ctx.update({"party": party, "b1": b1, "b2": b2, "slots": slots})
    return ctx


def scenario_day_cap(window_cap: int = 2,
                     teacher_override: Optional[int] = None) -> Dict[str, Any]:
    """BOOKING_OPEN window with the given teacher daily cap (or a teacher-level
    override); one family with three homeroom-linked students."""
    teacher_specs = None
    if teacher_override is not None:
        teacher_specs = [{"daily_conf_cap_override": teacher_override}]
    ctx = setup_window_at_stage(
        "BOOKING_OPEN",
        window_overrides={"teacher_daily_conf_cap": window_cap},
        teacher_specs=teacher_specs,
    )
    teacher_id = ctx["teachers"][0]["id"]
    party = setup_family_with_students(ctx, 3, grade_levels=[1, 2, 3])
    ctx.update({"party": party, "slots": ctx["teacher_slots"][teacher_id]})
    return ctx


def scenario_inactive_interpreter() -> Dict[str, Any]:
    """A booking carrying an 'es' interpreter request; the only interpreter
    has been patched to INACTIVE."""
    ctx = setup_window_at_stage("BOOKING_OPEN")
    interpreter = add_interpreter()
    get_success_data(api_client.patch_interpreter(interpreter["id"], {"status": "INACTIVE"}, ADMIN))
    interpreter["status"] = "INACTIVE"
    party = setup_family_with_students(
        ctx, 1, family_overrides={"preferred_language": "es"}
    )
    slot = ctx["teacher_slots"][ctx["teachers"][0]["id"]][0]
    booking = book_slot(slot["id"], party["students"][0]["id"], party["guardian"],
                        interpreter_language="es")
    request = request_for_booking(booking["id"])
    ctx.update({"interpreter": interpreter, "booking": booking, "request": request,
                "party": party})
    return ctx


def scenario_overlap() -> Dict[str, Any]:
    """Zero-buffer SECONDARY window; interpreter base 200 / max_consecutive 120.
    r1 (TA slot 0, 15:00-15:20) already ASSIGNED; r2 (TB slot 1, 15:20-15:40)
    and r3 (TB slot 0, 15:00-15:20) still REQUESTED."""
    ctx = scenario_zero_buffer_secondary(
        {"max_consecutive_minutes": 120, "base_minutes_per_window": 200}
    )
    teacher_a, teacher_b = ctx["teachers"]
    slot_a0 = ctx["teacher_slots"][teacher_a["id"]][0]
    slot_b0 = ctx["teacher_slots"][teacher_b["id"]][0]
    slot_b1 = ctx["teacher_slots"][teacher_b["id"]][1]
    party_a = setup_family_with_students(
        ctx, 1, teacher_id=teacher_a["id"],
        family_overrides={"preferred_language": "es"}, grade_levels=[9],
    )
    party_b = setup_family_with_students(
        ctx, 2, teacher_id=teacher_b["id"],
        family_overrides={"preferred_language": "es"}, grade_levels=[10, 11],
    )
    booking_a = book_slot(slot_a0["id"], party_a["students"][0]["id"],
                          party_a["guardian"], interpreter_language="es")
    booking_b1 = book_slot(slot_b1["id"], party_b["students"][0]["id"],
                           party_b["guardian"], interpreter_language="es")
    booking_b2 = book_slot(slot_b0["id"], party_b["students"][1]["id"],
                           party_b["guardian"], interpreter_language="es")
    r1 = request_for_booking(booking_a["id"])
    r2 = request_for_booking(booking_b1["id"])
    r3 = request_for_booking(booking_b2["id"])
    get_success_data(api_client.assign_interpreter(
        r1["id"], {"interpreter_id": ctx["interpreter"]["id"]}, STAFF))
    ctx.update({"r1": r1, "r2": r2, "r3": r3})
    return ctx


def scenario_travel_gap() -> Dict[str, Any]:
    """BOOKING_OPEN window (buffer 5, travel 30); one teacher supporting both
    channels; one family with three homeroom-linked students. Tests place the
    bookings."""
    ctx = setup_window_at_stage(
        "BOOKING_OPEN",
        teacher_specs=[{"supports_in_person": True, "supports_virtual": True}],
    )
    party = setup_family_with_students(ctx, 3, grade_levels=[1, 2, 3])
    ctx.update({"party": party, "slots": ctx["teacher_slots"][ctx["teachers"][0]["id"]]})
    return ctx


def scenario_round_trip() -> Dict[str, Any]:
    """A booking with an 'es' interpreter request (REQUESTED) and a ready
    interpreter; baseline committed_minutes is 0."""
    ctx = setup_window_at_stage("BOOKING_OPEN")
    interpreter = add_interpreter()
    party = setup_family_with_students(
        ctx, 1, family_overrides={"preferred_language": "es"}
    )
    slot = ctx["teacher_slots"][ctx["teachers"][0]["id"]][0]
    booking = book_slot(slot["id"], party["students"][0]["id"], party["guardian"],
                        interpreter_language="es")
    request = request_for_booking(booking["id"])
    ctx.update({"interpreter": interpreter, "booking": booking, "request": request,
                "party": party})
    return ctx
