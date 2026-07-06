"""License endpoints (PRD §3.7, §2.10)."""
from flask import Blueprint, request

from db import db
from middleware import authenticate
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_INTERVAL,
    ERR_INTERVAL_OVERLAP, ERR_INVALID_STATE, ERR_PROJECT_WRONG_STAGE,
)
from helpers import (
    require_role, get_json_body, require_fields, require_enum, as_string,
    require_nonneg_int, parse_pagination, paginate, get_studio,
)
from util import parse_iso8601
from response import success, success_list
from serialize import view
from services.calc import license_billable
from services.ledger import project_licenses

bp = Blueprint("licenses", __name__)

KINDS = {"STOCK", "FONT"}


def _resolve_license(studio_id, license_id):
    get_studio(studio_id)
    lc = db.licenses.get(license_id)
    if lc is None:
        raise err(ERR_NOT_FOUND, "License not found")
    proj = db.projects.get(lc["project_id"])
    if proj is None or proj["studio_id"] != studio_id:
        raise err(ERR_NOT_FOUND, "License not found in this studio")
    return proj, lc


def _closed_overlap(a_from, a_until, b_from, b_until):
    """Closed intervals [a_from, a_until] and [b_from, b_until] overlap iff they
    share any instant: a_from <= b_until and b_from <= a_until (PRD §2.10)."""
    return a_from <= b_until and b_from <= a_until


@bp.route("/studios/<studio_id>/licenses", methods=["POST"])
def reserve_license(studio_id):
    caller = authenticate()
    require_role(caller, "StudioOps")
    studio = get_studio(studio_id)
    body = get_json_body()
    require_fields(body, "project_id", "kind", "cost_cents", "valid_from", "valid_until")
    project_id = as_string(body["project_id"], "project_id")
    kind = require_enum(body["kind"], "kind", KINDS)
    cost_cents = require_nonneg_int(body["cost_cents"], "cost_cents")
    valid_from_raw = as_string(body["valid_from"], "valid_from")
    valid_until_raw = as_string(body["valid_until"], "valid_until")
    valid_from = parse_iso8601(valid_from_raw)
    valid_until = parse_iso8601(valid_until_raw)
    if valid_from is None or valid_until is None:
        raise err(ERR_INVALID_REQUEST, "valid_from/valid_until must be ISO 8601 datetimes")

    # Body-referenced existence (§2.9).
    proj = db.projects.get(project_id)
    if proj is None or proj["studio_id"] != studio_id:
        raise err(ERR_NOT_FOUND, "Project not found in this studio")

    # Malformed window: start not strictly before end (PRD §2.10).
    if not (valid_from < valid_until):
        raise err(ERR_INVALID_INTERVAL, "valid_from must be strictly before valid_until")

    # Closed-interval overlap with another license window on the same project
    # (PRD §2.10). The rule names "another license window on the same project"
    # without status qualification, so all license windows are considered.
    for other in project_licenses(project_id):
        of = parse_iso8601(other["valid_from"])
        ou = parse_iso8601(other["valid_until"])
        if _closed_overlap(valid_from, valid_until, of, ou):
            raise err(ERR_INTERVAL_OVERLAP, "License window overlaps an existing license")

    billable = license_billable(cost_cents, studio["license_markup_pct"])

    rec = db.create(db.licenses, {
        "project_id": project_id,
        "kind": kind,
        "cost_cents": cost_cents,
        "billable_cents": billable,
        "valid_from": valid_from_raw,
        "valid_until": valid_until_raw,
        "status": "RESERVED",
    })
    return success(view(rec), status=201)


@bp.route("/studios/<studio_id>/licenses/<license_id>", methods=["GET"])
def get_license(studio_id, license_id):
    caller = authenticate()
    require_role(caller, "StudioOps", "BillingOps")
    proj, lc = _resolve_license(studio_id, license_id)
    return success(view(lc), status=200)


@bp.route("/studios/<studio_id>/licenses", methods=["GET"])
def list_licenses(studio_id):
    caller = authenticate()
    require_role(caller, "StudioOps", "BillingOps")
    get_studio(studio_id)
    limit, offset = parse_pagination()

    studio_project_ids = {
        p["id"] for p in db.projects.values() if p["studio_id"] == studio_id
    }
    records = [lc for lc in db.licenses.values()
               if lc["project_id"] in studio_project_ids]
    filter_project = request.args.get("project_id")
    if filter_project is not None:
        records = [lc for lc in records if lc["project_id"] == filter_project]

    window, total = paginate(records, limit, offset)
    return success_list([view(r) for r in window], limit, offset, total)


@bp.route("/studios/<studio_id>/licenses/<license_id>/clear", methods=["POST"])
def clear_license(studio_id, license_id):
    caller = authenticate()
    require_role(caller, "StudioOps")
    proj, lc = _resolve_license(studio_id, license_id)
    # RESERVED -> CLEARED.
    if lc["status"] != "RESERVED":
        raise err(ERR_INVALID_STATE, "License is not RESERVED")
    # Parent project must not be terminal.
    if proj["status"] in ("COMPLETED", "CANCELLED"):
        raise err(ERR_PROJECT_WRONG_STAGE, "Project is terminal")
    lc["status"] = "CLEARED"
    db.touch(lc)
    return success(view(lc), status=200)
