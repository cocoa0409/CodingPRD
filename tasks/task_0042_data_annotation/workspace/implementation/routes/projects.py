"""AnnotationProject and TaskPackage-split / golden-sample sub-routes."""

import math

from flask import Blueprint, request

import db
from middleware import require_role
from response import success, success_list, parse_pagination
from errors import (
    raise_error,
    ERR_PROJECT_NOT_FOUND,
    ERR_INVALID_PARAMETER,
    ERR_PROJECT_NOT_DRAFT,
    ERR_PROJECT_NOT_OPEN,
    ERR_PROJECT_NOT_CLOSED,
    ERR_GUIDELINE_REQUIRED,
    ERR_SAMPLE_PREVIEW_REQUIRED,
    ERR_GOLDEN_SAMPLES_INSUFFICIENT,
    ERR_NO_TASK_PACKAGES,
    ERR_VERSION_CONFLICT,
    ERR_PACKAGES_STILL_OPEN,
    ERR_SALARY_NOT_FINALIZED,
)
from config import (
    TASK_TYPES, DIFFICULTIES, DISTRIBUTION_MODES,
    DEFAULT_TIMEOUT_SECONDS, MIN_TIMEOUT_SECONDS,
    MIN_PACKAGE_SIZE, MAX_PACKAGE_SIZE,
    MIN_GOLDENS,
)
from services.serializers import (
    project_view, golden_sample_view, task_package_view,
)
from services.audit import queue_event
from services.package import initial_tier_required


bp = Blueprint("projects", __name__)


# ----- helpers -----------------------------------------------------------

def _get_project_or_404(project_id: str) -> dict:
    p = db.find_by_id("projects", project_id)
    if not p:
        raise_error(ERR_PROJECT_NOT_FOUND, "Project not found.")
    return p


def _validate_create_payload(body: dict):
    project_name = body.get("project_name")
    if not project_name or not isinstance(project_name, str):
        raise_error(ERR_INVALID_PARAMETER, "project_name is required.")
    task_type = body.get("task_type")
    if task_type not in TASK_TYPES:
        raise_error(ERR_INVALID_PARAMETER, f"task_type must be one of {sorted(TASK_TYPES)}.")
    difficulty = body.get("difficulty")
    if difficulty not in DIFFICULTIES:
        raise_error(ERR_INVALID_PARAMETER, f"difficulty must be one of {sorted(DIFFICULTIES)}.")
    guideline_doc_url = body.get("guideline_doc_url")
    if not isinstance(guideline_doc_url, str):
        raise_error(ERR_INVALID_PARAMETER, "guideline_doc_url must be a string.")
    sample_preview_urls = body.get("sample_preview_urls")
    if not isinstance(sample_preview_urls, list):
        raise_error(ERR_INVALID_PARAMETER, "sample_preview_urls must be an array.")
    package_size = body.get("package_size")
    if not isinstance(package_size, int) or package_size < MIN_PACKAGE_SIZE or package_size > MAX_PACKAGE_SIZE:
        raise_error(ERR_INVALID_PARAMETER,
                    f"package_size must be int in [{MIN_PACKAGE_SIZE}, {MAX_PACKAGE_SIZE}].")
    distribution_mode = body.get("distribution_mode")
    if distribution_mode not in DISTRIBUTION_MODES:
        raise_error(ERR_INVALID_PARAMETER,
                    f"distribution_mode must be one of {sorted(DISTRIBUTION_MODES)}.")
    unit_price_cents = body.get("unit_price_cents")
    if not isinstance(unit_price_cents, int) or unit_price_cents < 0:
        raise_error(ERR_INVALID_PARAMETER, "unit_price_cents must be a non-negative integer.")
    pass_rate_target = body.get("pass_rate_target")
    if not isinstance(pass_rate_target, (int, float)) or pass_rate_target <= 0 or pass_rate_target > 1:
        raise_error(ERR_INVALID_PARAMETER, "pass_rate_target must be in (0, 1].")
    timeout_seconds = body.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if timeout_seconds is None:
        timeout_seconds = DEFAULT_TIMEOUT_SECONDS
    if not isinstance(timeout_seconds, int) or timeout_seconds < MIN_TIMEOUT_SECONDS:
        raise_error(ERR_INVALID_PARAMETER,
                    f"timeout_seconds must be int >= {MIN_TIMEOUT_SECONDS}.")
    return {
        "project_name": project_name,
        "task_type": task_type,
        "difficulty": difficulty,
        "guideline_doc_url": guideline_doc_url,
        "sample_preview_urls": list(sample_preview_urls),
        "package_size": package_size,
        "distribution_mode": distribution_mode,
        "unit_price_cents": unit_price_cents,
        "pass_rate_target": pass_rate_target,
        "timeout_seconds": timeout_seconds,
    }


