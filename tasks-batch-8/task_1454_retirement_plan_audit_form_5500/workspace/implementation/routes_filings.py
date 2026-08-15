"""Service provider fees, Form 5500 filings, schedule entries, extensions,
correction program filings."""
from flask import Blueprint, g, request

from auth import roles_allowed
from dates import parse_date
from domain import (active_extension, any_fee_reportable, extended_due_date,
                    filing_of, original_due_dates, recompute_posture,
                    recompute_provider_flags, refresh_filing, DFVCP_CAP_LARGE_CENTS,
                    DFVCP_CAP_SMALL_CENTS, DFVCP_PER_DAY_CENTS)
from envelope import success_list, success_object
from errors import (ERR_AMENDMENT_NOT_ALLOWED, ERR_AUDIT_REPORT_MISSING,
                    ERR_DFVCP_FILING_REQUIRED, ERR_ENGAGEMENT_BLOCKED,
                    ERR_EXTENSION_ALREADY_EXISTS, ERR_EXTENSION_EXPIRED,
                    ERR_FILING_ALREADY_EXISTS, ERR_FILING_DEADLINE_PASSED,
                    ERR_FOREIGN_REFERENCE, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_SCHEDULE_INCOMPLETE,
                    ERR_SCHEDULE_NOT_VERIFIED, ERR_SOD,
                    ERR_STALE_FILING_VERSION, raise_err)
from store import base_fields, public, store, touch
from validate import (get_body, opt, opt_bool, paginate, parse_bool_param,
                      parse_pagination, req_date, req_enum, req_int, req_str,
                      sorted_created)

bp = Blueprint('filings', __name__)

SERVICE_CODES = ('RECORDKEEPING', 'INVESTMENT_MANAGEMENT', 'LEGAL', 'AUDIT',
                 'CONSULTING', 'TPA', 'CUSTODIAL', 'OTHER')
COMP_TYPES = ('DIRECT', 'INDIRECT', 'ELIGIBLE_INDIRECT')
SCHEDULE_TYPES = ('H', 'I', 'C', 'A')
PROGRAMS = ('VFCP', 'EPCRS_SCP', 'EPCRS_VCP', 'EPCRS_AUDIT_CAP', 'DFVCP')


def get_filing_or_404(fid):
    f = store.filings.get(fid)
    if f is None:
        raise_err(ERR_NOT_FOUND, 'Filing %s not found' % fid)
    return f


def get_entry_or_404(sid):
    s = store.schedule_entries.get(sid)
    if s is None:
        raise_err(ERR_NOT_FOUND, 'Schedule entry %s not found' % sid)
    return s


def get_extension_or_404(eid):
    e = store.extensions.get(eid)
    if e is None:
        raise_err(ERR_NOT_FOUND, 'Filing extension %s not found' % eid)
    return e


def get_cpf_or_404(cid):
    c = store.correction_filings.get(cid)
    if c is None:
        raise_err(ERR_NOT_FOUND, 'Correction program filing %s not found' % cid)
    return c


# --- service provider fees ---------------------------------------------------------
@bp.route('/plan-audit/service-provider-fees', methods=['POST'])
@roles_allowed('SponsorAdmin')
def create_fee():
    body = get_body()
    engagement_id = req_str(body, 'engagement_id')
    provider_name = req_str(body, 'provider_name')
    service_code = req_enum(body, 'service_code', SERVICE_CODES)
    comp_type = req_enum(body, 'compensation_type', COMP_TYPES)
    amount = req_int(body, 'amount_cents', 1)
    if store.engagements.get(engagement_id) is None:
        raise_err(ERR_NOT_FOUND, 'Engagement %s not found' % engagement_id)
    f = base_fields()
    f.update({
        'engagement_id': engagement_id,
        'provider_name': provider_name,
        'service_code': service_code,
        'compensation_type': comp_type,
        'amount_cents': amount,
        'reportable_on_schedule_c': False,
    })
    store.fees[f['id']] = f
    recompute_provider_flags(engagement_id, provider_name)
    return success_object(public(f), status=201)


