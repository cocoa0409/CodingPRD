"""Dual-variant calculations: earned-premium (exonerate vs revoke) and net
judgment (with vs without recovery credit).

Each test builds its own state from scratch via test_helpers fixtures and pins
literal expected values copied from the PRD's stated formulas.
"""
from test_helpers import (
    validate_success, get_success_data, api_client,
    setup_active_surety_bond, setup_draft_surety_bond,
    setup_judgment_ready, enter_judgment_on,
    TEST_USERS,
)

OFFICER = TEST_USERS["compliance_officer_headers"]
AGENT = TEST_USERS["bonds_agent_headers"]


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/earned_premium_exonerate_vs_revoke
# ---------------------------------------------------------------------------
def test_earned_premium_full_on_exoneration(api):
    """PRD 3.7: "The bond's `premium_earned_cents` is set equal to its
    `premium_cents` — the fully-earned variant, in which the entire premium is
    recognized regardless of how long the bond was active."

    SURETY 2,000,000c at 1000 bps: premium_cents == 200000 (band1 1,000,000*1000
    + band2 1,000,000*1000)/10000, and on exoneration premium_earned_cents ==
    premium_cents == 200000.

    Design: Difficulty/dual_variant_calc/earned_premium_exonerate_vs_revoke
    """
    scen = setup_active_surety_bond(bail_amount_cents=2_000_000, liability_share_cents=2_000_000,
                                    collateral_value_cents=500_000)
    assert scen["bond"]["premium_cents"] == 200000, scen["bond"]["premium_cents"]
    exon = validate_success(api.exonerate_bond(scen["def_id"], scen["bond_id"], OFFICER))
    assert exon["premium_earned_cents"] == 200000, exon["premium_earned_cents"]
    assert exon["premium_cents"] == 200000, exon["premium_cents"]
    assert exon["coverage_status"] == "EXONERATED"


def test_earned_premium_zero_on_revoke_from_draft(api):
    """PRD 3.7: "a bond that was revoked from draft before activation, whose
    `premium_earned_cents` stays 0 because the premium was never collected (its
    `settlement_status` never reached `PREMIUM_COLLECTED`)."

    A second DRAFT bond on the same order revoked before activation keeps
    premium_earned_cents == 0 and reaches coverage_status REVOKED.

    Design: Difficulty/dual_variant_calc/earned_premium_exonerate_vs_revoke
    """
    scen = setup_draft_surety_bond(bail_amount_cents=2_000_000, with_indemnity=False,
                                   with_collateral=False)
    # Post a second draft bond on the same order, then revoke it.
    bond2 = get_success_data(
        api_client.create_bond(scen["def_id"], scen["order_id"],
                               {"bond_type": "SURETY", "premium_rate_bps": 1000}, scen["agent"])
    )
    revoked = validate_success(api.revoke_bond(scen["def_id"], bond2["id"], scen["agent"]))
    assert revoked["coverage_status"] == "REVOKED"
    assert revoked["premium_earned_cents"] == 0, revoked["premium_earned_cents"]


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/judgment_amount_with_vs_without_recovery_credit
# ---------------------------------------------------------------------------
def test_judgment_amount_with_recovery_credit(api):
    """PRD 3.6: "and only if the proceeding passed through `RECOVERY_OPEN` on its
    way to judgment, subtract a flat recovery credit of 500 dollars (50,000 cents)
    recognizing the good-faith recovery effort; the running figure is floored at
    zero so the judgment is never negative."

    Face 2,000,000c minus 500,000c liquidated collateral minus 50,000c recovery
    credit == 1,450,000c.

    Design: Difficulty/dual_variant_calc/judgment_amount_with_vs_without_recovery_credit
    """
    scen = setup_judgment_ready(open_recovery=True, bail_amount_cents=2_000_000,
                                liability_share_cents=2_000_000, collateral_value_cents=500_000)
    proc = enter_judgment_on(scen)
    assert proc["judgment_amount_cents"] == 1_450_000, proc["judgment_amount_cents"]


def test_judgment_amount_without_recovery_credit(api):
    """PRD 3.6: "A proceeding that went straight from `FORFEITED` to `JUDGMENT`
    without opening recovery receives no such credit — its judgment is face value
    minus liquidated collateral, floored at zero."

    Face 2,000,000c minus 500,000c liquidated collateral, no recovery credit ==
    1,500,000c.

    Design: Difficulty/dual_variant_calc/judgment_amount_with_vs_without_recovery_credit
    """
    scen = setup_judgment_ready(open_recovery=False, bail_amount_cents=2_000_000,
                                liability_share_cents=2_000_000, collateral_value_cents=500_000)
    proc = enter_judgment_on(scen)
    assert proc["judgment_amount_cents"] == 1_500_000, proc["judgment_amount_cents"]
