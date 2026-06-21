"""State-machine behavior: dependent verification cycle, enrollment EOI branching,
EOI cross-entity gating, and invalid-transition / terminal-lockdown rejections.

Covers Difficulty/non_linear_state_machine, Difficulty/cross_entity_state_dependency
(EOI), and Corner/state_machines invalid-transition claims.
"""
from test_helpers import (
    get_success_data, validate_success, validate_error, ApiErrorId,
    setup_pending_dependent, setup_pending_eoi_enrollment,
    setup_eligible_employee, setup_active_medical_enrollment,
    create_offering, create_tier, create_draft_enrollment, employee_version,
    setup_lowest_cost_medical_for_employee,
    api_client as api,
    build_user_headers, TEST_USERS,
)

_ADMIN = TEST_USERS["benefits_admin_headers"]
_VERIFIER = TEST_USERS["dependent_verifier_headers"]
_COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_dependent_verification_cycle_then_verified():
    """PRD §3.3: "This loop is cyclic: a dependent may bounce between PENDING and
    INFO_REQUESTED any number of rounds before it is resolved, and each request-info and
    each resubmit increments the dependent's version."
    PRD §3.3: "from PENDING a DependentVerifier verifies the dependent, moving it from
    PENDING to VERIFIED, which records the verifier's X-User-ID into verified_by_user_id
    and increments version."

    Design: Difficulty/non_linear_state_machine/dependent_verification_cycle_pending_inforequested_pending
    """
    ctx = setup_pending_dependent(relationship="CHILD")
    dep_id = ctx["dependent"]["id"]
    # Round 1: PENDING -> INFO_REQUESTED -> PENDING
    d = get_success_data(api.request_info_dependent(dep_id, _VERIFIER))
    assert d["verification_status"] == "INFO_REQUESTED", d
    d = get_success_data(api.resubmit_dependent(dep_id, _ADMIN))
    assert d["verification_status"] == "PENDING", d
    # Round 2: PENDING -> INFO_REQUESTED -> PENDING
    d = get_success_data(api.request_info_dependent(dep_id, _VERIFIER))
    assert d["verification_status"] == "INFO_REQUESTED", d
    d = get_success_data(api.resubmit_dependent(dep_id, _ADMIN))
    assert d["verification_status"] == "PENDING", d
    # Final: PENDING -> VERIFIED
    verifier = build_user_headers("verifier_x", "DependentVerifier")
    d = get_success_data(api.verify_dependent(dep_id, verifier))
    assert d["verification_status"] == "VERIFIED", d
    assert d["verified_by_user_id"] == "verifier_x", d


def test_dependent_version_increments_through_cycle():
    """PRD §3.3: "each request-info and each resubmit increments the dependent's version."

    Design: Difficulty/non_linear_state_machine/dependent_verification_cycle_pending_inforequested_pending
    """
    ctx = setup_pending_dependent(relationship="CHILD")
    dep_id = ctx["dependent"]["id"]
    v0 = ctx["dependent"]["version"]
    v1 = get_success_data(api.request_info_dependent(dep_id, _VERIFIER))["version"]
    assert v1 == v0 + 1, (v0, v1)
    v2 = get_success_data(api.resubmit_dependent(dep_id, _ADMIN))["version"]
    assert v2 == v1 + 1, (v1, v2)
    v3 = get_success_data(api.request_info_dependent(dep_id, _VERIFIER))["version"]
    assert v3 == v2 + 1, (v2, v3)


def test_eoi_approved_activates_enrollment_and_emits_add_feed():
    """PRD §3.4: "When the decision is set to APPROVED, the request moves from PENDING to
    APPROVED and the linked enrollment is carried from PENDING_EOI to ACTIVE: the
    enrollment's monthly_employee_cost_cents and per_paycheck_deduction_cents are
    recomputed, a carrier feed record with the ADD maintenance type is emitted, and the
    enrollment's version is incremented."

    Design: Difficulty/non_linear_state_machine/enrollment_branching_eoi_approve_vs_deny_revert
    """
    ctx = setup_pending_eoi_enrollment(coverage_amount_cents=30000000,
                                       guaranteed_issue_amount_cents=15000000,
                                       rate_per_1000_monthly_cents=25)
    enr_id = ctx["enrollment"]["id"]
    get_success_data(api.decide_eoi_request(ctx["eoi_request"]["id"], {"decision": "APPROVED"}, _COMPLIANCE))
    enr = get_success_data(api.get_enrollment(enr_id, _ADMIN))
    assert enr["status"] == "ACTIVE", enr
    # 30000000 / 100000 = 300 units * 25 = 7500
    assert enr["monthly_employee_cost_cents"] == 7500, enr
    records = get_success_data(api.list_carrier_feed_records(
        _ADMIN, params={"enrollment_id": enr_id, "transaction_set": "ADD"}))
    assert len(records) == 1, records


