"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only: the harness restarts the server before each test, so each test
starts against an empty database.

Setup calls use the lenient `get_success_data` validator so a broken
precondition surfaces as a clear "Setup step failed" message.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import TEST_DEFAULTS
from .factories import (
    create_critical_crane_payload,
    create_customer_payload,
    create_engineer_payload,
    create_gear_assignment_payload,
    create_gear_inspection_payload,
    create_lift_plan_payload,
    create_load_chart_entry_payload,
    create_operator_payload,
    create_rigger_payload,
    create_rigging_gear_payload,
    create_site_payload,
    create_standard_crane_payload,
    site_survey_payload,
)
from .test_users import (
    BILLING_CLERK,
    DISPATCHER,
    LIFT_DIRECTOR,
    SAFETY_MANAGER,
    make_engineer_headers,
    make_operator_headers,
)


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> dict:
    """Move the server's logical UTC clock."""
    return get_success_data(api.set_clock(to_iso8601, DISPATCHER))


def new_customer(**overrides) -> dict:
    return get_success_data(api.create_customer(create_customer_payload(**overrides), DISPATCHER))


def new_site(customer_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_site(create_site_payload(customer_id, **overrides), DISPATCHER)
    )


def new_standard_crane(**overrides) -> dict:
    return get_success_data(
        api.create_crane(create_standard_crane_payload(**overrides), DISPATCHER)
    )


def new_critical_crane(**overrides) -> dict:
    return get_success_data(
        api.create_crane(create_critical_crane_payload(**overrides), DISPATCHER)
    )


def new_chart_row(crane_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_load_chart_entry(create_load_chart_entry_payload(crane_id, **overrides),
                                    DISPATCHER)
    )


def new_operator(**overrides) -> dict:
    return get_success_data(api.create_personnel(create_operator_payload(**overrides), DISPATCHER))


def new_rigger(**overrides) -> dict:
    return get_success_data(api.create_personnel(create_rigger_payload(**overrides), DISPATCHER))


def new_engineer(**overrides) -> dict:
    return get_success_data(api.create_personnel(create_engineer_payload(**overrides), DISPATCHER))


def new_gear(**overrides) -> dict:
    return get_success_data(
        api.create_rigging_gear(create_rigging_gear_payload(**overrides), SAFETY_MANAGER)
    )


def inspect_gear(gear_id: str, result: str = "PASS", note: str = "acceptance") -> dict:
    return get_success_data(
        api.create_gear_inspection(
            create_gear_inspection_payload(gear_id, result=result, inspector_note=note),
            SAFETY_MANAGER,
        )
    )


def read_gear(gear_id: str) -> dict:
    return get_success_data(api.get_rigging_gear(gear_id, DISPATCHER))


def gear_version(gear_id: str) -> int:
    return read_gear(gear_id)["version"]


def new_serviceable_gear(**overrides) -> dict:
    """Register a piece of gear and take it through the acceptance inspection
    that moves it out of DUE_INSPECTION."""
    gear = new_gear(**overrides)
    inspect_gear(gear["id"], "PASS")
    return read_gear(gear["id"])


def read_plan(plan_id: str) -> dict:
    return get_success_data(api.get_lift_plan(plan_id, DISPATCHER))


def read_crane(crane_id: str) -> dict:
    return get_success_data(api.get_crane(crane_id, DISPATCHER))


def read_personnel(personnel_id: str) -> dict:
    return get_success_data(api.get_personnel(personnel_id, DISPATCHER))


def read_customer(customer_id: str) -> dict:
    return get_success_data(api.get_customer(customer_id, BILLING_CLERK))


def read_assignment(assignment_id: str) -> dict:
    return get_success_data(api.get_gear_assignment(assignment_id, DISPATCHER))


def read_review(review_id: str) -> dict:
    return get_success_data(api.get_engineering_review(review_id, DISPATCHER))


def read_permit(permit_id: str) -> dict:
    return get_success_data(api.get_permit(permit_id, DISPATCHER))


def read_invoice(invoice_id: str) -> dict:
    return get_success_data(api.get_invoice(invoice_id, BILLING_CLERK))


