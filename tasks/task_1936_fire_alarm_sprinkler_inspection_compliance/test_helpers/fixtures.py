"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: ContractorAdmin calls are entity-backed by Contractor and
Technician calls are entity-backed by Technician. Every context dict carries
per-instance headers built from the real entity ids via the make_* builders;
ownership-gated calls never fall back to the shared constants.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CATEGORY_LICENSE_CLASS, DEFAULT_CLOCK_ISO
from .factories import (
    create_backflow_test_payload,
    create_contractor_payload,
    create_device_payload,
    create_deficiency_payload,
    create_event_payload,
    create_false_alarm_payload,
    create_impairment_payload,
    create_license_payload,
    create_permit_payload,
    create_plan_payload,
    create_property_payload,
    create_pump_test_payload,
    create_system_payload,
    create_technician_payload,
)
from .test_users import (
    TEST_USERS,
    make_contractor_admin_headers,
    make_technician_headers,
)

MARSHAL = TEST_USERS["fire_marshal_headers"]

_license_seq = itertools.count(1)
_serial_seq = itertools.count(1)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_CLOCK_ISO):
    """Advance the logical clock (FireMarshal-only); runs the daily sweep."""
    return get_success_data(api_client.set_clock(to_iso8601, MARSHAL))


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_contractor(legal_name="Acme Fire Protection", state_license_no=None):
    """Register a contractor (born ACTIVE, score 1000, GOOD_STANDING)."""
    payload = create_contractor_payload(
        legal_name=legal_name,
        state_license_no=state_license_no or f"C-{next(_license_seq):05d}",
    )
    return get_success_data(api_client.create_contractor(payload, MARSHAL), 201)


def admin_headers(con):
    return make_contractor_admin_headers(con["id"])


def tech_headers(tech):
    return make_technician_headers(tech["id"])


def add_technician(con, full_name="Test Tech", nicet_level="II"):
    """Add a technician to a contractor (born ACTIVE)."""
    payload = create_technician_payload(full_name=full_name, nicet_level=nicet_level)
    return get_success_data(
        api_client.create_technician(con["id"], payload, admin_headers(con)), 201)


def add_license(con, tech, license_class="ALARM",
                issued_on="2026-01-01", expires_on="2027-06-01"):
    """Record a license for a technician (born ACTIVE)."""
    payload = create_license_payload(
        license_class=license_class, issued_on=issued_on, expires_on=expires_on)
    return get_success_data(
        api_client.create_license_record(tech["id"], payload, admin_headers(con)),
        201)


def create_property(con, address_line="1 Test Way", occupancy_class="BUSINESS",
                    jurisdiction_code="LACO"):
    """Register a property under the contractor of record (born ACTIVE)."""
    payload = create_property_payload(
        con["id"], address_line=address_line, occupancy_class=occupancy_class,
        jurisdiction_code=jurisdiction_code)
    return get_success_data(
        api_client.create_property(payload, admin_headers(con)), 201)


def create_system(con, prop, system_category="FIRE_ALARM",
                  install_date="2026-01-01", certification_cycle_anchor="2000-01-01"):
    """Register a protected system on a property (born IN_SERVICE, NORMAL)."""
    payload = create_system_payload(
        system_category=system_category, install_date=install_date,
        certification_cycle_anchor=certification_cycle_anchor)
    return get_success_data(
        api_client.create_system(prop["id"], payload, admin_headers(con)), 201)


def create_device(con, sys, device_type="SMOKE_DETECTOR", serial_no=None):
    """Register a device in a system (born IN_SERVICE; frequency + due computed)."""
    payload = create_device_payload(
        device_type=device_type,
        serial_no=serial_no or f"SN-{next(_serial_seq):05d}")
    return get_success_data(
        api_client.create_device(sys["id"], payload, admin_headers(con)), 201)


def create_plan(con, prop, plan_year=2026):
    """Create an annual plan, threading the property's current version (OCC)."""
    payload = create_plan_payload(plan_year, prop["version"])
    return get_success_data(
        api_client.create_plan(prop["id"], payload, admin_headers(con)), 201)


