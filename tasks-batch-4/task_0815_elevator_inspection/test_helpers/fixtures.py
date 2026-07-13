"""Composite setup helpers.

Every helper takes the ApiClient as its first argument and drives the PRD's
public endpoints from an empty database (the harness restarts the server before
every test). Helpers use get_success_data (lenient) so a broken precondition
surfaces as a clear "Setup failed" rather than a confusing assertion error.

Identity threading: whenever an ownership-gated call follows creation of an
entity-backed actor, the acting header is built with that entity's id via the
make_* builders — never the shared TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .factories import (
    create_owner_payload, create_inspector_payload, create_device_payload,
    create_inspection_payload, create_fee_invoice_payload, create_citation_payload,
    create_certificate_payload, create_oos_order_payload, create_accident_report_payload,
    assign_payload, complete_payload, deficiency_entry, open_investigation_payload,
    close_payload, resolve_contest_payload,
)
from .test_users import (
    TEST_USERS, make_licensed_inspector_headers, make_building_owner_headers,
)

REG = TEST_USERS["registrar_headers"]
SAFETY = TEST_USERS["safety_admin_headers"]


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(api, period):
    get_success_data(api.set_clock(period, REG))


# --------------------------------------------------------------------------
# Primitive creators
# --------------------------------------------------------------------------
def new_owner(api, **overrides) -> dict:
    return get_success_data(api.create_owner(create_owner_payload(**overrides), REG))


def new_inspector(api, categories=None, expiry=999, **overrides) -> dict:
    if categories is not None:
        overrides["certified_categories"] = categories
    overrides.setdefault("license_expiry_period", expiry)
    return get_success_data(api.create_inspector(create_inspector_payload(**overrides), REG))


def new_device(api, owner_id, category="PASSENGER_ELEVATOR", **overrides) -> dict:
    return get_success_data(
        api.create_device(create_device_payload(owner_id, category=category, **overrides), REG)
    )


def registration_invoice(api, device_id) -> dict:
    resp = api.list_fee_invoices(REG, params={"device_id": device_id, "type": "REGISTRATION"})
    data = get_success_data(resp)
    return data[0]


def pay_fee_invoice(api, invoice_id, owner_id) -> dict:
    return get_success_data(api.pay_fee_invoice(invoice_id, make_building_owner_headers(owner_id)))


def pay_registration_fee(api, device_id, owner_id) -> dict:
    inv = registration_invoice(api, device_id)
    return pay_fee_invoice(api, inv["id"], owner_id)


def get_device(api, device_id) -> dict:
    return get_success_data(api.get_device(device_id, REG))


def device_version(api, device_id) -> int:
    return get_device(api, device_id)["version"]


# --------------------------------------------------------------------------
# Device lifecycle
# --------------------------------------------------------------------------
def setup_owner_and_device(api, category="PASSENGER_ELEVATOR", **device_overrides) -> dict:
    """Owner + a REGISTERED device (registration invoice still PENDING)."""
    owner = new_owner(api)
    device = new_device(api, owner["id"], category=category, **device_overrides)
    return {"owner": owner, "device": device}


def setup_device_fee_paid(api, category="PASSENGER_ELEVATOR", **device_overrides) -> dict:
    """Owner + REGISTERED device whose registration fee has been PAID."""
    ctx = setup_owner_and_device(api, category=category, **device_overrides)
    pay_registration_fee(api, ctx["device"]["id"], ctx["owner"]["id"])
    return ctx


def setup_active_device(api, category="PASSENGER_ELEVATOR", **device_overrides) -> dict:
    """Owner + ACTIVE device (fee paid then activated)."""
    ctx = setup_device_fee_paid(api, category=category, **device_overrides)
    device = get_success_data(api.activate_device(ctx["device"]["id"], REG))
    ctx["device"] = device
    return ctx


# --------------------------------------------------------------------------
# Inspection lifecycle
# --------------------------------------------------------------------------
def schedule_inspection(api, device_id, itype="ANNUAL", start=1, end=2) -> dict:
    return get_success_data(
        api.create_inspection(
            create_inspection_payload(device_id, type=itype, scheduled_start_period=start, scheduled_end_period=end),
            REG,
        )
    )


def assign_inspection(api, inspection_id, inspector_id) -> dict:
    return get_success_data(api.assign_inspection(inspection_id, assign_payload(inspector_id), REG))


def start_inspection(api, inspection_id, inspector_id) -> dict:
    return get_success_data(api.start_inspection(inspection_id, make_licensed_inspector_headers(inspector_id)))


def complete_inspection(api, inspection_id, inspector_id, result, deficiencies=None) -> dict:
    return get_success_data(
        api.complete_inspection(inspection_id, complete_payload(result, deficiencies),
                                make_licensed_inspector_headers(inspector_id))
    )


def inspection_in_progress(api, device_id, inspector_id, itype="ANNUAL", start=1, end=2) -> dict:
    """Schedule -> assign -> start; returns the IN_PROGRESS inspection."""
    ins = schedule_inspection(api, device_id, itype, start, end)
    assign_inspection(api, ins["id"], inspector_id)
    return start_inspection(api, ins["id"], inspector_id)


def passed_inspection(api, device_id, inspector_id, itype="ANNUAL", start=1, end=2) -> dict:
    """Full walk to a PASSED inspection."""
    ins = inspection_in_progress(api, device_id, inspector_id, itype, start, end)
    return complete_inspection(api, ins["id"], inspector_id, "PASS")


def conditional_with_deficiency(api, device_id, inspector_id, severity="MINOR",
                                code="D-1", itype="PERIODIC", start=1, end=2) -> tuple:
    """CONDITIONAL completion producing one OPEN deficiency. Returns (inspection, deficiency)."""
    ins = inspection_in_progress(api, device_id, inspector_id, itype, start, end)
    complete_inspection(api, ins["id"], inspector_id, "CONDITIONAL",
                        [deficiency_entry(code=code, severity=severity, description="finding")])
    defs = get_success_data(api.list_deficiencies(REG, params={"inspection_id": ins["id"]}))
    return ins, defs[0]


def deficiencies_for_inspection(api, inspection_id) -> list:
    return get_success_data(api.list_deficiencies(REG, params={"inspection_id": inspection_id}))


# --------------------------------------------------------------------------
# Citations
# --------------------------------------------------------------------------
def issue_citation(api, deficiency_id) -> dict:
    return get_success_data(api.create_citation(create_citation_payload(deficiency_id), REG))


def setup_issued_citation(api, category="PASSENGER_ELEVATOR", severity="MINOR",
                          fee_paid=True) -> dict:
    """Device + one CONDITIONAL deficiency cited. Returns dict with owner, inspector,
    device, inspection, deficiency, citation."""
    if fee_paid:
        ctx = setup_device_fee_paid(api, category=category)
    else:
        ctx = setup_owner_and_device(api, category=category)
    inspector = new_inspector(api, categories=[category])
    ins, deficiency = conditional_with_deficiency(api, ctx["device"]["id"], inspector["id"], severity=severity)
    citation = issue_citation(api, deficiency["id"])
    ctx.update({"inspector": inspector, "inspection": ins, "deficiency": deficiency, "citation": citation})
    return ctx


# --------------------------------------------------------------------------
# Certificates
# --------------------------------------------------------------------------
def issue_certificate(api, device_id, source_inspection_id, expected_version=None) -> dict:
    if expected_version is None:
        expected_version = device_version(api, device_id)
    return get_success_data(
        api.create_certificate(
            create_certificate_payload(device_id, source_inspection_id, expected_version), REG
        )
    )


def post_certificate(api, certificate_id, owner_id) -> dict:
    return get_success_data(api.post_certificate(certificate_id, make_building_owner_headers(owner_id)))


def setup_posted_certificate(api, category="PASSENGER_ELEVATOR") -> dict:
    """Fee-paid device with a PASSED inspection, an ISSUED-then-POSTED certificate
    (device ACTIVE). Returns dict with owner, inspector, device, inspection, certificate."""
    ctx = setup_device_fee_paid(api, category=category)
    inspector = new_inspector(api, categories=[category])
    ins = passed_inspection(api, ctx["device"]["id"], inspector["id"])
    cert = issue_certificate(api, ctx["device"]["id"], ins["id"])
    cert = post_certificate(api, cert["id"], ctx["owner"]["id"])
    ctx.update({"inspector": inspector, "inspection": ins, "certificate": cert})
    return ctx


def setup_device_with_passed_inspection(api, category="PASSENGER_ELEVATOR", fee_paid=True) -> dict:
    """Device (fee paid unless fee_paid=False) with a certified inspector and one
    PASSED inspection ready to source a certificate. Returns owner, inspector,
    device, inspection."""
    if fee_paid:
        ctx = setup_device_fee_paid(api, category=category)
    else:
        ctx = setup_owner_and_device(api, category=category)
    inspector = new_inspector(api, categories=[category])
    ins = passed_inspection(api, ctx["device"]["id"], inspector["id"])
    ctx.update({"inspector": inspector, "inspection": ins})
    return ctx


# --------------------------------------------------------------------------
# Out-of-service orders
# --------------------------------------------------------------------------
def create_oos_order(api, device_id, reason="NONPAYMENT", start=0, end=5, citation_id=None) -> dict:
    overrides = {"reason": reason, "effective_start_period": start, "effective_end_period": end}
    if citation_id is not None:
        overrides["citation_id"] = citation_id
    return get_success_data(api.create_oos_order(create_oos_order_payload(device_id, **overrides), SAFETY))


def lift_oos_order(api, oos_id) -> dict:
    return get_success_data(api.lift_oos_order(oos_id, SAFETY))


# --------------------------------------------------------------------------
# Fee invoices
# --------------------------------------------------------------------------
def create_fee_invoice(api, device_id, itype="ANNUAL_RENEWAL", due_period=12) -> dict:
    return get_success_data(
        api.create_fee_invoice(create_fee_invoice_payload(device_id, type=itype, due_period=due_period), REG)
    )


# --------------------------------------------------------------------------
# Accident reports
# --------------------------------------------------------------------------
def file_accident_report(api, device_id, severity="SEVERE", occurred_period=1, description="accident") -> dict:
    return get_success_data(
        api.create_accident_report(
            create_accident_report_payload(device_id, severity=severity,
                                           occurred_period=occurred_period, description=description),
            SAFETY,
        )
    )


def open_investigation(api, report_id, lead_investigator_id) -> dict:
    return get_success_data(
        api.open_investigation(report_id, open_investigation_payload(lead_investigator_id), SAFETY)
    )


def close_investigation(api, report_id, lead_investigator_id, finding) -> dict:
    return get_success_data(
        api.close_investigation(report_id, close_payload(finding),
                                make_licensed_inspector_headers(lead_investigator_id))
    )
