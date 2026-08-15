"""SLA deadline calculation + lazy/clock-driven sla_status evaluation."""
import math
from datetime import timedelta
from decimal import Decimal

import db
from db import bump

SLA_AT_RISK_FRACTION = Decimal('0.75')

NON_TERMINAL_WORKFLOWS = ('NEW', 'TRIAGED', 'IN_PROGRESS', 'PENDING_EMPLOYEE',
                          'ESCALATED', 'REOPENED')

_SEVERITY = {'ON_TRACK': 0, 'AT_RISK': 1, 'BREACHED_RESPONSE': 2,
             'BREACHED_RESOLUTION': 3}


def find_policy(category_id, priority):
    for p in db.sla_policies.values():
        if p['category_id'] == category_id and p['priority'] == priority:
            return p
    return None


def surge_multiplier_at(category, instant):
    """Surge multiplier in effect for the category's specialist team at the
    given instant: the ACTIVE staffing window of the team whose inclusive
    bounds cover the instant (at most one per team by the overlap rule)."""
    team_id = category['specialist_team_id']
    for w in db.staffing_windows.values():
        if w['team_id'] != team_id or w['status'] != 'ACTIVE':
            continue
        if w['window_start'] <= instant <= w['window_end']:
            return Decimal(str(w['sla_multiplier']))
    return Decimal('1.0')


def eff_minutes(base_minutes, surge):
    """Multiplier applied, then rounded UP to whole minutes."""
    return int(math.ceil(Decimal(base_minutes) * surge))


def _add_business_minutes(anchor, minutes):
    """Walk forward from anchor consuming only minutes inside 09:00-17:00 UTC
    Monday-Friday. The due instant is the moment the minutes-th business
    minute is consumed."""
    need = int(minutes) * 60  # seconds
    t = anchor
    while True:
        day_open = t.replace(hour=9, minute=0, second=0, microsecond=0)
        day_close = t.replace(hour=17, minute=0, second=0, microsecond=0)
        if t.weekday() >= 5:
            t = day_open + timedelta(days=1)
            continue
        if t < day_open:
            t = day_open
            continue
        if t >= day_close:
            t = day_open + timedelta(days=1)
            continue
        avail = (day_close - t).total_seconds()
        if need <= avail:
            return t + timedelta(seconds=need)
        need -= avail
        t = day_open + timedelta(days=1)


def add_minutes(anchor, minutes, clock_mode):
    if clock_mode == 'BUSINESS_HOURS':
        return _add_business_minutes(anchor, minutes)
    return anchor + timedelta(minutes=int(minutes))


def compute_deadlines(anchor, policy, surge):
    """Return (first_response_due_at, resolution_due_at) for an anchor instant."""
    eff_fr = eff_minutes(policy['first_response_minutes'], surge)
    eff_res = eff_minutes(policy['resolution_minutes'], surge)
    return (add_minutes(anchor, eff_fr, policy['clock_mode']),
            add_minutes(anchor, eff_res, policy['clock_mode']))


def append_event(ticket, event_type, actor, from_state, to_state, note=None):
    ev = {
        'ticket_id': ticket['id'],
        'actor_user_id': actor,
        'event_type': event_type,
        'from_state': from_state,
        'to_state': to_state,
        'note': note,
    }
    db.stamp_created(ev)
    db.ticket_events[ev['id']] = ev
    return ev


def evaluate_ticket_sla(ticket):
    """Re-evaluate sla_status against the current logical clock.

    Severity chain with breach priority resolution > response > at-risk;
    severity never heals backwards. Breach requires now strictly past the
    deadline; the at-risk 0.75 fraction boundary is inclusive. Each actual
    transition appends an SLA_BREACH event and bumps the ticket version.
    """
    if ticket['workflow_status'] not in NON_TERMINAL_WORKFLOWS:
        return False
    current = ticket['sla_status']
    if current in ('MET', 'BREACHED_RESOLUTION'):
        return False  # terminal for the SLA dimension
    now = db.now()
    created = ticket['created_at']
    res_due = ticket['resolution_due_at']
    fr_due = ticket['first_response_due_at']
    if now > res_due:
        evaluated = 'BREACHED_RESOLUTION'
    elif ticket['first_responded_at'] is None and now > fr_due:
        evaluated = 'BREACHED_RESPONSE'
    else:
        total = (res_due - created).total_seconds()
        elapsed = (now - created).total_seconds()
        if total > 0 and Decimal(str(elapsed)) / Decimal(str(total)) >= SLA_AT_RISK_FRACTION:
            evaluated = 'AT_RISK'
        else:
            evaluated = 'ON_TRACK'
    if _SEVERITY[evaluated] > _SEVERITY[current]:
        ticket['sla_status'] = evaluated
        append_event(ticket, 'SLA_BREACH', 'system', None, None, note=evaluated)
        bump(ticket)
        return True
    return False


def sweep_all_tickets_sla():
    for t in db.tickets.values():
        evaluate_ticket_sla(t)
