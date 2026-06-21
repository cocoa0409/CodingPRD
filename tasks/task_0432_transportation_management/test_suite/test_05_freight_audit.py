"""Freight audit: quoted-versus-audited divergence, accessorial pricing,
variance, the approval tolerance, unknown-code rejection, the
audit-requires-delivered cross-entity gate, and audit/approve preconditions.
"""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error,
    assert_freight_invoice,
    ApiErrorId,
    create_freight_invoice_payload,
    setup_received_invoice, setup_audited_invoice, setup_in_transit_shipment,
    setup_delivered_shipment,
)

CARRIER = TEST_USERS["carrier_ops_headers"]
SHIPPER = TEST_USERS["shipper_ops_headers"]
DOCK = TEST_USERS["dock_ops_headers"]
AUDITOR = TEST_USERS["freight_auditor_headers"]


class TestQuotedVsAuditedDiverge:
    """The same shipment carries two valid freight costings that differ."""

    def test_audited_cost_prices_actual_accessorials(self, api):
        """PRD §3.10: "the shipment's `audited_cost_cents` is the linehaul plus the
        fuel plus the accessorial total. This differs from the provisional quote in
        §3.5 precisely in the accessorial term: the quote used a flat 5000-cent
        reserve, whereas the audit prices the carrier's actual accessorial codes."

        Design: Difficulty/dual_variant_calc/freight_cost_quoted_vs_audited_diverge_on_shipment
        """
        ctx = setup_received_invoice(
            ship_weight=6000, distance_miles=300,
            invoiced_linehaul_cents=86250,
            invoiced_accessorial_codes=["DETENTION", "REWEIGH"])
        validate_success(api.audit_freight_invoice(ctx["invoice"]["id"], AUDITOR), 200)
        ship = validate_success(api.get_shipment(ctx["shipment"]["id"], SHIPPER), 200)
        assert ship["quoted_cost_cents"] == 91250
        assert ship["audited_cost_cents"] == 97750
        assert ship["audited_cost_cents"] != ship["quoted_cost_cents"]

    def test_variance_zero_when_invoiced_matches_contract(self, api):
        """PRD §3.10: "The audit then computes the invoice's `variance_cents` as the
        carrier's invoiced linehaul plus the accessorial total, minus the audited
        cost — a signed figure that isolates the linehaul-and-fuel discrepancy"

        Design: Difficulty/dual_variant_calc/freight_cost_quoted_vs_audited_diverge_on_shipment
        """
        ctx = setup_received_invoice(
            ship_weight=6000, distance_miles=300,
            invoiced_linehaul_cents=86250,
            invoiced_accessorial_codes=["DETENTION", "REWEIGH"])
        invoice = validate_success(api.audit_freight_invoice(ctx["invoice"]["id"], AUDITOR), 200)
        assert_freight_invoice(invoice)
        assert invoice["variance_cents"] == 0
        assert invoice["status"] == "AUDITED"


def test_reweigh_accessorial_tier_boundary_exact_5000(api):
    """PRD §3.10: "A `REWEIGH` code is weight-tiered with an inclusive lower
    boundary: when the shipment weight is below 5000 pounds it charges 1500 cents;
    when the weight is at least 5000 pounds but below 20000 pounds it charges 4000
    cents"
    PRD §3.10: "a weight of exactly 5000 pounds falls in the 4000-cent tier"

    Design: Corner/calculations/reweigh_accessorial_tier_boundary_exact_5000
    """
    ctx = setup_received_invoice(
        order_weight=5000, ship_weight=5000, distance_miles=300,
        invoiced_linehaul_cents=86250, invoiced_accessorial_codes=["REWEIGH"])
    invoice = validate_success(api.audit_freight_invoice(ctx["invoice"]["id"], AUDITOR), 200)
    ship = validate_success(api.get_shipment(ctx["shipment"]["id"], SHIPPER), 200)
    assert ship["audited_cost_cents"] == 90250
    assert invoice["variance_cents"] == 0


