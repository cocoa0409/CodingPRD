"""StaleReturn dispute cycle: VERIFIED -> DISPUTED -> VERIFIED with
dispute_round accounting and recomputation (PRD §3.8)."""
from test_helpers import (
    TEST_USERS,
    make_qa_headers,
    make_store_receiver_headers,
    setup_verified_stale_return_scenario,
    validate_success,
)


class TestStaleReturnDisputeCycle:
    def test_dispute_moves_verified_to_disputed(self, api):
        """PRD §3.8: "A store that disagrees with a verification disputes it:
        a `StoreReceiver` whose `X-User-ID` equals the return's `store_id`
        (else `ERR_FORBIDDEN_FOR_ROLE`) moves the return from `VERIFIED` to
        `DISPUTED`."

        Design: Difficulty/non_linear_state_machine/stale_return_dispute_cycle
        """
        ctx = setup_verified_stale_return_scenario(
            plant_name="Plant Zeta", stale_lines_qty=3,
        )
        sre = ctx["stale_return"]
        store = ctx["store"]

        disputed = validate_success(
            api.dispute_stale_return(
                sre["id"], make_store_receiver_headers(store["id"])
            )
        )
        assert disputed["status"] == "DISPUTED", (
            f"VERIFIED -> DISPUTED loop leg must succeed, got {disputed['status']}"
        )

    def test_resolve_dispute_recomputes_and_increments_round(self, api):
        """PRD §3.8: "Resolution is again QA's: supplying fresh
        `verified_lines` moves the return from `DISPUTED` back to `VERIFIED`,
        recomputes `final_credit_cents` with the same verified variant, and
        increments `dispute_round` by 1."

        Design: Difficulty/non_linear_state_machine/stale_return_dispute_cycle
        """
        ctx = setup_verified_stale_return_scenario(
            plant_name="Plant Zeta 2", stale_lines_qty=3,
        )
        sre = ctx["stale_return"]
        store = ctx["store"]
        batch = ctx["batch"]

        validate_success(
            api.dispute_stale_return(
                sre["id"], make_store_receiver_headers(store["id"])
            )
        )
        resolved = validate_success(
            api.resolve_dispute_stale_return(
                sre["id"],
                {"verified_lines": [{"batch_id": batch["id"], "qty": 3}]},
                make_qa_headers("qa-1"),
            )
        )
        assert resolved["status"] == "VERIFIED", (
            f"DISPUTED -> VERIFIED must succeed, got {resolved['status']}"
        )
        assert resolved["dispute_round"] == 1, (
            f"dispute_round must increment to 1, got {resolved['dispute_round']}"
        )
        # Batch baked 2026-08-09T09:00:00Z; pickup clock 2026-08-10T15:00:00Z
        # (age 30h -> rate 0.50); qty 3 -> round_half_up(3*199*0.5) = 299.
        assert resolved["final_credit_cents"] == 299, (
            f"final must be recomputed to 299, got {resolved['final_credit_cents']}"
        )
