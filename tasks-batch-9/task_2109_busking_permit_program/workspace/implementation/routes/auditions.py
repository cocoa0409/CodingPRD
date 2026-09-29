"""Vetting: audition sittings and panel scores (PRD section 3.3)."""
from flask import Blueprint, request

import db
from body import Body
from errors import invalid_state, raise_err
from gates import (P_BODY, P_BODY_FK, P_DUP_PANEL_SCORE, P_PANEL_INCOMPLETE,
                   P_PATH, P_STATE, resolve, resolve_body_fk, run_gates)
from listing import listing, paged
from middleware import (AUDITION_PANELIST, PERFORMER, PERMIT_OFFICER,
                        require_roles)
from response import ok_object
from services import calc, domain
from services.serializers import serialize
from utils import new_entity, touch

bp = Blueprint("auditions", __name__, url_prefix="/busking")


@bp.post("/auditions")
def schedule_audition():
    require_roles([PERMIT_OFFICER])
    raw = request.get_json(silent=True) or {}
    body = Body(raw)
    ctx = {}

    def check_fks():
        ctx["app"] = resolve_body_fk("applications", raw, "application_id")

    def check_body():
        ctx["application_id"] = body.req_id("application_id")
        ctx["scheduled_for"] = body.req_dt("scheduled_for")

    def check_state():
        application = ctx["app"]
        if application["status"] != "AUDITION_REQUIRED":
            invalid_state("A sitting is only scheduled from AUDITION_REQUIRED")
        if any(a["status"] == "SCHEDULED" for a in domain.application_auditions(application)):
            invalid_state("This application already has a live sitting")

    run_gates([
        (P_BODY_FK, check_fks),
        (P_BODY, check_body),
        (P_STATE, check_state),
    ])

    application = ctx["app"]
    audition = new_entity("auditions", {
        "application_id": application["id"],
        "scheduled_for": ctx["scheduled_for"],
        "status": "SCHEDULED",
        "panel_score": None,
        "score_count": 0,
        "finalized_by_user_id": None,
        "finalized_at": None,
    })
    application["status"] = "AUDITION_SCHEDULED"
    touch(application)
    return ok_object(serialize(audition), status=201)


@bp.get("/auditions/<audition_id>")
def read_audition(audition_id):
    require_roles([PERMIT_OFFICER, PERFORMER])
    ctx = {}
    run_gates([(P_PATH, lambda: ctx.update(audition=resolve("auditions", audition_id)))])
    return ok_object(serialize(ctx["audition"]))


@bp.get("/auditions")
def list_auditions():
    require_roles([PERMIT_OFFICER, PERFORMER])
    return listing("auditions", ["application_id", "status"], request.args)


@bp.post("/auditions/<audition_id>/scores")
def file_score(audition_id):
    user_id, _role = require_roles([AUDITION_PANELIST])
    body = Body(request.get_json(silent=True))
    ctx = {}

    def check_body():
        ctx["technical"] = body.req_int("technical_score", 0, 10)
        ctx["suitability"] = body.req_int("suitability_score", 0, 10)
        ctx["safety"] = body.req_int("safety_score", 0, 10)

    def check_duplicate():
        for score in domain.audition_scores(ctx["audition"]):
            if score["panelist_user_id"] == user_id:
                raise_err("ERR_DUPLICATE_PANEL_SCORE",
                          "This panelist has already filed a score on this sitting")

    run_gates([
        (P_PATH, lambda: ctx.update(audition=resolve("auditions", audition_id))),
        (P_BODY, check_body),
        (P_DUP_PANEL_SCORE, check_duplicate),
    ])

    audition = ctx["audition"]
    score = new_entity("audition_scores", {
        "audition_id": audition["id"],
        "panelist_user_id": user_id,
        "technical_score": ctx["technical"],
        "suitability_score": ctx["suitability"],
        "safety_score": ctx["safety"],
        "composite_score": calc.composite_score(
            ctx["technical"], ctx["suitability"], ctx["safety"]),
    }, common_fields=False)
    audition["score_count"] += 1
    touch(audition)
    return ok_object(serialize(score), status=201)


@bp.get("/auditions/<audition_id>/scores")
def list_scores(audition_id):
    require_roles([PERMIT_OFFICER, AUDITION_PANELIST])
    ctx = {}
    run_gates([(P_PATH, lambda: ctx.update(audition=resolve("auditions", audition_id)))])
    return paged(domain.audition_scores(ctx["audition"]), request.args)


@bp.post("/auditions/<audition_id>/finalize")
def finalize_audition(audition_id):
    user_id, _role = require_roles([PERMIT_OFFICER])
    ctx = {}

    def check_state():
        if ctx["audition"]["status"] != "SCHEDULED":
            invalid_state("Only a SCHEDULED sitting can be closed")

    def check_panel():
        if ctx["audition"]["score_count"] < calc.AUDITION_MIN_PANELISTS:
            raise_err("ERR_AUDITION_PANEL_INCOMPLETE",
                      "At least %d panel scores are required" % calc.AUDITION_MIN_PANELISTS)

    run_gates([
        (P_PATH, lambda: ctx.update(audition=resolve("auditions", audition_id))),
        (P_STATE, check_state),
        (P_PANEL_INCOMPLETE, check_panel),
    ])

    audition = ctx["audition"]
    composites = [row["composite_score"] for row in domain.audition_scores(audition)]
    score = calc.panel_score(composites, audition["score_count"])
    passed = calc.panel_passes(score)
    audition["panel_score"] = score
    audition["status"] = "PASSED" if passed else "FAILED"
    audition["finalized_by_user_id"] = user_id
    audition["finalized_at"] = db.now()
    touch(audition)

    application = db.get("applications", audition["application_id"])
    if application is not None and application["status"] == "AUDITION_SCHEDULED":
        application["status"] = "AUDITION_PASSED" if passed else "AUDITION_FAILED"
        touch(application)
    return ok_object(serialize(audition))
