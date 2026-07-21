"""Dual-variant fee, policy exposure dual view, disbursement waterfall, final-fee rounding."""
from test_helpers import (
    TEST_USERS,
    validate_success, get_success_data,
    create_claim_payload, create_payment_payload,
    make_public_adjuster_headers,
    assert_disbursement_waterfall, assert_policy_invariants,
)
from test_helpers.fixtures import (
    setup_active_contract, setup_settled_claim, setup_paid_claim_with_disbursement,
    new_draft_claim, file_claim,
)

FIRM = TEST_USERS["firm_principal_headers"]
CARRIER = TEST_USERS["carrier_headers"]


# ------------------------------------------- dual-variant fee (difficulty)
def test_fee_provisional_estimate_vs_final_recovery_diverge(api):
    """PRD §3.4: "The provisional fee, `provisional_fee_cents`, is the effective fee rate
    multiplied by the claim's `pa_acv_estimate_cents`, rounded half up to whole cents,
    where the effective rate is the smaller of the contract's `fee_pct` and its
    `statutory_cap_pct`."
    PRD §3.7: "the final fee, `final_fee_cents`, is computed over actual recovery: for each
    `CLEARED` payment on the claim, the effective rate times that payment's `amount_cents`
    is rounded half up to whole cents, and those per-payment rounded fees are then summed."

    Design: Difficulty/dual_variant_calc/fee_provisional_estimate_vs_final_recovery_diverge
    """
    # rcv 10000000, dep 0.20 -> ACV 8000000; offer/payment 7000000 -> PAID
    ctx = setup_paid_claim_with_disbursement(api, offer_cents=7_000_000)
    claim = get_success_data(api.get_claim(ctx["clm"], FIRM))
    assert claim["status"] == "PAID"
    assert claim["provisional_fee_cents"] == 800_000   # 0.10 * 8000000
    assert claim["final_fee_cents"] == 700_000         # 0.10 * 7000000
    assert claim["provisional_fee_cents"] != claim["final_fee_cents"]


def test_provisional_fee_set_on_settlement_before_any_payment(api):
    """PRD §3.4: "The provisional fee, `provisional_fee_cents`, is the effective fee rate
    multiplied by the claim's `pa_acv_estimate_cents`, rounded half up to whole cents,
    where the effective rate is the smaller of the contract's `fee_pct` and its
    `statutory_cap_pct`."

    Design: Difficulty/dual_variant_calc/fee_provisional_estimate_vs_final_recovery_diverge
    """
    ctx = setup_settled_claim(api, offer_cents=7_000_000)
    claim = get_success_data(api.get_claim(ctx["clm"], FIRM))
    assert claim["status"] == "SETTLED"
    assert claim["provisional_fee_cents"] == 800_000   # computed on ACV estimate
    assert claim["final_fee_cents"] == 0               # no CLEARED payment yet


# ------------------------------------- policy exposure forward vs booked (difficulty)
def _two_claim_policy(api):
    """One policy, claim A filed (open, ACV 8000000), claim B settled at 5000000 (ACV 6000000)."""
    ctx = setup_active_contract(api)
    pa = make_public_adjuster_headers(ctx["adj"])
    clm_a = new_draft_claim(api, ctx["pol"], ctx["con"], ctx["adj"],
                            pa_rcv_estimate_cents=10_000_000, depreciation_pct=0.20)
    file_claim(api, clm_a, ctx["adj"])
    clm_b = new_draft_claim(api, ctx["pol"], ctx["con"], ctx["adj"], peril_type="HAIL",
                            date_of_loss="2026-06-20T00:00:00Z",
                            pa_rcv_estimate_cents=7_500_000, depreciation_pct=0.20)
    file_claim(api, clm_b, ctx["adj"])
    validate_success(api.record_offer(clm_b, {"offer_cents": 5_000_000}, CARRIER))
    validate_success(api.accept_settlement(clm_b, pa))
    return ctx


def test_policy_exposure_forward_vs_booked_diverge(api):
    """PRD §2.9: "The forward-looking figure, `forward_exposure_cents`, is the sum of
    `pa_acv_estimate_cents` over every claim on the policy whose `status` is neither `PAID`
    nor `WITHDRAWN` — a reserve view across all still-open claims."
    PRD §2.9: "The booked figure, `committed_cents`, counts only realized commitments: the
    sum of `settlement_amount_cents` over claims whose `status` is `SETTLED` or `PAID`, plus
    the sum of `amount_cents` over supplements on the policy whose `status` is `APPROVED`."

    Design: Difficulty/dual_variant_calc/policy_exposure_forward_vs_booked_diverge
    """
    ctx = _two_claim_policy(api)
    pol = get_success_data(api.get_policy(ctx["pol"], FIRM))
    assert pol["forward_exposure_cents"] == 14_000_000   # 8000000 + 6000000
    assert pol["committed_cents"] == 5_000_000
    assert pol["remaining_limit_cents"] == 95_000_000
    assert pol["forward_exposure_cents"] != pol["committed_cents"]


