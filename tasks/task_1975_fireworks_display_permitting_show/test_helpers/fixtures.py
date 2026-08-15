"""Composite setup helpers (PRD §3 workflows).

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database). Setup calls use get_success_data() so
setup failures surface as clear "Setup failed" errors.

Identity threading: Operator and CrewMember are entity-backed roles (PRD
§2.1); every ownership- or scope-gated call uses headers built from the
actual entity's id.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_operator_payload,
    create_crew_member_payload,
    create_display_payload,
    create_site_plan_payload,
    create_permit_application_payload,
    create_magazine_payload,
    create_batch_payload,
    create_checkout_payload,
    create_return_payload,
    create_expend_payload,
    create_weather_reading_payload,
    create_security_post_payload,
    create_assign_payload,
    create_misfire_payload,
    create_sweep_payload,
    create_standby_confirm_payload,
    create_go_no_go_payload,
)
from .test_users import (
    TEST_USERS,
    make_operator_headers,
    make_crew_member_headers,
    make_marshal_headers,
)

ADMIN = TEST_USERS["admin_headers"]
MARSHAL_1 = make_marshal_headers("fm_1")
MARSHAL_2 = make_marshal_headers("fm_2")


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation
# ---------------------------------------------------------------------------

def create_operator(**overrides):
    """Register an operator (SystemAdmin). Returns (operator, operator_headers)."""
    resp = api_client.create_operator(create_operator_payload(**overrides), ADMIN)
    op = get_success_data(resp)
    return op, make_operator_headers(op["id"])


def set_clock(to_iso8601: str):
    """Advance the logical clock (SystemAdmin)."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: event progression
# ---------------------------------------------------------------------------

def create_display_event(op, op_headers, **overrides):
    """Create a DRAFT display event owned by op."""
    resp = api_client.create_display(create_display_payload(**overrides), op_headers)
    return get_success_data(resp)


def add_site_plan(ev, op_headers, **overrides):
    """Create a CURRENT site plan against the event's current version."""
    fresh = get_success_data(api_client.get_display(ev["id"], op_headers))
    payload = create_site_plan_payload(fresh["version"], **overrides)
    resp = api_client.create_site_plan(ev["id"], payload, op_headers)
    return get_success_data(resp)


def submit_permit_application(ev, sp, op_headers, **overrides):
    """Submit a permit application (event DRAFT -> SUBMITTED)."""
    resp = api_client.create_permit_application(
        ev["id"], create_permit_application_payload(sp["id"], **overrides), op_headers
    )
    return get_success_data(resp)


def approve_permit(app, marshal_headers=None):
    resp = api_client.approve_permit(app["id"], {"decision_note": "ok"}, marshal_headers or MARSHAL_1)
    return get_success_data(resp)


def confirm_standby(ev, engines_on_site=1, marshal_headers=None):
    resp = api_client.standby_confirm(
        ev["id"],
        create_standby_confirm_payload(standby_engines_on_site=engines_on_site),
        marshal_headers or MARSHAL_2,
    )
    return get_success_data(resp)


def create_magazine_with_batch(op_headers, batch_overrides=None, magazine_overrides=None):
    """Create a magazine + one batch. Returns (magazine, batch)."""
    mag = get_success_data(
        api_client.create_magazine(create_magazine_payload(**(magazine_overrides or {})), op_headers)
    )
    batch = get_success_data(
        api_client.create_batch(mag["id"], create_batch_payload(**(batch_overrides or {})), op_headers)
    )
    return mag, batch


def checkout_product(batch, ev, op_headers, quantity):
    resp = api_client.create_movement(
        batch["id"], create_checkout_payload(ev["id"], quantity), op_headers
    )
    return get_success_data(resp)


def add_lead_crew(op, op_headers, **overrides):
    """Register a LEAD_OPERATOR crew member. Returns (crew, crew_headers)."""
    resp = api_client.create_crew_member(
        op["id"], create_crew_member_payload(**overrides), op_headers
    )
    crew = get_success_data(resp)
    return crew, make_crew_member_headers(crew["id"])


def add_secured_post(ev, op_headers, arc_degrees=45, radius_ft=300, guards=None):
    """Create a security post and assign guards until SECURED.

    For the default geometry (r=300, arc=45) required_guards == 3
    (ceil(2*pi*300*45/360 / 100) = 3), so the default is 3 guards.
    """
    post = get_success_data(
        api_client.create_security_post(
            ev["id"],
            create_security_post_payload(arc_degrees=arc_degrees, radius_ft=radius_ft),
            op_headers,
        )
    )
    n = guards if guards is not None else post["required_guards"]
    for i in range(n):
        post = get_success_data(
            api_client.assign_guard(post["id"], create_assign_payload(f"g{i+1}"), op_headers)
        )
    return post


def post_weather(ev, crew_headers, **overrides):
    resp = api_client.create_weather_reading(
        ev["id"], create_weather_reading_payload(**overrides), crew_headers
    )
    return get_success_data(resp)


def go_decision(ev, op_headers, decision="GO"):
    """Read the current version, then submit the go/no-go decision."""
    fresh = get_success_data(api_client.get_display(ev["id"], op_headers))
    resp = api_client.go_no_go(
        ev["id"], create_go_no_go_payload(decision, fresh["version"]), op_headers
    )
    return resp


# ---------------------------------------------------------------------------
# Tier 3: full-lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_event_draft(display_overrides=None, operator_overrides=None):
    """Operator + DRAFT event. Returns (op, op_headers, ev)."""
    op, op_headers = create_operator(**(operator_overrides or {}))
    ev = create_display_event(op, op_headers, **(display_overrides or {}))
    return op, op_headers, ev


