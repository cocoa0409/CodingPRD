"""Requisition, Distribution, Submittal, Assignment routes."""
from flask import Blueprint, request

import db
import services
from errors import err
from middleware import (get_user_context, require_role, get_json_body, parse_iso)
from response import success
from serializers import public
from listing import paginate, filter_by
import validators as V

bp = Blueprint("requisitions", __name__)

SUBMITTAL_TERMINAL = {"HIRED", "REJECTED", "WITHDRAWN"}


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ============================= Requisition =================================

@bp.route("/vms/requisitions", methods=["POST"])
def create_requisition():
    _, role = get_user_context()
    require_role(role, ["ProgramManager", "HiringManager"])
    body = get_json_body()
    program_id = V.as_string(V.require_present(body, "program_id"), "program_id")
    program = db.programs.get(program_id)
    if program is None:
        raise err("ERR_NOT_FOUND", "Program not found")
    title = V.as_string(V.require_present(body, "title"), "title")
    openings = V.as_int(V.require_present(body, "openings"), "openings")
    if openings < 1:
        raise err("ERR_INVALID_REQUEST", "openings must be >= 1")
    max_pay = V.as_int(V.require_present(body, "max_pay_rate_cents"), "max_pay_rate_cents")
    if max_pay < 1:
        raise err("ERR_INVALID_REQUEST", "max_pay_rate_cents must be >= 1")
    interval = 24
    if body.get("tier_release_interval_hours") is not None:
        interval = V.as_int(body["tier_release_interval_hours"], "tier_release_interval_hours")
        if interval < 0:
            raise err("ERR_INVALID_REQUEST", "tier_release_interval_hours must be >= 0")

    record = db.common_fields()
    record.update({
        "program_id": program_id,
        "title": title,
        "openings": openings,
        "filled_count": 0,
        "max_pay_rate_cents": max_pay,
        "tier_release_interval_hours": interval,
        "status": "DRAFT",
    })
    db.requisitions[record["id"]] = record
    return success(public(record), 201)


@bp.route("/vms/requisitions/<rid>", methods=["GET"])
def get_requisition(rid):
    get_user_context()
    req = db.requisitions.get(rid)
    if req is None:
        raise err("ERR_NOT_FOUND", "Requisition not found")
    return success(public(req), 200)


@bp.route("/vms/requisitions", methods=["GET"])
def list_requisitions():
    get_user_context()
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    records = filter_by(list(db.requisitions.values()), program_id=program_id, status=status)
    data, pagination = paginate(records)
    return success(data, 200, "array", pagination)


@bp.route("/vms/requisitions/<rid>/distribute", methods=["POST"])
def distribute(rid):
    _, role = get_user_context()
    require_role(role, ["ProgramManager"])
    req = db.requisitions.get(rid)
    if req is None:
        raise err("ERR_NOT_FOUND", "Requisition not found")

    # State precondition (priority 5) before business rules.
    if req["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Requisition is not DRAFT")

    program = db.programs[req["program_id"]]
    if program["status"] != "ACTIVE":
        raise err("ERR_PROGRAM_NOT_ACTIVE", "Program is not ACTIVE")

    body = get_json_body()
    supplier_ids = body.get("supplier_ids")
    if not isinstance(supplier_ids, list) or len(supplier_ids) < 1:
        raise err("ERR_INVALID_REQUEST", "supplier_ids must be a non-empty list")

    # Validate every listed supplier is ACTIVE and in this program.
    chosen = []
    for sid in supplier_ids:
        supplier = db.suppliers.get(sid)
        if supplier is None or supplier["program_id"] != req["program_id"] or supplier["status"] != "ACTIVE":
            raise err("ERR_SUPPLIER_NOT_ELIGIBLE", "Supplier %s is not eligible" % sid)
        chosen.append(supplier)

    # Transition + waterfall.
    req["status"] = "DISTRIBUTED"
    db.touch(req)

    t0_iso = program["current_clock"]
    t0 = parse_iso(t0_iso, "current_clock")
    interval = req["tier_release_interval_hours"]
    distinct_tiers = [s["tier"] for s in chosen]
    offsets = services.compute_release_offsets(distinct_tiers, interval)

    for supplier in chosen:
        tier = supplier["tier"]
        offset_hours = offsets[tier]
        released_at = services.add_hours_iso(t0_iso, offset_hours)
        ra_dt = parse_iso(released_at, "released_at")
        status = "RELEASED" if ra_dt <= t0 else "PENDING"
        dist = db.common_fields()
        dist.update({
            "requisition_id": req["id"],
            "supplier_id": supplier["id"],
            "tier_at_distribution": tier,
            "released_at": released_at,
            "status": status,
        })
        db.distributions[dist["id"]] = dist

    return success(public(req), 200)


