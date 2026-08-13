"""Case endpoints: intake, assignment, advance, adjudication, reopen, merge,
resolve-subject, close-referred, summary (PRD §3.3, §3.5)."""

from datetime import timedelta

from flask import Blueprint, request

from db import db, clock_now, fmt_iso, parse_iso
from middleware import get_auth, require_role, ALL_ROLES
from response import success_object, success_list, parse_pagination
from services.validate import (
    body, req_string, opt_string, opt_int, req_enum, opt_bool, get_or_404,
)
from services.entities import make_case, pub, touch
from services.calculations import (
    recompute_case_total_loss, recompute_case_priority,
    recompute_case_restitution_status, recompute_period_accruals,
    recompute_group_counters, evaluate_group_escalation,
    refresh_case_hold_retention,
)
from errors import (
    ApiError, err400, err403, err404, err409,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION, ERR_STORE_CLOSED,
    ERR_EMPLOYEE_NOT_ACTIVE, ERR_SUBJECT_MISMATCH, ERR_SUBJECT_UNRESOLVED,
    ERR_NOT_CASE_ASSIGNEE, ERR_NO_ACTIVE_EVIDENCE, ERR_RECOVERED_EXCEEDS_LOSS,
    ERR_SOD_INTERVIEWER_ADJUDICATOR, ERR_SOD_CASE_CREATOR,
    ERR_INTERVIEW_DOC_STALE, ERR_DEMAND_REQUIRED, ERR_NO_OPEN_PERIOD,
    ERR_REOPEN_WINDOW_CLOSED, ERR_PERIOD_LOCKED, ERR_CASE_HAS_PAYMENTS,
    ERR_MERGE_NOT_ALLOWED, ERR_CASE_NOT_REFERRABLE, ERR_FORBIDDEN_FOR_ROLE,
)

bp = Blueprint("cases", __name__)

TERMINAL_CASE_STATES = {"CLOSED_REFERRED", "MERGED"}
CLOSED_STATES = {"CLOSED_SUBSTANTIATED", "CLOSED_UNSUBSTANTIATED", "CLOSED_REFERRED"}


def _check_subject_consistency(subject_type, employee_id):
    """Shared subject-consistency rules (create / convert / resolve-subject)."""
    if subject_type == "EMPLOYEE":
        if employee_id is None:
            raise err409(ERR_SUBJECT_MISMATCH,
                         "subject_type=EMPLOYEE requires employee_id")
        emp = db.employees.get(employee_id)
        if emp is None:
            raise err404("employee %s not found" % employee_id)
        if emp["status"] == "TERMINATED":
            raise err409(ERR_EMPLOYEE_NOT_ACTIVE, "Employee is TERMINATED")
    else:
        if employee_id is not None:
            raise err409(ERR_SUBJECT_MISMATCH,
                         "EXTERNAL/UNKNOWN subject types require null employee_id")


def _post_loss_to_period(case):
    """Post case.total_loss_cents into the store's eligible shrink period."""
    now = clock_now()
    eligible = None
    for p in db.shrink_periods.values():
        if p["store_id"] != case["store_id"]:
            continue
        if p["status"] not in ("OPEN", "COUNTED"):
            continue
        if parse_iso(p["period_start"]) <= now <= parse_iso(p["period_end"]):
            eligible = p
            break
    if eligible is None:
        raise err409(ERR_NO_OPEN_PERIOD,
                     "No shrink period containing the current date in OPEN or "
                     "COUNTED status")
    amount = case["total_loss_cents"]
    case["loss_posted_cents"] = amount
    case["loss_posted_period_id"] = eligible["id"]
    eligible["known_loss_posted_cents"] += amount
    recompute_period_accruals(eligible)
    touch(eligible)
    store = db.stores[case["store_id"]]
    store["total_adjudicated_loss_cents"] += amount
    touch(store)


def _reverse_loss_posting(case):
    if case["loss_posted_cents"] > 0 and case.get("loss_posted_period_id"):
        period = db.shrink_periods.get(case["loss_posted_period_id"])
        if period is not None:
            period["known_loss_posted_cents"] -= case["loss_posted_cents"]
            recompute_period_accruals(period)
            touch(period)
        store = db.stores.get(case["store_id"])
        if store is not None:
            store["total_adjudicated_loss_cents"] -= case["loss_posted_cents"]
            touch(store)
    case["loss_posted_cents"] = 0
    case["loss_posted_period_id"] = None


