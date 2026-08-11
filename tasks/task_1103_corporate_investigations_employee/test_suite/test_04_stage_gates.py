"""Corner tests for stage gates (findings-exit, disposition, remediation, close)."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    reset_clock, create_case, create_case_in_fieldwork, create_triaged_case,
    create_plan_payload, create_allegation_payload, create_subject_payload,
    create_collection_scope_payload, create_preservation_notice_payload,
    create_recommendation_payload, create_disclosure_payload,
    create_remediation_payload, create_calibrate_payload,
    setup_final_substantiated_finding, setup_disposition_case,
    make_investigator_headers, make_manager_headers, make_hr_headers,
    make_gc_headers, make_clo_headers, TEST_DEFAULTS,
)

IC = TEST_USERS["intake_coordinator_headers"]
INV = TEST_USERS["investigator_headers"]
MGR = TEST_USERS["manager_headers"]
HR = TEST_USERS["hr_headers"]
GC = TEST_USERS["gc_headers"]
CLO = TEST_USERS["clo_headers"]


def _reach_fieldwork_with_ack_notice_and_proposed_scope(api, case_overrides=None):
    """Helper: case FIELDWORK, notice ACK, scope PROPOSED. Returns dict."""
    bundle = create_case_in_fieldwork(**(case_overrides or {}))
    case = bundle["case"]
    notice = get_success_data(api.create_preservation_notice(
        case["id"],
        create_preservation_notice_payload(
            custodian_ref="EMP-100", scope="ALL_DATA", is_regulator_ordered=False
        ),
        GC,
    ))
    get_success_data(api.transition_preservation_notice(
        notice["id"], {"to_status": "ACKNOWLEDGED"}, GC
    ))
    scope_payload = create_collection_scope_payload(
        custodian_ref="EMP-100", data_source="EMAIL",
        preservation_notice_id=notice["id"],
    )
    scope = get_success_data(api.create_collection_scope(case["id"], scope_payload, INV))
    return {"case": case, "notice": notice, "scope": scope, "plan": bundle["plan"]}


def test_scope_collect_with_zero_items_rejected(api):
    """PRD §3.4: "Completing a collection moves a scope from `IN_PROGRESS` to
    `COLLECTED` and requires at least one linked evidence item in `LOGGED`,
    `UNDER_REVIEW`, or `ADMITTED`; otherwise `ERR_EMPTY_COLLECTION`."

    Design: Corner/state_machines/scope_collect_with_zero_items_rejected
    """
    reset_clock()
    bundle = _reach_fieldwork_with_ack_notice_and_proposed_scope(
        api,
        {"title": "EmptyCol", "allegation_category": "FRAUD", "severity": "HIGH",
         "department": "Finance"},
    )
    scope = bundle["scope"]
    mgr = make_manager_headers(TEST_DEFAULTS["APPROVER_ID"])
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    get_success_data(api.transition_collection_scope(scope["id"], {"to_status": "APPROVED"}, mgr))
    get_success_data(api.transition_collection_scope(scope["id"], {"to_status": "IN_PROGRESS"}, inv1))
    resp = api.transition_collection_scope(scope["id"], {"to_status": "COLLECTED"}, inv1)
    validate_error(resp, ApiErrorId.ERR_EMPTY_COLLECTION, expected_status=409)
    after = get_success_data(api.get_collection_scope(scope["id"], INV))
    assert after["status"] == "IN_PROGRESS"


def test_scope_create_without_preservation_rejected(api):
    """PRD §3.4: "The custodian must be covered by an `ISSUED` or
    `ACKNOWLEDGED` preservation notice whose `scope` covers the requested
    `data_source` — `ALL_DATA` covers every source; `EMAIL` covers `EMAIL`;
    `DEVICES` covers `DEVICE`; `CHAT` covers `CHAT`; `FILES` covers `FILES` —
    otherwise the create is rejected with `ERR_CUSTODIAN_NOT_PRESERVED`."

    Design: Corner/state_machines/scope_create_without_preservation_rejected
    """
    reset_clock()
    bundle = create_case_in_fieldwork(
        title="NoPres", allegation_category="DATA_BREACH", severity="HIGH",
        department="IT",
    )
    case = bundle["case"]
    payload = create_collection_scope_payload(
        custodian_ref="EMP-100", data_source="EMAIL",
    )
    resp = api.create_collection_scope(case["id"], payload, INV)
    validate_error(resp, ApiErrorId.ERR_CUSTODIAN_NOT_PRESERVED, expected_status=409)


def test_findings_gate_open_scopes_rejected(api):
    """PRD §3.12: "Moving a case from `FIELDWORK` to `FINDINGS` is performed
    by an `Investigator` and requires two conditions: no `CollectionScope` of
    the case may remain in `PROPOSED`, `APPROVED`, or `IN_PROGRESS`
    (`ERR_OPEN_COLLECTION_SCOPES`)..."

    Design: Corner/state_machines/findings_gate_open_scopes_rejected
    """
    reset_clock()
    bundle = _reach_fieldwork_with_ack_notice_and_proposed_scope(
        api,
        {"title": "OpenScope", "allegation_category": "FRAUD", "severity": "HIGH",
         "department": "Finance"},
    )
    case = bundle["case"]
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    resp = api.transition_case(case["id"], {"to_status": "FINDINGS"}, inv1)
    validate_error(resp, ApiErrorId.ERR_OPEN_COLLECTION_SCOPES, expected_status=409)
    after = get_success_data(api.get_case(case["id"], IC))
    assert after["status"] == "FIELDWORK"


def test_findings_gate_preservation_incomplete_rejected(api):
    """PRD §3.12: "Moving a case from `FIELDWORK` to `FINDINGS` is performed
    by an `Investigator` and requires two conditions: no `CollectionScope`
    of the case may remain in `PROPOSED`, `APPROVED`, or `IN_PROGRESS`
    (`ERR_OPEN_COLLECTION_SCOPES`), and the case's
    `preservation_completeness_ratio` must equal 1.00
    (`ERR_PRESERVATION_INCOMPLETE`) — meaning every issued notice has been
    acknowledged and none remain in `ISSUED`."

    Design: Corner/state_machines/findings_gate_preservation_incomplete_rejected
    """
    reset_clock()
    bundle = create_case_in_fieldwork(
        title="PresInc", allegation_category="FRAUD", severity="HIGH",
        department="Finance",
    )
    case = bundle["case"]
    # Notice created but NOT acknowledged => ratio 0.00
    get_success_data(api.create_preservation_notice(
        case["id"],
        create_preservation_notice_payload(
            custodian_ref="EMP-100", scope="ALL_DATA", is_regulator_ordered=False,
        ),
        GC,
    ))
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    resp = api.transition_case(case["id"], {"to_status": "FINDINGS"}, inv1)
    validate_error(resp, ApiErrorId.ERR_PRESERVATION_INCOMPLETE, expected_status=409)
    # Now acknowledge and retry
    notices = get_success_data(api.list_preservation_notices(GC, params={"case_id": case["id"]}))
    notice_id = notices[0]["id"] if isinstance(notices, list) else notices["data"][0]["id"]
    # list returns raw data; re-read carefully
    from test_helpers import validate_paginated
    data, meta = validate_paginated(api.list_preservation_notices(GC, params={"case_id": case["id"]}))
    notice_id = data[0]["id"]
    get_success_data(api.transition_preservation_notice(
        notice_id, {"to_status": "ACKNOWLEDGED"}, GC
    ))
    ok = api.transition_case(case["id"], {"to_status": "FINDINGS"}, inv1)
    case_after = validate_success(ok, expected_status=200)
    assert case_after["status"] == "FINDINGS"


def test_critical_case_remediation_blocked_without_disclosure_rejected(api):
    """PRD §3.12: "Second, if the case's severity is `CRITICAL`, there must
    be at least one `SelfDisclosureDecision` of the case in `DECIDED`,
    `FILED`, or `OVERRIDDEN`, and none may be in `PENDING` — otherwise
    `ERR_DISCLOSURE_REQUIRED`."

    Design: Corner/state_machines/critical_case_remediation_blocked_without_disclosure_rejected
    """
    reset_clock()
    bundle = setup_disposition_case(severity="CRITICAL", finding_type="INCONCLUSIVE")
    case = bundle["case"]
    # Note: setup_disposition_case already moved case to DISPOSITION
    # Need to go back: but PRD says disclosure must be opened while case is
    # in FINDINGS or DISPOSITION — case is in DISPOSITION, so we can still
    # open one.
    case_fresh = get_success_data(api.get_case(case["id"], GC))
    d1 = get_success_data(api.create_self_disclosure_decision(
        case["id"],
        create_disclosure_payload(
            regulator="SEC", decision_deadline="2026-05-15T00:00:00Z",
            expected_case_version=case_fresh["version"],
        ),
        GC,
    ))
    mgr = make_manager_headers(TEST_DEFAULTS["APPROVER_ID"])
    resp = api.transition_case(case["id"], {"to_status": "REMEDIATION"}, mgr)
    validate_error(resp, ApiErrorId.ERR_DISCLOSURE_REQUIRED, expected_status=409)
    # Decide the pending decision, then retry
    clo1 = make_clo_headers("clo-1")
    get_success_data(api.transition_self_disclosure_decision(
        d1["id"],
        {"to_status": "DECIDED", "decision": "NO_DISCLOSE", "rationale": "reviewed"},
        clo1,
    ))
    ok = api.transition_case(case["id"], {"to_status": "REMEDIATION"}, mgr)
    case_after = validate_success(ok, expected_status=200)
    assert case_after["status"] == "REMEDIATION"


def test_regulator_ordered_notice_release_rejected(api):
    """PRD §3.3: "Releasing a notice — whether from `ISSUED` or `ACKNOWLEDGED`
    — moves it to `RELEASED`. If `is_regulator_ordered` is true, release is
    forbidden until the parent case is `CLOSED`; attempting earlier release
    is rejected with `ERR_ORDERED_NOTICE_RESTRICTION`."

    Design: Corner/state_machines/regulator_ordered_notice_release_rejected
    """
    reset_clock()
    bundle = create_case_in_fieldwork(
        title="RegOrd", allegation_category="FRAUD", severity="HIGH",
        department="Finance",
    )
    case = bundle["case"]
    n1 = get_success_data(api.create_preservation_notice(
        case["id"],
        create_preservation_notice_payload(
            custodian_ref="EMP-100", scope="ALL_DATA", is_regulator_ordered=True,
        ),
        GC,
    ))
    n1 = get_success_data(api.transition_preservation_notice(
        n1["id"], {"to_status": "ACKNOWLEDGED"}, GC
    ))
    n2 = get_success_data(api.create_preservation_notice(
        case["id"],
        create_preservation_notice_payload(
            custodian_ref="EMP-200", scope="ALL_DATA", is_regulator_ordered=False,
        ),
        GC,
    ))
    resp = api.transition_preservation_notice(n1["id"], {"to_status": "RELEASED"}, GC)
    validate_error(resp, ApiErrorId.ERR_ORDERED_NOTICE_RESTRICTION, expected_status=409)
    n1_after = get_success_data(api.get_preservation_notice(n1["id"], GC))
    assert n1_after["status"] == "ACKNOWLEDGED"
    ok = api.transition_preservation_notice(n2["id"], {"to_status": "RELEASED"}, GC)
    n2_after = validate_success(ok, expected_status=200)
    assert n2_after["status"] == "RELEASED"


def test_case_close_with_open_remediation_rejected(api):
    """PRD §3.14: "Closing a case is performed by an `InvestigationsManager`
    and moves `REMEDIATION` to `CLOSED`. It requires every `RemediationAction`
    of the case to be in `VERIFIED` or `WAIVED` — any action still in `OPEN`,
    `IN_PROGRESS`, or `AWAITING_VERIFICATION` rejects the close with
    `ERR_OPEN_REMEDIATION`."

    Design: Corner/state_machines/case_close_with_open_remediation_rejected
    """
    reset_clock()
    bundle = setup_disposition_case(severity="MEDIUM", finding_type="INCONCLUSIVE")
    case = bundle["case"]
    mgr = make_manager_headers(TEST_DEFAULTS["APPROVER_ID"])
    case = get_success_data(api.transition_case(case["id"], {"to_status": "REMEDIATION"}, mgr))
    hr1 = make_hr_headers(TEST_DEFAULTS["HR_ID"])
    rem = get_success_data(api.create_remediation_action(
        case["id"],
        create_remediation_payload(action_type="POLICY_UPDATE", owner_ref="own-1"),
        hr1,
    ))
    resp = api.transition_case(case["id"], {"to_status": "CLOSED"}, mgr)
    validate_error(resp, ApiErrorId.ERR_OPEN_REMEDIATION, expected_status=409)
    # Waive the action then retry
    get_success_data(api.transition_remediation_action(
        rem["id"], {"to_status": "WAIVED", "rationale": "covered by other program"}, GC
    ))
    ok = api.transition_case(case["id"], {"to_status": "CLOSED"}, mgr)
    case_after = validate_success(ok, expected_status=200)
    assert case_after["status"] == "CLOSED"


def test_remediation_gate_with_proposed_discipline_rejected(api):
    """PRD §3.12: "Moving from `DISPOSITION` to `REMEDIATION` is performed by
    an `InvestigationsManager` and requires two conditions. First, every
    `DisciplinaryRecommendation` on every finding of the case must be in
    `APPROVED` or `REJECTED` — none may remain in `PROPOSED` — otherwise
    `ERR_UNRESOLVED_DISCIPLINE`."

    Design: Corner/state_machines/remediation_gate_with_proposed_discipline_rejected
    """
    reset_clock()
    bundle = setup_disposition_case(severity="HIGH", finding_type="SUBSTANTIATED")
    case = bundle["case"]
    finding = bundle["finding"]
    hr1 = make_hr_headers(TEST_DEFAULTS["HR_ID"])
    rec = get_success_data(api.create_disciplinary_recommendation(
        finding["id"], create_recommendation_payload(), hr1
    ))
    mgr = make_manager_headers(TEST_DEFAULTS["APPROVER_ID"])
    resp = api.transition_case(case["id"], {"to_status": "REMEDIATION"}, mgr)
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_DISCIPLINE, expected_status=409)
    get_success_data(api.transition_disciplinary_recommendation(
        rec["id"], {"to_status": "REJECTED", "rationale": "redo"}, mgr
    ))
    ok = api.transition_case(case["id"], {"to_status": "REMEDIATION"}, mgr)
    case_after = validate_success(ok, expected_status=200)
    assert case_after["status"] == "REMEDIATION"


def test_open_recommendation_exists_rejected(api):
    """PRD §3.8: "At most one `PROPOSED` recommendation may exist per finding
    — a second concurrent proposal is rejected with
    `ERR_OPEN_RECOMMENDATION_EXISTS`."

    Design: Corner/state_machines/open_recommendation_exists_rejected
    """
    reset_clock()
    bundle = setup_final_substantiated_finding(severity="HIGH")
    finding = bundle["finding"]
    hr1 = make_hr_headers(TEST_DEFAULTS["HR_ID"])
    get_success_data(api.create_disciplinary_recommendation(
        finding["id"], create_recommendation_payload(), hr1
    ))
    hr2 = make_hr_headers("hr-2")
    resp = api.create_disciplinary_recommendation(
        finding["id"],
        create_recommendation_payload(mitigation_count=1, recommended_action="COACHING",
                                      justification="HR disagrees"),
        hr2,
    )
    validate_error(resp, ApiErrorId.ERR_OPEN_RECOMMENDATION_EXISTS, expected_status=409)
