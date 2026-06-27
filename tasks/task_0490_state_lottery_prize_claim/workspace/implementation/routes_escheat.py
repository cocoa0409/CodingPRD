"""EscheatRecord endpoints (PRD 3.10)."""
from flask import Blueprint, request

from db import db
from middleware import get_auth, require_roles
from models import (serialize, get_or_404, parse_pagination, paginate,
                    sort_by_created)
from response import success

escheat_bp = Blueprint("escheat", __name__)


def _serialize_record(r):
    return serialize(r)


@escheat_bp.route("/escheat-records/<rid>", methods=["GET"])
def get_record(rid):
    _, role = get_auth()
    require_roles(role, {"LotteryOfficer"})
    record = get_or_404(db.escheat_records, rid, "escheat record")
    return success(_serialize_record(record), 200)


@escheat_bp.route("/escheat-records", methods=["GET"])
def list_records():
    _, role = get_auth()
    require_roles(role, {"LotteryOfficer"})
    limit, offset = parse_pagination(request.args)
    rows = list(db.escheat_records.values())
    ticket_f = request.args.get("ticket_id")
    if ticket_f is not None:
        rows = [r for r in rows if r["ticket_id"] == ticket_f]
    rows = sort_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return success([_serialize_record(r) for r in page], 200, pagination=meta)
