"""Premium quoting, earned premium, rider premium, cession amounts, and incurred-loss math.

Covers difficulty queue (A) rules dual_variant_calc and combinatorial_formula, plus the
corner queue (B) calculations section.
"""
import pytest
from test_helpers import (
    validate_success,
    get_success_data,
    create_application_payload,
    create_rider_payload,
    create_cession_payload,
    setup_active_bond,
    setup_submitted_application,
    setup_investigating_claim,
    setup_active_cession,
    create_principal_with_indemnity,
    create_program,
    create_treaty,
    set_clock,
    UW,
    CE,
)


# ─── dual_variant_calc: premium_earning (PRO_RATA vs SHORT_RATE) ───────────────

def test_cancel_short_rate_earned_premium_includes_penalty(api):
    """PRD §3.5: "earned premium is that same pro-rata earned amount plus an additional
    penalty equal to ten percent of the unearned portion, where the unearned portion is
    `written_premium_cents` multiplied by remaining months and divided by `term_months`;
    the two parts are summed and the single final sum is rounded half up once to whole cents
    (sum-then-round, not round-per-part), so that less premium is returned than under
    pro-rata."

    Design: Difficulty/dual_variant_calc/premium_earning_pro_rata_vs_short_rate_on_bond
    """
    # PREFERRED/BID penal 12M with single_limit 20M: 12M*2>=20M -> surcharge -> rate 150,
    # written_premium = 12,000,000 * 150 / 10000 = 180,000.
    prin, _ = create_principal_with_indemnity(
        legal_name="Acme", credit_score=760, working_capital_cents=5_000_000
    )
    prog = create_program(name="P1")
    _, _, _, bond = setup_active_bond(
        program=prog,
        principal=prin,
        app_overrides={"bond_type": "BID", "requested_penal_sum_cents": 12_000_000,
                       "term_months": 12},
    )
    assert bond["written_premium_cents"] == 180_000
    # Advance clock 3 months (default 2026-01-01 -> 2026-04-01).
    set_clock("2026-04-01T00:00:00Z")

    res = api.cancel_bond(bond["id"], {"cancel_mode": "SHORT_RATE"}, UW)
    cancelled = validate_success(res, 200)
    # pro-rata earned = 180000*3/12 = 45000; unearned = 180000*9/12 = 135000;
    # short-rate = round_half_up(45000 + 0.10*135000) = round(58500) = 58500.
    assert cancelled["earned_premium_cents"] == 58_500
    assert cancelled["status"] == "CANCELLED"


def test_cancel_pro_rata_earned_premium_no_penalty(api):
    """PRD §3.5: "Under `PRO_RATA` — a voluntary cancel with no penalty — earned premium is
    the bond's `written_premium_cents` multiplied by elapsed months and divided by
    `term_months`, rounded half up once to whole cents; the unearned portion is fully
    returned."

    Design: Difficulty/dual_variant_calc/premium_earning_pro_rata_vs_short_rate_on_bond
    """
    prin, _ = create_principal_with_indemnity(
        legal_name="Acme2", credit_score=760, working_capital_cents=5_000_000
    )
    prog = create_program(name="P1b")
    _, _, _, bond = setup_active_bond(
        program=prog,
        principal=prin,
        app_overrides={"bond_type": "BID", "requested_penal_sum_cents": 12_000_000,
                       "term_months": 12},
    )
    assert bond["written_premium_cents"] == 180_000
    set_clock("2026-04-01T00:00:00Z")

    res = api.cancel_bond(bond["id"], {"cancel_mode": "PRO_RATA"}, UW)
    cancelled = validate_success(res, 200)
    # pro-rata earned = 180000*3/12 = 45000 (delta 13500 vs short-rate is the penalty).
    assert cancelled["earned_premium_cents"] == 45_000
    assert cancelled["status"] == "CANCELLED"


# ─── dual_variant_calc: incurred_loss (case-reserve vs paid-actual) ────────────

def test_incurred_loss_case_reserve_then_paid_net_of_salvage(api):
    """PRD §2.7: "for each claim still in `FILED` or `INVESTIGATING`, its case reserve
    (`reserve_cents`) contributes; for each claim that has reached `PAID`, the realized net
    loss contributes in place of any reserve — that net loss is the paid loss minus salvage,
    taken as `paid_loss_cents` minus `salvage_cents` but floored at zero so that salvage can
    never drive a single claim's contribution below zero."

    Design: Difficulty/dual_variant_calc/incurred_loss_case_reserve_vs_paid_actual_on_claim
    """
    prog = create_program(name="P2")
    prin, _ = create_principal_with_indemnity(
        legal_name="Beta", credit_score=700, working_capital_cents=1_000_000
    )
    _, bond, claim = setup_investigating_claim(
        program=prog,
        bond=setup_active_bond(
            program=prog, principal=prin,
            app_overrides={"bond_type": "PERFORMANCE",
                           "requested_penal_sum_cents": 5_000_000, "term_months": 12},
        )[3],
        claim_overrides={"claimant_name": "Obligee X", "demand_cents": 900_000,
                         "reserve_cents": 800_000},
        investigate_reserve=800_000,
    )
    # While INVESTIGATING: case-reserve view = 800,000.
    bond_before = validate_success(api.get_bond(bond["id"], UW), 200)
    assert bond_before["incurred_loss_cents"] == 800_000

    res = api.settle_claim(
        claim["id"], {"outcome": "PAY", "paid_loss_cents": 600_000, "salvage_cents": 100_000}, CE
    )
    settled = validate_success(res, 200)
    assert settled["status"] == "PAID"
    # After settle PAY: paid-net-of-salvage = 600,000 - 100,000 = 500,000 replaces reserve.
    bond_after = validate_success(api.get_bond(bond["id"], UW), 200)
    assert bond_after["incurred_loss_cents"] == 500_000


