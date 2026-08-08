"""Charge pricing (estimate vs final, nested min/max), and the two conserved-
quantity invariants (refill count, insurance deductible).

Difficulty: charge_estimate_vs_final_diverge, insurance_responsibility_nested_min_max,
refill_reverse_voids_charge_restores_deductible, refills_conservation_on_reverse,
deductible_conservation_on_charge_reverse.
Corner: charge_adjudicate_twice_returns_invalid_state.
"""
from test_helpers import (
    ApiErrorId,
    validate_success, validate_error, validate_paginated, get_success_data,
    assert_deductible_conservation, assert_refill_count_invariant,
    setup_active_prescription, add_fulfilled_refill,
    billing_admin_headers,
)

FULL_POLICY = {"deductible_cents": 25000, "coinsurance_rate": 0.20,
               "out_of_pocket_max_cents": 500000}
CAPPED_POLICY = {"deductible_cents": 5000, "coinsurance_rate": 0.20,
                 "out_of_pocket_max_cents": 7000}


def _get_policy(api, patient_id, headers):
    data, _ = validate_paginated(api.list_insurance_policies(patient_id, headers))
    return data[0]


# ---------------------------------------------------------------------------
# Estimate vs final divergence (difficulty, dual-variant calc)
# ---------------------------------------------------------------------------
def _second_charge_adjudicated(api):
    ctx = setup_active_prescription(api, billing_mode="INSURANCE", policy=FULL_POLICY,
                                    rx_overrides={"total_refills_authorized": 2,
                                                  "refill_price_cents": 20000})
    f1 = add_fulfilled_refill(api, ctx)
    f2 = add_fulfilled_refill(api, ctx)
    validate_success(api.adjudicate_charge(f1["charge_id"], billing_admin_headers()))
    charge2 = validate_success(api.adjudicate_charge(f2["charge_id"], billing_admin_headers()))
    return charge2


def test_second_charge_final_diverges_from_estimate(api):
    """PRD §3.8: "The final variant runs at adjudication and writes
    final_patient_responsibility_cents, recomputing against the policy's current
    remaining_deductible_cents and oop_accumulated_cents — which may have shrunk
    because other charges adjudicated in between — so the final amount diverges
    from the estimate once the deductible is partially consumed."

    Design: Difficulty/dual_variant_calc/charge_estimate_vs_final_diverge
    """
    charge2 = _second_charge_adjudicated(api)
    assert charge2["estimated_patient_responsibility_cents"] == 20000, \
        f"estimate should be 20000, got {charge2['estimated_patient_responsibility_cents']}"
    assert charge2["final_patient_responsibility_cents"] == 8000, \
        f"final should be 8000, got {charge2['final_patient_responsibility_cents']}"
    assert (charge2["estimated_patient_responsibility_cents"]
            != charge2["final_patient_responsibility_cents"]), \
        "estimate and final must diverge once the deductible is partially consumed"


def test_second_charge_insurance_paid_after_deductible_drawn(api):
    """PRD §3.8: "insurance paid equals the allowed amount minus the final
    responsibility."

    Design: Difficulty/dual_variant_calc/charge_estimate_vs_final_diverge
    """
    charge2 = _second_charge_adjudicated(api)
    assert charge2["insurance_paid_cents"] == 12000, \
        f"insurance_paid should be 12000, got {charge2['insurance_paid_cents']}"


# ---------------------------------------------------------------------------
# Insurance responsibility nested min/max with OOP cap binding (difficulty)
# ---------------------------------------------------------------------------
def _capped_charge_adjudicated(api):
    ctx = setup_active_prescription(api, billing_mode="INSURANCE", policy=CAPPED_POLICY,
                                    rx_overrides={"hrt_type": "COMBINED",
                                                  "total_refills_authorized": 1,
                                                  "refill_price_cents": 20000})
    f1 = add_fulfilled_refill(api, ctx)
    return validate_success(api.adjudicate_charge(f1["charge_id"], billing_admin_headers()))


def test_oop_cap_binds_final_responsibility(api):
    """PRD §3.8: "The deductible portion is the smaller of the policy's
    remaining_deductible_cents and the allowed amount. ... The coinsurance
    portion is the after-deductible amount multiplied by the policy's
    coinsurance_rate, rounded half up to whole cents. The pre-cap responsibility
    is the deductible portion plus the coinsurance portion. The out-of-pocket
    room is the policy's out_of_pocket_max_cents minus its oop_accumulated_cents.
    The final responsibility is the smaller of the pre-cap responsibility and
    that out-of-pocket room."

    Design: Difficulty/combinatorial_formula/insurance_responsibility_nested_min_max
    """
    charge = _capped_charge_adjudicated(api)
    # deductible 5000, after 15000, coinsurance 3000, pre-cap 8000, oop room 7000 -> final 7000
    assert charge["deductible_applied_cents"] == 5000, \
        f"deductible_applied should be 5000, got {charge['deductible_applied_cents']}"
    assert charge["final_patient_responsibility_cents"] == 7000, \
        f"final should be capped at 7000, got {charge['final_patient_responsibility_cents']}"


