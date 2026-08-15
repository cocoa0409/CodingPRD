"""ApprovalStep endpoints: list per offer, decide."""

from flask import Blueprint

import db
from errors import (
    raise_err, ERR_OFFER_NOT_FOUND, ERR_APPROVAL_STEP_NOT_FOUND,
    ERR_STEP_NOT_ACTIONABLE, ERR_SELF_APPROVAL_FORBIDDEN,
    ERR_UNAUTHORIZED_ROLE, ERR_DELEGATION_NOT_ACTIVE,
)
from middleware import get_actor, require_role, get_json_body, validate_fields, req_enum, req_string
from response import success
from services import calc
from services import offer_ops

bp = Blueprint("approval_steps", __name__)

READ_ROLES = ["Recruiter", "HiringManager", "CompAnalyst", "DepartmentDirector",
              "VPPeople", "HRAdmin"]
DECIDE_ROLES = ["HiringManager", "CompAnalyst", "DepartmentDirector", "VPPeople"]


@bp.route("/api/offers/<offer_id>/approval-steps", methods=["GET"])
def list_steps(offer_id):
    uid, role = get_actor()
    require_role(role, READ_ROLES)
    offer = db.offers.get(offer_id)
    if offer is None:
        raise_err(ERR_OFFER_NOT_FOUND, "Offer not found")
    steps = sorted(
        [s for s in db.approval_steps.values() if s["offer_id"] == offer_id],
        key=lambda s: s["sequence"],
    )
    return success(steps, response_type="array")


def _find_active_grant(delegate_uid, scope_role):
    """Locate an ACTIVE grant for (delegate, scope_role) whose window contains the
    logical clock. Lazily marks expired grants EXPIRED. Returns (grant, error_code)
    where error_code is set when a grant exists but is not usable."""
    now = db.clock_now()
    candidate = None
    for g in db.delegation_grants.values():
        if g["delegate_user_id"] == delegate_uid and g["scope_role"] == scope_role:
            if g["status"] == "ACTIVE" and now >= g["valid_until"]:
                g["status"] = "EXPIRED"
                calc.touch(g)
            if g["status"] == "ACTIVE":
                if g["valid_from"] <= now < g["valid_until"]:
                    candidate = g
                else:
                    # active but not yet valid (clock before valid_from)
                    if candidate is None:
                        candidate = None
    return candidate


@bp.route("/api/approval-steps/<step_id>/decide", methods=["POST"])
def decide(step_id):
    uid, role = get_actor()
    body = get_json_body()
    validate_fields(body, ["decision"], ["note"])
    decision = req_enum(body, "decision", ["APPROVED", "REJECTED"])
    note = body.get("note")
    if note is not None and not isinstance(note, str):
        from errors import ERR_INVALID_REQUEST
        raise_err(ERR_INVALID_REQUEST, "note must be a string")
    require_role(role, DECIDE_ROLES)
    step = db.approval_steps.get(step_id)
    if step is None:
        raise_err(ERR_APPROVAL_STEP_NOT_FOUND, "Approval step not found")
    offer = db.offers[step["offer_id"]]
    # Authorization: role match OR active delegation (priority 3)
    via_grant = None
    if role != step["required_role"]:
        via_grant = _find_active_grant(uid, step["required_role"])
        if via_grant is None:
            # A grant exists in some state but unusable, or none at all.
            any_grant = [
                g for g in db.delegation_grants.values()
                if g["delegate_user_id"] == uid and g["scope_role"] == step["required_role"]
            ]
            if any_grant:
                raise_err(ERR_DELEGATION_NOT_ACTIVE,
                          "Delegation grant is revoked, expired, or not yet valid")
            raise_err(ERR_UNAUTHORIZED_ROLE,
                      f"Role {role} does not match required role {step['required_role']}")
    # State gate (priority 6)
    if step["status"] != "ACTIONABLE":
        raise_err(ERR_STEP_NOT_ACTIONABLE, "Approval step is not ACTIONABLE")
    # Segregation of duties (priority 8)
    if uid == offer["created_by_user_id"]:
        raise_err(ERR_SELF_APPROVAL_FORBIDDEN, "Offer creator may not decide its approval steps")
    req = db.requisitions[offer["requisition_id"]]
    step["decided_by_user_id"] = uid
    step["decided_via_delegation"] = via_grant is not None
    step["delegation_grant_id"] = via_grant["id"] if via_grant else None
    step["decision_note"] = note
    if decision == "APPROVED":
        step["status"] = "APPROVED"
        calc.touch(step)
        offer_ops.append_event(offer["id"], "STEP_APPROVED", uid, f"sequence={step['sequence']}")
        # next WAITING step becomes ACTIONABLE; else offer approved.
        # Only consider the current (non-superseded) chain.
        current_chain = [s for s in db.approval_steps.values()
                         if s["offer_id"] == offer["id"] and s["status"] in ("WAITING", "ACTIONABLE", "APPROVED")]
        waiting = [s for s in current_chain if s["status"] == "WAITING"]
        if waiting:
            nxt = min(waiting, key=lambda s: s["sequence"])
            nxt["status"] = "ACTIONABLE"
            calc.touch(nxt)
        else:
            # chain fully approved
            offer["status"] = "APPROVED"
            calc.touch_no_version(offer)
            for p in db.perks.values():
                if p["offer_id"] == offer["id"] and p["status"] == "LOCKED":
                    p["status"] = "APPROVED"
                    calc.touch(p)
            offer_ops.append_event(offer["id"], "APPROVED", uid, None)
    else:  # REJECTED
        step["status"] = "REJECTED"
        calc.touch(step)
        offer_ops.append_event(offer["id"], "STEP_REJECTED", uid, f"sequence={step['sequence']}")
        # cascade: offer PENDING_APPROVAL -> RETURNED
        offer["status"] = "RETURNED"
        calc.touch_no_version(offer)
        offer_ops.supersede_steps(offer["id"], ("WAITING", "ACTIONABLE"), uid)
        for p in db.perks.values():
            if p["offer_id"] == offer["id"] and p["status"] == "LOCKED":
                p["status"] = "DRAFT"
                calc.touch(p)
        calc.recompute_committed_budget(req)
        offer_ops.append_event(offer["id"], "RETURNED", uid, None)
    return success(step)
