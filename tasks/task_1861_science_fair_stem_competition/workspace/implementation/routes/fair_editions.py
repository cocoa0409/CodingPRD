"""FairEdition routes: CRUD + phase-transition state machine."""

from flask import Blueprint, request
import db
import validators as V
from middleware import require_roles
from response import success_object, success_list
from pagination import parse_pagination, paginate
from serializers import fair_edition_out
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_ALREADY_TERMINAL,
    ERR_NO_OPEN_CATEGORY, ERR_PROJECTS_UNINSPECTED, ERR_UNJUDGED_PROJECTS,
    ERR_STALE_VERSION, ERR_SCHOLARSHIP_POOL_MISSING, ERR_INVALID_REQUEST,
)
from services.calculations import (
    run_advancement_allocation, run_scholarship_waterfall,
    recompute_mentor_recognition,
)

bp = Blueprint("fair_editions", __name__)

_ALL_ROLES = ("FairDirector", "Mentor", "EthicsReviewer", "Judge",
              "OperationsLead", "SafetyInspector")

_VALID_ALGO = {"Z_SCORE", "MIN_MAX"}
_VALID_STATUS = {"SETUP", "REGISTRATION_OPEN", "REGISTRATION_CLOSED",
                 "JUDGING", "ADVANCEMENT_PUBLISHED", "AWARDS_FINALIZED",
                 "ARCHIVED"}


def _touch(e):
    e["updated_at"] = db.now_display_iso()
    e["version"] += 1