@bp.route('/plan-audit/service-provider-fees', methods=['GET'])
@roles_allowed('Any')
def list_fees():
    limit, offset = parse_pagination()
    items = sorted_created(store.fees.values())
    for param, field in (('engagement_id', 'engagement_id'),
                         ('provider_name', 'provider_name'),
                         ('service_code', 'service_code')):
        v = request.args.get(param)
        if v is not None:
            items = [f for f in items if f.get(field) == v]
    reportable = parse_bool_param('reportable_on_schedule_c')
    if reportable is not None:
        items = [f for f in items if f['reportable_on_schedule_c'] == reportable]
    page, total = paginate(items, limit, offset)
    return success_list([public(f) for f in page], total, limit, offset)


@bp.route('/plan-audit/service-provider-fees/<fid>', methods=['GET'])
@roles_allowed('Any')
def get_fee(fid):
    f = store.fees.get(fid)
    if f is None:
        raise_err(ERR_NOT_FOUND, 'Service provider fee %s not found' % fid)
    return success_object(public(f))


# --- Form 5500 filings ---------------------------------------------------------------
@bp.route('/plan-audit/filings', methods=['POST'])
@roles_allowed('TPASpecialist')
def create_filing():
    body = get_body()
    engagement_id = req_str(body, 'engagement_id')
    eng = store.engagements.get(engagement_id)
    if eng is None:
        raise_err(ERR_NOT_FOUND, 'Engagement %s not found' % engagement_id)
    if filing_of(engagement_id) is not None:
        raise_err(ERR_FILING_ALREADY_EXISTS,
                  'A Form5500Filing already exists for this engagement')
    raw, rolled = original_due_dates(eng)
    f = base_fields()
    f.update({
        'engagement_id': engagement_id,
        'status': 'DRAFT',
        'is_amendment': False,
        'created_by_user_id': g.user_id,
        'original_due_date': rolled.isoformat(),
        'effective_due_date': rolled.isoformat(),
        'filed_date': None,
        'is_late': False,
        'penalty_cents': 0,
        'has_active_extension': False,
        '_original_due_date_raw': raw.isoformat(),
        '_amendment_cycle': False,
    })
    store.filings[f['id']] = f
    recompute_posture(eng)
    return success_object(public(f), status=201)


@bp.route('/plan-audit/filings', methods=['GET'])
@roles_allowed('Any')
def list_filings():
    limit, offset = parse_pagination()
    items = sorted_created(store.filings.values())
    for f in items:
        refresh_filing(f)
    engagement_id = request.args.get('engagement_id')
    status = request.args.get('status')
    if engagement_id is not None:
        items = [f for f in items if f['engagement_id'] == engagement_id]
    if status is not None:
        items = [f for f in items if f['status'] == status]
    page, total = paginate(items, limit, offset)
    return success_list([public(f) for f in page], total, limit, offset)


@bp.route('/plan-audit/filings/<fid>', methods=['GET'])
@roles_allowed('Any')
def get_filing(fid):
    f = get_filing_or_404(fid)
    refresh_filing(f)
    return success_object(public(f))


def _required_schedule_types(filing):
    eng = store.engagements.get(filing['engagement_id'])
    required = []
    if eng is not None and eng['required_schedule_type'] is not None:
        required.append(eng['required_schedule_type'])
    elif eng is None or eng['required_schedule_type'] is None:
        required.append(None)  # count never computed -> unsatisfiable member
    if any_fee_reportable(filing['engagement_id']):
        required.append('C')
    if eng is not None and eng['funding_arrangement'] in ('INSURANCE', 'SPLIT'):
        required.append('A')
    return required


