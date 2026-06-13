"""ServiceCategory endpoints + the test-only clock (PRD §3.1, §4).

POST /service-categories is a PlatformAdmin operation that the PRD lists among
the self-registration endpoints exempt from authentication. We accept it without
mandatory auth headers but only when the caller is the admin (or unauthenticated,
treated as admin self-config). Reads require the standard auth + role checks.
"""
import re

from flask import Blueprint, request, g

from db import store
from errors import ApiError
from middleware import require_role, _read_headers, VALID_ROLES
from models import category_common, serialize, SERVICE_CATEGORY_FIELDS
from response import object_response, array_response, empty_response
from timeutil import parse_dt, now_iso
from services.lookup import (
    require_body, require_string, require_enum, require_int, require_bool,
    require_number, require_string_array, get_or_404, paginate,
    sorted_by_creation,
)

bp = Blueprint("catalog", __name__)

_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,31}$")


@bp.post("/service-categories")
def create_service_category():
    # PRD §2.1: this is one of the three no-auth self-registration endpoints. If
    # auth headers are present they must name PlatformAdmin (the only permitted
    # role); when absent the request is allowed as admin self-config.
    user_id, role = _read_headers()
    if role is not None:
        if role not in VALID_ROLES or not user_id:
            raise ApiError("ERR_UNAUTHENTICATED", "Invalid auth headers")
        if role != "PlatformAdmin":
            raise ApiError("ERR_UNAUTHORIZED", "Only PlatformAdmin may create categories")

    body = require_body()
    code = require_string(body, "code")
    if not _CODE_RE.match(code):
        raise ApiError("ERR_INVALID_REQUEST", "code must match ^[A-Z][A-Z0-9_]{1,31}$")
    name = require_string(body, "name")
    pricing_model = require_enum(body, "pricing_model", {"HOURLY", "FLAT"})
    requires_license = require_bool(body, "requires_license", required=False, default=False)
    flat_task_fee = require_int(body, "flat_task_fee_cents", required=False, default=None, minimum=0)
    hourly_rate = require_int(body, "hourly_rate_cents", required=False, default=None, minimum=0)
    instant_eligible = require_bool(body, "instant_quote_eligible", required=False, default=False)
    instant_flat = require_int(body, "instant_quote_flat_cents", required=False, default=None, minimum=0)
    callback_days = require_int(body, "callback_warranty_days", required=False, default=30, minimum=0)
    skill_tags = require_string_array(body, "skill_tags", required=False, default=[])

    # ERR_VALIDATION (422): semantic coherence of pricing fields (PRD §3.1).
    if pricing_model == "FLAT":
        if flat_task_fee is None or hourly_rate is not None:
            raise ApiError("ERR_VALIDATION",
                           "FLAT category must carry flat_task_fee_cents and null hourly_rate_cents")
    else:  # HOURLY
        if hourly_rate is None or flat_task_fee is not None:
            raise ApiError("ERR_VALIDATION",
                           "HOURLY category must carry hourly_rate_cents and null flat_task_fee_cents")
    if instant_eligible:
        if instant_flat is None:
            raise ApiError("ERR_VALIDATION",
                           "instant_quote_eligible category must carry instant_quote_flat_cents")
    else:
        if instant_flat is not None:
            raise ApiError("ERR_VALIDATION",
                           "instant_quote_flat_cents must be null when not instant_quote_eligible")

    # unique code across ServiceCategory.
    for c in store.service_categories.values():
        if c["code"] == code:
            raise ApiError("ERR_VALIDATION", "code must be unique across ServiceCategory")

    cat = {
        "code": code,
        "name": name,
        "requires_license": requires_license,
        "pricing_model": pricing_model,
        "flat_task_fee_cents": flat_task_fee,
        "hourly_rate_cents": hourly_rate,
        "instant_quote_eligible": instant_eligible,
        "instant_quote_flat_cents": instant_flat,
        "callback_warranty_days": callback_days,
        "skill_tags": skill_tags,
    }
    category_common(cat)
    store.service_categories[cat["id"]] = cat
    return object_response(serialize(cat, SERVICE_CATEGORY_FIELDS), status=201)


@bp.get("/service-categories/<cid>")
@require_role({"PlatformAdmin", "Customer", "Pro", "Dispatcher"})
def get_service_category(cid):
    cat = get_or_404(store.service_categories, cid)
    return object_response(serialize(cat, SERVICE_CATEGORY_FIELDS))


@bp.get("/service-categories")
@require_role({"PlatformAdmin", "Customer", "Pro", "Dispatcher"})
def list_service_categories():
    items = sorted_by_creation(list(store.service_categories.values()))
    page, limit, offset, total = paginate(request.args, items)
    return array_response([serialize(c, SERVICE_CATEGORY_FIELDS) for c in page],
                          limit, offset, total)


def _v_set_clock(body):
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field: to_iso8601")
    try:
        dt = parse_dt(body["to_iso8601"])
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 datetime")
    return {"dt": dt}


@bp.post("/_clock/set_current_utc")
@require_role({"PlatformAdmin"}, validate=_v_set_clock)
def set_clock():
    store.set_clock(g.validated["dt"])
    return empty_response()
