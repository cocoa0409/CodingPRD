"""
Who may act, and what the plant looks like when the wrong badge is presented.

The seven roles of this shop are deliberately non-overlapping: the engineer who
draws a spring may not decide it, the manager who decides it may not redraw it,
the technician who runs the coiler holds no quality authority, the inspector who
measures may neither open nor close a run, the commercial manager files the
approval package but does not grant it, and the plant administrator — who owns
the coilers, the ovens and the clock — can neither engineer nor sell. The buying
organisation acts as itself: its identifier is a customer program, so its refusals
come in two layers, a plain role refusal on a plant-internal listing it may not
call at all and an ownership refusal on a row that belongs to somebody else's
program. Every test here checks the refusal and then the state the refusal was
supposed to protect, because a rejection that still moved a row is worse than no
rejection at all.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_PROGRAM_OWNERSHIP_MISMATCH,
    ERR_SELF_DISPOSITION_FORBIDDEN,
    ERR_UNAUTHORIZED,
)
from test_helpers.test_users import (
    DESIGN_ENGINEER_HEADERS,
    ENGINEERING_MANAGER_HEADERS,
    PLANT_ADMIN_HEADERS,
    PROCESS_TECHNICIAN_HEADERS,
    PROGRAM_MANAGER_HEADERS,
    QUALITY_INSPECTOR_ALT_HEADERS,
    QUALITY_INSPECTOR_HEADERS,
    QUALITY_INSPECTOR_THIRD_HEADERS,
    make_customer_representative_headers,
)

# The second program of the ownership scenarios: a different buying organisation
# on different commercial terms, so nothing but the identifier can be confused.
_SECOND_PROGRAM = dict(
    program_code="PGM-2",
    customer_name="Thicket Motorworks",
    application_class=C.CLASS_AUTOMOTIVE_SAFETY,
    ppap_level=3,
    committed_pieces=120_000,
    minimum_order_quantity=2_000,
    amortization_method=C.ACTUAL_BASIS,
)

# The outer-diameter characteristic of the two-inspector first article: a tenth of
# a millimetre tighter on each side than the free-length print.
_OUTER_DIAMETER_PLAN = dict(
    char_code=C.CHAR_OUTER_DIAMETER,
    nominal_value=20.0,
    lsl=19.8,
    usl=20.2,
)
_OUTER_DIAMETER_SUBGROUP = [19.95, 20.0, 20.05]


def test_design_engineer_may_not_render_the_engineering_verdict(api: ApiClient) -> None:
    """The author submits the design for review and stops there.

    The engineer who drew D1 puts it in front of engineering and then tries to
    approve his own prototype. The verdict is an engineering manager's act, so the
    request never reaches the fatigue floor or the segregation-of-duties gate: the
    design is still sitting in `ENG_REVIEW` with no reviewer recorded, and the
    program still has no granted approval on file.

    PRD §2.1: "If both headers are well formed but the named role is not among the roles authorised for the requested endpoint in section 4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "`DesignEngineer` owns the engineering record — material specifications, spring and wire-form designs, the statistical-process-control plan of critical characteristics, and revisions."
    PRD §2.1: "It may submit a design for review but may never decide one."
    PRD §3.3: "Submitting for review advances the design `DRAFT → ENG_REVIEW` and is the author's own act."
    PRD §3.3: "The engineering verdict belongs to an `EngineeringManager` and is delivered as a `decision` of either `APPROVE_PROTOTYPE` or `REJECT`."
    PRD §3.3: "Both branches stamp `reviewed_by_user_id` with the reviewer's `X-User-ID`."
    PRD §3.3: "When it passes, the design moves `ENG_REVIEW → PROTOTYPE_RELEASED` and the program's `delivery_posture` is re-derived."
    PRD §3.1: "If no submission of the program is in either granted status, the posture is `BLOCKED`."
    PRD §4: "Roles are exhaustive: a role absent from an endpoint's list receives `ERR_UNAUTHORIZED`."
    Design: Corner/rbac/design_engineer_rendering_an_engineering_verdict_unauthorized
    """
    world = X.draft_design_world(api)
    get_success_data(
        api.submit_design_for_review(world.design_id, DESIGN_ENGINEER_HEADERS)
    )

    response = api.review_design(
        world.design_id,
        {"decision": C.DECISION_APPROVE_PROTOTYPE},
        DESIGN_ENGINEER_HEADERS,
    )
    validate_error(response, ERR_UNAUTHORIZED, 403)

    design = X.refresh_design(api, world.design_id)
    assert design["release_status"] == C.RELEASE_ENG_REVIEW, (
        "the design stays in ENG_REVIEW because no authorised verdict landed"
    )
    assert design["reviewed_by_user_id"] is None, (
        "reviewed_by_user_id is stamped by the verdict, which was refused"
    )

    program = X.refresh_program(api, world.program_id)
    assert program["delivery_posture"] == C.POSTURE_BLOCKED, (
        "no granted approval is on file, so the program's posture stays BLOCKED"
    )


def test_engineering_manager_may_not_author_a_revision(api: ApiClient) -> None:
    """The deciding authority cannot pull the design back to the drawing board.

    The manager holds a current `expected_design_version`, so the optimistic
    concurrency guard would have passed, and asks for ten active coils instead of
    eight. Cutting a revision is reserved to a design engineer, so nothing is
    recalculated: the coil count is still eight, the spring rate is still 9.031
    N/mm, and the design row has not advanced its revision counter or its version.

    PRD §2.1: "If both headers are well formed but the named role is not among the roles authorised for the requested endpoint in section 4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "`EngineeringManager` is the independent engineering authority: it decides designs against the program's fatigue-margin floor, retires designs, and capitalises tooling; it may neither author nor revise a design."
    PRD §3.3: "Either can be pulled back to the drawing board by cutting a **revision**, an act reserved to a `DesignEngineer`."
    PRD §3.3: "An accepted revision does the following bookkeeping: `superseded_revision_no` is set to the value `current_revision_no` held before the revision, `current_revision_no` is increased by 1, `release_status` returns to `DRAFT`, `reviewed_by_user_id` is cleared to null, and `created_by_user_id` is re-stamped with the revising engineer's `X-User-ID` — so the segregation-of-duties gate on the next review is measured against whoever cut the latest revision."
    PRD §3.3: "Every computed engineering field is then recalculated from the post-revision geometry: spring rate, all four stress fields, the fatigue criterion and margin, the life tier, the per-piece wire mass, and the tangle-risk index and class."
    PRD §3.2: "The value written to `spring_rate_n_per_mm` is that megapascal shear modulus multiplied by the wire diameter raised to the fourth power, divided by the product of eight, the mean coil diameter cubed, and the active coil count, with the result rounded half up to three decimal places."
    PRD §4: "Roles are exhaustive: a role absent from an endpoint's list receives `ERR_UNAUTHORIZED`."
    Design: Corner/rbac/engineering_manager_authoring_a_revision_unauthorized
    """
    world = X.build_world(api, "prototype")
    before = world.design

    response = api.revise_design(
        world.design_id,
        F.revision_payload(world.design_version, active_coils=10),
        ENGINEERING_MANAGER_HEADERS,
    )
    validate_error(response, ERR_UNAUTHORIZED, 403)

    design = X.refresh_design(api, world.design_id)
    assert design["active_coils"] == 8, (
        "the geometry the refused revision asked for was never written"
    )
    assert design["spring_rate_n_per_mm"] == C.D1_SPRING_RATE, (
        "no engineering field is recalculated when the revision is refused"
    )
    assert design["release_status"] == C.RELEASE_PROTOTYPE, (
        "an accepted revision would have returned the design to DRAFT"
    )
    assert design["current_revision_no"] == 1, (
        "current_revision_no is increased only by an accepted revision"
    )
    assert design["version"] == world.design_version, (
        "nothing was mutated, so the design's version counter did not move"
    )
    assert design == before, (
        "the refused revision left the design row exactly as it stood"
    )


def test_process_technician_may_not_measure_the_first_article(api: ApiClient) -> None:
    """The technician at the coiler cannot sign off his own first piece.

    The run is open and waiting on its first article, and the technician who set it
    up offers the three free-length readings himself. Measurement is quality's act,
    so no inspection record exists afterwards and the run is still at rest on both
    axes: `FAI_PENDING`, disposition `PENDING`, and no observed capability at all.

    PRD §2.1: "If both headers are well formed but the named role is not among the roles authorised for the requested endpoint in section 4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "`ProcessTechnician` runs the floor: booking and activating coiling setups, opening, completing and cancelling production runs, scheduling, charging, discharging and cancelling stress-relief batches, and packing finished lots; it holds no quality authority."
    PRD §3.7: "A `QualityInspector` records a first-article subgroup against one characteristic of the run's design, supplying the `characteristic_id` and `measurements`, an array of numbers in measurement order."
    PRD §3.7: "It also stamps `inspected_by_user_id` with the inspector's `X-User-ID`, which is what makes the segregation gate on the verdict possible."
    PRD §3.7: "A newly opened run starts on both axes at rest — `process_status` `FAI_PENDING`, `quality_status` `OPEN`, `fai_disposition` `PENDING`, `heat_treat_state` `NOT_STARTED`, `peening_verified` false, `produced_pieces` and `scrapped_pieces` at 0, `wire_consumed_kg` at 0.000, and both `min_cpk_observed` and `min_ppk_observed` null."
    PRD §4: "Roles are exhaustive: a role absent from an endpoint's list receives `ERR_UNAUTHORIZED`."
    Design: Corner/rbac/process_technician_measuring_a_first_article_unauthorized
    """
    world = X.run_world(api)

    response = api.record_fai(
        world.run_id,
        F.measurement_payload(world.characteristic_id),
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(response, ERR_UNAUTHORIZED, 403)

    records, meta = validate_paginated(
        api.list_inspection_records(
            QUALITY_INSPECTOR_HEADERS, params={"run_id": world.run_id}
        )
    )
    assert meta["total_count"] == 0, (
        "the refused subgroup was never filed as an inspection record"
    )
    assert records == [], "no measurement exists for this run"

    run = X.refresh_run(api, world.run_id)
    assert run["process_status"] == C.PROCESS_FAI_PENDING, (
        "the run is still waiting for a first article from an inspector"
    )
    assert run["fai_disposition"] == C.FAI_PENDING, (
        "no first-article verdict is reachable without a measurement"
    )
    assert run["min_cpk_observed"] is None, (
        "min_cpk_observed is refreshed by an accepted measurement, and none landed"
    )
    assert run["min_ppk_observed"] is None, (
        "the run keeps the null pooled capability it opened with"
    )


def test_quality_inspector_may_not_complete_a_run(api: ApiClient) -> None:
    """The inspector who cleared the first article cannot close the run.

    The first article is accepted and the coiler is making springs, so the only
    thing standing between the inspector and a closed run is the role table. The
    refusal leaves the whole conserved wire ledger where it was: the run still
    holds its 567.334 kg reservation with nothing consumed, the heat still shows
    232.666 kg on hand against that reservation, and the setup is still `ACTIVE`
    on a coiler still in production.

    PRD §2.1: "If both headers are well formed but the named role is not among the roles authorised for the requested endpoint in section 4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "`QualityInspector` owns incoming wire certification, first-article and in-process measurement, both dispositions, and lot quarantine and release; it may neither open nor complete a run."
    PRD §3.7: "A `ProcessTechnician` completes a `RUNNING` run by supplying `produced_pieces` and `scrapped_pieces`."
    PRD §3.7: "On success both counts are recorded and `process_status` becomes `COMPLETE`."
    PRD §3.7: "Consumption is then computed as the design's stored six-decimal `wire_mass_per_piece_kg` multiplied by the sum of `produced_pieces` and `scrapped_pieces` — scrap burns wire exactly like good product does — rounded half up to three decimal places, and written to `wire_consumed_kg`."
    PRD §3.7: "The run's setup transitions `ACTIVE → RELEASED`, and the coiler returns `PRODUCTION → IDLE` with `active_setup_id` cleared and `version` increased by 1."
    PRD §3.7: "Start from the design's **stored** `wire_mass_per_piece_kg`, already rounded to six decimal places."
    PRD §3.7: "Multiply it by `planned_pieces`."
    PRD §3.7: "Inflate that product by a scrap allowance of three percent — that is, multiply by one plus 0.03."
    PRD §3.7: "Round the result half up to three decimal places, once, at the very end."
    PRD §3.7: "On success the reservation moves mass without creating any: `wire_reserved_kg` is subtracted from the heat's `on_hand_kg` and added to its `reserved_kg`, leaving `received_kg` untouched."
    PRD §4: "Roles are exhaustive: a role absent from an endpoint's list receives `ERR_UNAUTHORIZED`."
    Design: Corner/rbac/quality_inspector_closing_a_run_unauthorized
    """
    world = X.running_run_world(api)

    response = api.complete_run(
        world.run_id, F.completion_payload(), QUALITY_INSPECTOR_HEADERS
    )
    validate_error(response, ERR_UNAUTHORIZED, 403)

    run = X.refresh_run(api, world.run_id)
    assert run["process_status"] == C.PROCESS_RUNNING, (
        "only a technician's completion moves the run to COMPLETE"
    )
    assert run["produced_pieces"] == 0, "no piece counts were recorded"
    assert run["scrapped_pieces"] == 0, "no piece counts were recorded"
    assert run["wire_reserved_kg"] == 567.334, (
        "the reservation the run opened with is untouched"
    )
    assert run["wire_consumed_kg"] == 0.0, (
        "consumption is computed by completion, which was refused"
    )

    heat = X.refresh_wire_lot(api, world.wire_lot_id)
    assert heat["reserved_kg"] == 567.334, "the heat still carries the reservation"
    assert heat["on_hand_kg"] == 232.666, "no kilogram came back to the shelf"
    assert heat["consumed_kg"] == 0.0, "nothing was burned"
    assert heat["received_kg"] == 800.0, "received_kg is conserved throughout"

    setup = X.refresh_setup(api, world.setup_id)
    assert setup["setup_status"] == C.SETUP_ACTIVE, (
        "the setup is released only when its run reaches COMPLETE"
    )

    machine = X.refresh_machine(api, world.machine_id)
    assert machine["machine_state"] == C.MACHINE_PRODUCTION, (
        "the coiler returns to IDLE only on completion"
    )
    assert machine["active_setup_id"] == world.setup_id, (
        "the coiler is still occupied by this setup"
    )


def test_program_manager_may_not_render_the_customer_verdict(api: ApiClient) -> None:
    """The manager who filed the package cannot grant it on the customer's behalf.

    The PPAP package is on the customer's desk in `SUBMITTED`, and the program
    manager tries to sign `APPROVE` himself. The verdict is the buying
    organisation's alone, so the four-hop release cascade never starts: the
    submission is still open and undecided, the design is still only
    `PROTOTYPE_RELEASED`, the tool is still `PENDING` with no basis frozen, and the
    quote is still open for repricing.

    PRD §2.1: "If both headers are well formed but the named role is not among the roles authorised for the requested endpoint in section 4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "`ProgramManager` owns the commercial record: opening programs, pricing and freezing quotes, filing production-part approval packages, allocating, shipping and taking back lots."
    PRD §2.1: "`CustomerRepresentative` is the buying organisation acting as itself and is the sole holder of the production-part approval verdict."
    PRD §3.10: "The verdict belongs to the `CustomerRepresentative` alone, and only for its own program: because that role is entity-backed, its `X-User-ID` must equal the submission's `program_id` or the request is refused with `ERR_PROGRAM_OWNERSHIP_MISMATCH`."
    PRD §3.10: "Every verdict stamps `reviewed_by_program_id` from the header and `decided_at` from the logical clock, and every verdict re-derives the program's `delivery_posture`."
    PRD §3.10: "Hop one sets `submission_status` to `APPROVED`, a terminal status."
    PRD §3.10: "Hop two promotes the design `PROTOTYPE_RELEASED → PRODUCTION_RELEASED`."
    PRD §3.10: "Hop three, fired by that promotion, takes every `PENDING` tooling asset of the design to `AMORTIZING`, freezing `amortization_basis_pieces` from the program's `committed_pieces` and `amort_per_piece_cents` as the cost divided by that basis rounded up."
    PRD §3.4: "Both `amortization_basis_pieces` and `amort_per_piece_cents` stay null: until the customer has granted full approval, nobody knows over how many pieces the tool will be recovered."
    PRD §3.1: "If no submission of the program is in either granted status, the posture is `BLOCKED`."
    PRD §4: "Roles are exhaustive: a role absent from an endpoint's list receives `ERR_UNAUTHORIZED`."
    Design: Corner/rbac/program_manager_rendering_the_ppap_verdict_unauthorized
    """
    world = X.submitted_world(api)

    response = api.review_submission(
        world.submission_id,
        {"decision": C.DECISION_APPROVE},
        PROGRAM_MANAGER_HEADERS,
    )
    validate_error(response, ERR_UNAUTHORIZED, 403)

    submission = X.refresh_submission(api, world.submission_id)
    assert submission["submission_status"] == C.SUBMISSION_SUBMITTED, (
        "the package is still waiting on the customer"
    )
    assert submission["reviewed_by_program_id"] is None, (
        "reviewed_by_program_id is stamped by a verdict, and none was rendered"
    )
    assert submission["decided_at"] is None, (
        "decided_at is stamped by a verdict, and none was rendered"
    )

    design = X.refresh_design(api, world.design_id)
    assert design["release_status"] == C.RELEASE_PROTOTYPE, (
        "hop two of the approval cascade never fired"
    )

    tool = X.refresh_tooling(api, world.tooling_id)
    assert tool["amortization_status"] == C.AMORT_PENDING, (
        "hop three arms the ledger, and the cascade never started"
    )
    assert tool["amortization_basis_pieces"] is None, (
        "no basis is frozen until full approval is granted"
    )
    assert tool["amort_per_piece_cents"] is None, (
        "no per-piece figure is frozen until full approval is granted"
    )

    program = X.refresh_program(api, world.program_id)
    assert program["quote_frozen"] is False, "hop four never fired"
    assert program["delivery_posture"] == C.POSTURE_BLOCKED, (
        "no submission of the program is in a granted status"
    )


def test_plant_admin_may_not_open_a_customer_program(api: ApiClient) -> None:
    """The asset custodian owns the coilers and the clock, not the order book.

    With one program already on the books, the plant administrator tries to open a
    second one and is refused: the role is not an override. The same administrator
    then does its own two jobs in the same test — commissioning a coiler, which
    answers 201 with a fresh idle machine, and advancing the logical clock — so the
    refusal is clearly about the endpoint and not about the badge being broken.

    PRD §2.1: "If both headers are well formed but the named role is not among the roles authorised for the requested endpoint in section 4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "`PlantAdmin` is the asset and infrastructure custodian: it commissions coilers and stress-relief ovens and drives the logical clock."
    PRD §2.1: "`PlantAdmin` is deliberately **not** a superset of the other roles — it can neither engineer, run, inspect nor sell, and an attempt to use it as an override answers `ERR_UNAUTHORIZED`."
    PRD §3.1: "Everything downstream hangs off a **customer program**, which a `ProgramManager` opens by declaring who is buying and on what terms."
    PRD §3.6: "A `PlantAdmin` commissions each computer-controlled coiler with a `machine_code` unique across all machines, a `max_wire_diameter_mm` greater than zero giving the largest wire the coiler can form, and `changeover_buffer_minutes`, the whole number of minutes of tooling changeover that must separate two setup windows on this machine, which must be at least 0."
    PRD §3.6: "A new coiler opens in `machine_state` `IDLE` with `active_setup_id` null."
    PRD §2.5: "A `PlantAdmin` advances it by supplying a `to_iso8601` instant to the clock-setting endpoint; the clock is monotonic, so a requested instant earlier than the current reading is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422) and the clock is left untouched."
    PRD §4: "Creation endpoints return HTTP 201 with the new resource; reads, lists and state-changing operations on an existing resource return HTTP 200 with the affected resource."
    PRD §4: "Roles are exhaustive: a role absent from an endpoint's list receives `ERR_UNAUTHORIZED`."
    Design: Corner/rbac/plant_admin_opening_a_customer_program_unauthorized
    """
    X.open_program(api)

    response = api.create_program(
        F.program_payload(**_SECOND_PROGRAM), PLANT_ADMIN_HEADERS
    )
    validate_error(response, ERR_UNAUTHORIZED, 403)

    programs, meta = validate_paginated(api.list_programs(PROGRAM_MANAGER_HEADERS))
    assert meta["total_count"] == 1, "the refused program was never opened"
    assert programs[0]["program_code"] == C.CANONICAL_PROGRAM_CODE, (
        "only the manager's own program is on the books"
    )

    machine = validate_success(
        api.create_machine(F.machine_payload(), PLANT_ADMIN_HEADERS), 201
    )
    assert machine["machine_state"] == C.MACHINE_IDLE, (
        "the administrator's own commissioning endpoint still answers it"
    )
    assert machine["active_setup_id"] is None, "a new coiler is unoccupied"

    validate_success(
        api.set_clock(F.clock_payload(C.CLOCK_SETUP_DAY_START), PLANT_ADMIN_HEADERS)
    )


def test_customer_representative_may_not_list_production_runs(api: ApiClient) -> None:
    """The buyer is refused the shop floor outright, not scoped down to its own rows.

    The production-run listing is plant-internal, and the refusal is the plain role
    refusal at the second rung of the rejection ladder rather than the ownership
    refusal at the third — the buyer is not a customer looking at somebody else's
    run, it is a caller with no business on that endpoint at all. The listings and
    reads the buyer is entitled to still answer for it in the same test.

    PRD §2.1: "If both headers are well formed but the named role is not among the roles authorised for the requested endpoint in section 4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "`CustomerRepresentative` is the buying organisation acting as itself and is the sole holder of the production-part approval verdict."
    PRD §2.1: "Ownership checks on any resource that references a `CustomerProgram` compare the resource's program foreign-key field to `X-User-ID`: a customer representative may read only its own program, only the designs whose `program_id` is its own program, only the qualification submissions and shipment lots whose `program_id` is its own program, and may decide only qualification submissions filed against its own program."
    PRD §2.8: "`ERR_UNAUTHORIZED` — role not authorised for the endpoint, on every endpoint."
    PRD §2.8: "`ERR_PROGRAM_OWNERSHIP_MISMATCH` — customer-representative ownership, on every endpoint a `CustomerRepresentative` may call."
    PRD §4: "Roles are exhaustive: a role absent from an endpoint's list receives `ERR_UNAUTHORIZED`."
    Design: Corner/rbac/customer_representative_reading_a_plant_internal_listing_unauthorized
    """
    world = X.running_run_world(api)

    response = api.list_runs(world.customer)
    validate_error(response, ERR_UNAUTHORIZED, 403)

    filtered = api.list_runs(world.customer, params={"design_id": world.design_id})
    validate_error(filtered, ERR_UNAUTHORIZED, 403)

    lots, lot_meta = validate_paginated(api.list_lots(world.customer))
    assert lot_meta["total_count"] == 0, (
        "the buyer may call the lot listing, and its own program has shipped nothing yet"
    )
    assert lots == [], "an authorised listing answers a page, not a refusal"

    program = validate_success(api.get_program(world.program_id, world.customer))
    assert program["id"] == world.program_id, (
        "the buyer reads its own program through the same identity"
    )


def test_customer_representative_reading_another_programs_lot_hits_the_ownership_gate(
    api: ApiClient,
) -> None:
    """A second buyer asks for a lot that belongs to the first one.

    Both callers present a perfectly valid customer identity and both are allowed
    on the shipment-lot read, so the refusal cannot be the role gate: the second
    buyer's `X-User-ID` is its own program's `id`, which is not the lot's
    `program_id`, and that is an ownership refusal. The owning buyer reads the very
    same lot successfully a moment later, which is what makes the refusal
    specifically about ownership.

    PRD §2.1: "When `X-User-Role` is `CustomerRepresentative`, `X-User-ID` is the `id` of the acting `CustomerProgram`."
    PRD §2.1: "Ownership checks on any resource that references a `CustomerProgram` compare the resource's program foreign-key field to `X-User-ID`: a customer representative may read only its own program, only the designs whose `program_id` is its own program, only the qualification submissions and shipment lots whose `program_id` is its own program, and may decide only qualification submissions filed against its own program."
    PRD §2.1: "Any customer-representative request that targets a program, design, submission or lot belonging to a different program is rejected with `ERR_PROGRAM_OWNERSHIP_MISMATCH` (HTTP 403)."
    PRD §2.8: "`ERR_PROGRAM_OWNERSHIP_MISMATCH` — customer-representative ownership, on every endpoint a `CustomerRepresentative` may call."
    PRD §3.11: "A lot that survives all of that opens in `lot_status` `ALLOCATED` with `packaging_method` null, and it snapshots the commercial terms at creation: `unit_price_cents` from the program's `quoted_unit_price_cents`, `tooling_amort_per_piece_cents` from the program's `quoted_tooling_amort_per_piece_cents`, and `extended_price_cents` as `piece_count` multiplied by `unit_price_cents`."
    Design: Corner/rbac/customer_representative_reading_another_programs_lot_hits_the_ownership_gate
    """
    world = X.allocated_world(api)
    intruder = X.open_program(api, **_SECOND_PROGRAM)
    intruder_headers = make_customer_representative_headers(intruder["id"])

    response = api.get_lot(world.lot_id, intruder_headers)
    validate_error(response, ERR_PROGRAM_OWNERSHIP_MISMATCH, 403)

    intruder_lots, intruder_meta = validate_paginated(api.list_lots(intruder_headers))
    assert intruder_meta["total_count"] == 0, (
        "the second buyer sees only lots of its own program, and it has none"
    )
    assert intruder_lots == [], "another program's lot is not the intruder's to read"

    owned = validate_success(api.get_lot(world.lot_id, world.customer))
    assert owned["id"] == world.lot_id, "the owning buyer reads the same lot"
    assert owned["program_id"] == world.program_id, (
        "the lot's program foreign key is what the ownership check compares"
    )
    assert owned["piece_count"] == 1_000, "the lot is unchanged by the refused read"
    assert owned["lot_status"] == C.LOT_ALLOCATED, "the lot is still on the dock"


def test_customer_representative_reads_the_amortization_of_its_own_program(
    api: ApiClient,
) -> None:
    """The buyer is entitled to the tooling arithmetic on its own program.

    Approval has frozen the tool over the program's 500 000 committed pieces, so a
    hypothetical thousand-piece lot recovers 10 000 cents on the forecast basis
    while the accelerated variant on the same numbers would take 14 400 — and the
    buying organisation, reading with its own program's identity, is shown both
    figures side by side alongside the live ledger.

    PRD §2.1: "When `X-User-Role` is `CustomerRepresentative`, `X-User-ID` is the `id` of the acting `CustomerProgram`."
    PRD §2.1: "Ownership checks on any resource that references a `CustomerProgram` compare the resource's program foreign-key field to `X-User-ID`: a customer representative may read only its own program, only the designs whose `program_id` is its own program, only the qualification submissions and shipment lots whose `program_id` is its own program, and may decide only qualification submissions filed against its own program."
    PRD §3.4: "A computed read on the program exposes them side by side for a hypothetical lot of a stated `piece_count`, returning the program's own `amortization_method`, the `tooling_asset_id` of the newest tooling asset by `created_at` for the program's most recently quoted design, that tool's `original_cost_cents`, `recovered_cents` and `unamortized_cents`, the program's live `open_commitment_pieces`, and then both hypothetical figures: `forecast_basis_recovery_cents` and `actual_basis_recovery_cents`."
    PRD §3.4: "Under `FORECAST_BASIS` — a straight-line forecast recovery — the amount is the lot's `piece_count` multiplied by the tool's frozen `amort_per_piece_cents`, capped at the tool's live `unamortized_cents`; whichever of the two is smaller is posted."
    PRD §3.4: "Under `ACTUAL_BASIS` — an accelerated declining recovery — the amount starts from the tool's live `unamortized_cents` multiplied by an acceleration factor of 1.5, multiplied by the lot's `piece_count`, divided by the program's `open_commitment_pieces` (or by 1 if that figure is zero or lower, so the division is always defined), rounded **up** toward positive infinity to a whole cent, and then capped at the tool's live `unamortized_cents`; again the smaller of the two is posted."
    PRD §3.10: "Hop three, fired by that promotion, takes every `PENDING` tooling asset of the design to `AMORTIZING`, freezing `amortization_basis_pieces` from the program's `committed_pieces` and `amort_per_piece_cents` as the cost divided by that basis rounded up."
    Design: Corner/rbac/customer_representative_reads_the_amortization_of_its_own_program
    """
    world = X.approved_world(api)

    view = validate_success(
        api.get_tooling_amortization(
            world.program_id, world.customer, params={"piece_count": 1_000}
        )
    )
    assert view["amortization_method"] == C.FORECAST_BASIS, (
        "the program's own method leads the computed read"
    )
    assert view["tooling_asset_id"] == world.tooling_id, (
        "the newest tool of the program's design is the one consulted"
    )
    assert view["original_cost_cents"] == 4_800_000
    assert view["recovered_cents"] == 0, "nothing has shipped yet"
    assert view["unamortized_cents"] == 4_800_000, "the whole tool is still outstanding"
    assert view["open_commitment_pieces"] == 500_000, "the live commitment ledger"
    assert view["forecast_basis_recovery_cents"] == 10_000, (
        "1 000 pieces at the frozen 10 cents a piece"
    )
    assert view["actual_basis_recovery_cents"] == 14_400, (
        "the accelerated variant on the same outstanding balance"
    )


def test_first_article_disposition_excludes_every_measuring_inspector(
    api: ApiClient,
) -> None:
    """Two inspectors measured, so neither of them may judge — not just the later one.

    Free length is measured by the first inspector and outer diameter by the
    second, which is exactly the case a shortcut implementation gets wrong by
    remembering only the most recent measurer. Both are refused with the
    self-disposition error while the run is still open on both of the earlier
    gates, and only a third inspector who touched nothing can accept: the run then
    walks to `RUNNING` carrying the lower of the two short-run capabilities, 1.333
    from the tighter outer-diameter band, with the pooled figure still null because
    no in-process subgroup exists.

    PRD §3.7: "A second `QualityInspector` closes out the first article with a `decision` of either `ACCEPT` or `REJECT`."
    PRD §3.7: "Both branches enforce exactly the same five gates, in this order: the run's `process_status` must be `FAI_PENDING`, otherwise `ERR_RUN_INVALID_STATE`; `fai_disposition` must still be `PENDING`, otherwise `ERR_FAI_ALREADY_DISPOSITIONED` (HTTP 409); the acting `X-User-ID` must not match the `inspected_by_user_id` of any first-article record on this run, otherwise `ERR_SELF_DISPOSITION_FORBIDDEN` (HTTP 409) — whoever measured may not judge; the run's design must have at least one critical characteristic, otherwise `ERR_CHARACTERISTIC_SET_EMPTY` (HTTP 422); and every critical characteristic of that design must have at least one first-article record on this run, otherwise `ERR_INCOMPLETE_FAI_COVERAGE` (HTTP 422)."
    PRD §3.7: "It also stamps `inspected_by_user_id` with the inspector's `X-User-ID`, which is what makes the segregation gate on the verdict possible."
    PRD §3.7: "`ACCEPT` sets `fai_disposition` to `ACCEPTED` and advances the run `FAI_PENDING → RUNNING`, and nothing else moves."
    PRD §3.7: "`sigma_value` is the Bessel-corrected sample standard deviation: take each measurement's deviation from the **unrounded** mean, square it, sum the squares, divide by one less than the subgroup size, take the square root, and round half up to six decimal places."
    PRD §3.7: "`cpk_value` is the short-run capability of this subgroup: take the characteristic's `usl` minus the unrounded mean, and the unrounded mean minus the characteristic's `lsl`, keep whichever of those two distances is **smaller**, divide it by three times the unrounded standard deviation, and round half up to three decimal places."
    PRD §3.7: "`ppk_value` is the pooled long-run capability and is **null on every first-article record**."
    PRD §3.7: "At the run level, `min_cpk_observed` is refreshed to the lowest `cpk_value` across all of the run's inspection records, while `min_ppk_observed` is refreshed to the lowest `ppk_value` across only those of the run's records whose `record_kind` is `SPC` and whose characteristic has `is_safety_critical` true."
    PRD §3.7: "First-article records therefore move `min_cpk_observed` but leave `min_ppk_observed` untouched."
    Design: Corner/rbac/first_article_disposition_excludes_every_measuring_inspector_not_only_the_last
    """
    world = X.build_world(
        api, "run", characteristics=[{}, dict(_OUTER_DIAMETER_PLAN)]
    )
    free_length, outer_diameter = world.characteristics

    first = X.record_fai_subgroup(
        api, world.run_id, free_length, headers=QUALITY_INSPECTOR_HEADERS
    )
    second = X.record_fai_subgroup(
        api,
        world.run_id,
        outer_diameter,
        measurements=_OUTER_DIAMETER_SUBGROUP,
        headers=QUALITY_INSPECTOR_ALT_HEADERS,
    )
    assert first["cpk_value"] == 3.333, "the free-length subgroup is comfortably capable"
    assert second["cpk_value"] == 1.333, (
        "the tighter outer-diameter band binds at three sigma"
    )
    assert first["ppk_value"] is None, "no first-article record carries a pooled figure"
    assert second["ppk_value"] is None, "no first-article record carries a pooled figure"

    # Both refusals are taken while the run is still FAI_PENDING and undispositioned,
    # so the segregation gate is the first gate either caller can fail.
    for measurer in (QUALITY_INSPECTOR_HEADERS, QUALITY_INSPECTOR_ALT_HEADERS):
        refused = api.dispose_fai(
            world.run_id, {"decision": C.DECISION_ACCEPT}, measurer
        )
        validate_error(refused, ERR_SELF_DISPOSITION_FORBIDDEN, 409)
        held = X.refresh_run(api, world.run_id)
        assert held["process_status"] == C.PROCESS_FAI_PENDING, (
            "a refused verdict leaves the run waiting"
        )
        assert held["fai_disposition"] == C.FAI_PENDING, (
            "a refused verdict decides nothing"
        )

    accepted = validate_success(
        api.dispose_fai(
            world.run_id,
            {"decision": C.DECISION_ACCEPT},
            QUALITY_INSPECTOR_THIRD_HEADERS,
        )
    )
    assert accepted["fai_disposition"] == C.FAI_ACCEPTED, (
        "an inspector who measured nothing may judge"
    )
    assert accepted["process_status"] == C.PROCESS_RUNNING, (
        "ACCEPT advances the run FAI_PENDING to RUNNING"
    )
    assert accepted["quality_status"] == C.QUALITY_OPEN, (
        "and nothing else moves on the quality axis"
    )
    assert accepted["min_cpk_observed"] == 1.333, (
        "the run carries the lowest cpk_value across its records"
    )
    assert accepted["min_ppk_observed"] is None, (
        "first-article records leave min_ppk_observed untouched"
    )
