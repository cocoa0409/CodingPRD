"""DenialCase endpoints."""
from flask import Blueprint

import db
from middleware import require_roles
from response import success_object
from routes.helpers import paginate, lookup, any_authenticated
from services.case_service import maybe_close_denial

bp = Blueprint("denials", __name__)


def denial_view(d):
    """Serialize a denial with the computed denial_is_final flag."""
    from services.case_service import denial_is_final
    out = dict(d)
    out["denial_is_final"] = denial_is_final(d)
    return out


@bp.get("/api/utilization-cases/<cid>/denial-cases")
def list_denials(cid):
    any_authenticated()
    lookup(db.utilization_cases, cid, "UtilizationCase")
    items = sorted(
        (d for d in db.denial_cases.values() if d["case_id"] == cid),
        key=lambda d: d["created_at"],
    )
    for d in items:
        maybe_close_denial(d)
    return paginate([denial_view(d) for d in items])


@bp.get("/api/denial-cases/<did>")
def get_denial(did):
    any_authenticated()
    denial = lookup(db.denial_cases, did, "DenialCase")
    maybe_close_denial(denial)
    return success_object(denial_view(denial))
