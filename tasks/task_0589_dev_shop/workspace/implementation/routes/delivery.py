"""Milestones, sprints, tickets and time entries — PRD §3.2, §3.3, §3.4."""
from decimal import Decimal

from flask import Blueprint, g, request

from core import (ZERO, auth, clock, created, err, fk, get_body, invalid, must_get,
                  new_entity, ok, ok_list, pagination, paginate, req_date, req_enum,
                  req_int, req_number, req_str, opt_bool, opt_str, r2, store, touch)
import services as S

bp = Blueprint("delivery", __name__)

SPRINT_STATUSES = {"PLANNED", "ACTIVE", "CLOSED"}
TICKET_STATUSES = {"TODO", "IN_PROGRESS", "IN_QA", "REWORK", "DONE", "CANCELLED"}


# --------------------------------------------------------------------------
# Milestones
# --------------------------------------------------------------------------
@bp.post("/milestones")
def create_milestone():
    auth("DeliveryLead")
    b = get_body()
    eng = fk(b, "engagement_id", "engagement")
    if eng is None:
        invalid("engagement_id is required.")
    sequence = req_int(b, "sequence", minimum=1)
    title = req_str(b, "title")
    amount = req_number(b, "amount", positive=True, max_dp=2)
    due_date = req_date(b, "due_date")
    siblings = [m for m in store.milestones.values() if m["engagement_id"] == eng["id"]]
    if any(m["sequence"] == sequence for m in siblings):
        invalid("sequence must be unique within the engagement.")
    if eng["status"] != "ACTIVE":
        err("ERR_ENGAGEMENT_NOT_ACTIVE", "The engagement is not ACTIVE.")
    existing_total = ZERO
    for m in siblings:
        existing_total += m["amount"]
    if existing_total + r2(amount) > eng["contract_value"]:
        err("ERR_MILESTONE_AMOUNT_EXCEEDS_CONTRACT",
            "Milestone amounts would exceed the engagement's contract value.")
    row = new_entity({
        "engagement_id": eng["id"], "sequence": sequence, "title": title,
        "amount": r2(amount), "due_date": due_date, "status": "PLANNED",
        "accepted_at": None,
    })
    store.milestones[row["id"]] = row
    return created(S.ser_milestone(row))


@bp.get("/milestones/<mid>")
def get_milestone(mid):
    auth()
    return ok(S.ser_milestone(must_get("milestone", mid)))


