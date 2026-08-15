"""Entity -> public JSON serializers. Computed fields are derived here."""
from decimal import Decimal

import db
from db import iso

TICKET_OPEN_WORKFLOWS = ('NEW', 'TRIAGED', 'IN_PROGRESS', 'PENDING_EMPLOYEE',
                         'ESCALATED', 'REOPENED')
# assigned_open_count pool: REOPENED deliberately excluded (scaffold).
AGENT_OPEN_WORKFLOWS = ('NEW', 'TRIAGED', 'IN_PROGRESS', 'PENDING_EMPLOYEE',
                        'ESCALATED')


def _common(rec):
    return {
        'id': rec['id'],
        'created_at': iso(rec['created_at']),
        'updated_at': iso(rec['updated_at']),
        'version': rec['version'],
    }


def _append_only(rec):
    return {'id': rec['id'], 'created_at': iso(rec['created_at'])}


def _num(x):
    """Decimal/int/float -> JSON number via float (values are pre-quantized)."""
    if isinstance(x, Decimal):
        return float(x)
    return x


def employee_open_ticket_count(emp_id):
    return sum(1 for t in db.tickets.values()
               if t['employee_id'] == emp_id
               and t['workflow_status'] in TICKET_OPEN_WORKFLOWS)


def agent_assigned_open_count(agent_id):
    return sum(1 for t in db.tickets.values()
               if t.get('assigned_agent_id') == agent_id
               and t['workflow_status'] in AGENT_OPEN_WORKFLOWS)


def ser_employee(e):
    out = _common(e)
    out.update({
        'employee_number': e['employee_number'],
        'full_name': e['full_name'],
        'email': e['email'],
        'status': e['status'],
        'manager_id': e['manager_id'],
        'address_line1': e['address_line1'],
        'city': e['city'],
        'region': e['region'],
        'postal_code': e['postal_code'],
        'bank_routing_number': e['bank_routing_number'],
        'bank_account_number': e['bank_account_number'],
        'bank_account_type': e['bank_account_type'],
        'has_pending_dcr': e['has_pending_dcr'],
        'open_ticket_count': employee_open_ticket_count(e['id']),
    })
    return out


def ser_team(t):
    out = _common(t)
    out.update({'name': t['name'], 'description': t['description']})
    return out


def ser_agent(a, rolling_csat=None):
    out = _common(a)
    out.update({
        'display_name': a['display_name'],
        'email': a['email'],
        'tier': a['tier'],
        'clearance': a['clearance'],
        'team_id': a['team_id'],
        'capacity_max': a['capacity_max'],
        'active': a['active'],
        'assigned_open_count': agent_assigned_open_count(a['id']),
        'rolling_csat': _num(rolling_csat) if rolling_csat is not None else None,
        'coaching_hold': a['coaching_hold'],
    })
    return out


def ser_category(c):
    out = _common(c)
    out.update({
        'code': c['code'],
        'name': c['name'],
        'is_sensitive': c['is_sensitive'],
        'specialist_team_id': c['specialist_team_id'],
        'active': c['active'],
    })
    return out


def ser_sla_policy(p):
    out = _common(p)
    out.update({
        'category_id': p['category_id'],
        'priority': p['priority'],
        'first_response_minutes': p['first_response_minutes'],
        'resolution_minutes': p['resolution_minutes'],
        'clock_mode': p['clock_mode'],
    })
    return out


def article_view_count(article_id):
    return sum(1 for v in db.article_views.values() if v['article_id'] == article_id)


def article_deflection_fail_count(article_id):
    return sum(1 for v in db.article_views.values()
               if v['article_id'] == article_id
               and v['deflection_outcome'] == 'TICKET_CREATED')


def ser_article(a):
    out = _common(a)
    out.update({
        'title': a['title'],
        'body': a['body'],
        'keywords': list(a['keywords']),
        'category_id': a['category_id'],
        'author_user_id': a['author_user_id'],
        'status': a['status'],
        'supersedes_article_id': a['supersedes_article_id'],
        'published_at': iso(a['published_at']) if a['published_at'] else None,
        'published_by_user_id': a['published_by_user_id'],
        'view_count': article_view_count(a['id']),
        'deflection_fail_count': article_deflection_fail_count(a['id']),
    })
    return out


def ser_article_view(v):
    out = _append_only(v)
    out.update({
        'employee_id': v['employee_id'],
        'article_id': v['article_id'],
        'viewed_at': iso(v['viewed_at']),
        'deflection_outcome': v['deflection_outcome'],
    })
    return out


