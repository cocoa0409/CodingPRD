"""Premium quoting and peril reimbursement calculations (§3.2, §3.6).

Covers difficulty rules dual_variant_calc (cancellation provisional vs final),
combinatorial_formula (premium quote, baggage per-item rounding), and the
corner calculation correctness instances.
"""
from test_helpers import (
    validate_success,
    setup_active_policy, setup_claim_under_review, approve_claim,
    add_insured, create_quoted_policy, create_plan, create_traveler,
    make_traveler_headers,
)


# ─── dual_variant_calc: cancellation provisional vs final ──────────────────

def test_cancellation_provisional_amount_documented_basis(api):
    """PRD §3.4: "For a cancellation claim this provisional figure sums, over each
    prepaid-trip expense line, the smaller of that line's `documented_amount_cents` and
    its `prepaid_nonrefundable_cents`, then caps the sum at the cancellation peril cap and
    again at the policy's `remaining_aggregate_cents`".

    Lines: min(210000,200000)=200000 and min(160000,150000)=150000 -> 350000;
    cancellation cap = floor(500000*100/100) = 500000; remaining = aggregate (huge);
    provisional = 350000. The provisional basis ignores supplier refunds.

    Design: Difficulty/dual_variant_calc/cancellation_provisional_vs_final_diverges_on_supplier_refund
    """
    bundle = setup_claim_under_review(
        plan_overrides={"base_rate_bps": 600, "cancellation_limit_pct": 100,
                        "medical_limit_cents": 500000, "delay_limit_cents": 100000,
                        "baggage_limit_cents": 100000, "claim_filing_window_days": 90},
        peril="CANCELLATION", incident_at="2026-06-01T00:00:00Z",
        claim_overrides={"cancellation_reason": "COVERED_REASON"},
        expenses=[
            {"category": "PREPAID_TRIP", "description": "flights",
             "documented_amount_cents": 210000, "prepaid_nonrefundable_cents": 200000,
             "supplier_refund_received_cents": 0},
            {"category": "PREPAID_TRIP", "description": "hotel",
             "documented_amount_cents": 160000, "prepaid_nonrefundable_cents": 150000,
             "supplier_refund_received_cents": 50000},
        ],
        doc_type="RECEIPT",
    )
    claim = bundle["claim"]
    assert claim["provisional_amount_cents"] == 350000, \
        f"provisional must be 350000, got {claim['provisional_amount_cents']}"


def test_cancellation_final_amount_nets_supplier_refund(api):
    """PRD §3.6: "the raw figure sums over each prepaid-trip expense line the larger of zero
    and that line's `prepaid_nonrefundable_cents` minus its `supplier_refund_received_cents`."
    PRD §3.6: "This final basis differs from the provisional basis in two ways: it subtracts
    each line's supplier refund, and it applies the CFAR percentage for CFAR cancellations."

    final = max(0,200000-0) + max(0,150000-50000) = 200000 + 100000 = 300000;
    so the supplier refund produces a 50000 delta below the 350000 provisional figure.

    Design: Difficulty/dual_variant_calc/cancellation_provisional_vs_final_diverges_on_supplier_refund
    """
    bundle = setup_claim_under_review(
        plan_overrides={"base_rate_bps": 600, "cancellation_limit_pct": 100,
                        "medical_limit_cents": 500000, "delay_limit_cents": 100000,
                        "baggage_limit_cents": 100000, "claim_filing_window_days": 90},
        peril="CANCELLATION", incident_at="2026-06-01T00:00:00Z",
        claim_overrides={"cancellation_reason": "COVERED_REASON"},
        expenses=[
            {"category": "PREPAID_TRIP", "description": "flights",
             "documented_amount_cents": 210000, "prepaid_nonrefundable_cents": 200000,
             "supplier_refund_received_cents": 0},
            {"category": "PREPAID_TRIP", "description": "hotel",
             "documented_amount_cents": 160000, "prepaid_nonrefundable_cents": 150000,
             "supplier_refund_received_cents": 50000},
        ],
        doc_type="RECEIPT",
    )
    claim = approve_claim(bundle["claim"]["id"])
    assert claim["approved_amount_cents"] == 300000, \
        f"final approved must be 300000, got {claim['approved_amount_cents']}"
    assert claim["provisional_amount_cents"] - claim["approved_amount_cents"] == 50000, \
        "provisional minus final must equal the 50000 supplier-refund delta"


# ─── combinatorial_formula: premium quote ──────────────────────────────────