@bp.route('/plan-audit/filings/<fid>/mark_schedules_complete', methods=['POST'])
@roles_allowed('TPASpecialist')
def mark_schedules_complete(fid):
    f = get_filing_or_404(fid)
    if f['status'] not in ('DRAFT', 'AMENDED_DRAFT'):
        raise_err(ERR_INVALID_STATE,
                  'Filing in %s cannot be marked schedules-complete' % f['status'])
    required = _required_schedule_types(f)
    entries = [s for s in store.schedule_entries.values() if s['filing_id'] == fid]
    for rtype in required:
        if rtype is None or not any(s['schedule_type'] == rtype for s in entries):
            raise_err(ERR_SCHEDULE_INCOMPLETE,
                      'Required schedule type %s has no entries' % (rtype or '(uncomputed)'))
    for rtype in required:
        for s in entries:
            if s['schedule_type'] == rtype and s['status'] not in ('VERIFIED', 'LOCKED'):
                raise_err(ERR_SCHEDULE_NOT_VERIFIED,
                          'A required schedule entry is still %s' % s['status'])
    f['status'] = 'SCHEDULES_COMPLETE'
    touch(f)
    return success_object(public(f))


@bp.route('/plan-audit/filings/<fid>/mark_ready', methods=['POST'])
@roles_allowed('EngagementManager')
def mark_ready(fid):
    f = get_filing_or_404(fid)
    if f['status'] != 'SCHEDULES_COMPLETE':
        raise_err(ERR_INVALID_STATE,
                  'Filing in %s cannot be marked ready' % f['status'])
    eng = store.engagements.get(f['engagement_id'])
    if eng is not None:
        recompute_posture(eng)
        if eng['posture'] == 'BLOCKED':
            raise_err(ERR_ENGAGEMENT_BLOCKED,
                      'Engagement posture BLOCKED gates filing readiness')
    if g.user_id == f['created_by_user_id']:
        raise_err(ERR_SOD, 'Filing creator cannot mark their own filing ready')
    f['status'] = 'READY_TO_FILE'
    touch(f)
    return success_object(public(f))


@bp.route('/plan-audit/filings/<fid>/submit', methods=['POST'])
@roles_allowed('EngagementManager')
def submit_filing(fid):
    f = get_filing_or_404(fid)
    if f['status'] != 'READY_TO_FILE':
        raise_err(ERR_INVALID_STATE, 'Only a READY_TO_FILE filing can be submitted')
    body = get_body()
    late_with_dfvcp = opt_bool(body, 'late_with_dfvcp', False)
    eng = store.engagements.get(f['engagement_id'])
    # Preconditions in the pinned order of PRD section 3.9.
    if eng is None or eng['status'] != 'REPORT_ISSUED':
        raise_err(ERR_INVALID_STATE,
                  'Engagement must be in REPORT_ISSUED to submit the filing')
    if eng['audit_required'] is True and not eng['auditor_report_ref']:
        raise_err(ERR_AUDIT_REPORT_MISSING,
                  'Audit-required engagement must attach the IQPA audit report')
    refresh_filing(f)
    today = store.clock_date()
    effective = parse_date(f['effective_due_date'])
    if today > effective and not late_with_dfvcp:
        raise_err(ERR_FILING_DEADLINE_PASSED,
                  'Filing deadline has passed; resubmit with late_with_dfvcp')
    if late_with_dfvcp:
        has_dfvcp = any(c['engagement_id'] == f['engagement_id']
                        and c['program'] == 'DFVCP'
                        for c in store.correction_filings.values())
        if not has_dfvcp:
            raise_err(ERR_DFVCP_FILING_REQUIRED,
                      'late_with_dfvcp requires an existing DFVCP correction program filing')
    f['filed_date'] = today.isoformat()
    f['is_late'] = today > effective
    if f['is_late'] and late_with_dfvcp:
        days_late = (today - effective).days
        raw = DFVCP_PER_DAY_CENTS * days_late
        cap = (DFVCP_CAP_SMALL_CENTS if eng['required_schedule_type'] == 'I'
               else DFVCP_CAP_LARGE_CENTS)
        f['penalty_cents'] = min(raw, cap)
    f['status'] = 'FILED'
    if f['_amendment_cycle']:
        f['is_amendment'] = True
    touch(f)
    for s in store.schedule_entries.values():
        if s['filing_id'] == fid and s['status'] == 'VERIFIED':
            s['status'] = 'LOCKED'
            touch(s)
    ext = active_extension(f)
    if ext is not None and ext['status'] == 'GRANTED':
        ext['status'] = 'USED'
        touch(ext)
        refresh_filing(f)
    recompute_posture(eng)
    return success_object(public(f))


