"""Dual-variant calculations (quote vs settlement; risk vs ledger), the risk
input-set filter, and the deposit conservation invariant."""
from test_helpers import (
    validate_success, ApiErrorId,
    get_artist, get_reservation, get_unit, settle_reservation,
    setup_quote_settlement_divergence, setup_deposit_hold_pair,
    setup_deposit_invariant_scene, setup_risk_filtering_scene,
    api_client, TEST_USERS,
)

OPS = TEST_USERS["ops_manager_headers"]
TM = TEST_USERS["tour_manager_headers"]


def test_quote_settlement_divergence_amounts(api, tour_manager_headers):
    """PRD §3.9: "Insurance is evaluated against the artist's `risk_score` at
    settle time rather than quote time, so whenever the score has crossed the
    inclusive threshold of 50 in either direction between the two moments, quote
    and settlement differ for otherwise identical inputs."
    Quoted at risk 0: 500000; settled at risk 60 with a 2-block late return:
    840000.

    Design: Difficulty/dual_variant_calc/reservation_fee_quote_vs_settlement_divergence
    """
    ctx = setup_quote_settlement_divergence()
    assert ctx["quoted_at_source"] == 500_000

    settled = settle_reservation(ctx["reservation"]["id"], tour_manager_headers)
    assert settled["settled_fee_cents"] == 840_000
    assert settled["settled_fee_cents"] != ctx["quoted_at_source"]


def test_quote_settlement_divergence_decomposition(api, tour_manager_headers):
    """PRD §3.9: "Lateness is priced from reality: each started 24-hour block
    between the `end_date` and the actual `checked_in_at` adds one day billed at
    one-and-a-half times the daily base rate, with that inflated day rate
    rounded half-up to whole cents once and then multiplied by the block count
    — an on-time return adds nothing."
    Divergence 840000 - 500000 = 340000 decomposes as insurance 40000
    (8% of the 500000 base at risk 60) plus two late blocks at
    round_half_up(100000 * 1.5) = 150000 each.

    Design: Difficulty/dual_variant_calc/reservation_fee_quote_vs_settlement_divergence
    """
    ctx = setup_quote_settlement_divergence()
    settled = settle_reservation(ctx["reservation"]["id"], tour_manager_headers)
    insurance_component = 40_000      # round_half_up(500000 * 0.08)
    late_component = 2 * 150_000      # 2 started 24h blocks * 150% of 100000
    assert settled["settled_fee_cents"] - ctx["quoted_at_source"] == 340_000
    assert settled["settled_fee_cents"] == 500_000 + insurance_component + late_component


def test_ledger_drawdown_to_zero(api, ops_manager_headers):
    """PRD §2.7: "When a reservation is sourced, a hold computed from the
    sourced model's replacement value is blocked on the artist: the amount is
    recorded on the reservation as `deposit_held_cents` and debited from the
    artist's balance in the same operation."
    A 75000 top-up drawn down by holds of 55000 and 20000 leaves exactly 0,
    while no claim has been assessed so the recomputed risk stays 0.

    Design: Difficulty/dual_variant_calc/artist_risk_score_vs_deposit_hold_independent_variants
    """
    ctx = setup_deposit_hold_pair()
    assert ctx["r_hi"]["deposit_held_cents"] == 55_000
    assert ctx["r_lo"]["deposit_held_cents"] == 20_000

    artist = get_artist(ctx["artist"]["id"], ops_manager_headers)
    assert artist["deposit_credit_cents"] == 0
    assert artist["risk_score"] == 0


def test_ledger_release_vs_risk_recompute_independence(api, ops_manager_headers,
                                                       tour_manager_headers):
    """PRD §2.7: "Cancelling a sourced reservation credits its hold back to the
    balance".
    PRD §3.1: "It is recomputed from scratch — never adjusted incrementally —
    each time one of the artist's claims is assessed and again when one is
    marked paid".
    Cancelling the 55000-hold reservation returns the balance to exactly 55000
    (incremental compensation), while the risk score remains 0 (recompute over
    an empty claim window): two independent variants on the Artist.

    Design: Difficulty/dual_variant_calc/artist_risk_score_vs_deposit_hold_independent_variants
    """
    ctx = setup_deposit_hold_pair()
    validate_success(api.cancel_reservation(ctx["r_hi"]["id"], tour_manager_headers))

    artist = get_artist(ctx["artist"]["id"], ops_manager_headers)
    assert artist["deposit_credit_cents"] == 55_000
    assert artist["risk_score"] == 0


def test_risk_score_input_set_filtering(api, ops_manager_headers):
    """PRD §3.1: "it draws on every claim attached to the artist's reservations
    whose status is `ASSESSED`, `CHARGED`, `DISPUTED`, or `PAID` and whose
    assessment falls within the trailing 365 days."
    PRD §3.1: "Each qualifying claim contributes a severity weight — 2 for
    `COSMETIC`, 5 for `MINOR`, 12 for `MAJOR`, and 30 for `TOTAL_LOSS` — and
    that weight is doubled when the assessment is no more than 90 days old".
    An ASSESSED MAJOR claim assessed today contributes 12 * 2 = 24.

    Design: Corner/calculations/risk_score_input_set_filtering
    """
    ctx = setup_risk_filtering_scene()
    assert get_artist(ctx["artist"]["id"], ops_manager_headers)["risk_score"] == 24


def test_deposit_conserved_source_then_cancel(api, ops_manager_headers,
                                              tour_manager_headers):
    """PRD §2.7: "When a reservation is sourced, a hold computed from the
    sourced model's replacement value is blocked on the artist: the amount is
    recorded on the reservation as `deposit_held_cents` and debited from the
    artist's balance in the same operation. Cancelling a sourced reservation
    credits its hold back to the balance".
    55000 top-up -> 0 after sourcing (held 55000) -> 55000 after cancel:
    balance plus non-terminal held is conserved with zero drift.

    Design: Difficulty/compensating_invariant/deposit_balance_conserved_under_source_then_cancel
    """
    ctx = setup_deposit_invariant_scene()
    assert ctx["reservation"]["deposit_held_cents"] == 55_000
    assert get_artist(ctx["artist"]["id"], ops_manager_headers)["deposit_credit_cents"] == 0

    validate_success(api.cancel_reservation(ctx["reservation"]["id"], tour_manager_headers))
    assert get_artist(ctx["artist"]["id"], ops_manager_headers)["deposit_credit_cents"] == 55_000


def test_deposit_conservation_releases_unit(api, tour_manager_headers):
    """PRD §2.7: "Cancelling a sourced reservation credits its hold back to the
    balance".
    PRD §3.9: "each `SOURCED` reservation is cancelled with the standard
    compensation — its unit released from `RESERVED` to `AVAILABLE` with
    `active_reservation_id` cleared and its held deposit credited back".

    Design: Difficulty/compensating_invariant/deposit_balance_conserved_under_source_then_cancel
    """
    ctx = setup_deposit_invariant_scene()
    assert get_unit(ctx["unit"]["id"])["status"] == "RESERVED"

    validate_success(api.cancel_reservation(ctx["reservation"]["id"], tour_manager_headers))
    unit = get_unit(ctx["unit"]["id"])
    assert unit["status"] == "AVAILABLE"
    assert unit["active_reservation_id"] is None