def test_eoi_denied_reverts_enrollment_to_draft_no_feed():
    """PRD §3.4: "When the decision is set to DENIED, the request moves from PENDING to
    DENIED and, as a compensating action, the linked enrollment reverts from PENDING_EOI
    back to DRAFT with its version incremented — and, deliberately, no carrier feed record
    is emitted on denial."

    Design: Difficulty/non_linear_state_machine/enrollment_branching_eoi_approve_vs_deny_revert
    """
    ctx = setup_pending_eoi_enrollment(coverage_amount_cents=30000000,
                                       guaranteed_issue_amount_cents=15000000,
                                       rate_per_1000_monthly_cents=25)
    enr_id = ctx["enrollment"]["id"]
    get_success_data(api.decide_eoi_request(ctx["eoi_request"]["id"], {"decision": "DENIED"}, _COMPLIANCE))
    enr = get_success_data(api.get_enrollment(enr_id, _ADMIN))
    assert enr["status"] == "DRAFT", enr
    records = get_success_data(api.list_carrier_feed_records(
        _ADMIN, params={"enrollment_id": enr_id}))
    assert len(records) == 0, records


def test_eoi_decide_blocked_when_enrollment_not_pending_eoi():
    """PRD §3.4: "A ComplianceOfficer decides a pending evidence-of-insurability request
    by supplying a decision. The request must currently be PENDING and its linked
    enrollment must currently be in PENDING_EOI."

    Design: Difficulty/cross_entity_state_dependency/eoi_approve_requires_enrollment_pending_eoi
    """
    ctx = setup_pending_eoi_enrollment(coverage_amount_cents=30000000,
                                       guaranteed_issue_amount_cents=15000000,
                                       rate_per_1000_monthly_cents=25)
    enr_id = ctx["enrollment"]["id"]
    eoi_id = ctx["eoi_request"]["id"]
    # First DENY reverts the enrollment to DRAFT and terminates the request.
    get_success_data(api.decide_eoi_request(eoi_id, {"decision": "DENIED"}, _COMPLIANCE))
    # Now attempt to APPROVE the already-decided request.
    resp = api.decide_eoi_request(eoi_id, {"decision": "APPROVED"}, _COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    enr = get_success_data(api.get_enrollment(enr_id, _ADMIN))
    assert enr["status"] == "DRAFT", enr


def test_eoi_decide_blocked_after_enrollment_already_activated():
    """PRD §3.4: "A ComplianceOfficer decides a pending evidence-of-insurability request by
    supplying a decision. The request must currently be PENDING and its linked enrollment
    must currently be in PENDING_EOI."

    Design: Difficulty/cross_entity_state_dependency/eoi_approve_requires_enrollment_pending_eoi
    """
    ctx = setup_pending_eoi_enrollment(coverage_amount_cents=30000000,
                                       guaranteed_issue_amount_cents=15000000,
                                       rate_per_1000_monthly_cents=25)
    enr_id = ctx["enrollment"]["id"]
    eoi_id = ctx["eoi_request"]["id"]
    # First APPROVE carries the enrollment to ACTIVE and terminates the request as APPROVED.
    get_success_data(api.decide_eoi_request(eoi_id, {"decision": "APPROVED"}, _COMPLIANCE))
    enr = get_success_data(api.get_enrollment(enr_id, _ADMIN))
    assert enr["status"] == "ACTIVE", enr
    # A second decision on the terminal request is blocked: request no longer PENDING and
    # the enrollment is no longer PENDING_EOI.
    resp = api.decide_eoi_request(eoi_id, {"decision": "DENIED"}, _COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_activate_already_active_enrollment_invalid_state():
    """PRD §3.4: "Activation of a draft enrollment is performed by a BenefitsAdmin and is
    the system's central gate. The enrollment must be in DRAFT".
    PRD §2.10: "for any transition endpoint, the target resource must currently be in a
    state from which the requested transition is defined; otherwise the request fails with
    ERR_INVALID_STATE."

    Design: Corner/state_machines/activate_already_active_enrollment_invalid_state
    """
    ctx = setup_active_medical_enrollment()
    enr_id = ctx["enrollment"]["id"]
    ev = employee_version(ctx["employee"]["id"])
    resp = api.activate_enrollment(enr_id, {"expected_employee_version": ev}, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    enr = get_success_data(api.get_enrollment(enr_id, _ADMIN))
    assert enr["status"] == "ACTIVE", enr


def test_cancel_active_enrollment_invalid_state():
    """PRD §3.4: "A BenefitsAdmin may instead cancel a draft that will not be activated,
    moving the enrollment from DRAFT to CANCELLED and incrementing its version."
    PRD §2.10: "for any transition endpoint, the target resource must currently be in a
    state from which the requested transition is defined; otherwise the request fails with
    ERR_INVALID_STATE."

    Design: Corner/state_machines/cancel_active_enrollment_invalid_state
    """
    ctx = setup_active_medical_enrollment()
    resp = api.cancel_enrollment(ctx["enrollment"]["id"], _ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_verify_dependent_from_info_requested_invalid_state():
    """PRD §3.3: "Each of these four transitions requires the dependent to be in the
    precise originating state named, and a request from any other state is refused with
    ERR_INVALID_STATE."

    Design: Corner/state_machines/verify_dependent_from_inforequested_invalid_state
    """
    ctx = setup_pending_dependent(relationship="SPOUSE")
    dep_id = ctx["dependent"]["id"]
    get_success_data(api.request_info_dependent(dep_id, _VERIFIER))
    verifier = build_user_headers("ver_a", "DependentVerifier")
    resp = api.verify_dependent(dep_id, verifier)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_file_already_filed_1095c_rejected():
    """PRD §3.10: "FILED is terminal and immutable: any attempt to mutate a form that is
    already FILED is rejected with ERR_FORM_ALREADY_FILED."

    Design: Corner/state_machines/file_already_filed_1095c_invalid_state
    """
    ctx = setup_lowest_cost_medical_for_employee(monthly_household_income_cents=100000)
    form = get_success_data(api.generate_form_1095c(ctx["employee"]["id"], {"tax_year": 2026}, _COMPLIANCE))
    get_success_data(api.file_form_1095c(form["id"], _COMPLIANCE))
    resp = api.file_form_1095c(form["id"], _COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_FORM_ALREADY_FILED.value)
    after = get_success_data(api.get_form_1095c(form["id"], _COMPLIANCE))
    assert after["status"] == "FILED", after


def test_submit_eoi_for_under_gi_life_enrollment_invalid_state():
    """PRD §3.4: "When the enrollment's benefit_type is VOLUNTARY_LIFE and its
    coverage_amount_cents exceeds the offering's guaranteed_issue_amount_cents, a
    BenefitsAdmin submits the draft for evidence of insurability, moving it from DRAFT to
    PENDING_EOI."
    PRD §2.10: "the target resource must currently be in a state from which the requested
    transition is defined; otherwise the request fails with ERR_INVALID_STATE."

    Design: Corner/endpoints/submit_eoi_for_under_gi_life_enrollment_invalid_state
    """
    emp = setup_eligible_employee()
    off = create_offering(benefit_type="VOLUNTARY_LIFE", name="Voluntary Life",
                          requires_eoi=True, guaranteed_issue_amount_cents=15000000)
    tier = create_tier(off["id"], coverage_level="EMPLOYEE_ONLY",
                       monthly_premium_cents=1, employer_contribution_pct=0.0,
                       rate_per_1000_monthly_cents=25)
    enr = create_draft_enrollment(emp["id"], tier["id"], coverage_start_date="2026-02-01",
                                  coverage_amount_cents=10000000)
    resp = api.submit_eoi_enrollment(enr["id"], _ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
