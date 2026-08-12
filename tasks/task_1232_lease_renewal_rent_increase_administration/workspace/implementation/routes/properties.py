from flask import Blueprint, request

from db import store
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_PROPERTY_NOT_FOUND, ERR_POLICY_NOT_FOUND,
    ERR_STALE_PROPERTY_VERSION,
)
from middleware import require_roles
from response import success_object, success_list
from services.calc import compute_retention_metrics, compute_expiration_forecast
from services.common import new_entity, touch
from timeutil import parse_date

bp = Blueprint("properties", __name__)


def _serialize(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "name": p["name"],
        "rent_cap_policy_id": p["rent_cap_policy_id"],
        "min_term_months": p["min_term_months"],
        "max_term_months": p["max_term_months"],
    }


def _get_pagination():
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "limit/offset must be integers")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


@bp.route("/properties", methods=["POST"])
def create_property():
    require_roles("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    rent_cap_policy_id = body.get("rent_cap_policy_id")
    min_t = body.get("min_term_months")
    max_t = body.get("max_term_months")
    if not name or not isinstance(name, str):
        raise_err(ERR_INVALID_REQUEST, "name required")
    if not rent_cap_policy_id or not isinstance(rent_cap_policy_id, str):
        raise_err(ERR_INVALID_REQUEST, "rent_cap_policy_id required")
    if not isinstance(min_t, int) or isinstance(min_t, bool):
        raise_err(ERR_INVALID_REQUEST, "min_term_months must be int")
    if not isinstance(max_t, int) or isinstance(max_t, bool):
        raise_err(ERR_INVALID_REQUEST, "max_term_months must be int")
    if min_t < 1:
        raise_err(ERR_INVALID_REQUEST, "min_term_months must be >= 1")
    if max_t < min_t:
        raise_err(ERR_INVALID_REQUEST, "max_term_months must be >= min_term_months")
    # Existence of FK
    if rent_cap_policy_id not in store.rent_cap_policies:
        raise_err(ERR_POLICY_NOT_FOUND, "rent_cap_policy not found")
    rec = new_entity()
    rec.update({
        "name": name,
        "rent_cap_policy_id": rent_cap_policy_id,
        "min_term_months": min_t,
        "max_term_months": max_t,
    })
    store.properties[rec["id"]] = rec
    return success_object(_serialize(rec), status_code=201)


@bp.route("/properties", methods=["GET"])
def list_properties():
    require_roles("PlatformAdmin", "RegionalDirector", "PropertyManager", "LeasingAgent")
    limit, offset = _get_pagination()
    rcp = request.args.get("rent_cap_policy_id")
    items = list(store.properties.values())
    if rcp:
        items = [p for p in items if p["rent_cap_policy_id"] == rcp]
    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([_serialize(p) for p in page], limit, offset, total)


@bp.route("/properties/<pid>", methods=["GET"])
def get_property(pid):
    require_roles("PlatformAdmin", "RegionalDirector", "PropertyManager", "LeasingAgent")
    p = store.properties.get(pid)
    if p is None:
        raise_err(ERR_PROPERTY_NOT_FOUND, "property not found")
    return success_object(_serialize(p))


@bp.route("/properties/<pid>", methods=["PATCH"])
def patch_property(pid):
    require_roles("PlatformAdmin")
    p = store.properties.get(pid)
    if p is None:
        raise_err(ERR_PROPERTY_NOT_FOUND, "property not found")
    body = request.get_json(silent=True) or {}
    # Schema validation
    if "name" in body and (not isinstance(body["name"], str) or not body["name"]):
        raise_err(ERR_INVALID_REQUEST, "name must be string")
    new_min = body.get("min_term_months")
    new_max = body.get("max_term_months")
    if new_min is not None and (not isinstance(new_min, int) or isinstance(new_min, bool)):
        raise_err(ERR_INVALID_REQUEST, "min_term_months must be int")
    if new_max is not None and (not isinstance(new_max, int) or isinstance(new_max, bool)):
        raise_err(ERR_INVALID_REQUEST, "max_term_months must be int")
    final_min = new_min if new_min is not None else p["min_term_months"]
    final_max = new_max if new_max is not None else p["max_term_months"]
    if final_min < 1:
        raise_err(ERR_INVALID_REQUEST, "min_term_months must be >= 1")
    if final_max < final_min:
        raise_err(ERR_INVALID_REQUEST, "max_term_months must be >= min_term_months")
    # OCC
    expected = body.get("expected_property_version")
    if expected is not None:
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise_err(ERR_INVALID_REQUEST, "expected_property_version must be int")
        if expected != p["version"]:
            raise_err(ERR_STALE_PROPERTY_VERSION, "stale property version")
    if "name" in body:
        p["name"] = body["name"]
    if new_min is not None:
        p["min_term_months"] = new_min
    if new_max is not None:
        p["max_term_months"] = new_max
    touch(p)
    return success_object(_serialize(p))


@bp.route("/properties/<pid>/retention-metrics", methods=["GET"])
def retention_metrics(pid):
    require_roles("PlatformAdmin", "RegionalDirector", "PropertyManager")
    p = store.properties.get(pid)
    if p is None:
        raise_err(ERR_PROPERTY_NOT_FOUND, "property not found")
    cs = request.args.get("cohort_start")
    ce = request.args.get("cohort_end")
    variant = request.args.get("variant")
    if not cs or not ce or not variant:
        raise_err(ERR_INVALID_REQUEST, "cohort_start, cohort_end, variant required")
    try:
        cs_d = parse_date(cs)
        ce_d = parse_date(ce)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "cohort dates malformed")
    if variant not in ("TRAILING", "PIPELINE"):
        raise_err(ERR_INVALID_REQUEST, "variant must be TRAILING or PIPELINE")
    result = compute_retention_metrics(pid, cs_d, ce_d, variant)
    return success_object(result)


@bp.route("/properties/<pid>/expiration-forecast", methods=["GET"])
def expiration_forecast(pid):
    require_roles("PlatformAdmin", "RegionalDirector", "PropertyManager", "LeasingAgent")
    p = store.properties.get(pid)
    if p is None:
        raise_err(ERR_PROPERTY_NOT_FOUND, "property not found")
    months_ahead_raw = request.args.get("months_ahead", "12")
    try:
        months_ahead = int(months_ahead_raw)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "months_ahead must be int")
    if months_ahead < 1:
        months_ahead = 1
    if months_ahead > 60:
        months_ahead = 60
    result = compute_expiration_forecast(pid, months_ahead)
    return success_object(result)