def _cancel_draft_demands(case_id):
    for d in db.civil_demands.values():
        if d["case_id"] == case_id and d["status"] == "DRAFT":
            d["status"] = "CANCELLED"
            touch(d)


@bp.route("/cases", methods=["POST"])
def create_case():
    user_id, role = get_auth()
    require_role(role, {"LPAnalyst"})
    data = body()
    store_id = req_string(data, "store_id")
    subject_type = req_enum(data, "subject_type",
                            ["EMPLOYEE", "EXTERNAL", "UNKNOWN"])
    employee_id = opt_string(data, "employee_id")
    manual_loss_cents = opt_int(data, "manual_loss_cents", default=0, minimum=0)

    store = get_or_404(db.stores, store_id, "store")
    if employee_id is not None:
        get_or_404(db.employees, employee_id, "employee")
    if store["status"] != "ACTIVE":
        raise err409(ERR_STORE_CLOSED, "Store is CLOSED")
    _check_subject_consistency(subject_type, employee_id)

    case = make_case(store, "MANUAL", subject_type, employee_id, user_id,
                     manual_loss_cents=manual_loss_cents)
    db.cases[case["id"]] = case
    recompute_case_total_loss(case)
    touch(case)
    return success_object(pub(case), status=201)


@bp.route("/cases", methods=["GET"])
def list_cases():
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    filters = {
        "store_id": _q("store_id"),
        "employee_id": _q("employee_id"),
        "status": _q("status"),
        "subject_type": _q("subject_type"),
        "source": _q("source"),
        "merged_into_case_id": _q("merged_into_case_id"),
        "loss_posted_period_id": _q("loss_posted_period_id"),
        "priority": _q("priority"),
    }
    items = sorted(db.cases.values(), key=lambda c: (c["created_at"], c["id"]))
    for field, val in filters.items():
        if val is not None:
            items = [c for c in items if c.get(field) == val]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([pub(c) for c in page], limit, offset, total)


@bp.route("/cases/<case_id>", methods=["GET"])
def get_case(case_id):
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    case = get_or_404(db.cases, case_id, "case")
    return success_object(pub(case))


@bp.route("/cases/<case_id>/summary", methods=["GET"])
def case_summary(case_id):
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    case = get_or_404(db.cases, case_id, "case")
    evidence = [e for e in db.evidence_items.values() if e["case_id"] == case_id]
    interviews = [i for i in db.interviews.values() if i["case_id"] == case_id]
    demands = [d for d in db.civil_demands.values() if d["case_id"] == case_id]
    links = [l for l in db.case_links.values()
             if l["case_id"] == case_id and l["status"] == "CONFIRMED"]
    demand_outstanding = sum(d["outstanding_cents"] for d in demands
                             if d["status"] in ("ISSUED", "PARTIALLY_PAID"))
    return success_object({
        "case_id": case["id"],
        "total_loss_cents": case["total_loss_cents"],
        "evidence_count": len(evidence),
        "sealed_evidence_count": len([e for e in evidence if e["status"] == "SEALED"]),
        "documented_interview_count": len([i for i in interviews
                                           if i["status"] == "DOCUMENTED"]),
        "demand_outstanding_cents": demand_outstanding,
        "confirmed_link_count": len(links),
        "restitution_status": case["restitution_status"],
    })


@bp.route("/cases/<case_id>/assign", methods=["POST"])
def assign_case(case_id):
    user_id, role = get_auth()
    require_role(role, {"LPManager"})
    data = body()
    analyst_id = req_string(data, "analyst_id")
    case = get_or_404(db.cases, case_id, "case")
    if case["status"] != "OPEN":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Case must be OPEN to assign")
    case["assigned_analyst_id"] = analyst_id
    case["status"] = "INVESTIGATING"
    touch(case)
    return success_object(pub(case))


