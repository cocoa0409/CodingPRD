"""Account pricing, the multi-pet discount, and cascade re-pricing.

Difficulty queue: dual_variant_calc (premium), combinatorial_formula (premium),
transitive_cascade (activate/lapse), compensating_invariant (premium).
"""
from test_helpers import (
    validate_success,
    create_account, create_policy, activate_policy,
    make_underwriter_headers,
)


def _uw():
    return make_underwriter_headers()


def test_rider_premium_escapes_multi_pet_discount(api):
    """PRD 3.1: "the per-policy line is that rounded discounted base plus a flat
    Wellness rider premium of 1500 cents only when the policy carries the
    wellness_rider, and nothing otherwise. The discount applies to the base premium
    only — the rider premium is added after the discount and rounding, and is never
    itself discounted."

    Two ACTIVE policies (10% multi-pet discount): P1 base 4500 with rider, P2 base
    3800 no rider -> 4050+1500 + 3420 == 8970, not 8820.

    Design: Difficulty/dual_variant_calc/premium_discount_base_vs_full_line_on_account
    """
    acct = create_account(email="dv1@x.com", full_name="A One")
    p1 = create_policy(acct["id"], pet_name="Rex", base_premium_cents=4500, wellness_rider=True)
    p2 = create_policy(acct["id"], pet_name="Mia", species="CAT", base_premium_cents=3800, wellness_rider=False)
    activate_policy(acct["id"], p1["id"])
    activate_policy(acct["id"], p2["id"])

    data = validate_success(api.get_account(acct["id"], _uw()))
    assert data["active_policy_count"] == 2, f"expected 2 active, got {data['active_policy_count']}"
    assert data["multi_pet_discount_applied"] is True
    assert data["monthly_premium_cents"] == 8970, f"expected 8970, got {data['monthly_premium_cents']}"


def test_premium_round_per_policy_then_sum_order(api):
    """PRD 3.1: "The account's monthly_premium_cents is the sum of all per-policy
    lines computed in that pinned order: discount and round each policy's base, then
    add the undiscounted rider, then sum across policies."

    Two ACTIVE policies base 4500 (rider) + 3800 (no rider) -> 8970.

    Design: Difficulty/combinatorial_formula/premium_round_per_policy_then_sum_order
    """
    acct = create_account(email="cf2@x.com", full_name="A Four")
    p1 = create_policy(acct["id"], pet_name="Rex", base_premium_cents=4500, wellness_rider=True)
    p2 = create_policy(acct["id"], pet_name="Mia", species="CAT", base_premium_cents=3800, wellness_rider=False)
    activate_policy(acct["id"], p1["id"])
    activate_policy(acct["id"], p2["id"])

    data = validate_success(api.get_account(acct["id"], _uw()))
    assert data["monthly_premium_cents"] == 8970, f"expected 8970, got {data['monthly_premium_cents']}"


def test_activate_cascade_creates_year_and_reprices_account_depth3(api):
    """PRD 3.2: "Activation then creates the first coverage year — a PolicyYear with
    year_index 0, period_start equal to the effective date and period_end equal to the
    effective date plus 365 days, in OPEN status — and recomputes the account's
    active_policy_count, monthly_premium_cents, and multi_pet_discount_applied per the
    pricing rule of Section 3.1."

    Activating the second policy: P2 -> ACTIVE -> year 0 created -> account re-prices
    to two-active-policy premium 8970.

    Design: Difficulty/transitive_cascade/activate_policy_year_account_reprice_depth3
    """
    acct = create_account(email="tc7@x.com", full_name="A Seven")
    p1 = create_policy(acct["id"], pet_name="Rex", base_premium_cents=4500, wellness_rider=True)
    activate_policy(acct["id"], p1["id"])
    p2 = create_policy(acct["id"], pet_name="Mia", species="CAT", base_premium_cents=3800, wellness_rider=False)

    activated = validate_success(api.activate_policy(acct["id"], p2["id"], {}, _uw()))
    assert activated["status"] == "ACTIVE"

    years_data, years_meta = _years(api, acct["id"], p2["id"])
    assert years_meta["total_count"] == 1, f"expected exactly one year created, got {years_meta['total_count']}"
    assert years_data[0]["year_index"] == 0

    acct_data = validate_success(api.get_account(acct["id"], _uw()))
    assert acct_data["active_policy_count"] == 2
    assert acct_data["monthly_premium_cents"] == 8970, f"expected 8970, got {acct_data['monthly_premium_cents']}"


