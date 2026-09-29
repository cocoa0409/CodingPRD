"""Permit applications: the review desk and its revision loop (PRD 3.2, 3.4)."""
from flask import Blueprint, request

import db
from body import Body
from errors import invalid_request, invalid_state, raise_err
from gates import (P_AUDITION_REQUIRED, P_BODY, P_BODY_FK, P_DUP_APPLICATION,
                   P_OCC_APPLICATION, P_OWNER, P_PATH, P_REVISION_LIMIT,
                   P_SOD_DECISION, P_STATE, require_version, resolve,
                   resolve_body_fk, run_gates)
from listing import listing
from middleware import PERFORMER, PERMIT_OFFICER, require_owner, require_roles
from response import ok_object
from services import domain
from services.calc import ACT_TYPES, MAX_REVISIONS
from services.serializers import serialize
from utils import new_entity, touch

bp = Blueprint("applications", __name__, url_prefix="/busking")

OUTCOMES = {"APPROVED", "REJECTED", "CHANGES_REQUESTED"}


def recompute_requires_audition(application):
    """True when the act is AMPLIFIED_MUSIC or CIRCUS_SKILL, or amplification is
    asked for, or the applicant's standing is WATCH (PRD section 3.2)."""
    performer = db.get("performers", application["performer_id"])
    standing = performer["standing"] if performer else "GOOD"
    application["requires_audition"] = bool(
        application["requested_act_type"] in ("AMPLIFIED_MUSIC", "CIRCUS_SKILL")
        or application["amplification_requested"]
        or standing == "WATCH"
    )


def has_live_application(performer_id, season_year, exclude_id=None):
    for row in db.all_of("applications"):
        if row["id"] == exclude_id or row["performer_id"] != performer_id:
            continue
        if row["season_year"] == season_year and row["status"] != "REJECTED":
            return True
    return False


def cancel_scheduled_auditions(application):
    for audition in domain.application_auditions(application):
        if audition["status"] == "SCHEDULED":
            audition["status"] = "CANCELLED"
            touch(audition)


@bp.post("/permit-applications")
def create_application():
    user_id, role = require_roles([PERFORMER, PERMIT_OFFICER])
    raw = request.get_json(silent=True) or {}
    body = Body(raw)
    ctx = {}

    def check_fks():
        ctx["performer"] = resolve_body_fk("performers", raw, "performer_id")
        ctx["zone"] = resolve_body_fk("zones", raw, "requested_zone_id")

    def check_owner():
        if ctx["performer"] is not None:
            require_owner(role, user_id, ctx["performer"]["id"])

    def check_body():
        ctx["fields"] = {
            "performer_id": body.req_id("performer_id"),
            "requested_zone_id": body.req_id("requested_zone_id"),
            "season_year": body.req_int("season_year", 2025, 2035),
            "requested_act_type": body.req_enum("requested_act_type", ACT_TYPES),
            "amplification_requested": body.opt_bool("amplification_requested", False),
            "status": "DRAFT",
            "requires_audition": False,
            "revision_count": 0,
            "change_request_reason": None,
            "reviewed_by_user_id": None,
            "decided_by_user_id": None,
            "submitted_at": None,
            "decided_at": None,
            "assessed_fee_cents": 0,
        }

    def check_duplicate():
        if has_live_application(ctx["fields"]["performer_id"], ctx["fields"]["season_year"]):
            raise_err("ERR_DUPLICATE_ACTIVE_APPLICATION",
                      "That performer already holds a live application for this season")

    run_gates([
        (P_BODY_FK, check_fks),
        (P_OWNER, check_owner),
        (P_BODY, check_body),
        (P_DUP_APPLICATION, check_duplicate),
    ])
    return ok_object(serialize(new_entity("applications", ctx["fields"])), status=201)


@bp.get("/permit-applications/<application_id>")
def read_application(application_id):
    user_id, role = require_roles([PERMIT_OFFICER, PERFORMER])
    ctx = {}
    run_gates([
        (P_PATH, lambda: ctx.update(app=resolve("applications", application_id))),
        (P_OWNER, lambda: require_owner(role, user_id, ctx["app"]["performer_id"])),
    ])
    return ok_object(serialize(ctx["app"]))


@bp.get("/permit-applications")
def list_applications():
    require_roles([PERMIT_OFFICER, PERFORMER])
    return listing("applications",
                   ["performer_id", "requested_zone_id", "status", "season_year"],
                   request.args)


@bp.post("/permit-applications/<application_id>/submit")
def submit_application(application_id):
    user_id, role = require_roles([PERFORMER])
    ctx = {}

    def check_state():
        if ctx["app"]["status"] != "DRAFT":
            invalid_state("Only a DRAFT application can be lodged")

    def check_duplicate():
        application = ctx["app"]
        if has_live_application(application["performer_id"], application["season_year"],
                                exclude_id=application["id"]):
            raise_err("ERR_DUPLICATE_ACTIVE_APPLICATION",
                      "That performer already holds a live application for this season")

    run_gates([
        (P_PATH, lambda: ctx.update(app=resolve("applications", application_id))),
        (P_OWNER, lambda: require_owner(role, user_id, ctx["app"]["performer_id"])),
        (P_STATE, check_state),
        (P_DUP_APPLICATION, check_duplicate),
    ])

    application = ctx["app"]
    recompute_requires_audition(application)
    application["submitted_at"] = db.now()
    application["status"] = "SUBMITTED"
    touch(application)
    return ok_object(serialize(application))


