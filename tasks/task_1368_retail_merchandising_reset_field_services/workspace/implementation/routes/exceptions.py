from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp
import services

bp = Blueprint("exceptions", __name__)
COLL = "exceptions"


def _get_exception_or_404(eid):
    e = db.collections[COLL].get(eid)
    if e is None:
        raise errors.not_found("exception report not found")
    return e


def _check_exception_read_ownership(uid, role, e):
    v = db.collections["store_visits"].get(e["store_visit_id"])
    a = db.collections["assignments"].get(v["assignment_id"]) if v else None
    project = services.project_of_assignment(a)
    if role == "FieldRep" and a is not None and a["rep_id"] != uid:
        raise errors.unauthorized("rep acting on another rep's visit")
    if role == "Client" and project is not None and project["client_id"] != uid:
        raise errors.unauthorized("client acting on another client's project")


@bp.get("/exceptions/<eid>")
def get_exception(eid):
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager", "Client", "FieldRep", "BillingClerk"})
    e = _get_exception_or_404(eid)
    _check_exception_read_ownership(uid, role, e)
    return resp.success_object(db.serialize(e))


@bp.post("/exceptions/<eid>/resolve")
def resolve_exception(eid):
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager"})
    e = _get_exception_or_404(eid)
    # Priority 4: only OPEN exceptions can be settled.
    if e["resolution"] != "OPEN":
        raise errors.invalid_state("exception is not OPEN")
    body = mw.get_body()
    # Priority 13: input sanitization.
    e["resolution"] = mw.req_enum(body, "resolution", {"RESOLVED", "WAIVED"})
    # ExceptionReport carries no updated_at/version (PRD §2.4).
    return resp.success_object(db.serialize(e))
