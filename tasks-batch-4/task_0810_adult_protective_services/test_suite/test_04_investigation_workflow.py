"""Investigation lifecycle: the FINDINGS_SUBMITTED <-> IN_PROGRESS revision
cycle, the dispose cascade into the case and client, findings preconditions,
FK-filtered reads, and service-plan activation."""
from test_helpers import validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS
from test_helpers import fixtures as fx

CASEWORKER = TEST_USERS["caseworker_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


def test_return_moves_investigation_back_to_in_progress(api):
    """PRD §3.3: "Returning findings for re-investigation takes a `return_reason`,
    moves the investigation from `FINDINGS_SUBMITTED` back to `IN_PROGRESS`, and
    increments its `return_count` by one".

    Design: Difficulty/non_linear_state_machine/investigation_revision_cycle
    """
    base = fx.create_findings_submitted(allegation_types=["NEGLECT"], priority="ROUTINE")
    inv_id = base["investigation"]["id"]
    resp = api.return_findings(inv_id, {"return_reason": "obtain bank records"}, SUPERVISOR)
    data = validate_success(resp)
    assert data["status"] == "IN_PROGRESS"


def test_return_increments_return_count(api):
    """PRD §3.3: "Returning findings for re-investigation takes a `return_reason`,
    moves the investigation from `FINDINGS_SUBMITTED` back to `IN_PROGRESS`, and
    increments its `return_count` by one, capturing how many times the findings
    have been bounced back."

    Design: Difficulty/non_linear_state_machine/investigation_revision_cycle
    """
    base = fx.create_findings_submitted(allegation_types=["NEGLECT"], priority="ROUTINE")
    inv_id = base["investigation"]["id"]
    resp = api.return_findings(inv_id, {"return_reason": "obtain bank records"}, SUPERVISOR)
    data = validate_success(resp)
    assert data["return_count"] == 1, f"expected return_count 1, got {data['return_count']}"


def test_dispose_advances_investigation_and_case(api):
    """PRD §3.3: "Disposing the findings takes a `disposition` ... moves the
    investigation from `FINDINGS_SUBMITTED` to `DISPOSED` ... Disposal also
    drives a cascade: the owning case advances from `UNDER_INVESTIGATION` to
    `READY_FOR_CLOSURE`".

    Design: Difficulty/transitive_cascade/dispose_cascade_case_client_status
    """
    base = fx.create_findings_submitted(allegation_types=["NEGLECT"], priority="PRIORITY")
    inv_id = base["investigation"]["id"]
    resp = api.dispose_investigation(inv_id, {"disposition": "SUBSTANTIATED"}, SUPERVISOR)
    data = validate_success(resp)
    assert data["status"] == "DISPOSED"
    case = fx.get_case(base["case_id"])
    assert case["status"] == "READY_FOR_CLOSURE"


def test_dispose_cascades_client_to_services_pending(api):
    """PRD §3.3: "and as part of that same chain the subject client advances from
    `UNDER_INVESTIGATION` to `SERVICES_PENDING`."

    Design: Difficulty/transitive_cascade/dispose_cascade_case_client_status
    """
    base = fx.create_findings_submitted(allegation_types=["NEGLECT"], priority="PRIORITY")
    inv_id = base["investigation"]["id"]
    api.dispose_investigation(inv_id, {"disposition": "SUBSTANTIATED"}, SUPERVISOR)
    client = fx.get_client(base["client"]["id"])
    assert client["status"] == "SERVICES_PENDING", (
        f"dispose must advance client to SERVICES_PENDING; got {client['status']}"
    )


def test_dispose_from_in_progress_returns_invalid_state(api):
    """PRD §3.3: "both actions require the investigation to be in
    `FINDINGS_SUBMITTED`, and attempting either from another status yields
    `ERR_INVESTIGATION_INVALID_STATE` (409)."

    Design: Corner/state_machines/dispose_from_in_progress_returns_invalid_state
    """
    base = fx.create_case_under_investigation(allegation_types=["NEGLECT"], priority="PRIORITY")
    inv_id = base["investigation"]["id"]  # still IN_PROGRESS
    resp = api.dispose_investigation(inv_id, {"disposition": "SUBSTANTIATED"}, SUPERVISOR)
    validate_error(resp, ApiErrorId.ERR_INVESTIGATION_INVALID_STATE.value)


def test_submit_findings_without_comprehensive_assessment_rejected(api):
    """PRD §3.3: "Submission additionally requires that a comprehensive
    assessment already exist for the subject client — that is, the client's
    `comprehensive_risk_score` is not null; if it is still null the submission
    is rejected with `ERR_COMPREHENSIVE_ASSESSMENT_REQUIRED` (409)."

    Design: Corner/state_machines/submit_findings_without_comprehensive_assessment_rejected
    """
    base = fx.create_case_under_investigation(allegation_types=["NEGLECT"], priority="PRIORITY")
    inv_id = base["investigation"]["id"]
    resp = api.submit_findings(inv_id, {"finding_summary": "premature"}, CASEWORKER)
    validate_error(resp, ApiErrorId.ERR_COMPREHENSIVE_ASSESSMENT_REQUIRED.value)


def test_investigations_filtered_by_case_id(api):
    """PRD §4: "GET `/investigations` — List investigations, optionally filtered
    by case".
    PRD §3.3: "a `Caseworker` opens an **Investigation** against it by supplying
    the `case_id` of the case to be investigated."

    Design: Corner/endpoints/investigations_filtered_by_case_id
    """
    base = fx.create_case_under_investigation(allegation_types=["NEGLECT"], priority="PRIORITY")
    inv_id = base["investigation"]["id"]
    data, meta = validate_paginated(api.list_investigations(CASEWORKER, params={"case_id": base["case_id"]}))
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == inv_id
    assert data[0]["case_id"] == base["case_id"]


def test_service_plan_activates_client(api):
    """PRD §3.7: "Creating the plan sets the case's `service_plan_status` from
    `NONE` to `ACTIVE`, records the linked `benefit_programs` on the case, and
    advances the subject client from `SERVICES_PENDING` to `SERVICES_ACTIVE`."

    Design: Corner/endpoints/service_plan_activates_client
    """
    base = fx.create_case_ready_for_closure(allegation_types=["NEGLECT"], priority="PRIORITY",
                                            disposition="UNSUBSTANTIATED",
                                            comp_levels=dict(isolation_level=1, cognitive_impairment_level=1,
                                                             financial_vulnerability_level=1,
                                                             caregiver_dependency_level=1, prior_report_count=0))
    resp = api.create_service_plan(base["case_id"], {"benefit_programs": ["SNAP", "MEDICAID"]}, CASEWORKER)
    data = validate_success(resp)
    assert data["service_plan_status"] == "ACTIVE"
    client = fx.get_client(base["client"]["id"])
    assert client["status"] == "SERVICES_ACTIVE"