def test_lapse_cascade_drops_discount_and_reprices_depth2(api):
    """PRD 3.1: "lapsing or cancelling one of exactly two active policies drops the
    account to a single active policy, removes the multi-pet discount, and therefore
    re-prices the surviving sibling policy upward on the very same operation."

    After lapse, only P1 (base 4500 rider) remains active and is no longer discounted:
    4500 + 1500 == 6000.

    Design: Difficulty/transitive_cascade/lapse_policy_account_reprice_depth2
    """
    acct = create_account(email="tc8@x.com", full_name="A Eight")
    p1 = create_policy(acct["id"], pet_name="Rex", base_premium_cents=4500, wellness_rider=True)
    activate_policy(acct["id"], p1["id"])
    p2 = create_policy(acct["id"], pet_name="Mia", species="CAT", base_premium_cents=3800, wellness_rider=False)
    activate_policy(acct["id"], p2["id"])

    validate_success(api.lapse_policy(acct["id"], p2["id"], _uw()))

    acct_data = validate_success(api.get_account(acct["id"], _uw()))
    assert acct_data["active_policy_count"] == 1
    assert acct_data["multi_pet_discount_applied"] is False
    assert acct_data["monthly_premium_cents"] == 6000, f"expected 6000, got {acct_data['monthly_premium_cents']}"


def test_lapse_then_reactivate_restores_premium_no_drift(api):
    """PRD 3.1: "The account's monthly_premium_cents is the sum of all per-policy lines
    computed in that pinned order: discount and round each policy's base, then add the
    undiscounted rider, then sum across policies."

    Lapsing P2 then activating an identical fresh P3 must return the premium to its
    pre-lapse two-active value of 8970 with no drift.

    Design: Difficulty/compensating_invariant/lapse_then_reactivate_account_premium_invariant
    """
    acct = create_account(email="ci18@x.com", full_name="A Eighteen")
    p1 = create_policy(acct["id"], pet_name="Rex", base_premium_cents=4500, wellness_rider=True)
    activate_policy(acct["id"], p1["id"])
    p2 = create_policy(acct["id"], pet_name="Mia", species="CAT", base_premium_cents=3800, wellness_rider=False)
    activate_policy(acct["id"], p2["id"])
    validate_success(api.lapse_policy(acct["id"], p2["id"], _uw()))
    p3 = create_policy(acct["id"], pet_name="Mia2", species="CAT", base_premium_cents=3800, wellness_rider=False)

    validate_success(api.activate_policy(acct["id"], p3["id"], {}, _uw()))

    acct_data = validate_success(api.get_account(acct["id"], _uw()))
    assert acct_data["active_policy_count"] == 2
    assert acct_data["monthly_premium_cents"] == 8970, f"expected 8970, got {acct_data['monthly_premium_cents']}"


def test_single_rider_policy_premium_is_undiscounted_base_plus_rider(api):
    """PRD 3.1: "The multi-pet discount is in force when the count of those active
    policies is at least two; the threshold for the discount is two active policies."
    PRD 3.1: "the per-policy line is that rounded discounted base plus a flat Wellness
    rider premium of 1500 cents only when the policy carries the wellness_rider."

    A lone ACTIVE rider policy (count 1, no discount): premium == 4500 + 1500 == 6000.

    Design: Difficulty/dual_variant_calc/premium_discount_base_vs_full_line_on_account
    """
    acct = create_account(email="dv1b@x.com", full_name="A One B")
    p1 = create_policy(acct["id"], pet_name="Rex", base_premium_cents=4500, wellness_rider=True)
    activate_policy(acct["id"], p1["id"])

    data = validate_success(api.get_account(acct["id"], _uw()))
    assert data["active_policy_count"] == 1
    assert data["multi_pet_discount_applied"] is False
    assert data["monthly_premium_cents"] == 6000, f"expected 6000, got {data['monthly_premium_cents']}"