@bp.route("/cases/<case_id>/advance", methods=["POST"])
def advance_case(case_id):
    user_id, role = get_auth()
    require_role(role, {"LPAnalyst"})
    data = body()
    recovered = opt_int(data, "recovered_value_cents", default=None, minimum=0)
    case = get_or_404(db.cases, case_id, "case")
    # ownership: assignee only
    if case.get("assigned_analyst_id") != user_id:
        raise err403(ERR_NOT_CASE_ASSIGNEE,
                     "Actor is not the case's assigned analyst")
    if case["status"] == "INVESTIGATING":
        # INVESTIGATING -> READY_FOR_INTERVIEW
        has_evidence = any(
            e["case_id"] == case_id and e["status"] in ("ACTIVE", "SEALED")
            for e in db.evidence_items.values())
        if not has_evidence:
            raise err409(ERR_NO_ACTIVE_EVIDENCE,
                         "At least one evidence item in ACTIVE or SEALED status "
                         "is required")
        if recovered is not None:
            attributable = (sum(
                db.exception_events[eid]["amount_cents"]
                for a in db.alerts.values() if a.get("case_id") == case_id
                for eid in a["_member_event_ids"])
                + case["manual_loss_cents"])
            if recovered > attributable:
                raise err409(ERR_RECOVERED_EXCEEDS_LOSS,
                             "recovered_value_cents exceeds member-event sum plus "
                             "manual loss")
            case["recovered_value_cents"] = recovered
        recompute_case_total_loss(case)
        case["status"] = "READY_FOR_INTERVIEW"
        touch(case)
        return success_object(pub(case))
    elif case["status"] == "INTERVIEWED":
        # INTERVIEWED -> ADJUDICATING
        if case["subject_type"] not in ("EMPLOYEE", "EXTERNAL"):
            raise err409(ERR_SUBJECT_UNRESOLVED,
                         "subject_type must be EMPLOYEE or EXTERNAL")
        if recovered is not None:
            attributable = (sum(
                db.exception_events[eid]["amount_cents"]
                for a in db.alerts.values() if a.get("case_id") == case_id
                for eid in a["_member_event_ids"])
                + case["manual_loss_cents"])
            if recovered > attributable:
                raise err409(ERR_RECOVERED_EXCEEDS_LOSS,
                             "recovered_value_cents exceeds member-event sum plus "
                             "manual loss")
            case["recovered_value_cents"] = recovered
            recompute_case_total_loss(case)
        case["status"] = "ADJUDICATING"
        touch(case)
        return success_object(pub(case))
    else:
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "No advance transition from status %s" % case["status"])


@bp.route("/cases/<case_id>/dismiss", methods=["POST"])
def dismiss_case(case_id):
    user_id, role = get_auth()
    require_role(role, {"LPManager"})
    data = body()
    req_string(data, "reason")
    case = get_or_404(db.cases, case_id, "case")
    if case["status"] != "INVESTIGATING":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Case must be INVESTIGATING to dismiss")
    case["status"] = "CLOSED_UNSUBSTANTIATED"
    case["closed_at"] = fmt_iso(clock_now())
    touch(case)
    refresh_case_hold_retention(case)
    return success_object(pub(case))


