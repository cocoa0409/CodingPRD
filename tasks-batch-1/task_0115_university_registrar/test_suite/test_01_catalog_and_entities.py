"""Catalog creation, entity defaults, immutability, and access control.

Translates Corner queue instances from the `entities`, `state_machines`,
`endpoints`, and `rbac` sections that concern catalog setup and authorization.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    make_student_headers,
)
from test_helpers import fixtures as fx
from test_helpers import factories as F

REG = TEST_USERS["registrar_headers"]
ADV = TEST_USERS["advisor_headers"]
BUR = TEST_USERS["bursar_headers"]


def test_create_term_returns_201_planning_status(api):
    """PRD §3.1: "A new term begins in `PLANNING`."
    PRD §2.4: "The `version` field is an integer that begins at its initial
    value and increments by one on every mutation."

    Design: Corner/entities/create_term_returns_201_with_planning_status
    """
    resp = api.create_term(F.create_term_payload(per_credit_cost_cents=50000), REG)
    data = validate_success(resp, 201)
    assert data["status"] == "PLANNING", f"new term must be PLANNING, got {data['status']}"
    assert data["per_credit_cost_cents"] == 50000
    assert data["version"] == 1, f"version begins at 1, got {data['version']}"


def test_get_term_not_found_returns_404(api):
    """PRD §2.8: "returns `ERR_NOT_FOUND` on the first reference that does not resolve".

    Design: Corner/entities/get_term_not_found_returns_404
    """
    resp = api.get_term(NON_EXISTENT_UUID, REG)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_create_section_missing_seat_capacity_returns_validation(api):
    """PRD §3.11: "body well-formedness on mutating endpoints — required fields
    present with correct types and enum values among their legal members —
    yields `ERR_VALIDATION`".

    Design: Corner/entities/create_section_missing_required_field_returns_validation
    """
    cat = fx.setup_catalog()
    payload = F.create_section_payload(
        cat["term"]["id"], cat["course"]["id"], cat["instructor"]["id"]
    )
    del payload["seat_capacity"]  # seat_capacity is required (at least 1), no default
    resp = api.create_section(payload, REG)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 400)


def test_create_student_defaults_completed_credit_hours_zero(api):
    """PRD §3.3: "an optional `completed_credit_hours` (default 0)".
    PRD §3.3: "On creation, a student's `gpa` is 0.00, `academic_standing` is
    `GOOD`, and `earned_credit_hours` equals `completed_credit_hours`."

    Design: Corner/entities/create_student_default_completed_credit_hours_zero
    """
    prog = fx.make_program()
    resp = api.create_student(
        {"full_name": "Stu Z", "email": "cz-defaults@u.edu", "program_id": prog["id"]}, REG
    )
    data = validate_success(resp, 201)
    assert data["completed_credit_hours"] == 0
    assert data["earned_credit_hours"] == 0
    assert data["gpa"] == 0.00
    assert data["academic_standing"] == "GOOD"


def test_section_seats_taken_starts_zero(api):
    """PRD §3.2: "A new section opens with `status` `OPEN`, `seats_taken` 0, and
    `waitlist_count` 0."

    Design: Corner/entities/section_computed_seats_taken_ignores_input
    """
    cat = fx.setup_catalog()
    resp = api.create_section(
        F.create_section_payload(
            cat["term"]["id"], cat["course"]["id"], cat["instructor"]["id"],
            seat_capacity=30,
        ),
        REG,
    )
    data = validate_success(resp, 201)
    assert data["seats_taken"] == 0
    assert data["waitlist_count"] == 0
    assert data["status"] == "OPEN"


def test_program_immutable_no_version_field(api):
    """PRD §2.4: "Three entities are immutable after creation and therefore carry
    only `id` and `created_at`, with both `updated_at` and `version` absent:
    `Program`, `CourseRequirement`, and `RefundTransaction`."

    Design: Corner/entities/program_immutable_no_version_field
    """
    prog = fx.make_program()
    resp = api.get_program(prog["id"], REG)
    data = validate_success(resp, 200)
    for field in ("id", "created_at", "name", "required_credit_hours", "min_gpa"):
        assert field in data, f"program must expose {field}"
    assert "version" not in data, "immutable Program must not carry version"
    assert "updated_at" not in data, "immutable Program must not carry updated_at"


def test_open_registration_with_no_sections_rejected(api):
    """PRD §3.1: "Opening registration — the `PLANNING → REGISTRATION_OPEN`
    transition — requires that at least one section already exists for the term;
    an attempt with no sections is rejected with `ERR_TERM_HAS_NO_SECTIONS`."

    Design: Corner/state_machines/term_open_registration_with_no_sections_rejected
    """
    term = fx.make_term()
    resp = api.set_term_status(term["id"], {"to_status": "REGISTRATION_OPEN"}, REG)
    validate_error(resp, ApiErrorId.ERR_TERM_HAS_NO_SECTIONS.value, 409)


def test_cancelled_section_cannot_reopen(api):
    """PRD §3.2: "A section's lifecycle is `OPEN | CLOSED | CANCELLED`, with
    `CANCELLED` terminal".
    PRD §3.2: "A section transition requested from a state that does not define it
    is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancelled_section_cannot_reopen
    """
    cat = fx.setup_catalog()
    sec = fx.make_section(cat["term"]["id"], cat["course"]["id"], cat["instructor"]["id"])
    fx.set_section_status(sec["id"], "CANCELLED")
    resp = api.set_section_status(sec["id"], {"to_status": "OPEN"}, REG)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_clear_already_cleared_hold_returns_invalid_state(api):
    """PRD §3.3: "A hold is cleared by the appropriate office, moving
    `ACTIVE → CLEARED`".
    PRD §3.5 / §3.11: "A drop, a withdraw, or a grade entry requested against an
    enrollment whose current state does not define that transition is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/hold_clear_twice_second_returns_invalid_state
    """
    prog = fx.make_program()
    stu = fx.make_student(prog["id"])
    hold = fx.make_hold(stu["id"], "FINANCIAL")
    validate_success(api.clear_hold(hold["id"], BUR), 200)
    resp = api.clear_hold(hold["id"], BUR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_list_sections_in_term_returns_array(api):
    """PRD §2.8: "the sections of a term, course, or instructor ... These are
    read-only projections".

    Design: Corner/endpoints/list_sections_in_term_returns_array
    """
    cat = fx.setup_catalog()
    sec = fx.make_section(cat["term"]["id"], cat["course"]["id"], cat["instructor"]["id"])
    resp = api.list_term_sections(cat["term"]["id"], REG)
    data, _meta = validate_paginated(resp)
    assert any(item["id"] == sec["id"] for item in data), "term sections must include the created section"


def test_list_sections_pagination_envelope(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object, where `total_count` is the total number
    of matching items before paging and `has_more` indicates whether any items
    remain beyond the current page."

    Design: Corner/endpoints/list_sections_pagination_envelope
    """
    prog = fx.make_program()
    instr_a = fx.make_instructor()
    instr_b = fx.make_instructor()
    term = fx.make_term()
    c1 = fx.make_course(prog["id"])
    c2 = fx.make_course(prog["id"])
    fx.make_section(term["id"], c1["id"], instr_a["id"],
                    meeting_days="MWF", meeting_start_min=540, meeting_end_min=590)
    fx.make_section(term["id"], c2["id"], instr_b["id"],
                    meeting_days="TR", meeting_start_min=600, meeting_end_min=650)
    resp = api.list_term_sections(term["id"], REG, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, "has_more must be true when items remain"
    assert len(data) == 1, f"limit=1 must return one item, got {len(data)}"


def test_list_refunds_for_enrollment_after_drop(api):
    """PRD §3.7: "Every drop or withdraw that releases a charged seat produces a
    **RefundTransaction**, a permanent record naming the `enrollment_id`, the
    credited `student_id`, the `refund_tier` applied, the `amount_cents` credited,
    and the `triggered_by` cause".

    Design: Corner/endpoints/list_refunds_for_enrollment_after_drop
    """
    base = fx.setup_one_enrolled_student(credit_hours=3)  # 3 * 50000 = 150000, clock in full window
    fx.drop(base["enrollment"]["id"], base["student"]["id"])
    resp = api.list_enrollment_refunds(base["enrollment"]["id"], REG)
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, f"expected one refund, got {len(data)}"
    assert data[0]["refund_tier"] == "FULL"
    assert data[0]["amount_cents"] == 150000


# --------------------------------------------------------------------------
# RBAC (Corner queue: rbac section)
# --------------------------------------------------------------------------
def test_student_cannot_create_section(api):
    """PRD §2.1: "If the headers are present and the role is recognized but that
    role is not permitted to perform the requested operation under the
    access-control matrix, the request is rejected with `ERR_FORBIDDEN`."
    PRD §4: "POST | `/sections` | Create a section offering | Registrar".

    Design: Corner/rbac/student_cannot_create_section
    """
    cat = fx.setup_catalog()
    stu = fx.make_student(cat["program"]["id"])
    payload = F.create_section_payload(
        cat["term"]["id"], cat["course"]["id"], cat["instructor"]["id"], seat_capacity=5
    )
    resp = api.create_section(payload, make_student_headers(stu["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, 403)


def test_student_cannot_drop_another_students_enrollment(api):
    """PRD §2.1: "ownership checks on any enrollment or swap request compare the
    resource's `student_id` foreign key to `X-User-ID`, and a mismatch is rejected
    with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/student_cannot_enroll_for_another_student
    """
    base = fx.setup_one_enrolled_student(credit_hours=3)
    other = fx.make_student(base["program"]["id"])
    resp = api.drop_enrollment(base["enrollment"]["id"], make_student_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)


def test_bursar_cannot_clear_advising_hold(api):
    """PRD §3.3: "a `FINANCIAL` hold may be cleared only by a `Bursar` and an
    `ADVISING` hold only by an `Advisor`, and a mismatch is rejected with
    `ERR_HOLD_WRONG_CLEARER`."

    Design: Corner/rbac/bursar_cannot_clear_advising_hold
    """
    prog = fx.make_program()
    stu = fx.make_student(prog["id"])
    hold = fx.make_hold(stu["id"], "ADVISING")  # placed by Advisor
    resp = api.clear_hold(hold["id"], BUR)
    validate_error(resp, ApiErrorId.ERR_HOLD_WRONG_CLEARER.value, 403)


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If `X-User-Role` is missing or is not one of these four known
    roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    resp = api.get_term(NON_EXISTENT_UUID, headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
