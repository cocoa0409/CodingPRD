"""Drawdown waterfall allocation, the federal ledger, and conservation on return.

Sources: Difficulty queue (transitive_cascade on disburse, boundary_precision on the
waterfall remainder, resource_temporal_overlap on fund/ceiling capacity,
compensating_invariant on return) and Corner queue (calculations waterfall variants,
validations allocation-mismatch, entities immutability, cross_cutting derived fields,
consistency_model).
"""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    ApiErrorId,
    assert_fund_allocation,
    TEST_USERS,
)
import test_helpers.fixtures as fx

FO = TEST_USERS["finance_officer_headers"]
AO = TEST_USERS["agency_officer_headers"]


# ==========================================================================
# Transitive cascade (Difficulty Rule 4): disburse -> allocations -> fund -> ledger
# ==========================================================================
def test_disburse_cascade_allocations_then_fund_balances(api):
    """PRD §3.5: "First, one fund-allocation line is created for each waterfall line,
    each carrying its parent drawdown_id, the target restricted_fund_id, and the
    amount_cents posted. Second, each restricted fund's allocated_cents is increased by
    the amount of its allocation line."
    PRD §3.5: "a drawdown larger than the first fund's headroom fills that fund to its
    budget and spills the remainder into the next-priority fund or funds."

    Design: Difficulty/transitive_cascade/disburse_cascade_allocation_then_fund_balance_then_award_ledger
    """
    award, funds = fx.create_award_with_funds(
        [
            {"category": "PERSONNEL", "budgeted_cents": 10_000_000, "priority_order": 1},
            {"category": "TRAVEL", "budgeted_cents": 2_000_000, "priority_order": 2},
            {"category": "SUPPLIES", "budgeted_cents": 3_000_000, "priority_order": 3},
        ],
        nofo_number="NOFO-2026-A7", applicant_org_name="Org G",
        requested_amount_cents=50_000_000,
    )
    rf_a, rf_b, rf_c = funds
    dd = fx.create_drawdown(
        award["id"], 11_000_000,
        [
            {"restricted_fund_id": rf_a["id"], "amount_cents": 10_000_000},
            {"restricted_fund_id": rf_b["id"], "amount_cents": 1_000_000},
        ],
        initiator_user_id="officer-draw-A7",
    )
    disbursed = validate_success(api.disburse_drawdown(dd["id"], fx.make_finance_officer_headers("officer-draw-A7")))
    assert disbursed["status"] == "DISBURSED"
    assert validate_success(api.get_restricted_fund(rf_a["id"], FO))["allocated_cents"] == 10_000_000
    assert validate_success(api.get_restricted_fund(rf_b["id"], FO))["allocated_cents"] == 1_000_000
    assert validate_success(api.get_restricted_fund(rf_c["id"], FO))["allocated_cents"] == 0


def test_disburse_cascade_rolls_up_into_award_federal_drawn(api):
    """PRD §3.5: "Third, the award's federal_drawn_cents is increased by the drawdown's
    amount_cents, keeping the federal ledger in sync."

    Design: Difficulty/transitive_cascade/disburse_cascade_allocation_then_fund_balance_then_award_ledger
    """
    award, funds = fx.create_award_with_funds(
        [
            {"category": "PERSONNEL", "budgeted_cents": 10_000_000, "priority_order": 1},
            {"category": "TRAVEL", "budgeted_cents": 2_000_000, "priority_order": 2},
        ],
        nofo_number="NOFO-2026-A7b", applicant_org_name="Org G2",
        requested_amount_cents=50_000_000,
    )
    rf_a, rf_b = funds
    dd = fx.create_drawdown(
        award["id"], 11_000_000,
        [
            {"restricted_fund_id": rf_a["id"], "amount_cents": 10_000_000},
            {"restricted_fund_id": rf_b["id"], "amount_cents": 1_000_000},
        ],
        initiator_user_id="officer-draw-A7b",
    )
    fx.disburse_drawdown(dd["id"], "officer-draw-A7b")
    award_after = validate_success(api.get_award(award["id"], AO))
    assert award_after["federal_drawn_cents"] == 11_000_000


