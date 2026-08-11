"""Document packages."""
from flask import Blueprint, request
import db
from errors import err
from middleware import require_role, get_body, require_fields, check_enum, paginate_args
from response import success_obj, success_list
from services.common import (
    base_record, touch, get_or_404, serialize_document_package,
    find_job_document_package, maybe_complete_package,
)

bp = Blueprint("documents", __name__)

ARTIFACT_KINDS = {"PHOTO", "AUTHORIZATION", "MEASUREMENT_SHEET"}


@bp.route("/jobs/<jid>/document-packages", methods=["POST"])
def create_document_package(jid):
    require_role("Dispatcher")
    job = get_or_404(db.jobs, jid, "Job")
    if job["work_status"] == "CLOSED":
        raise err("ERR_ALREADY_TERMINAL", "Job is CLOSED")
    # requires job SECURED or later
    if job["work_status"] not in ("SECURED", "BREACH_HOLD", "READY_FOR_REMOVAL", "REMOVED"):
        raise err("ERR_INVALID_STATE", "Job must be SECURED or later")
    existing = find_job_document_package(job["id"])
    if existing is not None:
        raise err("ERR_DUPLICATE_PACKAGE", "Job already has a document package")
    installed_count = sum(
        1 for s in db.scope_items.values()
        if s["job_id"] == job["id"] and s["status"] == "INSTALLED"
    )
    rec = base_record()
    rec.update({
        "job_id": job["id"],
        "photo_count": 0,
        "authorization_signed": False,
        "measurement_sheet_recorded": False,
        "required_photo_count": 2 * installed_count,
        "status": "INCOMPLETE",
    })
    db.document_packages[rec["id"]] = rec
    maybe_complete_package(rec)
    return success_obj(serialize_document_package(rec), 201)


@bp.route("/jobs/<jid>/document-packages", methods=["GET"])
def list_document_packages(jid):
    require_role("PlatformAdmin", "Dispatcher", "Customer", "Subcontractor")
    get_or_404(db.jobs, jid, "Job")
    limit, offset = paginate_args()
    items = [p for p in db.document_packages.values() if p["job_id"] == jid]
    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_document_package(p) for p in page], total, limit, offset)


@bp.route("/document-packages/<pid>/artifacts", methods=["POST"])
def add_artifact(pid):
    require_role("Dispatcher")
    pkg = get_or_404(db.document_packages, pid, "DocumentPackage")
    body = get_body()
    require_fields(body, ["kind", "expected_package_version"])
    kind = check_enum(body["kind"], ARTIFACT_KINDS, "kind")
    if pkg["status"] == "LOCKED":
        raise err("ERR_PACKAGE_LOCKED", "Package is LOCKED")
    expected = body["expected_package_version"]
    if not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_package_version must be integer")
    if expected != pkg["version"]:
        raise err("ERR_STALE_VERSION", "Stale package version")
    if kind == "PHOTO":
        pkg["photo_count"] = pkg.get("photo_count", 0) + 1
    elif kind == "AUTHORIZATION":
        pkg["authorization_signed"] = True
    elif kind == "MEASUREMENT_SHEET":
        pkg["measurement_sheet_recorded"] = True
    touch(pkg)
    maybe_complete_package(pkg)
    return success_obj(serialize_document_package(pkg), 200)
