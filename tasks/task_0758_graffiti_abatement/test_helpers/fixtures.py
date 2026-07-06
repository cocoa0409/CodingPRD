"""Composite setup helpers.

These encapsulate the multi-step API sequences needed to drive the system into
the states the tests assert against. Every helper builds its preconditions from
scratch using only PRD-declared endpoints (each pytest test runs against a fresh,
empty database). Setup calls use get_success_data (lenient) so a broken precondition
surfaces as a clear "Setup failed" error rather than a confusing assertion failure.

Identity threading: after a Crew / PropertyOwner is created, every ownership-gated
call uses make_crew_lead_headers(crew_id) / make_property_owner_headers(owner_id).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from . import factories as f
from .test_users import (
    TEST_USERS, make_crew_lead_headers, make_property_owner_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
CLERK = TEST_USERS["intake_clerk_headers"]
INV = TEST_USERS["inventory_manager_headers"]

WINDOW_START = "2026-03-05T09:00:00Z"
WINDOW_END = "2026-03-05T12:00:00Z"


# --------------------------------------------------------------------------
# Low-level single-entity helpers (return the created resource dict)
# --------------------------------------------------------------------------
def register_owner(api=api_client, **over) -> dict:
    return get_success_data(api.create_property_owner(f.create_property_owner_payload(**over), ADMIN))


def register_site(api=api_client, ownership_type="PUBLIC", property_owner_id=None, **over) -> dict:
    payload = f.create_site_payload(ownership_type=ownership_type,
                                    property_owner_id=property_owner_id, **over)
    return get_success_data(api.create_site(payload, COORD))


def register_material(api=api_client, **over) -> dict:
    return get_success_data(api.create_material(f.create_material_payload(**over), INV))


def register_crew(api=api_client, **over) -> dict:
    return get_success_data(api.create_crew(f.create_crew_payload(**over), COORD))


def file_report(api=api_client, site_id=None, **over) -> dict:
    return get_success_data(api.create_report(f.create_report_payload(site_id, **over), CLERK))


def triage(api=api_client, report_id=None) -> dict:
    return get_success_data(api.triage_report(report_id, CLERK))


def set_clock(api=api_client, iso=None) -> None:
    get_success_data(api.set_clock(iso, ADMIN))


def cost_recovery_for_work_order(api=api_client, wo_id=None) -> dict:
    resp = api.list_cost_recoveries(COORD, params={"work_order_id": wo_id})
    body = resp.json()
    rows = body["data"]
    assert rows, f"Setup failed: no cost recovery found for work order {wo_id}"
    return rows[0]


# --------------------------------------------------------------------------
# Building blocks with material lines
# --------------------------------------------------------------------------
def material_lines(material_id, quantity):
    return [{"material_id": material_id, "quantity": quantity}]


# --------------------------------------------------------------------------
# Composite scenarios
# --------------------------------------------------------------------------
def setup_triaged_report(api=api_client, *, ownership_type="PRIVATE", severity="HIGH",
                         surface_type="WALL", is_offensive=False, crew_certified=True,
                         with_material=True, unit_cost_cents=1200, quantity_available=10.0):
    """Owner (if PRIVATE) + site + crew + material + one TRIAGED report.

    Returns a scenario dict with all ids and the entity-backed headers.
    """
    scn = {}
    owner_id = None
    if ownership_type == "PRIVATE":
        owner = register_owner(api)
        owner_id = owner["id"]
        scn["owner"] = owner
    scn["owner_id"] = owner_id

    site = register_site(api, ownership_type=ownership_type, property_owner_id=owner_id)
    scn["site"] = site
    scn["site_id"] = site["id"]

    crew = register_crew(api, is_offensive_certified=crew_certified)
    scn["crew"] = crew
    scn["crew_id"] = crew["id"]
    scn["crew_headers"] = make_crew_lead_headers(crew["id"])

    if with_material:
        material = register_material(api, unit_cost_cents=unit_cost_cents,
                                     quantity_available=quantity_available)
        scn["material"] = material
        scn["material_id"] = material["id"]

    report = file_report(api, scn["site_id"], severity=severity,
                         surface_type=surface_type, is_offensive=is_offensive)
    triage(api, report["id"])
    scn["report"] = report
    scn["report_id"] = report["id"]
    if owner_id is not None:
        scn["owner_headers"] = make_property_owner_headers(owner_id)
    return scn


def setup_dispatched(api=api_client, *, est_labor=2.5, reserve_qty=3.0,
                     scheduled_start=WINDOW_START, scheduled_end=WINDOW_END,
                     method="PAINT_OVER", **kw):
    """setup_triaged_report + dispatch (WorkOrder SCHEDULED, CostRecovery PENDING).

    reserve_qty=None dispatches with no material_lines.
    """
    scn = setup_triaged_report(api, **kw)
    lines = None
    if reserve_qty is not None and scn.get("material_id"):
        lines = material_lines(scn["material_id"], reserve_qty)
    payload = f.create_work_order_payload(
        scn["report_id"], scn["crew_id"], method=method,
        estimated_labor_hours=est_labor, material_lines=lines,
        scheduled_start=scheduled_start, scheduled_end=scheduled_end,
    )
    wo = get_success_data(api.create_work_order(payload, COORD))
    scn["work_order"] = wo
    scn["work_order_id"] = wo["id"]
    scn["cost_recovery"] = cost_recovery_for_work_order(api, wo["id"])
    scn["cost_recovery_id"] = scn["cost_recovery"]["id"]
    return scn


def setup_in_progress(api=api_client, **kw):
    """setup_dispatched + BEFORE photo + start (WorkOrder / Report IN_PROGRESS)."""
    scn = setup_dispatched(api, **kw)
    ch = scn["crew_headers"]
    get_success_data(api.upload_photo(scn["work_order_id"],
                                      f.create_photo_payload("BEFORE", "http://p/b.jpg"), ch))
    get_success_data(api.start_work_order(scn["work_order_id"], ch))
    return scn


def setup_completed(api=api_client, *, actual_labor=3.0, **kw):
    """Full remediation: setup_in_progress + AFTER photo + complete.

    With the default money scenario (est 2.5h, reserve 3.0L, unit 1200, actual 3.0h)
    the recovery is ASSESSED with recoverable_cents == 26565 and the site's
    outstanding_recovery_cents == 26565.
    """
    scn = setup_in_progress(api, **kw)
    ch = scn["crew_headers"]
    get_success_data(api.upload_photo(scn["work_order_id"],
                                      f.create_photo_payload("AFTER", "http://p/a.jpg"), ch))
    get_success_data(api.complete_work_order(
        scn["work_order_id"], {"actual_labor_hours": actual_labor}, ch))
    # refresh derived state
    scn["cost_recovery"] = get_success_data(api.get_cost_recovery(scn["cost_recovery_id"], COORD))
    scn["site"] = get_success_data(api.get_site(scn["site_id"], COORD))
    return scn


def setup_assessed_notice(api=api_client, *, cure_days=30, **kw):
    """setup_completed (CostRecovery ASSESSED) + issue a COST_RECOVERY_NOTICE (SENT).

    Captures the site version used for issuance as scn['site_version'].
    """
    scn = setup_completed(api, **kw)
    site = get_success_data(api.get_site(scn["site_id"], COORD))
    scn["site_version"] = site["version"]
    payload = f.create_notice_payload(
        notice_type="COST_RECOVERY_NOTICE", cure_days=cure_days,
        expected_site_version=site["version"], cost_recovery_id=scn["cost_recovery_id"],
    )
    notice = get_success_data(api.issue_notice(scn["site_id"], payload, COORD))
    scn["notice"] = notice
    scn["notice_id"] = notice["id"]
    return scn


def setup_site_monitored(api=api_client):
    """A PUBLIC site carrying exactly two in-window reports (status MONITORED).

    Returns (site_id).
    """
    site = register_site(api, ownership_type="PUBLIC")
    file_report(api, site["id"], severity="LOW", surface_type="FENCE", reported_via="WEB")
    file_report(api, site["id"], severity="LOW", surface_type="FENCE", reported_via="WEB")
    return site["id"]
