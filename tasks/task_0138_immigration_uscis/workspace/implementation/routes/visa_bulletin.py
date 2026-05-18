"""Visa Bulletin endpoints (Supervisor admin + universal listing)."""
from __future__ import annotations

import re

from flask import Blueprint, request

from config import CHART_TYPES, VB_PREFERENCE_CATEGORIES
from db import store
from errors import err_validation
from middleware import require_auth
from response import list_success, success
from services.serializers import serialize_visa_bulletin
from utils import is_valid_bulletin_month, is_valid_country_code, new_uuid, parse_iso_date

from routes._helpers import (
    get_json,
    parse_pagination,
    paginate_and_sort,
    require_enum,
    require_string,
)


bp = Blueprint("visa_bulletin", __name__)


_CUTOFF_LITERALS = {"CURRENT", "UNAVAILABLE"}


@bp.post("/admin/visa-bulletin")
@require_auth(["Supervisor"])
def publish_visa_bulletin():
    body = get_json()

    bulletin_month = require_string(body, "bulletin_month")
    if not is_valid_bulletin_month(bulletin_month):
        raise err_validation("bulletin_month must match YYYY-MM (months 01-12).")

    chart_type = require_enum(body, "chart_type", CHART_TYPES)
    preference_category = require_enum(body, "preference_category", VB_PREFERENCE_CATEGORIES)

    country = require_string(body, "country")
    if country != "ROW" and not is_valid_country_code(country):
        raise err_validation("country must be a 3-letter ISO 3166-1 alpha-3 code or the literal 'ROW'.")

    cutoff_date = require_string(body, "cutoff_date")
    if cutoff_date not in _CUTOFF_LITERALS:
        if parse_iso_date(cutoff_date) is None:
            raise err_validation("cutoff_date must be a YYYY-MM-DD date or one of 'CURRENT'/'UNAVAILABLE'.")

    with store.lock:
        now = store.now()
        entity = {
            "id": new_uuid(),
            "created_at": now,
            "bulletin_month": bulletin_month,
            "chart_type": chart_type,
            "preference_category": preference_category,
            "country": country,
            "cutoff_date": cutoff_date,
            "published_at": now,
        }
        store.visa_bulletins[entity["id"]] = entity

    return success(serialize_visa_bulletin(entity), 201)


@bp.get("/admin/visa-bulletin")
@require_auth(["Petitioner", "Beneficiary", "Officer", "Supervisor"])
def list_visa_bulletin():
    limit, offset = parse_pagination()

    bulletin_month = request.args.get("bulletin_month")
    chart_type = request.args.get("chart_type")
    preference_category = request.args.get("preference_category")
    country = request.args.get("country")

    rows = list(store.visa_bulletins.values())

    def matches(r):
        if bulletin_month and r["bulletin_month"] != bulletin_month:
            return False
        if chart_type and r["chart_type"] != chart_type:
            return False
        if preference_category and r["preference_category"] != preference_category:
            return False
        if country and r["country"] != country:
            return False
        return True

    filtered = [r for r in rows if matches(r)]
    page, total = paginate_and_sort(filtered, limit, offset)
    return list_success([serialize_visa_bulletin(r) for r in page], limit, offset, total, 200)


@bp.post("/admin/visa-bulletin/chart-in-effect")
@require_auth(["Supervisor"])
def set_chart_in_effect():
    body = get_json()
    chart_type = require_enum(body, "chart_type", CHART_TYPES)
    with store.lock:
        store.chart_in_effect = chart_type
    return success({"chart_in_effect": chart_type}, 200)
