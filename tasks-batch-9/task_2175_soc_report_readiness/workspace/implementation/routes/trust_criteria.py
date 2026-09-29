from flask import Blueprint, request

import auth
import calcs
import store
import validators as v
from auth import ALL_ROLES
from envelope import ok, ok_page
from errors import ApiError
from store import DB

bp = Blueprint("trust_criteria", __name__)


@bp.post("/soc/trust-criteria")
def create_trust_criterion():
    auth.authenticate({"PlatformAdmin"})
    body = auth.body()
    code = v.req_str(body, "criterion_code", 1, 20, upper=True)
    category = v.req_enum(body, "category", calcs.CATEGORIES)
    title = v.req_str(body, "title", 1, 200)
    min_primary = v.opt_int(body, "min_primary_controls", minv=1, default=1)
    report_types = v.opt_enum_array(
        body, "applies_to_report_types", calcs.REPORT_TYPES, default=["SOC_2_TYPE_2"]
    )

    for row in DB["trust_criteria"].values():
        if row["criterion_code"] == code:
            raise ApiError("ERR_DUPLICATE_RESOURCE")

    row = store.new_row(
        "trust_criteria",
        {
            "criterion_code": code,
            "category": category,
            "title": title,
            "min_primary_controls": min_primary,
            "applies_to_report_types": report_types,
        },
        versioned=False,
    )
    return ok(store.public(row), 201)


@bp.get("/soc/trust-criteria/<trust_criterion_id>")
def read_trust_criterion(trust_criterion_id):
    auth.authenticate(ALL_ROLES)
    row = store.get_or_404("trust_criteria", trust_criterion_id)
    return ok(store.public(row))


@bp.get("/soc/trust-criteria")
def list_trust_criteria():
    auth.authenticate(ALL_ROLES)
    limit, offset = auth.pagination()
    items = store.rows("trust_criteria")
    category = request.args.get("category")
    if category is not None:
        items = [r for r in items if r["category"] == category]
    page, total = auth.paginate(items, limit, offset)
    return ok_page([store.public(r) for r in page], limit, offset, total)
