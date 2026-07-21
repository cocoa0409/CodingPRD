"""Transitive cascades (payment clear, contract rescind) and compensating invariants."""
from test_helpers import (
    TEST_USERS,
    validate_success, get_success_data,
    create_payment_payload,
    make_public_adjuster_headers, make_client_headers,
    assert_policy_invariants, assert_disbursement_waterfall,
)
from test_helpers.fixtures import (
    setup_settled_claim, setup_settled_claim_with_draft_supplement,
    setup_paid_claim_with_disbursement, set_clock, _first_disbursement_id,
)

FIRM = TEST_USERS["firm_principal_headers"]
CARRIER = TEST_USERS["carrier_headers"]


# ------------------------------------- payment clear depth-3 cascade (difficulty)
def _settled_with_received_payment(api, amount=8_000_000):
    ctx = setup_settled_claim(api, offer_cents=amount)
    pay = get_success_data(api.create_payment(create_payment_payload(ctx["clm"], amount), CARRIER))["id"]
    ctx["pay"] = pay
    return ctx


def test_payment_clear_cascades_paid_completed_disbursed(api):
    """PRD §3.7: "a `Disbursement` is created in `PENDING` to split this payment, and if the
    claim's cumulative `amount_recovered_cents` has reached or exceeded its
    `settlement_amount_cents`, the claim advances from `SETTLED` to the terminal `PAID`. When
    the claim reaches `PAID`, the final fee is recomputed, the contract advances to
    `COMPLETED`, and the policy's booked exposure is reconciled to the amount actually
    recovered."

    Design: Difficulty/transitive_cascade/payment_clear_cascade_paid_completed_disbursed
    """
    ctx = _settled_with_received_payment(api, amount=8_000_000)
    validate_success(api.clear_payment(ctx["pay"], CARRIER))
    claim = get_success_data(api.get_claim(ctx["clm"], FIRM))
    assert claim["status"] == "PAID"
    assert claim["final_fee_cents"] == 800_000
    contract = get_success_data(api.get_contract(ctx["con"], FIRM))
    assert contract["status"] == "COMPLETED"
    dis = get_success_data(api.get_disbursement(_first_disbursement_id(api, ctx["clm"]), FIRM))
    assert dis["status"] == "PENDING"
    assert dis["client_cents"] == 7_200_000


def test_payment_clear_records_recovery_and_reconciles_booked_exposure(api):
    """PRD §3.7: "Clearing stamps `received_at`, moves the payment to `CLEARED`, adds its
    `amount_cents` to the claim's `amount_recovered_cents`, and triggers a cascade".

    Design: Difficulty/transitive_cascade/payment_clear_cascade_paid_completed_disbursed
    """
    ctx = _settled_with_received_payment(api, amount=8_000_000)
    validate_success(api.clear_payment(ctx["pay"], CARRIER))
    claim = get_success_data(api.get_claim(ctx["clm"], FIRM))
    assert claim["amount_recovered_cents"] == 8_000_000
    pol = get_success_data(api.get_policy(ctx["pol"], FIRM))
    assert pol["committed_cents"] == 8_000_000
    assert_policy_invariants(pol)


# --------------------------------- contract rescind depth-3 cascade (difficulty)
def test_contract_rescind_cascades_claim_withdrawn_supplement_voided(api):
    """PRD §3.2: "every non-terminal claim on the contract — any claim in `FILED`,
    `NEGOTIATING`, `OFFER_RECEIVED`, `IN_APPRAISAL`, or `SETTLED` — is driven to `WITHDRAWN`,
    and any settlement that had been committed for a `SETTLED` claim is released from the
    policy's `committed_cents` with `remaining_limit_cents` recomputed".
    PRD §3.2: "Second, as each such claim is withdrawn, its own supplements in `DRAFT` or
    `SUBMITTED` are driven to the terminal `VOIDED`."

    Design: Difficulty/transitive_cascade/contract_rescind_cascade_claim_withdrawn_supplement_voided
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    ctx = setup_settled_claim_with_draft_supplement(api, offer_cents=8_000_000, amount_cents=1_000_000)
    validate_success(api.rescind_contract(ctx["con"], FIRM))
    contract = get_success_data(api.get_contract(ctx["con"], FIRM))
    assert contract["status"] == "RESCINDED"
    claim = get_success_data(api.get_claim(ctx["clm"], FIRM))
    assert claim["status"] == "WITHDRAWN"
    supplement = get_success_data(api.get_supplement(ctx["sup"], FIRM))
    assert supplement["status"] == "VOIDED"
    pol = get_success_data(api.get_policy(ctx["pol"], FIRM))
    assert pol["committed_cents"] == 0
    assert pol["remaining_limit_cents"] == 100_000_000


def test_contract_rescind_releases_forward_exposure(api):
    """PRD §3.2: "while the policy's `forward_exposure_cents` is recomputed as those claims
    leave the open set."

    Design: Difficulty/transitive_cascade/contract_rescind_cascade_claim_withdrawn_supplement_voided
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    ctx = setup_settled_claim_with_draft_supplement(api, offer_cents=8_000_000, amount_cents=1_000_000)
    validate_success(api.rescind_contract(ctx["con"], FIRM))
    pol = get_success_data(api.get_policy(ctx["pol"], FIRM))
    assert pol["forward_exposure_cents"] == 0   # withdrawn claim left the open set
    assert_policy_invariants(pol)


