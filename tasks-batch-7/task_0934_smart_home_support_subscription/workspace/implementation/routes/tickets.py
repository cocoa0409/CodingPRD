"""The support ticket, its three independent axes, the SLA clock and the
satisfaction survey (PRD 3.5, 3.6 and 3.12)."""

from flask import Blueprint, request

import sla
import serializers as S
from counters import household_of_ticket
from envelope import created, ok, ok_list, paginate, read_pagination
from errors import ApiError
from ladder import (begin, filter_enum, gates, in_force_subscription, invalid_state,
                    opt_str, plan_of, req_enum, req_id, req_int, req_str,
                    require_subscription, resolve, scope_household, touch)
from money import (CSAT_BREACH_COMPOUNDED_CREDIT_PCT, CSAT_GOODWILL_CREDIT_PCT,
                   CSAT_LOW_SCORE_MAX, CSAT_SURVEY_WINDOW_HOURS,
                   TICKET_REOPEN_WINDOW_HOURS, as_decimal, round_half_up)
from store import clock, db, new_row, sort_rows
from timeutil import add_hours, render_instant, try_parse_instant

bp = Blueprint("tickets", __name__)
PREFIX = "/smart-home-support"

TICKET_READ_ROLES = ("PlatformAdmin", "SupportAgent", "Owner", "Member", "BillingAdmin")


def _ticket_context(ctx, tid, skip_ticket_gate=False):
    found = resolve(ticket=tid)
    ticket = found["ticket"]
    household = household_of_ticket(ticket)
    scope_household(ctx, ticket.get("household_id"))
    return ticket, household


# --------------------------------------------------------------------------
# Creation and reads
# --------------------------------------------------------------------------
@bp.post(PREFIX + "/tickets")
def create_ticket():
    ctx = begin(("Owner", "Member", "SupportAgent"))
    body = ctx.body
    found = resolve(household=body.get("household_id"), device=body.get("device_id"))
    household = found.get("household")
    if household is None:
        req_id(body, "household_id")
    subscription = require_subscription(household["id"])
    device = found.get("device")
    scope_household(ctx, household["id"])

    severity = req_enum(body, "severity")
    summary = req_str(body, "summary", 1, 200)
    opened_by_member_id = body.get("opened_by_member_id")
    if opened_by_member_id is not None and not isinstance(opened_by_member_id, str):
        req_id(body, "opened_by_member_id")
    # Gate 2 guards ticket creation that names a device_id (PRD 2.8).
    gates(household=household, device=device)

    plan = plan_of(subscription)
    suffix = severity.lower()
    first_target = plan["first_response_minutes_" + suffix]
    onsite_target = 60 * plan["onsite_resolution_hours_" + suffix]

    row = new_row()
    row.update({
        "household_id": household["id"],
        "device_id": device["id"] if device is not None else None,
        "opened_by_member_id": opened_by_member_id,
        "severity": severity,
        "summary": summary,
        "workflow_status": "NEW",
        "sla_status": "WITHIN",
        "dispatch_status": "NOT_REQUIRED",
        "first_response_at": None,
        "resolved_at": None,
        "closed_at": None,
        "pause_started_at": None,
        "sla_paused_minutes": 0,
        "sla_uncovered_minutes": 0,
        "sla_counted_minutes": 0,
        "first_response_target_minutes": first_target,
        "onsite_resolution_target_minutes": onsite_target,
        "remote_session_failure_count": 0,
        "escalation_reason": None,
        "survey_solicited_at": None,
        "_pause_segments": [],
    })
    db.tickets[row["id"]] = row
    return created(S.ticket(row))


@bp.get(PREFIX + "/tickets")
def list_tickets():
    begin(TICKET_READ_ROLES)
    limit, offset = read_pagination(request.args)
    workflow = filter_enum(request.args, "workflow_status")
    hid = request.args.get("household_id")
    did = request.args.get("device_id")
    mid = request.args.get("opened_by_member_id")
    rows = []
    for row in db.tickets.values():
        if hid is not None and row.get("household_id") != hid:
            continue
        if did is not None and row.get("device_id") != did:
            continue
        if mid is not None and row.get("opened_by_member_id") != mid:
            continue
        if workflow is not None and row.get("workflow_status") != workflow:
            continue
        rows.append(row)
    page, total = paginate(sort_rows(rows), limit, offset)
    return ok_list([S.ticket(r) for r in page], limit, offset, total)


@bp.get(PREFIX + "/tickets/<tid>")
def read_ticket(tid):
    ctx = begin(TICKET_READ_ROLES)
    ticket, _household = _ticket_context(ctx, tid)
    return ok(S.ticket(ticket))


