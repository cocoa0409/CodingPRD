"""Executive dashboard: draft vs published variants, rounding, publish gates."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_dashboard,
    create_budget,
    create_dashboard,
    create_paid_invoice,
    get_success_data,
    hard_close_period,
    publish_dashboard,
    reopen_period,
    setup_matter_graph,
    setup_reopened_period,
    setup_soft_closed_period,
    setup_taxonomy,
    soft_close_period,
    validate_error,
    ANALYST,
    MANAGER,
)


class TestDraftVsPublished:
    def test_draft_and_published_reads_diverge_after_interim_spend(self, api):
        """PRD §3.8: "A `DRAFT` dashboard is provisional: each read recomputes
        against live period totals, so values may drift between reads."
        PRD §3.8: "`budget_accuracy_pct` compares the period's total allocation
        across all of its budgets, regardless of posture, against its actual
        spend: when the total allocation is zero the figure is null; otherwise the
        absolute difference between allocation and actual spend is taken first,
        divided by the total allocation, the resulting fraction is subtracted from
        one, multiplied by one hundred, rounded half-up to two decimal places, and
        finally divided by one hundred."

        Design: Difficulty/dual_variant_calc/dashboard_draft_vs_published_snapshot_diverges
        """
        graph = setup_matter_graph()
        fp_id = graph["fiscal_period"]["id"]
        create_budget(
            fp_id, graph["practice_area"]["id"], 10000000,
            matter_type_id=graph["matter_type"]["id"],
        )
        m_id = graph["matter"]["id"]
        firm_id = graph["firm"]["id"]

        create_paid_invoice(m_id, firm_id, fp_id, 4000000)
        dash = create_dashboard(fp_id, snapshot_label="Q3")

        draft = get_success_data(api_client.get_dashboard(dash["id"], ANALYST))
        assert draft["total_actual_spend_cents"] == 4000000
        assert draft["budget_accuracy_pct"] == pytest.approx(0.40, abs=1e-9)

        create_paid_invoice(m_id, firm_id, fp_id, 1000000)

        # Publishing requires the period SOFT_CLOSED or HARD_CLOSED (PRD §3.8).
        soft_close_period(fp_id)
        published = publish_dashboard(dash["id"])
        assert published["status"] == "PUBLISHED"

        pub = get_success_data(api_client.get_dashboard(dash["id"], ANALYST))
        assert pub["total_actual_spend_cents"] == 5000000
        assert pub["budget_accuracy_pct"] == pytest.approx(0.50, abs=1e-9)
        assert pub["budget_accuracy_pct"] != draft["budget_accuracy_pct"]

    def test_published_dashboard_frozen_against_later_spend(self, api):
        """PRD §3.8: "Publishing freezes the computed panel permanently:
        subsequent invoices, releases, and closes do not move a `PUBLISHED` (or
        later `SUPERSEDED`) dashboard's numbers."

        Design: Difficulty/dual_variant_calc/dashboard_draft_vs_published_snapshot_diverges
        """
        graph = setup_matter_graph()
        fp_id = graph["fiscal_period"]["id"]
        create_budget(
            fp_id, graph["practice_area"]["id"], 10000000,
            matter_type_id=graph["matter_type"]["id"],
        )
        m_id = graph["matter"]["id"]
        firm_id = graph["firm"]["id"]

        create_paid_invoice(m_id, firm_id, fp_id, 4000000)
        dash = create_dashboard(fp_id, snapshot_label="Q3")

        soft_close_period(fp_id)
        publish_dashboard(dash["id"])
        frozen = get_success_data(api_client.get_dashboard(dash["id"], ANALYST))
        assert frozen["total_actual_spend_cents"] == 4000000
        assert frozen["budget_accuracy_pct"] == pytest.approx(0.40, abs=1e-9)

        # Cycle the period back to REOPENED so another invoice can be paid.
        hard_close_period(fp_id)
        reopen_period(fp_id)
        create_paid_invoice(m_id, firm_id, fp_id, 1000000)

        after = get_success_data(api_client.get_dashboard(dash["id"], ANALYST))
        assert after["status"] == "PUBLISHED"
        assert after["total_actual_spend_cents"] == 4000000
        assert after["budget_accuracy_pct"] == pytest.approx(0.40, abs=1e-9)


class TestBudgetAccuracyRounding:
    def test_rounding_order_pinned_multiply_then_round_then_divide(self, api):
        """PRD §2.9: "Percentage-style outputs follow a pinned rounding order.
        `utilization_pct`, `budget_accuracy_pct`, and `deflection_rate_pct` are
        each computed as a fraction, multiplied by one hundred, rounded half-up to
        two decimal places, and then divided by one hundred — so the stored value
        is expressed as a fraction (0.95 means ninety-five percent) carrying at
        most two decimal places."

        Design: Difficulty/combinatorial_formula/dashboard_accuracy_rounding_order_pinned
        """
        graph = setup_matter_graph()
        fp_id = graph["fiscal_period"]["id"]
        create_budget(
            fp_id, graph["practice_area"]["id"], 333333,
            matter_type_id=graph["matter_type"]["id"],
        )
        create_paid_invoice(graph["matter"]["id"], graph["firm"]["id"], fp_id, 100001)
        dash = create_dashboard(fp_id, snapshot_label="snap")
        data = get_success_data(api_client.get_dashboard(dash["id"], ANALYST))
        assert_dashboard(data)
        assert data["total_actual_spend_cents"] == 100001
        # delta = 233332; (1 - 233332/333333) * 100 = 30.0003...
        # round_half_up(..., 2) = 30.00; / 100 = 0.30
        assert data["budget_accuracy_pct"] == pytest.approx(0.30, abs=1e-9)

    def test_overspend_accuracy_rounds_up_across_integer_boundary(self, api):
        """PRD §3.8: "otherwise the absolute difference between allocation and
        actual spend is taken first, divided by the total allocation, the
        resulting fraction is subtracted from one, multiplied by one hundred,
        rounded half-up to two decimal places, and finally divided by one
        hundred."

        Design: Difficulty/combinatorial_formula/dashboard_accuracy_rounding_order_pinned
        """
        graph = setup_matter_graph()
        fp_id = graph["fiscal_period"]["id"]
        create_budget(
            fp_id, graph["practice_area"]["id"], 333333,
            matter_type_id=graph["matter_type"]["id"],
        )
        # Spend above allocation but within the fixed 10% overrun allowance of
        # PRD §2.7/§3.5 (cap: 333333 * 1.10 = 366666.3, so 400000 would be
        # refused as ERR_BUDGET_OVERRUN_EXCEEDED): delta = 6667;
        # (1 - 6667/333333)*100 = 97.999898...
        # round_half_up(..., 2) = 98.00; / 100 = 0.98
        create_paid_invoice(graph["matter"]["id"], graph["firm"]["id"], fp_id, 340000)
        dash = create_dashboard(fp_id, snapshot_label="snap")
        data = get_success_data(api_client.get_dashboard(dash["id"], ANALYST))
        assert data["total_actual_spend_cents"] == 340000
        assert data["budget_accuracy_pct"] == pytest.approx(0.98, abs=1e-9)


class TestPublishPeriodGate:
    def test_publish_rejected_while_period_open(self, api):
        """PRD §3.8: "Publishing is a manager action requiring the dashboard to
        still be in `DRAFT` and the period to be `SOFT_CLOSED` or `HARD_CLOSED`; a
        period in any other state makes the transition undefined and is rejected
        with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/dashboard_publish_blocked_by_period_state
        """
        graph = setup_taxonomy()
        dash = create_dashboard(graph["fiscal_period"]["id"], snapshot_label="snap")
        res = api_client.publish_dashboard(
            dash["id"], {"expected_dashboard_version": dash["version"]}, MANAGER
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api_client.get_dashboard(dash["id"], ANALYST))
        assert after["status"] == "DRAFT"

    def test_publish_rejected_while_period_reopened(self, api):
        """PRD §3.8: "Publishing is a manager action requiring the dashboard to
        still be in `DRAFT` and the period to be `SOFT_CLOSED` or `HARD_CLOSED`; a
        period in any other state makes the transition undefined and is rejected
        with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/dashboard_publish_blocked_by_period_state
        """
        graph = setup_reopened_period()
        assert graph["fiscal_period"]["status"] == "REOPENED"
        dash = create_dashboard(graph["fiscal_period"]["id"], snapshot_label="snap")
        res = api_client.publish_dashboard(
            dash["id"], {"expected_dashboard_version": dash["version"]}, MANAGER
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_publish_supersedes_prior_published_dashboard(api):
    """PRD §3.8: "At most one dashboard per period is published at a time — every
    other `PUBLISHED` dashboard for the same period transitions to `SUPERSEDED`
    the moment a new one publishes, each such row incrementing its own `version` —
    and the freshly published row's `version` increments as well."

    Design: Corner/state_machines/dashboard_publish_supersedes_prior
    """
    graph = setup_soft_closed_period()
    fp_id = graph["fiscal_period"]["id"]
    d1 = create_dashboard(fp_id, snapshot_label="D1")
    d2 = create_dashboard(fp_id, snapshot_label="D2")

    publish_dashboard(d1["id"])
    publish_dashboard(d2["id"])

    d1_after = get_success_data(api_client.get_dashboard(d1["id"], ANALYST))
    d2_after = get_success_data(api_client.get_dashboard(d2["id"], ANALYST))
    assert d1_after["status"] == "SUPERSEDED"
    assert d2_after["status"] == "PUBLISHED"


def test_second_publish_reports_invalid_state_before_version_check(api):
    """PRD §3.8: "The request carries `expected_dashboard_version`, checked after
    the state gate; a mismatch — typically because a peer's publish superseded
    this row and advanced its `version` — is rejected with `ERR_STALE_VERSION`."
    PRD §3.8: "Publishing is a manager action requiring the dashboard to still be
    in `DRAFT` and the period to be `SOFT_CLOSED` or `HARD_CLOSED`; a period in
    any other state makes the transition undefined and is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/cross_cutting_layers/dashboard_publish_occ_conflict
    """
    graph = setup_soft_closed_period()
    dash = create_dashboard(graph["fiscal_period"]["id"], snapshot_label="D1")
    original_version = dash["version"]

    publish_dashboard(dash["id"])

    # Publish is defined only from DRAFT; the state gate runs first, so a repeat
    # publish reports ERR_INVALID_STATE regardless of the version carried.
    res = api_client.publish_dashboard(
        dash["id"], {"expected_dashboard_version": original_version}, MANAGER
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_mean_cycle_days_null_when_no_closed_matters(api):
    """PRD §3.8: "`mean_cycle_days` averages `cycle_days` across the period's
    closed matters that have one — summing whole days first, dividing once,
    rounding half-up to two decimals — and is null when no closed matter
    qualifies; reopened matters are excluded because reopening reset their
    `cycle_days` to null."

    Design: Corner/calculations/mean_cycle_days_null_when_no_closed
    """
    graph = setup_taxonomy()
    dash = create_dashboard(graph["fiscal_period"]["id"], snapshot_label="s")
    assert dash["mean_cycle_days"] is None


def test_analyst_cannot_publish_dashboard(api, analyst_headers):
    """PRD §3.8: "Publishing is a manager action requiring the dashboard to still
    be in `DRAFT` and the period to be `SOFT_CLOSED` or `HARD_CLOSED`"
    PRD §2.1: "A well-authenticated request whose role is not authorized for the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/analyst_cannot_publish_dashboard
    """
    graph = setup_soft_closed_period()
    dash = create_dashboard(graph["fiscal_period"]["id"], snapshot_label="s")
    res = api_client.publish_dashboard(
        dash["id"], {"expected_dashboard_version": dash["version"]}, analyst_headers
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
