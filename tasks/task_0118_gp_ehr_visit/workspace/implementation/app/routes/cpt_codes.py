"""CPT fee catalog endpoints."""
from __future__ import annotations

from flask import Blueprint

from ..auth import (
    ROLE_BILLING_CLERK,
    ROLE_CLINIC_ADMIN,
    ROLE_NURSE,
    ROLE_PROVIDER,
    ROLE_RECEPTIONIST,
    require_roles,
)
from ..clock import now
from ..errors import err_invalid_billing_units, err_not_found
from ..helpers import (
    assert_bool,
    assert_integer,
    assert_string,
    require_json_object,
)
from ..responses import created, ok
from ..services.lookups import get_cpt_fee
from ..services.serialize import cpt_fee_to_dict
from ..store import store

bp = Blueprint("cpt_codes", __name__)

CPT_PATTERN = r"^[0-9]{5}$"


@bp.route("/cpt-codes", methods=["POST"])
@require_roles(ROLE_CLINIC_ADMIN)
def create_cpt(**_kwargs):
    body = require_json_object()
    cpt_code = assert_string(body.get("cpt_code"), "cpt_code", pattern=CPT_PATTERN)
    description = assert_string(body.get("description"), "description")
    list_price = assert_integer(body.get("list_price_cents"), "list_price_cents", minimum=0)
    allowed_price = assert_integer(body.get("allowed_price_cents"), "allowed_price_cents", minimum=0)
    if allowed_price > list_price:
        raise err_invalid_billing_units(
            "allowed_price_cents must be <= list_price_cents"
        )
    is_preventive = body.get("is_preventive", False)
    if is_preventive is None:
        is_preventive = False
    is_preventive = assert_bool(is_preventive, "is_preventive")

    is_telehealth = body.get("is_telehealth_eligible", False)
    if is_telehealth is None:
        is_telehealth = False
    is_telehealth = assert_bool(is_telehealth, "is_telehealth_eligible")

    s = store()
    with s.lock:
        if cpt_code in s.cpt_fee_catalog:
            # treat duplicate as conflict — surface as invalid_input/conflict (no specific id)
            raise err_invalid_billing_units(f"cpt_code {cpt_code} already exists")
        row = {
            "cpt_code": cpt_code,
            "description": description,
            "list_price_cents": list_price,
            "allowed_price_cents": allowed_price,
            "is_preventive": bool(is_preventive),
            "is_telehealth_eligible": bool(is_telehealth),
            "created_at": now(),
        }
        s.cpt_fee_catalog[cpt_code] = row
    return created(cpt_fee_to_dict(row))


@bp.route("/cpt-codes/<cpt_code>", methods=["GET"])
@require_roles(
    ROLE_RECEPTIONIST, ROLE_NURSE, ROLE_PROVIDER, ROLE_CLINIC_ADMIN, ROLE_BILLING_CLERK
)
def get_cpt(cpt_code: str, **_kwargs):
    s = store()
    with s.lock:
        row = get_cpt_fee(cpt_code)
    return ok(cpt_fee_to_dict(row))