@bp.get(PREFIX + "/tickets/<tid>/sla")
def read_sla(tid):
    """The read-only projection: recomputes the clock partition for the
    response only and writes nothing -- no version bump, no updated_at."""
    ctx = begin(("PlatformAdmin", "SupportAgent", "Owner"))
    ticket, _household = _ticket_context(ctx, tid)
    counted, paused, uncovered, total = sla.partition(ticket)
    return ok({
        "sla_counted_minutes": counted,
        "sla_paused_minutes": paused,
        "sla_uncovered_minutes": uncovered,
        "total_elapsed_minutes": total,
        "active_target_minutes": sla.active_target(ticket),
        "sla_status": ticket.get("sla_status"),
    })


# --------------------------------------------------------------------------
# The workflow and SLA axes
# --------------------------------------------------------------------------
@bp.post(PREFIX + "/tickets/<tid>/first-response")
def first_response(tid):
    ctx = begin(("SupportAgent",))
    ticket, household = _ticket_context(ctx, tid)
    req_str(ctx.body, "note", 1)
    gates(household=household, ticket=ticket)
    if ticket.get("workflow_status") != "NEW" or ticket.get("first_response_at") is not None:
        invalid_state("The first response may only be recorded on a NEW ticket.")

    ticket["first_response_at"] = clock.now_iso()
    ticket["workflow_status"] = "TRIAGED"
    counted = sla.recompute(ticket)

    target = ticket["first_response_target_minutes"]
    if counted > target:
        ticket["sla_status"] = "BREACHED_FIRST_RESPONSE"
        subscription = in_force_subscription(ticket["household_id"])
        if subscription is not None:
            tier, pct = sla.breach_tier_and_pct(counted, target)
            uncapped = round_half_up(as_decimal(subscription["monthly_fee_cents"]) * pct)
            # The first-response settlement never reports ERR_CREDIT_CAP_REACHED:
            # when no room remains it simply issues no credit and succeeds.
            credit = sla.issue_credit(subscription, ticket["household_id"], ticket["id"],
                                      "SLA_FIRST_RESPONSE_BREACH", tier, uncapped)
            if credit is not None:
                ticket["sla_status"] = "CREDITED"
    touch(ticket)
    return ok(S.ticket(ticket))


@bp.post(PREFIX + "/tickets/<tid>/await-customer")
def await_customer(tid):
    ctx = begin(("SupportAgent",))
    ticket, household = _ticket_context(ctx, tid)
    opt_str(ctx.body, "note")
    gates(household=household, ticket=ticket)
    if ticket.get("workflow_status") != "REMOTE_DIAG":
        invalid_state("Only a REMOTE_DIAG ticket may be parked on the customer.")
    if ticket.get("pause_started_at") is not None:
        invalid_state("The ticket is already parked on the customer.")

    ticket["pause_started_at"] = clock.now_iso()
    ticket["workflow_status"] = "AWAITING_CUSTOMER"
    if ticket.get("sla_status") in ("WITHIN", "AT_RISK"):
        ticket["sla_status"] = "PAUSED"
    touch(ticket)
    return ok(S.ticket(ticket))


@bp.post(PREFIX + "/tickets/<tid>/customer-reply")
def customer_reply(tid):
    ctx = begin(("Owner", "Member"))
    ticket, household = _ticket_context(ctx, tid)
    req_str(ctx.body, "message", 1)
    gates(household=household, ticket=ticket)
    if ticket.get("workflow_status") != "AWAITING_CUSTOMER":
        invalid_state("Only an AWAITING_CUSTOMER ticket may receive a customer reply.")
    if ticket.get("pause_started_at") is None:
        invalid_state("The ticket is not parked on the customer.")

    ticket.setdefault("_pause_segments", []).append(
        (ticket["pause_started_at"], clock.now_iso()))
    ticket["pause_started_at"] = None
    ticket["workflow_status"] = "REMOTE_DIAG"
    if ticket.get("sla_status") == "PAUSED":
        ticket["sla_status"] = "WITHIN"
    # Recomputing the whole partition is what guarantees the ticket-minute
    # conservation invariant: the pause moves minutes from the counted bucket
    # to the paused bucket and never creates or destroys one.
    sla.recompute(ticket)
    touch(ticket)
    return ok(S.ticket(ticket))


