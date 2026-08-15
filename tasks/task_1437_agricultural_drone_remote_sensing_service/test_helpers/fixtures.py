"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors. All callers are responsible for their own assertions.

Identity threading: ownership-gated calls always use the per-instance builders
from test_users (make_pilot_headers / make_agronomist_headers /
make_grower_headers) with the real entity id — never the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_authorization_payload,
    create_claim_payload,
    create_field_payload,
    create_grower_payload,
    create_mission_payload,
    create_pilot_payload,
    create_subscription_plan_payload,
)
from .test_users import (
    TEST_USERS,
    make_agronomist_headers,
    make_grower_headers,
    make_pilot_headers,
)

ADMIN = TEST_USERS["ops_admin_headers"]
FC = TEST_USERS["flight_coordinator_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]
ENGINE = TEST_USERS["processing_engine_headers"]


def _ok(step, resp, expected=None):
    data = get_success_data(resp)
    if expected is not None and isinstance(data, dict):
        status = data.get("status")
        assert status == expected, (
            f"Setup failed at {step}: expected status {expected}, got {status}"
        )
    return data


# ---------------------------------------------------------------------------
# Tier 0 — logical clock (PRD section 2.5)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    resp = api_client.set_current_utc({"to_iso8601": to_iso8601}, ADMIN)
    return _ok("set_current_utc", resp)


# ---------------------------------------------------------------------------
# Tier 1 — onboarding primitives (PRD section 3.1)
# ---------------------------------------------------------------------------

def create_plan(**overrides):
    resp = api_client.create_subscription_plan(
        create_subscription_plan_payload(**overrides), ADMIN)
    return _ok("create_subscription_plan", resp)


def create_grower(plan_id=None, **overrides):
    if plan_id is None:
        plan_id = create_plan()["id"]
    resp = api_client.create_grower(
        create_grower_payload(plan_id, **overrides), ADMIN)
    return _ok("create_grower", resp, expected="ACTIVE")


def create_field(grower_id, **overrides):
    resp = api_client.create_field(
        grower_id, create_field_payload(**overrides), ADMIN)
    return _ok("create_field", resp)


def create_pilot(**overrides):
    resp = api_client.create_pilot(create_pilot_payload(**overrides), ADMIN)
    return _ok("create_pilot", resp, expected="ACTIVE")


def create_authorization(field_id, **overrides):
    resp = api_client.create_authorization(
        create_authorization_payload(field_id, **overrides), ADMIN)
    return _ok("create_authorization", resp, expected="ACTIVE")


def setup_ops(plan_overrides=None, grower_overrides=None, field_overrides=None,
              pilot_overrides=None, clock="2026-06-01T00:00:00Z"):
    """Tier 2 hierarchy: plan + grower + field + pilot, clock pinned.

    Returns a dict with keys plan, grower, field, pilot. The default clock is
    moved back to 2026-06-01 so missions scheduled in June 2026 are in the
    future at creation.
    """
    if clock is not None:
        set_clock(clock)
    plan = create_plan(**(plan_overrides or {}))
    grower = create_grower(plan["id"], **(grower_overrides or {}))
    field = create_field(grower["id"], **(field_overrides or {}))
    pilot = create_pilot(**(pilot_overrides or {}))
    return {"plan": plan, "grower": grower, "field": field, "pilot": pilot}


# ---------------------------------------------------------------------------
# Tier 1/3 — mission lifecycle walkers (PRD sections 3.3 and 3.4)
# ---------------------------------------------------------------------------

def create_mission(field_id, pilot_id, **overrides):
    """Create a mission (born PLANNED)."""
    resp = api_client.create_mission(
        field_id, create_mission_payload(pilot_id, **overrides), FC)
    return _ok("create_mission", resp, expected="PLANNED")


def authorize(mission_id):
    resp = api_client.authorize_mission(mission_id, FC)
    return _ok("authorize_mission", resp, expected="AUTHORIZED")


def launch_at(mission_id, pilot_id, at_iso8601):
    """Move the clock inside the window and launch as the assigned pilot."""
    set_clock(at_iso8601)
    resp = api_client.launch_mission(mission_id, make_pilot_headers(pilot_id))
    return _ok("launch_mission", resp, expected="IN_FLIGHT")


def capture(mission_id, pilot_id, acres_flown, wind_kt=5, gallons=None):
    payload = {"acres_flown": acres_flown, "wind_kt_max_observed": wind_kt}
    if gallons is not None:
        payload["gallons_dispensed"] = gallons
    resp = api_client.capture_mission(
        mission_id, payload, make_pilot_headers(pilot_id))
    return _ok("capture_mission", resp, expected="CAPTURED")


def complete(mission_id, deliverable_kinds=None):
    payload = {"deliverable_kinds": deliverable_kinds or ["NDVI"]}
    resp = api_client.complete_mission(mission_id, payload, FC)
    return _ok("complete_mission", resp, expected="COMPLETED")


def abort_weather(mission_id, pilot_id, wind_kt=25):
    resp = api_client.abort_weather_mission(
        mission_id, {"wind_kt_max_observed": wind_kt},
        make_pilot_headers(pilot_id))
    return _ok("abort_weather_mission", resp, expected="WEATHER_ABORTED")


def create_mission_authorized(field_id, pilot_id, **overrides):
    """Tier 3: create + authorize. Returns the AUTHORIZED mission."""
    mission = create_mission(field_id, pilot_id, **overrides)
    return authorize(mission["id"])


def create_mission_in_flight(field_id, pilot_id,
                             start="2026-06-02T08:00:00Z",
                             end="2026-06-02T10:00:00Z",
                             launch_time="2026-06-02T08:30:00Z", **overrides):
    """Tier 3: create + authorize + launch. Returns the IN_FLIGHT mission."""
    mission = create_mission_authorized(
        field_id, pilot_id, scheduled_start=start, scheduled_end=end,
        **overrides)
    return launch_at(mission["id"], pilot_id, launch_time)


def create_mission_captured(field_id, pilot_id, acres_flown, wind_kt=5,
                            gallons=None, **window):
    """Tier 3: full path through CAPTURED. Returns the CAPTURED mission."""
    mission = create_mission_in_flight(field_id, pilot_id, **window)
    return capture(mission["id"], pilot_id, acres_flown, wind_kt, gallons)


def create_mission_completed(field_id, pilot_id, acres_flown, wind_kt=5,
                             gallons=None, deliverable_kinds=None, **window):
    """Tier 3: full path through COMPLETED. Returns the COMPLETED mission."""
    mission = create_mission_captured(
        field_id, pilot_id, acres_flown, wind_kt, gallons, **window)
    return complete(mission["id"], deliverable_kinds)


def create_mission_weather_aborted(field_id, pilot_id, wind_kt=25, **window):
    """Tier 3: full path through WEATHER_ABORTED. Returns the mission."""
    mission = create_mission_in_flight(field_id, pilot_id, **window)
    return abort_weather(mission["id"], pilot_id, wind_kt)


# ---------------------------------------------------------------------------
# Tier 2/3 — deliverable processing and alerts (PRD section 3.6)
# ---------------------------------------------------------------------------

def list_first_deliverable(mission_id):
    resp = api_client.list_mission_deliverables(mission_id, ENGINE)
    data = _ok("list_mission_deliverables", resp)
    assert isinstance(data, list) and data, \
        f"Setup failed at list_mission_deliverables: no deliverables for {mission_id}"
    return data[0]


def process_deliverable(deliverable_id, payload):
    resp = api_client.process_deliverable(deliverable_id, payload, ENGINE)
    return _ok("process_deliverable", resp, expected="READY")


def process_ndvi_deliverable(mission_id, ndvi_mean, cells_below_threshold):
    deliverable = list_first_deliverable(mission_id)
    return process_deliverable(deliverable["id"], {
        "ndvi_mean": ndvi_mean,
        "cells_below_threshold": cells_below_threshold,
    })


def process_plant_count_deliverable(mission_id, plant_count_per_acre):
    deliverable = list_first_deliverable(mission_id)
    return process_deliverable(deliverable["id"], {
        "plant_count_per_acre": plant_count_per_acre,
    })


def list_field_alerts(field_id, params=None):
    resp = api_client.list_field_alerts(field_id, FC, params=params)
    return _ok("list_field_alerts", resp)


def get_field(field_id):
    resp = api_client.get_field(field_id, FC)
    return _ok("get_field", resp)


def get_grower(grower_id):
    resp = api_client.get_grower(grower_id, ADMIN)
    return _ok("get_grower", resp)


def get_mission(mission_id):
    resp = api_client.get_mission(mission_id, FC)
    return _ok("get_mission", resp)


def setup_field_with_open_alert(cells_below_threshold=2000, acres=100,
                                ndvi_mean=0.500, **ops_kwargs):
    """Tier 4: drive a mission to COMPLETED and process its NDVI deliverable
    so exactly one ScoutingAlert is OPEN on the field (anomaly_count > 0
    requires cells_below_threshold * acres / 1000 to round to >= 1).

    Returns (ctx, mission, deliverable, alert).
    """
    # PRD section 3.4: capture requires acres_flown <= acres_planned, and
    # PRD section 3.3 caps acres_planned at the field's legal_acres — so the
    # field's deeded acreage must cover the flown acreage and the mission
    # must plan at least as many acres as it flies.
    ops_kwargs.setdefault("field_overrides", {})
    ops_kwargs["field_overrides"].setdefault("legal_acres", max(100, acres))
    ctx = setup_ops(**ops_kwargs)
    mission = create_mission_completed(
        ctx["field"]["id"], ctx["pilot"]["id"],
        acres_flown=acres, acres_planned=acres)
    deliverable = process_ndvi_deliverable(
        mission["id"], ndvi_mean, cells_below_threshold)
    alerts = list_field_alerts(ctx["field"]["id"])
    assert len(alerts) == 1, \
        f"Setup failed: expected exactly one alert, got {len(alerts)}"
    assert alerts[0]["status"] == "OPEN"
    return ctx, mission, deliverable, alerts[0]


# ---------------------------------------------------------------------------
# Tier 3 — claims lifecycle (PRD section 3.8)
# ---------------------------------------------------------------------------

def create_claim(grower_id, mission_id, claim_amount_cents=1000):
    resp = api_client.create_claim(
        grower_id, create_claim_payload(mission_id,
                                        claim_amount_cents=claim_amount_cents),
        make_grower_headers(grower_id))
    return _ok("create_claim", resp, expected="SUBMITTED")


def open_claim_review(claim_id, adjuster_headers=None):
    resp = api_client.open_claim_review(claim_id, adjuster_headers or ADJUSTER)
    return _ok("open_claim_review", resp, expected="UNDER_REVIEW")


def approve_claim(claim_id, amount_cents):
    resp = api_client.approve_claim(claim_id, {"amount_cents": amount_cents},
                                    ADJUSTER)
    return _ok("approve_claim", resp, expected="APPROVED")


def deny_claim(claim_id):
    resp = api_client.deny_claim(claim_id, ADJUSTER)
    return _ok("deny_claim", resp, expected="DENIED")


def pay_claim(claim_id):
    resp = api_client.pay_claim(claim_id, ADJUSTER)
    return _ok("pay_claim", resp, expected="PAID")


def setup_completed_mission_scenario(acres_planned=10, acres_flown=10,
                                     **ops_kwargs):
    """Tier 2 convenience: ops context + one COMPLETED SCOUT mission.

    Returns (ctx, mission).
    """
    ctx = setup_ops(**ops_kwargs)
    mission = create_mission_completed(
        ctx["field"]["id"], ctx["pilot"]["id"], acres_flown=acres_flown,
        acres_planned=acres_planned)
    return ctx, mission
