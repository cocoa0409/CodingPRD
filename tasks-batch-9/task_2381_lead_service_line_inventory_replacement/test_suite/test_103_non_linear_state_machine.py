"""Queue A - rule ``non_linear_state_machine``.

Both the service line and the replacement order carry two independent axes. One
instance drives the inventory axis forward while the replacement axis is parked
mid-program; the other walks the order's work axis around its ``DRAFT -> SCOPED
-> DRAFT`` cycle and checks that the two consent branches undo each other.
"""

import pytest

from test_helpers import ApiClient, fixtures
from test_helpers.types import (
    CertaintyBasis,
    Classification,
    ConsentBarrierReason,
    ConsentOutcome,
    ConsentState,
    FulfillmentState,
    FundingMode,
    InventoryState,
    InventoryStatus,
    Material,
    OrderScope,
    ProgramPosture,
    ReplacementState,
    Side,
    SourceType,
)


# ---------------------------------------------------------------------------
# service_line_inventory_axis_advances_while_replacement_axis_holds_in_program
# ---------------------------------------------------------------------------


def _line_in_program_awaiting_second_side(api: ApiClient):
    """A published LEAD line parked at IN_PROGRAM with field evidence on one side."""
    system = fixtures.create_water_system(
        api,
        "IL2031006",
        system_name="Kestrel Ridge Water",
        compliance_deadline_date="2027-10-16",
        baseline_lead_and_grr_count=100,
        disadvantaged_tract_codes=[],
        funding_mode=FundingMode.WATERFALL,
    )
    line = fixtures.make_lead_line(
        api, system["id"], address_label="101 Elm St", census_tract_code="17031-9900"
    )
    fixtures.publish_inventory(api, system["id"], line["id"])
    order = fixtures.open_order(
        api,
        line["id"],
        estimated_cost_cents=100000,
        excavation_start_date="2026-08-10",
        excavation_end_date="2026-08-11",
    )
    fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.POTHOLE,
        side=Side.UTILITY,
        observed_material=Material.LEAD,
        observed_at="2026-08-01T08:00:00Z",
    )
    return {"system": system, "line": line, "order": order}


def test_inventory_axis_reaches_verified_while_the_replacement_axis_holds_in_program(
    api: ApiClient,
) -> None:
    """Both-sides field evidence verifies a line that is already mid-program.

    PRD 3.2: "Neither axis is terminal and neither drives the other directly: a
    line may be `CLASSIFIED_PROVISIONAL` while already `IN_PROGRAM`, or
    `CLASSIFIED_VERIFIED` while still `NOT_REQUIRED`."
    PRD 3.2: "The moment that both-sides field-evidence condition does hold —
    immediately after any evidence insertion, whether manual, by override, or by
    an appointment cascade — the server moves the line from
    `CLASSIFIED_PROVISIONAL` to `CLASSIFIED_VERIFIED` on its own initiative."

    Design: Difficulty/non_linear_state_machine/service_line_inventory_axis_advances_while_replacement_axis_holds_in_program
    """
    scenario = _line_in_program_awaiting_second_side(api)

    before = fixtures.read_service_line(api, scenario["line"]["id"])
    assert before["inventory_state"] == InventoryState.CLASSIFIED_PROVISIONAL
    assert before["replacement_state"] == ReplacementState.IN_PROGRAM

    fixtures.add_evidence(
        api,
        scenario["line"]["id"],
        source_type=SourceType.VISUAL_INSPECTION,
        side=Side.CUSTOMER,
        observed_material=Material.LEAD,
        observed_at="2026-08-01T09:00:00Z",
    )

    after = fixtures.read_service_line(api, scenario["line"]["id"])
    assert after["inventory_state"] == InventoryState.CLASSIFIED_VERIFIED
    assert after["replacement_state"] == ReplacementState.IN_PROGRAM
    assert after["certainty_basis"] == CertaintyBasis.FIELD_BASIS
    assert after["certainty_score"] == pytest.approx(91.00)
    assert after["classification"] == Classification.LEAD
    assert after["replacement_priority_score"] == pytest.approx(65.00)


def test_verifying_a_line_without_changing_its_classification_leaves_system_published(
    api: ApiClient,
) -> None:
    """The line stays LEAD, so no amendment fires and the draft order is untouched.

    PRD 2.8: "And only then — if the water system's `inventory_status` was
    `PUBLISHED` and the recompute actually changed at least one service line's
    `classification` to a different value than it held before — does the water
    system move to `AMENDMENT_PENDING`, which by clause 3 of §2.7 forces the
    posture to `RESTRICTED`."
    PRD 3.7: "The new order is created with `fulfillment_state` `DRAFT` and
    `consent_state` `NOT_REQUESTED`, and the service line moves from `ELIGIBLE` to
    `IN_PROGRAM`"

    Design: Difficulty/non_linear_state_machine/service_line_inventory_axis_advances_while_replacement_axis_holds_in_program
    """
    scenario = _line_in_program_awaiting_second_side(api)

    fixtures.add_evidence(
        api,
        scenario["line"]["id"],
        source_type=SourceType.VISUAL_INSPECTION,
        side=Side.CUSTOMER,
        observed_material=Material.LEAD,
        observed_at="2026-08-01T09:00:00Z",
    )

    system = fixtures.read_water_system(api, scenario["system"]["id"])
    assert system["inventory_status"] == InventoryStatus.PUBLISHED
    assert system["program_posture"] == ProgramPosture.RESTRICTED
    assert system["lead_count"] == 1

    order = fixtures.read_order(api, scenario["order"]["id"])
    assert order["fulfillment_state"] == FulfillmentState.DRAFT
    assert order["consent_state"] == ConsentState.NOT_REQUESTED


