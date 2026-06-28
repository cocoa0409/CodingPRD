"""Top-level cap-table-entry read endpoints (PRD 3.7)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_auth, require_role
from pagination import paginate
from response import success
from serializers import cap_table_entry_out

bp = Blueprint("cap_table", __name__)

READ_ROLES = {"Issuer", "Investor", "ComplianceOfficer"}


@bp.get("/cap-table-entries/<id>")
def get_cap_table_entry(id):
    uid, role = get_auth()
    require_role(role, READ_ROLES)
    rec = db.cap_table_entries.get(id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Cap-table entry not found")
    return success(cap_table_entry_out(rec))


@bp.get("/cap-table-entries")
def list_cap_table_entries():
    uid, role = get_auth()
    require_role(role, READ_ROLES)
    rows = list(db.cap_table_entries.values())
    for field in ("offering_id", "investor_id", "investment_id"):
        val = request.args.get(field)
        if val is not None:
            rows = [r for r in rows if r[field] == val]
    page, meta = paginate(rows)
    return success([cap_table_entry_out(r) for r in page], pagination=meta)
