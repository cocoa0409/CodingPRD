"""Posting: airspace consumption, cell/facility cascade, and facility-version concurrency."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_gate_operator_headers, post_payload,
    setup_ticket_in_state, setup_two_inspected_tickets_same_facility,
    facility_version, post_ticket, get_facility,
)

POST_USER = "op_post"


def test_post_fills_cell_to_capacity(api):
    """PRD §3.6: "If the cell's `consumed_cubic_yards` then reaches or exceeds its
    `capacity_cubic_yards`, the cell transitions `OPEN → FULL`; and if that newly full cell
    leaves the facility with no `OPEN` cell still holding remaining airspace, the facility's
    `acceptance_posture` is recomputed to `CLOSED`."

    Design: Difficulty/transitive_cascade/post_airspace_cascade_cell_full_facility_closed
    """
    ctx = setup_ticket_in_state("INSPECTED", total_airspace=0.75, cell_capacity=0.75,
                                material="CONSTRUCTION_DEBRIS", gross=1.5, tare=1.0)
    post_ticket(ctx["ticket"]["id"], ctx["facility"]["id"], op_id=POST_USER)
    cell = validate_success(api.get_cell(ctx["cell"]["id"], make_gate_operator_headers(POST_USER)))
    assert cell["consumed_cubic_yards"] == 0.75
    assert cell["status"] == "FULL"


def test_post_full_cell_closes_facility(api):
    """PRD §3.6: "If the cell's `consumed_cubic_yards` then reaches or exceeds its
    `capacity_cubic_yards`, the cell transitions `OPEN → FULL`; and if that newly full cell
    leaves the facility with no `OPEN` cell still holding remaining airspace, the facility's
    `acceptance_posture` is recomputed to `CLOSED`."

    Design: Difficulty/transitive_cascade/post_airspace_cascade_cell_full_facility_closed
    """
    ctx = setup_ticket_in_state("INSPECTED", total_airspace=0.75, cell_capacity=0.75,
                                material="CONSTRUCTION_DEBRIS", gross=1.5, tare=1.0)
    post_ticket(ctx["ticket"]["id"], ctx["facility"]["id"], op_id=POST_USER)
    facility = get_facility(ctx["facility"]["id"])
    assert facility["acceptance_posture"] == "CLOSED"


def test_diverted_load_consumes_no_airspace(api):
    """PRD §3.6: "The airspace this load consumes, `posted_airspace_cy`, is the ticket's
    `net_weight_tons` multiplied by 1.5 and rounded half up to two decimal places for a
    landfilled material, and exactly 0 for a diverted material (which is recycled and occupies
    no cell)."

    Design: Corner/calculations/diverted_load_consumes_no_airspace
    """
    ctx = setup_ticket_in_state("INSPECTED", total_airspace=500, cell_capacity=100,
                                credit_limit=100_000, material="GREEN_WASTE", gross=12.0, tare=2.0)
    posted = post_ticket(ctx["ticket"]["id"], ctx["facility"]["id"], op_id=POST_USER)
    assert posted["status"] == "POSTED"
    assert posted["posted_airspace_cy"] == 0
    cell = validate_success(api.get_cell(ctx["cell"]["id"], make_gate_operator_headers(POST_USER)))
    assert cell["consumed_cubic_yards"] == 0


def test_post_without_sufficient_open_cell_returns_no_airspace(api):
    """PRD §3.6: "For a landfilled (non-diverted) material, there must be at least one `OPEN`
    cell in the facility whose `remaining_cubic_yards` is at least the airspace this load will
    consume, otherwise `ERR_NO_AIRSPACE`."

    Design: Corner/validations/no_open_cell_with_airspace_returns_no_airspace
    """
    ctx = setup_ticket_in_state("INSPECTED", total_airspace=500, cell_capacity=1.0,
                                material="MSW", gross=10.0, tare=2.0)
    version = facility_version(ctx["facility"]["id"], POST_USER)
    resp = api.post_ticket(ctx["ticket"]["id"], post_payload(version),
                           make_gate_operator_headers(POST_USER))
    validate_error(resp, ApiErrorId.ERR_NO_AIRSPACE)


def test_stale_facility_version_on_post_rejected(api):
    """PRD §2.7: "If `expected_facility_version` does not equal the facility's current
    `version`, the post is rejected with `ERR_STALE_FACILITY_VERSION` (HTTP 412): another post
    has already consumed airspace and advanced the facility's `version` since this operator
    last read it, so this operator's view of remaining airspace and posture is out of date."

    Design: Corner/cross_cutting/occ_stale_facility_version_conflict
    """
    ctx = setup_two_inspected_tickets_same_facility()
    post_ticket(ctx["t1"]["id"], ctx["facility"]["id"], op_id=POST_USER,
                expected_version=ctx["pre_version"])
    resp = api.post_ticket(ctx["t2"]["id"], post_payload(ctx["pre_version"]),
                           make_gate_operator_headers(POST_USER))
    validate_error(resp, ApiErrorId.ERR_STALE_FACILITY_VERSION)


def test_successful_post_increments_facility_version_by_one(api):
    """PRD §2.7: "Each successful post and each void of a posted ticket increments
    `Facility.version` by exactly 1, which is what makes a subsequent stale post detectable."

    Design: Corner/cross_cutting/facility_version_increments_on_post
    """
    ctx = setup_ticket_in_state("INSPECTED", total_airspace=500, cell_capacity=100,
                                material="CONSTRUCTION_DEBRIS", gross=1.5, tare=1.0)
    version = facility_version(ctx["facility"]["id"], POST_USER)
    posted = post_ticket(ctx["ticket"]["id"], ctx["facility"]["id"], op_id=POST_USER,
                         expected_version=version)
    assert posted["status"] == "POSTED"
    facility = get_facility(ctx["facility"]["id"])
    assert facility["version"] == version + 1
