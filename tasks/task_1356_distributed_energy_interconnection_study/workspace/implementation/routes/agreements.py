"""InterconnectionAgreement endpoints: issuance (OCC-guarded), execution,
extension, and per-project listing."""
from datetime import timedelta

from flask import Blueprint

from clock import CLOCK, format_clock, parse_iso
from db import DB, new_id, next_seq, pub, stamp_new, touch
from errors import ApiError
from middleware import READ_ROLES, auth
from response import ok, ok_list
from services import (EXECUTION_DEADLINE_DAYS, EXTENSION_LIMIT,
                      EXTENSION_MAX_DAYS, EXTENSION_NOTICE_DAYS,
                      agreements_of, study_of_cluster)
from util import body, opt_int, pagination_args, req_dt_str, req_num

bp = Blueprint("agreements", __name__)


def _get_agreement(agreement_id):
    agreement = DB["agreements"].get(agreement_id)
    if agreement is None:
        raise ApiError(
            "ERR_AGREEMENT_NOT_FOUND", 404,
            "InterconnectionAgreement id does not exist",
        )
    return agreement


@bp.route("/interconnection/projects/<project_id>/agreements", methods=["POST"])
def issue_agreement(project_id):
    auth(["QueueAdministrator"])
    project = DB["projects"].get(project_id)
    if project is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND", 404, "Project id does not exist")

    data = body()

    # Optimistic concurrency (fifth in the pipeline): when the client supplied
    # expected_project_version, it must match the project's current version.
    expected = data.get("expected_project_version")
    if expected is not None and expected != project["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", 412,
            "expected_project_version does not match the Project's current version",
        )

    # State: first issuance requires STUDY_COMPLETE; re-issuance requires
    # AGREEMENT_PENDING with every prior agreement EXPIRED.
    if project["status"] == "STUDY_COMPLETE":
        pass
    elif project["status"] == "AGREEMENT_PENDING" and all(
            a["status"] == "EXPIRED" for a in agreements_of(project_id)):
        pass
    else:
        raise ApiError(
            "ERR_PROJECT_NOT_STUDY_COMPLETE", 409,
            "Agreement issuance requires project STUDY_COMPLETE, or "
            "AGREEMENT_PENDING with all prior agreements EXPIRED",
        )

    # Cross-entity: the cluster study must be RESULTS_PUBLISHED or FINALIZED.
    study = study_of_cluster(project["cluster_group_id"])
    if study is None or study["status"] not in ("RESULTS_PUBLISHED", "FINALIZED"):
        raise ApiError(
            "ERR_STUDY_NOT_PUBLISHED", 409,
            "Agreement issuance requires cluster Study in RESULTS_PUBLISHED or "
            "FINALIZED",
        )

    # Structural / well-formedness.
    if expected is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "expected_project_version is required")
    now = CLOCK.now()
    target_cod_raw = req_dt_str(data, "target_cod")
    if parse_iso(target_cod_raw) <= now:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "target_cod must be strictly after the issuance timestamp",
        )
    max_injection_mw = req_num(data, "max_injection_mw")
    if not (max_injection_mw > 0) or max_injection_mw > project["capacity_mw"]:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "max_injection_mw must be greater than 0 and no more than the "
            "project capacity_mw",
        )
    curtailment_hours_cap = opt_int(data, "curtailment_hours_cap", 0)
    if curtailment_hours_cap < 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "curtailment_hours_cap must be at least 0",
        )

    issued_at = now
    execution_deadline = issued_at + timedelta(days=EXECUTION_DEADLINE_DAYS)
    agreement = {
        "id": new_id(),
        "_seq": next_seq(),
        "project_id": project_id,
        "issued_at": format_clock(issued_at),
        "execution_deadline": format_clock(execution_deadline),
        "target_cod": target_cod_raw,
        "extension_count": 0,
        "max_injection_mw": max_injection_mw,
        "curtailment_hours_cap": curtailment_hours_cap,
        "status": "ISSUED",
    }
    stamp_new(agreement)
    DB["agreements"][agreement["id"]] = agreement

    # First issuance moves STUDY_COMPLETE -> AGREEMENT_PENDING; re-issuance
    # keeps AGREEMENT_PENDING. Either way the project version advances by one.
    if project["status"] == "STUDY_COMPLETE":
        project["status"] = "AGREEMENT_PENDING"
    touch(project)
    return ok(pub(agreement), 201)


