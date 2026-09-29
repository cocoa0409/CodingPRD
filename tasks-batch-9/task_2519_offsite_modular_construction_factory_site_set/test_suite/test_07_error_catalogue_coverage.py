"""Every rejection the modular programme can hand back, provoked on purpose.

Ten disciplines write to this system and none of them trusts the others, so a
refusal has to say precisely which seam gave way: which entity the path could
not resolve, which of the two permitting authorities reached across into the
other's track, which uniqueness scope a repeated code broke, and which of the
three independent module dimensions was standing in the wrong state. The tests
below walk the plant, the design freeze chain, the permit ladder, the inspection
panel, the transport yard, the crane pad and the lender's draw book, and for
each guard they build exactly the situation that trips it — then check that the
refused request wrote nothing at all.
"""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_AGENCY_NOT_FOUND,
    ERR_CLAIM_NOT_ADJUDICABLE,
    ERR_CLAIM_NOT_ADJUDICATED,
    ERR_CLOCK_NOT_MONOTONIC,
    ERR_DEFECT_CLAIM_NOT_FOUND,
    ERR_DESIGN_NOT_SUBMITTABLE,
    ERR_DESIGN_PACKAGE_NOT_FOUND,
    ERR_DESIGN_REVIEW_IN_FLIGHT,
    ERR_DRAW_NOT_CERTIFIED,
    ERR_DRAW_NOT_FOUND,
    ERR_DRAW_SEQUENCE_GAP,
    ERR_DUPLICATE_CODE,
    ERR_DUPLICATE_MODULE_CODE,
    ERR_FACTORY_NOT_FOUND,
    ERR_FIELD_SCOPE_NOT_SIGNED_OFF,
    ERR_HOLD_NOT_ACTIVE,
    ERR_INSPECTION_NOT_FOUND,
    ERR_INSPECTION_NOT_PENDING,
    ERR_INVALID_SUPERSESSION,
    ERR_MODULE_ALREADY_LOADED,
    ERR_MODULE_NOT_FOUND,
    ERR_MODULE_NOT_ON_LINE,
    ERR_MODULE_NOT_PLANNED,
    ERR_MODULE_NOT_READY_TO_SET,
    ERR_MODULE_NOT_SLOTTED,
    ERR_NO_FROZEN_PACKAGE,
    ERR_PERMIT_ALREADY_DECIDED,
    ERR_PERMIT_NOT_FOUND,
    ERR_PERMIT_TRACK_ROLE_MISMATCH,
    ERR_PICK_RADIUS_OFF_CHART,
    ERR_PICK_WINDOW_INVALID,
    ERR_PROJECT_NOT_FOUND,
    ERR_QC_NOT_RELEASED,
    ERR_QC_STAGE_OUT_OF_ORDER,
    ERR_SET_SEQUENCE_VIOLATION,
    ERR_SHIPMENT_NOT_FOUND,
    ERR_SHIPMENT_NOT_LOADABLE,
    ERR_SURVEY_NOT_PENDING,
)
from test_helpers.assertions import (
    assert_cents,
    assert_instant,
    assert_module_dimensions,
)
from test_helpers.test_users import (
    AUTHORITY_HAVING_JURISDICTION,
    DESIGN_ENGINEER_SUBMITTER,
    LENDER_DRAW_ADMINISTRATOR,
    PROGRAM_ADMIN,
    STATE_PROGRAM_OFFICER,
    TRANSPORT_COORDINATOR,
    WARRANTY_ADJUDICATOR,
)


# ─── Unresolvable path identifiers ────────────────────────────────────────────
@pytest.mark.parametrize(
    "reader, expected_error",
    [
        ("get_factory", ERR_FACTORY_NOT_FOUND),
        ("get_agency", ERR_AGENCY_NOT_FOUND),
        ("get_project", ERR_PROJECT_NOT_FOUND),
        ("get_design_package", ERR_DESIGN_PACKAGE_NOT_FOUND),
        ("get_module", ERR_MODULE_NOT_FOUND),
        ("get_permit", ERR_PERMIT_NOT_FOUND),
        ("get_inspection", ERR_INSPECTION_NOT_FOUND),
        ("get_shipment", ERR_SHIPMENT_NOT_FOUND),
        ("get_defect_claim", ERR_DEFECT_CLAIM_NOT_FOUND),
        ("get_draw_request", ERR_DRAW_NOT_FOUND),
    ],
)
def test_an_unknown_identifier_names_the_entity_type_it_failed_to_resolve(
    api, reader, expected_error
):
    """PRD §2.5: "An unresolvable identifier produces the 404 that names the missing type: `ERR_FACTORY_NOT_FOUND`, `ERR_AGENCY_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_DESIGN_PACKAGE_NOT_FOUND`, `ERR_MODULE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_DEFECT_CLAIM_NOT_FOUND` or `ERR_DRAW_NOT_FOUND`."
    PRD §2.5: "Path identifiers are nevertheless resolved strictly left to right, and each is resolved before any body field is examined."

    Design: Corner/errors/every_path_id_error_in_the_catalog_is_triggerable
    """
    body = validate_error(
        getattr(api, reader)(NON_EXISTENT_UUID, PROGRAM_ADMIN), expected_error
    )

    assert body["message"], "a rejection must carry a human-readable message"


# ─── The bifurcated permit ladder rejects cross-track officers ────────────────
@pytest.fixture
def one_application_on_each_track(api):
    """A project with a state plan-review filing and a local foundation filing.

    Both applications sit in SUBMITTED, so either officer's decision would be a
    legal one on its own track.
    """
    world = fx.world_plant_and_project(api)
    applications = {
        "STATE_MODULAR_PROGRAM": get_success_data(
            api.create_permit(
                f.permit_payload(
                    world.project_id, "STATE_MODULAR_PROGRAM", "PLAN_REVIEW"
                ),
                PROGRAM_ADMIN,
            )
        ),
        "LOCAL_AHJ": get_success_data(
            api.create_permit(
                f.permit_payload(world.project_id, "LOCAL_AHJ", "FOUNDATION"),
                PROGRAM_ADMIN,
            )
        ),
    }
    return world, applications


