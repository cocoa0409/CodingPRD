from datetime import timedelta

from flask import Blueprint, request

import clock
import db
from db import new_entity, touch
from errors import (
    ApiError,
    ERR_COURSE_NOT_CERTIFIED,
    ERR_FLAGS_OUTSTANDING,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_PROTESTS_OUTSTANDING,
    ERR_PROTEST_WINDOW_OPEN,
    ERR_RACE_CUTOFF_NOT_REACHED,
    ERR_SOD_VIOLATION,
    ERR_STALE_RACE_VERSION,
    ERR_TIMING_CONFIG_INCOMPLETE,
)
from middleware import endpoint, ALL_ROLES, STAFF_ROLES
from response import ok
from serializers import (
    ser_award,
    ser_certification,
    ser_race,
    ser_timing_point,
    ser_wave,
)
from services import recompute as engine
from util import fmt_dt, fmt_km
from validators import (
    get_body,
    get_or_404,
    list_page,
    v_enum,
    v_int,
    v_num,
    v_str,
    v_dt,
)

bp = Blueprint("races", __name__)


@bp.post("/race-timing/races")
@endpoint("RaceDirector")
def create_race():
    body = get_body(
        ("name", "race_date", "distance_km", "course_type", "course_time_limit_minutes")
    )
    name = v_str(body, "name")
    race_date = v_dt(body, "race_date")
    distance_km = v_num(body, "distance_km")
    if distance_km <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "distance_km must be greater than zero")
    course_type = v_enum(body, "course_type", ("CERTIFIED_COURSE", "UNCERTIFIED_COURSE"))
    limit_min = v_int(body, "course_time_limit_minutes")
    if limit_min <= 0:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "course_time_limit_minutes must be greater than zero"
        )
    qs = body.get("qualifying_standard_ms")
    if qs is not None:
        qs = v_int(body, "qualifying_standard_ms")

    race = new_entity()
    race.update(
        {
            "name": name,
            "race_date": race_date,
            "distance_km": distance_km,
            "course_type": course_type,
            "course_time_limit_minutes": limit_min,
            "qualifying_standard_ms": qs,
            "status": "DRAFT",
            "timing_locked_at": None,
            "locked_by_user_id": None,
            "timing_config_fingerprint": None,
            "provisional_published_at": None,
            "protest_window_closes_at": None,
            "finalized_at": None,
            "amendment_count": 0,
        }
    )
    db.races[race["id"]] = race
    return ok(ser_race(race), 201)


@bp.get("/race-timing/races/<race_id>")
@endpoint(*ALL_ROLES)
def get_race(race_id):
    return ok(ser_race(get_or_404(db.races, race_id)))


@bp.get("/race-timing/races/<race_id>/waves")
@endpoint(*ALL_ROLES)
def list_race_waves(race_id):
    get_or_404(db.races, race_id)
    items = [w for w in db.waves.values() if w["race_id"] == race_id]
    return list_page(items, ser_wave)


@bp.get("/race-timing/races/<race_id>/timing-points")
@endpoint(*STAFF_ROLES)
def list_race_timing_points(race_id):
    get_or_404(db.races, race_id)
    items = [p for p in db.timing_points.values() if p["race_id"] == race_id]
    return list_page(items, ser_timing_point)


@bp.get("/race-timing/races/<race_id>/certifications")
@endpoint(*ALL_ROLES)
def list_race_certifications(race_id):
    get_or_404(db.races, race_id)
    items = [c for c in db.certifications.values() if c["race_id"] == race_id]
    return list_page(items, ser_certification)


@bp.get("/race-timing/races/<race_id>/awards")
@endpoint(*ALL_ROLES)
def list_race_awards(race_id):
    get_or_404(db.races, race_id)
    items = [a for a in db.awards.values() if a["race_id"] == race_id]
    category = request.args.get("category")
    if category is not None:
        items = [a for a in items if a["category"] == category]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_page(items, ser_award)


@bp.post("/race-timing/races/<race_id>/open-registration")
@endpoint("RaceDirector")
def open_registration(race_id):
    race = get_or_404(db.races, race_id)
    if race["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Race is not in DRAFT")
    race["status"] = "REGISTRATION_OPEN"
    touch(race)
    return ok(ser_race(race))


@bp.post("/race-timing/races/<race_id>/lock-timing")
@endpoint("RaceDirector")
def lock_timing(race_id):
    race = get_or_404(db.races, race_id)
    if race["status"] != "REGISTRATION_OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Race is not in REGISTRATION_OPEN")
    points = engine.race_points(race_id)
    race_waves = [w for w in db.waves.values() if w["race_id"] == race_id]
    deployed = [p for p in points if p["status"] == "DEPLOYED"]
    deployed_starts = [p for p in deployed if p["kind"] == "START"]
    deployed_finishes = [
        p
        for p in deployed
        if p["kind"] == "FINISH" and float(p["distance_km"]) == float(race["distance_km"])
    ]
    planned = [p for p in points if p["status"] == "PLANNED"]
    if (
        len(race_waves) < 1
        or len(deployed_starts) != 1
        or len(deployed_finishes) != 1
        or len(planned) != 0
    ):
        raise ApiError(
            ERR_TIMING_CONFIG_INCOMPLETE,
            409,
            "Lock-timing requires at least one wave, exactly one DEPLOYED START, "
            "exactly one DEPLOYED FINISH matching the race distance, and zero "
            "PLANNED points",
        )
    deployed.sort(key=lambda p: p["point_index"])
    fingerprint = ",".join(
        "{}:{}:{}".format(p["point_index"], p["kind"], fmt_km(p["distance_km"]))
        for p in deployed
    )
    race["status"] = "TIMING_LOCKED"
    race["timing_locked_at"] = clock.now()
    race["locked_by_user_id"] = request.user_id
    race["timing_config_fingerprint"] = fingerprint
    touch(race)
    return ok(ser_race(race))


