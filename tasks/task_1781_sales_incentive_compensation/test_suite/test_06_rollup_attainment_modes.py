"""Manager roll-up cascade and the attainment mode filter: the posting chain
transaction -> DIRECT credit -> ROLLUP credit -> manager earned, and the
DIRECT_ONLY vs INCLUDE_ROLLUP divergence at settlement."""
from test_helpers import (
    CANONICAL_CURVE_TIERS,
    TEST_USERS,
    accept_assignment,
    assert_credit_entry,
    book_transaction,
    close_period,
    get_assignment,
    get_only_credit_entry,
    get_statement_for,
    setup_manager_rep,
)

ADMIN = TEST_USERS["comp_admin_headers"]


class TestRollupChain:
    def test_direct_post_spawns_rollup_for_manager(self, api):
        """PRD §3.4: "Then, for `DIRECT` entries only, the roll-up cascade
        fires: when the credited rep's `manager_id` is set and that manager
        holds an assignment with lifecycle `status` equal to `ACTIVE` on the
        **same plan**, the system spawns a `ROLLUP` credit entry for the
        manager — `parent_credit_id` pointing back at the spawning entry,
        `credit_amount_cents` equal to the spawning entry's amount multiplied
        by the plan's `rollup_rate_bps` and divided by ten thousand, rounded
        half up to a whole cent."

        Design: Difficulty/transitive_cascade/transaction_posting_rollup_chain
        """
        sc = setup_manager_rep(program_name="Prog Roll", plan_name="Plan RO",
                               rollup_rate_bps=5000,
                               curve_tiers=CANONICAL_CURVE_TIERS)
        txn = book_transaction(sc["program"]["id"], "RO-T1", 200000,
                               [{"rep_id": sc["rep"]["id"], "split_bps": 10000}])

        direct = get_only_credit_entry(transaction_id=txn["id"],
                                       rep_id=sc["rep"]["id"])
        assert_credit_entry(direct)
        assert direct["status"] == "POSTED"
        assert direct["credit_amount_cents"] == 200000
        assert direct["posted_period_index"] == 1

        rollup = get_only_credit_entry(parent_credit_id=direct["id"])
        assert_credit_entry(rollup)
        assert rollup["credit_type"] == "ROLLUP"
        # round_half_up(200000 * 5000 / 10000)
        assert rollup["credit_amount_cents"] == 100000
        assert rollup["status"] == "POSTED"
        assert rollup["assignment_id"] == sc["manager_assignment"]["id"]
        assert rollup["rep_id"] == sc["manager"]["id"]

    def test_rollup_post_increments_manager_earned(self, api):
        """PRD §3.4: "The assignment's `current_period_earned_cents` increases
        by the credit amount, raw, for both credit types."
        PRD §3.4: "The roll-up lands `POSTED` with the current
        `posted_period_index` when the manager's assignment is `ACCEPTED`, else
        `PENDING`, to be posted later by the manager's own acceptance cascade,
        at which point it runs these same posting side effects for the
        manager's assignment."

        Design: Difficulty/transitive_cascade/transaction_posting_rollup_chain
        """
        sc = setup_manager_rep(program_name="Prog Roll2", plan_name="Plan RO2",
                               rollup_rate_bps=5000,
                               curve_tiers=CANONICAL_CURVE_TIERS)
        book_transaction(sc["program"]["id"], "RO2-T1", 200000,
                         [{"rep_id": sc["rep"]["id"], "split_bps": 10000}])

        rep_now = get_assignment(sc["rep_assignment"]["id"])
        manager_now = get_assignment(sc["manager_assignment"]["id"])
        assert rep_now["current_period_earned_cents"] == 200000
        assert manager_now["current_period_earned_cents"] == 100000, (
            "the manager's earned rises via the ROLLUP posting, not the "
            "transaction directly"
        )

    def test_rollup_pending_until_manager_accepts(self, api):
        """PRD §3.4: "The roll-up lands `POSTED` with the current
        `posted_period_index` when the manager's assignment is `ACCEPTED`, else
        `PENDING`, to be posted later by the manager's own acceptance cascade,
        at which point it runs these same posting side effects for the
        manager's assignment."
        PRD §3.3: "Acceptance moves `acceptance_status` to `ACCEPTED`, pins
        `accepted_document_version` to the plan's current `document_version`,
        and — critically — releases every held credit: each `PENDING` credit
        entry of the assignment transitions to `POSTED` with
        `posted_period_index` set to the program's current period, and each
        such posting runs the full posting side effects of §3.4, earned
        increment and roll-up spawn included."

        Design: Corner/calculations/rollup_pending_until_manager_accepts
        """
        sc = setup_manager_rep(program_name="Prog RP", plan_name="Plan RP",
                               rollup_rate_bps=5000,
                               manager_accepted=False, rep_accepted=True)
        txn = book_transaction(sc["program"]["id"], "RP-T1", 200000,
                               [{"rep_id": sc["rep"]["id"], "split_bps": 10000}])
        direct = get_only_credit_entry(transaction_id=txn["id"],
                                       rep_id=sc["rep"]["id"])

        rollup = get_only_credit_entry(parent_credit_id=direct["id"])
        assert rollup["status"] == "PENDING"
        assert rollup.get("posted_period_index") is None
        assert (get_assignment(sc["manager_assignment"]["id"])
                ["current_period_earned_cents"] == 0)

        accept_assignment(sc["manager_assignment"]["id"], sc["manager"]["id"])
        rollup_after = get_only_credit_entry(parent_credit_id=direct["id"])
        assert rollup_after["status"] == "POSTED"
        assert rollup_after["posted_period_index"] == 1
        assert (get_assignment(sc["manager_assignment"]["id"])
                ["current_period_earned_cents"] == 100000)