@pytest.mark.parametrize(
    "track, officer",
    [
        ("LOCAL_AHJ", STATE_PROGRAM_OFFICER),
        ("STATE_MODULAR_PROGRAM", AUTHORITY_HAVING_JURISDICTION),
    ],
)
def test_neither_authority_may_decide_the_other_authoritys_application(
    one_application_on_each_track, track, officer
):
    """PRD §2.1: "Second, permit decisions are bifurcated by track: a `StateProgramOfficer` may decide only applications whose `track` is `STATE_MODULAR_PROGRAM`, and an `AuthorityHavingJurisdiction` only applications whose `track` is `LOCAL_AHJ`."
    PRD §2.1: "Both roles appear on the decision endpoint's role list, so a cross-track attempt passes the role check and is then rejected with `ERR_PERMIT_TRACK_ROLE_MISMATCH` (HTTP 403)."
    PRD §3.3: "A filed application starts in `status` `SUBMITTED` with `conditions_count` at 0, `insignia_count_issued` at 0, `pinned_package_id` null, `decided_at` and `decided_by_user_id` null, and `version` at 1."

    Design: Corner/errors/permit_track_role_mismatch_fires_in_both_directions
    """
    world, applications = one_application_on_each_track
    application = applications[track]

    validate_error(
        world.api.decide_permit(
            application["id"], f.permit_decision_payload("START_REVIEW"), officer
        ),
        ERR_PERMIT_TRACK_ROLE_MISMATCH,
    )

    untouched = validate_success(
        world.api.get_permit(application["id"], PROGRAM_ADMIN)
    )
    assert untouched["status"] == "SUBMITTED"
    assert untouched["decided_at"] is None
    assert untouched["decided_by_user_id"] is None
    assert untouched["version"] == 1


# ─── Two uniqueness scopes: global codes and per-project shop codes ───────────
def test_a_second_plant_may_not_reuse_an_existing_plant_code(api):
    """PRD §3.1: "A `ProgramAdmin` registers a volumetric modular plant by supplying its display `name` and a short plant `code` that must be globally unique across all plants; a repeated code is rejected with `ERR_DUPLICATE_CODE`."

    Design: Corner/errors/duplicate_code_and_duplicate_module_code_are_both_rejected
    """
    fx.set_clock(api)
    fx.create_factory(api)

    validate_error(
        api.create_factory(
            f.factory_payload(
                name="Impostor Plant",
                takt_minutes=60,
                station_count=3,
                parallel_station_capacity=1,
                wip_unit_value_cents=1000000,
            ),
            PROGRAM_ADMIN,
        ),
        ERR_DUPLICATE_CODE,
    )

    _, meta = validate_paginated(api.list_factories({}, PROGRAM_ADMIN))
    assert meta["total_count"] == 1, "the rejected registration must not persist a plant"


def test_a_second_inspection_agency_may_not_reuse_an_existing_agency_code(api):
    """PRD §3.1: "Each agency has a `name`, an `agency_code` that must be globally unique among agencies — a repeat again yielding `ERR_DUPLICATE_CODE` — and a non-empty `accredited_state_codes` array of two-character uppercase state codes naming the jurisdictions it may work in."

    Design: Corner/errors/duplicate_code_and_duplicate_module_code_are_both_rejected
    """
    fx.set_clock(api)
    fx.create_agency(api)

    validate_error(
        api.create_agency(
            f.agency_payload(
                name="Copycat Inspection",
                accredited_state_codes=["OR"],
                per_inspection_fee_cents=90000,
            ),
            PROGRAM_ADMIN,
        ),
        ERR_DUPLICATE_CODE,
    )

    _, meta = validate_paginated(api.list_agencies({}, PROGRAM_ADMIN))
    assert meta["total_count"] == 1, "the rejected registration must not persist an agency"


@pytest.fixture
def a_project_with_one_shop_module(api):
    """One module M-01 at set sequence position 1, against a DRAFT revision."""
    world = fx.world_plant_and_project(api)
    world.package = fx.create_design_package(
        api, world.project_id, world.project["version"]
    )
    world.modules["M-01"] = fx.create_module(
        api, world.project_id, world.package_id, world.factory_id, "M-01", 1
    )
    return world


@pytest.mark.parametrize(
    "module_code, set_sequence_index",
    [
        ("M-01", 2),
        ("M-02", 1),
    ],
)
def test_a_module_may_not_reuse_a_shop_code_or_a_set_position_of_its_project(
    a_project_with_one_shop_module, module_code, set_sequence_index
):
    """PRD §3.4: "A `FactoryProductionManager` creates a volumetric module against a frozen-or-otherwise design revision by supplying `project_id`, the `design_package_id` of the revision it is detailed against, a `module_code` shop code that must be unique within the project, and a `set_sequence_index` of at least 1 giving its position in the crane set order, which must also be unique within the project."
    PRD §3.4: "A repeat of either the code or the sequence position is rejected with `ERR_DUPLICATE_MODULE_CODE`."

    Design: Corner/errors/duplicate_code_and_duplicate_module_code_are_both_rejected
    """
    world = a_project_with_one_shop_module

    validate_error(
        world.api.create_module(
            f.module_payload(
                world.project_id,
                world.package_id,
                module_code,
                set_sequence_index,
            ),
            world.factory_manager,
        ),
        ERR_DUPLICATE_MODULE_CODE,
    )

    _, meta = validate_paginated(
        world.api.list_modules({"project_id": world.project_id}, PROGRAM_ADMIN)
    )
    assert meta["total_count"] == 1, "the rejected creation must not persist a module"


# ─── The logical clock is monotonic but not strictly monotonic ────────────────
def test_the_clock_accepts_being_reset_to_the_instant_it_already_holds(api):
    """PRD §2.10: "The clock never moves backwards: a `current_utc` that is less than the clock's present value is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422), while a value equal to the present value is accepted."

    Design: Corner/errors/clock_accepts_the_same_instant_but_never_moves_backwards
    """
    fx.set_clock(api, "2026-09-01T08:00:00Z")

    validate_success(api.set_clock(f.clock_payload("2026-09-01T08:00:00Z"), PROGRAM_ADMIN))

    plant = validate_success(api.create_factory(f.factory_payload(), PROGRAM_ADMIN), 201)
    assert_instant(plant["created_at"], "2026-09-01T08:00:00Z", "created_at")


def test_the_clock_refuses_to_step_one_second_into_the_past(api):
    """PRD §2.10: "The clock never moves backwards: a `current_utc` that is less than the clock's present value is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422), while a value equal to the present value is accepted."
    PRD §2.10: "The server owns a single logical clock and never consults wall-clock time."
    PRD §2.4: "`created_at` is the instant the row was first persisted, `updated_at` is the instant of the most recent mutation, and both are rendered as ISO 8601 UTC timestamps with exactly three fractional-second digits."

    Design: Corner/errors/clock_accepts_the_same_instant_but_never_moves_backwards
    """
    fx.set_clock(api, "2026-09-01T08:00:00Z")

    validate_error(
        api.set_clock(f.clock_payload("2026-09-01T07:59:59Z"), PROGRAM_ADMIN),
        ERR_CLOCK_NOT_MONOTONIC,
    )

    # The rejected attempt must not have rolled the clock back one second.
    plant = validate_success(api.create_factory(f.factory_payload(), PROGRAM_ADMIN), 201)
    assert_instant(plant["created_at"], "2026-09-01T08:00:00Z", "created_at")


