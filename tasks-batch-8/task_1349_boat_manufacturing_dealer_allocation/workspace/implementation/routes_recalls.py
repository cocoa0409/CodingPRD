"""Recall campaigns (draft/issue with fan-out) and notices (plant remedy)."""
from flask import Blueprint, request

from store import DB, CLOCK, fmt_dt, new_rec, serialize, touch
from services import remedy_notice
from util import (ApiError, respond, list_response, auth_context, require_roles,
                  json_body, need, as_str, as_int, as_enum, invalid,
                  get_or_404)

bp = Blueprint('recalls', __name__)

SEVERITIES = {'SAFETY_STOP', 'SAFETY_STANDARD', 'EMISSIONS'}


# ---------------------------------------------------------------- campaigns
@bp.post('/recall-campaigns')
def create_campaign():
    uid, role = auth_context()
    require_roles(role, 'ComplianceOfficer')
    data = json_body()
    code = as_str(need(data, 'campaign_code'), 'campaign_code')
    severity = as_enum(need(data, 'severity'), 'severity', SEVERITIES)
    model_code = as_str(need(data, 'model_code'), 'model_code')
    model_year = as_int(need(data, 'model_year'), 'model_year')
    start = as_int(need(data, 'hin_serial_start'), 'hin_serial_start')
    end = as_int(need(data, 'hin_serial_end'), 'hin_serial_end')
    if start < 1:
        invalid('hin_serial_start must be >= 1')
    if end < start:
        invalid('hin_serial_end must be >= hin_serial_start')
    if any(c['campaign_code'] == code for c in DB['campaigns'].values()):
        invalid('campaign_code must be unique across RecallCampaign')
    rec = new_rec({
        'campaign_code': code,
        'severity': severity,
        'model_code': model_code,
        'model_year': model_year,
        'hin_serial_start': start,
        'hin_serial_end': end,
        'status': 'DRAFT',
        'issued_at': None,
        'notice_count': 0,
        'open_notice_count': 0,
    })
    DB['campaigns'][rec['id']] = rec
    return respond(serialize(rec), 201)


@bp.get('/recall-campaigns')
def list_campaigns():
    auth_context()
    items = list(DB['campaigns'].values())
    model_code = request.args.get('model_code')
    if model_code is not None:
        items = [c for c in items if c['model_code'] == model_code]
    status = request.args.get('status')
    if status is not None:
        items = [c for c in items if c['status'] == status]
    return list_response(items, serialize)


@bp.post('/recall-campaigns/<cid>/issue')
def issue_campaign(cid):
    uid, role = auth_context()
    require_roles(role, 'ComplianceOfficer')
    campaign = get_or_404(DB['campaigns'], cid, 'ERR_CAMPAIGN_NOT_FOUND',
                          'RecallCampaign')
    if campaign['status'] != 'DRAFT':
        raise ApiError(409, 'ERR_CAMPAIGN_NOT_DRAFT',
                       'Issue requires a DRAFT campaign')
    now = CLOCK.now()
    # Fan-out: hulls matching model code + model year + closed serial band
    # whose certification dimension is CERTIFIED.
    matched = []
    for hull in DB['hulls'].values():
        model = DB['models'][hull['model_id']]
        if (model['model_code'] == campaign['model_code']
                and model['model_year'] == campaign['model_year']
                and campaign['hin_serial_start'] <= hull['serial_no']
                <= campaign['hin_serial_end']
                and hull['certification_status'] == 'CERTIFIED'):
            matched.append(hull)
    matched.sort(key=lambda h: (h['_cts'], h['_seq']))
    for hull in matched:
        notice = new_rec({
            'campaign_id': campaign['id'],
            'hull_id': hull['id'],
            'status': 'NOTIFIED',
            'notified_at': fmt_dt(now),
            'remedied_at': None,
            'remedy_path': None,
        })
        DB['notices'][notice['id']] = notice
        hull['certification_status'] = 'RECALL_HOLD'
        touch(hull)
    campaign['notice_count'] = len(matched)
    campaign['open_notice_count'] = len(matched)
    campaign['issued_at'] = fmt_dt(now)
    campaign['status'] = 'ISSUED'
    touch(campaign)
    # zero-match issue auto-transitions ISSUED -> CLOSED
    if len(matched) == 0:
        campaign['status'] = 'CLOSED'
        touch(campaign)
    return respond(serialize(campaign), 200)


# ---------------------------------------------------------------- notices
@bp.get('/recall-notices')
def list_notices():
    auth_context()
    items = list(DB['notices'].values())
    for param in ('campaign_id', 'hull_id', 'status'):
        v = request.args.get(param)
        if v is not None:
            items = [n for n in items if n[param] == v]
    return list_response(items, serialize)


@bp.get('/recall-notices/<nid>')
def get_notice(nid):
    auth_context()
    rec = get_or_404(DB['notices'], nid, 'ERR_NOTICE_NOT_FOUND',
                     'RecallNotice')
    return respond(serialize(rec), 200)


@bp.post('/recall-notices/<nid>/remedy')
def remedy_notice_endpoint(nid):
    uid, role = auth_context()
    require_roles(role, 'ComplianceOfficer')
    notice = get_or_404(DB['notices'], nid, 'ERR_NOTICE_NOT_FOUND',
                        'RecallNotice')
    if notice['status'] != 'NOTIFIED':
        raise ApiError(409, 'ERR_INVALID_NOTICE_STATE',
                       'Remedy requires a NOTIFIED notice')
    remedy_notice(notice, 'PLANT_REMEDY')
    return respond(serialize(notice), 200)
