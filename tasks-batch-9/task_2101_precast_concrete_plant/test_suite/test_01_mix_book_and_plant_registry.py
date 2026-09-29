"""The mix book, the static plant registry and the shared response contract."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_casting_bed,
    assert_mix_design,
    assert_project,
    assert_project_counters,
    CLOCK_START,
    CLOCK_START_STAMP,
    TEST_USERS,
    create_casting_bed,
    create_casting_bed_payload,
    create_bed_run,
    create_bed_run_payload,
    create_cylinder_set,
    create_curing_cycle,
    create_draft_mix,
    create_mix_design_payload,
    create_piece,
    create_piece_payload,
    create_project,
    create_project_payload,
    create_qualified_mix,
    create_shipment_payload,
    create_steam_zone,
    cylinder_break_payload,
    read_mix_design,
    read_piece,
    read_project,
    record_break,
    set_clock,
    setup_plant,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["plant_admin_headers"]
SUPERVISOR = TEST_USERS["production_supervisor_headers"]
QC = TEST_USERS["qc_technician_headers"]
ENGINEER = TEST_USERS["quality_engineer_headers"]
FOREMAN = TEST_USERS["yard_foreman_headers"]
PERMITS = TEST_USERS["permit_coordinator_headers"]


def test_register_erection_package_starts_every_counter_at_zero(api):
    """PRD §3.2: "All six of the package's counters described in §2.11 begin at 0."
    PRD §2.5: "`version` is an integer that is 1 when the row is created and
    increases by exactly 1 on every subsequent mutation of that row."

    Design: Corner/entities/create_project_returns_zeroed_counters
    """
    set_clock(CLOCK_START)

    response = api.create_project(create_project_payload(), ADMIN)
    project = validate_success(response, 201)

    assert_project(project)
    assert_project_counters(
        project,
        total_piece_count=0,
        held_piece_count=0,
        cleared_piece_count=0,
        scrapped_piece_count=0,
        erected_piece_count=0,
        committed_cost_cents=0,
    )
    assert project["version"] == 1, f"a new project starts at version 1, got {project['version']}"
    assert project["name"] == "Riverfront Garage"


def test_new_casting_bed_defaults_to_available_and_down_may_be_seeded(api):
    """PRD §3.3: "The bed's `status` defaults to `AVAILABLE`, and the only way a
    bed is ever unavailable at registration is for the operator to seed the
    optional `status` as `DOWN`."
    PRD §3.3: "A new bed's `committed_strand_force_kips` initialises to 0.00 and
    its `cumulative_cycle_count` to 0."

    Design: Corner/entities/create_casting_bed_applies_status_default_and_zero_committed_force
    """
    set_clock(CLOCK_START)
    zone = create_steam_zone()

    default_bed = validate_success(
        api.create_casting_bed(create_casting_bed_payload(zone["id"]), ADMIN), 201
    )
    down_bed = validate_success(
        api.create_casting_bed(
            create_casting_bed_payload(
                zone["id"],
                bed_code="B9",
                bed_type="FLAT_BED_RC",
                length_ft=200,
                max_strand_force_kips=0.01,
                turnaround_buffer_hours=0,
                status="DOWN",
            ),
            ADMIN,
        ),
        201,
    )

    assert_casting_bed(default_bed)
    assert default_bed["status"] == "AVAILABLE", (
        f"omitting status must yield AVAILABLE, got {default_bed['status']}"
    )
    assert default_bed["committed_strand_force_kips"] == 0
    assert default_bed["cumulative_cycle_count"] == 0
    assert down_bed["status"] == "DOWN", (
        f"a seeded DOWN status must be honoured, got {down_bed['status']}"
    )

    beds, meta = validate_paginated(api.list_steam_zone_casting_beds(zone["id"], ADMIN))
    assert meta["total_count"] == 2, f"the zone serves 2 beds, got {meta['total_count']}"
    assert {b["id"] for b in beds} == {default_bed["id"], down_bed["id"]}


def test_create_mix_design_without_required_release_psi_is_rejected(api):
    """PRD §2.8: "**Body schema.** Every required field is present, every type
    matches, every enum value is a member of its declared set, every numeric
    field satisfies its declared range, every ISO 8601 datetime parses, and
    every interval satisfies its ordering rule — `scheduled_end` after
    `scheduled_start`, `planned_end` after `planned_start`, `valid_to` after
    `valid_from`. Any breach fails with `ERR_VALIDATION` (400 Bad Request)."

    Design: Corner/entities/create_mix_design_missing_required_field_returns_validation
    """
    set_clock(CLOCK_START)
    payload = create_mix_design_payload()
    payload.pop("required_release_psi")

    response = api.create_mix_design(payload, ENGINEER)
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

    _, meta = validate_paginated(api.list_bed_runs(SUPERVISOR))
    assert meta["total_count"] == 0, "a rejected mix design must leave no side effects"


def test_invalid_enum_and_equal_window_bounds_return_validation(api):
    """PRD §2.8: "**Body schema.** Every required field is present, every type
    matches, every enum value is a member of its declared set, every numeric
    field satisfies its declared range, every ISO 8601 datetime parses, and
    every interval satisfies its ordering rule — `scheduled_end` after
    `scheduled_start`, `planned_end` after `planned_start`, `valid_to` after
    `valid_from`. Any breach fails with `ERR_VALIDATION` (400 Bad Request)."
    PRD §2.8: "**Body reference existence.** Every foreign identifier supplied
    in the body resolves, or the request fails with the matching 404 code."

    Design: Corner/entities/invalid_enum_and_inverted_interval_return_validation
    """
    ctx = setup_plant()

    bad_enum = api.create_mix_design(
        create_mix_design_payload(code="M99-X", strength_class="C99"), ENGINEER
    )
    validate_error(bad_enum, ApiErrorId.ERR_VALIDATION.value, 400)

    equal_bounds = api.create_bed_run(
        create_bed_run_payload(
            ctx["bed"]["id"],
            ctx["mix"]["id"],
            scheduled_start="2026-08-04T06:00:00Z",
            scheduled_end="2026-08-04T06:00:00Z",
        ),
        SUPERVISOR,
    )
    validate_error(equal_bounds, ApiErrorId.ERR_VALIDATION.value, 400)

    # Schema validation is step 5 of the order of refusal; body reference
    # existence is step 6, so the unresolvable bed_id must not decide this one.
    schema_before_reference = api.create_bed_run(
        create_bed_run_payload(
            NON_EXISTENT_UUID,
            ctx["mix"]["id"],
            scheduled_start="2026-08-04T06:00:00Z",
            scheduled_end="2026-08-04T05:00:00Z",
        ),
        SUPERVISOR,
    )
    validate_error(schema_before_reference, ApiErrorId.ERR_VALIDATION.value, 400)


def test_qualifying_a_qualified_mix_is_rejected_and_does_not_restamp(api):
    """PRD §3.1: "Qualification — the `QualityEngineer`'s act of accepting the
    mix into production, moving `status` from `DRAFT` to `QUALIFIED` — is
    permitted only from `DRAFT`, and any other starting status is refused with
    `ERR_MIX_DESIGN_INVALID_STATE`."
    PRD §3.1: "Qualification stamps `qualified_at` with the current logical
    clock instant and increments the mix's `version` by 1."

    Design: Corner/state_machines/mix_design_qualify_twice_returns_invalid_state
    """
    set_clock(CLOCK_START)
    mix = create_qualified_mix()
    set_clock("2026-08-04T06:00:00Z")

    response = api.qualify_mix_design(mix["id"], ENGINEER)
    validate_error(response, ApiErrorId.ERR_MIX_DESIGN_INVALID_STATE.value, 409)

    reread = read_mix_design(mix["id"])
    assert reread["status"] == "QUALIFIED"
    assert reread["qualified_at"].startswith("2026-08-03T06:00:00"), (
        f"qualified_at must keep the first qualification instant, got {reread['qualified_at']}"
    )


def test_retire_is_reachable_only_from_suspended_and_is_absorbing(api):
    """PRD §3.1: "Retirement is terminal and is reachable only from `SUSPENDED`,
    so retiring a live mix always costs a suspension first."
    PRD §3.1: "Reinstatement from any status other than `SUSPENDED` is refused
    with `ERR_MIX_DESIGN_INVALID_STATE`."

    Design: Corner/state_machines/mix_design_retire_reachable_only_from_suspended_and_is_terminal
    """
    set_clock(CLOCK_START)
    mix = create_qualified_mix()

    early = api.retire_mix_design(mix["id"], ENGINEER)
    validate_error(early, ApiErrorId.ERR_MIX_DESIGN_INVALID_STATE.value, 409)

    suspended = validate_success(
        api.suspend_mix_design(mix["id"], {"reason": "Mix withdrawn from the plant book"}, ENGINEER)
    )
    assert suspended["status"] == "SUSPENDED"

    retired = validate_success(api.retire_mix_design(mix["id"], ENGINEER))
    assert_mix_design(retired)
    assert retired["status"] == "RETIRED"

    after = api.reinstate_mix_design(mix["id"], ENGINEER)
    validate_error(after, ApiErrorId.ERR_MIX_DESIGN_INVALID_STATE.value, 409)
    assert read_mix_design(mix["id"])["status"] == "RETIRED"


def test_duplicate_mix_code_bed_code_and_piece_mark_return_their_errors(api):
    """PRD §3.1: "The `code` is between 1 and 32 characters long and must be
    unique across the whole mix book; a collision is rejected with
    `ERR_DUPLICATE_MIX_CODE`."
    PRD §3.3: "A `PlantAdmin` registers each **casting bed** with its identifier
    `bed_code`, which must be unique across the plant and collides with
    `ERR_DUPLICATE_RESOURCE_CODE`"
    PRD §3.2: "The `piece_mark` must be unique within its own project — two
    projects may reuse the same mark freely — and a collision inside one project
    is rejected with `ERR_DUPLICATE_PIECE_MARK`."

    Design: Corner/validations/uniqueness_violations_return_their_duplicate_errors
    """
    ctx = setup_plant(project_count=2)
    first_piece = create_piece(ctx["projects"][0]["id"], ctx["mix"]["id"])

    dup_mix = api.create_mix_design(
        create_mix_design_payload(
            code="M40-STD",
            strength_class="C50",
            design_28day_psi=7000,
            required_release_psi=3800,
            w_c_ratio=0.36,
            cement_lb_per_cy=740,
            unit_cost_cents_per_cy=15500,
        ),
        ENGINEER,
    )
    validate_error(dup_mix, ApiErrorId.ERR_DUPLICATE_MIX_CODE.value, 409)

    dup_bed = api.create_casting_bed(
        create_casting_bed_payload(
            ctx["zone"]["id"],
            bed_code="B1",
            bed_type="FLAT_BED_RC",
            length_ft=120,
            max_strand_force_kips=100,
            turnaround_buffer_hours=2,
        ),
        ADMIN,
    )
    validate_error(dup_bed, ApiErrorId.ERR_DUPLICATE_RESOURCE_CODE.value, 409)

    dup_mark = api.create_piece(
        create_piece_payload(
            ctx["projects"][0]["id"], ctx["mix"]["id"], piece_mark="DT-101", erection_sequence_no=40
        ),
        SUPERVISOR,
    )
    validate_error(dup_mark, ApiErrorId.ERR_DUPLICATE_PIECE_MARK.value, 409)

    reused_mark = validate_success(
        api.create_piece(
            create_piece_payload(
                ctx["projects"][1]["id"], ctx["mix"]["id"], piece_mark="DT-101"
            ),
            SUPERVISOR,
        ),
        201,
    )
    assert reused_mark["piece_mark"] == "DT-101"
    assert reused_mark["project_id"] == ctx["projects"][1]["id"]
    assert read_project(ctx["projects"][0]["id"])["total_piece_count"] == 1
    assert read_project(ctx["projects"][1]["id"])["total_piece_count"] == 1
    assert first_piece["piece_mark"] == "DT-101"


def test_unresolvable_path_and_body_identifiers_return_family_404s(api):
    """PRD §2.6: "Each entity family has its own 404 Not Found code: a `Project`
    reference that does not resolve yields `ERR_PROJECT_NOT_FOUND`; a
    `MixDesign` reference yields `ERR_MIX_DESIGN_NOT_FOUND`; a `SteamZone`,
    `CastingBed` or `YardSlot` reference yields `ERR_PLANT_RESOURCE_NOT_FOUND`;
    a `BedRun` or `CuringCycle` reference yields `ERR_BED_RUN_NOT_FOUND`; a
    `CylinderSet` reference yields `ERR_CYLINDER_SET_NOT_FOUND`; a `Piece` or
    `YardPlacement` reference yields `ERR_PIECE_NOT_FOUND`; a `HaulPermit`
    reference yields `ERR_HAUL_PERMIT_NOT_FOUND`; a `Shipment` reference yields
    `ERR_SHIPMENT_NOT_FOUND`; and a `RepairDisposition` reference yields
    `ERR_REPAIR_DISPOSITION_NOT_FOUND`."
    PRD §2.6: "The same mapping governs identifiers supplied inside a request
    body, but body references are resolved only after the body itself has passed
    schema validation."

    Design: Corner/entities/unresolvable_path_and_body_ids_return_not_found
    """
    ctx = setup_plant()
    piece = create_piece(ctx["project"]["id"], ctx["mix"]["id"])

    validate_error(
        api.get_project(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_PROJECT_NOT_FOUND.value, 404
    )
    validate_error(
        api.get_mix_design(NON_EXISTENT_UUID, ENGINEER),
        ApiErrorId.ERR_MIX_DESIGN_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.create_casting_bed(
            create_casting_bed_payload(NON_EXISTENT_UUID, bed_code="BX"), ADMIN
        ),
        ApiErrorId.ERR_PLANT_RESOURCE_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.assign_piece_to_run(piece["id"], {"bed_run_id": NON_EXISTENT_UUID}, SUPERVISOR),
        ApiErrorId.ERR_BED_RUN_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.record_cylinder_break(NON_EXISTENT_UUID, cylinder_break_payload(43983), QC),
        ApiErrorId.ERR_CYLINDER_SET_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_piece(NON_EXISTENT_UUID, SUPERVISOR), ApiErrorId.ERR_PIECE_NOT_FOUND.value, 404
    )
    validate_error(
        api.create_shipment(
            create_shipment_payload(
                ctx["project"]["id"],
                scheduled_departure="2026-08-05T13:00:00Z",
                haul_permit_id=NON_EXISTENT_UUID,
            ),
            FOREMAN,
        ),
        ApiErrorId.ERR_HAUL_PERMIT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.dispatch_shipment(NON_EXISTENT_UUID, FOREMAN),
        ApiErrorId.ERR_SHIPMENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.decide_disposition(NON_EXISTENT_UUID, {"disposition": "USE_AS_IS"}, ENGINEER),
        ApiErrorId.ERR_REPAIR_DISPOSITION_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.create_piece(
            create_piece_payload(
                NON_EXISTENT_UUID,
                ctx["mix"]["id"],
                piece_mark="GHOST",
                erection_sequence_no=99,
                length_ft=20.00,
                width_ft=4.00,
                height_ft=3.00,
                weight_lb=5000,
                concrete_volume_cy=2.00,
            ),
            SUPERVISOR,
        ),
        ApiErrorId.ERR_PROJECT_NOT_FOUND.value,
        404,
    )

    reread = read_piece(piece["id"])
    assert reread["production_status"] == "PLANNED"
    assert reread["bed_run_id"] is None, "the failed assign-run must have written nothing"
    assert read_project(ctx["project"]["id"])["total_piece_count"] == 1


def test_responses_carry_the_declared_success_and_error_envelope(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."

    Design: Corner/endpoints/success_and_error_responses_use_the_declared_envelope
    """
    set_clock(CLOCK_START)

    created = api.create_project(create_project_payload(), ADMIN)
    project = validate_success(created, 201)
    body = created.json()
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {body['meta']['api_request_id']}"
    )
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert body["response_type"] == "object"
    assert body["data"]["id"] == project["id"]

    listed = api.list_pieces(SUPERVISOR, {"project_id": project["id"]})
    rows, meta = validate_paginated(listed)
    assert listed.json()["response_type"] == "array"
    assert rows == []
    assert meta["limit"] == 10 and meta["offset"] == 0
    assert meta["total_count"] == 0 and meta["has_more"] is False

    failed = api.get_project(NON_EXISTENT_UUID, ADMIN)
    error = validate_error(failed, ApiErrorId.ERR_PROJECT_NOT_FOUND.value, 404)
    assert failed.json()["response_type"] == "error"
    assert error["message"].strip(), "an error response must carry a human-readable message"


