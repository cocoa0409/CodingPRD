"""Budget posture thresholds, inclusive boundaries, OCC on budget updates."""

from test_helpers import (
    ApiErrorId,
    api_client,
    create_budget,
    create_paid_invoice,
    get_success_data,
    setup_matter_graph,
    validate_success,
    validate_error,
    ANALYST,
    MANAGER,
)


class TestTieredThreshold:
    def test_posture_walks_ok_critical_exceeded(self, api):
        """PRD §2.7: "A ratio of at least 1.0 yields `EXCEEDED`; failing that, a
        ratio of at least `budget_critical_pct` yields `CRITICAL`; failing that, a
        ratio of at least `budget_warning_pct` yields `WARNING`; anything lower is
        `OK`. All three comparisons are inclusive at the boundary — an exact tie
        resolves toward the more severe posture."

        Design: Difficulty/combinatorial_formula/budget_posture_three_input_tiered_threshold
        """
        graph = setup_matter_graph(
            dept_overrides={"budget_warning_pct": 0.80, "budget_critical_pct": 0.95}
        )
        fp_id = graph["fiscal_period"]["id"]
        budget = create_budget(
            fp_id, graph["practice_area"]["id"], 10000000,
            matter_type_id=graph["matter_type"]["id"],
        )
        m_id = graph["matter"]["id"]
        firm_id = graph["firm"]["id"]

        # 79% consumed — below warning: OK
        create_paid_invoice(m_id, firm_id, fp_id, 7900000)
        b = get_success_data(api_client.get_budget(budget["id"], ANALYST))
        assert b["consumed_cents"] == 7900000
        assert b["posture"] == "OK"

        # 95% consumed — exactly at the critical threshold: CRITICAL (inclusive)
        create_paid_invoice(m_id, firm_id, fp_id, 1600000)
        b = get_success_data(api_client.get_budget(budget["id"], ANALYST))
        assert b["consumed_cents"] == 9500000
        assert b["posture"] == "CRITICAL"

        # 100% consumed — exactly at ratio 1.0: EXCEEDED (inclusive)
        create_paid_invoice(m_id, firm_id, fp_id, 500000)
        b = get_success_data(api_client.get_budget(budget["id"], ANALYST))
        assert b["consumed_cents"] == 10000000
        assert b["posture"] == "EXCEEDED"

    def test_warning_boundary_inclusive(self, api):
        """PRD §2.7: "A ratio of at least 1.0 yields `EXCEEDED`; failing that, a
        ratio of at least `budget_critical_pct` yields `CRITICAL`; failing that, a
        ratio of at least `budget_warning_pct` yields `WARNING`; anything lower is
        `OK`. All three comparisons are inclusive at the boundary — an exact tie
        resolves toward the more severe posture."

        Design: Difficulty/combinatorial_formula/budget_posture_three_input_tiered_threshold
        """
        graph = setup_matter_graph(
            dept_overrides={"budget_warning_pct": 0.80, "budget_critical_pct": 0.95}
        )
        fp_id = graph["fiscal_period"]["id"]
        budget = create_budget(
            fp_id, graph["practice_area"]["id"], 10000000,
            matter_type_id=graph["matter_type"]["id"],
        )
        # Exactly 80% — the warning threshold is inclusive.
        create_paid_invoice(
            graph["matter"]["id"], graph["firm"]["id"], fp_id, 8000000
        )
        b = get_success_data(api_client.get_budget(budget["id"], ANALYST))
        assert b["consumed_cents"] == 8000000
        assert b["posture"] == "WARNING"


