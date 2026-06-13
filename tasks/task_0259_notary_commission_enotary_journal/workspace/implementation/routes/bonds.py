"""Bond lifecycle routes (PRD §3.2, §3.3)."""
from flask import Blueprint, request

from db import store, new_common_fields, touch
from domain import find_bond, find_notary, find_jurisdiction, bond_coverage_conflicts
from errors import err
from middleware import endpoint
from response import success, list_response
from serialize import view, view_list
from validation import (
    get_body, require_str, require_int, require_datetime, non_negative_cents,
    parse_pagination, paginate,
)

bp = Blueprint("bonds", __name__)


@bp.post("/bonds")
@endpoint(("CommissionAuthority",))
def create_bond():
    body = get_body()
    notary_id = require_str(body, "notary_id")
    jurisdiction_id = require_str(body, "jurisdiction_id")
    face_value = require_int(body, "face_value_cents")
    start_dt = require_datetime(body, "coverage_start_at")
    end_dt = require_datetime(body, "coverage_end_at")

    # Existence (404) before semantic checks (PRD §2.8 / §2.9).
    find_notary(notary_id)
    find_jurisdiction(jurisdiction_id)
    non_negative_cents(face_value, "face_value_cents")
    if not (end_dt > start_dt):
        raise err("ERR_VALIDATION", "coverage_end_at must be after coverage_start_at")

    rec = dict(new_common_fields())
    rec.update({
        "notary_id": notary_id,
        "jurisdiction_id": jurisdiction_id,
        "face_value_cents": face_value,
        "coverage_start_at": body["coverage_start_at"],
        "coverage_end_at": body["coverage_end_at"],
        "claims_paid_cents": 0,
        "remaining_cents": 0,
        "status": "PENDING",
        # Internal parsed datetimes for overlap math.
        "_coverage_start_dt": start_dt,
        "_coverage_end_dt": end_dt,
    })
    store.bonds[rec["id"]] = rec
    return success(view(rec), status=201)


@bp.get("/bonds/<bond_id>")
@endpoint(("CommissionAuthority", "Notary"))
def get_bond(bond_id):
    return success(view(find_bond(bond_id)))


@bp.get("/bonds")
@endpoint(("CommissionAuthority", "Notary"))
def list_bonds():
    limit, offset = parse_pagination()
    recs = list(store.bonds.values())
    nid = request.args.get("notary_id")
    jid = request.args.get("jurisdiction_id")
    status = request.args.get("status")
    if nid is not None:
        recs = [r for r in recs if r["notary_id"] == nid]
    if jid is not None:
        recs = [r for r in recs if r["jurisdiction_id"] == jid]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, total = paginate(recs, limit, offset)
    return list_response(view_list(page), limit, offset, total)


@bp.post("/bonds/<bond_id>/activate")
@endpoint(("CommissionAuthority",))
def activate_bond(bond_id):
    bond = find_bond(bond_id)
    if bond["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Bond is not PENDING")
    juris = store.jurisdictions.get(bond["jurisdiction_id"])
    if bond["face_value_cents"] < juris["bond_minimum_cents"]:
        raise err("ERR_BOND_BELOW_MINIMUM", "Bond face value below jurisdiction minimum")
    if bond_coverage_conflicts(bond, bond["_coverage_start_dt"], bond["_coverage_end_dt"]):
        raise err("ERR_BOND_COVERAGE_OVERLAP", "Bond coverage overlaps another ACTIVE bond")
    bond["status"] = "ACTIVE"
    bond["remaining_cents"] = bond["face_value_cents"]
    bond["claims_paid_cents"] = 0
    touch(bond)
    return success(view(bond))
