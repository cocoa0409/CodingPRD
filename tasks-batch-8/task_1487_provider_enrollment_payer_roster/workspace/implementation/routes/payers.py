"""Payers."""
from flask import Blueprint

from db import base_fields, store
from errors import not_found
from middleware import ALL_ROLES, require_roles
from response import success_object
from serializers import pub
from validate import body, req_bool, req_enum, req_int, req_str

bp = Blueprint("payers", __name__)


@bp.post("/api/payers")
@require_roles("ComplianceOfficer")
def create_payer():
    b = body()
    payer = base_fields()
    payer.update(
        {
            "payer_code": req_str(b, "payer_code"),
            "name": req_str(b, "name"),
            "is_medicare": req_bool(b, "is_medicare"),
            "effective_date_policy": req_enum(
                b, "effective_date_policy", ("APPROVAL_DATE", "RETRO_90")
            ),
            "claims_hold_enabled": req_bool(b, "claims_hold_enabled"),
            "revalidation_interval_days": req_int(b, "revalidation_interval_days"),
        }
    )
    store.payers[payer["id"]] = payer
    return success_object(pub(payer), 201)


@bp.get("/api/payers/<pid>")
@require_roles(*ALL_ROLES)
def get_payer(pid):
    payer = store.payers.get(pid)
    if payer is None:
        raise not_found("Payer")
    return success_object(pub(payer))