@bp.post("/race-timing/races/<race_id>/publish-results")
@endpoint("RaceDirector")
def publish_results(race_id):
    race = get_or_404(db.races, race_id)
    body = get_body(("expected_race_version",))
    expected = v_int(body, "expected_race_version")
    # state first
    if race["status"] not in ("IN_PROGRESS", "AMENDMENT_OPEN"):
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            "Race must be IN_PROGRESS or AMENDMENT_OPEN to publish results",
        )
    # then concurrency
    if expected != race["version"]:
        raise ApiError(
            ERR_STALE_RACE_VERSION,
            412,
            "expected_race_version does not match the current race version",
        )
    # then the cutoff
    started = [
        w
        for w in db.waves.values()
        if w["race_id"] == race_id and w["status"] == "STARTED"
    ]
    if not started:
        raise ApiError(ERR_INVALID_STATE, 409, "No wave of the race has started")
    earliest = min(w["actual_start_time"] for w in started)
    cutoff = earliest + timedelta(minutes=race["course_time_limit_minutes"])
    if clock.now_sec() < cutoff:
        raise ApiError(
            ERR_RACE_CUTOFF_NOT_REACHED,
            409,
            "Course time limit has not elapsed since the first wave start",
        )
    engine.publish_race(race)
    return ok(ser_race(race))


@bp.post("/race-timing/races/<race_id>/finalize-results")
@endpoint("RaceDirector")
def finalize_results(race_id):
    race = get_or_404(db.races, race_id)
    if race["status"] != "PROVISIONAL_PUBLISHED":
        raise ApiError(ERR_INVALID_STATE, 409, "Race is not PROVISIONAL_PUBLISHED")
    if clock.now_sec() < race["protest_window_closes_at"]:
        raise ApiError(
            ERR_PROTEST_WINDOW_OPEN, 409, "The protest window is still open"
        )
    if any(
        p["race_id"] == race_id and p["status"] == "FILED"
        for p in db.protests.values()
    ):
        raise ApiError(
            ERR_PROTESTS_OUTSTANDING, 409, "Filed protests remain for the race"
        )
    reg_ids = {
        r["id"] for r in db.registrations.values() if r["race_id"] == race_id
    }
    if any(
        f["registration_id"] in reg_ids and f["status"] == "RAISED"
        for f in db.result_flags.values()
    ):
        raise ApiError(
            ERR_FLAGS_OUTSTANDING, 409, "Raised result flags remain for the race"
        )
    for res in db.results.values():
        if res["race_id"] == race_id and res["status"] == "PROVISIONAL":
            res["status"] = "OFFICIAL"
            touch(res)
    for a in db.awards.values():
        if a["race_id"] == race_id and a["status"] == "PROJECTED":
            a["status"] = "CONFIRMED"
            touch(a)
    race["status"] = "FINALIZED"
    race["finalized_at"] = clock.now()
    touch(race)
    return ok(ser_race(race))


@bp.post("/race-timing/races/<race_id>/certify")
@endpoint("CertificationOfficer")
def certify(race_id):
    race = get_or_404(db.races, race_id)
    # state first
    if race["status"] != "FINALIZED":
        raise ApiError(ERR_INVALID_STATE, 409, "Race is not FINALIZED")
    # then the duty rule
    if request.user_id == race["locked_by_user_id"]:
        raise ApiError(
            ERR_SOD_VIOLATION,
            403,
            "The certification issuer must differ from the user who locked timing",
        )
    # then the course requirement
    if race["course_type"] != "CERTIFIED_COURSE":
        raise ApiError(
            ERR_COURSE_NOT_CERTIFIED, 422, "Race course is not a certified course"
        )
    # dockets re-checked
    if any(
        p["race_id"] == race_id and p["status"] == "FILED"
        for p in db.protests.values()
    ):
        raise ApiError(
            ERR_PROTESTS_OUTSTANDING, 409, "Filed protests remain for the race"
        )
    reg_ids = {
        r["id"] for r in db.registrations.values() if r["race_id"] == race_id
    }
    if any(
        f["registration_id"] in reg_ids and f["status"] == "RAISED"
        for f in db.result_flags.values()
    ):
        raise ApiError(
            ERR_FLAGS_OUTSTANDING, 409, "Raised result flags remain for the race"
        )

    cert = None
    for c in db.certifications.values():
        if c["race_id"] == race_id:
            cert = c
            break
    qualified_count = sum(
        1 for r in db.results.values() if r["race_id"] == race_id and r["qualified"]
    )
    if cert is None:
        cert = new_entity()
        cert.update(
            {
                "race_id": race_id,
                "status": "ISSUED",
                "issued_by_user_id": request.user_id,
                "issued_at": clock.now(),
                "qualified_count": qualified_count,
                "revocation_reason": None,
            }
        )
        db.certifications[cert["id"]] = cert
    else:
        cert["status"] = "ISSUED"
        cert["issued_by_user_id"] = request.user_id
        cert["issued_at"] = clock.now()
        cert["qualified_count"] = qualified_count
        cert["revocation_reason"] = None
        touch(cert)
    return ok(ser_certification(cert))


@bp.get("/race-timing/races/<race_id>/live-board")
@endpoint(*ALL_ROLES)
def live_board(race_id):
    race = get_or_404(db.races, race_id)
    bib = request.args.get("bib_number")
    return ok(engine.build_live_board(race, bib))