# ─── Three guards on the design freeze track ──────────────────────────────────
@pytest.fixture
def a_revision_awaiting_its_reviewer(api):
    """Revision R1 submitted and sitting in IN_REVIEW, with no peer decision yet."""
    world = fx.world_plant_and_project(api)
    world.package = fx.create_design_package(
        api, world.project_id, world.project["version"]
    )
    world.package = get_success_data(
        api.submit_design_package(
            world.package_id, f.submit_payload(), DESIGN_ENGINEER_SUBMITTER
        )
    )
    return world


def test_a_revision_already_before_its_reviewer_cannot_be_submitted_again(
    a_revision_awaiting_its_reviewer,
):
    """PRD §3.2: "The package must be in `freeze_state` `DRAFT` or `REVISION_REQUIRED`; a submit against any other state is rejected with `ERR_DESIGN_NOT_SUBMITTABLE`."
    PRD §3.2: "Of the two, the in-flight check is evaluated first, so a package that is itself unsubmittable *and* whose sibling is under review reports the in-flight conflict."

    Design: Corner/errors/design_package_lifecycle_errors_are_triggerable
    """
    world = a_revision_awaiting_its_reviewer
    round_before = world.package["revision_round"]

    validate_error(
        world.api.submit_design_package(
            world.package_id,
            f.submit_payload(review_note="R1 again"),
            DESIGN_ENGINEER_SUBMITTER,
        ),
        ERR_DESIGN_NOT_SUBMITTABLE,
    )

    untouched = world.refresh_package()
    assert untouched["freeze_state"] == "IN_REVIEW"
    assert untouched["revision_round"] == round_before, (
        "a refused submit must not bump the revision round"
    )


def test_a_project_may_not_put_a_second_revision_before_the_reviewer(
    a_revision_awaiting_its_reviewer,
):
    """PRD §3.2: "And no *other* design package of the same project may already be in `freeze_state` `IN_REVIEW`, because a project may have at most one review in flight; a second concurrent review is rejected with `ERR_DESIGN_REVIEW_IN_FLIGHT`."
    PRD §3.2: "A new package is persisted in `freeze_state` `DRAFT` with `revision_round` at 0, `submitted_by_user_id`, `reviewed_by_user_id` and `review_note` all null, and `version` at 1; creating it also increments the project's `version`."

    Design: Corner/errors/design_package_lifecycle_errors_are_triggerable
    """
    world = a_revision_awaiting_its_reviewer

    # Opening the second revision is legal; only sending it to review is not.
    second = fx.create_design_package(
        world.api, world.project_id, world.project_version, revision_index=2
    )
    assert second["freeze_state"] == "DRAFT"
    assert second["revision_round"] == 0

    validate_error(
        world.api.submit_design_package(
            second["id"],
            f.submit_payload(review_note="R2 jumping the queue"),
            DESIGN_ENGINEER_SUBMITTER,
        ),
        ERR_DESIGN_REVIEW_IN_FLIGHT,
    )

    still_draft = validate_success(
        world.api.get_design_package(second["id"], PROGRAM_ADMIN)
    )
    assert still_draft["freeze_state"] == "DRAFT"


def test_a_supersession_must_name_a_predecessor_that_is_already_frozen(
    a_revision_awaiting_its_reviewer,
):
    """PRD §3.2: "When it is supplied, the predecessor must belong to the same project, must already be in `freeze_state` `FROZEN`, and must have a `revision_index` strictly less than the new package's `revision_index` — any of those three failing produces `ERR_INVALID_SUPERSESSION`."

    Design: Corner/errors/design_package_lifecycle_errors_are_triggerable
    """
    world = a_revision_awaiting_its_reviewer

    validate_error(
        world.api.create_design_package(
            f.design_package_payload(
                world.project_id,
                world.project_version,
                revision_index=3,
                supersedes_package_id=world.package_id,
            ),
            DESIGN_ENGINEER_SUBMITTER,
        ),
        ERR_INVALID_SUPERSESSION,
    )

    _, meta = validate_paginated(
        world.api.list_design_packages(
            {"project_id": world.project_id}, PROGRAM_ADMIN
        )
    )
    assert meta["total_count"] == 1, "the refused revision must not have been persisted"


# ─── Approving a plan review needs exactly one revision to pin ────────────────
def test_a_plan_review_cannot_be_approved_while_the_revision_is_still_a_draft(api):
    """PRD §3.3: "When the `scope` is `PLAN_REVIEW`, exactly one design package of the project must be in `freeze_state` `FROZEN`; zero frozen packages, or more than one, is rejected with `ERR_NO_FROZEN_PACKAGE`."
    PRD §3.3: "On success, an approval whose `scope` is `PLAN_REVIEW` sets `pinned_package_id` to the `id` of the project's single frozen design package."

    Design: Corner/errors/permit_approval_errors_are_triggerable
    """
    world = fx.world_plant_and_project(api)
    world.package = fx.create_design_package(
        api, world.project_id, world.project["version"]
    )
    application = get_success_data(
        api.create_permit(
            f.permit_payload(world.project_id, "STATE_MODULAR_PROGRAM", "PLAN_REVIEW"),
            PROGRAM_ADMIN,
        )
    )

    validate_error(
        api.decide_permit(
            application["id"],
            f.permit_decision_payload("APPROVE"),
            STATE_PROGRAM_OFFICER,
        ),
        ERR_NO_FROZEN_PACKAGE,
    )

    refused = validate_success(api.get_permit(application["id"], PROGRAM_ADMIN))
    assert refused["status"] == "SUBMITTED"
    assert refused["pinned_package_id"] is None


def test_a_plan_review_cannot_be_approved_when_two_revisions_are_frozen(api):
    """PRD §3.3: "When the `scope` is `PLAN_REVIEW`, exactly one design package of the project must be in `freeze_state` `FROZEN`; zero frozen packages, or more than one, is rejected with `ERR_NO_FROZEN_PACKAGE`."

    Design: Corner/errors/permit_approval_errors_are_triggerable
    """
    world = fx.world_frozen_design(api)
    second = fx.create_design_package(
        api, world.project_id, world.project_version, revision_index=2
    )
    fx.freeze_package(api, second["id"])
    application = get_success_data(
        api.create_permit(
            f.permit_payload(world.project_id, "STATE_MODULAR_PROGRAM", "PLAN_REVIEW"),
            PROGRAM_ADMIN,
        )
    )

    validate_error(
        api.decide_permit(
            application["id"],
            f.permit_decision_payload("APPROVE"),
            STATE_PROGRAM_OFFICER,
        ),
        ERR_NO_FROZEN_PACKAGE,
    )

    refused = validate_success(api.get_permit(application["id"], PROGRAM_ADMIN))
    assert refused["pinned_package_id"] is None, (
        "with two candidates the state must not pin either revision"
    )


