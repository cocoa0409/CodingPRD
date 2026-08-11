"""DueDiligencePackage and Contract routes."""
from flask import g, request

from core import (app, auth, base_entity, contract_out, contracts, dd_compute,
                  dd_out, dd_packages, engagements, err, fourth_parties,
                  get_body, get_engagement, latest_approved_dd, mutate, ok,
                  ok_list, paginate, parse_dt, recompute_vendor, req_bool,
                  req_dt, req_int, req_num, req_str, vendors)

DD_ROLES = ('VendorRelationshipManager', 'RiskOfficer', 'ComplianceDirector',
            'InternalAuditor')


def get_package(pid):
    p = dd_packages.get(pid)
    if p is None:
        err('ERR_NOT_FOUND', 404, 'Due-diligence package not found.')
    return p


def get_contract(cid):
    c = contracts.get(cid)
    if c is None:
        err('ERR_NOT_FOUND', 404, 'Contract not found.')
    return c


# ---------------------------------------------------- DD packages
@app.route('/tprm/engagements/<eid>/due-diligence-packages', methods=['POST'])
@auth('VendorRelationshipManager')
def create_dd_package(eid):
    e = get_engagement(eid)
    if e['lifecycle_status'] != 'DRAFT':
        err('ERR_ENGAGEMENT_NOT_DRAFT', 409, 'Engagement is not DRAFT.')
    body = get_body()
    fin = req_int(body, 'financial_review_score', lo=0, hi=100)
    sec = req_int(body, 'security_review_score', lo=0, hi=100)
    comp = req_int(body, 'compliance_review_score', lo=0, hi=100)
    fin_r = req_str(body, 'financial_reviewer_id')
    sec_r = req_str(body, 'security_reviewer_id')
    comp_r = req_str(body, 'compliance_reviewer_id')
    p = base_entity()
    p.update({
        'engagement_id': eid, 'financial_review_score': fin,
        'security_review_score': sec, 'compliance_review_score': comp,
        'financial_reviewer_id': fin_r, 'security_reviewer_id': sec_r,
        'compliance_reviewer_id': comp_r, 'aggregate_dd_score': None,
        'dd_outcome': 'PENDING', 'status': 'DRAFT',
        'submitted_by_user_id': None, 'approver_user_id': None,
        'review_round': 1,
    })
    dd_packages[p['id']] = p
    mutate(e, lifecycle_status='DD_IN_PROGRESS')
    return ok(dd_out(p), 201)


@app.route('/tprm/engagements/<eid>/due-diligence-packages', methods=['GET'])
@auth(*DD_ROLES)
def list_dd_packages(eid):
    get_engagement(eid)
    items = [p for p in dd_packages.values() if p['engagement_id'] == eid]
    val = request.args.get('status')
    if val is not None:
        items = [p for p in items if p['status'] == val]
    page, total, limit, offset = paginate(items)
    return ok_list([dd_out(p) for p in page], total, limit, offset)


@app.route('/tprm/due-diligence-packages/<pid>', methods=['GET'])
@auth(*DD_ROLES)
def get_one_dd_package(pid):
    return ok(dd_out(get_package(pid)))


@app.route('/tprm/due-diligence-packages/<pid>/submit', methods=['POST'])
@auth('VendorRelationshipManager')
def submit_dd_package(pid):
    p = get_package(pid)
    if p['status'] != 'DRAFT' or p['financial_review_score'] is None \
            or p['security_review_score'] is None \
            or p['compliance_review_score'] is None:
        err('ERR_DD_NOT_DRAFT', 409, 'Package is not DRAFT with all scores.')
    e = engagements[p['engagement_id']]
    v = vendors[e['vendor_id']]
    score, outcome = dd_compute(p, v['criticality_tier'])
    mutate(p, status='SUBMITTED', submitted_by_user_id=g.user_id,
           aggregate_dd_score=score, dd_outcome=outcome)
    return ok(dd_out(p))


@app.route('/tprm/due-diligence-packages/<pid>/begin-review', methods=['POST'])
@auth('RiskOfficer')
def begin_review_dd_package(pid):
    p = get_package(pid)
    if p['status'] != 'SUBMITTED':
        err('ERR_DD_NOT_SUBMITTED', 409, 'Package is not SUBMITTED.')
    mutate(p, status='UNDER_REVIEW')
    return ok(dd_out(p))