def test_premium_base_before_loadings(api):
    """PRD §3.2: "`base_premium_cents` is the ceiling of `trip_cost_cents` times `base_rate_bps`
    divided by 10000."

    trip_cost 500000 * 600 / 10000 = 30000 -> base_premium_cents == 30000 (no loadings at
    quote with no insured yet).

    Design: Difficulty/combinatorial_formula/premium_quote_tiered_rate_plus_senior_plus_cfar_loadings
    """
    plan = create_plan(tier="STANDARD", base_rate_bps=600, senior_loading_bps=5000,
                       cfar_loading_bps=4000)
    traveler = create_traveler()
    policy = create_quoted_policy(plan["id"], traveler["id"], trip_cost_cents=500000,
                                  cfar_opted=True)
    assert policy["base_premium_cents"] == 30000, \
        f"base_premium_cents must be 30000, got {policy['base_premium_cents']}"


def test_premium_total_with_senior_and_cfar_loadings(api):
    """PRD §3.2: "the senior loading is the ceiling of `base_premium_cents` times
    `senior_loading_bps` divided by 10000" ... "the CFAR loading is the ceiling of
    `base_premium_cents` times `cfar_loading_bps` divided by 10000" ... "`premium_cents` is
    their sum: base premium plus senior loading plus CFAR loading."

    base 30000 + senior ceil(30000*5000/10000)=15000 + CFAR ceil(30000*4000/10000)=12000
    -> premium_cents == 57000 after adding a qualifying senior insured.

    Design: Difficulty/combinatorial_formula/premium_quote_tiered_rate_plus_senior_plus_cfar_loadings
    """
    plan = create_plan(tier="STANDARD", base_rate_bps=600, senior_loading_bps=5000,
                       cfar_loading_bps=4000)
    traveler = create_traveler()
    policy = create_quoted_policy(plan["id"], traveler["id"], trip_cost_cents=500000,
                                  cfar_opted=True)
    add_insured(policy["id"], traveler["id"], age_at_departure=72,
                covered_trip_cost_cents=500000)
    headers = make_traveler_headers(traveler["id"])
    refreshed = validate_success(api.get_policy(policy["id"], headers), 200)
    assert refreshed["base_premium_cents"] == 30000
    assert refreshed["premium_cents"] == 57000, \
        f"premium_cents must be 57000 (30000+15000+12000), got {refreshed['premium_cents']}"


# ─── combinatorial_formula: baggage per-item rounding ──────────────────────

def test_baggage_round_per_item_before_sum(api):
    """PRD §3.6: "first compute the depreciated value as the item's `item_value_cents` times
    the quantity (10000 minus the plan's `baggage_depreciation_bps`) divided by 10000, rounded
    half up; then cap that depreciated value at the plan's `baggage_item_sublimit_cents` to get
    the line's covered amount."
    PRD §3.6: "depreciation is rounded and the sublimit applied per item *before* summation,
    never after."

    Two items value 1250 each, depreciation 2500 bps: round_half_up(1250*7500/10000)=
    round_half_up(937.5)=938 per item, sum = 1876 (sum-then-round would be 1875).

    Design: Difficulty/combinatorial_formula/baggage_reimbursement_round_per_item_before_sum
    """
    bundle = setup_claim_under_review(
        plan_overrides={"tier": "PREMIER", "base_rate_bps": 800,
                        "baggage_depreciation_bps": 2500,
                        "baggage_item_sublimit_cents": 30000,
                        "baggage_limit_cents": 100000},
        peril="BAGGAGE", incident_at="2026-06-05T00:00:00Z",
        expenses=[
            {"category": "BAGGAGE_ITEM", "description": "camera",
             "documented_amount_cents": 1250, "item_value_cents": 1250},
            {"category": "BAGGAGE_ITEM", "description": "watch",
             "documented_amount_cents": 1250, "item_value_cents": 1250},
        ],
        doc_type="POLICE_REPORT",
    )
    claim = approve_claim(bundle["claim"]["id"])
    assert claim["approved_amount_cents"] == 1876, \
        f"baggage approved must be 1876 (938+938), got {claim['approved_amount_cents']}"


