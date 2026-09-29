"""Carbide grades (PRD section 3.1)."""

from flask import Blueprint

import db
import validation as v
from errors import ApiError
from middleware import authenticate
from response import object_response
from routes import common as c
from services import derive, serialize

bp = Blueprint("grades", __name__)

READ_ROLES = [
    "MetallurgyEngineer",
    "GeometryEngineer",
    "CoatingEngineer",
    "ApplicationEngineer",
    "QualityApprover",
    "ProductionPlanner",
]
OWNER = ["MetallurgyEngineer"]


def _metallurgy_fields(payload):
    return (
        v.as_number(payload, "co_binder_pct", minimum=3.0, maximum=15.0),
        v.as_number(payload, "wc_grain_um", minimum=0.2, maximum=6.0),
        v.as_int(payload, "hardness_hv", minimum=1200, maximum=2000),
        v.as_int(payload, "trs_mpa", minimum=1000, maximum=4500),
    )


@bp.route("/tooling/carbide-grades", methods=["POST"])
def create():
    uid, _role = authenticate(OWNER)
    payload = v.body(
        required=(
            "grade_code",
            "target_workpiece_group",
            "co_binder_pct",
            "wc_grain_um",
            "hardness_hv",
            "trs_mpa",
        )
    )
    grade_code = v.as_string(payload, "grade_code", min_len=3, max_len=24)
    group = v.as_enum(payload, "target_workpiece_group", c.WORKPIECE_GROUPS)
    co, grain, hardness, trs = _metallurgy_fields(payload)

    derive.require_unique("grades", "grade_code", grade_code)

    row = db.new_row(
        {
            "grade_code": grade_code,
            "target_workpiece_group": group,
            "co_binder_pct": co,
            "wc_grain_um": grain,
            "hardness_hv": hardness,
            "trs_mpa": trs,
            "status": "DRAFT",
            "revision": 1,
            "authored_by_user_id": uid,
        }
    )
    db.grades[row["id"]] = row
    return object_response(serialize.grade(row), 201)


@bp.route("/tooling/carbide-grades", methods=["GET"])
def index():
    rows, limit, offset = c.listing(
        "grades",
        READ_ROLES,
        {"status": c.GRADE_STATUSES, "target_workpiece_group": c.WORKPIECE_GROUPS},
    )
    return c.list_response("grades", rows, limit, offset)


@bp.route("/tooling/carbide-grades/<grade_id>", methods=["GET"])
def read(grade_id):
    return c.read_one("grades", grade_id, READ_ROLES)


@bp.route("/tooling/carbide-grades/<grade_id>/start-pilot", methods=["POST"])
def start_pilot(grade_id):
    authenticate(OWNER)
    v.no_body()
    grade = derive.must_exist("grades", grade_id)
    if grade["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_GRADE_STATE",
            "A grade may only enter PILOT from DRAFT (currently %s)." % grade["status"],
        )
    if not derive.grade_has_passed_batch(grade):
        raise ApiError(
            "ERR_NO_PASSED_BATCH",
            "No QC-passed sinter batch exists on the grade's current revision.",
        )
    grade["status"] = "PILOT"
    db.touch(grade)
    return object_response(serialize.grade(grade))


@bp.route("/tooling/carbide-grades/<grade_id>/revise", methods=["POST"])
def revise(grade_id):
    authenticate(OWNER)
    payload = v.body(
        required=(
            "co_binder_pct",
            "wc_grain_um",
            "hardness_hv",
            "trs_mpa",
            "revision_note",
        )
    )
    co, grain, hardness, trs = _metallurgy_fields(payload)
    v.as_string(payload, "revision_note")

    grade = derive.must_exist("grades", grade_id)
    if grade["status"] not in ("PILOT", "QUALIFIED"):
        raise ApiError(
            "ERR_INVALID_GRADE_STATE",
            "A grade may only be revised from PILOT or QUALIFIED (currently %s)."
            % grade["status"],
        )

    was_qualified = grade["status"] == "QUALIFIED"
    grade["co_binder_pct"] = co
    grade["wc_grain_um"] = grain
    grade["hardness_hv"] = hardness
    grade["trs_mpa"] = trs
    grade["revision"] = grade["revision"] + 1
    grade["status"] = "DRAFT"
    db.touch(grade)

    products = [p for p in db.products.values() if p["grade_id"] == grade["id"]]
    if was_qualified:
        derive.revision_cascade(products, "pinned_grade_revision", grade["revision"])
    else:
        derive.recompute_lead_times_for(products)
    return object_response(serialize.grade(grade))


@bp.route("/tooling/carbide-grades/<grade_id>/retire", methods=["POST"])
def retire(grade_id):
    authenticate(OWNER)
    payload = v.body(optional=("retire_note",))
    v.as_string(payload, "retire_note", nullable=True)

    grade = derive.must_exist("grades", grade_id)
    if grade["status"] != "QUALIFIED":
        raise ApiError(
            "ERR_INVALID_GRADE_STATE",
            "A grade may only be retired from QUALIFIED (currently %s)." % grade["status"],
        )

    products = db.ordered([p for p in db.products.values() if p["grade_id"] == grade["id"]])
    ids = set(p["id"] for p in products)
    for order in db.orders.values():
        if order["product_id"] in ids and order["status"] in c.OPEN_ORDER_STATES:
            raise ApiError(
                "ERR_OPEN_DEMAND_EXISTS",
                "Open demand exists on a product built on this grade.",
            )

    grade["status"] = "RETIRED"
    db.touch(grade)
    for product in products:
        if product["release_status"] in ("QUALIFICATION", "RELEASED", "RESTRICTED"):
            product["release_status"] = "WITHDRAWN"
            product["supply_status"] = "UNAVAILABLE"
            db.touch(product)
    return object_response(serialize.grade(grade))
