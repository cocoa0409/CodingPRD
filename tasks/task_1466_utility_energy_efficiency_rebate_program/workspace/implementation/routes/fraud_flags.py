"""FraudFlag read endpoints (flags are immutable once persisted)."""
from flask import Blueprint, request

from auth import ALL_ROLES, require_roles
from db import store
from lookups import get_fraud_flag
from respond import respond_list, success
from serialize import fraud_flag_out

bp = Blueprint("fraud_flags", __name__)


@bp.get("/fraud-flags")
@require_roles(*ALL_ROLES)
def list_fraud_flags():
    application_id = request.args.get("application_id")
    flag_kind = request.args.get("flag_kind")
    rows = list(store.fraud_flags.values())
    if application_id is not None:
        rows = [r for r in rows if r["application_id"] == application_id]
    if flag_kind is not None:
        rows = [r for r in rows if r["flag_kind"] == flag_kind]
    return respond_list(rows, fraud_flag_out)


@bp.get("/fraud-flags/<rid>")
@require_roles(*ALL_ROLES)
def get_fraud_flag_route(rid):
    return success(fraud_flag_out(get_fraud_flag(rid)), "object", 200)
