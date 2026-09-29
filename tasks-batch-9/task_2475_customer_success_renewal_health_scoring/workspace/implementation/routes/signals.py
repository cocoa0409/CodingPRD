"""Account signals: E16-E17."""
from flask import Blueprint

import db as store
import middleware as mw
import response as resp
from db import base_row, db, mark_fresh
from services import calc, derive, serialize
from services.lookup import account as get_account

bp = Blueprint('signals', __name__)

SIGNAL_KINDS = ('USAGE_PERIOD', 'SUPPORT_TICKET')
TICKET_SEVERITIES = ('S1', 'S2', 'S3', 'S4')
USAGE_ONLY_FIELDS = ('period_end_date', 'weekly_active_users', 'licensed_seats',
                     'feature_depth_pct')


@bp.route('/accounts/<account_id>/signals', methods=['POST'])
def create_signal(account_id):
    mw.authenticate(('CsmUser', 'CsOpsAdmin'))
    account = get_account(account_id)
    data = mw.body()
    signal_kind = mw.as_enum(data, 'signal_kind', SIGNAL_KINDS)

    row = base_row(versioned=False)
    row.update({
        'account_id': account['id'],
        'signal_kind': signal_kind,
        'period_end_date': None,
        '_period_end_date': None,
        'weekly_active_users': None,
        'licensed_seats': None,
        'feature_depth_pct': None,
        'seat_utilisation_pct': None,
        'usage_row_index': None,
        'ticket_severity': None,
        'opened_at': None,
        '_opened_at': None,
        'resolved_at': None,
        'breached_sla': None,
        'csat_score': None,
        'penalty_points': None,
    })

    if signal_kind == 'USAGE_PERIOD':
        period_end = mw.as_date(data, 'period_end_date')
        weekly_active_users = mw.as_int(data, 'weekly_active_users', minimum=0)
        licensed_seats = mw.as_int(data, 'licensed_seats', minimum=0)
        feature_depth = mw.as_decimal(data, 'feature_depth_pct', minimum=0,
                                      maximum=100)
        seat_util = calc.seat_utilisation_pct(weekly_active_users, licensed_seats)
        row.update({
            'period_end_date': data['period_end_date'],
            '_period_end_date': period_end,
            'weekly_active_users': weekly_active_users,
            'licensed_seats': licensed_seats,
            'feature_depth_pct': feature_depth,
            'seat_utilisation_pct': seat_util,
            'usage_row_index': calc.usage_row_index(seat_util, feature_depth),
        })
    else:
        for field in USAGE_ONLY_FIELDS:
            if mw.present(data, field):
                raise mw.invalid('%s is not accepted on a SUPPORT_TICKET row.'
                                 % field)
        severity = mw.as_enum(data, 'ticket_severity', TICKET_SEVERITIES)
        opened_at = mw.as_datetime(data, 'opened_at')
        resolved_at = mw.as_datetime(data, 'resolved_at', required=False)
        breached_sla = mw.as_bool(data, 'breached_sla', required=False)
        if breached_sla is None:
            breached_sla = False
        csat_score = mw.as_int(data, 'csat_score', required=False, minimum=1,
                               maximum=5)
        row.update({
            'ticket_severity': severity,
            'opened_at': data['opened_at'],
            '_opened_at': opened_at,
            'resolved_at': data.get('resolved_at') if resolved_at else None,
            'breached_sla': breached_sla,
            'csat_score': csat_score,
            'penalty_points': calc.ticket_penalty_points(severity, breached_sla,
                                                         csat_score),
        })

    db.account_signals[row['id']] = row
    mark_fresh(row)

    if signal_kind == 'USAGE_PERIOD':
        derive.recompute_adoption_index(account)
    else:
        derive.recompute_support_risk_penalty(account)
    derive.recompute_health_scores(account)
    derive.recompute_renewal_likelihood(account)
    derive.derive_coverage_posture(account)
    return resp.entity(serialize.account_signal, row, 201)


@bp.route('/accounts/<account_id>/signals', methods=['GET'])
def list_signals(account_id):
    mw.authenticate(('CsmUser', 'CsOpsAdmin', 'CsExecutive'))
    account = get_account(account_id)
    limit, offset = mw.pagination()
    signal_kind = mw.query_enum('signal_kind', SIGNAL_KINDS)
    rows = store.account_signals(account['id'], signal_kind)
    return resp.collection(serialize.account_signal, rows, limit, offset)
