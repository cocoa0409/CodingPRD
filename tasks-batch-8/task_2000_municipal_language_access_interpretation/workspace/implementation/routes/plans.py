"""LanguageAccessPlan endpoints (PRD §3.2)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_TRANSITION,
    ERR_MISSING_CERTIFIED_ASSESSMENTS,
    ERR_PLAN_NOT_FOUND,
    ERR_PLAN_YEAR_CONFLICT,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one
from services.core import touch
from services.serializers import serialize_plan
from util import CLOCK, new_id, next_seq
from validate import get_body, opt_nullable_str, reject_unknown_fields, req_int, require_path

bp = Blueprint("language_access_plans", __name__)


@bp.post("/language-access-plans")
def create_plan():
    authorized(["LanguageAccessCoordinator"])
    body = get_body()
    reject_unknown_fields(body, {"plan_year", "summary"})
    plan_year = req_int(body, "plan_year")
    summary = opt_nullable_str(body, "summary")

    # Priority 8 uniqueness: at most one DRAFT/PUBLISHED plan per plan_year.
    for p in db["language_access_plans"].values():
        if p["plan_year"] == plan_year and p["status"] in ("DRAFT", "PUBLISHED"):
            raise_error(ERR_PLAN_YEAR_CONFLICT, "a DRAFT or PUBLISHED plan already exists for this plan_year")

    now = CLOCK.now_iso()
    rec = {
        "id": new_id(),
        "plan_year": plan_year,
        "summary": summary,
        "status": "DRAFT",
        "published_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db["language_access_plans"][rec["id"]] = rec
    return success_object(serialize_plan(rec), status=201)


@bp.get("/language-access-plans/<rid>")
def get_plan(rid):
    return get_one("language_access_plans", rid, ERR_PLAN_NOT_FOUND, serialize_plan)


@bp.post("/language-access-plans/<rid>/publish")
def publish_plan(rid):
    authorized(["LanguageAccessCoordinator"])
    body = get_body()
    reject_unknown_fields(body, set())
    rec = require_path("language_access_plans", rid, ERR_PLAN_NOT_FOUND)
    if rec["status"] != "DRAFT":
        raise_error(ERR_INVALID_TRANSITION, "only a DRAFT plan may be published")

    # Coverage gate: every department must hold >= 1 CERTIFIED assessment whose
    # plan_year matches the plan's plan_year by value.
    for dept in db["departments"].values():
        covered = any(
            a["department_id"] == dept["id"]
            and a["plan_year"] == rec["plan_year"]
            and a["status"] == "CERTIFIED"
            for a in db["language_assessments"].values()
        )
        if not covered:
            raise_error(
                ERR_MISSING_CERTIFIED_ASSESSMENTS,
                "every department must have a CERTIFIED assessment for the plan year",
            )

    rec["status"] = "PUBLISHED"
    rec["published_at"] = CLOCK.now_iso()
    touch(rec)
    # The previously PUBLISHED plan (if any) is superseded.
    for p in db["language_access_plans"].values():
        if p["id"] != rec["id"] and p["status"] == "PUBLISHED":
            p["status"] = "SUPERSEDED"
            touch(p)
    return success_object(serialize_plan(rec))