def test_variance_over_tolerance_blocks_approve(api):
    """PRD §3.11: "requires the absolute value of the invoice's variance to be
    within a tolerance of 500 cents — that is, the variance's magnitude must be at
    most 500 cents, otherwise the approval is rejected with
    `ERR_VARIANCE_EXCEEDS_TOLERANCE`."

    Design: Corner/calculations/variance_over_tolerance_blocks_approve
    """
    ctx = setup_received_invoice(
        order_weight=6000, ship_weight=6000, distance_miles=300,
        invoiced_linehaul_cents=87250, invoiced_accessorial_codes=["DETENTION", "REWEIGH"])
    invoice = validate_success(api.audit_freight_invoice(ctx["invoice"]["id"], AUDITOR), 200)
    assert invoice["variance_cents"] == 1000
    resp = api.approve_freight_invoice(ctx["invoice"]["id"], AUDITOR)
    validate_error(resp, ApiErrorId.ERR_VARIANCE_EXCEEDS_TOLERANCE.value)


def test_unknown_accessorial_code_blocks_audit(api):
    """PRD §3.10: "Any accessorial code that is not one of `DETENTION`,
    `LIFTGATE`, `RESIDENTIAL`, or `REWEIGH` causes the audit to be rejected with
    `ERR_UNKNOWN_ACCESSORIAL`."

    Design: Corner/validations/unknown_accessorial_code_blocks_audit
    """
    ctx = setup_received_invoice(
        invoiced_linehaul_cents=86250, invoiced_accessorial_codes=["FUMIGATION"])
    resp = api.audit_freight_invoice(ctx["invoice"]["id"], AUDITOR)
    validate_error(resp, ApiErrorId.ERR_UNKNOWN_ACCESSORIAL.value)


class TestInvoiceAuditRequiresDelivered:
    """Auditing an invoice depends on the linked shipment's execution_status."""

    def test_audit_blocked_while_shipment_in_transit(self, api):
        """PRD §3.10: "Auditing requires the invoice to be `RECEIVED` (otherwise
        `ERR_INVOICE_NOT_RECEIVED`) and the billed shipment to be `DELIVERED` in
        its execution dimension (otherwise `ERR_SHIPMENT_NOT_DELIVERED`)."

        Design: Difficulty/cross_entity_state_dependency/invoice_audit_requires_shipment_delivered
        """
        ctx = setup_in_transit_shipment()  # IN_TRANSIT, not delivered
        invoice = validate_success(api.create_freight_invoice(create_freight_invoice_payload(
            shipment_id=ctx["shipment"]["id"], invoiced_linehaul_cents=86250,
            invoiced_accessorial_codes=[]), AUDITOR), 201)
        resp = api.audit_freight_invoice(invoice["id"], AUDITOR)
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_DELIVERED.value)

    def test_audit_succeeds_once_shipment_delivered(self, api):
        """PRD §3.10: "The audit moves the invoice `RECEIVED → AUDITED` and writes
        both `audited_cost_cents` onto the shipment and `variance_cents` onto the
        invoice."

        Design: Difficulty/cross_entity_state_dependency/invoice_audit_requires_shipment_delivered
        """
        ctx = setup_received_invoice(
            invoiced_linehaul_cents=86250, invoiced_accessorial_codes=[])
        invoice = validate_success(api.audit_freight_invoice(ctx["invoice"]["id"], AUDITOR), 200)
        assert invoice["status"] == "AUDITED"


def test_approve_invoice_not_audited_rejected(api):
    """PRD §3.11: "Approval requires the invoice to be `AUDITED` (otherwise
    `ERR_INVOICE_NOT_AUDITED`)"

    Design: Corner/state_machines/approve_invoice_not_audited_rejected
    """
    ctx = setup_received_invoice(
        invoiced_linehaul_cents=86250, invoiced_accessorial_codes=[])
    resp = api.approve_freight_invoice(ctx["invoice"]["id"], AUDITOR)
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_AUDITED.value)


def test_dockops_cannot_record_invoice_forbidden(api):
    """PRD §2.1: "A `FreightAuditor` operator records carrier invoices, audits,
    approves, and disputes them, and approves or denies claims."
    PRD §2.1: "When a role attempts an operation it is not permitted to perform,
    the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/dockops_cannot_audit_invoice_forbidden
    """
    order = validate_success(api.create_order(
        {"customer_ref": "C1", "origin_zone": "Z1", "dest_zone": "Z2",
         "weight_lbs": 10000, "declared_value_cents": 200000}, SHIPPER), 201)
    ship = validate_success(api.create_shipment(
        {"order_id": order["id"], "mode": "TL", "distance_miles": 300,
         "weight_lbs": 6000, "promised_eta_minute": 500}, SHIPPER), 201)
    resp = api.create_freight_invoice(create_freight_invoice_payload(
        shipment_id=ship["id"], invoiced_linehaul_cents=86250,
        invoiced_accessorial_codes=[]), DOCK)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
