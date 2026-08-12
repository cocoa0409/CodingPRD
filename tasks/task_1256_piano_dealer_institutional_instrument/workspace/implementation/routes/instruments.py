from flask import Blueprint

import db
from errors import ApiError, invalid
from middleware import auth
from response import ok
from util import body, require, optional, as_str, as_int, as_enum, find, serialize

bp = Blueprint('instruments', __name__)

CATEGORIES = ('GRAND', 'UPRIGHT', 'DIGITAL', 'HYBRID')
CONDITIONS = ('EXCELLENT', 'GOOD', 'FAIR', 'POOR')
ACQUISITIONS = ('NEW', 'USED', 'CONSIGNMENT')


def _not_available(message='instrument is not in the required state'):
    return ApiError('ERR_INSTRUMENT_NOT_AVAILABLE', 409, message)


@bp.post('/piano-dealer/instruments')
def create_instrument():
    auth('StoreManager')
    d = body()
    serial = as_str(require(d, 'serial_number'), 'serial_number')
    category = as_enum(require(d, 'category'), 'category', CATEGORIES)
    manufacturer = as_str(require(d, 'manufacturer'), 'manufacturer')
    model = as_str(require(d, 'model'), 'model')
    year_built = as_int(require(d, 'year_built'), 'year_built')
    condition_grade = as_enum(require(d, 'condition_grade'), 'condition_grade', CONDITIONS)
    acquisition_type = as_enum(require(d, 'acquisition_type'), 'acquisition_type', ACQUISITIONS)
    list_price = as_int(require(d, 'list_price_cents'), 'list_price_cents')
    floor_price = as_int(require(d, 'floor_price_cents'), 'floor_price_cents')
    recoverable = as_int(optional(d, 'recoverable_costs_cents', 0), 'recoverable_costs_cents')
    consignor_id = optional(d, 'consignor_id')
    if acquisition_type == 'CONSIGNMENT':
        if consignor_id is None:
            raise invalid('consignor_id is required for CONSIGNMENT instruments')
        consignor_id = as_str(consignor_id, 'consignor_id')
        find(db.stores['consignors'], consignor_id, 'consignor')
    else:
        consignor_id = None
    # Global serial uniqueness (priority 8, after FK existence at priority 4)
    for inst in db.stores['instruments'].values():
        if inst['serial_number'] == serial:
            raise ApiError('ERR_DUPLICATE_SERIAL', 409, 'serial_number already exists')
    rec = db.base_fields()
    rec.update({
        'serial_number': serial,
        'category': category,
        'manufacturer': manufacturer,
        'model': model,
        'year_built': year_built,
        'condition_grade': condition_grade,
        'acquisition_type': acquisition_type,
        'consignor_id': consignor_id,
        'list_price_cents': list_price,
        'floor_price_cents': floor_price,
        'recoverable_costs_cents': recoverable,
        'status': 'IN_PREP',
    })
    db.stores['instruments'][rec['id']] = rec
    return ok(serialize(rec), 201)


@bp.get('/piano-dealer/instruments/<rid>')
def get_instrument(rid):
    auth('StoreManager', 'SalesAssociate', 'InstitutionalBidOfficer', 'Consignor')
    return ok(serialize(find(db.stores['instruments'], rid, 'instrument')))


@bp.post('/piano-dealer/instruments/<rid>/list-for-sale')
def list_for_sale(rid):
    auth('StoreManager')
    inst = find(db.stores['instruments'], rid, 'instrument')
    # Only IN_PREP is eligible; REPOSSESSION_HOLD in particular is not.
    if inst['status'] != 'IN_PREP':
        raise _not_available('only IN_PREP instruments can be listed for sale')
    inst['status'] = 'AVAILABLE'
    db.touch(inst)
    return ok(serialize(inst))


@bp.post('/piano-dealer/instruments/<rid>/complete-restoration')
def complete_restoration(rid):
    auth('StoreManager')
    inst = find(db.stores['instruments'], rid, 'instrument')
    if inst['status'] != 'RESTORATION_HOLD':
        raise _not_available('only RESTORATION_HOLD instruments can complete restoration')
    inst['status'] = 'IN_PREP'
    db.touch(inst)
    return ok(serialize(inst))


@bp.post('/piano-dealer/instruments/<rid>/release-hold')
def release_hold(rid):
    auth('StoreManager')
    inst = find(db.stores['instruments'], rid, 'instrument')
    if inst['status'] != 'REPOSSESSION_HOLD':
        raise _not_available('only REPOSSESSION_HOLD instruments can be released')
    inst['status'] = 'AVAILABLE'
    db.touch(inst)
    return ok(serialize(inst))


@bp.post('/piano-dealer/instruments/<rid>/return-to-consignor')
def return_to_consignor(rid):
    auth('StoreManager')
    inst = find(db.stores['instruments'], rid, 'instrument')
    if inst['acquisition_type'] != 'CONSIGNMENT':
        raise invalid('only CONSIGNMENT instruments can be returned to a consignor')
    if inst['status'] != 'AVAILABLE':
        raise _not_available('instrument must be AVAILABLE to return to consignor')
    inst['status'] = 'RETURNED_TO_CONSIGNOR'
    db.touch(inst)
    return ok(serialize(inst))