def test_incurred_loss_filed_claim_uses_reserve(api):
    """PRD §3.6: "The claim opens in `FILED`, and filing it recomputes the bond's
    `incurred_loss_cents` to fold in the new reserve."
    PRD §2.7: "for each claim still in `FILED` or `INVESTIGATING`, its case reserve
    (`reserve_cents`) contributes"

    Design: Difficulty/dual_variant_calc/incurred_loss_case_reserve_vs_paid_actual_on_claim
    """
    prog = create_program(name="P2b")
    prin, _ = create_principal_with_indemnity(
        legal_name="Beta2", credit_score=700, working_capital_cents=1_000_000
    )
    _, _, _, bond = setup_active_bond(
        program=prog, principal=prin,
        app_overrides={"bond_type": "PERFORMANCE", "requested_penal_sum_cents": 5_000_000,
                       "term_months": 12},
    )
    get_success_data(
        api.create_claim(
            {"bond_id": bond["id"], "claimant_name": "Obligee Y", "demand_cents": 900_000,
             "reserve_cents": 800_000}, CE
        )
    )
    bond_after = validate_success(api.get_bond(bond["id"], UW), 200)
    # FILED claim contributes its reserve_cents (case-reserve view).
    assert bond_after["incurred_loss_cents"] == 800_000


# ─── combinatorial_formula: premium_rating (table + surcharge + clamp) ─────────

def test_premium_rating_substandard_performance_surcharge_clamped_to_max(api):
    """PRD §3.3: "To that base rate the system adds a flat large-risk surcharge of 50 basis
    points whenever the request is a large risk — defined as a requested penal sum that, when
    doubled, is at least the program's `single_limit_cents`". PRD §3.3: "The base rate plus
    any surcharge is then clamped so that `quoted_premium_rate_bps` never exceeds 400 basis
    points: the stored rate is the smaller of 400 and the surcharged rate."

    Design: Difficulty/combinatorial_formula/premium_rating_table_surcharge_clamp_mode_a
    """
    prog = create_program(name="P3", single_limit_cents=20_000_000)
    prin, _ = create_principal_with_indemnity(
        legal_name="SubCo", credit_score=600, working_capital_cents=0
    )
    _, _, app = setup_submitted_application(
        program=prog, principal=prin,
        app_overrides={"bond_type": "PERFORMANCE", "requested_penal_sum_cents": 10_000_000,
                       "term_months": 12},
    )
    # SUBSTANDARD/PERFORMANCE base 375 + surcharge 50 = 425 -> clamped to MAX 400.
    assert app["quoted_premium_rate_bps"] == 400
    # premium = round_half_up(10,000,000 * 400 / 10000) = 400000.
    assert app["quoted_premium_cents"] == 400_000


def test_premium_rating_credit_tier_substandard_derived(api):
    """PRD §3.2: "in every remaining case — any principal whose working capital is negative,
    or whose score is below 620 — it is rated `SUBSTANDARD`."

    Design: Difficulty/combinatorial_formula/premium_rating_table_surcharge_clamp_mode_a
    """
    prin = get_success_data(
        api.create_principal(
            {"legal_name": "SubCo2", "credit_score": 600, "working_capital_cents": 0}, UW
        )
    )
    assert prin["credit_tier"] == "SUBSTANDARD"


# ─── combinatorial_formula: rider_premium (round-then-multiply) ────────────────

