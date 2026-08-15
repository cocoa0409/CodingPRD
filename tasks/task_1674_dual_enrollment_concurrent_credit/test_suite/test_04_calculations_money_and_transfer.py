"""Calculation claims: district-cap min() boundary, transfer-credit evaluation
variants, the 0-percent withdraw, and the calendar-sensitive W-posting rule
(PRD 3.5, 3.7, 3.8, 3.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_invoice_conservation,
    confirm_enrollment,
    create_articulation_agreement,
    create_college_term,
    create_course,
    create_enrollment,
    create_funding_agreement,
    create_high_school,
    create_hs_term,
    create_instructor,
    create_offering,
    create_student,
    credential_course,
    finalize_offering,
    first_invoice_for_enrollment,
    get_enrollment,
    get_invoice,
    get_offering,
    list_transcript_entries_for_enrollment,
    make_registrar_headers,
    move_offering_to_grading,
    open_offering,
    open_term,
    register_and_confirm,
    set_clock,
    setup_base,
    setup_graded_scenario,
    setup_mismatch_withdraw_scenario,
    submit_grade,
    validate_error,
    validate_success,
    withdraw_enrollment,
)

REGISTRAR = make_registrar_headers()


def test_district_contract_cap_boundary_exact(api, admin_headers):
    """PRD 3.7: "Bucket 2 is the district: when the agreement's `funding_model` is
    `FAMILY_RESPONSIBLE` the district bucket is skipped entirely and
    `district_amount_cents` is 0; otherwise `district_amount_cents` is the smaller
    of the first remainder and `district_cap_cents`."
    PRD 3.7: "Bucket 3 is the family, which takes the remainder:
    `family_amount_cents` is the first remainder minus `district_amount_cents`."
    PRD 3.7: "The three buckets always sum to `tuition_total_cents`."

    Design: Corner/calculations/district_contract_cap_boundary_exact
    """
    school_a = create_high_school(name="Northview HS", district_code="NV-01")
    school_b = create_high_school(name="Southview HS", district_code="SV-02")
    college_term = create_college_term()
    hs_term_a = create_hs_term(school_a["id"], name="Fall 2026 HS-A")
    hs_term_b = create_hs_term(school_b["id"], name="Fall 2026 HS-B")
    course = create_course()
    instructor = create_instructor(school_a["id"])
    credential_course(instructor["id"], course["id"], qualification_summary="MA History")
    create_funding_agreement(
        school_a["id"],
        college_term["id"],
        funding_model="DISTRICT_CONTRACT",
        state_rate_cents_per_credit=0,
        district_cap_cents=120000,
    )
    create_funding_agreement(
        school_b["id"],
        college_term["id"],
        funding_model="DISTRICT_CONTRACT",
        state_rate_cents_per_credit=0,
        district_cap_cents=119999,
    )
    offering_a = create_offering(
        course["id"], college_term["id"], hs_term_a["id"], school_a["id"], instructor["id"]
    )
    offering_b = create_offering(
        course["id"], college_term["id"], hs_term_b["id"], school_b["id"], instructor["id"]
    )
    open_term(college_term["id"])
    open_term(hs_term_a["id"])
    open_term(hs_term_b["id"])
    open_offering(offering_a["id"])
    open_offering(offering_b["id"])

    student_a = create_student(school_a["id"], full_name="Alpha One", grade_level=11)
    student_b = create_student(school_b["id"], full_name="Beta Two", grade_level=12)
    enr_a = create_enrollment(student_a["id"], offering_a["id"])
    enr_b = create_enrollment(student_b["id"], offering_b["id"])
    confirm_enrollment(offering_a["id"], enr_a["id"])
    confirm_enrollment(offering_b["id"], enr_b["id"])

    invoice_a = first_invoice_for_enrollment(enr_a["id"])
    invoice_b = first_invoice_for_enrollment(enr_b["id"])
    assert invoice_a["tuition_total_cents"] == 120000
    assert invoice_a["state_amount_cents"] == 0, (
        "DISTRICT_CONTRACT never uses the state bucket"
    )
    assert invoice_a["district_amount_cents"] == 120000, (
        f"cap == tuition: the min() boundary includes equality, got "
        f"{invoice_a['district_amount_cents']}"
    )
    assert invoice_a["family_amount_cents"] == 0
    assert_invoice_conservation(invoice_a)

    assert invoice_b["tuition_total_cents"] == 120000
    assert invoice_b["state_amount_cents"] == 0
    assert invoice_b["district_amount_cents"] == 119999, (
        f"One cent below the cap must bind at 119999, got "
        f"{invoice_b['district_amount_cents']}"
    )
    assert invoice_b["family_amount_cents"] == 1, (
        f"One cent below the cap leaves exactly one family cent, got "
        f"{invoice_b['family_amount_cents']}"
    )
    assert_invoice_conservation(invoice_b)


def test_transfer_evaluation_articulated_vs_native_loss(api, admin_headers):
    """PRD 3.9: "The enrollment is eligible when such an agreement exists and the
    enrollment's grade meets `min_grade_for_transfer` under the ordering `A` above
    `B` above `C`; `F` and `W` are never eligible."
    PRD 3.9: "The read returns two readings of the same completed course: the
    articulated reading, `articulated_credit_hours`, is the agreement's
    `transfer_credit_hours` when eligible and 0 otherwise; the native reading,
    `native_credit_hours`, is the course's `college_credit_hours` when eligible and
    0 otherwise; and `credit_loss_hours` is `native_credit_hours` minus
    `articulated_credit_hours`, the delta between the two readings whenever the
    target grants fewer hours than the college awarded."

    Design: Corner/calculations/transfer_evaluation_articulated_vs_native_loss
    """
    ctx = setup_graded_scenario(grade="B")
    create_articulation_agreement(ctx["course"]["id"], "StateU")
    # The clock still reads 2026-12-16 after finalization — inside the window.
    data = validate_success(
        api.get_transfer_evaluation(ctx["enrollment"]["id"], "StateU", admin_headers)
    )
    assert data["eligible"] is True, "Grade B meets min_grade_for_transfer C"
    assert data["articulated_credit_hours"] == pytest.approx(2.5, abs=1e-9)
    assert data["native_credit_hours"] == pytest.approx(3, abs=1e-9)
    assert data["credit_loss_hours"] == pytest.approx(0.5, abs=1e-9)


def test_transfer_evaluation_inactive_agreement_zero(api, admin_headers):
    """PRD 3.9: "The active window is a closed interval — the agreement is active
    when the logical clock reads at or after `effective_from` and at or before
    `effective_to`."
    PRD 3.9: "the articulated reading, `articulated_credit_hours`, is the
    agreement's `transfer_credit_hours` when eligible and 0 otherwise; the native
    reading, `native_credit_hours`, is the course's `college_credit_hours` when
    eligible and 0 otherwise"

    Design: Corner/calculations/transfer_evaluation_inactive_agreement_zero
    """
    ctx = setup_graded_scenario(grade="B")
    create_articulation_agreement(ctx["course"]["id"], "StateU")
    set_clock("2027-01-05T00:00:00Z")  # past effective_to 2026-12-31

    data = validate_success(
        api.get_transfer_evaluation(ctx["enrollment"]["id"], "StateU", admin_headers)
    )
    assert data["eligible"] is False, (
        "With the clock past effective_to the agreement is inactive"
    )
    assert data["articulated_credit_hours"] == 0
    assert data["native_credit_hours"] == 0
    assert data["credit_loss_hours"] == 0


def test_withdraw_plain_zero_pct_then_refund_rejected(api, bursar_headers):
    """PRD 3.5: "The invoice is settled per §3.7 with a `refund_pct` of 50 when the
    clock reads at or before the college term's `drop_deadline` and 0 otherwise —
    note that the college calendar alone governs the 50-percent compensation even
    though the high school calendar may have been what forced the withdraw, which
    is the cross-calendar mismatch window."
    PRD 3.7: "`refund_status` is set to `DUE` when the percentage is greater than 0
    and the sum of payments on the invoice is greater than 0, and `NONE` otherwise."
    PRD 3.7: "The settled variant fires when the `Bursar` processes the refund,
    moving `refund_status` from `DUE` to `PROCESSED` (any other starting value is
    rejected with `ERR_REFUND_NOT_DUE`, HTTP 409, including a second refund call on
    an already-processed invoice)."

    Design: Corner/calculations/withdraw_plain_zero_pct_then_refund_rejected
    """
    ctx = setup_mismatch_withdraw_scenario(withdraw_clock="2026-09-20T00:00:00Z")
    invoice = ctx["invoice"]
    assert invoice["refund_pct"] == 0, (
        f"Withdrawn 2026-09-20, past the college drop deadline 2026-09-15: "
        f"refund_pct must be 0, got {invoice['refund_pct']}"
    )
    assert invoice["refund_status"] == "NONE"
    assert invoice["status"] == "ISSUED", (
        f"A 0-percent withdraw does not void the invoice, got {invoice['status']}"
    )

    response = api.refund_invoice(invoice["id"], bursar_headers)
    validate_error(response, ApiErrorId.ERR_REFUND_NOT_DUE.value)


def test_finalize_hs_w_posting_calendar_nuance(api):
    """PRD 3.8: "A `WITHDRAWN` enrollment always produces a `COLLEGE` `PENDING`
    entry with grade `W`, and produces a `HIGH_SCHOOL` `PENDING` entry with grade
    `W` only when its `withdrawn_at` is strictly after the high school term's
    `drop_deadline` — a withdraw that happened before the high school's drop
    deadline leaves no record on the high school transcript."
    PRD 3.8: "a `COMPLETED` enrollment produces one `COLLEGE` entry whose
    `credit_value` is the course's `college_credit_hours` and one `HIGH_SCHOOL`
    entry whose `credit_value` is the course's `hs_credit_units`, both in `PENDING`
    status with the grade copied from the enrollment."

    Design: Corner/calculations/finalize_hs_w_posting_calendar_nuance
    """
    # Reversed mismatch: the COLLEGE drop deadline (09-10) precedes the HS one
    # (09-15), so a withdraw at 09-12 is at/before the HS drop deadline.
    ctx = setup_base(
        college_term_overrides={"drop_deadline": "2026-09-10T00:00:00Z"},
        hs_term_overrides={"drop_deadline": "2026-09-15T00:00:00Z"},
    )
    pair1 = register_and_confirm(ctx, full_name="Alpha One", grade_level=11)
    pair2 = register_and_confirm(ctx, full_name="Beta Two", grade_level=12)

    set_clock("2026-09-12T00:00:00Z")
    withdraw_enrollment(pair1["enrollment"]["id"])

    move_offering_to_grading(ctx["offering"]["id"])
    submit_grade(pair2["enrollment"]["id"], "A", ctx["instructor"]["id"])
    finalize_offering(ctx["offering"]["id"])

    e1_entries = list_transcript_entries_for_enrollment(pair1["enrollment"]["id"])
    assert len(e1_entries) == 1, (
        f"withdrawn_at 2026-09-12 <= hs drop 2026-09-15 suppresses the HS entry; "
        f"expected exactly 1 entry, got {len(e1_entries)}"
    )
    assert e1_entries[0]["institution"] == "COLLEGE"
    assert e1_entries[0]["grade"] == "W"
    assert e1_entries[0]["credit_value"] == 3
    assert e1_entries[0]["status"] == "PENDING"

    e2_entries = list_transcript_entries_for_enrollment(pair2["enrollment"]["id"])
    assert len(e2_entries) == 2, (
        f"A COMPLETED enrollment produces one COLLEGE and one HIGH_SCHOOL entry, "
        f"got {len(e2_entries)}"
    )
    by_institution = {entry["institution"]: entry for entry in e2_entries}
    assert by_institution["COLLEGE"]["credit_value"] == 3
    assert by_institution["COLLEGE"]["grade"] == "A"
    assert by_institution["HIGH_SCHOOL"]["credit_value"] == 1.0
    assert by_institution["HIGH_SCHOOL"]["grade"] == "A"

    assert get_enrollment(pair1["enrollment"]["id"])["status"] == "WITHDRAWN"
    assert get_enrollment(pair2["enrollment"]["id"])["status"] == "COMPLETED"


def test_transfer_evaluation_requires_completed(api, admin_headers):
    """PRD 3.9: "Transfer evaluation is a computed read over a `COMPLETED`
    enrollment — any other enrollment status fails with
    `ERR_ENROLLMENT_INVALID_STATE` — taking a `target_institution` query parameter."

    Design: Corner/endpoints/transfer_evaluation_requires_completed
    """
    ctx = setup_base()
    pair = register_and_confirm(ctx)
    assert pair["enrollment"]["status"] == "REGISTERED"
    create_articulation_agreement(ctx["course"]["id"], "StateU")

    response = api.get_transfer_evaluation(pair["enrollment"]["id"], "StateU", admin_headers)
    validate_error(response, ApiErrorId.ERR_ENROLLMENT_INVALID_STATE.value)
