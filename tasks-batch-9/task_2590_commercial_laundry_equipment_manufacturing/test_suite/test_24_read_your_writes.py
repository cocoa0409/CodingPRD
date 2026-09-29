"""Writes that mutate a parent report the finished parent in their own response.

There is no window in which a distributor has been authorized, or a part has
fallen to its reorder point, but the system still answers with the old figure: the
write that crossed the line returns the recomputed row, an immediately following
read agrees with it field for field, and a filtered listing already selects it.
"""

from prd_bench_local_runner.testing import validate_success
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    PLANT_MANAGER,
    PRODUCT_ENGINEER,
    TRAINING_ADMIN,
)


class TestTrainingCompletionVisibility:
    """The completion that authorizes a distributor says so in its own body."""

    def test_01_authorization_is_reported_by_the_writing_call(self, api):
        """The second technician's payment-systems record crosses the threshold, and
        the new standing, the recomputed headcount and the derived training state
        are all readable from that write's own response.

        PRD: "Action endpoints that mutate a parent rather than creating a child return the mutated parent resource."
        Design: Corner/consistency_model/training_completion_authorization_visible_in_the_same_response
        """
        channel = fx.make_pending_distributor(api)
        distributor_id = channel["distributor"]["id"]
        first, second = channel["technicians"]
        fx.record_training(api, distributor_id, first["id"], "INSTALLATION", "2026-07-20")

        written = validate_success(
            api.create_training_completion(
                distributor_id,
                f.training_completion_payload(
                    second["id"], "PAYMENT_SYSTEMS", "2026-07-21"
                ),
                TRAINING_ADMIN,
            ),
            expected_status=200,
        )
        assert written["distributor_state"] == "AUTHORIZED"
        assert written["trained_technician_count"] == 2
        assert written["installation_training_state"] == "COMPLETE"

        read_back = validate_success(
            api.get_distributor(distributor_id, TRAINING_ADMIN), expected_status=200
        )
        assert read_back["distributor_state"] == written["distributor_state"]
        assert read_back["version"] == written["version"]
        assert read_back["installation_training_state"] == "COMPLETE"
        assert len(read_back["completed_training_keys"]) == 2
        assert read_back == written, (
            "The write already returned the mutated distributor, so the following "
            f"read must agree with it: {written} then {read_back}"
        )

        # The authorization is visible to a filtered listing straight away.
        authorized = validate_success(
            api.list_distributors(TRAINING_ADMIN, distributor_state="AUTHORIZED"),
            expected_status=200,
        )
        assert len(authorized) == 1
        assert authorized[0]["id"] == distributor_id


class TestStockAdjustmentVisibility:
    """The adjustment that reaches the reorder point projects LOW in its own body."""

    def test_01_reorder_point_is_projected_by_the_adjusting_write(self, api):
        """A shrinkage of one unit drops the shelf to the inclusive reorder point,
        and the write itself reports the new quantity and the new stock state.

        PRD: "The same `stock_state` re-projection runs afterwards, with the same two cascades attached: entering `BACKORDERED` blocks every `SUBMITTED` claim on the part with `block_reason` `PART_BACKORDERED`, and leaving `BACKORDERED` returns the blocked ones to `SUBMITTED`."
        Design: Corner/consistency_model/stock_adjustment_state_visible_in_the_same_response
        """
        part = fx.make_service_part(api)
        assert part["on_hand_qty"] == 0
        assert part["stock_state"] == "BACKORDERED"
        assert part["reorder_point_qty"] == 2

        received = validate_success(
            api.create_stock_adjustment(
                part["id"], f.stock_adjustment_payload(3, "RECEIPT"), PLANT_MANAGER
            ),
            expected_status=200,
        )
        assert received["on_hand_qty"] == 3
        assert received["stock_state"] == "IN_STOCK"

        written = validate_success(
            api.create_stock_adjustment(
                part["id"], f.stock_adjustment_payload(-1, "SHRINKAGE"), PLANT_MANAGER
            ),
            expected_status=200,
        )
        assert written["on_hand_qty"] == 2
        assert written["stock_state"] == "LOW"
        assert written["version"] == 3

        read_back = validate_success(
            api.get_service_part(part["id"], PRODUCT_ENGINEER), expected_status=200
        )
        assert read_back["on_hand_qty"] == written["on_hand_qty"]
        assert read_back["stock_state"] == written["stock_state"]
        assert read_back["version"] == written["version"]
        assert read_back == written, (
            "The adjustment already returned the re-projected part, so the "
            f"following read must agree with it: {written} then {read_back}"
        )

        # The new stock position is immediately selectable by the listing filter.
        low = validate_success(
            api.list_service_parts(PRODUCT_ENGINEER, stock_state="LOW"),
            expected_status=200,
        )
        assert len(low) == 1
        assert low[0]["id"] == part["id"]
