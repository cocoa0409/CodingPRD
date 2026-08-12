"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database). Setup calls use get_success_data() so a
setup failure surfaces as a clear "Setup failed" error rather than a
confusing assertion failure.

Identity threading: FieldCrew and SugarMaker are entity-backed roles (PRD
§2.1). Any ownership-gated call (sap-run create/confirm with collected_by,
batch operations with boiled_by, flavor evaluation with evaluator_id) is made
with make_fieldcrew_headers(crew["id"]) / make_sugarmaker_headers(crew["id"]),
never with the shared fallback constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_batch_intake_payload,
    create_batch_payload,
    create_cert_audit_payload,
    create_crew_member_payload,
    create_finish_payload,
    create_flavor_evaluation_payload,
    create_grade_payload,
    create_sap_run_payload,
    create_season_payload,
    create_sugarbush_payload,
    create_tap_line_payload,
    create_weather_window_payload,
)
from .test_users import TEST_USERS, make_fieldcrew_headers, make_sugarmaker_headers

MANAGER = TEST_USERS["manager_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]

DEFAULT_CLOCK_INIT = "2027-02-15T00:00:00Z"
DEFAULT_WINDOW_OPEN_CLOCK = "2027-03-02T08:00:00Z"


def _setup_ok(res, what):
    data = get_success_data(res)
    assert res.status_code < 300, f"Setup failed ({what}): HTTP {res.status_code} {res.text}"
    return data


# ─── Tier 1: State progression ──────────────────────────────────────────────

def set_clock(iso8601: str):
    """Manager-only logical clock set (PRD §2.4)."""
    return _setup_ok(api_client.set_clock({"to_iso8601": iso8601}, MANAGER), "set clock")


def setup_open_season(year=2027, opens_on="2027-02-01", closes_on="2027-04-15",
                      planned_taps=10000, clock=DEFAULT_CLOCK_INIT) -> dict:
    """Create a season and open it (PLANNED -> OPEN). Returns the OPEN season."""
    set_clock(clock)
    season = _setup_ok(
        api_client.create_season(
            create_season_payload(year=year, opens_on=opens_on,
                                  closes_on=closes_on, planned_taps=planned_taps),
            MANAGER),
        "create season")
    return _setup_ok(api_client.open_season(season["id"], MANAGER), "open season")


def create_bush(season_id, name="North Woods", tap_capacity=5000) -> dict:
    """Create a sugarbush (PREP)."""
    return _setup_ok(
        api_client.create_sugarbush(
            create_sugarbush_payload(season_id, name=name, tap_capacity=tap_capacity),
            MANAGER),
        "create sugarbush")


def begin_tapping(bush_id) -> dict:
    return _setup_ok(api_client.begin_tapping(bush_id, MANAGER), "begin tapping")


def create_line(bush_id, line_code="L1", tap_count=100, vacuum_target_inhg=25.0) -> dict:
    """Create a tap line (INSTALLING)."""
    return _setup_ok(
        api_client.create_tap_line(
            create_tap_line_payload(bush_id, line_code=line_code, tap_count=tap_count,
                                    vacuum_target_inhg=vacuum_target_inhg),
            MANAGER),
        "create tap line")


def activate_line(line_id) -> dict:
    return _setup_ok(api_client.activate_tap_line(line_id, MANAGER), "activate tap line")


def go_live(bush_id) -> dict:
    return _setup_ok(api_client.go_live(bush_id, MANAGER), "go live")


def setup_live_bush(season_id, name="North Woods", tap_capacity=5000, tap_count=100,
                    vacuum_target_inhg=25.0):
    """Bush walked PREP -> TAPPING -> LIVE with one ACTIVE line. Returns (bush, line)."""
    bush = create_bush(season_id, name=name, tap_capacity=tap_capacity)
    begin_tapping(bush["id"])
    line = create_line(bush["id"], tap_count=tap_count, vacuum_target_inhg=vacuum_target_inhg)
    line = activate_line(line["id"])
    bush = go_live(bush["id"])
    return bush, line


def declare_window(season_id, season_version, opens_at="2027-03-01T00:00:00Z",
                   closes_at="2027-03-10T00:00:00Z", forecast_min_f=28.0,
                   forecast_max_f=42.0) -> dict:
    """Declare a weather window (FORECAST) under OCC on the season version."""
    return _setup_ok(
        api_client.create_weather_window(
            create_weather_window_payload(
                season_id, season_version,
                opens_at=opens_at, closes_at=closes_at,
                forecast_min_f=forecast_min_f, forecast_max_f=forecast_max_f),
            MANAGER),
        "declare weather window")


def open_window(window_id, clock=DEFAULT_WINDOW_OPEN_CLOCK) -> dict:
    """Move the clock inside the window and open it (FORECAST -> OPEN)."""
    set_clock(clock)
    return _setup_ok(api_client.open_weather_window(window_id, MANAGER), "open weather window")


def hire_crew_member(season_id, name, crew_role, cert_organic_handler=None) -> dict:
    """Hire a crew member (HIRED). cert_organic_handler omitted unless given."""
    payload = create_crew_member_payload(season_id, name=name, crew_role=crew_role)
    if cert_organic_handler is not None:
        payload["cert_organic_handler"] = cert_organic_handler
    return _setup_ok(api_client.create_crew_member(payload, MANAGER), f"hire {name}")


def activate_crew_member(crew_id) -> dict:
    return _setup_ok(api_client.activate_crew_member(crew_id, MANAGER), "activate crew member")


def hire_active_crew(season_id, name, crew_role, cert_organic_handler=None) -> dict:
    crew = hire_crew_member(season_id, name, crew_role, cert_organic_handler)
    return activate_crew_member(crew["id"])


# ─── Tier 2: Full live-operation composite ──────────────────────────────────

def setup_live_operation(with_boiler=True, with_grader=False, grader_certified=None,
                         open_the_window=True, open_window_at=DEFAULT_WINDOW_OPEN_CLOCK,
                         bush_name="North Woods", tap_capacity=5000, tap_count=100,
                         vacuum_target_inhg=25.0, planned_taps=10000) -> dict:
    """The canonical live chain: season OPEN; bush LIVE with one ACTIVE line;
    window declared (and OPEN unless open_the_window=False); tapper ACTIVE
    (plus boiler / grader when requested).

    Returns a ctx dict: season, bush, line, window, tapper, boiler, grader.
    """
    season = setup_open_season(planned_taps=planned_taps)
    bush, line = setup_live_bush(season_id=season["id"], name=bush_name,
                                 tap_capacity=tap_capacity, tap_count=tap_count,
                                 vacuum_target_inhg=vacuum_target_inhg)
    window = declare_window(season["id"], season["version"])
    tapper = hire_active_crew(season["id"], "Tammy Tapper", "TAPPER")
    boiler = hire_active_crew(season["id"], "Bob Boiler", "BOILER") if with_boiler else None
    grader = (hire_active_crew(season["id"], "Gail Grader", "GRADER",
                               cert_organic_handler=grader_certified)
              if with_grader else None)
    if open_the_window:
        window = open_window(window["id"], open_window_at)
    return {
        "season": season, "bush": bush, "line": line, "window": window,
        "tapper": tapper, "boiler": boiler, "grader": grader,
    }


# ─── Tier 3: Sap runs, batches, lots ────────────────────────────────────────

def collect_confirmed_run(ctx, gallons, measured_brix, clock=None) -> dict:
    """Record a sap run as the ctx tapper (FieldCrew, entity-backed) and confirm it."""
    if clock is not None:
        set_clock(clock)
    headers = make_fieldcrew_headers(ctx["tapper"]["id"])
    run = _setup_ok(
        api_client.create_sap_run(
            create_sap_run_payload(ctx["bush"]["id"], ctx["window"]["id"],
                                   ctx["tapper"]["id"],
                                   gallons_collected=gallons, measured_brix=measured_brix),
            headers),
        "create sap run")
    return _setup_ok(api_client.confirm_sap_run(run["id"], headers), "confirm sap run")


def create_filling_batch(ctx, capacity=200, boiler=None) -> dict:
    """Create an evaporator batch (FILLING) as the ctx boiler (SugarMaker)."""
    boiler = boiler or ctx["boiler"]
    return _setup_ok(
        api_client.create_batch(
            create_batch_payload(ctx["season"]["id"], boiler["id"],
                                 evaporator_capacity_gal=capacity),
            make_sugarmaker_headers(boiler["id"])),
        "create batch")


def draw_from_run(ctx, batch_id, run_id, gallons) -> dict:
    """Manual intake draw from a CONFIRMED run into a FILLING batch."""
    return _setup_ok(
        api_client.create_batch_intake(
            batch_id, create_batch_intake_payload(run_id, gallons),
            make_sugarmaker_headers(ctx["boiler"]["id"])),
        "create batch intake")


def start_boil(ctx, batch_id, clock=None) -> dict:
    if clock is not None:
        set_clock(clock)
    return _setup_ok(
        api_client.start_boil(batch_id, make_sugarmaker_headers(ctx["boiler"]["id"])),
        "start boil")


def finish_batch(ctx, batch_id, finished_brix, measured_syrup_gallons) -> dict:
    return _setup_ok(
        api_client.finish_batch(
            batch_id, create_finish_payload(finished_brix, measured_syrup_gallons),
            make_sugarmaker_headers(ctx["boiler"]["id"])),
        "finish batch")


def get_only_syrup_lot() -> dict:
    """Exactly one syrup lot exists (one lot per finished batch). Returns it."""
    lots = _setup_ok(api_client.list_syrup_lots(MANAGER), "list syrup lots")
    assert isinstance(lots, list) and len(lots) == 1, (
        f"Setup failed: expected exactly one syrup lot, got {len(lots)}")
    return lots[0]


def record_evaluation(ctx, lot_id, flavor_score, defect_flags=None, evaluator=None) -> dict:
    """Record a flavor evaluation as a GRADER crew member (SugarMaker, entity-backed)."""
    evaluator = evaluator or ctx["grader"]
    payload = create_flavor_evaluation_payload(evaluator["id"], flavor_score)
    if defect_flags is not None:
        payload["defect_flags"] = defect_flags
    return _setup_ok(
        api_client.create_flavor_evaluation(
            lot_id, payload, make_sugarmaker_headers(evaluator["id"])),
        "record flavor evaluation")


def grade_lot(ctx, lot_id, light_transmittance_pct, grader=None) -> dict:
    grader = grader or ctx["grader"]
    return _setup_ok(
        api_client.grade_syrup_lot(
            lot_id, create_grade_payload(light_transmittance_pct),
            make_sugarmaker_headers(grader["id"])),
        "grade syrup lot")


# ─── Tier 4: Canonical batch scenarios ──────────────────────────────────────

def setup_batch_x_filling(with_grader=False) -> dict:
    """Batch X through FILLING: run1 100 gal @ 2.0 collected 2027-03-02T00:00:00Z,
    run2 60 gal @ 3.0 collected 2027-03-03T00:00:00Z, both fully drawn into a
    200-gal batch; clock parked at 2027-03-04T12:00:00Z (boil not started).

    Held-sap math: run1 waits 60h (2 full days), run2 waits 36h (1 full day).
    """
    ctx = setup_live_operation(with_grader=with_grader,
                               open_window_at="2027-03-01T12:00:00Z")
    ctx["run1"] = collect_confirmed_run(ctx, 100.0, 2.0, clock="2027-03-02T00:00:00Z")
    ctx["run2"] = collect_confirmed_run(ctx, 60.0, 3.0, clock="2027-03-03T00:00:00Z")
    ctx["batch"] = create_filling_batch(ctx, capacity=200)
    ctx["intake1"] = draw_from_run(ctx, ctx["batch"]["id"], ctx["run1"]["id"], 100.0)
    ctx["intake2"] = draw_from_run(ctx, ctx["batch"]["id"], ctx["run2"]["id"], 60.0)
    set_clock("2027-03-04T12:00:00Z")
    return ctx


def setup_batch_x_boiling(with_grader=False) -> dict:
    """Batch X through start-boil at 2027-03-04T12:00:00Z.

    effective brix 1.6 / 2.8; input_brix 2.05; sap_gallons_in 160.00.
    """
    ctx = setup_batch_x_filling(with_grader=with_grader)
    ctx["batch"] = start_boil(ctx, ctx["batch"]["id"])
    return ctx


def setup_ungraded_lot(measured_syrup_gallons=3.60, finished_brix=66.2,
                       with_grader=False) -> dict:
    """Batch X finished with the given measured gallons; syrup lot created.

    With the defaults the expected yield is 3.72, variance -3.23% (< 15.0),
    so the lot enters UNGRADED with quality_hold_auto false.
    """
    ctx = setup_batch_x_boiling(with_grader=with_grader)
    ctx["batch"] = finish_batch(ctx, ctx["batch"]["id"], finished_brix,
                                measured_syrup_gallons)
    ctx["lot"] = get_only_syrup_lot()
    return ctx


def setup_single_run_graded_lot(measured_syrup_gallons=60.0, transmittance=80.0,
                                flavor_score=90, run_gallons=100.0, run_brix=2.0,
                                finished_brix=66.4) -> dict:
    """Single 100-gal run @ 2.0 collected and boiled same instant (no
    deterioration); batch finished with the given measured gallons, then the
    lot is evaluated and graded.

    Expected yield round(100*2.0/88.2, 2) == 2.27, so a measured value far
    above it (55.0 / 60.0) forces the auto-hold (HELD, quality_hold_auto);
    grading from HELD recomputes the grade the same way. Result: GRADED lot.
    """
    ctx = setup_live_operation(with_grader=True)
    ctx["run"] = collect_confirmed_run(ctx, run_gallons, run_brix)
    ctx["batch"] = create_filling_batch(ctx, capacity=200)
    ctx["intake"] = draw_from_run(ctx, ctx["batch"]["id"], ctx["run"]["id"], run_gallons)
    ctx["batch"] = start_boil(ctx, ctx["batch"]["id"])
    ctx["batch"] = finish_batch(ctx, ctx["batch"]["id"], finished_brix,
                                measured_syrup_gallons)
    ctx["lot_at_finish"] = get_only_syrup_lot()
    record_evaluation(ctx, ctx["lot_at_finish"]["id"], flavor_score)
    ctx["lot"] = grade_lot(ctx, ctx["lot_at_finish"]["id"], transmittance)
    return ctx


def setup_two_lots_for_grade_boundary() -> dict:
    """Two sequential batches (single evaporator: A finishes before B boils),
    each drawing 10 gal of a 20-gal run collected 2027-03-02T08:00:00Z and
    boiled the same instant; each finished measured 0.22 (expected 0.23,
    variance -4.35% -> UNGRADED); each lot has one evaluation flavor_score 90.
    """
    ctx = setup_live_operation(with_grader=True)
    ctx["run"] = collect_confirmed_run(ctx, 20.0, 2.0)
    ctx["batch_a"] = create_filling_batch(ctx, capacity=50)
    draw_from_run(ctx, ctx["batch_a"]["id"], ctx["run"]["id"], 10.0)
    ctx["batch_a"] = start_boil(ctx, ctx["batch_a"]["id"])
    ctx["batch_a"] = finish_batch(ctx, ctx["batch_a"]["id"], 66.5, 0.22)
    set_clock("2027-03-02T08:01:00Z")
    ctx["batch_b"] = create_filling_batch(ctx, capacity=50)
    draw_from_run(ctx, ctx["batch_b"]["id"], ctx["run"]["id"], 10.0)
    ctx["batch_b"] = start_boil(ctx, ctx["batch_b"]["id"])
    ctx["batch_b"] = finish_batch(ctx, ctx["batch_b"]["id"], 66.5, 0.22)
    lots = _setup_ok(api_client.list_syrup_lots(MANAGER), "list syrup lots")
    assert len(lots) == 2, f"Setup failed: expected 2 lots, got {len(lots)}"
    ctx["lot_a"], ctx["lot_b"] = lots[0], lots[1]
    record_evaluation(ctx, ctx["lot_a"]["id"], 90)
    record_evaluation(ctx, ctx["lot_b"]["id"], 90)
    return ctx


# ─── Tier 5: Leases and audits ──────────────────────────────────────────────

def create_lease_on_bush(bush_id, royalty_basis="PER_TAP", per_tap_cents=300,
                         share_pct=None, certified_organic_required=False,
                         term_start="2027-01-01", term_end="2027-12-31",
                         landowner_name="Landowner Lou") -> dict:
    """Create a lease (DRAFT). Only the conditionally-required royalty field
    for the chosen basis is sent (PRD §3.4)."""
    payload = {
        "sugarbush_id": bush_id,
        "landowner_name": landowner_name,
        "royalty_basis": royalty_basis,
        "certified_organic_required": certified_organic_required,
        "term_start": term_start,
        "term_end": term_end,
    }
    if royalty_basis == "PER_TAP":
        payload["per_tap_cents"] = per_tap_cents
    else:
        payload["share_pct"] = share_pct
    return _setup_ok(api_client.create_lease(payload, MANAGER), "create lease")


def submit_lease(lease_id) -> dict:
    return _setup_ok(api_client.submit_lease_audit(lease_id, MANAGER), "submit lease")


def activate_lease(lease_id) -> dict:
    return _setup_ok(api_client.activate_lease(lease_id, MANAGER), "activate lease")


def submit_and_activate_lease(lease_id) -> dict:
    submit_lease(lease_id)
    return activate_lease(lease_id)


def schedule_cert_audit(bush_id, audit_type, scheduled_for) -> dict:
    return _setup_ok(
        api_client.create_cert_audit(
            bush_id, create_cert_audit_payload(audit_type=audit_type,
                                               scheduled_for=scheduled_for),
            INSPECTOR),
        "schedule cert audit")


def record_cert_result(audit_id, result, clock=None) -> dict:
    if clock is not None:
        set_clock(clock)
    return _setup_ok(
        api_client.record_cert_audit_result(audit_id, {"result": result}, INSPECTOR),
        "record cert result")


def setup_leased_live_operation(share_pct=30.0, with_grader=False,
                                open_window_at="2027-03-01T12:00:00Z") -> dict:
    """Season OPEN; bush with an ACTIVE SHARE_OF_SYRUP lease (created on the
    PREP bush, submitted, activated); bush then walked to LIVE with one ACTIVE
    line; window declared and OPEN; tapper/boiler ACTIVE (grader optional).
    """
    season = setup_open_season()
    bush = create_bush(season["id"], name="Leased Hill")
    lease = create_lease_on_bush(bush["id"], royalty_basis="SHARE_OF_SYRUP",
                                 share_pct=share_pct)
    lease = submit_and_activate_lease(lease["id"])
    begin_tapping(bush["id"])
    line = activate_line(create_line(bush["id"])["id"])
    bush = go_live(bush["id"])
    window = declare_window(season["id"], season["version"])
    tapper = hire_active_crew(season["id"], "Tammy Tapper", "TAPPER")
    boiler = hire_active_crew(season["id"], "Bob Boiler", "BOILER")
    grader = (hire_active_crew(season["id"], "Gail Grader", "GRADER")
              if with_grader else None)
    window = open_window(window["id"], open_window_at)
    return {
        "season": season, "bush": bush, "line": line, "window": window,
        "tapper": tapper, "boiler": boiler, "grader": grader, "lease": lease,
    }


def setup_organic_audit_outcome(result, audit_date="2027-02-10",
                                record_clock="2027-02-15T00:00:00Z",
                                bush_name="Organic Knoll") -> dict:
    """Season OPEN (opened at 2027-02-01); bush PREP; one ORGANIC audit
    scheduled for `audit_date` and RECORDED with `result` at `record_clock`.
    """
    season = setup_open_season(clock="2027-02-01T00:00:00Z")
    bush = create_bush(season["id"], name=bush_name, tap_capacity=2000)
    audit = schedule_cert_audit(bush["id"], "ORGANIC", audit_date)
    audit = record_cert_result(audit["id"], result, clock=record_clock)
    return {"season": season, "bush": bush, "audit": audit}
