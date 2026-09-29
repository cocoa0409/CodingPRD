"""Read-your-write: every derived number is already correct in the response that moved it.

There is no settling delay anywhere in the programme — a write's own body carries the
recomputed values, and the very next read of a neighbouring record agrees with it.
"""

from test_helpers import (
    advance_clock,
    assert_exact_int,
    assert_instant_equals,
    assert_page,
    assert_score,
    assert_severity,
    build_scenario,
    created_data,
    engagement_version,
    factories,
    success_data,
)

T_FIELDWORK_OPENING = "2026-09-08T09:00:00Z"
T_ACK_DEADLINE = "2026-09-08T10:00:00Z"


class TestImmediateConsistency:
    """One critical finding, and four other records already know about it."""

    def test_every_derived_field_is_readable_in_the_same_response_that_changed_it(
        self, client
    ):
        """The finding's own body carries its rating while the plan, asset and alert already agree.

        PRD: "Registration also seeds the posture fields the server maintains from then on. A fresh asset opens with `exposure_state` set to `MONITORED` and with `open_finding_count`, `open_critical_finding_count` and `remediated_finding_count` all at 0, and its `last_cleared_at` is null."
        PRD: "Under `RISK_DRIVEN` — the default — exposure is weighted 0.45, tier points 0.30, staleness points 0.20 and regime points 0.05, so attack surface and business criticality dominate."
        PRD: "It then recomputes `coverage_score` from scratch and requires the recomputed value to be at least 60.00 percent, refusing anything lower with `ERR_COVERAGE_BELOW_MINIMUM` — a plan sitting at exactly 60.00 activates."
        PRD: "The rating starts from `technical_base_score` and multiplies it by an exposure multiplier — 0.95 for an `INTERNAL` finding, exactly 1.00 for a `PARTNER` finding, and 1.15 for an `INTERNET` finding."
        PRD: "`severity_band` is `CRITICAL` when `severity_score` is at least 9.00, otherwise `HIGH` when it is at least 7.00, otherwise `MEDIUM` when it is at least 4.00, and otherwise `LOW`."
        PRD: "Its points are added to the plan's `total_risk_points` and to its `open_risk_points`. Its asset's `open_finding_count` is incremented, and for a `CRITICAL` finding `open_critical_finding_count` is incremented too, which may drive the asset's posture from `MONITORED` or `CLEARED` to `ELEVATED` as described in §3.1."
        PRD: "Its `ack_deadline_at` is `raised_at` advanced by a window that depends on the finding's `exposure_class`: an internet-facing critical finding must be acknowledged within one hour, that is 60 minutes, while a partner-facing or internal critical finding is allowed four hours, that is 240 minutes."
        PRD: "The new engagement opens with `execution_state` at `PLANNED` and `authorization_state` at `ROE_PENDING`, with a null `suspension_reason` and with both `provisional_assurance_score` and `final_assurance_score` null."

        Design: Corner/consistency_model/every_derived_field_is_readable_in_the_same_response_that_changed_it
        """
        scenario = build_scenario(client, stage="executing")
        engagement_id = scenario["engagement_id"]
        asset_id = scenario["asset_id"]
        plan_id = scenario["plan_id"]

        assert scenario["asset"]["exposure_state"] == "MONITORED", (
            f"exposure_state: expected MONITORED, "
            f"got {scenario['asset']['exposure_state']}"
        )
        assert_exact_int(scenario["asset"]["open_finding_count"], 0, "open_finding_count")
        assert_exact_int(
            scenario["asset"]["open_critical_finding_count"],
            0,
            "open_critical_finding_count",
        )
        assert_score(scenario["scope_item"]["priority_score"], 89.80, "priority_score")
        assert_score(scenario["plan"]["coverage_score"], 100.00, "coverage_score")
        assert_exact_int(scenario["plan"]["total_risk_points"], 0, "total_risk_points")

        advance_clock(client, T_FIELDWORK_OPENING)
        finding = created_data(
            client.create_finding(
                factories.finding_payload(
                    engagement_id,
                    asset_id,
                    engagement_version(client, engagement_id),
                    title="Payments IDOR",
                    technical_base_score=8.0,
                    exposure_class="INTERNET",
                ),
                scenario["tester_headers"],
            )
        )
        assert_severity(finding, score=9.90, band="CRITICAL", points=40, immediate=True)
        assert_instant_equals(
            finding["discovered_at"], T_FIELDWORK_OPENING, "discovered_at"
        )

        asset_after = success_data(client.get_asset(asset_id))
        assert_exact_int(asset_after["open_finding_count"], 1, "open_finding_count")
        assert_exact_int(
            asset_after["open_critical_finding_count"], 1, "open_critical_finding_count"
        )
        assert asset_after["exposure_state"] == "ELEVATED", (
            f"exposure_state: expected ELEVATED, got {asset_after['exposure_state']}"
        )

        plan_after = success_data(client.get_test_plan(plan_id))
        assert_exact_int(
            plan_after["open_risk_points"], finding["severity_points"], "open_risk_points"
        )
        assert_exact_int(
            plan_after["total_risk_points"],
            finding["severity_points"],
            "total_risk_points",
        )

        alerts, _ = assert_page(
            client.list_critical_alerts(
                params={"finding_id": finding["id"], "limit": 10, "offset": 0}
            ),
            total_count=1,
            has_more=False,
            row_count=1,
        )
        assert alerts[0]["finding_id"] == finding["id"], (
            f"finding_id: expected {finding['id']}, got {alerts[0]['finding_id']}"
        )
        assert alerts[0]["state"] == "RAISED", (
            f"state: expected RAISED, got {alerts[0]['state']}"
        )
        assert_instant_equals(
            alerts[0]["ack_deadline_at"], T_ACK_DEADLINE, "ack_deadline_at"
        )

        engagement_after = success_data(client.get_engagement(engagement_id))
        assert engagement_after["provisional_assurance_score"] is None, (
            "provisional_assurance_score: expected None while fieldwork is still running, "
            f"got {engagement_after['provisional_assurance_score']}"
        )
