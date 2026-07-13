"""Body validation, ownership, and role-based access control."""
from test_helpers import (
    validate_error, ApiErrorId,
    make_facility_admin_headers, make_gate_operator_headers, make_hauler_headers,
    make_billing_clerk_headers, make_environmental_officer_headers,
    ticket_payload, manifest_payload, facility_payload, invoice_payload, decide_payload,
    create_facility, create_hauler, create_manifest, open_special_waste_approval,
)


def test_ticket_create_missing_gross_weight_returns_validation(api):
    """PRD §2.11: "Body validation — required fields present, enums valid, weights and cents
    non-negative, and any `window_end` strictly greater than its `window_start`; otherwise
    `ERR_VALIDATION` (422)."

    Design: Corner/entities/ticket_create_missing_required_field_returns_validation
    """
    facility = create_facility(500)
    hauler = create_hauler(100_000)
    payload = {"facility_id": facility["id"], "hauler_account_id": hauler["id"], "material": "MSW"}
    resp = api.create_ticket(payload, make_gate_operator_headers("op1"))
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_ticket_create_invalid_material_enum_returns_validation(api):
    """PRD §2.11: "Body validation — required fields present, enums valid, weights and cents
    non-negative, and any `window_end` strictly greater than its `window_start`; otherwise
    `ERR_VALIDATION` (422)."

    Design: Corner/entities/ticket_create_invalid_enum_material_returns_validation
    """
    facility = create_facility(500)
    hauler = create_hauler(100_000)
    resp = api.create_ticket(
        ticket_payload(facility["id"], hauler["id"], material="PLASTIC", gross_weight_tons=4.0),
        make_gate_operator_headers("op1"),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_hauler_cannot_create_manifest_for_other_account(api):
    """PRD §2.1: "A `Hauler` attempting to create or submit a manifest, open a payment, or
    read a resource that belongs to a different hauler account is rejected with
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/validations/hauler_cannot_create_manifest_for_other_account
    """
    h1 = create_hauler(100_000, name="H1")
    h2 = create_hauler(100_000, name="H2")
    resp = api.create_manifest(
        manifest_payload(h2["id"], declared_material="MSW", declared_weight_tons=3.0),
        make_hauler_headers(h1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


def test_invoice_generation_no_billable_tickets(api):
    """PRD §3.9: "If the hauler has no billable tickets, the invoice cannot be generated and
    the request is rejected with `ERR_NO_BILLABLE_TICKETS`."

    Design: Corner/validations/invoice_generation_no_billable_tickets
    """
    hauler = create_hauler(100_000)
    resp = api.create_invoice(invoice_payload(hauler["id"]), make_billing_clerk_headers("bc1"))
    validate_error(resp, ApiErrorId.ERR_NO_BILLABLE_TICKETS)


def test_hauler_cannot_create_facility_unauthorized(api):
    """PRD §2.1: "When a recognized user attempts an operation their role is not permitted to
    perform, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/hauler_cannot_create_facility_unauthorized
    """
    hauler = create_hauler(100_000)
    resp = api.create_facility(
        facility_payload(name="Rogue", total_airspace_cubic_yards=10),
        make_hauler_headers(hauler["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_gateoperator_cannot_decide_special_waste_unauthorized(api):
    """PRD §2.1: "When a recognized user attempts an operation their role is not permitted to
    perform, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/gateoperator_cannot_decide_special_waste_unauthorized
    """
    hauler = create_hauler(100_000)
    manifest = create_manifest(hauler["id"], declared_material="ASBESTOS", declared_weight_tons=2.0)
    approval = open_special_waste_approval(manifest["id"], waste_type="ASBESTOS", profile_ref="PRF-3")
    resp = api.decide_special_waste_approval(
        approval["id"], decide_payload("APPROVE"), make_gate_operator_headers("op1"),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
