"""Composite setup helpers.

Every test runs against an empty database (the runner restarts the server before
each test), so each helper builds its preconditions from scratch using only
endpoints the PRD declares. Setup calls use the lenient `get_success_data`
validator so a broken precondition surfaces as a clear "Setup step failed"
rather than a confusing assertion later.

Identity threading (PRD 2.1): any call whose success depends on the caller being
the acting Instructor uses `make_instructor_headers(instructor["id"])`, never
the shared fallback constant.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import CLOCK_AFTER_COLLEGE_END
from .factories import (
    create_articulation_agreement_payload,
    create_course_payload,
    create_credential_application_payload,
    create_enrollment_payload,
    create_funding_agreement_payload,
    create_high_school_payload,
    create_instructor_payload,
    create_offering_payload,
    create_payment_payload,
    create_placement_record_payload,
    create_prerequisite_payload,
    create_student_payload,
    create_term_payload,
)
from .test_users import (
    make_admin_headers,
    make_bursar_headers,
    make_coordinator_headers,
    make_credential_reviewer_headers,
    make_instructor_headers,
    make_registrar_headers,
)

ADMIN = make_admin_headers()
COORDINATOR = make_coordinator_headers()
REGISTRAR = make_registrar_headers()
BURSAR = make_bursar_headers()
REVIEWER_1 = make_credential_reviewer_headers("rev-1")
REVIEWER_2 = make_credential_reviewer_headers("rev-2")


# ---------------------------------------------------------------------------
# Tier 0 — primitive steps
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> Dict[str, Any]:
    """Advance the logical clock (DualCreditAdmin only, PRD 3.10)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_high_school(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_high_school(create_high_school_payload(**overrides), ADMIN))


def create_college_term(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_term(create_term_payload("COLLEGE", **overrides), ADMIN))


def create_hs_term(high_school_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_term(create_term_payload("HIGH_SCHOOL", high_school_id, **overrides), ADMIN)
    )


def open_term(term_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.open_term_registration(term_id, ADMIN))


def close_term(term_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.close_term_registration(term_id, ADMIN))


def create_course(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_course(create_course_payload(**overrides), ADMIN))


def create_prerequisite(course_id: str, requires_course_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_prerequisite(
            create_prerequisite_payload(course_id, requires_course_id, **overrides), ADMIN
        )
    )


def create_instructor(high_school_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_instructor(create_instructor_payload(high_school_id, **overrides), ADMIN)
    )


def create_credential_application(instructor_id: str, course_id: str, **overrides) -> Dict[str, Any]:
    """Filed by the acting Instructor — X-User-ID must equal instructor_id (PRD 2.1)."""
    return get_success_data(
        api_client.create_credential_application(
            create_credential_application_payload(instructor_id, course_id, **overrides),
            make_instructor_headers(instructor_id),
        )
    )


def begin_review(app_id: str, reviewer_headers=None) -> Dict[str, Any]:
    return get_success_data(
        api_client.begin_credential_review(app_id, reviewer_headers or REVIEWER_1)
    )


def approve_credential(app_id: str, reviewer_headers=None, **payload) -> Dict[str, Any]:
    return get_success_data(
        api_client.approve_credential_application(app_id, payload, reviewer_headers or REVIEWER_1)
    )


def credential_course(instructor_id: str, course_id: str, reviewer_headers=None, **overrides) -> Dict[str, Any]:
    """Full credentialing happy path: apply -> begin-review -> approve (APPROVED)."""
    app = create_credential_application(instructor_id, course_id, **overrides)
    begin_review(app["id"], reviewer_headers)
    return approve_credential(app["id"], reviewer_headers)


def create_funding_agreement(high_school_id: str, college_term_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_funding_agreement(
            create_funding_agreement_payload(high_school_id, college_term_id, **overrides), ADMIN
        )
    )


def create_offering(
    course_id: str,
    college_term_id: str,
    hs_term_id: str,
    high_school_id: str,
    instructor_id: str,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_offering(
            create_offering_payload(
                course_id, college_term_id, hs_term_id, high_school_id, instructor_id, **overrides
            ),
            ADMIN,
        )
    )


def open_offering(offering_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.open_offering(offering_id, ADMIN))


def start_session(offering_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.start_offering_session(offering_id, ADMIN))


def begin_grading(offering_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.begin_offering_grading(offering_id, ADMIN))


def finalize_offering(offering_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.finalize_offering(offering_id, REGISTRAR))


