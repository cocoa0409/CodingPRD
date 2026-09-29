"""§3.9 DocumentationPackage routes."""

from decimal import Decimal

from flask import Blueprint

import calc
import logic
from common import (ALL_ROLES, authenticate, get_body, need_fk, ok, path_row,
                    v_enum, v_fk, v_str)
from errors import ApiError
from store import store

bp = Blueprint("docs", __name__)

REVIEW_DECISIONS = ["APPROVED", "REJECTED"]
FULL_COMPLETENESS = Decimal("100.00")


@bp.post("/optics/documentation-packages")
def create_package():
    authenticate(["QualityManager", "ProcessTechnician"])
    body = get_body()

    # priority 4 — body foreign keys
    assembly = v_fk(body, "assembly_id", store.assemblies, "ERR_ASSEMBLY_NOT_FOUND")

    # priority 5 — field validation
    assembly = need_fk(body, "assembly_id", assembly)

    # priority 22 — at most one package per assembly
    if logic.packages_of_assembly(assembly["id"]):
        raise ApiError("ERR_DOCUMENTATION_PACKAGE_EXISTS")

    pkg = store.new_row()
    pkg["assembly_id"] = assembly["id"]
    pkg["attached_documents"] = []
    pkg["package_status"] = "ASSEMBLING"
    pkg["rejection_count"] = 0
    pkg["submitted_by_user_id"] = None
    pkg["reviewed_by_user_id"] = None
    pkg["last_review_note"] = None
    store.packages[pkg["id"]] = pkg
    return ok(logic.ser_package(pkg), 201)


@bp.get("/optics/documentation-packages/<row_id>")
def get_package(row_id):
    authenticate(ALL_ROLES)
    pkg = path_row(store.packages, row_id, "ERR_DOCUMENTATION_PACKAGE_NOT_FOUND")
    return ok(logic.ser_package(pkg))


@bp.post("/optics/documentation-packages/<row_id>/documents")
def attach_document(row_id):
    authenticate(["QualityManager", "ProcessTechnician", "MetrologyTechnician"])
    pkg = path_row(store.packages, row_id, "ERR_DOCUMENTATION_PACKAGE_NOT_FOUND")
    body = get_body()

    document_type = v_enum(body, "document_type", calc.DOCUMENT_TYPE_ENUM, True)
    reference = v_str(body, "document_reference", True, min_len=1, max_len=200)

    # priority 7 — documents may only be attached while the package is open
    if pkg["package_status"] != "ASSEMBLING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    # priority 22 — a document type appears at most once per package
    for entry in pkg["attached_documents"]:
        if entry["document_type"] == document_type:
            raise ApiError("ERR_DUPLICATE_DOCUMENT_TYPE")

    pkg["attached_documents"].append({
        "document_type": document_type,
        "document_reference": reference,
        "attached_at_utc": store.now_str(),
    })
    store.touch(pkg)
    return ok(logic.ser_package(pkg))


@bp.post("/optics/documentation-packages/<row_id>/submit")
def submit_package(row_id):
    user_id, _role = authenticate(["QualityManager", "ProcessTechnician"])
    pkg = path_row(store.packages, row_id, "ERR_DOCUMENTATION_PACKAGE_NOT_FOUND")

    # priority 7 — only an open package may be submitted
    if pkg["package_status"] != "ASSEMBLING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    # priority 24 — the package must be complete
    if logic.package_view(pkg)[3] != FULL_COMPLETENESS:
        raise ApiError("ERR_DOCUMENTATION_INCOMPLETE")

    pkg["package_status"] = "SUBMITTED"
    pkg["submitted_by_user_id"] = user_id
    store.touch(pkg)
    return ok(logic.ser_package(pkg))


@bp.post("/optics/documentation-packages/<row_id>/review")
def review_package(row_id):
    user_id, _role = authenticate(["QualityManager"])
    pkg = path_row(store.packages, row_id, "ERR_DOCUMENTATION_PACKAGE_NOT_FOUND")
    body = get_body()

    decision = v_enum(body, "decision", REVIEW_DECISIONS, True)
    note = v_str(body, "review_note", False, None, min_len=1, max_len=1000)

    # priority 7 — only a submitted package may be reviewed
    if pkg["package_status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    # priority 12 — segregation of duties
    if user_id == pkg["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if decision == "APPROVED":
        # priority 24 — completeness is re-checked at approval
        if logic.package_view(pkg)[3] != FULL_COMPLETENESS:
            raise ApiError("ERR_DOCUMENTATION_INCOMPLETE")
        pkg["package_status"] = "APPROVED"
    else:
        pkg["package_status"] = "ASSEMBLING"
        pkg["rejection_count"] = int(pkg["rejection_count"]) + 1

    pkg["reviewed_by_user_id"] = user_id
    pkg["last_review_note"] = note
    store.touch(pkg)
    return ok(logic.ser_package(pkg))
