"""Per-client, per-period fulfillment report.

Covers PRD §3.8 (fulfillment reporting).
"""
from test_helpers import (
    api_client,
    churn_payload,
    make_client_ops_headers,
    set_clock,
    setup_kitted_scenario,
    validate_paginated,
    validate_success,
)


class TestFulfillmentSummary:
    def test_fulfillment_summary_computed_read(self):
        """PRD §3.8: "The report's run set is the client's assembly runs for
        that period standing in `LOCKED`, `KITTING`, `KITTED`, or `CLOSED`;
        `DRAFT` and `CANCELLED` runs are excluded." PRD §3.8: "`fill_rate_pct`
        divides `kitted_boxes` by `planned_boxes`, multiplies by 100, and
        rounds half-up to one decimal place; when `planned_boxes` is zero it
        reports 0.0." PRD §3.8: "`churned_in_period` counts subscribers of the
        client's plans whose `churned_at` falls inside the period — from
        midnight UTC on the first day of the period up to but not including
        the first instant of the following month."

        Design: Corner/endpoints/fulfillment_summary_computed_read
        """
        env = setup_kitted_scenario(
            "EP2", num_subscribers=2, actual_kitted_count=1, stock=10,
            price_per_box_cents=1000, shipping_weight_grams=800, zone=2)
        client = env["client"]
        headers = make_client_ops_headers(client["id"])

        # Churn one still-ACTIVE subscriber mid-period (2026-05-20).
        set_clock("2026-05-20T00:00:00Z")
        resp = api_client.list_subscribers(
            headers, params={"plan_id": env["plan"]["id"], "status": "ACTIVE"})
        active, _meta = validate_paginated(resp)
        assert len(active) == 2
        validate_success(
            api_client.churn_subscriber(active[0]["id"], churn_payload("PRODUCT"),
                                        headers))

        report = validate_success(
            api_client.get_fulfillment_summary(client["id"], headers,
                                               params={"period": "2026-05"}))
        assert report["period"] == "2026-05"
        assert report["planned_boxes"] == 2, \
            f"LOCKED+ runs contribute planned boxes: {report['planned_boxes']}"
        assert report["kitted_boxes"] == 1
        assert report["fill_rate_pct"] == 50.0, (
            f"round_half_up(1*100.0/2, 1) == 50.0, got "
            f"{report['fill_rate_pct']}"
        )
        assert report["shipped_boxes"] == 0
        assert report["returned_boxes"] == 0
        assert report["active_subscribers"] == 1, \
            "the churned subscriber no longer counts as active"
        assert report["churned_in_period"] == 1, \
            "churned_at 2026-05-20 falls inside the 2026-05 window"
