"""PRD 3.4 - mandatory-element verdict rows and the regulatory waiver."""
from flask import Blueprint, request

import calc
from cascade import element_sort_key, recompute_compliance
from core import db, rows, touch
from errors import fail, invalid
from http_util import (
    ALL_ROLES,
    auth,
    body_fields,
    filter_exists,
    load,
    ok,
    paginate,
    query_int,
)
from serialize import element_check_json

bp = Blueprint("element_checks", __name__)


@bp.route("/element-checks/<check_id>", methods=["GET"])
def get_element_check(check_id):
    auth(ALL_ROLES)
    return ok(element_check_json(load("element_checks", check_id)))


@bp.route("/element-checks", methods=["GET"])
def list_element_checks():
    auth(ALL_ROLES)
    version_id = filter_exists("versions", "artwork_version_id")
    items = rows("element_checks")
    if version_id:
        items = [r for r in items if r["artwork_version_id"] == version_id]
    check_run_no = query_int("check_run_no")
    if check_run_no is not None:
        items = [r for r in items if r["check_run_no"] == check_run_no]
    result = request.args.get("result")
    if result:
        items = [r for r in items if r["result"] == result]
    # PRD 2.3 / 3.4: verdict rows are returned in the fixed element order.
    items = sorted(items, key=element_sort_key)
    return paginate(items, element_check_json)


@bp.route("/element-checks/<check_id>/waiver", methods=["POST"])
def waive_element_check(check_id):
    user_id, _role = auth(["RegulatoryReviewer"])
    row = load("element_checks", check_id)
    body = body_fields(["waiver_justification"])
    justification = body.get("waiver_justification")
    if not isinstance(justification, str) or not justification.strip():
        invalid("waiver_justification is required and must be non-empty")

    version = db.versions[row["artwork_version_id"]]
    if row["result"] != "FAIL" or row["check_run_no"] != version["check_run_no"]:
        fail(
            "ERR_ELEMENT_CHECK_NOT_FAILED",
            "only a FAIL row of the current check run may be waived",
        )

    row["result"] = "WAIVED"
    row["waived_by_user_id"] = user_id
    row["waiver_justification"] = justification
    row["deduction_points"] = calc.deduction_for(row["severity"], "WAIVED")
    touch(row)

    recompute_compliance(version)
    touch(version)
    return ok(element_check_json(row))