# ---------------------------------------------------------------------------
# Tier 2: whole-world builders
#
# Two canonical worlds recur across the suite.  The "standard" world is a
# 150 ton machine whose jobs classify STANDARD and need no permit; the
# "critical" world is a 275 ton machine whose jobs classify CRITICAL and draw
# an escort, and it additionally registers the two engineers a review needs.
# ---------------------------------------------------------------------------
def build_standard_world(
    *,
    customer=None,
    site=None,
    crane=None,
    chart_rows=None,
    operator=None,
    rigger=None,
    gear=None,
    with_engineers=False,
    serviceable_gear=True,
) -> dict:
    """Customer + site + 150 ton crane + one chart row + crew + one sling."""
    customer_row = new_customer(**(customer or {"account_name": "Harborline Fabricators"}))
    site_defaults = {
        "address_label": "Pier 9 Yard",
        "jurisdiction_code": TEST_DEFAULTS["STD_JURISDICTION"],
        "soil_bearing_capacity_psf": TEST_DEFAULTS["STD_SOIL_PSF"],
    }
    site_defaults.update(site or {})
    site_row = new_site(customer_row["id"], **site_defaults)

    crane_row = new_standard_crane(**(crane or {}))
    rows = chart_rows if chart_rows is not None else [{}]
    chart = [new_chart_row(crane_row["id"], **row) for row in rows]

    operator_row = new_operator(**(operator or {}))
    rigger_row = new_rigger(**(rigger or {}))

    gear_overrides = dict(gear or {})
    if serviceable_gear:
        gear_row = new_serviceable_gear(**gear_overrides)
    else:
        gear_row = new_gear(**gear_overrides)

    world = {
        "profile": "standard",
        "customer": customer_row,
        "cust_id": customer_row["id"],
        "site": site_row,
        "site_id": site_row["id"],
        "crane": crane_row,
        "crane_id": crane_row["id"],
        "chart_rows": chart,
        "operator": operator_row,
        "op_id": operator_row["id"],
        "rigger": rigger_row,
        "rig_id": rigger_row["id"],
        "gear": gear_row,
        "gear_id": gear_row["id"],
        "gear_version": gear_row["version"],
        "soil_psf": site_defaults["soil_bearing_capacity_psf"],
        "jurisdiction_code": site_defaults["jurisdiction_code"],
        "boom_length_ft": TEST_DEFAULTS["STD_BOOM_LENGTH_FT"],
        "radius_ft": TEST_DEFAULTS["STD_RADIUS_FT"],
        "load_weight_lb": TEST_DEFAULTS["STD_LOAD_WEIGHT_LB"],
    }
    if with_engineers:
        _add_engineers(world)
    return world


def build_critical_world(
    *,
    customer=None,
    site=None,
    crane=None,
    chart_rows=None,
    operator=None,
    rigger=None,
    gear=None,
    with_engineers=True,
    serviceable_gear=True,
) -> dict:
    """Customer + site + 275 ton crane + chart row + crew + one sling + engineers."""
    customer_row = new_customer(**(customer or {"account_name": "Northgate Industrial"}))
    site_defaults = {
        "address_label": "Bergen Plant 4",
        "jurisdiction_code": TEST_DEFAULTS["CRIT_JURISDICTION"],
        "soil_bearing_capacity_psf": TEST_DEFAULTS["CRIT_SOIL_PSF"],
        "proximity_to_energized_lines_ft": 45,
        "over_water": False,
    }
    site_defaults.update(site or {})
    site_row = new_site(customer_row["id"], **site_defaults)

    crane_row = new_critical_crane(**(crane or {}))
    default_row = {
        "boom_length_ft": TEST_DEFAULTS["CRIT_BOOM_LENGTH_FT"],
        "radius_ft": TEST_DEFAULTS["CRIT_RADIUS_FT"],
        "gross_capacity_lb": TEST_DEFAULTS["STD_CHART_CAPACITY_LB"],
    }
    rows = chart_rows if chart_rows is not None else [default_row]
    chart = [new_chart_row(crane_row["id"], **{**default_row, **row}) for row in rows]

    operator_row = new_operator(**({"endorsement_class_tons": 300, **(operator or {})}))
    rigger_row = new_rigger(**({"rigger_level": "ADVANCED", **(rigger or {})}))

    gear_defaults = {"gear_tag": "SL-4001", "rated_wll_lb": 25_000}
    gear_defaults.update(gear or {})
    if serviceable_gear:
        gear_row = new_serviceable_gear(**gear_defaults)
    else:
        gear_row = new_gear(**gear_defaults)

    world = {
        "profile": "critical",
        "customer": customer_row,
        "cust_id": customer_row["id"],
        "site": site_row,
        "site_id": site_row["id"],
        "crane": crane_row,
        "crane_id": crane_row["id"],
        "chart_rows": chart,
        "operator": operator_row,
        "op_id": operator_row["id"],
        "rigger": rigger_row,
        "rig_id": rigger_row["id"],
        "gear": gear_row,
        "gear_id": gear_row["id"],
        "gear_version": gear_row["version"],
        "soil_psf": site_defaults["soil_bearing_capacity_psf"],
        "jurisdiction_code": site_defaults["jurisdiction_code"],
        "boom_length_ft": TEST_DEFAULTS["CRIT_BOOM_LENGTH_FT"],
        "radius_ft": TEST_DEFAULTS["CRIT_RADIUS_FT"],
        "load_weight_lb": TEST_DEFAULTS["CRIT_LOAD_WEIGHT_LB"],
    }
    if with_engineers:
        _add_engineers(world)
    return world


