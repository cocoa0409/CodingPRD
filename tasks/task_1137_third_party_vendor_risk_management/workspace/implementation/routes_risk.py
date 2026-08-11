"""ConcentrationAssessment, BusinessContinuityTest, AuditExercise/AuditFinding
and BoardReport routes."""
from decimal import Decimal, ROUND_HALF_UP

from flask import g, request

from core import (DIMENSIONS, SCENARIOS, SCOPES, SEVERITIES, app, auth,
                  assessment_out, assessments, audit_out, audits, base_entity,
                  bcp_out, bcp_tests, bucket_out, buckets, contracts, cycles,
                  engagements, err, finding_out, findings, get_body,
                  get_engagement, mutate, now, ok, ok_list, paginate, parse_dt,
                  raise_incident, recompute_vendor, report_out, board_reports,
                  req_dt, req_enum, req_int, req_str, vendors)

READ_ROLES = ('RiskOfficer', 'ComplianceDirector', 'InternalAuditor')
BCP_ROLES = ('VendorRelationshipManager', 'RiskOfficer', 'ComplianceDirector',
             'InternalAuditor')


def get_assessment(aid):
    a = assessments.get(aid)
    if a is None:
        err('ERR_NOT_FOUND', 404, 'Concentration assessment not found.')
    return a


def get_bcp(bid):
    b = bcp_tests.get(bid)
    if b is None:
        err('ERR_NOT_FOUND', 404, 'BCP test not found.')
    return b


def get_audit(aid):
    a = audits.get(aid)
    if a is None:
        err('ERR_NOT_FOUND', 404, 'Audit exercise not found.')
    return a


def get_finding(fid):
    f = findings.get(fid)
    if f is None:
        err('ERR_NOT_FOUND', 404, 'Audit finding not found.')
    return f


def get_report(rid):
    r = board_reports.get(rid)
    if r is None:
        err('ERR_NOT_FOUND', 404, 'Board report not found.')
    return r


# ------------------------------------------- concentration assessments
@app.route('/tprm/concentration-assessments', methods=['POST'])
@auth('ComplianceDirector')
def create_assessment():
    body = get_body()
    start = parse_dt(body.get('assessment_window_start'))
    end = parse_dt(body.get('assessment_window_end'))
    if start is not None and end is not None and not end > start:
        err('ERR_TEMPORAL_ORDER', 422,
            'assessment_window_end must be > assessment_window_start.')
    start = req_dt(body, 'assessment_window_start')
    end = req_dt(body, 'assessment_window_end')
    dim = req_enum(body, 'grouping_dimension', DIMENSIONS)
    a = base_entity()
    a.update({
        'assessment_window_start': start, 'assessment_window_end': end,
        'grouping_dimension': dim, 'status': 'COMPUTING',
        'computed_at': None, 'published_by_user_id': None,
        'breach_bucket_keys': [],
    })
    assessments[a['id']] = a
    return ok(assessment_out(a), 201)


@app.route('/tprm/concentration-assessments', methods=['GET'])
@auth(*READ_ROLES)
def list_assessments():
    items = list(assessments.values())
    for field in ('status', 'grouping_dimension'):
        val = request.args.get(field)
        if val is not None:
            items = [a for a in items if a[field] == val]
    page, total, limit, offset = paginate(items)
    return ok_list([assessment_out(a) for a in page], total, limit, offset)


@app.route('/tprm/concentration-assessments/<aid>', methods=['GET'])
@auth(*READ_ROLES)
def get_one_assessment(aid):
    return ok(assessment_out(get_assessment(aid)))


