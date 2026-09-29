"""Endpoint surfaces: what each route accepts, what it returns and what it refuses.

These tests exercise whole routes rather than single rules: the plan surface end to
end, the two state-conditional plan actions, the target exclusion action with all of
its declared side effects, a per-row derived read, and the two-sided resolution of
the target join.
"""

from test_helpers import (
    advance_clock,
    assert_error_id,
    assert_exact_int,
    assert_instant_equals,
    assert_page,
    assert_score,
    build_scenario,
    created_data,
    factories,
    success_data,
    read_plan_version,
)
from test_helpers.api_errors import (
    ERR_ASSET_NOT_FOUND,
    ERR_PLAN_NOT_DRAFT,
    ERR_ROE_NOT_FOUND,
)
from test_helpers.constants import T_PROGRAMME_OPEN

UNKNOWN_ROE_ID = "00000000-0000-4000-8000-000000000abc"
UNKNOWN_ASSET_ID = "00000000-0000-4000-8000-000000000def"
TARGET_WINDOW_START = "2026-09-05T00:00:00Z"
TARGET_WINDOW_END = "2026-09-25T00:00:00Z"
SHORT_WINDOW_END = "2026-09-10T00:00:00Z"
EXCLUSION_REASON = "Partner declined the portal test this cycle"

NETWORK_FABRIC = {
    "name": "Core Switch Fabric",
    "criticality_tier": 3,
    "exposure_score": 55,
}
CLOUD_ACCOUNT = {
    "name": "Prod Cloud Account",
    "criticality_tier": 4,
    "compliance_regimes": ["SOC2"],
    "exposure_score": 70,
    "last_tested_at": "2026-02-10T00:00:00Z",
}


def _approved_candidate(client, plan_id, asset_id, justification="Payments coverage"):
    """Propose one candidate against the DRAFT plan and approve it."""
    candidate = created_data(
        client.create_scope_item(
            factories.scope_item_payload(
                plan_id,
                asset_id,
                read_plan_version(client, plan_id),
                justification=justification,
            )
        )
    )
    return success_data(
        client.decide_scope_item(
            candidate["id"], factories.decision_payload("APPROVE", note="In scope")
        )
    )


def _authorize(client, roe_id, asset_id, techniques, window_end=TARGET_WINDOW_END):
    """Add one authorized target to a document."""
    return client.create_authorized_target(
        factories.authorized_target_payload(
            roe_id,
            asset_id,
            window_start=TARGET_WINDOW_START,
            window_end=window_end,
            technique_allowlist=techniques,
        )
    )


