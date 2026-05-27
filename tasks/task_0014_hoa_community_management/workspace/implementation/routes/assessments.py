"""Assessment endpoints (create, fetch, list, projected-balance, waive)."""
from __future__ import annotations

from flask import Blueprint, request

import db
import recompute
from errors import ERR_INVALID_STATE, raise_err
from middleware import auth_required
from response import list_success, success
from .helpers import (
    fetch_or_404,
    get_json_body,
    paginate,
    parse_pagination,
    require_enum,
    require_int,
    require_str,
)


bp = Blueprint("assessments", __name__)


def _serialize(a: dict) -> dict:
    return {
        "id": a["id"],
        "property_id": a["property_id"],
        "kind": a["kind"],
        "principal_cents": int(a["principal_cents"]),
        "late_fee_cents": int(a["late_fee_cents"]),
        "paid_cents": int(a["paid_cents"]),
        "outstanding_cents": int(a["outstanding_cents"]),
        "due_date": a["due_date"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


@bp.route("/hoa/assessments", methods=["POST"])
@auth_required({"Treasurer"})
def create_assessment():
    body = get_json_body()
    property_id = require_str(body, "property_id")
    kind = require_enum(body, "kind", {"REGULAR", "SPECIAL"})
    principal_cents = require_int(body, "principal_cents", min_value=0)
    due_date_s = require_str(body, "due_date")
    try:
        due_date = db.parse_iso(due_date_s)
    except ValueError:
        raise_err("ERR_INVALID_REQUEST", "Invalid due_date ISO 8601 string")

    prop = fetch_or_404(db.properties, property_id, "Property")

    record = {
        **db.make_common_fields(),
        "property_id": property_id,
        "kind": kind,
        "principal_cents": principal_cents,
        "late_fee_cents": 0,
        "paid_cents": 0,
        "outstanding_cents": principal_cents,
        "due_date": db.fmt_iso(due_date),
        "status": "DUE",
    }
    db.assessments[record["id"]] = record

    # Side effect: recompute property's account_balance. Per PRD §2.6/§3.4, the
    # lien cascade is anchored to the DUE→OVERDUE transition; a brand-new DUE
    # assessment does not by itself trigger lien filing.
    recompute.recompute_property_account_balance(prop)

    return success(_serialize(record), status=201)


@bp.route("/hoa/assessments/<aid>", methods=["GET"])
@auth_required({"PlatformAdmin", "BoardPresident", "BoardSecretary",
                "Treasurer", "ACCMember", "HomeOwner"})
def fetch_assessment(aid):
    a = fetch_or_404(db.assessments, aid, "Assessment")
    return success(_serialize(a))


@bp.route("/hoa/assessments", methods=["GET"])
@auth_required({"PlatformAdmin", "BoardPresident", "BoardSecretary",
                "Treasurer", "ACCMember", "HomeOwner"})
def list_assessments():
    limit, offset = parse_pagination()
    property_id = request.args.get("property_id")
    status = request.args.get("status")
    rows = list(db.assessments.values())
    if property_id is not None:
        rows = [r for r in rows if r["property_id"] == property_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return list_success([_serialize(r) for r in page], total, limit, offset)


@bp.route("/hoa/assessments/<aid>/projected-balance", methods=["GET"])
@auth_required({"Treasurer", "HomeOwner"})
def projected_balance(aid):
    a = fetch_or_404(db.assessments, aid, "Assessment")
    as_of_s = request.args.get("as_of_iso8601")
    if not as_of_s:
        raise_err("ERR_INVALID_REQUEST",
                  "Query parameter as_of_iso8601 is required")
    try:
        as_of = db.parse_iso(as_of_s)
    except ValueError:
        raise_err("ERR_INVALID_REQUEST",
                  "Invalid as_of_iso8601 ISO 8601 string")

    prop = db.properties.get(a["property_id"])
    if prop is None:
        raise_err("ERR_NOT_FOUND", "Property not found")
    community = db.communities.get(prop["community_id"])
    if community is None:
        raise_err("ERR_NOT_FOUND", "Community not found")

    due_date = db.parse_iso(a["due_date"])
    projected_fee = recompute.compute_late_fee_projection(
        int(a["principal_cents"]), due_date, community, as_of)
    paid = int(a["paid_cents"])
    principal = int(a["principal_cents"])
    projected_outstanding = max(0, principal + projected_fee - paid)
    return success({
        "projected_late_fee_cents": int(projected_fee),
        "projected_outstanding_cents": int(projected_outstanding),
    })


@bp.route("/hoa/assessments/<aid>/waive", methods=["POST"])
@auth_required({"BoardPresident"})
def waive_assessment(aid):
    a = fetch_or_404(db.assessments, aid, "Assessment")
    if a["status"] != "DUE":
        raise_err(ERR_INVALID_STATE,
                  f"Assessment must be DUE to waive (currently {a['status']})")
    a["status"] = "WAIVED"
    db.bump(a)
    prop = db.properties.get(a["property_id"])
    if prop is not None:
        recompute.recompute_property_account_balance(prop)
    return success(_serialize(a))
