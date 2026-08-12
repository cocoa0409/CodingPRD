"""Incident and RemediationPlan routes."""
from datetime import timedelta

from flask import g, request

from core import (INCIDENT_TYPES, SEVERITIES, SEVERITY_WINDOW_DAYS, app, auth,
                  base_entity, engagements, err, get_body, get_engagement,
                  incident_out, incidents, latest_contract, mutate, now, ok,
                  ok_list, open_incidents_on_engagement, paginate, parse_dt,
                  plan_out, plans, raise_incident, recompute_vendor, req_dt,
                  req_enum, req_str, vendors)

INCIDENT_ROLES = ('VendorRelationshipManager', 'RiskOfficer',
                  'ComplianceDirector', 'InternalAuditor', 'BusinessUnitOwner')


def get_incident(iid):
    i = incidents.get(iid)
    if i is None:
        err('ERR_NOT_FOUND', 404, 'Incident not found.')
    return i


def get_plan(pid):
    p = plans.get(pid)
    if p is None:
        err('ERR_NOT_FOUND', 404, 'Remediation plan not found.')
    return p


# ------------------------------------------------------ incidents
@app.route('/tprm/engagements/<eid>/incidents', methods=['POST'])
@auth('BusinessUnitOwner')
def create_incident(eid):
    get_engagement(eid)
    body = get_body()
    itype = req_enum(body, 'incident_type', INCIDENT_TYPES)
    severity = req_enum(body, 'severity', SEVERITIES)
    detected = req_dt(body, 'detected_at')
    inc = raise_incident(engagements[eid], itype, severity, g.user_id,
                         detected_at=detected)
    recompute_vendor(vendors[engagements[eid]['vendor_id']])
    return ok(incident_out(inc), 201)


@app.route('/tprm/engagements/<eid>/incidents', methods=['GET'])
@auth(*INCIDENT_ROLES)
def list_incidents(eid):
    get_engagement(eid)
    items = [i for i in incidents.values() if i['engagement_id'] == eid]
    for field in ('status', 'severity', 'incident_type'):
        val = request.args.get(field)
        if val is not None:
            items = [i for i in items if i[field] == val]
    page, total, limit, offset = paginate(items)
    return ok_list([incident_out(i) for i in page], total, limit, offset)


@app.route('/tprm/incidents/<iid>', methods=['GET'])
@auth(*INCIDENT_ROLES)
def get_one_incident(iid):
    return ok(incident_out(get_incident(iid)))


@app.route('/tprm/incidents/<iid>/triage', methods=['POST'])
@auth('RiskOfficer')
def triage_incident(iid):
    inc = get_incident(iid)
    if inc['status'] != 'OPEN':
        err('ERR_INCIDENT_NOT_OPEN', 409, 'Incident is not OPEN.')
    e = engagements[inc['engagement_id']]
    v = vendors[e['vendor_id']]
    window = SEVERITY_WINDOW_DAYS[inc['severity']]
    ex = latest_contract(inc['engagement_id'], status='EXECUTED')
    if ex is not None:
        window = min(window, ex['breach_cure_window_days'])
    due = (now() + timedelta(days=window)).replace(microsecond=0)
    mutate(inc, status='TRIAGED', remediation_due_at=due)
    if e['risk_attention_state'] == 'NORMAL':
        mutate(e, risk_attention_state='UNDER_REVIEW')
    recompute_vendor(v)
    return ok(incident_out(inc))


@app.route('/tprm/incidents/<iid>/reopen', methods=['POST'])
@auth('BusinessUnitOwner')
def reopen_incident(iid):
    inc = get_incident(iid)
    if inc['status'] != 'CLOSED':
        err('ERR_INCIDENT_NOT_CLOSED', 409, 'Incident is not CLOSED.')
    if g.user_id != inc['reported_by_user_id']:
        err('ERR_SOD_REOPEN_NOT_REPORTER', 403,
            'Only the original reporter may reopen this incident.')
    if inc['reopen_count'] >= 2:
        err('ERR_REOPEN_LIMIT_REACHED', 422, 'Reopen limit (2) reached.')
    mutate(inc, status='REOPENED', reopen_count=inc['reopen_count'] + 1,
           closed_at=None)
    e = engagements[inc['engagement_id']]
    if e['risk_attention_state'] != 'UNDER_REVIEW':
        mutate(e, risk_attention_state='UNDER_REVIEW')
    recompute_vendor(vendors[e['vendor_id']])
    return ok(incident_out(inc))


# -------------------------------------------------- remediation plans
@app.route('/tprm/incidents/<iid>/remediation-plans', methods=['POST'])
@auth('RiskOfficer')
def create_plan(iid):
    inc = get_incident(iid)
    if inc['status'] != 'TRIAGED':
        err('ERR_INCIDENT_NOT_TRIAGED', 409, 'Incident is not TRIAGED.')
    if g.user_id == inc['reported_by_user_id']:
        err('ERR_SOD_INCIDENT_SELF_REMEDIATE', 403,
            'Plan owner must differ from the incident reporter.')
    body = get_body()
    committed = parse_dt(body.get('committed_completion_date'))
    if committed is not None and inc['remediation_due_at'] is not None \
            and committed > inc['remediation_due_at']:
        err('ERR_TEMPORAL_ORDER', 422,
            'committed_completion_date must be <= remediation_due_at.')
    summary = req_str(body, 'plan_summary', allow_empty=True)
    committed = req_dt(body, 'committed_completion_date')
    p = base_entity()
    p.update({
        'incident_id': iid, 'plan_summary': summary,
        'committed_completion_date': committed,
        'owner_user_id': g.user_id, 'verification_evidence_uri': None,
        'status': 'DRAFT', 'approved_by_user_id': None,
    })
    plans[p['id']] = p
    mutate(inc, status='REMEDIATION_PLANNED')
    return ok(plan_out(p), 201)


