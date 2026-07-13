"""RBAC denials, request-shape/referential validation, and completion-artifact errors
— all corner queue (one test per non-stub instance)."""
from test_helpers import (
    validate_error,
    create_customer_payload, create_compliance_report_payload,
    TEST_USERS, make_technician_headers, get_success_data,
)
from test_helpers.fixtures import (
    new_customer, new_site, new_equipment, new_technician, new_work_order,
    new_active_contract, new_draft_invoice, dispatch_work_order, start_work_order,
    file_manifest, setup_inprogress_grease_work_order, setup_inprogress_hood_work_order,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


def test_technician_cannot_create_customer(api):
    """PRD §2.1: "If the role is recognized but is not permitted to perform the requested
    operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)." (POST /customers is Admin-only.)

    Design: Corner/validations/rbac_technician_cannot_create_customer
    """
    tech = new_technician("BASIC")
    res = api.create_customer(create_customer_payload(business_name="Sneaky", billing_email="sk@x.com"),
                              make_technician_headers(tech["id"]))
    validate_error(res, "ERR_FORBIDDEN")


def test_technician_cannot_start_unowned_work_order(api):
    """PRD §2.1: "a technician may start or complete only a work order assigned to that
    technician, and a mismatch is rejected with `ERR_FORBIDDEN`."

    Design: Corner/validations/technician_cannot_start_unowned_work_order
    """
    cust = new_customer()
    site = new_site(cust["id"])
    eq = new_equipment(site["id"])
    tech_a = new_technician("BASIC")
    tech_b = new_technician("BASIC")
    wo = new_work_order(site["id"], eq["id"])
    dispatch_work_order(wo["id"], tech_a["id"])
    res = api.transition_work_order(
        wo["id"], {"to_status": "IN_PROGRESS"}, make_technician_headers(tech_b["id"]))
    validate_error(res, "ERR_FORBIDDEN")


def test_compliance_report_reversed_period_rejected(api):
    """PRD §3.6: "where `period_end` must be strictly after `period_start`, else
    `ERR_REPORT_PERIOD_INVALID`."

    Design: Corner/validations/compliance_report_period_invalid_returns_422
    """
    cust = new_customer()
    site = new_site(cust["id"], municipality_code="MUNI-B")
    res = api.create_compliance_report(
        create_compliance_report_payload(site["id"], municipality_code="MUNI-B",
                                         period_start="2026-05-01T00:00:00Z",
                                         period_end="2026-04-01T00:00:00Z"),
        COMPLIANCE)
    validate_error(res, "ERR_REPORT_PERIOD_INVALID")


def test_manifest_with_bad_facility_permit_rejected(api):
    """PRD §3.4: "`disposal_facility_permit` must be non-empty and begin with the prefix
    `FAC-`, or it is rejected with `ERR_DISPOSAL_FACILITY_INVALID`."

    Design: Corner/validations/manifest_invalid_facility_permit_returns_422
    """
    ctx = setup_inprogress_grease_work_order(wo_overrides={"planned_end": "2026-05-10T12:00:00Z"})
    res = api.create_manifest(
        {"work_order_id": ctx["wo_id"], "disposal_facility_name": "Acme",
         "disposal_facility_permit": "BADPERMIT", "hazmat_certified": False,
         "volume_gallons": 100, "fog_percentage": 5.0},
        ctx["tech_headers"])
    validate_error(res, "ERR_DISPOSAL_FACILITY_INVALID")


def test_hood_certificate_on_grease_order_rejected(api):
    """PRD §3.5: "The referenced work order must belong to `HOOD` equipment, or the request
    is rejected with `ERR_EQUIPMENT_TYPE_MISMATCH`."

    Design: Corner/validations/hood_certificate_on_grease_order_returns_type_mismatch
    """
    ctx = setup_inprogress_grease_work_order(wo_overrides={"planned_end": "2026-05-10T12:00:00Z"})
    res = api.create_hood_certificate(
        {"work_order_id": ctx["wo_id"], "cleanliness_grade": "ACCEPTABLE"},
        ctx["tech_headers"])
    validate_error(res, "ERR_EQUIPMENT_TYPE_MISMATCH")


def test_complete_grease_order_without_manifest_rejected(api):
    """PRD §3.3: "a `GREASE_TRAP` order requires an existing `RECORDED` pump-out manifest
    referencing it, absent which it is rejected with `ERR_MANIFEST_REQUIRED`".

    Design: Corner/errors/complete_grease_order_without_manifest_returns_422
    """
    ctx = setup_inprogress_grease_work_order(wo_overrides={"planned_end": "2026-05-10T12:00:00Z"})
    res = api.complete_work_order(ctx["wo_id"], {"actual_hours": 2}, ctx["tech_headers"])
    validate_error(res, "ERR_MANIFEST_REQUIRED")


def test_complete_hood_order_with_failing_certificate_rejected(api):
    """PRD §3.3: "with `ERR_CLEANLINESS_FAILED` when the certificate grade is `FAILING`."

    Design: Corner/errors/complete_hood_order_failing_grade_returns_422
    """
    ctx = setup_inprogress_hood_work_order(certification_level="NFPA96_CERTIFIED")
    get_success_data(api.create_hood_certificate(
        {"work_order_id": ctx["wo_id"], "cleanliness_grade": "FAILING"}, ctx["tech_headers"]))
    res = api.complete_work_order(ctx["wo_id"], {"actual_hours": 2}, ctx["tech_headers"])
    validate_error(res, "ERR_CLEANLINESS_FAILED")


def test_void_already_voided_manifest_rejected(api):
    """PRD §3.4: "Voiding a manifest that is already `VOIDED` is rejected with
    `ERR_MANIFEST_ALREADY_VOIDED`."

    Design: Corner/errors/void_already_voided_manifest_returns_409
    """
    ctx = setup_inprogress_grease_work_order(
        equipment_overrides={"equipment_type": "GREASE_TRAP", "capacity_gallons": 1000,
                             "nominal_frequency_days": 30},
        wo_overrides={"planned_end": "2026-05-10T12:00:00Z"})
    man = file_manifest(ctx["wo_id"], ctx["tech_id"], disposal_facility_permit="FAC-8",
                        volume_gallons=100)
    get_success_data(api.void_manifest(man["id"], ctx["tech_headers"]))
    res = api.void_manifest(man["id"], ctx["tech_headers"])
    validate_error(res, "ERR_MANIFEST_ALREADY_VOIDED")


def test_issue_over_credit_limit_rejected(api):
    """PRD §3.7: "the customer's `outstanding_balance_cents` plus this invoice's
    `total_amount_cents` must not exceed the customer's `credit_limit_cents`, else
    `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Corner/errors/issue_over_credit_limit_returns_402
    """
    cust = new_customer(credit_limit_cents=10000)
    contract = new_active_contract(cust["id"], base_rate_cents=12500, tax_rate_bps=0)
    inv = new_draft_invoice(cust["id"], contract_id=contract["id"])
    res = api.issue_invoice(inv["id"], BILLING)
    validate_error(res, "ERR_CREDIT_LIMIT_EXCEEDED")
