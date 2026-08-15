"""Difficulty queue: cyclic ExitValuation machine — APPRAISED <-> DISPUTED bounded loop."""
from test_helpers import (
    ApiErrorId,
    api_client,
    appraise_valuation,
    arbitrate_valuation,
    create_policy,
    create_shareholder,
    dispute_valuation,
    get_exit_valuation,
    initiate_exit,
    make_physician_headers,
    validate_error,
)


def _setup_appraised_valuation():
    create_policy(total_shares_authorized=1000000)
    x = create_shareholder("Dr X", 1000, "2010-01-01T00:00:00Z")
    valuation = initiate_exit(x["id"], "VOLUNTARY")
    appraised = appraise_valuation(valuation, 90000000)
    return x, appraised


class TestExitValuationAppraisedDisputedCycle:
    def test_dispute_reappraisal_loop_bounded_by_max_rounds(self, api):
        """PRD §3.6: "The exiting physician — and only that physician — may dispute an
        appraisal, moving the valuation from `APPRAISED` to `DISPUTED` and incrementing
        `dispute_rounds` by 1. Disputes are blocked once `appraisal_final` is true
        (`ERR_INVALID_STATE`) and capped at `max_dispute_rounds` rounds: when
        `dispute_rounds` has reached the cap, another dispute is rejected with
        `ERR_DISPUTE_LIMIT_REACHED`, and arbitration is the only path forward."
        Sole shareholder: ownership 1.0; re-appraisal at 95000000 recomputes
        final = round(95000000 * 0.85) = 80750000.

        Design: Difficulty/non_linear_state_machine/exit_valuation_appraised_disputed_cycle
        """
        x, appraised = _setup_appraised_valuation()
        assert appraised["status"] == "APPRAISED"

        disputed1 = dispute_valuation(appraised["id"], x)
        assert disputed1["status"] == "DISPUTED"
        assert disputed1["dispute_rounds"] == 1

        reappraised = appraise_valuation(disputed1, 95000000)
        assert reappraised["status"] == "APPRAISED"
        assert reappraised["final_value_cents"] == 80750000, (
            f"re-appraisal recomputes final: round(95000000*0.85) = 80750000, "
            f"got {reappraised['final_value_cents']}"
        )

        disputed2 = dispute_valuation(reappraised["id"], x)
        assert disputed2["dispute_rounds"] == 2

        # PRD §3.6: "a re-appraisal may be recorded from `DISPUTED` with the
        # same effect" — the capped dispute is attempted from `APPRAISED`, the
        # state the dispute transition starts from.
        reappraised2 = appraise_valuation(disputed2, 98000000)
        assert reappraised2["status"] == "APPRAISED"
        assert reappraised2["dispute_rounds"] == 2

        resp = api_client.dispute_exit_valuation(
            reappraised2["id"], make_physician_headers(x["id"])
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_LIMIT_REACHED)

    def test_arbitration_appraisal_is_final_and_blocks_disputes(self, api):
        """PRD §3.6: "From `ARBITRATION`, the appraisal recorded is the arbitrator's
        value: it marks `appraisal_final` true, which blocks all further disputes."
        PRD §3.6: "Disputes are blocked once `appraisal_final` is true
        (`ERR_INVALID_STATE`)".
        Arbitrator value 100000000 at ownership 1.0: round(100000000 * 0.85) = 85000000.

        Design: Difficulty/non_linear_state_machine/exit_valuation_appraised_disputed_cycle
        """
        x, appraised = _setup_appraised_valuation()
        disputed = dispute_valuation(appraised["id"], x)
        in_arbitration = arbitrate_valuation(disputed["id"])
        assert in_arbitration["status"] == "ARBITRATION"

        final = appraise_valuation(in_arbitration, 100000000)
        assert final["status"] == "APPRAISED"
        assert final["appraisal_final"] is True
        assert final["final_value_cents"] == 85000000, (
            f"arbitrator final must be round(100000000*0.85) = 85000000, "
            f"got {final['final_value_cents']}"
        )

        resp = api_client.dispute_exit_valuation(
            final["id"], make_physician_headers(x["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_exit_valuation(final["id"])["status"] == "APPRAISED"
