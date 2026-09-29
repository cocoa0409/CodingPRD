"""Unresolvable references and the page-size bound.

Every request here is otherwise complete and correctly authorised: the acting role
owns the endpoint, the body carries every required field with a legal shape, and
each competing business gate downstream has been satisfied on purpose. The single
defect is a reference that resolves to nothing — a program, material spec, design,
characteristic, tooling asset, wire heat, coiler, setup, run, oven, batch, approval
package or shipment lot that the collection does not hold — or, in the first test,
a page size outside the bound the pagination rule declares. In each case the
rejection has to be the not-found answer that owns that reference, and the row the
request would have written must not exist afterwards.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
)

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_BATCH_NOT_FOUND,
    ERR_CHARACTERISTIC_NOT_FOUND,
    ERR_DESIGN_NOT_FOUND,
    ERR_INVALID_PAGINATION,
    ERR_LOT_NOT_FOUND,
    ERR_MACHINE_NOT_FOUND,
    ERR_MATERIAL_SPEC_NOT_FOUND,
    ERR_OVEN_NOT_FOUND,
    ERR_PROGRAM_NOT_FOUND,
    ERR_RUN_NOT_FOUND,
    ERR_SETUP_NOT_FOUND,
    ERR_SUBMISSION_NOT_FOUND,
    ERR_TOOLING_NOT_FOUND,
    ERR_WIRE_LOT_NOT_FOUND,
)
from test_helpers.test_users import (
    DESIGN_ENGINEER_HEADERS,
    ENGINEERING_MANAGER_HEADERS,
    PROCESS_TECHNICIAN_HEADERS,
    PROGRAM_MANAGER_HEADERS,
    QUALITY_INSPECTOR_HEADERS,
)


def test_design_listing_refuses_a_limit_above_the_hundred_row_ceiling(api):
    """A page size of 101 is refused outright, not clamped to 100 or to the default 10.

    PRD §2.3: "`limit` controls page size; it defaults to 10 when omitted, has a
    minimum of 1 and a maximum of 100."
    PRD §2.3: "A `limit` outside the inclusive range 1 through 100, or a negative
    `offset`, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."
    PRD §2.8: "5. `ERR_INVALID_PAGINATION` — on every list endpoint."
    PRD §2.3: "The `meta` object of every list response carries `limit` and `offset`
    echoing the effective values in force, `total_count` giving the number of rows
    matching the filters before pagination is applied, and `has_more` set true exactly
    when rows remain beyond the current page."

    Design: Corner/errors/design_listing_over_the_page_ceiling_returns_invalid_pagination
    """
    X.build_world(api, "design")

    response = api.list_designs(DESIGN_ENGINEER_HEADERS, {"limit": 101})
    validate_error(response, ERR_INVALID_PAGINATION, 400)

    # One row past the ceiling is a rejection; the ceiling itself answers normally,
    # which is what proves the refusal was the bound and not the listing.
    designs, meta = validate_paginated(
        api.list_designs(DESIGN_ENGINEER_HEADERS, {"limit": 100})
    )
    assert meta["total_count"] == 1, (
        f"the one drafted design must be countable at the 100-row ceiling, got "
        f"{meta['total_count']}"
    )
    assert meta["limit"] == 100, (
        f"the effective limit echoes the accepted request value, got {meta['limit']}"
    )
    assert len(designs) == 1, f"one design row comes back, got {len(designs)}"


def test_design_creation_against_an_unknown_program_is_not_found(api):
    """A well-formed design body naming a program that does not exist creates no orphan.

    PRD §2.8: "Foreign keys carried in a request body are resolved after the path but
    before any business rule reads them."
    PRD §2.8: "6. `ERR_PROGRAM_NOT_FOUND` — on `GET`/`POST /customer-programs/{id}/*`,
    `POST /spring-designs`, `POST /qualification-submissions`, `POST /shipment-lots`."

    Design: Corner/errors/design_create_against_an_unknown_program_is_not_found
    """
    material = X.register_material(api)

    # The body is otherwise the canonical D1 geometry, so nothing above the program
    # lookup in the ladder — shape, enum membership or numeric constraint — can answer.
    response = api.create_design(
        F.design_payload(NON_EXISTENT_UUID, material["id"]), DESIGN_ENGINEER_HEADERS
    )
    validate_error(response, ERR_PROGRAM_NOT_FOUND, 404)

    designs, meta = validate_paginated(api.list_designs(DESIGN_ENGINEER_HEADERS))
    assert meta["total_count"] == 0, (
        f"the refused creation must leave no design row behind, got {meta['total_count']}"
    )
    assert designs == [], "no design exists for a program that was never opened"


def test_wire_receipt_against_an_unknown_material_spec_is_not_found(api):
    """A heat booked in against a spec that is not on file opens no mass ledger.

    PRD §2.8: "Foreign keys carried in a request body are resolved after the path but
    before any business rule reads them."
    PRD §2.8: "7. `ERR_MATERIAL_SPEC_NOT_FOUND` — on `GET /material-specs/{id}`, `POST
    /spring-designs`, `POST /spring-designs/{id}/revisions`, `POST /wire-lots`."
    PRD §3.5: "The receiving payload names the `material_spec_id`, the mill's
    `heat_number` — unique across all wire lots — and `received_kg`, the kilograms
    received, which must be greater than zero and is carried to three decimal places."

    Design: Corner/errors/wire_lot_create_against_an_unknown_material_spec_is_not_found
    """
    # A real grade is on file, so the rejection cannot be blamed on an empty catalogue:
    # the request simply names an id that is not this one.
    X.register_material(api)

    response = api.create_wire_lot(
        F.wire_lot_payload(NON_EXISTENT_UUID), QUALITY_INSPECTOR_HEADERS
    )
    validate_error(response, ERR_MATERIAL_SPEC_NOT_FOUND, 404)

    lots, meta = validate_paginated(api.list_wire_lots(QUALITY_INSPECTOR_HEADERS))
    assert meta["total_count"] == 0, (
        f"no wire lot row may be written for an unresolvable spec, got "
        f"{meta['total_count']}"
    )
    assert lots == [], "the mass ledger of a refused receipt is never opened"


def test_tooling_capitalisation_against_an_unknown_design_is_not_found(api):
    """Capitalising a tool against a design that does not exist opens no ledger.

    PRD §2.8: "Foreign keys carried in a request body are resolved after the path but
    before any business rule reads them."
    PRD §2.8: "8. `ERR_DESIGN_NOT_FOUND` — on every `/spring-designs/{id}/*` endpoint,
    `POST /machine-setups`, `POST /production-runs`, `POST /qualification-submissions`,
    `POST /tooling-assets`, `POST /customer-programs/{id}/quote`."
    PRD §3.4: "Coiling tools are capitalised by an `EngineeringManager` against a
    design, through a payload naming the `design_id`, a tool-room `tool_code` that must
    be unique across all tooling, and `original_cost_cents`, the capitalised cost in
    cents, which must be greater than zero and which is the conserved quantity of the
    amortization ledger."
    PRD §3.4: "A newly capitalised tool opens in `amortization_status` `PENDING` with
    `recovered_cents` at 0 and `unamortized_cents` equal to `original_cost_cents`."

    Design: Corner/errors/tooling_create_against_an_unknown_design_is_not_found
    """
    # A DRAFT design exists; the body names a different, unresolvable id. The cost is
    # the canonical positive figure, so the numeric constraint above the lookup passes.
    X.build_world(api, "design")

    response = api.create_tooling_asset(
        F.tooling_payload(NON_EXISTENT_UUID), ENGINEERING_MANAGER_HEADERS
    )
    validate_error(response, ERR_DESIGN_NOT_FOUND, 404)

    tools, meta = validate_paginated(
        api.list_tooling_assets(ENGINEERING_MANAGER_HEADERS)
    )
    assert meta["total_count"] == 0, (
        f"the refused capitalisation must not create an amortization ledger, got "
        f"{meta['total_count']}"
    )
    assert tools == [], "no tooling asset belongs to a design that does not exist"


def test_in_process_inspection_against_an_unknown_characteristic_is_not_found(api):
    """An SPC subgroup naming no known characteristic posts no capability figure.

    PRD §2.8: "Foreign keys carried in a request body are resolved after the path but
    before any business rule reads them."
    PRD §2.8: "9. `ERR_CHARACTERISTIC_NOT_FOUND` — on `POST /production-runs/{id}/fai`,
    `POST /production-runs/{id}/inspections`."
    PRD §3.7: "First-article records therefore move `min_cpk_observed` but leave
    `min_ppk_observed` untouched."
    PRD §3.7: "Inspection records may be read individually and listed filtered by
    `run_id`, `characteristic_id`, `record_kind` and `control_state`."

    Design: Corner/errors/inspection_against_an_unknown_characteristic_is_not_found
    """
    # A RUNNING run with its first article accepted: the endpoint's own state gate is
    # satisfied, and the subgroup carries three readings, so the subgroup-size floor
    # and the cross-design comparison are both live rather than pre-empting.
    world = X.running_run_world(api)
    before = X.refresh_run(api, world.run_id)

    response = api.record_inspection(
        world.run_id,
        F.measurement_payload(NON_EXISTENT_UUID, list(C.IN_CONTROL_SUBGROUP)),
        QUALITY_INSPECTOR_HEADERS,
    )
    validate_error(response, ERR_CHARACTERISTIC_NOT_FOUND, 404)

    after = X.refresh_run(api, world.run_id)
    assert after["min_cpk_observed"] == before["min_cpk_observed"], (
        f"the refused subgroup must not move the run's short-run capability: "
        f"{before['min_cpk_observed']} became {after['min_cpk_observed']}"
    )
    assert after["min_ppk_observed"] is None, (
        f"only in-process records post a pooled figure, so it stays null, got "
        f"{after['min_ppk_observed']}"
    )

    records, meta = validate_paginated(
        api.list_inspection_records(
            QUALITY_INSPECTOR_HEADERS, {"run_id": world.run_id}
        )
    )
    assert meta["total_count"] == 1, (
        f"the run keeps only its first-article row, got {meta['total_count']}"
    )
    assert records[0]["record_kind"] == C.RECORD_KIND_FAI, (
        f"the surviving record is the first-article one, got "
        f"{records[0]['record_kind']}"
    )


def test_setup_booking_against_an_unknown_tooling_asset_is_not_found(api):
    """An unresolvable tool id answers 404 though machine, design and window are valid.

    PRD §2.8: "Foreign keys carried in a request body are resolved after the path but
    before any business rule reads them."
    PRD §2.8: "10. `ERR_TOOLING_NOT_FOUND` — on `GET /tooling-assets/{id}`, `POST
    /machine-setups`."
    PRD §3.6: "The payload names the `machine_id` of the coiler, the `design_id` being
    set up, the `tooling_asset_id` of the tool set being mounted, and the occupation
    window as `window_start` (inclusive) and `window_end` (exclusive), both ISO 8601 UTC
    instants."
    PRD §3.6: "A successful booking stamps `set_by_user_id` from the technician's
    `X-User-ID`, opens the setup in `setup_status` `SCHEDULED`, and increases the
    coiler's `version` by 1."
    PRD §3.6: "A new coiler opens in `machine_state` `IDLE` with `active_setup_id` null."

    Design: Corner/errors/setup_create_against_an_unknown_tooling_asset_is_not_found
    """
    # A released design, a real capitalised tool and an IDLE coiler are all on file,
    # and the body carries the coiler's current version, so the optimistic-concurrency
    # check one rank below the lookup would pass rather than answer.
    world = X.build_world(api, "machine")

    response = api.create_setup(
        F.setup_payload(
            world.machine_id,
            world.design_id,
            NON_EXISTENT_UUID,
            world.machine_version,
        ),
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(response, ERR_TOOLING_NOT_FOUND, 404)

    setups, meta = validate_paginated(api.list_setups(PROCESS_TECHNICIAN_HEADERS))
    assert meta["total_count"] == 0, (
        f"no setup row may be booked around a tool that does not exist, got "
        f"{meta['total_count']}"
    )
    assert setups == [], "the shop schedule is untouched by the refused booking"

    machine = X.refresh_machine(api, world.machine_id)
    assert machine["machine_state"] == C.MACHINE_IDLE, (
        f"the coiler was never occupied, so it stays IDLE, got "
        f"{machine['machine_state']}"
    )
    assert machine["version"] == world.machine_version, (
        f"only a successful booking increases the coiler's version: expected "
        f"{world.machine_version}, got {machine['version']}"
    )


def test_setup_booking_against_an_unknown_machine_is_not_found(api):
    """An unknown coiler answers 404, not the version conflict one rank below it.

    PRD §2.8: "When a single request violates more than one rule, exactly one error is
    returned: the one with the **lowest priority number** in the following ladder."
    PRD §2.8: "12. `ERR_MACHINE_NOT_FOUND` — on `GET /coiling-machines/{id}`, `POST
    /machine-setups`."
    PRD §2.8: "19. The three optimistic-concurrency checks of section 2.7, which share
    this rank: `ERR_STALE_DESIGN_VERSION` on `POST /spring-designs/{id}/revisions`,
    `ERR_STALE_MACHINE_VERSION` on `POST /machine-setups`, and
    `ERR_STALE_PROGRAM_VERSION` on `POST /customer-programs/{id}/quote`."
    PRD §2.7: "A mismatch is rejected with `ERR_STALE_MACHINE_VERSION` (HTTP 412)."

    Design: Corner/errors/setup_create_against_an_unknown_machine_is_not_found
    """
    # The design and its tool are real; only the coiler is missing. The body still has
    # to carry expected_machine_version, or the shape check at rank 4 would answer, and
    # there is no version to be current against — which is exactly why the ladder puts
    # the coiler lookup above the concurrency guard.
    world = X.build_world(api, "machine")

    response = api.create_setup(
        F.setup_payload(
            NON_EXISTENT_UUID,
            world.design_id,
            world.tooling_id,
            world.machine_version,
        ),
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(response, ERR_MACHINE_NOT_FOUND, 404)

    setups, meta = validate_paginated(api.list_setups(PROCESS_TECHNICIAN_HEADERS))
    assert meta["total_count"] == 0, (
        f"a setup cannot be booked on a coiler that does not exist, got "
        f"{meta['total_count']}"
    )
    assert setups == [], "no schedule row survives the refused booking"

    machine = X.refresh_machine(api, world.machine_id)
    assert machine["version"] == world.machine_version, (
        f"the real coiler was never named and so never touched: expected version "
        f"{world.machine_version}, got {machine['version']}"
    )


def test_activation_of_an_unknown_setup_is_not_found(api):
    """The path lookup answers before the window gate, so this is 404 and not 409.

    PRD §2.8: "Path parameters are resolved strictly left to right, and the leftmost
    unresolvable segment decides the answer."
    PRD §2.8: "13. `ERR_SETUP_NOT_FOUND` — on `GET`/`POST /machine-setups/{id}/*`, `POST
    /production-runs`."
    PRD §2.8: "68. `ERR_OUTSIDE_SETUP_WINDOW` — on `POST /machine-setups/{id}/activate`."
    PRD §3.6: "And the logical clock must be inside the booked window, at or after
    `window_start` and strictly before `window_end`; outside that span the answer is
    `ERR_OUTSIDE_SETUP_WINDOW` (HTTP 409)."
    PRD §3.6: "On success the coiler transitions `IDLE → SETUP`, its `active_setup_id` is
    set to this setup's id, and its `version` increases by 1."

    Design: Corner/errors/activate_of_an_unknown_setup_is_not_found
    """
    # A genuine SCHEDULED setup is on file and the clock still stands well before its
    # window, so the low-ranked window conflict is armed for the real row. The path
    # names a different id, and the lookup answers first regardless.
    world = X.scheduled_setup_world(api)

    response = api.activate_setup(NON_EXISTENT_UUID, PROCESS_TECHNICIAN_HEADERS)
    validate_error(response, ERR_SETUP_NOT_FOUND, 404)

    setup = X.refresh_setup(api, world.setup_id)
    assert setup["setup_status"] == C.SETUP_SCHEDULED, (
        f"the real setup is untouched by an activation aimed elsewhere, got "
        f"{setup['setup_status']}"
    )

    machine = X.refresh_machine(api, world.machine_id)
    assert machine["machine_state"] == C.MACHINE_IDLE, (
        f"no coiler enters SETUP on a failed activation, got "
        f"{machine['machine_state']}"
    )
    assert machine["active_setup_id"] is None, (
        f"nothing was mounted, so active_setup_id stays null, got "
        f"{machine['active_setup_id']}"
    )


def test_lot_allocation_against_an_unknown_run_is_not_found(api):
    """An unknown run answers 404 rather than the COMPLETE-state gate eight ranks below.

    PRD §2.8: "Foreign keys carried in a request body are resolved after the path but
    before any business rule reads them."
    PRD §2.8: "14. `ERR_RUN_NOT_FOUND` — on `GET`/`POST /production-runs/{id}/*`, `POST
    /heat-treat-batches`, `POST /shipment-lots`."
    PRD §2.8: "22. `ERR_RUN_NOT_COMPLETE` — on `POST /shipment-lots`."
    PRD §3.11: "Creating a shipment lot is the densest gate in the API: a
    `ProgramManager` names a `run_id`, a `program_id` and a `piece_count` greater than
    zero, and eleven substantive conditions apply in the priority order of section 2.8."
    PRD §3.11: "The run's `process_status` must be `COMPLETE`, otherwise
    `ERR_RUN_NOT_COMPLETE` (HTTP 409); its `quality_status` must be `OPEN` or
    `DISPOSITIONED_ACCEPT`, and a held or scrapped run answers `ERR_RUN_ON_SPC_HOLD`
    (HTTP 409)."

    Design: Corner/errors/lot_create_against_an_unknown_run_is_not_found
    """
    # The whole chain is qualified — COMPLETE and heat-treated run, granted approval
    # package, priced program — so every one of the eleven allocation conditions would
    # pass for the real run. Only the run id in the body is unresolvable.
    world = X.approved_world(api)

    response = api.create_lot(
        F.lot_payload(NON_EXISTENT_UUID, world.program_id), PROGRAM_MANAGER_HEADERS
    )
    validate_error(response, ERR_RUN_NOT_FOUND, 404)

    lots, meta = validate_paginated(api.list_lots(PROGRAM_MANAGER_HEADERS))
    assert meta["total_count"] == 0, (
        f"no shipment lot may be allocated against a run that does not exist, got "
        f"{meta['total_count']}"
    )
    assert lots == [], "the dock stays empty after the refused allocation"

    program = X.refresh_program(api, world.program_id)
    assert program["allocated_pieces"] == 0, (
        f"a refused allocation consumes no commitment, got "
        f"{program['allocated_pieces']}"
    )


def test_batch_scheduling_against_an_unknown_oven_is_not_found(api):
    """The oven lookup answers before the temperature and capacity gates ever run.

    PRD §2.8: "Foreign keys carried in a request body are resolved after the path but
    before any business rule reads them."
    PRD §2.8: "15. `ERR_OVEN_NOT_FOUND` — on `GET /stress-relief-ovens/{id}`, `POST
    /heat-treat-batches`."
    PRD §3.9: "The payload names the `oven_id`, the `run_id` whose pieces are being
    relieved, the occupation window as `window_start` and `window_end` — both
    **inclusive** for this entity — the weighed basket `load_kg` in kilograms carried to
    three decimal places and greater than zero, the requested soak `target_temp_c`
    greater than zero, and the optional `peening_requested` flag recording whether shot
    peening is part of this batch's recipe, defaulting to false."
    PRD §3.9: "A new oven opens with `scheduled_load_kg` at 0.000, and that field is
    always the sum of `load_kg` over the oven's batches whose `batch_status` is
    `SCHEDULED` or `RUNNING`."
    PRD §3.9: "The run's `heat_treat_state` stays `NOT_STARTED` — scheduling a batch is
    not charging one."

    Design: Corner/errors/heat_treat_batch_against_an_unknown_oven_is_not_found
    """
    # The run is COMPLETE, so the state gate above the oven lookup passes, and a real
    # oven with room to spare is on file: the request simply names another id.
    world = X.build_world(api, "complete")
    oven = X.commission_oven(api)

    response = api.create_batch(
        F.batch_payload(NON_EXISTENT_UUID, world.run_id), PROCESS_TECHNICIAN_HEADERS
    )
    validate_error(response, ERR_OVEN_NOT_FOUND, 404)

    batches, meta = validate_paginated(api.list_batches(PROCESS_TECHNICIAN_HEADERS))
    assert meta["total_count"] == 0, (
        f"no load may be booked into an oven that does not exist, got "
        f"{meta['total_count']}"
    )
    assert batches == [], "the refused charge books nothing anywhere"

    real_oven = X.refresh_oven(api, oven["id"])
    assert real_oven["scheduled_load_kg"] == 0, (
        f"the real oven carries no load from a batch that was never created, got "
        f"{real_oven['scheduled_load_kg']}"
    )

    run = X.refresh_run(api, world.run_id)
    assert run["heat_treat_state"] == C.HEAT_TREAT_NOT_STARTED, (
        f"the run's heat treatment never began, got {run['heat_treat_state']}"
    )


def test_charging_an_unknown_heat_treat_batch_is_not_found(api):
    """The path lookup at rank 16 answers before the window-reached gate at rank 69.

    PRD §2.8: "Path parameters are resolved strictly left to right, and the leftmost
    unresolvable segment decides the answer."
    PRD §2.8: "16. `ERR_BATCH_NOT_FOUND` — on `GET`/`POST /heat-treat-batches/{id}/*`."
    PRD §2.8: "69. `ERR_BATCH_WINDOW_NOT_REACHED` — on `POST
    /heat-treat-batches/{id}/start`."
    PRD §3.9: "Charging a batch takes it `SCHEDULED → RUNNING`."
    PRD §3.9: "The batch must be `SCHEDULED`, otherwise `ERR_BATCH_INVALID_STATE` (HTTP
    409), and the logical clock must have reached at least `window_start`, otherwise
    `ERR_BATCH_WINDOW_NOT_REACHED` (HTTP 409)."
    PRD §3.9: "The cascade is a single hop: the run's `heat_treat_state` becomes
    `IN_PROCESS`."

    Design: Corner/errors/start_of_an_unknown_heat_treat_batch_is_not_found
    """
    # A real SCHEDULED batch waits on its afternoon window while the clock still reads
    # the morning, so the low-ranked early-start conflict is armed for that row. The
    # path names a batch that does not exist, and the lookup answers first.
    world = X.build_world(api, "complete")
    oven = X.commission_oven(api)
    batch = X.schedule_batch(api, oven["id"], world.run_id)

    response = api.start_batch(NON_EXISTENT_UUID, PROCESS_TECHNICIAN_HEADERS)
    validate_error(response, ERR_BATCH_NOT_FOUND, 404)

    real_batch = X.refresh_batch(api, batch["id"])
    assert real_batch["batch_status"] == C.BATCH_SCHEDULED, (
        f"the real batch is not charged by a start aimed elsewhere, got "
        f"{real_batch['batch_status']}"
    )

    real_oven = X.refresh_oven(api, oven["id"])
    assert real_oven["scheduled_load_kg"] == batch["load_kg"], (
        f"the scheduled load is unchanged by the failed charge: expected "
        f"{batch['load_kg']}, got {real_oven['scheduled_load_kg']}"
    )

    run = X.refresh_run(api, world.run_id)
    assert run["heat_treat_state"] == C.HEAT_TREAT_NOT_STARTED, (
        f"only a charged batch moves the run to IN_PROCESS, got "
        f"{run['heat_treat_state']}"
    )


def test_resubmission_of_an_unknown_submission_is_not_found(api):
    """An unknown package answers 404, not the state error a live package would earn.

    PRD §2.8: "Path parameters are resolved strictly left to right, and the leftmost
    unresolvable segment decides the answer."
    PRD §2.8: "17. `ERR_SUBMISSION_NOT_FOUND` — on `GET`/`POST
    /qualification-submissions/{id}/*`."
    PRD §2.8: "31. `ERR_SUBMISSION_INVALID_STATE` — on `POST
    /qualification-submissions/{id}/review`, `POST
    /qualification-submissions/{id}/resubmit`."
    PRD §3.10: "A `ProgramManager` may resubmit a package whose `submission_status` is
    `REVISION_REQUESTED` or `INTERIM_APPROVED`; `SUBMITTED`, `APPROVED` and
    `REJECTED_FINAL` answer `ERR_SUBMISSION_INVALID_STATE`."
    PRD §3.10: "A successful filing opens at `round_no` 1 in `submission_status`
    `SUBMITTED` with `submitted_by_user_id` stamped from the header,
    `interim_piece_cap`, `reviewed_by_program_id` and `decided_at` all null."

    Design: Corner/errors/resubmit_of_an_unknown_submission_is_not_found
    """
    # A genuine round-1 package sits in SUBMITTED, which is precisely a status the
    # resubmit rule refuses — so the state error is armed for the real row while the
    # request names an id that resolves to nothing.
    world = X.running_run_world(api)
    submission = X.file_submission(api, world.program_id, world.design_id)

    response = api.resubmit_submission(NON_EXISTENT_UUID, PROGRAM_MANAGER_HEADERS)
    validate_error(response, ERR_SUBMISSION_NOT_FOUND, 404)

    real_submission = X.refresh_submission(api, submission["id"])
    assert real_submission["submission_status"] == C.SUBMISSION_SUBMITTED, (
        f"the filed package is untouched by a resubmit aimed elsewhere, got "
        f"{real_submission['submission_status']}"
    )
    assert real_submission["round_no"] == 1, (
        f"no round is consumed by the refused resubmit, got "
        f"{real_submission['round_no']}"
    )


def test_packing_an_unknown_lot_is_not_found(api):
    """The lot lookup precedes the state check and both packaging rules.

    PRD §2.8: "Path parameters are resolved strictly left to right, and the leftmost
    unresolvable segment decides the answer."
    PRD §2.8: "18. `ERR_LOT_NOT_FOUND` — on `GET`/`POST /shipment-lots/{id}/*`."
    PRD §2.8: "32. `ERR_LOT_INVALID_STATE` — on `POST /shipment-lots/{id}/pack`,
    `.../ship`, `.../return`, `.../quarantine`, `.../release-from-quarantine`."
    PRD §3.11: "A `ProcessTechnician` packs an `ALLOCATED` lot with a stated
    `packaging_method`, and two independent rules apply in order."
    PRD §3.11: "A lot that survives all of that opens in `lot_status` `ALLOCATED` with
    `packaging_method` null, and it snapshots the commercial terms at creation:
    `unit_price_cents` from the program's `quoted_unit_price_cents`,
    `tooling_amort_per_piece_cents` from the program's
    `quoted_tooling_amort_per_piece_cents`, and `extended_price_cents` as `piece_count`
    multiplied by `unit_price_cents`."
    PRD §3.11: "Success records the method and moves the lot `ALLOCATED → PACKED`."

    Design: Corner/errors/pack_of_an_unknown_lot_is_not_found
    """
    # A real ALLOCATED lot is on the floor and the stated method is one an INDUSTRIAL
    # program permits, so neither packaging rule below the lookup could answer even if
    # the lot had resolved.
    world = X.allocated_world(api)

    response = api.pack_lot(
        NON_EXISTENT_UUID,
        {"packaging_method": C.PACK_TANGLE_FREE_TRAY},
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(response, ERR_LOT_NOT_FOUND, 404)

    lot = X.refresh_lot(api, world.lot_id)
    assert lot["lot_status"] == C.LOT_ALLOCATED, (
        f"the real lot is untouched by a pack aimed elsewhere, got "
        f"{lot['lot_status']}"
    )
    assert lot["packaging_method"] is None, (
        f"no packaging method is recorded anywhere by the refused pack, got "
        f"{lot['packaging_method']}"
    )


def test_run_creation_against_an_unknown_wire_heat_is_not_found(api):
    """An unknown heat answers 404 before certification, grade and sufficiency are read.

    PRD §2.8: "Foreign keys carried in a request body are resolved after the path but
    before any business rule reads them."
    PRD §2.8: "11. `ERR_WIRE_LOT_NOT_FOUND` — on `GET`/`POST /wire-lots/{id}/*`, `POST
    /production-runs`."
    PRD §2.8: "40. `ERR_WIRE_LOT_NOT_CERTIFIED` — on `POST /production-runs`."
    PRD §2.8: "48. `ERR_MATERIAL_MISMATCH` — on `POST /production-runs`."
    PRD §2.8: "72. `ERR_INSUFFICIENT_WIRE` — on `POST /production-runs`."
    PRD §3.7: "Opening a production run is the `ProcessTechnician`'s act and joins three
    things: the mounted setup named by `setup_id`, the certified heat named by
    `wire_lot_id`, and the design named by `design_id`, together with `planned_pieces`,
    the number of pieces the run is scheduled to coil, which must be greater than zero."
    PRD §3.7: "On success the reservation moves mass without creating any:
    `wire_reserved_kg` is subtracted from the heat's `on_hand_kg` and added to its
    `reserved_kg`, leaving `received_kg` untouched."

    Design: Corner/errors/run_create_against_an_unknown_wire_heat_is_not_found
    """
    # The setup is ACTIVE, the design is released and a CERTIFIED heat of the design's
    # own grade holds plenty of wire — every gate the ladder ranks below the heat lookup
    # would pass. Only the wire_lot_id is unresolvable.
    world = X.certified_wire_world(api)

    response = api.create_run(
        F.run_payload(world.setup_id, NON_EXISTENT_UUID, world.design_id),
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(response, ERR_WIRE_LOT_NOT_FOUND, 404)

    runs, meta = validate_paginated(api.list_runs(PROCESS_TECHNICIAN_HEADERS))
    assert meta["total_count"] == 0, (
        f"no run may be opened on a heat that does not exist, got "
        f"{meta['total_count']}"
    )
    assert runs == [], "the refused opening coils nothing"

    heat = X.refresh_wire_lot(api, world.wire_lot_id)
    assert heat["reserved_kg"] == 0, (
        f"the real heat holds no reservation for a run that was never opened, got "
        f"{heat['reserved_kg']}"
    )
    assert heat["on_hand_kg"] == heat["received_kg"], (
        f"all received mass is still free in the rack: {heat['on_hand_kg']} of "
        f"{heat['received_kg']}"
    )

    setup = X.refresh_setup(api, world.setup_id)
    assert setup["setup_status"] == C.SETUP_ACTIVE, (
        f"the mounted setup stays ACTIVE, got {setup['setup_status']}"
    )

    machine = X.refresh_machine(api, world.machine_id)
    assert machine["machine_state"] == C.MACHINE_SETUP, (
        f"the coiler never leaves SETUP for PRODUCTION, got "
        f"{machine['machine_state']}"
    )
