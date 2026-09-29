"""CSMs: E9-E11."""
from flask import Blueprint

import middleware as mw
import response as resp
from db import base_row, db, mark_fresh, touch
from errors import ApiError
from services import coverage, serialize
from services.lookup import csm as get_csm

bp = Blueprint('csms', __name__)

COVERAGE_SPECIALTIES = ('HIGH_TOUCH', 'LOW_TOUCH', 'DIGITAL')
CSM_STATUSES = ('ACTIVE', 'ON_LEAVE', 'OFFBOARDED')


@bp.route('/csms', methods=['POST'])
def create_csm():
    mw.authenticate(('CsOpsAdmin',))
    data = mw.body()
    full_name = mw.as_string(data, 'full_name', max_len=120)
    specialty = mw.as_enum(data, 'coverage_specialty', COVERAGE_SPECIALTIES)
    capacity_total = mw.as_int(data, 'capacity_units_total', minimum=1, maximum=200)
    row = base_row()
    row.update({
        'full_name': full_name,
        'coverage_specialty': specialty,
        'capacity_units_total': capacity_total,
        'capacity_units_committed': 0,
        'capacity_units_available': capacity_total,
        'status': 'ACTIVE',
    })
    db.csms[row['id']] = row
    mark_fresh(row)
    return resp.entity(serialize.csm, row, 201)


@bp.route('/csms/<csm_id>', methods=['GET'])
def read_csm(csm_id):
    mw.authenticate(('CsmUser', 'CsOpsAdmin', 'CsExecutive'))
    csm = get_csm(csm_id)
    return resp.entity(serialize.csm, csm, 200)


@bp.route('/csms/<csm_id>', methods=['PATCH'])
def patch_csm(csm_id):
    mw.authenticate(('CsOpsAdmin',))
    csm = get_csm(csm_id)
    data = mw.body()
    status = mw.as_enum(data, 'status', CSM_STATUSES, required=False)
    capacity_total = mw.as_int(data, 'capacity_units_total', required=False,
                               minimum=1, maximum=200)
    if (capacity_total is not None
            and capacity_total < csm['capacity_units_committed']):
        raise ApiError('ERR_CSM_CAPACITY_EXHAUSTED',
                       'capacity_units_total may not fall below the %d units '
                       'already committed.' % csm['capacity_units_committed'])
    touch(csm)
    if status is not None:
        csm['status'] = status
    if capacity_total is not None:
        csm['capacity_units_total'] = capacity_total
        coverage.sync_capacity(csm)
    return resp.entity(serialize.csm, csm, 200)
