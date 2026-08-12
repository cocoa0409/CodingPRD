"""Corner tests for prior_history cross-case counting, vacuous preservation
ratio, and the derived open_remediation_count reconciliation."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    reset_clock, create_case_in_fieldwork, create_allegation_payload,
    create_subject_payload, create_calibrate_payload, create_recommendation_payload,
    create_remediation_payload, create_plan_payload,
    setup_final_substantiated_finding, setup_disposition_case,
    make_investigator_headers, make_manager_headers, make_hr_headers,
    make_gc_headers, make_auditor_headers, TEST_DEFAULTS,
)

IC = TEST_USERS["intake_coordinator_headers"]
INV = TEST_USERS["investigator_headers"]
MGR = TEST_USERS["manager_headers"]
HR = TEST_USERS["hr_headers"]
GC = TEST_USERS["gc_headers"]
AUD = TEST_USERS["auditor_headers"]


def test_discipline_prior_history_counts_other_cases(api):
    """PRD §3.8: "`prior_history_count` is the number of `Finding` rows in
    `FINAL` status with `finding_type` of `SUBSTANTIATED` on cases other than
    this case, whose subject's `employee_ref` equals this finding's subject's
    `employee_ref`, and whose `created_at` is strictly earlier than this
    finding's `created_at`."
    PRD §3.8: "The base is 10 times the severity weight... The prior-history
    multiplier is 1 plus 0.25 times the smaller of `prior_history_count` and
    3. The `index_policy_matrix` is the product of the base and the
    multiplier, rounded half-up to an integer..."

    Design: Corner/calculations/discipline_prior_history_counts_other_cases
    """
    reset_clock()
    # Case A — build a FINAL SUBSTANTIATED finding for EMP-100
    bundle_a = setup_final_substantiated_finding(severity="HIGH", subject_emp="EMP-100")
    finding_a = bundle_a["finding"]
    assert finding_a["status"] == "FINAL"
    assert finding_a["finding_type"] == "SUBSTANTIATED"
    # Case B — same employee_ref, second case
    bundle_b = setup_final_substantiated_finding(severity="HIGH", subject_emp="EMP-100")
    finding_b = bundle_b["finding"]
    hr1 = make_hr_headers(TEST_DEFAULTS["HR_ID"])
    rec = get_success_data(api.create_disciplinary_recommendation(
        finding_b["id"], create_recommendation_payload(), hr1
    ))
    assert rec["prior_history_count"] == 1
    # HIGH severity base = 30; multiplier 1 + 0.25*1 = 1.25; round_half_up(37.5) = 38
    assert rec["index_policy_matrix"] == 38
    assert rec["index_calibrated"] == 38
    assert rec["suggested_action"] == "WARNING"


def test_preservation_ratio_vacuous_empty_set(api):
    """PRD §3.3: "When the case has no notices in `ISSUED` or `ACKNOWLEDGED`,
    the ratio is defined to be 1.00."
    PRD §3.12 gates FIELDWORK->FINDINGS on ratio == 1.00; with vacuous 1.00
    the preservation gate does not block.

    Design: Corner/calculations/preservation_ratio_vacuous_empty_set
    """
    reset_clock()
    bundle = create_case_in_fieldwork(
        title="Vacuous", allegation_category="POLICY_VIOLATION",
        severity="LOW", department="Ops",
    )
    case = bundle["case"]
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    # No notices, no scopes — the gate must pass
    resp = api.transition_case(case["id"], {"to_status": "FINDINGS"}, inv1)
    case_after = validate_success(resp, expected_status=200)
    assert case_after["status"] == "FINDINGS"
    assert case_after["preservation_completeness_ratio"] == 1.00


def test_derived_field_reconciliation_open_remediation_count(api):
    """PRD §3.13: "The count of a case's open remediations equals the number
    of `RemediationAction` rows for the case in `OPEN`, `IN_PROGRESS`, or
    `AWAITING_VERIFICATION`."
    PRD §3.13: "A new action enters `OPEN`, and the parent case's
    `open_remediation_count` is incremented by 1."
    PRD §3.13: "...waiver also requires a `rationale` and decrements the
    case's `open_remediation_count` by 1."

    Design: Corner/cross_cutting_layers/derived_field_reconciliation_open_remediation_count
    """
    reset_clock()
    bundle = setup_disposition_case(severity="MEDIUM", finding_type="INCONCLUSIVE")
    case = bundle["case"]
    mgr = make_manager_headers(TEST_DEFAULTS["APPROVER_ID"])
    case = get_success_data(api.transition_case(case["id"], {"to_status": "REMEDIATION"}, mgr))
    hr1 = make_hr_headers(TEST_DEFAULTS["HR_ID"])
    rem = get_success_data(api.create_remediation_action(
        case["id"],
        create_remediation_payload(action_type="PROCESS_CHANGE", owner_ref="own-1",
                                   description="fix process"),
        hr1,
    ))
    case_v = get_success_data(api.get_case(case["id"], HR))
    assert case_v["open_remediation_count"] == 1
    # OPEN -> IN_PROGRESS -> AWAITING_VERIFICATION -> IN_PROGRESS (reject)
    get_success_data(api.transition_remediation_action(rem["id"], {"to_status": "IN_PROGRESS"}, hr1))
    get_success_data(api.transition_remediation_action(rem["id"], {"to_status": "AWAITING_VERIFICATION"}, hr1))
    aud = make_auditor_headers(TEST_DEFAULTS["AUDITOR_ID"])
    get_success_data(api.transition_remediation_action(
        rem["id"], {"to_status": "IN_PROGRESS", "rationale": "insufficient evidence"}, aud
    ))
    case_v = get_success_data(api.get_case(case["id"], HR))
    assert case_v["open_remediation_count"] == 1
    # WAIVED
    get_success_data(api.transition_remediation_action(
        rem["id"], {"to_status": "WAIVED", "rationale": "superseded"}, GC
    ))
    case_v = get_success_data(api.get_case(case["id"], HR))
    assert case_v["open_remediation_count"] == 0


def test_immediate_consistency_after_plan_approval(api):
    """PRD §1: "All state changes, derived counters, and cross-entity
    cascades are immediately and atomically visible in the response that
    produces them."
    PRD §3.2: "Approval transitions `SUBMITTED` to `APPROVED`, records the
    approver's `X-User-ID` as `approved_by`, advances the parent case from
    `PLANNING` to `FIELDWORK`, and increments the case's `version` by 1."

    Design: Corner/consistency_model/immediate_consistency_after_plan_approval
    """
    reset_clock()
    case = get_success_data(api.create_case(
        {"title": "Immed", "allegation_category": "FRAUD", "severity": "HIGH",
         "department": "Finance", "lead_investigator_id": "inv-lead-1"},
        IC,
    ))
    case = get_success_data(api.transition_case(
        case["id"],
        {"to_status": "TRIAGED", "severity": "HIGH", "department": "Finance"},
        IC,
    ))
    plan = get_success_data(api.create_plan(
        case["id"], create_plan_payload(expected_case_version=case["version"]), INV
    ))
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    mgr = make_manager_headers(TEST_DEFAULTS["APPROVER_ID"])
    get_success_data(api.transition_plan(plan["id"], {"to_status": "SUBMITTED"}, inv1))
    resp = api.transition_plan(plan["id"], {"to_status": "APPROVED"}, mgr)
    plan_after = validate_success(resp, expected_status=200)
    assert plan_after["status"] == "APPROVED"
    assert plan_after["approved_by"] == TEST_DEFAULTS["APPROVER_ID"]
    case_after = get_success_data(api.get_case(case["id"], INV))
    assert case_after["status"] == "FIELDWORK"
