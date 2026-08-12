"""Difficulty queue A — cross_entity_state_dependency instances."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    reset_clock, create_case_in_fieldwork,
    create_collection_scope_payload, create_preservation_notice_payload,
    create_allegation_payload, create_subject_payload,
    create_calibrate_payload, create_report_payload,
    make_investigator_headers, make_manager_headers, make_hr_headers,
    make_gc_headers, TEST_DEFAULTS,
)

IC = TEST_USERS["intake_coordinator_headers"]
INV = TEST_USERS["investigator_headers"]
MGR = TEST_USERS["manager_headers"]
HR = TEST_USERS["hr_headers"]
GC = TEST_USERS["gc_headers"]


def _setup_scope_approve_scene(api):
    """Case FIELDWORK, plan APPROVED, notice N ISSUED (not acknowledged),
    scope S PROPOSED referencing N."""
    bundle = create_case_in_fieldwork(
        title="Case CE-1", allegation_category="DATA_BREACH", severity="HIGH",
        department="IT",
    )
    case = bundle["case"]
    n1 = get_success_data(api.create_preservation_notice(
        case["id"],
        create_preservation_notice_payload(
            custodian_ref="EMP-100", scope="ALL_DATA", is_regulator_ordered=False,
        ),
        GC,
    ))
    s1 = get_success_data(api.create_collection_scope(
        case["id"],
        create_collection_scope_payload(
            custodian_ref="EMP-100", data_source="EMAIL",
            planned_start="2026-05-05T00:00:00Z", planned_end="2026-05-10T00:00:00Z",
            preservation_notice_id=n1["id"],
        ),
        INV,
    ))
    return {"case": case, "n1": n1, "s1": s1}


def test_scope_approve_requires_notice_acknowledged_blocked(api):
    """PRD §3.4: "Scope approval is performed by an `InvestigationsManager`
    and requires the case still be in `FIELDWORK` and the covering
    preservation notice be `ACKNOWLEDGED` (an `ISSUED`-but-unacknowledged
    covering notice is rejected with `ERR_NOTICE_NOT_ACKNOWLEDGED`)."

    Design: Difficulty/cross_entity_state_dependency/scope_approve_requires_notice_acknowledged
    """
    reset_clock()
    bundle = _setup_scope_approve_scene(api)
    mgr = make_manager_headers(TEST_DEFAULTS["APPROVER_ID"])
    resp = api.transition_collection_scope(bundle["s1"]["id"], {"to_status": "APPROVED"}, mgr)
    validate_error(resp, ApiErrorId.ERR_NOTICE_NOT_ACKNOWLEDGED, expected_status=409)


def test_scope_approve_requires_notice_acknowledged_unblocks(api):
    """PRD §3.4: "Scope approval is performed by an `InvestigationsManager`
    and requires the case still be in `FIELDWORK` and the covering
    preservation notice be `ACKNOWLEDGED` (an `ISSUED`-but-unacknowledged
    covering notice is rejected with `ERR_NOTICE_NOT_ACKNOWLEDGED`)."

    After the notice transitions ISSUED -> ACKNOWLEDGED, the same approve
    call succeeds and the scope becomes APPROVED.

    Design: Difficulty/cross_entity_state_dependency/scope_approve_requires_notice_acknowledged
    """
    reset_clock()
    bundle = _setup_scope_approve_scene(api)
    mgr = make_manager_headers(TEST_DEFAULTS["APPROVER_ID"])
    get_success_data(api.transition_preservation_notice(
        bundle["n1"]["id"], {"to_status": "ACKNOWLEDGED"}, GC
    ))
    resp = api.transition_collection_scope(bundle["s1"]["id"], {"to_status": "APPROVED"}, mgr)
    scope_after = validate_success(resp, expected_status=200)
    assert scope_after["status"] == "APPROVED"


def _setup_report_legal_review_scene(api):
    """Case FINDINGS with one CALIBRATED finding; DRAFT report created with
    OCC on the current case version."""
    bundle = create_case_in_fieldwork(
        title="Case CE-2", allegation_category="POLICY_VIOLATION",
        severity="MEDIUM", department="Ops",
    )
    case = bundle["case"]
    alg = get_success_data(api.create_allegation(
        case["id"],
        create_allegation_payload(reporter_channel="EMAIL"),
        IC,
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
        create_calibrate_payload(consistency_level="MEDIUM", finding_type="INCONCLUSIVE"),
        hr1,
    ))
    case_fresh = get_success_data(api.get_case(case["id"], INV))
    report = get_success_data(api.create_report(
        case["id"],
        create_report_payload(
            title="R", distribution_tier="RESTRICTED", distribution_list=["gc-1"],
            report_privilege_type="NONE",
            expected_case_version=case_fresh["version"],
        ),
        inv1,
    ))
    return {"case": case, "finding": finding, "report": report}


def test_report_legal_review_requires_all_findings_final_blocked(api):
    """PRD §3.9: "Legal review moves the report from `DRAFT` to
    `LEGAL_REVIEW` and requires every finding of the parent case to be in
    `FINAL` — a case with any finding in `DRAFT`, `CALIBRATED`, or
    `CHALLENGED` rejects the transition with `ERR_FINDINGS_NOT_FINAL`."

    Design: Difficulty/cross_entity_state_dependency/report_legal_review_requires_all_findings_final
    """
    reset_clock()
    bundle = _setup_report_legal_review_scene(api)
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    resp = api.transition_report(bundle["report"]["id"], {"to_status": "LEGAL_REVIEW"}, inv1)
    validate_error(resp, ApiErrorId.ERR_FINDINGS_NOT_FINAL, expected_status=409)


def test_report_legal_review_requires_all_findings_final_unblocked(api):
    """PRD §3.9: "Legal review moves the report from `DRAFT` to
    `LEGAL_REVIEW` and requires every finding of the parent case to be in
    `FINAL`..."

    After the last CALIBRATED finding moves to FINAL, the same transition
    succeeds and the report enters LEGAL_REVIEW.

    Design: Difficulty/cross_entity_state_dependency/report_legal_review_requires_all_findings_final
    """
    reset_clock()
    bundle = _setup_report_legal_review_scene(api)
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    fin = make_manager_headers(TEST_DEFAULTS["FINALIZER_ID"])
    get_success_data(api.transition_finding(bundle["finding"]["id"], {"to_status": "FINAL"}, fin))
    resp = api.transition_report(bundle["report"]["id"], {"to_status": "LEGAL_REVIEW"}, inv1)
    report_after = validate_success(resp, expected_status=200)
    assert report_after["status"] == "LEGAL_REVIEW"
