"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch using only PRD endpoints
(the runner restarts the server before each test, so each test starts empty).
Setup calls use get_success_data() so a setup failure surfaces as a clear
"Setup failed" message rather than a confusing assertion error.

Context convention: helpers return a dict with the created entities keyed by
role, plus ready-to-use headers:
  ctx["dep_station"], ctx["arr_station"], ctx["alt_station"], ctx["aircraft"],
  ctx["dispatcher"], ctx["captain"], ctx["leg"], ctx["plan"], ctx["manifest"],
  ctx["release"], ctx["desk"], ctx["shift"], ctx["weather"], ctx["event"]...
  ctx["d_headers"] / ctx["c_headers"] / ctx["s_headers"]
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_captain_payload,
    create_desk_payload,
    create_desk_shift_payload,
    create_dispatcher_payload,
    create_aircraft_payload,
    create_leg_payload,
    create_manifest_payload,
    create_mel_item_payload,
    create_plan_payload,
    create_station_payload,
    create_weather_package_payload,
)
from .test_users import TEST_USERS, make_captain_headers, make_dispatcher_headers

SUP = TEST_USERS["supervisor_headers"]


def _must(resp, what: str):
    body = resp.json()
    assert 200 <= resp.status_code < 300, (
        f"Setup failed during {what}: HTTP {resp.status_code} {body}"
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

def create_station(**overrides):
    return _must(api_client.create_station(create_station_payload(**overrides), SUP),
                 "station create")


def setup_reference_data(with_alternate: bool = True, dispatcher_overrides=None,
                         captain_overrides=None, aircraft_overrides=None) -> dict:
    """Dep station, arr station, optional alternate (90 NM, OPEN), one
    aircraft (A320 standard), dispatcher D1 and captain C1 (A320-qualified)."""
    ctx = {}
    ctx["dep_station"] = create_station(iata_code="KAAA", alternate_distance_nm=10)
    ctx["arr_station"] = create_station(iata_code="KBBB", alternate_distance_nm=20)
    if with_alternate:
        ctx["alt_station"] = create_station(
            iata_code="KAL1", alternate_distance_nm=TEST_DEFAULTS["ALT_DISTANCE_NM"]
        )
    ctx["aircraft"] = _must(
        api_client.create_aircraft(
            create_aircraft_payload(tail_no="N100AA", **(aircraft_overrides or {})), SUP
        ),
        "aircraft create",
    )
    disp_kw = {"name": "Dana One", "license_no": "D001"}
    disp_kw.update(dispatcher_overrides or {})
    ctx["dispatcher"] = _must(
        api_client.create_dispatcher(create_dispatcher_payload(**disp_kw), SUP),
        "dispatcher create",
    )
    cap_kw = {"name": "Cole One", "license_no": "C001"}
    cap_kw.update(captain_overrides or {})
    ctx["captain"] = _must(
        api_client.create_captain(create_captain_payload(**cap_kw), SUP),
        "captain create",
    )
    ctx["d_headers"] = make_dispatcher_headers(ctx["dispatcher"]["id"])
    ctx["c_headers"] = make_captain_headers(ctx["captain"]["id"])
    ctx["s_headers"] = SUP
    return ctx


# ---------------------------------------------------------------------------
# Atomic chain steps (operate on a ctx dict)
# ---------------------------------------------------------------------------

def set_clock(ctx, to_iso8601: str):
    _must(api_client.set_clock(to_iso8601, SUP), f"set clock {to_iso8601}")
    ctx["clock"] = to_iso8601
    return ctx


def add_leg(ctx, **overrides) -> dict:
    """Create a leg assigned to ctx's dispatcher. Returns the leg."""
    leg = _must(
        api_client.create_leg(
            create_leg_payload(
                ctx["dep_station"]["id"], ctx["arr_station"]["id"],
                ctx["aircraft"]["id"], ctx["captain"]["id"],
                dispatcher_id=ctx["dispatcher"]["id"], **overrides,
            ),
            ctx["d_headers"],
        ),
        "leg create",
    )
    ctx["leg"] = leg
    ctx["leg_version"] = leg["version"]
    return leg


def add_second_leg(ctx, **overrides) -> dict:
    """A second leg for the same dispatcher (kept separate from ctx['leg'])."""
    leg = _must(
        api_client.create_leg(
            create_leg_payload(
                ctx["dep_station"]["id"], ctx["arr_station"]["id"],
                ctx["aircraft"]["id"], ctx["captain"]["id"],
                dispatcher_id=ctx["dispatcher"]["id"], **overrides,
            ),
            ctx["d_headers"],
        ),
        "second leg create",
    )
    ctx["leg2"] = leg
    return leg


def add_plan(ctx, **overrides) -> dict:
    """Create (compute) a plan for ctx['leg'] with a fresh OCC version."""
    leg = _must(api_client.get_leg(ctx["leg"]["id"], ctx["d_headers"]), "leg re-read")
    ctx["leg_version"] = leg["version"]
    plan = _must(
        api_client.create_plan(
            create_plan_payload(ctx["leg"]["id"], leg["version"], **overrides),
            ctx["d_headers"],
        ),
        "plan create",
    )
    ctx["plan"] = plan
    return plan


def add_weather(ctx, **overrides) -> dict:
    """Publish an ACTIVE weather package for the arrival station covering the
    leg's scheduled arrival (default window 09:00-13:00, ceiling 1000/5000)."""
    wx = _must(
        api_client.create_weather_package(
            create_weather_package_payload(ctx["arr_station"]["id"], **overrides), SUP
        ),
        "weather publish",
    )
    ctx["weather"] = wx
    return wx


def lock_plan(ctx) -> dict:
    plan = _must(api_client.lock_plan(ctx["plan"]["id"], ctx["d_headers"]), "plan lock")
    ctx["plan"] = plan
    return plan


def recompute_plan(ctx) -> dict:
    plan = _must(
        api_client.recompute_plan(ctx["plan"]["id"], ctx["d_headers"]), "plan recompute"
    )
    ctx["plan"] = plan
    return plan


def add_manifest(ctx, **overrides) -> dict:
    man = _must(
        api_client.create_manifest(
            create_manifest_payload(ctx["leg"]["id"], **overrides), ctx["d_headers"]
        ),
        "manifest create",
    )
    ctx["manifest"] = man
    return man


def add_release(ctx) -> dict:
    rel = _must(
        api_client.create_release({"leg_id": ctx["leg"]["id"]}, ctx["d_headers"]),
        "release create",
    )
    ctx["release"] = rel
    return rel


def submit_release(ctx) -> dict:
    rel = _must(
        api_client.submit_release(ctx["release"]["id"], ctx["d_headers"]),
        "release submit",
    )
    ctx["release"] = rel
    return rel


def sign_both(ctx) -> dict:
    """Dispatcher slot then captain slot; second valid signature releases."""
    _must(api_client.sign_release(ctx["release"]["id"], ctx["d_headers"]),
          "dispatcher sign")
    rel = _must(api_client.sign_release(ctx["release"]["id"], ctx["c_headers"]),
                "captain sign")
    ctx["release"] = rel
    return rel


def add_desk_and_shift(ctx, desk_overrides=None, shift_overrides=None) -> tuple:
    """One desk (max_dispatchers 1) and one 06:00-14:00 shift for the
    ctx dispatcher covering the standard departure clock."""
    desk = _must(
        api_client.create_desk(create_desk_payload(code="K1", **(desk_overrides or {})),
                               SUP),
        "desk create",
    )
    shift = _must(
        api_client.create_desk_shift(
            create_desk_shift_payload(ctx["dispatcher"]["id"], desk_id=desk["id"],
                                      **(shift_overrides or {})),
            SUP,
        ),
        "desk shift create",
    )
    ctx["desk"] = desk
    ctx["shift"] = shift
    return desk, shift


def depart_leg(ctx) -> dict:
    """Set the clock inside the shift window and mark departure."""
    set_clock(ctx, TEST_DEFAULTS["CLOCK_DEPART"])
    leg = _must(api_client.depart_leg(ctx["leg"]["id"], ctx["d_headers"]), "leg depart")
    ctx["leg"] = leg
    return leg


# ---------------------------------------------------------------------------
# Composite chains
# ---------------------------------------------------------------------------

def setup_computed_plan(distance_nm: int = TEST_DEFAULTS["LEG_DISTANCE_NM"],
                        with_alternate: bool = True,
                        leg_overrides=None, plan_overrides=None,
                        **ref_kwargs) -> dict:
    """Reference data + one leg + one COMPUTED plan (no weather, no lock)."""
    ctx = setup_reference_data(with_alternate=with_alternate, **ref_kwargs)
    add_leg(ctx, distance_nm=distance_nm, **(leg_overrides or {}))
    add_plan(ctx, **(plan_overrides or {}))
    return ctx


def setup_locked_plan(distance_nm: int = TEST_DEFAULTS["LEG_DISTANCE_NM"],
                      leg_overrides=None, plan_overrides=None,
                      weather_overrides=None, **ref_kwargs) -> dict:
    """Computed plan + clock 08:00 + arrival weather + LOCKED."""
    ctx = setup_computed_plan(distance_nm=distance_nm, leg_overrides=leg_overrides,
                              plan_overrides=plan_overrides, **ref_kwargs)
    set_clock(ctx, TEST_DEFAULTS["CLOCK_MORNING"])
    add_weather(ctx, **(weather_overrides or {}))
    lock_plan(ctx)
    return ctx


def setup_manifest_chain(pax_count: int = 150, bags_count: int = 150,
                         cargo_kg=3000, **kwargs) -> dict:
    """Locked plan + manifest pinned to it."""
    ctx = setup_locked_plan(**kwargs)
    add_manifest(ctx, pax_count=pax_count, bags_count=bags_count, cargo_kg=cargo_kg)
    return ctx


def setup_release_draft(**kwargs) -> dict:
    """Manifest chain + release in DRAFT (cycle_seq 1, amendment_count 0)."""
    ctx = setup_manifest_chain(**kwargs)
    add_release(ctx)
    return ctx


def setup_release_pending(**kwargs) -> dict:
    """Release chain through submission -> PENDING_SIGNATURES."""
    ctx = setup_release_draft(**kwargs)
    submit_release(ctx)
    return ctx


def setup_release_released(include_desk_shift: bool = False, **kwargs) -> dict:
    """Release chain through both signatures -> RELEASED (cycle_seq 1)."""
    ctx = setup_release_pending(**kwargs)
    sign_both(ctx)
    if include_desk_shift:
        add_desk_and_shift(ctx)
    return ctx


def setup_leg_departed(**kwargs) -> dict:
    """Released release + desk shift + clock 10:30 + leg DEPARTED/MONITORING."""
    ctx = setup_release_released(include_desk_shift=True, **kwargs)
    depart_leg(ctx)
    return ctx


# ---------------------------------------------------------------------------
# Specialized chains
# ---------------------------------------------------------------------------

def setup_two_variant_plans() -> dict:
    """Two identical 1200 NM legs on the standard aircraft; leg1 gets a
    FORECAST +30 kt plan, leg2 a WORST_CASE plan. Returns ctx with
    ctx['plan_forecast'] and ctx['plan_worst_case']."""
    ctx = setup_reference_data()
    add_leg(ctx, flight_no="FD100", distance_nm=1200)
    ctx["plan_forecast"] = add_plan(ctx, wind_assumption="FORECAST", forecast_wind_kts=30)
    leg2 = add_second_leg(ctx, flight_no="FD200", distance_nm=1200)
    plan_w = _must(
        api_client.create_plan(
            create_plan_payload(leg2["id"], leg2["version"], wind_assumption="WORST_CASE",
                                forecast_wind_kts=30),
            ctx["d_headers"],
        ),
        "worst-case plan create",
    )
    ctx["plan_worst_case"] = plan_w
    return ctx


def setup_release_draft_with_expired_mel() -> dict:
    """Release DRAFT chain; then an OPEN category-A item (deadline 09:00,
    created at clock 08:00) is expired by advancing the clock to 10:00."""
    ctx = setup_release_draft()
    mel = _must(
        api_client.create_mel_item(
            create_mel_item_payload(
                ctx["aircraft"]["id"], item_code="71-2", deferral_category="A",
                repair_deadline_utc="2026-05-01T09:00:00Z",
            ),
            SUP,
        ),
        "mel create",
    )
    ctx["mel"] = mel
    set_clock(ctx, "2026-05-01T10:00:00Z")
    return ctx