@bp.route("/vms/requisitions/<rid>/close", methods=["POST"])
def close_requisition(rid):
    _, role = get_user_context()
    require_role(role, ["ProgramManager"])
    req = db.requisitions.get(rid)
    if req is None:
        raise err("ERR_NOT_FOUND", "Requisition not found")
    if req["status"] != "DISTRIBUTED":
        raise err("ERR_INVALID_STATE", "Only a DISTRIBUTED requisition can be closed")
    req["status"] = "CLOSED"
    db.touch(req)
    services.revoke_and_reject(req)
    return success(public(req), 200)


@bp.route("/vms/requisitions/<rid>/cancel", methods=["POST"])
def cancel_requisition(rid):
    _, role = get_user_context()
    require_role(role, ["ProgramManager"])
    req = db.requisitions.get(rid)
    if req is None:
        raise err("ERR_NOT_FOUND", "Requisition not found")
    if req["status"] not in ("DRAFT", "DISTRIBUTED"):
        raise err("ERR_INVALID_STATE", "Requisition cannot be cancelled from its current state")

    if req["status"] == "DISTRIBUTED":
        for sub in db.submittals.values():
            if sub["requisition_id"] == req["id"] and sub["status"] == "HIRED":
                raise err("ERR_REQUISITION_HAS_HIRES",
                          "Cannot cancel a requisition that has hired submittals")
        req["status"] = "CANCELLED"
        db.touch(req)
        services.revoke_and_reject(req)
    else:  # DRAFT
        req["status"] = "CANCELLED"
        db.touch(req)
    return success(public(req), 200)


# ============================= Distribution ================================

@bp.route("/vms/distributions/<did>", methods=["GET"])
def get_distribution(did):
    get_user_context()
    dist = db.distributions.get(did)
    if dist is None:
        raise err("ERR_NOT_FOUND", "Distribution not found")
    return success(public(dist), 200)


@bp.route("/vms/distributions", methods=["GET"])
def list_distributions():
    get_user_context()
    requisition_id = request.args.get("requisition_id")
    supplier_id = request.args.get("supplier_id")
    status = request.args.get("status")
    records = filter_by(list(db.distributions.values()),
                        requisition_id=requisition_id, supplier_id=supplier_id, status=status)
    data, pagination = paginate(records)
    return success(data, 200, "array", pagination)


# ============================= Submittal ===================================

