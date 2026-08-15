"""Rolling CSAT calculation (pinned rounding order) + coaching cascade."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from db import bump
from services.sla import append_event

CSAT_WINDOW_DAYS = 30
CSAT_HALF_LIFE_DAYS = 14
CSAT_MIN_SURVEYS = 3
CSAT_COACHING_THRESHOLD = Decimal('3.00')

_Q6 = Decimal('0.000001')
_Q2 = Decimal('0.01')


def _rhup(x, q):
    return x.quantize(q, rounding=ROUND_HALF_UP)


def compute_csat(agent_id, now=None):
    """Return (survey_count, simple_mean, recency_weighted_mean).

    Means are Decimal quantized to 2dp, or None when no submitted survey is
    inside the trailing 30-day window (both ends inclusive).
    """
    now = now or db.now()
    lo = now - timedelta(days=CSAT_WINDOW_DAYS)
    rows = [s for s in db.surveys.values()
            if s['agent_id'] == agent_id and s['status'] == 'SUBMITTED'
            and lo <= s['submitted_at'] <= now]
    if not rows:
        return 0, None, None
    total_score = 0
    sum_terms = Decimal('0')
    sum_weights = Decimal('0')
    for s in rows:
        score = int(s['score'])
        total_score += score
        age_seconds = (now - s['submitted_at']).total_seconds()
        age_days = int(age_seconds // 86400)
        w = _rhup(Decimal(str(0.5 ** (age_days / CSAT_HALF_LIFE_DAYS))), _Q6)
        # Pinned rounding order: round each weighted term FIRST, then sum,
        # then divide, then round the quotient.
        term = _rhup(Decimal(score) * w, _Q2)
        sum_terms += term
        sum_weights += w
    simple = _rhup(Decimal(total_score) / Decimal(len(rows)), _Q2)
    weighted = _rhup(sum_terms / sum_weights, _Q2)
    return len(rows), simple, weighted


def recompute_agent_coaching(agent, actor_user_id):
    """Recompute coaching_hold after a survey submit. On a false->true flip,
    release the agent's assigned open tickets (TRIAGED/IN_PROGRESS/ESCALATED
    -> unassigned TRIAGED with a COACHING_RELEASE event each)."""
    count, _simple, weighted = compute_csat(agent['id'])
    new_hold = bool(count >= CSAT_MIN_SURVEYS
                    and weighted is not None
                    and weighted < CSAT_COACHING_THRESHOLD)
    if agent['coaching_hold'] == new_hold:
        return
    agent['coaching_hold'] = new_hold
    bump(agent)
    if not new_hold:
        return
    released = [t for t in db.tickets.values()
                if t.get('assigned_agent_id') == agent['id']
                and t['workflow_status'] in ('TRIAGED', 'IN_PROGRESS', 'ESCALATED')]
    released.sort(key=lambda t: t['_seq'])
    for t in released:
        from_state = t['workflow_status']
        t['assigned_agent_id'] = None
        t['workflow_status'] = 'TRIAGED'
        append_event(t, 'COACHING_RELEASE', actor_user_id, from_state, 'TRIAGED',
                     note=None)
        bump(t)
