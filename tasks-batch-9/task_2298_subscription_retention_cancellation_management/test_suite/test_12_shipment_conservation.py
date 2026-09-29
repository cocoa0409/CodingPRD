"""The term shipment allotment is conserved across a skip and its reversal.

Signup consumes one shipment unit, an applied skip consumes a second, and reversing the
skip hands that unit back.  At every step the three counters still add up to the plan's
allotment, and none of it touches the committed price.
"""

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_prior_snapshot_shape,
    assert_shipment_units_conserved,
    instant,
    modifications_for,
    pay_invoice,
    read_modification,
    read_subscription,
    request_modification,
    reverse_modification_payload,
    setup_active_subscription,
    validate_success,
)

RETENTION = TEST_USERS["retention_specialist_headers"]

SHIPMENTS_PER_TERM = 12


def _subscription_with_one_applied_skip():
    """Signup on 2026-01-10, invoice paid, then a skip aimed at the 2026-02-07 shipment."""
    world = setup_active_subscription(
        clock="2026-01-10",
        subscriber_overrides={"acquisition_channel": "ORGANIC"},
    )
    pay_invoice(world["invoice"]["id"])
    world["skip"] = request_modification(
        world["subscription"]["id"], "SKIP_SHIPMENT", world["subscriber_headers"],
        skip_ship_at=instant("2026-02-07"))
    return world


class TestTermShipmentConservation:

    def test_a_skip_moves_one_unit_from_remaining_into_skipped(self):
        """Signup leaves 1/0/11 and the applied skip leaves 1/1/10, still summing to 12.

        PRD §2.9: "`term_shipments_remaining` is always `shipments_per_term` minus those
        two counters — never an independently mutated number." and PRD §3.3: "Applying it
        increments `term_shipments_skipped` and decrements `term_shipments_remaining`."

        Design: Difficulty/compensating_invariant/term_shipment_units_conserved_across_skip_and_reversal
        """
        world = setup_active_subscription(
            clock="2026-01-10",
            subscriber_overrides={"acquisition_channel": "ORGANIC"},
        )
        pay_invoice(world["invoice"]["id"])

        assert world["plan"]["shipments_per_term"] == SHIPMENTS_PER_TERM

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["term_shipments_delivered"] == 1
        assert subscription["term_shipments_skipped"] == 0
        assert subscription["term_shipments_remaining"] == 11
        assert_shipment_units_conserved(subscription, SHIPMENTS_PER_TERM)

        skip = request_modification(
            subscription["id"], "SKIP_SHIPMENT", world["subscriber_headers"],
            skip_ship_at=instant("2026-02-07"))
        assert skip["mod_type"] == "SKIP_SHIPMENT"
        assert skip["state"] == "APPLIED"
        # A skip moves no price.
        assert skip["delta_price_cents"] == 0

        subscription = read_subscription(subscription["id"])
        assert subscription["term_shipments_delivered"] == 1
        assert subscription["term_shipments_skipped"] == 1
        assert subscription["term_shipments_remaining"] == 10
        assert_shipment_units_conserved(subscription, SHIPMENTS_PER_TERM)
        assert subscription["committed_price_cents"] == 4999

    def test_reversing_the_skip_hands_the_unit_back_to_remaining(self):
        """The snapshot restores term_shipments_skipped to 0 and remaining returns to 11.

        PRD §3.3: "The snapshot holds exactly seven values — `plan_id`,
        `frequency_weeks`, `addons`, `active_discount_pct`, `discount_remaining_cycles`,
        `committed_price_cents` and `term_shipments_skipped` — and a reversal restores
        precisely those."

        Design: Difficulty/compensating_invariant/term_shipment_units_conserved_across_skip_and_reversal
        """
        world = _subscription_with_one_applied_skip()
        subscription_id = world["subscription"]["id"]

        assert_prior_snapshot_shape(world["skip"]["prior_snapshot"])
        assert world["skip"]["prior_snapshot"]["term_shipments_skipped"] == 0

        response = api_client.reverse_modification(
            world["skip"]["id"], RETENTION,
            reverse_modification_payload(reason_note="subscriber changed their mind"))
        validate_success(response, 200)

        assert read_modification(world["skip"]["id"])["state"] == "REVERSED"

        compensating = modifications_for(
            subscription_id, reverses_modification_id=world["skip"]["id"])
        assert len(compensating) == 1
        assert compensating[0]["state"] == "APPLIED"
        assert compensating[0]["delta_price_cents"] == 0

        subscription = read_subscription(subscription_id)
        assert subscription["term_shipments_delivered"] == 1
        assert subscription["term_shipments_skipped"] == 0
        assert subscription["term_shipments_remaining"] == 11
        assert_shipment_units_conserved(subscription, SHIPMENTS_PER_TERM)
        assert subscription["committed_price_cents"] == 4999
