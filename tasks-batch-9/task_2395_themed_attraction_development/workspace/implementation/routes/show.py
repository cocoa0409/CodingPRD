"""ShowScene and EffectCue endpoints."""

from flask import Blueprint

import auth
import calc
import domain
import response
import store
import validate as V
from errors import ApiError
from routes.common import body, no_body, page, state

bp = Blueprint("show", __name__)

SCENE_READ = (
    auth.OWNER_REP,
    auth.CREATIVE_DIRECTOR,
    auth.SHOW_PROGRAMMER,
    auth.CONTRACTOR_PM,
    auth.PROGRAM_ADMIN,
)
CUE_READ = (auth.OWNER_REP, auth.CREATIVE_DIRECTOR, auth.SHOW_PROGRAMMER, auth.PROGRAM_ADMIN)


def _resolve_predecessor(project_id, predecessor_id):
    """A non-null follows_scene_id must resolve to a scene of the same project."""
    if predecessor_id is None:
        return None
    row = store.show_scenes.get(predecessor_id)
    if row is None or row["project_id"] != project_id:
        raise ApiError("ERR_SCENE_NOT_FOUND", 404)
    return row


def _check_sequence_unique(project_id, sequence_index, exclude_id=None):
    for other in domain.scenes_of(project_id):
        if other["id"] == exclude_id:
            continue
        if other["sequence_index"] == sequence_index:
            raise ApiError("ERR_SCENE_SEQUENCE_DUPLICATE", 409)


# ------------------------------------------------------------------- ShowScene
@bp.post("/show-scenes")
def create_scene():
    auth.authenticate((auth.CREATIVE_DIRECTOR,))
    data = body(
        V.ID("project_id"),
        V.S("scene_label", min_len=1, max_len=80),
        V.I("sequence_index", minimum=1),
        V.I("duration_seconds", minimum=1),
        V.ID("follows_scene_id", required=False, nullable=True),
    )
    project = domain.get_project(data["project_id"])
    predecessor_id = data.get("follows_scene_id")
    _resolve_predecessor(project["id"], predecessor_id)
    domain.check_not_frozen(project)
    _check_sequence_unique(project["id"], data["sequence_index"])

    row = store.base_row()
    if domain.scene_chain_has_cycle(row["id"], predecessor_id):
        raise ApiError("ERR_SCENE_ORDER_CYCLE", 422)
    row["project_id"] = project["id"]
    row["scene_label"] = data["scene_label"]
    row["sequence_index"] = data["sequence_index"]
    row["duration_seconds"] = data["duration_seconds"]
    row["follows_scene_id"] = predecessor_id
    row["lighting_score"] = None
    row["audio_score"] = None
    row["animation_score"] = None
    row["effects_score"] = None
    row["scene_quality_score"] = None
    row["validating_rehearsal_run_id"] = None
    row["status"] = "DRAFT"
    row["held_from_status"] = None
    row["hold_reason"] = None
    store.show_scenes[row["id"]] = row
    return response.created(store.public(row))


