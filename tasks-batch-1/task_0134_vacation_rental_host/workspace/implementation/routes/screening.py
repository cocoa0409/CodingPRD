"""Standalone screening-result reads (PRD §4)."""
from flask import Blueprint, request

from db import db
from middleware import require_auth
from response import success, list_success
from services.access import get_or_404
from services.listing_util import sort_and_paginate
from models import serialize
from validators import parse_pagination

bp = Blueprint("screening", __name__)


@bp.get("/screening-results/<sid>")
def get_screening(sid):
    require_auth({"Guest", "Host", "PlatformAdmin"})
    sr = get_or_404(db.screening_results, sid)
    return success(serialize(sr))


@bp.get("/screening-results")
def list_screenings():
    require_auth({"Guest", "Host", "PlatformAdmin"})
    limit, offset = parse_pagination()
    booking_id = request.args.get("booking_id")
    guest_id = request.args.get("guest_id")
    status = request.args.get("status")
    items = []
    for s in db.screening_results.values():
        if booking_id is not None and s["booking_id"] != booking_id:
            continue
        if guest_id is not None and s["guest_id"] != guest_id:
            continue
        if status is not None and s["status"] != status:
            continue
        items.append(s)
    page, total = sort_and_paginate(items, limit, offset)
    return list_success(page, limit, offset, total)
