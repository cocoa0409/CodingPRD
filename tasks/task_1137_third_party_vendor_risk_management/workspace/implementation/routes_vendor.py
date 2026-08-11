"""Vendor and VendorEngagement routes."""
from datetime import timedelta

from flask import g, request

from core import (CADENCE, CATEGORIES, REGIONS, SENSITIVITIES, TIERS,
                  app, auth, base_entity, bcp_tests, compute_exit_readiness,
                  compute_vendor_risk, cycles, engagement_out, engagements,
                  err, get_body, get_engagement, get_vendor, incidents,
                  latest_contract, log_out, mutate, now, ok, ok_list,
                  open_cycle_for, open_incidents_on_engagement, paginate,
                  req_enum, req_int, req_str, schedule_cycle, tier_logs,
                  vendor_open_incidents, vendor_out, vendors)


def g_user():
    return g.user_id

ALL_BUSINESS = ('VendorRelationshipManager', 'RiskOfficer', 'ComplianceDirector',
                'InternalAuditor', 'BusinessUnitOwner')


# ---------------------------------------------------------------- vendors
@app.route('/tprm/vendors', methods=['POST'])
@auth('VendorRelationshipManager')
def create_vendor():
    body = get_body()
    # Uniqueness (priority 18) before generic payload validation (priority 19)
    ln = body.get('legal_name')
    if isinstance(ln, str) and ln:
        for v in vendors.values():
            if v['archived_at'] is None and v['legal_name'] == ln:
                err('ERR_DUPLICATE_KEY', 409, 'legal_name already in use.')
    legal_name = req_str(body, 'legal_name')
    region = req_enum(body, 'headquarters_region', REGIONS)
    category = req_enum(body, 'service_category', CATEGORIES)
    # Client-supplied system/computed fields are accepted but ignored.
    v = base_entity()
    v.update({
        'legal_name': legal_name, 'headquarters_region': region,
        'service_category': category, 'criticality_tier': 'TIER_3_STANDARD',
        'status': 'ONBOARDING', 'tier_posture': 'CLEAN',
        'composite_risk_score': 0.0,
        'onboarded_by_user_id': g_user(), 'archived_at': None,
        'next_monitoring_due_at': None, '_activated_at': None,
    })
    vendors[v['id']] = v
    return ok(vendor_out(v), 201)


@app.route('/tprm/vendors', methods=['GET'])
@auth(*ALL_BUSINESS)
def list_vendors():
    items = list(vendors.values())
    include_archived = request.args.get('include_archived', '').lower() in (
        'true', '1', 'yes')
    if not include_archived:
        items = [v for v in items if v['archived_at'] is None]
    for field in ('status', 'criticality_tier', 'tier_posture',
                  'headquarters_region', 'service_category'):
        val = request.args.get(field)
        if val is not None:
            items = [v for v in items if v[field] == val]
    page, total, limit, offset = paginate(items)
    return ok_list([vendor_out(v) for v in page], total, limit, offset)


@app.route('/tprm/vendors/<vid>', methods=['GET'])
@auth(*ALL_BUSINESS)
def get_one_vendor(vid):
    return ok(vendor_out(get_vendor(vid)))


@app.route('/tprm/vendors/<vid>/activate', methods=['POST'])
@auth('RiskOfficer')
def activate_vendor(vid):
    v = get_vendor(vid)
    if v['status'] != 'ONBOARDING':
        err('ERR_VENDOR_NOT_ONBOARDING', 409, 'Vendor is not ONBOARDING.')
    if not any(e['vendor_id'] == vid and e['lifecycle_status'] == 'ACTIVE'
               for e in engagements.values()):
        err('ERR_NO_ACTIVE_ENGAGEMENT', 422,
            'Vendor activation requires at least one ACTIVE engagement.')
    if any(i['severity'] == 'SEV_1' for i in vendor_open_incidents(vid)):
        err('ERR_OPEN_SEV1_INCIDENT', 422,
            'Vendor activation blocked by an OPEN/REOPENED SEV_1 incident.')
    t = now()
    cycle = schedule_cycle(v, t)
    score, posture = compute_vendor_risk(v)
    mutate(v, status='ACTIVE', _activated_at=t,
           next_monitoring_due_at=cycle['due_at'],
           composite_risk_score=score, tier_posture=posture)
    return ok(vendor_out(v))


