"""Award and ScholarshipPool routes."""

from flask import Blueprint, request
import db
import validators as V
from middleware import require_roles
from response import success_object, success_list
from pagination import parse_pagination, paginate
from serializers import award_out, scholarship_pool_out
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL, ERR_REFERENTIAL_INTEGRITY,
)
from services.calculations import recompute_mentor_recognition

bp = Blueprint("awards", __name__)

_VALID_AWARD_TYPE = {"CATEGORY_FIRST", "CATEGORY_SECOND", "GRAND_PRIZE",
                     "SPECIAL_TOPIC"}
_VALID_AWARD_STATUS = {"PROPOSED", "CONFERRED", "REVOKED"}
_REVOCABLE_PHASES = {"JUDGING", "ADVANCEMENT_PUBLISHED"}


def _touch(e):
    e["updated_at"] = db.now_display_iso()
    e["version"] += 1


@bp.route("/science-fair/awards", methods=["POST"])
def create_award():
    body = V.get_json_body()
    V.require_fields(body, ["fair_edition_id", "project_id", "award_type"])
    feid = V.req_str(body, "fair_edition_id")
    pid = V.req_str(body, "project_id")
    award_type = V.req_enum(body, "award_type", _VALID_AWARD_TYPE)

    require_roles("FairDirector")

    edition = db.fair_editions.get(feid)
    if edition is None:
        raise_err(ERR_REFERENTIAL_INTEGRITY,
                  f"Fair edition not found: {feid}")
    project = db.projects.get(pid)
    if project is None or project["fair_edition_id"] != feid:
        raise_err(ERR_REFERENTIAL_INTEGRITY,
                  f"Project {pid} does not exist in edition {feid}")

    now = db.now_display_iso()
    a = {
        "id": db.new_id(),
        "fair_edition_id": feid,
        "project_id": pid,
        "award_type": award_type,
        "scholarship_amount_cents": None,
        "status": "PROPOSED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.awards[a["id"]] = a
    return success_object(award_out(a), 201)


@bp.route("/science-fair/awards", methods=["GET"])
def list_awards():
    require_roles("FairDirector", "Mentor", "Judge")
    limit, offset = parse_pagination()
    items = list(db.awards.values())
    feid = request.args.get("fair_edition_id")
    if feid:
        items = [a for a in items if a["fair_edition_id"] == feid]
    pid = request.args.get("project_id")
    if pid:
        items = [a for a in items if a["project_id"] == pid]
    st = request.args.get("status")
    if st:
        items = [a for a in items if a["status"] == st]
    data, total = paginate(items, award_out, limit, offset)
    return success_list(data, limit, offset, total)


@bp.route("/science-fair/awards/<aid>", methods=["GET"])
def get_award(aid):
    require_roles("FairDirector", "Mentor", "Judge")
    a = db.awards.get(aid)
    if a is None:
        raise_err(ERR_NOT_FOUND, f"Award not found: {aid}")
    return success_object(award_out(a))


@bp.route("/science-fair/awards/<aid>/revoke", methods=["POST"])
def revoke_award(aid):
    V.get_json_body()
    require_roles("FairDirector")
    a = db.awards.get(aid)
    if a is None:
        raise_err(ERR_NOT_FOUND, f"Award not found: {aid}")

    if a["status"] in ("CONFERRED", "REVOKED"):
        raise_err(ERR_ALREADY_TERMINAL,
                  f"Award is {a['status']} (terminal)")
    if a["status"] != "PROPOSED":
        raise_err(ERR_INVALID_STATE,
                  f"Cannot revoke award in status {a['status']}")

    edition = db.fair_editions.get(a["fair_edition_id"])
    if edition is None or edition["status"] not in _REVOCABLE_PHASES:
        st = edition["status"] if edition else "missing"
        raise_err(ERR_INVALID_STATE,
                  f"Award revoke requires edition in JUDGING or "
                  f"ADVANCEMENT_PUBLISHED; edition is {st}")

    a["status"] = "REVOKED"
    _touch(a)

    # Revocation recomputes mentor recognition totals
    recompute_mentor_recognition(a["fair_edition_id"])

    return success_object(award_out(a))


# ---- ScholarshipPool ----

@bp.route("/science-fair/scholarship-pools", methods=["POST"])
def create_pool():
    body = V.get_json_body()
    V.require_fields(body, ["fair_edition_id", "total_cents"])
    feid = V.req_str(body, "fair_edition_id")
    total = V.req_int(body, "total_cents")
    if total < 0:
        raise_err(ERR_INVALID_REQUEST, "total_cents must be >= 0")

    require_roles("FairDirector")

    edition = db.fair_editions.get(feid)
    if edition is None:
        raise_err(ERR_REFERENTIAL_INTEGRITY,
                  f"Fair edition not found: {feid}")

    # Exactly one pool per edition
    for sp in db.scholarship_pools.values():
        if sp["fair_edition_id"] == feid:
            raise_err(ERR_INVALID_STATE,
                      "Scholarship pool already exists for this edition")

    now = db.now_display_iso()
    p = {
        "id": db.new_id(),
        "fair_edition_id": feid,
        "total_cents": total,
        "remaining_cents": total,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.scholarship_pools[p["id"]] = p
    return success_object(scholarship_pool_out(p), 201)


@bp.route("/science-fair/scholarship-pools", methods=["GET"])
def list_pools():
    require_roles("FairDirector")
    limit, offset = parse_pagination()
    items = list(db.scholarship_pools.values())
    feid = request.args.get("fair_edition_id")
    if feid:
        items = [p for p in items if p["fair_edition_id"] == feid]
    data, total = paginate(items, scholarship_pool_out, limit, offset)
    return success_list(data, limit, offset, total)


@bp.route("/science-fair/scholarship-pools/<pid>", methods=["GET"])
def get_pool(pid):
    require_roles("FairDirector")
    p = db.scholarship_pools.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, f"Scholarship pool not found: {pid}")
    return success_object(scholarship_pool_out(p))