def test_capped_charge_insurance_paid(api):
    """PRD §3.8: "insurance paid equals the allowed amount minus the final
    responsibility."

    Design: Difficulty/combinatorial_formula/insurance_responsibility_nested_min_max
    """
    charge = _capped_charge_adjudicated(api)
    assert charge["insurance_paid_cents"] == 13000, \
        f"insurance_paid should be 13000, got {charge['insurance_paid_cents']}"


# ---------------------------------------------------------------------------
# Refill reverse -> charge reverse -> deductible restored (difficulty cascade)
# ---------------------------------------------------------------------------
def _insurance_prescription_with_adjudicated_charge(api):
    ctx = setup_active_prescription(api, billing_mode="INSURANCE", policy=FULL_POLICY,
                                    rx_overrides={"total_refills_authorized": 2,
                                                  "refill_price_cents": 20000})
    fulfilled = add_fulfilled_refill(api, ctx)
    validate_success(api.adjudicate_charge(fulfilled["charge_id"], billing_admin_headers()))
    return ctx, fulfilled


def test_refill_reverse_reverses_adjudicated_charge(api):
    """PRD §3.6: "if it has already been adjudicated it is reversed (ADJUDICATED
    → REVERSED), which restores the insurance policy's deductible and
    out-of-pocket accumulators as described in §3.8."

    Design: Difficulty/transitive_cascade/refill_reverse_voids_charge_restores_deductible
    """
    ctx, fulfilled = _insurance_prescription_with_adjudicated_charge(api)
    reversed_refill = validate_success(
        api.reverse_refill(fulfilled["id"], ctx["provider_headers"],
                           {"reason": "wrong medication"}))
    assert reversed_refill["status"] == "REVERSED", \
        f"expected REVERSED refill, got {reversed_refill['status']}"
    charge = get_success_data(api.get_charge(fulfilled["charge_id"], ctx["provider_headers"]))
    assert charge["status"] == "REVERSED", f"expected REVERSED charge, got {charge['status']}"


def test_refill_reverse_restores_policy_deductible(api):
    """PRD §2.11: "reversing that charge adds it back to remaining_deductible_cents
    and subtracts it from consumed_deductible_cents (net change zero)."

    Design: Difficulty/transitive_cascade/refill_reverse_voids_charge_restores_deductible
    """
    ctx, fulfilled = _insurance_prescription_with_adjudicated_charge(api)
    validate_success(api.reverse_refill(fulfilled["id"], ctx["provider_headers"],
                                        {"reason": "wrong medication"}))
    policy = _get_policy(api, ctx["patient"]["id"], ctx["provider_headers"])
    assert policy["remaining_deductible_cents"] == 25000, \
        f"remaining should restore to 25000, got {policy['remaining_deductible_cents']}"
    assert policy["consumed_deductible_cents"] == 0, \
        f"consumed should restore to 0, got {policy['consumed_deductible_cents']}"
    assert_deductible_conservation(policy)


# ---------------------------------------------------------------------------
# Deductible conservation on direct charge reverse (difficulty invariant)
# ---------------------------------------------------------------------------
def test_charge_reverse_restores_deductible_values(api):
    """PRD §3.8: "For an insured charge, reversal restores the policy in exact
    mirror image: remaining_deductible_cents increases by the previously applied
    deductible, consumed_deductible_cents decreases by the same, and
    oop_accumulated_cents decreases by the previously recorded final
    responsibility."

    Design: Difficulty/compensating_invariant/deductible_conservation_on_charge_reverse
    """
    ctx, fulfilled = _insurance_prescription_with_adjudicated_charge(api)
    reversed_charge = validate_success(
        api.reverse_charge(fulfilled["charge_id"], billing_admin_headers(),
                           {"reason": "billing error"}))
    assert reversed_charge["status"] == "REVERSED"
    policy = _get_policy(api, ctx["patient"]["id"], ctx["provider_headers"])
    assert policy["remaining_deductible_cents"] == 25000, \
        f"remaining should be 25000, got {policy['remaining_deductible_cents']}"
    assert policy["consumed_deductible_cents"] == 0, \
        f"consumed should be 0, got {policy['consumed_deductible_cents']}"


