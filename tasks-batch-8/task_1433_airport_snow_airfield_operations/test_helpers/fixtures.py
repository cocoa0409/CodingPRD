"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors. All callers are responsible for their own assertions.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_chemical_application_payload,
    create_chemical_product_payload,
    create_condition_report_payload,
    create_equipment_unit_payload,
    create_friction_assessment_payload,
    create_notam_payload,
    create_operator_shift_payload,
    create_snow_event_payload,
    create_surface_payload,
)
from .test_users import TEST_USERS, make_maintenance_lead_headers

OPS = TEST_USERS["ops_controller_headers"]
INSP = TEST_USERS["airfield_inspector_headers"]
ML = TEST_USERS["maintenance_lead_headers"]
AIRLINE = TEST_USERS["airline_coordinator_headers"]
ADMIN = TEST_USERS["system_admin_headers"]

# Segregation-of-duties user ids for the MaintenanceLead action pairs.
AUTH_USER = "ml-authorizer-1"
DISP_USER = "ml-dispenser-2"

DEFAULT_UNITS = [
    ("PLOW-01", "PLOW", 14500),
    ("PLOW-02", "PLOW", 14500),
    ("BROOM-01", "BROOM", 12000),
]


def _ok(step, resp):
    try:
        return get_success_data(resp)
    except AssertionError as exc:
        raise AssertionError(f"Setup failed at {step}: {exc}")


# ---------------------------------------------------------------------------
# Tier 1 — configuration + event activation
# ---------------------------------------------------------------------------

def create_ready_equipment(units=None):
    """Register equipment units (default: three units, all starting READY)."""
    created = []
    for code, unit_type, rate in (units or DEFAULT_UNITS):
        resp = api_client.create_equipment_unit(
            create_equipment_unit_payload(
                unit_code=code, unit_type=unit_type, hourly_rate_cents=rate),
            ADMIN,
        )
        created.append(_ok(f"create_equipment_unit({code})", resp))
    return created


def take_unit_out_of_service(unit_id):
    resp = api_client.equipment_readiness_action(
        unit_id, {"action": "TAKE_OUT_OF_SERVICE"}, ML)
    return _ok("take_unit_out_of_service", resp)


def create_surface(surface_code="RWY-09L", surface_type="RUNWAY",
                   length_ft=5000, width_ft=150, priority_rank=1,
                   **extra):
    resp = api_client.create_surface(
        create_surface_payload(
            surface_code=surface_code, surface_type=surface_type,
            length_ft=length_ft, width_ft=width_ft,
            priority_rank=priority_rank, **extra),
        ADMIN,
    )
    return _ok(f"create_surface({surface_code})", resp)


def create_snow_event(event_code="SNOW-1", chemical_limit_lbs=100000,
                      budget_cents=5000000, season_label="2025-2026",
                      **extra):
    resp = api_client.create_snow_event(
        create_snow_event_payload(
            event_code=event_code, season_label=season_label,
            chemical_limit_lbs=chemical_limit_lbs, budget_cents=budget_cents,
            **extra),
        OPS,
    )
    return _ok(f"create_snow_event({event_code})", resp)


def event_action(event_id, action):
    resp = api_client.event_action(event_id, {"action": action}, OPS)
    return _ok(f"event_action({action})", resp)


def closure_action(event_id, action, headers=None):
    resp = api_client.closure_action(event_id, {"action": action},
                                     headers or OPS)
    return _ok(f"closure_action({action})", resp)


def activate_event(event_id):
    return event_action(event_id, "ACTIVATE")


def setup_activated_event(event_code="SNOW-1", chemical_limit_lbs=100000,
                          budget_cents=5000000, with_equipment=True):
    """Three READY units (default) + event driven FORECAST -> ACTIVATED."""
    units = create_ready_equipment() if with_equipment else []
    event = create_snow_event(event_code, chemical_limit_lbs, budget_cents)
    event = activate_event(event["id"])
    return {"event": event, "units": units}