@app.route('/tprm/concentration-assessments/<aid>/publish', methods=['POST'])
@auth('ComplianceDirector')
def publish_assessment(aid):
    a = get_assessment(aid)
    if a['status'] != 'COMPUTING':
        err('ERR_ASSESSMENT_NOT_COMPUTING', 409,
            'Assessment is not COMPUTING.')
    dim = a['grouping_dimension']
    active = [e for e in engagements.values()
              if e['lifecycle_status'] == 'ACTIVE'
              and vendors[e['vendor_id']]['archived_at'] is None]
    grand = sum(e['annual_spend_cents'] for e in active)
    totals = {}
    for e in active:
        v = vendors[e['vendor_id']]
        key = v['headquarters_region'] if dim == 'REGION' \
            else v['service_category']
        totals[key] = totals.get(key, 0) + e['annual_spend_cents']
    rows = []
    for key, total in totals.items():
        if grand > 0:
            share_dec = (Decimal(total) * 100 / Decimal(grand)).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP)
        else:
            share_dec = Decimal('0.00')
        rows.append({'bucket_key': key, 'total_spend_cents': total,
                     'share_dec': share_dec,
                     'is_breach': share_dec >= Decimal('25.00')})
    rows.sort(key=lambda r: (-r['share_dec'], r['bucket_key']))
    breach_keys = []
    for r in rows:
        b = base_entity(with_version=False)
        b.update({'assessment_id': aid, 'bucket_key': r['bucket_key'],
                  'total_spend_cents': r['total_spend_cents'],
                  'share_pct': float(r['share_dec']),
                  'is_breach': r['is_breach']})
        buckets[b['id']] = b
        if r['is_breach']:
            breach_keys.append(r['bucket_key'])
    # Supersede prior PUBLISHED assessments on the same dimension.
    for other in assessments.values():
        if other['id'] != aid and other['grouping_dimension'] == dim \
                and other['status'] == 'PUBLISHED':
            mutate(other, status='SUPERSEDED')
    mutate(a, status='PUBLISHED', breach_bucket_keys=breach_keys,
           computed_at=now(), published_by_user_id=g.user_id)
    return ok(assessment_out(a))


@app.route('/tprm/concentration-assessments/<aid>/buckets', methods=['GET'])
@auth(*READ_ROLES)
def list_buckets(aid):
    get_assessment(aid)
    items = [b for b in buckets.values() if b['assessment_id'] == aid]
    items.sort(key=lambda b: (-Decimal(str(b['share_pct'])), b['bucket_key']))
    # stable ordering preserved; paginate without re-sorting by _seq
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
    page = items[offset:offset + limit]
    return ok_list([bucket_out(b) for b in page], total, limit, offset)


# ---------------------------------------------------------- BCP tests
@app.route('/tprm/engagements/<eid>/bcp-tests', methods=['POST'])
@auth('RiskOfficer')
def create_bcp(eid):
    get_engagement(eid)
    body = get_body()
    scheduled = parse_dt(body.get('scheduled_for'))
    if scheduled is not None and scheduled <= now():
        err('ERR_TEMPORAL_ORDER', 422,
            'scheduled_for must be in the future.')
    scheduled = req_dt(body, 'scheduled_for')
    scenario = req_enum(body, 'scenario', SCENARIOS)
    rto = req_int(body, 'rto_target_minutes', lo=1)
    rpo = req_int(body, 'rpo_target_minutes', lo=0)
    b = base_entity()
    b.update({
        'engagement_id': eid, 'scheduled_for': scheduled, 'scenario': scenario,
        'rto_target_minutes': rto, 'rpo_target_minutes': rpo,
        'actual_rto_minutes': None, 'actual_rpo_minutes': None,
        'status': 'SCHEDULED', 'outcome': None,
    })
    bcp_tests[b['id']] = b
    return ok(bcp_out(b), 201)


@app.route('/tprm/engagements/<eid>/bcp-tests', methods=['GET'])
@auth(*BCP_ROLES)
def list_bcps(eid):
    get_engagement(eid)
    items = [b for b in bcp_tests.values() if b['engagement_id'] == eid]
    for field in ('status', 'scenario'):
        val = request.args.get(field)
        if val is not None:
            items = [b for b in items if b[field] == val]
    page, total, limit, offset = paginate(items)
    return ok_list([bcp_out(b) for b in page], total, limit, offset)


@app.route('/tprm/bcp-tests/<bid>', methods=['GET'])
@auth(*BCP_ROLES)
def get_one_bcp(bid):
    return ok(bcp_out(get_bcp(bid)))