# ----- endpoints ---------------------------------------------------------

@bp.route("/annotation-projects", methods=["POST"])
def create_project():
    require_role("ProjectManager")
    body = request.get_json(silent=True) or {}
    data = _validate_create_payload(body)
    data["status"] = "DRAFT"
    project = db.insert("projects", data)
    return success(project_view(project), status_code=201)


@bp.route("/annotation-projects", methods=["GET"])
def list_projects():
    require_role("ProjectManager", "QAReviewer", "Annotator")
    limit, offset = parse_pagination(request.args)
    filters = {}
    status = request.args.get("status")
    if status:
        filters["status"] = status
    rows, total = db.query("projects", filters=filters, limit=limit, offset=offset)
    return success_list([project_view(r) for r in rows], total, limit, offset)


@bp.route("/annotation-projects/<project_id>", methods=["GET"])
def read_project(project_id):
    require_role("ProjectManager", "QAReviewer", "Annotator")
    p = _get_project_or_404(project_id)
    return success(project_view(p))


@bp.route("/annotation-projects/<project_id>", methods=["PATCH"])
def update_project(project_id):
    require_role("ProjectManager")
    p = _get_project_or_404(project_id)
    if p["status"] != "DRAFT":
        raise_error(ERR_PROJECT_NOT_DRAFT, "Only DRAFT projects may be edited.")

    body = request.get_json(silent=True) or {}
    version = body.get("version")
    if version is not None and version != p["version"]:
        raise_error(ERR_VERSION_CONFLICT, "Version mismatch.")

    updates = {}
    editable_string = ("guideline_doc_url",)
    for f in editable_string:
        if f in body and body[f] is not None:
            if not isinstance(body[f], str):
                raise_error(ERR_INVALID_PARAMETER, f"{f} must be a string.")
            updates[f] = body[f]

    if "sample_preview_urls" in body and body["sample_preview_urls"] is not None:
        spu = body["sample_preview_urls"]
        if not isinstance(spu, list):
            raise_error(ERR_INVALID_PARAMETER, "sample_preview_urls must be an array.")
        updates["sample_preview_urls"] = list(spu)

    if "unit_price_cents" in body and body["unit_price_cents"] is not None:
        v = body["unit_price_cents"]
        if not isinstance(v, int) or v < 0:
            raise_error(ERR_INVALID_PARAMETER, "unit_price_cents must be non-negative integer.")
        updates["unit_price_cents"] = v

    if "pass_rate_target" in body and body["pass_rate_target"] is not None:
        v = body["pass_rate_target"]
        if not isinstance(v, (int, float)) or v <= 0 or v > 1:
            raise_error(ERR_INVALID_PARAMETER, "pass_rate_target must be in (0, 1].")
        updates["pass_rate_target"] = v

    if "timeout_seconds" in body and body["timeout_seconds"] is not None:
        v = body["timeout_seconds"]
        if not isinstance(v, int) or v < MIN_TIMEOUT_SECONDS:
            raise_error(ERR_INVALID_PARAMETER,
                        f"timeout_seconds must be int >= {MIN_TIMEOUT_SECONDS}.")
        updates["timeout_seconds"] = v

    if "package_size" in body and body["package_size"] is not None:
        v = body["package_size"]
        if not isinstance(v, int) or v < MIN_PACKAGE_SIZE or v > MAX_PACKAGE_SIZE:
            raise_error(ERR_INVALID_PARAMETER,
                        f"package_size must be int in [{MIN_PACKAGE_SIZE}, {MAX_PACKAGE_SIZE}].")
        updates["package_size"] = v

    if "distribution_mode" in body and body["distribution_mode"] is not None:
        v = body["distribution_mode"]
        if v not in DISTRIBUTION_MODES:
            raise_error(ERR_INVALID_PARAMETER,
                        f"distribution_mode must be one of {sorted(DISTRIBUTION_MODES)}.")
        updates["distribution_mode"] = v

    if updates:
        db.update("projects", project_id, updates)
    return success(project_view(db.find_by_id("projects", project_id)))