def setup_event_with_surface(event_code="SNOW-1", surface_code="RWY-09L",
                             surface_type="RUNWAY", length_ft=5000,
                             width_ft=150, priority_rank=1,
                             chemical_limit_lbs=100000, budget_cents=5000000):
    """Three READY units + one surface + ACTIVATED event."""
    units = create_ready_equipment()
    surface = create_surface(surface_code, surface_type, length_ft,
                             width_ft, priority_rank)
    event = create_snow_event(event_code, chemical_limit_lbs, budget_cents)
    event = activate_event(event["id"])
    return {"event": event, "surface": surface, "units": units}


# ---------------------------------------------------------------------------
# Tier 2 — surface posture, condition reports, friction assessments
# ---------------------------------------------------------------------------

def surface_action(surface_id, action, event_id):
    resp = api_client.surface_action(
        surface_id, {"action": action, "event_id": event_id}, OPS)
    return _ok(f"surface_action({action})", resp)


def get_surface(surface_id):
    resp = api_client.get_surface(surface_id, OPS)
    return _ok("get_surface", resp)


def get_surface_version(surface_id):
    return get_surface(surface_id)["version"]


def file_condition_report(event_id, surface_id, expected_surface_version=None,
                          **overrides):
    """File a condition report, threading the OCC token from a fresh read."""
    if expected_surface_version is None:
        expected_surface_version = get_surface_version(surface_id)
    resp = api_client.create_condition_report(
        create_condition_report_payload(
            event_id, surface_id, expected_surface_version, **overrides),
        INSP,
    )
    return _ok("file_condition_report", resp)


def record_friction_assessment(event_id, surface_id, mu_value=0.60,
                               expected_surface_version=None, **overrides):
    """Record a friction assessment, threading the OCC token from a fresh read."""
    if expected_surface_version is None:
        expected_surface_version = get_surface_version(surface_id)
    resp = api_client.create_friction_assessment(
        create_friction_assessment_payload(
            event_id, surface_id, expected_surface_version,
            mu_value=mu_value, **overrides),
        INSP,
    )
    return _ok("record_friction_assessment", resp)


def setup_restricted_surface_with_friction(event_code="SNOW-N1",
                                           mu_value=0.60):
    """ACTIVATED event + surface RESTRICTED + one REPORTED friction reading.

    Returns dict(event, surface, units, assessment).
    """
    ctx = setup_event_with_surface(event_code=event_code)
    surface = surface_action(ctx["surface"]["id"], "RESTRICT",
                             ctx["event"]["id"])
    assessment = record_friction_assessment(
        ctx["event"]["id"], ctx["surface"]["id"], mu_value=mu_value)
    ctx["surface"] = surface
    ctx["assessment"] = assessment
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 — NOTAM drafting and issuance
# ---------------------------------------------------------------------------

def draft_notam(event_id, surface_id, source_report_id=None,
                source_assessment_id=None, **overrides):
    payload = create_notam_payload(event_id, surface_id, **overrides)
    if source_report_id is not None:
        payload["source_report_id"] = source_report_id
    if source_assessment_id is not None:
        payload["source_assessment_id"] = source_assessment_id
    resp = api_client.create_notam(payload, OPS)
    return _ok("draft_notam", resp)


def notam_action(notam_id, action, **window):
    payload = {"action": action}
    payload.update(window)
    resp = api_client.notam_action(notam_id, payload, OPS)
    return _ok(f"notam_action({action})", resp)


def issue_notam(notam_id, **window):
    return notam_action(notam_id, "ISSUE", **window)


def setup_issued_notam(event_code="SNOW-N2", notam_type="SURFACE_CONDITION",
                       effective_from="2026-08-02T00:00:00Z",
                       effective_until="2026-08-03T00:00:00Z",
                       mu_value=0.60, source="assessment"):
    """Surface RESTRICTED + friction REPORTED + sourced NOTAM driven to ISSUED.

    Returns dict(event, surface, units, assessment, notam).
    """
    ctx = setup_restricted_surface_with_friction(event_code=event_code,
                                                 mu_value=mu_value)
    link = {}
    if source == "assessment":
        link["source_assessment_id"] = ctx["assessment"]["id"]
    notam = draft_notam(
        ctx["event"]["id"], ctx["surface"]["id"],
        notam_type=notam_type, effective_from=effective_from,
        effective_until=effective_until, **link)
    notam = issue_notam(notam["id"])
    ctx["notam"] = notam
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — chemical products and applications
# ---------------------------------------------------------------------------