@bp.get("/milestones")
def list_milestones():
    auth()
    limit, offset = pagination()
    rows = list(store.milestones.values())
    eid = request.args.get("engagement_id")
    status = request.args.get("status")
    if eid:
        rows = [m for m in rows if m["engagement_id"] == eid]
    if status:
        rows = [m for m in rows if m["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([S.ser_milestone(m) for m in page], limit, offset, total)


# --------------------------------------------------------------------------
# Sprints
# --------------------------------------------------------------------------
@bp.post("/sprints")
def create_sprint():
    auth("DeliveryLead")
    b = get_body()
    eng = fk(b, "engagement_id", "engagement")
    if eng is None:
        invalid("engagement_id is required.")
    milestone = fk(b, "milestone_id", "milestone", required=False)
    req_str(b, "name")
    start = req_date(b, "start_date")
    end = req_date(b, "end_date")
    if eng["status"] != "ACTIVE":
        err("ERR_ENGAGEMENT_NOT_ACTIVE", "The engagement is not ACTIVE.")
    if milestone is not None and milestone["engagement_id"] != eng["id"]:
        err("ERR_MILESTONE_ENGAGEMENT_MISMATCH",
            "The milestone belongs to a different engagement.")
    # Half-open [start, end): overlap iff new.start < old.end AND old.start < new.end
    for s in S.sprints_of_engagement(eng["id"]):
        if s["status"] not in ("PLANNED", "ACTIVE"):
            continue
        if start < s["end_date"] and s["start_date"] < end:
            err("ERR_SPRINT_OVERLAP", "The sprint window overlaps an existing sprint.")
    row = new_entity({
        "engagement_id": eng["id"],
        "milestone_id": milestone["id"] if milestone else None,
        "name": b["name"], "start_date": start, "end_date": end,
        "status": "PLANNED", "spend_frozen": False,
        "committed_hours": Decimal("0.00"),
    })
    store.sprints[row["id"]] = row
    return created(S.ser_sprint(row))


@bp.get("/sprints/<sid>")
def get_sprint(sid):
    auth()
    return ok(S.ser_sprint(must_get("sprint", sid)))


@bp.get("/sprints")
def list_sprints():
    auth()
    limit, offset = pagination()
    rows = list(store.sprints.values())
    for key in ("engagement_id", "milestone_id", "status"):
        val = request.args.get(key)
        if val:
            rows = [s for s in rows if s[key] == val]
    page, total = paginate(rows, limit, offset)
    return ok_list([S.ser_sprint(s) for s in page], limit, offset, total)


@bp.post("/sprints/<sid>/transition")
def transition_sprint(sid):
    auth("DeliveryLead")
    s = must_get("sprint", sid)
    b = get_body()
    target = req_enum(b, "target_status", SPRINT_STATUSES)
    eng = store.engagements[s["engagement_id"]]
    if eng["status"] != "ACTIVE":
        err("ERR_ENGAGEMENT_NOT_ACTIVE", "The engagement is not ACTIVE.")
    if target == "ACTIVE" and s["status"] == "PLANNED":
        s["status"] = "ACTIVE"
        s["spend_frozen"] = eng["budget_posture"] != "HEALTHY"
        touch(s)
    elif target == "CLOSED" and s["status"] == "ACTIVE":
        s["status"] = "CLOSED"
        touch(s)
        for t in S.tickets_of_sprint(s["id"]):
            if t["status"] == "TODO":
                t["status"] = "CANCELLED"
                touch(t)
        S.recompute_committed_hours(s)
    else:
        err("ERR_INVALID_TRANSITION", "Illegal sprint transition.")
    return ok(S.ser_sprint(s))


# --------------------------------------------------------------------------
# Tickets
# --------------------------------------------------------------------------
@bp.post("/tickets")
def create_ticket():
    auth("DeliveryLead")
    b = get_body()
    sprint = fk(b, "sprint_id", "sprint")
    if sprint is None:
        invalid("sprint_id is required.")
    blocker = fk(b, "blocking_ticket_id", "ticket", required=False)
    title = req_str(b, "title")
    estimated = req_number(b, "estimated_hours", positive=True)
    assignee = req_str(b, "assignee_user_id")
    if sprint["status"] == "CLOSED":
        err("ERR_SPRINT_NOT_ACTIVE", "A CLOSED sprint cannot accept new tickets.")
    row = new_entity({
        "sprint_id": sprint["id"],
        "blocking_ticket_id": blocker["id"] if blocker else None,
        "title": title, "estimated_hours": r2(estimated),
        "assignee_user_id": assignee, "status": "TODO",
        "actual_hours": Decimal("0.00"), "variance_ratio": Decimal("0.0000"),
        "rework_rounds": 0,
    })
    if blocker is not None and S.would_create_cycle(row["id"], blocker["id"]):
        err("ERR_TICKET_CYCLE", "The blocker would create a cycle.")
    store.tickets[row["id"]] = row
    S.recompute_committed_hours(sprint)
    return created(S.ser_ticket(row))


@bp.get("/tickets/<tid>")
def get_ticket(tid):
    auth()
    return ok(S.ser_ticket(must_get("ticket", tid)))


@bp.get("/tickets")
def list_tickets():
    auth()
    limit, offset = pagination()
    rows = list(store.tickets.values())
    for key in ("sprint_id", "assignee_user_id", "blocking_ticket_id", "status"):
        val = request.args.get(key)
        if val:
            rows = [t for t in rows if t[key] == val]
    page, total = paginate(rows, limit, offset)
    return ok_list([S.ser_ticket(t) for t in page], limit, offset, total)


@bp.post("/tickets/<tid>/block")
def block_ticket(tid):
    auth("DeliveryLead")
    t = must_get("ticket", tid)
    b = get_body()
    blocker = fk(b, "blocking_ticket_id", "ticket")
    if blocker is None:
        invalid("blocking_ticket_id is required.")
    if S.would_create_cycle(t["id"], blocker["id"]):
        err("ERR_TICKET_CYCLE", "The blocker would create a cycle.")
    t["blocking_ticket_id"] = blocker["id"]
    touch(t)
    return ok(S.ser_ticket(t))


@bp.post("/tickets/<tid>/transition")
def transition_ticket(tid):
    auth("Engineer", "DeliveryLead")
    t = must_get("ticket", tid)
    b = get_body()
    target = req_enum(b, "target_status", TICKET_STATUSES)
    opt_str(b, "note")
    sprint = S.sprint_of_ticket(t)

    # Cancellation is a delivery-lead-only move (PRD 3.3).
    if target == "CANCELLED" and g.role != "DeliveryLead":
        err("ERR_FORBIDDEN_ROLE", "Only a DeliveryLead may cancel a ticket.")

    # Every transition other than the two cancellations requires an ACTIVE sprint.
    if target != "CANCELLED" and sprint["status"] != "ACTIVE":
        err("ERR_SPRINT_NOT_ACTIVE", "The owning sprint is not ACTIVE.")

    cur = t["status"]
    legal = (
        (cur == "TODO" and target == "IN_PROGRESS")
        or (cur == "IN_PROGRESS" and target == "IN_QA")
        or (cur == "IN_QA" and target == "REWORK")
        or (cur == "REWORK" and target == "IN_PROGRESS")
        or (cur == "IN_QA" and target == "DONE")
        or (cur == "TODO" and target == "CANCELLED")
        or (cur == "IN_PROGRESS" and target == "CANCELLED")
    )
    if not legal:
        err("ERR_INVALID_TRANSITION", "Illegal ticket transition %s -> %s." % (cur, target))

    # Segregation of duties outranks the spend / flow rules (PRD 2.5, 2.10).
    if cur == "IN_QA" and target == "DONE" and g.user_id == t["assignee_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", "The assignee may not sign off their own ticket.")

    if target == "IN_PROGRESS":
        if sprint["spend_frozen"]:
            err("ERR_SPRINT_SPEND_FROZEN", "The sprint is spend-frozen.")
        if cur == "TODO" and t["blocking_ticket_id"]:
            blocker = store.tickets.get(t["blocking_ticket_id"])
            if blocker is None or blocker["status"] != "DONE":
                err("ERR_TICKET_BLOCKED", "The blocking ticket is not DONE.")

    t["status"] = target
    if target == "REWORK":
        t["rework_rounds"] += 1
    touch(t)
    if target == "DONE":
        S.recompute_ticket(t)
    if target == "CANCELLED":
        S.recompute_committed_hours(sprint)
    return ok(S.ser_ticket(t))


# --------------------------------------------------------------------------
# Time entries
# --------------------------------------------------------------------------
@bp.post("/time-entries")
def create_time_entry():
    auth("Engineer")
    b = get_body()
    ticket = fk(b, "ticket_id", "ticket")
    if ticket is None:
        invalid("ticket_id is required.")
    work_date = req_date(b, "work_date")
    hours = req_number(b, "hours", positive=True, max_dp=2, max_value=Decimal("12"))
    billable = opt_bool(b, "billable", True)
    note = opt_str(b, "note")
    sprint = S.sprint_of_ticket(ticket)
    if sprint["status"] != "ACTIVE":
        err("ERR_SPRINT_NOT_ACTIVE", "Time may only be logged while the sprint is ACTIVE.")
    if g.user_id != ticket["assignee_user_id"]:
        err("ERR_NOT_TICKET_ASSIGNEE", "Only the ticket's assignee may log time against it.")
    if not (sprint["start_date"] <= work_date < sprint["end_date"]):
        err("ERR_WORK_DATE_OUT_OF_SPRINT",
            "work_date is outside the sprint's half-open window.")
    logged = ZERO
    for te in store.time_entries.values():
        if (te["employee_user_id"] == g.user_id
                and te["work_date"] == work_date
                and te["status"] in ("SUBMITTED", "APPROVED")):
            logged += te["hours"]
    if logged + r2(hours) > S.DAILY_HOURS_CAP:
        err("ERR_DAILY_HOURS_EXCEEDED", "Daily hours cap of 12 exceeded for this work_date.")
    row = new_entity({
        "ticket_id": ticket["id"], "employee_user_id": g.user_id,
        "work_date": work_date, "hours": r2(hours), "billable": billable,
        "note": note, "status": "SUBMITTED", "reviewed_by_user_id": None,
    })
    store.time_entries[row["id"]] = row
    return created(S.ser_time_entry(row))


@bp.get("/time-entries/<teid>")
def get_time_entry(teid):
    auth()
    return ok(S.ser_time_entry(must_get("time_entry", teid)))


@bp.get("/time-entries")
def list_time_entries():
    auth()
    limit, offset = pagination()
    rows = list(store.time_entries.values())
    for key in ("ticket_id", "employee_user_id", "status"):
        val = request.args.get(key)
        if val:
            rows = [te for te in rows if te[key] == val]
    page, total = paginate(rows, limit, offset)
    return ok_list([S.ser_time_entry(te) for te in page], limit, offset, total)


@bp.post("/time-entries/<teid>/review")
def review_time_entry(teid):
    auth("DeliveryLead")
    te = must_get("time_entry", teid)
    b = get_body()
    decision = req_enum(b, "decision", {"APPROVE", "REJECT"})
    opt_str(b, "note")
    ticket = store.tickets[te["ticket_id"]]
    sprint = S.sprint_of_ticket(ticket)
    eng = store.engagements[sprint["engagement_id"]]

    if sprint["status"] != "ACTIVE":
        err("ERR_SPRINT_NOT_ACTIVE", "The entry's sprint is not ACTIVE.")
    if te["status"] != "SUBMITTED":
        err("ERR_INVALID_TRANSITION", "Only a SUBMITTED time entry may be reviewed.")
    if g.user_id == te["employee_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", "A reviewer may not review their own time entry.")

    if decision == "REJECT":
        te["status"] = "REJECTED"
        te["reviewed_by_user_id"] = g.user_id
        touch(te)
        return ok(S.ser_time_entry(te))

    # APPROVE — budget cap guard fires before the cascade, billable entries only.
    if te["billable"]:
        cap = eng["budget_hours_cap"]
        if cap is not None and eng["approved_hours"] + te["hours"] > cap:
            err("ERR_BUDGET_HOURS_EXCEEDED",
                "Approving this entry would exceed the engagement's budget hour cap.")

    te["status"] = "APPROVED"                       # LINK 1
    te["reviewed_by_user_id"] = g.user_id
    touch(te)
    S.recompute_ticket(ticket)                      # LINK 2
    S.recompute_burn_ledger(eng)                    # LINKS 3, 4, 5
    touch(eng)
    return ok(S.ser_time_entry(te))


@bp.post("/time-entries/<teid>/reverse")
def reverse_time_entry(teid):
    auth("DeliveryLead")
    te = must_get("time_entry", teid)
    b = get_body()
    req_str(b, "reason")
    if te["status"] != "APPROVED":
        err("ERR_INVALID_TRANSITION", "Only an APPROVED time entry may be reversed.")
    ticket = store.tickets[te["ticket_id"]]
    sprint = S.sprint_of_ticket(ticket)
    eng = store.engagements[sprint["engagement_id"]]
    te["status"] = "REVERSED"
    touch(te)
    S.recompute_ticket(ticket)
    S.recompute_burn_ledger(eng)
    touch(eng)
    return ok(S.ser_time_entry(te))