@bp.route("/vms/submittals", methods=["POST"])
def create_submittal():
    user_id, role = get_user_context()
    require_role(role, ["Supplier"])
    body = get_json_body()
    requisition_id = V.as_string(V.require_present(body, "requisition_id"), "requisition_id")
    supplier_id = V.as_string(V.require_present(body, "supplier_id"), "supplier_id")
    worker_profile_id = V.as_string(V.require_present(body, "worker_profile_id"), "worker_profile_id")

    # Existence, left to right.
    req = db.requisitions.get(requisition_id)
    if req is None:
        raise err("ERR_NOT_FOUND", "Requisition not found")
    supplier = db.suppliers.get(supplier_id)
    if supplier is None:
        raise err("ERR_NOT_FOUND", "Supplier not found")
    worker = db.workers.get(worker_profile_id)
    if worker is None:
        raise err("ERR_NOT_FOUND", "Worker not found")

    # Ownership: acting supplier must be the supplier on the submittal.
    if user_id != supplier_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Supplier does not own this submittal")

    program = db.programs[req["program_id"]]

    # Supplier eligibility (must be ACTIVE; SUSPENDED cannot create submittals).
    if supplier["status"] != "ACTIVE":
        raise err("ERR_SUPPLIER_NOT_ELIGIBLE", "Supplier is not ACTIVE")

    pay_rate = V.as_int(V.require_present(body, "pay_rate_cents"), "pay_rate_cents")
    if pay_rate < 1:
        raise err("ERR_INVALID_REQUEST", "pay_rate_cents must be >= 1")
    bill_rate = None
    if body.get("bill_rate_cents") is not None:
        bill_rate = V.as_int(body["bill_rate_cents"], "bill_rate_cents")
        if bill_rate < 1:
            raise err("ERR_INVALID_REQUEST", "bill_rate_cents must be >= 1")

    # Distribution must be RELEASED for this supplier+requisition (temporal, priority 6).
    clock = parse_iso(program["current_clock"], "current_clock")
    released = False
    for dist in db.distributions.values():
        if (dist["requisition_id"] == requisition_id and dist["supplier_id"] == supplier_id
                and dist["status"] == "RELEASED"):
            released = True
            break
    if not released:
        raise err("ERR_DISTRIBUTION_NOT_RELEASED",
                  "Supplier's distribution for this requisition is not RELEASED")

    # Duplicate submittal: same worker non-terminal on this req from this supplier.
    for sub in db.submittals.values():
        if (sub["requisition_id"] == requisition_id and sub["supplier_id"] == supplier_id
                and sub["worker_profile_id"] == worker_profile_id
                and sub["status"] not in SUBMITTAL_TERMINAL):
            raise err("ERR_DUPLICATE_SUBMITTAL",
                      "Worker already has a live submittal on this requisition from this supplier")

    # Pay-rate ceiling (priority 11).
    if pay_rate > req["max_pay_rate_cents"]:
        raise err("ERR_PAY_RATE_EXCEEDS_MAX", "pay_rate_cents exceeds requisition max")

    # Bill-rate derivation + markup (priority 12).
    bill, effective = services.derive_bill_and_markup(program, pay_rate, bill_rate)
    if effective > services.Decimal(str(program["max_markup_pct"])):
        raise err("ERR_MARKUP_EXCEEDS_MAX", "effective markup exceeds program max")

    record = db.common_fields()
    record.update({
        "requisition_id": requisition_id,
        "supplier_id": supplier_id,
        "worker_profile_id": worker_profile_id,
        "pay_rate_cents": pay_rate,
        "bill_rate_cents": bill,
        "effective_markup_pct": services.markup_as_number(effective),
        "rounds": 0,
        "status": "SUBMITTED",
    })
    db.submittals[record["id"]] = record
    return success(public(record), 201)


@bp.route("/vms/submittals/<sid>", methods=["GET"])
def get_submittal(sid):
    get_user_context()
    sub = db.submittals.get(sid)
    if sub is None:
        raise err("ERR_NOT_FOUND", "Submittal not found")
    return success(public(sub), 200)


@bp.route("/vms/submittals", methods=["GET"])
def list_submittals():
    get_user_context()
    records = filter_by(
        list(db.submittals.values()),
        requisition_id=request.args.get("requisition_id"),
        supplier_id=request.args.get("supplier_id"),
        worker_profile_id=request.args.get("worker_profile_id"),
        status=request.args.get("status"),
    )
    data, pagination = paginate(records)
    return success(data, 200, "array", pagination)


def _load_submittal(sid):
    sub = db.submittals.get(sid)
    if sub is None:
        raise err("ERR_NOT_FOUND", "Submittal not found")
    return sub


def _check_supplier_owns_submittal(user_id, role, sub):
    if role == "Supplier" and user_id != sub["supplier_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Supplier does not own this submittal")


@bp.route("/vms/submittals/<sid>/shortlist", methods=["POST"])
def shortlist(sid):
    _, role = get_user_context()
    require_role(role, ["HiringManager"])
    sub = _load_submittal(sid)
    if sub["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Submittal is not SUBMITTED")
    req = db.requisitions[sub["requisition_id"]]
    if req["status"] != "DISTRIBUTED":
        raise err("ERR_INVALID_STATE", "Requisition is not DISTRIBUTED")
    sub["status"] = "SHORTLISTED"
    db.touch(sub)
    return success(public(sub), 200)


