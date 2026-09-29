"""Optimistic concurrency and derived-field reconciliation.

This file covers the two version-guarded writes of PRD §2.11 — structural
analysis creation against the tower `version` and cost-share reallocation
against the modification project `version` — together with the derived rollups
that have to be recomputed rather than accumulated: the tower `version` and
capacity picture of PRD §2.7 and §3.7, and the application `total_load_units`
of PRD §3.4. It also pins the immediacy PRD §3.7 promises, namely that the
response to a write already reflects the reconciliation it triggered.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_STALE_PROJECT_VERSION,
    ERR_STALE_TOWER_VERSION,
)
from test_helpers.assertions import (
    assert_amendment_axes,
    assert_analysis_outcome,
    assert_capacity_summary,
    assert_cents,
    assert_common_resource_fields,
    assert_load_units,
    assert_tower_capacity,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ENGINEER_HEADERS,
    make_tenant_headers,
)

# ─── Shared worlds ───────────────────────────────────────────────────────────

_ANTENNA_500_UNITS = {
    "equipment_type": "ANTENNA",
    "model_code": "OC-100",
    "quantity": 5,
    "unit_weight_lbs": 100,
    "wind_area_sqft": 0,
    "mount_elevation_ft": 80,
}


def _application_in_review(
    api,
    *,
    tower_overrides,
    tenant_overrides,
    application_overrides,
    line_overrides,
):
    """One carrier's application sitting in UNDER_STRUCTURAL_REVIEW.

    The tower posture is OPEN, so PRD §3.4 branches the submission straight into
    review, which is the only state from which PRD §3.5 admits an analysis.
    """
    tower = fixtures.new_tower(api, **tower_overrides)
    carrier = fixtures.carrier_with_active_lease(
        api,
        tenant_overrides=tenant_overrides,
        mla_overrides={
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
    )
    tenant_id = carrier["tenant"]["id"]
    application = fixtures.new_application(
        api, tower["id"], carrier["mla"]["id"], tenant_id, **application_overrides
    )
    line = fixtures.add_equipment_line(api, application["id"], tenant_id, **line_overrides)
    submitted = fixtures.submit_application(api, application["id"], tenant_id)
    assert submitted["status"] == "UNDER_STRUCTURAL_REVIEW", (
        f"an OPEN tower admits the submission into review, got {submitted['status']}"
    )
    return {
        "tower": tower,
        "tenant": carrier["tenant"],
        "tenant_headers": make_tenant_headers(tenant_id),
        "mla": carrier["mla"],
        "application": submitted,
        "line": line,
    }


def _draft_application_with_no_lines(api):
    """A DRAFT application on an empty tower, ready for equipment lines."""
    tower = fixtures.new_tower(
        api,
        site_name="Reconcile Ridge",
        structure_type="MONOPOLE",
        rated_capacity_load_units=9000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=300,
        ground_space_total_sqft=9000,
    )
    carrier = fixtures.carrier_with_active_lease(
        api,
        tenant_overrides={"legal_name": "Reconcile Radio", "carrier_code": "RCN"},
        mla_overrides={
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
    )
    tenant_id = carrier["tenant"]["id"]
    application = fixtures.new_application(
        api,
        tower["id"],
        carrier["mla"]["id"],
        tenant_id,
        requested_elevation_bottom_ft=80,
        requested_elevation_top_ft=240,
        requested_ground_space_sqft=300,
    )
    assert_load_units(application["total_load_units"], 0.0, "total_load_units")
    return {
        "tower": tower,
        "tenant_id": tenant_id,
        "tenant_headers": make_tenant_headers(tenant_id),
        "application": application,
    }


# ─── Optimistic concurrency on the tower version (PRD §2.11) ─────────────────


def test_stale_expected_tower_version_on_analysis_rejected(api):
    """PRD §2.11: "If it does not equal the tower's current `version`, the
    request is rejected with `ERR_STALE_TOWER_VERSION` (412)."

    The first analysis is itself a tower write — PRD §3.5: "Creating an analysis
    sets its `status` to `ISSUED`, records `engineer_user_id` as the acting
    operator identifier and `issued_at` as the current logical clock instant,
    sets every earlier analysis of the same application whose `status` is
    `ISSUED` or `QUOTED` to `SUPERSEDED`, and increments the tower's `version`
    by one." — so replaying the version the engineer captured before it is
    stale, while re-reading the tower and using the fresh version succeeds and
    supersedes the earlier analysis.

    Design: Corner/cross_cutting_complexity_layers/stale_expected_tower_version_on_analysis_rejected
    """
    world = _application_in_review(
        api,
        tower_overrides={
            "site_name": "Occ Guard Gap",
            "structure_type": "MONOPOLE",
            "rated_capacity_load_units": 9000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
        },
        tenant_overrides={"legal_name": "Occ Guard Radio", "carrier_code": "OCC"},
        application_overrides={
            "requested_elevation_bottom_ft": 100,
            "requested_elevation_top_ft": 140,
            "requested_ground_space_sqft": 300,
        },
        line_overrides=_ANTENNA_500_UNITS,
    )
    tower_id = world["tower"]["id"]
    app_id = world["application"]["id"]

    captured_version = fixtures.read_tower_version(api, tower_id)
    first = fixtures.run_analysis(
        api, app_id, tower_id, "PRELIMINARY", expected_tower_version=captured_version
    )
    current_version = fixtures.read_tower_version(api, tower_id)
    assert current_version == captured_version + 1, (
        "creating an analysis increments the tower version by one, "
        f"got {current_version} from {captured_version}"
    )

    stale = api.create_structural_analysis(
        factories.structural_analysis_payload(app_id, captured_version, "DETAILED"),
        ENGINEER_HEADERS,
    )
    validate_error(stale, ERR_STALE_TOWER_VERSION, 412)

    # The rejected write left the tower and the analysis history untouched.
    assert fixtures.read_tower_version(api, tower_id) == current_version, (
        "a rejected analysis creation must not move the tower version"
    )
    _rows, meta = validate_paginated(
        api.list_application_structural_analyses(app_id, {"limit": 100}, ENGINEER_HEADERS)
    )
    assert meta["total_count"] == 1, "the rejected request must not mint an analysis"
    assert_analysis_outcome(
        fixtures.read_analysis(api, app_id, first["id"]), status="ISSUED"
    )

    fresh = validate_success(
        api.create_structural_analysis(
            factories.structural_analysis_payload(app_id, current_version, "DETAILED"),
            ENGINEER_HEADERS,
        ),
        201,
    )
    assert_common_resource_fields(fresh)
    assert_analysis_outcome(
        fresh,
        variant="DETAILED",
        status="ISSUED",
        included_load_units=500.0,
        projected_loading_pct=5.556,
        result="PASS",
    )
    assert_analysis_outcome(
        fixtures.read_analysis(api, app_id, first["id"]), status="SUPERSEDED"
    )
    _rows, meta = validate_paginated(
        api.list_application_structural_analyses(app_id, {"limit": 100}, ENGINEER_HEADERS)
    )
    assert meta["total_count"] == 2, "the application now carries both analyses"


# ─── Optimistic concurrency on the project version (PRD §2.11) ──────────────


def test_stale_expected_project_version_on_cost_share_reallocation_rejected(api):
    """PRD §2.11: "If it does not equal the project's current `version`, the
    request is rejected with `ERR_STALE_PROJECT_VERSION` (412)."

    PRD §3.6 makes the first reallocation a project write — "Reallocating moves
    each affected share `PENDING → VOIDED` or `ACCEPTED → VOIDED`, updates
    `allocation_basis`, mints a fresh set of `PENDING` shares from a freshly
    resolved beneficiary set, restores `allocated_cents` to `total_cost_cents`,
    and increments the project's `version` by one." — so replaying the version
    read before it is stale and the EQUAL_SHARE allocation stands.

    Design: Corner/cross_cutting_complexity_layers/stale_expected_modification_project_version_on_reallocate_rejected
    """
    world = _application_in_review(
        api,
        tower_overrides={
            "site_name": "Occ Project Pass",
            "structure_type": "SELF_SUPPORT",
            "rated_capacity_load_units": 1000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
            "baseline_reserved_load_units": 900,
        },
        tenant_overrides={"legal_name": "Occ Project Cellular", "carrier_code": "OCP"},
        application_overrides={
            "requested_elevation_bottom_ft": 100,
            "requested_elevation_top_ft": 140,
            "requested_ground_space_sqft": 300,
        },
        line_overrides={
            "equipment_type": "ANTENNA",
            "model_code": "OP-60",
            "quantity": 1,
            "unit_weight_lbs": 60,
            "wind_area_sqft": 0,
            "mount_elevation_ft": 80,
        },
    )
    tower_id = world["tower"]["id"]
    app_id = world["application"]["id"]

    # 900 baseline plus 60 subject load over a 1000 rating is 96.000%, so the
    # analysis requires modification and can carry a quotation.
    analysis = fixtures.run_analysis(api, app_id, tower_id, "PRELIMINARY")
    assert_analysis_outcome(
        analysis,
        included_load_units=960.0,
        projected_loading_pct=96.000,
        result="MODIFICATION_REQUIRED",
    )
    fixtures.quote_analysis(api, analysis["id"], 1000000)
    project = fixtures.propose_project(
        api,
        tower_id,
        analysis["id"],
        construction_window_start_date="2026-09-01",
        construction_window_end_date="2026-10-31",
        allocation_basis="PRO_RATA_LOAD",
    )
    allocated = fixtures.allocate_shares(api, project["id"])
    assert_cents(allocated["allocated_cents"], 1120000, "allocated_cents")
    captured_version = allocated["version"]

    reallocated = validate_success(
        api.reallocate_cost_shares(
            project["id"],
            factories.reallocate_payload(captured_version, "EQUAL_SHARE"),
            ENGINEER_HEADERS,
        ),
        200,
    )
    assert reallocated["allocation_basis"] == "EQUAL_SHARE"
    assert reallocated["status"] == "COST_ALLOCATED"
    assert_cents(reallocated["allocated_cents"], 1120000, "allocated_cents")
    current_version = reallocated["version"]
    assert current_version == captured_version + 1, (
        f"reallocation increments the project version, got {current_version} "
        f"from {captured_version}"
    )

    replayed = api.reallocate_cost_shares(
        project["id"],
        factories.reallocate_payload(captured_version, "PRO_RATA_LOAD"),
        ENGINEER_HEADERS,
    )
    validate_error(replayed, ERR_STALE_PROJECT_VERSION, 412)

    settled = fixtures.read_project(api, project["id"])
    assert settled["allocation_basis"] == "EQUAL_SHARE", (
        "the rejected reallocation must not change the allocation basis"
    )
    assert settled["status"] == "COST_ALLOCATED"
    assert_cents(settled["allocated_cents"], 1120000, "allocated_cents")
    assert settled["version"] == current_version, (
        "a rejected reallocation must not move the project version"
    )

    _pending, pending_meta = validate_paginated(
        api.list_cost_shares(
            {"modification_project_id": project["id"], "status": "PENDING", "limit": 100},
            ADMIN_HEADERS,
        )
    )
    assert pending_meta["total_count"] == 1, "exactly one fresh PENDING share stands"
    _voided, voided_meta = validate_paginated(
        api.list_cost_shares(
            {"modification_project_id": project["id"], "status": "VOIDED", "limit": 100},
            ADMIN_HEADERS,
        )
    )
    assert voided_meta["total_count"] == 1, "the superseded share was voided exactly once"


# ─── The tower version counter (PRD §2.4, §3.2, §3.5, §3.7) ─────────────────


def test_ground_lease_creation_and_analysis_each_raise_tower_version(api):
    """PRD §3.2: "Creating a lease also recomputes the tower's
    `capacity_posture` and increments the tower's `version` by one."

    PRD §3.1 starts the counter — the tower's `version` is initialised to 1 —
    and PRD §3.5 declares the same side effect for analysis creation: "Creating
    an analysis sets its `status` to `ISSUED`, records `engineer_user_id` as the
    acting operator identifier and `issued_at` as the current logical clock
    instant, sets every earlier analysis of the same application whose `status`
    is `ISSUED` or `QUOTED` to `SUPERSEDED`, and increments the tower's
    `version` by one."

    Design: Corner/cross_cutting_complexity_layers/tower_version_increments_on_every_declared_write
    """
    tower = fixtures.new_tower(
        api,
        site_name="Version Rise Ridge",
        structure_type="MONOPOLE",
        rated_capacity_load_units=9000,
        min_colocation_elevation_ft=50,
        max_elevation_ft=300,
        ground_space_total_sqft=9000,
    )
    tower_id = tower["id"]
    registered = validate_success(api.get_tower(tower_id, ADMIN_HEADERS))
    assert_common_resource_fields(registered)
    assert registered["version"] == 1, "a freshly registered tower is at version 1"

    landlord = fixtures.new_landlord(
        api,
        legal_name="Version Ridge Land",
        remit_contact_email="ap@versionridge.example",
        w9_on_file=True,
    )
    fixtures.new_ground_lease(
        api,
        tower_id,
        landlord["id"],
        base_monthly_rent_cents=300000,
        escalator_pct=2.0,
        commencement_date="2020-06-01",
        term_end_date="2031-05-31",
        renewal_option_count=1,
        renewal_term_years=5,
        buyout_price_cents=9000000,
    )
    after_lease = validate_success(api.get_tower(tower_id, ADMIN_HEADERS))
    assert after_lease["version"] == 2, (
        f"the ground lease takes the tower to version 2, got {after_lease['version']}"
    )
    assert_tower_capacity(after_lease, capacity_posture="OPEN", reserved_load_units=0.0)

    carrier = fixtures.carrier_with_active_lease(
        api,
        tenant_overrides={"legal_name": "Version Rise Radio", "carrier_code": "VRS"},
        mla_overrides={
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
    )
    tenant_id = carrier["tenant"]["id"]
    application = fixtures.new_application(
        api,
        tower_id,
        carrier["mla"]["id"],
        tenant_id,
        requested_elevation_bottom_ft=100,
        requested_elevation_top_ft=140,
        requested_ground_space_sqft=300,
    )
    fixtures.add_equipment_line(
        api,
        application["id"],
        tenant_id,
        equipment_type="ANTENNA",
        model_code="VR-100",
        quantity=5,
        unit_weight_lbs=100,
        wind_area_sqft=0,
        mount_elevation_ft=80,
    )
    fixtures.submit_application(api, application["id"], tenant_id)

    before_analysis = fixtures.read_tower_version(api, tower_id)
    fixtures.run_analysis(
        api, application["id"], tower_id, "PRELIMINARY", expected_tower_version=before_analysis
    )
    after_analysis = validate_success(api.get_tower(tower_id, ADMIN_HEADERS))
    assert after_analysis["version"] == before_analysis + 1, (
        "the analysis takes the tower one version further, got "
        f"{after_analysis['version']} from {before_analysis}"
    )


def test_amendment_execution_raises_tower_version_and_reserved_load(api):
    """PRD §3.7: "The tower's `reserved_load_units`, `reserved_load_pct`,
    `reserved_ground_space_sqft`, `available_ground_space_sqft`,
    `occupied_elevation_bands` and `capacity_posture` are all recomputed, the
    master lease's `executed_amendment_count` is recomputed, and the tower's
    `version` is incremented by one."

    PRD §2.7 fixes the figure that lands: "`reserved_load_pct` is one hundred
    times `reserved_load_units` divided by `rated_capacity_load_units`, rounded
    half up to three decimal places."

    Design: Corner/cross_cutting_complexity_layers/tower_version_increments_on_every_declared_write
    """
    world = fixtures.build_colocation_chain(
        api,
        stage="PAPERED",
        tower_overrides={
            "site_name": "Version Rise Mesa",
            "structure_type": "MONOPOLE",
            "rated_capacity_load_units": 9000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
        },
        tenant_overrides={"legal_name": "Version Rise Radio", "carrier_code": "VRS"},
        mla_overrides={
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
        application_overrides={
            "requested_elevation_bottom_ft": 100,
            "requested_elevation_top_ft": 140,
            "requested_ground_space_sqft": 300,
        },
        lines=[
            {
                "equipment_type": "ANTENNA",
                "model_code": "VR-100",
                "quantity": 5,
                "unit_weight_lbs": 100,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 80,
            }
        ],
        amendment_overrides={"effective_date": "2026-08-01", "base_monthly_rent_cents": 200000},
    )
    tower_id = world["tower"]["id"]
    amendment = world["amendment"]
    assert_load_units(amendment["reserved_load_units"], 500.0, "reserved_load_units")

    before_execution = fixtures.read_tower_version(api, tower_id)
    executed = validate_success(
        api.execute_site_amendment(
            amendment["id"], factories.execute_payload(True), ADMIN_HEADERS
        ),
        200,
    )
    assert_amendment_axes(executed, execution_status="EXECUTED", billing_status="BILLING")

    after_execution = validate_success(api.get_tower(tower_id, ADMIN_HEADERS))
    assert after_execution["version"] == before_execution + 1, (
        "executing the amendment takes the tower one version further, got "
        f"{after_execution['version']} from {before_execution}"
    )
    assert_tower_capacity(
        after_execution,
        reserved_load_units=500.0,
        reserved_load_pct=5.556,
        reserved_ground_space_sqft=300,
        available_ground_space_sqft=8700,
        occupied_band_count=1,
        capacity_posture="OPEN",
    )


# ─── The application load rollup (PRD §3.4) ─────────────────────────────────


def test_application_total_load_rolls_up_each_added_equipment_line(api):
    """PRD §3.4: "A line's `load_units` is derived by first selecting an
    elevation multiplier from a strict three-tier ladder on
    `mount_elevation_ft`: below 100 feet the multiplier is 1.00; from 100 feet
    up to but not including 200 feet it is 1.25; at 200 feet and above it is
    1.50."

    The parent rollup follows from those per-line figures — PRD §3.4: "The
    application's `total_load_units` is the sum of the **already rounded**
    per-line figures, so each line is rounded to three decimals first and only
    then are the lines added together."

    Design: Corner/cross_cutting_complexity_layers/application_total_load_reconciles_after_line_add_and_delete
    """
    world = _draft_application_with_no_lines(api)
    app_id = world["application"]["id"]
    tenant_headers = world["tenant_headers"]

    first = validate_success(
        api.create_equipment_line(
            app_id,
            factories.equipment_line_payload(
                equipment_type="ANTENNA",
                model_code="RC-100",
                quantity=5,
                unit_weight_lbs=100,
                wind_area_sqft=0,
                mount_elevation_ft=80,
            ),
            tenant_headers,
        ),
        201,
    )
    assert_common_resource_fields(first)
    assert_load_units(first["load_units"], 500.0, "load_units")
    assert_load_units(
        fixtures.read_application(api, app_id)["total_load_units"], 500.0, "total_load_units"
    )

    second = validate_success(
        api.create_equipment_line(
            app_id,
            factories.equipment_line_payload(
                equipment_type="TMA",
                model_code="RC-50",
                quantity=1,
                unit_weight_lbs=50,
                wind_area_sqft=0,
                mount_elevation_ft=100,
            ),
            tenant_headers,
        ),
        201,
    )
    assert_load_units(second["load_units"], 62.5, "load_units")

    rolled_up = fixtures.read_application(api, app_id)
    assert_load_units(rolled_up["total_load_units"], 562.5, "total_load_units")
    assert rolled_up["status"] == "DRAFT"


def test_application_total_load_returns_to_surviving_lines_after_deletion(api):
    """PRD §3.4: "Deletion returns no body and immediately recomputes the
    application's `total_load_units` from the surviving lines; the sibling
    lines' own `load_units` are unchanged."

    Because the rollup is recomputed rather than accumulated, dropping the
    62.5-unit line restores 500.0 and adding a 75.0-unit line at 200 feet lands
    on 575.0 rather than on the append-only 637.5.

    Design: Corner/cross_cutting_complexity_layers/application_total_load_reconciles_after_line_add_and_delete
    """
    world = _draft_application_with_no_lines(api)
    app_id = world["application"]["id"]
    tenant_id = world["tenant_id"]
    tenant_headers = world["tenant_headers"]

    kept = fixtures.add_equipment_line(
        api,
        app_id,
        tenant_id,
        equipment_type="ANTENNA",
        model_code="RC-100",
        quantity=5,
        unit_weight_lbs=100,
        wind_area_sqft=0,
        mount_elevation_ft=80,
    )
    dropped = fixtures.add_equipment_line(
        api,
        app_id,
        tenant_id,
        equipment_type="TMA",
        model_code="RC-50",
        quantity=1,
        unit_weight_lbs=50,
        wind_area_sqft=0,
        mount_elevation_ft=100,
    )
    assert_load_units(
        fixtures.read_application(api, app_id)["total_load_units"], 562.5, "total_load_units"
    )

    deletion = api.delete_equipment_line(dropped["id"], tenant_headers)
    assert deletion.status_code == 204, (
        f"removing a line from a DRAFT application returns 204, got "
        f"{deletion.status_code}: {deletion.text}"
    )
    assert deletion.text == "", "the delete operation returns no response body"

    after_deletion = fixtures.read_application(api, app_id)
    assert_load_units(after_deletion["total_load_units"], 500.0, "total_load_units")
    assert_load_units(
        fixtures.read_equipment_line(api, kept["id"])["load_units"], 500.0, "load_units"
    )

    replacement = validate_success(
        api.create_equipment_line(
            app_id,
            factories.equipment_line_payload(
                equipment_type="TMA",
                model_code="RC-50H",
                quantity=1,
                unit_weight_lbs=50,
                wind_area_sqft=0,
                mount_elevation_ft=200,
            ),
            tenant_headers,
        ),
        201,
    )
    assert_load_units(replacement["load_units"], 75.0, "load_units")

    reconciled = fixtures.read_application(api, app_id)
    assert_load_units(reconciled["total_load_units"], 575.0, "total_load_units")
    assert reconciled["status"] == "DRAFT"

    # Nothing is standing on the structure yet, so the tower holds no load.
    assert_tower_capacity(
        fixtures.read_tower(api, world["tower"]["id"]),
        reserved_load_units=0.0,
        occupied_band_count=0,
    )


# ─── No lag between a write and the picture it reconciles (PRD §2.7, §3.7) ───


def test_execute_response_already_shows_reconciled_capacity(api):
    """PRD §3.7: "Reaching `EXECUTED` fires a broad set of effects inside the
    same request."

    PRD §2.7 names the trigger — "The reconciliation runs whenever a site
    amendment's `execution_status` changes, whenever a ground lease's `status`
    changes, whenever a modification project's `status` changes, and whenever
    `rated_capacity_load_units` changes." — so the execute response itself
    already carries the executed amendment's load and the capacity summary read
    immediately afterwards agrees with it, with no second write needed.

    Design: Corner/consistency_model/execute_response_already_shows_reconciled_counters
    """
    world = fixtures.build_colocation_chain(
        api,
        stage="PAPERED",
        tower_overrides={
            "site_name": "Immediate Mesa",
            "structure_type": "MONOPOLE",
            "rated_capacity_load_units": 9000,
            "min_colocation_elevation_ft": 50,
            "max_elevation_ft": 300,
            "ground_space_total_sqft": 9000,
        },
        landlord_overrides={
            "legal_name": "Immediate Mesa Land",
            "remit_contact_email": "ap@immediatemesa.example",
            "w9_on_file": True,
        },
        lease_overrides={
            "base_monthly_rent_cents": 300000,
            "escalator_pct": 2.0,
            "commencement_date": "2020-06-01",
            "term_end_date": "2031-05-31",
            "renewal_option_count": 1,
            "renewal_term_years": 5,
            "buyout_price_cents": 9000000,
        },
        tenant_overrides={"legal_name": "Immediate Mesa Radio", "carrier_code": "IMM"},
        mla_overrides={
            "base_monthly_rent_cents": 200000,
            "escalator_pct": 3.0,
            "initial_term_years": 10,
            "renewal_terms_count": 1,
            "expires_on": "2036-07-31",
        },
        application_overrides={
            "requested_elevation_bottom_ft": 100,
            "requested_elevation_top_ft": 140,
            "requested_ground_space_sqft": 300,
        },
        lines=[
            {
                "equipment_type": "ANTENNA",
                "model_code": "IM-100",
                "quantity": 5,
                "unit_weight_lbs": 100,
                "wind_area_sqft": 0,
                "mount_elevation_ft": 80,
            }
        ],
        amendment_overrides={"effective_date": "2026-08-01", "base_monthly_rent_cents": 200000},
    )
    tower_id = world["tower"]["id"]

    executed = validate_success(
        api.execute_site_amendment(
            world["amendment"]["id"], factories.execute_payload(True), ADMIN_HEADERS
        ),
        200,
    )
    assert_amendment_axes(executed, execution_status="EXECUTED", billing_status="BILLING")
    assert_load_units(executed["reserved_load_units"], 500.0, "reserved_load_units")

    summary = validate_success(api.get_capacity_summary(tower_id, ADMIN_HEADERS))
    assert_capacity_summary(
        summary,
        rated_capacity_load_units=9000,
        reserved_load_units=500.0,
        reserved_load_pct=5.556,
        available_ground_space_sqft=8700,
        occupied_band_count=1,
        open_review_count=0,
        capacity_posture="OPEN",
        capacity_hold_application_count=0,
    )
    assert summary["tower_id"] == tower_id
