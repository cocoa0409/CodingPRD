from flask import Blueprint, request

import errors
import serializers
from errors import fail
from auth import require_auth, ANY_ROLE
from store import db, new_id, stamp_new, parse_dt
from envelope import ok, created, list_response
from validation import get_body, require_str, require_int_nonneg, parse_pagination

bp = Blueprint("reports", __name__)

REPORTABLE_THRESHOLD_CENTS = 60000


@bp.post("/form-1099s/generate")
def generate_form():
    require_auth({"Auditor"})
    body = get_body()
    provider_id = require_str(body, "provider_id")
    if provider_id not in db.providers:
        fail(errors.ERR_PROVIDER_NOT_FOUND, "Provider not found")
    tax_year = require_int_nonneg(body, "tax_year")

    total = 0
    for c in db.claims.values():
        if c["provider_id"] == provider_id and c["status"] == "PAID" and c["paid_at"] is not None:
            if parse_dt(c["paid_at"]).year == tax_year:
                total += c["plan_paid_cents"] or 0

    form = {
        "id": new_id(),
        "provider_id": provider_id,
        "tax_year": tax_year,
        "total_paid_cents": total,
        "reportable": total >= REPORTABLE_THRESHOLD_CENTS,
    }
    stamp_new(form)
    db.forms[form["id"]] = form
    return created(serializers.form1099(form))


@bp.get("/form-1099s/<fid>")
def get_form(fid):
    require_auth(ANY_ROLE)
    form = db.forms.get(fid)
    if not form:
        fail(errors.ERR_FORM_1099_NOT_FOUND, "Form 1099 not found")
    return ok(serializers.form1099(form))


@bp.get("/form-1099s")
def list_forms():
    require_auth(ANY_ROLE)
    limit, offset = parse_pagination()
    items = list(db.forms.values())
    provider_id = request.args.get("provider_id")
    if provider_id is not None:
        items = [f for f in items if f["provider_id"] == provider_id]
    return list_response(items, serializers.form1099, limit, offset)
