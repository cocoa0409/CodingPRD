"""Error precedence on post — the fixed §2.11 priority order decides which rejection surfaces."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_gate_operator_headers, post_payload,
    create_gas_reading, facility_version, setup_ticket_in_state,
)

POST_USER = "op_post"


def test_state_error_precedes_fiscal_on_post(api):
    """PRD §2.11: "State — the target resource is in a valid state for the requested
    transition, else `ERR_INVALID_STATE` (409)."
    PRD §2.11: "A given endpoint applies whichever of these checks are relevant to it, but
    always in this relative order, so that (for example) a stale facility version surfaces
    before a segregation-of-duties conflict, which in turn surfaces before an airspace or
    credit rejection."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_post
    """
    ctx = setup_ticket_in_state("WEIGHED", total_airspace=1000, cell_capacity=1000,
                                credit_limit=100, material="MSW", gross=10.0, tare=2.0)
    version = facility_version(ctx["facility"]["id"], POST_USER)
    resp = api.post_ticket(ctx["ticket"]["id"], post_payload(version),
                           make_gate_operator_headers(POST_USER))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_state_rejected_post_leaves_ticket_weighed(api):
    """PRD §2.11: "State — the target resource is in a valid state for the requested
    transition, else `ERR_INVALID_STATE` (409)."
    PRD §2.11: "Fiscal — on post, the hauler's balance plus this fee stays within the credit
    limit, else `ERR_CREDIT_LIMIT_EXCEEDED` (402)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_post
    """
    ctx = setup_ticket_in_state("WEIGHED", total_airspace=1000, cell_capacity=1000,
                                credit_limit=100, material="MSW", gross=10.0, tare=2.0)
    version = facility_version(ctx["facility"]["id"], POST_USER)
    resp = api.post_ticket(ctx["ticket"]["id"], post_payload(version),
                           make_gate_operator_headers(POST_USER))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    fetched = validate_success(api.get_ticket(ctx["ticket"]["id"], make_gate_operator_headers(POST_USER)))
    assert fetched["status"] == "WEIGHED"


def test_posture_safety_error_precedes_airspace_on_post(api):
    """PRD §2.11: "Posture and clearance safety — facility not `CLOSED`, special-waste
    manifest cleared, hauler not suspended, yielding `ERR_FACILITY_CLOSED`,
    `ERR_SPECIAL_WASTE_NOT_APPROVED`, or `ERR_HAULER_SUSPENDED` (all 409) as applicable."
    PRD §2.11: "A given endpoint applies whichever of these checks are relevant to it, but
    always in this relative order, so that (for example) a stale facility version surfaces
    before a segregation-of-duties conflict, which in turn surfaces before an airspace or
    credit rejection."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_post
    """
    ctx = setup_ticket_in_state("INSPECTED", total_airspace=1000, with_cell=False,
                                material="MSW", gross=10.0, tare=2.0)
    create_gas_reading(ctx["facility"]["id"], 500, "2026-03-01T09:00:00Z")
    version = facility_version(ctx["facility"]["id"], POST_USER)
    resp = api.post_ticket(ctx["ticket"]["id"], post_payload(version),
                           make_gate_operator_headers(POST_USER))
    validate_error(resp, ApiErrorId.ERR_FACILITY_CLOSED)


def test_posture_rejected_post_leaves_ticket_inspected(api):
    """PRD §2.11: "Posture and clearance safety — facility not `CLOSED`, special-waste
    manifest cleared, hauler not suspended, yielding `ERR_FACILITY_CLOSED`,
    `ERR_SPECIAL_WASTE_NOT_APPROVED`, or `ERR_HAULER_SUSPENDED` (all 409) as applicable."
    PRD §2.11: "Weight and airspace — weigh-out net weight positive and tare at most gross,
    and at least one open cell with sufficient airspace on post, yielding `ERR_EMPTY_LOAD`,
    `ERR_INVALID_WEIGHT`, or `ERR_NO_AIRSPACE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_post
    """
    ctx = setup_ticket_in_state("INSPECTED", total_airspace=1000, with_cell=False,
                                material="MSW", gross=10.0, tare=2.0)
    create_gas_reading(ctx["facility"]["id"], 500, "2026-03-01T09:00:00Z")
    version = facility_version(ctx["facility"]["id"], POST_USER)
    resp = api.post_ticket(ctx["ticket"]["id"], post_payload(version),
                           make_gate_operator_headers(POST_USER))
    validate_error(resp, ApiErrorId.ERR_FACILITY_CLOSED)
    fetched = validate_success(api.get_ticket(ctx["ticket"]["id"], make_gate_operator_headers(POST_USER)))
    assert fetched["status"] == "INSPECTED"
