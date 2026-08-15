"""Difficulty queue: dual-variant buy-out valuation (provisional vs final)."""
from test_helpers import (
    adopted_capital_call,
    appraise_valuation,
    bill_call,
    create_policy,
    create_shareholder,
    get_exit_valuation,
    get_physician,
    initiate_exit,
    list_physician_assessments,
    pay_assessment,
)


def _setup_x_with_capital_account():
    """X (1000 shares) + Y (8000 shares); a billed call X paid in full.

    X's capital account becomes 1500000: assessment 13500000 * 1000/9000.
    Policy carries trailing EBITDA 50000000 for the provisional estimate.
    """
    create_policy(total_shares_authorized=1000000, board_quorum_count=1,
                  trailing_ebitda_cents=50000000)
    x = create_shareholder("Dr X", 1000, "2010-01-01T00:00:00Z")
    create_shareholder("Dr Y", 8000, "2011-01-01T00:00:00Z")
    _motion, call = adopted_capital_call(
        x, 13500000, due_date="2026-08-20T00:00:00Z", purpose="Imaging equipment"
    )
    bill_call(call["id"])
    assessments, _ = list_physician_assessments(x["id"])
    assert len(assessments) == 1, "Setup failed: X should have exactly one assessment"
    assert assessments[0]["assessed_cents"] == 1500000, (
        f"Setup failed: X assessment {assessments[0]['assessed_cents']} != 1500000"
    )
    pay_assessment(assessments[0]["id"], 1500000)
    return x


class TestBuyoutProvisionalVsFinalDiverge:
    def test_provisional_variant_at_initiation(self, api):
        """PRD §3.6: "Initiation pins `ownership_pct_snapshot` — the physician's exact
        ownership fraction at that instant, displayed at 6 decimal places and never
        re-opened by later share changes — and computes `provisional_value_cents`, the
        book-style estimate: the physician's `capital_account_balance_cents` plus their
        ownership snapshot multiplied by `trailing_ebitda_cents` and by
        `ebitda_multiple`, that product rounded half-up to cents."
        1500000 + round_half_up(1000/9000 * 50000000 * 6) = 1500000 + 33333333 = 34833333.
        PRD §3.6: "The physician's `partnership_status` moves from `SHAREHOLDER` to
        `EXITING` at initiation, and the valuation starts at `INITIATED`."

        Design: Difficulty/dual_variant_calc/buyout_provisional_vs_final_diverge
        """
        x = _setup_x_with_capital_account()
        valuation = initiate_exit(x["id"], "VOLUNTARY")
        assert valuation["status"] == "INITIATED"
        assert valuation["provisional_value_cents"] == 34833333, (
            f"provisional must be 34833333 (1500000 + round(1000/9000*50000000*6)), "
            f"got {valuation['provisional_value_cents']}"
        )
        assert valuation["ownership_pct_snapshot"] == 0.111111
        physician = get_physician(x["id"])
        assert physician["partnership_status"] == "EXITING", (
            "initiation moves the physician SHAREHOLDER -> EXITING"
        )

    def test_final_variant_diverges_after_appraisal(self, api):
        """PRD §3.6: "The final value depends on the trigger: for `VOLUNTARY` and
        `RETIREMENT` exits it is the appraised practice value multiplied by the
        ownership snapshot and by one minus `minority_discount_pct`, rounded half-up;
        for `TERMINATION` and `DEATH` the minority discount is waived, so it is simply
        the appraised practice value multiplied by the ownership snapshot, rounded
        half-up."
        round_half_up(120000000 * 1000/9000 * 0.85) = 11333333, which differs from the
        provisional variant's 34833333 on identical physician state.

        Design: Difficulty/dual_variant_calc/buyout_provisional_vs_final_diverge
        """
        x = _setup_x_with_capital_account()
        valuation = initiate_exit(x["id"], "VOLUNTARY")
        assert valuation["provisional_value_cents"] == 34833333
        appraised = appraise_valuation(valuation, 120000000)
        assert appraised["status"] == "APPRAISED"
        assert appraised["final_value_cents"] == 11333333, (
            f"final must be 11333333 (round(120000000 * 1000/9000 * 0.85)), "
            f"got {appraised['final_value_cents']}"
        )
        assert appraised["provisional_value_cents"] != appraised["final_value_cents"], (
            "the two variants must produce different cents for identical physician state"
        )
        fetched = get_exit_valuation(valuation["id"])
        assert fetched["final_value_cents"] == 11333333