@bp.route("/vms/submittals/<sid>/start_interview", methods=["POST"])
def start_interview(sid):
    _, role = get_user_context()
    require_role(role, ["HiringManager"])
    sub = _load_submittal(sid)
    if sub["status"] != "SHORTLISTED":
        raise err("ERR_INVALID_STATE", "Submittal is not SHORTLISTED")
    sub["status"] = "INTERVIEWING"
    db.touch(sub)
    return success(public(sub), 200)


@bp.route("/vms/submittals/<sid>/propose_rate", methods=["POST"])
def propose_rate(sid):
    user_id, role = get_user_context()
    require_role(role, ["Supplier"])
    sub = _load_submittal(sid)
    _check_supplier_owns_submittal(user_id, role, sub)
    if sub["status"] != "INTERVIEWING":
        raise err("ERR_INVALID_STATE", "Submittal is not INTERVIEWING")

    body = get_json_body()
    pay_rate = V.as_int(V.require_present(body, "pay_rate_cents"), "pay_rate_cents")
    if pay_rate < 1:
        raise err("ERR_INVALID_REQUEST", "pay_rate_cents must be >= 1")
    bill_rate = None
    if body.get("bill_rate_cents") is not None:
        bill_rate = V.as_int(body["bill_rate_cents"], "bill_rate_cents")
        if bill_rate < 1:
            raise err("ERR_INVALID_REQUEST", "bill_rate_cents must be >= 1")

    req = db.requisitions[sub["requisition_id"]]
    program = db.programs[req["program_id"]]

    if pay_rate > req["max_pay_rate_cents"]:
        raise err("ERR_PAY_RATE_EXCEEDS_MAX", "pay_rate_cents exceeds requisition max")
    bill, effective = services.derive_bill_and_markup(program, pay_rate, bill_rate)
    if effective > services.Decimal(str(program["max_markup_pct"])):
        raise err("ERR_MARKUP_EXCEEDS_MAX", "effective markup exceeds program max")

    sub["pay_rate_cents"] = pay_rate
    sub["bill_rate_cents"] = bill
    sub["effective_markup_pct"] = services.markup_as_number(effective)
    sub["status"] = "RATE_PROPOSED"
    db.touch(sub)
    return success(public(sub), 200)


@bp.route("/vms/submittals/<sid>/counter_rate", methods=["POST"])
def counter_rate(sid):
    _, role = get_user_context()
    require_role(role, ["HiringManager"])
    sub = _load_submittal(sid)
    if sub["status"] != "RATE_PROPOSED":
        raise err("ERR_INVALID_STATE", "Submittal is not RATE_PROPOSED")
    if sub["rounds"] >= 5:
        raise err("ERR_NEGOTIATION_ROUNDS_EXCEEDED", "Negotiation rounds cap reached")
    sub["rounds"] += 1
    sub["status"] = "INTERVIEWING"
    db.touch(sub)
    return success(public(sub), 200)


@bp.route("/vms/submittals/<sid>/offer", methods=["POST"])
def offer(sid):
    _, role = get_user_context()
    require_role(role, ["HiringManager"])
    sub = _load_submittal(sid)
    if sub["status"] != "RATE_PROPOSED":
        raise err("ERR_INVALID_STATE", "Submittal is not RATE_PROPOSED")
    req = db.requisitions[sub["requisition_id"]]
    if req["filled_count"] >= req["openings"]:
        raise err("ERR_REQUISITION_FULL", "Requisition has no remaining openings")
    sub["status"] = "OFFERED"
    db.touch(sub)
    return success(public(sub), 200)


