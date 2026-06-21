"""State-machine behaviour: invalid transitions, terminal lockdown, initial
state, valid-transition loops, cross-entity guards, side effects, plus the two
non-linear revision-cycle difficulty instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    get_success_data,
    ApiErrorId,
    factories as F,
    fixtures as FX,
    make_licensee_headers,
)

ADMIN = FX.ADMIN
ADMIN_INITIATOR = FX.ADMIN_INITIATOR
AUDITOR = FX.AUDITOR


# ===========================================================================
# Corner/state_machines
# ===========================================================================
def test_accredit_already_accredited_provider_returns_invalid_state(api):
    """PRD §3.1: "Accreditation is a deliberate act: accrediting an `APPLIED`
    provider requires the request to supply an `accredited_until` instant that is
    strictly later than the current clock."
    PRD §2.10: "then whether the target is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/accredit_already_accredited_provider_returns_invalid_state
    """
    board = FX.create_board(with_requirements=False)
    provider = FX.create_accredited_provider(board["id"])

    resp = api.accredit_provider(
        provider["id"], F.accredit_provider_payload("2031-01-01T00:00:00Z"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_revoke_from_revoked_terminal_returns_invalid_state(api):
    """PRD §3.1: "A provider may be revoked from either `ACCREDITED` or
    `SUSPENDED`, advancing it to the terminal `REVOKED` state."
    PRD §2.10: "then whether the target is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/revoke_from_revoked_terminal_returns_invalid_state
    """
    board = FX.create_board(with_requirements=False)
    provider = FX.create_accredited_provider(board["id"])
    get_success_data(api.revoke_provider(provider["id"], ADMIN))

    resp = api.revoke_provider(provider["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_new_provider_starts_in_applied(api):
    """PRD §3.1: "A newly registered provider begins in `APPLIED`."

    Design: Corner/state_machines/new_provider_starts_in_applied
    """
    board = FX.create_board(with_requirements=False)
    data = validate_success(
        api.create_provider(F.create_provider_payload(board["id"]), ADMIN), 201)
    assert data["status"] == "APPLIED"


def test_provider_suspend_reinstate_loop_returns_to_accredited(api):
    """PRD §3.1: "An accredited provider may be suspended (moving from
    `ACCREDITED` to `SUSPENDED`); suspension freezes new verifications but does
    not deactivate courses and is reversible. A suspended provider may be
    reinstated back to `ACCREDITED`."

    Design: Corner/state_machines/provider_suspend_reinstate_loop_returns_to_accredited
    """
    board = FX.create_board(with_requirements=False)
    provider = FX.create_accredited_provider(board["id"])
    get_success_data(api.suspend_provider(provider["id"], ADMIN))

    data = validate_success(api.reinstate_provider(provider["id"], ADMIN), 200)
    assert data["status"] == "ACCREDITED"


def test_reciprocity_deny_then_approve_returns_invalid_state(api):
    """PRD §3.7: "A `BoardAdmin` may instead deny a requested grant, moving it to
    the terminal `DENIED` state with no effect on any cycle."
    PRD §2.10: "then whether the target is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/reciprocity_deny_then_approve_returns_invalid_state
    """
    base = FX.setup_board_provider_licensee_cycle(
        with_requirements=False, with_provider=False)
    licensee, cycle = base["licensee"], base["cycle"]
    grant = FX.request_reciprocity(licensee["id"], cycle["id"], "GENERAL", 2.0, "NY")
    get_success_data(api.deny_reciprocity_grant(grant["id"], ADMIN))

    resp = api.approve_reciprocity_grant(grant["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_resubmit_pending_completion_returns_invalid_state(api):
    """PRD §3.4: "A rejected completion is not terminal: the owning `Licensee`
    may resubmit it, moving it from `REJECTED` back to `PENDING_VERIFICATION`."
    PRD §2.10: "then whether the target is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/resubmit_pending_completion_returns_invalid_state
    """
    base = FX.setup_board_provider_licensee_cycle(with_requirements=False)
    provider, licensee, cycle = base["provider"], base["licensee"], base["cycle"]
    course = FX.create_course(provider["id"], "ETHICS", 4.0)
    comp = FX.log_completion(licensee["id"], course["id"], cycle["id"])

    # Still PENDING_VERIFICATION — resubmit is not defined from this state.
    resp = api.resubmit_completion(comp["id"], make_licensee_headers(licensee["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_second_open_audit_on_cycle_returns_audit_already_open(api):
    """PRD §3.9: "The audit may be initiated only when the cycle is `OPEN` or
    `REQUIREMENTS_MET` and when no other audit for that cycle is currently in a
    non-terminal state; a second concurrent audit is rejected with
    `ERR_AUDIT_ALREADY_OPEN`."
    PRD §2.10: "then whether the target is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`). Endpoint-specific business
    checks — ... single-open-audit ... — are evaluated after those foundational
    checks." Initiating the first audit moves the cycle into `AUDIT_HOLD`, so a
    second initiation always targets a cycle that is no longer `OPEN`/
    `REQUIREMENTS_MET`. The single-open business check (`ERR_AUDIT_ALREADY_OPEN`)
    and the foundational state check (`ERR_INVALID_STATE`) are coupled here and
    §2.10 orders the state check first; PRD does not uniquely determine which of
    the two §409 errors surfaces, so either is acceptable.

    Design: Corner/state_machines/second_open_audit_on_cycle_returns_audit_already_open
    """
    met = FX.setup_requirements_met_cycle()
    cycle = met["cycle"]
    FX.initiate_audit(cycle["id"], ADMIN_INITIATOR)

    resp = api.create_audit(F.create_audit_payload(cycle["id"]), ADMIN_INITIATOR)
    assert resp.status_code == 409
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_AUDIT_ALREADY_OPEN.value, ApiErrorId.ERR_INVALID_STATE.value],
    )


def test_audit_decide_attestation_mismatch_forces_failed(api):
    """PRD §3.9: "The audit fails — moving to the terminal `FAILED` — when the
    `decision` is to fail, or when the latest attestation's `attested_hours` does
    not equal the cycle's `final_earned_hours` even on a pass decision."
    PRD §3.9: "on a fail, the cycle moves from `AUDIT_HOLD` to the terminal
    `LAPSED` and its `carryover_out_hours` is reset to 0."

    Design: Corner/state_machines/audit_decide_attestation_mismatch_forces_failed
    """
    # final_earned_hours == 30.0 but the licensee attests 29.0 (mismatch).
    setup = FX.setup_audit_under_review(attested_hours=29.0)
    audit, cycle = setup["audit"], setup["cycle"]

    data = validate_success(
        api.decide_audit(audit["id"], F.decide_audit_payload("PASS"), AUDITOR), 200)
    assert data["status"] == "FAILED", "attested 29.0 != final 30.0 forces FAIL"

    cyc = get_success_data(api.get_renewal_cycle(cycle["id"], ADMIN))
    assert cyc["status"] == "LAPSED", "cycle bubbles AUDIT_HOLD -> LAPSED on fail"


# ===========================================================================
# Difficulty/non_linear_state_machine  (>=2 tests per instance)
# ===========================================================================
def test_completion_reject_resubmit_verify_cycle_reaches_verified(api):
    """PRD §3.4: "A rejected completion is not terminal: the owning `Licensee`
    may resubmit it, moving it from `REJECTED` back to `PENDING_VERIFICATION`
    (permitted only while the cycle is `OPEN` or `REQUIREMENTS_MET`)."
    PRD §3.4: "The loop `REJECTED → PENDING_VERIFICATION → VERIFIED` is therefore
    a revision cycle."

    Design: Difficulty/non_linear_state_machine/completion_reject_resubmit_verify_cycle
    """
    base = FX.setup_board_provider_licensee_cycle(with_requirements=False)
    provider, licensee, cycle = base["provider"], base["licensee"], base["cycle"]
    course = FX.create_course(provider["id"], "ETHICS", 4.0)
    lic = make_licensee_headers(licensee["id"])
    comp = FX.log_completion(licensee["id"], course["id"], cycle["id"])

    get_success_data(api.reject_completion(comp["id"], ADMIN, {"reason": "bad scan"}))
    get_success_data(api.resubmit_completion(comp["id"], lic))

    data = validate_success(api.verify_completion(comp["id"], ADMIN), 200)
    assert data["status"] == "VERIFIED", (
        "REJECTED->PENDING_VERIFICATION->VERIFIED revision loop ends VERIFIED")


def test_completion_revision_loop_intermediate_states(api):
    """PRD §3.4: "A `BoardAdmin` may instead reject a pending completion.
    Rejection moves it from `PENDING_VERIFICATION` to `REJECTED`."
    PRD §3.4: "A rejected completion is not terminal: the owning `Licensee` may
    resubmit it, moving it from `REJECTED` back to `PENDING_VERIFICATION`."

    Design: Difficulty/non_linear_state_machine/completion_reject_resubmit_verify_cycle
    """
    base = FX.setup_board_provider_licensee_cycle(with_requirements=False)
    provider, licensee, cycle = base["provider"], base["licensee"], base["cycle"]
    course = FX.create_course(provider["id"], "ETHICS", 4.0)
    lic = make_licensee_headers(licensee["id"])
    comp = FX.log_completion(licensee["id"], course["id"], cycle["id"])

    rejected = get_success_data(api.reject_completion(comp["id"], ADMIN, {"reason": "x"}))
    assert rejected["status"] == "REJECTED"

    resubmitted = get_success_data(api.resubmit_completion(comp["id"], lic))
    assert resubmitted["status"] == "PENDING_VERIFICATION", (
        "the entity returns to a state it previously left")


def test_audit_under_review_request_attestation_loop_then_pass(api):
    """PRD §3.9: "A `BoardAdmin` (or, on a later revision pass, an `Auditor`)
    requests attestation, moving the audit to `ATTESTATION_PENDING` from either
    `INITIATED` or `UNDER_REVIEW`."
    PRD §3.9: "The audit passes — moving to the terminal `PASSED` — when the
    `decision` is to pass and the latest attestation's `attested_hours` equals
    the cycle's `final_earned_hours`."

    Design: Difficulty/non_linear_state_machine/audit_under_review_request_attestation_loop
    """
    setup = FX.setup_audit_under_review(attested_hours=30.0)  # final == 30.0
    audit, licensee = setup["audit"], setup["licensee"]
    lic = make_licensee_headers(licensee["id"])

    # Auditor asks for a fresh attestation: UNDER_REVIEW -> ATTESTATION_PENDING.
    get_success_data(api.request_attestation(audit["id"], AUDITOR))
    # Licensee attests again: ATTESTATION_PENDING -> UNDER_REVIEW.
    get_success_data(api.submit_attestation(
        audit["id"], F.submit_attestation_payload(30.0, statement="second attestation"), lic))

    data = validate_success(
        api.decide_audit(audit["id"], F.decide_audit_payload("PASS"), AUDITOR), 200)
    assert data["status"] == "PASSED", (
        "UNDER_REVIEW->ATTESTATION_PENDING->UNDER_REVIEW loop then PASS decision")


def test_audit_request_attestation_returns_to_attestation_pending(api):
    """PRD §3.9: "A `BoardAdmin` (or, on a later revision pass, an `Auditor`)
    requests attestation, moving the audit to `ATTESTATION_PENDING` from either
    `INITIATED` or `UNDER_REVIEW`."

    Design: Difficulty/non_linear_state_machine/audit_under_review_request_attestation_loop
    """
    setup = FX.setup_audit_under_review(attested_hours=30.0)
    audit = setup["audit"]
    assert audit["status"] == "UNDER_REVIEW"

    data = validate_success(api.request_attestation(audit["id"], AUDITOR), 200)
    assert data["status"] == "ATTESTATION_PENDING", (
        "auditor revision request moves UNDER_REVIEW back to ATTESTATION_PENDING")