# ---------------------------------- cash conservation compensating (difficulty)
def _partial_paid_then_disbursed(api):
    """Claim settled at 8000000; partial payment 5000000 cleared (claim stays SETTLED)."""
    ctx = setup_settled_claim(api, offer_cents=8_000_000)
    pay = get_success_data(api.create_payment(create_payment_payload(ctx["clm"], 5_000_000), CARRIER))["id"]
    validate_success(api.clear_payment(pay, CARRIER))
    ctx["pay"] = pay
    ctx["dis"] = _first_disbursement_id(api, ctx["clm"])
    return ctx


def test_cash_conservation_reverse_voids_disbursement_and_restores_recovery(api):
    """PRD §3.7: "Reversal moves the payment from `CLEARED` to the terminal `REVERSED`,
    subtracts its `amount_cents` back out of the claim's `amount_recovered_cents`, drives the
    splitting disbursement to the terminal `VOIDED`, and restores the contract's
    `advance_recouped_cents` by that disbursement's `advance_recoup_cents`."

    Design: Difficulty/compensating_invariant/cash_conservation_recovery_equals_fee_plus_advance_plus_client
    """
    ctx = _partial_paid_then_disbursed(api)
    dis_before = get_success_data(api.get_disbursement(ctx["dis"], FIRM))
    assert dis_before["fee_cents"] == 500_000
    assert dis_before["advance_recoup_cents"] == 0
    assert dis_before["client_cents"] == 4_500_000
    validate_success(api.reverse_payment(ctx["pay"], CARRIER))
    dis = get_success_data(api.get_disbursement(ctx["dis"], FIRM))
    assert dis["status"] == "VOIDED"
    claim = get_success_data(api.get_claim(ctx["clm"], FIRM))
    assert claim["amount_recovered_cents"] == 0


def test_cash_conservation_disbursement_split_sums_to_gross(api):
    """PRD §3.7: "The gross amount, `gross_cents`, equals the cleared payment's
    `amount_cents`."
    PRD §3.7: "The client's share, `client_cents`, is `gross_cents` minus `fee_cents` minus
    `advance_recoup_cents`."

    Design: Difficulty/compensating_invariant/cash_conservation_recovery_equals_fee_plus_advance_plus_client
    """
    ctx = _partial_paid_then_disbursed(api)
    dis = get_success_data(api.get_disbursement(ctx["dis"], FIRM))
    assert dis["gross_cents"] == 5_000_000
    assert_disbursement_waterfall(dis)
    claim = get_success_data(api.get_claim(ctx["clm"], FIRM))
    assert claim["status"] == "SETTLED"  # partial payment below settlement
    assert claim["amount_recovered_cents"] == 5_000_000


# ------------------------- coverage-limit conservation settle then rescind (difficulty)
def test_coverage_limit_conservation_settle_then_rescind(api):
    """PRD §3.2: "and any settlement that had been committed for a `SETTLED` claim is
    released from the policy's `committed_cents` with `remaining_limit_cents` recomputed".

    Design: Difficulty/compensating_invariant/coverage_limit_conservation_settle_then_rescind
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    ctx = setup_settled_claim(api, offer_cents=8_000_000)
    validate_success(api.rescind_contract(ctx["con"], FIRM))
    claim = get_success_data(api.get_claim(ctx["clm"], FIRM))
    assert claim["status"] == "WITHDRAWN"
    pol = get_success_data(api.get_policy(ctx["pol"], FIRM))
    assert pol["committed_cents"] == 0
    assert pol["remaining_limit_cents"] == 100_000_000


def test_coverage_limit_invariant_holds_after_settlement(api):
    """PRD §2.9: "The policy's `remaining_limit_cents` is `coverage_limit_cents` minus
    `committed_cents`, and the invariant `coverage_limit_cents == remaining_limit_cents +
    committed_cents` holds at all times."

    Design: Difficulty/compensating_invariant/coverage_limit_conservation_settle_then_rescind
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    ctx = setup_settled_claim(api, offer_cents=8_000_000)
    pol = get_success_data(api.get_policy(ctx["pol"], FIRM))
    assert pol["committed_cents"] == 8_000_000
    assert pol["remaining_limit_cents"] == 92_000_000
    assert_policy_invariants(pol)
