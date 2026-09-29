"""Titles, cuts, characters and platform specifications."""
from flask import Blueprint, request

import calc
from auth import ALL_ROLES, auth
from domain import get_cut, get_character, get_spec, get_title, rows_where
from errors import ApiError
from responses import created, ok, paged
from store import db, new_row, serialize, touch
from validate import body, v_array, v_bool, v_enum, v_int, v_number, v_string

bp = Blueprint("catalog", __name__)

CONTENT_RATINGS = ("GENERAL", "TEEN", "MATURE")
STEM_LAYOUTS = ("STEREO_ME", "FIVE_ONE_ME")


# --------------------------------------------------------------------------
# Titles
# --------------------------------------------------------------------------
@bp.post("/titles")
@auth("ProductionCoordinator")
def create_title():
    data = body()
    title_code = v_string(data, "title_code")
    source_language = v_string(data, "source_language")
    runtime_seconds = v_int(data, "runtime_seconds", minimum=1)
    content_rating = v_enum(data, "content_rating", CONTENT_RATINGS, required=False, default="GENERAL")
    for row in db.titles.values():
        if row["title_code"] == title_code:
            raise ApiError("ERR_INVALID_REQUEST", "title_code must be unique.")
    row = new_row({
        "title_code": title_code,
        "source_language": source_language,
        "runtime_seconds": runtime_seconds,
        "content_rating": content_rating,
        "cut_count": 0,
    })
    db.titles[row["id"]] = row
    return created(serialize(row))


@bp.get("/titles/<title_id>")
@auth(*ALL_ROLES)
def read_title(title_id):
    return ok(serialize(get_title(title_id)))


# --------------------------------------------------------------------------
# Cuts
# --------------------------------------------------------------------------
def _assert_cut_code_unique(title_id, cut_code):
    for row in db.cuts.values():
        if row["title_id"] == title_id and row["cut_code"] == cut_code:
            raise ApiError("ERR_INVALID_REQUEST", "cut_code must be unique per title.")


@bp.post("/cuts")
@auth("ProductionCoordinator")
def create_cut():
    data = body()
    title = get_title(data.get("title_id"))          # rung 7
    cut_code = v_string(data, "cut_code")            # rung 8
    loop_count = v_int(data, "loop_count", minimum=1)
    runtime_seconds = v_int(data, "runtime_seconds", minimum=1)
    _assert_cut_code_unique(title["id"], cut_code)

    row = new_row({
        "title_id": title["id"],
        "derived_from_cut_id": None,
        "cut_code": cut_code,
        "loop_count": loop_count,
        "runtime_seconds": runtime_seconds,
        "conform_delta_seconds": 0,
        "lineage_depth": 0,
        "derived_cut_count": 0,
        "status": "OPEN",
    })
    db.cuts[row["id"]] = row
    title["cut_count"] = title["cut_count"] + 1
    touch(title)
    return created(serialize(row))


@bp.post("/cuts/<cut_id>/derive")
@auth("ProductionCoordinator")
def derive_cut(cut_id):
    parent = get_cut(cut_id)                          # rung 6
    data = body()
    cut_code = v_string(data, "cut_code")             # rung 8
    loop_count = v_int(data, "loop_count", minimum=1)
    runtime_seconds = v_int(data, "runtime_seconds", minimum=1)
    expected = v_int(data, "expected_parent_cut_version")
    _assert_cut_code_unique(parent["title_id"], cut_code)

    if expected != parent["version"]:                 # rung 13
        raise ApiError("ERR_STALE_CUT_VERSION")
    if parent["lineage_depth"] >= calc.MAX_LINEAGE_DEPTH:   # rung 23
        raise ApiError("ERR_LINEAGE_DEPTH_EXCEEDED")

    title = db.titles[parent["title_id"]]
    row = new_row({
        "title_id": parent["title_id"],
        "derived_from_cut_id": parent["id"],
        "cut_code": cut_code,
        "loop_count": loop_count,
        "runtime_seconds": runtime_seconds,
        "conform_delta_seconds": runtime_seconds - parent["runtime_seconds"],
        "lineage_depth": parent["lineage_depth"] + 1,
        "derived_cut_count": 0,
        "status": "OPEN",
    })
    db.cuts[row["id"]] = row
    parent["derived_cut_count"] = parent["derived_cut_count"] + 1
    touch(parent)
    title["cut_count"] = title["cut_count"] + 1
    touch(title)
    return created(serialize(row))


