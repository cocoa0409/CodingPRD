"""Claim adjudication and the settlement cycle: partial vs full remittance, the
deny/resubmit loop, the conserved-value invariant, and terminal lockdown.

Covers difficulty rules dual_variant_calc (claim settlement) and
non_linear_state_machine (deny/resubmit cycle), plus corner claims for the
remittance-exceeds guard and the PAID terminal-state lockdown.
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    remit_payload, TEST_USERS, ApiErrorId,
    setup_finalized_eligible_period, setup_accepted_claim_full_eligible,
)

BILL = TEST_USERS["billing_specialist_headers"]
PAYER_AGENT = TEST_USERS["payer_agent_headers"]


def test_partial_remittance_yields_partially_paid(api):
    """PRD §3.9: "if it is greater than zero but strictly less than the claimed amount,
    the claim becomes `PARTIALLY_PAID`."
    PRD §3.9: "the new reimbursed amount is the prior reimbursed amount plus the
    remittance."

    Design: Difficulty/dual_variant_calc/claim_settlement_partial_vs_full_diverges_on_claim
    """
    ctx = setup_accepted_claim_full_eligible(mrn="M-SET-1", serial_number="SN-SET-1")
    claim = ctx["claim"]
    assert claim["claimed_cents"] == 11616, "99453+99454+99457 = 11616"
    after = validate_success(api.remit_claim(claim["id"], remit_payload(5000), PAYER_AGENT), 200)
    assert after["status"] == "PARTIALLY_PAID"
    assert after["reimbursed_cents"] == 5000


def test_full_remittance_after_partial_yields_paid(api):
    """PRD §3.9: "From `PARTIALLY_PAID`, a further remittance that brings the cumulative
    reimbursed amount exactly to the claimed amount adds to `reimbursed_cents` and moves
    the claim to `PAID`."
    PRD §3.9: "If the new reimbursed amount equals the claimed amount, the claim becomes
    `PAID`."

    Design: Difficulty/dual_variant_calc/claim_settlement_partial_vs_full_diverges_on_claim
    """
    ctx = setup_accepted_claim_full_eligible(mrn="M-SET-2", serial_number="SN-SET-2")
    claim = ctx["claim"]
    validate_success(api.remit_claim(claim["id"], remit_payload(5000), PAYER_AGENT), 200)
    after = validate_success(api.remit_claim(claim["id"], remit_payload(6616), PAYER_AGENT), 200)
    assert after["status"] == "PAID"
    assert after["reimbursed_cents"] == 11616, "5000 + 6616 == claimed 11616"


def test_claim_denied_resets_period_to_finalized(api):
    """PRD §3.9: "Denying a submitted claim moves it `SUBMITTED → DENIED` and cascades the
    linked period back from `CLAIMED → FINALIZED` so it can be corrected and resubmitted."

    Design: Difficulty/non_linear_state_machine/claim_denied_then_resubmitted_cycle
    """
    ctx = setup_finalized_eligible_period(
        mrn="M-CL-1", serial_number="SN-CL-1", device_type="BP_CUFF",
        care_minutes=20, device_day_count=0)
    period_id = ctx["period"]["id"]
    claim = get_success_data(api.submit_claim(period_id, BILL))
    assert claim["claimed_cents"] == 6842, "99453 (1965) + 99457 (4877) = 6842"
    denied = validate_success(api.deny_claim(claim["id"], PAYER_AGENT), 200)
    assert denied["status"] == "DENIED"
    period = get_success_data(api.get_billing_period(period_id, BILL))
    assert period["status"] == "FINALIZED", "deny cascades period CLAIMED -> FINALIZED"


def test_denied_claim_resubmitted_returns_to_submitted(api):
    """PRD §3.9: "A denied claim may be resubmitted against a re-finalized period, moving
    it `DENIED → SUBMITTED` and resetting its `claimed_cents` to the period's current
    `finalized_total_cents` — this forms the resubmit cycle."

    Design: Difficulty/non_linear_state_machine/claim_denied_then_resubmitted_cycle
    """
    ctx = setup_finalized_eligible_period(
        mrn="M-CL-2", serial_number="SN-CL-2", device_type="BP_CUFF",
        care_minutes=20, device_day_count=0)
    period_id = ctx["period"]["id"]
    claim = get_success_data(api.submit_claim(period_id, BILL))
    validate_success(api.deny_claim(claim["id"], PAYER_AGENT), 200)
    resubmitted = validate_success(api.submit_claim(period_id, BILL), 201)
    assert resubmitted["status"] == "SUBMITTED", "resubmit moves DENIED -> SUBMITTED"
    assert resubmitted["claimed_cents"] == 6842


def test_remittance_exceeding_claim_rejected(api):
    """PRD §2.10: "a remittance that would push it above is refused with
    `ERR_REMITTANCE_EXCEEDS_CLAIM`."
    PRD §3.9: "A remittance that would push the cumulative reimbursed amount above the
    claimed amount is refused with `ERR_REMITTANCE_EXCEEDS_CLAIM`."

    Design: Corner/validations/remittance_exceeds_claim_rejected
    """
    ctx = setup_finalized_eligible_period(
        mrn="M-V6-1", serial_number="SN-V6-1", device_type="BP_CUFF",
        care_minutes=20, device_day_count=0)
    claim = get_success_data(api.submit_claim(ctx["period"]["id"], BILL))
    assert claim["claimed_cents"] == 6842
    accepted = get_success_data(api.accept_claim(claim["id"], PAYER_AGENT))
    assert accepted["status"] == "ACCEPTED"
    resp = api.remit_claim(claim["id"], remit_payload(9000), PAYER_AGENT)
    validate_error(resp, ApiErrorId.ERR_REMITTANCE_EXCEEDS_CLAIM.value)
    after = get_success_data(api.get_claim(claim["id"], PAYER_AGENT))
    assert after["reimbursed_cents"] == 0, "rejected remittance leaves reimbursed_cents unchanged"


def test_paid_claim_cannot_remit_again(api):
    """PRD §3.9: "`PAID` is terminal."
    PRD §2.5: "State-transition legality (`ERR_INVALID_STATE`) is evaluated ... when the
    target entity is not in a state from which the requested transition is defined."

    Design: Corner/state_machines/terminal_claim_paid_cannot_remit_again
    """
    ctx = setup_finalized_eligible_period(
        mrn="M-SM3-1", serial_number="SN-SM3-1", device_type="BP_CUFF",
        care_minutes=20, device_day_count=0)
    claim = get_success_data(api.submit_claim(ctx["period"]["id"], BILL))
    assert claim["claimed_cents"] == 6842
    get_success_data(api.accept_claim(claim["id"], PAYER_AGENT))
    paid = validate_success(api.remit_claim(claim["id"], remit_payload(6842), PAYER_AGENT), 200)
    assert paid["status"] == "PAID"
    resp = api.remit_claim(claim["id"], remit_payload(1), PAYER_AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