@bp.post("/permit-applications/<application_id>/review")
def review_application(application_id):
    user_id, _role = require_roles([PERMIT_OFFICER])
    ctx = {}

    def check_state():
        if ctx["app"]["status"] != "SUBMITTED":
            invalid_state("Only a SUBMITTED application can be picked up")

    run_gates([
        (P_PATH, lambda: ctx.update(app=resolve("applications", application_id))),
        (P_STATE, check_state),
    ])

    application = ctx["app"]
    application["status"] = ("AUDITION_REQUIRED" if application["requires_audition"]
                             else "UNDER_REVIEW")
    application["reviewed_by_user_id"] = user_id
    touch(application)
    return ok_object(serialize(application))


@bp.post("/permit-applications/<application_id>/revisions")
def revise_application(application_id):
    user_id, role = require_roles([PERFORMER])
    body = Body(request.get_json(silent=True))
    ctx = {}

    def check_body():
        ctx["expected"] = body.req_int("expected_application_version")
        ctx["act_type"] = body.opt_enum("requested_act_type", ACT_TYPES)
        ctx["amplification"] = (body.req_bool("amplification_requested")
                                if body.supplied("amplification_requested") else None)
        ctx["zone_id"] = body.opt_id("requested_zone_id")

    def check_state():
        if ctx["app"]["status"] != "CHANGES_REQUESTED":
            invalid_state("A revision is only accepted from CHANGES_REQUESTED")

    def check_version():
        require_version(ctx["expected"], ctx["app"]["version"],
                        "ERR_STALE_APPLICATION_VERSION")

    def check_revision_limit():
        if ctx["app"]["revision_count"] >= MAX_REVISIONS:
            raise_err("ERR_REVISION_LIMIT_EXCEEDED", "The revision allowance is exhausted")

    run_gates([
        (P_PATH, lambda: ctx.update(app=resolve("applications", application_id))),
        (P_OWNER, lambda: require_owner(role, user_id, ctx["app"]["performer_id"])),
        (P_BODY, check_body),
        (P_STATE, check_state),
        (P_OCC_APPLICATION, check_version),
        (P_REVISION_LIMIT, check_revision_limit),
    ])

    application = ctx["app"]
    if ctx["act_type"] is not None:
        application["requested_act_type"] = ctx["act_type"]
    if ctx["amplification"] is not None:
        application["amplification_requested"] = ctx["amplification"]
    if ctx["zone_id"] is not None:
        application["requested_zone_id"] = ctx["zone_id"]
    application["revision_count"] += 1
    recompute_requires_audition(application)
    application["submitted_at"] = db.now()
    application["change_request_reason"] = None
    cancel_scheduled_auditions(application)
    application["status"] = "SUBMITTED"
    touch(application)
    return ok_object(serialize(application))


@bp.post("/permit-applications/<application_id>/decision")
def decide_application(application_id):
    user_id, _role = require_roles([PERMIT_OFFICER])
    body = Body(request.get_json(silent=True))
    ctx = {}

    def check_body():
        ctx["outcome"] = body.req_enum("outcome", OUTCOMES)
        ctx["note"] = body.opt_str("decision_note")
        if ctx["outcome"] == "CHANGES_REQUESTED" and not ctx["note"]:
            invalid_request("decision_note is required when the outcome is CHANGES_REQUESTED")

    def check_audition_required():
        application = ctx["app"]
        if (ctx["outcome"] == "APPROVED" and application["requires_audition"]
                and application["status"] != "AUDITION_PASSED"):
            raise_err("ERR_AUDITION_REQUIRED",
                      "This application must pass a vetting panel before approval")

    def check_state():
        status = ctx["app"]["status"]
        outcome = ctx["outcome"]
        if outcome == "APPROVED":
            allowed = ("UNDER_REVIEW", "AUDITION_PASSED")
        elif outcome == "REJECTED":
            allowed = ("UNDER_REVIEW", "AUDITION_SCHEDULED", "AUDITION_PASSED",
                       "AUDITION_FAILED")
        else:
            allowed = ("UNDER_REVIEW", "AUDITION_FAILED")
        if status not in allowed:
            invalid_state("A %s decision is not declared from %s" % (outcome, status))

    def check_segregation():
        for audition in domain.application_auditions(ctx["app"]):
            if audition["status"] == "PASSED" and audition["finalized_by_user_id"] == user_id:
                raise_err("ERR_SEGREGATION_OF_DUTIES",
                          "The officer who finalized the panel may not decide this application")

    def check_revision_limit():
        if ctx["outcome"] == "CHANGES_REQUESTED" and ctx["app"]["revision_count"] >= MAX_REVISIONS:
            raise_err("ERR_REVISION_LIMIT_EXCEEDED", "The revision allowance is exhausted")

    run_gates([
        (P_PATH, lambda: ctx.update(app=resolve("applications", application_id))),
        (P_BODY, check_body),
        (P_AUDITION_REQUIRED, check_audition_required),
        (P_STATE, check_state),
        (P_SOD_DECISION, check_segregation),
        (P_REVISION_LIMIT, check_revision_limit),
    ])

    application = ctx["app"]
    outcome = ctx["outcome"]
    if outcome == "CHANGES_REQUESTED":
        application["change_request_reason"] = ctx["note"]
        application["status"] = "CHANGES_REQUESTED"
    elif outcome == "REJECTED":
        cancel_scheduled_auditions(application)
        application["decided_by_user_id"] = user_id
        application["decided_at"] = db.now()
        application["status"] = "REJECTED"
    else:
        application["decided_by_user_id"] = user_id
        application["decided_at"] = db.now()
        application["status"] = "APPROVED"
        domain.mint_permit_for_application(application)
    touch(application)
    return ok_object(serialize(application))
