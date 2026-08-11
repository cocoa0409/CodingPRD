"""Assembly run rework cycle and excess shipment selection.

Covers PRD §3.4: the KITTING -> KITTED -> KITTING -> KITTED loop, delta
commits after rework, and the deterministic excess-cancellation selector.
"""
from test_helpers import (
    api_client,
    assert_assembly_run,
    complete_kitting_payload,
    create_active_plan_with_bom,
    create_client,
    create_run,
    create_stocked_component,
    get_component,
    get_run,
    import_named_subscribers,
    list_run_shipments,
    lock_run,
    rework_payload,
    set_clock,
    setup_kitted_scenario,
    validate_success,
    TEST_USERS,
)

WAREHOUSE = TEST_USERS["warehouse_ops_headers"]


class TestReworkCycle:
    def _setup_nl1(self):
        """Run LOCKED with planned 3, then completed with actual 2."""
        return setup_kitted_scenario(
            "NL1", num_subscribers=3, actual_kitted_count=2,
            qty_per_box=1, stock=500, price_per_box_cents=1000,
            shipping_weight_grams=1000, wallet_cents=100000, run_state="KITTED")

    def test_rework_recomplete_commits_only_positive_delta(self):
        """PRD §3.4: "The newly committed quantity per line is always
        `actual_kitted_count` minus the run's current `kitted_box_count`".
        PRD §3.4: "On a completion after rework, the reservation is already
        gone, so `COMMIT` events draw straight from stock: `on_hand_units`
        alone drops by the delta quantity per line." PRD §3.4: "rework moves
        `KITTED → KITTING`".

        Design: Difficulty/non_linear_state_machine/assembly_run_rework_cycle_delta_commit
        """
        env = self._setup_nl1()
        run_id = env["run"]["id"]
        component_id = env["component"]["id"]

        mid = get_component(component_id)
        assert mid["on_hand_units"] == 498 and mid["reserved_units"] == 0, (
            f"first completion commits 2 and releases the excess reservation: "
            f"on_hand {mid['on_hand_units']}, reserved {mid['reserved_units']}"
        )

        reworked = validate_success(
            api_client.rework_assembly_run(run_id, rework_payload("found 1 kitting miss"),
                                           WAREHOUSE))
        assert reworked["status"] == "KITTING", "rework must cycle KITTED -> KITTING"

        recompleted = validate_success(
            api_client.complete_kitting(run_id, complete_kitting_payload(3),
                                        WAREHOUSE))
        assert_assembly_run(recompleted)
        assert recompleted["status"] == "KITTED"
        assert recompleted["kitted_box_count"] == 3

        after = get_component(component_id)
        assert after["on_hand_units"] == 497, (
            f"re-completion must commit only the +1 delta, not 3: "
            f"on_hand {after['on_hand_units']}"
        )
        assert after["reserved_units"] == 0

    def test_rework_recomplete_never_uncancels_excess_shipment(self):
        """PRD §3.4: "This selection never re-runs and never un-cancels;
        re-completions after a rework loop commit deltas only."

        Design: Difficulty/non_linear_state_machine/assembly_run_rework_cycle_delta_commit
        """
        env = self._setup_nl1()
        run_id = env["run"]["id"]
        cancelled_before = list_run_shipments(run_id, fulfill_status="CANCELLED")
        assert len(cancelled_before) == 1, \
            "first completion with actual 2 of planned 3 cancels exactly one shipment"

        validate_success(api_client.rework_assembly_run(
            run_id, rework_payload("rework"), WAREHOUSE))
        validate_success(api_client.complete_kitting(
            run_id, complete_kitting_payload(3), WAREHOUSE))

        cancelled_after = list_run_shipments(run_id, fulfill_status="CANCELLED")
        assert len(cancelled_after) == 1, \
            "the excess-cancelled shipment must stay CANCELLED after rework"
        assert cancelled_after[0]["id"] == cancelled_before[0]["id"], \
            "selection must not re-run onto a different shipment"
        staged = list_run_shipments(run_id, fulfill_status="STAGED")
        assert len(staged) == 2, f"two kept shipments remain STAGED, got {len(staged)}"


class TestExcessShipmentSelection:
    def test_excess_selection_cancels_newest_subscriber_first(self):
        """PRD §3.4: "the excess is `planned_box_count` minus
        `actual_kitted_count`, the candidates are the run's shipments still in
        `QUEUED`, ordered by their subscriber's `created_at` descending with
        ties broken by `email` ascending, and the first excess-count candidates
        are cancelled to `CANCELLED`." PRD §3.4: "Shipments the run keeps move
        `QUEUED → STAGED` at completion."

        Design: Corner/calculations/excess_selection_cancels_newest_subscriber_first
        """
        set_clock()
        client = create_client(wallet_cents=100000, name="CC3 Client",
                               billing_email="cc3@acme.test")
        component = create_stocked_component("CMP-CC3", 50)
        plan, _revision = create_active_plan_with_bom(
            client["id"], "PL-CC3", [(component["id"], 1)],
            price_per_box_cents=1000, shipping_weight_grams=800)
        # One batch, imported in order; every row shares the same logical-clock
        # created_at, so the tie-break decides: email ascending puts
        # aaa@x.test first in the cancellation order.
        import_named_subscribers(plan["id"], client["id"], [
            ("cc3m1@x.test", 2), ("cc3m2@x.test", 2), ("aaa@x.test", 2),
        ])
        run = create_run(plan["id"])
        locked = lock_run(run["id"])
        assert locked["planned_box_count"] == 3
        validate_success(api_client.start_kitting(run["id"], WAREHOUSE))

        validate_success(api_client.complete_kitting(
            run["id"], complete_kitting_payload(2), WAREHOUSE))

        cancelled = list_run_shipments(run["id"], fulfill_status="CANCELLED")
        assert len(cancelled) == 1, "exactly one excess shipment is cancelled"
        cancelled_subscriber = validate_success(
            api_client.get_subscriber(cancelled[0]["subscriber_id"], WAREHOUSE))
        assert cancelled_subscriber["email"] == "aaa@x.test", (
            f"the newest-created / email-first subscriber must be dropped, "
            f"got {cancelled_subscriber['email']}"
        )
        staged = list_run_shipments(run["id"], fulfill_status="STAGED")
        assert len(staged) == 2, "the two kept shipments move QUEUED -> STAGED"