def cancel_offering(offering_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.cancel_offering(offering_id, ADMIN))


def create_student(high_school_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_student(create_student_payload(high_school_id, **overrides), COORDINATOR)
    )


def create_placement_record(student_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_placement_record(
            create_placement_record_payload(student_id, **overrides), COORDINATOR
        )
    )


def create_enrollment(student_id: str, offering_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_enrollment(create_enrollment_payload(student_id, offering_id), COORDINATOR)
    )


def get_offering(offering_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_offering(offering_id, ADMIN))


def get_offering_version(offering_id: str) -> int:
    return get_offering(offering_id)["version"]


def get_enrollment(enrollment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_enrollment(enrollment_id, ADMIN))


def get_credential_application(app_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_credential_application(app_id, ADMIN))


def get_student(student_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_student(student_id, ADMIN))


def get_invoice(invoice_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_invoice(invoice_id, ADMIN))


def list_invoices_for_enrollment(enrollment_id: str) -> List[Dict[str, Any]]:
    data, _meta = validate_paginated(
        api_client.list_invoices(ADMIN, params={"enrollment_id": enrollment_id})
    )
    return data


def first_invoice_for_enrollment(enrollment_id: str) -> Dict[str, Any]:
    invoices = list_invoices_for_enrollment(enrollment_id)
    assert invoices, f"Setup expected an invoice for enrollment {enrollment_id}"
    return invoices[0]


def list_transcript_entries_for_enrollment(
    enrollment_id: str, institution: Optional[str] = None
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"enrollment_id": enrollment_id}
    if institution is not None:
        params["institution"] = institution
    data, _meta = validate_paginated(api_client.list_transcript_entries(ADMIN, params=params))
    return data


def pay_invoice(invoice_id: str, payer: str, amount_cents: int) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_payment(
            invoice_id, create_payment_payload(payer, amount_cents), BURSAR
        )
    )


def refund_invoice(invoice_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.refund_invoice(invoice_id, BURSAR))


def submit_grade(enrollment_id: str, grade: str, instructor_id: str) -> Dict[str, Any]:
    """Only the offering's instructor of record may submit (PRD 2.1)."""
    return get_success_data(
        api_client.submit_grade(
            enrollment_id, {"grade": grade}, make_instructor_headers(instructor_id)
        )
    )


def create_articulation_agreement(course_id: str, target_institution: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_articulation_agreement(
            create_articulation_agreement_payload(course_id, target_institution, **overrides), ADMIN
        )
    )


# ---------------------------------------------------------------------------
# Tier 1 — confirm / drop / withdraw / reinstate with OCC version handling
# ---------------------------------------------------------------------------


def confirm_enrollment(offering_id: str, enrollment_id: str) -> Dict[str, Any]:
    """Confirm with a freshly read expected_offering_version (PRD 2.8)."""
    version = get_offering_version(offering_id)
    return get_success_data(
        api_client.confirm_enrollment(
            enrollment_id, {"expected_offering_version": version}, COORDINATOR
        )
    )


def confirm_enrollment_raw(
    offering_id: str, enrollment_id: str, expected_version: Optional[int] = None
):
    """Raw confirm response for error-path tests; reads a fresh version by default."""
    if expected_version is None:
        expected_version = get_offering_version(offering_id)
    return api_client.confirm_enrollment(
        enrollment_id, {"expected_offering_version": expected_version}, COORDINATOR
    )


def drop_enrollment(enrollment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.drop_enrollment(enrollment_id, COORDINATOR))


def withdraw_enrollment(enrollment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.withdraw_enrollment(enrollment_id, COORDINATOR))


def reinstate_enrollment(offering_id: str, enrollment_id: str) -> Dict[str, Any]:
    version = get_offering_version(offering_id)
    return get_success_data(
        api_client.reinstate_enrollment(
            enrollment_id, {"expected_offering_version": version}, REGISTRAR
        )
    )


# ---------------------------------------------------------------------------
# Tier 2 — the standard scenario (school, calendar pair, course, credentialed
# instructor, funding agreement, offering) that most lifecycle tests build on
# ---------------------------------------------------------------------------


