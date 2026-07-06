"""Initial states, invalid/idempotent transitions, terminal lockdown, and
clock-driven side effects (PRD §3).

Queue B / Corner — section `state_machines`.
"""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_employer, create_pending_pwd, create_issued_pwd, create_perm_case,
    create_lca, certify_lca, create_certified_lca, get_employer_version,
    create_beneficiary, create_i140_petition, submit_i140_petition,
    setup_submitted_h1b_petition, issue_rfe, approve_h1b_petition, set_clock,
    make_employer_agent_headers,
)

DOL = TEST_USERS["dol_analyst_headers"]
USCIS = TEST_USERS["uscis_officer_headers"]


def test_pwd_starts_in_pending(api):
    """PRD §3.2: "A freshly created determination is in `PENDING`."

    Design: Corner/state_machines/pwd_starts_in_pending
    """
    emp = create_employer()
    pwd = create_pending_pwd(emp["id"])
    assert pwd["status"] == "PENDING"


def test_perm_case_starts_in_draft(api):
    """PRD §3.3: "An `EmployerAgent` creates one in `DRAFT` by supplying the
    `employer_id`, the `pwd_id` of the governing determination, the certified
    `job_title`, and the `offered_wage_cents`".

    Design: Corner/state_machines/perm_case_starts_in_draft
    """
    emp = create_employer()
    pwd = create_issued_pwd(emp["id"])
    pc = create_perm_case(emp["id"], pwd["id"])
    assert pc["status"] == "DRAFT"


def test_pwd_issue_from_issued_rejected_idempotency(api):
    """PRD §3.2: "Issuance is allowed only from `PENDING` (otherwise
    `ERR_INVALID_STATE`)".

    Design: Corner/state_machines/pwd_issue_from_issued_rejected_idempotency
    """
    emp = create_employer()
    pwd = create_issued_pwd(emp["id"])
    # OCC passes (current version) so the state check is the sole failure.
    version = get_employer_version(emp["id"])
    res = api.transition_pwd(pwd["id"], {"to_status": "ISSUED", "expected_employer_version": version}, DOL)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    fetched = validate_success(api.get_pwd(pwd["id"], DOL), 200)
    assert fetched["status"] == "ISSUED"


def test_perm_case_file_from_draft_invalid_transition(api):
    """PRD §3.3: "Filing moves the case from `QUIET_PERIOD` to `FILED`, and is
    permitted only from `QUIET_PERIOD`."
    PRD §4: "the server resolves it against the state machine described in
    Section 3 (rejecting an undefined transition with `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/perm_case_file_from_draft_invalid_transition
    """
    emp = create_employer()
    pwd = create_issued_pwd(emp["id"])
    pc = create_perm_case(emp["id"], pwd["id"])
    hdr = make_employer_agent_headers(emp["id"])
    res = api.transition_perm_case(pc["id"], {"to_status": "FILED"}, hdr)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    assert validate_success(api.get_perm_case(pc["id"], hdr), 200)["status"] == "DRAFT"


def test_lca_transition_from_withdrawn_terminal_locked(api):
    """PRD §3.4: "The employer's agent may later withdraw a certified application,
    moving it from `CERTIFIED` to `WITHDRAWN` (defined only from `CERTIFIED`)."
    PRD §3.4: "Both `WITHDRAWN` and `EXPIRED` are terminal."

    Design: Corner/state_machines/lca_transition_from_withdrawn_terminal_locked
    """
    emp = create_employer()
    lca = create_certified_lca(emp["id"])
    hdr = make_employer_agent_headers(emp["id"])
    lca = validate_success(api.transition_lca(lca["id"], {"to_status": "WITHDRAWN"}, hdr), 200)
    assert lca["status"] == "WITHDRAWN"
    res = api.transition_lca(lca["id"], {"to_status": "WITHDRAWN"}, hdr)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_i140_transition_from_denied_terminal_locked(api):
    """PRD §3.7: "A `USCISOfficer` adjudicates from `SUBMITTED`, approving to
    `APPROVED` or denying to `DENIED`, each defined only from `SUBMITTED`."
    PRD §3.7: "`APPROVED` and `DENIED` are terminal."

    Design: Corner/state_machines/i140_transition_from_denied_terminal_locked
    """
    emp = create_employer()
    ben = create_beneficiary(emp["id"])
    i140 = create_i140_petition(emp["id"], ben["id"], category="EB1")
    i140 = submit_i140_petition(emp["id"], i140["id"])
    i140 = validate_success(api.transition_i140_petition(i140["id"], {"to_status": "DENIED"}, USCIS), 200)
    assert i140["status"] == "DENIED"
    res = api.transition_i140_petition(i140["id"], {"to_status": "APPROVED"}, USCIS)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_pwd_auto_expires_when_clock_passes_validity_end(api):
    """PRD §3.2: "Expiry happens on its own when the logical clock advances past a
    determination's `validity_end`, moving an `ISSUED` determination to `EXPIRED`."

    Design: Corner/state_machines/pwd_auto_expires_when_clock_passes_validity_end
    """
    emp = create_employer()
    pwd = create_issued_pwd(emp["id"], validity_end="2026-06-01T00:00:00Z")
    set_clock("2026-07-01T00:00:00Z")
    fetched = validate_success(api.get_pwd(pwd["id"], DOL), 200)
    assert fetched["status"] == "EXPIRED"