def test_sub_resource_reads_return_child_arrays(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.3: "Bed runs may be narrowed by `bed_id`, by `mix_design_id` and by
    `status`."
    PRD §2.3: "The cylinder sets of a run may be narrowed by `purpose`."
    PRD §2.3: "The curing cycles of a boiler zone, the placement history of a
    piece, the placements at a yard slot and the nonconformance reports of a
    piece may each be narrowed by `status`."

    Design: Corner/endpoints/sub_resource_reads_return_child_arrays_for_every_foreign_key
    """
    ctx = setup_plant()
    run = create_bed_run(ctx["bed"]["id"], ctx["mix"]["id"])
    cylinder_set = create_cylinder_set(run["id"])
    cycle = create_curing_cycle(run["id"], ctx["zone"]["id"])
    record_break(cylinder_set["id"], 43983)

    zone_read = api.get_steam_zone(ctx["zone"]["id"], ADMIN)
    zone = validate_success(zone_read)
    assert zone_read.json()["response_type"] == "object"
    assert zone["boiler_capacity_bhp"] == 100
    assert zone["therm_rate_cents_per_therm"] == 95

    set_read = api.get_cylinder_set(cylinder_set["id"], QC)
    read_set = validate_success(set_read)
    assert set_read.json()["response_type"] == "object"
    assert read_set["purpose"] == "RELEASE"
    assert read_set["specimen_count"] == 2
    assert read_set["recorded_break_count"] == 1

    beds_resp = api.list_steam_zone_casting_beds(ctx["zone"]["id"], ADMIN)
    beds, _ = validate_paginated(beds_resp)
    assert beds_resp.json()["response_type"] == "array"
    assert [b["id"] for b in beds] == [ctx["bed"]["id"]]

    sets, _ = validate_paginated(
        api.list_bed_run_cylinder_sets(run["id"], QC, {"purpose": "RELEASE"})
    )
    assert [s["id"] for s in sets] == [cylinder_set["id"]]

    cycles, _ = validate_paginated(api.list_bed_run_curing_cycles(run["id"], SUPERVISOR))
    assert [c["id"] for c in cycles] == [cycle["id"]]

    zone_cycles, _ = validate_paginated(
        api.list_steam_zone_curing_cycles(ctx["zone"]["id"], SUPERVISOR, {"status": "SCHEDULED"})
    )
    assert [c["id"] for c in zone_cycles] == [cycle["id"]]

    breaks, _ = validate_paginated(api.list_cylinder_breaks(cylinder_set["id"], QC))
    assert len(breaks) == 1
    assert breaks[0]["computed_psi"] == 3500
    assert breaks[0]["inclusion_status"] == "VALID"

    runs, _ = validate_paginated(
        api.list_bed_runs(SUPERVISOR, {"bed_id": ctx["bed"]["id"], "status": "SCHEDULED"})
    )
    assert [r["id"] for r in runs] == [run["id"]]
