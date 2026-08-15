"""Validation claims: auth rungs, FK existence ordering, term/fk referential
guards, edge rules, uniqueness rules, and the fiscal guards (PRD 2.1, 2.9, 2.10,
3.2, 3.4, 3.5, 3.7)."""
from test_helpers import (
    ApiErrorId,
    confirm_enrollment,
    confirm_enrollment_raw,
    create_college_term,
    create_course,
    create_funding_agreement,
    create_high_school,
    create_hs_term,
    create_instructor,
    create_prerequisite,
    first_invoice_for_enrollment,
    get_enrollment,
    get_invoice,
    get_offering,
    get_offering_version,
    list_invoices_for_enrollment,
    pay_invoice,
    register_and_confirm,
    register_student,
    set_clock,
    setup_base,
    validate_error,
    validate_success,
    withdraw_enrollment,
)


def test_missing_auth_header_unauthenticated(api, no_auth_headers):
    """PRD 2.1: "A request missing either header, or presenting a role that is not
    one of the declared names, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_header_unauthenticated
    """
    response = api.create_high_school(
        {"name": "Northview HS", "district_code": "NV-01"}, no_auth_headers
    )
    validate_error(response, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value, 400)


def test_enrollment_body_fk_existence_student_first(api, coordinator_headers):
    """PRD 2.9: "Requests that carry resource identifiers in the path validate them
    left to right, rejecting with `ERR_NOT_FOUND` (HTTP 404) at the first identifier
    that does not resolve to an existing resource. After the path is fully resolved,
    body-supplied foreign keys are validated in their declared input order, again
    with `ERR_NOT_FOUND` on the first miss."

    Design: Corner/validations/enrollment_body_fk_existence_student_first
    """
    response = api.create_enrollment(
        {"student_id": "00000000-0000-4000-8000-000000000001", "offering_id": "00000000-0000-4000-8000-000000000002"},
        coordinator_headers,
    )
    validate_error(response, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_offering_term_type_and_school_mismatch_rejected(api, admin_headers):
    """PRD 3.4: "The referenced `college_term_id` must point to a term whose
    `institution_type` is `COLLEGE`, and `hs_term_id` to a term whose
    `institution_type` is `HIGH_SCHOOL`; a mismatch in either is rejected with
    `ERR_TERM_TYPE_MISMATCH` (HTTP 409)."
    PRD 3.4: "The high school term's `high_school_id` must also equal the offering's
    own `high_school_id`; a mismatch is rejected with `ERR_TERM_SCHOOL_MISMATCH`
    (HTTP 409)."

    Design: Corner/validations/offering_term_type_and_school_mismatch_rejected
    """
    school_a = create_high_school(name="Northview HS", district_code="NV-01")
    school_b = create_high_school(name="Southview HS", district_code="SV-02")
    college_term = create_college_term()
    hs_term_a = create_hs_term(school_a["id"], name="Fall 2026 HS-A")
    hs_term_b = create_hs_term(school_b["id"], name="Fall 2026 HS-B")
    course = create_course()
    instructor = create_instructor(school_a["id"])

    base_payload = {
        "course_id": course["id"],
        "high_school_id": school_a["id"],
        "instructor_id": instructor["id"],
        "capacity": 2,
    }
    type_mismatch = api.create_offering(
        {**base_payload, "college_term_id": hs_term_a["id"], "hs_term_id": hs_term_a["id"]},
        admin_headers,
    )
    validate_error(type_mismatch, ApiErrorId.ERR_TERM_TYPE_MISMATCH.value)

    school_mismatch = api.create_offering(
        {**base_payload, "college_term_id": college_term["id"], "hs_term_id": hs_term_b["id"]},
        admin_headers,
    )
    validate_error(school_mismatch, ApiErrorId.ERR_TERM_SCHOOL_MISMATCH.value)


def test_duplicate_and_invalid_prerequisite_edges_rejected(api, admin_headers):
    """PRD 3.2: "Edge creation applies three rules in a fixed sub-order: a
    self-edge — `course_id` equal to `requires_course_id` — is rejected first with
    `ERR_SELF_PREREQUISITE` (HTTP 400); an exact duplicate edge is rejected next
    with `ERR_DUPLICATE_PREREQUISITE` (HTTP 409); and an edge that would close a
    cycle, detected by depth-first reachability from `requires_course_id` back to
    `course_id`, is rejected last with `ERR_PREREQUISITE_CYCLE` (HTTP 409)."

    Design: Corner/validations/duplicate_and_invalid_prerequisite_edges_rejected
    """
    course_a = create_course(
        course_code="MATH151", title="College Algebra", placement_exam_code="MATH",
        min_placement_score=70,
    )
    course_b = create_course(
        course_code="MATH099", title="Pre-Algebra", college_credit_hours=2,
        hs_credit_units=0.5,
    )
    create_prerequisite(course_a["id"], course_b["id"], min_grade="C")

    self_edge = api.create_prerequisite(
        {"course_id": course_a["id"], "requires_course_id": course_a["id"]}, admin_headers
    )
    validate_error(self_edge, ApiErrorId.ERR_SELF_PREREQUISITE.value, 400)

    duplicate = api.create_prerequisite(
        {"course_id": course_a["id"], "requires_course_id": course_b["id"], "min_grade": "C"},
        admin_headers,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_PREREQUISITE.value)

    cycle = api.create_prerequisite(
        {"course_id": course_b["id"], "requires_course_id": course_a["id"]}, admin_headers
    )
    validate_error(cycle, ApiErrorId.ERR_PREREQUISITE_CYCLE.value)


def test_duplicate_funding_agreement_rejected(api, admin_headers):
    """PRD 3.7: "A system-enforced `uniqueness` rule caps this at one agreement per
    school and college-term pair; a second creation for the same pair is rejected
    with `ERR_DUPLICATE_FUNDING_AGREEMENT` (HTTP 409)."

    Design: Corner/validations/duplicate_funding_agreement_rejected
    """
    school = create_high_school()
    college_term = create_college_term()
    create_funding_agreement(school["id"], college_term["id"])

    response = api.create_funding_agreement(
        {
            "high_school_id": school["id"],
            "college_term_id": college_term["id"],
            "funding_model": "FAMILY_RESPONSIBLE",
            "tuition_cents_per_credit": 41000,
        },
        admin_headers,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_FUNDING_AGREEMENT.value)


def test_duplicate_enrollment_rejected(api, coordinator_headers):
    """PRD 3.5: "Creating an enrollment is rejected with `ERR_DUPLICATE_ENROLLMENT`
    (HTTP 409) when an enrollment for the same `student_id` and `offering_id`
    already exists in `PENDING_VERIFICATION`, `REGISTERED`, or `WAITLISTED`."

    Design: Corner/validations/duplicate_enrollment_rejected
    """
    ctx = setup_base()
    pair = register_student(ctx)
    assert pair["enrollment"]["status"] == "PENDING_VERIFICATION"

    response = api.create_enrollment(
        {"student_id": pair["student"]["id"], "offering_id": ctx["offering"]["id"]},
        coordinator_headers,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_ENROLLMENT.value)


def test_prerequisite_not_met_solo_rejected(api):
    """PRD 3.5: "every prerequisite of the offering's course is satisfied (else
    `ERR_PREREQUISITE_NOT_MET`, HTTP 409)"
    PRD 3.5: "Prerequisite satisfaction means: for every `Prerequisite` row of the
    course, there exists a `TranscriptEntry` whose `institution` is `COLLEGE` and
    `status` is `POSTED`, belonging to an enrollment of this student on an offering
    of `requires_course_id`, with a grade at or above `min_grade`."

    Design: Corner/validations/prerequisite_not_met_solo_rejected
    """
    ctx = setup_base(
        course_overrides={
            "course_code": "MATH151",
            "title": "College Algebra",
            "placement_exam_code": "MATH",
            "min_placement_score": 70,
        }
    )
    prereq_course = create_course(
        course_code="MATH099", title="Pre-Algebra", college_credit_hours=2,
        hs_credit_units=0.5,
    )
    create_prerequisite(ctx["course"]["id"], prereq_course["id"], min_grade="C")
    pair = register_student(
        ctx, placement={"exam_code": "MATH", "score": 85, "taken_at": "2026-08-01T00:00:00Z"}
    )

    response = confirm_enrollment_raw(ctx["offering"]["id"], pair["enrollment"]["id"])
    validate_error(response, ApiErrorId.ERR_PREREQUISITE_NOT_MET.value)
    assert get_enrollment(pair["enrollment"]["id"])["status"] == "PENDING_VERIFICATION"
    assert list_invoices_for_enrollment(pair["enrollment"]["id"]) == [], (
        "A failed confirm must not create an invoice"
    )


def test_placement_missing_solo_rejected(api):
    """PRD 3.5: "Placement, checked only when the course's `min_placement_score` is
    greater than 0, means: among the student's non-expired `PlacementRecord` rows
    for the course's `placement_exam_code`, there is at least one (else
    `ERR_PLACEMENT_MISSING`); the latest such record — ordered by `taken_at`
    descending, then `created_at` descending — has a `score` at least the course's
    `min_placement_score` (else `ERR_PLACEMENT_SCORE_INSUFFICIENT`)."

    Design: Corner/validations/placement_missing_solo_rejected
    """
    ctx = setup_base(
        course_overrides={
            "course_code": "MATH151",
            "title": "College Algebra",
            "placement_exam_code": "MATH",
            "min_placement_score": 70,
        }
    )
    pair = register_student(ctx)  # no placement records at all

    response = confirm_enrollment_raw(ctx["offering"]["id"], pair["enrollment"]["id"])
    validate_error(response, ApiErrorId.ERR_PLACEMENT_MISSING.value)


def test_school_suspended_solo_rejected(api, admin_headers):
    """PRD 3.1: "Suspending a school does not modify any existing enrollment; it
    blocks only future enrollment confirmations, which fail with
    `ERR_SCHOOL_SUSPENDED` (HTTP 409) when the student's school is `SUSPENDED`."

    Design: Corner/validations/school_suspended_solo_rejected
    """
    ctx = setup_base()
    pair = register_student(ctx)
    response = api.suspend_high_school(ctx["school"]["id"], admin_headers)
    assert validate_success(response)["status"] == "SUSPENDED"

    response = confirm_enrollment_raw(ctx["offering"]["id"], pair["enrollment"]["id"])
    validate_error(response, ApiErrorId.ERR_SCHOOL_SUSPENDED.value)
    assert get_enrollment(pair["enrollment"]["id"])["status"] == "PENDING_VERIFICATION", (
        "The failed confirm leaves the enrollment untouched"
    )


def test_no_funding_agreement_solo_rejected(api):
    """PRD 3.5: "and a `FundingAgreement` exists for the offering's `high_school_id`
    and `college_term_id` pair (else `ERR_NO_FUNDING_AGREEMENT`, HTTP 409)."

    Design: Corner/validations/no_funding_agreement_solo_rejected
    """
    ctx = setup_base(funding=False)
    pair = register_student(ctx)

    response = confirm_enrollment_raw(ctx["offering"]["id"], pair["enrollment"]["id"])
    validate_error(response, ApiErrorId.ERR_NO_FUNDING_AGREEMENT.value)
    offering = get_offering(ctx["offering"]["id"])
    assert offering["seats_taken"] == 0, "No seat may be consumed by a failed confirm"
    assert list_invoices_for_enrollment(pair["enrollment"]["id"]) == []


def test_reinstate_without_seats_rejected(api, registrar_headers):
    """PRD 3.5: "The request carries `expected_offering_version` per §2.8, and
    reinstate requires: the enrollment in `WITHDRAWN` (else
    `ERR_ENROLLMENT_INVALID_STATE`); the offering's current `version` matching
    `expected_offering_version` (else `ERR_STALE_VERSION`); the offering in `OPEN`
    or `IN_SESSION` (else `ERR_OFFERING_INVALID_STATE`); the logical clock at or
    before the college term's `end_date` (else `ERR_WITHDRAW_WINDOW_CLOSED`); and
    at least one free seat (else `ERR_NO_SEATS_AVAILABLE`, HTTP 409)."

    Design: Corner/validations/reinstate_without_seats_rejected
    """
    ctx = setup_base(capacity=1)
    pair1 = register_and_confirm(ctx, full_name="Alpha One", grade_level=11)
    pair2 = register_student(ctx, full_name="Beta Two", grade_level=12)

    # e1 withdraws inside the withdraw window, freeing the only seat.
    set_clock("2026-09-12T00:00:00Z")
    withdraw_enrollment(pair1["enrollment"]["id"])
    # e2 confirms into the freed seat while the add window is open.
    set_clock("2026-08-20T00:00:00Z")
    confirm_enrollment(ctx["offering"]["id"], pair2["enrollment"]["id"])
    assert get_offering(ctx["offering"]["id"])["seats_taken"] == 1

    set_clock("2026-09-20T00:00:00Z")
    fresh_version = get_offering_version(ctx["offering"]["id"])
    response = api.reinstate_enrollment(
        pair1["enrollment"]["id"],
        {"expected_offering_version": fresh_version},
        registrar_headers,
    )
    validate_error(response, ApiErrorId.ERR_NO_SEATS_AVAILABLE.value)
    assert get_enrollment(pair1["enrollment"]["id"])["status"] == "WITHDRAWN"


def test_overpayment_rejected(api, bursar_headers):
    """PRD 3.7: "The payment is rejected with `ERR_INVOICE_INVALID_STATE` (HTTP 409)
    when the invoice is not in `ISSUED` or `PARTIALLY_PAID` — a `VOIDED` invoice
    cannot take payments — and with `ERR_OVERPAYMENT` (HTTP 409) when the payment
    would push the payer's running paid total above that payer's billed share."
    PRD 3.7: "When the cumulative paid total across all three buckets is greater
    than 0 but less than `tuition_total_cents`, the invoice's `status` moves to
    `PARTIALLY_PAID`; when the cumulative total equals `tuition_total_cents`, it
    moves to `PAID`."

    Design: Corner/validations/overpayment_rejected
    """
    ctx = setup_base()
    pair = register_and_confirm(ctx)
    invoice = first_invoice_for_enrollment(pair["enrollment"]["id"])
    assert invoice["family_amount_cents"] == 30000
    pay_invoice(invoice["id"], "FAMILY", 30000)

    response = api.create_payment(
        invoice["id"], {"payer": "FAMILY", "amount_cents": 1}, bursar_headers
    )
    validate_error(response, ApiErrorId.ERR_OVERPAYMENT.value)

    # The STATE bucket still has its full 90000-cent room; paying it completes
    # the invoice.
    state_payment = api.create_payment(
        invoice["id"], {"payer": "STATE", "amount_cents": 90000}, bursar_headers
    )
    validate_success(state_payment, 201)
    final_invoice = get_invoice(invoice["id"])
    assert final_invoice["status"] == "PAID", (
        f"paid 120000 == tuition_total_cents 120000 must flip the status to PAID, "
        f"got {final_invoice['status']}"
    )