@bp.route("/cases/<case_id>/adjudicate", methods=["POST"])
def adjudicate_case(case_id):
    user_id, role = get_auth()
    require_role(role, {"LPManager", "HRPartner"})
    data = body()
    decision = req_enum(data, "decision", ["SUBSTANTIATED", "UNSUBSTANTIATED"])
    employment_action = data.get("employment_action")
    if employment_action is not None and employment_action not in ("TERMINATE", "SUSPEND"):
        raise err400(ERR_INVALID_REQUEST,
                     "employment_action must be TERMINATE or SUSPEND")
    restitution_waived = opt_bool(data, "restitution_waived", default=False)
    documentation_override = opt_bool(data, "documentation_override", default=False)

    case = get_or_404(db.cases, case_id, "case")

    # role routing by subject type (priority 2, context routing)
    if case["subject_type"] == "EMPLOYEE" and role != "HRPartner":
        raise ApiError(ERR_FORBIDDEN_FOR_ROLE,
                       "EMPLOYEE-subject cases may be adjudicated only by HRPartner",
                       403)
    if case["subject_type"] == "EXTERNAL" and role != "LPManager":
        raise ApiError(ERR_FORBIDDEN_FOR_ROLE,
                       "EXTERNAL-subject cases may be adjudicated only by LPManager",
                       403)

    if case["status"] != "ADJUDICATING":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Case must be ADJUDICATING to adjudicate")

    # SoD gates (priority 9)
    documented = [i for i in db.interviews.values()
                  if i["case_id"] == case_id and i["status"] == "DOCUMENTED"]
    for iv in documented:
        if iv["interviewer_id"] == user_id:
            raise err409(ERR_SOD_INTERVIEWER_ADJUDICATOR,
                         "Adjudicator conducted a DOCUMENTED interview on this case")
    if case["created_by"] == user_id:
        raise err409(ERR_SOD_CASE_CREATOR,
                     "Adjudicator is the analyst who created the case")

    # documentation staleness (priority 10)
    if documented:
        latest = max(documented, key=lambda i: i["documented_at"])
        if latest["doc_stale"] and not documentation_override:
            raise err409(ERR_INTERVIEW_DOC_STALE,
                         "Latest DOCUMENTED interview is stale and no override passed")

    if decision == "SUBSTANTIATED":
        # demand-required gate (priority 11)
        if not restitution_waived:
            has_demand = any(
                d["case_id"] == case_id and d["status"] in
                ("DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID_IN_FULL")
                for d in db.civil_demands.values())
            if not has_demand:
                raise err409(ERR_DEMAND_REQUIRED,
                             "A civil demand in DRAFT/ISSUED/PARTIALLY_PAID/"
                             "PAID_IN_FULL is required unless restitution waived")
        now_iso = fmt_iso(clock_now())
        # find the target period FIRST so a missing period fails atomically
        _post_loss_to_period(case)
        case["adjudicated_at"] = now_iso
        case["adjudicated_by"] = user_id
        case["closed_at"] = now_iso
        case["status"] = "CLOSED_SUBSTANTIATED"
        if case["subject_type"] == "EMPLOYEE" and case.get("employee_id"):
            emp = db.employees[case["employee_id"]]
            emp["prior_substantiated_count"] += 1
            if employment_action == "TERMINATE":
                emp["status"] = "TERMINATED"
            elif employment_action == "SUSPEND":
                emp["status"] = "SUSPENDED"
            touch(emp)
        if restitution_waived:
            case["restitution_status"] = "NONE"
        else:
            recompute_case_restitution_status(case)
            if case["restitution_status"] == "NONE":
                case["restitution_status"] = "OUTSTANDING"
        touch(case)
        refresh_case_hold_retention(case)
        return success_object(pub(case))
    else:
        now_iso = fmt_iso(clock_now())
        case["adjudicated_at"] = now_iso
        case["adjudicated_by"] = user_id
        case["closed_at"] = now_iso
        case["status"] = "CLOSED_UNSUBSTANTIATED"
        _cancel_draft_demands(case_id)
        touch(case)
        refresh_case_hold_retention(case)
        return success_object(pub(case))


@bp.route("/cases/<case_id>/reopen", methods=["POST"])
def reopen_case(case_id):
    user_id, role = get_auth()
    require_role(role, {"LPManager"})
    data = body()
    req_string(data, "reason")
    case = get_or_404(db.cases, case_id, "case")
    if case["status"] not in ("CLOSED_SUBSTANTIATED", "CLOSED_UNSUBSTANTIATED"):
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Case must be CLOSED_SUBSTANTIATED or CLOSED_UNSUBSTANTIATED")
    now = clock_now()
    if case.get("closed_at") is not None:
        if now > parse_iso(case["closed_at"]) + timedelta(days=30):
            raise err409(ERR_REOPEN_WINDOW_CLOSED,
                         "Reopen window (closed_at + 30 days) has passed")
    if case.get("loss_posted_period_id"):
        period = db.shrink_periods.get(case["loss_posted_period_id"])
        if period is not None and period["status"] not in ("OPEN", "COUNTED"):
            raise err409(ERR_PERIOD_LOCKED,
                         "Loss-posted period is no longer OPEN or COUNTED")
    # no POSTED payment on any demand of the case
    for d in db.civil_demands.values():
        if d["case_id"] != case_id:
            continue
        for p in db.restitution_payments.values():
            if p["demand_id"] == d["id"] and p["status"] == "POSTED":
                raise err409(ERR_CASE_HAS_PAYMENTS,
                             "A demand of the case has a POSTED payment")

    was_substantiated = case["status"] == "CLOSED_SUBSTANTIATED"
    if was_substantiated:
        _reverse_loss_posting(case)
        if case["subject_type"] == "EMPLOYEE" and case.get("employee_id"):
            emp = db.employees.get(case["employee_id"])
            if emp is not None:
                emp["prior_substantiated_count"] -= 1
                touch(emp)
    _cancel_draft_demands(case_id)
    case["status"] = "INVESTIGATING"
    case["closed_at"] = None
    recompute_case_restitution_status(case)
    touch(case)
    refresh_case_hold_retention(case)
    return success_object(pub(case))


