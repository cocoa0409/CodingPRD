"""Composite setup helpers.

Each test runs against a freshly-restarted, empty server, so every helper builds
its preconditions from scratch using only PRD-declared endpoints. Helpers return a
context dict of the live entities they created; consumers refresh sub-resources via
GET as needed. All setup calls use get_success_data() so a broken precondition
surfaces as a clear "Setup step failed" rather than a confusing assertion.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated
from .api_client import api_client
from .test_users import TEST_USERS, make_carrier_user_headers
from .factories import (
    create_carrier_payload, create_adverse_party_payload, create_claim_payload,
    assess_liability_payload, create_demand_payload, record_response_payload,
    create_arbitration_payload, propose_settlement_payload,
    create_recovery_payment_payload, create_commission_statement_payload,
)

SPECIALIST = TEST_USERS["specialist_headers"]
MANAGER = TEST_USERS["manager_headers"]
MANAGER2 = TEST_USERS["manager2_headers"]
FINANCE = TEST_USERS["finance_headers"]
READER = TEST_USERS["reader_headers"]
SYSTEM = TEST_USERS["system_headers"]


# --- Tier 1: single-entity builders -----------------------------------------

def create_carrier(api, *, commission_basis="NET", commission_rate_bps=2500, name="Acme Mutual", naic_code="12345"):
    payload = create_carrier_payload(
        name=name, naic_code=naic_code,
        commission_rate_bps=commission_rate_bps, commission_basis=commission_basis,
    )
    return get_success_data(api.create_carrier(payload, MANAGER))


def suspend_carrier(api, carrier_id):
    return get_success_data(api.suspend_carrier(carrier_id, MANAGER))


def create_adverse_party(api, *, is_arbitration_eligible=True, policy_limit_cents=5_000_000, name="Adverse Party"):
    payload = create_adverse_party_payload(
        name=name, is_arbitration_eligible=is_arbitration_eligible, policy_limit_cents=policy_limit_cents,
    )
    return get_success_data(api.create_adverse_party(payload, SPECIALIST))


def refer_claim(api, carrier_id, adverse_party_id, **overrides):
    payload = create_claim_payload(carrier_id, adverse_party_id, **overrides)
    return get_success_data(api.create_claim(payload, make_carrier_user_headers(carrier_id)))


# --- Tier 2: claim state-progression ----------------------------------------

def setup_referred_claim(api, *, commission_basis="NET", commission_rate_bps=2500,
                         is_arbitration_eligible=True, policy_limit_cents=5_000_000,
                         claim_overrides=None):
    """Active carrier + adverse party + a REFERRED claim owned by that carrier."""
    carrier = create_carrier(api, commission_basis=commission_basis, commission_rate_bps=commission_rate_bps)
    ap = create_adverse_party(api, is_arbitration_eligible=is_arbitration_eligible, policy_limit_cents=policy_limit_cents)
    claim = refer_claim(api, carrier["id"], ap["id"], **(claim_overrides or {}))
    return {"carrier": carrier, "adverse_party": ap, "claim": claim}


def setup_assessed_claim(api, *, liability_pct=80, **kw):
    """Claim advanced to LIABILITY_ASSESSED with provisional_recoverable_cents computed."""
    ctx = setup_referred_claim(api, **kw)
    ctx["claim"] = get_success_data(
        api.assess_liability(ctx["claim"]["id"], assess_liability_payload(liability_pct), SPECIALIST)
    )
    return ctx


def setup_demand_issued_claim(api, *, liability_pct=80, amount_demanded_cents=3_000_000, **kw):
    """Claim in DEMAND_ISSUED with one ISSUED demand."""
    ctx = setup_assessed_claim(api, liability_pct=liability_pct, **kw)
    ctx["demand"] = get_success_data(
        api.create_demand(ctx["claim"]["id"], create_demand_payload(amount_demanded_cents), SPECIALIST)
    )
    ctx["claim"] = get_success_data(api.get_claim(ctx["claim"]["id"], READER))
    return ctx


def setup_disputed_demand_claim(api, **kw):
    """Claim in DEMAND_ISSUED whose demand has been recorded DISPUTED."""
    ctx = setup_demand_issued_claim(api, **kw)
    ctx["demand"] = get_success_data(
        api.record_response(ctx["demand"]["id"], record_response_payload("DISPUTED"), SPECIALIST)
    )
    return ctx


def setup_filed_arbitration(api, *, forum="AF", **kw):
    """Claim in ARBITRATION with a FILED arbitration (adverse party eligible + demand DISPUTED)."""
    ctx = setup_disputed_demand_claim(api, **kw)
    ctx["arbitration"] = get_success_data(
        api.create_arbitration(ctx["claim"]["id"], create_arbitration_payload(forum), SPECIALIST)
    )
    ctx["claim"] = get_success_data(api.get_claim(ctx["claim"]["id"], READER))
    return ctx


# --- Tier 3: settlement lifecycle -------------------------------------------

def propose_settlement(api, claim_id, settled_amount_cents, *, proposer=SPECIALIST):
    """Read the current claim version, then propose a settlement under OCC."""
    claim = get_success_data(api.get_claim(claim_id, READER))
    payload = propose_settlement_payload(settled_amount_cents, claim["version"])
    return get_success_data(api.propose_settlement(claim_id, payload, proposer))


def setup_proposed_settlement(api, *, settled_amount_cents=1_000_000, **kw):
    """Claim in DEMAND_ISSUED with one PROPOSED settlement (proposer = spec-1)."""
    ctx = setup_demand_issued_claim(api, **kw)
    ctx["settlement"] = propose_settlement(api, ctx["claim"]["id"], settled_amount_cents)
    ctx["claim"] = get_success_data(api.get_claim(ctx["claim"]["id"], READER))
    return ctx


def setup_settled_claim(api, *, settled_amount_cents=3_000_000, from_arbitration=False, **kw):
    """Claim driven to SETTLED via propose -> approve -> accept.

    When from_arbitration=True the claim passes through ARBITRATION before acceptance,
    leaving a live FILED arbitration to be rendered moot by acceptance.
    """
    if from_arbitration:
        ctx = setup_filed_arbitration(api, **kw)
    else:
        ctx = setup_demand_issued_claim(api, **kw)
    settlement = propose_settlement(api, ctx["claim"]["id"], settled_amount_cents)
    get_success_data(api.approve_settlement(settlement["id"], MANAGER2))
    get_success_data(api.accept_settlement(settlement["id"], make_carrier_user_headers(ctx["carrier"]["id"])))
    ctx["settlement"] = get_success_data(api.get_settlement(settlement["id"], READER))
    ctx["claim"] = get_success_data(api.get_claim(ctx["claim"]["id"], READER))
    return ctx


# --- Tier 4: recovery-payment / recovered lifecycle -------------------------

def record_payment(api, claim_id, amount_cents):
    return get_success_data(
        api.create_recovery_payment(claim_id, create_recovery_payment_payload(amount_cents), FINANCE)
    )


def clear_payment(api, payment_id):
    return get_success_data(api.clear_payment(payment_id, FINANCE))


def setup_cleared_payment(api, *, settled_amount_cents=3_000_000, payment_amount_cents=None, **kw):
    """Claim SETTLED, then one recovery payment recorded and CLEARED (waterfall run)."""
    ctx = setup_settled_claim(api, settled_amount_cents=settled_amount_cents, **kw)
    amt = settled_amount_cents if payment_amount_cents is None else payment_amount_cents
    payment = record_payment(api, ctx["claim"]["id"], amt)
    clear_payment(api, payment["id"])
    ctx["payment"] = get_success_data(api.get_recovery_payment(payment["id"], READER))
    ctx["claim"] = get_success_data(api.get_claim(ctx["claim"]["id"], READER))
    return ctx


def get_only_reimbursement(api, claim_id):
    data, _meta = validate_paginated(api.list_deductible_reimbursements(READER, params={"claim_id": claim_id}))
    assert len(data) == 1, f"Expected exactly one reimbursement for claim, got {len(data)}"
    return data[0]


def setup_recovered_with_disbursed_reimbursement(api, *, settled_amount_cents=3_000_000, **kw):
    """Full lifecycle to RECOVERED with the deductible reimbursement DISBURSED."""
    ctx = setup_cleared_payment(api, settled_amount_cents=settled_amount_cents, **kw)
    reimb = get_only_reimbursement(api, ctx["claim"]["id"])
    get_success_data(api.disburse_reimbursement(reimb["id"], FINANCE))
    ctx["reimbursement"] = get_success_data(api.get_deductible_reimbursement(reimb["id"], READER))
    ctx["claim"] = get_success_data(api.get_claim(ctx["claim"]["id"], READER))
    return ctx


# --- Tier 5: multi-claim commission-statement scenarios ---------------------

def _recover_one_claim(api, carrier_id, adverse_party_id, *, claim_reference,
                       paid_loss_cents, deductible_cents, settled_amount_cents, liability_pct=100):
    claim = refer_claim(
        api, carrier_id, adverse_party_id, claim_reference=claim_reference,
        paid_loss_cents=paid_loss_cents, deductible_cents=deductible_cents,
    )
    get_success_data(api.assess_liability(claim["id"], assess_liability_payload(liability_pct), SPECIALIST))
    get_success_data(api.create_demand(claim["id"], create_demand_payload(settled_amount_cents), SPECIALIST))
    settlement = propose_settlement(api, claim["id"], settled_amount_cents)
    get_success_data(api.approve_settlement(settlement["id"], MANAGER2))
    get_success_data(api.accept_settlement(settlement["id"], make_carrier_user_headers(carrier_id)))
    payment = record_payment(api, claim["id"], settled_amount_cents)
    clear_payment(api, payment["id"])
    return get_success_data(api.get_claim(claim["id"], READER))


def setup_two_recovered_claims_same_carrier(api, *, commission_basis="NET", commission_rate_bps=2500,
                                            paid_loss_cents=1_000_033, deductible_cents=0,
                                            settled_amount_cents=1_000_033):
    """One NET/GROSS carrier with two RECOVERED claims — for statement sweep + totals."""
    carrier = create_carrier(api, commission_basis=commission_basis, commission_rate_bps=commission_rate_bps)
    ap = create_adverse_party(api)
    claims = []
    for ref in ("CLM-R1", "CLM-R2"):
        claims.append(_recover_one_claim(
            api, carrier["id"], ap["id"], claim_reference=ref,
            paid_loss_cents=paid_loss_cents, deductible_cents=deductible_cents,
            settled_amount_cents=settled_amount_cents,
        ))
    return {"carrier": carrier, "adverse_party": ap, "claims": claims}


def create_commission_statement(api, carrier_id, *, period_label="2026-Q3"):
    return get_success_data(
        api.create_commission_statement(carrier_id, create_commission_statement_payload(period_label), FINANCE)
    )


# --- Shared-adverse-party arbitration docket --------------------------------

def _drive_claim_to_filed_arbitration(api, carrier_id, adverse_party_id, claim_reference):
    claim = refer_claim(api, carrier_id, adverse_party_id, claim_reference=claim_reference)
    get_success_data(api.assess_liability(claim["id"], assess_liability_payload(80), SPECIALIST))
    demand = get_success_data(api.create_demand(claim["id"], create_demand_payload(3_000_000), SPECIALIST))
    get_success_data(api.record_response(demand["id"], record_response_payload("DISPUTED"), SPECIALIST))
    arb = get_success_data(api.create_arbitration(claim["id"], create_arbitration_payload("AF"), SPECIALIST))
    return claim, arb


def setup_two_filed_arbitrations_same_adverse(api, *, policy_limit_cents=9_000_000):
    """Two claims sharing one eligible adverse party, each with a FILED arbitration —
    for hearing-docket buffer-overlap tests."""
    carrier = create_carrier(api)
    ap = create_adverse_party(api, policy_limit_cents=policy_limit_cents)
    claim1, arb1 = _drive_claim_to_filed_arbitration(api, carrier["id"], ap["id"], "CLM-14A")
    claim2, arb2 = _drive_claim_to_filed_arbitration(api, carrier["id"], ap["id"], "CLM-14B")
    return {"carrier": carrier, "adverse_party": ap,
            "claim1": claim1, "arbitration1": arb1,
            "claim2": claim2, "arbitration2": arb2}
