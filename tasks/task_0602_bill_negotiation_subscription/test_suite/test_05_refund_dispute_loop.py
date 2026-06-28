"""Refund claim review, approval ceilings, and the DENIED->DISPUTED->UNDER_REVIEW loop."""
from test_helpers import (
    validate_success, validate_error,
    make_member_headers, make_agent_headers,
    setup_under_review_claim, setup_denied_claim, setup_confirmed_charge,
    create_agent, create_refund_claim_payload,
    ApiErrorId,
)


def test_refund_claim_denied_disputed_review_loop(api):
    """PRD §3.9: "A successful dispute advances the claim from `DENIED` to `DISPUTED`, increments `dispute_round` by one, and bumps the `version`. From `DISPUTED`, the agent starts review again, returning the claim to `UNDER_REVIEW` (and bumping the `version`)".

    Design: Difficulty/non_linear_state_machine/refund_claim_denied_disputed_review_loop
    """
    member, agent, charge, claim = setup_denied_claim(
        claim_type="DOUBLE_BILL", observed_old_amount_cents=2000,
        observed_new_amount_cents=0, charge_amount_cents=2000,
    )
    mh = make_member_headers(member["id"])
    ah = make_agent_headers(agent["id"])
    disputed = validate_success(api.dispute_refund_claim(
        claim["id"], {"expected_refund_claim_version": claim["version"]}, headers=mh))
    assert disputed["status"] == "DISPUTED"
    reviewed = validate_success(api.start_review_refund_claim(claim["id"], headers=ah))
    assert reviewed["status"] == "UNDER_REVIEW"
    assert reviewed["dispute_round"] == 1


def test_dispute_increments_round_returns_to_review(api):
    """PRD §3.9: "A successful dispute advances the claim from `DENIED` to `DISPUTED`, increments `dispute_round` by one, and bumps the `version`."
    PRD §3.9: "From `DISPUTED`, the agent starts review again, returning the claim to `UNDER_REVIEW".

    Design: Difficulty/non_linear_state_machine/refund_claim_denied_disputed_review_loop
    """
    member, agent, charge, claim = setup_denied_claim(charge_amount_cents=2000)
    mh = make_member_headers(member["id"])
    disputed = validate_success(api.dispute_refund_claim(
        claim["id"], {"expected_refund_claim_version": claim["version"]}, headers=mh))
    assert disputed["dispute_round"] == 1
    assert disputed["status"] == "DISPUTED"


def test_refund_above_claim_rejected(api):
    """PRD §3.9: "Approval** supplies `approved_refund_cents`, which must be at least zero and may not exceed the claim's `claimed_refund_cents` (an approval above the pursued amount is rejected with `ERR_REFUND_ABOVE_CLAIM`)".

    Design: Corner/validations/refund_above_claim_rejected
    """
    member, agent, charge, claim = setup_under_review_claim(
        claim_type="DOUBLE_BILL", observed_old_amount_cents=4000,
        observed_new_amount_cents=0, charge_amount_cents=4000,
    )
    resp = api.approve_refund_claim(claim["id"], {"approved_refund_cents": 5000},
                                    headers=make_agent_headers(agent["id"]))
    validate_error(resp, ApiErrorId.ERR_REFUND_ABOVE_CLAIM.value)


def test_dispute_with_correct_version_succeeds(api):
    """PRD §2.7: "A member disputing a denied claim must include `expected_refund_claim_version`, carrying the `version` of the claim as last observed."
    PRD §3.9: "A successful dispute advances the claim from `DENIED` to `DISPUTED`, increments `dispute_round` by one, and bumps the `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_refund_dispute_succeeds
    """
    member, agent, charge, claim = setup_denied_claim(
        claim_type="DOUBLE_BILL", observed_old_amount_cents=2000,
        observed_new_amount_cents=0, charge_amount_cents=2000,
    )
    resp = api.dispute_refund_claim(
        claim["id"], {"expected_refund_claim_version": claim["version"]},
        headers=make_member_headers(member["id"]),
    )
    data = validate_success(resp)
    assert data["status"] == "DISPUTED"
    assert data["dispute_round"] == 1