@app.route('/tprm/bcp-tests/<bid>/begin', methods=['POST'])
@auth('RiskOfficer')
def begin_bcp(bid):
    b = get_bcp(bid)
    if b['status'] != 'SCHEDULED':
        err('ERR_BCP_NOT_SCHEDULED', 409, 'BCP test is not SCHEDULED.')
    e = engagements[b['engagement_id']]
    if e['lifecycle_status'] != 'ACTIVE':
        err('ERR_ENGAGEMENT_NOT_ACTIVE', 409, 'Engagement is not ACTIVE.')
    mutate(b, status='IN_PROGRESS')
    return ok(bcp_out(b))


@app.route('/tprm/bcp-tests/<bid>/submit-result', methods=['POST'])
@auth('RiskOfficer')
def submit_bcp_result(bid):
    b = get_bcp(bid)
    if b['status'] != 'IN_PROGRESS':
        err('ERR_BCP_NOT_IN_PROGRESS', 409, 'BCP test is not IN_PROGRESS.')
    body = get_body()
    rto = req_int(body, 'actual_rto_minutes', lo=0)
    rpo = req_int(body, 'actual_rpo_minutes', lo=0)
    passed = rto <= b['rto_target_minutes'] and rpo <= b['rpo_target_minutes']
    e = engagements[b['engagement_id']]
    v = vendors[e['vendor_id']]
    mutate(b, status='PASSED' if passed else 'FAILED',
           outcome='PASS' if passed else 'FAIL',
           actual_rto_minutes=rto, actual_rpo_minutes=rpo)
    if not passed:
        if v['criticality_tier'] == 'TIER_1_CRITICAL':
            raise_incident(e, 'OUTAGE', 'SEV_2', 'system')
        recompute_vendor(v)
    return ok(bcp_out(b))


@app.route('/tprm/bcp-tests/<bid>/cancel', methods=['POST'])
@auth('RiskOfficer')
def cancel_bcp(bid):
    b = get_bcp(bid)
    if b['status'] != 'SCHEDULED':
        err('ERR_BCP_NOT_SCHEDULED', 409, 'BCP test is not SCHEDULED.')
    mutate(b, status='CANCELLED')
    return ok(bcp_out(b))


# ------------------------------------------------------------- audits
@app.route('/tprm/engagements/<eid>/audits', methods=['POST'])
@auth('InternalAuditor')
def create_audit(eid):
    e = get_engagement(eid)
    if g.user_id == e['started_by_user_id']:
        err('ERR_SOD_AUDITOR_IS_CREATOR', 403,
            'Auditor must differ from the engagement creator.')
    ex = [c for c in contracts.values() if c['engagement_id'] == eid
          and c['status'] == 'EXECUTED' and c['has_right_to_audit_clause']]
    if not ex:
        err('ERR_AUDIT_NO_RIGHT_TO_AUDIT', 422,
            'Engagement lacks an EXECUTED contract with right-to-audit.')
    if any(a['engagement_id'] == eid and a['status'] in
           ('INITIATED', 'FIELDWORK', 'FINDINGS_ISSUED')
           for a in audits.values()):
        err('ERR_AUDIT_ALREADY_ACTIVE', 422,
            'An audit is already active on this engagement.')
    body = get_body()
    scope = req_enum(body, 'scope', SCOPES)
    a = base_entity()
    a.update({
        'engagement_id': eid, 'scope': scope,
        'exercised_by_user_id': g.user_id, 'initiated_at': now(),
        'findings_count': 0, 'status': 'INITIATED', 'closed_at': None,
    })
    audits[a['id']] = a
    return ok(audit_out(a), 201)


@app.route('/tprm/engagements/<eid>/audits', methods=['GET'])
@auth(*READ_ROLES)
def list_audits(eid):
    get_engagement(eid)
    items = [a for a in audits.values() if a['engagement_id'] == eid]
    val = request.args.get('status')
    if val is not None:
        items = [a for a in items if a['status'] == val]
    page, total, limit, offset = paginate(items)
    return ok_list([audit_out(a) for a in page], total, limit, offset)


@app.route('/tprm/audits/<aid>', methods=['GET'])
@auth(*READ_ROLES)
def get_one_audit(aid):
    return ok(audit_out(get_audit(aid)))