def test_a_denied_application_is_closed_to_every_further_decision(api):
    """PRD §3.3: "The `decision` is one of `START_REVIEW`, `ISSUE_CONDITIONS`, `APPROVE` or `DENY`, and each demands a compatible current `status`; an incompatible pairing, or any decision at all against a record already in `DENIED` or `EXPIRED`, is rejected with `ERR_PERMIT_ALREADY_DECIDED`."
    PRD §3.3: "`DENY` moves `status` to `DENIED`, which is terminal."

    Design: Corner/errors/permit_approval_errors_are_triggerable
    """
    world = fx.world_plant_and_project(api)
    application = get_success_data(
        api.create_permit(
            f.permit_payload(world.project_id, "STATE_MODULAR_PROGRAM", "PLAN_REVIEW"),
            PROGRAM_ADMIN,
        )
    )
    denied = validate_success(
        api.decide_permit(
            application["id"], f.permit_decision_payload("DENY"), STATE_PROGRAM_OFFICER
        )
    )
    assert denied["status"] == "DENIED"

    validate_error(
        api.decide_permit(
            application["id"],
            f.permit_decision_payload("APPROVE"),
            STATE_PROGRAM_OFFICER,
        ),
        ERR_PERMIT_ALREADY_DECIDED,
    )

    still_denied = validate_success(api.get_permit(application["id"], PROGRAM_ADMIN))
    assert still_denied["status"] == "DENIED"
    assert still_denied["version"] == denied["version"]


# ─── The production dimension: three guards, one module, three states ─────────
def test_a_module_that_already_holds_a_takt_window_cannot_claim_a_second(api):
    """PRD §3.4: "The module must be in `production_status` `PLANNED`, or the request is `ERR_MODULE_NOT_PLANNED`."
    PRD §3.4: "Claiming a takt window moves `production_status` from `PLANNED` to `SLOTTED`, and the only payload field is `line_slot_start`, the instant at which the module wants the line."

    Design: Corner/errors/module_production_state_errors_are_triggerable
    """
    world = fx.world_slotted_module(api)
    assert_module_dimensions(world.module(), production_status="SLOTTED")

    validate_error(
        world.api.schedule_line_slot(
            world.module_id(),
            f.line_slot_payload("2026-09-03T14:00:00Z"),
            world.factory_manager,
        ),
        ERR_MODULE_NOT_PLANNED,
    )

    unmoved = world.refresh_module()
    assert_instant(unmoved["line_slot_start"], fx.DEFAULT_LINE_SLOT_START)
    assert world.refresh_factory()["committed_line_minutes"] == 540, (
        "the refused second claim must not book a second slot's worth of minutes"
    )


def test_a_module_off_the_end_of_the_line_can_no_longer_release_its_slot(api):
    """PRD §3.4: "It requires `production_status` `SLOTTED`, or the request is `ERR_MODULE_NOT_SLOTTED`."
    PRD §3.4: "A terminating advance, where `station_index` plus `stations_advanced` reaches or exceeds the plant's `station_count`, moves `production_status` to `LINE_COMPLETE`, sets `station_index` exactly to the plant's `station_count`, subtracts the module's `line_slot_minutes` from the plant's `committed_line_minutes` and increments the plant's `version` — the line is released, and the interval stays on the module as history while no longer occupying capacity — recomputes `wip_earned_cents`, which under the station-progress rule now yields the plant's full `wip_unit_value_cents`, recomputes the `basis_earned_cents` and `requested_cents` of the project's `DRAFT` draw requests, and increments the module's `version`."

    Design: Corner/errors/module_production_state_errors_are_triggerable
    """
    world = fx.world_line_complete_module(api)
    assert_module_dimensions(world.module(), production_status="LINE_COMPLETE")
    assert world.module()["station_index"] == 6

    validate_error(
        world.api.release_line_slot(
            world.module_id(),
            {"reason": "too late to release"},
            world.factory_manager,
        ),
        ERR_MODULE_NOT_SLOTTED,
    )

    # The terminating advance already refunded the minutes; a second refund
    # would drive the conserved ledger negative.
    assert world.refresh_factory()["committed_line_minutes"] == 0
    assert_instant(world.refresh_module()["line_slot_start"], fx.DEFAULT_LINE_SLOT_START)


def test_a_module_off_the_end_of_the_line_can_no_longer_advance_a_station(api):
    """PRD §3.4: "In all three cases the module must be in `production_status` `SLOTTED` or `IN_LINE` — otherwise `ERR_MODULE_NOT_ON_LINE` — its `qc_status` must not be `HOLD` — otherwise `ERR_QC_HOLD_BLOCKS_OPERATION` — and the plant's `line_state` must be `RUNNING` — otherwise `ERR_FACTORY_LINE_NOT_RUNNING`."
    PRD §3.4: "`LINE_COMPLETE` is terminal on the production dimension."

    Design: Corner/errors/module_production_state_errors_are_triggerable
    """
    world = fx.world_line_complete_module(api)

    validate_error(
        world.api.advance_station(
            world.module_id(), f.advance_payload(1), world.factory_manager
        ),
        ERR_MODULE_NOT_ON_LINE,
    )

    stuck = world.refresh_module()
    assert stuck["station_index"] == 6, "the station index must not pass the last station"
    assert_module_dimensions(stuck, production_status="LINE_COMPLETE")


# ─── Staged inspection records, recorded once, cleared only when held ─────────
@pytest.fixture
def a_module_with_an_open_in_plant_record(api):
    """M-01 standing at station 1 of the line with a PENDING IN_PLANT record."""
    world = fx.world_with_module(api)
    fx.schedule_slot(world)
    fx.advance_stations(world, "M-01", 1)
    world.inspections["M-01:IN_PLANT"] = fx.open_inspection(
        api, world.module_id(), world.agency_id, "IN_PLANT"
    )
    assert world.inspections["M-01:IN_PLANT"]["result"] == "PENDING"
    return world