# ---------------------------------------------------------------------------
# replacement_order_consent_cycle_revisits_scoping_fork_with_divergent_side_effects
# ---------------------------------------------------------------------------


def _no_response_order(api: ApiClient):
    """A disadvantaged LEAD line whose order has been canvassed to NO_RESPONSE."""
    system = fixtures.create_water_system(
        api,
        "IL2031007",
        system_name="Sableton Water",
        compliance_deadline_date="2027-10-16",
        baseline_lead_and_grr_count=100,
        disadvantaged_tract_codes=["17031-8402"],
        funding_mode=FundingMode.WATERFALL,
    )
    line = fixtures.make_lead_line(
        api, system["id"], address_label="101 Elm St", census_tract_code="17031-8402"
    )
    fixtures.publish_inventory(api, system["id"], line["id"])
    order = fixtures.open_order(
        api,
        line["id"],
        estimated_cost_cents=100000,
        excavation_start_date="2026-08-10",
        excavation_end_date="2026-08-11",
    )
    fixtures.request_consent(api, order["id"])
    scoped = fixtures.respond_consent(
        api,
        order["id"],
        outcome=ConsentOutcome.NO_RESPONSE,
        barrier_reason=ConsentBarrierReason.NO_CONTACT,
    )
    return {"system": system, "line": line, "order": order, "scoped": scoped}


def test_second_consent_request_walks_the_work_axis_back_from_scoped_to_draft(
    api: ApiClient,
) -> None:
    """Re-canvassing a NO_RESPONSE order rewinds it to DRAFT and clears the scope.

    PRD 3.7: "A `NO_RESPONSE` order can be re-canvassed, and only a `NO_RESPONSE`
    order can."
    PRD 3.7: "A second consent request against an order whose `consent_state` is
    `NO_RESPONSE` and whose `fulfillment_state` is `SCOPED` returns
    `consent_state` to `REQUESTED` and walks the work axis back from `SCOPED` to
    `DRAFT`, clearing `scope` and `consent_barrier_reason` to null, setting the
    service line's `consent_barrier_flag` back to false and recomputing its
    `replacement_priority_score` without the barrier penalty, and advancing the
    order's `version` by one."

    Design: Difficulty/non_linear_state_machine/replacement_order_consent_cycle_revisits_scoping_fork_with_divergent_side_effects
    """
    scenario = _no_response_order(api)

    assert scenario["scoped"]["fulfillment_state"] == FulfillmentState.SCOPED
    assert scenario["scoped"]["scope"] == OrderScope.PARTIAL
    penalized = fixtures.read_service_line(api, scenario["line"]["id"])
    assert penalized["consent_barrier_flag"] is True
    assert penalized["replacement_priority_score"] == pytest.approx(67.00)

    recanvassed = fixtures.request_consent(api, scenario["order"]["id"])

    assert recanvassed["fulfillment_state"] == FulfillmentState.DRAFT
    assert recanvassed["consent_state"] == ConsentState.REQUESTED
    assert recanvassed["scope"] is None
    assert recanvassed["consent_barrier_reason"] is None

    rewound = fixtures.read_service_line(api, scenario["line"]["id"])
    assert rewound["consent_barrier_flag"] is False
    assert rewound["replacement_priority_score"] == pytest.approx(75.00)


def test_revisiting_the_scoping_fork_on_the_granting_branch_reverses_the_side_effects(
    api: ApiClient,
) -> None:
    """The second pass through DRAFT -> SCOPED lands FULL scope and no barrier.

    PRD 3.7: "On the **granting branch**, with `outcome` of `GRANTED`, the order's
    `scope` is set to `FULL` and its `consent_state` to `GRANTED`."
    PRD 3.7: "The service line's `consent_barrier_flag` stays false and its
    `replacement_priority_score` is recomputed with no barrier penalty."
    PRD 3.7: "Where the granting branch mutates no service-line field, this branch
    mutates two."

    Design: Difficulty/non_linear_state_machine/replacement_order_consent_cycle_revisits_scoping_fork_with_divergent_side_effects
    """
    scenario = _no_response_order(api)
    fixtures.request_consent(api, scenario["order"]["id"])

    granted = fixtures.respond_consent(
        api, scenario["order"]["id"], outcome=ConsentOutcome.GRANTED
    )

    assert granted["fulfillment_state"] == FulfillmentState.SCOPED
    assert granted["consent_state"] == ConsentState.GRANTED
    assert granted["scope"] == OrderScope.FULL
    assert granted["consent_barrier_reason"] is None

    line = fixtures.read_service_line(api, scenario["line"]["id"])
    assert line["consent_barrier_flag"] is False
    assert line["replacement_priority_score"] == pytest.approx(75.00)