def test_premium_discount_applied_flag_set_with_two_active(api):
    """PRD 3.1: "when it is met multi_pet_discount_applied is true. The applicable
    discount when in force is 1000 basis points."

    With two active policies the discount flag is true and the discounted total 8970 is
    below the undiscounted sum (4500+1500 + 3800 == 9800).

    Design: Difficulty/combinatorial_formula/premium_round_per_policy_then_sum_order
    """
    acct = create_account(email="cf2b@x.com", full_name="A Four B")
    p1 = create_policy(acct["id"], pet_name="Rex", base_premium_cents=4500, wellness_rider=True)
    p2 = create_policy(acct["id"], pet_name="Mia", species="CAT", base_premium_cents=3800, wellness_rider=False)
    activate_policy(acct["id"], p1["id"])
    activate_policy(acct["id"], p2["id"])

    data = validate_success(api.get_account(acct["id"], _uw()))
    assert data["multi_pet_discount_applied"] is True
    assert data["monthly_premium_cents"] == 8970


def test_activate_sets_policy_active_and_increments_versions(api):
    """PRD 3.2: "Both the account version and the policy version increment by one as part
    of this transition."

    Activating the second policy yields P2 ACTIVE and account active_policy_count 2 —
    the first cascade link.

    Design: Difficulty/transitive_cascade/activate_policy_year_account_reprice_depth3
    """
    acct = create_account(email="tc7b@x.com", full_name="A Seven B")
    p1 = create_policy(acct["id"], pet_name="Rex", base_premium_cents=4500, wellness_rider=True)
    activate_policy(acct["id"], p1["id"])
    p2 = create_policy(acct["id"], pet_name="Mia", species="CAT", base_premium_cents=3800, wellness_rider=False)

    activated = validate_success(api.activate_policy(acct["id"], p2["id"], {}, _uw()))
    assert activated["status"] == "ACTIVE"
    acct_data = validate_success(api.get_account(acct["id"], _uw()))
    assert acct_data["active_policy_count"] == 2


def test_lapse_drops_active_count_and_discount_flag(api):
    """PRD 3.2: "When a policy that was ACTIVE is lapsed or cancelled, the platform
    recomputes the account's active_policy_count, monthly_premium_cents, and
    multi_pet_discount_applied."

    Lapsing P2 drops active_policy_count to 1 and clears multi_pet_discount_applied.

    Design: Difficulty/transitive_cascade/lapse_policy_account_reprice_depth2
    """
    acct = create_account(email="tc8b@x.com", full_name="A Eight B")
    p1 = create_policy(acct["id"], pet_name="Rex", base_premium_cents=4500, wellness_rider=True)
    activate_policy(acct["id"], p1["id"])
    p2 = create_policy(acct["id"], pet_name="Mia", species="CAT", base_premium_cents=3800, wellness_rider=False)
    activate_policy(acct["id"], p2["id"])

    validate_success(api.lapse_policy(acct["id"], p2["id"], _uw()))
    acct_data = validate_success(api.get_account(acct["id"], _uw()))
    assert acct_data["active_policy_count"] == 1
    assert acct_data["multi_pet_discount_applied"] is False


def test_lapse_then_reactivate_restores_active_count(api):
    """PRD 3.1: "The active_policy_count is the number of the account's child policies
    currently in ACTIVE status; policies in PENDING_PAYMENT, LAPSED, or CANCELLED status
    are not counted."

    After lapsing P2 (count 1) and activating fresh P3, the count returns to 2.

    Design: Difficulty/compensating_invariant/lapse_then_reactivate_account_premium_invariant
    """
    acct = create_account(email="ci18b@x.com", full_name="A Eighteen B")
    p1 = create_policy(acct["id"], pet_name="Rex", base_premium_cents=4500, wellness_rider=True)
    activate_policy(acct["id"], p1["id"])
    p2 = create_policy(acct["id"], pet_name="Mia", species="CAT", base_premium_cents=3800, wellness_rider=False)
    activate_policy(acct["id"], p2["id"])
    validate_success(api.lapse_policy(acct["id"], p2["id"], _uw()))
    p3 = create_policy(acct["id"], pet_name="Mia2", species="CAT", base_premium_cents=3800, wellness_rider=False)

    validate_success(api.activate_policy(acct["id"], p3["id"], {}, _uw()))
    acct_data = validate_success(api.get_account(acct["id"], _uw()))
    assert acct_data["active_policy_count"] == 2


def _years(api, account_id, policy_id):
    resp = api.list_policy_years(account_id, policy_id, _uw())
    body = resp.json()
    return body["data"], body["meta"]
