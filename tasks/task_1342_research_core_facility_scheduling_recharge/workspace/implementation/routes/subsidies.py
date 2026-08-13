"""Subsidy applications and awards (PRD §3.10)."""

from flask import Blueprint, request

from auth import authenticate, require_roles, is_entity_role, auth_id, auth_role, check_create_ownership
from errors import fail
from helpers import (
    Body, validate_body, non_empty_str, is_int, dt_ok, parse_dt,
    award_status, ser_application, ser_award,
)
from store import store
from util import new_entity, ok_object, parse_pagination, paginate, sort_default, touch, fmt_ts

bp = Blueprint("subsidies", __name__)


def get_application_or_404(aid):
    a = store.applications.get(aid)
    if a is None:
        fail("ERR_NOT_FOUND", "Subsidy application not found")
    return a


def get_award_or_404(aid):
    a = store.awards.get(aid)
    if a is None:
        fail("ERR_NOT_FOUND", "Subsidy award not found")
    return a


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

@bp.route("/subsidy-applications", methods=["POST"])
def create_application():
    authenticate()
    require_roles("Researcher")
    body = Body(request.get_json(silent=True))
    # Priority 2 — entity-backed create ownership
    check_create_ownership(body)
    user_id = body.get("user_id")
    # Priority 4 — FK existence
    if user_id is not None and user_id not in store.users:
        fail("ERR_NOT_FOUND", "user_id does not reference an existing user")
    # Priority 21 — formats
    validate_body(
        body,
        allowed={"user_id", "kind", "requested_amount_cents", "justification"},
        required={"user_id", "kind", "requested_amount_cents", "justification"},
        checkers={
            "user_id": lambda v: isinstance(v, str),
            "kind": lambda v: v in ("STARTUP", "SUBSIDY"),
            "requested_amount_cents": lambda v: is_int(v) and v > 0,
            "justification": lambda v: isinstance(v, str),
        },
    )
    # Priority 38 — applicant affiliation must be INTERNAL
    user = store.users.get(user_id)
    if user is not None and user["affiliation"] != "INTERNAL":
        fail("ERR_SUBSIDY_INELIGIBLE", "Only INTERNAL users may apply for subsidies")
    app = new_entity({
        "user_id": user_id,
        "kind": body.get("kind"),
        "requested_amount_cents": body.get("requested_amount_cents"),
        "justification": body.get("justification"),
        "status": "DRAFT",
        "reviewed_by": None,
    })
    store.applications[app["id"]] = app
    return ok_object(ser_application(app), status=201)


@bp.route("/subsidy-applications", methods=["GET"])
def list_applications():
    authenticate()
    require_roles("FinanceOfficer", "FacilityAdmin", "Researcher")
    limit, offset = parse_pagination(request.args)
    items = list(store.applications.values())
    if auth_role() == "Researcher":
        items = [a for a in items if a["user_id"] == auth_id()]
    else:
        user_id = request.args.get("user_id")
        if user_id is not None:
            items = [a for a in items if a["user_id"] == user_id]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return paginate(sort_default(items), limit, offset, ser_application)


@bp.route("/subsidy-applications/<aid>", methods=["GET"])
def get_application(aid):
    authenticate()
    require_roles("FinanceOfficer", "FacilityAdmin", "Researcher")
    app = get_application_or_404(aid)
    if auth_role() == "Researcher" and app["user_id"] != auth_id():
        fail("ERR_FORBIDDEN", "Researchers may only read their own applications")
    return ok_object(ser_application(app))


