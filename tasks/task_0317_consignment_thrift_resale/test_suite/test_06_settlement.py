"""The daily settlement: branching, rollup totals, sweep, and concurrency.

Covers the settlement branching and round-per-line-then-sum difficulty instances
plus corner instances for empty finalize, date uniqueness, void-frees-date,
terminal lockdown, sweep reconciliation, and the OCC stale-version rejection.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    assert_settlement,
    create_settlement_payload, create_sale_payload,
    create_intake_batch_payload, create_item_payload, grade_accept_payload,
    finalize_settlement_payload,
    TEST_USERS,
    set_clock, setup_agreement, open_settlement, finalize_settlement,
    setup_sold_item,
)

ADMIN = TEST_USERS["store_admin_headers"]
GRADER = TEST_USERS["intake_grader_headers"]
CASHIER = TEST_USERS["cashier_clerk_headers"]
SETTLER = TEST_USERS["settlement_manager_headers"]


# ─── Difficulty: non-linear state machine — settlement branching ─────────────

def test_open_settlement_void_branch(api):
    """PRD §3.9: "An `OPEN` settlement may be voided by a `SettlementManager`,
    advancing it `OPEN → VOIDED`, which frees its `business_date` for a fresh
    settlement".

    Design: Difficulty/non_linear_state_machine/settlement_branching_open_to_finalized_or_voided
    """
    s3 = open_settlement("2026-06-03")
    voided = validate_success(api.void_settlement(s3["id"], SETTLER), 200)
    assert voided["status"] == "VOIDED"


def test_open_settlement_finalize_branch_empty(api):
    """PRD §3.9: "A `SettlementManager` finalizes an `OPEN` settlement, advancing
    it `OPEN → FINALIZED`."
    PRD §3.9: "The `swept_sale_count` is the count of sales swept into the
    settlement."

    Design: Difficulty/non_linear_state_machine/settlement_branching_open_to_finalized_or_voided
    """
    s4 = open_settlement("2026-06-04")
    finalized = validate_success(api.finalize_settlement(
        s4["id"], finalize_settlement_payload(s4["version"]), SETTLER), 200)
    assert finalized["status"] == "FINALIZED"
    assert finalized["swept_sale_count"] == 0


# ─── Difficulty: combinatorial formula — round-per-line-then-sum ─────────────

def _setup_two_net_lines_sold(business_date, clock_iso, email):
    """One CASH NET consignor (split 0.50) with two items priced 8001 sold in a
    single sale on `business_date`, plus an OPEN settlement for that date."""
    set_clock(clock_iso)
    _, _, agreement = setup_agreement(
        split_pct=0.50, split_basis="NET", payout_method="CASH",
        consignor_email=email, consignor_name="Round Rita")
    batch = validate_success(api_client.create_intake_batch(
        create_intake_batch_payload(agreement["id"]), GRADER), 201)
    item_ids = []
    for title in ("Coat A", "Coat B"):
        item = validate_success(api_client.create_item(
            create_item_payload(batch["id"], title=title), GRADER), 201)
        graded = validate_success(api_client.grade_item(
            item["id"], grade_accept_payload(8001, item["version"]), GRADER), 200)
        validate_success(api_client.list_item(graded["id"], GRADER), 200)
        item_ids.append(graded["id"])
    validate_success(api_client.create_sale(
        create_sale_payload(lines=[{"item_id": i} for i in item_ids]), CASHIER), 201)
    return open_settlement(business_date)


def test_settlement_payable_round_per_line_then_sum(api):
    """PRD §3.9: "Each of these sums is taken over per-line values that were
    already rounded at sale time; the settlement sums those rounded integers and
    does not re-derive a single split on the gross total and round once — this
    round-per-line-then-sum ordering is fixed and can differ from a sum-then-round
    by up to one cent per line."

    Design: Difficulty/combinatorial_formula/settlement_round_per_line_then_sum_order_pinned
    """
    settlement = _setup_two_net_lines_sold(
        "2026-06-02", "2026-06-02T09:00:00Z", "round@x.com")
    finalized = validate_success(api.finalize_settlement(
        settlement["id"], finalize_settlement_payload(settlement["version"]), SETTLER), 200)
    # Per line: NET base 8001-150=7851; round_half_up(7851*0.5)=3926; x2 = 7852.
    assert finalized["total_consignor_payable_cents"] == 7852, (
        f"round-per-line then sum -> 7852, got {finalized['total_consignor_payable_cents']}")


def test_settlement_total_gross_sums_line_prices(api):
    """PRD §3.9: "The `total_gross_cents` is the sum of `gross_total_cents` across
    the in-scope `COMPLETED` sales."

    Design: Difficulty/combinatorial_formula/settlement_round_per_line_then_sum_order_pinned
    """
    settlement = _setup_two_net_lines_sold(
        "2026-06-12", "2026-06-12T09:00:00Z", "round2@x.com")
    finalized = validate_success(api.finalize_settlement(
        settlement["id"], finalize_settlement_payload(settlement["version"]), SETTLER), 200)
    assert finalized["total_gross_cents"] == 16002, (
        f"8001 + 8001 = 16002, got {finalized['total_gross_cents']}")


# ─── Difficulty: boundary precision — empty settlement finalize ──────────────

def test_empty_settlement_finalize_status_and_count(api):
    """PRD §3.9: "A settlement is opened for a `business_date` ... and starts in
    `OPEN` status with all its totals at zero."
    PRD §3.9: "The `swept_sale_count` is the count of sales swept into the
    settlement."

    Design: Difficulty/boundary_precision_check/empty_settlement_zero_sales_finalize
    """
    settlement = open_settlement("2026-07-01")
    finalized = validate_success(api.finalize_settlement(
        settlement["id"], finalize_settlement_payload(settlement["version"]), SETTLER), 200)
    assert finalized["status"] == "FINALIZED"
    assert finalized["swept_sale_count"] == 0


def test_empty_settlement_finalize_zero_totals(api):
    """PRD §3.9: "The `total_gross_cents` is the sum of `gross_total_cents` across
    the in-scope `COMPLETED` sales. The `total_consignor_payable_cents` is the sum
    of `consignor_proceeds_cents` across every `SaleLine` of the in-scope sales
    whose agreement pays out in `CASH`."

    Design: Difficulty/boundary_precision_check/empty_settlement_zero_sales_finalize
    """
    settlement = open_settlement("2026-07-02")
    finalized = validate_success(api.finalize_settlement(
        settlement["id"], finalize_settlement_payload(settlement["version"]), SETTLER), 200)
    assert finalized["total_gross_cents"] == 0
    assert finalized["total_consignor_payable_cents"] == 0


# ─── Difficulty: resource temporal overlap — settlement date uniqueness ──────

def test_second_settlement_same_date_returns_date_taken(api):
    """PRD §3.9: "At most one non-`VOIDED` settlement may exist for any given
    `business_date`; opening a second while a non-voided one already covers that
    date is rejected with `ERR_SETTLEMENT_DATE_TAKEN`."

    Design: Difficulty/resource_temporal_overlap/settlement_date_uniqueness_non_voided_overlap
    """
    open_settlement("2026-06-06")
    res = api.create_settlement(create_settlement_payload("2026-06-06"), SETTLER)
    validate_error(res, "ERR_SETTLEMENT_DATE_TAKEN", expected_status=409)


def test_existing_open_settlement_survives_rejected_duplicate(api):
    """PRD §3.9: "At most one non-`VOIDED` settlement may exist for any given
    `business_date`; opening a second while a non-voided one already covers that
    date is rejected with `ERR_SETTLEMENT_DATE_TAKEN`."

    Design: Difficulty/resource_temporal_overlap/settlement_date_uniqueness_non_voided_overlap
    """
    s1 = open_settlement("2026-06-16")
    validate_error(
        api.create_settlement(create_settlement_payload("2026-06-16"), SETTLER),
        "ERR_SETTLEMENT_DATE_TAKEN", expected_status=409)
    read = validate_success(api.get_settlement(s1["id"], SETTLER), 200)
    assert read["status"] == "OPEN", "the original OPEN settlement is unaffected"


# ─── Corner: void frees date ─────────────────────────────────────────────────

def test_void_open_settlement_frees_date_for_new_settlement(api):
    """PRD §3.9: "An `OPEN` settlement may be voided by a `SettlementManager`,
    advancing it `OPEN → VOIDED`, which frees its `business_date` for a fresh
    settlement".

    Design: Corner/state_machines/void_open_settlement_frees_date_for_new_settlement
    """
    s1 = open_settlement("2026-09-01")
    validate_success(api.void_settlement(s1["id"], SETTLER), 200)
    s2 = validate_success(api.create_settlement(
        create_settlement_payload("2026-09-01"), SETTLER), 201)
    assert s2["status"] == "OPEN"


# ─── Corner: terminal lockdown ───────────────────────────────────────────────

def test_terminal_settlement_void_after_finalize_returns_invalid_state(api):
    """PRD §3.9: "a `FINALIZED` settlement can never be voided."
    PRD §3.9: "finalizing a settlement that is not `OPEN` is rejected with
    `ERR_INVALID_STATE`".

    Design: Corner/state_machines/terminal_settlement_void_after_finalize_returns_invalid_state
    """
    s1 = open_settlement("2026-09-02")
    finalize_settlement(s1)
    res = api.void_settlement(s1["id"], SETTLER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Corner: sweep reconciliation ────────────────────────────────────────────

def test_settlement_finalize_sweeps_ledger_derived_reconciliation(api):
    """PRD §3.9: "Each affected consignor then has their `unsettled_payable_cents`
    recomputed — the now-settled entries drop out of it — and their
    `lifetime_payout_cents` recomputed — the now-settled `SALE_PAYOUT` entries
    enter it."

    Design: Corner/cross_cutting_complexity_layers/settlement_finalize_sweeps_ledger_derived_reconciliation
    """
    set_clock("2026-06-22T08:00:00Z")
    consignor, _, _, _ = setup_sold_item(
        split_basis="GROSS", payout_method="CASH", list_price_cents=8000,
        consignor_email="sweep@x.com", consignor_name="Sweep Sal")
    settlement = open_settlement("2026-06-22")
    finalized = finalize_settlement(settlement)
    after = validate_success(api.get_consignor(consignor["id"], ADMIN), 200)
    assert after["unsettled_payable_cents"] == 0, (
        f"settled entries drop out of payable, got {after['unsettled_payable_cents']}")
    assert after["lifetime_payout_cents"] == 4000, (
        f"settled SALE_PAYOUT enters lifetime, got {after['lifetime_payout_cents']}")
    assert finalized["total_consignor_payable_cents"] == 4000


# ─── Corner: OCC stale settlement version ────────────────────────────────────

def test_finalize_with_stale_version_returns_412(api):
    """PRD §2.8: "Finalizing a settlement requires the request to carry
    `expected_settlement_version`, which must equal the target `DailySettlement`'s
    current `version`. If the settlement's `version` has advanced since the client
    last read it, the finalize is rejected with `ERR_STALE_SETTLEMENT_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_settlement_stale_version_rejected_corner
    """
    settlement = open_settlement("2026-06-21")
    stale = settlement["version"] - 1  # one below current -> stale
    res = api.finalize_settlement(
        settlement["id"], finalize_settlement_payload(stale), SETTLER)
    validate_error(res, "ERR_STALE_SETTLEMENT_VERSION", expected_status=412)
    read = validate_success(api.get_settlement(settlement["id"], SETTLER), 200)
    assert read["status"] == "OPEN", "a rejected finalize leaves the settlement OPEN"
