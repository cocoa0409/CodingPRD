"""LabResult endpoints (PRD §3.5). Append-only; drives Package PASS/FAIL branch."""
from decimal import Decimal

from flask import Blueprint, request

import constants
import db
from errors import err
from helpers import (get_json_body, require_fields, is_number, paginate,
                     sort_by_created, stamp_create, touch)
from middleware import require_auth, get_identity
from response import object_response, array_response
from serializers import lab_result_view

bp = Blueprint("lab_results", __name__)

READ_ROLES = ["QALabUser", "ComplianceManager", "StateRegulator"]


def get_lab_result_or_404(lr_id):
    r = db.lab_results.get(lr_id)
    if r is None:
        raise err("ERR_NOT_FOUND", "LabResult not found.")
    return r


@bp.route("/compliance/lab-results", methods=["POST"])
@require_auth(["QALabUser"])
def create_lab_result():
    body = get_json_body()
    require_fields(body, ["package_id", "testing_license_id", "thc_pct", "pesticide_pass", "tested_at"])

    package_id = body["package_id"]
    testing_license_id = body["testing_license_id"]
    thc_pct = body["thc_pct"]
    pesticide_pass = body["pesticide_pass"]
    tested_at = body["tested_at"]

    if not is_number(thc_pct) or thc_pct < 0 or thc_pct > 100:
        raise err("ERR_INVALID_REQUEST", "thc_pct must be in [0, 100].")
    if not isinstance(pesticide_pass, bool):
        raise err("ERR_INVALID_REQUEST", "pesticide_pass must be a boolean.")

    # Existence (priority 3): package + testing license.
    pkg = db.packages.get(package_id)
    if pkg is None:
        raise err("ERR_NOT_FOUND", "Package not found.")
    lic = db.licenses.get(testing_license_id)
    if lic is None:
        raise err("ERR_NOT_FOUND", "Testing license not found.")

    # State (priority 4): package must be TESTING.
    if pkg["status"] != "TESTING":
        raise err("ERR_INVALID_STATE", "Package must be in TESTING to record a result.")

    # License-active (priority 5): recording license must be ACTIVE.
    if lic["status"] != "ACTIVE":
        raise err("ERR_LICENSE_NOT_ACTIVE", "Testing license is not ACTIVE.")

    # License-type (priority 6): must be TESTING type.
    if lic["license_type"] != "TESTING":
        raise err("ERR_LICENSE_TYPE_MISMATCH", "Lab results require a TESTING license.")

    # Recording license must not be the package's custodying license (§3.5).
    if testing_license_id == pkg["license_id"]:
        raise err("ERR_LICENSE_TYPE_MISMATCH", "Testing license must not be the custodying license.")

    # Compute overall_result: PASS iff pesticide_pass AND thc_pct <= ceiling.
    ceiling = Decimal(constants.POTENCY_CEILING_PCT)
    overall = "PASS" if (pesticide_pass and Decimal(str(thc_pct)) <= ceiling) else "FAIL"

    rec = {
        "id": db.new_id(),
        "package_id": package_id,
        "testing_license_id": testing_license_id,
        "thc_pct": thc_pct,
        "pesticide_pass": pesticide_pass,
        "overall_result": overall,
        "tested_at": tested_at,
    }
    stamp_create(rec, versioned=False)
    db.lab_results[rec["id"]] = rec

    # Cascade: divergent package branch.
    user_id, _ = get_identity()
    if overall == "PASS":
        pkg["status"] = "PASSED"
        pkg["lab_hold"] = False
        pkg["thc_pct"] = thc_pct
        pkg["_pass_lab_user_id"] = user_id  # remembered for segregation of duties
    else:
        pkg["status"] = "FAILED"
        # lab_hold stays True; nothing cleared.
    touch(pkg)

    return object_response(lab_result_view(rec), 201)


@bp.route("/compliance/lab-results", methods=["GET"])
@require_auth(READ_ROLES, open_read=True)
def list_lab_results():
    items = list(db.lab_results.values())
    package_id = request.args.get("package_id")
    testing_license_id = request.args.get("testing_license_id")
    if package_id is not None:
        items = [r for r in items if r["package_id"] == package_id]
    if testing_license_id is not None:
        items = [r for r in items if r["testing_license_id"] == testing_license_id]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([lab_result_view(r) for r in page], limit, offset, total)


@bp.route("/compliance/lab-results/<lr_id>", methods=["GET"])
@require_auth(READ_ROLES, open_read=True)
def get_lab_result(lr_id):
    return object_response(lab_result_view(get_lab_result_or_404(lr_id)))
