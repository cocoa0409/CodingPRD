"""Record shapes: what each collection stores, defaults, echoes and refuses.

These tests read the persisted representation of the programme's records rather
than the behaviour that moves them. A registered asset must come back with the
posture fields the registrar never supplied, a tester must come back with the
concurrency cap nobody stated, a candidate must already carry its score and its
rank, and a body naming a record that does not exist must be refused before any
of that arithmetic runs.
"""

from test_helpers import (
    advance_clock,
    assert_analytics_record_shape,
    assert_asset_posture,
    assert_error_id,
    assert_exact_int,
    assert_instant_equals,
    assert_page,
    assert_risk_ledger,
    assert_score,
    assert_system_fields,
    build_scenario,
    created_data,
    emitted_rows,
    engagement_version,
    factories,
    report_finding,
    success_data,
    read_plan_version,
)
from test_helpers.api_errors import (
    ERR_ASSET_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_TEST_PLAN_NOT_FOUND,
)
from test_helpers.constants import (
    T_BEFORE_ASSIGNMENT,
    T_FIELDWORK_DAY,
    T_PROGRAMME_OPEN,
    WINDOW_START,
)

UNREGISTERED_ID = "00000000-0000-4000-8000-000000000000"
SECOND_UNREGISTERED_ID = "00000000-0000-4000-8000-000000000001"

BILLING_CLUSTER = {
    "name": "Billing Cluster",
    "asset_class": "NETWORK",
    "criticality_tier": 2,
    "compliance_regimes": ["SOC2"],
    "exposure_score": 55,
    "last_tested_at": "2026-01-05T00:00:00Z",
}
WIKI = {
    "name": "Wiki",
    "asset_class": "APPLICATION",
    "criticality_tier": 3,
    "compliance_regimes": [],
    "exposure_score": 20,
    "last_tested_at": None,
}


