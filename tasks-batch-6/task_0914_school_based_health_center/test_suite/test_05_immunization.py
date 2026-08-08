"""Immunization records: dose validity dates, the compliance posture and the
cascade a void sets off."""

from test_helpers import (
    assert_dose,
    assert_instant_ordering,
    assert_same_date,
    assert_student_dose_counter_identity,
    dose_payload,
    get_clearance,
    get_dose,
    get_student,
    notifications_for_student,
    record_clearance,
    record_dose,
    run_daily_sweep,
    set_clock,
    setup_enrolled_student,
    setup_fully_immunized_student,
    setup_visit_in_progress,
    validate_success,
    void_dose,
)


def _student_with_first_hepb_dose():
    """One ACTIVE enrollment and one VALID HEPB dose 1 on 2025-09-01."""
    ctx = setup_enrolled_student(guardians=[], consents=())
    ctx["hepb1"] = record_dose(
        ctx["student"]["id"], ctx["clinician"]["id"], "HEPB", 1, "2025-09-01"
    )
    return ctx


def test_second_dose_one_day_before_the_grace_adjusted_date_is_invalid(api):
    """PRD §3.7: "If such a predecessor exists, the strict earliest valid date is
    that predecessor's `administered_date` advanced by the series interval: 28
    days for the second `HEPB` dose, 56 days for the third `HEPB` dose, and 28
    days for the second `MMR` dose. The **earliest valid date** is then the strict
    date pulled 4 days earlier — a grace of 4 calendar days."
    PRD §3.7: "A dose that fails carries an `invalid_reason` of `MIN_AGE_NOT_MET`
    when it is a first dose and `MIN_INTERVAL_NOT_MET` when it is a later one."

    Design: Difficulty/boundary_precision_check/dose_valid_exactly_on_grace_adjusted_earliest_date_invalid_one_day_before
    """
    ctx = _student_with_first_hepb_dose()

    resp = api.create_immunization_dose(
        ctx["student"]["id"],
        dose_payload("HEPB", 2, "2025-09-24"),
        ctx["clinician_headers"],
    )
    early = validate_success(resp, 201)

    assert_dose(early)
    assert early["status"] == "INVALID_TOO_EARLY"
    assert early["invalid_reason"] == "MIN_INTERVAL_NOT_MET"
    assert_same_date(early["strict_earliest_valid_date"], "2025-09-29", "strict_earliest_valid_date")
    assert_same_date(early["earliest_valid_date"], "2025-09-25", "earliest_valid_date")


def test_second_dose_exactly_on_the_grace_adjusted_date_is_valid(api):
    """PRD §3.7: "The dose's `status` follows directly: it is `VALID` when
    `administered_date` falls on or after `earliest_valid_date` — the boundary is
    inclusive, so a dose given exactly on the earliest valid date counts — and
    `INVALID_TOO_EARLY` otherwise."
    PRD §3.7: "A `VALID` dose has a null `invalid_reason`. Recording any dose
    recomputes the student's four counters — `valid_dose_count` counts doses in
    `VALID`, `invalid_dose_count` counts doses in `INVALID_TOO_EARLY`,
    `voided_dose_count` counts doses in `VOIDED`, and `total_dose_count` is every
    dose row for that student and equals the sum of the other three — recomputes
    the compliance posture, and increments the student's `version` by 1."

    Design: Difficulty/boundary_precision_check/dose_valid_exactly_on_grace_adjusted_earliest_date_invalid_one_day_before
    """
    ctx = _student_with_first_hepb_dose()
    validate_success(
        api.create_immunization_dose(
            ctx["student"]["id"], dose_payload("HEPB", 2, "2025-09-24"), ctx["clinician_headers"]
        ),
        201,
    )

    resp = api.create_immunization_dose(
        ctx["student"]["id"],
        dose_payload("HEPB", 2, "2025-09-25"),
        ctx["clinician_headers"],
    )
    edge = validate_success(resp, 201)

    assert edge["status"] == "VALID"
    assert edge["invalid_reason"] is None
    assert_same_date(edge["earliest_valid_date"], "2025-09-25", "earliest_valid_date")

    student = get_student(ctx["student"]["id"])
    assert student["valid_dose_count"] == 2
    assert student["invalid_dose_count"] == 1
    assert student["total_dose_count"] == 3
    assert_student_dose_counter_identity(student)
    assert student["immunization_compliance_status"] == "NON_COMPLIANT"