def setup_base(
    *,
    capacity: int = 2,
    delivery_mode: Optional[str] = "HS_CAMPUS",
    course_overrides: Optional[Dict[str, Any]] = None,
    funding: bool = True,
    funding_overrides: Optional[Dict[str, Any]] = None,
    college_term_overrides: Optional[Dict[str, Any]] = None,
    hs_term_overrides: Optional[Dict[str, Any]] = None,
    open_terms: bool = True,
    approve_credential: bool = True,
    create_offering_flag: bool = True,
    open_offering_flag: bool = True,
    school_name: str = "Northview HS",
) -> Dict[str, Any]:
    """School + COLLEGE/HIGH_SCHOOL term pair + course + instructor (+ APPROVED
    credential) (+ funding agreement) + offering, with terms and offering OPEN."""
    ctx: Dict[str, Any] = {}
    ctx["school"] = create_high_school(name=school_name)
    ctx["college_term"] = create_college_term(**(college_term_overrides or {}))
    ctx["hs_term"] = create_hs_term(ctx["school"]["id"], **(hs_term_overrides or {}))
    ctx["course"] = create_course(**(course_overrides or {}))
    ctx["instructor"] = create_instructor(ctx["school"]["id"])
    ctx["credential"] = None
    if approve_credential:
        ctx["credential"] = credential_course(ctx["instructor"]["id"], ctx["course"]["id"])
    ctx["agreement"] = None
    if funding:
        ctx["agreement"] = create_funding_agreement(
            ctx["school"]["id"], ctx["college_term"]["id"], **(funding_overrides or {})
        )
    ctx["offering"] = None
    if create_offering_flag:
        offering_kwargs: Dict[str, Any] = {"capacity": capacity}
        if delivery_mode is not None:
            offering_kwargs["delivery_mode"] = delivery_mode
        ctx["offering"] = create_offering(
            ctx["course"]["id"],
            ctx["college_term"]["id"],
            ctx["hs_term"]["id"],
            ctx["school"]["id"],
            ctx["instructor"]["id"],
            **offering_kwargs,
        )
    if open_terms:
        open_term(ctx["college_term"]["id"])
        open_term(ctx["hs_term"]["id"])
    if open_offering_flag and ctx["offering"] is not None:
        ctx["offering"] = open_offering(ctx["offering"]["id"])
    return ctx