def test_lca_auto_expires_when_clock_passes_validity_end(api):
    """PRD §3.4: "expiry is system-driven: when the logical clock advances past a
    certified application's `validity_end`, it moves from `CERTIFIED` to `EXPIRED`."

    Design: Corner/state_machines/lca_auto_expires_when_clock_passes_validity_end
    """
    emp = create_employer()
    lca = create_certified_lca(emp["id"], validity_end="2026-06-01T00:00:00Z")
    set_clock("2026-07-01T00:00:00Z")
    fetched = validate_success(api.get_lca(lca["id"], DOL), 200)
    assert fetched["status"] == "EXPIRED"


def test_rfe_issued_sets_status_and_due_date_87_days_out(api):
    """PRD §3.6: "Issuing an RFE sets `rfe_status` to `ISSUED`, stamps
    `rfe_issued_date` to the current clock, and computes `rfe_due_date` as
    `rfe_issued_date` plus 87 days."

    Design: Corner/state_machines/rfe_issued_sets_status_and_due_date_87_days_out
    """
    ctx = setup_submitted_h1b_petition()
    pet = issue_rfe(ctx["petition"]["id"])
    assert pet["status"] == "RFE_ISSUED"
    assert pet["rfe_status"] == "ISSUED"
    # RFE issued at the default clock 2026-05-01 + 87 days = 2026-07-27.
    assert pet["rfe_due_date"] == "2026-07-27T00:00:00Z"


def test_rfe_past_due_auto_denies_petition_on_clock_advance(api):
    """PRD §3.6: "when the logical clock advances past `rfe_due_date` while the
    petition is still `RFE_ISSUED`, the system denies it, moving it from
    `RFE_ISSUED` to `DENIED`."

    Design: Corner/state_machines/rfe_past_due_auto_denies_petition_on_clock_advance
    """
    ctx = setup_submitted_h1b_petition()
    issue_rfe(ctx["petition"]["id"])  # due 2026-07-27
    set_clock("2026-07-28T00:00:00Z")
    fetched = validate_success(api.get_h1b_petition(ctx["petition"]["id"], USCIS), 200)
    assert fetched["status"] == "DENIED"


def test_petition_approved_recomputes_beneficiary_active_status(api):
    """PRD §3.6: "A successful approval recomputes the beneficiary's
    `current_status_code` and `status_valid_until`."
    PRD §3.6: "otherwise it is `H1B_ACTIVE` when the logical clock is strictly
    before `status_valid_until`, and `H1B_EXPIRED` when the clock is at or after
    `status_valid_until`."

    Design: Corner/state_machines/petition_approved_recomputes_beneficiary_active_status
    """
    ctx = setup_submitted_h1b_petition(
        petition_overrides={"employment_start": "2026-06-01T00:00:00Z",
                            "employment_end": "2029-06-01T00:00:00Z"})
    approve_h1b_petition(ctx["petition"]["id"])
    set_clock("2026-07-01T00:00:00Z")
    ben = validate_success(api.get_beneficiary(ctx["beneficiary"]["id"], USCIS), 200)
    assert ben["status_valid_until"] == "2029-06-01T00:00:00Z"
    assert ben["current_status_code"] == "H1B_ACTIVE"
