"""
Multi-step formulas whose rounding order and evaluation order are normative:
the two-step deposit quantity chain and the seven-step collateral valuation.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers.assertions import assert_fields_equal
from test_helpers.test_users import make_lender_headers, make_warehouse_operator_headers


class TestDepositNetBushelsStepwiseRounding:
    @pytest.fixture
    def weighed_load(
        self, licensed_warehouse, new_producer, new_agreement, new_bin, weighed_ticket
    ):
        warehouse = licensed_warehouse()
        producer = new_producer()
        agreement = new_agreement(warehouse["id"], producer["id"])
        storage_bin = new_bin(warehouse["id"])
        return weighed_ticket(warehouse["id"], agreement["id"], storage_bin["id"])

    def test_dockage_is_rounded_before_the_shrink_step_reads_its_base(self, weighed_load):
        """
        Gross 1005 at 4.5 percent dockage rounds to 45 bushels first, leaving
        960 clean bushels; the one excess moisture point then costs
        960 * 1 * 0.0118 = 11 bushels, so net_bushels is 949. Collapsing the two
        factors into a single multiplication rounded once would give 948.

        PRD: "Applying dockage and shrink as a single combined multiplication
        rounded once is wrong; the dockage rounding must land before the shrink
        step reads its base."

        Design: Difficulty/combinatorial_formula/deposit_net_bushels_stepwise_rounding_order
        """
        assert_fields_equal(
            weighed_load,
            {
                "dockage_bushels": 45,
                "clean_bushels": 960,
                "shrink_bushels": 11,
                "net_bushels": 949,
            },
        )
        assert weighed_load["net_bushels"] != 948

    def test_weigh_in_grades_the_load_and_pins_the_settlement_variant(self, weighed_load):
        """
        The same pass that quantifies the load grades it from the three factors
        (56.5 lbs, 2.0 percent damage, 1.0 percent foreign material all clear
        the US_NO_1 thresholds) and copies the agreement's COMMINGLED storage
        kind onto the ticket, which lands in WEIGHED.

        PRD: "A new ticket lands in `ticket_state` `WEIGHED`, with `accepted_at`
        null, and raises the bin's `scheduled_inbound_bushels` by its
        `net_bushels` as a soft reservation."

        Design: Difficulty/combinatorial_formula/deposit_net_bushels_stepwise_rounding_order
        """
        assert_fields_equal(
            weighed_load,
            {
                "assigned_grade": "US_NO_1",
                "settlement_variant": "COMMINGLED",
                "ticket_state": "WEIGHED",
                "accepted_at": None,
            },
        )


class TestLienAdminFeeAndAdvanceRateTier:
    @pytest.fixture
    def big_lot(
        self,
        licensed_warehouse,
        new_producer,
        new_lender,
        new_agreement,
        new_bin,
        accepted_ticket,
        issue_receipt,
        set_clock,
    ):
        """
        A 25000-bushel receipt whose eligible value lands exactly on the
        10,000,000-cent advance-rate threshold before the warehouseman lien is
        deducted, read 16 inclusive days after issuance.
        """
        warehouse = licensed_warehouse()
        producer = new_producer()
        lender = new_lender()
        agreement = new_agreement(warehouse["id"], producer["id"])
        storage_bin = new_bin(warehouse["id"])
        ticket = accepted_ticket(
            warehouse["id"],
            agreement["id"],
            storage_bin["id"],
            gross_bushels=25000,
            moisture_pct=14.0,
            dockage_pct=0.0,
        )
        receipt = issue_receipt(
            warehouse["id"], ticket["id"], producer["id"], receipt_number="WR-0100"
        )
        set_clock("2026-08-20T09:00:00Z")
        return {
            "ticket": ticket,
            "receipt_id": receipt["id"],
            "lender_id": lender["id"],
            "operator_headers": make_warehouse_operator_headers(warehouse["id"]),
            "lender_headers": make_lender_headers(lender["id"]),
        }

    @staticmethod
    def _record_lien(api, big_lot):
        return get_success_data(
            api.create_collateral_lien(
                f.collateral_lien_payload(
                    big_lot["receipt_id"],
                    big_lot["lender_id"],
                    principal_cents=1000000,
                    valuation_basis="MARK_TO_MARKET",
                    mark_price_cents_per_bushel=400,
                    perfection_method="ELECTRONIC_CONTROL",
                ),
                big_lot["lender_headers"],
            ),
            201,
        )

    def test_admin_fee_is_25_bps_of_the_pre_lien_eligible_value(self, api, big_lot):
        """
        On a 25000-bushel US_NO_1 receipt marked at 400 cents the gross and the
        eligible value are both 10,000,000 cents, so the administration fee is
        25 bps of that pre-lien figure — 25000 cents — and it then joins the
        140000-cent provisional storage charge and the 150000-cent receiving
        charge inside a 315000-cent warehouseman lien.

        PRD: "It is keyed on the pre-lien eligible value: not on the gross
        value, and not on the post-lien net value."

        Design: Difficulty/combinatorial_formula/lien_admin_fee_keyed_on_pre_lien_eligible_value
        """
        assert big_lot["ticket"]["net_bushels"] == 25000
        receipt = get_success_data(
            api.get_receipt(big_lot["receipt_id"], big_lot["operator_headers"]), 200
        )
        assert_fields_equal(
            receipt,
            {
                "receiving_charge_cents": 150000,
                "provisional_storage_charge_cents": 140000,
            },
        )

        lien = self._record_lien(api, big_lot)

        assert_fields_equal(
            lien,
            {
                "gross_value_cents": 10000000,
                "eligible_value_cents": 10000000,
                "admin_fee_cents": 25000,
                "warehouseman_lien_cents": 315000,
            },
        )

    def test_advance_rate_tier_is_keyed_on_the_post_lien_net_collateral(
        self, api, big_lot
    ):
        """
        The warehouseman lien pulls the net collateral to 9,685,000 cents, just
        under the 10,000,000-cent threshold, so the tier is 7000 bps and the
        limit is 6,779,500 — not the 7,748,000 that the 8000 bps tier keyed on
        the eligible value would have produced.

        PRD: "The tier is keyed on the **post**-lien net collateral value
        produced by step 5, and the threshold test is inclusive."

        Design: Difficulty/combinatorial_formula/lien_admin_fee_keyed_on_pre_lien_eligible_value
        """
        lien = self._record_lien(api, big_lot)

        assert_fields_equal(
            lien,
            {
                "net_collateral_cents": 9685000,
                "advance_rate_bps": 7000,
                "advance_limit_cents": 6779500,
            },
        )
        assert lien["advance_limit_cents"] != 7748000
