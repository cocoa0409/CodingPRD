"""Weigh-out guards and the inspection PASS/REJECT branch."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_gate_operator_headers, make_facility_admin_headers,
    weigh_out_payload, inspect_payload,
    create_facility, create_hauler, create_ticket, inspect,
    setup_ticket_in_state,
)

INSPECT_USER = "op_insp"


def test_weighout_zero_net_weight_rejected_empty_load(api):
    """PRD §3.4: "the net weight — `gross_weight_tons` minus `tare_weight_tons` — must be
    strictly greater than zero, otherwise the load is treated as empty and rejected with
    `ERR_EMPTY_LOAD`."

    Design: Difficulty/boundary_precision_check/empty_load_zero_net_weight_boundary
    """
    facility = create_facility(1000)
    hauler = create_hauler(100_000_000)
    ticket = create_ticket(facility["id"], hauler["id"], material="MSW", gross_weight_tons=5.0,
                           op_id=INSPECT_USER)
    resp = api.weigh_out_ticket(ticket["id"], weigh_out_payload(5.0),
                                make_gate_operator_headers(INSPECT_USER))
    validate_error(resp, ApiErrorId.ERR_EMPTY_LOAD)
    fetched = validate_success(api.get_ticket(ticket["id"], make_gate_operator_headers(INSPECT_USER)))
    assert fetched["status"] == "CREATED"


def test_weighout_positive_net_weight_succeeds(api):
    """PRD §3.4: "the net weight — `gross_weight_tons` minus `tare_weight_tons` — must be
    strictly greater than zero, otherwise the load is treated as empty and rejected with
    `ERR_EMPTY_LOAD`."

    Design: Difficulty/boundary_precision_check/empty_load_zero_net_weight_boundary
    """
    facility = create_facility(1000)
    hauler = create_hauler(100_000_000)
    ticket = create_ticket(facility["id"], hauler["id"], material="MSW", gross_weight_tons=5.0,
                           op_id=INSPECT_USER)
    resp = api.weigh_out_ticket(ticket["id"], weigh_out_payload(4.0),
                                make_gate_operator_headers(INSPECT_USER))
    data = validate_success(resp)
    assert data["status"] == "WEIGHED"
    assert data["net_weight_tons"] == 1.0


def test_weighout_tare_exceeds_gross_returns_invalid_weight(api):
    """PRD §3.4: "the tare may not exceed the gross weight, otherwise the request is rejected
    with `ERR_INVALID_WEIGHT`".

    Design: Corner/validations/weighout_tare_exceeds_gross_returns_invalid_weight
    """
    facility = create_facility(500)
    hauler = create_hauler(100_000)
    ticket = create_ticket(facility["id"], hauler["id"], material="MSW", gross_weight_tons=5.0,
                           op_id=INSPECT_USER)
    resp = api.weigh_out_ticket(ticket["id"], weigh_out_payload(7.0),
                                make_gate_operator_headers(INSPECT_USER))
    validate_error(resp, ApiErrorId.ERR_INVALID_WEIGHT)


def test_inspect_reject_terminates_with_no_hauler_charge(api):
    """PRD §3.5: "When the `result` is a reject, the ticket advances `WEIGHED → REJECTED`:
    the supplied `reject_reason` is recorded, no airspace is consumed, no hauler charge is
    raised, and any linked manifest is left untouched in `SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/ticket_branch_inspect_pass_vs_reject
    """
    ctx = setup_ticket_in_state("WEIGHED", material="MSW", gross=10.0, tare=2.0,
                                inspect_user=INSPECT_USER)
    rejected = inspect(ctx["ticket"]["id"], "REJECT", reject_reason="contaminated",
                       op_id=INSPECT_USER)
    assert rejected["status"] == "REJECTED"
    hauler = validate_success(
        api.get_hauler_account(ctx["hauler"]["id"], make_facility_admin_headers("adm1")))
    assert hauler["balance_cents"] == 0


def test_inspect_pass_advances_to_inspected_and_records_inspector(api):
    """PRD §3.5: "When the `result` is a pass, the ticket advances `WEIGHED → INSPECTED` and
    the inspecting operator's identity is written to `inspected_by`."

    Design: Difficulty/non_linear_state_machine/ticket_branch_inspect_pass_vs_reject
    """
    ctx = setup_ticket_in_state("WEIGHED", material="MSW", gross=10.0, tare=2.0,
                                inspect_user=INSPECT_USER)
    passed = inspect(ctx["ticket"]["id"], "PASS", op_id=INSPECT_USER)
    assert passed["status"] == "INSPECTED"
    assert passed["inspected_by"] == INSPECT_USER


def test_inspect_before_weighout_returns_invalid_state(api):
    """PRD §3.5: "A weighed load is inspected before it can be posted."
    PRD §2.11: "State — the target resource is in a valid state for the requested transition,
    else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/ticket_inspect_before_weighout_returns_invalid_state
    """
    facility = create_facility(500)
    hauler = create_hauler(100_000)
    ticket = create_ticket(facility["id"], hauler["id"], material="MSW", gross_weight_tons=6.0,
                           op_id=INSPECT_USER)
    resp = api.inspect_ticket(ticket["id"], inspect_payload("PASS"),
                              make_gate_operator_headers(INSPECT_USER))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