def create_chemical_product(product_code="NAAC-01", base_rate=30,
                            unit_cost=12, seasonal_limit=100000):
    resp = api_client.create_chemical_product(
        create_chemical_product_payload(
            product_code=product_code,
            base_rate_lbs_per_1000sqft=base_rate,
            unit_cost_cents_per_lb=unit_cost,
            seasonal_limit_lbs=seasonal_limit),
        ADMIN,
    )
    return _ok(f"create_chemical_product({product_code})", resp)


def get_chemical_product(product_id):
    resp = api_client.get_chemical_product(product_id, ML)
    return _ok("get_chemical_product", resp)


def propose_application(event_id, surface_id, product_id, pavement_temp_f=20):
    resp = api_client.create_chemical_application(
        create_chemical_application_payload(
            event_id, surface_id, product_id,
            pavement_temp_f=pavement_temp_f),
        ML,
    )
    return _ok("propose_application", resp)


def get_chemical_application(application_id):
    resp = api_client.get_chemical_application(application_id, ML)
    return _ok("get_chemical_application", resp)


def authorize_application(application_id, user_id=AUTH_USER):
    resp = api_client.application_action(
        application_id, {"action": "AUTHORIZE"},
        make_maintenance_lead_headers(user_id))
    return _ok("authorize_application", resp)


def dispense_application(application_id, user_id=DISP_USER):
    resp = api_client.application_action(
        application_id, {"action": "DISPENSE"},
        make_maintenance_lead_headers(user_id))
    return _ok("dispense_application", resp)


def void_application(application_id, user_id=AUTH_USER):
    resp = api_client.application_action(
        application_id, {"action": "VOID"},
        make_maintenance_lead_headers(user_id))
    return _ok("void_application", resp)


def setup_proposed_application(event_code="SNOW-CH1", product_code="NAAC-01",
                               base_rate=30, unit_cost=12,
                               seasonal_limit=100000,
                               chemical_limit_lbs=100000,
                               budget_cents=50000000,
                               surface_code="RWY-09L", surface_type="RUNWAY",
                               length_ft=5000, width_ft=150,
                               pavement_temp_f=20):
    """ACTIVATED event + surface + product + one PROPOSED application."""
    ctx = setup_event_with_surface(
        event_code=event_code, surface_code=surface_code,
        surface_type=surface_type, length_ft=length_ft, width_ft=width_ft,
        chemical_limit_lbs=chemical_limit_lbs, budget_cents=budget_cents)
    product = create_chemical_product(product_code, base_rate, unit_cost,
                                      seasonal_limit)
    app = propose_application(ctx["event"]["id"], ctx["surface"]["id"],
                              product["id"], pavement_temp_f)
    ctx["product"] = product
    ctx["application"] = app
    return ctx


# ---------------------------------------------------------------------------
# Tier 5 — operator shifts and cost reads
# ---------------------------------------------------------------------------

def schedule_shift(event_id, operator_code="OP-01",
                   base_rate_cents_per_hour=5000,
                   start_utc="2026-08-10T08:00:00Z",
                   end_utc="2026-08-10T16:00:00Z", equipment_unit_id=None):
    payload = create_operator_shift_payload(
        event_id, operator_code=operator_code,
        base_rate_cents_per_hour=base_rate_cents_per_hour,
        start_utc=start_utc, end_utc=end_utc)
    if equipment_unit_id is not None:
        payload["equipment_unit_id"] = equipment_unit_id
    resp = api_client.create_operator_shift(payload, OPS)
    return _ok(f"schedule_shift({operator_code})", resp)


def shift_action(shift_id, action, worked_hours=None):
    payload = {"action": action}
    if worked_hours is not None:
        payload["worked_hours"] = worked_hours
    resp = api_client.shift_action(shift_id, payload, OPS)
    return _ok(f"shift_action({action})", resp)


def get_cost_summary(event_id):
    resp = api_client.get_cost_summary(event_id, OPS)
    return _ok("get_cost_summary", resp)