@app.route('/tprm/incidents/<iid>/remediation-plans', methods=['GET'])
@auth(*INCIDENT_ROLES)
def list_plans(iid):
    get_incident(iid)
    items = [p for p in plans.values() if p['incident_id'] == iid]
    val = request.args.get('status')
    if val is not None:
        items = [p for p in items if p['status'] == val]
    page, total, limit, offset = paginate(items)
    return ok_list([plan_out(p) for p in page], total, limit, offset)


@app.route('/tprm/remediation-plans/<pid>', methods=['GET'])
@auth(*INCIDENT_ROLES)
def get_one_plan(pid):
    return ok(plan_out(get_plan(pid)))


@app.route('/tprm/remediation-plans/<pid>/submit', methods=['POST'])
@auth('RiskOfficer')
def submit_plan(pid):
    p = get_plan(pid)
    if p['status'] != 'DRAFT':
        err('ERR_PLAN_NOT_DRAFT', 409, 'Plan is not DRAFT.')
    mutate(p, status='SUBMITTED')
    return ok(plan_out(p))


@app.route('/tprm/remediation-plans/<pid>/approve', methods=['POST'])
@auth('RiskOfficer')
def approve_plan(pid):
    p = get_plan(pid)
    inc = incidents[p['incident_id']]
    if p['status'] != 'SUBMITTED':
        err('ERR_PLAN_NOT_SUBMITTED', 409, 'Plan is not SUBMITTED.')
    if g.user_id == p['owner_user_id'] \
            or g.user_id == inc['reported_by_user_id']:
        err('ERR_SOD_PLAN_SELF_APPROVE', 403,
            'Approver must differ from plan owner and incident reporter.')
    # Atomic two-step: SUBMITTED -> APPROVED -> IN_EXECUTION.
    mutate(p, status='IN_EXECUTION', approved_by_user_id=g.user_id)
    mutate(inc, status='REMEDIATION_IN_PROGRESS')
    return ok(plan_out(p))


@app.route('/tprm/remediation-plans/<pid>/reject', methods=['POST'])
@auth('RiskOfficer')
def reject_plan(pid):
    p = get_plan(pid)
    if p['status'] != 'SUBMITTED':
        err('ERR_PLAN_NOT_SUBMITTED', 409, 'Plan is not SUBMITTED.')
    if g.user_id == p['owner_user_id']:
        err('ERR_SOD_PLAN_SELF_APPROVE', 403,
            'Rejector must differ from the plan owner.')
    mutate(p, status='REJECTED')
    inc = incidents[p['incident_id']]
    mutate(inc, status='TRIAGED')
    return ok(plan_out(p))


@app.route('/tprm/remediation-plans/<pid>/submit-verification',
           methods=['POST'])
@auth('RiskOfficer')
def submit_verification(pid):
    p = get_plan(pid)
    if p['status'] != 'IN_EXECUTION':
        err('ERR_PLAN_NOT_IN_EXECUTION', 409, 'Plan is not IN_EXECUTION.')
    body = get_body()
    evidence = body.get('verification_evidence_uri')
    if not isinstance(evidence, str) or evidence == '':
        err('ERR_EVIDENCE_REQUIRED', 422,
            'verification_evidence_uri is required.')
    mutate(p, status='VERIFICATION_SUBMITTED',
           verification_evidence_uri=evidence)
    inc = incidents[p['incident_id']]
    mutate(inc, status='AWAITING_VERIFICATION')
    return ok(plan_out(p))


@app.route('/tprm/remediation-plans/<pid>/verify', methods=['POST'])
@auth('BusinessUnitOwner')
def verify_plan(pid):
    p = get_plan(pid)
    inc = incidents[p['incident_id']]
    if p['status'] != 'VERIFICATION_SUBMITTED':
        err('ERR_PLAN_NOT_VERIFICATION_SUBMITTED', 409,
            'Plan is not VERIFICATION_SUBMITTED.')
    if g.user_id != inc['reported_by_user_id']:
        err('ERR_SOD_VERIFY_NOT_REPORTER', 403,
            'Only the original incident reporter may verify.')
    mutate(p, status='VERIFIED')
    mutate(inc, status='CLOSED', closed_at=now())
    e = engagements[inc['engagement_id']]
    if not open_incidents_on_engagement(e['id']) \
            and e['risk_attention_state'] != 'NORMAL':
        mutate(e, risk_attention_state='NORMAL')
    recompute_vendor(vendors[e['vendor_id']])
    return ok(plan_out(p))
