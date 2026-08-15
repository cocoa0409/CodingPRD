"""Deliverable and QCReport routes (PRD §3.7)."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_QC_THRESHOLD_NOT_MET,
    ERR_QC_ATTEMPTS_EXHAUSTED,
)
from helpers import (
    new_entity,
    touch,
    now_iso,
    get_json_body,
    require_fields,
    check_string,
    check_enum,
    check_bool,
    get_pagination,
    get_filter,
    paginate,
)
from middleware import require_roles
from response import success_object, success_list
from routes.projects import get_project_or_404
from services.transitions import guard_transition
from services.derived import recompute_deliverable_counters

bp = Blueprint("deliverables", __name__)

SPEC_KINDS = ("MEZZANINE", "BROADCAST")
CONTAINERS = ("MXF_OP1A", "MOV_PRORES", "IMF")
DELIVERABLE_TERMINAL = ("DELIVERED", "REJECTED", "SUPERSEDED")
LIST_ROLES = ("PostSupervisor", "ConformEditor", "QCOperator")
MAX_QC_ATTEMPTS = 3


def serialize(deliverable):
    return dict(deliverable)


def serialize_qc_report(report):
    return dict(report)


def get_deliverable_or_404(project, deliverable_id):
    deliverable = db.deliverables.get(deliverable_id)
    if deliverable is None or deliverable["project_id"] != project["id"]:
        raise ApiError(
            ERR_NOT_FOUND, f"Deliverable {deliverable_id} does not exist", 404
        )
    return deliverable


@bp.route("/post-production/projects/<project_id>/deliverables", methods=["POST"])
def create_deliverable(project_id):
    require_roles(("ConformEditor",))
    project = get_project_or_404(project_id)
    body = get_json_body()
    require_fields(body, ("spec_kind", "sequence_label", "container", "requires_qc"))
    spec_kind = check_enum(body, "spec_kind", SPEC_KINDS)
    sequence_label = check_string(body, "sequence_label")
    container = check_enum(body, "container", CONTAINERS)
    requires_qc = check_bool(body, "requires_qc")
    # Creating a new deliverable with the same (sequence_label, spec_kind)
    # supersedes a predecessor still in SPEC_DRAFT (at creation) or in
    # RENDERING (by the system when the newer deliverable is created).
    for existing in db.deliverables.values():
        if (
            existing["project_id"] == project_id
            and existing["sequence_label"] == sequence_label
            and existing["spec_kind"] == spec_kind
            and existing["status"] in ("SPEC_DRAFT", "RENDERING")
        ):
            existing["status"] = "SUPERSEDED"
            touch(existing)
            recompute_deliverable_counters(existing)
    deliverable = new_entity(
        {
            "project_id": project_id,
            "spec_kind": spec_kind,
            "sequence_label": sequence_label,
            "container": container,
            "requires_qc": requires_qc,
            "status": "SPEC_DRAFT",
            "render_progress_pct": 0,
            "qc_attempt_count": 0,
        }
    )
    db.deliverables[deliverable["id"]] = deliverable
    return success_object(serialize(deliverable), 201)


@bp.route("/post-production/projects/<project_id>/deliverables", methods=["GET"])
def list_deliverables(project_id):
    require_roles(LIST_ROLES)
    get_project_or_404(project_id)
    limit, offset = get_pagination()
    items = [d for d in db.deliverables.values() if d["project_id"] == project_id]
    status = get_filter("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    spec_kind = get_filter("spec_kind")
    if spec_kind is not None:
        items = [d for d in items if d["spec_kind"] == spec_kind]
    window, total = paginate(items, limit, offset)
    return success_list([serialize(d) for d in window], limit, offset, total)


@bp.route(
    "/post-production/projects/<project_id>/deliverables/<deliverable_id>",
    methods=["GET"],
)
def get_deliverable(project_id, deliverable_id):
    require_roles(LIST_ROLES)
    project = get_project_or_404(project_id)
    deliverable = get_deliverable_or_404(project, deliverable_id)
    return success_object(serialize(deliverable))


@bp.route(
    "/post-production/projects/<project_id>/deliverables/<deliverable_id>/render",
    methods=["POST"],
)
def render_deliverable(project_id, deliverable_id):
    require_roles(("ConformEditor",))
    project = get_project_or_404(project_id)
    deliverable = get_deliverable_or_404(project, deliverable_id)
    body = get_json_body()
    require_fields(body, ("expected_project_version",))
    expected = body["expected_project_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(
            ERR_INVALID_REQUEST,
            "Field 'expected_project_version' must be an integer",
            400,
        )
    # Stale-version guard (priority 5) — OCC on the project.
    if expected != project["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_project_version does not match the project's current "
            "version",
            412,
        )
    # From-state (priority 6): SPEC_DRAFT or QC_FAILED.
    guard_transition(
        deliverable, ("SPEC_DRAFT", "QC_FAILED"), DELIVERABLE_TERMINAL, "deliverable"
    )
    if deliverable["status"] == "SPEC_DRAFT":
        # Render from SPEC_DRAFT requires Project.conform_ready == true.
        if not project.get("conform_ready"):
            raise ApiError(
                ERR_INVALID_STATE,
                "Project.conform_ready must be true to render from SPEC_DRAFT",
                409,
            )
    else:  # QC_FAILED -> RENDERING requires qc_attempt_count < 3 (priority 16)
        if deliverable.get("qc_attempt_count", 0) >= MAX_QC_ATTEMPTS:
            raise ApiError(
                ERR_QC_ATTEMPTS_EXHAUSTED,
                "Render from QC_FAILED requires qc_attempt_count < 3",
                422,
            )
    deliverable["status"] = "RENDERING"
    deliverable["render_progress_pct"] = 0
    touch(deliverable)
    # Render increments the project's version by one (endpoint side effect).
    touch(project)
    return success_object(serialize(deliverable))


@bp.route(
    "/post-production/projects/<project_id>/deliverables/<deliverable_id>/render-complete",
    methods=["POST"],
)
def render_complete(project_id, deliverable_id):
    require_roles(("ConformEditor",))
    project = get_project_or_404(project_id)
    deliverable = get_deliverable_or_404(project, deliverable_id)
    guard_transition(deliverable, "RENDERING", DELIVERABLE_TERMINAL, "deliverable")
    deliverable["status"] = "RENDERED"
    deliverable["render_progress_pct"] = 100
    touch(deliverable)
    return success_object(serialize(deliverable))


@bp.route(
    "/post-production/projects/<project_id>/deliverables/<deliverable_id>/enqueue-qc",
    methods=["POST"],
)
def enqueue_qc(project_id, deliverable_id):
    require_roles(("QCOperator",))
    project = get_project_or_404(project_id)
    deliverable = get_deliverable_or_404(project, deliverable_id)
    guard_transition(deliverable, "RENDERED", DELIVERABLE_TERMINAL, "deliverable")
    # Enqueueing is permitted only when requires_qc is true.
    if not deliverable["requires_qc"]:
        raise ApiError(
            ERR_INVALID_STATE,
            "Deliverable.requires_qc is false; it skips QC",
            409,
        )
    deliverable["status"] = "QC_QUEUED"
    touch(deliverable)
    recompute_deliverable_counters(deliverable)
    return success_object(serialize(deliverable))


@bp.route(
    "/post-production/projects/<project_id>/deliverables/<deliverable_id>/qc-reports",
    methods=["POST"],
)
def create_qc_report(project_id, deliverable_id):
    user_id, role = require_roles(("QCOperator",))
    project = get_project_or_404(project_id)
    deliverable = get_deliverable_or_404(project, deliverable_id)
    body = get_json_body()
    require_fields(body, ("verdict",))
    verdict = check_enum(body, "verdict", ("PASS", "FAIL"))
    fail_codes = body.get("fail_codes")
    # fail_codes required on FAIL, must be empty on PASS — a mismatch is a
    # body-shape violation (ERR_INVALID_REQUEST).
    if verdict == "FAIL":
        if fail_codes is None:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "Field 'fail_codes' is required when verdict is FAIL",
                400,
            )
        if not isinstance(fail_codes, list) or len(fail_codes) == 0:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "Field 'fail_codes' must be a non-empty array when verdict "
                "is FAIL",
                400,
            )
        for code in fail_codes:
            if not isinstance(code, str):
                raise ApiError(
                    ERR_INVALID_REQUEST,
                    "Field 'fail_codes' entries must be strings",
                    400,
                )
    else:  # PASS
        if fail_codes is not None:
            if not isinstance(fail_codes, list):
                raise ApiError(
                    ERR_INVALID_REQUEST,
                    "Field 'fail_codes' must be an array",
                    400,
                )
            if len(fail_codes) != 0:
                raise ApiError(
                    ERR_INVALID_REQUEST,
                    "Field 'fail_codes' must be empty on PASS",
                    400,
                )
        else:
            fail_codes = []
    # Optional asset_id scope; resolves when present.
    asset_id = body.get("asset_id")
    asset = None
    if asset_id is not None:
        if not isinstance(asset_id, str):
            raise ApiError(
                ERR_INVALID_REQUEST, "Field 'asset_id' must be a string", 400
            )
        asset = db.assets.get(asset_id)
        if asset is None or asset["project_id"] != project_id:
            raise ApiError(
                ERR_NOT_FOUND, f"MediaAsset {asset_id} does not exist", 404
            )
    # From-state: the deliverable must be QC_QUEUED (priority 6).
    guard_transition(deliverable, "QC_QUEUED", DELIVERABLE_TERMINAL, "deliverable")
    # Append the immutable QCReport (id + created_at only, no updated_at /
    # version per PRD §2.5).
    attempt_no = deliverable.get("qc_attempt_count", 0) + 1
    report = new_entity(
        {
            "project_id": project_id,
            "deliverable_id": deliverable_id,
            "asset_id": asset_id,
            "attempt_no": attempt_no,
            "verdict": verdict,
            "fail_codes": list(fail_codes),
            "issued_by": user_id,
        },
        common=False,
    )
    db.qc_reports[report["id"]] = report
    # Apply the verdict to the deliverable.
    if verdict == "PASS":
        deliverable["status"] = "QC_PASSED"
    else:
        deliverable["status"] = "QC_FAILED"
    touch(deliverable)
    recompute_deliverable_counters(deliverable)
    if verdict == "FAIL" and asset is not None:
        # Increment that asset's qc_fail_count by one (a mutation).
        asset["qc_fail_count"] = asset.get("qc_fail_count", 0) + 1
        touch(asset)
    return success_object(serialize_qc_report(report), 201)


@bp.route(
    "/post-production/projects/<project_id>/deliverables/<deliverable_id>/qc-reports",
    methods=["GET"],
)
def list_qc_reports(project_id, deliverable_id):
    require_roles(LIST_ROLES)
    project = get_project_or_404(project_id)
    deliverable = get_deliverable_or_404(project, deliverable_id)
    limit, offset = get_pagination()
    items = [
        r for r in db.qc_reports.values() if r.get("deliverable_id") == deliverable_id
    ]
    verdict = get_filter("verdict")
    if verdict is not None:
        items = [r for r in items if r["verdict"] == verdict]
    window, total = paginate(items, limit, offset)
    return success_list([serialize_qc_report(r) for r in window], limit, offset, total)


@bp.route(
    "/post-production/projects/<project_id>/deliverables/<deliverable_id>/deliver",
    methods=["POST"],
)
def deliver_deliverable(project_id, deliverable_id):
    require_roles(("PostSupervisor",))
    project = get_project_or_404(project_id)
    deliverable = get_deliverable_or_404(project, deliverable_id)
    # Two legitimate paths: QC_PASSED -> DELIVERED (project ACTIVE), or
    # RENDERED -> DELIVERED when requires_qc is false.
    if deliverable["status"] in DELIVERABLE_TERMINAL:
        raise ApiError(
            "ERR_ALREADY_TERMINAL",
            "Attempted transition on a deliverable already in terminal state "
            f"{deliverable['status']}",
            409,
        )
    if deliverable["status"] == "QC_PASSED":
        if project["status"] != "ACTIVE":
            raise ApiError(
                ERR_INVALID_STATE,
                f"Project is in state {project['status']}, not ACTIVE",
                409,
            )
    elif deliverable["status"] == "RENDERED":
        if deliverable["requires_qc"]:
            raise ApiError(
                ERR_INVALID_STATE,
                "Deliverable requires QC; it cannot be delivered from "
                "RENDERED",
                409,
            )
    else:
        raise ApiError(
            ERR_INVALID_STATE,
            f"Deliverable is in state {deliverable['status']}, not QC_PASSED "
            "or RENDERED",
            409,
        )
    deliverable["status"] = "DELIVERED"
    touch(deliverable)
    recompute_deliverable_counters(deliverable)
    return success_object(serialize(deliverable))


@bp.route(
    "/post-production/projects/<project_id>/deliverables/<deliverable_id>/reject",
    methods=["POST"],
)
def reject_deliverable(project_id, deliverable_id):
    require_roles(("PostSupervisor",))
    project = get_project_or_404(project_id)
    deliverable = get_deliverable_or_404(project, deliverable_id)
    guard_transition(deliverable, "QC_FAILED", DELIVERABLE_TERMINAL, "deliverable")
    # Rejection requires qc_attempt_count >= 3 (priority 15).
    if deliverable.get("qc_attempt_count", 0) < MAX_QC_ATTEMPTS:
        raise ApiError(
            ERR_QC_THRESHOLD_NOT_MET,
            "Deliverable reject requires qc_attempt_count >= 3",
            422,
        )
    deliverable["status"] = "REJECTED"
    touch(deliverable)
    recompute_deliverable_counters(deliverable)
    # Cascade: the review round whose target_ref_id names this deliverable
    # transitions to REJECTED.
    for rr in db.review_rounds.values():
        if (
            rr.get("target_ref_id") == deliverable_id
            and rr.get("target_kind") == "DELIVERABLE"
            and rr["status"] in ("OPEN", "NOTES_CLOSED")
        ):
            rr["status"] = "REJECTED"
            touch(rr)
    return success_object(serialize(deliverable))


# ---------------------------------------------------------------------------
# Flat aliases
# ---------------------------------------------------------------------------


@bp.route("/post-production/deliverables/<deliverable_id>", methods=["GET"])
def get_deliverable_flat(deliverable_id):
    require_roles(LIST_ROLES)
    deliverable = db.deliverables.get(deliverable_id)
    if deliverable is None:
        raise ApiError(
            ERR_NOT_FOUND, f"Deliverable {deliverable_id} does not exist", 404
        )
    return success_object(serialize(deliverable))


@bp.route(
    "/post-production/deliverables/<deliverable_id>/qc-reports", methods=["GET"]
)
def list_deliverable_qc_reports_flat(deliverable_id):
    require_roles(LIST_ROLES)
    deliverable = db.deliverables.get(deliverable_id)
    if deliverable is None:
        raise ApiError(
            ERR_NOT_FOUND, f"Deliverable {deliverable_id} does not exist", 404
        )
    limit, offset = get_pagination()
    items = [
        r for r in db.qc_reports.values() if r.get("deliverable_id") == deliverable_id
    ]
    verdict = get_filter("verdict")
    if verdict is not None:
        items = [r for r in items if r["verdict"] == verdict]
    window, total = paginate(items, limit, offset)
    return success_list([serialize_qc_report(r) for r in window], limit, offset, total)


@bp.route("/post-production/qc-reports/<report_id>", methods=["GET"])
def get_qc_report_flat(report_id):
    require_roles(LIST_ROLES)
    report = db.qc_reports.get(report_id)
    if report is None:
        raise ApiError(ERR_NOT_FOUND, f"QCReport {report_id} does not exist", 404)
    return success_object(serialize_qc_report(report))