@app.route('/tprm/vendors/<vid>/suspend', methods=['POST'])
@auth('RiskOfficer')
def suspend_vendor(vid):
    v = get_vendor(vid)
    if v['status'] != 'ACTIVE':
        err('ERR_VENDOR_NOT_ACTIVE', 409, 'Vendor is not ACTIVE.')
    t = now()
    eng_ids = {e['id'] for e in engagements.values() if e['vendor_id'] == vid}
    trig_a = any(i['severity'] == 'SEV_1' for i in vendor_open_incidents(vid))
    trig_b = any(c['vendor_id'] == vid and c['status'] == 'OVERDUE'
                 and t > c['due_at'] + timedelta(days=30)
                 for c in cycles.values())
    trig_c = (v['criticality_tier'] == 'TIER_1_CRITICAL' and any(
        b['engagement_id'] in eng_ids and b['status'] == 'FAILED'
        for b in bcp_tests.values()))
    if not (trig_a or trig_b or trig_c):
        err('ERR_INVALID_STATE', 409,
            'No suspension trigger condition is met.')
    mutate(v, status='SUSPENDED', next_monitoring_due_at=None)
    for e in engagements.values():
        if e['vendor_id'] == vid and e['lifecycle_status'] == 'ACTIVE':
            mutate(e, risk_attention_state='UNDER_REVIEW')
    return ok(vendor_out(v))


@app.route('/tprm/vendors/<vid>/reinstate', methods=['POST'])
@auth('RiskOfficer')
def reinstate_vendor(vid):
    v = get_vendor(vid)
    if v['status'] != 'SUSPENDED':
        err('ERR_VENDOR_NOT_SUSPENDED', 409, 'Vendor is not SUSPENDED.')
    if any(i['severity'] == 'SEV_1' for i in vendor_open_incidents(vid)):
        err('ERR_OPEN_SEV1_INCIDENT', 422,
            'Reinstatement blocked by an OPEN/REOPENED SEV_1 incident.')
    if any(c['vendor_id'] == vid and c['status'] == 'OVERDUE'
           for c in cycles.values()):
        err('ERR_INVALID_STATE', 409,
            'Reinstatement blocked by an OVERDUE monitoring cycle.')
    score, posture = compute_vendor_risk(v)
    live = open_cycle_for(v)
    if live is not None:
        next_due = live['due_at']
    else:
        next_due = schedule_cycle(v, now())['due_at']
    mutate(v, status='ACTIVE', next_monitoring_due_at=next_due,
           composite_risk_score=score, tier_posture=posture)
    return ok(vendor_out(v))


@app.route('/tprm/vendors/<vid>/exit', methods=['POST'])
@auth('RiskOfficer')
def exit_vendor(vid):
    v = get_vendor(vid)
    if v['status'] != 'ACTIVE':
        err('ERR_VENDOR_NOT_ACTIVE', 409, 'Vendor is not ACTIVE.')
    if any(e['vendor_id'] == vid and e['lifecycle_status'] not in
           ('EXITED', 'TERMINATED_FOR_CAUSE') for e in engagements.values()):
        err('ERR_ENGAGEMENTS_NOT_EXITED', 422,
            'All engagements must be EXITED or TERMINATED_FOR_CAUSE.')
    if vendor_open_incidents(vid):
        err('ERR_OPEN_INCIDENTS_REMAIN', 422,
            'Open incidents remain on the vendor.')
    mutate(v, status='EXITED', archived_at=now(), next_monitoring_due_at=None)
    return ok(vendor_out(v))


@app.route('/tprm/vendors/<vid>/tier-change', methods=['POST'])
@auth('RiskOfficer')
def tier_change(vid):
    v = get_vendor(vid)
    body = get_body()
    # OCC (priority 17) evaluated before payload validation (priority 19)
    evv = body.get('expected_vendor_version')
    if isinstance(evv, int) and not isinstance(evv, bool) \
            and evv != v['version']:
        err('ERR_STALE_VERSION', 412, 'expected_vendor_version is stale.')
    to_tier = req_enum(body, 'to_tier', TIERS)
    reason = req_str(body, 'reason')
    if not isinstance(evv, int) or isinstance(evv, bool):
        err('ERR_INVALID_REQUEST', 400,
            'expected_vendor_version is required and must be an integer.')
    from_tier = v['criticality_tier']
    row = base_entity(with_version=False)
    row.update({'vendor_id': vid, 'from_tier': from_tier, 'to_tier': to_tier,
                'reason': reason, 'changed_by_user_id': g_user()})
    tier_logs[row['id']] = row
    # Recompute next_monitoring_due_at from new cadence (PRD §3.11)
    if v['status'] == 'ACTIVE':
        done = [c for c in cycles.values()
                if c['vendor_id'] == vid and c['status'] in
                ('COMPLETED_ON_TIME', 'COMPLETED_LATE')]
        done.sort(key=lambda c: c['_seq'])
        anchor = done[-1]['completed_at'] if done else (
            v['_activated_at'] or v['created_at'])
        next_due = anchor.replace(microsecond=0) + timedelta(
            days=CADENCE[to_tier])
    else:
        next_due = None
    v['criticality_tier'] = to_tier  # risk compute needs the new tier
    score, posture = compute_vendor_risk(v)
    mutate(v, criticality_tier=to_tier, composite_risk_score=score,
           tier_posture=posture, next_monitoring_due_at=next_due)
    return ok(vendor_out(v))