def test_policy_exposure_invariant_holds_across_dual_view(api):
    """PRD §2.9: "The policy's `remaining_limit_cents` is `coverage_limit_cents` minus
    `committed_cents`, and the invariant `coverage_limit_cents == remaining_limit_cents +
    committed_cents` holds at all times."

    Design: Difficulty/dual_variant_calc/policy_exposure_forward_vs_booked_diverge
    """
    ctx = _two_claim_policy(api)
    pol = get_success_data(api.get_policy(ctx["pol"], FIRM))
    assert_policy_invariants(pol)
    assert pol["coverage_limit_cents"] == 100_000_000


# ---------------------------------------- disbursement waterfall (difficulty)
def test_disbursement_waterfall_fee_then_advance_recoup_then_client(api):
    """PRD §3.7: "The advance recoupment, `advance_recoup_cents`, is the smaller of two
    quantities: the gross net of fee (that is, `gross_cents` minus `fee_cents`), and the
    contract's outstanding advance (that is, `prior_advance_cents` minus
    `advance_recouped_cents` at the moment of the split). The client's share, `client_cents`,
    is `gross_cents` minus `fee_cents` minus `advance_recoup_cents`."

    Design: Difficulty/combinatorial_formula/disbursement_waterfall_fee_then_advance_recoup_then_client
    """
    ctx = setup_paid_claim_with_disbursement(api, offer_cents=8_000_000, prior_advance_cents=500_000)
    dis = get_success_data(api.get_disbursement(ctx["dis"], FIRM))
    assert dis["gross_cents"] == 8_000_000
    assert dis["fee_cents"] == 800_000                 # 0.10 * 8000000
    assert dis["advance_recoup_cents"] == 500_000      # min(7200000, 500000)
    assert dis["client_cents"] == 6_700_000            # 8000000 - 800000 - 500000
    assert_disbursement_waterfall(dis)


def test_disbursement_waterfall_no_advance_gives_client_gross_net_of_fee(api):
    """PRD §3.7: "The firm's fee, `fee_cents`, is the effective fee rate — the smaller of
    the contract's `fee_pct` and `statutory_cap_pct` — multiplied by `gross_cents`, rounded
    half up to whole cents."
    PRD §3.7: "The client's share, `client_cents`, is `gross_cents` minus `fee_cents` minus
    `advance_recoup_cents`."

    Design: Difficulty/combinatorial_formula/disbursement_waterfall_fee_then_advance_recoup_then_client
    """
    ctx = setup_paid_claim_with_disbursement(api, offer_cents=8_000_000, prior_advance_cents=0)
    dis = get_success_data(api.get_disbursement(ctx["dis"], FIRM))
    assert dis["fee_cents"] == 800_000
    assert dis["advance_recoup_cents"] == 0            # no outstanding advance
    assert dis["client_cents"] == 7_200_000            # 8000000 - 800000 - 0
    assert_disbursement_waterfall(dis)


# --------------------------------- final-fee per-payment rounding (difficulty)
def _settled_claim_for_rounding(api):
    """Claim settled at 24690 via rcv 30000000/dep 0.20 (ACV 24000000), offer 24690."""
    ctx = setup_active_contract(api)
    pa = make_public_adjuster_headers(ctx["adj"])
    clm = new_draft_claim(api, ctx["pol"], ctx["con"], ctx["adj"], peril_type="WATER",
                          pa_rcv_estimate_cents=30_000_000, depreciation_pct=0.20)
    file_claim(api, clm, ctx["adj"])
    validate_success(api.record_offer(clm, {"offer_cents": 24_690}, CARRIER))
    validate_success(api.accept_settlement(clm, pa))
    ctx["clm"] = clm
    return ctx


def test_final_fee_per_payment_rounding_beats_aggregate_rounding(api):
    """PRD §3.7: "The order is fixed — each payment's fee is rounded first and the rounded
    results are summed — rather than rounding a single product of the rate and the aggregate
    of payment amounts; the two can differ by up to a cent."

    Design: Difficulty/combinatorial_formula/final_fee_per_payment_rounding_beats_aggregate_rounding
    """
    ctx = _settled_claim_for_rounding(api)
    for _ in range(2):
        pay = get_success_data(api.create_payment(create_payment_payload(ctx["clm"], 12_345), CARRIER))["id"]
        validate_success(api.clear_payment(pay, CARRIER))
    claim = get_success_data(api.get_claim(ctx["clm"], FIRM))
    assert claim["status"] == "PAID"
    assert claim["amount_recovered_cents"] == 24_690
    # round(1234.5)+round(1234.5) = 1235+1235 = 2470, not round(2469.0) = 2469
    assert claim["final_fee_cents"] == 2_470


def test_final_fee_per_payment_sum_differs_from_aggregate(api):
    """PRD §3.7: "for each `CLEARED` payment on the claim, the effective rate times that
    payment's `amount_cents` is rounded half up to whole cents, and those per-payment
    rounded fees are then summed."

    Design: Difficulty/combinatorial_formula/final_fee_per_payment_rounding_beats_aggregate_rounding
    """
    ctx = _settled_claim_for_rounding(api)
    for _ in range(2):
        pay = get_success_data(api.create_payment(create_payment_payload(ctx["clm"], 12_345), CARRIER))["id"]
        validate_success(api.clear_payment(pay, CARRIER))
    claim = get_success_data(api.get_claim(ctx["clm"], FIRM))
    aggregate_rounding = round(0.10 * 24_690)  # 2469
    assert claim["final_fee_cents"] == 2_470
    assert claim["final_fee_cents"] != aggregate_rounding
