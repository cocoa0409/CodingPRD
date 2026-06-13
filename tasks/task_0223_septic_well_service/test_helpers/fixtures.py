"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup failed" errors instead of confusing downstream assertion failures.

Identity threading: FieldTech is entity_backed:Technician, so any start/complete
call uses make_field_tech_headers(technician_id) with the real Technician.id — never
the shared TEST_USERS fallback — because those calls are ownership-gated.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_account_payload, create_technician_payload, create_site_payload,
    create_asset_payload, create_service_plan_payload, create_work_order_payload,
    create_route_payload, create_repair_line_payload,
    create_inspection_report_payload, create_permit_filing_payload,
)
from .test_users import TEST_USERS, make_field_tech_headers

DISPATCHER = TEST_USERS["dispatcher_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ─── Clock control ────────────────────────────────────

def set_clock(iso8601: str):
    """Set the server's current UTC clock deterministically (PRD §3.12)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso8601}, DISPATCHER))


# ─── Tier 1: Primitive creators ───────────────────────

def create_account(**overrides):
    return get_success_data(api_client.create_account(create_account_payload(**overrides), DISPATCHER))


def create_technician(**overrides):
    return get_success_data(api_client.create_technician(create_technician_payload(**overrides), DISPATCHER))


def create_site(account_id, **overrides):
    return get_success_data(
        api_client.create_site(create_site_payload(account_id, **overrides), DISPATCHER)
    )


def create_asset(site_id, **overrides):
    return get_success_data(
        api_client.create_asset(create_asset_payload(site_id, **overrides), DISPATCHER)
    )


def create_route(technician_id, route_date, **overrides):
    return get_success_data(
        api_client.create_route(create_route_payload(technician_id, route_date, **overrides), DISPATCHER)
    )


def create_service_plan(site_id, expected_site_version, **overrides):
    return get_success_data(
        api_client.create_service_plan(
            create_service_plan_payload(site_id, expected_site_version, **overrides), DISPATCHER
        )
    )


def create_work_order(site_id, work_type, scheduled_date, window_start_minute, **overrides):
    return get_success_data(
        api_client.create_work_order(
            create_work_order_payload(site_id, work_type, scheduled_date, window_start_minute, **overrides),
            DISPATCHER,
        )
    )


# ─── Tier 2: Common base scenario ─────────────────────

def setup_account_site_tech_route(route_date, site_overrides=None, tech_overrides=None):
    """Account GOOD + one Site + one ACTIVE Technician + one OPEN Route on route_date.

    Returns dict with keys: account, site, technician, route.
    """
    account = create_account()
    site = create_site(account["id"], **(site_overrides or {}))
    technician = create_technician(**(tech_overrides or {}))
    route = create_route(technician["id"], route_date)
    return {"account": account, "site": site, "technician": technician, "route": route}


# ─── Tier 3: Work-order lifecycle shortcuts ───────────

def schedule_work_order(work_order_id, route_id):
    return get_success_data(
        api_client.schedule_work_order(work_order_id, {"route_id": route_id}, DISPATCHER)
    )


def dispatch_work_order(work_order_id):
    return get_success_data(api_client.dispatch_work_order(work_order_id, DISPATCHER))


def start_work_order(work_order_id, technician_id):
    return get_success_data(
        api_client.start_work_order(work_order_id, make_field_tech_headers(technician_id))
    )


def complete_work_order(work_order_id, technician_id, **complete_payload):
    return get_success_data(
        api_client.complete_work_order(
            work_order_id, dict(complete_payload), make_field_tech_headers(technician_id)
        )
    )


def create_scheduled_work_order(site_id, route_id, scheduled_date, window_start_minute,
                                work_type="PUMPING", **wo_overrides):
    """Create a DRAFT work order and schedule it onto route_id. Returns scheduled WO."""
    wo = create_work_order(site_id, work_type, scheduled_date, window_start_minute, **wo_overrides)
    return schedule_work_order(wo["id"], route_id)


def create_dispatched_work_order(site_id, route_id, scheduled_date, window_start_minute,
                                 work_type="PUMPING", **wo_overrides):
    """Create -> schedule -> dispatch. Returns dispatched WO."""
    wo = create_scheduled_work_order(
        site_id, route_id, scheduled_date, window_start_minute, work_type=work_type, **wo_overrides
    )
    return dispatch_work_order(wo["id"])


def create_started_work_order(site_id, route_id, technician_id, scheduled_date,
                              window_start_minute, work_type="PUMPING", **wo_overrides):
    """Create -> schedule -> dispatch -> start. Returns started (IN_PROGRESS) WO."""
    wo = create_dispatched_work_order(
        site_id, route_id, scheduled_date, window_start_minute, work_type=work_type, **wo_overrides
    )
    return start_work_order(wo["id"], technician_id)


def create_completed_work_order(site_id, route_id, technician_id, scheduled_date,
                                window_start_minute, work_type="PUMPING",
                                complete_payload=None, **wo_overrides):
    """Full path: create -> schedule -> dispatch -> start -> complete. Returns completed WO."""
    wo = create_started_work_order(
        site_id, route_id, technician_id, scheduled_date, window_start_minute,
        work_type=work_type, **wo_overrides
    )
    return complete_work_order(wo["id"], technician_id, **(complete_payload or {}))


# ─── Tier 4: Compliance lifecycle shortcuts ───────────

def create_completed_inspection_wo(base, scheduled_date, window_start_minute):
    """On a setup_account_site_tech_route base, create a COMPLETED INSPECTION WO.

    Returns the completed WorkOrder dict. INSPECTION completion needs no measured_gallons.
    """
    return create_completed_work_order(
        base["site"]["id"], base["route"]["id"], base["technician"]["id"],
        scheduled_date, window_start_minute, work_type="INSPECTION",
    )


def create_inspection_report(work_order_id, **overrides):
    return get_success_data(
        api_client.create_inspection_report(
            create_inspection_report_payload(work_order_id, **overrides), COMPLIANCE
        )
    )


def finalize_inspection_report(report_id, result):
    return get_success_data(
        api_client.finalize_inspection_report(report_id, {"result": result}, COMPLIANCE)
    )


def create_permit_filing(inspection_report_id, site_id):
    return get_success_data(
        api_client.create_permit_filing(
            create_permit_filing_payload(inspection_report_id, site_id), COMPLIANCE
        )
    )


def setup_finalized_report(result, defect_count, scheduled_date="2026-06-02",
                           window_start_minute=540, finalize_clock="2026-06-01T00:00:00Z",
                           site_overrides=None, asset_overrides=None):
    """Drive a Site to a FINALIZED inspection report with the given result/defect_count.

    Steps: set clock -> account/site/(optional asset)/tech/route -> COMPLETED INSPECTION WO
    -> DRAFT report (defect_count) -> finalize(result).

    Returns dict: account, site, technician, route, work_order, report.
    """
    set_clock(finalize_clock)
    base = setup_account_site_tech_route(scheduled_date, site_overrides=site_overrides)
    if asset_overrides is not None:
        create_asset(base["site"]["id"], **asset_overrides)
    wo = create_completed_inspection_wo(base, scheduled_date, window_start_minute)
    report = create_inspection_report(wo["id"], defect_count=defect_count)
    report = finalize_inspection_report(report["id"], result)
    return {
        "account": base["account"], "site": base["site"], "technician": base["technician"],
        "route": base["route"], "work_order": wo, "report": report,
    }


def setup_submitted_permit(result="PASS", defect_count=0,
                           finalize_clock="2026-06-01T00:00:00Z",
                           submit_clock="2026-06-05T00:00:00Z",
                           scheduled_date="2026-06-02", site_overrides=None,
                           asset_overrides=None):
    """Drive to a SUBMITTED PermitFiling: finalized report -> open filing -> advance clock
    past cooling-off -> submit.

    Returns dict: account, site, technician, route, work_order, report, filing.
    """
    ctx = setup_finalized_report(
        result, defect_count, scheduled_date=scheduled_date, finalize_clock=finalize_clock,
        site_overrides=site_overrides, asset_overrides=asset_overrides,
    )
    filing = create_permit_filing(ctx["report"]["id"], ctx["site"]["id"])
    set_clock(submit_clock)
    filing = get_success_data(api_client.submit_permit_filing(filing["id"], COMPLIANCE))
    ctx["filing"] = filing
    return ctx


# ─── Tier 5: Account-balance / invoicing shortcut ─────

def invoice_work_order(work_order_id):
    return get_success_data(api_client.invoice_work_order(work_order_id, DISPATCHER))


def pay_work_order(work_order_id):
    return get_success_data(api_client.pay_work_order(work_order_id, DISPATCHER))


# ─── Helpers for reading current state ────────────────

def get_site(site_id):
    return get_success_data(api_client.get_site(site_id, DISPATCHER))


def get_route(route_id):
    return get_success_data(api_client.get_route(route_id, DISPATCHER))


def get_work_order(work_order_id):
    return get_success_data(api_client.get_work_order(work_order_id, DISPATCHER))


def get_account(account_id):
    return get_success_data(api_client.get_account(account_id, DISPATCHER))


def get_permit_filing(filing_id):
    return get_success_data(api_client.get_permit_filing(filing_id, DISPATCHER))


def get_service_plan(plan_id):
    return get_success_data(api_client.get_service_plan(plan_id, DISPATCHER))