class TestAssetRegistration:
    """What the inventory row carries the moment the registrar creates it."""

    def test_a_registered_asset_opens_monitored_with_empty_counters(self, client):
        """The registrar supplies six fields and the server seeds the posture behind them.

        PRD: "A fresh asset opens with `exposure_state` set to `MONITORED` and with `open_finding_count`, `open_critical_finding_count` and `remediated_finding_count` all at 0, and its `last_cleared_at` is null."
        PRD: "Each asset also declares its `criticality_tier`, an integer that must be 1, 2, 3 or 4 where 1 denotes the most business-critical estate; its `compliance_regimes`, a duplicate-free and possibly empty subset of `PCI_DSS`, `HIPAA`, `SOX`, `SOC2` and `FEDRAMP`; and its `exposure_score`, an attack-surface metric between 0 and 100 inclusive carrying at most two decimal places."

        Design: Corner/entities/asset_creation_returns_the_declared_field_set_with_system_defaults
        """
        advance_clock(client, T_PROGRAMME_OPEN)

        asset = created_data(client.create_asset(factories.asset_payload()))

        assert asset["name"] == "Payments API", f"name: got {asset['name']}"
        assert asset["asset_class"] == "APPLICATION", (
            f"asset_class: expected APPLICATION, got {asset['asset_class']}"
        )
        assert_exact_int(asset["criticality_tier"], 1, "criticality_tier")
        assert asset["compliance_regimes"] == ["SOC2"], (
            f"compliance_regimes: expected [SOC2], got {asset['compliance_regimes']}"
        )
        assert_score(asset["exposure_score"], 88, "exposure_score")
        assert_instant_equals(
            asset["last_tested_at"], "2025-10-02T00:00:00Z", "last_tested_at"
        )
        assert_asset_posture(
            asset,
            exposure_state="MONITORED",
            open_findings=0,
            open_critical=0,
            remediated=0,
            last_cleared_at=None,
        )
        assert_system_fields(asset, version=1)

    def test_the_system_fields_are_stamped_from_the_clock_and_open_at_version_one(
        self, client
    ):
        """The client supplies no id and no timestamps; both come from the server.

        PRD: "Every record the service persists carries a server-minted `id` in UUID form."
        PRD: "Most records additionally carry `updated_at`, refreshed to the current instant on every mutation, and `version`, an integer that starts at 1 when the record is created and increases by exactly 1 on every mutation of that record."
        PRD: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

        Design: Corner/entities/asset_system_fields_are_server_generated_and_start_at_version_one
        """
        advance_clock(client, T_PROGRAMME_OPEN)

        response = client.create_asset(factories.asset_payload())

        asset = created_data(response)
        assert_system_fields(asset, version=1)
        assert_instant_equals(asset["created_at"], T_PROGRAMME_OPEN, "created_at")
        assert_instant_equals(asset["updated_at"], T_PROGRAMME_OPEN, "updated_at")
        body = response.json()
        assert body["response_type"] == "object", (
            f"response_type: expected object, got {body['response_type']}"
        )
        assert body["meta"]["api_request_id"].startswith("req_"), (
            f"api_request_id: expected a req_ prefix, got {body['meta']['api_request_id']}"
        )
        assert body["meta"]["api_request_timestamp"], (
            "every response envelope carries an api_request_timestamp"
        )

    def test_omitting_the_exposure_score_is_refused_rather_than_defaulted(self, client):
        """`exposure_score` is an input with no default, so its absence is malformed.

        PRD: "For every request that carries a body, the body is checked against the endpoint's declared inputs: required fields present and non-blank, types correct, enumerated values drawn from the known member list, numeric values inside their declared ranges, arrays free of duplicate members, every target window ending strictly after it starts, and every assignment interval ending strictly after it starts. Any violation is `ERR_INVALID_REQUEST` with HTTP 400."

        Design: Corner/entities/asset_creation_without_exposure_score_is_rejected
        """
        advance_clock(client, T_PROGRAMME_OPEN)

        response = client.create_asset(
            factories.asset_payload(exposure_score=None, last_tested_at=None)
        )

        assert_error_id(response, ERR_INVALID_REQUEST)
        assert response.status_code == 400, (
            f"expected HTTP 400 for a missing exposure_score, got {response.status_code}"
        )
        assert_page(client.list_assets(), total_count=0, row_count=0)

    def test_a_tier_outside_the_declared_range_and_an_unknown_class_are_refused(
        self, client
    ):
        """Range membership and enum membership are both request-shape rules.

        PRD: "Each asset also declares its `criticality_tier`, an integer that must be 1, 2, 3 or 4 where 1 denotes the most business-critical estate; its `compliance_regimes`, a duplicate-free and possibly empty subset of `PCI_DSS`, `HIPAA`, `SOX`, `SOC2` and `FEDRAMP`; and its `exposure_score`, an attack-surface metric between 0 and 100 inclusive carrying at most two decimal places."
        PRD: "A `PlatformAdmin` builds the inventory of testable things, giving each one a human label in `name` (between 1 and 120 characters, and not merely whitespace) and classifying it in `asset_class` as one of `APPLICATION`, `NETWORK` or `CLOUD`."

        Design: Corner/entities/asset_criticality_tier_outside_one_to_four_is_rejected
        """
        advance_clock(client, T_PROGRAMME_OPEN)

        out_of_range = client.create_asset(
            factories.asset_payload(criticality_tier=5, last_tested_at=None)
        )
        unknown_class = client.create_asset(
            factories.asset_payload(asset_class="MAINFRAME", last_tested_at=None)
        )

        assert_error_id(out_of_range, ERR_INVALID_REQUEST)
        assert out_of_range.status_code == 400, (
            f"expected HTTP 400 for criticality_tier 5, got {out_of_range.status_code}"
        )
        assert_error_id(unknown_class, ERR_INVALID_REQUEST)
        assert unknown_class.status_code == 400, (
            f"expected HTTP 400 for asset_class MAINFRAME, got {unknown_class.status_code}"
        )


