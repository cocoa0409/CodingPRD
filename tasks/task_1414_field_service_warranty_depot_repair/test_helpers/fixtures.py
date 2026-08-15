"""Composite setup helpers for multi-step test prerequisites (PRD §3).

Every helper builds its preconditions from scratch through the public API and
uses the lenient get_success_data() validator so setup failures surface as
clear "Setup failed" errors. Ownership-gated customer calls thread the real
Customer.id through make_customer_headers(); segregation-of-duties flows use
distinct opaque operator identities (tech-1 vs tech-2, mgr-1 vs wa-1).
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO
from .factories import (
    consume_part_payload,
    create_customer_payload,
    create_depot_bay_payload,
    create_failure_code_payload,
    create_loaner_unit_payload,
    create_part_payload,
    create_product_model_payload,
    create_rma_payload,
    create_unit_payload,
    diagnose_payload,
    escalation_payload,
    loaner_reservation_payload,
    planned_part_line,
    quote_revision_payload,
    warranty_override_payload,
)
from .test_users import TEST_USERS, make_customer_headers

INTAKE = TEST_USERS["intake_agent_headers"]
TECH1 = TEST_USERS["depot_technician_headers"]          # X-User-ID tech-1
MGR = TEST_USERS["depot_manager_headers"]               # X-User-ID mgr-1
WA = TEST_USERS["warranty_admin_headers"]               # X-User-ID wa-1
ENG = TEST_USERS["engineering_lead_headers"]            # X-User-ID eng-1


# ---------------------------------------------------------------------------
# Clock and ops
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PRD §2.4). Returns the echoed payload."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, MGR))


def reset_clock() -> dict:
    return set_clock(DEFAULT_CLOCK_ISO)


def run_daily_close() -> dict:
    """Run the daily ops checkpoint (PRD §3.9). Returns the five result lists."""
    return get_success_data(api_client.run_daily_close(MGR))


# ---------------------------------------------------------------------------
# Tier 1: catalog / registry creation
# ---------------------------------------------------------------------------

def create_model(**overrides) -> dict:
    return get_success_data(
        api_client.create_product_model(create_product_model_payload(**overrides), MGR))


def create_customer(**overrides) -> dict:
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), INTAKE))


def create_unit(model_id, customer_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_unit(create_unit_payload(model_id, customer_id, **overrides), INTAKE))


def create_part(**overrides) -> dict:
    return get_success_data(api_client.create_part(create_part_payload(**overrides), MGR))


def create_failure_code(**overrides) -> dict:
    return get_success_data(
        api_client.create_failure_code(create_failure_code_payload(**overrides), ENG))


def create_bay(**overrides) -> dict:
    return get_success_data(
        api_client.create_depot_bay(create_depot_bay_payload(**overrides), MGR))


def create_loaner_unit(model_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_loaner_unit(create_loaner_unit_payload(model_id, **overrides), MGR))


# ---------------------------------------------------------------------------
# Tier 1b: reads
# ---------------------------------------------------------------------------

def get_rma(rma_id) -> dict:
    return get_success_data(api_client.get_rma(rma_id, INTAKE))


def get_quote(quote_id) -> dict:
    return get_success_data(api_client.get_quote(quote_id, INTAKE))


def get_customer(customer_id) -> dict:
    return get_success_data(api_client.get_customer(customer_id, INTAKE))


def get_part(part_id) -> dict:
    return get_success_data(api_client.get_part(part_id, MGR))


def get_product_model(model_id) -> dict:
    return get_success_data(api_client.get_product_model(model_id, MGR))


def get_unit(unit_id) -> dict:
    return get_success_data(api_client.get_unit(unit_id, INTAKE))


def get_loaner_unit(loaner_unit_id) -> dict:
    return get_success_data(api_client.get_loaner_unit(loaner_unit_id, INTAKE))


def get_reservation(reservation_id) -> dict:
    return get_success_data(api_client.get_loaner_reservation(reservation_id, INTAKE))


def get_escalation(escalation_id) -> dict:
    return get_success_data(api_client.get_engineering_escalation(escalation_id, ENG))


def get_repair_line(repair_line_id) -> dict:
    return get_success_data(api_client.get_repair_line(repair_line_id, MGR))


def list_quotes(rma_id) -> list:
    return get_success_data(api_client.list_rma_quotes(rma_id, TECH1))


def list_notifications(rma_id, params=None) -> list:
    return get_success_data(api_client.list_rma_notifications(rma_id, INTAKE, params=params))


# ---------------------------------------------------------------------------
# Tier 2: RMA lifecycle steps
# ---------------------------------------------------------------------------

def create_draft_rma(customer_id, unit_id, service_option=None,
                     reported_issue="dead") -> dict:
    overrides = {"reported_issue": reported_issue}
    if service_option is not None:
        overrides["service_option"] = service_option
    return get_success_data(
        api_client.create_rma(create_rma_payload(customer_id, unit_id, **overrides), INTAKE))


def authorize_rma(rma_id) -> dict:
    return get_success_data(api_client.authorize_rma(rma_id, INTAKE))


def receive_rma(rma_id, serial_number) -> dict:
    return get_success_data(
        api_client.receive_rma(rma_id, {"serial_number": serial_number}, INTAKE))


def triage_rma(rma_id, failure_code_id) -> dict:
    return get_success_data(
        api_client.triage_rma(rma_id, {"primary_failure_code_id": failure_code_id}, INTAKE))


def diagnose_rma(rma_id, labor_minutes_est=10, repairability="REPAIRABLE",
                 planned_parts=None, tech_headers=None) -> dict:
    """Diagnose a TRIAGED RMA; returns the post-diagnosis RMA (carries version)."""
    return get_success_data(api_client.diagnose_rma(
        rma_id,
        diagnose_payload(labor_minutes_est=labor_minutes_est,
                         repairability=repairability,
                         planned_parts=planned_parts),
        tech_headers or TECH1))


def consume_part(rma_id, part_id, quantity, failure_code_id, expected_rma_version,
                 tech_headers=None):
    """Raw response: callers may assert either success or an error."""
    return api_client.consume_part(
        rma_id,
        consume_part_payload(part_id, quantity, failure_code_id, expected_rma_version),
        tech_headers or TECH1)


def consume_part_ok(rma_id, part_id, quantity, failure_code_id,
                    expected_rma_version, tech_headers=None) -> dict:
    return get_success_data(consume_part(
        rma_id, part_id, quantity, failure_code_id, expected_rma_version,
        tech_headers=tech_headers))


def repair_complete(rma_id, tech_headers=None) -> dict:
    return get_success_data(api_client.repair_complete(rma_id, tech_headers or TECH1))


def qa_release(rma_id, outcome, tech_headers) -> dict:
    return get_success_data(api_client.qa_release(rma_id, {"outcome": outcome}, tech_headers))


def ship_rma(rma_id, tech_headers=None, carrier="UPS", tracking_number="1Z") -> dict:
    return get_success_data(api_client.ship_rma(
        rma_id, {"carrier": carrier, "tracking_number": tracking_number},
        tech_headers or TECH1))


def close_rma(rma_id) -> dict:
    return get_success_data(api_client.close_rma(rma_id, INTAKE))


def approve_quote(quote_id, customer_id, payment_reference="pay-1") -> dict:
    return get_success_data(api_client.approve_quote(
        quote_id, {"payment_reference": payment_reference},
        make_customer_headers(customer_id)))


def decline_quote(quote_id, customer_id) -> dict:
    return get_success_data(
        api_client.decline_quote(quote_id, make_customer_headers(customer_id)))


def revise_quote(rma_id, labor_minutes, parts_lines, expected_rma_version,
                 tech_headers=None, **overrides) -> dict:
    return get_success_data(api_client.create_quote_revision(
        rma_id,
        quote_revision_payload(labor_minutes, parts_lines, expected_rma_version,
                               **overrides),
        tech_headers or TECH1))


# ---------------------------------------------------------------------------
# Tier 2b: loaner logistics steps
# ---------------------------------------------------------------------------

def create_reservation(rma_id, loaner_unit_id=None,
                       start_date="2026-08-01", end_date="2026-08-20") -> dict:
    overrides = {"start_date": start_date, "end_date": end_date}
    if loaner_unit_id is not None:
        overrides["loaner_unit_id"] = loaner_unit_id
    return get_success_data(api_client.create_loaner_reservation(
        rma_id, loaner_reservation_payload(**overrides), INTAKE))


def ship_reservation(reservation_id) -> dict:
    return get_success_data(api_client.ship_loaner_reservation(reservation_id, INTAKE))


def return_reservation(reservation_id, condition="OK",
                       damage_assessment_cents=None) -> dict:
    payload = {"condition": condition}
    if damage_assessment_cents is not None:
        payload["damage_assessment_cents"] = damage_assessment_cents
    return get_success_data(
        api_client.return_loaner_reservation(reservation_id, payload, INTAKE))


def cancel_reservation(reservation_id) -> dict:
    return get_success_data(api_client.cancel_loaner_reservation(reservation_id, INTAKE))


def forfeit_reservation(reservation_id) -> dict:
    return get_success_data(api_client.forfeit_loaner_reservation(reservation_id, MGR))


def inspect_loaner(loaner_unit_id, outcome, tech_headers=None) -> dict:
    return get_success_data(api_client.inspect_loaner_unit(
        loaner_unit_id, {"outcome": outcome}, tech_headers or TECH1))


# ---------------------------------------------------------------------------
# Tier 2c: escalation steps
# ---------------------------------------------------------------------------

def create_manual_escalation(rma_id, failure_code_id) -> dict:
    return get_success_data(api_client.create_engineering_escalation(
        escalation_payload(rma_id, failure_code_id), ENG))


def resolve_escalation(escalation_id, note="fixed") -> dict:
    return get_success_data(
        api_client.resolve_escalation(escalation_id, {"resolution_note": note}, ENG))


def contain_escalation(escalation_id) -> dict:
    return get_success_data(api_client.contain_escalation(escalation_id, ENG))


# ---------------------------------------------------------------------------
# Tier 3: composite scenarios
# ---------------------------------------------------------------------------

def setup_catalog(purchase_date="2026-01-01", channel="RETAIL",
                  with_part=True, with_fc=True, part_overrides=None,
                  fc_overrides=None, **model_overrides) -> dict:
    """Model + customer + unit (+ failure code + part). Returns a context dict."""
    ctx = {}
    ctx["model"] = create_model(**model_overrides)
    ctx["customer"] = create_customer()
    ctx["unit"] = create_unit(ctx["model"]["id"], ctx["customer"]["id"],
                              channel=channel, purchase_date=purchase_date,
                              ship_date=purchase_date)
    if with_fc:
        ctx["fc"] = create_failure_code(**(fc_overrides or {}))
    if with_part:
        ctx["part"] = create_part(**(part_overrides or {}))
    return ctx


def setup_draft_rma(service_option=None, **catalog_kwargs) -> dict:
    ctx = setup_catalog(**catalog_kwargs)
    ctx["rma"] = create_draft_rma(ctx["customer"]["id"], ctx["unit"]["id"],
                                  service_option=service_option)
    return ctx


def setup_authorized_rma(service_option=None, **catalog_kwargs) -> dict:
    ctx = setup_draft_rma(service_option=service_option, **catalog_kwargs)
    ctx["rma"] = authorize_rma(ctx["rma"]["id"])
    return ctx


def setup_received_rma(**catalog_kwargs) -> dict:
    ctx = setup_authorized_rma(**catalog_kwargs)
    ctx["rma"] = receive_rma(ctx["rma"]["id"], ctx["unit"]["serial_number"])
    return ctx


def setup_triaged_rma(**catalog_kwargs) -> dict:
    ctx = setup_received_rma(**catalog_kwargs)
    ctx["rma"] = triage_rma(ctx["rma"]["id"], ctx["fc"]["id"])
    return ctx


def setup_in_repair_rma(labor_minutes_est=10, planned_qty=1,
                        consume=False, **catalog_kwargs) -> dict:
    """In-warranty RMA diagnosed REPAIR (auto-routed to IN_REPAIR).

    ctx["rma"] is the post-diagnosis RMA whose version is the OCC baseline for
    the first parts-consumption call.
    """
    ctx = setup_triaged_rma(**catalog_kwargs)
    planned = [planned_part_line(ctx["part"]["id"], planned_qty)] if planned_qty else []
    ctx["rma"] = diagnose_rma(ctx["rma"]["id"], labor_minutes_est=labor_minutes_est,
                              planned_parts=planned)
    assert ctx["rma"]["status"] == "IN_REPAIR", (
        f"Setup failed: expected IN_REPAIR, got {ctx['rma']['status']}")
    if consume and planned_qty:
        ctx["line"] = consume_part_ok(ctx["rma"]["id"], ctx["part"]["id"], planned_qty,
                                      ctx["fc"]["id"], ctx["rma"]["version"])
        ctx["rma"] = get_rma(ctx["rma"]["id"])
    return ctx


def setup_awaiting_quote_rma(labor_minutes_est=20, planned_qty=1,
                             **model_overrides) -> dict:
    """OUT_OF_WARRANTY RMA diagnosed REPAIR -> AWAITING_QUOTE_APPROVAL with the
    auto-created SENT quote q1 attached as ctx["quote"]."""
    model_overrides.setdefault("standard_warranty_days", 365)
    ctx = setup_catalog(purchase_date="2024-01-01", **model_overrides)
    ctx["rma"] = create_draft_rma(ctx["customer"]["id"], ctx["unit"]["id"])
    ctx["rma"] = authorize_rma(ctx["rma"]["id"])
    assert ctx["rma"]["coverage_path"] == "OUT_OF_WARRANTY", (
        f"Setup failed: expected OUT_OF_WARRANTY, got {ctx['rma']['coverage_path']}")
    ctx["rma"] = receive_rma(ctx["rma"]["id"], ctx["unit"]["serial_number"])
    ctx["rma"] = triage_rma(ctx["rma"]["id"], ctx["fc"]["id"])
    planned = [planned_part_line(ctx["part"]["id"], planned_qty)] if planned_qty else []
    ctx["rma"] = diagnose_rma(ctx["rma"]["id"], labor_minutes_est=labor_minutes_est,
                              planned_parts=planned)
    assert ctx["rma"]["status"] == "AWAITING_QUOTE_APPROVAL", (
        f"Setup failed: expected AWAITING_QUOTE_APPROVAL, got {ctx['rma']['status']}")
    ctx["quote"] = list_quotes(ctx["rma"]["id"])[0]
    return ctx


def setup_qa_hold_rma(**kwargs) -> dict:
    """In-warranty RMA driven to QA_HOLD with one CONSUMED line; repair
    completed by tech-1 (so QA release must come from a different technician)."""
    ctx = setup_in_repair_rma(consume=True, **kwargs)
    ctx["rma"] = repair_complete(ctx["rma"]["id"], tech_headers=TECH1)
    assert ctx["rma"]["status"] == "QA_HOLD", (
        f"Setup failed: expected QA_HOLD, got {ctx['rma']['status']}")
    return ctx


def setup_authorized_loaner_with_reservation(deposit_value_cents=40000,
                                             credit_limit_cents=100000,
                                             start_date="2026-08-01",
                                             end_date="2026-08-20",
                                             grade="A") -> dict:
    """AUTHORIZED LOANER RMA + pool unit RESERVED."""
    ctx = setup_catalog(with_part=False, with_fc=False)
    ctx["customer"] = get_customer(ctx["customer"]["id"])  # refresh
    if credit_limit_cents != 100000:
        # recreate customer with the requested limit
        ctx["customer"] = create_customer(credit_limit_cents=credit_limit_cents)
        ctx["unit"] = create_unit(ctx["model"]["id"], ctx["customer"]["id"])
    ctx["lu"] = create_loaner_unit(ctx["model"]["id"], condition_grade=grade,
                                   deposit_value_cents=deposit_value_cents)
    ctx["rma"] = create_draft_rma(ctx["customer"]["id"], ctx["unit"]["id"],
                                  service_option="LOANER")
    ctx["rma"] = authorize_rma(ctx["rma"]["id"])
    ctx["res"] = create_reservation(ctx["rma"]["id"], ctx["lu"]["id"],
                                    start_date=start_date, end_date=end_date)
    return ctx


def setup_shipped_loaner_rma(loaner_grace_days=10) -> dict:
    """Full LOANER lifecycle: authorized + reservation shipped + unit repaired
    and shipped at the current clock (default 2026-08-01). The reservation
    receives due_date = ship date + grace days at RMA ship time."""
    ctx = setup_catalog(loaner_grace_days=loaner_grace_days)
    ctx["lu"] = create_loaner_unit(ctx["model"]["id"])
    ctx["rma"] = create_draft_rma(ctx["customer"]["id"], ctx["unit"]["id"],
                                  service_option="LOANER")
    ctx["rma"] = authorize_rma(ctx["rma"]["id"])
    ctx["res"] = create_reservation(ctx["rma"]["id"], ctx["lu"]["id"])
    ctx["res"] = ship_reservation(ctx["res"]["id"])
    ctx["rma"] = receive_rma(ctx["rma"]["id"], ctx["unit"]["serial_number"])
    ctx["rma"] = triage_rma(ctx["rma"]["id"], ctx["fc"]["id"])
    ctx["rma"] = diagnose_rma(ctx["rma"]["id"], labor_minutes_est=10,
                              planned_parts=[planned_part_line(ctx["part"]["id"], 1)])
    ctx["line"] = consume_part_ok(ctx["rma"]["id"], ctx["part"]["id"], 1,
                                  ctx["fc"]["id"], ctx["rma"]["version"])
    ctx["rma"] = repair_complete(ctx["rma"]["id"], tech_headers=TECH1)
    ctx["rma"] = qa_release(ctx["rma"]["id"], "PASS",
                            tech_headers=_tech2())
    ctx["rma"] = ship_rma(ctx["rma"]["id"], tech_headers=_tech2())
    assert ctx["rma"]["status"] == "SHIPPED", (
        f"Setup failed: expected SHIPPED, got {ctx['rma']['status']}")
    return ctx


def _tech2():
    from .test_users import make_depot_technician_headers
    return make_depot_technician_headers("tech-2")


def setup_monitoring_escalation() -> dict:
    """Manual escalation on a DRAFT RMA, resolved at the default clock ->
    MONITORING with monitoring_until = clock date + 90 days."""
    ctx = setup_catalog()
    ctx["rma"] = create_draft_rma(ctx["customer"]["id"], ctx["unit"]["id"])
    ctx["esc"] = create_manual_escalation(ctx["rma"]["id"], ctx["fc"]["id"])
    ctx["esc"] = resolve_escalation(ctx["esc"]["id"])
    assert ctx["esc"]["status"] == "MONITORING", (
        f"Setup failed: expected MONITORING, got {ctx['esc']['status']}")
    return ctx
