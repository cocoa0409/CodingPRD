"""TenB5Plan endpoints: create (OCC + supersede), submit, decision, action."""
from datetime import timedelta

from flask import Blueprint, g, request

from db import STORE
from errors import (err, ERR_COMPLIANCE_HOLD, ERR_INVALID_STATE,
                    ERR_POLICY_ACK_REQUIRED, ERR_SELF_ACTION_FORBIDDEN,
                    ERR_STALE_VERSION, ERR_TRAINING_OVERDUE, ERR_UNAUTHORIZED)
from middleware import require_roles, insider_owns, is_insider
from response import success, paginate
from services.core import (new_entity, touch, serialize, sort_created, get_or_404,
                           compute_flags, COOLING_OFF_STANDARD_DAYS,
                           COOLING_OFF_EXECUTIVE_DAYS, EARNINGS_BUFFER_DAYS,
                           EXECUTIVE_DESIGNATIONS)
from util import Body, fmt_ts

bp = Blueprint("plans", __name__)

READ_ROLES = ("Insider", "ComplianceOfficer", "LegalAdmin")


def _cooling_off_end(person, approved_at):
    """STANDARD: approved_at + 30d. EXECUTIVE: max(approved_at + 90d,
    containing QUARTERLY window end_at + 2d); no containing window -> +90d."""
    if person["designation"] not in EXECUTIVE_DESIGNATIONS:
        return approved_at + timedelta(days=COOLING_OFF_STANDARD_DAYS)
    base = approved_at + timedelta(days=COOLING_OFF_EXECUTIVE_DAYS)
    containing = [w for w in STORE.blackout_windows.values()
                  if w["kind"] == "QUARTERLY" and w["status"] != "MERGED"
                  and w["_start_dt"] <= approved_at < w["_end_dt"]]
    if not containing:
        return base
    latest_end = max(w["_end_dt"] for w in containing)
    return max(base, latest_end + timedelta(days=EARNINGS_BUFFER_DAYS))


@bp.post("/tenb5-plans")
def create_plan():
    require_roles("Insider")
    body = Body()
    person_id = body.get_str("covered_person_id")
    ticker = body.get_str("security_ticker")
    total_qty = body.get_num("total_quantity", positive=True, max_dp=4)
    first_trade = body.get_dt("first_trade_date")
    expected = body.get_int("expected_covered_person_version")
    # Authorization (Insider creates only for themselves), then FK existence.
    if person_id is not None:
        insider_owns(person_id)
    person = None
    if person_id is not None:
        person = get_or_404("covered_persons", person_id, "covered person")
    # OCC rides with the state group: creation increments the person's
    # version, so a previously observed version is stale.
    if person is not None and expected is not None and expected != person["version"]:
        raise err(ERR_STALE_VERSION,
                  "expected_covered_person_version does not match the person's current version")
    # Standing gates: compliance hold, policy acknowledgment, training.
    if person is not None:
        ack, training, hold = compute_flags(person)
        if hold:
            raise err(ERR_COMPLIANCE_HOLD, "subject has an open ViolationCase")
        if not ack:
            raise err(ERR_POLICY_ACK_REQUIRED, "policy acknowledgment is not current")
        if not training:
            raise err(ERR_TRAINING_OVERDUE, "annual training is not current")
    body.flush()
    # Supersede: existing DRAFT/SUBMITTED/RETURNED plan for same person +
    # ticker -> CANCELLED.
    for p in sort_created(STORE.tenb5_plans.values()):
        if p["covered_person_id"] == person_id and p["security_ticker"] == ticker \
                and p["status"] in ("DRAFT", "SUBMITTED", "RETURNED"):
            p["status"] = "CANCELLED"
            touch(p)
    p = new_entity()
    p.update({
        "covered_person_id": person_id,
        "security_ticker": ticker,
        "total_quantity": total_qty,
        "first_trade_date": fmt_ts(first_trade),
        "status": "DRAFT",
        "approved_at": None,
        "approved_by": None,
        "return_note": None,
        "cooling_off_end": None,
        "_first_trade_dt": first_trade,
        "_approved_at_dt": None,
        "_cooling_off_end_dt": None,
    })
    STORE.tenb5_plans[p["id"]] = p
    touch(person)  # creation increments the owner's CoveredPerson version
    return success(serialize(p), 201)


