from flask import Blueprint, g, request

from core import (ApiError, body, db, list_response, new_resource, ok,
                  req_enum, req_int, require_roles, touch)
from logic import WAVE_TERMINAL, compute_weights
from serializers import ser_snapshot

bp = Blueprint("snapshots", __name__)


def get_snapshot_or_404(snapshot_id):
    s = db.snapshots.get(snapshot_id)
    if s is None:
        raise ApiError("ERR_SNAPSHOT_NOT_FOUND", 404, "Weight snapshot not found")
    return s


@bp.post("/feedback-panel/survey-waves/<wave_id>/weight-snapshots")
@require_roles("DataAnalyst")
def create_snapshot(wave_id):
    wave = db.waves.get(wave_id)
    if wave is None:
        raise ApiError("ERR_WAVE_NOT_FOUND", 404, "Survey wave not found")
    data = body()
    method = req_enum(data, "method", ("RIM", "POST_STRAT"))
    expected = req_int(data, "expected_wave_version")
    if expected != wave["version"]:
        raise ApiError("ERR_STALE_WAVE_VERSION", 412,
                       "expected_wave_version does not match the wave's current version")
    if wave["status"] in WAVE_TERMINAL:
        raise ApiError("ERR_WAVE_ALREADY_TERMINAL", 409, "Wave is terminal")
    if wave["status"] not in ("CLOSED", "WEIGHTED"):
        raise ApiError("ERR_WAVE_INVALID_STATE", 409,
                       "Snapshot creation requires wave status CLOSED or WEIGHTED")
    computed = compute_weights(wave, method)
    # Supersede history before recording the new snapshot.
    for s in db.snapshots.values():
        if s["wave_id"] == wave["id"] and s["status"] in ("PROVISIONAL", "FINALIZED"):
            s["status"] = "SUPERSEDED"
            touch(s)
    if wave["status"] == "WEIGHTED":
        wave["status"] = "CLOSED"
    touch(wave)
    snap = new_resource()
    snap.update({
        "wave_id": wave["id"],
        "method": method,
        "weight_mass": computed["weight_mass"],
        "accepted_count": computed["accepted_count"],
        "design_effect": computed["design_effect"],
        "weighted_cell_shares": computed["weighted_cell_shares"],
        "status": "PROVISIONAL",
        "finalized_by_user_id": None,
    })
    db.snapshots[snap["id"]] = snap
    return ok(ser_snapshot(snap), 201)


@bp.get("/feedback-panel/weight-snapshots")
@require_roles("DataAnalyst", "PrivacyOfficer")
def list_snapshots():
    items = list(db.snapshots.values())
    wave_id = request.args.get("wave_id")
    if wave_id is not None:
        items = [s for s in items if s["wave_id"] == wave_id]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return list_response(items, ser_snapshot)


@bp.get("/feedback-panel/weight-snapshots/<snapshot_id>")
@require_roles("DataAnalyst", "PrivacyOfficer")
def get_snapshot(snapshot_id):
    return ok(ser_snapshot(get_snapshot_or_404(snapshot_id)))


@bp.post("/feedback-panel/weight-snapshots/<snapshot_id>/finalize")
@require_roles("DataAnalyst")
def finalize(snapshot_id):
    s = get_snapshot_or_404(snapshot_id)
    wave = db.waves[s["wave_id"]]
    if wave["status"] != "CLOSED":
        raise ApiError("ERR_WAVE_NOT_CLOSED", 409,
                       "Snapshot finalize requires wave status CLOSED")
    if s["status"] != "PROVISIONAL":
        raise ApiError("ERR_SNAPSHOT_SUPERSEDED", 409,
                       "Only the wave's latest, non-SUPERSEDED snapshot can finalize")
    s["status"] = "FINALIZED"
    s["finalized_by_user_id"] = g.user_id
    touch(s)
    wave["status"] = "WEIGHTED"
    touch(wave)
    return ok(ser_snapshot(s))