def test_the_final_factory_record_cannot_open_over_a_pending_in_plant_record(
    a_module_with_an_open_in_plant_record,
):
    """PRD §3.5: "Inspection staging must be respected: a `FINAL_FACTORY` record may be opened only when an `IN_PLANT` record of the same module already carries a `result` of `PASS` or `CONDITIONAL`, and no other record of the same module may still be sitting at `result` `PENDING`; either failure is `ERR_QC_STAGE_OUT_OF_ORDER`."

    Design: Corner/errors/inspection_staging_and_result_errors_are_triggerable
    """
    world = a_module_with_an_open_in_plant_record

    validate_error(
        world.api.create_inspection(
            f.inspection_payload(world.module_id(), world.agency_id, "FINAL_FACTORY"),
            world.inspector,
        ),
        ERR_QC_STAGE_OUT_OF_ORDER,
    )

    _, meta = validate_paginated(
        world.api.list_inspections({"module_id": world.module_id()}, PROGRAM_ADMIN)
    )
    assert meta["total_count"] == 1, "the refused stage-two record must not exist"
    assert_module_dimensions(
        world.refresh_module(), production_status="IN_LINE", qc_status="IN_PROGRESS"
    )


def test_a_hold_cannot_be_cleared_from_a_record_that_never_held_the_module(
    a_module_with_an_open_in_plant_record,
):
    """PRD §3.5: "The inspector supplies a required `corrective_note`, and three preconditions apply: the module's `qc_status` must be `HOLD` and the record's `hold_state` must be `AGENCY_HOLD` — otherwise the attempt is `ERR_HOLD_NOT_ACTIVE` — and the clearing agency's `accreditation_state` must be `ACCREDITED` or `PROBATION`."
    PRD §3.5: "A new record is persisted with `result` `PENDING`, `hold_state` `NONE`, `defect_count` 0, `severity_max` 0, `corrective_note`, `recorded_at` and `recorded_by_user_id` all null, and `version` 1; the module's `version` increments when the first record flips its quality dimension."

    Design: Corner/errors/inspection_staging_and_result_errors_are_triggerable
    """
    world = a_module_with_an_open_in_plant_record
    record = world.inspections["M-01:IN_PLANT"]
    assert record["hold_state"] == "NONE"

    validate_error(
        world.api.clear_hold(
            record["id"], f.clear_hold_payload(), world.inspector
        ),
        ERR_HOLD_NOT_ACTIVE,
    )

    untouched = validate_success(
        world.api.get_inspection(record["id"], PROGRAM_ADMIN)
    )
    assert untouched["hold_state"] == "NONE"
    assert untouched["result"] == "PENDING"
    assert untouched["version"] == record["version"]


def test_an_outcome_may_be_recorded_against_a_record_only_once(
    a_module_with_an_open_in_plant_record,
):
    """PRD §3.5: "The record itself must still be at `result` `PENDING` and its module's `qc_status` must be either `IN_PROGRESS` or `CONDITIONAL_RELEASE`; otherwise the attempt is `ERR_INSPECTION_NOT_PENDING`."

    Design: Corner/errors/inspection_staging_and_result_errors_are_triggerable
    """
    world = a_module_with_an_open_in_plant_record
    record = world.inspections["M-01:IN_PLANT"]
    passed = fx.record_result(world.api, record["id"], world.agency_id, "PASS")
    assert passed["result"] == "PASS"

    validate_error(
        world.api.record_inspection_result(
            record["id"],
            f.inspection_result_payload("FAIL", 3, 4),
            world.inspector,
        ),
        ERR_INSPECTION_NOT_PENDING,
    )

    unchanged = validate_success(
        world.api.get_inspection(record["id"], PROGRAM_ADMIN)
    )
    assert unchanged["result"] == "PASS", "the refused FAIL must not overwrite the pass"
    assert unchanged["defect_count"] == 0
    assert_module_dimensions(world.refresh_module(), qc_status="IN_PROGRESS")


# ─── Four gates on the loading dock ───────────────────────────────────────────
def test_a_module_the_agency_has_not_released_may_not_be_loaded(api):
    """PRD §3.6: "The module's `qc_status` must not be `HOLD`, reported as `ERR_QC_HOLD_BLOCKS_OPERATION`, and must be `RELEASED` or `CONDITIONAL_RELEASE`, reported as `ERR_QC_NOT_RELEASED`."
    PRD §3.5: "Two further operations read the quality dimension without being blocked by a hold as such: loading requires `qc_status` to be `RELEASED` or `CONDITIONAL_RELEASE`, reported as `ERR_QC_NOT_RELEASED` when it is `PENDING` or `IN_PROGRESS`, and closing connections requires `qc_status` not to be `HOLD`."

    Design: Corner/errors/transport_load_errors_are_triggerable
    """
    world = fx.world_line_complete_module(api)
    assert_module_dimensions(
        world.module(),
        production_status="LINE_COMPLETE",
        qc_status="PENDING",
        site_status="AT_FACTORY",
    )
    world.shipment = fx.create_shipment(api, world.project_id)

    validate_error(
        api.load_module(
            world.shipment_id,
            f.load_module_payload(world.module_id(), world.shipment["version"]),
            TRANSPORT_COORDINATOR,
        ),
        ERR_QC_NOT_RELEASED,
    )

    assert world.refresh_shipment()["loaded_module_count"] == 0
    assert world.refresh_module()["shipment_id"] is None


def test_a_module_already_booked_on_one_load_cannot_be_booked_on_another(api):
    """PRD §3.6: "The module must not already carry a `shipment_id`; a double booking is rejected with `ERR_MODULE_ALREADY_LOADED`, and that specific answer deliberately outranks the generic loadability answer below."
    PRD §3.6: "On success the module's `site_status` moves from `AT_FACTORY` to `LOADED`, its `shipment_id` is set to the shipment, the shipment's `loaded_module_count` increases by 1, and both rows take `version` increments."

    Design: Corner/errors/transport_load_errors_are_triggerable
    """
    world = fx.world_loaded_module(api)
    first_load = world.shipment_id
    second_load = fx.create_shipment(api, world.project_id, carrier_code="CASCADEHV")

    # The module's site_status is LOADED, so the generic loadability gate would
    # also refuse it; the specific double-booking answer must win.
    validate_error(
        api.load_module(
            second_load["id"],
            f.load_module_payload(world.module_id(), second_load["version"]),
            TRANSPORT_COORDINATOR,
        ),
        ERR_MODULE_ALREADY_LOADED,
    )

    assert validate_success(api.get_shipment(second_load["id"], PROGRAM_ADMIN))[
        "loaded_module_count"
    ] == 0
    assert world.refresh_module()["shipment_id"] == first_load


def test_an_empty_load_has_no_route_to_survey(api):
    """PRD §3.6: "Three gates apply. The shipment's `status` must be `DRAFT` or `SURVEY_REQUIRED`, its `route_survey_state` must not already be `COMPLETED`, and its `loaded_module_count` must be at least 1; an empty load, an already-completed survey or a dispatched load is rejected with `ERR_SURVEY_NOT_PENDING`."

    Design: Corner/errors/transport_load_errors_are_triggerable
    """
    world = fx.world_plant_and_project(api)
    world.shipment = fx.create_shipment(api, world.project_id)
    assert world.shipment["loaded_module_count"] == 0

    validate_error(
        api.record_route_survey(
            world.shipment_id, f.route_survey_payload(), TRANSPORT_COORDINATOR
        ),
        ERR_SURVEY_NOT_PENDING,
    )

    refused = world.refresh_shipment()
    assert refused["route_survey_state"] == "NOT_REQUIRED"
    assert refused["survey_completed_at"] is None
    assert refused["permit_expires_at"] is None
    assert refused["status"] == "DRAFT"


