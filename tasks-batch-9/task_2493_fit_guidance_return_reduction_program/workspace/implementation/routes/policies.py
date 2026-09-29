"""Return policy rows: category defaults and customer overrides (PRD 3.7)."""

from flask import Blueprint

import constants as C
import validate as V
from db import db, new_row
from lookup import filtered, get_policy
from middleware import authenticate
from response import array_response, object_response

bp = Blueprint("return_policies", __name__)


def read_policy_body(body):
    """The shared shape of both policy creates, in body-declaration order."""
    return {
        "category_code": V.req_enum(body, "category_code", C.CATEGORY_CODES),
        "window_days": V.req_int(body, "window_days", minimum=1),
        "restocking_applies": V.req_bool(body, "restocking_applies"),
        "non_refundable_shipping": V.req_bool(body, "non_refundable_shipping"),
        "effective_from": V.req_instant(body, "effective_from"),
        "effective_to": V.opt_instant(body, "effective_to"),
    }


def build_policy_row(scope, customer_profile_id, fields):
    return new_row({
        "scope": scope,
        "customer_profile_id": customer_profile_id,
        "category_code": fields["category_code"],
        "window_days": fields["window_days"],
        "restocking_applies": fields["restocking_applies"],
        "non_refundable_shipping": fields["non_refundable_shipping"],
        "effective_from": fields["effective_from"],
        "effective_to": fields["effective_to"],
    })


@bp.post("/fit-program/return-policies")
def create_category_default():
    authenticate(C.ROLE_MERCH_OPS_ADMIN)
    body = V.get_body()
    fields = read_policy_body(body)
    policy = build_policy_row("CATEGORY_DEFAULT", None, fields)
    db.policies[policy["id"]] = policy
    return object_response(policy, 201)


@bp.get("/fit-program/return-policies/<policy_id>")
def read_return_policy(policy_id):
    authenticate(C.ROLE_MERCH_OPS_ADMIN, C.ROLE_RETURNS_AUDITOR)
    return object_response(get_policy(policy_id))


@bp.get("/fit-program/return-policies")
def list_return_policies():
    authenticate(C.ROLE_MERCH_OPS_ADMIN, C.ROLE_RETURNS_AUDITOR)
    limit, offset = V.pagination_params()
    rows = filtered(db.policies.values(), {
        "customer_profile_id": "customer_profile_id",
        "category_code": "category_code",
        "scope": "scope",
    })
    page, meta = V.paginate(rows, limit, offset)
    return array_response(page, meta)