class TestAttainmentModes:
    def _dual_mode_scenario(self, api, prefix, attainment_mode):
        """Manager direct 300000 + subordinate direct 600000 rolling up
        300000 at rollup_rate_bps 5000; period 1 closed."""
        sc = setup_manager_rep(program_name=f"Prog {prefix}",
                               plan_name=f"Plan {prefix}",
                               rollup_rate_bps=5000,
                               attainment_mode=attainment_mode,
                               curve_tiers=CANONICAL_CURVE_TIERS)
        book_transaction(sc["program"]["id"], f"{prefix}-T1", 300000,
                         [{"rep_id": sc["manager"]["id"], "split_bps": 10000}])
        book_transaction(sc["program"]["id"], f"{prefix}-T2", 600000,
                         [{"rep_id": sc["rep"]["id"], "split_bps": 10000}],
                         transaction_date="2026-02-02")
        close_period(sc["program"]["id"])
        return sc

    def test_direct_only_mode_excludes_rollup_from_attainment(self, api):
        """PRD §3.4: "The mode filter is the plan's `attainment_mode`: under
        `DIRECT_ONLY` only `DIRECT` entries count and roll-ups are excluded
        entirely, while under `INCLUDE_ROLLUP` both types count — so identical
        raw credits yield strictly higher attainment under `INCLUDE_ROLLUP`
        whenever any roll-up exists."
        PRD §3.7: "First, `earned_credits_cents` captures the assignment's
        `current_period_earned_cents` filtered by the plan's
        `attainment_mode`, exactly as §3.4 defines the mode filter."

        Design: Difficulty/dual_variant_calc/attainment_direct_vs_rollup_mode
        """
        sc = self._dual_mode_scenario(api, "A", "DIRECT_ONLY")
        stmt = get_statement_for(sc["manager_assignment"]["id"], 1)
        assert stmt["earned_credits_cents"] == 300000, (
            "the 300000 ROLLUP entry is excluded under DIRECT_ONLY"
        )
        assert stmt["attainment_bps"] == 3000
        # Canonical curve, quota 1000000: 300000 * 10% band-0 rate.
        assert stmt["gross_payout_cents"] == 30000

    def test_include_rollup_mode_counts_rollup_in_attainment(self, api):
        """PRD §3.4: "The mode filter is the plan's `attainment_mode`: under
        `DIRECT_ONLY` only `DIRECT` entries count and roll-ups are excluded
        entirely, while under `INCLUDE_ROLLUP` both types count — so identical
        raw credits yield strictly higher attainment under `INCLUDE_ROLLUP`
        whenever any roll-up exists."

        Design: Difficulty/dual_variant_calc/attainment_direct_vs_rollup_mode
        """
        sc = self._dual_mode_scenario(api, "B", "INCLUDE_ROLLUP")
        stmt = get_statement_for(sc["manager_assignment"]["id"], 1)
        assert stmt["earned_credits_cents"] == 600000, (
            "300000 DIRECT + 300000 ROLLUP both count under INCLUDE_ROLLUP"
        )
        assert stmt["attainment_bps"] == 6000
        assert stmt["gross_payout_cents"] == 60000, (
            "identical raw credit magnitudes yield strictly higher attainment "
            "and gross than the DIRECT_ONLY variant (3000 bps / 30000)"
        )