def test_deductible_conservation_invariant_holds_across_reverse(api):
    """PRD §2.11: "For any insurance policy, remaining_deductible_cents plus
    consumed_deductible_cents always equals deductible_cents."

    Design: Difficulty/compensating_invariant/deductible_conservation_on_charge_reverse
    """
    ctx, fulfilled = _insurance_prescription_with_adjudicated_charge(api)
    policy_before = _get_policy(api, ctx["patient"]["id"], ctx["provider_headers"])
    assert_deductible_conservation(policy_before)
    validate_success(api.reverse_charge(fulfilled["charge_id"], billing_admin_headers(),
                                        {"reason": "billing error"}))
    policy_after = _get_policy(api, ctx["patient"]["id"], ctx["provider_headers"])
    assert_deductible_conservation(policy_after)


# ---------------------------------------------------------------------------
# Refill-count conservation on reverse (difficulty invariant)
# ---------------------------------------------------------------------------
def test_refill_count_restored_on_reverse(api):
    """PRD §2.11: "Fulfilling a refill decrements refills_remaining by 1 as the
    refill enters FULFILLED (net change zero); reversing a fulfilled refill
    increments refills_remaining by 1 as the refill leaves FULFILLED (net change
    zero)."

    Design: Difficulty/compensating_invariant/refills_conservation_on_reverse
    """
    ctx = setup_active_prescription(api, rx_overrides={"hrt_type": "ESTROGEN_ORAL",
                                                       "total_refills_authorized": 2,
                                                       "refill_price_cents": 15000})
    fulfilled = add_fulfilled_refill(api, ctx)
    rx_before = get_success_data(api.get_prescription(ctx["prescription"]["id"],
                                                      ctx["provider_headers"]))
    assert rx_before["refills_remaining"] == 1, \
        f"expected 1 remaining before reverse, got {rx_before['refills_remaining']}"
    validate_success(api.reverse_refill(fulfilled["id"], ctx["provider_headers"],
                                        {"reason": "returned"}))
    rx_after = get_success_data(api.get_prescription(ctx["prescription"]["id"],
                                                     ctx["provider_headers"]))
    assert rx_after["refills_remaining"] == 2, \
        f"expected 2 remaining after reverse, got {rx_after['refills_remaining']}"


def test_refill_count_invariant_holds_before_and_after_reverse(api):
    """PRD §2.11: "For any prescription, refills_remaining plus the count of that
    prescription's refills currently in FULFILLED status always equals
    total_refills_authorized."

    Design: Difficulty/compensating_invariant/refills_conservation_on_reverse
    """
    ctx = setup_active_prescription(api, rx_overrides={"hrt_type": "ESTROGEN_ORAL",
                                                       "total_refills_authorized": 2,
                                                       "refill_price_cents": 15000})
    fulfilled = add_fulfilled_refill(api, ctx)
    rx_before = get_success_data(api.get_prescription(ctx["prescription"]["id"],
                                                      ctx["provider_headers"]))
    assert_refill_count_invariant(rx_before, fulfilled_count=1)
    validate_success(api.reverse_refill(fulfilled["id"], ctx["provider_headers"],
                                        {"reason": "returned"}))
    rx_after = get_success_data(api.get_prescription(ctx["prescription"]["id"],
                                                     ctx["provider_headers"]))
    assert_refill_count_invariant(rx_after, fulfilled_count=0)


# ---------------------------------------------------------------------------
# Corner: adjudicating an already-adjudicated charge is rejected (idempotency)
# ---------------------------------------------------------------------------
def test_charge_adjudicate_twice_returns_invalid_state(api):
    """PRD §3.8: "A billing operator adjudicates an ESTIMATED charge (ESTIMATED →
    ADJUDICATED), permitted only from ESTIMATED, else ERR_CHARGE_INVALID_STATE
    (409)."

    Design: Corner/state_machines/charge_adjudicate_twice_returns_invalid_state
    """
    ctx = setup_active_prescription(api, billing_mode="INSURANCE", policy=FULL_POLICY,
                                    rx_overrides={"total_refills_authorized": 2,
                                                  "refill_price_cents": 20000})
    fulfilled = add_fulfilled_refill(api, ctx)
    validate_success(api.adjudicate_charge(fulfilled["charge_id"], billing_admin_headers()))
    resp = api.adjudicate_charge(fulfilled["charge_id"], billing_admin_headers())
    validate_error(resp, ApiErrorId.ERR_CHARGE_INVALID_STATE)
    policy = _get_policy(api, ctx["patient"]["id"], ctx["provider_headers"])
    assert policy["consumed_deductible_cents"] == 20000, \
        f"deductible must not be consumed twice, got {policy['consumed_deductible_cents']}"
