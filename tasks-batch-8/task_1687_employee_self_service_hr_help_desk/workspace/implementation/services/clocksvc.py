"""Logical clock advance + the four time-driven sweeps (PRD §2.5)."""
from datetime import timedelta

import db
from db import bump
from services.sla import append_event, sweep_all_tickets_sla

AUTO_CLOSE_DAYS = 5


def _sweep_survey_expiry(now):
    for s in db.surveys.values():
        if s['status'] == 'ISSUED' and s['expires_at'] < now:
            s['status'] = 'EXPIRED'
            bump(s)


def _sweep_auto_close(now):
    cutoff = now - timedelta(days=AUTO_CLOSE_DAYS)
    targets = [t for t in db.tickets.values()
               if t['workflow_status'] == 'RESOLVED'
               and t['resolved_at'] is not None
               and t['resolved_at'] <= cutoff]
    targets.sort(key=lambda t: t['_seq'])
    for t in targets:
        t['workflow_status'] = 'CLOSED'
        t['closed_at'] = now
        append_event(t, 'AUTO_CLOSED', 'system', 'RESOLVED', 'CLOSED', note=None)
        bump(t)


def _sweep_windows(now):
    for w in db.staffing_windows.values():
        if w['status'] == 'PLANNED' and w['window_start'] <= now <= w['window_end']:
            w['status'] = 'ACTIVE'
            bump(w)
        elif w['status'] == 'ACTIVE' and now > w['window_end']:
            w['status'] = 'COMPLETED'
            bump(w)


def advance_clock(to_dt):
    """Set the logical clock and run the sweeps in the specified order:
    SLA re-evaluation, survey expiry, RESOLVED auto-close, window sweep."""
    db.set_now(to_dt)
    sweep_all_tickets_sla()
    _sweep_survey_expiry(to_dt)
    _sweep_auto_close(to_dt)
    _sweep_windows(to_dt)
