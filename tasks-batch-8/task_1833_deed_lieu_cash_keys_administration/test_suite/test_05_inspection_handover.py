"""Handover inspection: scheduling constraints, the condition-deduction
schedule, the submission cascade, the holdover penalty, and the cure loop
(PRD §3.5, §3.6)."""
from test_helpers import (
    ApiErrorId,
    assert_inspection_report,
    create_appointment_payload,
    create_report_payload,
    get_agreement,
    get_case,
    make_inspector_headers,
    schedule_appointment,
    set_clock,
    setup_case_at_agreement_active,
    setup_case_at_disbursement_pending,
    submit_inspection_report,
    validate_error,
    validate_paginated,
    validate_success,
)

TWO_MATERIAL_LINES = [
    {"item_code": "CLEANLINESS_FAIL", "severity": "MATERIAL"},
    {"item_code": "DEBRIS_REMOVAL", "severity": "MATERIAL"},
]


def _bundle_with_handover_appointment(api, start="2026-09-05T10:00:00Z", end="2026-09-05T11:00:00Z"):
    """AGREEMENT_ACTIVE case plus a first HANDOVER appointment (case then sits in
    VACATE_PENDING per PRD §3.6)."""
    bundle = setup_case_at_agreement_active(loan_number="LN-OV2")
    appointment = schedule_appointment(
        bundle["case"]["id"], scheduled_start=start, scheduled_end=end
    )
    bundle["appointment"] = appointment
    bundle["case"] = get_case(bundle["case"]["id"])
    return bundle


def test_inspection_too_soon_rejected(api, specialist_headers):
    """A start less than 24 hours after the current logical time violates the
    notice minimum; no appointment is created.

    PRD §3.6: "For the notice, `scheduled_start` must fall at least 24 hours after the current logical time, failing which the request is rejected with `ERR_INSPECTION_TOO_SOON`."

    Design: Corner/validations/inspection_too_soon_rejected
    """
    bundle = setup_case_at_agreement_active(loan_number="LN-V14")
    case_id = bundle["case"]["id"]
    # Clock is 2026-08-01T00:00:00Z; a 23:00Z start is only 23 hours ahead.
    resp = api.create_inspection_appointment(
        create_appointment_payload(
            case_id,
            inspector_id="insp_9",
            appointment_type="HANDOVER",
            scheduled_start="2026-08-01T23:00:00Z",
            scheduled_end="2026-08-02T00:00:00Z",
        ),
        specialist_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INSPECTION_TOO_SOON.value)
    appointments = validate_paginated(api.list_case_inspection_appointments(case_id, specialist_headers))[0]
    assert appointments == [], "no appointment may be created for a too-soon start"


def test_conflict_outranks_notice_error(api, specialist_headers):
    """An appointment that both collides with the inspector's buffered calendar
    and violates the 24-hour notice reports the calendar conflict — the pinned
    order puts the constraint check first.

    PRD §3.6: "Two constraints are then evaluated in a pinned order, calendar conflict first, notice second."
    PRD §2.10: "On inspection scheduling, the calendar-conflict rule is evaluated before the minimum-notice rule."

    Design: Difficulty/priority_pair_validation_conflict/constraint_beats_temporal_on_schedule
    """
    bundle = _bundle_with_handover_appointment(api)  # insp_1 holds 2026-09-05T10:00-11:00Z
    set_clock("2026-09-05T09:00:00Z")  # a 10:30Z start is also inside the 24h notice window

    resp = api.create_inspection_appointment(
        create_appointment_payload(
            bundle["case"]["id"],
            inspector_id="insp_1",
            appointment_type="HANDOVER",
            scheduled_start="2026-09-05T10:30:00Z",
            scheduled_end="2026-09-05T11:30:00Z",
        ),
        specialist_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INSPECTOR_SCHEDULE_CONFLICT.value)