@bp.post("/cuts/<cut_id>/lock")
@auth("ProductionCoordinator")
def lock_cut(cut_id):
    cut = get_cut(cut_id)
    if cut["status"] != "OPEN":                       # rung 11
        raise ApiError("ERR_INVALID_STATE")
    if cut["derived_from_cut_id"] is not None:
        parent = db.cuts.get(cut["derived_from_cut_id"])
        if parent is None or parent["status"] != "LOCKED":
            raise ApiError("ERR_INVALID_STATE")
    cut["status"] = "LOCKED"
    touch(cut)
    return ok(serialize(cut))


@bp.get("/cuts/<cut_id>")
@auth(*ALL_ROLES)
def read_cut(cut_id):
    return ok(serialize(get_cut(cut_id)))


@bp.get("/cuts")
@auth(*ALL_ROLES)
def list_cuts():
    rows = list(db.cuts.values())
    for key in ("title_id", "derived_from_cut_id", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    return paged(rows, serialize)


# --------------------------------------------------------------------------
# Characters
# --------------------------------------------------------------------------
@bp.post("/characters")
@auth("ProductionCoordinator")
def create_character():
    data = body()
    title = get_title(data.get("title_id"))
    character_code = v_string(data, "character_code")
    loop_count = v_int(data, "loop_count", minimum=0)
    screen_time_seconds = v_int(data, "screen_time_seconds", minimum=0)
    is_principal = v_bool(data, "is_principal", required=False, default=False)

    for row in db.characters.values():
        if row["title_id"] == title["id"] and row["character_code"] == character_code:
            raise ApiError("ERR_INVALID_REQUEST", "character_code must be unique per title.")

    row = new_row({
        "title_id": title["id"],
        "character_code": character_code,
        "loop_count": loop_count,
        "is_principal": is_principal,
        "screen_time_seconds": screen_time_seconds,
    })
    db.characters[row["id"]] = row
    return created(serialize(row))


@bp.get("/characters/<character_id>")
@auth(*ALL_ROLES)
def read_character(character_id):
    return ok(serialize(get_character(character_id)))


@bp.get("/characters")
@auth(*ALL_ROLES)
def list_characters():
    rows = list(db.characters.values())
    value = request.args.get("title_id")
    if value is not None:
        rows = [r for r in rows if r["title_id"] == value]
    return paged(rows, serialize)


# --------------------------------------------------------------------------
# Platform specifications
# --------------------------------------------------------------------------
@bp.post("/platform-specs")
@auth("ProductionCoordinator")
def create_platform_spec():
    data = body()
    platform_code = v_string(data, "platform_code")
    loudness_target_lufs = v_number(data, "loudness_target_lufs", minimum=-40.0, maximum=0.0)
    stem_layout = v_enum(data, "stem_layout", STEM_LAYOUTS)
    max_lipsync_deviation_ms = v_int(data, "max_lipsync_deviation_ms", minimum=1)
    min_fidelity_score = v_number(data, "min_fidelity_score", minimum=0.0, maximum=1.0)
    qc_pass_threshold = v_number(data, "qc_pass_threshold", minimum=0.0, maximum=1.0)
    metadata_fields_required = v_array(data, "metadata_fields_required",
                                       member_type=str, member_non_empty=True)
    for row in db.platform_specs.values():
        if row["platform_code"] == platform_code:
            raise ApiError("ERR_INVALID_REQUEST", "platform_code must be unique.")

    row = new_row({
        "platform_code": platform_code,
        "loudness_target_lufs": loudness_target_lufs,
        "stem_layout": stem_layout,
        "max_lipsync_deviation_ms": max_lipsync_deviation_ms,
        "min_fidelity_score": min_fidelity_score,
        "qc_pass_threshold": qc_pass_threshold,
        "metadata_fields_required": list(metadata_fields_required),
    })
    db.platform_specs[row["id"]] = row
    return created(serialize(row))


@bp.get("/platform-specs/<spec_id>")
@auth(*ALL_ROLES)
def read_platform_spec(spec_id):
    return ok(serialize(get_spec(spec_id)))