def register_student(
    ctx: Dict[str, Any],
    *,
    full_name: str = "Jamie Diaz",
    grade_level: int = 12,
    placement: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a student (+ optional placement record) and a PENDING_VERIFICATION
    enrollment on ctx['offering']. Returns {'student', 'enrollment'}."""
    student = create_student(ctx["school"]["id"], full_name=full_name, grade_level=grade_level)
    if placement is not None:
        create_placement_record(student["id"], **placement)
    enrollment = create_enrollment(student["id"], ctx["offering"]["id"])
    return {"student": student, "enrollment": enrollment}


def register_and_confirm(
    ctx: Dict[str, Any],
    *,
    full_name: str = "Jamie Diaz",
    grade_level: int = 12,
    placement: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """register_student + confirm -> the enrollment lands REGISTERED (or
    WAITLISTED when the offering is full). Returns {'student', 'enrollment'}."""
    pair = register_student(
        ctx, full_name=full_name, grade_level=grade_level, placement=placement
    )
    pair["enrollment"] = confirm_enrollment(ctx["offering"]["id"], pair["enrollment"]["id"])
    return pair


# ---------------------------------------------------------------------------
# Tier 3 — full lifecycle shortcuts (grading pipeline)
# ---------------------------------------------------------------------------


def move_offering_to_grading(offering_id: str, clock: str = CLOCK_AFTER_COLLEGE_END) -> Dict[str, Any]:
    """OPEN -> IN_SESSION -> GRADING; the clock must read at/after the college
    term's end_date before begin-grading (PRD 3.4)."""
    set_clock(clock)
    start_session(offering_id)
    return begin_grading(offering_id)


def complete_enrollment_with_grade(
    ctx: Dict[str, Any], enrollment_id: str, grade: str
) -> Dict[str, Any]:
    """Submit a final grade as the offering's instructor of record, then finalize
    the offering (REGISTERED -> COMPLETED, PENDING transcript entries created)."""
    move_offering_to_grading(ctx["offering"]["id"])
    submit_grade(enrollment_id, grade, ctx["instructor"]["id"])
    return finalize_offering(ctx["offering"]["id"])


def setup_graded_scenario(
    *,
    grade: str = "A",
    course_overrides: Optional[Dict[str, Any]] = None,
    funding_overrides: Optional[Dict[str, Any]] = None,
    placement: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Full pipeline: standard fixture -> one student REGISTERED -> grading ->
    grade submitted -> offering FINALIZED. Returns ctx with 'student',
    'enrollment' (COMPLETED) keys added."""
    ctx = setup_base(course_overrides=course_overrides, funding_overrides=funding_overrides)
    pair = register_and_confirm(ctx, placement=placement)
    complete_enrollment_with_grade(ctx, pair["enrollment"]["id"], grade)
    ctx["student"] = pair["student"]
    ctx["enrollment"] = get_enrollment(pair["enrollment"]["id"])
    return ctx


def setup_dual_course_posted_scenario() -> Dict[str, Any]:
    """One student completes two courses — MATH151 (3 college credits, 1.0 HS
    units, placement MATH >= 70) with grade A and ENGL101 (4 college credits,
    1.0 HS units, no placement) with grade B — and all four transcript entries
    are POSTED. Returns a ctx dict carrying 'student', 'math_entry_college',
    'math_entry_hs', 'engl_entry_college', 'engl_entry_hs'."""
    ctx = setup_base(
        course_overrides={
            "course_code": "MATH151",
            "title": "College Algebra",
            "placement_exam_code": "MATH",
            "min_placement_score": 70,
        }
    )
    engl_course = create_course(
        course_code="ENGL101",
        title="Composition I",
        college_credit_hours=4,
        hs_credit_units=1.0,
        placement_exam_code="ENGL",
        min_placement_score=0,
    )
    credential_course(
        ctx["instructor"]["id"], engl_course["id"], qualification_summary="MA English"
    )
    engl_offering = create_offering(
        engl_course["id"],
        ctx["college_term"]["id"],
        ctx["hs_term"]["id"],
        ctx["school"]["id"],
        ctx["instructor"]["id"],
        capacity=2,
        delivery_mode="HS_CAMPUS",
    )
    open_offering(engl_offering["id"])

    student = create_student(ctx["school"]["id"], full_name="Jamie Diaz", grade_level=12)
    create_placement_record(student["id"], exam_code="MATH", score=85)

    enr_math = create_enrollment(student["id"], ctx["offering"]["id"])
    enr_math = confirm_enrollment(ctx["offering"]["id"], enr_math["id"])
    enr_engl = create_enrollment(student["id"], engl_offering["id"])
    enr_engl = confirm_enrollment(engl_offering["id"], enr_engl["id"])
    assert enr_math["status"] == "REGISTERED" and enr_engl["status"] == "REGISTERED"

    move_offering_to_grading(ctx["offering"]["id"])
    submit_grade(enr_math["id"], "A", ctx["instructor"]["id"])
    finalize_offering(ctx["offering"]["id"])
    move_offering_to_grading(engl_offering["id"])
    submit_grade(enr_engl["id"], "B", ctx["instructor"]["id"])
    finalize_offering(engl_offering["id"])

    entries = {
        "math_entry_college": list_transcript_entries_for_enrollment(
            enr_math["id"], institution="COLLEGE"
        )[0],
        "math_entry_hs": list_transcript_entries_for_enrollment(
            enr_math["id"], institution="HIGH_SCHOOL"
        )[0],
        "engl_entry_college": list_transcript_entries_for_enrollment(
            enr_engl["id"], institution="COLLEGE"
        )[0],
        "engl_entry_hs": list_transcript_entries_for_enrollment(
            enr_engl["id"], institution="HIGH_SCHOOL"
        )[0],
    }
    # Post every entry and keep the POSTED snapshots (post returns the entry).
    entries = {
        key: get_success_data(api_client.post_transcript_entry(entry["id"], REGISTRAR))
        for key, entry in entries.items()
    }

    ctx["student"] = student
    ctx["enr_math"] = enr_math
    ctx["enr_engl"] = enr_engl
    ctx["engl_course"] = engl_course
    ctx["engl_offering"] = engl_offering
    ctx.update(entries)
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — accumulation / seat-pressure scenarios
# ---------------------------------------------------------------------------


def setup_delivery_mode_pair() -> Dict[str, Any]:
    """One STATE_PROGRAM agreement (40000/cr tuition, 30000/cr state rate,
    district cap 50000) governing two offerings of the same 3-credit course —
    one HS_CAMPUS, one ONLINE — with the same student REGISTERED in both.
    Returns ctx with 'invoice_a' (HS_CAMPUS) and 'invoice_b' (ONLINE)."""
    ctx = setup_base(
        course_overrides={
            "course_code": "MATH151",
            "title": "College Algebra",
            "placement_exam_code": "MATH",
            "min_placement_score": 70,
        },
        funding_overrides={"district_cap_cents": 50000},
    )
    offering_b = create_offering(
        ctx["course"]["id"],
        ctx["college_term"]["id"],
        ctx["hs_term"]["id"],
        ctx["school"]["id"],
        ctx["instructor"]["id"],
        capacity=2,
        delivery_mode="ONLINE",
    )
    open_offering(offering_b["id"])
    student = create_student(ctx["school"]["id"], full_name="Jamie Diaz", grade_level=12)
    create_placement_record(student["id"], exam_code="MATH", score=85)
    enr_a = create_enrollment(student["id"], ctx["offering"]["id"])
    confirm_enrollment(ctx["offering"]["id"], enr_a["id"])
    enr_b = create_enrollment(student["id"], offering_b["id"])
    confirm_enrollment(offering_b["id"], enr_b["id"])
    ctx["student"] = student
    ctx["offering_b"] = offering_b
    ctx["invoice_a"] = first_invoice_for_enrollment(enr_a["id"])
    ctx["invoice_b"] = first_invoice_for_enrollment(enr_b["id"])
    return ctx


def setup_mixed_enrollment_scenario(
    *,
    capacity: int,
    num_students: int,
    course_overrides: Optional[Dict[str, Any]] = None,
    funding_overrides: Optional[Dict[str, Any]] = None,
    grade_levels: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Standard fixture + N students, each enrolled and confirmed in order.
    The first `capacity` land REGISTERED, the rest WAITLISTED. Returns ctx with
    'students' and 'enrollments' lists in creation order."""
    ctx = setup_base(
        capacity=capacity,
        course_overrides=course_overrides,
        funding_overrides=funding_overrides,
    )
    ctx["students"] = []
    ctx["enrollments"] = []
    names = ["Alpha One", "Beta Two", "Gamma Three", "Delta Four"]
    levels = grade_levels or [11, 12, 12, 11]
    for index in range(num_students):
        pair = register_and_confirm(
            ctx, full_name=names[index % len(names)], grade_level=levels[index % len(levels)]
        )
        ctx["students"].append(pair["student"])
        ctx["enrollments"].append(pair["enrollment"])
    return ctx


def setup_mismatch_withdraw_scenario(
    *,
    pay_family: bool = False,
    fully_pay: bool = False,
    course_overrides: Optional[Dict[str, Any]] = None,
    funding_overrides: Optional[Dict[str, Any]] = None,
    withdraw_clock: str = "2026-09-12T00:00:00Z",
) -> Dict[str, Any]:
    """Standard fixture + one REGISTERED student + invoice; optionally collects
    payment(s); advances the clock and withdraws the enrollment. Returns ctx
    with 'student', 'enrollment' (pre-withdraw snapshot), 'invoice', and
    'withdrawn' (the withdraw response data)."""
    ctx = setup_base(course_overrides=course_overrides, funding_overrides=funding_overrides)
    placement = (
        {"exam_code": "MATH", "score": 85, "taken_at": "2026-08-01T00:00:00Z"}
        if ctx["course"]["min_placement_score"] > 0
        else None
    )
    pair = register_and_confirm(ctx, placement=placement)
    invoice = first_invoice_for_enrollment(pair["enrollment"]["id"])
    if fully_pay:
        if invoice["state_amount_cents"] > 0:
            pay_invoice(invoice["id"], "STATE", invoice["state_amount_cents"])
        if invoice["district_amount_cents"] > 0:
            pay_invoice(invoice["id"], "DISTRICT", invoice["district_amount_cents"])
        if invoice["family_amount_cents"] > 0:
            pay_invoice(invoice["id"], "FAMILY", invoice["family_amount_cents"])
    elif pay_family and invoice["family_amount_cents"] > 0:
        pay_invoice(invoice["id"], "FAMILY", invoice["family_amount_cents"])
    set_clock(withdraw_clock)
    withdrawn = withdraw_enrollment(pair["enrollment"]["id"])
    ctx["student"] = pair["student"]
    ctx["enrollment"] = pair["enrollment"]
    ctx["invoice"] = get_invoice(invoice["id"])
    ctx["withdrawn"] = withdrawn
    return ctx