class TestAssetReadChannels:
    """Reading one asset and reading a page of them."""

    def test_reading_one_asset_echoes_what_registration_stored(self, client):
        """The single-resource read neither recomputes nor re-defaults anything.

        PRD: "Creating a new resource returns HTTP 201 with the created resource in `data`; every other successful operation, including all state-driving actions and all reads, returns HTTP 200 with the affected or requested resource in `data`."
        PRD: "A fresh asset opens with `exposure_state` set to `MONITORED` and with `open_finding_count`, `open_critical_finding_count` and `remediated_finding_count` all at 0, and its `last_cleared_at` is null."

        Design: Corner/entities/asset_retrieval_returns_the_stored_row_unchanged
        """
        advance_clock(client, T_PROGRAMME_OPEN)
        registered = created_data(client.create_asset(factories.asset_payload()))

        response = client.get_asset(registered["id"])

        asset = success_data(response)
        assert response.status_code == 200, (
            f"expected HTTP 200 from a read, got {response.status_code}"
        )
        assert asset["id"] == registered["id"], (
            f"id: expected {registered['id']}, got {asset['id']}"
        )
        assert_score(asset["exposure_score"], 88, "exposure_score")
        assert_asset_posture(asset, exposure_state="MONITORED")
        assert_exact_int(asset["criticality_tier"], 1, "criticality_tier")
        assert asset["compliance_regimes"] == ["SOC2"], (
            f"compliance_regimes: expected [SOC2], got {asset['compliance_regimes']}"
        )

    def test_the_inventory_pages_and_reports_the_unpaginated_total(self, client, admin):
        """Three assets read two at a time: total_count counts all three on both pages.

        PRD: "List responses set `response_type` to `"array"` and populate four pagination fields inside `meta`: `limit` (the effective page size), `offset` (the effective skip), `total_count` (the number of records matching the filters before pagination is applied) and `has_more` (true when records remain beyond the current page)."
        PRD: "Unless an endpoint's description states otherwise, list results are ordered by `created_at` ascending — oldest record first."

        Design: Corner/entities/asset_listing_paginates_and_reports_total_count_and_has_more
        """
        advance_clock(client, T_PROGRAMME_OPEN)
        created_data(client.create_asset(factories.asset_payload()))
        created_data(client.create_asset(factories.asset_payload(**BILLING_CLUSTER)))
        created_data(client.create_asset(factories.asset_payload(**WIKI)))

        first = client.list_assets(params={"limit": 2, "offset": 0}, headers=admin)
        second = client.list_assets(params={"limit": 2, "offset": 2}, headers=admin)

        first_rows, _first_meta = assert_page(
            first, total_count=3, has_more=True, row_count=2, limit=2, offset=0
        )
        assert first.json()["response_type"] == "array", (
            f"response_type: expected array, got {first.json()['response_type']}"
        )
        second_rows, _second_meta = assert_page(
            second, total_count=3, has_more=False, row_count=1, offset=2
        )
        assert first_rows[0]["id"] != second_rows[0]["id"], (
            "the two pages must be disjoint, but both begin with the same asset"
        )

    def test_an_unregistered_asset_id_in_the_path_answers_not_found(self, client, admin):
        """A well-formed identifier that resolves to nothing is a path-resolution failure.

        PRD: "Every identifier embedded in the URL is resolved left to right, and the first one that fails to resolve determines the error: `ERR_ASSET_NOT_FOUND`, `ERR_TEST_PLAN_NOT_FOUND`, `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_ROE_NOT_FOUND`, `ERR_TARGET_NOT_FOUND`, `ERR_TESTER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_REMEDIATION_NOT_FOUND` or `ERR_RETEST_NOT_FOUND`, each with HTTP 404."

        Design: Corner/entities/asset_get_with_unknown_id_returns_asset_not_found
        """
        advance_clock(client, T_PROGRAMME_OPEN)

        response = client.get_asset(UNREGISTERED_ID, headers=admin)

        assert_error_id(response, ERR_ASSET_NOT_FOUND)
        assert response.status_code == 404, (
            f"expected HTTP 404 for an unregistered asset, got {response.status_code}"
        )
        assert response.json()["response_type"] == "error", (
            f"response_type: expected error, got {response.json()['response_type']}"
        )


