"""Ringing sales: split base, consignor proceeds, and the two payout channels.

Covers the dual-variant split (GROSS vs NET) and payout (CASH vs STORE_CREDIT)
difficulty instances, the tiered store-credit bonus and its boundary, plus
sale-line immutability, duplicate-line rejection, and FK reverse-reachability.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    assert_sale_line,
    create_sale_payload,
    TEST_USERS,
    set_clock, setup_on_floor_item, setup_sold_item,
)

ADMIN = TEST_USERS["store_admin_headers"]
GRADER = TEST_USERS["intake_grader_headers"]
CASHIER = TEST_USERS["cashier_clerk_headers"]
SETTLER = TEST_USERS["settlement_manager_headers"]


# ─── Difficulty: dual-variant calc — GROSS vs NET split base ─────────────────

def test_gross_vs_net_split_base_diverges(api):
    """PRD §3.5: "Under `GROSS` basis the split base equals the line's
    `sold_price_cents`; the per-line `processing_fee_cents` is ignored and the
    store absorbs it from its own share. Under `NET` basis the split base is the
    line's `sold_price_cents` minus its `processing_fee_cents`, but never less
    than zero ... that configured fee is 150 cents."

    Design: Difficulty/dual_variant_calc/split_basis_gross_vs_net_diverge_on_saleline
    """
    set_clock("2026-06-01T00:00:00Z")
    _, _, _, sale_g = setup_sold_item(
        split_basis="GROSS", payout_method="CASH", list_price_cents=8000,
        consignor_email="gross@x.com", consignor_name="Gross Gail")
    _, _, _, sale_n = setup_sold_item(
        split_basis="NET", payout_method="CASH", list_price_cents=8000,
        consignor_email="net@x.com", consignor_name="Net Ned")
    line_g = validate_success(api.list_sale_lines(sale_g["id"], CASHIER), 200)
    line_n = validate_success(api.list_sale_lines(sale_n["id"], CASHIER), 200)
    assert line_g[0]["split_base_cents"] == 8000
    assert line_n[0]["split_base_cents"] == 7850, (
        f"NET base = 8000-150 = 7850, got {line_n[0]['split_base_cents']}")


def test_gross_vs_net_consignor_proceeds_diverge(api):
    """PRD §3.5: "the line's `consignor_proceeds_cents` is the `split_base_cents`
    multiplied by the agreement's `split_pct`, rounded half up to a whole cent."

    Design: Difficulty/dual_variant_calc/split_basis_gross_vs_net_diverge_on_saleline
    """
    set_clock("2026-06-01T00:00:00Z")
    _, _, _, sale_g = setup_sold_item(
        split_basis="GROSS", payout_method="CASH", list_price_cents=8000,
        consignor_email="gross2@x.com", consignor_name="Gross Two")
    _, _, _, sale_n = setup_sold_item(
        split_basis="NET", payout_method="CASH", list_price_cents=8000,
        consignor_email="net2@x.com", consignor_name="Net Two")
    line_g = validate_success(api.list_sale_lines(sale_g["id"], CASHIER), 200)
    line_n = validate_success(api.list_sale_lines(sale_n["id"], CASHIER), 200)
    assert_sale_line(line_g[0])
    assert line_g[0]["consignor_proceeds_cents"] == 4000, (
        f"GROSS proceeds round_half_up(8000*0.5)=4000, got {line_g[0]['consignor_proceeds_cents']}")
    assert line_n[0]["consignor_proceeds_cents"] == 3925, (
        f"NET proceeds round_half_up(7850*0.5)=3925, got {line_n[0]['consignor_proceeds_cents']}")


# ─── Difficulty: dual-variant calc — CASH vs STORE_CREDIT payout ─────────────

def test_cash_payout_credits_unsettled_payable(api):
    """PRD §3.6: "When the agreement pays out in `CASH`, the sale appends a
    `PayoutLedgerEntry` for the line with an `entry_type` of `SALE_PAYOUT` and an
    `amount_cents` equal to the positive `consignor_proceeds_cents` ... Creating
    the entry causes the consignor's `unsettled_payable_cents` to be recomputed."

    Design: Difficulty/dual_variant_calc/cash_payout_vs_store_credit_payout_diverge_on_consignor
    """
    set_clock("2026-06-01T00:00:00Z")
    consignor, _, _, _ = setup_sold_item(
        split_basis="GROSS", payout_method="CASH", list_price_cents=8000,
        consignor_email="cash@x.com", consignor_name="Cash Cara")
    after = validate_success(api.get_consignor(consignor["id"], ADMIN), 200)
    assert after["unsettled_payable_cents"] == 4000, (
        f"expected 4000 cash payable, got {after['unsettled_payable_cents']}")
    assert after["store_credit_cents"] == 0


def test_store_credit_payout_issues_proceeds_plus_bonus(api):
    """PRD §3.6: "The **store-credit payout** takes the line's
    `consignor_proceeds_cents` as its base and adds a bonus that steps with the
    size of that base ... if the base is at least 2,000 cents — twenty dollars or
    more — the bonus is the base multiplied by 0.10, rounded half up ... The
    issued amount is the base plus the bonus."

    Design: Difficulty/dual_variant_calc/cash_payout_vs_store_credit_payout_diverge_on_consignor
    """
    set_clock("2026-06-01T00:00:00Z")
    consignor, _, _, _ = setup_sold_item(
        split_basis="GROSS", payout_method="STORE_CREDIT", list_price_cents=8000,
        consignor_email="credit@x.com", consignor_name="Credit Cleo")
    after = validate_success(api.get_consignor(consignor["id"], ADMIN), 200)
    assert after["store_credit_cents"] == 4400, (
        f"4000 proceeds + 10% bonus 400 = 4400, got {after['store_credit_cents']}")
    assert after["unsettled_payable_cents"] == 0


# ─── Difficulty: combinatorial formula — tiered nonlinear bonus branch ───────

def test_store_credit_bonus_tier2_at_proceeds_10000(api):
    """PRD §3.6: "If the base is at least 10,000 cents — that is, one hundred
    dollars or more — the bonus is the base multiplied by 0.20, rounded half up to
    a whole cent ... a base of exactly 10,000 cents earns the twenty-percent tier."

    Design: Difficulty/combinatorial_formula/store_credit_bonus_tiered_nonlinear_branch
    """
    set_clock("2026-06-01T00:00:00Z")
    consignor, _, _, _ = setup_sold_item(
        split_basis="GROSS", payout_method="STORE_CREDIT", list_price_cents=20000,
        consignor_email="t2@x.com", consignor_name="Tier Two Tina")
    after = validate_success(api.get_consignor(consignor["id"], ADMIN), 200)
    assert after["store_credit_cents"] == 12000, (
        f"10000 proceeds + 20% bonus 2000 = 12000, got {after['store_credit_cents']}")
    txns = validate_success(
        api.list_consignor_store_credit_transactions(consignor["id"], ADMIN), 200)
    assert txns[0]["amount_cents"] == 12000


def test_store_credit_bonus_tier1_just_below_tier2(api):
    """PRD §3.6: "a base of 9,999 cents earns only the ten-percent tier."

    Design: Difficulty/combinatorial_formula/store_credit_bonus_tiered_nonlinear_branch
    """
    set_clock("2026-06-01T00:00:00Z")
    # list 19998, GROSS split 0.50 -> proceeds round_half_up(19998*0.5)=9999;
    # bonus round_half_up(9999*0.10)=1000; issued 10999.
    consignor, _, _, _ = setup_sold_item(
        split_basis="GROSS", payout_method="STORE_CREDIT", list_price_cents=19998,
        consignor_email="t1edge@x.com", consignor_name="Tier One Edge")
    after = validate_success(api.get_consignor(consignor["id"], ADMIN), 200)
    assert after["store_credit_cents"] == 10999, (
        f"9999 proceeds + 10% bonus 1000 = 10999, got {after['store_credit_cents']}")


# ─── Difficulty: boundary precision — tier-1 bonus boundary at 2000 ──────────

def test_store_credit_bonus_at_tier1_boundary_2000(api):
    """PRD §3.6: "The boundaries are inclusive: a base of exactly 2,000 cents earns
    the ten-percent tier."

    Design: Difficulty/boundary_precision_check/store_credit_bonus_tier1_boundary_at_2000
    """
    set_clock("2026-06-01T00:00:00Z")
    consignor, _, _, _ = setup_sold_item(
        split_basis="GROSS", payout_method="STORE_CREDIT", list_price_cents=4000,
        consignor_email="edgeat@x.com", consignor_name="Edge At")
    after = validate_success(api.get_consignor(consignor["id"], ADMIN), 200)
    assert after["store_credit_cents"] == 2200, (
        f"2000 proceeds + 10% bonus 200 = 2200, got {after['store_credit_cents']}")


def test_store_credit_no_bonus_below_tier1_boundary(api):
    """PRD §3.6: "Below 2,000 cents there is no bonus ... The issued amount is the
    base plus the bonus."

    Design: Difficulty/boundary_precision_check/store_credit_bonus_tier1_boundary_at_2000
    """
    set_clock("2026-06-01T00:00:00Z")
    # list 3998, GROSS split 0.50 -> proceeds round_half_up(3998*0.5)=1999 (< 2000).
    consignor, _, _, _ = setup_sold_item(
        split_basis="GROSS", payout_method="STORE_CREDIT", list_price_cents=3998,
        consignor_email="edgebelow@x.com", consignor_name="Edge Below")
    after = validate_success(api.get_consignor(consignor["id"], ADMIN), 200)
    assert after["store_credit_cents"] == 1999, (
        f"1999 proceeds, no bonus -> 1999, got {after['store_credit_cents']}")


# ─── Corner: sale-line immutability ──────────────────────────────────────────

def test_saleline_is_immutable_no_version_field(api):
    """PRD §2.4: "Three entities are append-only ledger records rather than mutable
    resources and therefore carry only `id` and `created_at` — they have no
    `updated_at` and no `version`. These are the `SaleLine` (a child line of a
    `Sale`), the `PayoutLedgerEntry`, and the `StoreCreditTransaction`."

    Design: Corner/entities/saleline_is_immutable_no_version_field
    """
    set_clock("2026-06-01T00:00:00Z")
    _, _, _, sale = setup_sold_item(list_price_cents=5000, consignor_email="imm@x.com")
    lines = validate_success(api.list_sale_lines(sale["id"], CASHIER), 200)
    assert len(lines) == 1
    line = lines[0]
    assert "id" in line and "created_at" in line
    assert "version" not in line, "SaleLine must not carry a version field"
    assert "updated_at" not in line, "SaleLine must not carry updated_at"


# ─── Corner: duplicate sale line ─────────────────────────────────────────────

def test_duplicate_sale_line_same_item_returns_409(api):
    """PRD §3.5: "The same `item_id` may appear at most once across all the lines
    of a single sale — no double-ringing one garment — and a duplicate is rejected
    with `ERR_DUPLICATE_SALE_LINE`."

    Design: Corner/validations/duplicate_sale_line_same_item_returns_409
    """
    set_clock("2026-06-01T00:00:00Z")
    _, _, _, _, item = setup_on_floor_item(list_price_cents=5000, consignor_email="dupdel@x.com")
    res = api.create_sale(
        create_sale_payload(lines=[{"item_id": item["id"]}, {"item_id": item["id"]}]),
        CASHIER)
    validate_error(res, "ERR_DUPLICATE_SALE_LINE", expected_status=409)


# ─── Corner: FK reverse-reachability ─────────────────────────────────────────

def test_item_sale_lines_reverse_reachable(api):
    """PRD §4: "GET `/items/{id}/sale-lines` — List sale lines referencing an item".
    PRD §3.5: "the server creates a `SaleLine` capturing its `sale_id`, the
    `item_id`, and the `consignor_id` copied from the item for ledger attribution".

    Design: Corner/endpoints/fk_saleline_to_item_reverse_reachable_via_item_sale_lines
    """
    set_clock("2026-06-01T00:00:00Z")
    _, _, item, _ = setup_sold_item(list_price_cents=5000, consignor_email="sl@x.com")
    lines = validate_success(api.list_item_sale_lines(item["id"], SETTLER), 200)
    assert len(lines) == 1, f"expected 1 sale line for item, got {len(lines)}"
    assert lines[0]["item_id"] == item["id"]
