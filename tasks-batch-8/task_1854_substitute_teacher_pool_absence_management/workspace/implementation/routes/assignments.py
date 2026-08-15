"""Assignment endpoints: manual offer, get, list, respond, cancel,
report-outcome, verify, extend."""

from flask import Blueprint, request

import domain
from db import STORE, new_entity, touch, public
from errors import (
    raise_err, ERR_ABSENCE_NOT_FOUND, ERR_ASSIGNMENT_NOT_FOUND,
    ERR_SUBSTITUTE_NOT_FOUND, ERR_ABSENCE_INVALID_STATE,
    ERR_ASSIGNMENT_INVALID_STATE, ERR_SUBSTITUTE_INVALID_STATE,
    ERR_SUBSTITUTE_DO_NOT_RETURN, ERR_CLEARANCE_INVALID,
    ERR_QUALIFICATION_MISMATCH, ERR_INVALID_DATE_RANGE,
    ERR_ASSIGNMENT_DATE_OVERLAP, ERR_LONG_TERM_APPROVAL_REQUIRED,
    ERR_COVERAGE_BUDGET_INSUFFICIENT,
)
from middleware import (
    auth_context, require_role, require_coordinator_school,
    require_substitute_self, ALL_ROLES,
)
from response import ok, paginated
from util import parse_date, parse_datetime, weekday_count, midnight_utc
from decimal import Decimal
from validate import body, req_str, req_enum, req_date

bp = Blueprint("assignments", __name__)

ASG_STATUSES = ("OFFERED", "ACCEPTED", "DECLINED", "EXPIRED", "CANCELLED",
                "WORKED", "NO_SHOW", "VERIFIED", "PAID")


def _get_assignment_or_404(aid):
    asg = STORE.assignments.get(aid)
    if asg is None:
        raise_err(ERR_ASSIGNMENT_NOT_FOUND, "assignment id does not exist")
    return asg


def _lazy_expire(asg):
    """An offer whose expiry instant has been reached auto-flips to EXPIRED
    (with the decline-style re-dispatch cascade) when it is acted upon."""
    if asg["status"] == "OFFERED" and parse_datetime(asg["offer_expires_at"]) <= domain.now():
        asg["status"] = "EXPIRED"
        touch(asg)
        domain.redispatch(domain.assignment_absence(asg))


def _check_offerable_absence(absence):
    if absence["fill_status"] not in ("REPORTED", "DISPATCHING", "UNFILLED"):
        raise_err(ERR_ABSENCE_INVALID_STATE,
                  "offers require fill_status REPORTED, DISPATCHING, or UNFILLED")
    if absence["approval_status"] in ("PENDING", "REJECTED"):
        raise_err(ERR_ABSENCE_INVALID_STATE,
                  "dispatch and offers are blocked while approval is PENDING or REJECTED")
    if parse_date(absence["end_date"]) < domain.now().date():
        raise_err(ERR_ABSENCE_INVALID_STATE, "the absence end_date has passed")
    if absence["days_covered_internal"] != 0:
        raise_err(ERR_ABSENCE_INVALID_STATE,
                  "the absence already has internal coverage days")


def _check_substitute_eligibility(sub, absence):
    """The acceptance gauntlet of PRD 3.4 in pinned pipeline order
    (substitute state -> DNR -> clearance -> qualification -> overlap)."""
    domain.refresh_substitute_scores(sub)
    if sub["status"] != "ACTIVE":
        raise_err(ERR_SUBSTITUTE_INVALID_STATE, "substitute is not ACTIVE")
    if domain.active_mark(absence["school_id"], sub["id"], "DO_NOT_RETURN"):
        raise_err(ERR_SUBSTITUTE_DO_NOT_RETURN,
                  "an ACTIVE DO_NOT_RETURN mark exists for this school and substitute")
    if not domain.required_clearances_valid(sub["id"], parse_date(absence["end_date"])):
        raise_err(ERR_CLEARANCE_INVALID,
                  "required clearances must be VERIFIED through the absence end_date")
    if not domain.has_qualification(sub["id"], absence["required_subject"],
                                    absence["required_grade_band"]):
        raise_err(ERR_QUALIFICATION_MISMATCH, "substitute lacks the required qualification")
    if domain.has_assignment_overlap(sub["id"], parse_date(absence["start_date"]),
                                     parse_date(absence["end_date"])):
        raise_err(ERR_ASSIGNMENT_DATE_OVERLAP,
                  "substitute already holds a committed assignment overlapping this range")