# --- Golden samples ------------------------------------------------------

@bp.route("/annotation-projects/<project_id>/golden-samples", methods=["POST"])
def add_golden_sample(project_id):
    require_role("ProjectManager")
    p = _get_project_or_404(project_id)
    body = request.get_json(silent=True) or {}
    payload_url = body.get("payload_url")
    if not isinstance(payload_url, str) or not payload_url:
        raise_error(ERR_INVALID_PARAMETER, "payload_url is required.")
    expected_label = body.get("expected_label")
    if expected_label is None:
        raise_error(ERR_INVALID_PARAMETER, "expected_label is required.")

    gs = db.insert("golden_samples", {
        "project_id": p["id"],
        "payload_url": payload_url,
        "expected_label": expected_label,
    }, with_version=False)
    queue_event("STORAGE", "golden_sample.uploaded", gs["id"])
    return success(golden_sample_view(gs), status_code=201)


@bp.route("/annotation-projects/<project_id>/golden-samples", methods=["GET"])
def list_golden_samples(project_id):
    require_role("ProjectManager", "QAReviewer")
    _get_project_or_404(project_id)
    limit, offset = parse_pagination(request.args)
    rows, total = db.query("golden_samples",
                           filters={"project_id": project_id},
                           limit=limit, offset=offset)
    return success_list([golden_sample_view(r) for r in rows], total, limit, offset)


# --- Task package split / list -----------------------------------------

@bp.route("/annotation-projects/<project_id>/task-packages/split", methods=["POST"])
def split_packages(project_id):
    require_role("ProjectManager")
    p = _get_project_or_404(project_id)
    if p["status"] not in {"DRAFT", "OPEN"}:
        # allow split in DRAFT or OPEN per PRD §3.1
        raise_error(ERR_PROJECT_NOT_DRAFT, "Project must be DRAFT or OPEN to split.")

    body = request.get_json(silent=True) or {}
    total_item_count = body.get("total_item_count")
    if not isinstance(total_item_count, int) or total_item_count <= 0:
        raise_error(ERR_INVALID_PARAMETER,
                    "total_item_count must be positive integer.")

    pkg_size = p["package_size"]
    n = math.ceil(total_item_count / pkg_size)

    # Determine starting batch_no (continuation if packages already exist).
    existing = db.find_many("task_packages", project_id=project_id)
    start_batch = max([pkg["batch_no"] for pkg in existing], default=0) + 1

    created = []
    remaining = total_item_count
    for i in range(n):
        item_count = pkg_size if remaining >= pkg_size else remaining
        remaining -= item_count
        tier_required = (initial_tier_required(p["difficulty"])
                         if p["status"] == "OPEN" else None)
        pkg = db.insert("task_packages", {
            "project_id": project_id,
            "batch_no": start_batch + i,
            "item_count": item_count,
            "golden_inserted_count": 0,
            "assigned_annotator_id": None,
            "claimed_at": None,
            "deadline_at": None,
            "rework_round": 0,
            "tier_required": tier_required,
            "status": "POOL",
        })
        created.append(pkg)
    return success([task_package_view(p) for p in created], status_code=201)