# ==========================================================================
# Boundary precision (Difficulty Rule 6): exact-fill leaves no third allocation
# ==========================================================================
def test_exact_fill_two_buckets_skips_zero_take_third_allocation(api):
    """PRD §3.5: "whenever the amount taken is greater than zero, an allocation line is
    recorded for that fund and the remaining cash is reduced by the amount taken."
    PRD §3.5: "A drawdown that needs only its first eligible fund yields a single
    allocation line and leaves later funds untouched."

    Design: Difficulty/boundary_precision_check/drawdown_zero_remainder_exact_fill_no_third_allocation
    """
    award, funds = fx.create_award_with_funds(
        [
            {"category": "PERSONNEL", "budgeted_cents": 4_000_000, "priority_order": 1},
            {"category": "TRAVEL", "budgeted_cents": 3_000_000, "priority_order": 2},
            {"category": "SUPPLIES", "budgeted_cents": 5_000_000, "priority_order": 3},
        ],
        nofo_number="NOFO-2026-A12", applicant_org_name="Org L",
        requested_amount_cents=50_000_000,
    )
    rf_a, rf_b, rf_c = funds
    dd = fx.create_drawdown(
        award["id"], 7_000_000,
        [
            {"restricted_fund_id": rf_a["id"], "amount_cents": 4_000_000},
            {"restricted_fund_id": rf_b["id"], "amount_cents": 3_000_000},
        ],
        initiator_user_id="officer-draw-A12",
    )
    disbursed = fx.disburse_drawdown(dd["id"], "officer-draw-A12")
    assert disbursed["status"] == "DISBURSED"
    allocs = api.list_drawdown_allocations(dd["id"], FO).json()["data"]
    assert len(allocs) == 2, f"Expected exactly 2 allocation rows, got {len(allocs)}"
    assert validate_success(api.get_restricted_fund(rf_c["id"], FO))["allocated_cents"] == 0


def test_exact_fill_two_buckets_post_exact_headroom_amounts(api):
    """PRD §3.5: "Walking the funds in that order, each fund absorbs the smaller of the
    cash still remaining and that fund's headroom, where headroom is budgeted_cents minus
    current allocated_cents."
    PRD §3.5: "a drawdown larger than the first fund's headroom fills that fund to its
    budget and spills the remainder into the next-priority fund or funds."

    Design: Difficulty/boundary_precision_check/drawdown_zero_remainder_exact_fill_no_third_allocation
    """
    award, funds = fx.create_award_with_funds(
        [
            {"category": "PERSONNEL", "budgeted_cents": 4_000_000, "priority_order": 1},
            {"category": "TRAVEL", "budgeted_cents": 3_000_000, "priority_order": 2},
            {"category": "SUPPLIES", "budgeted_cents": 5_000_000, "priority_order": 3},
        ],
        nofo_number="NOFO-2026-A12b", applicant_org_name="Org L2",
        requested_amount_cents=50_000_000,
    )
    rf_a, rf_b, rf_c = funds
    dd = fx.create_drawdown(
        award["id"], 7_000_000,
        [
            {"restricted_fund_id": rf_a["id"], "amount_cents": 4_000_000},
            {"restricted_fund_id": rf_b["id"], "amount_cents": 3_000_000},
        ],
        initiator_user_id="officer-draw-A12b",
    )
    fx.disburse_drawdown(dd["id"], "officer-draw-A12b")
    # First two funds filled to their full headroom; third untouched.
    assert validate_success(api.get_restricted_fund(rf_a["id"], FO))["allocated_cents"] == 4_000_000
    assert validate_success(api.get_restricted_fund(rf_b["id"], FO))["allocated_cents"] == 3_000_000
    assert validate_success(api.get_restricted_fund(rf_c["id"], FO))["allocated_cents"] == 0


