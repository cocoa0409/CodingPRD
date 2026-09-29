"""Registering, reading and listing the estate: defaults, envelopes and the append-only log."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    CLOCK_EPOCH,
    DEFAULT_LIMIT,
    PLATFORM_ADMIN_HEADERS,
    assert_append_only_row,
    assert_common_fields,
    assert_instant,
    assert_pagination_meta,
    assert_posture,
    assert_projection,
    assert_runbook_state,
    factories as f,
    fixtures as fx,
)


def test_recovery_group_posture_and_projection_are_derived_from_its_members(api):
    """A posture refresh recomputes every derived group field from the estate.

    PRD: "Every request that touches a group's runbooks, steps, findings or
    membership ends by re-running this derivation, and a coordinator or audit
    liaison may re-run it deliberately: a posture refresh recomputes the current
    runbook's `readiness_score` against the current logical clock, recomputes
    `projected_recovery_minutes`, `recovery_sequence` and `open_finding_count`,
    and then re-derives `posture` and `posture_reason`, answering 200 OK with the
    group."

    Design: Corner/entities/recovery_group_computed_posture_and_projection_are_derived_from_members
    """
    estate = fx.setup_single_application_estate(api)
    coordinator = estate["coordinator_headers"]

    group = validate_success(
        api.refresh_posture(estate["group"]["id"], coordinator), 200
    )

    assert_posture(group, "READY", "READY_ALL_CHECKS_PASSED")
    assert group["current_runbook_id"] == estate["runbook"]["id"]
    assert group["open_finding_count"] == 0
    assert_projection(
        group, 80, [estate["app_core"]["id"], estate["asset_db"]["id"]]
    )
    assert_runbook_state(
        fx.read_runbook(api, coordinator, estate["runbook"]["id"]),
        "VALIDATED",
        readiness_score=100.00,
    )


def test_create_application_returns_its_declared_defaults(api):
    """A newly registered application carries every negotiation field at its default.

    PRD: "A freshly registered application starts with `tier_agreement_status` at
    `DRAFT`, its `recovery_group_id` null until it is assigned to a group,
    `retier_count` at 0, and `tier`, `rto_minutes` and `rpo_minutes` all null
    because nothing has been agreed yet."

    Design: Corner/entities/create_application_returns_201_with_declared_defaults
    """
    estate = fx.setup_single_application_estate(
        api, through=fx.CORE_SITES_REGISTERED
    )

    application = validate_success(
        api.create_application(
            f.application_payload(
                business_owner_id=estate["business_owner"]["id"],
                primary_site_id=estate["site_primary"]["id"],
                app_code="APP-RPT",
                name="Reporting portal",
                criticality_weight=4,
            ),
            estate["coordinator_headers"],
        ),
        201,
    )

    assert application["name"] == "Reporting portal"
    assert application["app_code"] == "APP-RPT"
    assert application["criticality_weight"] == 4
    assert application["tier_agreement_status"] == "DRAFT"
    for field in ("tier", "rto_minutes", "rpo_minutes", "proposed_tier"):
        assert application[field] is None, f"{field} should start null"
    assert application["proposed_rto_minutes"] is None
    assert application["proposed_rpo_minutes"] is None
    assert application["proposed_by_id"] is None
    assert application["recovery_group_id"] is None
    assert application["retier_count"] == 0
    assert_common_fields(application, expected_version=1)
    assert_instant(application["created_at"], CLOCK_EPOCH)
    assert_instant(application["updated_at"], CLOCK_EPOCH)


def test_get_asset_returns_the_stored_representation(api):
    """The asset read echoes its registration and the group assignment applied later.

    PRD: "An optional `expected_txn_rate_per_minute`, defaulting to 0 and never
    negative, records the steady-state write rate; §3.7 explains why that number
    decides how a data-loss window is measured."

    Design: Corner/entities/get_asset_by_id_returns_the_stored_representation
    """
    estate = fx.setup_single_application_estate(api, through=fx.CORE_ASSET_ASSIGNED)

    asset = validate_success(
        api.get_asset(estate["asset_db"]["id"], estate["operator_headers"]), 200
    )

    assert asset["asset_code"] == "AST-DB1"
    assert asset["asset_kind"] == "DATA_STORE"
    assert asset["replication_mode"] == "ASYNCHRONOUS"
    assert asset["restore_minutes"] == 20
    assert asset["expected_txn_rate_per_minute"] == 150
    assert asset["site_id"] == estate["site_primary"]["id"]
    assert asset["recovery_group_id"] == estate["group"]["id"]


def test_runbook_step_list_composes_its_filter_with_pagination(api):
    """The runbook filter, the limit and the offset all apply to the same list.

    PRD: "Every list response repeats `limit` and `offset` in the `meta` object
    alongside `total_count`, the number of rows matching the filter before
    pagination, and `has_more`, a boolean that is true when rows remain beyond
    the current page."

    Design: Corner/entities/list_runbook_steps_filtered_by_runbook_paginates_with_total_count
    """
    estate = fx.setup_single_application_estate(api, through=fx.CORE_STEP_ADDED)
    coordinator = estate["coordinator_headers"]
    runbook_id = estate["runbook"]["id"]
    second = fx.add_step(
        api,
        coordinator,
        runbook_id,
        estate["operator"]["id"],
        step_number=2,
        description="Open the database at the recovery site",
        expected_minutes=20,
        weight=10,
        covers_asset_id=estate["asset_db"]["id"],
    )

    first_page, first_meta = validate_paginated(
        api.list_runbook_steps(
            coordinator, params={"runbook_id": runbook_id, "limit": 1, "offset": 0}
        )
    )
    second_page, second_meta = validate_paginated(
        api.list_runbook_steps(
            coordinator, params={"runbook_id": runbook_id, "limit": 1, "offset": 1}
        )
    )

    assert len(first_page) == 1
    assert_pagination_meta(first_meta, total_count=2, limit=1, offset=0, has_more=True)
    assert len(second_page) == 1
    assert_pagination_meta(second_meta, total_count=2, limit=1, offset=1, has_more=False)
    assert {first_page[0]["id"], second_page[0]["id"]} == {
        estate["step_core"]["id"],
        second["id"],
    }
    all_rows, all_meta = validate_paginated(
        api.list_runbook_steps(coordinator, params={"runbook_id": runbook_id})
    )
    assert len(all_rows) == 2
    assert_pagination_meta(
        all_meta, total_count=2, limit=DEFAULT_LIMIT, offset=0, has_more=False
    )


def test_get_exercise_with_an_unknown_id_is_not_found(api):
    """An unresolvable path id answers with the exercise not-found error.

    PRD: "Existence of every id templated into the path, validated **left to
    right**, on every endpoint with a templated segment." And: "The first
    identifier that does not resolve determines the error, drawn from
    `ERR_STAKEHOLDER_NOT_FOUND`, `ERR_SITE_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`,
    `ERR_DEPENDENCY_EDGE_NOT_FOUND`, `ERR_RECOVERY_GROUP_NOT_FOUND`,
    `ERR_RUNBOOK_NOT_FOUND`, `ERR_RUNBOOK_STEP_NOT_FOUND`,
    `ERR_EXERCISE_NOT_FOUND`, `ERR_SCOPE_ITEM_NOT_FOUND`,
    `ERR_STEP_EXECUTION_NOT_FOUND`, `ERR_FINDING_NOT_FOUND` and
    `ERR_EVIDENCE_PACKAGE_NOT_FOUND`, each HTTP 404."

    Design: Corner/entities/get_exercise_with_unknown_id_not_found
    """
    estate = fx.setup_single_application_estate(
        api, through=fx.CORE_PEOPLE_REGISTERED
    )

    validate_error(
        api.get_exercise(NON_EXISTENT_UUID, estate["coordinator_headers"]),
        ApiErrorId.ERR_EXERCISE_NOT_FOUND,
        404,
    )


def test_create_site_without_usable_capacity_is_an_invalid_request(api):
    """The capacity figure is a required input, never silently defaulted.

    PRD: "Each carries a display `name`, a `site_code` unique across all sites, a
    `role` that is either `PRIMARY` for a site that normally runs production or
    `RECOVERY` for one that receives failover, and a `usable_capacity_units`
    figure that must not be negative."

    Design: Corner/entities/create_site_missing_required_usable_capacity_returns_invalid_request
    """
    fx.setup_single_application_estate(api, through=fx.CORE_PEOPLE_REGISTERED)

    validate_error(
        api.create_site(
            f.site_payload(
                site_code="SITE-X",
                name="Half-specified site",
                role="RECOVERY",
                usable_capacity_units=None,
            ),
            PLATFORM_ADMIN_HEADERS,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    _, meta = validate_paginated(api.list_sites(PLATFORM_ADMIN_HEADERS))
    assert meta["total_count"] == 0


def test_runbook_created_without_validity_days_defaults_to_one_hundred_eighty(api):
    """The optional validity window falls back to its declared default.

    PRD: "An optional `validity_days` — an integer from 1 to 3650, defaulting to
    180 — declares how long a validation of this revision remains acceptable for
    exercise scoping." And: "The new revision starts with `status` `DRAFT`,
    `readiness_score` 0.00, `stale_reason` `NONE` and `validated_at` null, and
    opening it increments the owning group's `version` by 1."

    Design: Corner/entities/create_runbook_without_validity_days_applies_the_default_180
    """
    estate = fx.setup_single_application_estate(
        api, through=fx.CORE_GROUP_VERSION_READ
    )
    coordinator = estate["coordinator_headers"]

    runbook = validate_success(
        api.create_runbook(
            f.runbook_payload(
                estate["group"]["id"],
                estate["coordinator"]["id"],
                estate["group_version"],
                title="Runbook without an explicit validity",
            ),
            coordinator,
        ),
        201,
    )

    assert runbook["validity_days"] == 180
    assert_runbook_state(runbook, "DRAFT", stale_reason="NONE", readiness_score=0.00)
    assert runbook["validated_at"] is None
    assert runbook["revision"] == 1
    group = fx.read_group(api, coordinator, estate["group"]["id"])
    assert group["version"] == estate["group_version"] + 1
    assert group["current_runbook_id"] is None


def test_client_supplied_system_fields_on_a_stakeholder_are_ignored(api):
    """Identity, audit columns and computed status come from the server alone.

    PRD: "An `approval_authority_level` may be supplied at registration and
    defaults to `LEVEL_1` when it is not; `status` begins at `ACTIVE`." And:
    "Every computed timestamp the server stamps thereafter — `validated_at`,
    `last_validated_at`, `execution_started_at`, `failover_completed_at`,
    `sealed_at` — reads the logical clock, and every age computation reads it
    too."

    Design: Corner/entities/create_stakeholder_system_fields_input_ignored
    """
    fx.set_logical_clock(api, CLOCK_EPOCH)
    submitted_id = "11111111-1111-4111-8111-111111111111"

    stakeholder = validate_success(
        api.create_stakeholder(
            {
                "full_name": "Ignored Fields",
                "email": "ignored.fields@example.com",
                "org_roles": ["IT_OPERATOR"],
                "id": submitted_id,
                "created_at": "2020-01-01T00:00:00Z",
                "version": 99,
                "status": "SUSPENDED",
            },
            PLATFORM_ADMIN_HEADERS,
        ),
        201,
    )

    assert stakeholder["id"] != submitted_id
    assert_instant(stakeholder["created_at"], CLOCK_EPOCH)
    assert stakeholder["version"] == 1
    assert stakeholder["status"] == "ACTIVE"
    assert stakeholder["approval_authority_level"] == "LEVEL_1"


def test_out_of_set_enum_and_out_of_range_integer_are_invalid_requests(api):
    """Both a foreign enum member and an integer past its range are shape errors.

    PRD: "Request shape: required fields present, enum values members of their
    declared sets, integers inside their declared ranges, datetimes well-formed
    ISO 8601 UTC, and pagination within bounds — `ERR_INVALID_REQUEST` (400), on
    every endpoint."

    Design: Corner/entities/create_exercise_with_unknown_type_invalid_enum
    """
    estate = fx.setup_single_application_estate(
        api, through=fx.CORE_SITES_REGISTERED
    )
    coordinator = estate["coordinator_headers"]

    validate_error(
        api.create_exercise(
            f.exercise_payload(
                recovery_site_id=estate["site_recovery"]["id"],
                coordinator_id=estate["coordinator"]["id"],
                planned_start_at="2026-08-20T00:00:00Z",
                planned_end_at="2026-08-20T06:00:00Z",
                name="Unknown type",
                exercise_type="PARTIAL_FAILOVER",
            ),
            coordinator,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_application(
            f.application_payload(
                business_owner_id=estate["business_owner"]["id"],
                primary_site_id=estate["site_primary"]["id"],
                app_code="APP-OVER",
                name="Over-weighted application",
                criticality_weight=11,
            ),
            coordinator,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )

    _, exercise_meta = validate_paginated(api.list_exercises(coordinator))
    assert exercise_meta["total_count"] == 0
    _, application_meta = validate_paginated(api.list_applications(coordinator))
    assert application_meta["total_count"] == 0


def test_replication_observations_append_and_carry_no_version(api):
    """Two measurements on one asset both persist and neither carries a version.

    PRD: "A `ReplicationObservation` is an append-only event log row: it carries
    only `id` and `created_at`." And: "The server records the asset the
    observation belongs to as `asset_id` and stamps `recorded_by_user_id` with
    the acting `X-User-ID`; no other entity is mutated by the append." And: "There
    is exactly one exception in this API: an asset's replication-observation log is
    returned with the most recent `observed_at` first."

    Design: Corner/entities/replication_observation_is_append_only_with_no_version_field
    """
    estate = fx.setup_single_application_estate(api, through=fx.CORE_ASSET_ASSIGNED)
    operator = estate["operator_headers"]
    asset_id = estate["asset_db"]["id"]

    first = validate_success(
        api.create_replication_observation(
            asset_id,
            f.replication_observation_payload("2026-07-31T23:00:00Z", 120, 300),
            operator,
        ),
        201,
    )
    second = validate_success(
        api.create_replication_observation(
            asset_id,
            f.replication_observation_payload(CLOCK_EPOCH, 240, 900),
            operator,
        ),
        201,
    )

    assert first["id"] != second["id"]
    assert_append_only_row(first)
    assert_append_only_row(second)
    assert first["recorded_by_user_id"] == estate["operator"]["id"]
    assert first["asset_id"] == asset_id
    rows, meta = validate_paginated(
        api.list_replication_observations(asset_id, estate["coordinator_headers"])
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [second["id"], first["id"]]


def test_observation_against_an_unknown_asset_is_not_found(api):
    """The log is only reachable under an asset that exists.

    PRD: "Existence of every id templated into the path, validated **left to
    right**, on every endpoint with a templated segment."

    Design: Corner/entities/replication_observation_with_unknown_parent_asset_not_found
    """
    estate = fx.setup_single_application_estate(
        api, through=fx.CORE_PEOPLE_REGISTERED
    )

    validate_error(
        api.create_replication_observation(
            NON_EXISTENT_UUID,
            f.replication_observation_payload(CLOCK_EPOCH, 60, 10),
            estate["operator_headers"],
        ),
        ApiErrorId.ERR_ASSET_NOT_FOUND,
        404,
    )


def test_polymorphic_edges_coexist_while_a_hard_cycle_is_refused(api):
    """Application and asset endpoints mix freely, but a HARD cycle is blocked.

    PRD: "An edge whose `from_node_id` equals its `to_node_id` is rejected with
    `ERR_SELF_DEPENDENCY`; a `HARD` edge that would close a directed cycle among
    the existing `HARD` edges is rejected with `ERR_DEPENDENCY_CYCLE`, while
    `SOFT` edges are exempt from that check entirely; and an edge duplicating an
    existing combination of `from_node_id`, `to_node_id` and `edge_kind` is
    rejected with `ERR_DUPLICATE_DEPENDENCY_EDGE`."

    Design: Corner/entities/dependency_graph_supports_polymorphic_nodes_and_rejects_hard_cycles
    """
    estate = fx.setup_single_application_estate(api, through=fx.CORE_EDGE_CREATED)
    coordinator = estate["coordinator_headers"]
    switch = fx.register_asset(
        api,
        estate["operator_headers"],
        site_id=estate["site_primary"]["id"],
        asset_code="AST-NET1",
        name="Core switch",
        asset_kind="INFRA_COMPONENT",
        replication_mode="SYNCHRONOUS",
        restore_minutes=12,
    )
    fx.assign_asset(api, coordinator, switch["id"], estate["group"]["id"])
    fx.create_dependency_edge(
        api,
        coordinator,
        from_node_kind="ASSET",
        from_node_id=estate["asset_db"]["id"],
        to_node_kind="ASSET",
        to_node_id=switch["id"],
        edge_kind="HARD",
    )

    validate_error(
        api.create_dependency_edge(
            f.dependency_edge_payload(
                "ASSET", switch["id"], "APPLICATION", estate["app_core"]["id"], "HARD"
            ),
            coordinator,
        ),
        ApiErrorId.ERR_DEPENDENCY_CYCLE,
        422,
    )
    soft_edge = validate_success(
        api.create_dependency_edge(
            f.dependency_edge_payload(
                "ASSET", switch["id"], "APPLICATION", estate["app_core"]["id"], "SOFT"
            ),
            coordinator,
        ),
        201,
    )

    group = fx.read_group(api, coordinator, estate["group"]["id"])
    assert_projection(
        group,
        92,
        [estate["app_core"]["id"], estate["asset_db"]["id"], switch["id"]],
    )
    rows, meta = validate_paginated(
        api.list_dependency_edges(coordinator, params={"from_node_id": switch["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == soft_edge["id"]
