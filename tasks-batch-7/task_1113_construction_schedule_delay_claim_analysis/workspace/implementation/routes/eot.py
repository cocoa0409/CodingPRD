"""TimeExtensionRequest endpoints (PRD §3.6).

Business-rule order for draft and submit (PRD §2.6):
  ERR_TIA_NOT_ACCEPTED -> ERR_REQUESTED_DAYS_EXCEED_ENTITLEMENT
  -> ERR_NON_COMPENSABLE_COST.
For approval: state -> approved-days match -> award match -> stale-version
(the stale-version check is always last).
"""

from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_TIA_NOT_ACCEPTED,
    ERR_REQUESTED_DAYS_EXCEED_ENTITLEMENT,
    ERR_NON_COMPENSABLE_COST,
    ERR_APPROVED_DAYS_MISMATCH,
    ERR_INVALID_PARTIAL_DAYS,
    ERR_AWARD_MISMATCH,
    ERR_APPEAL_LIMIT_REACHED,
    ERR_STALE_VERSION,
)
from middleware import (
    require_roles, json_body, req_field, as_str, as_int, paginate,
    sorted_items, touch, serialize, ANY_ROLE,
)
from response import ok_object, ok_list
from util import new_id, clock_iso, parse_dt, fmt_dt
from routes.common import get_project, get_eot
from services.lda import offset_overlapping_ldas

bp = Blueprint("eot", __name__)