@bp.route("/annotation-projects/<project_id>/task-packages", methods=["GET"])
def list_packages(project_id):
    require_role("ProjectManager", "QAReviewer", "Annotator")
    _get_project_or_404(project_id)
    limit, offset = parse_pagination(request.args)
    filters = {"project_id": project_id}
    status = request.args.get("status")
    if status:
        filters["status"] = status

    rows, total = db.query("task_packages", filters=filters,
                           limit=limit, offset=offset)
    return success_list([task_package_view(r) for r in rows], total, limit, offset)


# --- Project lifecycle transitions ---------------------------------------

@bp.route("/annotation-projects/<project_id>/open", methods=["POST"])
def open_project(project_id):
    require_role("ProjectManager")
    p = _get_project_or_404(project_id)
    if p["status"] != "DRAFT":
        raise_error(ERR_PROJECT_NOT_DRAFT, "Project not in DRAFT.")

    if not p.get("guideline_doc_url"):
        raise_error(ERR_GUIDELINE_REQUIRED, "guideline_doc_url required to open.")
    if not p.get("sample_preview_urls"):
        raise_error(ERR_SAMPLE_PREVIEW_REQUIRED, "sample_preview_urls required to open.")
    g_count = len(db.find_many("golden_samples", project_id=project_id))
    if g_count < MIN_GOLDENS:
        raise_error(ERR_GOLDEN_SAMPLES_INSUFFICIENT,
                    f"At least {MIN_GOLDENS} golden samples required to open.")
    pkgs = db.find_many("task_packages", project_id=project_id)
    if not pkgs:
        raise_error(ERR_NO_TASK_PACKAGES, "At least one task package required.")

    # Initialize tier_required on each package based on difficulty.
    tier_req = initial_tier_required(p["difficulty"])
    for pkg in pkgs:
        if pkg.get("tier_required") != tier_req:
            db.update("task_packages", pkg["id"], {"tier_required": tier_req})

    db.update("projects", project_id, {"status": "OPEN"})
    queue_event("STORAGE", "project.opened", project_id)
    return success(project_view(db.find_by_id("projects", project_id)))


@bp.route("/annotation-projects/<project_id>/close", methods=["POST"])
def close_project(project_id):
    require_role("ProjectManager")
    p = _get_project_or_404(project_id)
    if p["status"] != "OPEN":
        raise_error(ERR_PROJECT_NOT_OPEN, "Project not OPEN.")
    blocked = {"IN_PROGRESS", "SUBMITTED", "INSPECTING", "REWORK_PENDING", "ARBITRATING"}
    for pkg in db.find_many("task_packages", project_id=project_id):
        if pkg["status"] in blocked:
            raise_error(ERR_PACKAGES_STILL_OPEN,
                        "Packages still in non-terminal non-POOL states.")
    db.update("projects", project_id, {"status": "CLOSED"})
    return success(project_view(db.find_by_id("projects", project_id)))


@bp.route("/annotation-projects/<project_id>/archive", methods=["POST"])
def archive_project(project_id):
    require_role("ProjectManager")
    p = _get_project_or_404(project_id)
    if p["status"] != "CLOSED":
        raise_error(ERR_PROJECT_NOT_CLOSED, "Project not CLOSED.")

    pkg_ids = {pkg["id"] for pkg in db.find_many("task_packages", project_id=project_id)}
    for entry in db.all_rows("ledger_entries"):
        if entry.get("package_id") in pkg_ids and entry.get("settlement_state") == "WITHHELD":
            raise_error(ERR_SALARY_NOT_FINALIZED,
                        "Some salary entries still WITHHELD.")
    db.update("projects", project_id, {"status": "ARCHIVED"})
    queue_event("STORAGE", "project.archived", project_id)
    return success(project_view(db.find_by_id("projects", project_id)))