@bp.route("/vms/submittals/<sid>/hire", methods=["POST"])
def hire(sid):
    _, role = get_user_context()
    require_role(role, ["ProgramManager"])
    sub = _load_submittal(sid)
    if sub["status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", "Submittal is not OFFERED")

    body = get_json_body()
    if "expected_requisition_version" not in body or body["expected_requisition_version"] is None:
        raise err("ERR_INVALID_REQUEST", "expected_requisition_version is required")
    expected_version = V.as_int(body["expected_requisition_version"], "expected_requisition_version")
    start_raw = V.as_string(V.require_present(body, "start_date"), "start_date")
    end_raw = V.as_string(V.require_present(body, "planned_end_date"), "planned_end_date")
    start_dt = parse_iso(start_raw, "start_date")
    end_dt = parse_iso(end_raw, "planned_end_date")

    req = db.requisitions[sub["requisition_id"]]

    # 1) OCC (priority for hire-race; PRD §2.7 -> 412).
    if expected_version != req["version"]:
        raise err("ERR_STALE_VERSION", "expected_requisition_version is stale")

    # 2) Tenure breach safety (priority 7).
    worker = db.workers[sub["worker_profile_id"]]
    if worker["tenure_status"] == "BREACH":
        raise err("ERR_TENURE_LIMIT_REACHED", "Worker is in tenure breach")

    # 3) Remaining openings (priority 10).
    if req["filled_count"] >= req["openings"]:
        raise err("ERR_REQUISITION_FULL", "Requisition has no remaining openings")

    # 4) Double-booking: closed-interval overlap with any non-ENDED assignment of same worker.
    for a in db.assignments.values():
        if a["worker_profile_id"] != worker["id"]:
            continue
        if a["engagement_status"] == "ENDED":
            continue
        a_start = parse_iso(a["start_date"], "start_date")
        a_end = parse_iso(a["planned_end_date"], "planned_end_date")
        # Closed-interval overlap: start <= a_end AND a_start <= end.
        if start_dt <= a_end and a_start <= end_dt:
            raise err("ERR_WORKER_DOUBLE_BOOKED",
                      "Engagement window overlaps an existing assignment for this worker")

    program = db.programs[req["program_id"]]

    # Create the assignment.
    asg = db.common_fields()
    asg.update({
        "program_id": req["program_id"],
        "submittal_id": sub["id"],
        "worker_profile_id": worker["id"],
        "pay_rate_cents": sub["pay_rate_cents"],
        "bill_rate_cents": sub["bill_rate_cents"],
        "start_date": _iso(start_dt),
        "planned_end_date": _iso(end_dt),
        "actual_end_date": None,
        "engaged_days": services.compute_engaged_days(
            {"start_date": _iso(start_dt), "planned_end_date": _iso(end_dt),
             "engagement_status": "ACTIVE", "actual_end_date": None}, program),
        "engagement_status": "ACTIVE",
        "compliance_status": _seed_compliance(worker["tenure_status"]),
    })
    db.assignments[asg["id"]] = asg

    # Submittal -> HIRED.
    sub["status"] = "HIRED"
    db.touch(sub)

    # Requisition bookkeeping. PRD §3.5: the hire increments filled_count by one
    # and the requisition's version by one. The DISTRIBUTED -> FILLED transition,
    # when the seat count is reached, is part of this same single hire mutation
    # (one version bump), not a separate secondary touch on the requisition.
    req["filled_count"] += 1
    if req["filled_count"] >= req["openings"]:
        req["status"] = "FILLED"
    db.touch(req)  # the single hire version bump (covers filled_count + FILLED)
    if req["status"] == "FILLED":
        services.fill_cascade(req)

    return success(public(sub), 200)


def _seed_compliance(tenure_status):
    return {
        "CLEAR": "CLEAR",
        "WARNING": "TENURE_WARNING",
        "BREACH": "TENURE_BREACH",
    }.get(tenure_status, "CLEAR")


@bp.route("/vms/submittals/<sid>/reject", methods=["POST"])
def reject_submittal(sid):
    _, role = get_user_context()
    require_role(role, ["HiringManager"])
    sub = _load_submittal(sid)
    if sub["status"] not in ("SUBMITTED", "SHORTLISTED", "INTERVIEWING", "RATE_PROPOSED"):
        raise err("ERR_INVALID_STATE", "Submittal cannot be rejected from its current state")
    sub["status"] = "REJECTED"
    db.touch(sub)
    return success(public(sub), 200)


@bp.route("/vms/submittals/<sid>/withdraw", methods=["POST"])
def withdraw_submittal(sid):
    user_id, role = get_user_context()
    require_role(role, ["Supplier"])
    sub = _load_submittal(sid)
    _check_supplier_owns_submittal(user_id, role, sub)
    if sub["status"] not in ("SUBMITTED", "SHORTLISTED", "INTERVIEWING", "RATE_PROPOSED"):
        raise err("ERR_INVALID_STATE", "Submittal cannot be withdrawn from its current state")
    sub["status"] = "WITHDRAWN"
    db.touch(sub)
    return success(public(sub), 200)


