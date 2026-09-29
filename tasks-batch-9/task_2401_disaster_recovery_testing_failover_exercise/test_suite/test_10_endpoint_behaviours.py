"""Partial patches, action endpoints, membership links and computed reads."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    assert_axes,
    assert_impact_scores,
    assert_instant,
    assert_posture,
    assert_projection,
    assert_reserved_capacity,
    factories as f,
    fixtures as fx,
)


def test_patching_a_stakeholder_writes_only_the_supplied_field(api):
    """The partial patch lifts the authority level and leaves the rest alone.

    PRD: "Later the administrator may patch any combination of `status`,
    `approval_authority_level` and `org_roles` on an existing person." And:
    "Patching a stakeholder, refreshing a recovery group's posture and setting the
    logical clock therefore answer 200, while every `POST` that mints a row or
    records an action answers 201."

    Design: Corner/endpoints/patch_stakeholder_updates_authority_and_bumps_the_version
    """
    estate = fx.setup_single_application_estate(
        api, through=fx.CORE_PEOPLE_REGISTERED
    )
    liaison_id = estate["audit_liaison"]["id"]

    patched = validate_success(
        api.patch_stakeholder(
            liaison_id, {"approval_authority_level": "LEVEL_2"}, estate["admin_headers"]
        ),
        200,
    )

    assert patched["approval_authority_level"] == "LEVEL_2"
    assert patched["version"] == 2
    assert patched["full_name"] == "Ally Ito"
    assert patched["email"] == "ally.ito@example.com"
    assert patched["org_roles"] == ["AUDIT_LIAISON"]
    assert patched["status"] == "ACTIVE"
    untouched = validate_success(
        api.get_stakeholder(estate["risk_approver"]["id"], estate["admin_headers"])
    )
    assert untouched["version"] == 1


def test_a_zero_length_change_freeze_is_stored_and_bumps_the_group_version(api):
    """A closed interval may be a single instant, and storing it versions the group.

    PRD: "Both endpoints of that interval are **inclusive** — it is a closed
    interval — and `change_freeze_end_at` must be at or after
    `change_freeze_start_at` or the request is rejected with `ERR_INVALID_WINDOW`."
    And: "Storing the window increments the group's `version` by 1."

    Design: Corner/endpoints/change_freeze_stores_the_interval_and_bumps_the_group_version
    """
    estate = fx.setup_single_application_estate(api, through=fx.CORE_GROUP_CREATED)
    coordinator = estate["coordinator_headers"]
    assert estate["group"]["version"] == 1

    frozen = validate_success(
        api.set_change_freeze(
            estate["group"]["id"],
            f.change_freeze_payload("2026-08-20T00:00:00Z", "2026-08-20T00:00:00Z"),
            coordinator,
        ),
        201,
    )

    assert_instant(frozen["change_freeze_start_at"], "2026-08-20T00:00:00Z")
    assert_instant(frozen["change_freeze_end_at"], "2026-08-20T00:00:00Z")
    assert frozen["version"] == 2
    assert_posture(frozen, "RESTRICTED", "NO_VALIDATED_RUNBOOK")


def test_assigning_an_asset_pulls_it_into_the_projection(api):
    """The edge only counts once both of its endpoints are members of the group.

    PRD: "It writes the application's `recovery_group_id`, recomputes the group's
    `projected_recovery_minutes` and `recovery_sequence`, and increments that
    group's `version` by 1." And: "Assets are assigned to groups the same way and
    with the same three consequences." And: "The edge set is every `HARD`
    dependency edge whose two endpoints are both members of that node set; `SOFT`
    edges are excluded, and every edge that reaches outside the group's membership
    is excluded too."

    Design: Corner/endpoints/asset_group_assignment_links_both_rows_and_recomputes_the_projection
    """
    estate = fx.setup_single_application_estate(
        api, through=fx.CORE_APPLICATION_ASSIGNED
    )
    coordinator = estate["coordinator_headers"]
    group_id = estate["group"]["id"]
    edge = fx.create_dependency_edge(
        api,
        coordinator,
        from_node_kind="APPLICATION",
        from_node_id=estate["app_core"]["id"],
        to_node_kind="ASSET",
        to_node_id=estate["asset_db"]["id"],
        edge_kind="HARD",
    )
    before = fx.read_group(api, coordinator, group_id)
    assert_projection(before, 60, [estate["app_core"]["id"]])

    assigned = fx.assign_asset(api, coordinator, estate["asset_db"]["id"], group_id)

    assert assigned["recovery_group_id"] == group_id
    after = fx.read_group(api, coordinator, group_id)
    assert_projection(
        after, 80, [estate["app_core"]["id"], estate["asset_db"]["id"]]
    )
    stored_edge = validate_success(
        api.get_dependency_edge(edge["id"], coordinator)
    )
    assert stored_edge["version"] == edge["version"]
    assert stored_edge["from_node_id"] == estate["app_core"]["id"]
    assert stored_edge["to_node_id"] == estate["asset_db"]["id"]
    assert after["version"] > before["version"]


def test_reading_a_group_returns_the_three_node_chain_without_changing_it(api):
    """The derived values are stored, so a plain read reports the full HARD chain.

    PRD: "Over that directed subgraph — always acyclic, because cycle creation is
    blocked at write time — the server finds the directed path whose total node
    weight is greatest, and `projected_recovery_minutes` is that total." And:
    "`recovery_sequence` is the ordered list of node ids along that winning path,
    running from the most dependent node at the head down to the deepest dependency
    at the tail, following the direction of the edges."

    Design: Corner/endpoints/recovery_group_read_reflects_the_three_node_hard_chain
    """
    estate = fx.setup_single_application_estate(api, through=fx.CORE_EDGE_CREATED)
    coordinator = estate["coordinator_headers"]
    group_id = estate["group"]["id"]
    fabric = fx.register_asset(
        api,
        estate["operator_headers"],
        site_id=estate["site_primary"]["id"],
        asset_code="AST-NET1",
        name="Core network fabric",
        asset_kind="INFRA_COMPONENT",
        replication_mode="SYNCHRONOUS",
        restore_minutes=12,
    )
    fx.assign_asset(api, coordinator, fabric["id"], group_id)
    fx.create_dependency_edge(
        api,
        coordinator,
        from_node_kind="ASSET",
        from_node_id=estate["asset_db"]["id"],
        to_node_kind="ASSET",
        to_node_id=fabric["id"],
        edge_kind="HARD",
    )

    read = validate_success(
        api.get_recovery_group(group_id, estate["liaison_headers"]), 200
    )

    assert_projection(
        read,
        92,
        [estate["app_core"]["id"], estate["asset_db"]["id"], fabric["id"]],
    )
    assert_posture(read, "RESTRICTED", "NO_VALIDATED_RUNBOOK")
    second_read = fx.read_group(api, coordinator, group_id)
    assert second_read["version"] == read["version"]


def test_scheduling_is_refused_before_the_impact_approval(api):
    """The same call fails from SCOPED and succeeds from APPROVED.

    PRD: "Scheduling is the act that reserves the site, moving `execution_state`
    from `APPROVED` to `SCHEDULED` and optionally recording a `scheduling_note`."
    And: "The exercise's `execution_state` is a declared from-state for the
    requested action — `ERR_INVALID_EXERCISE_STATE` (409), on scope-item creation,
    impact submission, impact decision, scheduling, execution transitions and
    step-execution recording."

    Design: Corner/endpoints/schedule_is_allowed_only_from_approved
    """
    estate = fx.setup_single_application_estate(api)
    coordinator = estate["coordinator_headers"]
    site_id = estate["site_recovery"]["id"]
    exercise = fx.setup_scoped_exercise(
        api,
        estate,
        name="Conditional schedule subject",
        planned_start_at="2026-08-20T00:00:00Z",
        planned_end_at="2026-08-20T06:00:00Z",
    )

    validate_error(
        api.schedule_exercise(
            exercise["id"],
            {"scheduling_note": "Too early, impact not approved"},
            coordinator,
        ),
        ApiErrorId.ERR_INVALID_EXERCISE_STATE,
        409,
    )
    assert_reserved_capacity(fx.read_site(api, coordinator, site_id), 0)

    fx.submit_impact(api, coordinator, exercise["id"])
    approved = fx.approve_impact(
        api, estate["approver_headers"], exercise["id"], note="Window accepted"
    )
    assert_axes(approved, execution_state="APPROVED")
    assert approved["impact_approved_by_id"] == estate["risk_approver"]["id"]
    assert_impact_scores(approved, 30.50, 31.50, "LEVEL_1")

    scheduled = validate_success(
        api.schedule_exercise(
            exercise["id"],
            {"scheduling_note": "Approved, booking the window"},
            coordinator,
        ),
        201,
    )

    assert_axes(scheduled, execution_state="SCHEDULED")
    assert_reserved_capacity(fx.read_site(api, coordinator, site_id), 2)
