"""Claim settlement calculation: RCV vs ACV, pinned rounding, deductible, limits."""
from test_helpers import (
    add_claim_item,
    add_full_coverage,
    add_scheduled_item,
    api_client,
    create_policyholder,
    create_quoted_policy,
    file_pp_claim,
    issue_policy,
    make_adjuster_headers,
    make_policyholder_headers,
    set_clock,
    setup_active_policy,
    setup_claim_under_review,
    validate_error,
    validate_success,
    TEST_USERS,
)

UW = TEST_USERS["underwriter_headers"]
ADJ = TEST_USERS["adjuster_headers"]


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc — RCV vs ACV settlement diverge on same items
# ---------------------------------------------------------------------------
def test_claim_settlement_rcv_full_replacement_cost(api):
    """PRD §3.8: "Otherwise — under `RCV`, or for any liability or loss-of-use
    loss — the item's `covered_item_cents` is its full `replacement_cost_cents`
    with no depreciation."
    PRD §3.8: "`settlement_cents` is the larger of zero and the capped loss
    minus `deductible_applied_cents`."

    Design: Difficulty/dual_variant_calc/claim_settlement_rcv_vs_acv_same_items_diverge
    """
    set_clock("2026-06-01T00:00:00Z")
    _ph, _policy, _lines, claim, _items = setup_claim_under_review(
        deductible_cents=25000, pp_valuation_method="RCV",
        items=[
            {"replacement_cost_cents": 120000, "age_months": 24, "useful_life_months": 60},
            {"replacement_cost_cents": 80000, "age_months": 90, "useful_life_months": 120},
        ],
        loss_date="2026-03-01T00:00:00Z", email="dvrcv@x.com",
    )
    assert claim["covered_loss_cents"] == 200000, claim["covered_loss_cents"]
    assert claim["settlement_cents"] == 175000, claim["settlement_cents"]


def test_claim_settlement_acv_depreciated_lower_payout(api):
    """PRD §3.8: "When the claim's `valuation_method` is `ACV` and the loss is
    `PERSONAL_PROPERTY`, the item depreciates: its depreciation fraction is the
    smaller of its `age_months` divided by its `useful_life_months` and the
    maximum depreciation of 0.80, and its `covered_item_cents` is the
    `replacement_cost_cents` multiplied by one minus that depreciation fraction,
    rounded half up to a whole cent."
    PRD §3.8: "Under identical inputs an ACV claim yields a strictly lower
    payout than an RCV claim."

    Design: Difficulty/dual_variant_calc/claim_settlement_rcv_vs_acv_same_items_diverge
    """
    set_clock("2026-06-01T00:00:00Z")
    _ph, _policy, _lines, claim, _items = setup_claim_under_review(
        deductible_cents=25000, pp_valuation_method="ACV",
        items=[
            {"replacement_cost_cents": 120000, "age_months": 24, "useful_life_months": 60},
            {"replacement_cost_cents": 80000, "age_months": 90, "useful_life_months": 120},
        ],
        loss_date="2026-03-01T00:00:00Z", email="dvacv@x.com",
    )
    assert claim["covered_loss_cents"] == 92000, claim["covered_loss_cents"]
    assert claim["settlement_cents"] == 67000, claim["settlement_cents"]


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula mode (b) — pinned per-item rounding order
# ---------------------------------------------------------------------------
def test_claim_settlement_round_per_item_then_sum(api):
    """PRD §3.8: "The rounding order is pinned: each item is rounded to whole
    cents first, and only then are the items summed, so that `covered_loss_cents`
    is the sum of the already-rounded per-item amounts."

    Two ACV items each value to 5000.5 cents; rounding each first gives 5001,
    summing gives 10002 (sum-then-round would give 10001).

    Design: Difficulty/combinatorial_formula/claim_settlement_round_per_item_then_sum_order_pinned
    """
    _ph, _policy, _lines, claim, _items = setup_claim_under_review(
        deductible_cents=0, pp_valuation_method="ACV",
        items=[
            {"replacement_cost_cents": 10001, "age_months": 30, "useful_life_months": 60},
            {"replacement_cost_cents": 10001, "age_months": 30, "useful_life_months": 60},
        ],
        email="rnd@x.com",
    )
    assert claim["covered_loss_cents"] == 10002, claim["covered_loss_cents"]
    assert claim["settlement_cents"] == 10002, claim["settlement_cents"]


def test_claim_settlement_single_item_acv_rounds_half_up(api):
    """PRD §3.8: "its `covered_item_cents` is the `replacement_cost_cents`
    multiplied by one minus that depreciation fraction, rounded half up to a
    whole cent."

    A single ACV item at 5000.5 cents rounds half up to 5001.

    Design: Difficulty/combinatorial_formula/claim_settlement_round_per_item_then_sum_order_pinned
    """
    _ph, _policy, _lines, claim, _items = setup_claim_under_review(
        deductible_cents=0, pp_valuation_method="ACV",
        items=[
            {"replacement_cost_cents": 10001, "age_months": 30, "useful_life_months": 60},
        ],
        email="rnd2@x.com",
    )
    assert claim["covered_loss_cents"] == 5001, claim["covered_loss_cents"]


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check — deductible == covered loss -> 0 payout
# ---------------------------------------------------------------------------
def test_deductible_equals_covered_loss_yields_zero_payout(api):
    """PRD §3.8: "the capped loss is the smaller of `covered_loss_cents` and the
    sum of `remaining_limit_cents` across the referenced coverage lines, and
    `settlement_cents` is the larger of zero and the capped loss minus
    `deductible_applied_cents`."

    ACV item depreciates to exactly 25000, deductible is 25000 -> payout 0.

    Design: Difficulty/boundary_precision_check/deductible_equals_covered_loss_yields_zero_payout
    """
    _ph, _policy, _lines, claim, _items = setup_claim_under_review(
        deductible_cents=25000, pp_valuation_method="ACV",
        items=[
            {"replacement_cost_cents": 50000, "age_months": 30, "useful_life_months": 60},
        ],
        email="bd1@x.com",
    )
    assert claim["covered_loss_cents"] == 25000, claim["covered_loss_cents"]
    assert claim["deductible_applied_cents"] == 25000, claim["deductible_applied_cents"]
    assert claim["settlement_cents"] == 0, claim["settlement_cents"]