# ============================= Assignment ==================================

def _assignment_view(asg):
    """Return public view; engaged_days for non-ENDED reflects current clock."""
    out = public(asg)
    if asg["engagement_status"] != "ENDED":
        program = db.programs.get(asg["program_id"])
        if program is not None:
            out["engaged_days"] = services.compute_engaged_days(asg, program)
    return out


@bp.route("/vms/assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    get_user_context()
    asg = db.assignments.get(aid)
    if asg is None:
        raise err("ERR_NOT_FOUND", "Assignment not found")
    return success(_assignment_view(asg), 200)


@bp.route("/vms/assignments", methods=["GET"])
def list_assignments():
    get_user_context()
    records = filter_by(
        list(db.assignments.values()),
        program_id=request.args.get("program_id"),
        submittal_id=request.args.get("submittal_id"),
        worker_profile_id=request.args.get("worker_profile_id"),
        engagement_status=request.args.get("engagement_status"),
        compliance_status=request.args.get("compliance_status"),
    )
    limit_off = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    from listing import _parse_pagination
    limit, offset = _parse_pagination()
    total = len(limit_off)
    window = limit_off[offset:offset + limit]
    data = [_assignment_view(r) for r in window]
    pagination = {"limit": limit, "offset": offset, "total_count": total,
                  "has_more": offset + limit < total}
    return success(data, 200, "array", pagination)


def _load_assignment(aid):
    asg = db.assignments.get(aid)
    if asg is None:
        raise err("ERR_NOT_FOUND", "Assignment not found")
    return asg


@bp.route("/vms/assignments/<aid>/hold", methods=["POST"])
def hold_assignment(aid):
    _, role = get_user_context()
    require_role(role, ["ProgramManager"])
    asg = _load_assignment(aid)
    if asg["engagement_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Assignment is not ACTIVE")
    asg["engagement_status"] = "ON_HOLD"
    db.touch(asg)
    return success(_assignment_view(asg), 200)


@bp.route("/vms/assignments/<aid>/resume", methods=["POST"])
def resume_assignment(aid):
    _, role = get_user_context()
    require_role(role, ["ProgramManager"])
    asg = _load_assignment(aid)
    if asg["engagement_status"] != "ON_HOLD":
        raise err("ERR_INVALID_STATE", "Assignment is not ON_HOLD")
    if asg["compliance_status"] == "TENURE_BREACH":
        raise err("ERR_TENURE_LIMIT_REACHED", "Cannot resume a tenure-breached worker")
    asg["engagement_status"] = "ACTIVE"
    db.touch(asg)
    return success(_assignment_view(asg), 200)


@bp.route("/vms/assignments/<aid>/offboard", methods=["POST"])
def offboard_assignment(aid):
    _, role = get_user_context()
    require_role(role, ["ProgramManager"])
    asg = _load_assignment(aid)
    if asg["engagement_status"] not in ("ACTIVE", "ON_HOLD"):
        raise err("ERR_INVALID_STATE", "Assignment is already ENDED")

    # Blocked while any SUBMITTED timesheet or expense remains (priority 14).
    for ts in db.timesheets.values():
        if ts["assignment_id"] == aid and ts["status"] == "SUBMITTED":
            raise err("ERR_OPEN_APPROVALS_PENDING", "Open timesheet approvals pending")
    for ex in db.expenses.values():
        if ex["assignment_id"] == aid and ex["status"] == "SUBMITTED":
            raise err("ERR_OPEN_APPROVALS_PENDING", "Open expense approvals pending")

    program = db.programs[asg["program_id"]]
    clock_dt = parse_iso(program["current_clock"], "current_clock")
    asg["engagement_status"] = "ENDED"
    asg["actual_end_date"] = _iso(clock_dt)
    # Freeze engaged_days at the inclusive count.
    asg["engaged_days"] = services.compute_engaged_days(asg, program)
    db.touch(asg)

    services.offboard_rollup(asg, program)
    return success(_assignment_view(asg), 200)
