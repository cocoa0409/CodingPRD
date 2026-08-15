"""Audit case endpoints (PRD section 3.6)."""
from flask import Blueprint, request

from db import db, base_fields
from errors import (ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST,
                    ERR_INVALID_DATE_RANGE, ERR_AUDIT_STATE_FORBIDS,
                    ERR_AUDIT_FINDING_REPORT_STATE)
from middleware import require_roles, body_json, req_str, req_month, is_int
from response import ok, ok_list
from services.core import (pub, touch, find_settlement, recalc_settlement,
                           recompute_arrears)
from services.validation import check_enum, paginate

bp = Blueprint('audits', __name__)

AUDIT_STATUSES = ('OPENED', 'FINDINGS_ISSUED', 'CLOSED')


def get_audit_or_404(aid):
    a = db.audits.get(aid)
    if a is None:
        raise ApiError(ERR_NOT_FOUND, 404, 'Audit case not found')
    return a


@bp.route('/concessions/audits', methods=['POST'])
def create_audit():
    require_roles('Auditor')
    body = body_json()
    lease_id = body.get('lease_id')
    if isinstance(lease_id, str) and lease_id not in db.leases:
        raise ApiError(ERR_NOT_FOUND, 404, 'Referenced lease does not exist')
    lease_id = req_str(body, 'lease_id')
    if lease_id not in db.leases:
        raise ApiError(ERR_NOT_FOUND, 404, 'Referenced lease does not exist')
    start = req_month(body, 'period_start_month')
    end = req_month(body, 'period_end_month')
    # Both bounds inclusive; the start must not be after the end.
    if start > end:
        raise ApiError(ERR_INVALID_DATE_RANGE, 422,
                       'period_start_month must not be after period_end_month')
    rec = base_fields()
    rec.update({
        'lease_id': lease_id,
        'period_start_month': start,
        'period_end_month': end,
        'status': 'OPENED',
        'understatement_cents': 0,
    })
    db.audits[rec['id']] = rec
    return ok(pub(rec), status=201)


@bp.route('/concessions/audits', methods=['GET'])
def list_audits():
    require_roles('AirportAdmin', 'ConcessionAnalyst', 'Auditor')
    items = sorted(db.audits.values(), key=lambda a: a['_seq'])
    f_lease = request.args.get('lease_id')
    f_status = request.args.get('status')
    if f_status is not None:
        check_enum(f_status, AUDIT_STATUSES, 'status')
    if f_lease is not None:
        items = [a for a in items if a['lease_id'] == f_lease]
    if f_status is not None:
        items = [a for a in items if a['status'] == f_status]
    page, meta = paginate(items)
    return ok_list([pub(a) for a in page], meta)


@bp.route('/concessions/audits/<aid>', methods=['GET'])
def get_audit(aid):
    require_roles('AirportAdmin', 'ConcessionAnalyst', 'Auditor')
    return ok(pub(get_audit_or_404(aid)))


@bp.route('/concessions/audits/<aid>/issue-findings', methods=['POST'])
def issue_findings(aid):
    require_roles('Auditor')
    audit = get_audit_or_404(aid)
    body = body_json()
    # Shape: findings is a required list of {report_id, restated_gross_sales_cents}.
    findings = body.get('findings')
    if not isinstance(findings, list):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       'Required field missing or malformed: findings')
    parsed = []
    for f in findings:
        if not isinstance(f, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, 'Each finding must be an object')
        # The finding pairs a report reference with the restated amount (PRD
        # 3.6); accept the reference under either natural key spelling.
        rid = f.get('sales_report_id')
        if rid is None:
            rid = f.get('report_id')
        amt = f.get('restated_gross_sales_cents')
        if not isinstance(rid, str) or rid == '':
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           'Each finding requires a sales_report_id')
        if not is_int(amt) or amt < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           'Each finding requires restated_gross_sales_cents >= 0')
        # Body FK existence for the referenced report.
        report = db.sales_reports.get(rid)
        if report is None:
            raise ApiError(ERR_NOT_FOUND, 404, 'Referenced report does not exist')
        parsed.append((report, amt))
    # Stage 6: findings are issued only from OPENED.
    if audit['status'] != 'OPENED':
        raise ApiError(ERR_AUDIT_STATE_FORBIDS, 409,
                       'Findings can be issued only while the audit is OPENED')
    # Every finding must reference an ACCEPTED report of the audit's lease,
    # inside the audited window. Validate all before applying any (atomicity).
    for report, _amt in parsed:
        if (report['status'] != 'ACCEPTED'
                or report['lease_id'] != audit['lease_id']
                or not (audit['period_start_month'] <= report['period_month']
                        <= audit['period_end_month'])):
            raise ApiError(ERR_AUDIT_FINDING_REPORT_STATE, 409,
                           'Finding must reference an ACCEPTED report of the '
                           "audit's lease within the audited window")
    # Apply the restatement cascade.
    understatement = 0
    years = set()
    for report, amt in parsed:
        report['status'] = 'ADJUSTED'
        report['restated_gross_sales_cents'] = amt
        touch(report)
        understatement += amt - report['gross_sales_cents']
        years.add(int(report['period_month'][:4]))
    audit['understatement_cents'] = understatement
    audit['status'] = 'FINDINGS_ISSUED'
    touch(audit)
    lease = db.leases[audit['lease_id']]
    # Owning settlement(s) recalculated under FINAL semantics; a PAID
    # settlement reopens to PARTIALLY_PAID when the amount due rises above
    # the amount paid. This reopen is the only way out of PAID.
    for year in years:
        st = find_settlement(audit['lease_id'], year)
        if st is None:
            continue
        was_paid = st['status'] == 'PAID'
        recalc_settlement(st, variant='FINAL')
        if was_paid and st['amount_due_cents'] > st['amount_paid_cents']:
            st['status'] = 'PARTIALLY_PAID'
    recompute_arrears(lease)
    return ok(pub(audit))


@bp.route('/concessions/audits/<aid>/close', methods=['POST'])
def close_audit(aid):
    require_roles('Auditor')
    audit = get_audit_or_404(aid)
    if audit['status'] not in ('OPENED', 'FINDINGS_ISSUED'):
        raise ApiError(ERR_AUDIT_STATE_FORBIDS, 409,
                       'Close is valid only from OPENED or FINDINGS_ISSUED')
    audit['status'] = 'CLOSED'
    touch(audit)
    return ok(pub(audit))
