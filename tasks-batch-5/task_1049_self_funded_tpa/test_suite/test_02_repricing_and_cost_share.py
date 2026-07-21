"""Claim repricing (PPO vs UCR) and the member cost-share waterfall."""
from test_helpers import (
    validate_success, TEST_USERS,
    create_plan, create_provider, create_member,
    submit_claim, adjudicate_claim,
)

ADMIN = TEST_USERS["tpa_admin_headers"]


# ---- dual_variant_calc: in-network PPO vs out-of-network UCR ---------------
def test_repricing_in_network_ppo_allowed_amount(api):
    """PRD 3.4: "For an in-network provider, each line's allowed amount is the line's
    `billed_cents` multiplied by one minus the provider's `ppo_discount_pct`, rounded
    half-up to whole cents, and the `allowed_amount_cents` is the sum of those per-line
    rounded results — the rounding is applied to each line before summing, not to the total."

    Design: Difficulty/dual_variant_calc/repricing_in_network_ppo_vs_out_of_network_ucr
    """
    plan = create_plan()
    prov = create_provider(name="InNet Clinic", in_network=True, ppo_discount_pct=0.40)
    member = create_member(plan["id"])
    claim = submit_claim(member["id"], prov["id"], billed_lines=[{"billed_cents": 100000}])
    adjudicate_claim(claim["id"])
    data = validate_success(api.get_claim(claim["id"], ADMIN))
    assert data["allowed_amount_cents"] == 60000, (
        f"in-network 40% PPO on 100000 -> 60000, got {data['allowed_amount_cents']}")


def test_repricing_out_of_network_ucr_allowed_amount(api):
    """PRD 3.4: "For an out-of-network provider, the PPO discount is ignored entirely
    and the `allowed_amount_cents` is the lesser of the claim's `billed_total_cents`
    and its `ucr_amount_cents`."

    Design: Difficulty/dual_variant_calc/repricing_in_network_ppo_vs_out_of_network_ucr
    """
    plan = create_plan()
    prov = create_provider(name="OON Clinic", tax_id="33-3333333", npi="2222222222",
                           in_network=False, ppo_discount_pct=0)
    member = create_member(plan["id"])
    claim = submit_claim(member["id"], prov["id"],
                         billed_lines=[{"billed_cents": 100000}], ucr_amount_cents=70000)
    adjudicate_claim(claim["id"])
    data = validate_success(api.get_claim(claim["id"], ADMIN))
    assert data["allowed_amount_cents"] == 70000, (
        f"out-of-network UCR min(100000, 70000) -> 70000, got {data['allowed_amount_cents']}")


# ---- combinatorial_formula: nested deductible/coinsurance/OOP waterfall -----
def _setup_two_claim_waterfall(api):
    plan = create_plan()  # ded 100000, oop 500000, coins 0.80
    prov = create_provider(in_network=True, ppo_discount_pct=0.40)
    member = create_member(plan["id"])
    # first claim: billed 100000 -> allowed 60000, deductible_met becomes 60000
    c1 = submit_claim(member["id"], prov["id"], service_date="2026-03-01",
                      billed_lines=[{"billed_cents": 100000}])
    adjudicate_claim(c1["id"])
    # second claim under test: billed 200000 -> allowed 120000
    c2 = submit_claim(member["id"], prov["id"], service_date="2026-03-02",
                      billed_lines=[{"billed_cents": 200000}])
    adjudicate_claim(c2["id"])
    return member, c2


def test_cost_share_waterfall_claim_fields(api):
    """PRD 3.4: "the `deductible_applied_cents` is the lesser of the `allowed_amount_cents`
    and that remaining deductible." "The `member_coinsurance_cents` is that after-deductible
    amount multiplied by one minus the plan's `plan_coinsurance_pct` (the member's share is
    whatever the plan does not pay), rounded half-up to whole cents." "Finally,
    `plan_paid_cents` is the `allowed_amount_cents` minus `member_responsibility_cents`."

    Design: Difficulty/combinatorial_formula/cost_share_nested_deductible_coinsurance_oop_mode_a
    """
    _member, c2 = _setup_two_claim_waterfall(api)
    data = validate_success(api.get_claim(c2["id"], ADMIN))
    assert data["allowed_amount_cents"] == 120000
    assert data["deductible_applied_cents"] == 40000
    assert data["member_coinsurance_cents"] == 16000
    assert data["member_responsibility_cents"] == 56000
    assert data["plan_paid_cents"] == 64000


def test_cost_share_waterfall_updates_deductible_accumulator(api):
    """PRD 3.4: "Adjudication then advances the member's accumulators: `deductible_met_cents`
    increases by `deductible_applied_cents`, `oop_met_cents` increases by
    `member_responsibility_cents`, and `member_plan_paid_ytd_cents` increases by `plan_paid_cents`."

    Design: Difficulty/combinatorial_formula/cost_share_nested_deductible_coinsurance_oop_mode_a
    """
    member, _c2 = _setup_two_claim_waterfall(api)
    data = validate_success(api.get_member(member["id"], ADMIN))
    assert data["deductible_met_cents"] == 100000, (
        f"deductible_met after 60000 + 40000 -> 100000, got {data['deductible_met_cents']}")