class TestRosterAndPlanDefaults:
    """Two optional inputs whose omission is filled in by the specification."""

    def test_a_tester_registered_without_a_cap_holds_two_engagements(self, client):
        """The concurrency cap defaults to 2 and the roster row opens unusable.

        PRD: "A tester record carries `full_name` (1 to 120 characters), a duplicate-free and possibly empty `certifications` list drawn from `OSCP`, `GPEN`, `CREST` and `CISSP`, a `clearance_expires_at` instant after which the tester's clearance is no longer valid, and `max_concurrent_engagements` — the aggregate cap on how many interval-overlapping assignments the tester may hold, which must be between 1 and 5 and defaults to 2 when the registrar does not state it."
        PRD: "From the certification list the server derives `qualification_score`: award 45 points for `OSCP`, 35 for `GPEN`, 25 for `CREST` and 15 for `CISSP`, add up the points for the certifications the tester actually holds, and cap the total at 100."
        PRD: "Their `background_check_status` opens at `PENDING`, their `background_check_at` is null, their `availability_state` opens at `PENDING_CLEARANCE`, and their `active_assignment_count` — the number of assignments they hold in the provisioned access state — opens at 0."

        Design: Corner/entities/tester_max_concurrent_engagements_defaults_to_two
        """
        advance_clock(client, T_PROGRAMME_OPEN)

        tester = created_data(
            client.create_tester(factories.tester_payload(max_concurrent_engagements=None))
        )

        assert_exact_int(
            tester["max_concurrent_engagements"], 2, "max_concurrent_engagements"
        )
        assert tester["availability_state"] == "PENDING_CLEARANCE", (
            f"availability_state: expected PENDING_CLEARANCE, "
            f"got {tester['availability_state']}"
        )
        assert tester["background_check_status"] == "PENDING", (
            f"background_check_status: expected PENDING, "
            f"got {tester['background_check_status']}"
        )
        assert_score(tester["qualification_score"], 80, "qualification_score")
        assert tester["background_check_at"] is None, (
            f"background_check_at: expected null, got {tester['background_check_at']}"
        )
        assert_exact_int(
            tester["active_assignment_count"], 0, "active_assignment_count"
        )

    def test_a_plan_opened_without_a_mode_scores_risk_driven(self, client):
        """The mode defaults, the threshold is derived, and every ledger opens empty.

        PRD: "The plan also declares `prioritization_mode`, either `RISK_DRIVEN` or `COMPLIANCE_DRIVEN`, defaulting to `RISK_DRIVEN` when the manager does not say."
        PRD: "`risk_appetite_score`, an integer from 0 to 100 inclusive, expresses how much low-scoring scope the programme is willing to admit, and from it the server immediately derives `admission_threshold` as 100 minus the appetite — a hungry programme with an appetite of 90 admits candidates scoring as low as 10, while a conservative programme with an appetite of 20 demands 80."
        PRD: "A new plan opens at `DRAFT` status with `coverage_score` at 0 and all five risk-point buckets — `total_risk_points`, `open_risk_points`, `closed_risk_points`, `accepted_risk_points` and `duplicate_risk_points` — at 0."

        Design: Corner/entities/test_plan_prioritization_mode_defaults_to_risk_driven
        """
        advance_clock(client, T_PROGRAMME_OPEN)

        plan = created_data(
            client.create_test_plan(factories.test_plan_payload(prioritization_mode=None))
        )

        assert plan["prioritization_mode"] == "RISK_DRIVEN", (
            f"prioritization_mode: expected RISK_DRIVEN, got {plan['prioritization_mode']}"
        )
        assert_score(plan["admission_threshold"], 60, "admission_threshold")
        assert plan["status"] == "DRAFT", f"status: expected DRAFT, got {plan['status']}"
        assert_score(plan["coverage_score"], 0, "coverage_score")
        assert_risk_ledger(
            plan, total=0, open_points=0, closed=0, accepted=0, duplicate=0
        )
        assert_system_fields(plan, version=1)


