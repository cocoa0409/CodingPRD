"""Difficulty queue A — non_linear_state_machine instances."""
import pytest
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    reset_clock, create_case, create_triaged_case, create_case_in_fieldwork,
    create_plan_payload, create_interview_payload,
    create_allegation_payload, create_subject_payload,
    create_calibrate_payload, create_recommendation_payload,
    setup_final_substantiated_finding,
    make_investigator_headers, make_manager_headers, make_hr_headers,
    make_gc_headers, TEST_DEFAULTS,
)

IC = TEST_USERS["intake_coordinator_headers"]
INV = TEST_USERS["investigator_headers"]
MGR = TEST_USERS["manager_headers"]
HR = TEST_USERS["hr_headers"]
GC = TEST_USERS["gc_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _setup_interview_past_window(api):
    """Case FIELDWORK; interview I [2026-05-02 14:00-15:00Z]; clock at 2026-05-03."""
    bundle = create_case_in_fieldwork(
        title="Case NL-1", allegation_category="HARASSMENT", severity="MEDIUM",
        department="Ops",
    )
    case = bundle["case"]
    interview = get_success_data(api.create_interview(
        case["id"],
        create_interview_payload(
            witness_ref="W-1", interviewer_id="inv-9",
            scheduled_start="2026-05-02T14:00:00Z",
            scheduled_end="2026-05-02T15:00:00Z",
        ),
        INV,
    ))
    reset_clock("2026-05-03T00:00:00Z")
    return {"case": case, "interview": interview}


def test_interview_no_show_reschedule_cycle_count_invariant(api):
    """PRD §3.5: "Each transition into `NO_SHOW` increments `no_show_count`
    by exactly 1."
    PRD §3.5: "On a successful reschedule `scheduled_start` and
    `scheduled_end` are overwritten by `new_start` and `new_end`, and
    `upjohn_delivered_at` is cleared..."

    Design: Difficulty/non_linear_state_machine/interview_no_show_reschedule_cycle
    """
    reset_clock()
    bundle = _setup_interview_past_window(api)
    interview = bundle["interview"]
    resp = api.transition_interview(interview["id"], {"to_status": "NO_SHOW"}, INV)
    n1 = validate_success(resp, expected_status=200)
    assert n1["no_show_count"] == 1
    # Reschedule — no_show_count survives
    resp = api.transition_interview(
        interview["id"],
        {"to_status": "SCHEDULED",
         "new_start": "2026-05-04T14:00:00Z",
         "new_end": "2026-05-04T15:00:00Z"},
        INV,
    )
    rescheduled = validate_success(resp, expected_status=200)
    assert rescheduled["no_show_count"] == 1
    assert rescheduled["scheduled_start"] == "2026-05-04T14:00:00Z"
    assert rescheduled["scheduled_end"] == "2026-05-04T15:00:00Z"


def test_interview_no_show_reschedule_cycle_completion(api):
    """PRD §3.5: "...`upjohn_delivered_at` is cleared — the Upjohn warning
    must be delivered anew before the rescheduled interview may complete."
    PRD §3.5: "On success `upjohn_delivered_at` is set to the current
    logical clock."

    After the cycle SCHEDULED -> NO_SHOW -> SCHEDULED -> UPJOHN_DELIVERED ->
    COMPLETED, the second-pass Upjohn stamp equals the clock at the second
    delivery instant (2026-05-04T14:30:00Z) and the interview ends COMPLETED.

    Design: Difficulty/non_linear_state_machine/interview_no_show_reschedule_cycle
    """
    reset_clock()
    bundle = _setup_interview_past_window(api)
    interview = bundle["interview"]
    get_success_data(api.transition_interview(interview["id"], {"to_status": "NO_SHOW"}, INV))
    get_success_data(api.transition_interview(
        interview["id"],
        {"to_status": "SCHEDULED",
         "new_start": "2026-05-04T14:00:00Z",
         "new_end": "2026-05-04T15:00:00Z"},
        INV,
    ))
    reset_clock("2026-05-04T14:30:00Z")
    resp = api.transition_interview(interview["id"], {"to_status": "UPJOHN_DELIVERED"}, INV)
    upj = validate_success(resp, expected_status=200)
    assert upj["upjohn_delivered_at"] == "2026-05-04T14:30:00Z"
    resp = api.transition_interview(
        interview["id"],
        {"to_status": "COMPLETED", "completion_note": "rescheduled memo"},
        INV,
    )
    done = validate_success(resp, expected_status=200)
    assert done["status"] == "COMPLETED"


def _setup_final_substantiated_with_approved_rec(api, severity="HIGH"):
    """Case FINDINGS with one FINAL SUBSTANTIATED finding carrying an
    APPROVED disciplinary recommendation. Returns dict."""
    bundle = setup_final_substantiated_finding(severity=severity)
    finding = bundle["finding"]
    hr1 = make_hr_headers(TEST_DEFAULTS["HR_ID"])
    rec = get_success_data(api.create_disciplinary_recommendation(
        finding["id"],
        create_recommendation_payload(
            mitigation_count=0, aggravation_count=0, recommended_action="WARNING",
        ),
        hr1,
    ))
    mgr = make_manager_headers(TEST_DEFAULTS["APPROVER_ID"])
    rec = get_success_data(api.transition_disciplinary_recommendation(
        rec["id"], {"to_status": "APPROVED"}, mgr
    ))
    bundle["recommendation"] = rec
    return bundle


def test_finding_challenge_recalibration_cycle_recall_cascade(api):
    """PRD §3.7: "`FINAL` is challengeable — `GeneralCounsel` may move a
    `FINAL` finding to `CHALLENGED`, and doing so recalls every
    `DisciplinaryRecommendation` of the finding currently in `APPROVED` to
    `RECALLED`."

    Design: Difficulty/non_linear_state_machine/finding_challenge_recalibration_cycle
    """
    reset_clock()
    bundle = _setup_final_substantiated_with_approved_rec(api)
    finding, rec = bundle["finding"], bundle["recommendation"]
    resp = api.transition_finding(finding["id"], {"to_status": "CHALLENGED"}, GC)
    finding_after = validate_success(resp, expected_status=200)
    assert finding_after["status"] == "CHALLENGED"
    rec_after = get_success_data(api.get_disciplinary_recommendation(rec["id"], HR))
    assert rec_after["status"] == "RECALLED"


def test_finding_challenge_recalibration_cycle_recalibrate_and_finalize(api):
    """PRD §3.7: "A `CHALLENGED` finding may be recalibrated back to
    `CALIBRATED` by an `HRBusinessPartner` under the same payload requirements
    and the same 0.70 substantiation threshold as the original calibration;
    on recalibration `substantiation_score_final` is recomputed."

    After CHALLENGED -> CALIBRATED (recomputed score 0.70) -> FINAL, the
    cycle FINAL -> CHALLENGED -> CALIBRATED -> FINAL closes.

    Design: Difficulty/non_linear_state_machine/finding_challenge_recalibration_cycle
    """
    reset_clock()
    bundle = _setup_final_substantiated_with_approved_rec(api)
    finding = bundle["finding"]
    get_success_data(api.transition_finding(finding["id"], {"to_status": "CHALLENGED"}, GC))
    hr1 = make_hr_headers(TEST_DEFAULTS["HR_ID"])
    resp = api.transition_finding(
        finding["id"],
        create_calibrate_payload(
            consistency_level="HIGH", subject_admission=False,
            finding_type="SUBSTANTIATED",
        ),
        hr1,
    )
    recal = validate_success(resp, expected_status=200)
    assert recal["status"] == "CALIBRATED"
    assert recal["substantiation_score_final"] == pytest.approx(0.70, abs=0.001)
    fin = make_manager_headers(TEST_DEFAULTS["FINALIZER_ID"])
    resp = api.transition_finding(finding["id"], {"to_status": "FINAL"}, fin)
    fin_after = validate_success(resp, expected_status=200)
    assert fin_after["status"] == "FINAL"


def test_plan_rejection_supersede_loop_prior_superseded(api):
    """PRD §3.2: "Plan creation has two cascades. First, any prior plan of
    the same case that is still in `DRAFT` or `REJECTED` is moved to
    `SUPERSEDED`. Second, if the parent case is `TRIAGED`, the case advances
    to `PLANNING` and its `version` increments by 1."
    PRD §3.2: "The new plan's `plan_version` is one greater than the maximum
    `plan_version` of all plans ever created for the case; the very first
    plan has `plan_version` 1."

    Design: Difficulty/non_linear_state_machine/plan_rejection_supersede_loop
    """
    reset_clock()
    case = create_triaged_case(title="Case NL-3", allegation_category="POLICY_VIOLATION",
                               severity="LOW", department="Ops")
    inv1 = make_investigator_headers("inv-1")
    mgr1 = make_manager_headers("mgr-1")
    p1 = get_success_data(api.create_plan(
        case["id"],
        create_plan_payload(scope_statement="v1 scope",
                            expected_case_version=case["version"]),
        inv1,
    ))
    get_success_data(api.transition_plan(p1["id"], {"to_status": "SUBMITTED"}, inv1))
    get_success_data(api.transition_plan(
        p1["id"],
        {"to_status": "REJECTED", "rejection_reason": "scope too narrow"},
        mgr1,
    ))
    case_v2 = get_success_data(api.get_case(case["id"], INV))["version"]
    p2 = get_success_data(api.create_plan(
        case["id"],
        create_plan_payload(scope_statement="v2 broader scope",
                            planned_start="2026-05-03T00:00:00Z",
                            planned_end="2026-05-22T00:00:00Z",
                            expected_case_version=case_v2),
        inv1,
    ))
    assert p2["plan_version"] == 2
    p1_after = get_success_data(api.get_plan(p1["id"], INV))
    assert p1_after["status"] == "SUPERSEDED"


def test_plan_rejection_supersede_loop_eventual_approval(api):
    """PRD §3.2: "Approval transitions `SUBMITTED` to `APPROVED`, records
    the approver's `X-User-ID` as `approved_by`, advances the parent case
    from `PLANNING` to `FIELDWORK`, and increments the case's `version` by
    1."

    Design: Difficulty/non_linear_state_machine/plan_rejection_supersede_loop
    """
    reset_clock()
    case = create_triaged_case(title="Case NL-3", allegation_category="POLICY_VIOLATION",
                               severity="LOW", department="Ops")
    inv1 = make_investigator_headers("inv-1")
    mgr1 = make_manager_headers("mgr-1")
    p1 = get_success_data(api.create_plan(
        case["id"],
        create_plan_payload(scope_statement="v1 scope",
                            expected_case_version=case["version"]),
        inv1,
    ))
    get_success_data(api.transition_plan(p1["id"], {"to_status": "SUBMITTED"}, inv1))
    get_success_data(api.transition_plan(
        p1["id"],
        {"to_status": "REJECTED", "rejection_reason": "scope too narrow"},
        mgr1,
    ))
    case_v2 = get_success_data(api.get_case(case["id"], INV))["version"]
    p2 = get_success_data(api.create_plan(
        case["id"],
        create_plan_payload(scope_statement="v2 broader scope",
                            planned_start="2026-05-03T00:00:00Z",
                            planned_end="2026-05-22T00:00:00Z",
                            expected_case_version=case_v2),
        inv1,
    ))
    get_success_data(api.transition_plan(p2["id"], {"to_status": "SUBMITTED"}, inv1))
    get_success_data(api.transition_plan(p2["id"], {"to_status": "APPROVED"}, mgr1))
    case_after = get_success_data(api.get_case(case["id"], INV))
    assert case_after["status"] == "FIELDWORK"
