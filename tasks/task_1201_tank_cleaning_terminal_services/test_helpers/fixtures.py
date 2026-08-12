"""Composite setup helpers for multi-step test prerequisites (PRD §3 workflows).

Every helper builds its preconditions from scratch via the public API (the
harness restarts the server before each test, so nothing carries over).
Setup calls use get_success_data() so failures surface as clear setup errors.

A "ctx" is a plain dict carrying the entities of one scenario:
  terminal, gas, dist, tank, contractor, job, window, profile, shipments,
  cert, permit, inspector, inspection, findings.
Chain helpers mutate and return the ctx so tests can read ctx["job"]["id"].
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START
from .factories import (
    DEFAULTS,
    create_terminal_payload, create_product_payload, create_tank_payload,
    create_contractor_payload, create_safety_event_payload,
    create_cleaning_job_payload, create_service_window_payload,
    create_waste_profile_payload, create_waste_shipment_payload,
    create_gas_free_certificate_payload, create_entry_permit_payload,
    create_inspector_payload, create_inspection_payload,
    create_inspection_finding_payload, create_repair_order_payload,
    create_wastewater_batch_payload, submit_lab_payload,
)
from .test_users import (
    TEST_USERS, make_contractor_supervisor_headers, make_inspector_headers,
)

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["operator_headers"]
OPERATOR2 = TEST_USERS["operator2_headers"]
CHEMIST = TEST_USERS["chemist_headers"]
EHS = TEST_USERS["ehs_headers"]
EHS2 = TEST_USERS["ehs2_headers"]
LAB = TEST_USERS["lab_headers"]


def parse_ts(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (accepts trailing Z)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc)


# ---------------------------------------------------------------------------
# Tier 1: base landscape (clock, terminal, products, tank, contractor)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=CLOCK_START):
    """Drive the logical clock (TerminalAdmin-only test capability)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_terminal(**overrides):
    payload = create_terminal_payload(**overrides)
    return get_success_data(api_client.create_terminal(payload, ADMIN))


def create_product(**overrides):
    payload = create_product_payload(**overrides)
    return get_success_data(api_client.create_product(payload, ADMIN))


def create_tank(terminal_id, current_product_id, **overrides):
    payload = create_tank_payload(terminal_id, current_product_id, **overrides)
    return get_success_data(api_client.create_tank(payload, ADMIN))


def create_contractor(**overrides):
    payload = create_contractor_payload(**overrides)
    return get_success_data(api_client.create_contractor(payload, ADMIN))


def qualify_contractor(contractor_id, terminal_id):
    return get_success_data(api_client.qualify_contractor(
        contractor_id, {"terminal_id": terminal_id}, ADMIN))


def record_safety_event(contractor_id, kind, severity_weight, occurred_at):
    payload = create_safety_event_payload(
        contractor_id, kind=kind, severity_weight=severity_weight,
        occurred_at=occurred_at)
    return get_success_data(api_client.create_safety_event(payload, EHS))


def new_ctx(terminal_overrides=None, tank_overrides=None, qualify=True,
            clock=CLOCK_START):
    """Clock + terminal + GAS89/DSL10 products + tank + (qualified) contractor."""
    if clock is not None:
        set_clock(clock)
    terminal = create_terminal(**(terminal_overrides or {}))
    gas = create_product(code="GAS89", family="GASOLINE", viscosity_class="LOW",
                         compatibility_group="GAS", flash_point_c=-40)
    dist = create_product(code="DSL10", family="DISTILLATE",
                          viscosity_class="MEDIUM", compatibility_group="DIST",
                          flash_point_c=55)
    tank = create_tank(terminal["id"], gas["id"], **(tank_overrides or {}))
    contractor = create_contractor()
    if qualify:
        qualify_contractor(contractor["id"], terminal["id"])
    return {
        "terminal": terminal, "gas": gas, "dist": dist, "tank": tank,
        "contractor": contractor,
    }


def contractor_headers(ctx) -> dict:
    return make_contractor_supervisor_headers(ctx["contractor"]["id"])


def inspector_headers(ctx) -> dict:
    return make_inspector_headers(ctx["inspector"]["id"])


def fresh_tank_version(tank_id) -> int:
    return get_success_data(api_client.get_tank(tank_id, OPERATOR))["version"]