def test_a_load_that_has_already_left_the_yard_cannot_take_another_module(api):
    """PRD §3.6: "The shipment's `status` must be `DRAFT` or `SURVEY_REQUIRED`, and the module's `site_status` must be `AT_FACTORY` with `production_status` `LINE_COMPLETE`; any of those failing is `ERR_SHIPMENT_NOT_LOADABLE`."
    PRD §3.6: "On success `status` moves from `PERMITTED` to `DISPATCHED`, `dispatched_at` is stamped with the current clock instant, every module aboard moves its `site_status` from `LOADED` to `IN_TRANSIT`, the project's `phase` is re-derived up to `SHIPPING`, and the shipment, every module aboard and the project all take `version` increments."

    Design: Corner/errors/transport_load_errors_are_triggerable
    """
    world = fx.world_loaded_module(api)

    # A second module, fully released, standing at the plant with nowhere to go.
    fx.add_module(world, "M-02", 2)
    fx.schedule_slot(world, "M-02", "2026-09-03T14:00:00Z")
    fx.advance_stations(world, "M-02", world.factory["station_count"])
    fx.release_quality(world, "M-02")
    assert_module_dimensions(
        world.module("M-02"), qc_status="RELEASED", site_status="AT_FACTORY"
    )

    validate_success(
        api.record_route_survey(
            world.shipment_id, f.route_survey_payload(), TRANSPORT_COORDINATOR
        )
    )
    dispatched = validate_success(
        api.dispatch_shipment(world.shipment_id, {}, TRANSPORT_COORDINATOR)
    )
    assert dispatched["status"] == "DISPATCHED"

    validate_error(
        api.load_module(
            world.shipment_id,
            f.load_module_payload(world.module_id("M-02"), dispatched["version"]),
            TRANSPORT_COORDINATOR,
        ),
        ERR_SHIPMENT_NOT_LOADABLE,
    )

    assert world.refresh_shipment()["loaded_module_count"] == 1
    assert world.refresh_module("M-02")["shipment_id"] is None


# ─── Three independent rejection modes on the crane pad ───────────────────────
@pytest.fixture
def a_module_still_standing_at_the_plant(api):
    """M-01 at the plant, against the default three-row crane chart."""
    world = fx.world_plant_and_project(api)
    world.package = fx.create_design_package(
        api, world.project_id, world.project["version"]
    )
    world.modules["M-01"] = fx.create_module(
        api, world.project_id, world.package_id, world.factory_id, "M-01", 1
    )
    return world


@pytest.mark.parametrize(
    "pick_window_start, pick_window_end",
    [
        ("2026-09-10T09:00:00Z", "2026-09-10T09:00:00Z"),
        ("2026-09-01T07:59:59Z", "2026-09-10T09:00:00Z"),
    ],
)
def test_a_pick_window_must_close_after_it_opens_and_open_no_earlier_than_now(
    a_module_still_standing_at_the_plant, pick_window_start, pick_window_end
):
    """PRD §3.7: "The window must be coherent and in the future: `pick_window_end` must be strictly after `pick_window_start`, and `pick_window_start` must be at or after the current logical clock instant, or the request is `ERR_PICK_WINDOW_INVALID`."

    Design: Corner/errors/crane_pick_input_errors_are_triggerable
    """
    world = a_module_still_standing_at_the_plant

    # A 75 foot radius sits on the chart, so only the window can be at fault.
    validate_error(
        world.api.schedule_pick(
            world.module_id(),
            f.pick_payload(pick_window_start, pick_window_end, 75, 4000),
            world.superintendent,
        ),
        ERR_PICK_WINDOW_INVALID,
    )

    unplanned = world.refresh_module()
    assert unplanned["pick_window_start"] is None
    assert unplanned["pick_window_end"] is None
    assert unplanned["crane_utilization_pct"] is None


def test_a_radius_beyond_the_last_chart_row_has_no_capacity_to_read(
    a_module_still_standing_at_the_plant,
):
    """PRD §3.7: "If the chart holds no such entry — the requested radius reaches further out than the chart covers — the request is rejected with `ERR_PICK_RADIUS_OFF_CHART`."
    PRD §3.7: "First, the server looks up the chart entry with the *smallest* `radius_ft` that is greater than or equal to the requested `pick_radius_ft`."

    Design: Corner/errors/crane_pick_input_errors_are_triggerable
    """
    world = a_module_still_standing_at_the_plant

    validate_error(
        world.api.schedule_pick(
            world.module_id(),
            f.pick_payload("2026-09-10T09:00:00Z", "2026-09-10T09:45:00Z", 150, 4000),
            world.superintendent,
        ),
        ERR_PICK_RADIUS_OFF_CHART,
    )

    unplanned = world.refresh_module()
    assert unplanned["pick_radius_ft"] is None
    assert unplanned["rigging_weight_lb"] is None


def test_a_module_that_never_left_the_plant_cannot_be_landed_on_the_foundation(
    a_module_still_standing_at_the_plant,
):
    """PRD §3.7: "The module's `site_status` must be `DELIVERED`, or the attempt is `ERR_MODULE_NOT_READY_TO_SET`."
    PRD §3.7: "A successful set stamps `set_at` with the current clock instant, resets the module's `exposure_open_hours` to 0 because the exposure clock starts now, increases the project's `modules_set_count` by 1, re-derives the project's `phase` up to `SETTING`, and increments both the module's and the project's `version`."

    Design: Corner/errors/crane_pick_input_errors_are_triggerable
    """
    world = a_module_still_standing_at_the_plant
    assert_module_dimensions(world.module(), site_status="AT_FACTORY")

    validate_error(
        world.api.execute_set(world.module_id(), {}, world.superintendent),
        ERR_MODULE_NOT_READY_TO_SET,
    )

    unset = world.refresh_module()
    assert unset["set_at"] is None
    assert world.refresh_project()["modules_set_count"] == 0


