"""Difficulty queue A — boundary_precision_check instances."""
import pytest
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    reset_clock, create_case_in_fieldwork,
    create_allegation_payload, create_subject_payload,
    create_collection_scope_payload, create_evidence_item_payload,
    create_interview_payload, create_calibrate_payload,
    create_remediation_payload, add_acknowledged_notice,
    setup_disposition_case,
    make_investigator_headers, make_manager_headers, make_hr_headers,
    TEST_DEFAULTS,
)

IC = TEST_USERS["intake_coordinator_headers"]
INV = TEST_USERS["investigator_headers"]
MGR = TEST_USERS["manager_headers"]
HR = TEST_USERS["hr_headers"]
GC = TEST_USERS["gc_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _setup_bp1_scenario(api):
    """Case FINDINGS with allegation LINKED, subject EMP-100, TWO ADMITTED
    evidence items (e1, e2) on a COLLECTED scope, ONE COMPLETED interview,
    and two DRAFT findings f1 (links [e1]) and f2 (links [e1, e2])."""
    bundle = create_case_in_fieldwork(
        title="Case BP-1", allegation_category="FRAUD", severity="HIGH",
        department="Finance",
    )
    case = bundle["case"]
    alg = get_success_data(api.create_allegation(
        case["id"],
        create_allegation_payload(
            reporter_channel="HOTLINE", is_anonymous=False, reporter_ref="rep-1",
            narrative="n",
        ),
        IC,
    ))
    get_success_data(api.transition_allegation(alg["id"], {"to_status": "TRIAGED"}, IC))
    alg = get_success_data(api.transition_allegation(alg["id"], {"to_status": "LINKED"}, IC))
    subj = get_success_data(api.create_subject(
        case["id"], create_subject_payload(employee_ref="EMP-100"), INV
    ))
    notice = add_acknowledged_notice(case["id"], custodian_ref="EMP-100")
    scope = get_success_data(api.create_collection_scope(
        case["id"],
        create_collection_scope_payload(
            custodian_ref="EMP-100", data_source="EMAIL",
            planned_start="2026-05-05T00:00:00Z", planned_end="2026-05-10T00:00:00Z",
            preservation_notice_id=notice["id"],
        ),
        INV,
    ))
    mgr = make_manager_headers(TEST_DEFAULTS["APPROVER_ID"])
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    get_success_data(api.transition_collection_scope(scope["id"], {"to_status": "APPROVED"}, mgr))
    get_success_data(api.transition_collection_scope(scope["id"], {"to_status": "IN_PROGRESS"}, inv1))
    e1 = get_success_data(api.create_evidence_item(
        scope["id"],
        create_evidence_item_payload(
            custodian_ref="EMP-100", hash_value="h1", size_bytes=1_000_000,
            captured_at="2026-05-06T00:00:00Z",
        ),
        INV,
    ))
    e2 = get_success_data(api.create_evidence_item(
        scope["id"],
        create_evidence_item_payload(
            custodian_ref="EMP-100", hash_value="h2", size_bytes=1_000_000,
            captured_at="2026-05-06T01:00:00Z",
        ),
        INV,
    ))
    for e in (e1, e2):
        get_success_data(api.transition_evidence_item(e["id"], {"to_status": "UNDER_REVIEW"}, inv1))
        get_success_data(api.transition_evidence_item(e["id"], {"to_status": "ADMITTED"}, inv1))
    get_success_data(api.transition_collection_scope(scope["id"], {"to_status": "COLLECTED"}, inv1))
    interview = get_success_data(api.create_interview(
        case["id"],
        create_interview_payload(
            witness_ref="W-1", interviewer_id="inv-9",
            scheduled_start="2026-05-08T14:00:00Z",
            scheduled_end="2026-05-08T15:00:00Z",
        ),
        INV,
    ))
    get_success_data(api.transition_interview(interview["id"], {"to_status": "UPJOHN_DELIVERED"}, inv1))
    get_success_data(api.transition_interview(
        interview["id"],
        {"to_status": "COMPLETED", "completion_note": "memo"},
        inv1,
    ))
    get_success_data(api.transition_case(case["id"], {"to_status": "FINDINGS"}, inv1))
    f1 = get_success_data(api.create_finding(
        case["id"],
        {"allegation_id": alg["id"], "subject_id": subj["id"],
         "evidence_item_ids": [e1["id"]]},
        inv1,
    ))
    f2 = get_success_data(api.create_finding(
        case["id"],
        {"allegation_id": alg["id"], "subject_id": subj["id"],
         "evidence_item_ids": [e1["id"], e2["id"]]},
        inv1,
    ))
    return {"case": case, "f1": f1, "f2": f2}


def test_substantiation_threshold_exactly_070_passes(api):
    """PRD §3.7: "A `SUBSTANTIATED` finding requires
    `substantiation_score_final` to be at least 0.70; below the threshold
    the calibration is rejected with `ERR_THRESHOLD_NOT_MET`."

    Final score exactly 0.70 (1 ADMITTED evidence 0.25 + 1 COMPLETED
    interview 0.15 + HIGH consistency 0.30) SATISFIES the >= 0.70 gate.

    Design: Difficulty/boundary_precision_check/substantiation_threshold_exactly_070
    """
    reset_clock()
    bundle = _setup_bp1_scenario(api)
    hr1 = make_hr_headers(TEST_DEFAULTS["HR_ID"])
    resp = api.transition_finding(
        bundle["f1"]["id"],
        create_calibrate_payload(
            consistency_level="HIGH", subject_admission=False,
            finding_type="SUBSTANTIATED",
        ),
        hr1,
    )
    after = validate_success(resp, expected_status=200)
    assert after["substantiation_score_final"] == pytest.approx(0.70, abs=0.001)
    assert after["status"] == "CALIBRATED"


def test_substantiation_threshold_below_070_rejected(api):
    """PRD §3.7: "A `SUBSTANTIATED` finding requires
    `substantiation_score_final` to be at least 0.70; below the threshold
    the calibration is rejected with `ERR_THRESHOLD_NOT_MET`."

    2 ADMITTED evidence (0.50) + 1 COMPLETED interview (0.15) + LOW
    consistency (0.00) = 0.65, below 0.70 — rejected.

    Design: Difficulty/boundary_precision_check/substantiation_threshold_exactly_070
    """
    reset_clock()
    bundle = _setup_bp1_scenario(api)
    hr1 = make_hr_headers(TEST_DEFAULTS["HR_ID"])
    resp = api.transition_finding(
        bundle["f2"]["id"],
        create_calibrate_payload(
            consistency_level="LOW", subject_admission=False,
            finding_type="SUBSTANTIATED",
        ),
        hr1,
    )
    validate_error(resp, ApiErrorId.ERR_THRESHOLD_NOT_MET, expected_status=409)
    after = get_success_data(api.get_finding(bundle["f2"]["id"], HR))
    assert after["status"] == "DRAFT"


def test_remediation_overdue_strict_greater_than_at_due_date(api):
    """PRD §3.13: "The action's `is_overdue` flag is recomputed on every
    read and on every transition: it is true when the current logical clock
    is strictly later than `due_date` and the action's status is one of
    `OPEN`, `IN_PROGRESS`, or `AWAITING_VERIFICATION`. The boundary is
    strict — when the clock equals `due_date` exactly, `is_overdue` is
    false."

    Design: Difficulty/boundary_precision_check/remediation_overdue_strict_greater_than
    """
    reset_clock()
    bundle = setup_disposition_case(severity="MEDIUM", finding_type="INCONCLUSIVE")
    case = bundle["case"]
    hr1 = make_hr_headers(TEST_DEFAULTS["HR_ID"])
    rem = get_success_data(api.create_remediation_action(
        case["id"],
        create_remediation_payload(
            action_type="TRAINING", owner_ref="own-1",
            due_date="2026-06-01T00:00:00Z", description="policy retraining",
        ),
        hr1,
    ))
    # At the exact due_date
    reset_clock("2026-06-01T00:00:00Z")
    rem_eq = get_success_data(api.get_remediation_action(rem["id"], HR))
    assert rem_eq["is_overdue"] is False


def test_remediation_overdue_strict_greater_than_one_second_past(api):
    """PRD §3.13: "The boundary is strict — when the clock equals `due_date`
    exactly, `is_overdue` is false." One second past the boundary the flag
    must be true.

    Design: Difficulty/boundary_precision_check/remediation_overdue_strict_greater_than
    """
    reset_clock()
    bundle = setup_disposition_case(severity="MEDIUM", finding_type="INCONCLUSIVE")
    case = bundle["case"]
    hr1 = make_hr_headers(TEST_DEFAULTS["HR_ID"])
    rem = get_success_data(api.create_remediation_action(
        case["id"],
        create_remediation_payload(
            action_type="TRAINING", owner_ref="own-1",
            due_date="2026-06-01T00:00:00Z", description="policy retraining",
        ),
        hr1,
    ))
    reset_clock("2026-06-01T00:00:01Z")
    rem_gt = get_success_data(api.get_remediation_action(rem["id"], HR))
    assert rem_gt["is_overdue"] is True