# ==========================================================================
# Resource temporal overlap (Difficulty Rule 8): capacity ceilings
# ==========================================================================
def test_per_fund_budget_overlap_rejected_with_budget_would_exceed(api):
    """PRD §3.5: "The per-fund budget guard is the same condition that drives the
    waterfall — for every derived line, the fund's allocated_cents plus that line's
    amount_cents must not exceed the fund's budgeted_cents, and a breach surfaces as
    ERR_BUDGET_WOULD_EXCEED."

    Design: Difficulty/resource_temporal_overlap/restricted_fund_budget_capacity_overlap_aggregate
    """
    award, funds = fx.create_award_with_funds(
        [{"category": "PERSONNEL", "budgeted_cents": 5_000_000, "priority_order": 1}],
        nofo_number="NOFO-2026-A15", applicant_org_name="Org O",
        requested_amount_cents=50_000_000,
    )
    fund = funds[0]
    fx.create_disbursed_drawdown(
        award["id"], 4_000_000, fx.single_line_plan(fund["id"], 4_000_000),
        initiator_user_id="officer-draw-A15",
    )
    dd2 = fx.create_drawdown(
        award["id"], 2_000_000, fx.single_line_plan(fund["id"], 2_000_000),
        initiator_user_id="officer-draw-A15",
    )
    resp = api.disburse_drawdown(dd2["id"], fx.make_finance_officer_headers("officer-draw-A15"))
    # PRD §3.5 sequences the undistributed-remainder (ERR_BUDGET_WOULD_EXCEED) check
    # before the plan-vs-derived comparison ("must then ... or ERR_ALLOCATION_MISMATCH"),
    # while PRD §3.9 orders ERR_ALLOCATION_MISMATCH (tenth) before ERR_BUDGET_WOULD_EXCEED
    # (thirteenth). Here the 2,000,000 request against a fund with only 1,000,000 headroom
    # trips BOTH conditions simultaneously, and the two PRD sections name different winners,
    # so a faithful PRD-only implementer can land on either. Accept the named set.
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_BUDGET_WOULD_EXCEED.value, ApiErrorId.ERR_ALLOCATION_MISMATCH.value],
    )
    assert validate_success(api.get_restricted_fund(fund["id"], FO))["allocated_cents"] == 4_000_000


def test_per_fund_budget_overlap_leaves_drawdown_requested(api):
    """PRD §3.5: "for every derived line, the fund's allocated_cents plus that line's
    amount_cents must not exceed the fund's budgeted_cents, and a breach surfaces as
    ERR_BUDGET_WOULD_EXCEED."

    Design: Difficulty/resource_temporal_overlap/restricted_fund_budget_capacity_overlap_aggregate
    """
    award, funds = fx.create_award_with_funds(
        [{"category": "PERSONNEL", "budgeted_cents": 5_000_000, "priority_order": 1}],
        nofo_number="NOFO-2026-A15b", applicant_org_name="Org O2",
        requested_amount_cents=50_000_000,
    )
    fund = funds[0]
    fx.create_disbursed_drawdown(
        award["id"], 4_000_000, fx.single_line_plan(fund["id"], 4_000_000),
        initiator_user_id="officer-draw-A15b",
    )
    dd2 = fx.create_drawdown(
        award["id"], 2_000_000, fx.single_line_plan(fund["id"], 2_000_000),
        initiator_user_id="officer-draw-A15b",
    )
    resp = api.disburse_drawdown(dd2["id"], fx.make_finance_officer_headers("officer-draw-A15b"))
    # PRD §3.5 sequences the undistributed-remainder (ERR_BUDGET_WOULD_EXCEED) check
    # before the plan-vs-derived comparison ("must then ... or ERR_ALLOCATION_MISMATCH"),
    # while PRD §3.9 orders ERR_ALLOCATION_MISMATCH (tenth) before ERR_BUDGET_WOULD_EXCEED
    # (thirteenth). The 2,000,000 request against a fund with only 1,000,000 headroom trips
    # BOTH conditions, and the two PRD sections disagree on the winner, so accept either.
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_BUDGET_WOULD_EXCEED.value, ApiErrorId.ERR_ALLOCATION_MISMATCH.value],
    )
    # The over-budget drawdown was not disbursed.
    assert validate_success(api.get_drawdown(dd2["id"], FO))["status"] == "REQUESTED"


