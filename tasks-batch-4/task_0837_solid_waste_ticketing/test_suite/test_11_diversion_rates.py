"""The facility's forward-looking vs actual diversion rates read from different ticket sets."""
from test_helpers import (
    create_facility, create_cell, create_hauler, create_ticket, weigh_out, inspect,
    post_ticket, get_facility,
)

INSPECT_USER = "op_insp"
POST_USER = "op_post"


def _facility_with_one_posted_green_one_inspected_msw(api):
    facility = create_facility(1000)
    create_cell(facility["id"], 1000)
    hauler = create_hauler(100_000_000)
    green = create_ticket(facility["id"], hauler["id"], material="GREEN_WASTE",
                          gross_weight_tons=12.0, op_id=INSPECT_USER)
    weigh_out(green["id"], 2.0, op_id=INSPECT_USER)
    inspect(green["id"], "PASS", op_id=INSPECT_USER)
    post_ticket(green["id"], facility["id"], op_id=POST_USER)
    msw = create_ticket(facility["id"], hauler["id"], material="MSW",
                        gross_weight_tons=8.0, op_id=INSPECT_USER)
    weigh_out(msw["id"], 2.0, op_id=INSPECT_USER)
    inspect(msw["id"], "PASS", op_id=INSPECT_USER)
    return facility


def test_diversion_provisional_counts_inspected_and_posted(api):
    """PRD §2.9: "The forward-looking `diversion_rate_provisional` counts tickets in either
    `INSPECTED` or `POSTED` status, while the actual `diversion_rate_final` counts only
    `POSTED` tickets."

    Design: Difficulty/dual_variant_calc/facility_diversion_provisional_vs_final
    """
    facility = _facility_with_one_posted_green_one_inspected_msw(api)
    fetched = get_facility(facility["id"])
    assert fetched["diversion_rate_provisional"] == 0.625


def test_diversion_final_counts_posted_only(api):
    """PRD §2.9: "The forward-looking `diversion_rate_provisional` counts tickets in either
    `INSPECTED` or `POSTED` status, while the actual `diversion_rate_final` counts only
    `POSTED` tickets."

    Design: Difficulty/dual_variant_calc/facility_diversion_provisional_vs_final
    """
    facility = _facility_with_one_posted_green_one_inspected_msw(api)
    fetched = get_facility(facility["id"])
    assert fetched["diversion_rate_final"] == 1.0