def _add_engineers(world: dict) -> dict:
    """Two licensed engineers: an author and an independent decider."""
    eng_a = new_engineer(full_name="Alan Pope", certification_number="PE-NJ-3391")
    eng_b = new_engineer(
        full_name="Mei Sato",
        certification_number="PE-NJ-4102",
        certification_expires_on="2028-02-28T00:00:00Z",
    )
    world["engineer_a"] = eng_a
    world["eng_a_id"] = eng_a["id"]
    world["engineer_b"] = eng_b
    world["eng_b_id"] = eng_b["id"]
    world["eng_a_headers"] = make_engineer_headers(eng_a["id"])
    world["eng_b_headers"] = make_engineer_headers(eng_b["id"])
    return world


# ---------------------------------------------------------------------------
# Tier 1/3: lift-plan progression helpers
# ---------------------------------------------------------------------------
def open_plan(world: dict, **overrides) -> dict:
    """Open a lift plan against the world's site (readiness DRAFT)."""
    opts = {"load_weight_lb": world["load_weight_lb"]}
    opts.update(overrides)
    payload = create_lift_plan_payload(world["site_id"], **opts)
    return get_success_data(api.create_lift_plan(payload, DISPATCHER))


def survey_plan(world: dict, plan_id: str, **overrides) -> dict:
    """Record the site survey, advancing the plan DRAFT -> SURVEYED."""
    opts = {"confirmed_soil_bearing_capacity_psf": world["soil_psf"]}
    opts.update(overrides)
    payload = site_survey_payload(**opts)
    return get_success_data(api.site_survey(plan_id, payload, DISPATCHER))


def commit_gear(world: dict, plan_id: str, gear_id: str = None, **overrides) -> dict:
    """Commit one serviceable gear item to the plan (assignment opens ACTIVE)."""
    target_gear = gear_id or world["gear_id"]
    expected = overrides.pop("expected_gear_version", None)
    if expected is None:
        expected = gear_version(target_gear)
    payload = create_gear_assignment_payload(plan_id, target_gear, expected, **overrides)
    return get_success_data(api.create_gear_assignment(payload, DISPATCHER))


def configure_body(world: dict, expected_lift_plan_version: int, **overrides) -> dict:
    """Build a configure payload keyed to the world's crane, crew and chart row."""
    body = {
        "crane_id": world["crane_id"],
        "operator_id": world["op_id"],
        "rigger_id": world["rig_id"],
        "configuration": "MAIN_BOOM",
        "boom_length_ft": world["boom_length_ft"],
        "radius_ft": world["radius_ft"],
        "parts_of_line": TEST_DEFAULTS["PARTS_OF_LINE"],
        "block_weight_lb": TEST_DEFAULTS["BLOCK_WEIGHT_LB"],
        "jib_weight_lb": 0,
        "aux_head_weight_lb": 0,
        "expected_lift_plan_version": expected_lift_plan_version,
    }
    body.update(overrides)
    return body


