"""Release-fee computation (boot flat vs tow storage-accrued, capped) and release guards.

Covers difficulty rules dual_variant_calc (boot_vs_tow_release_fee) and
combinatorial_formula (tow_release_fee_nested_min), plus corner validations
(release_fee_wrong_amount, release_with_balance).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, TEST_USERS,
    setup_boot_and_tow_applied, setup_applied_tow_order, setup_applied_boot_order,
    make_owner_headers,
)

EO = TEST_USERS["enforcement_officer_headers"]


# ─── dual_variant_calc / boot_vs_tow_release_fee ───────────────────────────

def test_boot_release_fee_is_flat(api):
    """PRD §3.6: "release fee is a flat BOOT_FEE_CENTS of 15,000 cents (one hundred
    fifty dollars) plus an ADMIN_FEE_CENTS of 5,000 cents (fifty dollars), with no storage
    accrual."

    Design: Difficulty/dual_variant_calc/boot_vs_tow_release_fee
    """
    boot_order, _ = setup_boot_and_tow_applied(
        final_clock="2026-06-06T00:00:00Z",
        tow_stored_from="2026-06-01T00:00:00Z", tow_stored_until="2026-06-30T00:00:00Z")
    fresh = validate_success(api.get_boot_tow_order(boot_order["id"], EO), 200)
    assert fresh["release_fee_cents"] == 20000


def test_tow_release_fee_includes_storage_days(api):
    """PRD §3.6: "release fee is TOW_FEE_CENTS of 25,000 cents (two hundred fifty
    dollars) plus the same ADMIN_FEE_CENTS of 5,000 cents, plus storage: the number of
    storage days is the elapsed time from stored_from to the as-of instant, rounded up to
    whole days and never negative, then capped at MAX_STORAGE_DAYS of 30 days, and that
    capped day count is multiplied by the DAILY_STORAGE_RATE_CENTS of 4,000 cents (forty
    dollars) per day."

    Design: Difficulty/dual_variant_calc/boot_vs_tow_release_fee
    """
    boot_order, tow_order = setup_boot_and_tow_applied(
        final_clock="2026-06-06T00:00:00Z",
        tow_stored_from="2026-06-01T00:00:00Z", tow_stored_until="2026-06-30T00:00:00Z")
    boot_fee = validate_success(api.get_boot_tow_order(boot_order["id"], EO), 200)["release_fee_cents"]
    tow_fee = validate_success(api.get_boot_tow_order(tow_order["id"], EO), 200)["release_fee_cents"]
    # 25000 + 5000 + 5 storage days * 4000 = 50000
    assert tow_fee == 50000
    assert tow_fee != boot_fee


# ─── combinatorial_formula / tow_release_fee_nested_min ────────────────────

def test_tow_storage_capped_at_max_days(api):
    """PRD §3.6: "the number of storage days is the elapsed time from stored_from to the
    as-of instant, rounded up to whole days and never negative, then capped at
    MAX_STORAGE_DAYS of 30 days, and that capped day count is multiplied by the
    DAILY_STORAGE_RATE_CENTS of 4,000 cents (forty dollars) per day."

    Design: Difficulty/combinatorial_formula/tow_release_fee_nested_min
    """
    # stored_from 2026-06-01, clock 2026-07-11 -> 40 days -> capped 30 -> 25000+5000+30*4000
    _, _, _, _, order = setup_applied_tow_order(
        stored_from="2026-06-01T00:00:00Z", stored_until="2026-08-01T00:00:00Z",
        final_clock="2026-07-11T00:00:00Z")
    fresh = validate_success(api.get_boot_tow_order(order["id"], EO), 200)
    assert fresh["release_fee_cents"] == 150000


def test_tow_storage_stays_capped_far_beyond_max(api):
    """PRD §3.6: "the number of storage days is the elapsed time from stored_from to the
    as-of instant, rounded up to whole days and never negative, then capped at
    MAX_STORAGE_DAYS of 30 days, and that capped day count is multiplied by the
    DAILY_STORAGE_RATE_CENTS of 4,000 cents (forty dollars) per day."

    Design: Difficulty/combinatorial_formula/tow_release_fee_nested_min
    """
    # ~92 days elapsed, still capped at 30 -> 150000
    _, _, _, _, order = setup_applied_tow_order(
        stored_from="2026-06-01T00:00:00Z", stored_until="2026-08-01T00:00:00Z",
        final_clock="2026-09-01T00:00:00Z")
    fresh = validate_success(api.get_boot_tow_order(order["id"], EO), 200)
    assert fresh["release_fee_cents"] == 150000


# ─── corner: pay-release-fee wrong amount ──────────────────────────────────

def test_pay_release_fee_wrong_amount_rejected(api):
    """PRD §3.6: "The owner pays by submitting amount_cents, which must equal the order's
    current release_fee_cents; any other amount is rejected with ERR_RELEASE_FEE_UNPAID
    (HTTP 409)."

    Design: Corner/validations/release_fee_wrong_amount_rejected
    """
    owner, _, _, order = setup_applied_boot_order(fine_each=13000, count=5)
    res = api.pay_release_fee(order["id"], {"amount_cents": 999}, make_owner_headers(owner["id"]))
    validate_error(res, "ERR_RELEASE_FEE_UNPAID", expected_status=409)


# ─── corner: release with outstanding balance ──────────────────────────────

def test_release_with_outstanding_balance_rejected(api):
    """PRD §3.6: "Releasing the order requires it to be APPLIED, release_fee_paid to be
    true, and the owning case's collectible_balance_cents to be exactly 0."
    PRD §3.6: "a release attempted while the case still carries a collectible balance is
    rejected with ERR_BALANCE_OUTSTANDING (HTTP 409)."

    Design: Corner/validations/release_with_balance_rejected
    """
    owner, _, case, order = setup_applied_boot_order(fine_each=13000, count=5)
    # Pay the exact boot release fee (20000) so release_fee_paid becomes true.
    validate_success(api.pay_release_fee(
        order["id"], {"amount_cents": 20000}, make_owner_headers(owner["id"])), 200)
    res = api.release_order(order["id"], EO)
    validate_error(res, "ERR_BALANCE_OUTSTANDING", expected_status=409)