def test_a_module_already_on_the_foundation_cannot_have_its_lift_replanned(api):
    """PRD §3.7: "A pick may be planned while the module's `site_status` is `AT_FACTORY`, `LOADED`, `IN_TRANSIT` or `DELIVERED` — planning ahead of delivery is normal practice — but not once it is `SET` or `CONNECTED`; an attempt against an already-set module is rejected with `ERR_MODULE_NOT_READY_TO_SET`."
    PRD §2.6: "Ranks 39 through 59 are the state preconditions, in this order: `ERR_DESIGN_REVIEW_IN_FLIGHT` (39), `ERR_DESIGN_NOT_SUBMITTABLE` (40), `ERR_DESIGN_NOT_IN_REVIEW` (41), `ERR_DRAW_NOT_DRAFT` (42), `ERR_DRAW_NOT_CERTIFIED` (43), `ERR_MODULE_NOT_PLANNED` (44), `ERR_MODULE_NOT_SLOTTED` (45), `ERR_MODULE_NOT_ON_LINE` (46), `ERR_MODULE_NOT_READY_TO_SET` (47), `ERR_MODULE_NOT_SET` (48), `ERR_SHIPMENT_NOT_LOADABLE` (49), `ERR_SURVEY_NOT_PENDING` (50), `ERR_SHIPMENT_NOT_PERMITTED` (51), `ERR_SHIPMENT_NOT_DISPATCHED` (52), `ERR_SHIPMENT_TERMINAL` (53), `ERR_PERMIT_ALREADY_DECIDED` (54), `ERR_INSPECTION_NOT_PENDING` (55), `ERR_HOLD_NOT_ACTIVE` (56), `ERR_CLAIM_NOT_ADJUDICABLE` (57), `ERR_CLAIM_NOT_ADJUDICATED` (58) and `ERR_DISPUTE_ROUND_LIMIT` (59)."

    Design: Corner/errors/crane_pick_input_errors_are_triggerable
    """
    world = fx.world_set_module(api)
    assert_module_dimensions(world.module(), site_status="SET")

    # The radius is off the chart and the window opens in the past as well; the
    # rank-47 state answer must be reported ahead of both.
    validate_error(
        world.api.schedule_pick(
            world.module_id(),
            f.pick_payload("2026-08-01T09:00:00Z", "2026-08-01T09:00:00Z", 150, 4000),
            world.superintendent,
        ),
        ERR_MODULE_NOT_READY_TO_SET,
    )

    unchanged = world.refresh_module()
    assert_instant(unchanged["pick_window_start"], fx.DEFAULT_PICK_WINDOW_START)
    assert unchanged["pick_radius_ft"] == fx.DEFAULT_PICK_RADIUS_FT


# ─── Set order and the field-scope sign-off ───────────────────────────────────
@pytest.fixture
def two_delivered_modules_ready_to_set(api):
    """M-01 and M-02 delivered to a set-cleared site, each with its own lift.

    The two pick windows are far enough apart that the rigging buffer cannot
    make them overlap, so crane exclusivity is not in play.
    """
    world = fx.world_loaded_module(api)
    fx.add_module(world, "M-02", 2)
    fx.schedule_slot(world, "M-02", "2026-09-03T14:00:00Z")
    fx.advance_stations(world, "M-02", world.factory["station_count"])
    fx.release_quality(world, "M-02")
    world.shipment = fx.load_module(
        api,
        world.shipment_id,
        world.module_id("M-02"),
        world.refresh_shipment()["version"],
    )

    get_success_data(
        api.record_route_survey(
            world.shipment_id, f.route_survey_payload(), TRANSPORT_COORDINATOR
        )
    )
    get_success_data(api.dispatch_shipment(world.shipment_id, {}, TRANSPORT_COORDINATOR))
    get_success_data(api.deliver_shipment(world.shipment_id, {}, TRANSPORT_COORDINATOR))
    world.refresh_module("M-01")
    world.refresh_module("M-02")

    fx.clear_the_site_for_setting(world)
    fx.plan_pick(world, "M-01")
    fx.plan_pick(world, "M-02", "2026-09-05T13:00:00Z", "2026-09-05T13:45:00Z")
    return world


def test_the_second_module_may_not_go_on_before_the_first_one(
    two_delivered_modules_ready_to_set,
):
    """PRD §3.7: "Under `STRICT_ASCENDING`, the module's `set_sequence_index` must equal the project's current `modules_set_count` plus 1 — modules go on in exactly the numbered order, with no gaps and no reordering."
    PRD §3.7: "And set order must respect the project's `set_sequence_policy`, or the attempt is `ERR_SET_SEQUENCE_VIOLATION`."

    Design: Corner/errors/set_and_connect_errors_are_triggerable
    """
    world = two_delivered_modules_ready_to_set
    assert world.refresh_project()["modules_set_count"] == 0

    validate_error(
        world.api.execute_set(world.module_id("M-02"), {}, world.superintendent),
        ERR_SET_SEQUENCE_VIOLATION,
    )

    refused = world.refresh_module("M-02")
    assert_module_dimensions(refused, site_status="DELIVERED")
    assert refused["set_at"] is None

    # The identical call is admitted for the module whose turn it is.
    first = validate_success(
        world.api.execute_set(world.module_id("M-01"), {}, world.superintendent)
    )
    assert first["site_status"] == "SET"
    assert world.refresh_project()["modules_set_count"] == 1


def test_a_module_cannot_be_closed_in_until_the_field_scope_is_signed_off(api):
    """PRD §3.7: "And `field_scope_signed_off` must be true — the site-built scope adjoining the module must be signed off before its connections are closed — or the attempt is rejected with `ERR_FIELD_SCOPE_NOT_SIGNED_OFF`, which by its rank of 93 is the very last check this operation performs, below even the fiscal rules."
    PRD §3.7: "Closing connections stamps `connected_at` with the current clock instant and freezes `exposure_open_hours` at the elapsed span between `set_at` and `connected_at`."

    Design: Corner/errors/set_and_connect_errors_are_triggerable
    """
    world = fx.world_set_module(api)

    validate_error(
        world.api.close_connections(
            world.module_id(),
            f.close_connections_payload(False),
            world.superintendent,
        ),
        ERR_FIELD_SCOPE_NOT_SIGNED_OFF,
    )

    still_open = world.refresh_module()
    assert_module_dimensions(still_open, site_status="SET")
    assert still_open["connected_at"] is None
    assert world.refresh_project()["modules_connected_count"] == 0


