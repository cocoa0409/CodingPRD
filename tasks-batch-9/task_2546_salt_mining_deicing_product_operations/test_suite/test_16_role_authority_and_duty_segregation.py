"""
Operator identity and role authority on the Salt Deicing Operations API (PRD §2.1,
§2.6 stages 1-4 and the §4 authorization table).

Covers the seven recognized roles each writing the rows they own, the refusal of one
role on another role's exclusive operation, the missing-identity refusal, the
entity-backed `DepotManager` ownership rule in both its refusing and its permitting
direction, and the two segregation-of-duties comparands.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_DEPOT_NOT_OWNED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.constants import (
    ACTION_CITE,
    CITED,
    COMPLIANT,
    CONTRACT_DRAFT,
    DECISION_PASS,
    DEPOT_CLOSED,
    DEPOT_OPEN,
    DEPOT_SURGE,
    FINDING_PASS,
    HOIST_AVAILABLE,
    LOT_AVAILABLE,
    MODE_TRUCK,
    PANEL_PRODUCING,
    QC_PASSED,
    QC_PENDING,
    RUN_HOISTED,
    RUN_SCHEDULED,
    SHIPMENT_LOADED,
    SHIPMENT_RECEIVED,
)
from test_helpers.test_users import (
    COMPLIANCE,
    COMPLIANCE_AS_INSPECTOR,
    CONTRACT_ADMIN,
    GROUND_CONTROL,
    GROUND_CONTROL_USER_ID,
    LAB_LEAD,
    LAB_LEAD_USER_ID,
    LAB_TECH,
    LAB_TECH_USER_ID,
    LOGISTICS,
    LOGISTICS_USER_ID,
    MINE_PLANNER,
    MISSING_USER_ID,
    make_depot_manager_headers,
)

# The standing baseline used throughout this module: a 24,000 t/day mine whose
# 100,000 t panel at 50 % extraction, 96.00 % NaCl and 2.00 % insolubles carries a
# recoverable reserve of 50,000.00 t (PRD §3.2), a 1,000 t run over a 24-hour hoist
# window, a 5,000 t covered depot, and a COARSE HIGHWAY_DEICING batch of 1,000 input
# tons at 0.00 % moisture whose yield is 940.00 t at 96.500 % NaCl (PRD §3.5).
_MINE = {"name": "Retsof Salt Mine", "state_code": "NY", "rated_hoist_tons_per_day": 24000}
_PANEL = {
    "panel_code": "P-1",
    "gross_tons_in_place": 100000,
    "extraction_ratio_pct": 50,
    "grade_pct_nacl": 96.00,
    "insolubles_pct": 2.00,
}
_RUN = {
    "planned_tons": 1000,
    "hoist_window_start": "2026-08-02T00:00:00Z",
    "hoist_window_end": "2026-08-03T00:00:00Z",
}
_DEPOT = {
    "name": "Syracuse Depot",
    "state_code": "NY",
    "covered_capacity_tons": 5000,
    "open_pad_capacity_tons": 5000,
    "loadout_rate_tons_per_hour": 500,
    "outbound_freight_rate_per_ton": 12.500,
}
_BATCH = {
    "anticaking_ppm": 20.00,
    "corrosion_inhibitor_pct": 0.50,
    "input_tons": 1000,
    "moisture_pct": 0.00,
}


def _hoisted_world(api):
    """Mine, PRODUCING panel and a HOISTED 1,000 t run on the baseline geometry."""
    return fx.hoisted_run(
        api,
        mine_kwargs=dict(_MINE),
        panel_kwargs=dict(_PANEL),
        hoisted_tons=1000,
        **_RUN,
    )


def _lot_world(api):
    """The baseline chain through to the 940.00 t covered lot at Syracuse Depot."""
    return fx.lot_at_depot(
        api,
        mine_kwargs=dict(_MINE),
        panel_kwargs=dict(_PANEL),
        depot_kwargs=dict(_DEPOT),
        run_kwargs=dict(_RUN),
        hoisted_tons=1000,
        **_BATCH,
    )


def test_mine_planner_and_ground_control_engineer_each_write_their_own_rows(api):
    """
    A `MinePlanner` registers the mine, lays out the panel, walks it into production
    and schedules and hoists a run, and a `GroundControlEngineer` appends the
    inspection record that carries its own identity as the inspector.
    "Where it names roles, only those roles may call it; any other role is refused
    with `ERR_UNAUTHORIZED`, and role authorization is checked before the resource is
    looked up, per §2.6."

    Design: Corner/rbac/each_role_can_perform_its_own_exclusive_write
    """
    mine = validate_success(api.create_mine(f.mine_payload(**_MINE), MINE_PLANNER), 201)
    panel = validate_success(
        api.create_panel(f.panel_payload(mine["id"], **_PANEL), MINE_PLANNER), 201
    )

    validate_success(api.develop_panel(panel["id"], MINE_PLANNER), 200)
    producing = validate_success(api.start_production(panel["id"], MINE_PLANNER), 200)
    assert producing["status"] == PANEL_PRODUCING

    mine_v = fx.mine_version(api, mine["id"])
    run = validate_success(
        api.create_run(f.run_payload(mine["id"], panel["id"], mine_v, **_RUN), MINE_PLANNER),
        201,
    )
    assert run["status"] == RUN_SCHEDULED

    hoisted = validate_success(
        api.hoist_run(run["id"], f.hoist_payload(1000), MINE_PLANNER), 200
    )
    assert hoisted["status"] == RUN_HOISTED

    inspection = validate_success(
        api.create_inspection(
            f.inspection_payload(
                panel["id"],
                FINDING_PASS,
                roof_span_ft=40,
                convergence_rate_in_per_day=0.010,
            ),
            GROUND_CONTROL,
        ),
        201,
    )
    assert inspection["finding"] == FINDING_PASS
    assert inspection["inspector_user_id"] == GROUND_CONTROL_USER_ID


def test_logistics_planner_quality_lab_and_contract_administrator_each_write_their_own_rows(
    api,
):
    """
    A `LogisticsPlanner` opens the depot, a `QualityLab` operator opens the treatment
    batch against the hoisted run and is recorded as its creator, and a
    `ContractAdministrator` files the season forecast and drafts the bid.
    "The server stamps `created_by_user_id` with the creating `X-User-ID` — the
    comparand for the segregation-of-duties rule at stage 3 of §2.6 — and opens the
    batch with `qc_state` at `PENDING`, `rework_count` at 0, `qc_decided_by_user_id`
    null, and `version` at 1."

    Design: Corner/rbac/each_role_can_perform_its_own_exclusive_write
    """
    world = _hoisted_world(api)

    depot = validate_success(api.create_depot(f.depot_payload(**_DEPOT), LOGISTICS), 201)
    assert depot["depot_state"] == DEPOT_OPEN

    batch = validate_success(
        api.create_batch(
            f.batch_payload(world["run"]["id"], depot["id"], **_BATCH), LAB_TECH
        ),
        201,
    )
    assert batch["created_by_user_id"] == LAB_TECH_USER_ID
    assert batch["qc_state"] == QC_PENDING

    forecast = validate_success(
        api.create_forecast(
            f.forecast_payload(season_code="2026-27", region_code="NY-CENTRAL"),
            CONTRACT_ADMIN,
        ),
        201,
    )
    contract = validate_success(
        api.create_contract(
            f.contract_payload(
                forecast["id"],
                committed_tons=1000,
                guaranteed_price_per_ton=80.00,
                max_take_pct=110,
                failure_to_supply_penalty_per_ton=30.00,
                price_guarantee_cap_pct=10,
            ),
            CONTRACT_ADMIN,
        ),
        201,
    )
    assert contract["status"] == CONTRACT_DRAFT


def test_compliance_officer_cites_the_mine_and_the_depot_manager_sets_its_own_posture(api):
    """
    The `ComplianceOfficer` owns the compliance dimension of the mine, and the
    `DepotManager` — whose identity is the depot itself — sets the storm posture of
    that depot and is recorded as the operator who set it.
    "A `DepotManager` or a `LogisticsPlanner` sets it explicitly by naming the target
    `depot_state` and optionally a `reason`; the value named must differ from the value
    currently held, and the manual call stamps `storm_state_set_by_user_id` with the
    caller's `X-User-ID`."

    Design: Corner/rbac/each_role_can_perform_its_own_exclusive_write
    """
    world = _hoisted_world(api)
    depot = fx.create_depot(api, **_DEPOT)

    inspection = fx.file_inspection(
        api, world["panel"]["id"], FINDING_PASS, roof_span_ft=40
    )
    cited = validate_success(
        api.compliance_action(
            world["mine"]["id"],
            f.compliance_action_payload(
                ACTION_CITE,
                inspection_id=inspection["id"],
                note="MSHA 104(a) roof control citation",
            ),
            COMPLIANCE,
        ),
        200,
    )
    assert cited["compliance_state"] == CITED

    surged = validate_success(
        api.set_posture(
            depot["id"],
            f.posture_payload(DEPOT_SURGE, reason="lake effect band forecast"),
            make_depot_manager_headers(depot["id"]),
        ),
        200,
    )
    assert surged["depot_state"] == DEPOT_SURGE
    assert surged["storm_state_set_by_user_id"] == depot["id"]


def test_logistics_planner_cannot_schedule_a_production_run(api):
    """
    A `LogisticsPlanner` sends a completely valid production-run body against a mine
    with a PRODUCING panel and is still refused, and a `MinePlanner` aiming a batch at
    identifiers that do not exist is refused on the role check rather than on the
    missing references — so nothing is scheduled and the mine's open tonnage stays 0.
    "If the headers are well-formed but the declared role is not among the roles
    authorized for the endpoint being called (see the table in §4), the request is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/logistics_planner_cannot_create_a_production_run_returns_unauthorized
    """
    world = fx.mine_with_producing_panel(
        api, mine_kwargs=dict(_MINE), panel_kwargs=dict(_PANEL)
    )
    mine_before = fx.refresh_mine(api, world["mine"]["id"])
    mine_v = int(mine_before["version"])

    refused = api.create_run(
        f.run_payload(world["mine"]["id"], world["panel"]["id"], mine_v, **_RUN),
        LOGISTICS,
    )
    validate_error(refused, ERR_UNAUTHORIZED, 403)

    # "role authorization is checked before the resource is looked up": the batch body
    # names a run and a depot that do not exist, and the role check still answers first.
    unknown_run = "00000000-0000-0000-0000-0000000000b1"
    unknown_depot = "00000000-0000-0000-0000-0000000000b2"
    validate_error(
        api.create_batch(
            f.batch_payload(unknown_run, unknown_depot, **_BATCH), MINE_PLANNER
        ),
        ERR_UNAUTHORIZED,
        403,
    )

    mine_after = fx.refresh_mine(api, world["mine"]["id"])
    assertions.assert_version_unchanged(mine_after, mine_before)
    assertions.assert_tons(
        mine_after["scheduled_hoist_tons_open"], 0, "scheduled_hoist_tons_open"
    )
    _rows, meta = validate_paginated(
        api.list_runs(MINE_PLANNER, {"mine_id": world["mine"]["id"]})
    )
    assertions.assert_page_meta(meta, total_count=0)


def test_mine_registration_without_a_user_id_header_is_unauthenticated(api):
    """
    A mine registration that declares a legitimate `MinePlanner` role but carries no
    `X-User-ID` is refused with 401 and writes nothing; the identical body with both
    headers present is accepted, which isolates the missing identity as the only cause.
    "If either header is absent or empty, or if `X-User-Role` is not exactly one of the
    seven role names below, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/request_without_a_user_id_header_returns_unauthenticated
    """
    payload = f.mine_payload(**_MINE)

    validate_error(api.create_mine(payload, MISSING_USER_ID), ERR_UNAUTHENTICATED, 401)

    _rows, meta = validate_paginated(api.list_mines(MINE_PLANNER))
    assertions.assert_page_meta(meta, total_count=0)

    mine = validate_success(api.create_mine(payload, MINE_PLANNER), 201)
    assert mine["hoist_state"] == HOIST_AVAILABLE

    rows, meta = validate_paginated(api.list_mines(MINE_PLANNER))
    assertions.assert_page_meta(meta, total_count=1)
    assert rows[0]["id"] == mine["id"]


def test_depot_manager_cannot_set_the_posture_of_a_sibling_depot(api):
    """
    The manager of the Syracuse depot is refused when it aims a posture change at the
    Rochester depot, succeeds on its own depot, and the opaque-identity
    `LogisticsPlanner` may post posture on either depot — so the refusal is an
    ownership check, not a blanket role restriction.
    "Any of these attempted against another depot is rejected with
    `ERR_DEPOT_NOT_OWNED` (HTTP 403)."

    Design: Corner/rbac/depot_manager_cannot_set_posture_on_another_depot_returns_depot_not_owned
    """
    depot_a = fx.create_depot(api, **_DEPOT)
    depot_b = fx.create_depot(
        api,
        name="Rochester Depot",
        state_code="NY",
        covered_capacity_tons=5000,
        open_pad_capacity_tons=5000,
        loadout_rate_tons_per_hour=400,
        outbound_freight_rate_per_ton=8.000,
    )

    validate_error(
        api.set_posture(
            depot_b["id"],
            f.posture_payload(DEPOT_CLOSED, reason="not my depot"),
            make_depot_manager_headers(depot_a["id"]),
        ),
        ERR_DEPOT_NOT_OWNED,
        403,
    )
    untouched = fx.refresh_depot(api, depot_b["id"])
    assert untouched["depot_state"] == DEPOT_OPEN
    assertions.assert_version_unchanged(untouched, depot_b)
    assert untouched["version"] == 1

    own = validate_success(
        api.set_posture(
            depot_a["id"],
            f.posture_payload(DEPOT_CLOSED, reason="conveyor rebuild at my own depot"),
            make_depot_manager_headers(depot_a["id"]),
        ),
        200,
    )
    assert own["depot_state"] == DEPOT_CLOSED
    assertions.assert_version_bumped(own, depot_a)
    assert own["storm_state_set_by_user_id"] == depot_a["id"]

    other = validate_success(
        api.set_posture(
            depot_b["id"],
            f.posture_payload(DEPOT_SURGE, reason="network-wide storm staging"),
            LOGISTICS,
        ),
        200,
    )
    assert other["depot_state"] == DEPOT_SURGE
    assert other["storm_state_set_by_user_id"] == LOGISTICS_USER_ID


def test_depot_manager_loads_out_of_its_own_depot_and_receives_into_its_own_depot(api):
    """
    A 400 t truck movement between two depots is loaded by the manager of the origin
    depot and received by the manager of the destination depot, so the ownership check
    is made against `origin_depot_id` on the load and against `destination_depot_id` on
    the receipt; the tonnage leaves the origin pile and lands as a new lot.
    "Receipt advances `LOADED → RECEIVED`, terminal, and is performed by the destination
    depot's own `DepotManager` — whose `X-User-ID` must equal the
    `destination_depot_id` — or by a `LogisticsPlanner`."

    Design: Corner/rbac/depot_manager_loads_the_shipment_leaving_its_own_depot
    """
    world = _lot_world(api)
    depot_a = world["depot"]
    lot = world["lot"]
    assertions.assert_lot_tonnage(lot, on_hand=940.00, reserved=0, available=940.00)

    depot_b = fx.create_depot(
        api,
        name="Rochester Depot",
        state_code="NY",
        covered_capacity_tons=5000,
        open_pad_capacity_tons=5000,
        loadout_rate_tons_per_hour=400,
        outbound_freight_rate_per_ton=8.000,
    )
    shipment = fx.create_shipment(
        api,
        lot["id"],
        depot_a["id"],
        depot_b["id"],
        400,
        mode=MODE_TRUCK,
        load_window_start="2026-08-05T08:00:00Z",
        load_window_end="2026-08-05T09:00:00Z",
    )

    loaded = validate_success(
        api.load_shipment(shipment["id"], make_depot_manager_headers(depot_a["id"])), 200
    )
    assert loaded["status"] == SHIPMENT_LOADED

    received = validate_success(
        api.receive_shipment(shipment["id"], make_depot_manager_headers(depot_b["id"])),
        200,
    )
    assert received["status"] == SHIPMENT_RECEIVED
    assert received["received_lot_id"] is not None

    source = fx.refresh_lot(api, lot["id"])
    assert source["lot_state"] == LOT_AVAILABLE
    assertions.assert_lot_tonnage(source, on_hand=540.00, reserved=0, available=540.00)

    minted = get_success_data(api.get_lot(received["received_lot_id"], LOGISTICS))
    assert minted["depot_id"] == depot_b["id"]
    assertions.assert_lot_tonnage(minted, on_hand=400.00, reserved=0, available=400.00)

    assertions.assert_tons(
        fx.refresh_depot(api, depot_a["id"])["covered_stored_tons"],
        540.00,
        "covered_stored_tons",
    )
    assertions.assert_tons(
        fx.refresh_depot(api, depot_b["id"])["covered_stored_tons"],
        400.00,
        "covered_stored_tons",
    )


def test_the_lab_operator_who_opened_a_batch_cannot_decide_its_quality_control(api):
    """
    The `QualityLab` role is sufficient but the identity is not: the operator recorded
    as the batch's creator is refused when it tries to pass the batch, no tonnage is
    minted, and a second lab operator then passes the identical batch.
    "The `X-User-ID` deciding quality control on a treatment batch must differ from the
    `X-User-ID` recorded as that batch's creator, and the `X-User-ID` issuing a mine
    compliance action must differ from the `X-User-ID` recorded as the inspector on the
    ground-control inspection cited as evidence for that action."

    Design: Corner/rbac/same_lab_user_cannot_create_and_pass_the_same_batch
    """
    world = _hoisted_world(api)
    depot = fx.create_depot(api, **_DEPOT)
    batch = fx.create_batch(
        api, world["run"]["id"], depot["id"], headers=LAB_TECH, **_BATCH
    )
    assert batch["created_by_user_id"] == LAB_TECH_USER_ID

    validate_error(
        api.qc_decision(batch["id"], f.qc_decision_payload(DECISION_PASS), LAB_TECH),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )

    still_pending = fx.refresh_batch(api, batch["id"])
    assert still_pending["qc_state"] == QC_PENDING
    assertions.assert_version_unchanged(still_pending, batch)
    assert still_pending["version"] == 1
    _rows, meta = validate_paginated(
        api.list_lots(LOGISTICS, {"treatment_batch_id": batch["id"]})
    )
    assertions.assert_page_meta(meta, total_count=0)
    assertions.assert_tons(
        fx.refresh_depot(api, depot["id"])["covered_stored_tons"], 0, "covered_stored_tons"
    )

    passed = validate_success(
        api.qc_decision(batch["id"], f.qc_decision_payload(DECISION_PASS), LAB_LEAD), 200
    )
    assert passed["qc_state"] == QC_PASSED
    assert passed["qc_decided_by_user_id"] == LAB_LEAD_USER_ID
    assertions.assert_tons(
        fx.lot_of_batch(api, batch["id"])["tons_on_hand"], 940.00, "tons_on_hand"
    )


def test_compliance_officer_cannot_cite_the_mine_on_its_own_inspection(api):
    """
    The evidence author and the enforcement author must differ: an operator that filed
    the ground-control inspection is refused when it cites that same inspection as a
    compliance officer, and an independent officer then records the citation, which
    reprices the mine's effective hoisting capacity to 80 percent of nameplate.
    "Either collision is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/compliance_officer_cannot_cite_on_its_own_inspection
    """
    world = fx.mine_with_producing_panel(
        api, mine_kwargs=dict(_MINE), panel_kwargs=dict(_PANEL)
    )
    inspection = fx.file_inspection(
        api, world["panel"]["id"], FINDING_PASS, headers=GROUND_CONTROL, roof_span_ft=40
    )
    assert inspection["inspector_user_id"] == GROUND_CONTROL_USER_ID

    mine_before = fx.refresh_mine(api, world["mine"]["id"])
    validate_error(
        api.compliance_action(
            world["mine"]["id"],
            f.compliance_action_payload(
                ACTION_CITE, inspection_id=inspection["id"], note="self-citation attempt"
            ),
            COMPLIANCE_AS_INSPECTOR,
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    unchanged = fx.refresh_mine(api, world["mine"]["id"])
    assert unchanged["compliance_state"] == COMPLIANT
    assertions.assert_version_unchanged(unchanged, mine_before)

    cited = validate_success(
        api.compliance_action(
            world["mine"]["id"],
            f.compliance_action_payload(
                ACTION_CITE,
                inspection_id=inspection["id"],
                note="MSHA 104(a) citation on a colleague's inspection",
            ),
            COMPLIANCE,
        ),
        200,
    )
    assert cited["compliance_state"] == CITED
    assert cited["last_compliance_action_at"] == "2026-08-01T00:00:00.000Z"

    assertions.assert_hoist_capacity_view(
        fx.hoist_capacity(api, world["mine"]["id"]),
        rated=24000,
        hoist_factor=1.00,
        compliance_factor=0.80,
        effective=19200.00,
        scheduled_open=0,
        scheduled_run_count=0,
    )
    assert fx.refresh_panel(api, world["panel"]["id"])["status"] == PANEL_PRODUCING