@bp.route("/subsidy-applications/<aid>/submit", methods=["POST"])
def submit_application(aid):
    authenticate()
    require_roles("Researcher")
    app = get_application_or_404(aid)
    if app["user_id"] != auth_id():
        fail("ERR_FORBIDDEN", "Only the owning Researcher may submit the application")
    body = Body(request.get_json(silent=True))
    if body.raw:
        for k in body.raw:
            fail("ERR_INVALID_REQUEST", "Unknown field in request body: %s" % k)
    # Priority 6 — state legality
    if app["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        fail("ERR_INVALID_STATE", "Only DRAFT or REVISION_REQUESTED applications can be submitted")
    # Priority 38 — applicant affiliation INTERNAL
    user = store.users.get(app["user_id"])
    if user is not None and user["affiliation"] != "INTERNAL":
        fail("ERR_SUBSIDY_INELIGIBLE", "Only INTERNAL users may apply for subsidies")
    app["status"] = "SUBMITTED"
    touch(app)
    return ok_object(ser_application(app))


@bp.route("/subsidy-applications/<aid>/review", methods=["POST"])
def review_application(aid):
    authenticate()
    require_roles("FinanceOfficer")
    app = get_application_or_404(aid)
    body = Body(request.get_json(silent=True))
    if body.raw:
        for k in body.raw:
            fail("ERR_INVALID_REQUEST", "Unknown field in request body: %s" % k)
    if app["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED application can move to UNDER_REVIEW")
    app["status"] = "UNDER_REVIEW"
    app["reviewed_by"] = auth_id()
    touch(app)
    return ok_object(ser_application(app))


@bp.route("/subsidy-applications/<aid>/request-revision", methods=["POST"])
def request_revision(aid):
    authenticate()
    require_roles("FinanceOfficer")
    app = get_application_or_404(aid)
    body = Body(request.get_json(silent=True))
    if body.raw:
        for k in body.raw:
            if k not in ("note",):
                fail("ERR_INVALID_REQUEST", "Unknown field in request body: %s" % k)
    if app["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "Only an UNDER_REVIEW application can be sent back for revision")
    app["status"] = "REVISION_REQUESTED"
    app["reviewed_by"] = auth_id()
    touch(app)
    return ok_object(ser_application(app))


@bp.route("/subsidy-applications/<aid>/approve", methods=["POST"])
def approve_application(aid):
    authenticate()
    require_roles("FinanceOfficer")
    app = get_application_or_404(aid)
    body = Body(request.get_json(silent=True))
    # Priority 6 — state legality
    if app["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "Only an UNDER_REVIEW application can be approved")
    # Priority 21 — formats
    validate_body(
        body,
        allowed={"awarded_amount_cents", "valid_from", "valid_until", "conveys_priority"},
        required={"awarded_amount_cents", "valid_from", "valid_until", "conveys_priority"},
        checkers={
            "awarded_amount_cents": is_int,
            "valid_from": dt_ok,
            "valid_until": dt_ok,
            "conveys_priority": lambda v: isinstance(v, bool),
        },
    )
    vf = parse_dt(body.get("valid_from"))
    vu = parse_dt(body.get("valid_until"))
    if not (vu > vf):
        fail("ERR_INVALID_REQUEST", "valid_until must be after valid_from")
    # Priority 38 — subsidy eligibility: amount bounds + priority only for STARTUP
    awarded = body.get("awarded_amount_cents")
    if awarded <= 0 or awarded > app["requested_amount_cents"]:
        fail("ERR_SUBSIDY_INELIGIBLE", "awarded_amount_cents must be > 0 and <= requested_amount_cents")
    if body.get("conveys_priority") and app["kind"] != "STARTUP":
        fail("ERR_SUBSIDY_INELIGIBLE", "conveys_priority is permitted only for STARTUP awards")
    # Mint the award (one per approved application)
    award = new_entity({
        "application_id": app["id"],
        "user_id": app["user_id"],
        "kind": app["kind"],
        "awarded_amount_cents": awarded,
        "remaining_amount_cents": awarded,
        "conveys_priority": bool(body.get("conveys_priority")),
        "valid_from": fmt_ts(vf),
        "valid_until": fmt_ts(vu),
        "_valid_from": vf,
        "_valid_until": vu,
        "_revoked": False,
    })
    store.awards[award["id"]] = award
    app["status"] = "APPROVED"
    app["reviewed_by"] = auth_id()
    touch(app)
    return ok_object(ser_award(award))


@bp.route("/subsidy-applications/<aid>/reject", methods=["POST"])
def reject_application(aid):
    authenticate()
    require_roles("FinanceOfficer")
    app = get_application_or_404(aid)
    body = Body(request.get_json(silent=True))
    if body.raw:
        for k in body.raw:
            if k not in ("reason",):
                fail("ERR_INVALID_REQUEST", "Unknown field in request body: %s" % k)
    if app["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "Only an UNDER_REVIEW application can be rejected")
    app["status"] = "REJECTED"
    app["reviewed_by"] = auth_id()
    touch(app)
    return ok_object(ser_application(app))


# ---------------------------------------------------------------------------
# Awards
# ---------------------------------------------------------------------------

@bp.route("/subsidy-awards", methods=["GET"])
def list_awards():
    authenticate()
    require_roles("FinanceOfficer", "Researcher")
    limit, offset = parse_pagination(request.args)
    items = list(store.awards.values())
    if auth_role() == "Researcher":
        items = [a for a in items if a["user_id"] == auth_id()]
    else:
        user_id = request.args.get("user_id")
        if user_id is not None:
            items = [a for a in items if a["user_id"] == user_id]
    application_id = request.args.get("application_id")
    if application_id is not None:
        items = [a for a in items if a["application_id"] == application_id]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if award_status(a) == status]
    return paginate(sort_default(items), limit, offset, ser_award)


@bp.route("/subsidy-awards/<aid>", methods=["GET"])
def get_award(aid):
    authenticate()
    require_roles("FinanceOfficer", "Researcher")
    award = get_award_or_404(aid)
    if auth_role() == "Researcher" and award["user_id"] != auth_id():
        fail("ERR_FORBIDDEN", "Researchers may only read their own awards")
    return ok_object(ser_award(award))


@bp.route("/subsidy-awards/<aid>/revoke", methods=["POST"])
def revoke_award(aid):
    authenticate()
    require_roles("FinanceOfficer")
    award = get_award_or_404(aid)
    body = Body(request.get_json(silent=True))
    if body.raw:
        for k in body.raw:
            if k not in ("reason",):
                fail("ERR_INVALID_REQUEST", "Unknown field in request body: %s" % k)
    if award.get("_revoked"):
        fail("ERR_INVALID_STATE", "Award is already REVOKED")
    award["_revoked"] = True
    award["remaining_amount_cents"] = 0
    touch(award)
    return ok_object(ser_award(award))
