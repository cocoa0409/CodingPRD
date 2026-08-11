"""Composite setup helpers.

Every helper builds its preconditions from scratch through declared endpoints:
the harness restarts the API server before each test, so no state ever carries
over and nothing is seeded.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client as api
from .test_users import (
    ACCOUNT_MANAGER,
    AUDITOR,
    DISPATCHER,
    FIELD_TECH,
    PLATFORM_ADMIN,
    STORM_COORDINATOR,
    TECH_ALPHA_ID,
    TECH_BRAVO_ID,
    make_field_tech_headers,
    make_owner_headers,
    make_vendor_headers,
)

DEFAULT_CLOCK = "2026-06-01T00:00:00Z"


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------

def set_clock(instant: str) -> dict:
    return get_success_data(api.set_clock({"to_iso8601": instant}, PLATFORM_ADMIN))


def read_clock() -> str:
    return get_success_data(api.get_clock(PLATFORM_ADMIN))["current_utc"]


# --------------------------------------------------------------------------
# Single-row creators
# --------------------------------------------------------------------------

def new_owner(**overrides) -> dict:
    return get_success_data(api.create_owner(f.create_owner_payload(**overrides), PLATFORM_ADMIN))


def new_property(owner_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_property(f.create_property_payload(owner_id, **overrides), PLATFORM_ADMIN)
    )


def new_service_plan(**overrides) -> dict:
    return get_success_data(
        api.create_service_plan(f.create_service_plan_payload(**overrides), PLATFORM_ADMIN)
    )


def new_subscription(property_id: str, plan_id: str, started_on: str = DEFAULT_CLOCK) -> dict:
    return get_success_data(
        api.create_subscription(
            f.create_subscription_payload(property_id, plan_id, started_on), ACCOUNT_MANAGER
        )
    )


def activate_subscription(subscription_id: str) -> dict:
    return get_success_data(api.activate_subscription(subscription_id, {}, ACCOUNT_MANAGER))


def new_template(visit_type: str = "ROUTINE_WATCH", **overrides) -> dict:
    return get_success_data(
        api.create_checklist_template(
            f.create_checklist_template_payload(visit_type, **overrides), PLATFORM_ADMIN
        )
    )


def new_visit(property_id: str, template_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_visit(f.create_visit_payload(property_id, template_id, **overrides), DISPATCHER)
    )


def new_vendor(**overrides) -> dict:
    return get_success_data(api.create_vendor(f.create_vendor_payload(**overrides), DISPATCHER))


def new_eligible_vendor(**overrides) -> dict:
    """Onboard a contractor and reinstate it to ELIGIBLE."""
    vendor = new_vendor(**overrides)
    return get_success_data(api.reinstate_vendor(vendor["id"], {}, DISPATCHER))


def new_key_asset(property_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_property_key_asset(
            property_id, f.create_key_asset_payload(**overrides), DISPATCHER
        )
    )


def new_rental_turnover(property_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_property_rental_turnover(
            property_id, f.create_rental_turnover_payload(**overrides), DISPATCHER
        )
    )


def new_mail_hold(property_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_property_mail_hold(
            property_id, f.create_mail_hold_payload(**overrides), DISPATCHER
        )
    )


def new_security_incident(property_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_property_security_incident(
            property_id, f.create_security_incident_payload(**overrides), DISPATCHER
        )
    )


def new_storm_event(**overrides) -> dict:
    return get_success_data(
        api.create_storm_event(f.create_storm_event_payload(**overrides), STORM_COORDINATOR)
    )


def new_winterization_record(property_id: str, **payload) -> dict:
    return get_success_data(
        api.create_property_winterization_record(property_id, dict(payload), DISPATCHER)
    )


def list_all(list_call, headers, **params) -> list:
    body = list_call(headers=headers, params=params or None)
    return get_success_data(body)


# --------------------------------------------------------------------------
# Tier 1/2: a subscribed property, the backbone of almost every scenario
# --------------------------------------------------------------------------

def setup_subscribed_property(clock: str = DEFAULT_CLOCK,
                              owner_overrides: dict = None,
                              property_overrides: dict = None,
                              plan_overrides: dict = None,
                              started_on: str = None,
                              activate: bool = True) -> dict:
    """Clock + Owner + Property + published plan + subscription (activated by default).

    Returns a context dict carrying every id the callers need, including
    owner_headers built from the real Owner row id so ownership-gated calls pass.
    """
    if clock is not None:
        set_clock(clock)
    owner = new_owner(**(owner_overrides or {}))
    prop = new_property(owner["id"], **(property_overrides or {}))
    plan = new_service_plan(**(plan_overrides or {}))
    subscription = new_subscription(prop["id"], plan["id"], started_on or clock or DEFAULT_CLOCK)
    ctx = {
        "owner": owner,
        "owner_id": owner["id"],
        "owner_headers": make_owner_headers(owner["id"]),
        "property": prop,
        "property_id": prop["id"],
        "plan": plan,
        "plan_id": plan["id"],
        "subscription": subscription,
        "subscription_id": subscription["id"],
        "cycle_id": None,
    }
    if activate:
        activated = activate_subscription(subscription["id"])
        ctx["subscription"] = activated
        ctx["cycle_id"] = activated["current_cycle_id"]
    return ctx


def refresh_property(ctx: dict) -> dict:
    return get_success_data(api.get_property(ctx["property_id"], DISPATCHER))


def refresh_cycle(cycle_id: str) -> dict:
    return get_success_data(api.get_billing_cycle(cycle_id, ACCOUNT_MANAGER))


def refresh_visit(visit_id: str) -> dict:
    return get_success_data(api.get_visit(visit_id, DISPATCHER))


def refresh_finding(finding_id: str) -> dict:
    return get_success_data(api.get_finding(finding_id, DISPATCHER))


def refresh_work_order(work_order_id: str) -> dict:
    return get_success_data(api.get_work_order(work_order_id, DISPATCHER))


def refresh_key_asset(key_asset_id: str) -> dict:
    return get_success_data(api.get_key_asset(key_asset_id, DISPATCHER))


def refresh_access_grant(grant_id: str) -> dict:
    return get_success_data(api.get_access_grant(grant_id, DISPATCHER))


def refresh_key_issuance(issuance_id: str) -> dict:
    return get_success_data(api.get_key_issuance(issuance_id, DISPATCHER))


def refresh_invoice(invoice_id: str) -> dict:
    return get_success_data(api.get_invoice(invoice_id, ACCOUNT_MANAGER))


def refresh_invoice_line(line_id: str) -> dict:
    return get_success_data(api.get_invoice_line(line_id, ACCOUNT_MANAGER))


def refresh_vendor(vendor_id: str) -> dict:
    return get_success_data(api.get_vendor(vendor_id, DISPATCHER))


def refresh_assignment(assignment_id: str) -> dict:
    return get_success_data(api.get_vendor_assignment(assignment_id, DISPATCHER))


def refresh_subscription(subscription_id: str) -> dict:
    return get_success_data(api.get_subscription(subscription_id, ACCOUNT_MANAGER))


def refresh_storm_event(storm_event_id: str) -> dict:
    return get_success_data(api.get_storm_event(storm_event_id, STORM_COORDINATOR))


def refresh_storm_response(response_id: str) -> dict:
    return get_success_data(api.get_storm_response(response_id, STORM_COORDINATOR))


def refresh_turnover(turnover_id: str) -> dict:
    return get_success_data(api.get_rental_turnover(turnover_id, DISPATCHER))


def refresh_mail_hold(mail_hold_id: str) -> dict:
    return get_success_data(api.get_mail_hold(mail_hold_id, DISPATCHER))


def refresh_incident(incident_id: str) -> dict:
    return get_success_data(api.get_security_incident(incident_id, DISPATCHER))


def refresh_winterization(record_id: str) -> dict:
    return get_success_data(api.get_winterization_record(record_id, DISPATCHER))


# --------------------------------------------------------------------------
# Tier 3: visit lifecycles
# --------------------------------------------------------------------------

def run_visit_to_in_progress(visit_id: str, arrive_clock: str = None,
                             tech_id: str = None) -> dict:
    """Depart then arrive. Optionally advance the clock first and act as a named tech."""
    headers = make_field_tech_headers(tech_id) if tech_id else FIELD_TECH
    if arrive_clock:
        set_clock(arrive_clock)
    get_success_data(api.depart_visit(visit_id, {}, headers))
    return get_success_data(api.arrive_visit(visit_id, {}, headers))


def complete_visit(visit_id: str, completed_item_codes, failed_item_codes=None,
                   interior_temp_f=None, tech_id: str = None) -> dict:
    headers = make_field_tech_headers(tech_id) if tech_id else FIELD_TECH
    payload = {
        "completed_item_codes": list(completed_item_codes),
        "failed_item_codes": list(failed_item_codes or []),
    }
    if interior_temp_f is not None:
        payload["interior_temp_f"] = interior_temp_f
    return get_success_data(api.complete_visit(visit_id, payload, headers))


def setup_completed_visit(ctx: dict = None,
                          item_codes=("EXT_WALK",),
                          critical_item_codes=(),
                          default_finding_category: str = None,
                          visit_type: str = "ROUTINE_WATCH",
                          trigger_source: str = "SCHEDULED",
                          scheduled_start_at: str = "2026-06-02T13:00:00Z",
                          scheduled_end_at: str = "2026-06-02T15:00:00Z",
                          arrive_clock: str = "2026-06-02T14:00:00Z",
                          completed_item_codes=None,
                          failed_item_codes=(),
                          interior_temp_f=None,
                          tech_id: str = None,
                          **subscribed_kwargs) -> dict:
    """A subscribed property carrying one COMPLETED visit.

    Returns the context dict extended with 'template' and 'visit'.
    """
    ctx = ctx or setup_subscribed_property(**subscribed_kwargs)
    tmpl_overrides = {
        "item_codes": list(item_codes),
        "critical_item_codes": list(critical_item_codes),
    }
    if default_finding_category is not None:
        tmpl_overrides["default_finding_category"] = default_finding_category
    template = new_template(visit_type, **tmpl_overrides)
    visit = new_visit(
        ctx["property_id"], template["id"],
        visit_type=visit_type, trigger_source=trigger_source,
        scheduled_start_at=scheduled_start_at, scheduled_end_at=scheduled_end_at,
    )
    run_visit_to_in_progress(visit["id"], arrive_clock, tech_id)
    if completed_item_codes is None:
        completed_item_codes = [c for c in item_codes if c not in (failed_item_codes or ())]
    visit = complete_visit(
        visit["id"], completed_item_codes, failed_item_codes, interior_temp_f, tech_id
    )
    ctx = dict(ctx)
    ctx["template"] = template
    ctx["template_id"] = template["id"]
    ctx["visit"] = visit
    ctx["visit_id"] = visit["id"]
    return ctx


# --------------------------------------------------------------------------
# Tier 3: findings and work orders
# --------------------------------------------------------------------------

def record_finding(visit_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_visit_finding(visit_id, f.create_finding_payload(**overrides), FIELD_TECH)
    )


def triage_finding(finding_id: str) -> dict:
    return get_success_data(api.triage_finding(finding_id, {}, DISPATCHER))


def setup_triaged_finding(ctx: dict = None, severity: str = "MEDIUM",
                          category: str = "PLUMBING", item_code: str = "EXT_WALK",
                          description: str = "Observed during the watch visit",
                          **completed_visit_kwargs) -> dict:
    """A COMPLETED visit carrying one TRIAGED finding. Adds 'finding' to the context."""
    ctx = ctx if ctx and "visit_id" in ctx else setup_completed_visit(
        ctx=ctx, **completed_visit_kwargs
    )
    finding = record_finding(
        ctx["visit_id"], item_code=item_code, severity=severity,
        category=category, description=description,
    )
    finding = triage_finding(finding["id"])
    ctx = dict(ctx)
    ctx["finding"] = finding
    ctx["finding_id"] = finding["id"]
    ctx["finding_version"] = finding["version"]
    return ctx


def create_work_order(finding_id: str, expected_finding_version: int, headers=None,
                      **overrides) -> dict:
    return get_success_data(
        api.create_finding_work_order(
            finding_id,
            f.create_work_order_payload(expected_finding_version, **overrides),
            headers or DISPATCHER,
        )
    )


def setup_work_order(ctx: dict = None, estimated_labour_hours: float = 2.0,
                     estimated_parts_cents: int = 5000, work_type: str = "REPAIR",
                     storm_event_id: str = None, headers=None,
                     **triaged_kwargs) -> dict:
    """A TRIAGED finding carrying one submitted work order. Adds 'work_order'."""
    ctx = ctx if ctx and "finding_id" in ctx else setup_triaged_finding(ctx=ctx, **triaged_kwargs)
    extra = {}
    if storm_event_id:
        extra["storm_event_id"] = storm_event_id
    work_order = create_work_order(
        ctx["finding_id"], ctx["finding_version"], headers=headers,
        work_type=work_type, estimated_labour_hours=estimated_labour_hours,
        estimated_parts_cents=estimated_parts_cents, **extra,
    )
    ctx = dict(ctx)
    ctx["work_order"] = work_order
    ctx["work_order_id"] = work_order["id"]
    return ctx


def assignment_for(work_order_id: str, vendor_id: str = None) -> dict:
    params = {"work_order_id": work_order_id}
    if vendor_id:
        params["vendor_id"] = vendor_id
    rows = get_success_data(api.list_vendor_assignments(headers=DISPATCHER, params=params))
    assert rows, f"expected an assignment on work order {work_order_id}"
    return rows[0]


def setup_dispatched_work_order(ctx: dict = None,
                                window_start_at: str = "2026-06-03T09:00:00Z",
                                window_end_at: str = "2026-06-03T17:00:00Z",
                                vendor_overrides: dict = None,
                                key_asset_overrides: dict = None,
                                with_key_asset: bool = True,
                                dispatch_headers=None,
                                **work_order_kwargs) -> dict:
    """An APPROVED work order dispatched to an ELIGIBLE vendor.

    A key asset is registered by default so the key-selection pool is non-empty and
    the dispatch chain creates its issuance and access grant.
    """
    ctx = ctx if ctx and "work_order_id" in ctx else None
    if ctx is None:
        base = work_order_kwargs.pop("ctx", None)
        ctx = setup_work_order(ctx=base, **work_order_kwargs)
    vendor = new_eligible_vendor(**(vendor_overrides or {}))
    if with_key_asset:
        key_asset = new_key_asset(ctx["property_id"], **(key_asset_overrides or {}))
    else:
        key_asset = None
    get_success_data(
        api.dispatch_work_order(
            ctx["work_order_id"],
            {"window_start_at": window_start_at, "window_end_at": window_end_at},
            dispatch_headers or DISPATCHER,
        )
    )
    assignment = assignment_for(ctx["work_order_id"], vendor["id"])
    ctx = dict(ctx)
    ctx["vendor"] = vendor
    ctx["vendor_id"] = vendor["id"]
    ctx["vendor_headers"] = make_vendor_headers(vendor["id"])
    ctx["key_asset"] = key_asset
    ctx["key_asset_id"] = key_asset["id"] if key_asset else None
    ctx["assignment"] = assignment
    ctx["assignment_id"] = assignment["id"]
    return ctx


def run_assignment_to_finished(ctx: dict, start_clock: str = None) -> dict:
    """Accept, start on site and finish the assignment held in the context.

    `start_clock` moves the logical clock inside the on-site window before the vendor
    starts, because starting work requires the clock to lie inside the access grant's
    window.
    """
    headers = ctx["vendor_headers"]
    get_success_data(api.accept_vendor_assignment(ctx["assignment_id"], {}, headers))
    if start_clock:
        set_clock(start_clock)
    get_success_data(api.start_work_vendor_assignment(ctx["assignment_id"], {}, headers))
    return get_success_data(api.finish_work_vendor_assignment(ctx["assignment_id"], {}, headers))


def setup_completed_work_order(ctx: dict = None, actual_labour_hours: float = 2.0,
                               actual_parts_cents: int = 5000, start_clock: str = None,
                               **dispatch_kwargs) -> dict:
    """A work order carried all the way to COMPLETED with actuals recorded."""
    ctx = ctx if ctx and "assignment_id" in ctx else setup_dispatched_work_order(
        ctx=ctx, **dispatch_kwargs
    )
    run_assignment_to_finished(ctx, start_clock)
    work_order = get_success_data(
        api.complete_work_order(
            ctx["work_order_id"],
            {"actual_labour_hours": actual_labour_hours, "actual_parts_cents": actual_parts_cents},
            ctx["vendor_headers"],
        )
    )
    ctx = dict(ctx)
    ctx["work_order"] = work_order
    return ctx


# --------------------------------------------------------------------------
# Tier 4: invoices
# --------------------------------------------------------------------------

def open_draft_invoice(cycle_id: str) -> dict:
    return get_success_data(api.create_billing_cycle_invoice(cycle_id, {}, ACCOUNT_MANAGER))


def append_line(invoice_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_invoice_invoice_line(
            invoice_id, f.create_invoice_line_payload(**overrides), ACCOUNT_MANAGER
        )
    )


def lines_of(invoice_id: str) -> list:
    return get_success_data(
        api.list_invoice_lines(headers=ACCOUNT_MANAGER, params={"invoice_id": invoice_id})
    )


def setup_draft_invoice(ctx: dict = None, **subscribed_kwargs) -> dict:
    """A subscribed property with a DRAFT invoice seeded with its subscription-fee line."""
    ctx = ctx or setup_subscribed_property(**subscribed_kwargs)
    invoice = open_draft_invoice(ctx["cycle_id"])
    ctx = dict(ctx)
    ctx["invoice"] = invoice
    ctx["invoice_id"] = invoice["id"]
    return ctx


def setup_issued_invoice(ctx: dict = None, **subscribed_kwargs) -> dict:
    ctx = ctx if ctx and "invoice_id" in ctx else setup_draft_invoice(ctx=ctx, **subscribed_kwargs)
    invoice = get_success_data(api.issue_invoice(ctx["invoice_id"], {}, ACCOUNT_MANAGER))
    ctx = dict(ctx)
    ctx["invoice"] = invoice
    return ctx


# --------------------------------------------------------------------------
# Tier 4: seasonal and winterization
# --------------------------------------------------------------------------

def seasonal(property_id: str, action: str, headers=None):
    return api.create_property_seasonal_transition(
        property_id, {"action": action}, headers or DISPATCHER
    )


def run_seasonal(property_id: str, action: str, headers=None) -> dict:
    return get_success_data(seasonal(property_id, action, headers))


def occupancy(property_id: str, to_state: str, headers=None):
    return api.create_property_occupancy_transition(
        property_id, {"to_state": to_state}, headers or DISPATCHER
    )


def run_occupancy(property_id: str, to_state: str, headers=None) -> dict:
    return get_success_data(occupancy(property_id, to_state, headers))


def winterization_record_of(property_id: str) -> dict:
    rows = get_success_data(
        api.list_winterization_records(headers=DISPATCHER, params={"property_id": property_id})
    )
    assert rows, f"expected a winterization record on property {property_id}"
    return rows[-1]


def record_step(record_id: str, step_code: str, thermostat_f=None) -> dict:
    payload = {"step_code": step_code}
    if thermostat_f is not None:
        payload["thermostat_f"] = thermostat_f
    return get_success_data(api.steps_winterization_record(record_id, payload, FIELD_TECH))


def setup_winterized_property(clock: str = "2026-10-01T00:00:00Z",
                              property_overrides: dict = None) -> dict:
    """Owner + property closed and fully winterized, leaving seasonal_state WINTERIZED."""
    set_clock(clock)
    owner = new_owner()
    prop = new_property(owner["id"], **(property_overrides or {"travel_distance_miles": 5.0}))
    run_seasonal(prop["id"], "BEGIN_CLOSE")
    record = winterization_record_of(prop["id"])
    record_step(record["id"], "ALL_REQUIRED", thermostat_f=55)
    prop = run_seasonal(prop["id"], "COMPLETE_WINTERIZATION")
    return {
        "owner": owner,
        "owner_id": owner["id"],
        "owner_headers": make_owner_headers(owner["id"]),
        "property": prop,
        "property_id": prop["id"],
        "winterization_record": record,
        "winterization_record_id": record["id"],
    }


# --------------------------------------------------------------------------
# Tier 5: the storm pipeline
# --------------------------------------------------------------------------

def advisory(storm_event_id: str, to_status: str) -> dict:
    return get_success_data(
        api.advisory_storm_event(storm_event_id, {"to_status": to_status}, STORM_COORDINATOR)
    )


def raise_storm_to_imminent(storm_event_id: str) -> dict:
    advisory(storm_event_id, "WATCH")
    advisory(storm_event_id, "WARNING")
    return advisory(storm_event_id, "IMMINENT")


def enrol_storm_response(storm_event_id: str, property_id: str) -> dict:
    return get_success_data(
        api.create_storm_event_storm_response(
            storm_event_id, {"property_id": property_id}, STORM_COORDINATOR
        )
    )


def schedule_sweep(response_id: str, template_id: str, scheduled_start_at: str) -> dict:
    return get_success_data(
        api.schedule_sweep_storm_response(
            response_id,
            {"checklist_template_id": template_id, "scheduled_start_at": scheduled_start_at},
            STORM_COORDINATOR,
        )
    )


def setup_storm_response_assessment_due(clock: str = "2026-06-04T18:00:00Z",
                                        landfall_eta_at: str = "2026-06-05T00:00:00Z",
                                        sweep_start: str = "2026-06-04T18:30:00Z",
                                        sweep_clock: str = "2026-06-04T19:00:00Z",
                                        landfall_clock: str = "2026-06-05T01:00:00Z",
                                        all_clear_clock: str = "2026-06-05T06:00:00Z",
                                        sweep_tech_id: str = TECH_ALPHA_ID,
                                        plan_overrides: dict = None,
                                        property_overrides: dict = None,
                                        started_on: str = "2026-06-01T00:00:00Z") -> dict:
    """A FL storm swept on time, landfall recorded and all-clear declared, leaving
    the response in ASSESSMENT_DUE and the sweep signed by `sweep_tech_id`."""
    plan_overrides = plan_overrides or {
        "tier": "PREMIUM", "monthly_fee_cents": 34944, "included_visit_units": 8,
        "covered_visit_types": ["ROUTINE_WATCH"], "storm_guarantee_included": True,
    }
    ctx = setup_subscribed_property(
        clock=clock, plan_overrides=plan_overrides,
        property_overrides=property_overrides, started_on=started_on,
    )
    secure_template = new_template("STORM_SECURE", item_codes=["SHUTTERS"], critical_item_codes=[])
    storm = new_storm_event(name="Hurricane Test", region_state_code="FL",
                            landfall_eta_at=landfall_eta_at)
    raise_storm_to_imminent(storm["id"])
    response = enrol_storm_response(storm["id"], ctx["property_id"])
    response = schedule_sweep(response["id"], secure_template["id"], sweep_start)
    sweep_visit_id = response["secure_sweep_visit_id"]
    run_visit_to_in_progress(sweep_visit_id, sweep_clock, sweep_tech_id)
    complete_visit(sweep_visit_id, ["SHUTTERS"], [], tech_id=sweep_tech_id)
    set_clock(landfall_clock)
    get_success_data(api.landfall_storm_event(storm["id"], {}, STORM_COORDINATOR))
    set_clock(all_clear_clock)
    storm = get_success_data(api.all_clear_storm_event(storm["id"], {}, STORM_COORDINATOR))
    response = refresh_storm_response(response["id"])
    ctx = dict(ctx)
    ctx["secure_template"] = secure_template
    ctx["storm_event"] = storm
    ctx["storm_event_id"] = storm["id"]
    ctx["storm_response"] = response
    ctx["storm_response_id"] = response["id"]
    ctx["sweep_visit_id"] = sweep_visit_id
    ctx["sweep_tech_id"] = sweep_tech_id
    return ctx


# --------------------------------------------------------------------------
# Tier 5: security incidents
# --------------------------------------------------------------------------

def setup_investigating_incident(property_id: str, incident_type: str = "ALARM_INTRUSION",
                                 severity: str = "LOW", investigate_payload: dict = None) -> dict:
    incident = new_security_incident(property_id, incident_type=incident_type, severity=severity)
    get_success_data(api.acknowledge_security_incident(incident["id"], {}, DISPATCHER))
    return get_success_data(
        api.investigate_security_incident(incident["id"], investigate_payload or {}, DISPATCHER)
    )


def reclassify_false_alarm(incident_id: str, resolution_note: str = "Reclassified") -> dict:
    return get_success_data(
        api.reclassify_false_alarm_security_incident(
            incident_id, {"resolution_note": resolution_note}, DISPATCHER
        )
    )


def run_false_alarm_cycle(property_id: str, clock: str, note: str = "Reclassified") -> dict:
    """Report, acknowledge, investigate and reclassify one alarm incident."""
    set_clock(clock)
    incident = setup_investigating_incident(property_id)
    return reclassify_false_alarm(incident["id"], note)


# --------------------------------------------------------------------------
# Tier 5: mail holds
# --------------------------------------------------------------------------

def log_packages(mail_hold_id: str, delta: int) -> dict:
    return get_success_data(
        api.log_packages_mail_hold(mail_hold_id, {"package_delta": delta}, FIELD_TECH)
    )


def setup_active_mail_hold(property_id: str = None, ctx: dict = None, **hold_overrides) -> dict:
    """A mail hold moved from REQUESTED to ACTIVE by a zero-delta package log."""
    assert property_id or ctx, "need a property"
    property_id = property_id or ctx["property_id"]
    hold = new_mail_hold(property_id, **hold_overrides)
    hold = log_packages(hold["id"], 0)
    return hold


# --------------------------------------------------------------------------
# Tier 5: keys and access grants
# --------------------------------------------------------------------------

def issue_key(key_asset_id: str, vendor_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_key_asset_key_issuance(
            key_asset_id, f.create_key_issuance_payload(vendor_id, **overrides), DISPATCHER
        )
    )


def create_grant(key_asset_id: str, vendor_id: str, window_start_at: str, window_end_at: str,
                 expected_key_asset_version: int, **overrides) -> dict:
    return get_success_data(
        api.create_key_asset_access_grant(
            key_asset_id,
            f.create_access_grant_payload(
                vendor_id, window_start_at, window_end_at, expected_key_asset_version, **overrides
            ),
            DISPATCHER,
        )
    )


def activate_grant(grant_id: str) -> dict:
    return get_success_data(api.activate_access_grant(grant_id, {}, DISPATCHER))
