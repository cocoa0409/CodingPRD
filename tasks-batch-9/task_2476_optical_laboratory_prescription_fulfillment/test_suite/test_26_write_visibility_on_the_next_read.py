"""A trace is fully computed in its own response and fully visible on the next read."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f, fixtures
from test_helpers.test_users import OPTICIAN_A_HEADERS, TECHNICIAN_A_HEADERS

TRACE = {"a_mm": 50.0, "b_mm": 28.0, "ed_mm": 52.0, "dbl_mm": 17.0}


def _traced_draft_order(api):
    """Traces the stock DRAFT order once, returning the create response verbatim."""
    scenario = fixtures.stock_draft_order(api)
    assert scenario["order"]["fulfillment_status"] == "DRAFT"
    assert scenario["order_version"] == 1
    layout = validate_success(
        api.create_frame_layout(
            f.create_frame_layout_payload(
                scenario["order_id"], scenario["order_version"], **TRACE
            ),
            OPTICIAN_A_HEADERS,
        ),
        expected_status=201,
    )
    scenario["layout"] = layout
    scenario["layout_id"] = layout["id"]
    return scenario


def test_the_trace_response_already_carries_the_computed_blank_requirement(api):
    """No second call is needed to learn the geometry the write derived.

    PRD 3.4: "The blank each eye needs is then `ed_mm` plus twice that eye's total
    decentration plus a chuck allowance of 2.0 millimetres, rounded half up to one
    decimal place."

    PRD 3.4: "`layout_status` follows from the result: `BLANK_TOO_SMALL` when
    `required_blank_diameter_mm` exceeds the largest blank this laboratory can chuck,
    85.0 millimetres, and `COMPUTED` otherwise."

    Design: Corner/consistency_model/the_layout_geometry_and_the_order_bump_are_visible_in_the_same_round_trip
    """
    scenario = _traced_draft_order(api)

    layout = scenario["layout"]

    # ed 52.0 plus twice the 2.0 horizontal decentration plus the 2.0 chuck allowance.
    assert layout["required_blank_diameter_mm"] == 58.0
    assert layout["effective_fitting_height_mm"] == 16.0
    assert layout["layout_status"] == "COMPUTED"


def test_the_decentrations_are_readable_at_their_natural_precision(api):
    """Frame PD 67.0 against two 31.5 mm halves, and 16.0 against half of 28.0.

    PRD 3.4: "For each eye, the horizontal decentration is the absolute difference
    between half of that frame pupillary distance and that eye's monocular pupillary
    distance: `decentration_h_od_mm` uses `monocular_pd_od_mm` and
    `decentration_h_os_mm` uses `monocular_pd_os_mm`."

    PRD 3.4: "The vertical decentration, `decentration_v_mm`, is the absolute difference
    between `effective_fitting_height_mm` and half of `b_mm`, and it is a single figure
    shared by both eyes."

    Design: Corner/consistency_model/the_layout_geometry_and_the_order_bump_are_visible_in_the_same_round_trip
    """
    scenario = _traced_draft_order(api)

    layout = fixtures.read_layout(api, scenario["layout_id"])

    assert layout["decentration_h_od_mm"] == 2.0
    assert layout["decentration_h_os_mm"] == 2.0
    assert layout["decentration_v_mm"] == 2.0
    assert layout["rx_order_id"] == scenario["order_id"]


def test_the_parent_order_shows_the_bump_and_the_advance_on_the_very_next_read(api):
    """One trace, and the order is already at version 2 in LAYOUT_READY.

    PRD 3.4: "The order's `version` is incremented by 1. And the order advances `DRAFT →
    LAYOUT_READY`, or stays `LAYOUT_READY → LAYOUT_READY` on a retrace — **regardless**
    of the computed `layout_status`."

    Design: Corner/consistency_model/the_layout_geometry_and_the_order_bump_are_visible_in_the_same_round_trip
    """
    scenario = _traced_draft_order(api)

    order = validate_success(
        api.get_rx_order(scenario["order_id"], TECHNICIAN_A_HEADERS)
    )

    assert order["fulfillment_status"] == "LAYOUT_READY"
    assert order["version"] == 2

    rows, meta = validate_paginated(
        api.list_order_frame_layouts(scenario["order_id"], TECHNICIAN_A_HEADERS)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == scenario["layout_id"]