@bp.post(PREFIX + "/tickets/<tid>/sla-evaluate")
def sla_evaluate(tid):
    ctx = begin(("SupportAgent", "PlatformAdmin"))
    ticket, household = _ticket_context(ctx, tid)
    gates(household=household, ticket=ticket)

    counted, paused, uncovered, _total = sla.partition(ticket)
    status = ticket.get("sla_status")
    subscription = in_force_subscription(ticket["household_id"])
    fr_target = ticket["first_response_target_minutes"]
    onsite_target = ticket["onsite_resolution_target_minutes"]

    reason = None
    new_status = None
    base_cents = 0
    target = None
    if (ticket.get("first_response_at") is None and counted > fr_target
            and status in ("WITHIN", "AT_RISK")):
        new_status = "BREACHED_FIRST_RESPONSE"
        reason = "SLA_FIRST_RESPONSE_BREACH"
        target = fr_target
        base_cents = subscription["monthly_fee_cents"] if subscription else 0
    elif (ticket.get("first_response_at") is not None and ticket.get("resolved_at") is None
            and counted > onsite_target and status in ("WITHIN", "AT_RISK", "CREDITED")):
        new_status = "BREACHED_ONSITE"
        reason = "SLA_ONSITE_BREACH"
        target = onsite_target
        # The onsite base is widened by the overage booked in the cycle.
        base_cents = (subscription["monthly_fee_cents"]
                      + (subscription.get("overage_charges_cents_this_cycle") or 0)
                      ) if subscription else 0
    elif status == "WITHIN":
        active = sla.active_target(ticket)
        if active > 0 and counted >= (as_decimal(active) * sla.SLA_AT_RISK_PCT) and counted <= active:
            new_status = "AT_RISK"

    if reason is not None and subscription is not None:
        tier, pct = sla.breach_tier_and_pct(counted, target)
        uncapped = round_half_up(as_decimal(base_cents) * pct)
        room = sla.cap_remaining(subscription)
        # Rung 51 -- unlike the first-response settlement, explicit evaluation
        # DOES enforce the cap rung: nothing is written when a credit is due
        # and no room remains.
        if uncapped > 0 and room <= 0:
            raise ApiError("ERR_CREDIT_CAP_REACHED")
        ticket["sla_counted_minutes"] = counted
        ticket["sla_paused_minutes"] = paused
        ticket["sla_uncovered_minutes"] = uncovered
        ticket["sla_status"] = new_status
        credit = sla.issue_credit(subscription, ticket["household_id"], ticket["id"],
                                  reason, tier, uncapped)
        if credit is not None:
            ticket["sla_status"] = "CREDITED"
    else:
        ticket["sla_counted_minutes"] = counted
        ticket["sla_paused_minutes"] = paused
        ticket["sla_uncovered_minutes"] = uncovered
        if new_status is not None:
            ticket["sla_status"] = new_status
    touch(ticket)
    return ok(S.ticket(ticket))


@bp.post(PREFIX + "/tickets/<tid>/close")
def close_ticket(tid):
    ctx = begin(("SupportAgent",))
    ticket, household = _ticket_context(ctx, tid)
    gates(household=household, ticket=ticket)
    if ticket.get("workflow_status") != "RESOLVED":
        invalid_state("Only a RESOLVED ticket may be closed.")
    ticket["closed_at"] = clock.now_iso()
    ticket["workflow_status"] = "CLOSED"
    touch(ticket)
    return ok(S.ticket(ticket))


@bp.post(PREFIX + "/tickets/<tid>/reopen")
def reopen_ticket(tid):
    ctx = begin(("Owner", "Member"))
    ticket, household = _ticket_context(ctx, tid)
    req_str(ctx.body, "reason", 1)
    gates(household=household, ticket=ticket)
    if ticket.get("workflow_status") != "RESOLVED":
        invalid_state("Only a RESOLVED ticket may be reopened.")
    resolved_at = try_parse_instant(ticket.get("resolved_at"))
    # Rung 45 -- strictly before resolved_at plus 168 hours.
    if resolved_at is None or clock.now() >= add_hours(resolved_at, TICKET_REOPEN_WINDOW_HOURS):
        raise ApiError("ERR_REOPEN_WINDOW_CLOSED")

    ticket["workflow_status"] = "REOPENED"
    ticket["resolved_at"] = None
    # survey_solicited_at is deliberately left untouched: the satisfaction
    # window is anchored to the ticket's first resolution.
    if ticket.get("sla_status") == "MET":
        ticket["sla_status"] = "WITHIN"
    touch(ticket)
    return ok(S.ticket(ticket))


