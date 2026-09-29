"""ExamForm endpoints: assembly, standard setting, publication (PRD 3.5)."""

from flask import Blueprint

import serialize
from db import DB, mark_created, new_record, ordered, touch
from dispatch import api
from errors import ApiError
from middleware import (
    ROLE_EXAM_OPERATIONS,
    ROLE_PANELIST,
    ROLE_PROGRAM_ADMIN,
    ROLE_PSYCHOMETRICIAN,
    authenticate,
    ensure_body,
    opt_enum,
    opt_str,
    opt_str_list,
    peek_body,
    req_int,
    req_num,
    req_str,
    req_str_list,
)
from response import apply_filters, created_response, object_response, paginate, read_pagination
from services import calc, derive, lookup

bp = Blueprint("forms", __name__)

PANEL_METHODS = ("MODIFIED_ANGOFF", "BOOKMARK")
FORM_ELIGIBLE_ITEM_STATUSES = ("APPROVED", "PRETEST", "OPERATIONAL")


@bp.post("/forms")
@api
def create_form():
    authenticate([ROLE_PSYCHOMETRICIAN])
    raw = peek_body()
    payload = raw or {}

    # Layer 4: every foreign identifier in the body resolves first.
    program = lookup.program(payload.get("program_id"))
    raw_item_ids = payload.get("item_ids")
    if isinstance(raw_item_ids, list):
        for identifier in raw_item_ids:
            lookup.item(identifier)
    raw_pretest_ids = payload.get("pretest_item_ids")
    if isinstance(raw_pretest_ids, list):
        for identifier in raw_pretest_ids:
            lookup.item(identifier)

    body = ensure_body(raw)
    form_code = req_str(body, "form_code")
    item_ids = req_str_list(body, "item_ids")
    pretest_item_ids = opt_str_list(body, "pretest_item_ids", default=[])
    panelist_user_ids = req_str_list(body, "panelist_user_ids", minimum_length=1, distinct=True)
    panel_method = opt_enum(body, "panel_method", PANEL_METHODS, "MODIFIED_ANGOFF")

    known_domains = [spec["domain_code"] for spec in program["domain_specs"]]
    cited = [DB.items[identifier] for identifier in item_ids]

    # Layer 22: item provenance.
    for item in cited:
        if item["program_id"] != program["id"]:
            raise ApiError("ERR_ITEM_DOMAIN_MISMATCH")
        if item["domain_code"] not in known_domains:
            raise ApiError("ERR_ITEM_DOMAIN_MISMATCH")

    # Layer 23: every scored position must be form-eligible.
    pretest_set = set(pretest_item_ids)
    for item in cited:
        if item["id"] in pretest_set:
            continue
        if item["status"] not in FORM_ELIGIBLE_ITEM_STATUSES:
            raise ApiError("ERR_ITEM_NOT_ELIGIBLE_FOR_FORM")

    # Layer 24: the pretest list is a subset of the form's positions.
    for identifier in pretest_item_ids:
        if identifier not in item_ids:
            raise ApiError("ERR_ITEM_NOT_IN_FORM")

    # Layer 35: exact form length.
    if len(item_ids) != program["form_length"]:
        raise ApiError("ERR_FORM_LENGTH_MISMATCH")

    form = new_record(
        program_id=program["id"],
        form_code=form_code,
        item_ids=item_ids,
        pretest_item_ids=pretest_item_ids,
        panelist_user_ids=panelist_user_ids,
        panel_method=panel_method,
        panel_status="OPEN",
        panel_ratings=[],
        mean_expected_pass_rate=None,
        raw_cut_score=None,
        scored_item_count=len(item_ids) - len(pretest_item_ids),
        retired_item_count=0,
        status="ASSEMBLED",
    )
    mark_created(form)
    DB.forms[form["id"]] = form
    derive.recompute_form_retired_count(form, bump=False)
    return created_response(serialize.form(form))


@bp.get("/forms/<form_id>")
@api
def read_form(form_id):
    authenticate([ROLE_PSYCHOMETRICIAN, ROLE_PROGRAM_ADMIN, ROLE_EXAM_OPERATIONS,
                  ROLE_PANELIST])
    return object_response(serialize.form(lookup.form(form_id)))