@app.route('/tprm/audits/<aid>/begin-fieldwork', methods=['POST'])
@auth('InternalAuditor')
def begin_fieldwork(aid):
    a = get_audit(aid)
    if a['status'] != 'INITIATED':
        err('ERR_AUDIT_NOT_INITIATED', 409, 'Audit is not INITIATED.')
    mutate(a, status='FIELDWORK')
    return ok(audit_out(a))


@app.route('/tprm/audits/<aid>/findings', methods=['POST'])
@auth('InternalAuditor')
def add_finding(aid):
    a = get_audit(aid)
    if a['status'] != 'FIELDWORK':
        err('ERR_AUDIT_NOT_FIELDWORK', 409, 'Audit is not in FIELDWORK.')
    body = get_body()
    severity = req_enum(body, 'severity', SEVERITIES)
    description = req_str(body, 'description', allow_empty=True)
    f = base_entity(with_version=False)
    f.update({'audit_exercise_id': aid, 'severity': severity,
              'description': description, 'raised_incident_id': None})
    findings[f['id']] = f
    mutate(a, findings_count=a['findings_count'] + 1)
    return ok(finding_out(f), 201)


@app.route('/tprm/audits/<aid>/findings', methods=['GET'])
@auth(*READ_ROLES)
def list_audit_findings(aid):
    get_audit(aid)
    items = [f for f in findings.values() if f['audit_exercise_id'] == aid]
    val = request.args.get('severity')
    if val is not None:
        items = [f for f in items if f['severity'] == val]
    page, total, limit, offset = paginate(items)
    return ok_list([finding_out(f) for f in page], total, limit, offset)


@app.route('/tprm/audit-findings', methods=['GET'])
@auth(*READ_ROLES)
def list_all_findings():
    items = list(findings.values())
    for field in ('audit_exercise_id', 'severity', 'raised_incident_id'):
        val = request.args.get(field)
        if val is not None:
            items = [f for f in items if f[field] == val]
    page, total, limit, offset = paginate(items)
    return ok_list([finding_out(f) for f in page], total, limit, offset)


@app.route('/tprm/audit-findings/<fid>', methods=['GET'])
@auth(*READ_ROLES)
def get_one_finding(fid):
    return ok(finding_out(get_finding(fid)))


@app.route('/tprm/audits/<aid>/issue-findings', methods=['POST'])
@auth('InternalAuditor')
def issue_findings(aid):
    a = get_audit(aid)
    if a['status'] != 'FIELDWORK':
        err('ERR_AUDIT_NOT_FIELDWORK', 409, 'Audit is not in FIELDWORK.')
    e = engagements[a['engagement_id']]
    v = vendors[e['vendor_id']]
    raised = False
    for f in sorted((f for f in findings.values()
                     if f['audit_exercise_id'] == aid),
                    key=lambda f: f['_seq']):
        if f['severity'] in ('SEV_1', 'SEV_2'):
            inc = raise_incident(e, 'REGULATORY_FINDING', f['severity'],
                                 'system')
            f['raised_incident_id'] = inc['id']
            raised = True
    mutate(a, status='FINDINGS_ISSUED')
    if raised:
        recompute_vendor(v)
    return ok(audit_out(a))


@app.route('/tprm/audits/<aid>/close', methods=['POST'])
@auth('InternalAuditor')
def close_audit(aid):
    a = get_audit(aid)
    if a['status'] != 'FINDINGS_ISSUED':
        err('ERR_AUDIT_NOT_FINDINGS_ISSUED', 409,
            'Audit is not FINDINGS_ISSUED.')
    from core import incidents
    for f in findings.values():
        if f['audit_exercise_id'] == aid and f['raised_incident_id']:
            inc = incidents.get(f['raised_incident_id'])
            if inc is not None and inc['status'] != 'CLOSED':
                err('ERR_AUDIT_FINDINGS_UNRESOLVED', 422,
                    'Auto-raised incidents are not all CLOSED.')
    mutate(a, status='CLOSED', closed_at=now())
    return ok(audit_out(a))


