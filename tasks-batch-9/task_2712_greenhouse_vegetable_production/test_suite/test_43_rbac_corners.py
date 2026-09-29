"""Role authority corners: exclusive operations, shared operations, segregation of
duties between the scout who saw the pest and the coordinator who signs off the
treatment, and the opaque identity of a quality inspector.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_four_decimal_places,
    assert_money,
    create_harvest_lot_payload,
    create_labor_task,
    create_scout_worker,
    create_worker,
    make_harvest_supervisor_headers,
    make_ipm_coordinator_headers,
    make_quality_inspector_headers,
    read_crop_cycle,
    read_lot,
    read_zone,
    request_release,
    set_clock,
    setup_graded_lot,
    setup_production_cycle,
    setup_scout_alert_zone,
    setup_transplanted_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)

GM = TEST_USERS["grower_manager_headers"]
IT = TEST_USERS["irrigation_tech_headers"]
AUDIT_INSPECTOR_USER_ID = "qc-audit-7"


def test_irrigation_tech_cannot_register_a_harvest_lot(api):
    """PRD §4: "The `Authorized Role(s)` column is exhaustive: any other role receives `ERR_UNAUTHORIZED` with a `403`."

    Design: Corner/rbac/irrigation_tech_cannot_register_a_harvest_lot
    """
    state = setup_production_cycle()
    payload = create_harvest_lot_payload(
        state["cycle"]["id"], harvest_date="2026-08-24", gross_weight_lbs=2000.00
    )

    response = api.create_harvest_lot(payload, IT)

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

    rows, meta = validate_paginated(api.list_harvest_lots(GM))
    assert meta["total_count"] == 0, (
        f"no lot may be registered by an unauthorised role, got {meta['total_count']}"
    )
    cycle = read_crop_cycle(state["cycle"]["id"])
    assert cycle["cumulative_harvested_lbs"] == 0.00, (
        "a rejected registration adds no pounds to the cycle, got "
        f"{cycle['cumulative_harvested_lbs']}"
    )


def test_the_scout_who_filed_the_observation_cannot_approve_its_release(api):
    """PRD §3.6: "The request must be in `REQUESTED`; the acting `X-User-ID` must differ from the justifying observation's `observed_by_worker_id`, or the approval is rejected with `ERR_SEGREGATION_OF_DUTIES` — the scout who found the pest may not sign off the treatment it justifies, and the role check earlier in the sequence does not catch this because both actors are legitimately IPM staff resolving to workers with `skill` `SCOUT`; and the acting worker must itself resolve to a worker with `skill` `SCOUT` or the approval is rejected with `ERR_WORKER_SKILL_MISMATCH`."

    Design: Corner/rbac/the_scout_who_filed_the_observation_cannot_approve_its_release
    """
    state = setup_scout_alert_zone(clock="2026-08-06T00:00:00Z")
    filer = state["scout"]
    coordinator = create_scout_worker(full_name="Tomas Reyn", hourly_rate_usd=26.00)
    assert state["observation"]["observed_by_worker_id"] == filer["id"], (
        "the observation must be attributed to the filing scout"
    )
    release = request_release(
        state["zone"]["id"], state["observation"]["id"], filer["id"]
    )

    # The filer wears the coordinator hat, which is not enough.
    response = api.approve_bio_control_release(
        release["id"], {}, make_ipm_coordinator_headers(filer["id"])
    )

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    # An independent coordinator may sign the same request off.
    approved = validate_success(
        api.approve_bio_control_release(
            release["id"], {}, make_ipm_coordinator_headers(coordinator["id"])
        ),
        200,
    )
    assert approved["status"] == "APPROVED", (
        f"an approved request sits in APPROVED, got {approved['status']}"
    )
    assert approved["approved_release_count"] == 6000, (
        "approved_release_count becomes planned_release_count when no revision was "
        f"supplied, got {approved['approved_release_count']}"
    )
    assert approved["decided_by_worker_id"] == coordinator["id"], (
        f"decided_by_worker_id records the coordinator, got {approved['decided_by_worker_id']}"
    )
    assert approved["revision_count"] == 0, (
        f"a first approval revises nothing, got {approved['revision_count']}"
    )


def test_grower_manager_starts_the_task_and_harvest_supervisor_completes_it(api):
    """PRD §2.1: "`HarvestSupervisor` registers picked lots and owns the grading dimension of a lot, and shares labor-task transitions with `GrowerManager`."

    Design: Corner/rbac/labor_task_transitions_are_shared_by_grower_manager_and_harvest_supervisor
    """
    state = setup_transplanted_cycle(clock="2026-08-06T00:00:00Z")
    worker = create_worker(
        full_name="Petra Lund", hourly_rate_usd=19.50, productivity_index=1.00
    )
    task = create_labor_task(
        state["zone"]["id"],
        state["cycle"]["id"],
        worker["id"],
        planned_units=4000,
        standard_units_per_hour=500,
    )
    assert_money(task["planned_cost_usd"], 156.00, "planned_cost_usd")

    set_clock("2026-08-07T07:00:00Z")
    started = validate_success(
        api.transition_labor_task(task["id"], {"to_status": "IN_PROGRESS"}, GM), 200
    )
    assert started["status"] == "IN_PROGRESS", (
        f"the head grower may start the work, got {started['status']}"
    )

    completed = validate_success(
        api.transition_labor_task(
            task["id"],
            {"to_status": "COMPLETED", "actual_hours": 8.0, "actual_units": 4000},
            make_harvest_supervisor_headers(worker["id"]),
        ),
        200,
    )
    assert completed["status"] == "COMPLETED", (
        f"the harvest supervisor may close the same task out, got {completed['status']}"
    )
    assert_four_decimal_places(
        completed["productivity_ratio"], 1.0000, "productivity_ratio"
    )
    assert_money(completed["bonus_usd"], 0.00, "bonus_usd")
    assert_money(completed["actual_cost_usd"], 156.00, "actual_cost_usd")

    zone = read_zone(state["zone"]["id"])
    assert_money(
        zone["labor_budget_committed_usd"], 156.00, "labor_budget_committed_usd"
    )


def test_an_opaque_inspector_identifier_advances_the_cold_chain(api):
    """PRD §2.1: "When `X-User-Role` is `GrowerManager`, `IrrigationTech`, or `QualityInspector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it to any entity's `id`."

    Design: Corner/rbac/opaque_quality_inspector_ids_need_no_worker_row
    """
    state = setup_graded_lot()
    inspector = make_quality_inspector_headers(AUDIT_INSPECTOR_USER_ID)

    precooled = validate_success(
        api.create_cold_chain_event(
            state["lot"]["id"], {"to_status": "PRECOOLED", "pulp_temp_c": 10.0}, inspector
        ),
        200,
    )
    assert precooled["cold_chain_status"] == "PRECOOLED", (
        f"an inspector with no worker row may pre-cool, got {precooled['cold_chain_status']}"
    )

    cold_held = validate_success(
        api.create_cold_chain_event(
            state["lot"]["id"], {"to_status": "COLD_HELD", "pulp_temp_c": 6.0}, inspector
        ),
        200,
    )
    assert cold_held["cold_chain_status"] == "COLD_HELD", (
        f"the same opaque identifier may hold the lot cold, got {cold_held['cold_chain_status']}"
    )


def test_cold_chain_release_records_the_opaque_inspector_identifier(api):
    """PRD §3.9: "Release records `cold_chain_released_by_user_id` from the releasing inspector's `X-User-ID`, and that identifier is retained specifically so that it can be compared against whoever signs the shipment in §3.10."

    Design: Corner/rbac/opaque_quality_inspector_ids_need_no_worker_row
    """
    state = setup_graded_lot()
    inspector = make_quality_inspector_headers(AUDIT_INSPECTOR_USER_ID)
    validate_success(
        api.create_cold_chain_event(
            state["lot"]["id"], {"to_status": "PRECOOLED", "pulp_temp_c": 10.0}, inspector
        ),
        200,
    )
    validate_success(
        api.create_cold_chain_event(
            state["lot"]["id"], {"to_status": "COLD_HELD", "pulp_temp_c": 6.0}, inspector
        ),
        200,
    )

    released = validate_success(
        api.create_cold_chain_event(
            state["lot"]["id"], {"to_status": "RELEASED", "pulp_temp_c": 5.0}, inspector
        ),
        200,
    )

    assert released["cold_chain_status"] == "RELEASED", (
        f"the lot leaves cold storage RELEASED, got {released['cold_chain_status']}"
    )
    assert released["cold_chain_released_by_user_id"] == AUDIT_INSPECTOR_USER_ID, (
        "the releasing inspector's opaque identifier is recorded verbatim, got "
        f"{released['cold_chain_released_by_user_id']}"
    )
    assert read_lot(state["lot"]["id"])["cold_chain_released_by_user_id"] == (
        AUDIT_INSPECTOR_USER_ID
    ), "the recorded identifier survives a re-read of the lot"