@bp.route("/interconnection/projects/<project_id>/agreements", methods=["GET"])
def list_project_agreements(project_id):
    auth(READ_ROLES)
    if DB["projects"].get(project_id) is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND", 404, "Project id does not exist")
    limit, offset = pagination_args()
    items = agreements_of(project_id)
    page = items[offset:offset + limit]
    return ok_list([pub(a) for a in page], len(items), limit, offset)


@bp.route("/interconnection/agreements/<agreement_id>/execute", methods=["POST"])
def execute_agreement(agreement_id):
    user_id, _role = auth(["Developer"])
    agreement = _get_agreement(agreement_id)
    project = DB["projects"].get(agreement["project_id"])

    # Ownership resolves through the parent project.
    if project is None or project["developer_id"] != user_id:
        raise ApiError(
            "ERR_FORBIDDEN_RESOURCE_OWNERSHIP", 403,
            "Developer-role caller does not own the target project",
        )

    # State: execution requires ISSUED.
    if agreement["status"] != "ISSUED":
        raise ApiError(
            "ERR_AGREEMENT_NOT_ISSUED", 409,
            "Execute requires agreement ISSUED",
        )

    # Clock: the attempt must arrive no later than execution_deadline
    # (inclusive boundary). A late attempt materializes ISSUED -> EXPIRED
    # lazily and is rejected; the project remains AGREEMENT_PENDING.
    if CLOCK.now() > parse_iso(agreement["execution_deadline"]):
        agreement["status"] = "EXPIRED"
        touch(agreement)
        raise ApiError(
            "ERR_AGREEMENT_EXECUTION_DEADLINE_PASSED", 409,
            "Execute attempted after execution_deadline; the agreement "
            "transitions to EXPIRED",
        )

    # Cross-entity: the cluster study must be FINALIZED.
    study = study_of_cluster(project["cluster_group_id"])
    if study is None or study["status"] != "FINALIZED":
        raise ApiError(
            "ERR_STUDY_NOT_FINALIZED", 409,
            "Agreement execution requires cluster Study FINALIZED",
        )

    agreement["status"] = "EXECUTED"
    touch(agreement)
    project["status"] = "AGREEMENT_EXECUTED"
    touch(project)
    return ok(pub(agreement), 200)


@bp.route("/interconnection/agreements/<agreement_id>/extensions", methods=["POST"])
def request_extension(agreement_id):
    user_id, _role = auth(["Developer"])
    agreement = _get_agreement(agreement_id)
    project = DB["projects"].get(agreement["project_id"])

    # Ownership resolves through the parent project.
    if project is None or project["developer_id"] != user_id:
        raise ApiError(
            "ERR_FORBIDDEN_RESOURCE_OWNERSHIP", 403,
            "Developer-role caller does not own the target project",
        )

    # State: extensions apply to an EXECUTED agreement.
    if agreement["status"] != "EXECUTED":
        raise ApiError(
            "ERR_AGREEMENT_NOT_EXECUTED", 409,
            "Extension requires agreement EXECUTED",
        )

    # Clock: the request must arrive at least 30 days before the current
    # target_cod.
    current_target = parse_iso(agreement["target_cod"])
    if CLOCK.now() > current_target - timedelta(days=EXTENSION_NOTICE_DAYS):
        raise ApiError(
            "ERR_EXTENSION_WINDOW_MISSED", 409,
            "Extension requested less than 30 days before the current target_cod",
        )

    # Structural: at most two extensions.
    if agreement["extension_count"] >= EXTENSION_LIMIT:
        raise ApiError(
            "ERR_EXTENSION_LIMIT_REACHED", 409,
            "extension_count already at the maximum of 2",
        )
    data = body()
    new_target_raw = req_dt_str(data, "new_target_cod")
    new_target = parse_iso(new_target_raw)
    if (new_target <= current_target
            or new_target > current_target + timedelta(days=EXTENSION_MAX_DAYS)):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "new_target_cod must be strictly after the current target_cod and "
            "no more than 365 days beyond it",
        )

    agreement["target_cod"] = new_target_raw
    agreement["extension_count"] += 1
    touch(agreement)
    return ok(pub(agreement), 201)