class TestTestPlanSurface:
    """Create, read and filtered list over the annual plan, with no delete anywhere."""

    def test_plan_create_read_and_filtered_list_round_trip(
        self, client, admin, compliance_officer
    ):
        """Two plans in different fiscal years read back with their own thresholds and page apart.

        PRD: "A `ProgramManager` opens the year's programme by creating a test plan for a `fiscal_year` between 2026 and 2099 inclusive."
        PRD: "`risk_appetite_score`, an integer from 0 to 100 inclusive, expresses how much low-scoring scope the programme is willing to admit, and from it the server immediately derives `admission_threshold` as 100 minus the appetite — a hungry programme with an appetite of 90 admits candidates scoring as low as 10, while a conservative programme with an appetite of 20 demands 80."
        PRD: "A new plan opens at `DRAFT` status with `coverage_score` at 0 and all five risk-point buckets — `total_risk_points`, `open_risk_points`, `closed_risk_points`, `accepted_risk_points` and `duplicate_risk_points` — at 0. Plans can be browsed with optional filters on `fiscal_year` and `status`."
        PRD: "List responses set `response_type` to `"array"` and populate four pagination fields inside `meta`: `limit` (the effective page size), `offset` (the effective skip), `total_count` (the number of records matching the filters before pagination is applied) and `has_more` (true when records remain beyond the current page)."
        PRD: "Unless an endpoint's description states otherwise, list results are ordered by `created_at` ascending — oldest record first."

        Design: Corner/endpoints/test_plan_create_read_and_filtered_list_round_trip
        """
        advance_clock(client, T_PROGRAMME_OPEN)

        first = created_data(client.create_test_plan(factories.test_plan_payload()))
        assert_exact_int(first["admission_threshold"], 60, "admission_threshold")
        assert first["status"] == "DRAFT", f"status: expected DRAFT, got {first['status']}"
        assert_exact_int(first["version"], 1, "version")

        second = created_data(
            client.create_test_plan(
                factories.test_plan_payload(
                    fiscal_year=2027,
                    risk_appetite_score=10,
                    planned_engagement_count=3,
                    prioritization_mode="COMPLIANCE_DRIVEN",
                )
            )
        )
        assert_exact_int(second["admission_threshold"], 90, "admission_threshold")
        assert second["prioritization_mode"] == "COMPLIANCE_DRIVEN", (
            f"prioritization_mode: expected COMPLIANCE_DRIVEN, "
            f"got {second['prioritization_mode']}"
        )

        read_back = success_data(
            client.get_test_plan(first["id"], headers=compliance_officer)
        )
        assert read_back["id"] == first["id"], (
            f"id: expected {first['id']}, got {read_back['id']}"
        )
        assert_exact_int(read_back["fiscal_year"], 2026, "fiscal_year")
        assert_score(read_back["coverage_score"], 0.00, "coverage_score")
        assert_exact_int(read_back["total_risk_points"], 0, "total_risk_points")

        filtered, _ = assert_page(
            client.list_test_plans(
                params={"fiscal_year": 2027, "limit": 10, "offset": 0}, headers=admin
            ),
            total_count=1,
            has_more=False,
            row_count=1,
        )
        assert filtered[0]["id"] == second["id"], (
            f"first row: expected {second['id']}, got {filtered[0]['id']}"
        )
        assert_exact_int(filtered[0]["fiscal_year"], 2027, "fiscal_year")

        page, _ = assert_page(
            client.list_test_plans(params={"limit": 1, "offset": 0}, headers=admin),
            total_count=2,
            has_more=True,
            row_count=1,
            limit=1,
            offset=0,
        )
        assert page[0]["id"] == first["id"], (
            "oldest plan first on an unfiltered page: "
            f"expected {first['id']}, got {page[0]['id']}"
        )

    def test_switching_the_prioritization_mode_is_refused_once_the_plan_is_active(
        self, client
    ):
        """The mode switch works while the plan drafts and is refused the moment it activates.

        PRD: "The plan also declares `prioritization_mode`, either `RISK_DRIVEN` or `COMPLIANCE_DRIVEN`, defaulting to `RISK_DRIVEN` when the manager does not say."
        PRD: "From that point on the plan's scope is frozen: no candidate may be proposed or decided, and the mode may not be switched, since all three of those operations demand a `DRAFT` plan."
        PRD: "The plan must be `DRAFT` (`ERR_PLAN_NOT_DRAFT`, 409) — for scope-item creation, scope decisions, prioritization-mode switching and plan activation."

        Design: Corner/endpoints/switching_the_prioritization_mode_is_refused_once_the_plan_is_active
        """
        scenario = build_scenario(client, stage="plan", plan={"risk_appetite_score": 100})
        plan_id = scenario["plan_id"]
        _approved_candidate(client, plan_id, scenario["asset_id"])

        switched = success_data(
            client.set_prioritization_mode(plan_id, "COMPLIANCE_DRIVEN")
        )
        assert switched["prioritization_mode"] == "COMPLIANCE_DRIVEN", (
            f"prioritization_mode: expected COMPLIANCE_DRIVEN, "
            f"got {switched['prioritization_mode']}"
        )
        assert switched["status"] == "DRAFT", (
            f"status: expected DRAFT, got {switched['status']}"
        )
        assert_exact_int(switched["version"], 4, "version")

        activated = success_data(client.activate_test_plan(plan_id))
        assert activated["status"] == "ACTIVE", (
            f"status: expected ACTIVE, got {activated['status']}"
        )
        assert_exact_int(activated["version"], 5, "version")

        assert_error_id(
            client.set_prioritization_mode(plan_id, "RISK_DRIVEN"), ERR_PLAN_NOT_DRAFT
        )

        final = success_data(client.get_test_plan(plan_id))
        assert final["prioritization_mode"] == "COMPLIANCE_DRIVEN", (
            f"prioritization_mode: expected COMPLIANCE_DRIVEN, "
            f"got {final['prioritization_mode']}"
        )
        assert_exact_int(final["version"], activated["version"], "version")


