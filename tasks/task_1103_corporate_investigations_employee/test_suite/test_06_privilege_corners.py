"""Corner tests for privilege designation, evidence admission, and BOARD distribution."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    reset_clock, create_case, create_case_in_fieldwork,
    create_interview_payload, create_collection_scope_payload,
    create_evidence_item_payload, create_preservation_notice_payload,
    create_allegation_payload, create_subject_payload,
    create_calibrate_payload, create_report_payload,
    add_acknowledged_notice, setup_final_substantiated_finding,
    make_investigator_headers, make_manager_headers, make_hr_headers,
    make_gc_headers, make_clo_headers, TEST_DEFAULTS,
)

IC = TEST_USERS["intake_coordinator_headers"]
INV = TEST_USERS["investigator_headers"]
MGR = TEST_USERS["manager_headers"]
HR = TEST_USERS["hr_headers"]
GC = TEST_USERS["gc_headers"]
CLO = TEST_USERS["clo_headers"]


def _fieldwork_with_scope_in_progress(api, case_overrides):
    bundle = create_case_in_fieldwork(**case_overrides)
    case = bundle["case"]
    notice = add_acknowledged_notice(case["id"], custodian_ref="EMP-100")
    scope = get_success_data(api.create_collection_scope(
        case["id"],
        create_collection_scope_payload(
            custodian_ref="EMP-100", data_source="EMAIL",
            preservation_notice_id=notice["id"],
        ),
        INV,
    ))
    mgr = make_manager_headers(TEST_DEFAULTS["APPROVER_ID"])
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    get_success_data(api.transition_collection_scope(scope["id"], {"to_status": "APPROVED"}, mgr))
    get_success_data(api.transition_collection_scope(scope["id"], {"to_status": "IN_PROGRESS"}, inv1))
    return {"case": case, "notice": notice, "scope": scope, "plan": bundle["plan"]}


def test_evidence_admit_blocked_by_pending_designation_rejected(api):
    """PRD §3.4: "Both the admit and the restore are blocked while any
    `PrivilegeDesignation` exists with `target_type` of `EVIDENCE_ITEM`,
    `target_id` equal to the item, and `status` of `DESIGNATED` (pending
    confirmation); the rejection is `ERR_PRIVILEGE_PENDING`."

    Design: Corner/state_machines/evidence_admit_blocked_by_pending_designation_rejected
    """
    reset_clock()
    bundle = _fieldwork_with_scope_in_progress(
        api,
        {"title": "PrivPending", "allegation_category": "FRAUD", "severity": "HIGH",
         "department": "Finance"},
    )
    case, scope = bundle["case"], bundle["scope"]
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    ev = get_success_data(api.create_evidence_item(
        scope["id"], create_evidence_item_payload(), INV
    ))
    get_success_data(api.transition_evidence_item(ev["id"], {"to_status": "UNDER_REVIEW"}, inv1))
    pd = get_success_data(api.create_privilege_designation(
        case["id"],
        {"target_type": "EVIDENCE_ITEM", "target_id": ev["id"],
         "privilege_type": "ACP", "rationale": "counsel review"},
        GC,
    ))
    resp = api.transition_evidence_item(ev["id"], {"to_status": "ADMITTED"}, inv1)
    validate_error(resp, ApiErrorId.ERR_PRIVILEGE_PENDING, expected_status=409)
    get_success_data(api.transition_privilege_designation(pd["id"], {"to_status": "CONFIRMED"}, GC))
    ok = api.transition_evidence_item(ev["id"], {"to_status": "ADMITTED"}, inv1)
    ev_after = validate_success(ok, expected_status=200)
    assert ev_after["status"] == "ADMITTED"


def test_duplicate_active_designation_rejected(api):
    """PRD §3.6: "At most one active designation — `DESIGNATED`, `CONFIRMED`,
    or `CHALLENGED` — may exist per (`target_type`, `target_id`) pair; a
    second active designation is rejected with `ERR_DUPLICATE_DESIGNATION`."

    Design: Corner/state_machines/duplicate_active_designation_rejected
    """
    reset_clock()
    bundle = create_case_in_fieldwork(
        title="DupDes", allegation_category="HARASSMENT", severity="MEDIUM",
        department="Ops",
    )
    case = bundle["case"]
    interview = get_success_data(api.create_interview(
        case["id"],
        create_interview_payload(
            witness_ref="W-1", interviewer_id="inv-9",
            scheduled_start="2026-05-10T14:00:00Z",
            scheduled_end="2026-05-10T15:00:00Z",
        ),
        INV,
    ))
    pd1 = get_success_data(api.create_privilege_designation(
        case["id"],
        {"target_type": "INTERVIEW", "target_id": interview["id"], "privilege_type": "ACP"},
        GC,
    ))
    resp = api.create_privilege_designation(
        case["id"],
        {"target_type": "INTERVIEW", "target_id": interview["id"],
         "privilege_type": "WORK_PRODUCT"},
        GC,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_DESIGNATION, expected_status=409)
    case_after = get_success_data(api.get_case(case["id"], GC))
    assert case_after["active_privileged_artifact_count"] == 1


def _board_report_ready(api, with_acp_evidence: bool):
    """Build a case to FINDINGS with one FINAL finding, then create a
    BOARD-tier report and advance it to DISTRIBUTION_APPROVED. If
    `with_acp_evidence`, also attach an ADMITTED evidence item carrying a
    CONFIRMED ACP designation to the finding."""
    bundle = create_case_in_fieldwork(
        title="BoardRep", allegation_category="POLICY_VIOLATION",
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
    pd = None
    ev = None
    if with_acp_evidence:
        # Need evidence: build through notice+scope+admit, then walk case to FINDINGS again
        # Rebuild from scratch: this helper only supports the simpler path;
        # use a separate builder below.
        raise NotImplementedError
    finding = get_success_data(api.create_finding(
        case["id"],
        {"allegation_id": alg["id"], "subject_id": subj["id"]},
        inv1,
    ))
    hr1 = make_hr_headers(TEST_DEFAULTS["HR_ID"])
    finding = get_success_data(api.transition_finding(
        finding["id"],
        create_calibrate_payload(consistency_level="MEDIUM", finding_type="INCONCLUSIVE"),
        hr1,
    ))
    fin = make_manager_headers(TEST_DEFAULTS["FINALIZER_ID"])
    finding = get_success_data(api.transition_finding(finding["id"], {"to_status": "FINAL"}, fin))
    case_fresh = get_success_data(api.get_case(case["id"], INV))
    report = get_success_data(api.create_report(
        case["id"],
        create_report_payload(
            title="Board Report", distribution_tier="BOARD",
            distribution_list=["board-1"], report_privilege_type="WORK_PRODUCT",
            expected_case_version=case_fresh["version"],
        ),
        inv1,
    ))
    get_success_data(api.transition_report(report["id"], {"to_status": "LEGAL_REVIEW"}, inv1))
    get_success_data(api.transition_report(report["id"], {"to_status": "DISTRIBUTION_APPROVED"}, GC))
    return {"case": case, "finding": finding, "report": report, "allegation": alg,
            "subject": subj}


def test_report_board_distribution_by_non_clo_rejected(api):
    """PRD §3.9: "When the report's `distribution_tier` is `BOARD`, two
    additional gates apply: the acting caller must be a `ChiefLegalOfficer`
    (otherwise `ERR_UNAUTHORIZED_ROLE`)..."
    PRD §3.9: "On successful distribution `distributed_at` is set to the
    current logical clock."

    Design: Corner/state_machines/report_board_distribution_by_non_clo_rejected
    """
    reset_clock()
    bundle = _board_report_ready(api, with_acp_evidence=False)
    report = bundle["report"]
    resp = api.transition_report(report["id"], {"to_status": "DISTRIBUTED"}, GC)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
    clo1 = make_clo_headers("clo-1")
    ok = api.transition_report(report["id"], {"to_status": "DISTRIBUTED"}, clo1)
    report_after = validate_success(ok, expected_status=200)
    assert report_after["status"] == "DISTRIBUTED"
    assert report_after["distributed_at"] is not None


def test_report_board_distribution_with_active_acp_rejected(api):
    """PRD §3.9: "When the report's `distribution_tier` is `BOARD`, two
    additional gates apply: the acting caller must be a `ChiefLegalOfficer`
    (otherwise `ERR_UNAUTHORIZED_ROLE`), and no evidence item linked to any
    finding of the case may carry a `PrivilegeDesignation` of type `ACP` in
    `DESIGNATED` or `CONFIRMED` (otherwise `ERR_PRIVILEGED_DISTRIBUTION`)."

    Design: Corner/state_machines/report_board_distribution_with_active_acp_rejected
    """
    reset_clock()
    # Build case with ADMITTED evidence linked to a FINAL SUBSTANTIATED finding,
    # then designate ACP on the evidence and CONFIRM it, then advance a BOARD
    # report to DISTRIBUTION_APPROVED.
    bundle = setup_final_substantiated_finding(severity="HIGH")
    case = bundle["case"]
    finding = bundle["finding"]
    ev = bundle["evidence"]
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    # Case is in FINDINGS now (set by setup_final_substantiated_finding).
    # Designate ACP on the evidence and confirm it.
    pd = get_success_data(api.create_privilege_designation(
        case["id"],
        {"target_type": "EVIDENCE_ITEM", "target_id": ev["id"],
         "privilege_type": "ACP", "rationale": "legal advice embedded"},
        GC,
    ))
    pd = get_success_data(api.transition_privilege_designation(
        pd["id"], {"to_status": "CONFIRMED"}, GC
    ))
    case_fresh = get_success_data(api.get_case(case["id"], INV))
    report = get_success_data(api.create_report(
        case["id"],
        create_report_payload(
            title="Board ACP Report", distribution_tier="BOARD",
            distribution_list=["board-1"], report_privilege_type="WORK_PRODUCT",
            expected_case_version=case_fresh["version"],
        ),
        inv1,
    ))
    get_success_data(api.transition_report(report["id"], {"to_status": "LEGAL_REVIEW"}, inv1))
    # DISTRIBUTION_APPROVED: requires all designations CONFIRMED or WAIVED — ours is
    # CONFIRMED, so this passes.
    get_success_data(api.transition_report(report["id"], {"to_status": "DISTRIBUTION_APPROVED"}, GC))
    clo1 = make_clo_headers("clo-1")
    resp = api.transition_report(report["id"], {"to_status": "DISTRIBUTED"}, clo1)
    validate_error(resp, ApiErrorId.ERR_PRIVILEGED_DISTRIBUTION, expected_status=403)
    # Waive the ACP and retry
    get_success_data(api.transition_privilege_designation(pd["id"], {"to_status": "WAIVED"}, GC))
    ok = api.transition_report(report["id"], {"to_status": "DISTRIBUTED"}, clo1)
    report_after = validate_success(ok, expected_status=200)
    assert report_after["status"] == "DISTRIBUTED"
