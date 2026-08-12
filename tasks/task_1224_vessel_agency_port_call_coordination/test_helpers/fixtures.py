"""Composite setup helpers — multi-step PRD workflow preambles.

Fixtures use get_success_data() internally so a setup failure surfaces as a
clear "Setup failed" assertion instead of a confusing downstream error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_principal_payload,
    create_port_call_payload,
    create_notification_payload,
    create_berth_window_payload,
    create_service_order_payload,
    create_crew_change_payload,
    create_vendor_payload,
    create_purchase_order_payload,
    create_cargo_document_payload,
    create_tariff_payload,
    create_da_payload,
    create_da_line_payload,
    create_funding_advance_payload,
    create_cost_dispute_payload,
    create_husbandry_case_payload,
)
from .test_users import (
    make_agency_admin_headers,
    make_agency_ops_headers,
    make_agency_finance_headers,
    make_port_authority_headers,
    make_principal_rep_headers,
    make_vendor_rep_headers,
    make_crewing_agent_headers,
    make_husbandry_officer_headers,
)

AUTHORITY_TYPES = ("PORT_STATE_CONTROL", "IMMIGRATION", "CUSTOMS", "HARBOR_MASTER")


# ---------------------------------------------------------------------------
# Tier 1: simple creation helpers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(
        {"to_iso8601": to_iso8601}, make_agency_admin_headers()))


def create_principal(**overrides):
    return get_success_data(api_client.create_principal(
        create_principal_payload(**overrides), make_agency_admin_headers()))


def create_port_call(principal_id, ops_user_id="ops-1", **overrides):
    return get_success_data(api_client.create_port_call(
        create_port_call_payload(principal_id, **overrides),
        make_agency_ops_headers(ops_user_id)))


def create_vendor(**overrides):
    return get_success_data(api_client.create_vendor(
        create_vendor_payload(**overrides), make_agency_admin_headers()))


def create_da_for_call(port_call, ops_user_id="ops-1"):
    """Create a DA for a port call, OCC-checked against its current version."""
    return get_success_data(api_client.create_disbursement_account(
        create_da_payload(port_call["id"], port_call["version"]),
        make_agency_ops_headers(ops_user_id)))


def add_manual_line(da_id, estimated_cents, category="SUNDRY", description="manual", role="ops"):
    headers = make_agency_ops_headers() if role == "ops" else make_agency_finance_headers()
    return get_success_data(api_client.create_da_line(
        da_id, create_da_line_payload(
            category=category, description=description, estimated_cents=estimated_cents),
        headers))


def create_notification(port_call_id, authority_type, **overrides):
    return get_success_data(api_client.create_authority_notification(
        create_notification_payload(port_call_id, authority_type, **overrides),
        make_agency_ops_headers()))


def create_berth_window(port_call_id, **overrides):
    return get_success_data(api_client.create_berth_window(
        create_berth_window_payload(port_call_id, **overrides),
        make_agency_ops_headers()))


def create_vendor_and_rep(**vendor_overrides):
    """Create a vendor and return (vendor, ownership-correct VendorRep headers)."""
    vendor = create_vendor(**vendor_overrides)
    return vendor, make_vendor_rep_headers(vendor["id"])


def create_service_order(port_call_id, **overrides):
    return get_success_data(api_client.create_service_order(
        create_service_order_payload(port_call_id, **overrides),
        make_agency_ops_headers()))


def create_purchase_order(port_call_id, vendor_id, **overrides):
    return get_success_data(api_client.create_purchase_order(
        create_purchase_order_payload(port_call_id, vendor_id, **overrides),
        make_agency_ops_headers()))


def create_crew_change(port_call_id, **overrides):
    return get_success_data(api_client.create_crew_change(
        create_crew_change_payload(port_call_id, **overrides),
        make_crewing_agent_headers()))


def create_husbandry_case(port_call_id, **overrides):
    return get_success_data(api_client.create_husbandry_case(
        create_husbandry_case_payload(port_call_id, **overrides),
        make_husbandry_officer_headers()))


def create_cargo_document(port_call_id, **overrides):
    return get_success_data(api_client.create_cargo_document(
        create_cargo_document_payload(port_call_id, **overrides),
        make_agency_ops_headers()))


# ---------------------------------------------------------------------------
# Tier 2/3: notification + clearance ladders, berth occupation
# ---------------------------------------------------------------------------

def file_all_notifications(port_call_id, acknowledge=True):
    """Create + submit all four authority notifications; optionally acknowledge.

    Returns dict mapping authority_type -> notification dict.
    """
    notes = {}
    for auth_type in AUTHORITY_TYPES:
        n = create_notification(port_call_id, auth_type)
        n = get_success_data(api_client.submit_notification(n["id"], make_agency_ops_headers()))
        if acknowledge:
            n = get_success_data(api_client.acknowledge_notification(
                n["id"], {"authority_reference": f"{auth_type}-REF"},
                make_port_authority_headers()))
        notes[auth_type] = n
    return notes


def drive_call_to_cleared(port_call, berth_code="BERTH-01",
                          window_start="2026-06-10T18:00:00Z",
                          window_end="2026-06-14T06:00:00Z"):
    """Walk a NOMINATED call to CLEARED_TO_ENTER with all four notifications
    acknowledged. Returns (port_call, notifications_dict)."""
    notes = file_all_notifications(port_call["id"], acknowledge=False)
    port_call = get_success_data(api_client.file_pre_arrival(
        port_call["id"], make_agency_ops_headers()))
    for auth_type, n in notes.items():
        notes[auth_type] = get_success_data(api_client.acknowledge_notification(
            n["id"], {"authority_reference": f"{auth_type}-REF"},
            make_port_authority_headers()))
    port_call = get_success_data(api_client.grant_clearance(
        port_call["id"], make_port_authority_headers()))
    return port_call, notes


def drive_call_to_alongside(port_call, berth_code="BERTH-01",
                            window_start="2026-06-10T18:00:00Z",
                            window_end="2026-06-14T06:00:00Z",
                            occupy_clock="2026-06-10T21:00:00Z"):
    """Walk a NOMINATED call to ALONGSIDE with an OCCUPIED berth window.

    Returns (port_call, berth_window).
    """
    port_call, _ = drive_call_to_cleared(port_call)
    bw = create_berth_window(
        port_call["id"], berth_code=berth_code, start_at=window_start, end_at=window_end)
    bw = get_success_data(api_client.confirm_berth_window(bw["id"], make_port_authority_headers()))
    set_clock(occupy_clock)
    bw = get_success_data(api_client.occupy_berth_window(bw["id"], make_agency_ops_headers()))
    port_call = get_success_data(api_client.record_arrival(
        port_call["id"], {"berth_window_id": bw["id"]}, make_agency_ops_headers()))
    return port_call, bw


def send_da_and_fund(da_id, advance_amount, finance_user_id="fin-1"):
    """Send DA to principal and record a funding advance. Returns (da, advance)."""
    da = get_success_data(api_client.send_disbursement_account(da_id, make_agency_ops_headers()))
    adv = get_success_data(api_client.create_funding_advance(
        da_id, create_funding_advance_payload(amount_cents=advance_amount),
        make_agency_finance_headers(finance_user_id)))
    da = get_success_data(api_client.get_disbursement_account(da_id, make_agency_finance_headers()))
    return da, adv


def sail_call(port_call, berth_window, sail_clock="2026-06-13T23:00:00Z"):
    """Record sailing at the given logical time. Returns updated port call."""
    set_clock(sail_clock)
    return get_success_data(api_client.record_sailing(
        port_call["id"], {"berth_window_id": berth_window["id"]},
        make_agency_ops_headers()))


def drive_call_to_sailed_with_da(port_call, berth_code="BERTH-01",
                                 advance_amount=820,
                                 line_estimated_cents=1000,
                                 sail_clock="2026-06-13T23:00:00Z"):
    """Full ladder: NOMINATED -> ALONGSIDE with a DA carrying one manual line,
    sent and funded at the given advance. Returns dict of artifacts."""
    da = create_da_for_call(port_call)
    if line_estimated_cents is not None:
        add_manual_line(da["id"], line_estimated_cents)
    port_call, bw = drive_call_to_alongside(port_call, berth_code=berth_code)
    da, adv = send_da_and_fund(da["id"], advance_amount)
    port_call = sail_call(port_call, bw, sail_clock=sail_clock)
    da = get_success_data(api_client.get_disbursement_account(da["id"], make_agency_finance_headers()))
    return {"port_call": port_call, "berth_window": bw, "da": da, "advance": adv}