class TestAuthorizedTargetSurface:
    """The target join: creation resolution, the exclusion action and derived reads."""

    def test_excluding_a_target_stamps_the_reason_and_frees_the_document_counter(
        self, client, compliance_officer
    ):
        """A compliance officer withdraws one of two targets; only that row and the counter move.

        PRD: "On acceptance the target opens at `ACTIVE` state with a null `exclusion_reason`, the parent document's `active_target_count` is incremented, and the document's `version` advances."
        PRD: "Either a `ProgramManager` or a `ComplianceOfficer` may exclude an `ACTIVE` target on a `DRAFT` or `SIGNED` document, supplying a mandatory `reason`. Exclusion moves the target `ACTIVE` → `EXCLUDED`, stamps the supplied text into `exclusion_reason`, decrements the document's `active_target_count`, and advances the document's `version`."
        PRD: "Targets can be browsed with optional filters on `roe_id`, `asset_id` and `state`."

        Design: Corner/endpoints/excluding_a_target_stamps_the_reason_and_frees_the_document_counter
        """
        scenario = build_scenario(
            client, stage="roe", roe={"allowed_techniques": ["SQLI", "XSS"]}
        )
        roe_id = scenario["roe_id"]
        opened = success_data(client.get_rules_of_engagement(roe_id))
        assert_exact_int(opened["version"], 1, "version")

        asset_b = created_data(
            client.create_asset(factories.partner_portal_asset_payload(criticality_tier=3))
        )
        target_a = created_data(
            _authorize(client, roe_id, scenario["asset_id"], ["SQLI"])
        )
        target_b = created_data(_authorize(client, roe_id, asset_b["id"], ["XSS"]))
        assert target_b["exclusion_reason"] is None, (
            f"exclusion_reason: expected None, got {target_b['exclusion_reason']}"
        )

        before = success_data(client.get_rules_of_engagement(roe_id))
        assert_exact_int(before["version"], 3, "version")
        assert_exact_int(before["active_target_count"], 2, "active_target_count")

        excluded = success_data(
            client.exclude_authorized_target(
                target_b["id"], EXCLUSION_REASON, headers=compliance_officer
            )
        )
        assert excluded["state"] == "EXCLUDED", (
            f"state: expected EXCLUDED, got {excluded['state']}"
        )
        assert excluded["exclusion_reason"] == EXCLUSION_REASON, (
            f"exclusion_reason: expected {EXCLUSION_REASON!r}, "
            f"got {excluded['exclusion_reason']!r}"
        )

        after = success_data(client.get_rules_of_engagement(roe_id))
        assert_exact_int(after["active_target_count"], 1, "active_target_count")
        assert_exact_int(after["version"], 4, "version")

        survivor = success_data(client.get_authorized_target(target_a["id"]))
        assert survivor["state"] == "ACTIVE", (
            f"state: expected ACTIVE, got {survivor['state']}"
        )
        assert survivor["exclusion_reason"] is None, (
            f"exclusion_reason: expected None, got {survivor['exclusion_reason']}"
        )

        rows, _ = assert_page(
            client.list_authorized_targets(
                params={"roe_id": roe_id, "state": "EXCLUDED", "limit": 10, "offset": 0}
            ),
            total_count=1,
            has_more=False,
            row_count=1,
        )
        assert rows[0]["id"] == target_b["id"], (
            f"first row: expected {target_b['id']}, got {rows[0]['id']}"
        )

    def test_target_read_exposes_the_cooldown_hours_of_its_asset_class(
        self, client, compliance_officer
    ):
        """Three targets over an application, a network and a cloud asset carry 0, 24 and 12 hours.

        PRD: "Each target records `cooldown_hours`, resolved from the asset's class: an `APPLICATION` asset needs no buffer at all, a `CLOUD` asset needs half a day of quiet on each side, and a `NETWORK` asset needs a full day on each side."

        Design: Corner/endpoints/target_read_exposes_the_cooldown_hours_of_its_asset_class
        """
        scenario = build_scenario(
            client,
            stage="roe",
            roe={
                "allowed_techniques": ["SQLI", "LATERAL_MOVEMENT", "IAM_ESCALATION"]
            },
        )
        roe_id = scenario["roe_id"]
        plan = success_data(client.get_test_plan(scenario["plan_id"]))
        assert_score(plan["coverage_score"], 100.00, "coverage_score")

        network_asset = created_data(
            client.create_asset(factories.core_network_asset_payload(**NETWORK_FABRIC))
        )
        cloud_asset = created_data(
            client.create_asset(factories.analytics_lake_asset_payload(**CLOUD_ACCOUNT))
        )

        application_target = created_data(
            _authorize(
                client,
                roe_id,
                scenario["asset_id"],
                ["SQLI"],
                window_end=SHORT_WINDOW_END,
            )
        )
        network_target = created_data(
            _authorize(
                client,
                roe_id,
                network_asset["id"],
                ["LATERAL_MOVEMENT"],
                window_end=SHORT_WINDOW_END,
            )
        )
        cloud_target = created_data(
            _authorize(
                client,
                roe_id,
                cloud_asset["id"],
                ["IAM_ESCALATION"],
                window_end=SHORT_WINDOW_END,
            )
        )

        assert_exact_int(application_target["cooldown_hours"], 0, "cooldown_hours")
        assert_exact_int(network_target["cooldown_hours"], 24, "cooldown_hours")
        assert_exact_int(cloud_target["cooldown_hours"], 12, "cooldown_hours")

        read_back = success_data(
            client.get_authorized_target(
                network_target["id"], headers=compliance_officer
            )
        )
        assert_exact_int(read_back["cooldown_hours"], 24, "cooldown_hours")
        assert read_back["asset_id"] == network_asset["id"], (
            f"asset_id: expected {network_asset['id']}, got {read_back['asset_id']}"
        )

    def test_authorizing_a_target_requires_both_the_document_and_the_asset_to_resolve(
        self, client
    ):
        """An unknown document and an unknown asset each earn their own 404 before the row is written.

        PRD: "Every foreign key supplied in a body must resolve: `test_plan_id`, `asset_id`, `scope_item_id`, `engagement_id`, `roe_id`, `tester_id`, `finding_id`, `remediation_id`, `duplicate_of_finding_id`, and each member of `granted_asset_ids`."
        PRD: "The failure carries the matching not-found identifier from Band 2's list at HTTP 404 — an unresolvable `asset_id` in a body, or inside `granted_asset_ids`, yields `ERR_ASSET_NOT_FOUND`."
        PRD: "Targets can be browsed with optional filters on `roe_id`, `asset_id` and `state`."

        Design: Corner/endpoints/authorizing_a_target_requires_both_the_document_and_the_asset_to_resolve
        """
        scenario = build_scenario(client, stage="roe")
        roe_id = scenario["roe_id"]
        asset_id = scenario["asset_id"]

        assert_error_id(
            _authorize(client, UNKNOWN_ROE_ID, asset_id, ["SQLI"]), ERR_ROE_NOT_FOUND
        )
        assert_error_id(
            _authorize(client, roe_id, UNKNOWN_ASSET_ID, ["SQLI"]), ERR_ASSET_NOT_FOUND
        )

        target = created_data(_authorize(client, roe_id, asset_id, ["SQLI"]))
        assert target["roe_id"] == roe_id, (
            f"roe_id: expected {roe_id}, got {target['roe_id']}"
        )
        assert target["asset_id"] == asset_id, (
            f"asset_id: expected {asset_id}, got {target['asset_id']}"
        )
        assert_instant_equals(
            target["window_start"], TARGET_WINDOW_START, "window_start"
        )

        by_asset, _ = assert_page(
            client.list_authorized_targets(
                params={"asset_id": asset_id, "limit": 10, "offset": 0}
            ),
            total_count=1,
            has_more=False,
            row_count=1,
        )
        assert by_asset[0]["id"] == target["id"], (
            f"first row: expected {target['id']}, got {by_asset[0]['id']}"
        )

        by_document, _ = assert_page(
            client.list_authorized_targets(
                params={"roe_id": roe_id, "limit": 10, "offset": 0}
            ),
            total_count=1,
            has_more=False,
            row_count=1,
        )
        assert by_document[0]["id"] == target["id"], (
            f"first row: expected {target['id']}, got {by_document[0]['id']}"
        )
