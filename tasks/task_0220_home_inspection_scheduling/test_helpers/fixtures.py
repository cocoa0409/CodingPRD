"""Composite setup helpers.

Every fixture builds its preconditions from scratch (the server DB is empty at the
start of each test) using only PRD-declared endpoints. Setup calls use the lenient
get_success_data() validator so setup failures surface as clear "Setup failed" errors.

Identity threading: after creating an entity-backed Inspector/Client/Agent, any
ownership-gated call uses make_<role>_headers(entity_id), never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_inspector_headers
from . import factories as F


SCHED = TEST_USERS["scheduler_headers"]


# ---------------------------------------------------------------------------
# Base configuration: published fee schedule, territory, inspector, parties,
# property. Returns a dict of created entities.
# ---------------------------------------------------------------------------
def setup_base_config(certifications=None, daily_capacity_minutes=480,
                      square_footage=2200, year_built=1990, zip_code="33101",
                      territory_zip_codes=None, travel_buffer_minutes=30,
                      client_role="BUYER", fs_overrides=None):
    """Create published fee schedule + territory + inspector + client + agent +
    property. Returns dict with keys: fee_schedule, territory, inspector, client,
    agent, property."""
    if certifications is None:
        certifications = ["BUYER", "SELLER", "FOUR_POINT", "WIND_MIT"]
    if territory_zip_codes is None:
        territory_zip_codes = ["33101"]

    fs_payload = F.create_fee_schedule_payload(**(fs_overrides or {}))
    fs = get_success_data(api_client.create_fee_schedule(fs_payload, SCHED))
    api_client.publish_fee_schedule(fs["id"], SCHED)
    fs = get_success_data(api_client.get_fee_schedule(fs["id"], SCHED))

    ter = get_success_data(api_client.create_territory(
        F.create_territory_payload(zip_codes=territory_zip_codes,
                                   travel_buffer_minutes=travel_buffer_minutes), SCHED))
    insp = get_success_data(api_client.create_inspector(
        F.create_inspector_payload(ter["id"], certifications=certifications,
                                   daily_capacity_minutes=daily_capacity_minutes), SCHED))
    cli = get_success_data(api_client.create_client(
        F.create_client_payload(role_in_deal=client_role), SCHED))
    agt = get_success_data(api_client.create_agent(F.create_agent_payload(), SCHED))
    prop = get_success_data(api_client.create_property(
        F.create_property_payload(square_footage=square_footage,
                                  year_built=year_built, zip_code=zip_code), SCHED))
    return {
        "fee_schedule": fs, "territory": ter, "inspector": insp,
        "client": cli, "agent": agt, "property": prop,
    }


def create_property(square_footage=2200, year_built=1990, zip_code="33101",
                    address_line="2 B St"):
    """Create an extra property."""
    return get_success_data(api_client.create_property(
        F.create_property_payload(square_footage=square_footage, year_built=year_built,
                                  zip_code=zip_code, address_line=address_line), SCHED))


def create_inspector(territory_id, certifications=None, daily_capacity_minutes=480,
                     full_name="Ivo"):
    """Create an extra inspector."""
    return get_success_data(api_client.create_inspector(
        F.create_inspector_payload(territory_id, certifications=certifications,
                                   daily_capacity_minutes=daily_capacity_minutes,
                                   full_name=full_name), SCHED))


# ---------------------------------------------------------------------------
# Tier 1/2: order in a given lifecycle stage
# ---------------------------------------------------------------------------
def create_requested_order(cfg, inspection_type="BUYER", property_id=None):
    """Create a primary REQUESTED order against an existing base config."""
    pid = property_id or cfg["property"]["id"]
    return get_success_data(api_client.create_inspection_order(
        F.create_inspection_order_payload(pid, cfg["client"]["id"], cfg["agent"]["id"],
                                          cfg["fee_schedule"]["id"], inspection_type),
        SCHED))


def setup_requested_order(inspection_type="BUYER", **cfg_kwargs):
    """Base config + a single REQUESTED order. Returns (cfg, order)."""
    cfg = setup_base_config(**cfg_kwargs)
    order = create_requested_order(cfg, inspection_type=inspection_type)
    return cfg, order


def add_addon(order_id, kind):
    return get_success_data(api_client.create_addon(order_id, F.create_addon_payload(kind), SCHED))


def schedule(order_id, inspector_id, scheduled_start):
    return get_success_data(api_client.schedule_order(
        order_id, F.schedule_order_payload(inspector_id, scheduled_start), SCHED))


def setup_scheduled_order(inspection_type="BUYER", scheduled_start="2026-07-01T13:00:00Z",
                          addons=None, **cfg_kwargs):
    """Base config + REQUESTED order (+ optional add-ons) + scheduled. Returns
    (cfg, order) where order is the scheduled order."""
    cfg, order = setup_requested_order(inspection_type=inspection_type, **cfg_kwargs)
    for kind in (addons or []):
        add_addon(order["id"], kind)
    order = schedule(order["id"], cfg["inspector"]["id"], scheduled_start)
    return cfg, order


def setup_started_order(inspection_type="BUYER", scheduled_start="2026-07-01T13:00:00Z",
                        addons=None, pay_amount=None, **cfg_kwargs):
    """Scheduled then started (IN_PROGRESS). Returns (cfg, order)."""
    cfg, order = setup_scheduled_order(inspection_type=inspection_type,
                                       scheduled_start=scheduled_start,
                                       addons=addons, **cfg_kwargs)
    if pay_amount is not None:
        get_success_data(api_client.pay_order(order["id"], F.pay_order_payload(pay_amount), SCHED))
    insp_headers = make_inspector_headers(cfg["inspector"]["id"])
    order = get_success_data(api_client.start_order(order["id"], insp_headers))
    return cfg, order


def setup_report_draft_order(inspection_type="BUYER", scheduled_start="2026-07-01T13:00:00Z",
                             measured_square_footage=2200, addons=None, pay_amount=None,
                             **cfg_kwargs):
    """Scheduled -> started -> report created (REPORT_DRAFT). Returns
    (cfg, order, report)."""
    cfg, order = setup_started_order(inspection_type=inspection_type,
                                     scheduled_start=scheduled_start,
                                     addons=addons, pay_amount=pay_amount, **cfg_kwargs)
    insp_headers = make_inspector_headers(cfg["inspector"]["id"])
    report = get_success_data(api_client.create_report(
        order["id"], F.create_report_payload(measured_square_footage), insp_headers))
    return cfg, order, report


def add_defects(report_id, inspector_id, defects):
    """defects: list of (location, severity)."""
    insp_headers = make_inspector_headers(inspector_id)
    created = []
    for location, severity in defects:
        created.append(get_success_data(api_client.create_defect(
            report_id, F.create_defect_payload(location, severity), insp_headers)))
    return created


def setup_submitted_report(inspection_type="BUYER", scheduled_start="2026-07-01T13:00:00Z",
                           measured_square_footage=2200, defects=None, addons=None,
                           pay_amount=None, **cfg_kwargs):
    """Report DRAFT (+ optional defects) -> SUBMITTED. Returns (cfg, order, report,
    defect_list)."""
    cfg, order, report = setup_report_draft_order(
        inspection_type=inspection_type, scheduled_start=scheduled_start,
        measured_square_footage=measured_square_footage, addons=addons,
        pay_amount=pay_amount, **cfg_kwargs)
    defect_list = add_defects(report["id"], cfg["inspector"]["id"], defects or [])
    insp_headers = make_inspector_headers(cfg["inspector"]["id"])
    report = get_success_data(api_client.submit_report(report["id"], insp_headers))
    return cfg, order, report, defect_list


def setup_approved_report(inspection_type="BUYER", scheduled_start="2026-07-01T13:00:00Z",
                          measured_square_footage=2200, defects=None, addons=None,
                          pay_amount=None, **cfg_kwargs):
    """Report SUBMITTED -> APPROVED. Returns (cfg, order, report, defect_list)."""
    cfg, order, report, defect_list = setup_submitted_report(
        inspection_type=inspection_type, scheduled_start=scheduled_start,
        measured_square_footage=measured_square_footage, defects=defects,
        addons=addons, pay_amount=pay_amount, **cfg_kwargs)
    report = get_success_data(api_client.approve_report(report["id"], SCHED))
    return cfg, order, report, defect_list


def setup_delivered_order(inspection_type="BUYER", scheduled_start="2026-07-01T13:00:00Z",
                          measured_square_footage=2200, defects=None, addons=None,
                          pay_amount=43000, **cfg_kwargs):
    """Full lifecycle through DELIVERED (paid in full). Returns
    (cfg, order, report, defect_list)."""
    cfg, order, report, defect_list = setup_approved_report(
        inspection_type=inspection_type, scheduled_start=scheduled_start,
        measured_square_footage=measured_square_footage, defects=defects,
        addons=addons, pay_amount=pay_amount, **cfg_kwargs)
    order = get_success_data(api_client.deliver_order(order["id"], SCHED))
    return cfg, order, report, defect_list


# ---------------------------------------------------------------------------
# Tier 3: re-inspection ready scenario (delivered parent with a failing report)
# ---------------------------------------------------------------------------
def setup_delivered_failing_parent(inspection_type="BUYER",
                                   scheduled_start="2026-07-19T13:00:00Z",
                                   property_sqft=2500, measured_square_footage=2200,
                                   defects=None, addons=None, pay_amount=52900,
                                   **cfg_kwargs):
    """Drive a parent order to DELIVERED with a failing (MAJOR/CRITICAL) report so a
    re-inspection is warranted. Returns (cfg, parent_order, report)."""
    if defects is None:
        defects = [("Panel", "MAJOR"), ("Foundation", "CRITICAL")]
    cfg_kwargs.setdefault("square_footage", property_sqft)
    cfg, order, report, _ = setup_delivered_order(
        inspection_type=inspection_type, scheduled_start=scheduled_start,
        measured_square_footage=measured_square_footage, defects=defects,
        addons=addons, pay_amount=pay_amount, **cfg_kwargs)
    return cfg, order, report


def reinspect(parent_order_id, inspector_id, scheduled_start, expected_order_version):
    return api_client.reinspect_order(
        parent_order_id,
        F.reinspect_order_payload(inspector_id, scheduled_start, expected_order_version),
        SCHED)
