"""Cancelling an order: the four-link cascade, and the frame-allowance dollars it must
restore without drift."""

from test_helpers import (
    assert_frame_benefit_conserved,
    claim_for,
    confirm_order,
    file_insurance_claim,
    lab_order_for,
    list_claims_for,
    read_claim,
    read_customer,
    read_lab_order,
    read_order,
    read_policy,
    setup_confirmed_order,
    setup_in_network_percey_order,
    start_lab_order,
    validate_success,
)
from test_helpers.fixtures import RX_POWER_EXACTLY_SIX


# ═════════════════════════════════════════════════════════════════════════════
# The depth-4 cancel chain: order → lab order → claim → policy ledger
# ═════════════════════════════════════════════════════════════════════════════

def test_cancel_moves_the_order_and_refunds_the_committed_fsa(api):
    """PRD §3.6: "The order's `fulfillment_status` becomes `CANCELLED`. Its payment dimension
    moves on its own axis: a `payment_status` of `AUTHORIZED` becomes `REFUNDED` and the
    customer's `fsa_balance_cents` is credited back by exactly the order's
    `fsa_applied_cents`, while a `payment_status` of `UNPAID` simply stays `UNPAID` and no FSA
    credit occurs."

    Design: Difficulty/transitive_cascade/order_cancel_cascades_order_to_lab_to_claim_to_policy_ledger
    """
    scenario = setup_in_network_percey_order(fsa_balance_cents=10000)
    order = confirm_order(scenario["order"]["id"], scenario["customer"]["id"], 5000)
    assert order["fsa_applied_cents"] == 5000
    assert read_customer(scenario["customer"]["id"])["fsa_balance_cents"] == 5000

    start_lab_order(lab_order_for(order["id"])["id"])

    resp = api.cancel_order(
        order["id"], {"reason": "changed my mind"}, scenario["headers"]
    )
    cancelled = validate_success(resp, 200)

    assert cancelled["fulfillment_status"] == "CANCELLED"
    assert cancelled["payment_status"] == "REFUNDED"
    assert read_customer(scenario["customer"]["id"])["fsa_balance_cents"] == 10000, (
        "the committed FSA is credited back in full"
    )


def test_cancel_cascades_through_the_lab_order_and_claim_to_the_policy_ledger(api):
    """PRD §3.6: "The cancellation then reaches the order's lab order: if that lab order's
    `status` is any of `QUEUED`, `IN_PRODUCTION`, `REMAKE_QUEUED`, or `QC_PASSED`, it
    transitions to `CANCELLED` and its `version` increments. The lab order's cancellation
    reaches the claim: the order's `active_claim_id` claim, if its `status` is anything other
    than `VOID`, transitions to `VOID`. And the claim's voiding reaches the policy:
    `frame_allowance_remaining_cents` is credited back by exactly the claim's
    `reserved_frame_benefit_cents`, and the order's `active_claim_id` is cleared to null."

    Each hop is caused by the previous hop, not by the cancel call directly: the lab order was
    already IN_PRODUCTION when the cancel landed.

    Design: Difficulty/transitive_cascade/order_cancel_cascades_order_to_lab_to_claim_to_policy_ledger
    """
    scenario = setup_in_network_percey_order(fsa_balance_cents=10000)
    order = confirm_order(scenario["order"]["id"], scenario["customer"]["id"], 5000)
    lab = lab_order_for(order["id"])
    claim = claim_for(order["id"])
    policy_id = scenario["policy"]["id"]

    assert read_policy(policy_id)["frame_allowance_remaining_cents"] == 0
    start_lab_order(lab["id"])

    validate_success(
        api.cancel_order(order["id"], {"reason": "changed my mind"}, scenario["headers"]),
        200,
    )

    assert read_lab_order(lab["id"])["status"] == "CANCELLED"

    voided = read_claim(claim["id"])
    assert voided["status"] == "VOID"
    assert voided["reserved_frame_benefit_cents"] == 15000, (
        "the reserved amount survives the void — the credit is that exact amount"
    )

    policy = read_policy(policy_id)
    assert policy["frame_allowance_remaining_cents"] == 15000
    assert read_order(order["id"])["active_claim_id"] is None