@bp.route('/plan-audit/filings/<fid>/record_disposition', methods=['POST'])
@roles_allowed('System')
def record_disposition(fid):
    f = get_filing_or_404(fid)
    body = get_body()
    outcome = req_enum(body, 'outcome', ('ACCEPTED', 'REJECTED'))
    if f['status'] != 'FILED':
        raise_err(ERR_INVALID_STATE, 'Only a FILED filing can receive a disposition')
    f['status'] = outcome
    touch(f)
    eng = store.engagements.get(f['engagement_id'])
    if eng is not None:
        recompute_posture(eng)
    return success_object(public(f))


@bp.route('/plan-audit/filings/<fid>/reopen', methods=['POST'])
@roles_allowed('TPASpecialist')
def reopen_filing(fid):
    f = get_filing_or_404(fid)
    if f['status'] != 'REJECTED':
        raise_err(ERR_INVALID_STATE, 'Only a REJECTED filing can be reopened')
    f['status'] = 'DRAFT'
    touch(f)
    return success_object(public(f))


@bp.route('/plan-audit/filings/<fid>/amendments', methods=['POST'])
@roles_allowed('TPASpecialist')
def amend_filing(fid):
    f = get_filing_or_404(fid)
    body = get_body()
    expected = req_int(body, 'expected_filing_version')
    req_str(body, 'amendment_reason')
    if expected != f['version']:
        raise_err(ERR_STALE_FILING_VERSION,
                  'Filing version has advanced; re-read before amending')
    if f['status'] != 'ACCEPTED':
        raise_err(ERR_AMENDMENT_NOT_ALLOWED,
                  'Only an ACCEPTED filing can be amended')
    f['status'] = 'AMENDED_DRAFT'
    f['_amendment_cycle'] = True
    touch(f)
    return success_object(public(f))


# --- schedule entries ------------------------------------------------------------------
def _check_fee_refs(filing, payload):
    """payload.service_provider_fee_ids must exist and belong to the filing's engagement."""
    if not isinstance(payload, dict):
        return
    ids = payload.get('service_provider_fee_ids')
    if ids is None:
        return
    if not isinstance(ids, list):
        raise_err(ERR_INVALID_REQUEST, 'service_provider_fee_ids must be an array')
    for fee_id in ids:
        fee = store.fees.get(fee_id)
        if fee is None:
            raise_err(ERR_NOT_FOUND, 'Service provider fee %s not found' % fee_id)
        if fee['engagement_id'] != filing['engagement_id']:
            raise_err(ERR_FOREIGN_REFERENCE,
                      'Fee %s belongs to a different engagement' % fee_id)


@bp.route('/plan-audit/schedule-entries', methods=['POST'])
@roles_allowed('TPASpecialist')
def create_schedule_entry():
    body = get_body()
    filing_id = req_str(body, 'filing_id')
    schedule_type = req_enum(body, 'schedule_type', SCHEDULE_TYPES)
    line_item = req_str(body, 'line_item')
    amount = req_int(body, 'amount_cents', 0)
    payload = body.get('payload')
    if payload is not None and not isinstance(payload, dict):
        raise_err(ERR_INVALID_REQUEST, 'payload must be an object')
    filing = store.filings.get(filing_id)
    if filing is None:
        raise_err(ERR_NOT_FOUND, 'Filing %s not found' % filing_id)
    _check_fee_refs(filing, payload)
    s = base_fields()
    s.update({
        'filing_id': filing_id,
        'schedule_type': schedule_type,
        'line_item': line_item,
        'amount_cents': amount,
        'payload': payload,
        'status': 'DRAFT',
    })
    store.schedule_entries[s['id']] = s
    return success_object(public(s), status=201)


