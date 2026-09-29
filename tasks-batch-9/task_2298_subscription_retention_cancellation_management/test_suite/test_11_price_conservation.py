"""Committed price is conserved across a downgrade and its reversal.

Two addon additions and a plan downgrade move the committed price three times.
Reversing the downgrade does not erase its delta: the original keeps it and moves to
REVERSED while a compensating row carries the exact inverse, so the ledger still
reconstructs the committed price from the baseline.
"""

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_prior_snapshot_shape,
    assert_price_conserved,
    instant,
    modifications_for,
    new_core_plan,
    new_lite_plan,
    pay_invoice,
    read_modification,
    read_subscription,
    request_modification,
    reverse_modification_payload,
    setup_active_subscription,
    validate_success,
)

RETENTION = TEST_USERS["retention_specialist_headers"]


def _subscription_after_two_addons_and_a_downgrade():
    """Baseline 4999, plus MUG 1299, plus TUMBLER 899, then downgraded onto the 2999 plan."""
    lite = new_lite_plan()
    core = new_core_plan(downgrade_target_plan_id=lite["id"])
    world = setup_active_subscription(
        clock="2026-01-10", plan=core,
        subscriber_overrides={"acquisition_channel": "SEARCH"},
    )
    pay_invoice(world["invoice"]["id"])

    subscription_id = world["subscription"]["id"]
    headers = world["subscriber_headers"]
    world["lite"] = lite
    world["add_mug"] = request_modification(subscription_id, "ADDON_ADD", headers,
                                            addon_code="MUG", addon_qty=1)
    world["add_tumbler"] = request_modification(subscription_id, "ADDON_ADD", headers,
                                                addon_code="TUMBLER", addon_qty=1)
    world["downgrade"] = request_modification(subscription_id, "PLAN_DOWNGRADE", headers,
                                              target_plan_id=lite["id"])
    return world


def _reverse(modification_id, note):
    response = api_client.reverse_modification(
        modification_id, RETENTION, reverse_modification_payload(reason_note=note))
    return validate_success(response, 200)


class TestCommittedPriceConservation:

    def test_the_delta_ledger_still_reconstructs_the_committed_price_after_a_reversal(self):
        """4999 + 1299 + 899 - 4198 + 4198 lands back on 7197.

        PRD §2.9: "A reversal does **not** erase the original row's delta: the original
        keeps its value and moves to `REVERSED`, and a compensating row is added
        carrying the exact arithmetic inverse, so a forward-plus-compensating pair
        leaves `committed_price_cents` where it started."

        Design: Difficulty/compensating_invariant/committed_price_conserved_across_downgrade_and_reversal
        """
        world = _subscription_after_two_addons_and_a_downgrade()
        subscription_id = world["subscription"]["id"]

        assert world["add_mug"]["delta_price_cents"] == 1299
        assert world["add_tumbler"]["delta_price_cents"] == 899
        # 2999 committed on the target plan against 7197 before the downgrade.
        assert world["downgrade"]["delta_price_cents"] == -4198

        subscription = read_subscription(subscription_id)
        assert subscription["baseline_price_cents"] == 4999
        assert subscription["committed_price_cents"] == 2999

        _reverse(world["downgrade"]["id"], "downgrade applied in error")
        original = read_modification(world["downgrade"]["id"])
        assert original["state"] == "REVERSED"
        assert original["delta_price_cents"] == -4198

        compensating = modifications_for(
            subscription_id, reverses_modification_id=world["downgrade"]["id"])
        assert len(compensating) == 1
        assert compensating[0]["state"] == "APPLIED"
        assert compensating[0]["delta_price_cents"] == 4198

        subscription = read_subscription(subscription_id)
        assert subscription["committed_price_cents"] == 7197
        assert 4999 + 1299 + 899 + (-4198) + 4198 == subscription["committed_price_cents"]
        assert_price_conserved(subscription, modifications_for(subscription_id))

    def test_the_reversal_restores_the_snapshot_and_a_scheduled_row_moves_nothing(self):
        """The plan and both addons come back, and a future-dated removal changes no price.

        PRD §3.3: "Every application captures `prior_snapshot` immediately before
        touching the subscription. The snapshot holds exactly seven values —
        `plan_id`, `frequency_weeks`, `addons`, `active_discount_pct`,
        `discount_remaining_cycles`, `committed_price_cents` and
        `term_shipments_skipped` — and a reversal restores precisely those."

        Design: Difficulty/compensating_invariant/committed_price_conserved_across_downgrade_and_reversal
        """
        world = _subscription_after_two_addons_and_a_downgrade()
        subscription_id = world["subscription"]["id"]

        assert_prior_snapshot_shape(world["downgrade"]["prior_snapshot"])
        _reverse(world["downgrade"]["id"], "downgrade applied in error")

        subscription = read_subscription(subscription_id)
        assert subscription["plan_id"] == world["plan"]["id"]
        assert sorted(addon["code"] for addon in subscription["addons"]) == ["MUG", "TUMBLER"]
        assert subscription["committed_price_cents"] == 7197

        scheduled = request_modification(
            subscription_id, "ADDON_REMOVE", world["subscriber_headers"],
            addon_code="MUG", effective_at=instant("2026-03-01"))
        assert scheduled["state"] == "SCHEDULED"
        assert scheduled["delta_price_cents"] == 0
        assert scheduled["applied_at"] is None

        subscription = read_subscription(subscription_id)
        assert subscription["committed_price_cents"] == 7197
        assert len(subscription["addons"]) == 2
        assert_price_conserved(subscription, modifications_for(subscription_id))