def test_voiding_a_dose_invalidates_its_successors_and_drops_the_posture(api):
    """PRD §3.7: "**Link one:** the dose itself becomes `VOIDED` and stops counting
    anywhere. **Link two:** because that dose is no longer valid, every later dose
    of the same student and series is re-evaluated, and any dose that has lost its
    valid predecessor moves `VALID → INVALID_TOO_EARLY` with `invalid_reason` set
    to `PREDECESSOR_VOIDED`. **Link three:** the student's counters and compliance
    posture are recomputed from the new dose statuses — the posture may fall to
    `NON_COMPLIANT` — and the student's `version` increments by 1."

    Design: Difficulty/transitive_cascade/dose_void_drives_five_link_compliance_and_clearance_cascade
    """
    ctx = setup_fully_immunized_student()
    assert ctx["student"]["immunization_compliance_status"] == "COMPLIANT"

    voided = validate_success(
        api.void_immunization_dose(
            ctx["doses"]["HEPB1"]["id"],
            {"reason": "Recorded against the wrong student"},
            ctx["clinician_headers"],
        )
    )

    assert voided["status"] == "VOIDED"
    for key in ("HEPB2", "HEPB3"):
        dose = get_dose(ctx["doses"][key]["id"])
        assert dose["status"] == "INVALID_TOO_EARLY", f"{key} lost its valid predecessor"
        assert dose["invalid_reason"] == "PREDECESSOR_VOIDED"
    for key in ("MMR1", "MMR2"):
        assert get_dose(ctx["doses"][key]["id"])["status"] == "VALID", (
            f"{key} belongs to another series and is untouched"
        )

    student = get_student(ctx["student"]["id"])
    assert student["immunization_compliance_status"] == "NON_COMPLIANT"
    assert student["valid_dose_count"] == 2
    assert student["invalid_dose_count"] == 2
    assert student["voided_dose_count"] == 1
    assert student["total_dose_count"] == 5
    assert_student_dose_counter_identity(student)


def test_voiding_a_dose_voids_the_clearance_and_orders_both_notifications(api):
    """PRD §3.7: "**Link four**, which fires only when link three actually produced
    `NON_COMPLIANT`: the student's sports-physical clearance whose status is
    `ACTIVE` or `PENDING_REEVALUATION` moves to `VOIDED` with a `void_reason` of
    `IMMUNIZATION_COMPLIANCE_LOST`. **Link five:** that clearance void creates a
    parent notification of event type `CLEARANCE_VOIDED`. When both notifications
    arise from one void, their order is pinned: the `IMMUNIZATION_NON_COMPLIANT`
    notification raised by link three is created **before** the `CLEARANCE_VOIDED`
    notification raised by link five."

    Design: Difficulty/transitive_cascade/dose_void_drives_five_link_compliance_and_clearance_cascade
    """
    ctx = setup_fully_immunized_student()
    ctx = setup_visit_in_progress(
        ctx, visit_type="SPORTS_PHYSICAL", scheduled_start_at="2026-05-10T10:00:00Z"
    )
    clearance = record_clearance(ctx["visit"]["id"], ctx["clinician"]["id"], "CLEARED")
    assert clearance["status"] == "ACTIVE"

    void_dose(ctx["doses"]["HEPB1"]["id"], ctx["clinician"]["id"])

    voided_clearance = get_clearance(clearance["id"])
    assert voided_clearance["status"] == "VOIDED"
    assert voided_clearance["void_reason"] == "IMMUNIZATION_COMPLIANCE_LOST"

    non_compliant = notifications_for_student(
        ctx["student"]["id"], event_type="IMMUNIZATION_NON_COMPLIANT"
    )
    voided_notices = notifications_for_student(
        ctx["student"]["id"], event_type="CLEARANCE_VOIDED"
    )
    assert len(non_compliant) == 1, (
        f"Expected exactly one IMMUNIZATION_NON_COMPLIANT notification, got {len(non_compliant)}"
    )
    assert len(voided_notices) == 1, (
        f"Expected exactly one CLEARANCE_VOIDED notification, got {len(voided_notices)}"
    )
    assert non_compliant[0]["status"] == "QUEUED"
    assert voided_notices[0]["status"] == "QUEUED"
    assert_instant_ordering(
        non_compliant[0]["created_at"],
        voided_notices[0]["created_at"],
        "IMMUNIZATION_NON_COMPLIANT before CLEARANCE_VOIDED",
    )


def test_provisional_posture_holds_to_day_thirty_then_lapses_on_the_sweep(api):
    """PRD §3.7: "otherwise a student whose `ACTIVE` enrollment has a non-null
    `activated_at`, whose current logical clock date is at or before that
    activation date advanced by 30 days, and who has at least 1 valid `HEPB` dose
    and at least 1 valid `MMR` dose, is `PROVISIONAL`; otherwise the student is
    `NON_COMPLIANT`. The 30-day provisional window is inclusive on its far end — on
    day 30 the student is still provisional, on day 31 they are not"
    PRD §3.12: "and it recomputes every student's `immunization_compliance_status`,
    which is where a `PROVISIONAL` posture lapses to `NON_COMPLIANT` once the
    30-day provisional window closes."

    Design: Corner/calculations/provisional_compliance_holds_to_day_thirty_then_lapses_on_sweep
    """
    ctx = setup_enrolled_student(guardians=[], consents=())
    hepb1 = record_dose(ctx["student"]["id"], ctx["clinician"]["id"], "HEPB", 1, "2026-05-01")
    mmr1 = record_dose(ctx["student"]["id"], ctx["clinician"]["id"], "MMR", 1, "2026-05-02")

    assert hepb1["status"] == "VALID"
    assert mmr1["status"] == "VALID"
    assert get_student(ctx["student"]["id"])["immunization_compliance_status"] == "PROVISIONAL"

    set_clock("2026-06-03T09:00:00Z")
    run_daily_sweep()
    assert get_student(ctx["student"]["id"])["immunization_compliance_status"] == "PROVISIONAL", (
        "Day 30 is inside the inclusive provisional window"
    )

    set_clock("2026-06-04T09:00:00Z")
    run_daily_sweep()
    student = get_student(ctx["student"]["id"])
    assert student["immunization_compliance_status"] == "NON_COMPLIANT", (
        "Day 31 is outside the provisional window"
    )
    assert student["valid_dose_count"] == 2
