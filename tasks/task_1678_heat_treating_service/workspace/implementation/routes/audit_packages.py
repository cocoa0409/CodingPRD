"""AuditPackage endpoints (Nadcap evidence)."""
from flask import Blueprint

import db
import validation as v
from db import store, new_id, new_common, touch
from errors import ApiError
from middleware import ANY_ROLES, get_context, require_roles
from response import Paginator, created, ok

bp = Blueprint("audit_packages", __name__)


@bp.post("/audit-packages")
def create_audit_package():
    get_context()
    require_roles(["QualityEngineer"])
    body = v.get_body()
    # tier 4: body FK existence — furnace, then each listed load
    furnace = None
    if v.present(body, "furnace_id"):
        furnace = v.resolve_fk(store.furnaces, body.get("furnace_id"), "ERR_FURNACE_NOT_FOUND")
    raw_ids = body.get("load_batch_ids")
    loads = []
    if isinstance(raw_ids, list):
        for lb_id in raw_ids:
            loads.append(v.resolve_fk(store.load_batches, lb_id, "ERR_LOAD_BATCH_NOT_FOUND"))
    # tier 5 (state): every listed load must be COMPLETED on this furnace
    for lb in loads:
        if lb["status"] != "COMPLETED" or (furnace is not None and lb["furnace_id"] != furnace["id"]):
            raise ApiError("ERR_LOAD_NOT_COMPLETED", 409,
                           "Audit package requires every listed load COMPLETED on the given furnace")
    # tier 9: required fields
    if furnace is None:
        v.req_string(body, "furnace_id")  # raises ERR_INVALID_REQUEST
    load_ids = v.req_list(body, "load_batch_ids")

    # evidence_manifest: listed loads + the furnace's pyrometry records performed on or
    # before the latest listed load's completed_at + per-load thermocouple counts.
    if loads:
        latest_completed = max(lb["completed_at"] for lb in loads)
        pyro_ids = [r["id"] for r in sorted(store.pyrometry_records.values(),
                                            key=lambda r: (r["created_at"], r["_seq"]))
                    if r["furnace_id"] == furnace["id"] and r["performed_at"] <= latest_completed]
    else:
        pyro_ids = []
    counts = {}
    for lb in loads:
        counts[lb["id"]] = sum(1 for r in store.thermocouple_readings.values()
                               if r["load_batch_id"] == lb["id"])
    package = {
        "id": new_id(),
        "furnace_id": furnace["id"],
        "load_batch_ids": list(load_ids),
        "evidence_manifest": {
            "load_batch_ids": list(load_ids),
            "pyrometry_record_ids": pyro_ids,
            "thermocouple_reading_counts": counts,
        },
        "status": "DRAFT",
        "issued_at": None,
    }
    new_common(package)
    store.audit_packages[package["id"]] = package
    return created(package)


@bp.get("/audit-packages")
def list_audit_packages():
    get_context()
    require_roles(ANY_ROLES)
    pg = Paginator()
    rows = list(store.audit_packages.values())
    rows = pg.filter(rows, "furnace_id")
    rows = pg.filter(rows, "status")
    return ok(pg(rows), rtype="array", pagination=pg)


@bp.get("/audit-packages/<package_id>")
def get_audit_package(package_id):
    get_context()
    require_roles(ANY_ROLES)
    return ok(v.resolve_path(store.audit_packages, package_id, "ERR_AUDIT_PACKAGE_NOT_FOUND"))


@bp.post("/audit-packages/<package_id>/issue")
def issue_audit_package(package_id):
    get_context()
    require_roles(["NadcapAuditor"])
    package = v.resolve_path(store.audit_packages, package_id, "ERR_AUDIT_PACKAGE_NOT_FOUND")
    # tier 5 (state): issue requires DRAFT; ISSUED is terminal and locked
    if package["status"] != "DRAFT":
        raise ApiError("ERR_PACKAGE_NOT_DRAFT", 409, "Issue requires package status DRAFT")
    package["status"] = "ISSUED"
    package["issued_at"] = db.clock()
    touch(package)
    return ok(package)