MASKED_PLACEHOLDER = '[REDACTED]'


def ser_ticket(t, masked=False):
    out = _common(t)
    out.update({
        'employee_id': t['employee_id'],
        'category_id': t['category_id'],
        'subject': MASKED_PLACEHOLDER if masked else t['subject'],
        'description': MASKED_PLACEHOLDER if masked else t['description'],
        'priority': t['priority'],
        'sensitive': t['sensitive'],
        'tier': t['tier'],
        'workflow_status': t['workflow_status'],
        'sla_status': t['sla_status'],
        'assigned_agent_id': t['assigned_agent_id'],
        'source_article_id': t['source_article_id'],
        'resolution_article_id': t['resolution_article_id'],
        'resolution_summary': t['resolution_summary'],
        'first_response_due_at': iso(t['first_response_due_at']),
        'resolution_due_at': iso(t['resolution_due_at']),
        'first_responded_at': iso(t['first_responded_at']) if t['first_responded_at'] else None,
        'resolved_at': iso(t['resolved_at']) if t['resolved_at'] else None,
        'closed_at': iso(t['closed_at']) if t['closed_at'] else None,
        'escalation_count': t['escalation_count'],
        'reopen_count': t['reopen_count'],
        'masked': masked,
    })
    return out


def ser_ticket_event(ev):
    out = _append_only(ev)
    out.update({
        'ticket_id': ev['ticket_id'],
        'actor_user_id': ev['actor_user_id'],
        'event_type': ev['event_type'],
        'from_state': ev['from_state'],
        'to_state': ev['to_state'],
        'note': ev['note'],
    })
    return out


def ser_dcr(d):
    out = _common(d)
    out.update({
        'employee_id': d['employee_id'],
        'change_type': d['change_type'],
        'new_values': dict(d['new_values']),
        'approval_status': d['approval_status'],
        'fraud_status': d['fraud_status'],
        'submitted_at': iso(d['submitted_at']),
        'decided_by_user_id': d['decided_by_user_id'],
        'decided_at': iso(d['decided_at']) if d['decided_at'] else None,
        'applied_at': iso(d['applied_at']) if d['applied_at'] else None,
        'reject_reason': d['reject_reason'],
    })
    return out


def ser_fraud_verification(f):
    out = _common(f)
    out.update({
        'dcr_id': f['dcr_id'],
        'method': f['method'],
        'challenge_code': f['challenge_code'],
        'attempts': f['attempts'],
        'status': f['status'],
        'verified_by_user_id': f['verified_by_user_id'],
        'verified_at': iso(f['verified_at']) if f['verified_at'] else None,
    })
    return out


def ser_survey(s):
    out = _common(s)
    out.update({
        'ticket_id': s['ticket_id'],
        'employee_id': s['employee_id'],
        'agent_id': s['agent_id'],
        'status': s['status'],
        'score': s['score'],
        'comment': s['comment'],
        'issued_at': iso(s['issued_at']),
        'expires_at': iso(s['expires_at']),
        'submitted_at': iso(s['submitted_at']) if s['submitted_at'] else None,
    })
    return out


def ser_staffing_window(w, covered_t1, covered_t2, posture):
    out = _common(w)
    out.update({
        'team_id': w['team_id'],
        'name': w['name'],
        'window_start': iso(w['window_start']),
        'window_end': iso(w['window_end']),
        'required_t1_hours': _num(w['required_t1_hours']),
        'required_t2_hours': _num(w['required_t2_hours']),
        'sla_multiplier': _num(w['sla_multiplier']),
        'status': w['status'],
        'covered_t1_hours': _num(covered_t1),
        'covered_t2_hours': _num(covered_t2),
        'coverage_posture': posture,
    })
    return out


def ser_agent_shift(s):
    out = _common(s)
    out.update({
        'agent_id': s['agent_id'],
        'staffing_window_id': s['staffing_window_id'],
        'shift_start': iso(s['shift_start']),
        'shift_end': iso(s['shift_end']),
        'status': s['status'],
    })
    return out


def ser_audit_entry(a):
    out = _append_only(a)
    out.update({
        'employee_id': a['employee_id'],
        'dcr_id': a['dcr_id'],
        'field_changed': a['field_changed'],
        'old_value': a['old_value'],
        'new_value': a['new_value'],
        'changed_by_user_id': a['changed_by_user_id'],
        'change_source': a['change_source'],
    })
    return out
