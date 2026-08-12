"""Corner tests for cross-entity referential rejections on Finding and PrivilegeDesignation."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    reset_clock, create_case, create_case_in_fieldwork,
    create_plan_payload, create_allegation_payload, create_subject_payload,
    create_collection_scope_payload, create_evidence_item_payload,
    create_calibrate_payload, create_interview_payload,
    add_acknowledged_notice, setup_final_substantiated_finding,
    make_investigator_headers, make_manager_headers, make_hr_headers,
    make_gc_headers, TEST_DEFAULTS,
)

IC = TEST_USERS["intake_coordinator_headers"]
INV = TEST_USERS["investigator_headers"]
MGR = TEST_USERS["manager_headers"]
HR = TEST_USERS["hr_headers"]
GC = TEST_USERS["gc_headers"]


def test_finding_with_unlinked_allegation_rejected(api):
    """PRD §3.7: "The referenced allegation must be in `LINKED` status and
    belong to the case, otherwise `ERR_ALLEGATION_NOT_LINKED`."

    Design: Corner/state_machines/finding_with_unlinked_allegation_rejected
    """
    reset_clock()
    bundle = create_case_in_fieldwork(
        title="Unlinked", allegation_category="POLICY_VIOLATION",
        severity="MEDIUM", department="Ops",
    )
    case = bundle["case"]
    # File allegation after triage cascade so it remains SUBMITTED, then TRIAGED (not LINKED)
    alg = get_success_data(api.create_allegation(
        case["id"],
        create_allegation_payload(reporter_channel="EMAIL", narrative="late"),
        IC,
    ))
    alg = get_success_data(api.transition_allegation(alg["id"], {"to_status": "TRIAGED"}, IC))
    subj = get_success_data(api.create_subject(
        case["id"], create_subject_payload(employee_ref="EMP-100"), INV
    ))
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    get_success_data(api.transition_case(case["id"], {"to_status": "FINDINGS"}, inv1))
    resp = api.create_finding(
        case["id"],
        {"allegation_id": alg["id"], "subject_id": subj["id"]},
        inv1,
    )
    validate_error(resp, ApiErrorId.ERR_ALLEGATION_NOT_LINKED, expected_status=409)


def test_finding_with_foreign_subject_and_unreviewable_evidence_rejected(api):
    """PRD §3.7: "The referenced subject must belong to the case, otherwise
    `ERR_SUBJECT_NOT_IN_CASE`."
    PRD §3.7: "Each element of `evidence_item_ids` must reference an
    `EvidenceItem` that belongs to the case and is in `UNDER_REVIEW` or
    `ADMITTED` at link time, otherwise `ERR_EVIDENCE_NOT_REVIEWABLE`."

    Design: Corner/state_machines/finding_with_foreign_subject_and_unreviewable_evidence_rejected
    """
    reset_clock()
    # Case A path — go to FINDINGS with a COLLECTED scope holding a LOGGED item
    bundle = create_case_in_fieldwork(
        title="CaseA", allegation_category="FRAUD", severity="HIGH",
        department="Finance",
    )
    ca = bundle["case"]
    alg_a = get_success_data(api.create_allegation(
        ca["id"], create_allegation_payload(is_anonymous=True, reporter_ref=None), IC
    ))
    get_success_data(api.transition_allegation(alg_a["id"], {"to_status": "TRIAGED"}, IC))
    alg_a = get_success_data(api.transition_allegation(alg_a["id"], {"to_status": "LINKED"}, IC))
    subj_a = get_success_data(api.create_subject(
        ca["id"], create_subject_payload(employee_ref="EMP-100"), INV
    ))
    notice = get_success_data(api.create_preservation_notice(
        ca["id"],
        {"custodian_ref": "EMP-100", "scope": "ALL_DATA", "is_regulator_ordered": False},
        GC,
    ))
    get_success_data(api.transition_preservation_notice(notice["id"], {"to_status": "ACKNOWLEDGED"}, GC))
    scope = get_success_data(api.create_collection_scope(
        ca["id"],
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
    ev = get_success_data(api.create_evidence_item(
        scope["id"],
        create_evidence_item_payload(custodian_ref="EMP-100", hash_value="h1", size_bytes=1000),
        INV,
    ))
    # Leave ev in LOGGED (do not review)
    get_success_data(api.transition_collection_scope(scope["id"], {"to_status": "COLLECTED"}, inv1))
    get_success_data(api.transition_case(ca["id"], {"to_status": "FINDINGS"}, inv1))
    # Case B with its own subject
    cb = get_success_data(api.create_case(
        {"title": "CaseB", "allegation_category": "FRAUD", "severity": "LOW",
         "department": "Finance", "lead_investigator_id": "inv-lead-2"},
        IC,
    ))
    subj_b = get_success_data(api.create_subject(
        cb["id"], create_subject_payload(employee_ref="EMP-200"), INV
    ))
    # Foreign subject rejection
    resp1 = api.create_finding(
        ca["id"],
        {"allegation_id": alg_a["id"], "subject_id": subj_b["id"]},
        inv1,
    )
    validate_error(resp1, ApiErrorId.ERR_SUBJECT_NOT_IN_CASE, expected_status=409)
    # LOGGED (not reviewable) evidence rejection
    resp2 = api.create_finding(
        ca["id"],
        {"allegation_id": alg_a["id"], "subject_id": subj_a["id"],
         "evidence_item_ids": [ev["id"]]},
        inv1,
    )
    validate_error(resp2, ApiErrorId.ERR_EVIDENCE_NOT_REVIEWABLE, expected_status=409)


def test_subject_clear_with_open_findings_rejected(api):
    """PRD §3.3: "An `InvestigationsManager` may later move a subject to
    `CLEARED` (permitted only when no `Finding` references the subject in
    `DRAFT`, `CALIBRATED`, or `CHALLENGED` — otherwise
    `ERR_SUBJECT_HAS_OPEN_FINDINGS`) or to `SEPARATED` (unconditionally)."

    Design: Corner/state_machines/subject_clear_with_open_findings_rejected
    """
    reset_clock()
    bundle = create_case_in_fieldwork(
        title="SubjClear", allegation_category="POLICY_VIOLATION",
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
    get_success_data(api.transition_finding(
        finding["id"],
        create_calibrate_payload(consistency_level="MEDIUM", finding_type="INCONCLUSIVE"),
        hr1,
    ))
    # Finding is CALIBRATED — open
    resp = api.transition_subject(subj["id"], {"to_status": "CLEARED"}, MGR)
    validate_error(resp, ApiErrorId.ERR_SUBJECT_HAS_OPEN_FINDINGS, expected_status=409)
    # Finalize then clear
    fin = make_manager_headers(TEST_DEFAULTS["FINALIZER_ID"])
    get_success_data(api.transition_finding(finding["id"], {"to_status": "FINAL"}, fin))
    ok = api.transition_subject(subj["id"], {"to_status": "CLEARED"}, MGR)
    subj_after = validate_success(ok, expected_status=200)
    assert subj_after["status"] == "CLEARED"


def test_privilege_designation_cross_case_target_rejected(api):
    """PRD §3.6: "The designated target must belong to the same case as the
    designation — a mismatch is rejected with `ERR_TARGET_CASE_MISMATCH`."

    Design: Corner/validations/privilege_designation_cross_case_target_rejected
    """
    reset_clock()
    bundle_a = create_case_in_fieldwork(
        title="TCaseA", allegation_category="HARASSMENT", severity="MEDIUM",
        department="Ops",
    )
    ca = bundle_a["case"]
    interview = get_success_data(api.create_interview(
        ca["id"],
        create_interview_payload(
            witness_ref="W-1", interviewer_id="inv-9",
            scheduled_start="2026-05-10T14:00:00Z",
            scheduled_end="2026-05-10T15:00:00Z",
        ),
        INV,
    ))
    cb = get_success_data(api.create_case(
        {"title": "TCaseB", "allegation_category": "FRAUD", "severity": "LOW",
         "department": "Finance", "lead_investigator_id": "inv-lead-2"},
        IC,
    ))
    resp = api.create_privilege_designation(
        cb["id"],
        {"target_type": "INTERVIEW", "target_id": interview["id"],
         "privilege_type": "ACP"},
        GC,
    )
    validate_error(resp, ApiErrorId.ERR_TARGET_CASE_MISMATCH, expected_status=409)