def configure_plan(world: dict, plan_id: str, expected_lift_plan_version: int,
                   **overrides) -> dict:
    """Configure the plan; returns the updated plan."""
    body = configure_body(world, expected_lift_plan_version, **overrides)
    return get_success_data(api.configure_lift_plan(plan_id, body, DISPATCHER))


def approve_plan(plan_id: str) -> dict:
    """LiftDirector sign-off for a STANDARD pick (CONFIGURED -> APPROVED)."""
    return get_success_data(api.approve_lift_plan(plan_id, LIFT_DIRECTOR))


def release_plan(plan_id: str) -> dict:
    """LiftDirector release (APPROVED -> RELEASED)."""
    return get_success_data(api.release_lift_plan(plan_id, LIFT_DIRECTOR))


def drive_field(world: dict, plan_id: str, action: str, operator_id: str = None) -> dict:
    """Advance the operational dimension as the plan's assigned operator."""
    headers = make_operator_headers(operator_id or world["op_id"])
    return get_success_data(api.set_field_status(plan_id, {"action": action}, headers))


def open_standby(plan_id: str, **overrides) -> dict:
    payload = {"lift_plan_id": plan_id, "cause": "WEATHER",
               "started_at": "2026-09-10T09:00:00Z"}
    payload.update(overrides)
    return get_success_data(api.create_standby_event(payload, SAFETY_MANAGER))


def close_standby(event_id: str, ended_at: str) -> dict:
    return get_success_data(
        api.close_standby_event(event_id, {"ended_at": ended_at}, SAFETY_MANAGER)
    )


def open_permit(plan_id: str, permit_type: str = "ROAD_CLOSURE",
                jurisdiction_code: str = None, world: dict = None) -> dict:
    code = jurisdiction_code or (world or {}).get("jurisdiction_code") \
        or TEST_DEFAULTS["STD_JURISDICTION"]
    payload = {"lift_plan_id": plan_id, "permit_type": permit_type,
               "jurisdiction_code": code}
    return get_success_data(api.create_permit(payload, DISPATCHER))


def submit_permit(permit_id: str) -> dict:
    return get_success_data(api.submit_permit(permit_id, DISPATCHER))


def approve_permit(permit_id: str, agency_reference: str = "NJH-2026-0042") -> dict:
    return get_success_data(
        api.record_permit_decision(
            permit_id, {"decision": "APPROVE", "agency_reference": agency_reference}, DISPATCHER
        )
    )


def open_review(world: dict, plan_id: str, author_id: str = None, notes: str = "rev 1 analysis") -> dict:
    author = author_id or world["eng_a_id"]
    payload = {"lift_plan_id": plan_id, "author_personnel_id": author,
               "analysis_notes": notes}
    return get_success_data(
        api.create_engineering_review(payload, make_engineer_headers(author))
    )


def decide_review(world: dict, review_id: str, action: str, note: str = "decision",
                  decider_id: str = None) -> dict:
    decider = decider_id or world["eng_b_id"]
    return get_success_data(
        api.decide_engineering_review(
            review_id, {"action": action, "note": note}, make_engineer_headers(decider)
        )
    )


def resubmit_review(world: dict, review_id: str, notes: str, author_id: str = None) -> dict:
    author = author_id or world["eng_a_id"]
    return get_success_data(
        api.resubmit_engineering_review(
            review_id, {"analysis_notes": notes}, make_engineer_headers(author)
        )
    )


def set_credit_hold(customer_id: str, on: bool, reason: str = None) -> dict:
    payload = {"credit_hold": on}
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(api.set_credit_status(customer_id, payload, BILLING_CLERK))


# ---------------------------------------------------------------------------
# Tier 3/4/5: composite lifecycle shortcuts
# ---------------------------------------------------------------------------
def setup_surveyed_plan_with_gear(world: dict, plan_overrides=None,
                                  assignment_overrides=None) -> dict:
    """Open a plan, record the survey, and commit one serviceable gear item.

    Returns a context dict carrying the plan, its post-survey version and the
    ACTIVE gear assignment.
    """
    plan = open_plan(world, **(plan_overrides or {}))
    surveyed = survey_plan(world, plan["id"])
    assignment = commit_gear(world, plan["id"], **(assignment_overrides or {}))
    return {
        "plan": surveyed,
        "plan_id": plan["id"],
        "plan_version": surveyed["version"],
        "assignment": assignment,
        "ga_id": assignment["id"],
    }


