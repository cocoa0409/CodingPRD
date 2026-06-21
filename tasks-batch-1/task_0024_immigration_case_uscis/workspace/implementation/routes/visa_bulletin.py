"""Visa Bulletin publish + list."""
from __future__ import annotations

import re
from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import require_fields, require_string, require_enum


bp = Blueprint("visa_bulletin", __name__)


BULLETIN_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PREFERENCE_CHOICES = {"F1", "F2A", "F2B", "F3", "F4", "IR"}
COUNTRY_CHOICES = {"WORLDWIDE", "CHINA", "INDIA", "MEXICO", "PHILIPPINES"}
CHART_CHOICES = {"FINAL_ACTION", "FILING_DATE"}


@bp.post("/uscis/visa-bulletin")
def publish_entry():
    require_auth(["FieldOfficeAdmin"])()
    body = get_json_body()
    require_fields(body, ["bulletin_month", "preference_category", "country", "chart_type", "cutoff_date"])
    month = body["bulletin_month"]
    pref = body["preference_category"]
    country = body["country"]
    chart = body["chart_type"]
    cutoff = body["cutoff_date"]

    require_string(month, "bulletin_month")
    if not BULLETIN_MONTH_RE.match(month):
        raise APIError(ERR_INVALID_REQUEST, 400, "bulletin_month must be YYYY-MM")
    require_enum(pref, PREFERENCE_CHOICES, "preference_category")
    require_enum(country, COUNTRY_CHOICES, "country")
    require_enum(chart, CHART_CHOICES, "chart_type")
    require_string(cutoff, "cutoff_date")
    if cutoff != "CURRENT" and not ISO_DATE_RE.match(cutoff):
        raise APIError(ERR_INVALID_REQUEST, 400, "cutoff_date must be 'CURRENT' or ISO YYYY-MM-DD")

    # Uniqueness: (bulletin_month, preference_category, country, chart_type)
    for e in db.visa_bulletin.values():
        if (
            e.get("bulletin_month") == month
            and e.get("preference_category") == pref
            and e.get("country") == country
            and e.get("chart_type") == chart
        ):
            raise APIError(ERR_INVALID_REQUEST, 400, "Visa bulletin entry already exists for this key")

    entry = {
        "bulletin_month": month,
        "preference_category": pref,
        "country": country,
        "chart_type": chart,
        "cutoff_date": cutoff,
    }
    db.stamp_immutable(entry)
    db.visa_bulletin[entry["id"]] = entry
    return ok_object(entry, 201)


@bp.get("/uscis/visa-bulletin")
def list_entries():
    require_auth(["Applicant", "Attorney", "Officer", "FieldOfficeAdmin"])()
    limit, offset = paginate_params(request.args)

    month = request.args.get("bulletin_month")
    pref = request.args.get("preference_category")
    country = request.args.get("country")
    chart = request.args.get("chart_type")

    items = list(db.visa_bulletin.values())
    if month is not None:
        items = [e for e in items if e.get("bulletin_month") == month]
    if pref is not None:
        items = [e for e in items if e.get("preference_category") == pref]
    if country is not None:
        items = [e for e in items if e.get("country") == country]
    if chart is not None:
        items = [e for e in items if e.get("chart_type") == chart]

    items.sort(key=lambda e: e.get("created_at", ""))
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)