@bp.route("/cases/<case_id>/merge", methods=["POST"])
def merge_case(case_id):
    user_id, role = get_auth()
    require_role(role, {"LPManager"})
    data = body()
    target_case_id = req_string(data, "target_case_id")
    source = get_or_404(db.cases, case_id, "case")
    # target existence is a body-FK existence check (priority 5)
    target = db.cases.get(target_case_id)
    if target is None:
        raise err404("case %s not found" % target_case_id)

    if source["status"] not in ("INVESTIGATING", "READY_FOR_INTERVIEW"):
        raise err409(ERR_MERGE_NOT_ALLOWED,
                     "Source case must be INVESTIGATING or READY_FOR_INTERVIEW")
    if (target_case_id == case_id or target["status"] in TERMINAL_CASE_STATES
            or target["status"] in CLOSED_STATES):
        raise err409(ERR_MERGE_NOT_ALLOWED,
                     "Target must differ from source and be non-terminal, not MERGED")

    # alerts re-pointed
    for a in db.alerts.values():
        if a.get("case_id") == case_id:
            a["case_id"] = target["id"]
            touch(a)
    # evidence re-parented
    for e in db.evidence_items.values():
        if e["case_id"] == case_id:
            e["case_id"] = target["id"]
            touch(e)
    # SCHEDULED interviews cancelled
    for i in db.interviews.values():
        if i["case_id"] == case_id and i["status"] == "SCHEDULED":
            i["status"] = "CANCELLED"
            touch(i)
    # DRAFT demands cancelled
    _cancel_draft_demands(case_id)
    # fold manual/recovered into target
    target["manual_loss_cents"] += source["manual_loss_cents"]
    target["recovered_value_cents"] += source["recovered_value_cents"]
    recompute_case_total_loss(target)
    recompute_case_priority(target)
    touch(target)

    source["merged_into_case_id"] = target["id"]
    source["status"] = "MERGED"
    touch(source)

    # ORC de-escalation may apply on groups linked to the source case
    affected_groups = {l["orc_group_id"] for l in db.case_links.values()
                       if l["case_id"] == case_id and l["status"] == "CONFIRMED"}
    for gid in affected_groups:
        group = db.orc_groups.get(gid)
        if group is None:
            continue
        recompute_group_counters(group)
        evaluate_group_escalation(group)
        touch(group)

    return success_object(pub(source))


@bp.route("/cases/<case_id>/resolve-subject", methods=["POST"])
def resolve_subject(case_id):
    user_id, role = get_auth()
    require_role(role, {"LPManager"})
    data = body()
    subject_type = req_enum(data, "subject_type",
                            ["EMPLOYEE", "EXTERNAL", "UNKNOWN"])
    employee_id = opt_string(data, "employee_id")
    case = get_or_404(db.cases, case_id, "case")
    if employee_id is not None:
        get_or_404(db.employees, employee_id, "employee")
    if case["status"] not in ("INVESTIGATING", "READY_FOR_INTERVIEW"):
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "resolve-subject requires INVESTIGATING or READY_FOR_INTERVIEW")
    _check_subject_consistency(subject_type, employee_id)
    case["subject_type"] = subject_type
    case["employee_id"] = employee_id
    touch(case)
    return success_object(pub(case))


@bp.route("/cases/<case_id>/close-referred", methods=["POST"])
def close_referred(case_id):
    user_id, role = get_auth()
    require_role(role, {"LPManager"})
    case = get_or_404(db.cases, case_id, "case")
    if case["status"] != "CLOSED_SUBSTANTIATED":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Case must be CLOSED_SUBSTANTIATED to close as referred")
    has_ack = any(p["case_id"] == case_id and p["status"] == "ACKNOWLEDGED"
                  for p in db.referral_packets.values())
    if not has_ack:
        raise err409(ERR_CASE_NOT_REFERRABLE,
                     "An ACKNOWLEDGED referral packet is required")
    case["status"] = "CLOSED_REFERRED"
    touch(case)
    refresh_case_hold_retention(case)
    return success_object(pub(case))


def _q(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None