def setup_event_submitted(display_overrides=None, site_plan_overrides=None,
                          permit_overrides=None):
    """Event with CURRENT plan and a SUBMITTED application.
    Returns (op, op_headers, ev, sp, app)."""
    op, op_headers, ev = setup_event_draft(display_overrides=display_overrides)
    sp = add_site_plan(ev, op_headers, **(site_plan_overrides or {}))
    app = submit_permit_application(ev, sp, op_headers, **(permit_overrides or {}))
    ev = get_success_data(api_client.get_display(ev["id"], op_headers))
    return op, op_headers, ev, sp, app


def setup_event_approved(standby_engines=1, display_overrides=None,
                         site_plan_overrides=None, approver=None):
    """Event APPROVED. Returns (op, op_headers, ev, sp, app)."""
    op, op_headers, ev, sp, app = setup_event_submitted(
        display_overrides=display_overrides,
        site_plan_overrides=site_plan_overrides,
        permit_overrides={"standby_engines": standby_engines},
    )
    approve_permit(app, marshal_headers=approver or MARSHAL_1)
    ev = get_success_data(api_client.get_display(ev["id"], op_headers))
    return op, op_headers, ev, sp, app


def setup_event_standby_confirmed(standby_engines=1, standby_clock=None,
                                  display_overrides=None, site_plan_overrides=None):
    """Event STANDBY_CONFIRMED (approver fm_1, confirmer fm_2 — SoD).
    Returns (op, op_headers, ev, sp, app)."""
    op, op_headers, ev, sp, app = setup_event_approved(
        standby_engines=standby_engines,
        display_overrides=display_overrides,
        site_plan_overrides=site_plan_overrides,
    )
    if standby_clock is not None:
        set_clock(standby_clock)
    confirm_standby(ev, engines_on_site=standby_engines, marshal_headers=MARSHAL_2)
    ev = get_success_data(api_client.get_display(ev["id"], op_headers))
    return op, op_headers, ev, sp, app


def setup_event_ready(checkout_qty=10, standby_engines=1,
                      display_overrides=None, site_plan_overrides=None,
                      batch_overrides=None, magazine_overrides=None,
                      post_arc_degrees=45, post_radius_ft=300,
                      standby_clock=None):
    """Event READY: approved, standby confirmed, product checked out,
    LEAD crew present, one SECURED security post.

    Returns dict with op, op_headers, ev, sp, app, mag, batch, crew,
    crew_headers, post."""
    op, op_headers, ev, sp, app = setup_event_standby_confirmed(
        standby_engines=standby_engines,
        standby_clock=standby_clock,
        display_overrides=display_overrides,
        site_plan_overrides=site_plan_overrides,
    )
    mag, batch = create_magazine_with_batch(
        op_headers, batch_overrides=batch_overrides,
        magazine_overrides=magazine_overrides,
    )
    if checkout_qty:
        checkout_product(batch, ev, op_headers, checkout_qty)
    crew, crew_headers = add_lead_crew(op, op_headers)
    post = add_secured_post(ev, op_headers, arc_degrees=post_arc_degrees,
                            radius_ft=post_radius_ft)
    resp = api_client.ready_display(ev["id"], op_headers)
    ev = get_success_data(resp)
    return {
        "op": op, "op_headers": op_headers, "ev": ev, "sp": sp, "app": app,
        "mag": mag, "batch": batch, "crew": crew, "crew_headers": crew_headers,
        "post": post,
    }


def setup_event_in_progress(checkout_qty=10, expend_qty=0, decision_clock="2026-09-01T19:30:00Z",
                            reading_overrides=None, **ready_kwargs):
    """Event IN_PROGRESS: READY fixture + clock advanced into the decision
    window + fresh weather reading + GO decision.

    Returns the READY dict with updated ev."""
    ctx = setup_event_ready(checkout_qty=checkout_qty, **ready_kwargs)
    set_clock(decision_clock)
    post_weather(ctx["ev"], ctx["crew_headers"], **(reading_overrides or {}))
    resp = go_decision(ctx["ev"], ctx["op_headers"], "GO")
    ctx["ev"] = get_success_data(resp)
    if expend_qty:
        resp = api_client.create_movement(
            ctx["batch"]["id"], create_expend_payload(ctx["ev"]["id"], expend_qty),
            ctx["op_headers"],
        )
        get_success_data(resp)
        ctx["batch"] = get_success_data(
            api_client.get_batch(ctx["batch"]["id"], ctx["op_headers"])
        )
    return ctx


def setup_event_show_complete(checkout_qty=20, expend_qty=20, **kwargs):
    """Event SHOW_COMPLETE: IN_PROGRESS + all expended + complete-show.
    Returns the context dict (net checked-out == 0 when checkout==expend)."""
    ctx = setup_event_in_progress(
        checkout_qty=checkout_qty, expend_qty=expend_qty,
        decision_clock="2026-09-01T20:00:00Z", **kwargs
    )
    resp = api_client.complete_show(ctx["ev"]["id"], ctx["op_headers"])
    ctx["ev"] = get_success_data(resp)
    return ctx


def setup_event_closed(**kwargs):
    """Full lifecycle through CLOSED: SHOW_COMPLETE + clear sweep VERIFIED
    (no incidents, net checked-out == 0). Returns (ctx, sweep, closed_event)."""
    ctx = setup_event_show_complete(**kwargs)
    sweep = get_success_data(
        api_client.create_sweep(ctx["ev"]["id"], create_sweep_payload(), ctx["crew_headers"])
    )
    get_success_data(
        api_client.verify_sweep(sweep["id"], {"verdict": "VERIFIED"}, MARSHAL_2)
    )
    closed = get_success_data(api_client.get_display(ctx["ev"]["id"], ctx["op_headers"]))
    return ctx, sweep, closed