@app.route('/tprm/vendors/<vid>/tier-change-log', methods=['GET'])
@auth('RiskOfficer', 'ComplianceDirector', 'InternalAuditor')
def tier_change_log(vid):
    get_vendor(vid)
    rows = [r for r in tier_logs.values() if r['vendor_id'] == vid]
    page, total, limit, offset = paginate(rows)
    return ok_list([log_out(r) for r in page], total, limit, offset)


# ------------------------------------------------------------ engagements
@app.route('/tprm/vendors/<vid>/engagements', methods=['POST'])
@auth('VendorRelationshipManager')
def create_engagement(vid):
    get_vendor(vid)
    body = get_body()
    code = body.get('engagement_code')
    if isinstance(code, str) and code:
        if any(e['vendor_id'] == vid and e['engagement_code'] == code
               for e in engagements.values()):
            err('ERR_DUPLICATE_KEY', 409,
                'engagement_code already in use for this vendor.')
    code = req_str(body, 'engagement_code')
    summary = req_str(body, 'service_summary', allow_empty=True)
    spend = req_int(body, 'annual_spend_cents', lo=0)
    sensitivity = req_enum(body, 'data_sensitivity', SENSITIVITIES)
    e = base_entity()
    e.update({
        'vendor_id': vid, 'engagement_code': code,
        'service_summary': summary, 'annual_spend_cents': spend,
        'data_sensitivity': sensitivity, 'lifecycle_status': 'DRAFT',
        'risk_attention_state': 'NORMAL',
        'started_by_user_id': g_user(), 'exit_readiness_score': None,
    })
    engagements[e['id']] = e
    return ok(engagement_out(e), 201)


@app.route('/tprm/vendors/<vid>/engagements', methods=['GET'])
@auth(*ALL_BUSINESS)
def list_engagements(vid):
    get_vendor(vid)
    items = [e for e in engagements.values() if e['vendor_id'] == vid]
    for field in ('lifecycle_status', 'risk_attention_state'):
        val = request.args.get(field)
        if val is not None:
            items = [e for e in items if e[field] == val]
    page, total, limit, offset = paginate(items)
    return ok_list([engagement_out(e) for e in page], total, limit, offset)


@app.route('/tprm/engagements/<eid>', methods=['GET'])
@auth(*ALL_BUSINESS)
def get_one_engagement(eid):
    return ok(engagement_out(get_engagement(eid)))


@app.route('/tprm/engagements/<eid>/initiate-exit', methods=['POST'])
@auth('VendorRelationshipManager')
def initiate_exit(eid):
    e = get_engagement(eid)
    if e['lifecycle_status'] != 'ACTIVE':
        err('ERR_ENGAGEMENT_NOT_ACTIVE', 409, 'Engagement is not ACTIVE.')
    if any(i['severity'] in ('SEV_1', 'SEV_2')
           for i in open_incidents_on_engagement(eid)):
        err('ERR_BLOCKING_INCIDENTS_OPEN', 422,
            'OPEN/REOPENED SEV_1/SEV_2 incidents block exit initiation.')
    score = compute_exit_readiness(e, vendors[e['vendor_id']])
    mutate(e, lifecycle_status='EXITING', exit_readiness_score=score)
    return ok(engagement_out(e))


@app.route('/tprm/engagements/<eid>/finalize-exit', methods=['POST'])
@auth('RiskOfficer')
def finalize_exit(eid):
    e = get_engagement(eid)
    if e['lifecycle_status'] != 'EXITING':
        err('ERR_ENGAGEMENT_NOT_EXITING', 409, 'Engagement is not EXITING.')
    if open_incidents_on_engagement(eid):
        err('ERR_OPEN_INCIDENTS_REMAIN', 422,
            'Open incidents remain on the engagement.')
    if e['exit_readiness_score'] is None or e['exit_readiness_score'] < 80.0:
        err('ERR_EXIT_READINESS_TOO_LOW', 422,
            'exit_readiness_score is below 80.00.')
    mutate(e, lifecycle_status='EXITED', risk_attention_state='NORMAL')
    return ok(engagement_out(e))


@app.route('/tprm/engagements/<eid>/terminate-for-cause', methods=['POST'])
@auth('RiskOfficer')
def terminate_for_cause(eid):
    e = get_engagement(eid)
    if e['lifecycle_status'] != 'ACTIVE':
        err('ERR_ENGAGEMENT_NOT_ACTIVE', 409, 'Engagement is not ACTIVE.')
    if not any(i['severity'] == 'SEV_1'
               for i in open_incidents_on_engagement(eid)):
        err('ERR_NO_SEV1_INCIDENT', 422,
            'Termination for cause requires an OPEN/REOPENED SEV_1 incident.')
    mutate(e, lifecycle_status='TERMINATED_FOR_CAUSE',
           risk_attention_state='REMEDIATION_REQUIRED')
    c = latest_contract(eid, status='EXECUTED')
    if c is not None:
        mutate(c, status='TERMINATED')
    return ok(engagement_out(e))
