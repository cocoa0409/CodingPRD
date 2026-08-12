"""Diversion and the MarketingOrderPool.total_pooled_lbs ledger: the
release/divert pair must conserve the pooled total exactly."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_pool,
    get_receipt,
    get_success_data,
    release_receipt,
    setup_intake_env,
    setup_releasable_receipt,
    setup_released_receipt,
    validate_error,
)

QA = TEST_USERS["qa_manager_headers"]


class TestReleaseDivertRevert:
    def test_release_then_divert_restores_pool_total(self, api):
        """PRD §3.3: "the `MarketingOrderPool` for the receipt's calendar month
        has its `total_pooled_lbs` incremented by this receipt's
        `net_weight_lbs`." PRD §3.4: "On a successful diversion, the
        `MarketingOrderPool` for the receipt's calendar month has its
        `total_pooled_lbs` decremented by `net_weight_lbs`".

        Design: Difficulty/non_linear_state_machine/tanker_receipt_release_divert_revert
        """
        env = setup_intake_env(pool=True)
        pid, hid, pool_id = env["producer"]["id"], env["hauler"]["id"], env["pool"]["id"]

        receipt = setup_released_receipt(pid, hid, gross=80000, tare=30000)
        assert receipt["net_weight_lbs"] == 50000
        assert get_pool(pool_id)["total_pooled_lbs"] == 50000

        diverted = get_success_data(api.divert_tanker_receipt(receipt["id"], {}, QA))
        assert diverted["disposition"] == "DIVERTED"
        assert get_pool(pool_id)["total_pooled_lbs"] == 0

    def test_diverted_receipt_cannot_be_diverted_again(self, api):
        """PRD §3.4: "A receipt that has already been released may still be
        diverted" — diversion is defined only out of `RELEASED_FOR_PROCESSING`,
        so a second diversion violates the state-machine precondition. PRD
        §2.10: "then state-machine precondition (→ `ERR_INVALID_STATE`)".

        Design: Difficulty/non_linear_state_machine/tanker_receipt_release_divert_revert
        """
        env = setup_intake_env(pool=True)
        receipt = setup_released_receipt(
            env["producer"]["id"], env["hauler"]["id"], gross=80000, tare=30000
        )
        get_success_data(api.divert_tanker_receipt(receipt["id"], {}, QA))
        assert get_receipt(receipt["id"])["disposition"] == "DIVERTED"

        res = api.divert_tanker_receipt(receipt["id"], {}, QA)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestReleaseDivertConservesPoolTotal:
    def test_release_divert_pair_conserves_pool_total(self, api):
        """PRD §3.3: release "has its `total_pooled_lbs` incremented by this
        receipt's `net_weight_lbs`"; PRD §3.4: "On a successful diversion, the
        `MarketingOrderPool` for the receipt's calendar month has its
        `total_pooled_lbs` decremented by `net_weight_lbs`". After the pair,
        the pool total must equal its pre-release value exactly.

        Design: Difficulty/compensating_invariant/release_then_divert_conserves_pool_total
        """
        env = setup_intake_env(pool=True)
        pid, hid, pool_id = env["producer"]["id"], env["hauler"]["id"], env["pool"]["id"]

        assert get_pool(pool_id)["total_pooled_lbs"] == 0

        receipt = setup_released_receipt(pid, hid, gross=100000, tare=30000)
        assert receipt["net_weight_lbs"] == 70000
        assert get_pool(pool_id)["total_pooled_lbs"] == 70000

        get_success_data(api.divert_tanker_receipt(receipt["id"], {}, QA))
        final_pool = get_pool(pool_id)
        assert final_pool["total_pooled_lbs"] == 0, (
            f"release+divert must conserve total_pooled_lbs, got {final_pool['total_pooled_lbs']}"
        )
        assert get_receipt(receipt["id"])["disposition"] == "DIVERTED"

    def test_partial_divert_leaves_remaining_pool_lbs(self, api):
        """PRD §3.4: "On a successful diversion, the `MarketingOrderPool` for
        the receipt's calendar month has its `total_pooled_lbs` decremented by
        `net_weight_lbs`" — diverting one of two released receipts leaves the
        other's net weight in the pool.

        Design: Difficulty/compensating_invariant/release_then_divert_conserves_pool_total
        """
        env = setup_intake_env(pool=True)
        pid, hid, pool_id = env["producer"]["id"], env["hauler"]["id"], env["pool"]["id"]

        r1 = setup_releasable_receipt(pid, hid, gross=100000, tare=30000)
        release_receipt(r1["id"], pid)
        r2 = setup_releasable_receipt(
            pid, hid, gross=60000, tare=30000, arrived_at="2026-05-06T08:00:00Z"
        )
        release_receipt(r2["id"], pid)
        assert get_pool(pool_id)["total_pooled_lbs"] == 100000

        get_success_data(api.divert_tanker_receipt(r1["id"], {}, QA))
        assert get_pool(pool_id)["total_pooled_lbs"] == 30000
        assert get_receipt(r2["id"])["disposition"] == "RELEASED_FOR_PROCESSING"
