"""Enplanement snapshot endpoints (PRD section 3.8)."""
from flask import Blueprint

from db import db, base_fields
from errors import ApiError, ERR_ENPLANEMENT_MONTH_DUPLICATE, ERR_INVALID_AMOUNT
from middleware import require_roles, body_json, req_month, req_int
from response import ok, ok_list
from services.core import pub
from services.validation import paginate

bp = Blueprint('enplanements', __name__)


@bp.route('/concessions/enplanement-snapshots', methods=['POST'])
def create_snapshot():
    require_roles('AirportAdmin')
    body = body_json()
    month = req_month(body, 'month')
    enplanements = req_int(body, 'enplanements')
    # Stage 7: one snapshot per month across the whole program.
    for s in db.enplanements.values():
        if s['month'] == month:
            raise ApiError(ERR_ENPLANEMENT_MONTH_DUPLICATE, 409,
                           'An enplanement snapshot already exists for the month')
    # Stage 9: the count must be positive.
    if enplanements <= 0:
        raise ApiError(ERR_INVALID_AMOUNT, 422, 'enplanements must be > 0')
    rec = base_fields()
    rec.update({'month': month, 'enplanements': enplanements})
    db.enplanements[rec['id']] = rec
    return ok(pub(rec), status=201)


@bp.route('/concessions/enplanement-snapshots', methods=['GET'])
def list_snapshots():
    require_roles('AirportAdmin', 'ConcessionAnalyst', 'Tenant')
    items = sorted(db.enplanements.values(), key=lambda s: s['_seq'])
    page, meta = paginate(items)
    return ok_list([pub(s) for s in page], meta)