def test_settlement_above_deductible_pays_difference(api):
    """PRD §3.8: "`deductible_applied_cents` is the smaller of the policy's
    `deductible_cents` and that eligible amount".
    PRD §3.8: "`settlement_cents` is the larger of zero and the capped loss
    minus `deductible_applied_cents`."

    Design: Difficulty/boundary_precision_check/deductible_equals_covered_loss_yields_zero_payout
    """
    _ph, _policy, _lines, claim, _items = setup_claim_under_review(
        deductible_cents=25000, pp_valuation_method="RCV",
        items=[
            {"replacement_cost_cents": 120000, "age_months": 0, "useful_life_months": 60},
        ],
        email="bd1b@x.com",
    )
    assert claim["covered_loss_cents"] == 120000, claim["covered_loss_cents"]
    assert claim["deductible_applied_cents"] == 25000, claim["deductible_applied_cents"]
    assert claim["settlement_cents"] == 95000, claim["settlement_cents"]


# ---------------------------------------------------------------------------
# Queue B: scheduled item with waived deductible -> no deductible subtracted
# ---------------------------------------------------------------------------
def test_scheduled_item_waived_deductible_not_subtracted(api):
    """PRD §3.8: "The waived portion is the sum of `covered_item_cents` over
    those items whose referenced scheduled item has `deductible_waived` true;
    the deductible-eligible amount is `covered_loss_cents` minus that waived
    portion; and `deductible_applied_cents` is the smaller of the policy's
    `deductible_cents` and that eligible amount — so when only deductible-waived
    scheduled items are claimed, the applied deductible is zero."

    Design: Corner/calculations/scheduled_item_waived_deductible_not_subtracted
    """
    ph = create_policyholder(email="cc1@x.com")
    policy = create_quoted_policy(ph["id"], deductible_cents=25000, pp_valuation_method="RCV")
    add_full_coverage(policy["id"])
    si = add_scheduled_item(policy["id"], 500000, description="ring", deductible_waived=True)
    policy = issue_policy(policy["id"])
    lines = validate_success(api.list_coverage_lines(policy["id"], UW), 200)
    cl_pp = next(l for l in lines if l["coverage_type"] == "PERSONAL_PROPERTY")["id"]
    claim = file_pp_claim(policy["id"], ph["id"])
    add_claim_item(claim["id"], ph["id"], cl_pp, 500000, age_months=0,
                   useful_life_months=60, scheduled_item_id=si["id"])
    reviewed = validate_success(api.start_review(claim["id"], ADJ), 200)
    assert reviewed["covered_loss_cents"] == 500000, reviewed["covered_loss_cents"]
    assert reviewed["deductible_applied_cents"] == 0, reviewed["deductible_applied_cents"]
    assert reviewed["settlement_cents"] == 500000, reviewed["settlement_cents"]


# ---------------------------------------------------------------------------
# Queue B: claim filing / item validations
# ---------------------------------------------------------------------------
def test_claim_loss_date_outside_term_rejected(api):
    """PRD §3.7: "The `loss_date` must fall within the owning policy's half-open
    term `[effective_date, expiry_date)`; a loss dated outside the term is
    rejected with `ERR_LOSS_OUTSIDE_TERM`."

    Design: Corner/validations/claim_loss_date_outside_term_rejected
    """
    _ph, policy, _lines, _inv = setup_active_policy(email="v2@x.com",
                                                    clock="2026-06-01T00:00:00Z")
    resp = api.file_claim(
        policy["id"], {"loss_type": "PERSONAL_PROPERTY", "loss_date": "2027-06-01T00:00:00Z"},
        make_policyholder_headers(_ph["id"]),
    )
    validate_error(resp, "ERR_LOSS_OUTSIDE_TERM", 422)


def test_claim_item_coverage_type_mismatch_rejected(api):
    """PRD §3.7: "The referenced coverage line's `coverage_type` must match the
    claim's `loss_type`; a mismatch is rejected with `ERR_COVERAGE_TYPE_MISMATCH`."

    Design: Corner/validations/claim_item_coverage_type_mismatch_rejected
    """
    _ph, policy, lines, _inv = setup_active_policy(email="v1@x.com")
    cl_liab = lines["LIABILITY"]["id"]
    claim = file_pp_claim(policy["id"], _ph["id"])
    resp = api.add_claim_item(
        claim["id"], {"coverage_line_id": cl_liab, "replacement_cost_cents": 50000},
        make_policyholder_headers(_ph["id"]),
    )
    validate_error(resp, "ERR_COVERAGE_TYPE_MISMATCH", 422)