# --------------------------------------------------------------------------
# The satisfaction survey (PRD 3.12)
# --------------------------------------------------------------------------
@bp.post(PREFIX + "/tickets/<tid>/survey")
def submit_survey(tid):
    ctx = begin(("Owner", "Member"))
    ticket, household = _ticket_context(ctx, tid)
    score = req_int(ctx.body, "score", 1, 5)
    comment = opt_str(ctx.body, "comment")
    # Survey submission is the one ticket-scoped mutation exempt from gate 3.
    gates(household=household, ticket=ticket, skip_ticket=True)

    # Rung 46 -- one survey per ticket.
    for row in db.satisfaction_surveys.values():
        if row.get("ticket_id") == ticket["id"]:
            raise ApiError("ERR_SURVEY_ALREADY_SUBMITTED")
    # Rung 47 -- the 72-hour window measured from the first resolution.
    solicited = try_parse_instant(ticket.get("survey_solicited_at")) \
        if ticket.get("survey_solicited_at") else None
    if solicited is None or clock.now() >= add_hours(solicited, CSAT_SURVEY_WINDOW_HOURS):
        raise ApiError("ERR_SURVEY_WINDOW_CLOSED")

    subscription = in_force_subscription(ticket["household_id"])
    plan = plan_of(subscription) if subscription is not None else None
    monthly = subscription["monthly_fee_cents"] if subscription is not None else 0

    low = score <= CSAT_LOW_SCORE_MAX
    breached = ticket.get("sla_status") in sla.BREACHED_STATES
    if not low:
        variant, uncapped = "NONE", 0
    elif breached:
        variant = "BREACH_COMPOUNDED"
        uncapped = round_half_up(as_decimal(monthly) * CSAT_BREACH_COMPOUNDED_CREDIT_PCT)
    elif plan is not None and plan.get("tier") == "PRO":
        variant = "GOODWILL"
        uncapped = round_half_up(as_decimal(monthly) * CSAT_GOODWILL_CREDIT_PCT)
    else:
        variant, uncapped = "NONE", 0

    credit_cents = 0
    if uncapped > 0 and subscription is not None:
        reason = "CSAT_BREACH_COMPOUNDED" if variant == "BREACH_COMPOUNDED" else "CSAT_GOODWILL"
        credit = sla.issue_credit(subscription, ticket["household_id"], ticket["id"],
                                  reason, None, uncapped)
        if credit is not None:
            credit_cents = credit["amount_cents"]

    row = new_row()
    row.update({
        "ticket_id": ticket["id"],
        "score": score,
        "comment": comment,
        "submitted_at": clock.now_iso(),
        "window_closes_at": render_instant(add_hours(solicited, CSAT_SURVEY_WINDOW_HOURS)),
        "credit_variant": variant,
        "credit_cents": credit_cents,
    })
    db.satisfaction_surveys[row["id"]] = row
    return created(S.satisfaction_survey(row))


@bp.get(PREFIX + "/surveys")
def list_surveys():
    begin(("PlatformAdmin", "SupportAgent", "Owner"))
    limit, offset = read_pagination(request.args)
    tid = request.args.get("ticket_id")
    rows = [r for r in db.satisfaction_surveys.values()
            if tid is None or r.get("ticket_id") == tid]
    page, total = paginate(sort_rows(rows), limit, offset)
    return ok_list([S.satisfaction_survey(r) for r in page], limit, offset, total)


@bp.get(PREFIX + "/surveys/<sid>")
def read_survey(sid):
    ctx = begin(("PlatformAdmin", "SupportAgent", "Owner"))
    row = db.satisfaction_surveys.get(sid)
    if row is None:
        raise ApiError("ERR_INVALID_REQUEST", "No such survey.")
    ticket = db.tickets.get(row.get("ticket_id"))
    scope_household(ctx, ticket.get("household_id") if ticket else None)
    return ok(S.satisfaction_survey(row))


@bp.get(PREFIX + "/service-credits")
def list_service_credits():
    begin(("PlatformAdmin", "BillingAdmin", "SupportAgent", "Owner"))
    limit, offset = read_pagination(request.args)
    hid = request.args.get("household_id")
    sid = request.args.get("subscription_id")
    tid = request.args.get("ticket_id")
    rows = []
    for row in db.service_credits.values():
        if hid is not None and row.get("household_id") != hid:
            continue
        if sid is not None and row.get("subscription_id") != sid:
            continue
        if tid is not None and row.get("ticket_id") != tid:
            continue
        rows.append(row)
    page, total = paginate(sort_rows(rows), limit, offset)
    return ok_list([S.service_credit(r) for r in page], limit, offset, total)


@bp.get(PREFIX + "/service-credits/<cid>")
def read_service_credit(cid):
    ctx = begin(("PlatformAdmin", "BillingAdmin", "SupportAgent", "Owner"))
    row = db.service_credits.get(cid)
    if row is None:
        raise ApiError("ERR_INVALID_REQUEST", "No such service credit.")
    scope_household(ctx, row.get("household_id"))
    return ok(S.service_credit(row))