# -------------------------------------------------------- board reports
@app.route('/tprm/board-reports', methods=['POST'])
@auth('ComplianceDirector')
def create_report():
    body = get_body()
    ps = parse_dt(body.get('period_start'))
    pe = parse_dt(body.get('period_end'))
    if ps is not None and pe is not None and not pe > ps:
        err('ERR_TEMPORAL_ORDER', 422, 'period_end must be > period_start.')
    if ps is not None and pe is not None:
        for r in board_reports.values():
            if r['status'] == 'PUBLISHED' and ps < r['period_end'] \
                    and r['period_start'] < pe:
                err('ERR_REPORT_WINDOW_OVERLAP', 422,
                    'Window overlaps a PUBLISHED board report.')
    ps = req_dt(body, 'period_start')
    pe = req_dt(body, 'period_end')
    r = base_entity()
    r.update({'period_start': ps, 'period_end': pe, 'status': 'DRAFT',
              'snapshot_payload': None, 'published_at': None,
              'published_by_user_id': None})
    board_reports[r['id']] = r
    return ok(report_out(r), 201)


@app.route('/tprm/board-reports', methods=['GET'])
@auth(*READ_ROLES)
def list_reports():
    items = list(board_reports.values())
    val = request.args.get('status')
    if val is not None:
        items = [r for r in items if r['status'] == val]
    page, total, limit, offset = paginate(items)
    return ok_list([report_out(r) for r in page], total, limit, offset)


@app.route('/tprm/board-reports/<rid>', methods=['GET'])
@auth(*READ_ROLES)
def get_one_report(rid):
    return ok(report_out(get_report(rid)))


def _count_by(items, field):
    out = {}
    for it in items:
        out[it[field]] = out.get(it[field], 0) + 1
    return out


@app.route('/tprm/board-reports/<rid>/publish', methods=['POST'])
@auth('ComplianceDirector')
def publish_report(rid):
    r = get_report(rid)
    if r['status'] != 'DRAFT':
        err('ERR_REPORT_NOT_DRAFT', 409, 'Report is not DRAFT.')
    from core import incidents
    ps, pe = r['period_start'], r['period_end']
    live_vendors = [v for v in vendors.values() if v['archived_at'] is None]
    breaches = 0
    for dim in ('REGION', 'SERVICE_CATEGORY'):
        pubs = [a for a in assessments.values()
                if a['grouping_dimension'] == dim and a['status'] == 'PUBLISHED']
        pubs.sort(key=lambda a: a['_seq'])
        if pubs:
            breaches += len(pubs[-1]['breach_bucket_keys'])
    hist = {'0-15': 0, '15-40': 0, '40-70': 0, '70-100': 0}
    for v in live_vendors:
        s = v['composite_risk_score']
        if s < 15:
            hist['0-15'] += 1
        elif s < 40:
            hist['15-40'] += 1
        elif s < 70:
            hist['40-70'] += 1
        else:
            hist['70-100'] += 1
    snapshot = {
        'vendor_count_by_tier': _count_by(live_vendors, 'criticality_tier'),
        'vendor_count_by_posture': _count_by(live_vendors, 'tier_posture'),
        'engagement_count_by_lifecycle': _count_by(list(engagements.values()),
                                                   'lifecycle_status'),
        'incidents_opened_in_window': sum(
            1 for i in incidents.values() if ps <= i['detected_at'] < pe),
        'incidents_closed_in_window': sum(
            1 for i in incidents.values()
            if i['closed_at'] is not None and ps <= i['closed_at'] < pe),
        'overdue_monitoring_cycles_at_publish': sum(
            1 for c in cycles.values() if c['status'] == 'OVERDUE'),
        'concentration_breaches_active': breaches,
        'bcp_failures_in_window': sum(
            1 for b in bcp_tests.values()
            if b['status'] == 'FAILED' and ps <= b['updated_at'] < pe),
        'composite_risk_score_distribution': hist,
    }
    mutate(r, status='PUBLISHED', snapshot_payload=snapshot,
           published_at=now(), published_by_user_id=g.user_id)
    return ok(report_out(r))
