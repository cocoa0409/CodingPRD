"""Requests that break two rules at once, and only ever hear about one.

The rejection ladder of §2.6 is ranked, and the lower rank answers. A draw that
is both past its draft state and over the contract ceiling reports the state
gate; a takt request against a paused line whose start also lies in the past
reports the safety gate. Each pair is set up so that both rules genuinely apply.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CONTRACT_BALANCE_EXCEEDED,
    ERR_DRAW_NOT_DRAFT,
    ERR_FACTORY_LINE_NOT_RUNNING,
    ERR_LINE_SLOT_IN_PAST,
)
from test_helpers.assertions import assert_cents, assert_module_dimensions
from test_helpers.test_users import LENDER_DRAW_ADMINISTRATOR, PROGRAM_ADMIN


@pytest.fixture
def one_certified_draw_against_a_small_contract(api):
    """A 320,000 cent contract, one certified deposit draw and a second in draft.

    The first draw was certified while the module stood at station 1, for 291,667
    cents against a ceiling of 304,000. The module has since come off the end of
    the line, so the second draw asks for the full unit value and cannot possibly
    fit under the same ceiling.
    """
    world = fx.world_with_module(api, project_overrides={"contract_price_cents": 320000})
    fx.schedule_slot(world, "M-01")
    fx.advance_stations(world, "M-01", 1)

    first = fx.create_draw(api, world.project_id, world.agency_id, "WIP_DEPOSIT", 1)
    first = validate_success(
        api.certify_draw(first["id"], f.certify_payload(), LENDER_DRAW_ADMINISTRATOR)
    )
    fx.advance_stations(world, "M-01", 5)
    second = fx.create_draw(api, world.project_id, world.agency_id, "WIP_DEPOSIT", 2)
    return world, first, second


def test_certifying_an_already_certified_draw_reports_the_lifecycle_gate(
    one_certified_draw_against_a_small_contract,
):
    """PRD §2.6: "The server evaluates candidate rejections in a strict ascending rank order and returns the **first** violated rule; no later rule may pre-empt an earlier one."
    PRD §2.6: "Ranks 39 through 59 are the state preconditions, in this order: `ERR_DESIGN_REVIEW_IN_FLIGHT` (39), `ERR_DESIGN_NOT_SUBMITTABLE` (40), `ERR_DESIGN_NOT_IN_REVIEW` (41), `ERR_DRAW_NOT_DRAFT` (42), `ERR_DRAW_NOT_CERTIFIED` (43), `ERR_MODULE_NOT_PLANNED` (44), `ERR_MODULE_NOT_SLOTTED` (45), `ERR_MODULE_NOT_ON_LINE` (46), `ERR_MODULE_NOT_READY_TO_SET` (47), `ERR_MODULE_NOT_SET` (48), `ERR_SHIPMENT_NOT_LOADABLE` (49), `ERR_SURVEY_NOT_PENDING` (50), `ERR_SHIPMENT_NOT_PERMITTED` (51), `ERR_SHIPMENT_NOT_DISPATCHED` (52), `ERR_SHIPMENT_TERMINAL` (53), `ERR_PERMIT_ALREADY_DECIDED` (54), `ERR_INSPECTION_NOT_PENDING` (55), `ERR_HOLD_NOT_ACTIVE` (56), `ERR_CLAIM_NOT_ADJUDICABLE` (57), `ERR_CLAIM_NOT_ADJUDICATED` (58) and `ERR_DISPUTE_ROUND_LIMIT` (59)."
    PRD §3.9: "It takes an optional `certification_note` and requires the draw's `status` to be `DRAFT`; certifying anything else is `ERR_DRAW_NOT_DRAFT`."

    Design: Difficulty/priority_pair_validation_conflict/draw_state_priority_42_beats_fiscal_ceiling_priority_90_on_certify
    """
    world, first, _ = one_certified_draw_against_a_small_contract
    assert first["status"] == "CERTIFIED"
    assert_cents(first["certified_cents"], 291667, "certified_cents")

    validate_error(
        world.api.certify_draw(
            first["id"], f.certify_payload(), LENDER_DRAW_ADMINISTRATOR
        ),
        ERR_DRAW_NOT_DRAFT,
    )


def test_a_draft_draw_that_would_breach_the_contract_ceiling_is_refused_on_the_ceiling(
    one_certified_draw_against_a_small_contract,
):
    """PRD §2.6: "The fiscal rules come last, in this order: `ERR_CONTRACT_BALANCE_EXCEEDED` (90), `ERR_NO_CERTIFIABLE_WIP` (91) and `ERR_DRAW_SEQUENCE_GAP` (92)."
    PRD §3.9: "The **contract ceiling** first: the sum of `certified_cents` across every *other* draw request of the project whose `status` is `CERTIFIED` or `FUNDED`, added to this draw's own `certified_cents`, must not exceed the project's `contract_price_cents` multiplied by one minus the project's `retainage_pct`, that product rounded half up to a whole cent."

    Design: Difficulty/priority_pair_validation_conflict/draw_state_priority_42_beats_fiscal_ceiling_priority_90_on_certify
    """
    world, _, second = one_certified_draw_against_a_small_contract
    assert_cents(second["requested_cents"], 1750000, "requested_cents")

    validate_error(
        world.api.certify_draw(
            second["id"], f.certify_payload(), LENDER_DRAW_ADMINISTRATOR
        ),
        ERR_CONTRACT_BALANCE_EXCEEDED,
    )

    still_draft = validate_success(
        world.api.get_draw_request(second["id"], PROGRAM_ADMIN)
    )
    assert still_draft["status"] == "DRAFT"
    assert_cents(
        world.refresh_project()["wip_certified_cents"], 291667, "wip_certified_cents"
    )


@pytest.fixture
def paused_line_and_a_module_wanting_a_past_slot(api):
    """A released project whose plant has stopped its line."""
    world = fx.world_with_module(api)
    world.factory = validate_success(
        api.update_factory_line_state(
            world.factory_id, f.line_state_payload("PAUSED"), PROGRAM_ADMIN
        )
    )
    return world


def test_a_paused_line_answers_before_the_requested_instant_is_examined(
    paused_line_and_a_module_wanting_a_past_slot,
):
    """PRD §2.6: "Ranks 60 through 66 are the safety and regulatory gates, in this order: `ERR_FACTORY_LINE_NOT_RUNNING` (60), `ERR_PICK_RADIUS_OFF_CHART` (61), `ERR_CRANE_CAPACITY_EXCEEDED` (62), `ERR_WEATHER_EXPOSURE_LIMIT` (63), `ERR_SET_NOT_PERMITTED` (64), `ERR_QC_HOLD_BLOCKS_OPERATION` (65) and `ERR_QC_NOT_RELEASED` (66)."
    PRD §3.4: "The plant resolved through the project's `factory_id` must have `line_state` `RUNNING`, or the request is `ERR_FACTORY_LINE_NOT_RUNNING`."

    Design: Difficulty/priority_pair_validation_conflict/line_safety_priority_60_beats_temporal_priority_76_on_schedule_line_slot
    """
    world = paused_line_and_a_module_wanting_a_past_slot
    assert world.factory["line_state"] == "PAUSED"

    # The requested instant is two days behind the clock, so the temporal rule
    # at rank 76 is violated as well.
    validate_error(
        world.api.schedule_line_slot(
            world.module_id(),
            f.line_slot_payload("2026-08-30T14:00:00Z"),
            world.factory_manager,
        ),
        ERR_FACTORY_LINE_NOT_RUNNING,
    )


def test_restarting_the_line_uncovers_the_start_instant_lying_in_the_past(
    paused_line_and_a_module_wanting_a_past_slot,
):
    """PRD §2.6: "Ranks 76 through 80 are the temporal rules, in this order: `ERR_LINE_SLOT_IN_PAST` (76), `ERR_LINE_SLOT_OUTSIDE_SHIFT` (77), `ERR_PICK_WINDOW_INVALID` (78), `ERR_TRANSPORT_PERMIT_EXPIRED` (79) and `ERR_CLOCK_NOT_MONOTONIC` (80)."
    PRD §3.4: "The requested `line_slot_start` must be at or after the current logical clock instant — a start exactly equal to the present instant is acceptable — or the request is `ERR_LINE_SLOT_IN_PAST`."

    Design: Difficulty/priority_pair_validation_conflict/line_safety_priority_60_beats_temporal_priority_76_on_schedule_line_slot
    """
    world = paused_line_and_a_module_wanting_a_past_slot
    restarted = validate_success(
        world.api.update_factory_line_state(
            world.factory_id, f.line_state_payload("RUNNING"), PROGRAM_ADMIN
        )
    )
    assert restarted["line_state"] == "RUNNING"

    validate_error(
        world.api.schedule_line_slot(
            world.module_id(),
            f.line_slot_payload("2026-08-30T14:00:00Z"),
            world.factory_manager,
        ),
        ERR_LINE_SLOT_IN_PAST,
    )

    module = world.refresh_module()
    assert_module_dimensions(module, production_status="PLANNED")
    assert module["line_slot_start"] is None
    assert world.refresh_factory()["committed_line_minutes"] == 0
