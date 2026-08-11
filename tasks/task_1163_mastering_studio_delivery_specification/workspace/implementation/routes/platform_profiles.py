from decimal import Decimal

from flask import Blueprint, request

import db
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import (
    auth, require_roles, body, req_field, as_int, as_num, as_enum,
    pagination_args, get_or_404,
)
from response import success, success_list

bp = Blueprint('platform_profiles', __name__)

PLATFORM_CODES = ('SPOTIFY', 'APPLE_MUSIC', 'YOUTUBE_MUSIC', 'TIDAL', 'DEEZER',
                  'BANDCAMP', 'VINYL', 'CD', 'CLUB')
CONTAINER_FORMATS = ('WAV', 'AIFF', 'FLAC', 'MP3_320', 'AAC_256', 'DDP', 'VINYL_PREMASTER')
BIT_DEPTHS = (16, 24, 32)


def _in_range(val, lo, hi, field):
    d = Decimal(str(val))
    if d < Decimal(str(lo)) or d > Decimal(str(hi)):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       '%s must be in [%s, %s]' % (field, lo, hi))


@bp.post('/studio/platform-profiles')
def create_profile():
    uid, role = auth()
    require_roles(role, ('StudioManager',))
    data = body()
    platform_code = as_enum(req_field(data, 'platform_code'), 'platform_code', PLATFORM_CODES)
    integrated_lufs = as_num(req_field(data, 'integrated_lufs'), 'integrated_lufs')
    _in_range(integrated_lufs, -30.0, -5.0, 'integrated_lufs')
    true_peak_dbtp = as_num(req_field(data, 'true_peak_dbtp'), 'true_peak_dbtp')
    _in_range(true_peak_dbtp, -6.0, 0.0, 'true_peak_dbtp')
    loudness_range_lu = as_num(req_field(data, 'loudness_range_lu'), 'loudness_range_lu')
    if Decimal(str(loudness_range_lu)) <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, 'loudness_range_lu must be > 0')
    required_sample_rate_hz = as_int(req_field(data, 'required_sample_rate_hz'), 'required_sample_rate_hz')
    if required_sample_rate_hz <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, 'required_sample_rate_hz must be > 0')
    required_bit_depth = as_int(req_field(data, 'required_bit_depth'), 'required_bit_depth')
    if required_bit_depth not in BIT_DEPTHS:
        raise ApiError(ERR_INVALID_REQUEST, 400, 'required_bit_depth must be 16, 24, or 32')
    container_format = as_enum(req_field(data, 'container_format'), 'container_format', CONTAINER_FORMATS)
    for p in db.platform_profiles.values():
        if p['platform_code'] == platform_code:
            raise ApiError(ERR_INVALID_REQUEST, 409, 'platform_code already registered')
    rec = db.new_record()
    rec.update({
        'platform_code': platform_code,
        'integrated_lufs': integrated_lufs,
        'true_peak_dbtp': true_peak_dbtp,
        'loudness_range_lu': loudness_range_lu,
        'required_sample_rate_hz': required_sample_rate_hz,
        'required_bit_depth': required_bit_depth,
        'container_format': container_format,
    })
    db.platform_profiles[rec['id']] = rec
    return success(db.public(rec), 201)


@bp.get('/studio/platform-profiles')
def list_profiles():
    uid, role = auth()
    require_roles(role, ('StudioManager', 'Client', 'Engineer', 'QAChecker'))
    limit, offset = pagination_args()
    code = request.args.get('platform_code')
    items = list(db.platform_profiles.values())
    if code is not None:
        items = [p for p in items if p['platform_code'] == code]
    items.sort(key=lambda p: p['_seq'])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list(db.public_list(page), limit, offset, total)


@bp.get('/studio/platform-profiles/<pid>')
def get_profile(pid):
    uid, role = auth()
    require_roles(role, ('StudioManager', 'Client', 'Engineer', 'QAChecker'))
    rec = get_or_404(db.platform_profiles, pid)
    return success(db.public(rec), 200)