def test_rider_increase_additional_premium_round_then_multiply(api):
    """PRD §3.5: "first take the increase amount multiplied by the bond's `premium_rate_bps`,
    divided by 10000 and then divided by 12, and round that per-month figure half up to whole
    cents; then multiply that rounded per-month figure by the number of remaining months."
    PRD §3.5: "The rounding happens on the per-month figure first and the multiplication
    second — round-then-multiply, never sum-then-round."

    Design: Difficulty/combinatorial_formula/rider_premium_round_then_multiply_mode_b
    """
    prog = create_program(name="P4", single_limit_cents=20_000_000)
    prin, _ = create_principal_with_indemnity(
        legal_name="Gamma", credit_score=700, working_capital_cents=1_000_000
    )
    # STANDARD/PERFORMANCE penal 5M (no surcharge: 5M*2 < 20M) -> rate 225.
    _, _, _, bond = setup_active_bond(
        program=prog, principal=prin,
        app_overrides={"bond_type": "PERFORMANCE", "requested_penal_sum_cents": 5_000_000,
                       "term_months": 12},
    )
    assert bond["premium_rate_bps"] == 225
    # Advance 6 months -> remaining 6 months.
    set_clock("2026-07-01T00:00:00Z")
    rider = get_success_data(
        api.create_rider(
            create_rider_payload(bond["id"], rider_type="INCREASE",
                                 penal_sum_delta_cents=2_500_000), UW
        )
    )
    res = api.apply_rider(rider["id"], UW)
    applied = validate_success(res, 200)
    # monthly = round_half_up(2,500,000*225/10000/12) = round_half_up(4687.5) = 4688;
    # additional = 4688 * 6 = 28128 (NOT sum-then-round 28125).
    assert applied["additional_premium_cents"] == 28_128
    assert applied["status"] == "APPLIED"
    bond_after = validate_success(api.get_bond(bond["id"], UW), 200)
    assert bond_after["penal_sum_cents"] == 7_500_000


def test_rider_decrease_has_zero_additional_premium(api):
    """PRD §3.5: "For a `DECREASE` or a `NAME_CHANGE`, `additional_premium_cents` is zero."

    Design: Difficulty/combinatorial_formula/rider_premium_round_then_multiply_mode_b
    """
    prog = create_program(name="P4b", single_limit_cents=20_000_000)
    prin, _ = create_principal_with_indemnity(
        legal_name="Gamma2", credit_score=700, working_capital_cents=1_000_000
    )
    _, _, _, bond = setup_active_bond(
        program=prog, principal=prin,
        app_overrides={"bond_type": "PERFORMANCE", "requested_penal_sum_cents": 5_000_000,
                       "term_months": 12},
    )
    rider = get_success_data(
        api.create_rider(
            create_rider_payload(bond["id"], rider_type="DECREASE",
                                 penal_sum_delta_cents=-1_000_000), UW
        )
    )
    applied = validate_success(api.apply_rider(rider["id"], UW), 200)
    assert applied["additional_premium_cents"] == 0
    assert applied["status"] == "APPLIED"


# ─── Corner (B) calculations ──────────────────────────────────────────────────

def test_cession_amount_quota_share_computed_on_create(api):
    """PRD §3.5: "The system computes the cession's `ceded_penal_sum_cents` at creation as
    the bond's `penal_sum_cents` multiplied by the treaty's `cession_pct_bps`, divided by
    10000, rounded half up to whole cents."

    Design: Corner/calculations/cession_amount_quota_share_computed_on_create
    """
    prog = create_program(name="CA1")
    treaty = create_treaty(name="TCA1", cession_pct_bps=2500, treaty_capacity_cents=10_000_000)
    prin, _ = create_principal_with_indemnity(
        legal_name="CAPrin", credit_score=760, working_capital_cents=5_000_000
    )
    _, bond, treaty, cession = setup_active_cession(
        program=prog, treaty=treaty,
        bond=setup_active_bond(
            program=prog, principal=prin,
            app_overrides={"bond_type": "BID", "requested_penal_sum_cents": 8_000_000,
                           "term_months": 12},
        )[3],
    )
    # ceded = round_half_up(8,000,000 * 2500 / 10000) = 2,000,000.
    assert cession["ceded_penal_sum_cents"] == 2_000_000
    bond_after = validate_success(api.get_bond(bond["id"], UW), 200)
    assert bond_after["net_retained_cents"] == 6_000_000
    treaty_after = validate_success(api.get_treaty(treaty["id"], UW), 200)
    assert treaty_after["ceded_committed_cents"] == 2_000_000


def test_premium_rating_no_surcharge_below_half_single_limit(api):
    """PRD §3.3: "a requested penal sum that, when doubled, is at least the program's
    `single_limit_cents` (equivalently, a requested penal sum that is at least half the single
    limit); otherwise the surcharge is zero."
    PRD §3.3: "a `STANDARD` principal is rated 150, 225, 225, 120, and 180 for those same five
    bond types in order"

    Design: Corner/calculations/premium_rating_no_surcharge_below_half_single_limit
    """
    prog = create_program(name="PR1", single_limit_cents=20_000_000)
    prin, _ = create_principal_with_indemnity(
        legal_name="PRPrin", credit_score=650, working_capital_cents=1_000_000
    )
    assert prin["credit_tier"] == "STANDARD"
    _, _, app = setup_submitted_application(
        program=prog, principal=prin,
        app_overrides={"bond_type": "BID", "requested_penal_sum_cents": 5_000_000,
                       "term_months": 12},
    )
    # STANDARD/BID base 150; 5M*2=10M < 20M -> no surcharge -> rate 150.
    assert app["quoted_premium_rate_bps"] == 150
    # premium = round_half_up(5,000,000 * 150 / 10000) = 75000.
    assert app["quoted_premium_cents"] == 75_000
