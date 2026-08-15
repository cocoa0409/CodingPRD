"""FK reverse-reachability: sub-resource lists and filtered lists.

Corner instance: fk_reverse_reachability_subresources_and_filters.
"""
from test_helpers import (
    add_action,
    make_analyst_headers,
    make_board_limit,
    make_line,
    make_metric,
    make_officer_headers,
    make_ops_headers,
    make_playbook,
    make_projection_run,
    make_scenario,
    post_reading,
    setup_line_with_pledge,
    validate_paginated,
)

ANALYST = make_analyst_headers("ta_1")
OFFICER = make_officer_headers("ro_1")
OPS = make_ops_headers("to_1")


class TestFkReverseReachability:
    def test_subresource_lists_return_children(self, api):
        """PRD §3.2: "Runs are listed through their parent scenario and fetched
        individually."
        PRD §3.6: "Readings remain listable under their metric."
        PRD §3.8: "Actions are listed under their playbook".
        PRD §3.7: "Breaches are listed under their limit and fetched
        individually."

        Design: Corner/endpoints/fk_reverse_reachability_subresources_and_filters
        """
        scenario = make_scenario(name="Base", tier="BASELINE")
        run = make_projection_run(scenario["id"], "CONTRACTUAL", scenario["version"])

        metric = make_metric(code="M", name="m")
        limit = make_board_limit(subject="EWI_METRIC", direction="ABOVE_BREACHES",
                                 limit_value=4000, severity="BOARD",
                                 ewi_metric_id=metric["id"])
        post_reading(metric["id"], 6000)  # RED reading + breach on the limit

        playbook = make_playbook(scenario["id"], name="PB",
                                 target_capacity_cents=50_000_000)
        line, _asset, _pledge = setup_line_with_pledge()
        action1 = add_action(playbook["id"], kind="LINE_DRAWDOWN", sequence_no=1,
                             estimated_proceeds_cents=30_000_000,
                             settlement_lag_days=0, line_id=line["id"])
        action2 = add_action(playbook["id"], kind="LINE_DRAWDOWN", sequence_no=2,
                             estimated_proceeds_cents=20_000_000,
                             settlement_lag_days=0, line_id=line["id"],
                             prerequisite_action_id=action1["id"])

        runs, _ = validate_paginated(api.list_projection_runs(scenario["id"], ANALYST))
        assert len(runs) == 1 and runs[0]["id"] == run["id"], (
            f"the scenario's run list must contain the created run, got {len(runs)}"
        )

        readings, _ = validate_paginated(api.list_metric_readings(metric["id"], ANALYST))
        assert len(readings) == 1, f"the metric's reading list must hold one entry, got {len(readings)}"

        actions, _ = validate_paginated(api.list_playbook_actions(playbook["id"], ANALYST))
        assert len(actions) == 2, f"the playbook's action list must hold two entries, got {len(actions)}"

        breaches, _ = validate_paginated(api.list_limit_breaches(limit["id"], OFFICER))
        assert len(breaches) == 1, (
            f"the limit's breach list must hold the detected breach (6000 > 4000), got {len(breaches)}"
        )

    def test_filtered_lists_reach_children_by_fk(self, api):
        """PRD §3.4: "Pledges are listable with `asset_id`, `line_id`, and
        `status` filters".
        PRD §3.8: "Actions are listed under their playbook, through a global
        list filterable by `playbook_id`, `prerequisite_action_id`, `line_id`,
        `asset_id`, and `status`, and fetched individually."
        PRD §3.7: "The limit catalogue lists with `subject` and
        `ewi_metric_id` filters."
        PRD §3.8: "The playbook list supports `scenario_id` and `status`
        filters."

        Design: Corner/endpoints/fk_reverse_reachability_subresources_and_filters
        """
        scenario = make_scenario(name="Base", tier="BASELINE")
        metric = make_metric(code="M", name="m")
        limit = make_board_limit(subject="EWI_METRIC", direction="ABOVE_BREACHES",
                                 limit_value=4000, severity="BOARD",
                                 ewi_metric_id=metric["id"])
        line, asset, pledge = setup_line_with_pledge()
        playbook = make_playbook(scenario["id"], name="PB",
                                 target_capacity_cents=50_000_000)
        action1 = add_action(playbook["id"], kind="LINE_DRAWDOWN", sequence_no=1,
                             estimated_proceeds_cents=30_000_000,
                             settlement_lag_days=0, line_id=line["id"])
        action2 = add_action(playbook["id"], kind="LINE_DRAWDOWN", sequence_no=2,
                             estimated_proceeds_cents=20_000_000,
                             settlement_lag_days=0, line_id=line["id"],
                             prerequisite_action_id=action1["id"])

        pledges, _ = validate_paginated(
            api.list_collateral_pledges(OPS, params={"line_id": line["id"]})
        )
        assert len(pledges) == 1 and pledges[0]["id"] == pledge["id"]

        dependents, _ = validate_paginated(
            api.list_all_playbook_actions(ANALYST, params={"prerequisite_action_id": action1["id"]})
        )
        assert len(dependents) == 1 and dependents[0]["id"] == action2["id"], (
            "the prerequisite filter must reach exactly the dependent action"
        )

        limits, _ = validate_paginated(
            api.list_board_limits(OFFICER, params={"ewi_metric_id": metric["id"]})
        )
        assert len(limits) == 1 and limits[0]["id"] == limit["id"]

        playbooks, _ = validate_paginated(
            api.list_playbooks(ANALYST, params={"scenario_id": scenario["id"]})
        )
        assert len(playbooks) == 1 and playbooks[0]["id"] == playbook["id"]