class TestCriticalBoundary:
    def test_exactly_95_percent_is_critical(self, api):
        """PRD §2.7: "A ratio of at least 1.0 yields `EXCEEDED`; failing that, a
        ratio of at least `budget_critical_pct` yields `CRITICAL`; failing that, a
        ratio of at least `budget_warning_pct` yields `WARNING`; anything lower is
        `OK`. All three comparisons are inclusive at the boundary — an exact tie
        resolves toward the more severe posture."

        Design: Difficulty/boundary_precision_check/budget_posture_critical_inclusive_boundary
        """
        graph = setup_matter_graph(
            dept_overrides={"budget_warning_pct": 0.80, "budget_critical_pct": 0.95}
        )
        fp_id = graph["fiscal_period"]["id"]
        budget = create_budget(
            fp_id, graph["practice_area"]["id"], 1000000,
            matter_type_id=graph["matter_type"]["id"],
        )
        create_paid_invoice(graph["matter"]["id"], graph["firm"]["id"], fp_id, 950000)
        b = get_success_data(api_client.get_budget(budget["id"], ANALYST))
        assert b["consumed_cents"] == 950000
        assert b["posture"] == "CRITICAL"

    def test_one_cent_below_critical_stays_warning(self, api):
        """PRD §2.7: "The ratio is compared as an exact rational value — it is
        never rounded before comparison."
        PRD §2.7: "A ratio of at least 1.0 yields `EXCEEDED`; failing that, a
        ratio of at least `budget_critical_pct` yields `CRITICAL`; failing that, a
        ratio of at least `budget_warning_pct` yields `WARNING`; anything lower is
        `OK`."

        Design: Difficulty/boundary_precision_check/budget_posture_critical_inclusive_boundary
        """
        graph = setup_matter_graph(
            dept_overrides={"budget_warning_pct": 0.80, "budget_critical_pct": 0.95}
        )
        fp_id = graph["fiscal_period"]["id"]
        budget = create_budget(
            fp_id, graph["practice_area"]["id"], 1000000,
            matter_type_id=graph["matter_type"]["id"],
        )
        # ratio 0.949999 < 0.95 — below critical, at/above warning
        create_paid_invoice(graph["matter"]["id"], graph["firm"]["id"], fp_id, 949999)
        b = get_success_data(api_client.get_budget(budget["id"], ANALYST))
        assert b["consumed_cents"] == 949999
        assert b["posture"] == "WARNING"


def test_budget_patch_with_stale_version_rejected(api):
    """PRD §2.11: "Updating a budget's allocation requires
    `expected_budget_version`. If it does not equal the budget's current
    `version`, the update is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/budget_patch_occ_conflict
    """
    graph = setup_matter_graph()
    budget = create_budget(
        graph["fiscal_period"]["id"], graph["practice_area"]["id"], 1000000,
        matter_type_id=graph["matter_type"]["id"],
    )
    observed_version = budget["version"]

    updated = validate_success(
        api_client.update_budget(
            budget["id"],
            {"allocated_cents": 2000000, "expected_budget_version": observed_version},
            MANAGER,
        ),
        200,
    )
    assert updated["allocated_cents"] == 2000000

    res = api_client.update_budget(
        budget["id"],
        {"allocated_cents": 3000000, "expected_budget_version": observed_version},
        MANAGER,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)


def test_posture_ladder_across_cumulative_payments(api):
    """PRD §2.7: "A ratio of at least 1.0 yields `EXCEEDED`; failing that, a ratio
    of at least `budget_critical_pct` yields `CRITICAL`; failing that, a ratio of
    at least `budget_warning_pct` yields `WARNING`; anything lower is `OK`."
    PRD §2.7: "Posture is re-derived after every spend-line insert, after every
    change to a budget's `allocated_cents`, and after any change to the
    department's threshold percentages."

    Design: Corner/cross_cutting_layers/rate_threshold_posture_transitions
    """
    graph = setup_matter_graph(
        dept_overrides={"budget_warning_pct": 0.5, "budget_critical_pct": 0.8}
    )
    fp_id = graph["fiscal_period"]["id"]
    budget = create_budget(
        fp_id, graph["practice_area"]["id"], 1000000,
        matter_type_id=graph["matter_type"]["id"],
    )
    m_id = graph["matter"]["id"]
    firm_id = graph["firm"]["id"]

    expected_ladder = ["OK", "WARNING", "CRITICAL", "EXCEEDED"]
    for amount, expected_posture in zip(
        (300000, 300000, 300000, 100000), expected_ladder
    ):
        create_paid_invoice(m_id, firm_id, fp_id, amount)
        b = get_success_data(api_client.get_budget(budget["id"], ANALYST))
        assert b["posture"] == expected_posture, (
            f"After paying {amount}, expected posture {expected_posture}, got {b['posture']}"
        )

    b = get_success_data(api_client.get_budget(budget["id"], ANALYST))
    assert b["consumed_cents"] == 1000000