@bp.get("/tenb5-plans/<pid>")
def get_plan(pid):
    require_roles(*READ_ROLES)
    p = get_or_404("tenb5_plans", pid, "10b5-1 plan")
    insider_owns(p["covered_person_id"])
    return success(serialize(p))


@bp.get("/tenb5-plans")
def list_plans():
    require_roles(*READ_ROLES)
    items = sort_created(STORE.tenb5_plans.values())
    person_id = request.args.get("covered_person_id")
    status = request.args.get("status")
    if person_id is not None:
        items = [p for p in items if p["covered_person_id"] == person_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate([serialize(p) for p in items])


@bp.post("/tenb5-plans/<pid>/submit")
def submit_plan(pid):
    require_roles("Insider")
    p = get_or_404("tenb5_plans", pid, "10b5-1 plan")
    insider_owns(p["covered_person_id"])
    if p["status"] not in ("DRAFT", "RETURNED"):
        raise err(ERR_INVALID_STATE, "only a DRAFT or RETURNED plan can be submitted")
    p["status"] = "SUBMITTED"
    touch(p)
    return success(serialize(p))


@bp.post("/tenb5-plans/<pid>/decision")
def decide_plan(pid):
    require_roles("ComplianceOfficer")
    p = get_or_404("tenb5_plans", pid, "10b5-1 plan")
    if p["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "only a SUBMITTED plan can be decided")
    if g.user_id == p["covered_person_id"]:
        raise err(ERR_SELF_ACTION_FORBIDDEN, "an officer may not decide their own plan")
    body = Body()
    outcome = body.get_enum("outcome", {"APPROVE", "RETURN"})
    return_note = body.get_str("return_note", required=False)
    body.flush()
    if outcome == "APPROVE":
        person = STORE.covered_persons.get(p["covered_person_id"])
        now = STORE.clock
        p["status"] = "APPROVED"
        p["approved_at"] = fmt_ts(now)
        p["approved_by"] = g.user_id
        p["_approved_at_dt"] = now
        cooling = _cooling_off_end(person, now)
        p["cooling_off_end"] = fmt_ts(cooling)
        p["_cooling_off_end_dt"] = cooling
    else:
        p["status"] = "RETURNED"
        p["return_note"] = return_note
    touch(p)
    return success(serialize(p))


@bp.post("/tenb5-plans/<pid>/action")
def plan_action(pid):
    require_roles("ComplianceOfficer", "Insider")
    p = get_or_404("tenb5_plans", pid, "10b5-1 plan")
    body = Body()
    action = body.get_enum("action", {"SUSPEND", "RESUME", "TERMINATE"})
    # Authorization for the requested action: SUSPEND/RESUME are officer-only;
    # TERMINATE is shared with the owning Insider.
    if action in ("SUSPEND", "RESUME") and is_insider():
        raise err(ERR_UNAUTHORIZED, "only a ComplianceOfficer may suspend or resume a plan")
    if action == "TERMINATE":
        insider_owns(p["covered_person_id"])
    # State validity per action.
    if action == "SUSPEND" and p["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "only an ACTIVE plan can be suspended")
    if action == "RESUME" and p["status"] != "SUSPENDED":
        raise err(ERR_INVALID_STATE, "only a SUSPENDED plan can be resumed")
    if action == "TERMINATE" and p["status"] not in ("DRAFT", "ACTIVE", "SUSPENDED"):
        raise err(ERR_INVALID_STATE,
                  "only a DRAFT, ACTIVE, or SUSPENDED plan can be terminated")
    body.flush()
    p["status"] = {"SUSPEND": "SUSPENDED", "RESUME": "ACTIVE", "TERMINATE": "TERMINATED"}[action]
    touch(p)
    return success(serialize(p))
