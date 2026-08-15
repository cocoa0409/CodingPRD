"""ForestryReview decision / clear endpoints and the defect-freeing rule."""
from flask import Blueprint, g

from db import db, touch
from errors import ApiError, not_found
from middleware import require_roles
from response import ok_object
from services import TERMINAL_NOTICE_STATUSES, recompute_segment, ser_forestry
from validation import get_body, validate

bp = Blueprint('forestry', __name__)


def _free_defect(review):
    """AWAITING_FORESTRY -> UNDER_REPAIR when a non-terminal notice references
    the defect, else -> OPEN."""
    defect = db.defects.get(review['defect_id'])
    if not defect or defect['status'] != 'AWAITING_FORESTRY':
        return
    referenced = any(
        defect['id'] in n['defect_ids'] and n['status'] not in TERMINAL_NOTICE_STATUSES
        for n in db.notices.values())
    defect['status'] = 'UNDER_REPAIR' if referenced else 'OPEN'
    touch(defect)
    seg = db.segments.get(defect['segment_id'])
    if seg:
        recompute_segment(seg)


@bp.post('/forestry-reviews/<rid>/decision')
@require_roles('ForestryOfficer')
def decide_review(rid):
    vals = validate(get_body(), [
        ('decision', 'enum', True,
         {'values': ['PRUNE_APPROVED', 'REMOVAL_ORDERED', 'NO_CITY_CONFLICT']}),
    ])
    r = db.forestry_reviews.get(rid)
    if not r:
        raise not_found('forestry')
    if r['status'] != 'PENDING':
        raise ApiError('ERR_INVALID_FORESTRY_STATE', 409, 'Review is not PENDING')
    r['decision'] = vals['decision']
    r['decided_by_user_id'] = g.uid
    if vals['decision'] == 'NO_CITY_CONFLICT':
        r['status'] = 'CLEARED'
        r['work_completed_at'] = None
        _free_defect(r)
    else:
        r['status'] = 'DECIDED'
    touch(r)
    return ok_object(ser_forestry(r))


@bp.post('/forestry-reviews/<rid>/clear')
@require_roles('ForestryOfficer')
def clear_review(rid):
    r = db.forestry_reviews.get(rid)
    if not r:
        raise not_found('forestry')
    if r['status'] != 'DECIDED':
        raise ApiError('ERR_INVALID_FORESTRY_STATE', 409, 'Review is not DECIDED')
    r['status'] = 'CLEARED'
    r['work_completed_at'] = db.clock
    _free_defect(r)
    touch(r)
    return ok_object(ser_forestry(r))