def fresh_inspector_version(inspector_id) -> int:
    return get_success_data(
        api_client.get_inspector(inspector_id, OPERATOR))["version"]


def get_job(ctx):
    return get_success_data(
        api_client.get_cleaning_job(ctx["job"]["id"], OPERATOR))


# ---------------------------------------------------------------------------
# Tier 2/3: cleaning-job lifecycle chain
# ---------------------------------------------------------------------------

def add_tank(ctx, tank_number, capacity_m3=5000, product_key="gas"):
    tank = create_tank(ctx["terminal"]["id"], ctx[product_key]["id"],
                       tank_number=tank_number, capacity_m3=capacity_m3)
    return tank


def create_job(ctx, tank=None, from_key="gas", to_key="dist", **overrides):
    """Create a DRAFT cleaning job on ctx's tank (or the given one).

    from_product_id / to_product_id may be given explicitly in overrides;
    they win over the from_key/to_key product lookups.
    """
    tank = tank or ctx["tank"]
    from_product_id = overrides.pop("from_product_id", ctx[from_key]["id"])
    to_product_id = overrides.pop("to_product_id", ctx[to_key]["id"])
    payload = create_cleaning_job_payload(
        ctx["terminal"]["id"], tank["id"], ctx["contractor"]["id"],
        from_product_id, to_product_id, **overrides)
    job = get_success_data(api_client.create_cleaning_job(payload, OPERATOR))
    ctx["job"] = job
    return job


def schedule_job(ctx, window_start=None, window_end=None):
    """Book a PLANNED window on the job's tank (fresh OCC version) + schedule."""
    job = ctx["job"]
    tank_id = job["tank_id"]
    payload = create_service_window_payload(
        tank_id, fresh_tank_version(tank_id),
        **({"planned_start": window_start} if window_start else {}),
        **({"planned_end": window_end} if window_end else {}))
    window = get_success_data(api_client.create_service_window(payload, OPERATOR))
    ctx["window"] = window
    ctx["job"] = get_success_data(api_client.schedule_job(
        job["id"], {"window_id": window["id"]}, OPERATOR))
    return ctx["job"]


def activate_window_and_take_oos(ctx, at=DEFAULTS["WINDOW_ACTIVE_AT"]):
    """Advance the clock inside the window, activate it, take the tank OOS."""
    set_clock(at)
    get_success_data(api_client.activate_window(ctx["window"]["id"], OPERATOR))
    ctx["job"] = get_success_data(
        api_client.take_out_of_service(ctx["job"]["id"], OPERATOR))
    return ctx["job"]


def record_heel(ctx, metered_liters=2100):
    ctx["job"] = get_success_data(api_client.record_heel_removal(
        ctx["job"]["id"], {"metered_liters": metered_liters},
        contractor_headers(ctx)))
    return ctx["job"]


def create_approved_profile(ctx, **overrides):
    profile = get_success_data(api_client.create_waste_profile(
        create_waste_profile_payload(ctx["job"]["id"], **overrides),
        contractor_headers(ctx)))
    get_success_data(api_client.submit_waste_profile(
        profile["id"], contractor_headers(ctx)))
    profile = get_success_data(api_client.approve_waste_profile(profile["id"], EHS))
    ctx["profile"] = profile
    return profile


def add_shipment(ctx, lines, dispatch=True, deliver=True, reconcile=False):
    """Book a shipment against ctx's approved profile; walk it down the conveyor."""
    shipment = get_success_data(api_client.create_waste_shipment(
        create_waste_shipment_payload(ctx["job"]["id"], ctx["profile"]["id"],
                                      lines=lines),
        contractor_headers(ctx)))
    if dispatch:
        get_success_data(api_client.dispatch_shipment(
            shipment["id"], contractor_headers(ctx)))
    if deliver:
        get_success_data(api_client.deliver_shipment(
            shipment["id"], contractor_headers(ctx)))
    if reconcile:
        shipment = get_success_data(
            api_client.reconcile_shipment(shipment["id"], EHS))
    ctx.setdefault("shipments", []).append(shipment)
    return shipment