def test_conflict_outranks_notice_no_side_effects(api, specialist_headers):
    """The doubly-invalid appointment is rejected wholesale: no second
    appointment exists and the case stays VACATE_PENDING.

    PRD §3.6: "Two constraints are then evaluated in a pinned order, calendar conflict first, notice second. For the calendar, the new appointment's half-open interval — extended by a 30-minute travel buffer at its end — must not intersect any other `SCHEDULED` appointment's similarly buffered interval for the same `inspector_id`; intervals that merely touch are allowed, and a genuine conflict is rejected with `ERR_INSPECTOR_SCHEDULE_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/constraint_beats_temporal_on_schedule
    """
    bundle = _bundle_with_handover_appointment(api)
    case_id = bundle["case"]["id"]
    set_clock("2026-09-05T09:00:00Z")

    resp = api.create_inspection_appointment(
        create_appointment_payload(
            case_id,
            inspector_id="insp_1",
            appointment_type="HANDOVER",
            scheduled_start="2026-09-05T10:30:00Z",
            scheduled_end="2026-09-05T11:30:00Z",
        ),
        specialist_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INSPECTOR_SCHEDULE_CONFLICT.value)

    appointments = validate_paginated(api.list_case_inspection_appointments(case_id, specialist_headers))[0]
    assert len(appointments) == 1, "the rejected appointment must not be persisted"
    assert get_case(case_id)["status"] == "VACATE_PENDING"


def test_inspector_buffer_conflict_inside(api, specialist_headers):
    """An 11:15Z start falls inside the 30-minute end buffer of the existing
    10:00-11:00Z appointment (buffered to 11:30Z) and conflicts.

    PRD §3.6: "For the calendar, the new appointment's half-open interval — extended by a 30-minute travel buffer at its end — must not intersect any other `SCHEDULED` appointment's similarly buffered interval for the same `inspector_id`; intervals that merely touch are allowed, and a genuine conflict is rejected with `ERR_INSPECTOR_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/inspector_buffer_conflict_half_open
    """
    bundle = _bundle_with_handover_appointment(api)  # 10:00-11:00Z buffered to 11:30Z

    resp = api.create_inspection_appointment(
        create_appointment_payload(
            bundle["case"]["id"],
            inspector_id="insp_1",
            appointment_type="RE_INSPECTION",
            scheduled_start="2026-09-05T11:15:00Z",
            scheduled_end="2026-09-05T12:00:00Z",
        ),
        specialist_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INSPECTOR_SCHEDULE_CONFLICT.value)


def test_inspector_buffer_touching_allowed(api, specialist_headers):
    """An 11:30Z start touches the buffer boundary exactly; half-open semantics
    permit it.

    PRD §3.6: "For the calendar, the new appointment's half-open interval — extended by a 30-minute travel buffer at its end — must not intersect any other `SCHEDULED` appointment's similarly buffered interval for the same `inspector_id`; intervals that merely touch are allowed, and a genuine conflict is rejected with `ERR_INSPECTOR_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/inspector_buffer_conflict_half_open
    """
    bundle = _bundle_with_handover_appointment(api)

    created = validate_success(
        api.create_inspection_appointment(
            create_appointment_payload(
                bundle["case"]["id"],
                inspector_id="insp_1",
                appointment_type="RE_INSPECTION",
                scheduled_start="2026-09-05T11:30:00Z",
                scheduled_end="2026-09-05T12:30:00Z",
            ),
            specialist_headers,
        ),
        201,
    )
    assert created["status"] == "SCHEDULED"
    assert created["inspector_id"] == "insp_1"


def test_no_access_marks_appointment(api, inspector_headers):
    """No-access flips the appointment to NO_ACCESS without moving the case.

    PRD §3.6: "The specialist may cancel a `SCHEDULED` appointment; the inspector assigned to it may record a no-access outcome — both demand the `SCHEDULED` state, otherwise `ERR_APPOINTMENT_INVALID_STATE`, and the no-access action additionally requires the acting inspector's `X-User-ID` to equal the appointment's `inspector_id` (`ERR_FORBIDDEN`)."
    PRD §3.6: "A no-access outcome is holdover evidence rather than a case transition: the case state does not change, and the specialist may cancel while the manager weighs escalation."

    Design: Corner/state_machines/no_access_marks_appointment
    """
    bundle = setup_case_at_agreement_active(loan_number="LN-S11")
    appointment = schedule_appointment(
        bundle["case"]["id"], scheduled_start="2026-09-01T10:00:00Z", scheduled_end="2026-09-01T11:00:00Z"
    )
    assert get_case(bundle["case"]["id"])["status"] == "VACATE_PENDING"
    set_clock("2026-09-01T10:15:00Z")

    marked = validate_success(api.no_access_inspection_appointment(appointment["id"], inspector_headers))
    assert marked["status"] == "NO_ACCESS"
    assert get_case(bundle["case"]["id"])["status"] == "VACATE_PENDING", "no-access must not move the case"


