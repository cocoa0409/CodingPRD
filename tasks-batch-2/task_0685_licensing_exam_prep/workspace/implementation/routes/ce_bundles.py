"""CEBundle routes (PRD §3.1, §3.7)."""
from flask import Blueprint, request

from db import db, stamp_create
from response import success, list_success
from middleware import get_auth, require_role, pagination_params, paginate
from services import validate as V
from services.serialize import public, public_list
from services.lookups import get_ce_bundle, get_license_program

bp = Blueprint("ce_bundles", __name__)


@bp.post("/ce-bundles")
def create_bundle():
    _, role = get_auth()
    require_role(role, {"ContentAdmin"})
    data = V.body()
    license_program_id = V.as_str(V.require(data, "license_program_id"),
                                  "license_program_id")
    ce_credits_total = V.as_int(V.require(data, "ce_credits_total"),
                                "ce_credits_total", minimum=1)
    modules_total = V.as_int(V.require(data, "modules_total"),
                             "modules_total", minimum=1)
    # existence of referenced program (priority 3)
    get_license_program(license_program_id)
    rec = {
        "license_program_id": license_program_id,
        "ce_credits_total": ce_credits_total,
        "modules_total": modules_total,
    }
    stamp_create(rec)
    db.ce_bundles[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.get("/ce-bundles/<bid>")
def get_bundle(bid):
    _, role = get_auth()
    require_role(role, {"ContentAdmin", "Learner"})
    rec = get_ce_bundle(bid)
    return success(public(rec))


@bp.get("/ce-bundles")
def list_bundles():
    _, role = get_auth()
    require_role(role, {"ContentAdmin", "Learner"})
    limit, offset = pagination_params()
    rows = list(db.ce_bundles.values())
    lpid = request.args.get("license_program_id")
    if lpid is not None:
        rows = [r for r in rows if r["license_program_id"] == lpid]
    rows.sort(key=lambda r: r["_seq"])
    window, total, has_more = paginate(rows, limit, offset)
    return list_success(public_list(window), limit, offset, total, has_more)


@bp.get("/ce-bundles/<bid>/ce-awards")
def list_bundle_awards(bid):
    _, role = get_auth()
    require_role(role, {"ContentAdmin", "Learner"})
    get_ce_bundle(bid)
    limit, offset = pagination_params()
    rows = [a for a in db.ce_credit_awards.values() if a["ce_bundle_id"] == bid]
    rows.sort(key=lambda r: r["_seq"])
    window, total, has_more = paginate(rows, limit, offset)
    return list_success(public_list(window), limit, offset, total, has_more)
