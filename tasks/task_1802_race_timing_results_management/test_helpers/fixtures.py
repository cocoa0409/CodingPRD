"""Composite setup helpers for multi-step test prerequisites.

Every test starts against an empty database, so these builders walk the full
chain — race, timing layout, waves, chips, registrations, lock, wave starts,
reads, publish/finalize/certify — using only PRD-declared endpoints. They use
get_success_data() internally so setup failures surface as clear
"Setup step failed" errors rather than confusing assertion failures.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_chip_payload,
    create_race_payload,
    create_registration_payload,
    create_timing_point_payload,
    create_timing_read_payload,
    create_wave_payload,
)
from .test_users import (
    make_certification_officer_headers,
    make_race_director_headers,
    make_race_official_headers,
    make_registration_clerk_headers,
    make_timing_operator_headers,
)

DIRECTOR = make_race_director_headers("director-1")
OPERATOR = make_timing_operator_headers("operator-1")
CLERK = make_registration_clerk_headers("clerk-1")
OFFICIAL = make_race_official_headers("official-1")


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, DIRECTOR))


def _advance_clock(iso, seconds):
    base = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (base + timedelta(seconds=seconds)).astimezone(
        timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── Tier 1/2: race construction engine ─────────────────────────────


def build_race(*, name, distance_km, cutoff_minutes, course_type="CERTIFIED_COURSE",
               qualifying_standard_ms=None, points=(), waves=(), chips=(),
               registrations=(), lock=True, lock_user_id="director-1",
               setup_clock=TEST_DEFAULTS["SETUP_CLOCK"],
               race_date=TEST_DEFAULTS["RACE_DATE"]):
    """Build a race through its pre-race lifecycle.

    points: dicts with key/point_index/kind/distance_km (+ optional device_id,
        deploy_at, expected_teardown_at, deploy=False to leave PLANNED).
    waves: dicts with key/wave_index/scheduled_start_time/max_capacity.
    chips: dicts with key/chip_code.
    registrations: dicts with key/wave/bib_number/participant_name/birth_date/
        gender (+ optional chip=<chip key>, pay=False, confirm=False,
        assign=False to stop earlier in the lifecycle).

    Returns a ctx dict: race, points, waves, chips, regs (all keyed dicts).
    Each registration is created under a logical clock advanced one second
    beyond the previous, so created_at strictly increases in list order.
    """
    set_clock(setup_clock)
    payload = create_race_payload(name=name, race_date=race_date,
                                  distance_km=distance_km, course_type=course_type,
                                  course_time_limit_minutes=cutoff_minutes)
    if qualifying_standard_ms is not None:
        payload["qualifying_standard_ms"] = qualifying_standard_ms
    race = get_success_data(api_client.create_race(payload, DIRECTOR))
    race = get_success_data(api_client.open_registration(race["id"], DIRECTOR))

    point_map = {}
    for p in points:
        point = get_success_data(api_client.create_timing_point(
            create_timing_point_payload(
                race["id"], p["point_index"], p["kind"], p["distance_km"],
                p.get("device_id", f"MAT-{p['point_index']:02d}"),
                p.get("deploy_at"), p.get("expected_teardown_at")),
            OPERATOR))
        if p.get("deploy", True):
            point = get_success_data(api_client.deploy_timing_point(point["id"], OPERATOR))
        point_map[p["key"]] = point

    wave_map = {}
    for w in waves:
        wave_map[w["key"]] = get_success_data(api_client.create_wave(
            create_wave_payload(race["id"], w["wave_index"], w["scheduled_start_time"],
                                w["max_capacity"]),
            DIRECTOR))

    chip_map = {}
    for c in chips:
        chip_map[c["key"]] = get_success_data(
            api_client.create_chip(create_chip_payload(c["chip_code"]), CLERK))

    reg_map = {}
    for idx, r in enumerate(registrations):
        # Distinct logical creation instants keep created_at strictly ordered.
        set_clock(_advance_clock(setup_clock, idx + 1))
        reg = get_success_data(api_client.create_registration(
            create_registration_payload(
                race["id"], wave_map[r["wave"]]["id"], r["bib_number"],
                r["participant_name"], r["birth_date"], r["gender"]),
            CLERK))
        if r.get("pay", True):
            reg = get_success_data(api_client.pay_registration(reg["id"], CLERK))
        if r.get("confirm", True):
            reg = get_success_data(api_client.confirm_registration(reg["id"], CLERK))
        reg_map[r["key"]] = reg

    if lock:
        race = get_success_data(api_client.lock_timing(
            race["id"], make_race_director_headers(lock_user_id)))

    for idx, r in enumerate(registrations):
        if r.get("chip") and r.get("assign", True):
            reg_map[r["key"]] = get_success_data(api_client.assign_chip(
                reg_map[r["key"]]["id"], chip_map[r["chip"]]["id"], CLERK))

    return {"race": race, "points": point_map, "waves": wave_map,
            "chips": chip_map, "regs": reg_map, "lock_user_id": lock_user_id}


# ─── Tier 3: race-day execution ─────────────────────────────────────


def start_waves(ctx, wave_start_times):
    """Start waves at logical instants: {wave_key: iso_timestamp}."""
    for key, ts in wave_start_times.items():
        set_clock(ts)
        ctx["waves"][key] = get_success_data(
            api_client.start_wave(ctx["waves"][key]["id"], OPERATOR))
    return ctx


def ingest_reads(ctx, reads, capture_key=None):
    """Ingest chip reads: dicts with point=<point key>, chip=<chip key>, ts=iso.

    Returns {key: read} only for entries that carry a "key"."""
    captured = {}
    for r in reads:
        read = get_success_data(api_client.create_timing_read(
            create_timing_read_payload(ctx["points"][r["point"]]["id"],
                                       ctx["chips"][r["chip"]]["id"], r["ts"]),
            OPERATOR))
        if r.get("key"):
            captured[r["key"]] = read
    ctx.setdefault("reads", {}).update(captured)
    return ctx


def race_version(ctx):
    race = get_success_data(api_client.get_race(ctx["race"]["id"], DIRECTOR))
    ctx["race"] = race
    return race["version"]


def publish_race(ctx, at_time):
    """Set the logical clock, observe the race version, publish (OCC)."""
    set_clock(at_time)
    version = race_version(ctx)
    ctx["race"] = get_success_data(
        api_client.publish_results(ctx["race"]["id"], version, DIRECTOR))
    return ctx


def finalize_race(ctx, at_time):
    set_clock(at_time)
    ctx["race"] = get_success_data(
        api_client.finalize_results(ctx["race"]["id"], DIRECTOR))
    return ctx


def certify_race(ctx, officer_user_id="cert-1"):
    return get_success_data(api_client.certify_race(
        ctx["race"]["id"], make_certification_officer_headers(officer_user_id)))


def get_race(ctx):
    ctx["race"] = get_success_data(api_client.get_race(ctx["race"]["id"], DIRECTOR))
    return ctx["race"]


def get_result_for_registration(registration_id):
    """Exactly one result per registration; returns the row or None."""
    data, _meta = validate_paginated(
        api_client.list_results(OFFICIAL, params={"registration_id": registration_id}))
    assert len(data) <= 1, f"expected at most one result for {registration_id}"
    return data[0] if data else None


def list_flags(registration_id, **extra_params):
    params = {"registration_id": registration_id}
    params.update(extra_params)
    data, meta = validate_paginated(api_client.list_result_flags(OFFICIAL, params=params))
    return data, meta


def find_awards(race_id, category=None, place=None, status=None):
    params = {}
    if category is not None:
        params["category"] = category
    if status is not None:
        params["status"] = status
    data, _meta = validate_paginated(
        api_client.list_race_awards(race_id, OFFICIAL, params=params))
    if place is not None:
        data = [a for a in data if a["place"] == place]
    return data


# ─── Tier 4/5: named composite scenarios ────────────────────────────


def setup_single_finisher_published_race(
        *, name="Solo 10K", distance_km=10.0, course_type="CERTIFIED_COURSE",
        cutoff_minutes=120, qualifying_standard_ms=None,
        start_ts="2026-08-01T07:00:05.000Z", finish_ts="2026-08-01T07:30:05.000Z",
        wave_start="2026-08-01T07:00:00Z", publish_time="2026-08-01T09:00:00Z",
        birth_date="1990-01-01", gender="M", bib_number="920",
        participant_name="Solo Runner", chip_code="CHIP-SOLO",
        lock_user_id="director-1"):
    """Race with START+FINISH layout, one CHECKED_IN finisher with both reads,
    published PROVISIONAL at publish_time. Returns ctx with reads captured as
    'start_read' and 'finish_read'."""
    ctx = build_race(
        name=name, distance_km=distance_km, course_type=course_type,
        cutoff_minutes=cutoff_minutes, qualifying_standard_ms=qualifying_standard_ms,
        points=[
            {"key": "start", "point_index": 1, "kind": "START", "distance_km": 0.0},
            {"key": "finish", "point_index": 2, "kind": "FINISH",
             "distance_km": distance_km},
        ],
        waves=[{"key": "w1", "wave_index": 1, "scheduled_start_time": wave_start,
                "max_capacity": 10}],
        chips=[{"key": "c1", "chip_code": chip_code}],
        registrations=[{"key": "r1", "wave": "w1", "bib_number": bib_number,
                        "participant_name": participant_name, "birth_date": birth_date,
                        "gender": gender, "chip": "c1"}],
        lock_user_id=lock_user_id,
    )
    start_waves(ctx, {"w1": wave_start})
    ingest_reads(ctx, [
        {"point": "start", "chip": "c1", "ts": start_ts, "key": "start_read"},
        {"point": "finish", "chip": "c1", "ts": finish_ts, "key": "finish_read"},
    ])
    publish_race(ctx, publish_time)
    return ctx


def setup_divergence_race(*, publish_time="2026-08-01T09:00:00Z", finalize=False,
                          finalize_time="2026-08-01T09:30:00Z", certify=False,
                          cert_user_id="cert-1", name="Divergence 10K"):
    """Two-wave 10km race whose gun and chip rankings disagree.

    A (wave 1, started 07:00): START 07:00:05, SPLIT5k 07:16:05, FINISH 07:32:05
        -> chip 1920000, gun 1925000.
    B (wave 2, started 07:10): START 07:10:30, SPLIT5k 07:26:15, FINISH 07:42:20
        -> chip 1910000, gun 1940000.
    """
    ctx = build_race(
        name=name, distance_km=10.0, cutoff_minutes=120,
        qualifying_standard_ms=1800000,
        points=[
            {"key": "start", "point_index": 1, "kind": "START", "distance_km": 0.0},
            {"key": "split5", "point_index": 2, "kind": "SPLIT", "distance_km": 5.0},
            {"key": "finish", "point_index": 3, "kind": "FINISH", "distance_km": 10.0},
        ],
        waves=[
            {"key": "w1", "wave_index": 1,
             "scheduled_start_time": "2026-08-01T07:00:00Z", "max_capacity": 100},
            {"key": "w2", "wave_index": 2,
             "scheduled_start_time": "2026-08-01T07:10:00Z", "max_capacity": 100},
        ],
        chips=[{"key": "ca", "chip_code": "CHIP-A"},
               {"key": "cb", "chip_code": "CHIP-B"}],
        registrations=[
            {"key": "a", "wave": "w1", "bib_number": "101",
             "participant_name": "Athlete A", "birth_date": "1990-01-01",
             "gender": "M", "chip": "ca"},
            {"key": "b", "wave": "w2", "bib_number": "102",
             "participant_name": "Athlete B", "birth_date": "1990-06-15",
             "gender": "M", "chip": "cb"},
        ],
    )
    start_waves(ctx, {"w1": "2026-08-01T07:00:00Z", "w2": "2026-08-01T07:10:00Z"})
    ingest_reads(ctx, [
        {"point": "start", "chip": "ca", "ts": "2026-08-01T07:00:05.000Z"},
        {"point": "split5", "chip": "ca", "ts": "2026-08-01T07:16:05.000Z"},
        {"point": "finish", "chip": "ca", "ts": "2026-08-01T07:32:05.000Z"},
        {"point": "start", "chip": "cb", "ts": "2026-08-01T07:10:30.000Z"},
        {"point": "split5", "chip": "cb", "ts": "2026-08-01T07:26:15.000Z"},
        {"point": "finish", "chip": "cb", "ts": "2026-08-01T07:42:20.000Z",
         "key": "b_finish_read"},
    ])
    publish_race(ctx, publish_time)
    if finalize:
        finalize_race(ctx, finalize_time)
    if certify:
        ctx["certification"] = certify_race(ctx, cert_user_id)
    return ctx