@bp.get("/show-scenes")
def list_scenes():
    auth.authenticate(SCENE_READ)
    limit, offset = V.pagination()
    project_id = V.string_filter("project_id")
    follows_scene_id = V.string_filter("follows_scene_id")
    validating_rehearsal_run_id = V.string_filter("validating_rehearsal_run_id")
    status = V.enum_filter("status", V.SCENE_STATUSES)
    rows = store.sorted_rows(list(store.show_scenes.values()))
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if follows_scene_id is not None:
        rows = [r for r in rows if r["follows_scene_id"] == follows_scene_id]
    if validating_rehearsal_run_id is not None:
        rows = [r for r in rows if r["validating_rehearsal_run_id"] == validating_rehearsal_run_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, total = page(rows, limit, offset)
    return response.collection(items, limit, offset, total)


@bp.get("/show-scenes/<row_id>")
def read_scene(row_id):
    auth.authenticate(SCENE_READ)
    return response.ok(store.public(domain.get_scene(row_id)))


@bp.post("/show-scenes/<row_id>/sequence")
def sequence_scene(row_id):
    auth.authenticate((auth.CREATIVE_DIRECTOR,))
    data = body(
        V.I("sequence_index", minimum=1),
        V.ID("follows_scene_id", required=False, nullable=True),
    )
    scene = domain.get_scene(row_id)
    predecessor_id = data.get("follows_scene_id")
    _resolve_predecessor(scene["project_id"], predecessor_id)
    state(scene, ("DRAFT",), "ERR_SCENE_STATE_INVALID")
    project = domain.get_project(scene["project_id"])
    domain.check_not_frozen(project)
    _check_sequence_unique(scene["project_id"], data["sequence_index"], exclude_id=scene["id"])
    if domain.scene_chain_has_cycle(scene["id"], predecessor_id):
        raise ApiError("ERR_SCENE_ORDER_CYCLE", 422)

    scene["sequence_index"] = data["sequence_index"]
    scene["follows_scene_id"] = predecessor_id
    scene["status"] = "SEQUENCED"
    store.touch(scene)
    return response.ok(store.public(scene))


@bp.post("/show-scenes/<row_id>/program")
def program_scene(row_id):
    auth.authenticate((auth.SHOW_PROGRAMMER,))
    data = body(
        V.N("lighting_score", minimum=0, maximum=100, max_dp=2),
        V.N("audio_score", minimum=0, maximum=100, max_dp=2),
        V.N("animation_score", minimum=0, maximum=100, max_dp=2),
        V.N("effects_score", minimum=0, maximum=100, max_dp=2),
    )
    scene = domain.get_scene(row_id)
    state(scene, ("SEQUENCED",), "ERR_SCENE_STATE_INVALID")
    project = domain.get_project(scene["project_id"])
    domain.check_not_frozen(project)
    cues = domain.cues_of_scene(scene["id"])
    if not cues or any(c["status"] != "VERIFIED" for c in cues):
        raise ApiError("ERR_CUES_NOT_VERIFIED", 409)

    scene["lighting_score"] = data["lighting_score"]
    scene["audio_score"] = data["audio_score"]
    scene["animation_score"] = data["animation_score"]
    scene["effects_score"] = data["effects_score"]
    scene["scene_quality_score"] = calc.scene_quality(
        data["lighting_score"], data["audio_score"], data["animation_score"], data["effects_score"]
    )
    scene["status"] = "PROGRAMMED"
    store.touch(scene)
    domain.recompute_show_quality(project)
    store.touch(project)
    return response.ok(store.public(scene))


@bp.post("/show-scenes/<row_id>/validate")
def validate_scene(row_id):
    auth.authenticate((auth.SHOW_PROGRAMMER,))
    data = body(V.ID("rehearsal_run_id"))
    scene = domain.get_scene(row_id)
    run = domain.get_rehearsal_run(data["rehearsal_run_id"])
    state(scene, ("PROGRAMMED",), "ERR_SCENE_STATE_INVALID")
    project = domain.get_project(scene["project_id"])
    domain.check_not_frozen(project)
    if run["project_id"] != scene["project_id"]:
        raise ApiError("ERR_REHEARSAL_RUN_PROJECT_MISMATCH", 422)
    if run["status"] != "COMPLETED" or run["result"] != "PASS":
        raise ApiError("ERR_REHEARSAL_NOT_PASSED", 409)

    scene["validating_rehearsal_run_id"] = run["id"]
    scene["status"] = "VALIDATED"
    store.touch(scene)
    return response.ok(store.public(scene))


@bp.get("/show-scenes/<row_id>/effect-cues")
def scene_cues(row_id):
    auth.authenticate(CUE_READ)
    limit, offset = V.pagination()
    channel = V.enum_filter("discipline_channel", V.DISCIPLINE_CHANNELS)
    scene = domain.get_scene(row_id)
    rows = domain.cues_of_scene(scene["id"])
    if channel is not None:
        rows = [r for r in rows if r["discipline_channel"] == channel]
    items, total = page(rows, limit, offset)
    return response.collection(items, limit, offset, total)


# ------------------------------------------------------------------- EffectCue
@bp.post("/effect-cues")
def create_cue():
    auth.authenticate((auth.SHOW_PROGRAMMER,))
    data = body(
        V.ID("scene_id"),
        V.S("cue_label", min_len=1, max_len=80),
        V.E("discipline_channel", V.DISCIPLINE_CHANNELS),
        V.I("offset_ms", minimum=0),
        V.I("duration_ms", minimum=1),
    )
    scene = domain.get_scene(data["scene_id"])
    if scene["status"] not in ("DRAFT", "SEQUENCED"):
        raise ApiError("ERR_CUE_STATE_INVALID", 409)
    project = domain.get_project(scene["project_id"])
    domain.check_not_frozen(project)

    channel = data["discipline_channel"]
    buffer_ms = calc.INTERLOCK_BUFFER_MS if channel in calc.BUFFERED_CHANNELS else 0
    new_start = data["offset_ms"]
    new_end = new_start + data["duration_ms"]
    for other in domain.cues_of_scene(scene["id"]):
        if other["discipline_channel"] != channel:
            continue
        other_start = other["offset_ms"]
        other_end = other_start + other["duration_ms"]
        if new_start < other_end + buffer_ms and new_end > other_start - buffer_ms:
            raise ApiError("ERR_CUE_CHANNEL_CONFLICT", 409)

    row = store.base_row()
    row["scene_id"] = scene["id"]
    row["cue_label"] = data["cue_label"]
    row["discipline_channel"] = channel
    row["offset_ms"] = data["offset_ms"]
    row["duration_ms"] = data["duration_ms"]
    row["status"] = "PLANNED"
    store.effect_cues[row["id"]] = row
    return response.created(store.public(row))


@bp.get("/effect-cues/<row_id>")
def read_cue(row_id):
    auth.authenticate(CUE_READ)
    return response.ok(store.public(domain.get_cue(row_id)))


@bp.post("/effect-cues/<row_id>/verify")
def verify_cue(row_id):
    auth.authenticate((auth.SHOW_PROGRAMMER,))
    no_body()
    cue = domain.get_cue(row_id)
    scene = domain.get_scene(cue["scene_id"])
    if cue["status"] != "PLANNED" or scene["status"] not in ("DRAFT", "SEQUENCED"):
        raise ApiError("ERR_CUE_STATE_INVALID", 409)
    project = domain.get_project(scene["project_id"])
    domain.check_not_frozen(project)

    cue["status"] = "VERIFIED"
    store.touch(cue)
    return response.ok(store.public(cue))