# ---- combinatorial_formula: per-line rounding order ------------------------
def test_per_line_repricing_rounds_each_line_before_summing(api):
    """PRD 3.4: "the `allowed_amount_cents` is the sum of those per-line rounded results
    — the rounding is applied to each line before summing, not to the total."
    PRD 2.6: "for repricing in particular, rounding happens on each line item before the
    lines are summed, never on the sum."

    Design: Difficulty/combinatorial_formula/per_line_repricing_rounding_order_mode_b
    """
    plan = create_plan()
    prov = create_provider(name="Frac Clinic", in_network=True, ppo_discount_pct=0.375)
    member = create_member(plan["id"])
    claim = submit_claim(member["id"], prov["id"],
                         billed_lines=[{"billed_cents": 100}, {"billed_cents": 100}])
    adjudicate_claim(claim["id"])
    data = validate_success(api.get_claim(claim["id"], ADMIN))
    # round(100*0.625)=63 per line; 63+63 = 126 (sum-then-round would give 125).
    assert data["allowed_amount_cents"] == 126, (
        f"per-line rounding 63+63 -> 126, got {data['allowed_amount_cents']}")


def test_per_line_repricing_result_reaches_adjudicated(api):
    """PRD 3.4: "For an in-network provider, each line's allowed amount is the line's
    `billed_cents` multiplied by one minus the provider's `ppo_discount_pct`, rounded
    half-up to whole cents, and the `allowed_amount_cents` is the sum of those per-line
    rounded results — the rounding is applied to each line before summing, not to the total."

    Design: Difficulty/combinatorial_formula/per_line_repricing_rounding_order_mode_b
    """
    plan = create_plan()
    prov = create_provider(name="Frac Clinic", in_network=True, ppo_discount_pct=0.375)
    member = create_member(plan["id"])
    claim = submit_claim(member["id"], prov["id"],
                         billed_lines=[{"billed_cents": 100}, {"billed_cents": 100}])
    data = validate_success(api.adjudicate_claim(claim["id"],
                                                 TEST_USERS["claims_examiner_headers"]))
    assert data["status"] == "ADJUDICATED"
    assert data["allowed_amount_cents"] == 126


# ---- boundary_precision_check: deductible exactly met ----------------------
def _setup_deductible_exactly_met(api):
    plan = create_plan()  # ded 100000
    prov = create_provider(in_network=True, ppo_discount_pct=0.40)
    member = create_member(plan["id"])
    c1 = submit_claim(member["id"], prov["id"], service_date="2026-03-01",
                      billed_lines=[{"billed_cents": 100000}])  # allowed 60000
    adjudicate_claim(c1["id"])
    c2 = submit_claim(member["id"], prov["id"], service_date="2026-03-02",
                      billed_lines=[{"billed_cents": 200000}])  # allowed 120000, ded_met -> 100000
    adjudicate_claim(c2["id"])
    c3 = submit_claim(member["id"], prov["id"], service_date="2026-03-03",
                      billed_lines=[{"billed_cents": 100000}])  # allowed 60000
    adjudicate_claim(c3["id"])
    return c3


def test_deductible_met_boundary_zero_deductible_applied(api):
    """PRD 3.4: "the remaining deductible is the plan's `individual_deductible_cents` minus
    the member's current `deductible_met_cents`, floored at 0; the `deductible_applied_cents`
    is the lesser of the `allowed_amount_cents` and that remaining deductible."

    Design: Difficulty/boundary_precision_check/deductible_exactly_met_boundary_on_adjudicate
    """
    c3 = _setup_deductible_exactly_met(api)
    data = validate_success(api.get_claim(c3["id"], ADMIN))
    assert data["deductible_applied_cents"] == 0, (
        f"deductible fully met -> 0 applied, got {data['deductible_applied_cents']}")


def test_deductible_met_boundary_full_coinsurance_and_plan_paid(api):
    """PRD 3.4: "The `member_coinsurance_cents` is that after-deductible amount multiplied by
    one minus the plan's `plan_coinsurance_pct` (the member's share is whatever the plan does
    not pay), rounded half-up to whole cents."
    PRD 3.4: "Finally, `plan_paid_cents` is the `allowed_amount_cents` minus `member_responsibility_cents`."

    Design: Difficulty/boundary_precision_check/deductible_exactly_met_boundary_on_adjudicate
    """
    c3 = _setup_deductible_exactly_met(api)
    data = validate_success(api.get_claim(c3["id"], ADMIN))
    assert data["member_coinsurance_cents"] == 12000
    assert data["plan_paid_cents"] == 48000


# ---- Corner: billed_total_cents computed from lines ------------------------
def test_claim_billed_total_computed_from_lines(api):
    """PRD 3.4: "On submission the server computes `billed_total_cents` as the sum of
    `billed_cents` across all `billed_lines`, and the claim begins in `SUBMITTED` status."

    Design: Corner/entities/claim_billed_total_computed_from_lines
    """
    plan = create_plan()
    prov = create_provider(in_network=True, ppo_discount_pct=0.40)
    member = create_member(plan["id"])
    claim = submit_claim(member["id"], prov["id"],
                         billed_lines=[{"billed_cents": 60000}, {"billed_cents": 40000}])
    data = validate_success(api.get_claim(claim["id"], ADMIN))
    assert data["billed_total_cents"] == 100000, (
        f"billed_total 60000 + 40000 -> 100000, got {data['billed_total_cents']}")