@app.route('/tprm/due-diligence-packages/<pid>/approve', methods=['POST'])
@auth('RiskOfficer')
def approve_dd_package(pid):
    p = get_package(pid)
    e = engagements[p['engagement_id']]
    if p['status'] != 'UNDER_REVIEW':
        err('ERR_DD_NOT_UNDER_REVIEW', 409, 'Package is not UNDER_REVIEW.')
    if g.user_id == p['submitted_by_user_id']:
        err('ERR_SOD_DD_SELF_APPROVE', 403,
            'Approver must differ from the submitter.')
    if p['dd_outcome'] not in ('PASS', 'CONDITIONAL_PASS'):
        err('ERR_DD_OUTCOME_FAIL', 422, 'DD outcome does not permit approval.')
    body = get_body()
    eev = body.get('expected_engagement_version')
    if isinstance(eev, int) and not isinstance(eev, bool) \
            and eev != e['version']:
        err('ERR_STALE_VERSION', 412, 'expected_engagement_version is stale.')
    if not isinstance(eev, int) or isinstance(eev, bool):
        err('ERR_INVALID_REQUEST', 400,
            'expected_engagement_version is required and must be an integer.')
    mutate(p, status='APPROVED', approver_user_id=g.user_id)
    for other in dd_packages.values():
        if other['engagement_id'] == p['engagement_id'] \
                and other['id'] != p['id'] and other['status'] == 'APPROVED' \
                and other['_seq'] < p['_seq']:
            mutate(other, status='SUPERSEDED')
    if e['lifecycle_status'] == 'DD_IN_PROGRESS':
        mutate(e, lifecycle_status='DD_APPROVED')
    else:
        mutate(e)  # approval still bumps the engagement version by 1
    return ok(dd_out(p))


@app.route('/tprm/due-diligence-packages/<pid>/reject', methods=['POST'])
@auth('RiskOfficer')
def reject_dd_package(pid):
    p = get_package(pid)
    if p['status'] != 'UNDER_REVIEW':
        err('ERR_DD_NOT_UNDER_REVIEW', 409, 'Package is not UNDER_REVIEW.')
    if g.user_id == p['submitted_by_user_id']:
        err('ERR_SOD_DD_SELF_APPROVE', 403,
            'Rejector must differ from the submitter.')
    mutate(p, status='REJECTED')
    return ok(dd_out(p))


@app.route('/tprm/due-diligence-packages/<pid>/resubmit', methods=['POST'])
@auth('VendorRelationshipManager')
def resubmit_dd_package(pid):
    p = get_package(pid)
    if p['status'] != 'REJECTED':
        err('ERR_DD_NOT_REJECTED', 409, 'Package is not REJECTED.')
    if p['review_round'] >= 3:
        err('ERR_DD_REVIEW_ROUND_EXHAUSTED', 422,
            'Review round cap (3) reached.')
    body = get_body()
    updates = {}
    for field in ('financial_review_score', 'security_review_score',
                  'compliance_review_score'):
        if field in body and body[field] is not None:
            v = body[field]
            if isinstance(v, bool) or not isinstance(v, int) \
                    or v < 0 or v > 100:
                err('ERR_INVALID_REQUEST', 400,
                    '%s must be an integer between 0 and 100.' % field)
            updates[field] = v
    e = engagements[p['engagement_id']]
    vendor = vendors[e['vendor_id']]
    merged = dict(p)
    merged.update(updates)
    score, outcome = dd_compute(merged, vendor['criticality_tier'])
    updates.update({
        'status': 'SUBMITTED', 'review_round': p['review_round'] + 1,
        'submitted_by_user_id': g.user_id,
        'aggregate_dd_score': score, 'dd_outcome': outcome,
    })
    mutate(p, **updates)
    return ok(dd_out(p))