def record_sludge(ctx, residual_sludge_kg=0):
    ctx["job"] = get_success_data(api_client.record_sludge_removal(
        ctx["job"]["id"], {"residual_sludge_kg": residual_sludge_kg},
        contractor_headers(ctx)))
    return ctx["job"]


def request_gas_free(ctx):
    ctx["job"] = get_success_data(
        api_client.request_gas_free(ctx["job"]["id"], contractor_headers(ctx)))
    return ctx["job"]


def issue_certificate(ctx, chemist=None, **reading_overrides):
    chemist = chemist or CHEMIST
    cert = get_success_data(api_client.create_gas_free_certificate(
        create_gas_free_certificate_payload(ctx["job"]["id"],
                                            **reading_overrides), chemist))
    ctx["cert"] = cert
    ctx["job"] = get_job(ctx)
    return cert


def add_permit(ctx, issue=True, activate=False, issue_headers=None,
               max_entrants=4):
    permit = get_success_data(api_client.create_entry_permit(
        create_entry_permit_payload(ctx["job"]["id"], ctx["cert"]["id"],
                                    max_entrants=max_entrants),
        contractor_headers(ctx)))
    if issue:
        permit = get_success_data(
            api_client.issue_permit(permit["id"], issue_headers or EHS))
    if activate:
        permit = get_success_data(
            api_client.activate_permit(permit["id"], contractor_headers(ctx)))
    ctx["permit"] = permit
    return permit


def begin_entry(ctx):
    ctx["job"] = get_success_data(
        api_client.begin_entry(ctx["job"]["id"], contractor_headers(ctx)))
    return ctx["job"]


def complete_entry(ctx):
    """Close the ctx permit, then complete the entry phase."""
    get_success_data(
        api_client.close_permit(ctx["permit"]["id"], contractor_headers(ctx)))
    ctx["permit"] = get_success_data(
        api_client.get_entry_permit(ctx["permit"]["id"], OPERATOR))
    ctx["job"] = get_success_data(
        api_client.complete_entry(ctx["job"]["id"], contractor_headers(ctx)))
    return ctx["job"]


def add_inspector(ctx, name="InspA", certification_level="API653"):
    ctx["inspector"] = get_success_data(api_client.create_inspector(
        create_inspector_payload(name=name,
                                 certification_level=certification_level),
        ADMIN))
    return ctx["inspector"]


def create_inspection(ctx, scheduled_start="2026-05-03T00:00:00Z",
                      scheduled_end="2026-05-03T08:00:00Z"):
    """Book an inspection with a fresh OCC inspector version."""
    inspector = ctx["inspector"]
    payload = create_inspection_payload(
        ctx["job"]["id"], inspector["id"], fresh_inspector_version(inspector["id"]),
        scheduled_start=scheduled_start, scheduled_end=scheduled_end)
    ctx["inspection"] = get_success_data(
        api_client.create_inspection(payload, OPERATOR))
    return ctx["inspection"]


def run_inspection(ctx, findings=None, accept=True, accept_headers=None):
    """start -> record findings -> report (-> accept). Returns the inspection."""
    inspection = ctx["inspection"]
    get_success_data(
        api_client.start_inspection(inspection["id"], inspector_headers(ctx)))
    ctx["findings"] = []
    for f in (findings or []):
        finding = get_success_data(api_client.create_inspection_finding(
            create_inspection_finding_payload(inspection["id"], **f),
            inspector_headers(ctx)))
        ctx["findings"].append(finding)
    inspection = get_success_data(
        api_client.report_inspection(inspection["id"], inspector_headers(ctx)))
    ctx["inspection"] = inspection
    if accept:
        ctx["inspection"] = get_success_data(api_client.accept_inspection(
            inspection["id"], accept_headers or OPERATOR))
        ctx["job"] = get_job(ctx)
    return ctx["inspection"]


def begin_and_verify_flush(ctx, actual_flush_liters=None):
    job = ctx["job"]
    get_success_data(api_client.begin_flush(job["id"], contractor_headers(ctx)))
    actual = actual_flush_liters
    if actual is None:
        actual = get_job(ctx)["flush_volume_liters"]
    ctx["job"] = get_success_data(api_client.verify_flush(
        job["id"], {"actual_flush_liters": actual}, EHS))
    return ctx["job"]


