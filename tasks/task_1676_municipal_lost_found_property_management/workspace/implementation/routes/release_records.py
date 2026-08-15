"""Release documentation records — append-only (PRD 3.5)."""
from flask import Blueprint

from db import db
from middleware import authorized, STAFF_ROLES
from response import success_object, success_list
from validate import require_path, pagination_params, opt_query_str, paginate

bp = Blueprint("release_records", __name__)


@bp.get("/release-records")
def list_release_records():
    limit, offset = pagination_params()
    item_id = opt_query_str("item_id")
    claim_id = opt_query_str("claim_id")
    authorized(STAFF_ROLES)
    recs = list(db["release_records"].values())
    if item_id is not None:
        recs = [r for r in recs if r["item_id"] == item_id]
    if claim_id is not None:
        recs = [r for r in recs if r["claim_id"] == claim_id]
    page, total = paginate(recs, limit, offset)
    return success_list(page, total, limit, offset)


@bp.get("/release-records/<record_id>")
def get_release_record(record_id):
    authorized(STAFF_ROLES)
    rec = require_path("release_records", record_id)
    return success_object(rec)
