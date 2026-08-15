"""Counterfeit safety: suspect flag gating, quarantine cascades, release."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_seller, create_customer, create_bin, create_lot, create_active_listing,
    create_listing_payload, place_order, fund_order_fully,
    setup_listed_broker_owned_scenario,
    make_customer_headers,
    api_client,
    TEST_USERS,
    ApiErrorId,
)

BROKER = TEST_USERS["broker_ops_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


class TestQuarantineCascade:
    def test_quarantine_withdraws_active_listing(self, api):
        """PRD section 3.3: "Quarantine forces the lot's status to
        `QUARANTINED` regardless of the posture derivation and withdraws every
        `ACTIVE` listing on the lot, each moving to `WITHDRAWN`; open orders on
        the lot remain in place, but they cannot be fulfilled and cannot be
        settled while the quarantine stands, both attempts failing with
        `ERR_LOT_QUARANTINED`."

        Design: Corner/state_machines/quarantine_cascades_active_listing_to_withdrawn
        """
        sc = setup_listed_broker_owned_scenario(
            mpn="ATmega328P", quantity=5, agreed_unit_price_cents=7000,
            asking_price_per_unit_cents=9000, bin_capacity=20,
        )
        validate_success(
            api.flag_lot_counterfeit_suspect(sc["lot"]["id"], INSPECTOR), 200
        )
        quarantined = validate_success(
            api.quarantine_lot(
                sc["lot"]["id"], INSPECTOR, payload={"quarantine_note": "x-ray anomaly"}
            ),
            200,
        )
        assert quarantined["status"] == "QUARANTINED"

        listing = validate_success(api.get_listing(sc["listing"]["id"], BROKER), 200)
        assert listing["status"] == "WITHDRAWN"


class TestFulfillBlockedOnQuarantine:
    def _scenario(self, api):
        sc = setup_listed_broker_owned_scenario(
            mpn="MCP6002", quantity=5, agreed_unit_price_cents=4000,
            asking_price_per_unit_cents=5000,
            credit_limit_cents=50000, urgency_tier="STANDARD", bin_capacity=20,
        )
        order = place_order(sc["customer"], sc["listing"], quantity=1)
        funded = fund_order_fully(sc["customer"], order)
        validate_success(
            api.flag_lot_counterfeit_suspect(sc["lot"]["id"], INSPECTOR), 200
        )
        validate_success(api.quarantine_lot(sc["lot"]["id"], INSPECTOR), 200)
        return sc, funded

    def test_fulfill_on_quarantined_lot_rejected(self, api):
        """PRD section 3.7: "Fulfillment begins by moving the order from
        `ESCROW_FUNDED` to `FULFILLING` — a step blocked while the lot is
        quarantined, failing with `ERR_LOT_QUARANTINED`."

        Design: Corner/state_machines/fulfill_blocked_on_quarantined_lot
        """
        sc, funded = self._scenario(api)
        res = api.fulfill_sales_order(funded["id"], BROKER)
        validate_error(res, ApiErrorId.ERR_LOT_QUARANTINED, expected_status=409)

    def test_order_state_untouched_by_rejected_fulfill(self, api):
        """PRD section 3.3: "open orders on the lot remain in place, but they
        cannot be fulfilled and cannot be settled while the quarantine stands,
        both attempts failing with `ERR_LOT_QUARANTINED`."

        Design: Corner/state_machines/fulfill_blocked_on_quarantined_lot
        """
        sc, funded = self._scenario(api)
        validate_error(
            api.fulfill_sales_order(funded["id"], BROKER),
            ApiErrorId.ERR_LOT_QUARANTINED,
        )
        order = validate_success(api.get_sales_order(funded["id"], BROKER), 200)
        assert order["status"] == "ESCROW_FUNDED", (
            "a rejected fulfill must leave the order in ESCROW_FUNDED"
        )


class TestReleaseQuarantine:
    def test_release_clears_flag_and_restores_in_stock(self, api):
        """PRD section 3.3: "Releasing the quarantine is valid only on a
        `QUARANTINED` lot: it clears the suspect flag and recomputes the base
        posture, which cannot be `LISTED` at that moment — quarantine withdrew
        every listing, and activation was impossible while the flag stood — so
        the lot ordinarily lands back on `IN_STOCK`."

        Design: Corner/cross_cutting_layers/cascading_side_effects_release_quarantine_restores_posture
        """
        sc = setup_listed_broker_owned_scenario(
            mpn="ATmega328P", quantity=5, agreed_unit_price_cents=7000,
            asking_price_per_unit_cents=9000, bin_capacity=20,
        )
        validate_success(
            api.flag_lot_counterfeit_suspect(sc["lot"]["id"], INSPECTOR), 200
        )
        validate_success(api.quarantine_lot(sc["lot"]["id"], INSPECTOR), 200)

        released = validate_success(
            api.release_lot_quarantine(sc["lot"]["id"], INSPECTOR), 200
        )
        assert released["status"] == "IN_STOCK"
        assert released["is_counterfeit_suspect"] is False

    def test_release_does_not_undo_listing_withdrawal(self, api):
        """PRD section 3.3: "Releasing the quarantine is valid only on a
        `QUARANTINED` lot: it clears the suspect flag and recomputes the base
        posture, which cannot be `LISTED` at that moment — quarantine withdrew
        every listing, and activation was impossible while the flag stood — so
        the lot ordinarily lands back on `IN_STOCK`."
        PRD section 3.5: "Withdrawing is permanent"

        Design: Corner/cross_cutting_layers/cascading_side_effects_release_quarantine_restores_posture
        """
        sc = setup_listed_broker_owned_scenario(
            mpn="ATmega328P", quantity=5, agreed_unit_price_cents=7000,
            asking_price_per_unit_cents=9000, bin_capacity=20,
        )
        validate_success(
            api.flag_lot_counterfeit_suspect(sc["lot"]["id"], INSPECTOR), 200
        )
        validate_success(api.quarantine_lot(sc["lot"]["id"], INSPECTOR), 200)
        validate_success(api.release_lot_quarantine(sc["lot"]["id"], INSPECTOR), 200)

        listing = validate_success(api.get_listing(sc["listing"]["id"], BROKER), 200)
        assert listing["status"] == "WITHDRAWN", (
            "quarantine withdrawal is not undone by release"
        )


class TestSafetyPrecedence:
    def test_rejected_activation_leaves_listing_draft(self, api):
        """PRD section 3.3: "the flag alone blocks listing activation and new
        order creation against the lot, both failing with
        `ERR_COUNTERFEIT_SUSPECTED`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_listing_activate
        """
        seller = create_seller(name="Juliet Joint")
        storage_bin = create_bin(capacity_units=100, bin_code="BIN-J1")
        lot, _ = create_lot(
            seller, storage_bin, mpn="ATmega328P", quantity=10,
            ask_price_per_unit_cents=8000, agreed_unit_price_cents=8000,
            provenance_doc_url="https://docs.x.com/p10.pdf",
        )
        # Asking 8000 satisfies the creation-time floor check (floor is 6400);
        # the suspect flag alone then blocks activation.
        listing = validate_success(
            api.create_listing(
                create_listing_payload(lot["id"], asking_price_per_unit_cents=8000),
                BROKER,
            ),
            201,
        )
        validate_success(api.flag_lot_counterfeit_suspect(lot["id"], INSPECTOR), 200)
        validate_error(
            api.activate_listing(listing["id"], BROKER),
            ApiErrorId.ERR_COUNTERFEIT_SUSPECTED,
        )

        reread = validate_success(api.get_listing(listing["id"], BROKER), 200)
        assert reread["status"] == "DRAFT"
