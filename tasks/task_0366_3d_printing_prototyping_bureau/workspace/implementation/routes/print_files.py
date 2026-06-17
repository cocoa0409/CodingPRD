"""PrintFile routes: upload, printability check, FLAGGED->PRINTABLE override."""

from flask import Blueprint, request

import errors
import validation as V
from db import DB, LOCK, stamp_create, touch
from middleware import require_auth, require_role
from pagination import paginate
from response import object_response, array_response
from services import calc, domain, ownership

bp = Blueprint("print_files", __name__)

READ_ROLES = ("Customer", "BureauAdmin", "QAReviewer", "Operator")


@bp.route("/bureaus/print-files", methods=["POST"])
def upload_print_file():
    with LOCK:
        principal = require_auth()
        require_role(principal, ("Customer", "BureauAdmin"))
        body = V.get_body()
        bureau_id = V.require_id(body, "bureau_id")
        customer_id = V.require_id(body, "customer_id")
        filename = V.require_string(body, "filename")
        volume = V.require_positive_number(body, "volume_cm3")
        bx = V.require_positive_number(body, "bbox_x_mm")
        by = V.require_positive_number(body, "bbox_y_mm")
        bz = V.require_positive_number(body, "bbox_z_mm")
        min_wall = V.require_positive_number(body, "min_wall_mm")
        max_overhang = V.require_positive_number(body, "max_overhang_deg")
        is_manifold = V.require_bool(body, "is_manifold")

        if bureau_id not in DB.bureaus:
            raise errors.reference_not_found()
        customer = domain.ref_or_404(DB.customers, customer_id, bureau_id)

        # A Customer may only upload for their own customer record.
        if principal.role == "Customer" and principal.user_id != customer["id"]:
            raise errors.forbidden()

        pf = stamp_create({
            "bureau_id": bureau_id,
            "customer_id": customer_id,
            "filename": filename,
            "volume_cm3": volume,
            "bbox_x_mm": bx,
            "bbox_y_mm": by,
            "bbox_z_mm": bz,
            "min_wall_mm": min_wall,
            "max_overhang_deg": max_overhang,
            "is_manifold": is_manifold,
            "printability_score": None,
            "checked_against_material_id": None,
            "status": "UPLOADED",
        })
        DB.print_files[pf["id"]] = pf
        return object_response(pf, 201)


@bp.route("/bureaus/print-files/<file_id>", methods=["GET"])
def get_print_file(file_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, READ_ROLES)
        pf = domain.get_or_404(DB.print_files, file_id)
        if principal.role == "Customer" and principal.user_id != ownership.file_customer_id(pf):
            raise errors.forbidden()
        return object_response(pf, 200)


@bp.route("/bureaus/print-files", methods=["GET"])
def list_print_files():
    with LOCK:
        principal = require_auth()
        require_role(principal, READ_ROLES)
        items = list(DB.print_files.values())
        for key in ("bureau_id", "customer_id", "checked_against_material_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [f for f in items if f.get(key) == val]
        if principal.role == "Customer":
            items = [f for f in items if ownership.file_customer_id(f) == principal.user_id]
        page, limit, offset, total = paginate(items)
        return array_response(page, limit, offset, total)


@bp.route("/bureaus/print-files/<file_id>/check", methods=["POST"])
def check_print_file(file_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, ("QAReviewer",))
        pf = domain.get_or_404(DB.print_files, file_id)
        body = V.get_body()
        material_id = V.require_id(body, "material_id")
        material = domain.ref_or_404(DB.materials, material_id, pf["bureau_id"])

        # State: a check is meaningful from UPLOADED or FLAGGED. REJECTED is terminal.
        if pf["status"] not in ("UPLOADED", "FLAGGED"):
            raise errors.invalid_state()

        # The check is only meaningful against an ACTIVE material.
        if material["status"] != "ACTIVE":
            raise errors.conflict(errors.ERR_MATERIAL_RETIRED, "Material is retired")

        online_machines = [
            m for m in DB.machines.values()
            if m["bureau_id"] == pf["bureau_id"]
            and m["status"] == "ONLINE"
            and m["process"] == material["process"]
        ]
        score, status = calc.printability_score(pf, material, online_machines)
        pf["printability_score"] = score
        pf["checked_against_material_id"] = material_id
        pf["status"] = status
        touch(pf)
        return object_response(pf, 200)


@bp.route("/bureaus/print-files/<file_id>/override", methods=["POST"])
def override_print_file(file_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, ("QAReviewer",))
        pf = domain.get_or_404(DB.print_files, file_id)
        if pf["status"] != "FLAGGED":
            raise errors.invalid_state()
        pf["status"] = "PRINTABLE"
        touch(pf)
        return object_response(pf, 200)
