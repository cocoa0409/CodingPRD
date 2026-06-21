"""Valid/invalid state transitions, terminal-state lockdown, precondition
enforcement, side effects, and cross-entity bubble-up.

Queue B (Corner) — section: state_machines.
"""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error, get_success_data, ApiErrorId,
    create_funeral_home, create_gpl_item, create_plot,
    create_case, create_disclosed_case, add_line, create_contract,
    setup_arranged_case, post_principal, submit_for_funding,
    current_contract_version, reserve_plot, setup_case_interment_ready,
    apply_permit, issue_permit, attach_assignment,
)

ADMIN = TEST_USERS["admin_headers"]
ARRANGER = TEST_USERS["arranger_headers"]
TRUST = TEST_USERS["trust_officer_headers"]
CLERK = TEST_USERS["cemetery_clerk_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


def test_acknowledge_disclosure_twice_rejected(api):
    """PRD §3.2: "The first move, acknowledging the FTC funeral-rule GPL
    disclosure, is performed by an Arranger and is allowed only when the case's
    arrangement_status is INTAKE ... Attempting this transition from any other
    arrangement state is rejected with ERR_INVALID_STATE."

    A second acknowledge on a DISCLOSED case is rejected; disclosure_officer_id
    is unchanged.

    Design: Corner/state_machines/acknowledge_disclosure_twice_returns_invalid_state
    """
    home = create_funeral_home()
    case = create_disclosed_case(home["id"], case_mode="AT_NEED",
                                 date_of_death="2026-06-01T00:00:00.000Z")
    before = validate_success(api.get_case(case["id"], ARRANGER))

    alt = TEST_USERS["arranger_headers_alt"]
    resp = api.acknowledge_disclosure(case["id"], alt)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    after = validate_success(api.get_case(case["id"], ARRANGER))
    assert after["disclosure_officer_id"] == before["disclosure_officer_id"]


def test_cancelled_case_cannot_be_completed(api):
    """PRD §3.10: "Completing a case is the Arranger's final arrangement move,
    from ARRANGED to COMPLETED ... attempting it from a non-ARRANGED arrangement
    state is rejected with ERR_INVALID_STATE."

    A CANCELLED (terminal) case rejects complete.

    Design: Corner/state_machines/terminal_cancelled_case_cannot_be_completed
    """
    home = create_funeral_home()
    case = create_case(home["id"], case_mode="AT_NEED",
                       date_of_death="2026-06-01T00:00:00.000Z")
    get_success_data(api.cancel_case(case["id"], ARRANGER))

    resp = api.complete_case(case["id"], ARRANGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    after = validate_success(api.get_case(case["id"], ARRANGER))
    assert after["arrangement_status"] == "CANCELLED"


def test_reapply_issued_permit_rejected(api):
    """PRD §3.7: "Re-applying a REJECTED permit moves it back to APPLIED so it can
    be re-evaluated ... re-applying a permit not in REJECTED is rejected with
    ERR_PERMIT_NOT_REJECTED (HTTP 409)."

    Design: Corner/state_machines/permit_reapply_on_issued_returns_permit_not_rejected
    """
    home = create_funeral_home()
    case = create_case(home["id"], case_mode="AT_NEED",
                       date_of_death="2026-06-01T00:00:00.000Z")
    dc = apply_permit(case["id"], "DEATH_CERTIFICATE")
    issue_permit(dc["id"], "DC-1")

    resp = api.reapply_permit(dc["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_REJECTED.value)

    after = validate_success(api.get_permit(dc["id"], REGISTRAR))
    assert after["status"] == "ISSUED"


def test_issue_rejected_permit_rejected(api):
    """PRD §3.7: "Issuing a permit ... is allowed only when the permit is APPLIED;
    issuing a permit not in APPLIED is rejected with ERR_PERMIT_NOT_APPLIED
    (HTTP 409)."

    A REJECTED permit cannot be issued.

    Design: Corner/state_machines/issue_on_rejected_permit_returns_permit_not_applied
    """
    home = create_funeral_home()
    case = create_case(home["id"], case_mode="AT_NEED",
                       date_of_death="2026-06-01T00:00:00.000Z")
    dc = apply_permit(case["id"], "DEATH_CERTIFICATE")
    get_success_data(api.reject_permit(dc["id"], REGISTRAR))

    resp = api.issue_permit(dc["id"], {"reference_number": "DC-1"}, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_APPLIED.value)

    after = validate_success(api.get_permit(dc["id"], REGISTRAR))
    assert after["status"] == "REJECTED"


def test_reopen_at_need_contract_rejected(api):
    """PRD §3.6: "Reopening is allowed only when the contract is PENDING_FUNDING
    and its funding_type is PRENEED_TRUST; only preneed contracts may be reopened,
    and attempting to reopen any other funding type is rejected with
    ERR_NOT_AMENDABLE (HTTP 409)."

    Design: Corner/state_machines/reopen_at_need_contract_returns_not_amendable
    """
    home, case, svc, contract = setup_arranged_case(
        funding_type="AT_NEED_DIRECT", case_mode="AT_NEED", svc_price=100000)
    submit_for_funding(contract["id"])

    resp = api.reopen_contract(contract["id"], ARRANGER)
    validate_error(resp, ApiErrorId.ERR_NOT_AMENDABLE.value)

    after = validate_success(api.get_contract(contract["id"], ARRANGER))
    assert after["status"] == "PENDING_FUNDING"


def test_submit_for_funding_before_gfs_rejected(api):
    """PRD §3.6: "This is allowed only when the contract is DRAFT and the case's
    gfs_issued is true; submitting before the GFS has been issued is rejected with
    ERR_GFS_NOT_ISSUED (HTTP 409)".

    Design: Corner/state_machines/submit_for_funding_before_gfs_returns_gfs_not_issued
    """
    home = create_funeral_home()
    svc = create_gpl_item(home["id"], code="SVC", name="Basic", category="SERVICE",
                          non_declinable=True, unit_price_cents=100000)
    case = create_disclosed_case(home["id"], case_mode="AT_NEED",
                                 date_of_death="2026-06-01T00:00:00.000Z")
    add_line(case["id"], svc["id"])
    contract = create_contract(case["id"], "AT_NEED_DIRECT")

    resp = api.submit_for_funding(contract["id"], ARRANGER)
    validate_error(resp, ApiErrorId.ERR_GFS_NOT_ISSUED.value)

    after = validate_success(api.get_contract(contract["id"], ARRANGER))
    assert after["status"] == "DRAFT"


def test_issue_gfs_without_contract_rejected(api):
    """PRD §3.3: "issuing before a contract exists is rejected with
    ERR_CONTRACT_REQUIRED (HTTP 409)."

    Design: Corner/state_machines/issue_gfs_without_contract_returns_contract_required
    """
    home = create_funeral_home()
    svc = create_gpl_item(home["id"], code="SVC", name="Basic", category="SERVICE",
                          non_declinable=True, unit_price_cents=100000)
    case = create_disclosed_case(home["id"], case_mode="AT_NEED",
                                 date_of_death="2026-06-01T00:00:00.000Z")
    add_line(case["id"], svc["id"])  # non-declinable -> auto-SELECTED, no contract yet

    resp = api.issue_gfs(case["id"], ARRANGER)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_REQUIRED.value)

    after = validate_success(api.get_case(case["id"], ARRANGER))
    assert after["arrangement_status"] == "DISCLOSED"


def test_complete_case_before_interment_rejected(api):
    """PRD §3.10: "Attempting completion while the interment is not yet INTERRED
    is rejected with ERR_INTERMENT_INCOMPLETE (HTTP 409)".

    A FUNDED contract but interment_status NOT_READY blocks completion.

    Design: Corner/state_machines/complete_case_before_interment_returns_interment_incomplete
    """
    home = create_funeral_home()
    svc = create_gpl_item(home["id"], code="SVC", name="Basic", category="SERVICE",
                          non_declinable=True, unit_price_cents=100000)
    case = create_disclosed_case(home["id"], case_mode="AT_NEED",
                                 date_of_death="2026-06-01T00:00:00.000Z")
    add_line(case["id"], svc["id"])
    contract = create_contract(case["id"], "AT_NEED_DIRECT")
    get_success_data(api.issue_gfs(case["id"], ARRANGER))
    post_principal(contract["id"], 100000)
    submit_for_funding(contract["id"])
    c_v = current_contract_version(contract["id"])
    get_success_data(api.mark_funded(contract["id"], {"expected_contract_version": c_v}, TRUST))

    resp = api.complete_case(case["id"], ARRANGER)
    validate_error(resp, ApiErrorId.ERR_INTERMENT_INCOMPLETE.value)

    after = validate_success(api.get_case(case["id"], ARRANGER))
    assert after["arrangement_status"] == "ARRANGED"


def test_complete_case_unfunded_contract_rejected(api):
    """PRD §3.10: "attempting it while the contract is not FUNDED is rejected with
    ERR_CONTRACT_NOT_FUNDED (HTTP 409)".

    Interment is INTERRED but the contract remains DRAFT, so completion fails.

    Design: Corner/state_machines/complete_case_unfunded_contract_returns_contract_not_funded
    """
    home = create_funeral_home()
    svc = create_gpl_item(home["id"], code="SVC", name="Basic", category="SERVICE",
                          non_declinable=True, unit_price_cents=100000)
    plot = create_plot(home["id"], section="A", plot_code="A-77", current_price_cents=80000)
    case = create_disclosed_case(home["id"], case_mode="AT_NEED",
                                 date_of_death="2026-06-01T00:00:00.000Z")
    add_line(case["id"], svc["id"])
    create_contract(case["id"], "AT_NEED_DIRECT")
    get_success_data(api.issue_gfs(case["id"], ARRANGER))
    setup_case_interment_ready(home["id"], case["id"])
    reserve_plot(plot["id"], case["id"], plot["version"])
    get_success_data(api.inter_plot(plot["id"], CLERK))

    resp = api.complete_case(case["id"], ARRANGER)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_FUNDED.value)

    after = validate_success(api.get_case(case["id"], ARRANGER))
    assert after["interment_status"] == "INTERRED"
    assert after["arrangement_status"] == "ARRANGED"


def test_verify_insurance_assignment_advances_funded_amount(api):
    """PRD §3.5: "Verification advances the assignment to VERIFIED, recomputes the
    contract's funded_amount_cents so it now includes the assigned value".
    PRD §3.4: "For an INSURANCE_ASSIGNMENT contract it is the sum of the
    assigned_value_cents of every insurance assignment on the contract whose
    status is VERIFIED."

    Design: Corner/state_machines/insurance_verify_advances_funded_amount
    """
    home, case, svc, contract = setup_arranged_case(
        funding_type="INSURANCE_ASSIGNMENT", case_mode="AT_NEED", svc_price=100000)
    assign = attach_assignment(contract["id"], 100000)

    verified = validate_success(api.verify_insurance_assignment(assign["id"], TRUST))
    assert verified["status"] == "VERIFIED"
    contract_after = validate_success(api.get_contract(contract["id"], TRUST))
    assert contract_after["funded_amount_cents"] == 100000


def test_verify_assignment_on_non_insurance_contract_rejected(api):
    """PRD §3.5: "Verifying an assignment is allowed only when it is PENDING and
    only when the parent contract's funding_type is INSURANCE_ASSIGNMENT;
    verifying against a contract of a different funding type is rejected with
    ERR_FUNDING_TYPE_MISMATCH (HTTP 409)."

    Design: Corner/state_machines/insurance_verify_on_non_insurance_contract_returns_funding_type_mismatch
    """
    home, case, svc, contract = setup_arranged_case(
        funding_type="AT_NEED_DIRECT", case_mode="AT_NEED", svc_price=100000)
    assign = attach_assignment(contract["id"], 100000)

    resp = api.verify_insurance_assignment(assign["id"], TRUST)
    validate_error(resp, ApiErrorId.ERR_FUNDING_TYPE_MISMATCH.value)

    after = validate_success(api.get_insurance_assignment(assign["id"], TRUST))
    assert after["status"] == "PENDING"


def test_decline_pending_assignment(api):
    """PRD §3.5: "Declining a PENDING assignment moves it to DECLINED and
    increments the assignment's version."
    PRD §3.5: "only a VERIFIED assignment counts toward funded_amount_cents".

    Design: Corner/state_machines/insurance_decline_transition
    """
    home, case, svc, contract = setup_arranged_case(
        funding_type="INSURANCE_ASSIGNMENT", case_mode="AT_NEED", svc_price=100000)
    assign = attach_assignment(contract["id"], 100000)

    declined = validate_success(api.decline_insurance_assignment(assign["id"], TRUST))
    assert declined["status"] == "DECLINED"
    contract_after = validate_success(api.get_contract(contract["id"], TRUST))
    assert contract_after["funded_amount_cents"] == 0


def test_case_bubbles_ready_when_both_permits_issued(api):
    """PRD §3.7: "if this issuance results in both a DEATH_CERTIFICATE and a
    BURIAL_TRANSIT permit being ISSUED for the case while the case's
    interment_status is still NOT_READY, the case's interment_status advances to
    READY and the case's version increments."

    Design: Corner/state_machines/case_ready_bubbles_up_when_both_permits_issued
    """
    home = create_funeral_home()
    case = create_case(home["id"], case_mode="AT_NEED",
                       date_of_death="2026-06-01T00:00:00.000Z")
    dc = apply_permit(case["id"], "DEATH_CERTIFICATE")
    issue_permit(dc["id"], "DC-1")
    bt = apply_permit(case["id"], "BURIAL_TRANSIT")

    bt_issued = validate_success(api.issue_permit(bt["id"], {"reference_number": "BT-1"}, REGISTRAR))
    assert bt_issued["status"] == "ISSUED"

    case_after = validate_success(api.get_case(case["id"], ARRANGER))
    assert case_after["interment_status"] == "READY"
