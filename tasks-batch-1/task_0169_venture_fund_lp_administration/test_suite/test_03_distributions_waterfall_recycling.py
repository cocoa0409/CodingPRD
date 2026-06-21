"""Distribution declaration, the four-tier waterfall, clawback, recycling/recall,
reversal, and LP statement K-1 figures. Covers the heavy difficulty-queue
calculation/state-machine/compensating-invariant instances plus corner-queue
distribution instances.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, make_limited_partner_headers,
    create_distribution_event_payload,
)
from test_helpers import fixtures as fx

FM = TEST_USERS["fund_manager_headers"]
FA = TEST_USERS["fund_administrator_headers"]


# ---------------------------------------------------------------------------
# Four-tier waterfall — combinatorial min/max
# ---------------------------------------------------------------------------

def test_waterfall_tiered_nonlinear_min_max(api):
    """PRD §3.5: "The event's `lp_share_cents` is the sum of tier one, tier two, and the LP portion of tier four; its `gp_carry_cents` is the sum of the tier-three catch-up and the GP portion of tier four."

    Design: Difficulty/combinatorial_formula/waterfall_tiered_nonlinear_min_max
    """
    fund, _, _ = fx.setup_fund_with_active_commitments(
        [6_000_000, 4_000_000], name="Waterfall Fund", vintage_year=2023,
        carry_rate_bps=2000, pref_rate_bps=800, gp_catchup_rate_bps=10000)
    fx.issue_and_fund_call(fund["id"], 10_000_000)
    inv, _ = fx.create_realized_investment(
        fund["id"], 15_000_000, cost_basis_cents=10_000_000, ownership_pct_bps=2000,
        company_name="Beta", sector="Fintech")
    event = fx.declare_distribution(
        fund["id"], inv["id"], 15_000_000, distribution_type="CAPITAL_GAIN")
    assert event["lp_share_cents"] == 14_000_000
    assert event["gp_carry_cents"] == 1_000_000


def test_waterfall_lp_and_gp_shares_sum_to_gross(api):
    """PRD §3.5: "The event's `lp_share_cents` is the sum of tier one, tier two, and the LP portion of tier four; its `gp_carry_cents` is the sum of the tier-three catch-up and the GP portion of tier four."

    Design: Difficulty/combinatorial_formula/waterfall_tiered_nonlinear_min_max
    """
    fund, _, _ = fx.setup_fund_with_active_commitments(
        [6_000_000, 4_000_000], name="Waterfall Sum Fund", vintage_year=2023,
        carry_rate_bps=2000, pref_rate_bps=800, gp_catchup_rate_bps=10000)
    fx.issue_and_fund_call(fund["id"], 10_000_000)
    inv, _ = fx.create_realized_investment(
        fund["id"], 15_000_000, cost_basis_cents=10_000_000, ownership_pct_bps=2000,
        company_name="Beta2", sector="Fintech")
    event = fx.declare_distribution(
        fund["id"], inv["id"], 15_000_000, distribution_type="CAPITAL_GAIN")
    # The full gross is partitioned into LP share and GP carry with nothing lost.
    assert event["lp_share_cents"] + event["gp_carry_cents"] == 15_000_000
    assert event["lp_share_cents"] == 14_000_000


def test_waterfall_base_no_clawback_keeps_gp_carry(api):
    """PRD §3.5: "When no shortfall exists, `clawback_flag` remains false on every allocation."
    PRD §3.5: "its `gp_carry_cents` is the sum of the tier-three catch-up and the GP portion of tier four."

    Design: Difficulty/dual_variant_calc/waterfall_base_vs_clawback_variant
    """
    # Capital fully returned by a prior 12,000,000 RETURN_OF_CAPITAL (prior_dist >
    # paid_in 10,000,000), so a subsequent 1,000,000 CAPITAL_GAIN sits above the
    # pref floor and the GP keeps its 20% carry: tier4_gp = round(1,000,000*2000/10000).
    fund, _, _ = fx.setup_fund_with_active_commitments(
        [6_000_000, 4_000_000], name="Carry Fund", vintage_year=2024,
        carry_rate_bps=2000, pref_rate_bps=800, gp_catchup_rate_bps=10000)
    fx.issue_and_fund_call(fund["id"], 10_000_000)
    inv, _ = fx.create_realized_investment(
        fund["id"], 14_000_000, cost_basis_cents=10_000_000, ownership_pct_bps=1500,
        company_name="Acme", sector="SaaS")
    fx.declare_and_pay_distribution(
        fund["id"], inv["id"], 12_000_000, distribution_type="RETURN_OF_CAPITAL")
    event = fx.declare_distribution(
        fund["id"], inv["id"], 1_000_000, distribution_type="CAPITAL_GAIN")
    assert event["gp_carry_cents"] == 200_000
    assert event["lp_share_cents"] == 800_000


def test_waterfall_base_no_clawback_flag_set(api):
    """PRD §3.5: "When no shortfall exists, `clawback_flag` remains false on every allocation."

    Design: Difficulty/dual_variant_calc/waterfall_base_vs_clawback_variant
    """
    fund, commitments, _ = fx.setup_fund_with_active_commitments(
        [6_000_000, 4_000_000], name="NoClawback Fund", vintage_year=2024,
        carry_rate_bps=2000, pref_rate_bps=800, gp_catchup_rate_bps=10000)
    fx.issue_and_fund_call(fund["id"], 10_000_000)
    inv, _ = fx.create_realized_investment(
        fund["id"], 14_000_000, cost_basis_cents=10_000_000, ownership_pct_bps=1500,
        company_name="Acme2", sector="SaaS")
    fx.declare_and_pay_distribution(
        fund["id"], inv["id"], 12_000_000, distribution_type="RETURN_OF_CAPITAL")
    event = fx.declare_distribution(
        fund["id"], inv["id"], 1_000_000, distribution_type="CAPITAL_GAIN")
    # Capital already fully returned -> LP receipts above the pref floor -> no clawback.
    allocs = validate_success(api.list_distribution_allocations(
        FA, params={"distribution_event_id": event["id"]}), 200)
    assert allocs, "the declared event must have been split into allocations"
    assert all(a["clawback_flag"] is False for a in allocs)


# ---------------------------------------------------------------------------
# Cyclic recall / recycling — drawn_cents restoration
# ---------------------------------------------------------------------------

def test_distribution_cyclic_recall_restores_drawn_cents(api):
    """PRD §3.6: "When the recall proceeds, the event's `recycled_amount_cents` is set to the recallable amount."
    PRD §3.6: "Each affected commitment's `drawn_cents` is reduced by its restoration share, which correspondingly restores its `unfunded_cents`, and the fund's `recycled_to_date_cents` is recomputed to reflect the recall."

    Design: Difficulty/non_linear_state_machine/distribution_cyclic_recall_recycling
    """
    fund, c1, c2 = fx.setup_two_commitment_fund_funded(
        6_000_000, 4_000_000, 10_000_000, name="Recycle Fund",
        recycling_cap_pct_bps=12000)
    inv, _ = fx.create_realized_investment(
        fund["id"], 5_000_000, cost_basis_cents=10_000_000, ownership_pct_bps=1000,
        company_name="Gamma", sector="Health")
    event = fx.declare_and_pay_distribution(
        fund["id"], inv["id"], 3_000_000, distribution_type="RETURN_OF_CAPITAL",
        recyclable=True)
    recalled = validate_success(api.recall_distribution_event(event["id"], FM), 200)
    assert recalled["status"] == "RECALLED"
    assert recalled["recycled_amount_cents"] == 3_000_000
    # lp_share 3,000,000 split pro-rata by drawn 6,000,000 / 4,000,000 -> 1,800,000 /
    # 1,200,000; recall restores drawn by those shares: 6,000,000-1,800,000=4,200,000,
    # 4,000,000-1,200,000=2,800,000.
    assert validate_success(api.get_commitment(c1["id"], FM), 200)["drawn_cents"] == 4_200_000
    assert validate_success(api.get_commitment(c2["id"], FM), 200)["drawn_cents"] == 2_800_000


def test_distribution_recall_sets_status_and_restores_unfunded(api):
    """PRD §3.6: "A `FundManager` recalls an event, moving it from `PAID` to `RECALLED`, but only when the event's `recyclable` flag is true and the recall stays within the fund's recycling cap."
    PRD §3.6: "Each affected commitment's `drawn_cents` is reduced by its restoration share, which correspondingly restores its `unfunded_cents`, and the fund's `recycled_to_date_cents` is recomputed to reflect the recall."

    Design: Difficulty/non_linear_state_machine/distribution_cyclic_recall_recycling
    """
    fund, commitment, _ = fx.setup_single_commitment_funded(
        5_000_000, name="Recycle Single Fund", recycling_cap_pct_bps=12000)
    inv, _ = fx.create_realized_investment(
        fund["id"], 6_000_000, cost_basis_cents=5_000_000, ownership_pct_bps=1000,
        company_name="Gamma2", sector="Health")
    event = fx.declare_and_pay_distribution(
        fund["id"], inv["id"], 1_500_000, distribution_type="RETURN_OF_CAPITAL",
        recyclable=True)
    recalled = validate_success(api.recall_distribution_event(event["id"], FM), 200)
    assert recalled["status"] == "RECALLED"
    refreshed = validate_success(api.get_commitment(commitment["id"], FM), 200)
    # Single commitment receives the full lp_share 1,500,000; recall restores it.
    assert refreshed["drawn_cents"] == 3_500_000
    assert refreshed["unfunded_cents"] == 1_500_000


def test_recycling_recall_conserves_total_capital(api):
    """PRD §3.6: "Each affected commitment's `drawn_cents` is reduced by its restoration share, which correspondingly restores its `unfunded_cents`, and the fund's `recycled_to_date_cents` is recomputed to reflect the recall."

    Design: Difficulty/compensating_invariant/recycling_recall_conserves_total_capital
    """
    fund, commitment, _ = fx.setup_single_commitment_funded(
        5_000_000, name="RecallCons Fund", recycling_cap_pct_bps=12000)
    inv, _ = fx.create_realized_investment(
        fund["id"], 6_000_000, cost_basis_cents=5_000_000, ownership_pct_bps=1000,
        company_name="Iota", sector="Gaming")
    event = fx.declare_and_pay_distribution(
        fund["id"], inv["id"], 2_000_000, distribution_type="RETURN_OF_CAPITAL",
        recyclable=True)
    recalled = validate_success(api.recall_distribution_event(event["id"], FM), 200)
    assert recalled["recycled_amount_cents"] == 2_000_000
    refreshed = validate_success(api.get_commitment(commitment["id"], FM), 200)
    assert refreshed["drawn_cents"] == 3_000_000
    assert refreshed["unfunded_cents"] == 2_000_000


def test_recycling_recall_preserves_committed_total(api):
    """PRD §2.6: "Its `unfunded_cents` is `committed_cents` minus `drawn_cents`, floored at zero — the remaining callable capital."
    PRD §3.6: "Each affected commitment's `drawn_cents` is reduced by its restoration share, which correspondingly restores its `unfunded_cents`, and the fund's `recycled_to_date_cents` is recomputed to reflect the recall."

    Design: Difficulty/compensating_invariant/recycling_recall_conserves_total_capital
    """
    fund, commitment, _ = fx.setup_single_commitment_funded(
        5_000_000, name="RecallCons2 Fund", recycling_cap_pct_bps=12000)
    inv, _ = fx.create_realized_investment(
        fund["id"], 6_000_000, cost_basis_cents=5_000_000, ownership_pct_bps=1000,
        company_name="Iota2", sector="Gaming")
    event = fx.declare_and_pay_distribution(
        fund["id"], inv["id"], 2_000_000, distribution_type="RETURN_OF_CAPITAL",
        recyclable=True)
    validate_success(api.recall_distribution_event(event["id"], FM), 200)
    refreshed = validate_success(api.get_commitment(commitment["id"], FM), 200)
    # The conserved quantity: drawn + unfunded always equals committed.
    assert refreshed["drawn_cents"] + refreshed["unfunded_cents"] == refreshed["committed_cents"]
    assert refreshed["committed_cents"] == 5_000_000


# ---------------------------------------------------------------------------
# Recycling cap boundary
# ---------------------------------------------------------------------------

def test_recycling_cap_zero_headroom_rejected(api):
    """PRD §3.6: "If the recallable amount is not positive — that is, the headroom is already exhausted so that the recycled-to-date plus this recall would breach the cap — the recall is rejected with `ERR_RECYCLING_CAP_EXCEEDED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/recycling_cap_boundary_exact_zero_headroom
    """
    fund, _, _ = fx.setup_two_commitment_fund_funded(
        6_000_000, 4_000_000, 10_000_000, name="CapBoundary Fund",
        recycling_cap_pct_bps=5000)  # cap = 50% of 10,000,000 = 5,000,000
    inv, _ = fx.create_realized_investment(
        fund["id"], 10_000_000, cost_basis_cents=10_000_000, ownership_pct_bps=1000,
        company_name="Epsilon", sector="Energy")
    # First recyclable distribution of 5,000,000 recalled to fill the cap exactly.
    evt1 = fx.declare_and_pay_distribution(
        fund["id"], inv["id"], 5_000_000, distribution_type="RETURN_OF_CAPITAL",
        recyclable=True)
    validate_success(api.recall_distribution_event(evt1["id"], FM), 200)
    # Second recyclable distribution: recall now hits zero headroom.
    evt2 = fx.declare_and_pay_distribution(
        fund["id"], inv["id"], 2_000_000, distribution_type="RETURN_OF_CAPITAL",
        recyclable=True)
    validate_error(api.recall_distribution_event(evt2["id"], FM),
                   "ERR_RECYCLING_CAP_EXCEEDED", 422)


def test_recall_nonrecyclable_event_is_invalid_state(api):
    """PRD §3.6: "A `FundManager` recalls an event, moving it from `PAID` to `RECALLED`, but only when the event's `recyclable` flag is true and the recall stays within the fund's recycling cap."

    Design: Difficulty/boundary_precision_check/recycling_cap_boundary_exact_zero_headroom
    """
    fund, commitment, _ = fx.setup_single_commitment_funded(
        5_000_000, name="NonRecyclable Fund", recycling_cap_pct_bps=12000)
    inv, _ = fx.create_realized_investment(
        fund["id"], 6_000_000, cost_basis_cents=5_000_000, ownership_pct_bps=1000,
        company_name="Sigma", sector="Energy")
    # recyclable defaults to false -> PAID->RECALLED transition is not defined.
    event = fx.declare_and_pay_distribution(
        fund["id"], inv["id"], 2_000_000, distribution_type="RETURN_OF_CAPITAL",
        recyclable=False)
    validate_error(api.recall_distribution_event(event["id"], FM),
                   "ERR_INVALID_STATE", 409)


# ---------------------------------------------------------------------------
# Distribution reverse — compensating invariant
# ---------------------------------------------------------------------------

def test_distribution_reverse_conserves_commitment_distributed(api):
    """PRD §3.5: "A `FundManager` may instead reverse a still-`DECLARED` event, moving it from `DECLARED` to `REVERSED` and zeroing the `amount_cents` on all of its allocations; because the event never reached `PAID`, no commitment's `distributed_cents` drifts."

    Design: Difficulty/compensating_invariant/distribution_reverse_conserves_commitment_distributed
    """
    fund, commitment, _ = fx.setup_single_commitment_funded(
        5_000_000, name="ReverseInv Fund")
    inv, _ = fx.create_realized_investment(
        fund["id"], 6_000_000, cost_basis_cents=5_000_000, ownership_pct_bps=1000,
        company_name="Theta", sector="Travel")
    event = fx.declare_distribution(
        fund["id"], inv["id"], 2_000_000, distribution_type="RETURN_OF_CAPITAL")
    reversed_evt = validate_success(api.reverse_distribution_event(event["id"], FM), 200)
    assert reversed_evt["status"] == "REVERSED"
    assert validate_success(api.get_commitment(commitment["id"], FM), 200)["distributed_cents"] == 0


def test_distribution_reverse_zeros_allocation_amounts(api):
    """PRD §3.5: "A `FundManager` may instead reverse a still-`DECLARED` event, moving it from `DECLARED` to `REVERSED` and zeroing the `amount_cents` on all of its allocations; because the event never reached `PAID`, no commitment's `distributed_cents` drifts."

    Design: Difficulty/compensating_invariant/distribution_reverse_conserves_commitment_distributed
    """
    fund, commitment, _ = fx.setup_single_commitment_funded(
        5_000_000, name="ReverseZero Fund")
    inv, _ = fx.create_realized_investment(
        fund["id"], 6_000_000, cost_basis_cents=5_000_000, ownership_pct_bps=1000,
        company_name="Theta2", sector="Travel")
    event = fx.declare_distribution(
        fund["id"], inv["id"], 2_000_000, distribution_type="RETURN_OF_CAPITAL")
    validate_success(api.reverse_distribution_event(event["id"], FM), 200)
    allocs = validate_success(api.list_distribution_allocations(
        FA, params={"distribution_event_id": event["id"]}), 200)
    assert all(a["amount_cents"] == 0 for a in allocs), \
        "reversal zeroes amount_cents on every allocation"


def test_distribution_pay_immediately_visible_on_commitment(api):
    """PRD §3.5: "Payment moves the event from `DECLARED` to `PAID`, recomputes `distributed_cents` on each commitment named by an allocation, and recomputes the fund's `total_distributed_cents`."

    Design: Corner/consistency_model/distribution_pay_immediately_visible_on_commitment
    """
    fund, commitment, _ = fx.setup_single_commitment_funded(
        5_000_000, name="Immediate Fund")
    inv, _ = fx.create_realized_investment(
        fund["id"], 6_000_000, cost_basis_cents=5_000_000, ownership_pct_bps=1000,
        company_name="Rho", sector="Agri")
    event = fx.declare_distribution(
        fund["id"], inv["id"], 2_000_000, distribution_type="RETURN_OF_CAPITAL")
    paid = validate_success(api.pay_distribution_event(event["id"], FA), 200)
    assert paid["status"] == "PAID"
    assert validate_success(api.get_commitment(commitment["id"], FM), 200)["distributed_cents"] == 2_000_000


# ---------------------------------------------------------------------------
# Distribution declaration guards
# ---------------------------------------------------------------------------

def test_distribution_declare_requires_realized_investment(api):
    """PRD §3.5: "The source investment must be in `REALIZED` status; declaring against an unrealized investment is rejected with `ERR_SOURCE_NOT_REALIZED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/distribution_declare_requires_realized_investment
    """
    fund, commitment, _ = fx.setup_single_commitment_funded(
        6_000_000, name="NotReal Fund")
    inv, _ = fx.create_investment(
        fund["id"], cost_basis_cents=6_000_000, ownership_pct_bps=1000,
        company_name="Zeta", sector="Retail")  # ACTIVE, not realized
    version = fx.fund_version(fund["id"])
    payload = create_distribution_event_payload(
        fund["id"], inv["id"], version, gross_amount_cents=1_000_000,
        distribution_type="CAPITAL_GAIN")
    validate_error(api.create_distribution_event(payload, FM),
                   "ERR_SOURCE_NOT_REALIZED", 422)


def test_distribution_declare_on_realized_investment_succeeds(api):
    """PRD §3.5: "A successful declaration creates the event in `DECLARED` status and increments the fund's `version` by one."

    Design: Difficulty/cross_entity_state_dependency/distribution_declare_requires_realized_investment
    """
    fund, commitment, _ = fx.setup_single_commitment_funded(
        6_000_000, name="RealOk Fund")
    inv, _ = fx.create_realized_investment(
        fund["id"], 6_000_000, cost_basis_cents=6_000_000, ownership_pct_bps=1000,
        company_name="Eta2", sector="Retail")
    version = fx.fund_version(fund["id"])
    payload = create_distribution_event_payload(
        fund["id"], inv["id"], version, gross_amount_cents=1_000_000,
        distribution_type="CAPITAL_GAIN")
    event = validate_success(api.create_distribution_event(payload, FM), 201)
    assert event["status"] == "DECLARED"


def test_distribution_exceeds_proceeds_rejected(api):
    """PRD §3.5: "The `gross_amount_cents` must not exceed the realized proceeds still available on the source investment — that is, its `realized_proceeds_cents` less the amounts already distributed from it; an over-draw is rejected with `ERR_DISTRIBUTION_EXCEEDS_PROCEEDS` (HTTP 422)."

    Design: Corner/validations/distribution_exceeds_proceeds_rejected
    """
    fund, commitment, _ = fx.setup_single_commitment_funded(
        6_000_000, name="Proceeds Fund")
    inv, _ = fx.create_realized_investment(
        fund["id"], 6_000_000, cost_basis_cents=6_000_000, ownership_pct_bps=1000,
        company_name="Nu", sector="Auto")
    version = fx.fund_version(fund["id"])
    payload = create_distribution_event_payload(
        fund["id"], inv["id"], version, gross_amount_cents=7_000_000,
        distribution_type="CAPITAL_GAIN")
    validate_error(api.create_distribution_event(payload, FM),
                   "ERR_DISTRIBUTION_EXCEEDS_PROCEEDS", 422)


# ---------------------------------------------------------------------------
# LP statement / K-1
# ---------------------------------------------------------------------------

def test_lp_statement_dpi_and_k1_lines(api):
    """PRD §3.8: "The distributions-to-paid-in ratio (`dpi_bps`) is the distributed amount multiplied by `10000` divided by paid-in capital, and the total-value-to-paid-in ratio (`tvpi_bps`) is the distributed amount plus NAV, multiplied by `10000`, divided by paid-in capital; both ratios are integer basis points and both are zero when paid-in capital is zero."
    PRD §3.8: "The K-1 line items sum the LP's distribution-allocation amounts on `PAID` events by type: the return-of-capital line totals the allocations from `RETURN_OF_CAPITAL` events, the capital-gain line totals those from `CAPITAL_GAIN` events, and the income line totals those from `INCOME` events."

    Design: Corner/calculations/lp_statement_dpi_tvpi_and_k1_lines
    """
    fund = fx.create_fund(name="Statement Fund", target_size_cents=5_000_000)
    lp = fx.create_lp(legal_name="LP ST", tax_id_last4="2727")
    commitment = fx.create_accepted_commitment(fund["id"], lp["id"], 5_000_000)
    fx.issue_and_fund_call(fund["id"], 5_000_000)
    inv, _ = fx.create_realized_investment(
        fund["id"], 6_000_000, cost_basis_cents=5_000_000, ownership_pct_bps=1000,
        company_name="Mu", sector="Space")
    fx.declare_and_pay_distribution(
        fund["id"], inv["id"], 2_000_000, distribution_type="RETURN_OF_CAPITAL")
    headers = make_limited_partner_headers(lp["id"])
    stmt = validate_success(api.get_commitment_statement(commitment["id"], headers), 200)
    assert stmt["paid_in_cents"] == 5_000_000
    assert stmt["distributed_cents"] == 2_000_000
    assert stmt["dpi_bps"] == 4000
    assert stmt["k1_return_of_capital_cents"] == 2_000_000