# ═════════════════════════════════════════════════════════════════════════════
# Conserved quantity #1 — frame-allowance dollars
# ═════════════════════════════════════════════════════════════════════════════

def _in_network_confirmed_no_coatings():
    """A 15,000c plan, a 19,500c frame and a 12,000c M167 blank — no coatings — confirmed,
    so the auto-minted claim has reserved the whole 15,000c allowance."""
    return setup_confirmed_order(
        policy={
            "network": "IN_NETWORK",
            "frame_allowance_cents": 15000,
            "lens_copay_cents": 2500,
            "annual_max_cents": 30000,
        },
        frame={"price_cents": 19500, "min_pd_mm": 54.0, "max_pd_mm": 70.0},
        material={"code": "M167", "base_price_cents": 12000, "material_index": 1.67},
        prescription=dict(RX_POWER_EXACTLY_SIX),
    )


def test_a_superseding_claim_re_reserves_exactly_what_the_void_released(api):
    """PRD §2.8: "For any policy, the policy's `frame_allowance_remaining_cents` plus the sum
    of `reserved_frame_benefit_cents` across every non-`VOID` claim against that policy always
    equals the policy's `frame_allowance_cents`."
    PRD §3.8: "An explicit filing **supersedes**. Any existing non-`VOID` claim on that order
    transitions to `VOID`, which credits its policy's `frame_allowance_remaining_cents` back by
    exactly its `reserved_frame_benefit_cents`. The new claim then reserves afresh: its
    `reserved_frame_benefit_cents` is set to the order's current `benefit_frame_cents`, and the
    policy's `frame_allowance_remaining_cents` is debited by that amount."

    Design: Difficulty/compensating_invariant/frame_benefit_dollars_conserved_across_claim_supersede_and_cancel
    """
    scenario = _in_network_confirmed_no_coatings()
    order = scenario["order"]
    policy_id = scenario["policy"]["id"]
    old_claim = claim_for(order["id"])

    assert_frame_benefit_conserved(read_policy(policy_id), list_claims_for(order["id"]))
    assert read_policy(policy_id)["frame_allowance_remaining_cents"] == 0

    new_claim = file_insurance_claim(
        order["id"], order["version"], [{"code": "92004", "billed_cents": 12000}]
    )

    assert read_claim(old_claim["id"])["status"] == "VOID"
    assert read_claim(old_claim["id"])["reserved_frame_benefit_cents"] == 15000
    assert new_claim["reserved_frame_benefit_cents"] == 15000

    policy = read_policy(policy_id)
    assert policy["frame_allowance_remaining_cents"] == 0, (
        "released 15,000 then re-reserved 15,000 — net zero, no drift"
    )
    assert_frame_benefit_conserved(policy, list_claims_for(order["id"]))


def test_cancelling_after_a_supersede_restores_the_whole_allowance(api):
    """PRD §2.8: "Confirming an order is the forward action that reserves benefit; cancelling
    the order is the compensating action that voids the claim and credits back the exact amount
    it had reserved — not a recomputed amount, the reserved amount."
    PRD §3.8: "A claim whose `status` is `SUBMITTED`, `ADJUDICATED_APPROVED`, or
    `ADJUDICATED_DENIED` goes `VOID` in exactly two circumstances: its parent order is
    cancelled, or a superseding claim is filed against that order."

    Two voids and one reservation later, the identity still balances at 15,000.

    Design: Difficulty/compensating_invariant/frame_benefit_dollars_conserved_across_claim_supersede_and_cancel
    """
    scenario = _in_network_confirmed_no_coatings()
    order = scenario["order"]
    policy_id = scenario["policy"]["id"]
    old_claim = claim_for(order["id"])

    new_claim = file_insurance_claim(
        order["id"], order["version"], [{"code": "92004", "billed_cents": 12000}]
    )

    validate_success(api.cancel_order(order["id"], {}, scenario["headers"]), 200)

    assert read_claim(old_claim["id"])["status"] == "VOID"
    assert read_claim(new_claim["id"])["status"] == "VOID"

    policy = read_policy(policy_id)
    assert policy["frame_allowance_remaining_cents"] == 15000
    assert policy["frame_allowance_cents"] == 15000
    assert read_order(order["id"])["active_claim_id"] is None
    assert_frame_benefit_conserved(policy, list_claims_for(order["id"]))
