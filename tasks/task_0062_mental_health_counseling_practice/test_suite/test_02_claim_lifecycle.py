"""Claim and appointment lifecycle: revert loop, COMPLETED fork, void reversal, OCC.

Queue A (Difficulty): non_linear_state_machine, compensating_invariant.
Queue B (Corner): state_machines (claim/appointment), cross_cutting (OCC).
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_submitted_claim, adjudicate, schedule_appointment, render_sign_complete,
    TEST_USERS, ApiErrorId,
)

BILLER = TEST_USERS["biller_headers"]


def test_claim_revert_loop_denied_resubmit_adjudicate():
    """PRD §3.7: "A biller may instead deny a SUBMITTED claim, moving it to DENIED,
    and a denied claim may be resubmitted, moving it from DENIED to RESUBMITTED and
    back into the adjudication queue — the revert loop that lets a once-denied claim
    be settled."
    PRD §2.11: "Under a copay model, the cost share is the smaller of the fixed copay
    and that post-deductible remainder."

    Design: Difficulty/non_linear_state_machine/claim_revert_loop_denied_resubmit_adjudicate
    """
    ctx = setup_submitted_claim(
        clock="2026-06-04T12:00:00Z", appt_start="2026-06-04T08:00:00Z",
        cpt_code="90834", duration_minutes=45, in_network=False, rate_90834=0,
        cost_share_model="COPAY", copay_cents=2500, deductible_total_cents=0)
    claim = ctx["claim"]
    denied = get_success_data(api_client.deny_claim(
        claim["id"], {"expected_claim_version": claim["version"]}, BILLER))
    assert denied["status"] == "DENIED"
    resubmitted = get_success_data(api_client.resubmit_claim(
        claim["id"], {"expected_claim_version": denied["version"]}, BILLER))
    assert resubmitted["status"] == "RESUBMITTED"
    adjudicated = adjudicate(claim["id"], resubmitted["version"])
    assert adjudicated["status"] == "ADJUDICATED"
    assert adjudicated["patient_responsibility_cents"] == 2500
    assert adjudicated["payer_paid_cents"] == 12500


def test_claim_revert_loop_status_sequence():
    """PRD §3.7: "A biller may instead deny a SUBMITTED claim, moving it to DENIED,
    and a denied claim may be resubmitted, moving it from DENIED to RESUBMITTED and
    back into the adjudication queue — the revert loop that lets a once-denied claim
    be settled."

    Design: Difficulty/non_linear_state_machine/claim_revert_loop_denied_resubmit_adjudicate
    """
    ctx = setup_submitted_claim(
        clock="2026-06-21T12:00:00Z", appt_start="2026-06-21T08:00:00Z",
        cpt_code="90834", duration_minutes=45, in_network=False, rate_90834=0,
        cost_share_model="COPAY", copay_cents=2500, deductible_total_cents=0)
    claim = ctx["claim"]
    assert claim["status"] == "SUBMITTED"
    denied = get_success_data(api_client.deny_claim(
        claim["id"], {"expected_claim_version": claim["version"]}, BILLER))
    assert denied["status"] == "DENIED"
    resubmitted = get_success_data(api_client.resubmit_claim(
        claim["id"], {"expected_claim_version": denied["version"]}, BILLER))
    assert resubmitted["status"] == "RESUBMITTED"
    final = adjudicate(claim["id"], resubmitted["version"])
    assert final["status"] == "ADJUDICATED"


def test_completed_appointment_forks_to_written_off_or_claimed():
    """PRD §3.7: "From COMPLETED, an insurance-path session forks toward billing while
    a self-pay session forks toward write-off."
    PRD §3.7: "Separately, a biller may write off a completed self-pay session, moving
    it from COMPLETED to WRITTEN_OFF and zeroing its patient_charge_cents."
    PRD §3.7: "Opening a claim creates it in SUBMITTED status, copies the
    insurance_policy_id and cpt_code from the appointment, stamps the
    billed_charge_cents at the standard procedure rate, advances the appointment from
    COMPLETED to CLAIMED, and increments the appointment's version by one."

    Design: Difficulty/non_linear_state_machine/appointment_branch_completed_to_claimed_or_writtenoff
    """
    from test_helpers import create_independent_therapist, create_payer_contract, \
        create_patient, create_policy, set_clock
    set_clock("2026-06-05T12:00:00Z")
    therapist = create_independent_therapist()
    contract = create_payer_contract(in_network=True, rate_90834=13000)
    patient = create_patient(income=30000, household=2)
    policy = create_policy(patient["id"], contract["id"], cost_share_model="COPAY",
                           copay_cents=2000, deductible_total_cents=0)
    # SELF_PAY branch -> write-off
    sp_appt = schedule_appointment(
        therapist["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-06-05T08:00:00Z", payment_path="SELF_PAY")
    sp_completed = render_sign_complete(sp_appt["id"], therapist["id"])
    written_off = get_success_data(api_client.write_off_appointment(sp_completed["id"], BILLER))
    assert written_off["status"] == "WRITTEN_OFF"
    assert written_off["patient_charge_cents"] == 0
    # INSURANCE branch -> claimed
    ins_appt = schedule_appointment(
        therapist["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-06-05T10:00:00Z", payment_path="INSURANCE",
        insurance_policy_id=policy["id"])
    ins_completed = render_sign_complete(ins_appt["id"], therapist["id"])
    claim = get_success_data(api_client.create_claim(
        {"appointment_id": ins_completed["id"],
         "expected_appointment_version": ins_completed["version"]}, BILLER))
    assert claim["status"] == "SUBMITTED"
    appt_after = get_success_data(api_client.get_appointment(ins_completed["id"], BILLER))
    assert appt_after["status"] == "CLAIMED"


def test_self_pay_write_off_branch_zeroes_charge():
    """PRD §3.7: "Separately, a biller may write off a completed self-pay session,
    moving it from COMPLETED to WRITTEN_OFF and zeroing its patient_charge_cents."

    Design: Difficulty/non_linear_state_machine/appointment_branch_completed_to_claimed_or_writtenoff
    """
    from test_helpers import create_independent_therapist, create_patient, set_clock
    set_clock("2026-06-22T12:00:00Z")
    therapist = create_independent_therapist()
    patient = create_patient(income=30000, household=2)  # 0.20 multiplier
    appt = schedule_appointment(
        therapist["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-06-22T08:00:00Z", payment_path="SELF_PAY")
    completed = render_sign_complete(appt["id"], therapist["id"])
    # Self-pay charge stamped at render (15000 * 0.20 = 3000), then zeroed on write-off.
    assert completed["patient_charge_cents"] == 3000
    written = get_success_data(api_client.write_off_appointment(completed["id"], BILLER))
    assert written["status"] == "WRITTEN_OFF"
    assert written["patient_charge_cents"] == 0


def test_void_claim_restores_deductible_met_to_pre_adjudication():
    """PRD §3.7: "An adjudicated claim may be voided, moving it to VOID; voiding is a
    compensating reversal that decreases the policy's deductible_met_cents by exactly
    the amount this claim had applied (restoring it to its pre-adjudication value),
    resets the linked appointment's patient_charge_cents to 0, and reverts that
    appointment from CLAIMED back to COMPLETED."

    Design: Difficulty/compensating_invariant/void_claim_restores_deductible_met
    """
    # First in-network 90791 claim (contracted 18000) drives deductible_met to 18000.
    ctx = setup_submitted_claim(
        clock="2026-06-14T12:00:00Z", appt_start="2026-06-14T03:00:00Z",
        cpt_code="90791", duration_minutes=60, in_network=True, rate_90791=18000,
        rate_90834=13000, cost_share_model="COINSURANCE", copay_cents=None,
        coinsurance_rate=0.20, deductible_total_cents=20000)
    therapist, patient, policy = ctx["therapist"], ctx["patient"], ctx["policy"]
    first = adjudicate(ctx["claim"]["id"], ctx["claim"]["version"])
    assert first["deductible_applied_cents"] == 18000  # met now 18000

    # A second 90834 claim is adjudicated then voided; the void must restore
    # deductible_met to its pre-adjudication value (18000), the conserved quantity.
    appt2 = schedule_appointment(
        therapist["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-06-14T08:00:00Z", payment_path="INSURANCE",
        insurance_policy_id=policy["id"])
    completed2 = render_sign_complete(appt2["id"], therapist["id"])
    claim2 = get_success_data(api_client.create_claim(
        {"appointment_id": completed2["id"],
         "expected_appointment_version": completed2["version"]}, BILLER))
    pol_before = get_success_data(api_client.get_insurance_policy(policy["id"], BILLER))
    met_before = pol_before["deductible_met_cents"]
    adj2 = adjudicate(claim2["id"], claim2["version"])
    voided = get_success_data(api_client.void_claim(
        claim2["id"], {"expected_claim_version": adj2["version"]}, BILLER))
    assert voided["status"] == "VOID"
    pol_after = get_success_data(api_client.get_insurance_policy(policy["id"], BILLER))
    assert pol_after["deductible_met_cents"] == met_before
    appt_after = get_success_data(api_client.get_appointment(completed2["id"], BILLER))
    assert appt_after["patient_charge_cents"] == 0
    assert appt_after["status"] == "COMPLETED"
    assert pol_after["deductible_met_cents"] == 18000


def test_void_claim_reverts_appointment_and_zeroes_deductible():
    """PRD §3.7: "voiding is a compensating reversal that decreases the policy's
    deductible_met_cents by exactly the amount this claim had applied (restoring it to
    its pre-adjudication value), resets the linked appointment's patient_charge_cents to
    0, and reverts that appointment from CLAIMED back to COMPLETED."

    Design: Difficulty/compensating_invariant/void_claim_restores_deductible_met
    """
    # Single claim on a fresh policy (deductible 5000): adjudicate then void must
    # restore deductible_met from 5000 back to 0 (its pre-adjudication value).
    ctx = setup_submitted_claim(
        clock="2026-06-23T12:00:00Z", appt_start="2026-06-23T08:00:00Z",
        cpt_code="90834", duration_minutes=45, in_network=True, rate_90834=13000,
        cost_share_model="COINSURANCE", copay_cents=None, coinsurance_rate=0.20,
        deductible_total_cents=5000)
    policy, appt, claim = ctx["policy"], ctx["appointment"], ctx["claim"]
    adj = adjudicate(claim["id"], claim["version"])
    assert adj["deductible_applied_cents"] == 5000
    voided = get_success_data(api_client.void_claim(
        claim["id"], {"expected_claim_version": adj["version"]}, BILLER))
    assert voided["status"] == "VOID"
    pol = get_success_data(api_client.get_insurance_policy(policy["id"], BILLER))
    assert pol["deductible_met_cents"] == 0
    appt_after = get_success_data(api_client.get_appointment(appt["id"], BILLER))
    assert appt_after["status"] == "COMPLETED"
    assert appt_after["patient_charge_cents"] == 0


def test_newly_created_claim_starts_submitted_with_billed_charge():
    """PRD §3.7: "Opening a claim creates it in SUBMITTED status, copies the
    insurance_policy_id and cpt_code from the appointment, stamps the
    billed_charge_cents at the standard procedure rate, advances the appointment from
    COMPLETED to CLAIMED, and increments the appointment's version by one."

    Design: Corner/state_machines/newly_created_claim_starts_submitted
    """
    ctx = setup_submitted_claim(
        clock="2026-07-02T12:00:00Z", appt_start="2026-07-02T08:00:00Z",
        cpt_code="90834", duration_minutes=45, in_network=False, rate_90834=0,
        cost_share_model="COPAY", copay_cents=2500, deductible_total_cents=0)
    claim = ctx["claim"]
    assert claim["status"] == "SUBMITTED"
    assert claim["billed_charge_cents"] == 15000


def test_void_terminal_claim_cannot_adjudicate_again():
    """PRD §3.7: "Each of these four claim transitions requires expected_claim_version
    to match and increments the claim's version by one; a transition requested from a
    state where it is not defined is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/void_terminal_claim_cannot_transition_again
    """
    ctx = setup_submitted_claim(
        clock="2026-07-03T12:00:00Z", appt_start="2026-07-03T08:00:00Z",
        cpt_code="90834", duration_minutes=45, in_network=False, rate_90834=0,
        cost_share_model="COPAY", copay_cents=2500, deductible_total_cents=0)
    claim = ctx["claim"]
    adj = adjudicate(claim["id"], claim["version"])
    voided = get_success_data(api_client.void_claim(
        claim["id"], {"expected_claim_version": adj["version"]}, BILLER))
    resp = api_client.adjudicate_claim(
        claim["id"], {"expected_claim_version": voided["version"]}, BILLER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_occ_stale_claim_version_on_adjudicate_rejected():
    """PRD §2.9: "For a claim-lifecycle transition, the request must carry
    expected_claim_version matching the target claim's current version; if another
    writer has advanced that claim's version since the client last read it, the
    transition is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_claim_version_on_adjudicate
    """
    ctx = setup_submitted_claim(
        clock="2026-07-15T12:00:00Z", appt_start="2026-07-15T08:00:00Z",
        cpt_code="90834", duration_minutes=45, in_network=False, rate_90834=0,
        cost_share_model="COPAY", copay_cents=2500, deductible_total_cents=0)
    claim = ctx["claim"]
    resp = api_client.adjudicate_claim(
        claim["id"], {"expected_claim_version": claim["version"] - 1}, BILLER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_occ_correct_claim_version_adjudicates_successfully():
    """PRD §2.9: "For a claim-lifecycle transition, the request must carry
    expected_claim_version matching the target claim's current version"
    PRD §2.9: "Each successful guarded write increments the parent record's version by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_claim_version_adjudicates_successfully
    """
    ctx = setup_submitted_claim(
        clock="2026-07-18T12:00:00Z", appt_start="2026-07-18T08:00:00Z",
        cpt_code="90834", duration_minutes=45, in_network=False, rate_90834=0,
        cost_share_model="COPAY", copay_cents=2500, deductible_total_cents=0)
    claim = ctx["claim"]
    adj = adjudicate(claim["id"], claim["version"])
    assert adj["status"] == "ADJUDICATED"
    assert adj["patient_responsibility_cents"] == 2500


def test_cancel_already_cancelled_appointment_returns_invalid_state():
    """PRD §3.7: "a transition requested from a state where it is not defined is
    rejected with ERR_INVALID_STATE."
    PRD §3.5: "A scheduled session may be cancelled by front-desk or a director,
    moving it to CANCELLED."

    Design: Corner/state_machines/cancel_already_cancelled_appointment_returns_invalid_state
    """
    from test_helpers import create_associate_therapist, create_patient, FD
    therapist = create_associate_therapist(full_name="Dr Cx")
    patient = create_patient()
    appt = schedule_appointment(
        therapist["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-07-01T08:00:00Z", payment_path="SELF_PAY")
    get_success_data(api_client.cancel_appointment(appt["id"], FD))
    resp = api_client.cancel_appointment(appt["id"], FD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_complete_appointment_twice_returns_invalid_state():
    """PRD §3.6: "Completing a rendered session advances it from RENDERED to COMPLETED
    and is performed by the rendering clinician."
    PRD §3.7: "a transition requested from a state where it is not defined is rejected
    with ERR_INVALID_STATE."

    Design: Corner/state_machines/complete_appointment_twice_returns_invalid_state
    """
    from test_helpers import create_independent_therapist, create_patient, \
        schedule_appointment, render_sign_complete, set_clock, make_therapist_headers
    set_clock("2026-07-05T12:00:00Z")
    therapist = create_independent_therapist()
    patient = create_patient()
    appt = schedule_appointment(
        therapist["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-07-05T08:00:00Z", payment_path="SELF_PAY")
    render_sign_complete(appt["id"], therapist["id"])
    resp = api_client.complete_appointment(
        appt["id"], make_therapist_headers(therapist["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