def test_award_ceiling_overlap_rejected_with_ceiling_exceeded(api):
    """PRD §3.5: "the drawdown must not breach the federal ceiling: the award's
    federal_drawn_cents plus the drawdown's amount_cents must not exceed the award's
    federal_ceiling_cents, failing otherwise with ERR_CEILING_EXCEEDED."

    Design: Difficulty/resource_temporal_overlap/award_federal_ceiling_lifetime_capacity_overlap
    """
    # total 10000000 * 0.80 = ceiling 8000000; fund budget 20000000 (ample).
    award, funds = fx.create_award_with_funds(
        [{"category": "PERSONNEL", "budgeted_cents": 20_000_000, "priority_order": 1}],
        nofo_number="NOFO-2026-A16", applicant_org_name="Org P",
        requested_amount_cents=10_000_000, federal_share_pct=0.80,
    )
    fund = funds[0]
    fx.create_disbursed_drawdown(
        award["id"], 8_000_000, fx.single_line_plan(fund["id"], 8_000_000),
        initiator_user_id="officer-draw-A16",
    )
    dd2 = fx.create_drawdown(
        award["id"], 1, fx.single_line_plan(fund["id"], 1),
        initiator_user_id="officer-draw-A16",
    )
    resp = api.disburse_drawdown(dd2["id"], fx.make_finance_officer_headers("officer-draw-A16"))
    validate_error(resp, ApiErrorId.ERR_CEILING_EXCEEDED.value, expected_status=409)
    assert validate_success(api.get_award(award["id"], AO))["federal_drawn_cents"] == 8_000_000


def test_award_ceiling_overlap_leaves_second_drawdown_requested(api):
    """PRD §3.5: "the award's federal_drawn_cents plus the drawdown's amount_cents must
    not exceed the award's federal_ceiling_cents, failing otherwise with
    ERR_CEILING_EXCEEDED."

    Design: Difficulty/resource_temporal_overlap/award_federal_ceiling_lifetime_capacity_overlap
    """
    award, funds = fx.create_award_with_funds(
        [{"category": "PERSONNEL", "budgeted_cents": 20_000_000, "priority_order": 1}],
        nofo_number="NOFO-2026-A16b", applicant_org_name="Org P2",
        requested_amount_cents=10_000_000, federal_share_pct=0.80,
    )
    fund = funds[0]
    fx.create_disbursed_drawdown(
        award["id"], 8_000_000, fx.single_line_plan(fund["id"], 8_000_000),
        initiator_user_id="officer-draw-A16b",
    )
    dd2 = fx.create_drawdown(
        award["id"], 1, fx.single_line_plan(fund["id"], 1),
        initiator_user_id="officer-draw-A16b",
    )
    resp = api.disburse_drawdown(dd2["id"], fx.make_finance_officer_headers("officer-draw-A16b"))
    validate_error(resp, ApiErrorId.ERR_CEILING_EXCEEDED.value, expected_status=409)
    # The ceiling-breaching drawdown was not disbursed; the fund headroom remains untouched by it.
    assert validate_success(api.get_drawdown(dd2["id"], FO))["status"] == "REQUESTED"
    assert validate_success(api.get_restricted_fund(fund["id"], FO))["allocated_cents"] == 8_000_000


