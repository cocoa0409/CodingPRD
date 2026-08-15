"""Staffing window coverage hours + posture (constraint propagation)."""
from decimal import Decimal, ROUND_HALF_UP

import db

COVERAGE_UNDER_RATIO = Decimal('0.90')
COVERAGE_SURPLUS_RATIO = Decimal('1.10')

_Q2 = Decimal('0.01')


def compute_coverage(window):
    """Return (covered_t1_hours, covered_t2_hours, coverage_posture).

    Per tier: sum of overlap minutes between each SCHEDULED shift (half-open)
    and the window's inclusive bounds, divided by 60; zero/negative clips
    contribute nothing. Covered hours are rounded half-up to 2dp for display;
    ratios are compared exactly against the thresholds, weakest tier gates.
    """
    raw = {'T1': Decimal('0'), 'T2': Decimal('0')}
    for s in db.agent_shifts.values():
        if s['staffing_window_id'] != window['id'] or s['status'] != 'SCHEDULED':
            continue
        agent = db.agents.get(s['agent_id'])
        if agent is None:
            continue
        tier = agent['tier']
        start = max(s['shift_start'], window['window_start'])
        end = min(s['shift_end'], window['window_end'])
        seconds = (end - start).total_seconds()
        if seconds <= 0:
            continue
        raw[tier] += Decimal(str(seconds)) / Decimal(3600)
    ratios = []
    covered = {}
    for tier, req_key in (('T1', 'required_t1_hours'), ('T2', 'required_t2_hours')):
        covered[tier] = raw[tier].quantize(_Q2, rounding=ROUND_HALF_UP)
        required = Decimal(str(window[req_key]))
        if required == 0:
            ratios.append(Decimal('1.0'))
        else:
            ratios.append(raw[tier] / required)
    overall = min(ratios)
    if overall < COVERAGE_UNDER_RATIO:
        posture = 'UNDER_STAFFED'
    elif overall <= COVERAGE_SURPLUS_RATIO:
        posture = 'ADEQUATE'
    else:
        posture = 'SURPLUS'
    return covered['T1'], covered['T2'], posture