def setup_configured_plan(world: dict, plan_overrides=None, assignment_overrides=None,
                          configure_overrides=None) -> dict:
    """Take a plan all the way to its post-configure readiness posture."""
    ctx = setup_surveyed_plan_with_gear(world, plan_overrides, assignment_overrides)
    configured = configure_plan(
        world, ctx["plan_id"], ctx["plan_version"], **(configure_overrides or {})
    )
    ctx["plan"] = configured
    ctx["plan_version"] = configured["version"]
    return ctx


def setup_approved_standard_plan(world: dict, plan_overrides=None,
                                 assignment_overrides=None,
                                 configure_overrides=None) -> dict:
    """A STANDARD pick carried through the LiftDirector's sign-off."""
    ctx = setup_configured_plan(world, plan_overrides, assignment_overrides,
                                configure_overrides)
    approved = approve_plan(ctx["plan_id"])
    ctx["plan"] = approved
    ctx["plan_version"] = approved["version"]
    return ctx


def setup_released_standard_plan(world: dict, plan_overrides=None,
                                 assignment_overrides=None,
                                 configure_overrides=None,
                                 with_permit=False,
                                 permit_type="ROAD_CLOSURE") -> dict:
    """A STANDARD pick released to the field.

    When `with_permit` is set the plan's permit is opened, filed and granted
    before the release, because a plan whose permit_required is true cannot
    leave APPROVED until at least one permit stands at APPROVED.
    """
    ctx = setup_configured_plan(world, plan_overrides, assignment_overrides,
                                configure_overrides)
    if with_permit:
        permit = open_permit(ctx["plan_id"], permit_type, world=world)
        submit_permit(permit["id"])
        approve_permit(permit["id"])
        ctx["permit"] = permit
        ctx["permit_id"] = permit["id"]
    approve_plan(ctx["plan_id"])
    released = release_plan(ctx["plan_id"])
    ctx["plan"] = released
    ctx["plan_version"] = released["version"]
    return ctx


def setup_mobilized_standard_plan(world: dict, clock_to: str = None, **kwargs) -> dict:
    """Released, the clock moved onto the window, and the crew mobilized."""
    ctx = setup_released_standard_plan(world, **kwargs)
    set_clock(clock_to or TEST_DEFAULTS["WINDOW_START"])
    mobilized = drive_field(world, ctx["plan_id"], "MOBILIZE")
    ctx["plan"] = mobilized
    ctx["plan_version"] = mobilized["version"]
    return ctx


# The canonical two-window standby history: [09:00, 11:00) and [11:00, 12:10)
# are perfectly adjacent, so they merge into one 3.1667 hour interval which
# rounds up to 3.25 billable hours.
CANONICAL_STANDBY = [
    {"cause": "WIND", "wind_speed_mph": 24.0,
     "started_at": "2026-09-10T09:00:00Z", "ended_at": "2026-09-10T11:00:00Z"},
    {"cause": "WIND", "wind_speed_mph": 22.0,
     "started_at": "2026-09-10T11:00:00Z", "ended_at": "2026-09-10T12:10:00Z"},
]


def setup_closed_standard_job(world: dict, with_standby: bool = True,
                              plan_overrides=None, assignment_overrides=None,
                              configure_overrides=None, with_permit=False) -> dict:
    """Run a STANDARD pick end to end until the readiness dimension is CLOSED.

    With `with_standby` the job absorbs the canonical pair of adjacent wind
    holds, which leaves standby_hours_billable at 3.25.  The plan is opened
    with a sail area so its derated wind envelope admits those holds.
    """
    plan_kwargs = {"sail_area_sqft": TEST_DEFAULTS["SAIL_AREA_SQFT"]}
    plan_kwargs.update(plan_overrides or {})
    ctx = setup_mobilized_standard_plan(
        world,
        plan_overrides=plan_kwargs,
        assignment_overrides=assignment_overrides,
        configure_overrides=configure_overrides,
        with_permit=with_permit,
    )
    drive_field(world, ctx["plan_id"], "START_LIFT")
    events = []
    if with_standby:
        for spec in CANONICAL_STANDBY:
            event = open_standby(
                ctx["plan_id"], cause=spec["cause"],
                wind_speed_mph=spec["wind_speed_mph"], started_at=spec["started_at"]
            )
            close_standby(event["id"], spec["ended_at"])
            drive_field(world, ctx["plan_id"], "RESUME")
            events.append(event)
    drive_field(world, ctx["plan_id"], "SECURE")
    closed = drive_field(world, ctx["plan_id"], "DEMOBILIZE")
    ctx["plan"] = closed
    ctx["plan_version"] = closed["version"]
    ctx["standby_events"] = events
    return ctx