def publish_plan(con, plan):
    return get_success_data(api_client.publish_plan(plan["id"], admin_headers(con)))


def schedule_event(con, plan, sys, tech,
                   scheduled_start="2026-08-05T09:00:00Z",
                   scheduled_end="2026-08-05T10:00:00Z"):
    payload = create_event_payload(
        sys["id"], tech["id"], scheduled_start=scheduled_start,
        scheduled_end=scheduled_end)
    return get_success_data(
        api_client.create_event(plan["id"], payload, admin_headers(con)), 201)


def start_event(tech, ev):
    return get_success_data(api_client.start_event(ev["id"], tech_headers(tech)))


def complete_event(tech, ev):
    return get_success_data(api_client.complete_event(ev["id"], tech_headers(tech)))


def record_deficiency(tech, ev, dev, classification="NONCRITICAL"):
    payload = create_deficiency_payload(dev["id"], classification=classification)
    return get_success_data(
        api_client.create_deficiency(ev["id"], payload, tech_headers(tech)), 201)


def list_event_deficiencies(con, ev):
    return get_success_data(api_client.list_deficiencies(ev["id"], admin_headers(con)))


def get_deficiency(con, deficiency_id):
    return get_success_data(api_client.get_deficiency(deficiency_id, admin_headers(con)))


def get_event_report(con, ev):
    """Return the single active marshal report auto-created for the event."""
    reports = get_success_data(api_client.list_event_reports(ev["id"], admin_headers(con)))
    assert isinstance(reports, list) and len(reports) == 1, (
        f"expected exactly one marshal report for the event, got {len(reports)}")
    return reports[0]


# ---------------------------------------------------------------------------
# Tier 2: the inspection site (contractor + property + system + device + tech)
# ---------------------------------------------------------------------------

def setup_inspection_site(system_category="FIRE_ALARM", device_type="SMOKE_DETECTOR",
                          install_date="2026-01-01", nicet_level="II",
                          license_class=None, license_issued_on="2026-01-01",
                          license_expires_on="2027-06-01",
                          occupancy_class="BUSINESS", device_count=1,
                          legal_name="Acme Fire Protection"):
    """Contractor + property + one system + N devices + one licensed technician.

    Returns a context dict with per-instance headers threaded throughout.
    With device_count=0, "dev" is None.
    """
    con = create_contractor(legal_name=legal_name)
    prop = create_property(con, occupancy_class=occupancy_class)
    sys = create_system(con, prop, system_category=system_category,
                        install_date=install_date)
    devices = [create_device(con, sys, device_type=device_type)
               for _ in range(device_count)]
    tech = add_technician(con, nicet_level=nicet_level)
    lic = add_license(con, tech,
                      license_class=license_class or CATEGORY_LICENSE_CLASS[system_category],
                      issued_on=license_issued_on, expires_on=license_expires_on)
    return {
        "con": con, "prop": prop, "sys": sys, "devices": devices,
        "dev": devices[0] if devices else None, "tech": tech, "lic": lic,
        "admin": admin_headers(con), "tech_headers": tech_headers(tech),
    }


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts — scheduled / in-progress / completed events
# ---------------------------------------------------------------------------

def setup_published_plan(ctx, plan_year=2026):
    """Attach a published plan to an existing site; refreshes ctx in place."""
    prop = get_success_data(api_client.get_property(ctx["prop"]["id"], ctx["admin"]))
    plan = create_plan(ctx["con"], prop, plan_year=plan_year)
    plan = publish_plan(ctx["con"], plan)
    ctx["prop"] = prop
    ctx["plan"] = plan
    return ctx


def setup_scheduled_event(scheduled_start="2026-08-05T09:00:00Z",
                          scheduled_end="2026-08-05T10:00:00Z", **site_kwargs):
    """Site + published plan + one SCHEDULED event."""
    ctx = setup_inspection_site(**site_kwargs)
    setup_published_plan(ctx)
    ctx["ev"] = schedule_event(ctx["con"], ctx["plan"], ctx["sys"], ctx["tech"],
                               scheduled_start=scheduled_start,
                               scheduled_end=scheduled_end)
    return ctx


