"""CodedCase endpoints (PRD §3.4)."""
from flask import Blueprint, request

from db import sort_default, store
from errors import (ERR_CODED_CASE_NOT_FOUND, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_STALE_VERSION, fail)
from middleware import ALL_ROLES, require_roles
from response import ok_obj, paginate
from services.calc import regroup_case
from services.core import GROUPER_VARIANTS, ser_case
from validators import body, has, opt_enum, req_int

bp = Blueprint("coded_cases", __name__)


def get_case_or_404(case_id):
    c = store.coded_cases.get(case_id)
    if c is None:
        fail(404, ERR_CODED_CASE_NOT_FOUND, f"CodedCase {case_id} does not exist")
    return c


@bp.route("/coded-cases/<id>", methods=["GET"])
def get_case(id):
    require_roles(*ALL_ROLES)
    return ok_obj(ser_case(get_case_or_404(id)), 200)


@bp.route("/coded-cases", methods=["GET"])
def list_cases():
    require_roles(*ALL_ROLES)
    items = list(store.coded_cases.values())
    chart_id = request.args.get("chart_id")
    if chart_id is not None:
        items = [c for c in items if c["chart_id"] == chart_id]
    principal_dx_id = request.args.get("principal_dx_id")
    if principal_dx_id is not None:
        items = [c for c in items if c["principal_dx_id"] == principal_dx_id]
    return paginate([ser_case(c) for c in sort_default(items)])


@bp.route("/coded-cases/<id>/regroup", methods=["POST"])
def regroup(id):
    require_roles("CodingManager", "Auditor")
    case = get_case_or_404(id)
    if case["status"] != "GROUPED":
        fail(409, ERR_INVALID_STATE,
             f"Cannot regroup a coded case in state {case['status']}")
    b = body()
    if has(b, "expected_coded_case_version"):
        expected = req_int(b, "expected_coded_case_version")
        if expected != case["version"]:
            fail(412, ERR_STALE_VERSION,
                 "expected_coded_case_version does not match the case's current version")
    else:
        fail(400, ERR_INVALID_REQUEST, "expected_coded_case_version is required")
    variant = opt_enum(b, "grouper_variant", GROUPER_VARIANTS)
    if variant is not None:
        case["grouper_variant"] = variant
    regroup_case(case)  # recomputes, bumps version, mirrors to DRAFT/READY bill
    return ok_obj(ser_case(case), 200)