# ==========================================================================
# Compensating invariants (Difficulty Rule 9): return conserves balances
# ==========================================================================
def test_return_conserves_award_federal_drawn(api):
    """PRD §3.5: "the award's federal_drawn_cents is decreased by the drawdown's
    amount_cents, returning the federal-drawn total to its pre-disbursement value."
    PRD §2.7: "the federal-drawn total is a conserved quantity across a disburse-then-return
    pair."

    Design: Difficulty/compensating_invariant/drawdown_return_conserves_award_federal_drawn
    """
    award, funds = fx.create_award_with_funds(
        [{"category": "PERSONNEL", "budgeted_cents": 10_000_000, "priority_order": 1}],
        nofo_number="NOFO-2026-A17", applicant_org_name="Org Q",
        requested_amount_cents=50_000_000,
    )
    fund = funds[0]
    dd = fx.create_disbursed_drawdown(
        award["id"], 6_000_000, fx.single_line_plan(fund["id"], 6_000_000),
        initiator_user_id="officer-draw-A17",
    )
    returned = validate_success(
        api.return_drawdown(dd["id"], fx.make_finance_officer_headers("officer-draw-A17"))
    )
    assert returned["status"] == "RETURNED"
    assert validate_success(api.get_award(award["id"], AO))["federal_drawn_cents"] == 0


def test_federal_drawn_returns_to_exact_pre_disburse_value(api):
    """PRD §2.7: "the federal-drawn total is a conserved quantity across a
    disburse-then-return pair."
    PRD §3.5: "the award's federal_drawn_cents is decreased by the drawdown's amount_cents,
    returning the federal-drawn total to its pre-disbursement value."

    Design: Difficulty/compensating_invariant/drawdown_return_conserves_award_federal_drawn
    """
    award, funds = fx.create_award_with_funds(
        [{"category": "PERSONNEL", "budgeted_cents": 10_000_000, "priority_order": 1}],
        nofo_number="NOFO-2026-A17b", applicant_org_name="Org Q2",
        requested_amount_cents=50_000_000,
    )
    fund = funds[0]
    before = validate_success(api.get_award(award["id"], AO))["federal_drawn_cents"]
    dd = fx.create_disbursed_drawdown(
        award["id"], 6_000_000, fx.single_line_plan(fund["id"], 6_000_000),
        initiator_user_id="officer-draw-A17b",
    )
    after_disburse = validate_success(api.get_award(award["id"], AO))["federal_drawn_cents"]
    assert after_disburse == before + 6_000_000
    validate_success(api.return_drawdown(dd["id"], fx.make_finance_officer_headers("officer-draw-A17b")))
    after_return = validate_success(api.get_award(award["id"], AO))["federal_drawn_cents"]
    assert after_return == before


def test_return_conserves_restricted_fund_allocated(api):
    """PRD §3.5: "for each of the drawdown's allocation lines, the corresponding
    restricted fund's allocated_cents is decreased by that line's amount."
    PRD §2.7: "a drawdown that is unwound must restore every category balance and the
    award's running federal-drawn total to their pre-disbursement values."

    Design: Difficulty/compensating_invariant/drawdown_return_conserves_restricted_fund_allocated
    """
    award, funds = fx.create_award_with_funds(
        [
            {"category": "PERSONNEL", "budgeted_cents": 5_000_000, "priority_order": 1},
            {"category": "TRAVEL", "budgeted_cents": 5_000_000, "priority_order": 2},
        ],
        nofo_number="NOFO-2026-A18", applicant_org_name="Org R",
        requested_amount_cents=50_000_000,
    )
    rf_a, rf_b = funds
    dd = fx.create_disbursed_drawdown(
        award["id"], 7_000_000,
        [
            {"restricted_fund_id": rf_a["id"], "amount_cents": 5_000_000},
            {"restricted_fund_id": rf_b["id"], "amount_cents": 2_000_000},
        ],
        initiator_user_id="officer-draw-A18",
    )
    returned = validate_success(
        api.return_drawdown(dd["id"], fx.make_finance_officer_headers("officer-draw-A18"))
    )
    assert returned["status"] == "RETURNED"
    assert validate_success(api.get_restricted_fund(rf_a["id"], FO))["allocated_cents"] == 0
    assert validate_success(api.get_restricted_fund(rf_b["id"], FO))["allocated_cents"] == 0