def setup_completed_event(deficiency_classifications=(),
                          scheduled_start="2026-08-03T09:00:00Z",
                          scheduled_end="2026-08-03T10:00:00Z",
                          complete_clock="2026-08-03T09:30:00Z",
                          **site_kwargs):
    """Site + published plan + event started and completed, with the given
    deficiencies recorded while IN_PROGRESS. The marshal report is captured.

    Returns ctx with keys: ev, defs (list), report.
    """
    ctx = setup_scheduled_event(scheduled_start=scheduled_start,
                                scheduled_end=scheduled_end, **site_kwargs)
    set_clock(complete_clock)
    start_event(ctx["tech"], ctx["ev"])
    defs = [record_deficiency(ctx["tech"], ctx["ev"], ctx["dev"], classification=c)
            for c in deficiency_classifications]
    ctx["defs"] = defs
    ctx["ev"] = complete_event(ctx["tech"], ctx["ev"])
    ctx["report"] = get_event_report(ctx["con"], ctx["ev"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: accumulation helpers — false alarms
# ---------------------------------------------------------------------------

def record_and_assess_alarm(prop, alarm_occurred_at, cause_code):
    """Record a false alarm (FireMarshal) and assess it. Returns the case."""
    payload = create_false_alarm_payload(alarm_occurred_at=alarm_occurred_at,
                                         cause_code=cause_code)
    case = get_success_data(
        api_client.create_false_alarm(prop["id"], payload, MARSHAL), 201)
    return get_success_data(api_client.assess_false_alarm(case["id"], MARSHAL))


def record_alarm(prop, alarm_occurred_at, cause_code):
    """Record a false alarm without assessing it. Returns the OPEN case."""
    payload = create_false_alarm_payload(alarm_occurred_at=alarm_occurred_at,
                                         cause_code=cause_code)
    return get_success_data(
        api_client.create_false_alarm(prop["id"], payload, MARSHAL), 201)


# ---------------------------------------------------------------------------
# Tier 5: specialty tests and permits
# ---------------------------------------------------------------------------

def setup_invoiced_backflow_test(invoice_clock="2026-08-02T00:00:00Z",
                                 tested_at="2026-08-01T10:00:00Z"):
    """BACKFLOW site + PASS backflow test invoiced at `invoice_clock`.

    Returns ctx with key `bt` (the INVOICED BackflowTest).
    """
    set_clock("2026-08-01T00:00:00Z")
    ctx = setup_inspection_site(system_category="BACKFLOW",
                                device_type="BACKFLOW_ASSEMBLY",
                                occupancy_class="MERCANTILE")
    payload = create_backflow_test_payload(ctx["dev"]["id"], ctx["tech"]["id"],
                                           tested_at=tested_at, result="PASS")
    bt = get_success_data(
        api_client.create_backflow_test(ctx["sys"]["id"], payload, ctx["admin"]), 201)
    set_clock(invoice_clock)
    ctx["bt"] = get_success_data(
        api_client.invoice_backflow_test(bt["id"], ctx["admin"]))
    return ctx


def create_permit_for_system(con, sys, project_valuation_cents):
    """Apply for a modification permit, threading the system's current version."""
    payload = create_permit_payload(project_valuation_cents, sys["version"])
    return get_success_data(
        api_client.create_permit(sys["id"], payload, admin_headers(con)), 201)


def setup_issued_permit(system_category="FIRE_ALARM", install_date="2026-01-01",
                        project_valuation_cents=500000, issue_clock=None,
                        **site_kwargs):
    """Site + permit in ISSUED. Returns ctx with key `permit`."""
    ctx = setup_inspection_site(system_category=system_category,
                                install_date=install_date, **site_kwargs)
    permit = create_permit_for_system(ctx["con"], ctx["sys"], project_valuation_cents)
    if issue_clock is not None:
        set_clock(issue_clock)
    ctx["permit"] = get_success_data(api_client.issue_permit(permit["id"], MARSHAL))
    return ctx
