"""FourthParty and MonitoringCycle routes."""
from flask import g, request

from core import (DATA_ACCESS, app, auth, base_entity, compute_vendor_risk,
                  cycle_out, cycles, engagements, err, fourth_parties, fp_out,
                  get_body, get_engagement, get_vendor, mutate, now, ok,
                  ok_list, paginate, recompute_vendor, req_enum, req_str,
                  schedule_cycle, vendors)

FP_ROLES = ('VendorRelationshipManager', 'RiskOfficer', 'ComplianceDirector',
            'InternalAuditor')


def get_fp(fid):
    f = fourth_parties.get(fid)
    if f is None:
        err('ERR_NOT_FOUND', 404, 'Fourth party not found.')
    return f


def get_cycle(cid):
    c = cycles.get(cid)
    if c is None:
        err('ERR_NOT_FOUND', 404, 'Monitoring cycle not found.')
    return c


# ------------------------------------------------- fourth parties
@app.route('/tprm/engagements/<eid>/fourth-parties', methods=['POST'])
@auth('VendorRelationshipManager')
def create_fp(eid):
    e = get_engagement(eid)
    body = get_body()
    # Referential check on parent link (priority 14) before payload (19)
    parent_id = body.get('parent_fourth_party_id')
    if parent_id is not None:
        parent = fourth_parties.get(parent_id) if isinstance(parent_id, str) \
            else None
        if parent is None or parent['engagement_id'] != eid:
            err('ERR_FP_PARENT_INVALID', 422,
                'parent_fourth_party_id must reference a fourth party on the '
                'same engagement.')
        # Cycle-freedom: walk the ancestor chain.
        seen, cursor = set(), parent
        while cursor is not None:
            if cursor['id'] in seen:
                err('ERR_FP_PARENT_INVALID', 422,
                    'Fourth-party chain must be cycle-free.')
            seen.add(cursor['id'])
            nxt = cursor['parent_fourth_party_id']
            cursor = fourth_parties.get(nxt) if nxt else None
    name = req_str(body, 'name')
    service = req_str(body, 'service_provided', allow_empty=True)
    level = req_enum(body, 'data_access_level', DATA_ACCESS)
    if parent_id is not None and not isinstance(parent_id, str):
        err('ERR_INVALID_REQUEST', 400,
            'parent_fourth_party_id must be a string or null.')
    f = base_entity()
    f.update({
        'engagement_id': eid, 'name': name, 'service_provided': service,
        'parent_fourth_party_id': parent_id, 'data_access_level': level,
        'acknowledgement_status': 'PENDING', 'acknowledged_by_user_id': None,
    })
    fourth_parties[f['id']] = f
    return ok(fp_out(f), 201)


@app.route('/tprm/engagements/<eid>/fourth-parties', methods=['GET'])
@auth(*FP_ROLES)
def list_fps(eid):
    get_engagement(eid)
    items = [f for f in fourth_parties.values() if f['engagement_id'] == eid]
    for field in ('acknowledgement_status', 'data_access_level'):
        val = request.args.get(field)
        if val is not None:
            items = [f for f in items if f[field] == val]
    page, total, limit, offset = paginate(items)
    return ok_list([fp_out(f) for f in page], total, limit, offset)


@app.route('/tprm/fourth-parties', methods=['GET'])
@auth(*FP_ROLES)
def list_all_fps():
    items = list(fourth_parties.values())
    for field in ('engagement_id', 'acknowledgement_status',
                  'data_access_level', 'parent_fourth_party_id'):
        val = request.args.get(field)
        if val is not None:
            items = [f for f in items if f[field] == val]
    page, total, limit, offset = paginate(items)
    return ok_list([fp_out(f) for f in page], total, limit, offset)


@app.route('/tprm/fourth-parties/<fid>', methods=['GET'])
@auth(*FP_ROLES)
def get_one_fp(fid):
    return ok(fp_out(get_fp(fid)))


@app.route('/tprm/fourth-parties/<fid>/acknowledge', methods=['POST'])
@auth('RiskOfficer')
def acknowledge_fp(fid):
    f = get_fp(fid)
    if f['acknowledgement_status'] != 'PENDING':
        err('ERR_FP_NOT_PENDING', 409, 'Fourth party is not PENDING.')
    e = engagements[f['engagement_id']]
    v = vendors[e['vendor_id']]
    if f['data_access_level'] == 'REGULATED_PII' and v['criticality_tier'] \
            not in ('TIER_1_CRITICAL', 'TIER_2_HIGH'):
        err('ERR_FP_PII_TIER_TOO_LOW', 422,
            'REGULATED_PII access requires a TIER_1/TIER_2 vendor.')
    mutate(f, acknowledgement_status='ACKNOWLEDGED',
           acknowledged_by_user_id=g.user_id)
    return ok(fp_out(f))