@bp.route('/plan-audit/schedule-entries', methods=['GET'])
@roles_allowed('Any')
def list_schedule_entries():
    limit, offset = parse_pagination()
    items = sorted_created(store.schedule_entries.values())
    for param, field in (('filing_id', 'filing_id'),
                         ('schedule_type', 'schedule_type'), ('status', 'status')):
        v = request.args.get(param)
        if v is not None:
            items = [s for s in items if s.get(field) == v]
    page, total = paginate(items, limit, offset)
    return success_list([public(s) for s in page], total, limit, offset)


@bp.route('/plan-audit/schedule-entries/<sid>', methods=['GET'])
@roles_allowed('Any')
def get_schedule_entry(sid):
    return success_object(public(get_entry_or_404(sid)))


@bp.route('/plan-audit/schedule-entries/<sid>/verify', methods=['POST'])
@roles_allowed('PlanAuditor')
def verify_schedule_entry(sid):
    s = get_entry_or_404(sid)
    if s['status'] != 'DRAFT':
        raise_err(ERR_INVALID_STATE, 'Only a DRAFT schedule entry can be verified')
    filing = store.filings.get(s['filing_id'])
    if filing is None or filing['status'] not in ('DRAFT', 'SCHEDULES_COMPLETE',
                                                 'AMENDED_DRAFT'):
        raise_err(ERR_INVALID_STATE,
                  'Filing in %s does not allow verification' % (filing and filing['status']))
    _check_fee_refs(filing, s.get('payload'))
    s['status'] = 'VERIFIED'
    touch(s)
    return success_object(public(s))


# --- filing extensions (Form 5558) ------------------------------------------------------
@bp.route('/plan-audit/filing-extensions', methods=['POST'])
@roles_allowed('TPASpecialist')
def create_extension():
    body = get_body()
    filing_id = req_str(body, 'filing_id')
    filed = req_date(body, 'filed_date')
    filing = store.filings.get(filing_id)
    if filing is None:
        raise_err(ERR_NOT_FOUND, 'Filing %s not found' % filing_id)
    if filing['status'] in ('FILED', 'ACCEPTED'):
        raise_err(ERR_INVALID_STATE,
                  'Cannot extend a filing already %s' % filing['status'])
    if store.clock_date() > parse_date(filing['original_due_date']):
        raise_err(ERR_EXTENSION_EXPIRED,
                  'Form 5558 must be filed by the original due date')
    if any(e['status'] == 'GRANTED' for e in store.extensions.values()
           if e['filing_id'] == filing_id):
        raise_err(ERR_EXTENSION_ALREADY_EXISTS,
                  'An active (GRANTED) extension already exists for this filing')
    raw_original = parse_date(filing['_original_due_date_raw'])
    ext = base_fields()
    ext.update({
        'filing_id': filing_id,
        'filed_date': filed.isoformat(),
        'extended_due_date': extended_due_date(raw_original).isoformat(),
        'status': 'GRANTED',
    })
    store.extensions[ext['id']] = ext
    refresh_filing(filing)
    eng = store.engagements.get(filing['engagement_id'])
    if eng is not None:
        recompute_posture(eng)
    return success_object(public(ext), status=201)


@bp.route('/plan-audit/filing-extensions', methods=['GET'])
@roles_allowed('Any')
def list_extensions():
    limit, offset = parse_pagination()
    items = sorted_created(store.extensions.values())
    filing_id = request.args.get('filing_id')
    status = request.args.get('status')
    if filing_id is not None:
        items = [e for e in items if e['filing_id'] == filing_id]
    if status is not None:
        items = [e for e in items if e['status'] == status]
    page, total = paginate(items, limit, offset)
    return success_list([public(e) for e in page], total, limit, offset)


