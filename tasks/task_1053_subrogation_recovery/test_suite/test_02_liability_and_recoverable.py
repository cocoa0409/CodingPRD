"""Liability assessment: the provisional three-way-min recoverable, the provisional
vs. final divergence, statute-at-referral, and invalid re-assessment."""
from test_helpers import (
    validate_success, validate_error,
    assess_liability_payload,
    setup_referred_claim, setup_assessed_claim, setup_settled_claim,
)
from test_helpers import TEST_USERS

SPECIALIST = TEST_USERS["specialist_headers"]
READER = TEST_USERS["reader_headers"]

# Claim shaped so the three ceilings differ: base_exposure = 2.5M + 0.5M = 3.0M,
# liability_share @80% of 4.0M = 3.2M, policy limit = 5.0M -> provisional = 3.0M.
PROV_CLAIM = {"paid_loss_cents": 2_500_000, "deductible_cents": 500_000, "total_damages_cents": 4_000_000}


def test_provisional_recoverable_is_three_way_min(api):
    """PRD §3.2: "That provisional figure is the **smallest** of three ceilings: the
    liability share, the adverse policy limit, and the carrier's out-of-pocket exposure."
    PRD §3.2: "The out-of-pocket exposure — the base exposure — is `paid_loss_cents`
    plus `deductible_cents`."

    Design: Difficulty/dual_variant_calc/claim_recoverable_provisional_vs_final
    """
    ctx = setup_assessed_claim(api, liability_pct=80, policy_limit_cents=5_000_000,
                               claim_overrides=dict(PROV_CLAIM))
    assert ctx["claim"]["provisional_recoverable_cents"] == 3_000_000


def test_final_recoverable_diverges_from_provisional(api):
    """PRD §3.5: "Acceptance drives the claim to `SETTLED` and sets the claim's
    `settled_amount_cents` to the settlement's `settled_amount_cents` — this accepted
    amount is the claim's final recoverable figure."

    Design: Difficulty/dual_variant_calc/claim_recoverable_provisional_vs_final
    """
    ctx = setup_settled_claim(api, settled_amount_cents=2_700_000, liability_pct=80,
                              policy_limit_cents=5_000_000, claim_overrides=dict(PROV_CLAIM))
    claim = ctx["claim"]
    assert claim["settled_amount_cents"] == 2_700_000
    assert claim["provisional_recoverable_cents"] == 3_000_000
    assert claim["provisional_recoverable_cents"] != claim["settled_amount_cents"], (
        "provisional estimate and accepted settlement must diverge for this claim"
    )


def test_recoverable_policy_limit_binds_as_minimum(api):
    """PRD §3.2: "That provisional figure is the **smallest** of three ceilings: the
    liability share, the adverse policy limit, and the carrier's out-of-pocket exposure."

    Design: Difficulty/combinatorial_formula/recoverable_three_way_min_policy_binds
    """
    # base_exposure = 3.0M, liability_share @80% = 3.2M, policy_limit = 2.8M (binds).
    ctx = setup_assessed_claim(api, liability_pct=80, policy_limit_cents=2_800_000,
                               claim_overrides=dict(PROV_CLAIM))
    assert ctx["claim"]["provisional_recoverable_cents"] == 2_800_000


def test_recoverable_equals_policy_limit_below_other_ceilings(api):
    """PRD §3.2: "The policy ceiling is the adverse party's `policy_limit_cents`. The
    provisional recoverable is whichever of these three is least."

    Design: Difficulty/combinatorial_formula/recoverable_three_way_min_policy_binds
    """
    ctx = setup_assessed_claim(api, liability_pct=80, policy_limit_cents=2_800_000,
                               claim_overrides=dict(PROV_CLAIM))
    ap = validate_success(api.get_adverse_party(ctx["adverse_party"]["id"], READER))
    prov = ctx["claim"]["provisional_recoverable_cents"]
    base_exposure = ctx["claim"]["paid_loss_cents"] + ctx["claim"]["deductible_cents"]
    assert prov == ap["policy_limit_cents"], "provisional must equal the binding policy limit"
    assert prov < base_exposure, "policy limit binds strictly below the out-of-pocket ceiling"


def test_assess_liability_on_past_statute_claim_rejected(api):
    """PRD §3.2: "If a claim is referred with a `statute_deadline` already in the past,
    it is simply born expired for action purposes — such a claim was never swept and
    any action on it fails the statute check (`ERR_STATUTE_EXPIRED`) rather than being
    auto-transitioned."

    Design: Corner/errors/assess_liability_past_statute_returns_statute_expired
    """
    ctx = setup_referred_claim(api, claim_overrides={
        "loss_date": "2024-01-01T00:00:00Z", "statute_deadline": "2026-06-01T00:00:00Z",
    })
    resp = api.assess_liability(ctx["claim"]["id"], assess_liability_payload(80), SPECIALIST)
    validate_error(resp, "ERR_STATUTE_EXPIRED", 409)


def test_assess_liability_twice_rejected(api):
    """PRD §3.2: "Liability assessment is the specialist's first substantive step and
    moves the claim from `REFERRED` to `LIABILITY_ASSESSED`."
    PRD §2.11: "(7) that the target resource is in a state permitting the requested
    transition (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/assess_liability_twice_returns_invalid_state
    """
    ctx = setup_assessed_claim(api, liability_pct=80)
    resp = api.assess_liability(ctx["claim"]["id"], assess_liability_payload(60), SPECIALIST)
    validate_error(resp, "ERR_INVALID_STATE", 409)
