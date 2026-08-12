"""Corner tests for segregation-of-duties rejections across all five SOD gates."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    reset_clock, create_case, create_case_in_fieldwork, create_triaged_case,
    create_plan_payload, create_allegation_payload, create_subject_payload,
    create_interview_payload, create_collection_scope_payload,
    create_evidence_item_payload, create_calibrate_payload,
    create_recommendation_payload, create_disclosure_payload,
    create_remediation_payload, add_acknowledged_notice,
    setup_final_substantiated_finding, setup_disposition_case,
    make_investigator_headers, make_manager_headers, make_hr_headers,
    make_gc_headers, make_clo_headers, make_auditor_headers,
    TEST_DEFAULTS,
)

IC = TEST_USERS["intake_coordinator_headers"]
INV = TEST_USERS["investigator_headers"]
MGR = TEST_USERS["manager_headers"]
HR = TEST_USERS["hr_headers"]
GC = TEST_USERS["gc_headers"]
CLO = TEST_USERS["clo_headers"]
AUD = TEST_USERS["auditor_headers"]


def test_plan_approve_by_drafter_sod_rejected(api):
    """PRD §3.2: "Both approval and rejection are subject to segregation of
    duties: the acting manager's `X-User-ID` must differ from the plan's
    `drafter_id`, or the call is rejected with `ERR_SOD_PLAN_APPROVAL`."

    Design: Corner/state_machines/plan_approve_by_drafter_sod_rejected
    """
    reset_clock()
    case = create_triaged_case(title="SOD Plan", allegation_category="FRAUD",
                               severity="HIGH", department="Finance")
    drafter_headers = make_investigator_headers("inv-1")
    plan = get_success_data(api.create_plan(
        case["id"],
        create_plan_payload(expected_case_version=case["version"]),
        drafter_headers,
    ))
    get_success_data(api.transition_plan(plan["id"], {"to_status": "SUBMITTED"}, drafter_headers))
    # Manager with same user_id as drafter
    same_id_mgr = make_manager_headers("inv-1")
    resp = api.transition_plan(plan["id"], {"to_status": "APPROVED"}, same_id_mgr)
    validate_error(resp, ApiErrorId.ERR_SOD_PLAN_APPROVAL, expected_status=403)
    after = get_success_data(api.get_plan(plan["id"], INV))
    assert after["status"] == "SUBMITTED"


def test_finding_finalize_by_lead_investigator_sod_rejected(api):
    """PRD §3.7: "Finalization is performed by an `InvestigationsManager` and
    moves the finding from `CALIBRATED` to `FINAL`. Segregation of duties
    applies: the approver's `X-User-ID` must differ from the parent case's
    `lead_investigator_id`, otherwise `ERR_SOD_FINDING_FINALIZATION`."

    Design: Corner/state_machines/finding_finalize_by_lead_investigator_sod_rejected
    """
    reset_clock()
    bundle = create_case_in_fieldwork(
        title="SOD Find", allegation_category="POLICY_VIOLATION",
        severity="MEDIUM", department="Ops",
    )
    case = bundle["case"]
    alg = get_success_data(api.create_allegation(
        case["id"], create_allegation_payload(reporter_channel="EMAIL"), IC
    ))
    get_success_data(api.transition_allegation(alg["id"], {"to_status": "TRIAGED"}, IC))
    alg = get_success_data(api.transition_allegation(alg["id"], {"to_status": "LINKED"}, IC))
    subj = get_success_data(api.create_subject(
        case["id"], create_subject_payload(employee_ref="EMP-100"), INV
    ))
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    get_success_data(api.transition_case(case["id"], {"to_status": "FINDINGS"}, inv1))
    finding = get_success_data(api.create_finding(
        case["id"],
        {"allegation_id": alg["id"], "subject_id": subj["id"]},
        inv1,
    ))
    hr1 = make_hr_headers(TEST_DEFAULTS["HR_ID"])
    finding = get_success_data(api.transition_finding(
        finding["id"],
        create_calibrate_payload(
            consistency_level="MEDIUM", subject_admission=False,
            finding_type="INCONCLUSIVE",
        ),
        hr1,
    ))
    # Manager with user_id matching the case's lead_investigator_id
    lead_mgr = make_manager_headers(TEST_DEFAULTS["LEAD_INVESTIGATOR_ID"])
    resp = api.transition_finding(finding["id"], {"to_status": "FINAL"}, lead_mgr)
    validate_error(resp, ApiErrorId.ERR_SOD_FINDING_FINALIZATION, expected_status=403)
    after = get_success_data(api.get_finding(finding["id"], HR))
    assert after["status"] == "CALIBRATED"


def test_discipline_approve_by_proposer_sod_rejected(api):
    """PRD §3.8: "Approval is subject to segregation of duties: the
    approver's `X-User-ID` must differ from `proposed_by`, otherwise
    `ERR_SOD_DISCIPLINE_APPROVAL`."

    Design: Corner/state_machines/discipline_approve_by_proposer_sod_rejected
    """
    reset_clock()
    bundle = setup_final_substantiated_finding(severity="HIGH")
    finding = bundle["finding"]
    hr1 = make_hr_headers(TEST_DEFAULTS["HR_ID"])
    rec = get_success_data(api.create_disciplinary_recommendation(
        finding["id"], create_recommendation_payload(), hr1
    ))
    # Manager with same user_id as the proposer
    same_id_mgr = make_manager_headers(TEST_DEFAULTS["HR_ID"])
    resp = api.transition_disciplinary_recommendation(
        rec["id"], {"to_status": "APPROVED"}, same_id_mgr
    )
    validate_error(resp, ApiErrorId.ERR_SOD_DISCIPLINE_APPROVAL, expected_status=403)
    after = get_success_data(api.get_disciplinary_recommendation(rec["id"], HR))
    assert after["status"] == "PROPOSED"


def test_remediation_verify_by_owner_sod_rejected(api):
    """PRD §3.13: "Verification is performed by a `ComplianceAuditor` and
    moves `AWAITING_VERIFICATION` to `VERIFIED`; segregation of duties
    requires the verifier's `X-User-ID` to differ from `owner_ref`
    (`ERR_SOD_REMEDIATION_VERIFICATION`). On verification `verified_by` is
    set to the caller's `X-User-ID` and the case's `open_remediation_count`
    is decremented by 1."

    Design: Corner/state_machines/remediation_verify_by_owner_sod_rejected
    """
    reset_clock()
    bundle = setup_disposition_case(severity="MEDIUM", finding_type="INCONCLUSIVE")
    case = bundle["case"]
    hr1 = make_hr_headers(TEST_DEFAULTS["HR_ID"])
    rem = get_success_data(api.create_remediation_action(
        case["id"], create_remediation_payload(owner_ref="own-1"), hr1
    ))
    get_success_data(api.transition_remediation_action(
        rem["id"], {"to_status": "IN_PROGRESS"}, hr1
    ))
    get_success_data(api.transition_remediation_action(
        rem["id"], {"to_status": "AWAITING_VERIFICATION"}, hr1
    ))
    # Auditor matching owner_ref
    same_id_aud = make_auditor_headers("own-1")
    resp = api.transition_remediation_action(
        rem["id"], {"to_status": "VERIFIED"}, same_id_aud
    )
    validate_error(resp, ApiErrorId.ERR_SOD_REMEDIATION_VERIFICATION, expected_status=403)
    # Different auditor succeeds
    aud = make_auditor_headers("aud-1")
    ok = api.transition_remediation_action(rem["id"], {"to_status": "VERIFIED"}, aud)
    final = validate_success(ok, expected_status=200)
    assert final["status"] == "VERIFIED"
    assert final["verified_by"] == "aud-1"
    case_after = get_success_data(api.get_case(case["id"], HR))
    assert case_after["open_remediation_count"] == 0


def test_disclosure_lifecycle_cooling_off_and_override_sod(api):
    """PRD §3.11: "Filing is performed by `GeneralCounsel` and moves `DECIDED`
    to `FILED`. Two preconditions apply: the recorded `decision` must be
    `DISCLOSE` (otherwise `ERR_DECISION_NOT_DISCLOSE`), and the current
    logical clock must be at least `decided_at` plus 72 hours — a mandatory
    cooling-off period (otherwise `ERR_COOLING_OFF`)."
    PRD §3.11: "A decided decision may be overridden by the
    `ChiefLegalOfficer` to `OVERRIDDEN`. The override is subject to
    segregation of duties: the overrider's `X-User-ID` must differ from
    `decided_by` (`ERR_SOD_DISCLOSURE_OVERRIDE`), and the payload must carry
    a `rationale` (`ERR_MISSING_REQUIRED_FIELD` when absent)."

    Design: Corner/state_machines/disclosure_lifecycle_cooling_off_and_override_sod
    """
    reset_clock()
    bundle = create_case_in_fieldwork(
        title="Disc", allegation_category="BRIBERY", severity="CRITICAL",
        department="Sales",
    )
    case = bundle["case"]
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    get_success_data(api.transition_case(case["id"], {"to_status": "FINDINGS"}, inv1))
    case = get_success_data(api.get_case(case["id"], GC))
    d1 = get_success_data(api.create_self_disclosure_decision(
        case["id"],
        create_disclosure_payload(
            regulator="SEC", decision_deadline="2026-05-15T00:00:00Z",
            expected_case_version=case["version"],
        ),
        GC,
    ))
    case = get_success_data(api.get_case(case["id"], GC))
    d2 = get_success_data(api.create_self_disclosure_decision(
        case["id"],
        create_disclosure_payload(
            regulator="DOJ", decision_deadline="2026-05-15T00:00:00Z",
            expected_case_version=case["version"],
        ),
        GC,
    ))
    clo1 = make_clo_headers("clo-1")
    d1 = get_success_data(api.transition_self_disclosure_decision(
        d1["id"],
        {"to_status": "DECIDED", "decision": "DISCLOSE", "rationale": "material"},
        clo1,
    ))
    d2 = get_success_data(api.transition_self_disclosure_decision(
        d2["id"],
        {"to_status": "DECIDED", "decision": "NO_DISCLOSE", "rationale": "immaterial"},
        clo1,
    ))
    # 24h later — still inside cooling-off
    reset_clock("2026-05-02T00:00:00Z")
    resp = api.transition_self_disclosure_decision(d1["id"], {"to_status": "FILED"}, GC)
    validate_error(resp, ApiErrorId.ERR_COOLING_OFF, expected_status=409)
    # Past 72h
    reset_clock("2026-05-04T00:00:01Z")
    ok = api.transition_self_disclosure_decision(d1["id"], {"to_status": "FILED"}, GC)
    d1_after = validate_success(ok, expected_status=200)
    assert d1_after["status"] == "FILED"
    assert d1_after["filed_at"] == "2026-05-04T00:00:01Z"
    # NO_DISCLOSE cannot be FILED
    resp = api.transition_self_disclosure_decision(d2["id"], {"to_status": "FILED"}, GC)
    validate_error(resp, ApiErrorId.ERR_DECISION_NOT_DISCLOSE, expected_status=409)
    # Same CLO cannot override own decision
    resp = api.transition_self_disclosure_decision(
        d2["id"],
        {"to_status": "OVERRIDDEN", "rationale": "second look"},
        clo1,
    )
    validate_error(resp, ApiErrorId.ERR_SOD_DISCLOSURE_OVERRIDE, expected_status=403)
    # Different CLO succeeds
    clo2 = make_clo_headers("clo-2")
    ok = api.transition_self_disclosure_decision(
        d2["id"],
        {"to_status": "OVERRIDDEN", "rationale": "second look"},
        clo2,
    )
    d2_after = validate_success(ok, expected_status=200)
    assert d2_after["status"] == "OVERRIDDEN"