@bp.get("/forms")
@api
def list_forms():
    authenticate([ROLE_PSYCHOMETRICIAN, ROLE_PROGRAM_ADMIN, ROLE_EXAM_OPERATIONS])
    limit, offset = read_pagination()
    rows = ordered(DB.forms.values())
    rows = apply_filters(rows, {
        "program_id": "program_id",
        "status": "status",
        "panel_status": "panel_status",
    })
    return paginate(rows, serialize.form, limit, offset)


@bp.post("/forms/<form_id>/panel-ratings")
@api
def submit_panel_rating(form_id):
    authenticate([ROLE_PANELIST, ROLE_PSYCHOMETRICIAN])
    form = lookup.form(form_id)
    body = ensure_body(peek_body())
    panelist_user_id = req_str(body, "panelist_user_id")
    mean_expected_pass_rate = req_num(body, "mean_expected_pass_rate", minimum=0)

    if form["status"] not in ("ASSEMBLED", "CUT_SCORE_SET"):
        raise ApiError("ERR_INVALID_STATE")

    # Layer 25: panel membership.
    if panelist_user_id not in form["panelist_user_ids"]:
        raise ApiError("ERR_PANELIST_NOT_ON_PANEL")

    # Layer 37: one rating per panellist.
    for rating in form["panel_ratings"]:
        if rating["panelist_user_id"] == panelist_user_id:
            raise ApiError("ERR_DUPLICATE_PANELIST_RATING")

    form["panel_ratings"] = form["panel_ratings"] + [{
        "panelist_user_id": panelist_user_id,
        "mean_expected_pass_rate": mean_expected_pass_rate,
        "submitted_at": DB.now(),
    }]
    if len(form["panel_ratings"]) == len(form["panelist_user_ids"]):
        form["panel_status"] = "RATINGS_COMPLETE"
    touch(form)
    return object_response(serialize.form(form))


@bp.post("/forms/<form_id>/adopt-cut-score")
@api
def adopt_cut_score(form_id):
    actor = authenticate([ROLE_PSYCHOMETRICIAN])
    form = lookup.form(form_id)
    body = ensure_body(peek_body())
    expected_form_version = req_int(body, "expected_form_version", minimum=0)
    opt_str(body, "adoption_note")

    # Layer 11: optimistic concurrency on the parent form.
    if expected_form_version != form["version"]:
        raise ApiError("ERR_STALE_VERSION")

    if form["status"] not in ("ASSEMBLED", "CUT_SCORE_SET"):
        raise ApiError("ERR_INVALID_STATE")

    # Layer 19: nobody ratifies their own judgement.
    if actor.user_id in form["panelist_user_ids"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    program = DB.programs[form["program_id"]]
    if not calc.panel_quorum_met(form, program):
        raise ApiError("ERR_PANEL_QUORUM_NOT_MET")

    raw_cut_score, trimmed_mean = calc.angoff_cut_score(form, program)
    form["raw_cut_score"] = raw_cut_score
    form["mean_expected_pass_rate"] = trimmed_mean
    form["panel_status"] = "ADOPTED"
    form["status"] = "CUT_SCORE_SET"
    touch(form)
    return object_response(serialize.form(form))


@bp.post("/forms/<form_id>/publish")
@api
def publish_form(form_id):
    authenticate([ROLE_PROGRAM_ADMIN])
    form = lookup.form(form_id)
    body = ensure_body(peek_body())
    opt_str(body, "publication_note")

    if form["status"] != "CUT_SCORE_SET":
        raise ApiError("ERR_INVALID_STATE")

    program = DB.programs[form["program_id"]]
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE")

    # Layer 34: the blueprint must be covered.
    if program["blueprint_posture"] != "COMPLETE":
        raise ApiError("ERR_BLUEPRINT_DEFICIENT")

    # Layer 43: every scored position must be operational right now.
    pretest_set = set(form["pretest_item_ids"])
    for identifier in form["item_ids"]:
        if identifier in pretest_set:
            continue
        item = DB.items.get(identifier)
        if item is None or item["status"] != "OPERATIONAL":
            raise ApiError("ERR_ITEM_NOT_OPERATIONAL")

    form["status"] = "PUBLISHED"
    touch(form)
    return object_response(serialize.form(form))
