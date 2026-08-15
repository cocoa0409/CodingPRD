"""Deadline endpoints (PRD 3.5)."""

from flask import Blueprint

import db
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_VALIDATION, ERR_FORBIDDEN,
    ERR_SEGREGATION_OF_DUTIES, ERR_EXTENSION_CAP_REACHED,
)
from middleware import require_roles, enforce_client_scope
from response import success
from services import domain
from services.domain import ser_deadline, compute_due_at
from util import (
    get_payload, reject_unknown_fields, require_int, stamp_new, touch,
    fmt_business, parse_dt,
)
from routes.common import do_list

bp = Blueprint("deadlines", __name__)

READ_ROLES = ("Paralegal", "AssociateAttorney", "PartnerAttorney", "ClientContact")


def _get_deadline(deadline_id):
    deadline = db.deadlines.get(deadline_id)
    if deadline is None:
        raise_error(ERR_NOT_FOUND, "Deadline not found")
    return deadline


def _scope(user_id, role, deadline):
    enforce_client_scope(user_id, role,
                         domain.client_id_for_resource("deadline", deadline))


@bp.route("/brand/deadlines", methods=["GET"])
def list_deadlines():
    user_id, role = require_roles(*READ_ROLES)
    return do_list(db.deadlines.values(), ser_deadline,
                   [("enforcement_matter_id", "enforcement_matter_id", None),
                    ("status", "status", None)],
                   user_id, role, "deadline")


@bp.route("/brand/deadlines/<deadline_id>", methods=["GET"])
def get_deadline(deadline_id):
    user_id, role = require_roles(*READ_ROLES)
    deadline = _get_deadline(deadline_id)
    _scope(user_id, role, deadline)
    return success(ser_deadline(deadline), 200)


@bp.route("/brand/deadlines/<deadline_id>/verify", methods=["POST"])
def verify_deadline(deadline_id):
    user_id, role = require_roles("AssociateAttorney", "PartnerAttorney")
    body = get_payload()
    reject_unknown_fields(body, set())
    deadline = _get_deadline(deadline_id)
    if deadline["status"] != "DOCKETED":
        raise_error(ERR_INVALID_STATE, "verify is declared only from DOCKETED")
    # Segregation of duties: the verifier must differ from the docketing caller.
    if user_id == deadline["docketed_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "Deadline verifier must differ from docketed_by_user_id")
    deadline["verified_by_user_id"] = user_id
    deadline["status"] = "PENDING"
    touch(deadline)
    return success(ser_deadline(deadline), 200)


@bp.route("/brand/deadlines/<deadline_id>/extend", methods=["POST"])
def extend_deadline(deadline_id):
    user_id, role = require_roles("Paralegal")
    body = get_payload()
    reject_unknown_fields(body, {"additional_days"})
    additional_days = require_int(body, "additional_days", minimum=1)
    deadline = _get_deadline(deadline_id)
    if deadline["status"] not in ("PENDING", "EXTENDED"):
        raise_error(ERR_INVALID_STATE, "extend is declared only from PENDING / EXTENDED")
    if deadline["extension_count"] >= deadline["max_extensions"]:
        raise_error(ERR_EXTENSION_CAP_REACHED, "extension_count has reached max_extensions")
    # Extensions reuse the deadline's own variant, treating the current
    # computed_due_at as the new basis (PRD 2.8).
    new_due = compute_due_at(deadline["computation_variant"],
                             parse_dt(deadline["computed_due_at"]), additional_days)
    deadline["computed_due_at"] = fmt_business(new_due)
    deadline["extension_count"] += 1
    deadline["status"] = "EXTENDED"
    touch(deadline)
    return success(ser_deadline(deadline), 200)


@bp.route("/brand/deadlines/<deadline_id>/satisfy", methods=["POST"])
def satisfy_deadline(deadline_id):
    user_id, role = require_roles("Paralegal", "PartnerAttorney")
    body = get_payload()
    reject_unknown_fields(body, {"allow_late"})
    allow_late = body.get("allow_late", None)
    if allow_late is not None and not isinstance(allow_late, bool):
        raise_error(ERR_VALIDATION, "allow_late must be a boolean")
    deadline = _get_deadline(deadline_id)
    now = db.clock.now()
    if deadline["status"] in ("PENDING", "EXTENDED"):
        # Timely satisfaction: the clock is at or before computed_due_at
        # (guaranteed by the MISSED clock sweep).
        deadline["satisfied_at"] = fmt_business(now)
        deadline["satisfied_late"] = False
        deadline["status"] = "SATISFIED"
        touch(deadline)
        return success(ser_deadline(deadline), 200)
    if deadline["status"] == "MISSED":
        # Late satisfaction: requires explicit allow_late: true.
        if allow_late is not True:
            raise_error(ERR_VALIDATION, "late satisfy requires allow_late: true")
        # ... and is a PartnerAttorney-only act.
        if role != "PartnerAttorney":
            raise_error(ERR_FORBIDDEN, "late satisfy from MISSED requires PartnerAttorney")
        deadline["satisfied_at"] = fmt_business(now)
        deadline["satisfied_late"] = True
        deadline["status"] = "SATISFIED"
        touch(deadline)
        # Matter posture (leaves JEOPARDY when no MISSED remains) and the
        # client exposure index are derived and reflect this immediately.
        matter = db.enforcement_matters.get(deadline["enforcement_matter_id"])
        if matter is not None:
            touch(matter)
        return success(ser_deadline(deadline), 200)
    raise_error(ERR_INVALID_STATE, "satisfy is not declared from %s" % deadline["status"])