def _opt_query(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


def _check_claim_rules(project, eot):
    """TIA acceptance -> entitlement ceiling -> compensable-cost rule."""
    ev = store.delay_events.get(eot["delay_event_id"])
    if ev is None or ev["project_id"] != project["id"] \
            or ev["status"] != "TIA_ACCEPTED":
        raise ApiError(ERR_TIA_NOT_ACCEPTED, 409,
                       "Linked DelayEvent must be in TIA_ACCEPTED")
    entitlement = (ev.get("apportioned_compensable_days") or 0) + (
        ev.get("apportioned_excusable_non_compensable_days") or 0)
    if eot["requested_days"] > entitlement:
        raise ApiError(ERR_REQUESTED_DAYS_EXCEED_ENTITLEMENT, 422,
                       "requested_days exceeds apportioned compensable + "
                       "excusable-non-compensable days")
    if (eot.get("cost_recovery_cents") or 0) > 0 and (
            ev.get("apportioned_compensable_days") or 0) <= 0:
        raise ApiError(ERR_NON_COMPENSABLE_COST, 422,
                       "cost_recovery_cents > 0 requires compensable days "
                       "> 0 on the linked DelayEvent")


def _apply_approval(project, eot, approved_days, awarded_cost_cents, status):
    eot["approved_days"] = approved_days
    eot["awarded_cost_cents"] = awarded_cost_cents
    eot["status"] = status
    touch(eot)
    old = parse_dt(project["current_completion_date"],
                   "current_completion_date")
    new = old + timedelta(days=approved_days)
    project["current_completion_date"] = fmt_dt(new)
    project["version"] += 1
    project["updated_at"] = clock_iso()
    offset_overlapping_ldas(project, old, new)


@bp.route("/construction-projects/<pid>/eot-requests", methods=["POST"],
          strict_slashes=False)
def create_eot(pid):
    require_roles("ContractorScheduler")
    project = get_project(pid)
    data = json_body()
    delay_event_id = as_str(req_field(data, "delay_event_id"),
                            "delay_event_id")
    requested_days = as_int(req_field(data, "requested_days"),
                            "requested_days")
    if requested_days < 1:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "requested_days must be at least 1")
    cost = as_int(data.get("cost_recovery_cents", 0), "cost_recovery_cents")
    if cost < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "cost_recovery_cents must be >= 0")
    now = clock_iso()
    eot = {
        "id": new_id(),
        "project_id": project["id"],
        "delay_event_id": delay_event_id,
        "requested_days": requested_days,
        "approved_days": None,
        "cost_recovery_cents": cost,
        "awarded_cost_cents": None,
        "submission_round": 1,
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    _check_claim_rules(project, eot)
    store.eot_requests[eot["id"]] = eot
    return ok_object(serialize(eot), 201)


@bp.route("/construction-projects/<pid>/eot-requests", methods=["GET"],
          strict_slashes=False)
def list_eots(pid):
    require_roles(*ANY_ROLE)
    project = get_project(pid)
    items = [e for e in store.eot_requests.values()
             if e["project_id"] == project["id"]]
    status = _opt_query("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items = sorted_items(items)
    page, pg = paginate(items)
    return ok_list([serialize(e) for e in page], pg)


@bp.route("/construction-projects/<pid>/eot-requests/<eid>", methods=["GET"],
          strict_slashes=False)
def get_one_eot(pid, eid):
    require_roles(*ANY_ROLE)
    _, eot = get_eot(pid, eid)
    return ok_object(serialize(eot))


@bp.route("/construction-projects/<pid>/eot-requests/<eid>/submit",
          methods=["POST"], strict_slashes=False)
def submit_eot(pid, eid):
    require_roles("ContractorScheduler")
    project, eot = get_eot(pid, eid)
    json_body()
    if eot["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "EOT request is not in DRAFT")
    _check_claim_rules(project, eot)
    eot["status"] = "SUBMITTED"
    touch(eot)
    return ok_object(serialize(eot))


@bp.route("/construction-projects/<pid>/eot-requests/<eid>/begin-review",
          methods=["POST"], strict_slashes=False)
def begin_review_eot(pid, eid):
    require_roles("OwnerRepresentative")
    project, eot = get_eot(pid, eid)
    json_body()
    if eot["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "EOT request is not in SUBMITTED")
    eot["status"] = "UNDER_REVIEW"
    touch(eot)
    return ok_object(serialize(eot))


@bp.route("/construction-projects/<pid>/eot-requests/<eid>/approve",
          methods=["POST"], strict_slashes=False)
def approve_eot(pid, eid):
    require_roles("OwnerRepresentative")
    project, eot = get_eot(pid, eid)
    data = json_body()
    expected = as_int(req_field(data, "expected_project_version"),
                      "expected_project_version")
    approved_days = as_int(req_field(data, "approved_days"), "approved_days")
    awarded = as_int(req_field(data, "awarded_cost_cents"),
                     "awarded_cost_cents")
    if eot["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "EOT request is not in UNDER_REVIEW")
    if approved_days != eot["requested_days"]:
        raise ApiError(ERR_APPROVED_DAYS_MISMATCH, 422,
                       "Full approval requires approved_days == "
                       "requested_days")
    if (eot.get("cost_recovery_cents") or 0) > 0 \
            and awarded != eot["cost_recovery_cents"]:
        raise ApiError(ERR_AWARD_MISMATCH, 422,
                       "Full approval requires awarded_cost_cents == "
                       "cost_recovery_cents when compensable")
    if expected != project["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_project_version does not match the "
                       "project's current version")
    _apply_approval(project, eot, approved_days, awarded, "APPROVED")
    return ok_object(serialize(eot))


@bp.route("/construction-projects/<pid>/eot-requests/<eid>/partial-approve",
          methods=["POST"], strict_slashes=False)
def partial_approve_eot(pid, eid):
    require_roles("OwnerRepresentative")
    project, eot = get_eot(pid, eid)
    data = json_body()
    expected = as_int(req_field(data, "expected_project_version"),
                      "expected_project_version")
    approved_days = as_int(req_field(data, "approved_days"), "approved_days")
    awarded = as_int(req_field(data, "awarded_cost_cents"),
                     "awarded_cost_cents")
    if eot["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "EOT request is not in UNDER_REVIEW")
    if not (0 < approved_days < eot["requested_days"]):
        raise ApiError(ERR_INVALID_PARTIAL_DAYS, 422,
                       "Partial approval requires 0 < approved_days < "
                       "requested_days")
    if expected != project["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_project_version does not match the "
                       "project's current version")
    _apply_approval(project, eot, approved_days, awarded,
                    "PARTIALLY_APPROVED")
    return ok_object(serialize(eot))


@bp.route("/construction-projects/<pid>/eot-requests/<eid>/deny",
          methods=["POST"], strict_slashes=False)
def deny_eot(pid, eid):
    require_roles("OwnerRepresentative")
    project, eot = get_eot(pid, eid)
    json_body()
    if eot["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "EOT request is not in UNDER_REVIEW")
    eot["status"] = "DENIED"
    touch(eot)
    return ok_object(serialize(eot))


@bp.route("/construction-projects/<pid>/eot-requests/<eid>/appeal",
          methods=["POST"], strict_slashes=False)
def appeal_eot(pid, eid):
    require_roles("ContractorScheduler")
    project, eot = get_eot(pid, eid)
    json_body()
    if eot["status"] != "DENIED":
        raise ApiError(ERR_INVALID_STATE, 409, "EOT request is not in DENIED")
    if eot["submission_round"] >= 3:
        raise ApiError(ERR_APPEAL_LIMIT_REACHED, 409,
                       "EOT appeal cap (submission_round >= 3) reached")
    eot["submission_round"] += 1
    eot["status"] = "SUBMITTED"
    touch(eot)
    return ok_object(serialize(eot))
