"""Posting preconditions: posture, segregation, credit, special-waste clearance, manifest match."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_gate_operator_headers, post_payload,
    create_facility, create_cell, create_hauler, create_manifest,
    create_ticket, weigh_out, inspect, create_gas_reading,
    facility_version, post_ticket, setup_ticket_in_state,
)

INSPECT_USER = "op_insp"
POST_USER = "op_post"


def test_post_into_closed_facility_rejected(api):
    """PRD §3.6: "The facility's `acceptance_posture` must not be `CLOSED`, otherwise
    `ERR_FACILITY_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/ticket_post_requires_facility_not_closed
    """
    ctx = setup_ticket_in_state("INSPECTED", total_airspace=1000, cell_capacity=1000,
                                material="MSW", gross=10.0, tare=2.0)
    create_gas_reading(ctx["facility"]["id"], 620, "2026-03-01T11:00:00Z")
    version = facility_version(ctx["facility"]["id"], POST_USER)
    resp = api.post_ticket(ctx["ticket"]["id"], post_payload(version),
                           make_gate_operator_headers(POST_USER))
    validate_error(resp, ApiErrorId.ERR_FACILITY_CLOSED)
    fetched = validate_success(api.get_ticket(ctx["ticket"]["id"], make_gate_operator_headers(POST_USER)))
    assert fetched["status"] == "INSPECTED"


def test_post_into_open_facility_succeeds(api):
    """PRD §3.6: "The facility's `acceptance_posture` must not be `CLOSED`, otherwise
    `ERR_FACILITY_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/ticket_post_requires_facility_not_closed
    """
    ctx = setup_ticket_in_state("INSPECTED", total_airspace=1000, cell_capacity=1000,
                                material="MSW", gross=10.0, tare=2.0)
    posted = post_ticket(ctx["ticket"]["id"], ctx["facility"]["id"], op_id=POST_USER)
    assert posted["status"] == "POSTED"


def test_post_by_inspector_rejected_segregation(api):
    """PRD §3.6: "The posting operator's `X-User-ID` must differ from the ticket's
    `inspected_by`; a match is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/post_same_user_inspected_returns_segregation
    """
    ctx = setup_ticket_in_state("INSPECTED", total_airspace=500, cell_capacity=100,
                                material="MSW", gross=6.0, tare=2.0, inspect_user="op_same")
    version = facility_version(ctx["facility"]["id"], "op_same")
    resp = api.post_ticket(ctx["ticket"]["id"], post_payload(version),
                           make_gate_operator_headers("op_same"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


def test_post_over_credit_limit_rejected(api):
    """PRD §3.6: "The hauler's `balance_cents` plus this ticket's `tipping_fee_cents` must
    not exceed the hauler's `credit_limit_cents`, otherwise `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Corner/validations/post_over_credit_limit_returns_fiscal_error
    """
    ctx = setup_ticket_in_state("INSPECTED", total_airspace=500, cell_capacity=100,
                                credit_limit=1000, material="MSW", gross=10.0, tare=2.0)
    version = facility_version(ctx["facility"]["id"], POST_USER)
    resp = api.post_ticket(ctx["ticket"]["id"], post_payload(version),
                           make_gate_operator_headers(POST_USER))
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


def test_post_special_waste_without_clearance_rejected(api):
    """PRD §3.6: "If the ticket's `material` is `TIRE` or `ASBESTOS`, the ticket must
    reference a `manifest_id` whose manifest has `special_waste_cleared` equal to true,
    otherwise `ERR_SPECIAL_WASTE_NOT_APPROVED`."

    Design: Corner/validations/special_waste_post_without_approval_rejected
    """
    facility = create_facility(500)
    create_cell(facility["id"], 100)
    hauler = create_hauler(100_000_000)
    manifest = create_manifest(hauler["id"], declared_material="TIRE", declared_weight_tons=2.0)
    ticket = create_ticket(facility["id"], hauler["id"], material="TIRE", gross_weight_tons=3.0,
                           manifest_id=manifest["id"], op_id=INSPECT_USER)
    weigh_out(ticket["id"], 1.0, op_id=INSPECT_USER)
    inspect(ticket["id"], "PASS", op_id=INSPECT_USER)
    version = facility_version(facility["id"], POST_USER)
    resp = api.post_ticket(ticket["id"], post_payload(version), make_gate_operator_headers(POST_USER))
    validate_error(resp, ApiErrorId.ERR_SPECIAL_WASTE_NOT_APPROVED)


def test_post_ticket_manifest_hauler_mismatch_rejected(api):
    """PRD §3.6: "If the ticket references a manifest at all, that manifest's
    `hauler_account_id` must equal the ticket's `hauler_account_id`, otherwise
    `ERR_MANIFEST_MISMATCH`."

    Design: Corner/validations/ticket_post_manifest_hauler_mismatch_rejected
    """
    facility = create_facility(500)
    create_cell(facility["id"], 100)
    h1 = create_hauler(100_000_000, name="H1")
    h2 = create_hauler(100_000_000, name="H2")
    manifest2 = create_manifest(h2["id"], declared_material="MSW", declared_weight_tons=4.0)
    ticket = create_ticket(facility["id"], h1["id"], material="MSW", gross_weight_tons=6.0,
                           manifest_id=manifest2["id"], op_id=INSPECT_USER)
    weigh_out(ticket["id"], 2.0, op_id=INSPECT_USER)
    inspect(ticket["id"], "PASS", op_id=INSPECT_USER)
    version = facility_version(facility["id"], POST_USER)
    resp = api.post_ticket(ticket["id"], post_payload(version), make_gate_operator_headers(POST_USER))
    validate_error(resp, ApiErrorId.ERR_MANIFEST_MISMATCH)