def test_return_restores_single_fund_allocated_to_zero(api):
    """PRD §3.5: "for each of the drawdown's allocation lines, the corresponding
    restricted fund's allocated_cents is decreased by that line's amount."
    PRD §3.5: "A DISBURSED drawdown may be returned by the FinanceOfficer, moving it to the
    terminal RETURNED state."

    Design: Difficulty/compensating_invariant/drawdown_return_conserves_restricted_fund_allocated
    """
    award, funds = fx.create_award_with_funds(
        [{"category": "PERSONNEL", "budgeted_cents": 5_000_000, "priority_order": 1}],
        nofo_number="NOFO-2026-A18b", applicant_org_name="Org R2",
        requested_amount_cents=50_000_000,
    )
    fund = funds[0]
    dd = fx.create_disbursed_drawdown(
        award["id"], 4_000_000, fx.single_line_plan(fund["id"], 4_000_000),
        initiator_user_id="officer-draw-A18b",
    )
    assert validate_success(api.get_restricted_fund(fund["id"], FO))["allocated_cents"] == 4_000_000
    returned = validate_success(
        api.return_drawdown(dd["id"], fx.make_finance_officer_headers("officer-draw-A18b"))
    )
    assert returned["status"] == "RETURNED"
    assert validate_success(api.get_restricted_fund(fund["id"], FO))["allocated_cents"] == 0


# ==========================================================================
# Corner: waterfall variants, allocation mismatch, immutability, derived field,
# immediate consistency
# ==========================================================================
def test_waterfall_full_fill_within_first_bucket(api):
    """PRD §3.5: "A drawdown that needs only its first eligible fund yields a single
    allocation line and leaves later funds untouched."

    Design: Corner/calculations/waterfall_full_fill_within_first_bucket_single_allocation
    """
    award, funds = fx.create_award_with_funds(
        [
            {"category": "PERSONNEL", "budgeted_cents": 5_000_000, "priority_order": 1},
            {"category": "TRAVEL", "budgeted_cents": 5_000_000, "priority_order": 2},
        ],
        nofo_number="NOFO-2026-C24", applicant_org_name="Corner Org 24",
        requested_amount_cents=50_000_000,
    )
    rf1, rf2 = funds
    dd = fx.create_drawdown(
        award["id"], 2_000_000, fx.single_line_plan(rf1["id"], 2_000_000),
        initiator_user_id="officer-draw-C24",
    )
    disbursed = fx.disburse_drawdown(dd["id"], "officer-draw-C24")
    assert disbursed["status"] == "DISBURSED"
    allocs = api.list_drawdown_allocations(dd["id"], FO).json()["data"]
    assert len(allocs) == 1
    assert validate_success(api.get_restricted_fund(rf1["id"], FO))["allocated_cents"] == 2_000_000
    assert validate_success(api.get_restricted_fund(rf2["id"], FO))["allocated_cents"] == 0


def test_allocation_plan_mismatch_returns_allocation_mismatch(api):
    """PRD §3.5: "The server's derived allocation must then equal the requester's
    allocation_plan line for line — the same fund identifiers, the same amounts, and the
    same order — or the disbursement is rejected with ERR_ALLOCATION_MISMATCH."

    Design: Corner/validations/allocation_plan_mismatch_returns_allocation_mismatch
    """
    award, funds = fx.create_award_with_funds(
        [
            {"category": "PERSONNEL", "budgeted_cents": 4_000_000, "priority_order": 1},
            {"category": "TRAVEL", "budgeted_cents": 4_000_000, "priority_order": 2},
        ],
        nofo_number="NOFO-2026-C25", applicant_org_name="Corner Org 25",
        requested_amount_cents=50_000_000,
    )
    rf1, rf2 = funds
    # Canonical waterfall for 6000000 is [4000000, 2000000]; the plan claims [3000000, 3000000].
    dd = fx.create_drawdown(
        award["id"], 6_000_000,
        [
            {"restricted_fund_id": rf1["id"], "amount_cents": 3_000_000},
            {"restricted_fund_id": rf2["id"], "amount_cents": 3_000_000},
        ],
        initiator_user_id="officer-draw-C25",
    )
    resp = api.disburse_drawdown(dd["id"], fx.make_finance_officer_headers("officer-draw-C25"))
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_MISMATCH.value, expected_status=422)
    after = validate_success(api.get_drawdown(dd["id"], FO))
    assert after["status"] == "REQUESTED"
    assert validate_success(api.get_restricted_fund(rf1["id"], FO))["allocated_cents"] == 0


