"""Operations whose admissibility is decided on another entity's row entirely.

A module may claim the plant's line only because a permit record on the state
track says APPROVED, and a lender may open a draw only because an inspection
agency's accreditation row says it is accredited in the project's own state. In
both cases nothing about the operating entity changes between the refusal and
the acceptance — only the other row moves.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_AGENCY_JURISDICTION_MISMATCH,
    ERR_AGENCY_NOT_ACCREDITED,
    ERR_PLAN_REVIEW_PREREQUISITE,
)
from test_helpers.assertions import assert_cents, assert_module_dimensions
from test_helpers.test_users import (
    LENDER_DRAW_ADMINISTRATOR,
    PROGRAM_ADMIN,
    STATE_PROGRAM_OFFICER,
)


@pytest.fixture
def plan_review_still_pending(api):
    """R1 frozen, a module detailed, and only the local foundation permit issued.

    The state plan-review application has been filed but not decided, so the site
    side of the bifurcation is cleared while the state side is not.
    """
    world = fx.world_frozen_design(api)
    world.modules["M-01"] = fx.create_module(
        api, world.project_id, world.package_id, world.factory_id, "M-01", 1
    )
    world.plan_review_permit = validate_success(
        api.create_permit(
            f.permit_payload(world.project_id, "STATE_MODULAR_PROGRAM", "PLAN_REVIEW"),
            PROGRAM_ADMIN,
        ),
        201,
    )
    fx.approve_permit(api, world.project_id, "LOCAL_AHJ", "FOUNDATION")
    return world


def test_the_line_stays_shut_until_the_state_plan_review_is_approved(
    plan_review_still_pending,
):
    """PRD §3.4: "The project must have a live state plan-review approval as defined in §3.3, or the request is `ERR_PLAN_REVIEW_PREREQUISITE`."
    PRD §3.3: "Otherwise, if the site side is cleared and state plan review is not live, it is `SITE_CLEARED_ONLY`."

    Design: Difficulty/cross_entity_state_dependency/module_line_slot_depends_on_permit_record_state_plan_review_approval
    """
    world = plan_review_still_pending
    assert world.plan_review_permit["status"] == "SUBMITTED"

    validate_error(
        world.api.schedule_line_slot(
            world.module_id(),
            f.line_slot_payload("2026-09-02T14:00:00Z"),
            world.factory_manager,
        ),
        ERR_PLAN_REVIEW_PREREQUISITE,
    )

    assert world.refresh_project()["permit_posture"] == "SITE_CLEARED_ONLY"
    assert_module_dimensions(world.refresh_module(), production_status="PLANNED")


def test_approving_the_plan_review_pins_the_frozen_revision(plan_review_still_pending):
    """PRD §3.3: "When the `scope` is `PLAN_REVIEW`, exactly one design package of the project must be in `freeze_state` `FROZEN`; zero frozen packages, or more than one, is rejected with `ERR_NO_FROZEN_PACKAGE`."
    PRD §3.3: "On success, an approval whose `scope` is `PLAN_REVIEW` sets `pinned_package_id` to the `id` of the project's single frozen design package."

    Design: Difficulty/cross_entity_state_dependency/module_line_slot_depends_on_permit_record_state_plan_review_approval
    """
    world = plan_review_still_pending

    approved = validate_success(
        world.api.decide_permit(
            world.plan_review_permit["id"],
            f.permit_decision_payload("APPROVE"),
            STATE_PROGRAM_OFFICER,
        )
    )

    assert approved["status"] == "APPROVED"
    assert approved["pinned_package_id"] == world.package_id


def test_the_line_opens_the_moment_the_state_approval_goes_live(
    plan_review_still_pending,
):
    """PRD §3.3: "A track-and-scope pair counts as *live* when the project has a permit record with that `track` and that `scope` whose `status` is `APPROVED` and whose `expires_at` is either null or strictly later than the current clock instant."
    PRD §3.3: "Otherwise, if state plan review is live and the site side is also cleared, it is again `STATE_CLEARED_ONLY` — this fifth branch is the bifurcation tie-break, and it reports the state track because the state track is the one that releases factory production, even though both tracks are partially cleared."
    PRD §3.4: "Claiming a takt window moves `production_status` from `PLANNED` to `SLOTTED`, and the only payload field is `line_slot_start`, the instant at which the module wants the line."

    Design: Difficulty/cross_entity_state_dependency/module_line_slot_depends_on_permit_record_state_plan_review_approval
    """
    world = plan_review_still_pending
    validate_success(
        world.api.decide_permit(
            world.plan_review_permit["id"],
            f.permit_decision_payload("APPROVE"),
            STATE_PROGRAM_OFFICER,
        )
    )

    slotted = validate_success(
        world.api.schedule_line_slot(
            world.module_id(),
            f.line_slot_payload("2026-09-02T14:00:00Z"),
            world.factory_manager,
        )
    )

    assert_module_dimensions(slotted, production_status="SLOTTED")
    assert slotted["line_slot_minutes"] == 540
    assert world.refresh_project()["permit_posture"] == "STATE_CLEARED_ONLY"


@pytest.fixture
def finished_module_and_an_unqualified_agency(api):
    """A module off the end of the line, and an agency in no shape to certify.

    The agency is suspended and accredited only in Oregon, while the project
    builds in Washington.
    """
    world = fx.world_line_complete_module(
        api,
        agency_overrides={
            "accredited_state_codes": ["OR"],
            "accreditation_state": "SUSPENDED",
        },
    )
    return world


def test_a_suspended_agency_cannot_be_named_as_the_certifier(
    finished_module_and_an_unqualified_agency,
):
    """PRD §3.9: "The certifying agency must be more strictly qualified than an inspecting agency: its `accreditation_state` must be exactly `ACCREDITED`, so an agency on `PROBATION` — acceptable for recording inspections — cannot certify a draw and produces `ERR_AGENCY_NOT_ACCREDITED`."

    Design: Difficulty/cross_entity_state_dependency/draw_request_creation_depends_on_inspection_agency_accreditation_and_jurisdiction
    """
    world = finished_module_and_an_unqualified_agency

    validate_error(
        world.api.create_draw_request(
            f.draw_request_payload(world.project_id, world.agency_id, "WIP_DEPOSIT", 1),
            LENDER_DRAW_ADMINISTRATOR,
        ),
        ERR_AGENCY_NOT_ACCREDITED,
    )


def test_an_agency_accredited_in_the_wrong_state_is_still_refused(
    finished_module_and_an_unqualified_agency,
):
    """PRD §3.9: "Its `accredited_state_codes` must also contain the project's `state_code`, or the attempt is `ERR_AGENCY_JURISDICTION_MISMATCH`."
    PRD §2.2: "Agencies may be listed filtered by `agency_code` or `accreditation_state`, and their posture may later be revised by either a `ProgramAdmin` or a `StateProgramOfficer` supplying a new `accreditation_state` and optionally a replacement `accredited_state_codes` list; that revision increments the agency's `version`."

    Design: Difficulty/cross_entity_state_dependency/draw_request_creation_depends_on_inspection_agency_accreditation_and_jurisdiction
    """
    world = finished_module_and_an_unqualified_agency

    reinstated = validate_success(
        world.api.update_agency_accreditation(
            world.agency_id, f.accreditation_payload("ACCREDITED"), PROGRAM_ADMIN
        )
    )
    assert reinstated["accreditation_state"] == "ACCREDITED"
    # The optional replacement list was omitted, so the jurisdictions stand.
    assert reinstated["accredited_state_codes"] == ["OR"]

    validate_error(
        world.api.create_draw_request(
            f.draw_request_payload(world.project_id, world.agency_id, "WIP_DEPOSIT", 1),
            LENDER_DRAW_ADMINISTRATOR,
        ),
        ERR_AGENCY_JURISDICTION_MISMATCH,
    )


def test_the_draw_opens_once_the_agency_is_accredited_in_the_project_state(
    finished_module_and_an_unqualified_agency,
):
    """PRD §3.9: "A new draw is persisted with `status` `DRAFT`, `certified_at`, `funded_at` and `reject_reason` null, and `version` 1."
    PRD §3.9: "Under `WIP_DEPOSIT`, the basis is every module of the project whose `production_status` is `SLOTTED`, `IN_LINE` or `LINE_COMPLETE` and whose `qc_status` is not `HOLD`; each such module contributes its station-progress earned value as defined in §3.4 — the plant's `wip_unit_value_cents` pro-rated by completed stations — and a module that has never left the plant contributes normally."
    PRD §3.9: "Draws may be listed filtered by `project_id`, `certifying_agency_id`, `status` or `basis_mode`."

    Design: Difficulty/cross_entity_state_dependency/draw_request_creation_depends_on_inspection_agency_accreditation_and_jurisdiction
    """
    world = finished_module_and_an_unqualified_agency
    validate_success(
        world.api.update_agency_accreditation(
            world.agency_id,
            f.accreditation_payload("ACCREDITED", accredited_state_codes=["WA", "OR"]),
            PROGRAM_ADMIN,
        )
    )

    draw = validate_success(
        world.api.create_draw_request(
            f.draw_request_payload(world.project_id, world.agency_id, "WIP_DEPOSIT", 1),
            LENDER_DRAW_ADMINISTRATOR,
        ),
        201,
    )

    assert draw["status"] == "DRAFT"
    assert_cents(draw["basis_earned_cents"], 8750000, "basis_earned_cents")
    assert_cents(draw["requested_cents"], 1750000, "requested_cents")

    listed = validate_success(
        world.api.list_draw_requests(
            {"project_id": world.project_id}, LENDER_DRAW_ADMINISTRATOR
        )
    )
    assert [row["id"] for row in listed] == [draw["id"]]