@app.route('/tprm/fourth-parties/<fid>/reject', methods=['POST'])
@auth('RiskOfficer')
def reject_fp(fid):
    f = get_fp(fid)
    if f['acknowledgement_status'] != 'PENDING':
        err('ERR_FP_NOT_PENDING', 409, 'Fourth party is not PENDING.')
    mutate(f, acknowledgement_status='REJECTED')
    e = engagements[f['engagement_id']]
    if e['risk_attention_state'] != 'UNDER_REVIEW':
        mutate(e, risk_attention_state='UNDER_REVIEW')
    return ok(fp_out(f))


# ------------------------------------------------- monitoring cycles
@app.route('/tprm/vendors/<vid>/monitoring-cycles', methods=['GET'])
@auth(*FP_ROLES)
def list_cycles(vid):
    get_vendor(vid)
    items = [c for c in cycles.values() if c['vendor_id'] == vid]
    val = request.args.get('status')
    if val is not None:
        items = [c for c in items if c['status'] == val]
    page, total, limit, offset = paginate(items)
    return ok_list([cycle_out(c) for c in page], total, limit, offset)


@app.route('/tprm/monitoring-cycles/<cid>', methods=['GET'])
@auth(*FP_ROLES)
def get_one_cycle(cid):
    return ok(cycle_out(get_cycle(cid)))


@app.route('/tprm/monitoring-cycles/<cid>/begin', methods=['POST'])
@auth('RiskOfficer')
def begin_cycle(cid):
    c = get_cycle(cid)
    if c['status'] != 'SCHEDULED':
        err('ERR_CYCLE_NOT_SCHEDULED', 409, 'Cycle is not SCHEDULED.')
    v = vendors[c['vendor_id']]
    if v['status'] != 'ACTIVE':
        err('ERR_VENDOR_NOT_ACTIVE', 409, 'Vendor is not ACTIVE.')
    mutate(c, status='IN_PROGRESS')
    return ok(cycle_out(c))


@app.route('/tprm/monitoring-cycles/<cid>/complete', methods=['POST'])
@auth('RiskOfficer')
def complete_cycle(cid):
    c = get_cycle(cid)
    if c['status'] != 'IN_PROGRESS':
        err('ERR_CYCLE_NOT_IN_PROGRESS', 409, 'Cycle is not IN_PROGRESS.')
    body = get_body()
    findings_summary = body.get('findings_summary')
    if findings_summary is not None and not isinstance(findings_summary, str):
        err('ERR_INVALID_REQUEST', 400, 'findings_summary must be a string.')
    t = now()
    status = 'COMPLETED_ON_TIME' if t <= c['due_at'] else 'COMPLETED_LATE'
    mutate(c, status=status, completed_at=t, findings_summary=findings_summary)
    v = vendors[c['vendor_id']]
    if v['status'] == 'ACTIVE':
        nxt = schedule_cycle(v, t)
        if status == 'COMPLETED_LATE':
            score, posture = compute_vendor_risk(v)
            mutate(v, next_monitoring_due_at=nxt['due_at'],
                   composite_risk_score=score, tier_posture=posture)
        else:
            mutate(v, next_monitoring_due_at=nxt['due_at'])
    else:
        if status == 'COMPLETED_LATE':
            recompute_vendor(v)
    return ok(cycle_out(c))


@app.route('/tprm/monitoring-cycles/<cid>/waive', methods=['POST'])
@auth('ComplianceDirector')
def waive_cycle(cid):
    c = get_cycle(cid)
    if c['status'] != 'SCHEDULED':
        err('ERR_CYCLE_NOT_SCHEDULED', 409, 'Cycle is not SCHEDULED.')
    v = vendors[c['vendor_id']]
    if v['criticality_tier'] != 'TIER_4_LOW':
        err('ERR_WAIVE_TIER_FORBIDDEN', 422,
            'Only TIER_4_LOW vendor cycles may be waived.')
    mutate(c, status='WAIVED', waived_by_user_id=g.user_id)
    # Next cycle is anchored to the waived cycle's due_at (PRD §3.7).
    nxt = schedule_cycle(v, c['due_at'])
    if v['status'] == 'ACTIVE':
        mutate(v, next_monitoring_due_at=nxt['due_at'])
    return ok(cycle_out(c))
