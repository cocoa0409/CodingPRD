"""PolicyVersion lifecycle: DRAFT / ACTIVE / SUPERSEDED / RETIRED."""

from flask import Blueprint, request

from db import store
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND,
                    ERR_INVALID_STATE, ERR_ALREADY_TERMINAL,
                    ERR_POLICY_WINDOW_CONFLICT)
from middleware import require_role
import services as svc
from services import new_entity, touch, POLICY_DEFAULTS
from util import (req_dt, opt_dt, opt_int, opt_str, respond_object,
                  respond_list, parse_pagination, paginate)
from views import policy_view

bp = Blueprint("policies", __name__)

READ_ROLES = ("PlatformAdmin", "TalentAdmin", "Recruiter", "HiringManager",
              "PayrollProcessor", "ComplianceOfficer")


def _get_policy(policy_id):
    p = store.policies.get(policy_id)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Policy version not found")
    return p


def _windows_overlap_half_open(f1, t1, f2, t2):
    """Half-open [from, to) overlap; touching endpoints do NOT overlap.
    None `to` means open-ended."""
    return (t2 is None or f1 < t2) and (t1 is None or f2 < t1)


def _check_window_conflict(candidate, exclude_id=None):
    for p in store.policies.values():
        if p["id"] == exclude_id:
            continue
        if p["status"] not in ("DRAFT", "ACTIVE"):
            continue
        if _windows_overlap_half_open(candidate["effective_from"], candidate["effective_to"],
                                      p["effective_from"], p["effective_to"]):
            raise ApiError(ERR_POLICY_WINDOW_CONFLICT, 409,
                           "Policy window overlaps another DRAFT/ACTIVE policy")


@bp.post("/erp/policy-versions")
def create_policy():
    body = request.get_json(silent=True) or {}
    effective_from = req_dt(body, "effective_from")
    effective_to = opt_dt(body, "effective_to", None)
    fields = {}
    for name, default in POLICY_DEFAULTS.items():
        fields[name] = opt_int(body, name, default)
    if not (1 <= fields["hire_pct"] <= 99):
        raise ApiError(ERR_INVALID_REQUEST, 400, "hire_pct must be between 1 and 99")
    note = opt_str(body, "note", None)
    require_role("TalentAdmin")
    policy = {
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "DRAFT",
        "note": note,
    }
    policy.update(fields)
    _check_window_conflict(policy)
    p = new_entity(store.policies, policy)
    return respond_object(policy_view(p), status=201)


@bp.get("/erp/policy-versions")
def list_policies():
    require_role(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = svc.sort_by_created(store.policies.values())
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total = paginate(items, limit, offset)
    return respond_list([policy_view(p) for p in page], total, limit, offset)


@bp.get("/erp/policy-versions/<policy_id>")
def get_policy(policy_id):
    require_role(*READ_ROLES)
    return respond_object(policy_view(_get_policy(policy_id)))


@bp.post("/erp/policy-versions/<policy_id>/activate")
def activate_policy(policy_id):
    require_role("TalentAdmin")
    p = _get_policy(policy_id)
    if p["status"] in svc.POLICY_TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "Policy is in terminal state %s" % p["status"])
    if p["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a DRAFT policy can be activated (currently %s)" % p["status"])
    # Window overlap guard (half-open; touching endpoints allowed).
    _check_window_conflict(p, exclude_id=p["id"])
    # Cannot activate a future policy.
    if p["effective_from"] > store.clock:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "effective_from is in the future; cannot activate")
    previous = svc.active_policy()
    if previous is not None:
        previous["status"] = "SUPERSEDED"
        touch(previous)
    p["status"] = "ACTIVE"
    touch(p)
    return respond_object(policy_view(p))


@bp.post("/erp/policy-versions/<policy_id>/retire")
def retire_policy(policy_id):
    require_role("TalentAdmin")
    p = _get_policy(policy_id)
    if p["status"] in svc.POLICY_TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "Policy is in terminal state %s" % p["status"])
    if p["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a DRAFT policy can be retired (currently %s)" % p["status"])
    p["status"] = "RETIRED"
    touch(p)
    return respond_object(policy_view(p))