# ------------------------------------------------------ contracts
@app.route('/tprm/engagements/<eid>/contracts', methods=['POST'])
@auth('VendorRelationshipManager')
def create_contract(eid):
    e = get_engagement(eid)
    if e['lifecycle_status'] != 'DD_APPROVED':
        err('ERR_DD_NOT_APPROVED', 409, 'Engagement is not DD_APPROVED.')
    body = get_body()
    # Temporal order (priority 10) before uniqueness (18) and payload (19)
    eff = parse_dt(body.get('effective_date'))
    exp = parse_dt(body.get('expiry_date'))
    if eff is not None and exp is not None and not exp > eff:
        err('ERR_TEMPORAL_ORDER', 422, 'expiry_date must be > effective_date.')
    ref = body.get('contract_reference')
    if isinstance(ref, str) and ref:
        vid = e['vendor_id']
        eng_ids = {x['id'] for x in engagements.values()
                   if x['vendor_id'] == vid}
        if any(c['engagement_id'] in eng_ids and c['contract_reference'] == ref
               for c in contracts.values()):
            err('ERR_DUPLICATE_KEY', 409,
                'contract_reference already in use for this vendor.')
    ref = req_str(body, 'contract_reference')
    eff = req_dt(body, 'effective_date')
    exp = req_dt(body, 'expiry_date')
    rta = req_bool(body, 'has_right_to_audit_clause')
    sla = req_bool(body, 'has_sla_terms')
    exit_plan = req_bool(body, 'has_exit_plan_section')
    uptime = req_num(body, 'sla_uptime_pct', lo=90.0, hi=100.0)
    cure = req_int(body, 'breach_cure_window_days', lo=1)
    notice = req_int(body, 'renewal_notice_days', lo=0)
    c = base_entity()
    c.update({
        'engagement_id': eid, 'contract_reference': ref,
        'effective_date': eff, 'expiry_date': exp,
        'has_right_to_audit_clause': rta, 'has_sla_terms': sla,
        'has_exit_plan_section': exit_plan, 'sla_uptime_pct': uptime,
        'breach_cure_window_days': cure, 'renewal_notice_days': notice,
        'status': 'DRAFT', 'version_pin_dd_package_id': None,
    })
    contracts[c['id']] = c
    mutate(e, lifecycle_status='CONTRACTING')
    return ok(contract_out(c), 201)


@app.route('/tprm/engagements/<eid>/contracts', methods=['GET'])
@auth(*DD_ROLES)
def list_contracts(eid):
    get_engagement(eid)
    items = [c for c in contracts.values() if c['engagement_id'] == eid]
    val = request.args.get('status')
    if val is not None:
        items = [c for c in items if c['status'] == val]
    page, total, limit, offset = paginate(items)
    return ok_list([contract_out(c) for c in page], total, limit, offset)


@app.route('/tprm/contracts', methods=['GET'])
@auth(*DD_ROLES)
def list_all_contracts():
    items = list(contracts.values())
    for field in ('engagement_id', 'status', 'version_pin_dd_package_id'):
        val = request.args.get(field)
        if val is not None:
            items = [c for c in items if c[field] == val]
    page, total, limit, offset = paginate(items)
    return ok_list([contract_out(c) for c in page], total, limit, offset)


@app.route('/tprm/contracts/<cid>', methods=['GET'])
@auth(*DD_ROLES)
def get_one_contract(cid):
    return ok(contract_out(get_contract(cid)))


@app.route('/tprm/contracts/<cid>/execute', methods=['POST'])
@auth('RiskOfficer')
def execute_contract(cid):
    c = get_contract(cid)
    e = engagements[c['engagement_id']]
    v = vendors[e['vendor_id']]
    if c['status'] != 'DRAFT':
        err('ERR_CONTRACT_NOT_DRAFT', 409, 'Contract is not DRAFT.')
    if not c['has_sla_terms']:
        err('ERR_MISSING_SLA_TERMS', 422, 'SLA terms are required.')
    if v['criticality_tier'] in ('TIER_1_CRITICAL', 'TIER_2_HIGH') \
            and not c['has_right_to_audit_clause']:
        err('ERR_MISSING_AUDIT_CLAUSE', 422,
            'Right-to-audit clause is required for this tier.')
    if v['criticality_tier'] == 'TIER_1_CRITICAL' \
            and not c['has_exit_plan_section']:
        err('ERR_MISSING_EXIT_PLAN', 422,
            'Exit-plan section is required for TIER_1_CRITICAL.')
    if any(f['engagement_id'] == c['engagement_id']
           and f['acknowledgement_status'] != 'ACKNOWLEDGED'
           for f in fourth_parties.values()):
        err('ERR_FOURTH_PARTY_PENDING', 422,
            'All fourth parties must be ACKNOWLEDGED before execution.')
    body = get_body()
    eev = body.get('expected_engagement_version')
    if isinstance(eev, int) and not isinstance(eev, bool) \
            and eev != e['version']:
        err('ERR_STALE_VERSION', 412, 'expected_engagement_version is stale.')
    if not isinstance(eev, int) or isinstance(eev, bool):
        err('ERR_INVALID_REQUEST', 400,
            'expected_engagement_version is required and must be an integer.')
    pin = latest_approved_dd(c['engagement_id'])
    mutate(c, status='EXECUTED',
           version_pin_dd_package_id=pin['id'] if pin else None)
    mutate(e, lifecycle_status='ACTIVE')
    recompute_vendor(v)
    return ok(contract_out(c))
