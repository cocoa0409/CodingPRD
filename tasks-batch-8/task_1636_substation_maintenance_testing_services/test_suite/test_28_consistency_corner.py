"""Corner coverage — consistency model: write effects are visible in the
mutation response itself and in the immediately following read."""
from test_helpers import (
    TEST_USERS,
    api_client,
    setup_asset,
    validate_success,
)

OPS = TEST_USERS["ops_manager_headers"]


class TestImmediateConsistency:
    def test_create_response_and_immediate_read_agree(self):
        """PRD §3.1: "The new asset arrives in `IN_SERVICE` status with
        `condition_score` initialized to 100.00 and `next_due_date` computed
        from the condition-adjusted variant described in §3.5."
        PRD §3.5: "Both share a baseline: the asset's
        `last_maintenance_completed_at` when set, else its `install_date`. The
        **interval-baseline** variant adds the policy's `interval_months` to
        the baseline regardless of condition."

        Design: Corner/consistency_model/immediate_consistency_on_create_and_mutate
        """
        sub_policy = setup_asset(
            "POWER_TRANSFORMER", install_date="2020-06-01T00:00:00Z"
        )
        asset_id = sub_policy["asset"]["id"]
        # Re-issue the create's twin read immediately: the response of creation
        # already carried the computed fields, and the following GET agrees.
        created = sub_policy["asset"]
        assert abs(created["condition_score"] - 100.00) < 1e-9
        assert created["next_due_date"] == "2021-06-01"
        read = validate_success(api_client.get_asset(asset_id, OPS))
        assert read["condition_score"] == created["condition_score"]
        assert read["next_due_date"] == created["next_due_date"]