def test_baggage_per_item_rounding_distinct_from_sum_then_round(api):
    """PRD §3.6: "depreciation is rounded and the sublimit applied per item *before* summation,
    never after."

    A faithful per-item implementation yields 1876; a (wrong) sum-then-round yields 1875.
    Asserting the result is exactly 1876 and not 1875 pins the rounding order.

    Design: Difficulty/combinatorial_formula/baggage_reimbursement_round_per_item_before_sum
    """
    bundle = setup_claim_under_review(
        plan_overrides={"tier": "PREMIER", "base_rate_bps": 800,
                        "baggage_depreciation_bps": 2500,
                        "baggage_item_sublimit_cents": 30000,
                        "baggage_limit_cents": 100000},
        peril="BAGGAGE", incident_at="2026-06-05T00:00:00Z",
        expenses=[
            {"category": "BAGGAGE_ITEM", "description": "camera",
             "documented_amount_cents": 1250, "item_value_cents": 1250},
            {"category": "BAGGAGE_ITEM", "description": "watch",
             "documented_amount_cents": 1250, "item_value_cents": 1250},
        ],
        doc_type="POLICE_REPORT",
    )
    claim = approve_claim(bundle["claim"]["id"])
    assert claim["approved_amount_cents"] == 1876
    assert claim["approved_amount_cents"] != 1875, \
        "sum-then-round (1875) is explicitly forbidden by the pinned per-item order"


# ─── Corner: calculations ──────────────────────────────────────────────────

def test_delay_reimbursement_blocks_capped_at_limit(api):
    """PRD §3.6: "the number of completed delay blocks is the floor of `delay_hours` divided by
    12".
    PRD §3.6: "The raw figure is the number of blocks times the plan's `delay_block_cap_cents`.
    The `approved_amount_cents` is the smallest of that raw figure, the plan's
    `delay_limit_cents`, and `remaining_aggregate_cents`."

    delay_hours 72 -> floor(72/12)=6 blocks * 20000 = 120000, capped at delay_limit 100000.

    Design: Corner/calculations/delay_reimbursement_two_blocks_capped_at_limit
    """
    bundle = setup_claim_under_review(
        plan_overrides={"base_rate_bps": 600, "delay_block_cap_cents": 20000,
                        "delay_limit_cents": 100000},
        peril="DELAY", incident_at="2026-06-05T00:00:00Z",
        claim_overrides={"delay_hours": 72},
        doc_type="CARRIER_DELAY_LETTER",
    )
    claim = approve_claim(bundle["claim"]["id"])
    assert claim["approved_amount_cents"] == 100000, \
        f"delay approved must be capped at delay_limit 100000, got {claim['approved_amount_cents']}"


def test_cfar_cancellation_applies_reimbursement_percentage(api):
    """PRD §3.6: "If the `cancellation_reason` is `CFAR`, that raw figure is then reduced to the
    floor of itself times the plan's `cfar_reimbursement_pct` divided by 100."

    Net loss = max(0,200000-0)+max(0,150000-50000) = 300000; CFAR 75% ->
    floor(300000*75/100) = 225000.

    Design: Corner/calculations/cfar_cancellation_applies_reimbursement_percentage
    """
    bundle = setup_claim_under_review(
        plan_overrides={"base_rate_bps": 600, "cancellation_limit_pct": 100,
                        "cfar_reimbursement_pct": 75},
        policy_overrides={"cfar_opted": True},
        peril="CANCELLATION", incident_at="2026-06-02T00:00:00Z",
        claim_overrides={"cancellation_reason": "CFAR"},
        expenses=[
            {"category": "PREPAID_TRIP", "description": "flights",
             "documented_amount_cents": 210000, "prepaid_nonrefundable_cents": 200000,
             "supplier_refund_received_cents": 0},
            {"category": "PREPAID_TRIP", "description": "hotel",
             "documented_amount_cents": 160000, "prepaid_nonrefundable_cents": 150000,
             "supplier_refund_received_cents": 50000},
        ],
        doc_type="OTHER",
    )
    claim = approve_claim(bundle["claim"]["id"])
    assert claim["approved_amount_cents"] == 225000, \
        f"CFAR approved must be floor(300000*0.75)=225000, got {claim['approved_amount_cents']}"


def test_preexisting_waiver_granted_within_window(api):
    """PRD §3.3: "the waiver is granted when days-to-issue is less than or equal to the plan's
    `waiver_window_days` **and** the sum of `covered_trip_cost_cents` across `COVERED` insured
    travelers equals `trip_cost_cents`."

    initial_deposit 2026-05-25, issued 2026-06-01 -> 6 days <= 14; full cost insured ->
    preexisting_waiver_granted == true.

    Design: Corner/calculations/preexisting_waiver_granted_when_issued_within_window
    """
    active = setup_active_policy(
        plan_overrides={"tier": "BASIC", "base_rate_bps": 400, "waiver_window_days": 14},
        policy_overrides={"initial_deposit_at": "2026-05-25T00:00:00Z"},
        insured_overrides={"has_preexisting_condition": True},
        clock="2026-06-01T00:00:00Z",
    )
    assert active["policy"]["preexisting_waiver_granted"] is True, \
        "preexisting_waiver_granted must be true when issued inside the window with full cost insured"
