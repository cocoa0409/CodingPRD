"""Core plumbing for the TPRM API server.

Holds the Flask app, the logical clock, the in-memory stores, the response
envelope helpers, auth/RBAC decorator, pagination, input validators,
serializers and shared business-logic helpers.
"""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import Flask, g, jsonify, request

app = Flask(__name__)
app.url_map.strict_slashes = False

# =====================================================================
# Logical clock (PRD §2.8) — boots at 2026-05-01T00:00:00Z
# =====================================================================
_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _CLOCK


def set_clock(dt):
    global _CLOCK
    _CLOCK = dt


# =====================================================================
# In-memory stores — start empty on every boot; nothing is seeded
# =====================================================================
vendors = {}
engagements = {}
dd_packages = {}
contracts = {}
fourth_parties = {}
cycles = {}
incidents = {}
plans = {}
assessments = {}
buckets = {}
bcp_tests = {}
audits = {}
findings = {}
board_reports = {}
tier_logs = {}

_seq_counter = [0]


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


# =====================================================================
# Time formatting / parsing (PRD §2.6)
# =====================================================================
def fmt_ms(dt):
    """Event timestamps: ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (dt.microsecond // 1000)


def fmt_sec(dt):
    """Computed scheduling fields: ISO 8601 UTC with second precision."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def fmt_rt(dt):
    """Round-trip format for caller-supplied datetimes."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return fmt_ms(dt)
    return fmt_sec(dt)


def parse_dt(v):
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s:
        return None
    try:
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


# =====================================================================
# Errors and response envelope (PRD §2.2)
# =====================================================================
class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err(error_id, status, message):
    raise ApiError(error_id, status, message)


def _meta():
    return {
        'api_request_id': 'req_' + ''.join(
            random.choices(string.ascii_letters + string.digits, k=20)),
        'api_request_timestamp': fmt_ms(now()),
    }


def ok(data, code=200):
    return jsonify({'meta': _meta(), 'response_type': 'object', 'data': data}), code


def ok_list(items, total, limit, offset):
    m = _meta()
    m['limit'] = limit
    m['offset'] = offset
    m['total_count'] = total
    m['has_more'] = (offset + len(items)) < total
    return jsonify({'meta': m, 'response_type': 'array', 'data': items}), 200


def error_body(error_id, message):
    return {'meta': _meta(), 'response_type': 'error',
            'data': {'error_id': error_id, 'message': message}}


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return jsonify(error_body(e.error_id, e.message)), e.status


@app.errorhandler(404)
def _handle_404(e):
    return jsonify(error_body('ERR_NOT_FOUND', 'Resource not found.')), 404


@app.errorhandler(405)
def _handle_405(e):
    return jsonify(error_body('ERR_INVALID_REQUEST', 'Method not allowed.')), 405


@app.errorhandler(Exception)
def _handle_500(e):
    if isinstance(e, ApiError):
        return jsonify(error_body(e.error_id, e.message)), e.status
    return jsonify(error_body('ERR_INTERNAL', 'Internal server error.')), 500


# =====================================================================
# Auth / RBAC (PRD §2.1, §3.16 priorities 1-2)
# =====================================================================
ROLES = {
    'VendorRelationshipManager', 'RiskOfficer', 'BusinessUnitOwner',
    'InternalAuditor', 'ComplianceDirector', 'PlatformAdmin',
}


def auth(*allowed_roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get('X-User-ID')
            role = request.headers.get('X-User-Role')
            if not uid or not isinstance(uid, str) or not role or role not in ROLES:
                err('ERR_UNAUTHENTICATED', 401,
                    'Missing or malformed X-User-ID / X-User-Role headers.')
            if allowed_roles and role not in allowed_roles:
                err('ERR_UNAUTHORIZED', 403,
                    'Role not permitted for this endpoint.')
            g.user_id = uid
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


# =====================================================================
# Request body / pagination / input validators (priority 19 -> 400)
# =====================================================================
def get_body():
    data = request.get_json(force=True, silent=True)
    return data if isinstance(data, dict) else {}


def paginate(items):
    """Sorts by insertion order (== created_at ascending) and slices."""
    items = sorted(items, key=lambda e: e['_seq'])
    limit, offset = 10, 0
    raw_limit = request.args.get('limit')
    raw_offset = request.args.get('offset')
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            err('ERR_INVALID_REQUEST', 400, 'limit must be an integer.')
        if limit < 1 or limit > 100:
            err('ERR_INVALID_REQUEST', 400, 'limit must be between 1 and 100.')
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            err('ERR_INVALID_REQUEST', 400, 'offset must be an integer.')
        if offset < 0:
            err('ERR_INVALID_REQUEST', 400, 'offset must be >= 0.')
    total = len(items)
    return items[offset:offset + limit], total, limit, offset


def req_str(body, key, allow_empty=False):
    v = body.get(key)
    if not isinstance(v, str) or (not allow_empty and v == ''):
        err('ERR_INVALID_REQUEST', 400, '%s is required and must be a string.' % key)
    return v


def req_int(body, key, lo=None, hi=None):
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        err('ERR_INVALID_REQUEST', 400, '%s is required and must be an integer.' % key)
    if lo is not None and v < lo:
        err('ERR_INVALID_REQUEST', 400, '%s must be >= %s.' % (key, lo))
    if hi is not None and v > hi:
        err('ERR_INVALID_REQUEST', 400, '%s must be <= %s.' % (key, hi))
    return v


def req_num(body, key, lo=None, hi=None):
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err('ERR_INVALID_REQUEST', 400, '%s is required and must be a number.' % key)
    if lo is not None and v < lo:
        err('ERR_INVALID_REQUEST', 400, '%s must be >= %s.' % (key, lo))
    if hi is not None and v > hi:
        err('ERR_INVALID_REQUEST', 400, '%s must be <= %s.' % (key, hi))
    return v


def req_bool(body, key):
    v = body.get(key)
    if not isinstance(v, bool):
        err('ERR_INVALID_REQUEST', 400, '%s is required and must be a boolean.' % key)
    return v


def req_enum(body, key, allowed):
    v = body.get(key)
    if v not in allowed:
        err('ERR_INVALID_REQUEST', 400, '%s must be one of %s.' % (key, sorted(allowed)))
    return v


def req_dt(body, key):
    v = parse_dt(body.get(key))
    if v is None:
        err('ERR_INVALID_REQUEST', 400, '%s is required and must be an ISO 8601 datetime.' % key)
    return v


# =====================================================================
# Entity helpers
# =====================================================================
def base_entity(with_version=True):
    t = now()
    e = {'id': str(uuid.uuid4()), 'created_at': t, '_seq': next_seq()}
    if with_version:
        e['updated_at'] = t
        e['version'] = 1
    return e


def mutate(e, **fields):
    """Apply one logical mutation: set fields, bump version, refresh updated_at."""
    e.update(fields)
    if 'version' in e:
        e['version'] += 1
        e['updated_at'] = now()


def dec2(value):
    return float(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


# =====================================================================
# Enum vocabularies (PRD §2.9)
# =====================================================================
REGIONS = {'NA', 'EMEA', 'APAC', 'LATAM'}
CATEGORIES = {'CLOUD_INFRA', 'PAYMENTS', 'KYC_AML', 'DATA_ANALYTICS',
              'CUSTODIAL', 'BPO', 'LEGAL', 'OTHER'}
TIERS = {'TIER_1_CRITICAL', 'TIER_2_HIGH', 'TIER_3_STANDARD', 'TIER_4_LOW'}
SENSITIVITIES = {'PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'REGULATED'}
DATA_ACCESS = {'NONE', 'METADATA', 'PII', 'REGULATED_PII'}
INCIDENT_TYPES = {'DATA_BREACH', 'SLA_BREACH', 'OUTAGE', 'FINANCIAL_DISTRESS',
                  'REGULATORY_FINDING', 'FOURTH_PARTY_EVENT'}
SEVERITIES = {'SEV_1', 'SEV_2', 'SEV_3', 'SEV_4'}
DIMENSIONS = {'REGION', 'SERVICE_CATEGORY'}
SCENARIOS = {'FULL_FAILOVER', 'PARTIAL_DEGRADATION', 'CYBER_INCIDENT', 'DATA_RESTORE'}
SCOPES = {'SECURITY', 'FINANCIAL', 'OPERATIONAL', 'REGULATORY', 'FULL'}

NONTERMINAL_INCIDENT = {'OPEN', 'TRIAGED', 'REMEDIATION_PLANNED',
                        'REMEDIATION_IN_PROGRESS', 'AWAITING_VERIFICATION',
                        'REOPENED'}
SEV_W = {'SEV_1': 40, 'SEV_2': 20, 'SEV_3': 8, 'SEV_4': 3}
TIER_MULT = {'TIER_1_CRITICAL': Decimal('1.5'), 'TIER_2_HIGH': Decimal('1.2'),
             'TIER_3_STANDARD': Decimal('1.0'), 'TIER_4_LOW': Decimal('0.8')}
CADENCE = {'TIER_1_CRITICAL': 90, 'TIER_2_HIGH': 180,
           'TIER_3_STANDARD': 365, 'TIER_4_LOW': 730}
DD_W = {'TIER_1_CRITICAL': (Decimal('0.25'), Decimal('0.45'), Decimal('0.30')),
        'TIER_2_HIGH': (Decimal('0.30'), Decimal('0.40'), Decimal('0.30')),
        'TIER_3_STANDARD': (Decimal('0.40'), Decimal('0.35'), Decimal('0.25')),
        'TIER_4_LOW': (Decimal('0.50'), Decimal('0.25'), Decimal('0.25'))}
SEVERITY_WINDOW_DAYS = {'SEV_1': 7, 'SEV_2': 30, 'SEV_3': 90, 'SEV_4': 180}


# =====================================================================
# Serializers
# =====================================================================
def vendor_out(v):
    return {
        'id': v['id'], 'legal_name': v['legal_name'],
        'headquarters_region': v['headquarters_region'],
        'service_category': v['service_category'],
        'criticality_tier': v['criticality_tier'], 'status': v['status'],
        'tier_posture': v['tier_posture'],
        'composite_risk_score': v['composite_risk_score'],
        'onboarded_by_user_id': v['onboarded_by_user_id'],
        'archived_at': fmt_ms(v['archived_at']),
        'next_monitoring_due_at': fmt_sec(v['next_monitoring_due_at']),
        'created_at': fmt_ms(v['created_at']),
        'updated_at': fmt_ms(v['updated_at']), 'version': v['version'],
    }


def engagement_out(e):
    return {
        'id': e['id'], 'vendor_id': e['vendor_id'],
        'engagement_code': e['engagement_code'],
        'service_summary': e['service_summary'],
        'annual_spend_cents': e['annual_spend_cents'],
        'data_sensitivity': e['data_sensitivity'],
        'lifecycle_status': e['lifecycle_status'],
        'risk_attention_state': e['risk_attention_state'],
        'started_by_user_id': e['started_by_user_id'],
        'exit_readiness_score': e['exit_readiness_score'],
        'created_at': fmt_ms(e['created_at']),
        'updated_at': fmt_ms(e['updated_at']), 'version': e['version'],
    }


def dd_out(p):
    return {
        'id': p['id'], 'engagement_id': p['engagement_id'],
        'financial_review_score': p['financial_review_score'],
        'security_review_score': p['security_review_score'],
        'compliance_review_score': p['compliance_review_score'],
        'financial_reviewer_id': p['financial_reviewer_id'],
        'security_reviewer_id': p['security_reviewer_id'],
        'compliance_reviewer_id': p['compliance_reviewer_id'],
        'aggregate_dd_score': p['aggregate_dd_score'],
        'dd_outcome': p['dd_outcome'], 'status': p['status'],
        'submitted_by_user_id': p['submitted_by_user_id'],
        'approver_user_id': p['approver_user_id'],
        'review_round': p['review_round'],
        'created_at': fmt_ms(p['created_at']),
        'updated_at': fmt_ms(p['updated_at']), 'version': p['version'],
    }


def contract_out(c):
    return {
        'id': c['id'], 'engagement_id': c['engagement_id'],
        'contract_reference': c['contract_reference'],
        'effective_date': fmt_rt(c['effective_date']),
        'expiry_date': fmt_rt(c['expiry_date']),
        'has_right_to_audit_clause': c['has_right_to_audit_clause'],
        'has_sla_terms': c['has_sla_terms'],
        'has_exit_plan_section': c['has_exit_plan_section'],
        'sla_uptime_pct': c['sla_uptime_pct'],
        'breach_cure_window_days': c['breach_cure_window_days'],
        'renewal_notice_days': c['renewal_notice_days'],
        'status': c['status'],
        'version_pin_dd_package_id': c['version_pin_dd_package_id'],
        'created_at': fmt_ms(c['created_at']),
        'updated_at': fmt_ms(c['updated_at']), 'version': c['version'],
    }


def fp_out(f):
    return {
        'id': f['id'], 'engagement_id': f['engagement_id'], 'name': f['name'],
        'service_provided': f['service_provided'],
        'parent_fourth_party_id': f['parent_fourth_party_id'],
        'data_access_level': f['data_access_level'],
        'acknowledgement_status': f['acknowledgement_status'],
        'acknowledged_by_user_id': f['acknowledged_by_user_id'],
        'created_at': fmt_ms(f['created_at']),
        'updated_at': fmt_ms(f['updated_at']), 'version': f['version'],
    }


def cycle_out(c):
    return {
        'id': c['id'], 'vendor_id': c['vendor_id'],
        'cycle_index': c['cycle_index'],
        'due_at': fmt_sec(c['due_at']), 'cadence_days': c['cadence_days'],
        'status': c['status'],
        'completed_at': fmt_ms(c['completed_at']),
        'findings_summary': c['findings_summary'],
        'waived_by_user_id': c['waived_by_user_id'],
        'created_at': fmt_ms(c['created_at']),
        'updated_at': fmt_ms(c['updated_at']), 'version': c['version'],
    }


def incident_out(i):
    return {
        'id': i['id'], 'engagement_id': i['engagement_id'],
        'incident_type': i['incident_type'], 'severity': i['severity'],
        'detected_at': fmt_rt(i['detected_at']),
        'reported_by_user_id': i['reported_by_user_id'],
        'status': i['status'],
        'remediation_due_at': fmt_sec(i['remediation_due_at']),
        'closed_at': fmt_ms(i['closed_at']),
        'reopen_count': i['reopen_count'],
        'created_at': fmt_ms(i['created_at']),
        'updated_at': fmt_ms(i['updated_at']), 'version': i['version'],
    }


def plan_out(p):
    return {
        'id': p['id'], 'incident_id': p['incident_id'],
        'plan_summary': p['plan_summary'],
        'committed_completion_date': fmt_rt(p['committed_completion_date']),
        'owner_user_id': p['owner_user_id'],
        'verification_evidence_uri': p['verification_evidence_uri'],
        'status': p['status'],
        'approved_by_user_id': p['approved_by_user_id'],
        'created_at': fmt_ms(p['created_at']),
        'updated_at': fmt_ms(p['updated_at']), 'version': p['version'],
    }


def assessment_out(a):
    return {
        'id': a['id'],
        'assessment_window_start': fmt_rt(a['assessment_window_start']),
        'assessment_window_end': fmt_rt(a['assessment_window_end']),
        'grouping_dimension': a['grouping_dimension'],
        'status': a['status'],
        'computed_at': fmt_ms(a['computed_at']),
        'published_by_user_id': a['published_by_user_id'],
        'breach_bucket_keys': a['breach_bucket_keys'],
        'created_at': fmt_ms(a['created_at']),
        'updated_at': fmt_ms(a['updated_at']), 'version': a['version'],
    }


def bucket_out(b):
    return {
        'id': b['id'], 'assessment_id': b['assessment_id'],
        'bucket_key': b['bucket_key'],
        'total_spend_cents': b['total_spend_cents'],
        'share_pct': b['share_pct'], 'is_breach': b['is_breach'],
        'created_at': fmt_ms(b['created_at']),
    }


def bcp_out(b):
    return {
        'id': b['id'], 'engagement_id': b['engagement_id'],
        'scheduled_for': fmt_rt(b['scheduled_for']),
        'scenario': b['scenario'],
        'rto_target_minutes': b['rto_target_minutes'],
        'rpo_target_minutes': b['rpo_target_minutes'],
        'actual_rto_minutes': b['actual_rto_minutes'],
        'actual_rpo_minutes': b['actual_rpo_minutes'],
        'status': b['status'], 'outcome': b['outcome'],
        'created_at': fmt_ms(b['created_at']),
        'updated_at': fmt_ms(b['updated_at']), 'version': b['version'],
    }


def audit_out(a):
    return {
        'id': a['id'], 'engagement_id': a['engagement_id'], 'scope': a['scope'],
        'exercised_by_user_id': a['exercised_by_user_id'],
        'initiated_at': fmt_ms(a['initiated_at']),
        'findings_count': a['findings_count'], 'status': a['status'],
        'closed_at': fmt_ms(a['closed_at']),
        'created_at': fmt_ms(a['created_at']),
        'updated_at': fmt_ms(a['updated_at']), 'version': a['version'],
    }


def finding_out(f):
    return {
        'id': f['id'], 'audit_exercise_id': f['audit_exercise_id'],
        'severity': f['severity'], 'description': f['description'],
        'raised_incident_id': f['raised_incident_id'],
        'created_at': fmt_ms(f['created_at']),
    }


def report_out(r):
    return {
        'id': r['id'],
        'period_start': fmt_rt(r['period_start']),
        'period_end': fmt_rt(r['period_end']),
        'status': r['status'],
        'snapshot_payload': r['snapshot_payload'],
        'published_at': fmt_ms(r['published_at']),
        'published_by_user_id': r['published_by_user_id'],
        'created_at': fmt_ms(r['created_at']),
        'updated_at': fmt_ms(r['updated_at']), 'version': r['version'],
    }


def log_out(row):
    return {
        'id': row['id'], 'vendor_id': row['vendor_id'],
        'from_tier': row['from_tier'], 'to_tier': row['to_tier'],
        'reason': row['reason'],
        'changed_by_user_id': row['changed_by_user_id'],
        'created_at': fmt_ms(row['created_at']),
    }


# =====================================================================
# Shared business-logic helpers
# =====================================================================
def get_vendor(vid):
    v = vendors.get(vid)
    if v is None:
        err('ERR_NOT_FOUND', 404, 'Vendor not found.')
    return v


def get_engagement(eid):
    e = engagements.get(eid)
    if e is None:
        err('ERR_NOT_FOUND', 404, 'Engagement not found.')
    return e


def vendor_engagement_ids(vid):
    return {e['id'] for e in engagements.values() if e['vendor_id'] == vid}


def compute_vendor_risk(v):
    """Pure composite_risk_score + tier_posture computation (PRD §3.10)."""
    eng_ids = vendor_engagement_ids(v['id'])
    base = 0
    for inc in incidents.values():
        if inc['engagement_id'] in eng_ids and inc['status'] in NONTERMINAL_INCIDENT:
            base += SEV_W[inc['severity']]
    base += sum(1 for c in cycles.values()
                if c['vendor_id'] == v['id'] and c['status'] == 'OVERDUE') * 10
    base += sum(1 for b in bcp_tests.values()
                if b['engagement_id'] in eng_ids and b['status'] == 'FAILED') * 15
    score = (Decimal(base) * TIER_MULT[v['criticality_tier']]).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP)
    score = max(Decimal('0'), min(Decimal('100'), score))
    if score >= 70:
        posture = 'BREACH'
    elif score >= 40:
        posture = 'ESCALATED'
    elif score >= 15:
        posture = 'WATCH'
    else:
        posture = 'CLEAN'
    return float(score), posture


def recompute_vendor(v):
    score, posture = compute_vendor_risk(v)
    if v['composite_risk_score'] != score or v['tier_posture'] != posture:
        mutate(v, composite_risk_score=score, tier_posture=posture)


def schedule_cycle(v, anchor):
    """Create the next MonitoringCycle for a vendor (PRD §3.7)."""
    cadence = CADENCE[v['criticality_tier']]
    anchor = anchor.replace(microsecond=0)
    due = anchor + timedelta(days=cadence)
    for c in cycles.values():
        if c['vendor_id'] == v['id'] and c['status'] in ('SCHEDULED', 'IN_PROGRESS'):
            if c['_anchor_at'] < due and anchor < c['due_at']:
                err('ERR_CYCLE_WINDOW_OVERLAP', 422,
                    'New monitoring cycle window overlaps an existing cycle.')
    idx = max([c['cycle_index'] for c in cycles.values()
               if c['vendor_id'] == v['id']], default=0) + 1
    c = base_entity()
    c.update({
        'vendor_id': v['id'], 'cycle_index': idx, 'due_at': due,
        'cadence_days': cadence, 'status': 'SCHEDULED', 'completed_at': None,
        'findings_summary': None, 'waived_by_user_id': None,
        '_anchor_at': anchor,
    })
    cycles[c['id']] = c
    return c


def open_cycle_for(v):
    live = [c for c in cycles.values()
            if c['vendor_id'] == v['id'] and c['status'] in ('SCHEDULED', 'IN_PROGRESS')]
    live.sort(key=lambda c: c['_seq'])
    return live[0] if live else None


def latest_contract(engagement_id, status=None):
    cs = [c for c in contracts.values()
          if c['engagement_id'] == engagement_id
          and (status is None or c['status'] == status)]
    cs.sort(key=lambda c: c['_seq'])
    return cs[-1] if cs else None


def latest_approved_dd(engagement_id):
    ps = [p for p in dd_packages.values()
          if p['engagement_id'] == engagement_id and p['status'] == 'APPROVED']
    ps.sort(key=lambda p: p['_seq'])
    return ps[-1] if ps else None


def dd_compute(p, tier):
    wf, ws, wc = DD_W[tier]
    raw = (Decimal(p['financial_review_score']) * wf
           + Decimal(p['security_review_score']) * ws
           + Decimal(p['compliance_review_score']) * wc)
    score = float(raw.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    if score >= 75.0:
        outcome = 'PASS'
    elif score >= 60.0:
        outcome = 'CONDITIONAL_PASS'
    else:
        outcome = 'FAIL'
    return score, outcome


def raise_incident(engagement, incident_type, severity, reported_by, detected_at=None):
    inc = base_entity()
    inc.update({
        'engagement_id': engagement['id'], 'incident_type': incident_type,
        'severity': severity,
        'detected_at': detected_at if detected_at is not None else now(),
        'reported_by_user_id': reported_by, 'status': 'OPEN',
        'remediation_due_at': None, 'closed_at': None, 'reopen_count': 0,
    })
    incidents[inc['id']] = inc
    return inc


def compute_exit_readiness(eng, v):
    score = 100
    eng_incidents = [i for i in incidents.values()
                     if i['engagement_id'] == eng['id']]
    if any(i['status'] in NONTERMINAL_INCIDENT for i in eng_incidents):
        score -= 50
    inc_ids = {i['id'] for i in eng_incidents}
    if any(p['incident_id'] in inc_ids and p['status'] in
           ('DRAFT', 'SUBMITTED', 'APPROVED', 'IN_EXECUTION',
            'VERIFICATION_SUBMITTED') for p in plans.values()):
        score -= 20
    if v['criticality_tier'] == 'TIER_1_CRITICAL':
        ex = latest_contract(eng['id'], status='EXECUTED')
        if ex is None or not ex['has_exit_plan_section']:
            score -= 30
    if any(f['engagement_id'] == eng['id']
           and f['acknowledgement_status'] == 'PENDING'
           for f in fourth_parties.values()):
        score -= 15
    if any(c['vendor_id'] == v['id'] and c['status'] == 'OVERDUE'
           for c in cycles.values()):
        score -= 10
    return float(max(0, min(100, score)))


def open_incidents_on_engagement(eid, open_only=True):
    states = ('OPEN', 'REOPENED') if open_only else tuple(NONTERMINAL_INCIDENT)
    return [i for i in incidents.values()
            if i['engagement_id'] == eid and i['status'] in states]


def vendor_open_incidents(vid, open_only=True):
    eng_ids = vendor_engagement_ids(vid)
    states = ('OPEN', 'REOPENED') if open_only else tuple(NONTERMINAL_INCIDENT)
    return [i for i in incidents.values()
            if i['engagement_id'] in eng_ids and i['status'] in states]
