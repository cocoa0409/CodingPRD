"""
Non-linear state dimensions: the warehouse's licensing revert cycle running
alongside an independent insolvency dimension, and the receipt's cyclic
encumbrance dimension running underneath a stationary receipt_state.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers.assertions import assert_fields_equal
from test_helpers.test_users import REGULATOR_HEADERS


class TestWarehouseLicenseCycleAndInsolvencyIndependence:
    def test_license_dimension_reverts_from_suspended_back_to_licensed(
        self, api, base_full
    ):
        """
        SUSPEND drives the licence out of LICENSED and closes the posture;
        REINSTATE is the revert edge back to LICENSED, and because the facility
        is still SOLVENT with zero position variance the posture returns to OPEN.

        PRD: "`SUSPENDED → LICENSED` on `REINSTATE`, the revert edge."

        Design: Difficulty/non_linear_state_machine/warehouse_license_cycle_and_insolvency_dimension_independence
        """
        warehouse_id = base_full["warehouse_id"]

        suspended = get_success_data(
            api.license_decision(
                warehouse_id,
                f.license_decision_payload("SUSPEND", note="moisture control findings"),
                REGULATOR_HEADERS,
            ),
            200,
        )
        assert_fields_equal(
            suspended,
            {
                "license_state": "SUSPENDED",
                "insolvency_state": "SOLVENT",
                "operational_posture": "CLOSED",
            },
        )

        reinstated = get_success_data(
            api.license_decision(
                warehouse_id,
                f.license_decision_payload("REINSTATE", note="findings cleared"),
                REGULATOR_HEADERS,
            ),
            200,
        )
        assert_fields_equal(
            reinstated,
            {"license_state": "LICENSED", "operational_posture": "OPEN"},
        )

    def test_insolvency_declaration_leaves_the_license_state_untouched(
        self, api, base_full
    ):
        """
        After the licence has cycled back to LICENSED, an insolvency
        declaration at 400 cents per bushel moves only the insolvency dimension:
        the row reads LICENSED and DECLARED at once, the posture is CLOSED, and
        the issued receipt survives both dimensions moving.

        PRD: "The insolvency dimension is entirely independent of the licensing
        dimension."

        Design: Difficulty/non_linear_state_machine/warehouse_license_cycle_and_insolvency_dimension_independence
        """
        warehouse_id = base_full["warehouse_id"]
        get_success_data(
            api.license_decision(
                warehouse_id,
                f.license_decision_payload("SUSPEND", note="moisture control findings"),
                REGULATOR_HEADERS,
            ),
            200,
        )
        get_success_data(
            api.license_decision(
                warehouse_id,
                f.license_decision_payload("REINSTATE", note="findings cleared"),
                REGULATOR_HEADERS,
            ),
            200,
        )

        get_success_data(
            api.insolvency_action(
                warehouse_id,
                f.insolvency_payload(
                    "DECLARE",
                    insolvency_price_cents_per_bushel=400,
                    note="operator default",
                ),
                REGULATOR_HEADERS,
            ),
            200,
        )

        warehouse = get_success_data(
            api.get_warehouse(warehouse_id, REGULATOR_HEADERS), 200
        )
        assert_fields_equal(
            warehouse,
            {
                "license_state": "LICENSED",
                "insolvency_state": "DECLARED",
                "operational_posture": "CLOSED",
                "insolvency_price_cents_per_bushel": 400,
            },
        )

        receipt = get_success_data(
            api.get_receipt(base_full["receipt_id"], base_full["operator_headers"]), 200
        )
        assert receipt["receipt_state"] == "ISSUED"


class TestReceiptEncumbranceCycle:
    def _pledge_release_pledge(self, api, base_full, set_clock):
        set_clock("2026-08-20T09:00:00Z")
        lender_headers = base_full["lender_headers"]
        lien_one = get_success_data(
            api.create_collateral_lien(
                f.collateral_lien_payload(
                    base_full["receipt_id"], base_full["lender_id"]
                ),
                lender_headers,
            ),
            201,
        )
        get_success_data(
            api.perfect_lien(lien_one["id"], f.perfect_payload(), lender_headers), 200
        )
        first_pledge = get_success_data(
            api.get_receipt(base_full["receipt_id"], base_full["operator_headers"]), 200
        )

        get_success_data(
            api.release_lien(lien_one["id"], f.release_payload(250000), lender_headers),
            200,
        )
        released = get_success_data(
            api.get_receipt(base_full["receipt_id"], base_full["operator_headers"]), 200
        )

        lien_two = get_success_data(
            api.create_collateral_lien(
                f.collateral_lien_payload(
                    base_full["receipt_id"],
                    base_full["lender_id"],
                    principal_cents=100000,
                    valuation_basis="FACE_ADVANCE",
                ),
                lender_headers,
            ),
            201,
        )
        get_success_data(
            api.perfect_lien(
                lien_two["id"], f.perfect_payload(attestation_note="re-pledged"), lender_headers
            ),
            200,
        )
        second_pledge = get_success_data(
            api.get_receipt(base_full["receipt_id"], base_full["operator_headers"]), 200
        )
        return {
            "lien_one_id": lien_one["id"],
            "lien_two_id": lien_two["id"],
            "first_pledge": first_pledge,
            "released": released,
            "second_pledge": second_pledge,
        }

    def test_encumbrance_dimension_cycles_pledged_released_and_pledged_again(
        self, api, base_full, set_clock
    ):
        """
        Electronic control sets registry_control_party_id to the lender and
        leaves the holder alone; release clears it; a second lien pledges the
        very same receipt again — and receipt_state never leaves ISSUED.

        PRD: "The collateral dimension, `encumbrance_state`, starts at
        `UNENCUMBERED`, cycles through `PLEDGED` and `RELEASED`, and has no
        terminal state at all — a released receipt can be pledged again."

        Design: Difficulty/non_linear_state_machine/receipt_encumbrance_cycle_independent_of_receipt_state
        """
        result = self._pledge_release_pledge(api, base_full, set_clock)

        assert_fields_equal(
            result["first_pledge"],
            {
                "encumbrance_state": "PLEDGED",
                "registry_control_party_id": base_full["lender_id"],
                "holder_party_id": base_full["depositor_id"],
                "receipt_state": "ISSUED",
            },
        )
        assert_fields_equal(
            result["released"],
            {
                "encumbrance_state": "RELEASED",
                "registry_control_party_id": None,
                "holder_party_id": base_full["depositor_id"],
                "receipt_state": "ISSUED",
            },
        )
        assert_fields_equal(
            result["second_pledge"],
            {
                "encumbrance_state": "PLEDGED",
                "registry_control_party_id": base_full["lender_id"],
                "receipt_state": "ISSUED",
            },
        )

    def test_re_pledging_commits_the_second_liens_limit_against_the_line(
        self, api, base_full, set_clock
    ):
        """
        The withdrawn first lien is terminal in RELEASED while the second lien
        is PERFECTED, and only the live lien's 271300-cent limit (a FACE_ADVANCE
        on 949 bushels at the pinned 420-cent face value) is committed against
        the lender's 50,000,000-cent line.

        PRD: "`committed_advance_cents` is the sum of `advance_limit_cents`
        across every lien naming this party as lender whose `lien_state` is
        `PERFECTED`."

        Design: Difficulty/non_linear_state_machine/receipt_encumbrance_cycle_independent_of_receipt_state
        """
        result = self._pledge_release_pledge(api, base_full, set_clock)

        lien_one = get_success_data(
            api.get_collateral_lien(result["lien_one_id"], base_full["lender_headers"]),
            200,
        )
        lien_two = get_success_data(
            api.get_collateral_lien(result["lien_two_id"], base_full["lender_headers"]),
            200,
        )
        assert lien_one["lien_state"] == "RELEASED"
        assert_fields_equal(
            lien_two, {"lien_state": "PERFECTED", "advance_limit_cents": 271300}
        )

        lender = get_success_data(
            api.get_party(base_full["lender_id"], base_full["lender_headers"]), 200
        )
        assert_fields_equal(
            lender,
            {"committed_advance_cents": 271300, "available_credit_cents": 49728700},
        )
