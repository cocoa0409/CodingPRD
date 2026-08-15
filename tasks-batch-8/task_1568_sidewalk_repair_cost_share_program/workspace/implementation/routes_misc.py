"""Logical clock control and the delinquency sweep."""
from flask import Blueprint

from db import db, touch
from middleware import require_roles
from response import ok_object
from services import transition_notice_to_delinquent
from util import fmt_dt
from validation import get_body, validate

bp = Blueprint('misc', __name__)


@bp.post('/_clock/set_current_utc')
@require_roles('ProgramCoordinator')
def set_clock():
    vals = validate(get_body(), [('to_iso8601', 'datetime', True, {})])
    db.clock = vals['to_iso8601']
    return ok_object({'current_utc': fmt_dt(db.clock)})


@bp.post('/delinquency-sweeps')
@require_roles('ProgramCoordinator')
def run_sweep():
    swept_notice_ids = []
    expired_application_ids = []
    # Notices first: ISSUED with clock strictly past the compliance deadline.
    for n in sorted(db.notices.values(), key=lambda e: e['_seq']):
        if n['status'] == 'ISSUED' and n['compliance_deadline'] is not None \
                and db.clock > n['compliance_deadline']:
            transition_notice_to_delinquent(n)
            swept_notice_ids.append(n['id'])
    # Then expire APPROVED applications whose approval window has passed
    # (applications cancelled by the cascade above are no longer APPROVED).
    for a in sorted(db.applications.values(), key=lambda e: e['_seq']):
        if a['review_status'] == 'APPROVED' and a['approval_expires_at'] is not None \
                and db.clock > a['approval_expires_at']:
            a['review_status'] = 'EXPIRED'
            touch(a)
            expired_application_ids.append(a['id'])
    return ok_object({
        'swept_notice_count': len(swept_notice_ids),
        'expired_application_count': len(expired_application_ids),
        'swept_notice_ids': swept_notice_ids,
        'expired_application_ids': expired_application_ids,
    })