def request_rts(ctx):
    ctx["job"] = get_success_data(api_client.request_rts(ctx["job"]["id"], OPERATOR))
    return ctx["job"]


# ---------------------------------------------------------------------------
# Composite lifecycle stages (each returns ctx)
# ---------------------------------------------------------------------------

def setup_ctx_scheduled(ctx=None, **job_overrides):
    """Base landscape + DRAFT job + SCHEDULED against a PLANNED window."""
    ctx = ctx or new_ctx()
    create_job(ctx, **job_overrides)
    schedule_job(ctx)
    return ctx


def setup_ctx_tank_oos(ctx=None, **job_overrides):
    ctx = setup_ctx_scheduled(ctx, **job_overrides)
    activate_window_and_take_oos(ctx)
    return ctx


def setup_ctx_heel_removed(ctx=None, metered_liters=2100, **job_overrides):
    ctx = setup_ctx_tank_oos(ctx, **job_overrides)
    record_heel(ctx, metered_liters)
    return ctx


def setup_ctx_sludge_removed(ctx=None, metered_liters=2100,
                             residual_sludge_kg=0, shipment_lines=None,
                             reconcile=False, profile_overrides=None,
                             **job_overrides):
    """Through SLUDGE_REMOVED with an APPROVED profile + one shipment."""
    ctx = setup_ctx_heel_removed(ctx, metered_liters, **job_overrides)
    create_approved_profile(ctx, **(profile_overrides or {}))
    add_shipment(ctx, shipment_lines
                 or [{"material": "SLUDGE", "kg": 2542,
                      "rate_cents_per_kg": 2.0}],
                 reconcile=reconcile)
    record_sludge(ctx, residual_sludge_kg)
    return ctx


def setup_ctx_gas_free_pending(ctx=None, **kwargs):
    ctx = setup_ctx_sludge_removed(ctx, **kwargs)
    request_gas_free(ctx)
    return ctx


def setup_ctx_gas_free_certified(ctx=None, **kwargs):
    ctx = setup_ctx_gas_free_pending(ctx, **kwargs)
    issue_certificate(ctx)
    return ctx


def setup_ctx_entry_in_progress(ctx=None, **kwargs):
    """Through ENTRY_IN_PROGRESS with one ACTIVE permit."""
    ctx = setup_ctx_gas_free_certified(ctx, **kwargs)
    add_permit(ctx, issue=True, activate=True)
    begin_entry(ctx)
    return ctx


def setup_ctx_entry_complete(ctx=None, **kwargs):
    ctx = setup_ctx_entry_in_progress(ctx, **kwargs)
    complete_entry(ctx)
    return ctx


def setup_ctx_inspection_accepted(ctx=None, findings=None, **kwargs):
    """Through INSPECTION_ACCEPTED (findings: list of finding overrides)."""
    ctx = setup_ctx_entry_complete(ctx, **kwargs)
    add_inspector(ctx)
    create_inspection(ctx)
    run_inspection(ctx, findings=findings, accept=True)
    return ctx


def setup_ctx_flush_verified(ctx=None, actual_flush_liters=None, **kwargs):
    ctx = setup_ctx_inspection_accepted(ctx, **kwargs)
    begin_and_verify_flush(ctx, actual_flush_liters)
    return ctx


def setup_ctx_rts_pending(ctx=None, **kwargs):
    ctx = setup_ctx_flush_verified(ctx, **kwargs)
    request_rts(ctx)
    return ctx


# ---------------------------------------------------------------------------
# Wastewater helpers
# ---------------------------------------------------------------------------

def add_wastewater_batch(ctx, volume_liters, lab_headers=None, ph=7.0,
                         tph_mg_l=5.0, authorize=False, authorize_headers=None):
    batch = get_success_data(api_client.create_wastewater_batch(
        create_wastewater_batch_payload(ctx["terminal"]["id"], ctx["job"]["id"],
                                        volume_liters=volume_liters),
        OPERATOR))
    batch = get_success_data(api_client.submit_lab_results(
        batch["id"], submit_lab_payload(ph=ph, tph_mg_l=tph_mg_l),
        lab_headers or LAB))
    if authorize:
        batch = get_success_data(api_client.authorize_batch(
            batch["id"], authorize_headers or OPERATOR))
    return batch