@bp.route("/science-fair/fair-editions", methods=["POST"])
def create_edition():
    body = V.get_json_body()
    # Priority 0 — shape validation before auth
    V.require_fields(body, ["name", "normalization_algorithm",
                            "max_judges_per_project", "min_quorum_ratio_pct"])
    name = V.req_str(body, "name")
    algo = V.req_enum(body, "normalization_algorithm", _VALID_ALGO)
    max_j = V.req_int(body, "max_judges_per_project")
    quorum = V.req_int(body, "min_quorum_ratio_pct")
    if max_j < 2:
        V.raise_err(ERR_INVALID_REQUEST,
                    "max_judges_per_project must be >= 2")
    if quorum < 1 or quorum > 100:
        V.raise_err(ERR_INVALID_REQUEST,
                    "min_quorum_ratio_pct must be between 1 and 100")

    require_roles("FairDirector")

    now = db.now_display_iso()
    e = {
        "id": db.new_id(),
        "name": name,
        "status": "SETUP",
        "normalization_algorithm": algo,
        "max_judges_per_project": max_j,
        "min_quorum_ratio_pct": quorum,
        "advancement_freeze": False,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.fair_editions[e["id"]] = e
    return success_object(fair_edition_out(e), 201)


@bp.route("/science-fair/fair-editions", methods=["GET"])
def list_editions():
    require_roles(*_ALL_ROLES)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = list(db.fair_editions.values())
    if status:
        if status not in _VALID_STATUS:
            raise_err(ERR_INVALID_REQUEST, f"Invalid status filter: {status}")
        items = [e for e in items if e["status"] == status]
    data, total = paginate(items, fair_edition_out, limit, offset)
    return success_list(data, limit, offset, total)


@bp.route("/science-fair/fair-editions/<eid>", methods=["GET"])
def get_edition(eid):
    require_roles(*_ALL_ROLES)
    e = db.fair_editions.get(eid)
    if e is None:
        raise_err(ERR_NOT_FOUND, f"Fair edition not found: {eid}")
    return success_object(fair_edition_out(e))


# ---------------------------------------------------------------------------
# Phase transitions
# ---------------------------------------------------------------------------

def _get_edition_or_404(eid):
    e = db.fair_editions.get(eid)
    if e is None:
        raise_err(ERR_NOT_FOUND, f"Fair edition not found: {eid}")
    return e


def _guard_terminal(e):
    if e["status"] == "ARCHIVED":
        raise_err(ERR_ALREADY_TERMINAL,
                  "Edition is ARCHIVED (terminal)")


@bp.route("/science-fair/fair-editions/<eid>/open-registration", methods=["POST"])
def open_registration(eid):
    V.get_json_body()
    require_roles("FairDirector")
    e = _get_edition_or_404(eid)
    _guard_terminal(e)
    if e["status"] != "SETUP":
        raise_err(ERR_INVALID_STATE,
                  f"Cannot open registration from status {e['status']}")
    # at least one OPEN category for this edition
    has_open = any(c["fair_edition_id"] == eid and c["status"] == "OPEN"
                   for c in db.categories.values())
    if not has_open:
        raise_err(ERR_NO_OPEN_CATEGORY,
                  "open-registration requires at least one OPEN category")
    e["status"] = "REGISTRATION_OPEN"
    _touch(e)
    return success_object(fair_edition_out(e))


@bp.route("/science-fair/fair-editions/<eid>/close-registration", methods=["POST"])
def close_registration(eid):
    V.get_json_body()
    require_roles("FairDirector")
    e = _get_edition_or_404(eid)
    _guard_terminal(e)
    if e["status"] != "REGISTRATION_OPEN":
        raise_err(ERR_INVALID_STATE,
                  f"Cannot close registration from status {e['status']}")

    # Sweep: DRAFT -> WITHDRAWN; SUBMITTED + ethics APPROVED/NOT_REQUIRED ->
    # CONFIRMED; SUBMITTED + PENDING stays SUBMITTED. Categories OPEN->LOCKED.
    for p in db.projects.values():
        if p["fair_edition_id"] != eid:
            continue
        if p["registration_status"] == "DRAFT":
            p["registration_status"] = "WITHDRAWN"
            _touch(p)
        elif p["registration_status"] == "SUBMITTED":
            if p["ethics_status"] in ("APPROVED", "NOT_REQUIRED"):
                p["registration_status"] = "CONFIRMED"
                _touch(p)
            # PENDING: stays SUBMITTED

    for c in db.categories.values():
        if c["fair_edition_id"] == eid and c["status"] == "OPEN":
            c["status"] = "LOCKED"
            _touch(c)

    e["status"] = "REGISTRATION_CLOSED"
    _touch(e)
    return success_object(fair_edition_out(e))


@bp.route("/science-fair/fair-editions/<eid>/begin-judging", methods=["POST"])
def begin_judging(eid):
    V.get_json_body()
    require_roles("FairDirector")
    e = _get_edition_or_404(eid)
    _guard_terminal(e)
    if e["status"] != "REGISTRATION_CLOSED":
        raise_err(ERR_INVALID_STATE,
                  f"Cannot begin judging from status {e['status']}")
    # every CONFIRMED project must be SCHEDULED or PASSED
    for p in db.projects.values():
        if (p["fair_edition_id"] == eid
                and p["registration_status"] == "CONFIRMED"
                and p["inspection_status"] not in ("SCHEDULED", "PASSED")):
            raise_err(ERR_PROJECTS_UNINSPECTED,
                      "begin-judging requires every CONFIRMED project to have "
                      "inspection_status in {SCHEDULED, PASSED}")
    e["status"] = "JUDGING"
    _touch(e)
    return success_object(fair_edition_out(e))


@bp.route("/science-fair/fair-editions/<eid>/publish-advancement", methods=["POST"])
def publish_advancement(eid):
    body = V.get_json_body()
    V.require_fields(body, ["expected_fair_edition_version"])
    expected = V.req_int(body, "expected_fair_edition_version")
    require_roles("FairDirector")
    e = _get_edition_or_404(eid)
    _guard_terminal(e)
    if e["status"] != "JUDGING":
        raise_err(ERR_INVALID_STATE,
                  f"Cannot publish advancement from status {e['status']}")
    # OCC check
    if expected != e["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_fair_edition_version does not match current "
                  "edition version")
    # every CONFIRMED project must be JUDGED
    for p in db.projects.values():
        if (p["fair_edition_id"] == eid
                and p["registration_status"] == "CONFIRMED"
                and p["judging_status"] != "JUDGED"):
            raise_err(ERR_UNJUDGED_PROJECTS,
                      "publish-advancement requires every CONFIRMED project "
                      "to be judging_status == JUDGED")

    run_advancement_allocation(e)
    e["advancement_freeze"] = True
    e["status"] = "ADVANCEMENT_PUBLISHED"
    _touch(e)
    return success_object(fair_edition_out(e))


@bp.route("/science-fair/fair-editions/<eid>/finalize-awards", methods=["POST"])
def finalize_awards(eid):
    V.get_json_body()
    require_roles("FairDirector")
    e = _get_edition_or_404(eid)
    _guard_terminal(e)
    if e["status"] != "ADVANCEMENT_PUBLISHED":
        raise_err(ERR_INVALID_STATE,
                  f"Cannot finalize awards from status {e['status']}")
    pool = None
    for sp in db.scholarship_pools.values():
        if sp["fair_edition_id"] == eid:
            pool = sp
            break
    if pool is None:
        raise_err(ERR_SCHOLARSHIP_POOL_MISSING,
                  "finalize-awards requires an existing ScholarshipPool")

    run_scholarship_waterfall(e)
    recompute_mentor_recognition(eid)
    e["status"] = "AWARDS_FINALIZED"
    _touch(e)
    return success_object(fair_edition_out(e))


@bp.route("/science-fair/fair-editions/<eid>/archive", methods=["POST"])
def archive_edition(eid):
    V.get_json_body()
    require_roles("FairDirector")
    e = _get_edition_or_404(eid)
    _guard_terminal(e)
    if e["status"] != "AWARDS_FINALIZED":
        raise_err(ERR_INVALID_STATE,
                  f"Cannot archive from status {e['status']}")
    e["status"] = "ARCHIVED"
    _touch(e)
    return success_object(fair_edition_out(e))