def test_inspector_cannot_report_on_others_appointment(api, inspector_2_headers):
    """The inspector identity must match the appointment's inspector_id; another
    inspector's report creation is forbidden.

    PRD §2.10: "Second, authorization and ownership: the acting role appears in the endpoint's authorized set, and entity-backed ownership holds — a Borrower's `X-User-ID` must equal the parent case's `borrower_id` to counter or accept an agreement, and an Inspector's `X-User-ID` must equal the appointment's `inspector_id` to create or submit a report or record a no-access — failing which the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/inspector_cannot_report_on_others_appointment
    """
    bundle = setup_case_at_agreement_active(loan_number="LN-RB4")
    appointment = schedule_appointment(
        bundle["case"]["id"], scheduled_start="2026-09-01T10:00:00Z", scheduled_end="2026-09-01T11:00:00Z"
    )

    resp = api.create_inspection_report(
        appointment["id"], create_report_payload(), inspector_2_headers  # insp_2 != insp_1
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
    reports = validate_paginated(api.list_appointment_reports(appointment["id"], inspector_2_headers))[0]
    assert reports == [], "no report may be created by a different inspector"


def test_per_item_rounding_two_material_lines(api, inspector_headers):
    """Each line rounds half-up before summation: MATERIAL CLEANLINESS_FAIL
    (22,499) + MATERIAL DEBRIS_REMOVAL (37,499) = 59,998.

    PRD §3.6: "The per-item rounding order is pinned, because it genuinely differs from the alternative: two `MATERIAL` lines on `CLEANLINESS_FAIL` and `DEBRIS_REMOVAL` round to 22,499 and 37,499 cents respectively for a total of 59,998, whereas summing the raw products first would yield 59,997 — the per-item order is the only correct one."

    Design: Difficulty/combinatorial_formula/condition_deduction_per_item_rounding
    """
    bundle = setup_case_at_agreement_active(loan_number="LN-CF2")
    appointment = schedule_appointment(
        bundle["case"]["id"], scheduled_start="2026-09-05T10:00:00Z", scheduled_end="2026-09-05T11:00:00Z"
    )
    report = submit_inspection_report(
        appointment["id"],
        {"broom_clean_verified": True, "keys_returned_count": 2, "line_items": TWO_MATERIAL_LINES},
        submit_clock="2026-09-05T10:30:00Z",
    )
    assert_inspection_report(report)
    assert report["total_deduction_cents"] == 59998, (
        f"per-item round 22499 + 37499 must total 59998, got {report['total_deduction_cents']}"
    )
    assert report["result"] == "PASSED_WITH_DEDUCTIONS"


def test_per_item_rounding_half_up_single_line(api, inspector_headers):
    """A single MATERIAL CLEANLINESS_FAIL line rounds 22,498.5 half-up to 22,499.

    PRD §3.6: "each line item's base amount — 14,999 cents for `CLEANLINESS_FAIL`, 24,999 for `DEBRIS_REMOVAL`, 39,999 for `APPLIANCE_REMOVED`, 59,999 for `FIXTURE_DAMAGE`, and 149,999 for `STRUCTURAL_DAMAGE` — is multiplied by the severity multiplier, 1.0 for `STANDARD` and 1.5 for `MATERIAL`, and each product is rounded half-up to whole cents before any summation; `total_deduction_cents` is then the sum of those rounded line amounts."

    Design: Difficulty/combinatorial_formula/condition_deduction_per_item_rounding
    """
    bundle = setup_case_at_agreement_active(loan_number="LN-CF2")
    appointment = schedule_appointment(
        bundle["case"]["id"], scheduled_start="2026-09-01T10:00:00Z", scheduled_end="2026-09-01T11:00:00Z"
    )
    report = submit_inspection_report(
        appointment["id"],
        {"broom_clean_verified": True, "keys_returned_count": 2,
         "line_items": [{"item_code": "CLEANLINESS_FAIL", "severity": "MATERIAL"}]},
        submit_clock="2026-09-01T10:30:00Z",
    )
    assert report["total_deduction_cents"] == 22499, (
        f"round_half_up(14999*1.5) must be 22499, got {report['total_deduction_cents']}"
    )
    assert report["result"] == "PASSED_WITH_DEDUCTIONS"


def test_report_submit_cascade_report_and_appointment(api, inspector_headers):
    """Hop 1 of the submission cascade: the report computes its deductions and
    result, and the appointment completes.

    PRD §3.6: "The submission cascades in hops. First, the appointment moves from `SCHEDULED` to `COMPLETED`, and the case moves from `VACATE_PENDING` to `HANDOVER_INSPECTION`, stamping `handover_date` with the logical date at submit and setting `keys_returned` — true exactly when the latest submitted handover report's `keys_returned_count` is greater than zero."

    Design: Difficulty/transitive_cascade/report_submit_cascade_to_disbursement_state
    """
    bundle = setup_case_at_agreement_active(loan_number="LN-TC2")
    appointment = schedule_appointment(
        bundle["case"]["id"], scheduled_start="2026-09-05T10:00:00Z", scheduled_end="2026-09-05T11:00:00Z"
    )
    report = submit_inspection_report(
        appointment["id"],
        {"broom_clean_verified": True, "keys_returned_count": 2, "line_items": TWO_MATERIAL_LINES},
        submit_clock="2026-09-05T10:30:00Z",
    )
    assert report["status"] == "SUBMITTED"
    assert report["result"] == "PASSED_WITH_DEDUCTIONS"
    assert report["total_deduction_cents"] == 59998

    appt = validate_success(api.get_inspection_appointment(appointment["id"], inspector_headers))
    assert appt["status"] == "COMPLETED", "the appointment completes with the submission (hop 1)"


def test_report_submit_cascade_case_and_agreement(api, inspector_headers):
    """Hops 2-3: the passing report advances the case to DISBURSEMENT_PENDING,
    stamps handover facts, and recomputes the agreement on the INSPECTED basis.

    PRD §3.6: "Second, the case forks on the result: a `PASSED` or `PASSED_WITH_DEDUCTIONS` report advances it from `HANDOVER_INSPECTION` to `DISBURSEMENT_PENDING`, flips the agreement's `condition_basis` from `SELF_REPORTED` to `INSPECTED`, and computes `final_assistance_cents` (which in turn recomputes the case's `remaining_assistance_cents`); a `FAILED` report loops the case back from `HANDOVER_INSPECTION` to `VACATE_PENDING` for cure and re-inspection."

    Design: Difficulty/transitive_cascade/report_submit_cascade_to_disbursement_state
    """
    bundle = setup_case_at_disbursement_pending(
        loan_number="LN-TC2",
        handover_start="2026-09-05T10:00:00Z",
        handover_end="2026-09-05T11:00:00Z",
        submit_clock="2026-09-05T10:30:00Z",
        report_overrides={"broom_clean_verified": True, "keys_returned_count": 2,
                          "line_items": TWO_MATERIAL_LINES},
    )
    case = bundle["case"]
    assert case["status"] == "DISBURSEMENT_PENDING"
    assert case["handover_date"] == "2026-09-05"
    assert case["keys_returned"] is True

    agreement = bundle["agreement"]
    assert agreement["condition_basis"] == "INSPECTED"
    # 550000 provisional - 59998 deductions - 15000 penalty (1 day past grace) = 475002
    assert agreement["final_assistance_cents"] == 475002
    assert case["remaining_assistance_cents"] == 475002


def test_failed_report_loops_back(api, inspector_headers):
    """A FAILED report (broom-clean not verified) loops the case back to
    VACATE_PENDING for cure.

    PRD §3.6: "The report's `result` is then derived: `FAILED` when `broom_clean_verified` is false or any `STRUCTURAL_DAMAGE` line is present; otherwise `PASSED_WITH_DEDUCTIONS` when `total_deduction_cents` is greater than zero; otherwise `PASSED`."
    PRD §3.6: "Second, the case forks on the result: a `PASSED` or `PASSED_WITH_DEDUCTIONS` report advances it from `HANDOVER_INSPECTION` to `DISBURSEMENT_PENDING`, flips the agreement's `condition_basis` from `SELF_REPORTED` to `INSPECTED`, and computes `final_assistance_cents` (which in turn recomputes the case's `remaining_assistance_cents`); a `FAILED` report loops the case back from `HANDOVER_INSPECTION` to `VACATE_PENDING` for cure and re-inspection."

    Design: Difficulty/non_linear_state_machine/inspection_failure_reinspection_loop
    """
    bundle = setup_case_at_agreement_active(loan_number="LN-NL3")
    appointment = schedule_appointment(
        bundle["case"]["id"], scheduled_start="2026-09-01T10:00:00Z", scheduled_end="2026-09-01T11:00:00Z"
    )
    report = submit_inspection_report(
        appointment["id"],
        {"broom_clean_verified": False, "keys_returned_count": 0,
         "line_items": [{"item_code": "DEBRIS_REMOVAL", "severity": "STANDARD"}]},
        submit_clock="2026-09-01T10:30:00Z",
    )
    assert report["result"] == "FAILED"
    case = get_case(bundle["case"]["id"])
    assert case["status"] == "VACATE_PENDING", "FAILED report cures back to VACATE_PENDING"
    # The agreement is untouched by the failed loop.
    agreement = get_agreement(bundle["agreement"]["id"])
    assert agreement["status"] == "ACCEPTED"
    assert agreement["final_assistance_cents"] is None


def test_reinspection_pass_completes_loop(api, inspector_headers):
    """After the cure, a passing RE_INSPECTION re-enters the handover and computes
    final assistance from the passing report only (handover 2 days after vacate
    is inside grace, so 550,000 stands).

    PRD §3.6: "The holdover penalty accrues at 15,000 cents for each whole day the handover was late beyond a three-day grace period: take the whole-day difference between the case's `handover_date` and the agreement's `vacate_date`, subtract the three grace days, floor at zero, and multiply by 15,000 — so a handover exactly on the third day after the vacate date (the last grace day) accrues nothing, while the fourth day accrues 15,000 cents."
    PRD §3.6: "a `FAILED` report loops the case back from `HANDOVER_INSPECTION` to `VACATE_PENDING` for cure and re-inspection."

    Design: Difficulty/non_linear_state_machine/inspection_failure_reinspection_loop
    """
    bundle = setup_case_at_agreement_active(loan_number="LN-NL3")
    case_id = bundle["case"]["id"]
    appt1 = schedule_appointment(case_id, scheduled_start="2026-09-01T10:00:00Z",
                                 scheduled_end="2026-09-01T11:00:00Z")
    submit_inspection_report(
        appt1["id"],
        {"broom_clean_verified": False, "keys_returned_count": 0,
         "line_items": [{"item_code": "DEBRIS_REMOVAL", "severity": "STANDARD"}]},
        submit_clock="2026-09-01T10:30:00Z",
    )
    assert get_case(case_id)["status"] == "VACATE_PENDING"

    appt2 = schedule_appointment(
        case_id, appointment_type="RE_INSPECTION",
        scheduled_start="2026-09-03T10:00:00Z", scheduled_end="2026-09-03T11:00:00Z",
    )
    submit_inspection_report(
        appt2["id"],
        {"broom_clean_verified": True, "keys_returned_count": 2, "line_items": []},
        submit_clock="2026-09-03T10:30:00Z",
    )
    case = get_case(case_id)
    assert case["status"] == "DISBURSEMENT_PENDING"
    assert case["handover_date"] == "2026-09-03"
    agreement = get_agreement(bundle["agreement"]["id"])
    assert agreement["status"] == "ACCEPTED", "the agreement survives the cure loop"
    # handover 2026-09-03 is 2 days after vacate 2026-09-01: days_late = max(0, 2-3) = 0.
    assert agreement["final_assistance_cents"] == 550000


def test_second_submit_rejected(api, inspector_headers):
    """SUBMITTED is terminal for a report; a second submit is refused and the
    cascade does not re-fire.

    PRD §3.6: "The report must be `DRAFT` — a second submit is refused with `ERR_REPORT_INVALID_STATE` — and the acting inspector's identity must match the appointment's `inspector_id`."

    Design: Corner/state_machines/second_submit_of_report_rejected
    """
    bundle = setup_case_at_disbursement_pending(loan_number="LN-S10")
    report_id = bundle["report"]["id"]
    assert bundle["report"]["status"] == "SUBMITTED"

    resp = api.submit_inspection_report(report_id, inspector_headers)
    validate_error(resp, ApiErrorId.ERR_REPORT_INVALID_STATE.value)

    assert get_case(bundle["case"]["id"])["status"] == "DISBURSEMENT_PENDING"
    agreement = get_agreement(bundle["agreement"]["id"])
    assert agreement["final_assistance_cents"] == 550000, "final assistance must not recompute"


def test_final_assistance_zero_floor(api, inspector_headers):
    """Deductions (299,995) plus the capped penalty (275,000) exceed the 550,000
    provisional; the final floors at zero and the case still advances.

    PRD §3.6: "The `final_assistance_cents` is the provisional amount minus the deductions minus the capped penalty, floored at zero. A zero final assistance still advances the case to `DISBURSEMENT_PENDING` — though, as §3.7 makes clear, no disbursement can be created for a zero remaining amount."

    Design: Corner/calculations/final_assistance_zero_floor
    """
    bundle = setup_case_at_disbursement_pending(
        loan_number="LN-C3",
        handover_start="2026-09-30T10:00:00Z",
        handover_end="2026-09-30T11:00:00Z",
        submit_clock="2026-09-30T10:30:00Z",
        report_overrides={
            "broom_clean_verified": True,
            "keys_returned_count": 2,
            "line_items": [
                {"item_code": "CLEANLINESS_FAIL", "severity": "MATERIAL"},
                {"item_code": "DEBRIS_REMOVAL", "severity": "MATERIAL"},
                {"item_code": "APPLIANCE_REMOVED", "severity": "MATERIAL"},
                {"item_code": "FIXTURE_DAMAGE", "severity": "MATERIAL"},
                {"item_code": "FIXTURE_DAMAGE", "severity": "MATERIAL"},
            ],
        },
    )
    # 22499 + 37499 + 59999 + 89999 + 89999 = 299995; penalty min(26*15000, 275000) = 275000.
    assert bundle["report"]["total_deduction_cents"] == 299995
    agreement = bundle["agreement"]
    assert agreement["final_assistance_cents"] == 0, (
        f"max(0, 550000 - 299995 - 275000) must floor at 0, got {agreement['final_assistance_cents']}"
    )
    assert bundle["case"]["status"] == "DISBURSEMENT_PENDING"
    assert bundle["case"]["remaining_assistance_cents"] == 0


def test_grace_day3_zero_penalty(api, inspector_headers):
    """A handover exactly on vacate+3 (the last grace day) accrues no penalty.

    PRD §3.6: "The holdover penalty accrues at 15,000 cents for each whole day the handover was late beyond a three-day grace period: take the whole-day difference between the case's `handover_date` and the agreement's `vacate_date`, subtract the three grace days, floor at zero, and multiply by 15,000 — so a handover exactly on the third day after the vacate date (the last grace day) accrues nothing, while the fourth day accrues 15,000 cents."

    Design: Difficulty/boundary_precision_check/holdover_grace_day3_vs_day4
    """
    bundle = setup_case_at_disbursement_pending(
        loan_number="LN-BP3",
        handover_start="2026-09-04T10:00:00Z",
        handover_end="2026-09-04T11:00:00Z",
        submit_clock="2026-09-04T10:30:00Z",
        report_overrides={"broom_clean_verified": True, "keys_returned_count": 2, "line_items": []},
    )
    assert bundle["case"]["handover_date"] == "2026-09-04"
    assert bundle["agreement"]["final_assistance_cents"] == 550000, (
        f"grace day 3 must accrue 0 penalty, final got {bundle['agreement']['final_assistance_cents']}"
    )


def test_grace_day4_first_penalty_day(api, inspector_headers):
    """A handover on vacate+4 accrues exactly one penalty day (15,000): the two
    cases straddle the boundary by a single day.

    PRD §3.6: "The holdover penalty accrues at 15,000 cents for each whole day the handover was late beyond a three-day grace period: take the whole-day difference between the case's `handover_date` and the agreement's `vacate_date`, subtract the three grace days, floor at zero, and multiply by 15,000 — so a handover exactly on the third day after the vacate date (the last grace day) accrues nothing, while the fourth day accrues 15,000 cents."

    Design: Difficulty/boundary_precision_check/holdover_grace_day3_vs_day4
    """
    bundle_a = setup_case_at_disbursement_pending(
        loan_number="LN-BP3",
        handover_start="2026-09-04T10:00:00Z",
        handover_end="2026-09-04T11:00:00Z",
        submit_clock="2026-09-04T10:30:00Z",
        report_overrides={"broom_clean_verified": True, "keys_returned_count": 2, "line_items": []},
    )
    bundle_b = setup_case_at_disbursement_pending(
        loan_number="LN-BP4",
        handover_start="2026-09-05T13:00:00Z",
        handover_end="2026-09-05T14:00:00Z",
        submit_clock="2026-09-05T13:30:00Z",
        report_overrides={"broom_clean_verified": True, "keys_returned_count": 2, "line_items": []},
    )
    final_a = bundle_a["agreement"]["final_assistance_cents"]
    final_b = bundle_b["agreement"]["final_assistance_cents"]
    assert final_a == 550000
    assert final_b == 535000, f"one day past grace must cost 15000, final got {final_b}"
    assert final_a - final_b == 15000, "the grace boundary differs by exactly one penalty day"


def test_provisional_vs_final_money_divergence(api, inspector_headers):
    """The two assistance variants diverge by exactly the inspection deductions
    plus the capped holdover penalty: 550,000 provisional vs 475,002 final.

    PRD §3.6: "The final assistance settlement starts from the accepted agreement's `provisional_assistance_cents` and subtracts two independently computed components: the report's `total_deduction_cents` and the capped holdover penalty."
    PRD §3.6: "The `final_assistance_cents` is the provisional amount minus the deductions minus the capped penalty, floored at zero."

    Design: Difficulty/dual_variant_calc/assistance_provisional_vs_final_divergence
    """
    bundle = setup_case_at_disbursement_pending(
        loan_number="LN-DV1",
        handover_start="2026-09-05T10:00:00Z",
        handover_end="2026-09-05T11:00:00Z",
        submit_clock="2026-09-05T10:30:00Z",
        report_overrides={"broom_clean_verified": True, "keys_returned_count": 2,
                          "line_items": TWO_MATERIAL_LINES},
    )
    agreement = bundle["agreement"]
    assert agreement["provisional_assistance_cents"] == 550000, "provisional basis is unchanged by inspection"
    assert agreement["condition_basis"] == "INSPECTED"
    # deductions 59998 + penalty min(1*15000, 275000) = 15000 -> 550000 - 59998 - 15000
    assert agreement["final_assistance_cents"] == 475002
    assert bundle["report"]["total_deduction_cents"] == 59998
    assert bundle["report"]["result"] == "PASSED_WITH_DEDUCTIONS"


def test_provisional_vs_final_case_state(api, inspector_headers):
    """With the final basis computed, the case advances to DISBURSEMENT_PENDING
    and remaining assistance tracks the final amount.

    PRD §3.6: "Second, the case forks on the result: a `PASSED` or `PASSED_WITH_DEDUCTIONS` report advances it from `HANDOVER_INSPECTION` to `DISBURSEMENT_PENDING`, flips the agreement's `condition_basis` from `SELF_REPORTED` to `INSPECTED`, and computes `final_assistance_cents` (which in turn recomputes the case's `remaining_assistance_cents`); a `FAILED` report loops the case back from `HANDOVER_INSPECTION` to `VACATE_PENDING` for cure and re-inspection."
    PRD §3.5: "Once an agreement exists, the case's `remaining_assistance_cents` is the agreement's applicable assistance — `final_assistance_cents` when it has been set on the `ACCEPTED` or `COMPLETED` agreement, otherwise `provisional_assistance_cents` — minus the case's `total_disbursed_cents`; until an agreement exists, `remaining_assistance_cents` is null."

    Design: Difficulty/dual_variant_calc/assistance_provisional_vs_final_divergence
    """
    bundle = setup_case_at_disbursement_pending(
        loan_number="LN-DV1",
        handover_start="2026-09-05T10:00:00Z",
        handover_end="2026-09-05T11:00:00Z",
        submit_clock="2026-09-05T10:30:00Z",
        report_overrides={"broom_clean_verified": True, "keys_returned_count": 2,
                          "line_items": TWO_MATERIAL_LINES},
    )
    case = bundle["case"]
    assert case["status"] == "DISBURSEMENT_PENDING"
    assert case["remaining_assistance_cents"] == 475002
    assert case["handover_date"] == "2026-09-05"
    assert case["keys_returned"] is True


def test_holdover_penalty_cap_final(api, inspector_headers):
    """A 29-day-late handover accrues 390,000 of raw penalty, capped at half the
    provisional (275,000); final = 550,000 - 59,998 - 275,000 = 215,002.

    PRD §3.6: "The accrued penalty is then capped at half of the provisional assistance, that half computed by multiplying `provisional_assistance_cents` by 0.5 and rounding half-up to whole cents; the applied penalty is the lesser of the accrual and the cap."

    Design: Difficulty/combinatorial_formula/holdover_penalty_cap_evaluation_order
    """
    bundle = setup_case_at_disbursement_pending(
        loan_number="LN-CF3",
        handover_start="2026-09-30T10:00:00Z",
        handover_end="2026-09-30T11:00:00Z",
        submit_clock="2026-09-30T10:30:00Z",
        report_overrides={"broom_clean_verified": True, "keys_returned_count": 1,
                          "line_items": TWO_MATERIAL_LINES},
    )
    # days_late = 29 - 3 = 26 -> raw 390000; cap round(550000*0.5) = 275000 (pinned to provisional).
    assert bundle["agreement"]["final_assistance_cents"] == 215002, (
        f"550000 - 59998 - min(390000, 275000) must be 215002, got {bundle['agreement']['final_assistance_cents']}"
    )


def test_holdover_penalty_cap_handover_date(api, inspector_headers):
    """The case's handover_date is the logical date at submit, and the case
    advances despite the capped penalty.

    PRD §3.6: "First, the appointment moves from `SCHEDULED` to `COMPLETED`, and the case moves from `VACATE_PENDING` to `HANDOVER_INSPECTION`, stamping `handover_date` with the logical date at submit and setting `keys_returned` — true exactly when the latest submitted handover report's `keys_returned_count` is greater than zero."
    PRD §3.6: "The `final_assistance_cents` is the provisional amount minus the deductions minus the capped penalty, floored at zero."

    Design: Difficulty/combinatorial_formula/holdover_penalty_cap_evaluation_order
    """
    bundle = setup_case_at_disbursement_pending(
        loan_number="LN-CF3",
        handover_start="2026-09-30T10:00:00Z",
        handover_end="2026-09-30T11:00:00Z",
        submit_clock="2026-09-30T10:30:00Z",
        report_overrides={"broom_clean_verified": True, "keys_returned_count": 1,
                          "line_items": TWO_MATERIAL_LINES},
    )
    assert bundle["case"]["handover_date"] == "2026-09-30"
    assert bundle["case"]["status"] == "DISBURSEMENT_PENDING"
    assert bundle["case"]["remaining_assistance_cents"] == 215002
