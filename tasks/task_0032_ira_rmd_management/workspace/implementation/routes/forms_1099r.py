"""Form 1099-R endpoints (read-only)."""

from flask import Blueprint, request

import db
from errors import ERR_INVALID_REQUEST, raise_api
from helpers import (
    get_form_1099r_or_404,
    get_pagination_params,
    paginate,
)
from middleware import g, parse_auth_headers, require_roles
from response import success_array, success_object
from serializers import form_1099r_to_json


bp = Blueprint("forms_1099r", __name__, url_prefix="/ira/forms-1099r")


@bp.route("/<f_id>", methods=["GET"])
def get_form(f_id):
    parse_auth_headers()
    require_roles("PlanAdministrator", "AccountOwner", "IRSAuditor")
    f = get_form_1099r_or_404(f_id)
    if g.role == "AccountOwner":
        # Determine the form's owner via the linked distribution or conversion.
        owner_id = None
        if f["distribution_id"] is not None:
            d = db.distributions.get(f["distribution_id"])
            if d is not None:
                acct = db.accounts.get(d["account_id"])
                if acct is not None:
                    owner_id = acct["owner_id"]
        elif f["conversion_id"] is not None:
            c = db.conversions.get(f["conversion_id"])
            if c is not None:
                source = db.accounts.get(c["source_account_id"])
                if source is not None:
                    owner_id = source["owner_id"]
        if owner_id is None or owner_id != g.user_id:
            from errors import ERR_UNAUTHORIZED
            raise_api(ERR_UNAUTHORIZED)
    return success_object(form_1099r_to_json(f))


@bp.route("", methods=["GET"])
def list_forms():
    parse_auth_headers()
    require_roles("PlanAdministrator", "AccountOwner", "IRSAuditor")
    limit, offset = get_pagination_params()
    distribution_id = request.args.get("distribution_id")
    conversion_id = request.args.get("conversion_id")
    tax_year_str = request.args.get("tax_year")
    rows = list(db.forms_1099r.values())
    if distribution_id is not None:
        rows = [f for f in rows if f["distribution_id"] == distribution_id]
    if conversion_id is not None:
        rows = [f for f in rows if f["conversion_id"] == conversion_id]
    if tax_year_str is not None:
        try:
            ty = int(tax_year_str)
        except ValueError:
            raise_api(ERR_INVALID_REQUEST, "tax_year filter must be an integer.")
        rows = [f for f in rows if f["tax_year"] == ty]
    if g.role == "AccountOwner":
        owned_accounts = {a["id"] for a in db.accounts.values() if a["owner_id"] == g.user_id}
        owned_dist_ids = {d["id"] for d in db.distributions.values() if d["account_id"] in owned_accounts}
        owned_conv_ids = {c["id"] for c in db.conversions.values() if c["source_account_id"] in owned_accounts}
        rows = [
            f for f in rows
            if (f["distribution_id"] in owned_dist_ids) or (f["conversion_id"] in owned_conv_ids)
        ]
    page, total = paginate(rows, limit, offset)
    return success_array([form_1099r_to_json(f) for f in page], limit, offset, total)
