"""Distribution channels and channel publications."""
from flask import Blueprint

import envelope as env
import ser
import svc
import validate as v
from errors import fail
from store import by_created, common_fields, db, now, touch

bp = Blueprint('dist', __name__)

CHANNEL_TYPE = ('DIRECT', 'GDS', 'OTA', 'NDC')
PARITY_STATUS = ('COMPLIANT', 'BREACHED')
PARITY_STATE = ('PENDING', 'IN_PARITY', 'OUT_OF_PARITY', 'WITHDRAWN')


@bp.post('/distribution-channels')
def create_channel():
    v.ctx(('DistributionManager',))
    data = v.fields(v.body(), [
        ('channel_code', True, lambda x: v.v_str(x)),
        ('channel_type', True, lambda x: v.v_enum(x, CHANNEL_TYPE)),
        ('commission_bp', True, lambda x: v.v_int(x, 0, 3000)),
        ('markup_bp', True, lambda x: v.v_int(x, 0, 2000)),
        ('max_ancillary_price_cents', True, lambda x: v.v_int(x, 1)),
        ('supported_categories', True,
         lambda x: v.v_enum_array(x, v.CATEGORIES, min_len=1)),
        ('parity_required', False, v.v_bool),
    ])
    if any(c['channel_code'] == data['channel_code'] for c in db.channels.values()):
        fail('ERR_DUPLICATE_CHANNEL_CODE')
    record = common_fields()
    record.update({
        'channel_code': data['channel_code'],
        'channel_type': data['channel_type'],
        'commission_bp': data['commission_bp'],
        'markup_bp': data['markup_bp'],
        'max_ancillary_price_cents': data['max_ancillary_price_cents'],
        'supported_categories': list(data['supported_categories']),
        'parity_required': data.get('parity_required', True),
        'content_parity_status': 'COMPLIANT', 'parity_breach_count': 0,
    })
    db.channels[record['id']] = record
    return env.created(ser.channel(record))


@bp.get('/distribution-channels/<id>')
def read_channel(id):
    v.ctx(v.ALL_ROLES)
    return env.obj(ser.channel(svc.channel_or_404(id)))


@bp.get('/distribution-channels')
def list_channels():
    v.ctx(v.ALL_ROLES)
    limit, offset = v.pagination()
    channel_type = v.q_enum('channel_type', CHANNEL_TYPE)
    status = v.q_enum('content_parity_status', PARITY_STATUS)
    rows = [c for c in db.channels.values()
            if (channel_type is None or c['channel_type'] == channel_type)
            and (status is None or c['content_parity_status'] == status)]
    return env.page(by_created(rows), ser.channel, limit, offset)


@bp.post('/channel-publications')
def create_publication():
    v.ctx(('DistributionManager',))
    data = v.fields(v.body(), [
        ('fare_family_id', True, v.v_id),
        ('distribution_channel_id', True, v.v_id),
        ('expected_fare_family_version', True, lambda x: v.v_int(x)),
    ])
    family = svc.family_or_404(data['fare_family_id'])
    channel = svc.channel_or_404(data['distribution_channel_id'])
    if data['expected_fare_family_version'] != family['version']:
        fail('ERR_STALE_FAMILY_VERSION')
    for existing in svc.publications_of_family(family['id']):
        if (existing['distribution_channel_id'] == channel['id']
                and existing['parity_state'] in ('PENDING', 'IN_PARITY',
                                                 'OUT_OF_PARITY')):
            fail('ERR_DUPLICATE_PUBLICATION')
    record = common_fields()
    record.update({
        'fare_family_id': family['id'],
        'distribution_channel_id': channel['id'],
        'published_family_version': None,
        'published_fee_fingerprint': None,
        'parity_state': 'PENDING', 'drift_reason': None,
        'last_resync_at': None,
    })
    db.publications[record['id']] = record
    # the family's version bump happens first: the publication pins the version
    # as of the end of the triggering request (PRD 3.2 / 3.4)
    touch(family)
    record['published_fee_fingerprint'] = family['fee_fingerprint']
    record['published_family_version'] = family['version']
    if family['status'] == 'PUBLISHED':
        record['parity_state'] = 'IN_PARITY'
    svc.recompute_publication_count(family)
    return env.created(ser.publication(record))


@bp.get('/channel-publications/<id>')
def read_publication(id):
    v.ctx(v.ALL_ROLES)
    return env.obj(ser.publication(svc.publication_or_404(id)))


@bp.get('/channel-publications')
def list_publications():
    v.ctx(v.ALL_ROLES)
    limit, offset = v.pagination()
    family_id = v.q_str('fare_family_id')
    channel_id = v.q_str('distribution_channel_id')
    state = v.q_enum('parity_state', PARITY_STATE)
    rows = [p for p in db.publications.values()
            if (family_id is None or p['fare_family_id'] == family_id)
            and (channel_id is None or p['distribution_channel_id'] == channel_id)
            and (state is None or p['parity_state'] == state)]
    return env.page(by_created(rows), ser.publication, limit, offset)


@bp.post('/channel-publications/<id>/resync')
def resync_publication(id):
    v.ctx(('DistributionManager',))
    v.fields(v.body(), [])
    publication = svc.publication_or_404(id)
    if publication['parity_state'] != 'OUT_OF_PARITY':
        fail('ERR_PUBLICATION_STATE_INVALID')
    family = db.families[publication['fare_family_id']]
    if family['status'] != 'PUBLISHED':
        fail('ERR_FAMILY_NOT_PUBLISHED')
    publication['parity_state'] = 'IN_PARITY'
    publication['published_fee_fingerprint'] = family['fee_fingerprint']
    publication['published_family_version'] = family['version']
    publication['drift_reason'] = None
    publication['last_resync_at'] = now()
    touch(publication)
    svc.apply_channel_parity(db.channels[publication['distribution_channel_id']])
    return env.obj(ser.publication(publication))