@bp.route('/plan-audit/filing-extensions/<eid>', methods=['GET'])
@roles_allowed('Any')
def get_extension(eid):
    return success_object(public(get_extension_or_404(eid)))


# --- DOL/IRS correction program filings ---------------------------------------------------
@bp.route('/plan-audit/correction-program-filings', methods=['POST'])
@roles_allowed('EngagementManager')
def create_correction_filing():
    body = get_body()
    engagement_id = req_str(body, 'engagement_id')
    program = req_enum(body, 'program', PROGRAMS)
    linked = body.get('linked_finding_ids')
    if linked is None or not isinstance(linked, list):
        raise_err(ERR_INVALID_REQUEST, 'linked_finding_ids must be an array')
    fee = req_int(body, 'government_fee_cents', 0)
    if store.engagements.get(engagement_id) is None:
        raise_err(ERR_NOT_FOUND, 'Engagement %s not found' % engagement_id)
    for fid_ in linked:
        fnd = store.findings.get(fid_)
        if fnd is None or fnd['engagement_id'] != engagement_id:
            raise_err(ERR_NOT_FOUND,
                      'Finding %s not found in this engagement' % fid_)
    c = base_fields()
    c.update({
        'engagement_id': engagement_id,
        'program': program,
        'linked_finding_ids': list(linked),
        'government_fee_cents': fee,
        'status': 'DRAFTED',
    })
    store.correction_filings[c['id']] = c
    return success_object(public(c), status=201)


@bp.route('/plan-audit/correction-program-filings', methods=['GET'])
@roles_allowed('Any')
def list_correction_filings():
    limit, offset = parse_pagination()
    items = sorted_created(store.correction_filings.values())
    for param, field in (('engagement_id', 'engagement_id'),
                         ('program', 'program'), ('status', 'status')):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c.get(field) == v]
    linked = request.args.get('linked_finding_ids')
    if linked is not None:
        items = [c for c in items if linked in c['linked_finding_ids']]
    page, total = paginate(items, limit, offset)
    return success_list([public(c) for c in page], total, limit, offset)


@bp.route('/plan-audit/correction-program-filings/<cid>', methods=['GET'])
@roles_allowed('Any')
def get_correction_filing(cid):
    return success_object(public(get_cpf_or_404(cid)))


@bp.route('/plan-audit/correction-program-filings/<cid>/submit', methods=['POST'])
@roles_allowed('EngagementManager')
def submit_correction_filing(cid):
    c = get_cpf_or_404(cid)
    if c['status'] not in ('DRAFTED', 'REJECTED'):
        raise_err(ERR_INVALID_STATE,
                  'Program filing in %s cannot be submitted' % c['status'])
    for fid_ in c['linked_finding_ids']:
        fnd = store.findings.get(fid_)
        if fnd is None or fnd['status'] not in ('CORRECTED', 'VERIFIED_CLOSED'):
            raise_err(ERR_INVALID_STATE,
                      'All linked findings must be CORRECTED or VERIFIED_CLOSED')
    c['status'] = 'SUBMITTED'
    touch(c)
    return success_object(public(c))


@bp.route('/plan-audit/correction-program-filings/<cid>/record_decision', methods=['POST'])
@roles_allowed('System')
def record_decision(cid):
    c = get_cpf_or_404(cid)
    body = get_body()
    outcome = req_enum(body, 'outcome', ('APPROVED', 'REJECTED', 'WITHDRAWN'))
    if outcome in ('APPROVED', 'REJECTED'):
        if c['status'] != 'SUBMITTED':
            raise_err(ERR_INVALID_STATE,
                      'Only a SUBMITTED program filing can be %s' % outcome)
    else:  # WITHDRAWN
        if c['status'] != 'DRAFTED':
            raise_err(ERR_INVALID_STATE,
                      'Only a DRAFTED program filing can be withdrawn')
    c['status'] = outcome
    touch(c)
    return success_object(public(c))
