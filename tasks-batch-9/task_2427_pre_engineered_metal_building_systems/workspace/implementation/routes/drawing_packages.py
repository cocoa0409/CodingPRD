"""PRD 3.7 -- producing and sealing the permit set."""

from flask import Blueprint, request

import serializers as S
import validation as V
from errors import ApiError
from middleware import ANY, actor, roles_required
from response import object_response, paginated
from services import calc, domain
from store import db, new_row, now_iso, ordered, touch

bp = Blueprint("drawing_packages", __name__)


@bp.route("/drawing-packages", methods=["POST"])
@roles_required("SealingEngineer")
def create_drawing_package():
    data = V.body()
    design_id = V.get_string(data, "design_id")
    jurisdiction_id = V.get_string(data, "jurisdiction_id")
    license_state = V.get_string(
        data, "sealing_license_state", min_len=2, max_len=2, pattern=r"[A-Z]{2}"
    )
    sheet_count = V.get_int(data, "sheet_count", minimum=1)

    design = domain.get_design(design_id)
    jurisdiction = domain.get_jurisdiction(jurisdiction_id)

    row = new_row(
        {
            "design_id": design["id"],
            "jurisdiction_id": jurisdiction["id"],
            "sealing_license_state": license_state,
            "sheet_count": sheet_count,
            "criteria_revision_at_seal": None,
            "sealed_at": None,
            "sealed_by_user_id": None,
            "status": "PENDING",
        }
    )
    db.drawing_packages[row["id"]] = row
    return object_response(S.drawing_package_out(row), 201)


@bp.route("/drawing-packages/<package_id>", methods=["GET"])
@roles_required(ANY)
def read_drawing_package(package_id):
    return object_response(S.drawing_package_out(domain.get_drawing_package(package_id)))


@bp.route("/drawing-packages", methods=["GET"])
@roles_required(ANY)
def list_drawing_packages():
    design_id = request.args.get("design_id")
    jurisdiction_id = request.args.get("jurisdiction_id")
    status = request.args.get("status")

    def predicate(row):
        if design_id is not None and row["design_id"] != design_id:
            return False
        if jurisdiction_id is not None and row["jurisdiction_id"] != jurisdiction_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return paginated(ordered(db.drawing_packages, predicate), S.drawing_package_out)


@bp.route("/drawing-packages/<package_id>/seal", methods=["POST"])
@roles_required("SealingEngineer")
def seal_drawing_package(package_id):
    package = domain.get_drawing_package(package_id)

    # Band 9.
    if package["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    design = db.designs.get(package["design_id"])
    if design is None:
        raise ApiError("ERR_DESIGN_NOT_FOUND")

    # Band 10.
    if design["status"] != "APPROVED":
        raise ApiError("ERR_DESIGN_NOT_APPROVED")

    # Band 11 -- completeness first, then knee capacity.
    details = [
        c
        for c in domain.components_of_design(design["id"])
        if c["component_class"] == "CONNECTION_DETAIL"
    ]
    knees = [c for c in details if c["connection_type"] == "KNEE"]
    bases = [c for c in details if c["connection_type"] == "BASE"]
    if not knees or not bases:
        raise ApiError("ERR_CONNECTION_DETAILS_INCOMPLETE")

    required_moment = calc.D(design["required_moment_kip_ft"])
    for knee in knees:
        if calc.D(knee["capacity_moment_kip_ft"]) < required_moment:
            raise ApiError("ERR_CONNECTION_CAPACITY_INSUFFICIENT")

    jurisdiction = db.jurisdictions.get(package["jurisdiction_id"])
    if jurisdiction is None:
        raise ApiError("ERR_JURISDICTION_NOT_FOUND")

    # Band 12 -- deliberately last of the five.
    if package["sealing_license_state"] != jurisdiction["state_code"]:
        raise ApiError("ERR_SEAL_LICENSE_STATE_MISMATCH")

    package["sealed_at"] = now_iso()
    package["sealed_by_user_id"] = actor()
    package["criteria_revision_at_seal"] = jurisdiction["criteria_revision"]
    package["status"] = "SEALED"
    touch(package)

    for order in ordered(
        db.orders, lambda o: o["engineering_design_id"] == package["design_id"]
    ):
        if order["engineering_status"] != "ENG_APPROVED":
            continue
        order["drawing_package_id"] = package["id"]
        order["engineering_status"] = "ENG_SEALED"
        touch(order)

    return object_response(S.drawing_package_out(package))
