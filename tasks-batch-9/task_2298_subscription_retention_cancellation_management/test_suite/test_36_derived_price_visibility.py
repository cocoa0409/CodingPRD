"""The derived price is current the moment the write returns.

Adding an extra is a single settled write: the response that creates the ledger row already
carries the price delta and the pre-change snapshot, and the very next read of the
subscription shows the recomputed commitment — with the already-issued invoice untouched.
"""

from test_helpers import (
    api_client,
    create_modification_payload,
    read_invoice,
    read_subscription,
    setup_active_subscription,
    validate_success,
)


class TestAddonAdditionRepricesWithoutALag:

    def test_the_creating_response_and_the_next_read_already_agree_on_the_new_price(self):
        """Delta 1299 on the ledger row, commitment 6298 on the very next read.

        PRD §3.3: "`committed_price_cents` is recomputed on every transition that moves
        `plan_id`, `addons`, `active_discount_pct` or `frequency_weeks` — a modification
        applied, a modification reversed, a save offer accepted, a save offer revoked."

        Design: Corner/consistency model/addon_add_is_visible_in_the_same_response_and_on_reread
        """
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "ORGANIC"})
        subscription_id = world["subscription"]["id"]
        assert world["subscription"]["version"] == 1

        payload = create_modification_payload("ADDON_ADD", 1, addon_code="MUG", addon_qty=1)
        row = validate_success(api_client.create_modification(
            subscription_id, payload, world["subscriber_headers"]), 201)

        assert row["state"] == "APPLIED"
        assert row["delta_price_cents"] == 1299
        assert row["prior_snapshot"]["addons"] == []
        assert row["prior_snapshot"]["committed_price_cents"] == 4999

        repriced = read_subscription(subscription_id)
        assert len(repriced["addons"]) == 1
        assert repriced["addons"][0]["code"] == "MUG"
        assert repriced["addons"][0]["qty"] == 1
        assert repriced["addons"][0]["unit_price_cents"] == 1299
        assert repriced["addons"][0]["unit_cogs_cents"] == 520
        assert repriced["committed_price_cents"] == 6298
        assert repriced["baseline_price_cents"] == 4999
        assert repriced["version"] == 2

        # The extra joins future cycles only; the cycle already invoiced keeps its price.
        signup = read_invoice(world["invoice"]["id"])
        assert signup["amount_cents"] == 4999
        assert signup["cogs_cents"] == 2100