# ─── The lender's ledger and the warranty file are both strictly sequenced ────
def test_the_first_draw_of_a_project_must_be_numbered_one(api):
    """PRD §3.9: "`draw_index` is a one-based draw number supplied by the lender and must equal exactly one more than the highest `draw_index` already recorded against the project, so the first draw of a project is 1 and there are never gaps or repeats; anything else is rejected with `ERR_DRAW_SEQUENCE_GAP`."

    Design: Corner/errors/draw_and_claim_sequencing_errors_are_triggerable
    """
    world = fx.world_plant_and_project(api)

    validate_error(
        api.create_draw_request(
            f.draw_request_payload(world.project_id, world.agency_id, "WIP_DEPOSIT", 2),
            LENDER_DRAW_ADMINISTRATOR,
        ),
        ERR_DRAW_SEQUENCE_GAP,
    )

    _, meta = validate_paginated(
        api.list_draw_requests({"project_id": world.project_id}, PROGRAM_ADMIN)
    )
    assert meta["total_count"] == 0, "the out-of-sequence draw must not be recorded"

    # Index 1 is the only number the empty ledger accepts.
    first = validate_success(
        api.create_draw_request(
            f.draw_request_payload(world.project_id, world.agency_id, "WIP_DEPOSIT", 1),
            LENDER_DRAW_ADMINISTRATOR,
        ),
        201,
    )
    assert first["draw_index"] == 1
    assert first["status"] == "DRAFT"


def test_an_uncertified_draw_cannot_be_funded(api):
    """PRD §3.9: "It takes an optional `funded_at` and requires `status` to be exactly `CERTIFIED`, or the attempt is `ERR_DRAW_NOT_CERTIFIED`."
    PRD §3.9: "It moves `status` to `FUNDED`, stamps `funded_at` with the current clock instant, adds `net_funded_cents` to the project's `funded_to_date_cents`, and increments the draw's and the project's `version`."

    Design: Corner/errors/draw_and_claim_sequencing_errors_are_triggerable
    """
    world = fx.world_plant_and_project(api)
    draw = fx.create_draw(api, world.project_id, world.agency_id, "WIP_DEPOSIT", 1)
    assert draw["status"] == "DRAFT"

    validate_error(
        api.fund_draw(draw["id"], {}, LENDER_DRAW_ADMINISTRATOR),
        ERR_DRAW_NOT_CERTIFIED,
    )

    unfunded = validate_success(api.get_draw_request(draw["id"], PROGRAM_ADMIN))
    assert unfunded["status"] == "DRAFT"
    assert unfunded["funded_at"] is None
    assert_cents(
        world.refresh_project()["funded_to_date_cents"], 0, "funded_to_date_cents"
    )


def test_a_draw_whose_money_has_already_gone_out_cannot_be_rejected(api):
    """PRD §3.9: "It takes a required `reject_reason` and accepts a draw in `status` `DRAFT` or `CERTIFIED`; a draw already `FUNDED` or already `REJECTED` cannot be rejected, and the attempt reports `ERR_DRAW_NOT_CERTIFIED` — the same code that guards funding, since both are the draw-lifecycle gate at rank 43."

    Design: Corner/errors/draw_and_claim_sequencing_errors_are_triggerable
    """
    # Reaching FUNDED requires a successful certification first, and PRD §3.9
    # refuses to certify a zero basis with ERR_NO_CERTIFIABLE_WIP. The world
    # therefore needs a module off the end of the line to back the draw.
    world = fx.world_line_complete_module(api)
    draw = fx.create_draw(api, world.project_id, world.agency_id, "WIP_DEPOSIT", 1)
    get_success_data(api.certify_draw(draw["id"], f.certify_payload(), LENDER_DRAW_ADMINISTRATOR))
    funded = get_success_data(api.fund_draw(draw["id"], {}, LENDER_DRAW_ADMINISTRATOR))
    assert funded["status"] == "FUNDED"

    validate_error(
        api.reject_draw(draw["id"], f.reject_payload(), LENDER_DRAW_ADMINISTRATOR),
        ERR_DRAW_NOT_CERTIFIED,
    )

    assert validate_success(api.get_draw_request(draw["id"], PROGRAM_ADMIN))[
        "status"
    ] == "FUNDED"


@pytest.fixture
def an_open_factory_phase_claim(api):
    """A sheathing defect found in the plant, raised but not yet allocated."""
    world = fx.world_with_module(api)
    claim = get_success_data(
        api.create_defect_claim(
            f.defect_claim_payload(world.module_id(), "FACTORY", 400000),
            world.factory_manager,
        )
    )
    return world, claim


def test_an_allocation_cannot_be_disputed_before_it_has_been_made(
    an_open_factory_phase_claim,
):
    """PRD §3.8: "The claim's `status` must be `ADJUDICATED`, or the attempt is `ERR_CLAIM_NOT_ADJUDICATED`, and its `adjudication_round` must be strictly less than 2, or the attempt is `ERR_DISPUTE_ROUND_LIMIT`: a claim already re-adjudicated on evidence is final and may be disputed no further."

    Design: Corner/errors/draw_and_claim_sequencing_errors_are_triggerable
    """
    world, claim = an_open_factory_phase_claim
    assert claim["status"] == "OPEN"
    assert claim["adjudication_round"] == 0

    validate_error(
        world.api.dispute_defect_claim(
            claim["id"],
            f.dispute_payload("disputing before any ruling"),
            world.factory_manager,
        ),
        ERR_CLAIM_NOT_ADJUDICATED,
    )

    untouched = validate_success(
        world.api.get_defect_claim(claim["id"], PROGRAM_ADMIN)
    )
    assert untouched["status"] == "OPEN"
    assert untouched["dispute_note"] is None
    assert untouched["version"] == claim["version"]


def test_an_allocation_cannot_be_run_twice_without_a_dispute_between(
    an_open_factory_phase_claim,
):
    """PRD §3.8: "The claim's `status` must be `OPEN` or `DISPUTED`, or the attempt is `ERR_CLAIM_NOT_ADJUDICABLE`."
    PRD §3.8: "Which of the two states the claim arrives in decides *which allocation variant runs*, and the two variants can reach materially different answers from identical claim data."

    Design: Corner/errors/draw_and_claim_sequencing_errors_are_triggerable
    """
    world, claim = an_open_factory_phase_claim
    adjudicated = validate_success(
        world.api.adjudicate_defect_claim(
            claim["id"], f.adjudicate_payload(), WARRANTY_ADJUDICATOR
        )
    )
    assert adjudicated["status"] == "ADJUDICATED"
    assert adjudicated["adjudication_round"] == 1

    validate_error(
        world.api.adjudicate_defect_claim(
            claim["id"],
            f.adjudicate_payload(adjudication_note="round 1 again"),
            WARRANTY_ADJUDICATOR,
        ),
        ERR_CLAIM_NOT_ADJUDICABLE,
    )

    unchanged = validate_success(
        world.api.get_defect_claim(claim["id"], PROGRAM_ADMIN)
    )
    assert unchanged["adjudication_round"] == 1, "a refused ruling must not add a round"
    assert_cents(
        unchanged["factory_charge_cents"],
        adjudicated["factory_charge_cents"],
        "factory_charge_cents",
    )