class TestScopeCandidateShape:
    """A candidate is scored and ranked by the same request that creates it."""

    def test_the_create_response_already_carries_the_score_the_rank_and_the_flag(
        self, client
    ):
        """No second request is needed to see the prioritisation the server applied.

        PRD: "Under `RISK_DRIVEN` — the default — exposure is weighted 0.45, tier points 0.30, staleness points 0.20 and regime points 0.05, so attack surface and business criticality dominate."
        PRD: "Finally `below_threshold_flag` is set to true when `priority_score` is strictly less than the plan's `admission_threshold` — a score exactly equal to the threshold is not below it and the flag stays false."
        PRD: "Only candidates of the plan whose status is `PROPOSED` or `APPROVED` are ranked."
        PRD: "A newly accepted candidate opens at `PROPOSED` status with a null `decision_note`."

        Design: Corner/entities/scope_item_computed_score_and_rank_are_stamped_at_creation
        """
        scenario = build_scenario(client, stage="plan")

        candidate = created_data(
            client.create_scope_item(
                factories.scope_item_payload(
                    scenario["plan_id"],
                    scenario["asset_id"],
                    scenario["plan"]["version"],
                )
            )
        )

        assert_score(candidate["priority_score"], 89.80, "priority_score")
        assert_exact_int(candidate["priority_rank"], 1, "priority_rank")
        assert candidate["scored_mode"] == "RISK_DRIVEN", (
            f"scored_mode: expected RISK_DRIVEN, got {candidate['scored_mode']}"
        )
        assert candidate["below_threshold_flag"] is False, (
            "89.80 is far above the admission threshold of 60, so the flag stays false"
        )
        assert candidate["status"] == "PROPOSED", (
            f"status: expected PROPOSED, got {candidate['status']}"
        )
        assert candidate["decision_note"] is None, (
            f"decision_note: expected null, got {candidate['decision_note']}"
        )

    def test_a_body_naming_an_unregistered_parent_is_refused_before_the_version_guard(
        self, client
    ):
        """Both body foreign keys resolve first, and neither refusal touches the plan.

        PRD: "Every foreign key supplied in a body must resolve: `test_plan_id`, `asset_id`, `scope_item_id`, `engagement_id`, `roe_id`, `tester_id`, `finding_id`, `remediation_id`, `duplicate_of_finding_id`, and each member of `granted_asset_ids`."
        PRD: "The failure carries the matching not-found identifier from Band 2's list at HTTP 404 — an unresolvable `asset_id` in a body, or inside `granted_asset_ids`, yields `ERR_ASSET_NOT_FOUND`."

        Design: Corner/entities/scope_item_creation_with_unknown_test_plan_is_rejected
        """
        scenario = build_scenario(client, stage="plan")
        declared_version = scenario["plan"]["version"]

        unknown_plan = client.create_scope_item(
            factories.scope_item_payload(
                UNREGISTERED_ID, scenario["asset_id"], declared_version
            )
        )
        unknown_asset = client.create_scope_item(
            factories.scope_item_payload(
                scenario["plan_id"], SECOND_UNREGISTERED_ID, declared_version
            )
        )

        assert_error_id(unknown_plan, ERR_TEST_PLAN_NOT_FOUND)
        assert unknown_plan.status_code == 404, (
            f"expected HTTP 404 for an unknown plan, got {unknown_plan.status_code}"
        )
        assert_error_id(unknown_asset, ERR_ASSET_NOT_FOUND)
        assert unknown_asset.status_code == 404, (
            f"expected HTTP 404 for an unknown asset, got {unknown_asset.status_code}"
        )
        assert_exact_int(
            read_plan_version(client, scenario["plan_id"]), 1, "test plan version"
        )


class TestChartersAndGrantsRefuseMalformedBodies:
    """Two body rules that answer before the workflow they would otherwise enter."""

    def test_a_window_that_ends_where_it_starts_is_refused(self, client):
        """An engagement window must be non-empty, and the refusal costs the candidate nothing.

        PRD: "Chartering names the `test_plan_id`, names the `scope_item_id` it is drawing down, declares the `engagement_type` as one of `APPLICATION_TEST`, `NETWORK_TEST` or `CLOUD_REVIEW`, fixes the engagement's testing window with an inclusive `window_start` and an inclusive `window_end` that must fall strictly after the start, and grants a tester-hour budget in `hours_allocated`, strictly greater than 0 and at most 2000."
        PRD: "For every request that carries a body, the body is checked against the endpoint's declared inputs: required fields present and non-blank, types correct, enumerated values drawn from the known member list, numeric values inside their declared ranges, arrays free of duplicate members, every target window ending strictly after it starts, and every assignment interval ending strictly after it starts. Any violation is `ERR_INVALID_REQUEST` with HTTP 400."
        PRD: "The scope item moves `APPROVED` → `CONSUMED`, which both records that the plan's intent has been acted on and releases the plan-and-asset uniqueness slot so a follow-up candidate for the same asset may be proposed later."

        Design: Corner/entities/engagement_window_end_not_after_window_start_is_rejected
        """
        scenario = build_scenario(client, stage="plan_active")

        response = client.create_engagement(
            factories.engagement_payload(
                scenario["plan_id"],
                scenario["scope_item_id"],
                window_start=WINDOW_START,
                window_end=WINDOW_START,
            )
        )

        assert_error_id(response, ERR_INVALID_REQUEST)
        assert response.status_code == 400, (
            f"expected HTTP 400 for an empty testing window, got {response.status_code}"
        )
        candidate = success_data(client.get_scope_item(scenario["scope_item_id"]))
        assert candidate["status"] == "APPROVED", (
            "a refused charter must not consume the candidate, "
            f"but its status is {candidate['status']}"
        )

    def test_one_unresolvable_granted_asset_sinks_the_whole_booking(self, client):
        """Every member of the grant array is a foreign key in its own right.

        PRD: "Every foreign key supplied in a body must resolve: `test_plan_id`, `asset_id`, `scope_item_id`, `engagement_id`, `roe_id`, `tester_id`, `finding_id`, `remediation_id`, `duplicate_of_finding_id`, and each member of `granted_asset_ids`."
        PRD: "The failure carries the matching not-found identifier from Band 2's list at HTTP 404 — an unresolvable `asset_id` in a body, or inside `granted_asset_ids`, yields `ERR_ASSET_NOT_FOUND`."
        PRD: "Its `requested_hours` are added to the engagement's `hours_reserved`, `hours_available` is recomputed as the allocation minus reserved minus consumed, and the engagement's `version` advances."

        Design: Corner/entities/assignment_granted_asset_id_that_does_not_resolve_is_rejected
        """
        scenario = build_scenario(client, stage="tester_cleared")
        advance_clock(client, T_BEFORE_ASSIGNMENT)
        declared_version = engagement_version(client, scenario["engagement_id"])

        response = client.create_tester_assignment(
            factories.tester_assignment_payload(
                scenario["engagement_id"],
                scenario["tester_id"],
                declared_version,
                [scenario["asset_id"], UNREGISTERED_ID],
            )
        )

        assert_error_id(response, ERR_ASSET_NOT_FOUND)
        assert response.status_code == 404, (
            f"expected HTTP 404 for an unresolvable granted asset, got {response.status_code}"
        )
        engagement = success_data(client.get_engagement(scenario["engagement_id"]))
        assert_exact_int(engagement["version"], declared_version, "engagement version")
        assert_exact_int(engagement["hours_reserved"], 0, "hours_reserved")


