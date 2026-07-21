"""Program maintenance: dual-variant breakage (ESTIMATED vs REMITTANCE),
per-card rounding order, the expiry->breakage cascade, dormancy accrual, and
escheat capture/remit.

Covers Difficulty dual_variant_calc (breakage), combinatorial_formula (estimated
rounding), transitive_cascade (expiry) plus Corner dormancy/escheat instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_escheat_report_payload,
    TEST_USERS, make_settlement_officer_headers,
    setup_multi_active_cards, setup_expired_card_pending_maintenance,
    setup_single_active_card, setup_escheatable_expired_card,
    set_clock, create_active_merchant, api_client,
)

PLATFORM = TEST_USERS["platform_admin_headers"]
ANY = TEST_USERS["any_headers"]
OFFICER_1 = make_settlement_officer_headers("officer-1")


# ─────────── Difficulty: ESTIMATED vs REMITTANCE breakage ───────────

def test_estimated_program_recognizes_ten_percent_without_forfeit(api):
    """PRD §3.6: "for a program whose `breakage_method` is `ESTIMATED`, maintenance recomputes `breakage_recognized_cents` as the sum, over the program's `ACTIVE` cards, of each card's balance multiplied by 1000 basis points divided by 10000 (that is, ten percent of the card's balance), rounded half up to a whole cent per card and then summed — value is recognized progressively this way without forfeiting any card's balance."

    Design: Difficulty/dual_variant_calc/breakage_estimated_vs_remittance
    """
    _merchant, program, _batch, cards = setup_multi_active_cards(
        1, 100000, program_overrides={"breakage_method": "ESTIMATED"})
    after = validate_success(api.run_maintenance(program["id"], PLATFORM), 200)
    assert after["breakage_recognized_cents"] == 10000
    card = validate_success(api.get_gift_card(cards[0]["id"], ANY), 200)
    assert card["status"] == "ACTIVE"
    assert card["balance_cents"] == 100000


def test_remittance_program_recognizes_nothing_before_expiry(api):
    """PRD §3.6: "Under `REMITTANCE`, `breakage_recognized_cents` is the sum of the magnitudes of the `BREAKAGE` entries created when cards actually expire with a positive balance, and an `ACTIVE`, un-expired card contributes nothing."

    Design: Difficulty/dual_variant_calc/breakage_estimated_vs_remittance
    """
    _merchant, program, _batch, _cards = setup_multi_active_cards(
        1, 100000, program_overrides={"breakage_method": "REMITTANCE"})
    after = validate_success(api.run_maintenance(program["id"], PLATFORM), 200)
    assert after["breakage_recognized_cents"] == 0


# ─────────── Difficulty: estimated per-card rounding order ───────────

def test_estimated_breakage_rounds_per_card_then_sums(api):
    """PRD §3.6: "for a program whose `breakage_method` is `ESTIMATED`, maintenance recomputes `breakage_recognized_cents` as the sum, over the program's `ACTIVE` cards, of each card's balance multiplied by 1000 basis points divided by 10000 (that is, ten percent of the card's balance), rounded half up to a whole cent per card and then summed — value is recognized progressively this way without forfeiting any card's balance."

    Design: Difficulty/combinatorial_formula/estimated_breakage_rounding_order_mode_b
    """
    # Two cards each balance 505: round_half_up(50.5)=51 per card, sum 102
    # (NOT round(sum 101.0)=101).
    _merchant, program, _batch, _cards = setup_multi_active_cards(
        2, 505, program_overrides={"breakage_method": "ESTIMATED"})
    after = validate_success(api.run_maintenance(program["id"], PLATFORM), 200)
    assert after["breakage_recognized_cents"] == 102


def test_estimated_breakage_single_card_rounds_half_up(api):
    """PRD §3.6: "for a program whose `breakage_method` is `ESTIMATED`, maintenance recomputes `breakage_recognized_cents` as the sum, over the program's `ACTIVE` cards, of each card's balance multiplied by 1000 basis points divided by 10000 (that is, ten percent of the card's balance), rounded half up to a whole cent per card and then summed — value is recognized progressively this way without forfeiting any card's balance."

    Design: Difficulty/combinatorial_formula/estimated_breakage_rounding_order_mode_b
    """
    # Single card balance 505: round_half_up(50.5) = 51.
    _merchant, program, _batch, _cards = setup_multi_active_cards(
        1, 505, program_overrides={"breakage_method": "ESTIMATED"})
    after = validate_success(api.run_maintenance(program["id"], PLATFORM), 200)
    assert after["breakage_recognized_cents"] == 51


# ─────────── Difficulty: expiry -> breakage cascade (REMITTANCE) ───────────

def test_expiry_forfeits_balance_to_zero(api):
    """PRD §3.6: "any `ACTIVE` card whose `expires_at` is at or before the current clock transitions to `EXPIRED`. If the program's `breakage_method` is `REMITTANCE` and such a card still has a positive balance, the system posts a `BREAKAGE` ledger entry with a negative `amount_cents` equal to the full remaining balance, forfeiting it; that forfeited magnitude raises the program's `breakage_recognized_cents`."

    Design: Difficulty/transitive_cascade/card_expiry_breakage_program_cascade
    """
    _merchant, program, card = setup_expired_card_pending_maintenance(
        breakage_method="REMITTANCE", unit_load_cents=30000)
    validate_success(api.run_maintenance(program["id"], PLATFORM), 200)
    card_after = validate_success(api.get_gift_card(card["id"], ANY), 200)
    assert card_after["status"] == "EXPIRED"
    assert card_after["balance_cents"] == 0


def test_expiry_breakage_raises_program_recognized(api):
    """PRD §3.6: "any `ACTIVE` card whose `expires_at` is at or before the current clock transitions to `EXPIRED`. If the program's `breakage_method` is `REMITTANCE` and such a card still has a positive balance, the system posts a `BREAKAGE` ledger entry with a negative `amount_cents` equal to the full remaining balance, forfeiting it; that forfeited magnitude raises the program's `breakage_recognized_cents`."

    Design: Difficulty/transitive_cascade/card_expiry_breakage_program_cascade
    """
    _merchant, program, _card = setup_expired_card_pending_maintenance(
        breakage_method="REMITTANCE", unit_load_cents=30000)
    after = validate_success(api.run_maintenance(program["id"], PLATFORM), 200)
    assert after["breakage_recognized_cents"] == 30000


# ─────────── Corner: dormancy accrual at the inclusive threshold ───────────

def test_dormancy_fee_accrues_at_365_days(api):
    """PRD §3.6: "for each `ACTIVE` card whose inactivity since `last_activity_at` is at least 365 days and whose balance is positive, the system posts a `DORMANCY_FEE` entry with a negative `amount_cents` equal to the lesser of 200 cents and the card's current balance, so the fee never drives a balance below 0; the inactivity boundary is inclusive, meaning exactly 365 days of inactivity counts as dormant."

    Design: Corner/calculations/dormancy_fee_accrues_at_threshold
    """
    # expiry_months 60 so the card does not expire at 365 days.
    _merchant, program, _batch, card = setup_single_active_card(
        10000, program_overrides={"expiry_months": 60})
    set_clock("2027-07-01T00:00:00Z")  # exactly 365 days after the default activation
    validate_success(api.run_maintenance(program["id"], PLATFORM), 200)
    card_after = validate_success(api.get_gift_card(card["id"], ANY), 200)
    assert card_after["status"] == "ACTIVE"
    assert card_after["balance_cents"] == 9800


# ─────────── Corner: escheat period + remit ───────────

def test_escheat_report_future_period_rejected(api):
    """PRD §3.8: "the `period_end` must be at or before the current clock, and a report whose period_end lies in the open future is rejected with `ERR_ESCHEAT_PERIOD_OPEN`."

    Design: Corner/validations/escheat_future_period_returns_period_open
    """
    merchant = create_active_merchant()
    res = api.create_escheat_report(
        create_escheat_report_payload(
            merchant["id"], "CA", "2026-07-01T00:00:00Z", "2030-01-01T00:00:00Z"), OFFICER_1)
    validate_error(res, "ERR_ESCHEAT_PERIOD_OPEN")


def test_escheat_remit_transitions_expired_card_to_escheated(api):
    """PRD §3.8: "At creation the report captures the eligible cards — the merchant's cards in `EXPIRED` status whose `expires_at` falls at or after `period_start` and strictly before `period_end` — and stores the computed `escheat_total_cents` (the sum of those captured cards' balances) and `card_count` (the number captured)."
    PRD §3.8: "on remit each captured `EXPIRED` card transitions to the terminal `ESCHEATED` state and the system posts an `ESCHEAT_REMIT` ledger entry for any residual balance on each captured card, moving the report to the terminal `REMITTED` state."

    Design: Corner/state_machines/escheat_remit_transitions_expired_card_to_escheated
    """
    _merchant, _program, card, report = setup_escheatable_expired_card(30000)
    assert report["escheat_total_cents"] == 30000
    assert report["card_count"] == 1
    remitted = validate_success(api.remit_escheat_report(report["id"], OFFICER_1), 200)
    assert remitted["status"] == "REMITTED"
    card_after = validate_success(api.get_gift_card(card["id"], ANY), 200)
    assert card_after["status"] == "ESCHEATED"
