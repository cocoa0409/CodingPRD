"""TaxRecord / 1099 endpoints (PRD 3.9)."""
from flask import Blueprint

import db
from errors import err
from middleware import require_auth, require_role
from response import now_iso, success
from services import calc, common, derive

bp = Blueprint("tax_records", __name__)


@bp.post("/tax-records")
def create_tax_record():
    _, role = require_auth()
    require_role(role, ["PlatformAdmin"])
    body = common.get_body()
    freelancer_id = common.require_str(body, "freelancer_id")
    tax_year = common.require_int(body, "tax_year")
    basis = body.get("basis", "GROSS_BASIS")
    if basis not in ("GROSS_BASIS", "NET_BASIS"):
        raise err("ERR_INVALID_REQUEST", "basis must be GROSS_BASIS or NET_BASIS")
    common.get_freelancer(freelancer_id)

    total = 0
    for p in db.payouts.values():
        if p["freelancer_id"] != freelancer_id or p["status"] != "PAID":
            continue
        if p["tax_year"] != tax_year:
            continue
        total += p["gross_cents"] if basis == "GROSS_BASIS" else p["net_cents"]

    is_reportable = total >= calc.REPORTING_THRESHOLD_CENTS
    rec = {
        "id": db.new_id(),
        "created_at": now_iso(),
        "_seq": db.next_seq(),
        "freelancer_id": freelancer_id,
        "tax_year": tax_year,
        "reportable_gross_cents": total,
        "is_reportable": is_reportable,
        "form_status": "GENERATED" if is_reportable else "BELOW_THRESHOLD",
    }
    db.tax_records[rec["id"]] = rec
    return success(derive.tax_record_view(rec), status=201)


@bp.get("/tax-records/<tid>")
def get_tax_record(tid):
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin", "Freelancer"])
    t = common.get_tax_record(tid)
    common.check_freelancer_owns(role, user_id, t["freelancer_id"])
    return success(derive.tax_record_view(t))