GENERATION_INSTANT = "2026-09-10T00:00:00Z"
ANALYSIS_WINDOW_END = "2026-09-10T00:00:00Z"


class TestTrainingRecommendationImmutability:
    """The one record in the programme that carries neither updated_at nor version."""

    def test_a_generated_recommendation_reads_back_byte_for_byte(self, client):
        """Trend analysis emits an analytics row that no endpoint can afterwards edit.

        PRD: "**Training recommendations are the single exception**: they are immutable analytics records, and they carry only `id` and `created_at` — both `updated_at` and `version` are absent from their representation entirely, because nothing ever mutates them after generation."
        PRD: "Each finding's contribution is its severity weight multiplied by its recency multiplier, **rounded half-up to two decimal places before anything is summed**."
        PRD: "Each recommendation also records `recurrence_count`, the number of contributing findings for the theme in the window; `source_engagement_count`, the number of distinct engagements those contributing findings came from; and `generated_at`, the logical-clock instant of generation, against which the recency decay was measured."
        PRD: "`urgency_band` is `MANDATORY` when `recurrence_count` is at least 3 **and** `priority_score` is at least 8.00, and `RECOMMENDED` in every other case — both conditions must hold, so a single devastating finding is never mandatory training on its own."

        Design: Corner/entities/training_recommendation_rows_are_immutable_and_carry_no_version
        """
        scenario = build_scenario(
            client,
            roe={"allowed_techniques": ["AUTHZ_BYPASS"]},
            target={"technique_allowlist": ["AUTHZ_BYPASS"]},
        )
        advance_clock(client, T_FIELDWORK_DAY)
        finding = report_finding(client, scenario)
        advance_clock(client, GENERATION_INSTANT)

        rows = emitted_rows(
            client.generate_training_recommendations(
                scenario["plan_id"], T_PROGRAMME_OPEN, ANALYSIS_WINDOW_END
            )
        )

        assert len(rows) == 1, f"expected exactly one recommendation, got {len(rows)}"
        recommendation = rows[0]
        assert recommendation["root_cause_theme"] == "ACCESS_CONTROL", (
            f"root_cause_theme: expected ACCESS_CONTROL, "
            f"got {recommendation['root_cause_theme']}"
        )
        assert_score(recommendation["priority_score"], 4.97, "priority_score")
        assert_exact_int(recommendation["recurrence_count"], 1, "recurrence_count")
        assert_exact_int(
            recommendation["source_engagement_count"], 1, "source_engagement_count"
        )
        assert recommendation["urgency_band"] == "RECOMMENDED", (
            f"urgency_band: expected RECOMMENDED, got {recommendation['urgency_band']}"
        )
        assert recommendation["contributing_finding_ids"] == [finding["id"]], (
            "the single contributing finding must be listed, got "
            f"{recommendation['contributing_finding_ids']}"
        )
        assert_analytics_record_shape(recommendation)

        re_read = success_data(client.get_training_recommendation(recommendation["id"]))
        assert_score(re_read["priority_score"], 4.97, "priority_score on re-read")
        assert_instant_equals(re_read["generated_at"], GENERATION_INSTANT, "generated_at")
        assert_analytics_record_shape(re_read)