def _accept_offer(asg, absence):
    """Shared accept side effects: ACCEPTED, absence -> ASSIGNED, other
    OFFERED assignments cancelled (ABSENCE_CANCEL), budget committed."""
    sub = STORE.substitutes[asg["substitute_id"]]
    school = STORE.schools[asg["school_id"]]
    if domain.budget_available(school) < asg["provisional_pay_cents"]:
        raise_err(ERR_COVERAGE_BUDGET_INSUFFICIENT,
                  "school coverage budget cannot cover the provisional pay")
    asg["status"] = "ACCEPTED"
    touch(asg)
    for other in sorted(STORE.assignments.values(), key=lambda x: x["_seq"]):
        if (other["absence_id"] == absence["id"] and other["id"] != asg["id"]
                and other["status"] == "OFFERED"):
            domain.cancel_assignment(other, "ABSENCE_CANCEL")
    absence["fill_status"] = "ASSIGNED"
    touch(absence)
    school["coverage_budget_committed_cents"] += asg["provisional_pay_cents"]
    touch(school)


@bp.route("/assignments", methods=["POST"])
def create_assignment():
    user_id, role = auth_context()
    data = body()
    absence_id = req_str(data, "absence_id")
    substitute_id = req_str(data, "substitute_id")
    require_role(role, ["SchoolCoordinator", "DistrictAdmin"])
    absence = STORE.absences.get(absence_id)
    if role == "SchoolCoordinator":
        require_coordinator_school(user_id, absence["school_id"] if absence else None)
    if absence is None:
        raise_err(ERR_ABSENCE_NOT_FOUND, "absence id does not exist")
    sub = STORE.substitutes.get(substitute_id)
    if sub is None:
        raise_err(ERR_SUBSTITUTE_NOT_FOUND, "substitute id does not exist")
    _check_offerable_absence(absence)
    _check_substitute_eligibility(sub, absence)
    if (domain.existing_assignment_for(absence_id, substitute_id, ("OFFERED", "ACCEPTED"))
            or domain.existing_assignment_for(absence_id, substitute_id, ("DECLINED", "EXPIRED"))):
        raise_err(ERR_ASSIGNMENT_INVALID_STATE,
                  "this substitute was already asked about this absence")
    asg = domain.create_offer(absence, sub, "MANUAL_OFFER")
    if absence["fill_status"] in ("REPORTED", "UNFILLED"):
        absence["fill_status"] = "DISPATCHING"
        touch(absence)
    return ok(public(asg), status=201)