def setup_stamped_critical_plan(world: dict, plan_overrides=None,
                                assignment_overrides=None,
                                configure_overrides=None) -> dict:
    """A CRITICAL pick configured into PENDING_ENGINEERING and then stamped by a
    second engineer, which carries the plan through to APPROVED."""
    ctx = setup_configured_plan(world, plan_overrides, assignment_overrides,
                                configure_overrides)
    review = open_review(world, ctx["plan_id"])
    stamped = decide_review(world, review["id"], "STAMP", "PE stamp applied")
    ctx["review"] = stamped
    ctx["review_id"] = review["id"]
    ctx["plan"] = read_plan(ctx["plan_id"])
    ctx["plan_version"] = ctx["plan"]["version"]
    return ctx


def setup_critical_plan_under_review(world: dict, plan_overrides=None,
                                     assignment_overrides=None,
                                     configure_overrides=None) -> dict:
    """A CRITICAL pick sitting at PENDING_ENGINEERING with one UNDER_REVIEW analysis."""
    ctx = setup_configured_plan(world, plan_overrides, assignment_overrides,
                                configure_overrides)
    review = open_review(world, ctx["plan_id"])
    ctx["review"] = review
    ctx["review_id"] = review["id"]
    return ctx


def setup_drafted_invoice(world: dict, invoice_overrides=None, **job_kwargs) -> dict:
    """A CLOSED job carrying one DRAFT invoice."""
    ctx = setup_closed_standard_job(world, **job_kwargs)
    payload = {
        "lift_plan_id": ctx["plan_id"],
        "billing_mode": "HOURLY",
        "on_site_hours": 2.5,
        "travel_hours": 1.0,
        "travel_miles": 0.0,
        "expected_lift_plan_version": ctx["plan_version"],
    }
    payload.update(invoice_overrides or {})
    invoice = get_success_data(api.create_invoice(payload, BILLING_CLERK))
    ctx["invoice"] = invoice
    ctx["invoice_id"] = invoice["id"]
    return ctx


def setup_closed_critical_job(world: dict, with_standby: bool = True,
                              plan_overrides=None) -> dict:
    """Run a CRITICAL road-closure pick end to end until the plan is CLOSED.

    The pick reaches APPROVED through an engineering stamp rather than a
    LiftDirector sign-off, and its granted road-closure permit is what lets the
    release through.
    """
    plan_kwargs = {
        "sail_area_sqft": TEST_DEFAULTS["SAIL_AREA_SQFT"],
        "road_closure_requested": True,
    }
    plan_kwargs.update(plan_overrides or {})
    ctx = setup_stamped_critical_plan(world, plan_overrides=plan_kwargs)
    permit = open_permit(ctx["plan_id"], "ROAD_CLOSURE", world=world)
    submit_permit(permit["id"])
    approve_permit(permit["id"], "NJB-2026-1188")
    ctx["permit"] = permit
    ctx["permit_id"] = permit["id"]
    release_plan(ctx["plan_id"])
    set_clock(TEST_DEFAULTS["WINDOW_START"])
    drive_field(world, ctx["plan_id"], "MOBILIZE")
    drive_field(world, ctx["plan_id"], "START_LIFT")
    events = []
    if with_standby:
        for spec in CANONICAL_STANDBY:
            event = open_standby(
                ctx["plan_id"], cause=spec["cause"],
                wind_speed_mph=spec["wind_speed_mph"], started_at=spec["started_at"]
            )
            close_standby(event["id"], spec["ended_at"])
            drive_field(world, ctx["plan_id"], "RESUME")
            events.append(event)
    drive_field(world, ctx["plan_id"], "SECURE")
    closed = drive_field(world, ctx["plan_id"], "DEMOBILIZE")
    ctx["plan"] = closed
    ctx["plan_version"] = closed["version"]
    ctx["standby_events"] = events
    return ctx