def test_fund_allocation_is_immutable_no_version_field(api):
    """PRD §2.4: "A fund-allocation line — the record produced when a disbursed drawdown
    posts cash to a restricted fund — carries only id and created_at. It has no updated_at
    and no version, because it is an immutable ledger artifact."
    PRD §2.4: "Implementations must not expose updated_at or version on fund-allocation lines."

    Design: Corner/entities/fund_allocation_immutable_no_version_field_common_fields_false
    """
    award, funds = fx.create_award_with_funds(
        [{"category": "PERSONNEL", "budgeted_cents": 10_000_000, "priority_order": 1}],
        nofo_number="NOFO-2026-C9", applicant_org_name="Corner Org 9",
        requested_amount_cents=50_000_000,
    )
    fund = funds[0]
    dd = fx.create_disbursed_drawdown(
        award["id"], 5_000_000, fx.single_line_plan(fund["id"], 5_000_000),
        initiator_user_id="officer-draw-C9",
    )
    allocs = api.list_drawdown_allocations(dd["id"], FO).json()["data"]
    assert len(allocs) == 1
    row = allocs[0]
    assert row["amount_cents"] == 5_000_000
    assert_fund_allocation(row)


def test_federal_drawn_reconciles_after_two_disbursements(api):
    """PRD §3.2: "federal_drawn_cents (federal cash actually disbursed)."
    PRD §3.5: "the award's federal_drawn_cents is increased by the drawdown's amount_cents,
    keeping the federal ledger in sync."

    Design: Corner/cross_cutting_complexity_layers/derived_field_federal_drawn_reconciles_after_two_disbursements
    """
    award, funds = fx.create_award_with_funds(
        [{"category": "PERSONNEL", "budgeted_cents": 10_000_000, "priority_order": 1}],
        nofo_number="NOFO-2026-C44", applicant_org_name="Corner Org 44",
        requested_amount_cents=50_000_000,
    )
    fund = funds[0]
    fx.create_disbursed_drawdown(
        award["id"], 2_000_000, fx.single_line_plan(fund["id"], 2_000_000),
        initiator_user_id="officer-draw-C44",
    )
    fx.create_disbursed_drawdown(
        award["id"], 3_000_000, fx.single_line_plan(fund["id"], 3_000_000),
        initiator_user_id="officer-draw-C44",
    )
    assert validate_success(api.get_award(award["id"], AO))["federal_drawn_cents"] == 5_000_000
    assert validate_success(api.get_restricted_fund(fund["id"], FO))["allocated_cents"] == 5_000_000


def test_disburse_immediately_reflected_in_award_read(api):
    """PRD §2.7: "Several operations touch more than one entity in a single atomic step,
    and the secondary effects matter as much as the primary one. When a drawdown is
    disbursed, the award's running federal-drawn ledger and every affected restricted-fund
    balance move together with the drawdown's own state, and the award's version advances."

    Design: Corner/consistency_model/immediate_consistency_disburse_reflects_in_same_response
    """
    award, funds = fx.create_award_with_funds(
        [{"category": "PERSONNEL", "budgeted_cents": 10_000_000, "priority_order": 1}],
        nofo_number="NOFO-2026-C45", applicant_org_name="Corner Org 45",
        requested_amount_cents=50_000_000,
    )
    fund = funds[0]
    dd = fx.create_drawdown(
        award["id"], 4_000_000, fx.single_line_plan(fund["id"], 4_000_000),
        initiator_user_id="officer-draw-C45",
    )
    disbursed = validate_success(
        api.disburse_drawdown(dd["id"], fx.make_finance_officer_headers("officer-draw-C45"))
    )
    assert disbursed["status"] == "DISBURSED"
    award_now = validate_success(api.get_award(award["id"], FO))
    assert award_now["federal_drawn_cents"] == 4_000_000