@bp.route("/assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return ok(public(_get_assignment_or_404(aid)))


@bp.route("/assignments", methods=["GET"])
def list_assignments():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    absence_id = request.args.get("absence_id")
    substitute_id = request.args.get("substitute_id")
    school_id = request.args.get("school_id")
    status = request.args.get("status")
    items = sorted(STORE.assignments.values(), key=lambda a: (a["created_at"], a["_seq"]))
    if absence_id is not None:
        items = [a for a in items if a["absence_id"] == absence_id]
    if substitute_id is not None:
        items = [a for a in items if a["substitute_id"] == substitute_id]
    if school_id is not None:
        items = [a for a in items if a["school_id"] == school_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, meta = paginated(items)
    return ok([public(a) for a in page], pagination=meta)


@bp.route("/assignments/<aid>/respond", methods=["POST"])
def respond_assignment(aid):
    user_id, role = auth_context()
    data = body()
    decision = req_enum(data, "decision", ("ACCEPT", "DECLINE"))
    require_role(role, ["Substitute"])
    asg = STORE.assignments.get(aid)
    if asg is not None:
        require_substitute_self(user_id, asg["substitute_id"])
    if asg is None:
        raise_err(ERR_ASSIGNMENT_NOT_FOUND, "assignment id does not exist")
    _lazy_expire(asg)
    if asg["status"] != "OFFERED":
        raise_err(ERR_ASSIGNMENT_INVALID_STATE, "respond requires status OFFERED")
    absence = domain.assignment_absence(asg)
    if decision == "DECLINE":
        asg["status"] = "DECLINED"
        touch(asg)
        domain.redispatch(absence)
        return ok(public(asg))
    # ACCEPT: the full gated chain in pipeline order.
    if absence["fill_status"] != "DISPATCHING":
        raise_err(ERR_ABSENCE_INVALID_STATE, "absence is not DISPATCHING")
    if absence["approval_status"] not in ("NOT_REQUIRED", "APPROVED"):
        raise_err(ERR_ABSENCE_INVALID_STATE, "absence approval does not allow acceptance")
    sub = STORE.substitutes[asg["substitute_id"]]
    _check_substitute_eligibility(sub, absence)
    _accept_offer(asg, absence)
    return ok(public(asg))


@bp.route("/assignments/<aid>/cancel", methods=["POST"])
def cancel_assignment_route(aid):
    user_id, role = auth_context()
    body()
    require_role(role, ["Substitute", "SchoolCoordinator", "DistrictAdmin"])
    asg = STORE.assignments.get(aid)
    if asg is not None:
        if role == "Substitute":
            require_substitute_self(user_id, asg["substitute_id"])
        elif role == "SchoolCoordinator":
            require_coordinator_school(user_id, asg["school_id"])
    if asg is None:
        raise_err(ERR_ASSIGNMENT_NOT_FOUND, "assignment id does not exist")
    if asg["status"] not in ("OFFERED", "ACCEPTED"):
        raise_err(ERR_ASSIGNMENT_INVALID_STATE,
                  "only an OFFERED or ACCEPTED assignment may be cancelled")
    absence = domain.assignment_absence(asg)
    district = domain.assignment_district(asg)
    reason = "SUB_CANCEL" if role == "Substitute" else "COORDINATOR_CANCEL"
    reliability = None
    if role == "Substitute" and asg["status"] == "ACCEPTED":
        # LATE when the cancel lands before the first day with strictly less
        # than short-notice lead remaining; otherwise EARLY.
        start_midnight = midnight_utc(parse_date(absence["start_date"]))
        lead = Decimal(str((start_midnight - domain.now()).total_seconds())) / Decimal(3600)
        if domain.now() < start_midnight and lead < Decimal(str(district["short_notice_hours"])):
            reliability = "SUB_CANCEL_LATE"
        else:
            reliability = "SUB_CANCEL_EARLY"
    domain.cancel_assignment(asg, reason, reliability_event=reliability, district=district)
    return ok(public(asg))


@bp.route("/assignments/<aid>/report-outcome", methods=["POST"])
def report_outcome(aid):
    user_id, role = auth_context()
    data = body()
    outcome = req_enum(data, "outcome", ("WORKED", "NO_SHOW"))
    require_role(role, ["SchoolCoordinator", "DistrictAdmin"])
    asg = STORE.assignments.get(aid)
    if role == "SchoolCoordinator":
        require_coordinator_school(user_id, asg["school_id"] if asg else None)
    if asg is None:
        raise_err(ERR_ASSIGNMENT_NOT_FOUND, "assignment id does not exist")
    if asg["status"] != "ACCEPTED":
        raise_err(ERR_ASSIGNMENT_INVALID_STATE, "report-outcome requires status ACCEPTED")
    absence = domain.assignment_absence(asg)
    if outcome == "WORKED":
        if domain.now().date() < parse_date(asg["start_date"]):
            raise_err(ERR_ASSIGNMENT_INVALID_STATE,
                      "the assignment start_date has not been reached")
        asg["status"] = "WORKED"
        touch(asg)
        return ok(public(asg))
    # NO_SHOW: release reserve, -25 event + suspension evaluation, auto flag,
    # absence reopens and re-dispatches.
    school = STORE.schools[asg["school_id"]]
    district = domain.assignment_district(asg)
    sub = STORE.substitutes[asg["substitute_id"]]
    school["coverage_budget_committed_cents"] -= asg["provisional_pay_cents"]
    touch(school)
    asg["status"] = "NO_SHOW"
    touch(asg)
    domain.append_event(sub, "NO_SHOW", assignment_id=asg["id"], district=district)
    new_entity(STORE.flags, {
        "substitute_id": sub["id"],
        "school_id": asg["school_id"],
        "assignment_id": asg["id"],
        "flag_type": "NO_SHOW",
        "severity": "MAJOR",
        "status": "OPEN",
        "auto_created": True,
    })
    if absence["fill_status"] == "ASSIGNED":
        absence["fill_status"] = "DISPATCHING"
        touch(absence)
    domain.redispatch(absence)
    return ok(public(asg))


@bp.route("/assignments/<aid>/verify", methods=["POST"])
def verify_assignment(aid):
    user_id, role = auth_context()
    body()
    require_role(role, ["SchoolCoordinator", "DistrictAdmin"])
    asg = STORE.assignments.get(aid)
    if role == "SchoolCoordinator":
        require_coordinator_school(user_id, asg["school_id"] if asg else None)
    if asg is None:
        raise_err(ERR_ASSIGNMENT_NOT_FOUND, "assignment id does not exist")
    if asg["status"] != "WORKED":
        raise_err(ERR_ASSIGNMENT_INVALID_STATE, "verify requires status WORKED")
    if any(t["assignment_id"] == aid and t["status"] == "SUBMITTED"
           for t in STORE.timesheets.values()):
        raise_err(ERR_ASSIGNMENT_INVALID_STATE,
                  "SUBMITTED timesheets must be reviewed before verification")
    absence = domain.assignment_absence(asg)
    district = domain.assignment_district(asg)
    sub = STORE.substitutes[asg["substitute_id"]]
    asg["final_payout_cents"] = domain.compute_final_payout(asg)
    asg["status"] = "VERIFIED"
    touch(asg)
    domain.append_event(sub, "COMPLETION", assignment_id=asg["id"], district=district)
    if absence["fill_status"] == "ASSIGNED":
        absence["fill_status"] = "COMPLETED"
    domain.recompute_day_counters(absence)
    return ok(public(asg))


@bp.route("/assignments/<aid>/extend", methods=["POST"])
def extend_assignment(aid):
    user_id, role = auth_context()
    data = body()
    new_end = req_date(data, "new_end_date")
    require_role(role, ["SchoolCoordinator", "DistrictAdmin"])
    asg = STORE.assignments.get(aid)
    if role == "SchoolCoordinator":
        require_coordinator_school(user_id, asg["school_id"] if asg else None)
    if asg is None:
        raise_err(ERR_ASSIGNMENT_NOT_FOUND, "assignment id does not exist")
    if asg["status"] not in ("ACCEPTED", "WORKED"):
        raise_err(ERR_ASSIGNMENT_INVALID_STATE,
                  "only an ACCEPTED or WORKED assignment may be extended")
    absence = domain.assignment_absence(asg)
    district = domain.assignment_district(asg)
    start = parse_date(asg["start_date"])
    end = parse_date(new_end)
    if end < start:
        raise_err(ERR_INVALID_DATE_RANGE, "new_end_date must not precede the start_date")
    new_total = weekday_count(start, end)
    if new_total < 1:
        raise_err(ERR_INVALID_DATE_RANGE, "the new range must contain at least one weekday")
    if domain.has_assignment_overlap(asg["substitute_id"], start, end,
                                     exclude_assignment_id=aid):
        raise_err(ERR_ASSIGNMENT_DATE_OVERLAP,
                  "extension collides with another committed assignment")
    if (new_total > district["long_term_approval_days"]
            and absence["approval_status"] != "APPROVED"):
        raise_err(ERR_LONG_TERM_APPROVAL_REQUIRED,
                  "extension past the approval threshold requires prior district approval")
    school = STORE.schools[asg["school_id"]]
    old_provisional = asg["provisional_pay_cents"]
    absence["end_date"] = new_end
    absence["total_days"] = new_total
    domain.recompute_day_counters(absence)
    asg["end_date"] = new_end
    asg["scheduled_days"] = new_total
    sub = STORE.substitutes[asg["substitute_id"]]
    asg["provisional_pay_cents"] = domain.provisional_pay(
        sub, new_total, asg["premium_multiplier_snapshot"])
    touch(asg)
    school["coverage_budget_committed_cents"] += asg["provisional_pay_cents"] - old_provisional
    touch(school)
    return ok(public(asg))
