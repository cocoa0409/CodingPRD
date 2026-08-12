"""Clock, InsuredPerson, and ProductTemplate endpoints."""
from flask import Blueprint, request

import domain
import errors
from db import store
from middleware import (
    require_auth, parse_pagination, json_body, require_fields, require_int,
    ALL_ROLES,
)
from response import ok_object, ok_list
from util import fmt_clock, parse_date

bp = Blueprint("core", __name__)


def _list_response(records, serializer):
    limit, offset = parse_pagination()
    ordered = domain.sorted_by_creation(records)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth(["PlatformAdmin"])
    body = json_body(required=True)
    require_fields(body, ["to_iso8601"])
    from util import parse_datetime
    dt = parse_datetime(body["to_iso8601"])
    if dt is None:
        raise errors.invalid_request("to_iso8601 must be a valid ISO 8601 timestamp")
    store.set_clock(dt)
    from services.engine import run_clock_transitions
    run_clock_transitions()
    return ok_object({"current_utc": fmt_clock(store.current_datetime())})


# ---------------------------------------------------------------------------
# InsuredPerson
# ---------------------------------------------------------------------------
@bp.route("/insured-persons", methods=["POST"])
def create_insured():
    require_auth(["Agent"])
    body = json_body(required=True)
    require_fields(body, ["full_name", "date_of_birth", "tobacco_user", "gender"])
    full_name = body["full_name"]
    if not isinstance(full_name, str) or not full_name.strip():
        raise errors.invalid_request("full_name must be a non-empty string")
    dob = parse_date(body["date_of_birth"])
    if dob is None:
        raise errors.invalid_request("date_of_birth must be an ISO date (YYYY-MM-DD)")
    tobacco = body["tobacco_user"]
    if not isinstance(tobacco, bool):
        raise errors.invalid_request("tobacco_user must be a boolean")
    gender = body["gender"]
    if gender not in domain.GENDERS:
        raise errors.invalid_request("gender must be MALE | FEMALE | OTHER")
    person = domain.stamp_new({
        "full_name": full_name, "date_of_birth": dob,
        "tobacco_user": tobacco, "gender": gender,
    })
    store.insured_persons[person["id"]] = person
    return ok_object(domain.serialize_insured(person), status=201)


@bp.route("/insured-persons", methods=["GET"])
def list_insured():
    require_auth(ALL_ROLES)
    return _list_response(list(store.insured_persons.values()),
                          domain.serialize_insured)


@bp.route("/insured-persons/<pid>", methods=["GET"])
def get_insured(pid):
    require_auth(ALL_ROLES)
    person = store.insured_persons.get(pid)
    if person is None:
        raise errors.not_found(errors.ERR_INSURED_NOT_FOUND, "insured person")
    return ok_object(domain.serialize_insured(person))


# ---------------------------------------------------------------------------
# ProductTemplate
# ---------------------------------------------------------------------------
def _validate_rate_table(value, name, key_field, rate_field):
    if not isinstance(value, list):
        raise errors.invalid_request("%s must be an array" % name)
    for entry in value:
        if not isinstance(entry, dict):
            raise errors.invalid_request("%s entries must be objects" % name)
        key = entry.get(key_field)
        rate = entry.get(rate_field)
        if isinstance(key, bool) or not isinstance(key, int) or key < 0:
            raise errors.invalid_request("%s.%s must be a non-negative integer"
                                         % (name, key_field))
        if isinstance(rate, bool) or not isinstance(rate, int) or rate < 0:
            raise errors.invalid_request("%s.%s must be a non-negative integer"
                                         % (name, rate_field))


@bp.route("/product-templates", methods=["POST"])
def create_template():
    require_auth(["PlatformAdmin"])
    body = json_body(required=True)
    require_fields(body, ["product_code", "product_type", "participating",
                          "allows_policy_loans", "min_face_amount_cents",
                          "max_face_amount_cents",
                          "base_monthly_premium_rate_per_thousand_cents"])
    code = body["product_code"]
    if not isinstance(code, str) or not code.strip():
        raise errors.invalid_request("product_code must be a non-empty string")
    for t in store.product_templates.values():
        if t["product_code"] == code:
            raise errors.invalid_request("product_code must be unique")
    ptype = body["product_type"]
    if ptype not in domain.PRODUCT_TYPES:
        raise errors.invalid_request("invalid product_type")
    participating = body["participating"]
    if not isinstance(participating, bool):
        raise errors.invalid_request("participating must be a boolean")
    allows_loans = body["allows_policy_loans"]
    if not isinstance(allows_loans, bool):
        raise errors.invalid_request("allows_policy_loans must be a boolean")
    min_face = require_int(body, "min_face_amount_cents", minimum=0)
    max_face = require_int(body, "max_face_amount_cents", minimum=0)
    if min_face > max_face:
        raise errors.invalid_request("min_face_amount_cents must be <= max_face_amount_cents")
    base_rate = require_int(body, "base_monthly_premium_rate_per_thousand_cents", minimum=0)
    coi_table = body.get("coi_rate_table", [])
    _validate_rate_table(coi_table, "coi_rate_table",
                         "attained_age", "monthly_rate_per_thousand_cents")
    surrender = body.get("surrender_charge_schedule", [])
    _validate_rate_table(surrender, "surrender_charge_schedule",
                         "policy_year_min_inclusive", "surrender_charge_pct_bps")
    template = domain.stamp_new({
        "product_code": code,
        "product_type": ptype,
        "participating": participating,
        "allows_policy_loans": allows_loans,
        "min_face_amount_cents": min_face,
        "max_face_amount_cents": max_face,
        "base_monthly_premium_rate_per_thousand_cents": base_rate,
        "coi_rate_table": coi_table,
        "surrender_charge_schedule": surrender,
        "capitalize_loan_interest": bool(body.get("capitalize_loan_interest", False)),
        "metadata": body.get("metadata") if isinstance(body.get("metadata"), dict) else {},
    })
    store.product_templates[template["id"]] = template
    return ok_object(domain.serialize_template(template), status=201)


@bp.route("/product-templates", methods=["GET"])
def list_templates():
    require_auth(ALL_ROLES)
    return _list_response(list(store.product_templates.values()),
                          domain.serialize_template)


@bp.route("/product-templates/<tid>", methods=["GET"])
def get_template(tid):
    require_auth(ALL_ROLES)
    template = store.product_templates.get(tid)
    if template is None:
        raise errors.not_found(errors.ERR_TEMPLATE_NOT_FOUND, "product template")
    return ok_object(domain.serialize_template(template))
