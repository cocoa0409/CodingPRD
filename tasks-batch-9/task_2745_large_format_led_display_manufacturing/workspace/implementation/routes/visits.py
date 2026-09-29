"""Commissioning visit endpoints: booking, arrival, on-site calibration, sign-off."""

from flask import Blueprint

import aggregates
import auth
import calc
import envelope
import serializers
import store
import validators as v
from errors import ApiError
from numeric import ceil_frac, to_fraction

bp = Blueprint("visits", __name__)


def _visit_and_crew(visit_id, user_id):
    """Rung 10 then rung 13 — the two checks every crew action shares."""
    visit = store.commissioning_visits.get(visit_id)
    if visit is None:
        raise ApiError("ERR_VISIT_NOT_FOUND")
    if user_id != visit["commissioning_crew_id"]:
        raise ApiError("ERR_CREW_NOT_ASSIGNED")
    return visit


@bp.route("/commissioning-visits", methods=["POST"])
def book_visit():
    auth.require("PlantAdmin", "FieldEngineer")
    body = v.body()
    project_id = v.get_id(body, "project_id")
    crew_id = v.get_id(body, "commissioning_crew_id")
    window_start, window_end = v.get_window(body)

    crew = store.commissioning_crews.get(crew_id)          # rung 4
    if crew is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    project = store.display_projects.get(project_id)        # rung 5
    if project is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND")

    # rung 36 — the overlap check runs BEFORE the licensing check (PRD 3.7).
    cand_start = store.ms(window_start)
    cand_end = store.ms(window_end)
    for other in store.commissioning_visits.values():
        if other["commissioning_crew_id"] != crew_id:
            continue
        if other["visit_state"] not in ("SCHEDULED", "ON_SITE", "CALIBRATED"):
            continue
        ex_start = store.ms(other["window_start"])
        ex_end = store.ms(other["window_end"])
        if cand_start < ex_end and ex_start < cand_end:      # HALF-OPEN overlap
            raise ApiError("ERR_CREW_DOUBLE_BOOKED")
    # rung 37
    if crew["region_code"] != project["site_region_code"]:
        raise ApiError("ERR_CREW_REGION_MISMATCH")

    rec = store.new_record({
        "project_id": project_id,
        "commissioning_crew_id": crew_id,
        "window_start": window_start,
        "window_end": window_end,
        "visit_state": "SCHEDULED",
        "measured_uniformity_pct": None,
        "measured_brightness_nits": None,
        "arrived_at": None,
        "signed_off_at": None,
        "abort_reason": None,
    })
    store.commissioning_visits[rec["id"]] = rec
    store.touch(crew)
    return envelope.object_response(serializers.commissioning_visit(rec), 201)


@bp.route("/commissioning-visits/<commissioning_visit_id>/arrive", methods=["POST"])
def arrive(commissioning_visit_id):
    user_id, _ = auth.require("FieldEngineer")
    v.body()
    visit = _visit_and_crew(commissioning_visit_id, user_id)
    if visit["visit_state"] != "SCHEDULED":                  # rung 22
        raise ApiError("ERR_INVALID_VISIT_STATE")
    project = store.display_projects.get(visit["project_id"])
    if project is None or project["production_state"] != "INSTALLED":   # rung 25
        raise ApiError("ERR_CABINETS_NOT_MOUNTED")
    now = store.logical_now()
    # rung 34 — half-open: window_start <= clock < window_end
    if not (store.ms(visit["window_start"]) <= store.ms(now)
            < store.ms(visit["window_end"])):
        raise ApiError("ERR_VISIT_WINDOW_NOT_CURRENT")

    visit["arrived_at"] = now
    visit["visit_state"] = "ON_SITE"
    store.touch(visit)
    return envelope.object_response(serializers.commissioning_visit(visit))


@bp.route("/commissioning-visits/<commissioning_visit_id>/calibrate", methods=["POST"])
def calibrate(commissioning_visit_id):
    user_id, _ = auth.require("FieldEngineer")
    body = v.body()
    brightness = v.get_int(body, "measured_brightness_nits", minimum=0)
    uniformity = v.get_num(body, "measured_uniformity_pct", minimum=0)

    visit = _visit_and_crew(commissioning_visit_id, user_id)
    if visit["visit_state"] != "ON_SITE":                    # rung 22
        raise ApiError("ERR_INVALID_VISIT_STATE")
    project = store.display_projects.get(visit["project_id"])
    floor_nits = ceil_frac(to_fraction(project["target_brightness_nits"])
                           * calc.ON_SITE_BRIGHTNESS_FLOOR_FRACTION)
    if brightness < floor_nits:
        v.fail("measured_brightness_nits is below the on-site acceptance floor.")
    if to_fraction(uniformity) < calc.ON_SITE_MIN_UNIFORMITY_PCT:
        v.fail("measured_uniformity_pct is below the on-site acceptance floor.")

    visit["measured_brightness_nits"] = brightness
    visit["measured_uniformity_pct"] = uniformity
    visit["visit_state"] = "CALIBRATED"
    store.touch(visit)
    return envelope.object_response(serializers.commissioning_visit(visit))


@bp.route("/commissioning-visits/<commissioning_visit_id>/sign-off", methods=["POST"])
def sign_off(commissioning_visit_id):
    user_id, _ = auth.require("FieldEngineer")
    v.body()
    visit = _visit_and_crew(commissioning_visit_id, user_id)
    if visit["visit_state"] != "CALIBRATED":                 # rung 22
        raise ApiError("ERR_INVALID_VISIT_STATE")
    project = store.display_projects.get(visit["project_id"])
    if project is None or project["production_state"] != "INSTALLED":   # rung 25
        raise ApiError("ERR_CABINETS_NOT_MOUNTED")

    now = store.logical_now()
    # hop 1
    visit["signed_off_at"] = now
    visit["visit_state"] = "SIGNED_OFF"
    store.touch(visit)
    # hop 2
    project["production_state"] = "COMMISSIONED"
    store.touch(project)
    # hop 3
    aggregates.activate_contracts_for(project, now)
    # hop 4 — the crew's live booking count drops
    crew = store.commissioning_crews.get(visit["commissioning_crew_id"])
    if crew is not None:
        store.touch(crew)
    return envelope.object_response(serializers.commissioning_visit(visit))


@bp.route("/commissioning-visits/<commissioning_visit_id>", methods=["GET"])
def get_visit(commissioning_visit_id):
    auth.require(*auth.ALL_ROLES)
    visit = store.commissioning_visits.get(commissioning_visit_id)
    if visit is None:
        raise ApiError("ERR_VISIT_NOT_FOUND")
    return envelope.object_response(serializers.commissioning_visit(visit))


@bp.route("/commissioning-visits", methods=["GET"])
def list_visits():
    auth.require(*auth.ALL_ROLES)
    limit, offset = v.pagination()
    project_id = v.query_str("project_id")
    crew_id = v.query_str("commissioning_crew_id")
    state = v.query_enum("visit_state", calc.VISIT_STATES)
    rows = aggregates.by_created(store.commissioning_visits.values())
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if crew_id is not None:
        rows = [r for r in rows if r["commissioning_crew_id"] == crew_id]
    if state is not None:
        rows = [r for r in rows if r["visit_state"] == state]
    return envelope.paginated(rows, limit, offset, serializers.commissioning_visit)
