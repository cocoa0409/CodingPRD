"""Catalog products, fare families and family attributes."""
from flask import Blueprint

import calc
import envelope as env
import ser
import svc
import validate as v
from errors import fail
from store import by_created, common_fields, db, touch

bp = Blueprint('catalog', __name__)

CATEGORY = ('BAGGAGE', 'SEAT', 'CHANGE', 'BOARDING', 'ONBOARD')
TAX_TREATMENT = ('TAXABLE_TRANSPORT', 'TAXABLE_SERVICE', 'EXEMPT')
REVENUE_CLASS = ('AIR_TRANSPORT_RELATED', 'NON_AIR')
PRODUCT_STATE = ('ACTIVE', 'WITHDRAWN')
CABIN_CLASS = ('ECONOMY', 'PREMIUM', 'BUSINESS')
REFUNDABILITY = ('NON_REFUNDABLE', 'REFUNDABLE_WITH_FEE', 'FULLY_REFUNDABLE')
FAMILY_STATUS = ('DRAFT', 'IN_REVIEW', 'PUBLISHED', 'SUSPENDED', 'RETIRED')
INCLUSION = ('INCLUDED', 'CHARGEABLE')
ATTRIBUTE_STATE = ('ACTIVE', 'WITHDRAWN')


# --------------------------------------------------------------------------
# ancillary products
# --------------------------------------------------------------------------
@bp.post('/ancillary-products')
def create_product():
    v.ctx(('MerchandisingAnalyst',))
    data = v.fields(v.body(), [
        ('sku', True, lambda x: v.v_str(x, v.RE_SKU)),
        ('name', True, lambda x: v.v_str(x)),
        ('category', True, lambda x: v.v_enum(x, CATEGORY)),
        ('list_price_cents', True, lambda x: v.v_int(x, 0)),
        ('tax_treatment', True, lambda x: v.v_enum(x, TAX_TREATMENT)),
        ('revenue_class', True, lambda x: v.v_enum(x, REVENUE_CLASS)),
        ('revenue_account_code', True, lambda x: v.v_str(x)),
        ('refundable', False, v.v_bool),
        ('disclosable_fee', False, v.v_bool),
        ('product_state', False, lambda x: v.v_enum(x, PRODUCT_STATE)),
    ])
    if any(p['sku'] == data['sku'] for p in db.products.values()):
        fail('ERR_DUPLICATE_SKU')
    record = common_fields()
    record.update({
        'sku': data['sku'], 'name': data['name'], 'category': data['category'],
        'list_price_cents': data['list_price_cents'],
        'tax_treatment': data['tax_treatment'],
        'revenue_class': data['revenue_class'],
        'revenue_account_code': data['revenue_account_code'],
        'refundable': data.get('refundable', False),
        'disclosable_fee': data.get('disclosable_fee', True),
        'product_state': data.get('product_state', 'ACTIVE'),
    })
    db.products[record['id']] = record
    return env.created(ser.product(record))


@bp.get('/ancillary-products/<id>')
def read_product(id):
    v.ctx(v.ALL_ROLES)
    return env.obj(ser.product(svc.product_or_404(id)))


@bp.get('/ancillary-products')
def list_products():
    v.ctx(v.ALL_ROLES)
    limit, offset = v.pagination()
    category = v.q_enum('category', CATEGORY)
    state = v.q_enum('product_state', PRODUCT_STATE)
    rows = [p for p in db.products.values()
            if (category is None or p['category'] == category)
            and (state is None or p['product_state'] == state)]
    return env.page(by_created(rows), ser.product, limit, offset)


@bp.get('/ancillary-products/<id>/family-attributes')
def list_product_attributes(id):
    v.ctx(v.ALL_ROLES)
    limit, offset = v.pagination()
    product = svc.product_or_404(id)
    rows = [a for a in db.attributes.values()
            if a['ancillary_product_id'] == product['id']]
    return env.page(by_created(rows), ser.attribute, limit, offset)


# --------------------------------------------------------------------------
# fare families
# --------------------------------------------------------------------------
def upsell_cycle(family_id, parent_id):
    """The upsell ladder must stay acyclic (PRD 3.2)."""
    seen = {family_id}
    current = parent_id
    while current is not None:
        if current in seen:
            return True
        seen.add(current)
        parent = db.families.get(current)
        if parent is None:
            return False
        current = parent['upsell_parent_family_id']
    return False


@bp.post('/fare-families')
def create_family():
    uid, _role = v.ctx(('MerchandisingAnalyst',))
    raw = v.body()
    data = v.fields(raw, [
        ('code', True, lambda x: v.v_str(x, v.RE_CODE)),
        ('name', True, lambda x: v.v_str(x)),
        ('cabin_class', True, lambda x: v.v_enum(x, CABIN_CLASS)),
        ('base_fare_cents', True, lambda x: v.v_int(x, 1)),
        ('bundle_price_cents', True, lambda x: v.v_int(x, 1)),
        ('refundability', True, lambda x: v.v_enum(x, REFUNDABILITY)),
        ('change_fee_cents', True, lambda x: v.v_int(x, 0)),
        ('boarding_priority_tier', True, lambda x: v.v_int(x, 1, 4)),
        ('upsell_parent_family_id', False, v.nullable(v.v_id)),
    ])
    parent_id = data.get('upsell_parent_family_id')
    if parent_id is not None:
        svc.family_or_404(parent_id)
    if any(f['code'] == data['code'] for f in db.families.values()):
        fail('ERR_DUPLICATE_FAMILY_CODE')
    record = common_fields()
    record.update({
        'code': data['code'], 'name': data['name'],
        'cabin_class': data['cabin_class'],
        'base_fare_cents': data['base_fare_cents'],
        'bundle_price_cents': data['bundle_price_cents'],
        'refundability': data['refundability'],
        'change_fee_cents': data['change_fee_cents'],
        'boarding_priority_tier': data['boarding_priority_tier'],
        'upsell_parent_family_id': parent_id,
        'design_owner_user_id': uid, 'reviewer_user_id': None,
        'status': 'DRAFT', 'revision_no': 1,
        'unbundled_value_cents': 0, 'a_la_carte_total_cents': 0,
        'bundle_discount_bp': 0, 'included_attribute_count': 0,
        'fee_fingerprint': None, 'publication_count': 0,
    })
    if upsell_cycle(record['id'], parent_id):
        fail('ERR_UPSELL_CYCLE_DETECTED')
    db.families[record['id']] = record
    record['fee_fingerprint'] = calc.fee_fingerprint(record)
    return env.created(ser.family(record))


@bp.get('/fare-families/<id>')
def read_family(id):
    v.ctx(v.ALL_ROLES)
    return env.obj(ser.family(svc.family_or_404(id)))


@bp.get('/fare-families')
def list_families():
    v.ctx(v.ALL_ROLES)
    limit, offset = v.pagination()
    status = v.q_enum('status', FAMILY_STATUS)
    cabin = v.q_enum('cabin_class', CABIN_CLASS)
    parent = v.q_str('upsell_parent_family_id')
    rows = [f for f in db.families.values()
            if (status is None or f['status'] == status)
            and (cabin is None or f['cabin_class'] == cabin)
            and (parent is None or f['upsell_parent_family_id'] == parent)]
    return env.page(by_created(rows), ser.family, limit, offset)


@bp.get('/fare-families/<id>/attributes')
def list_family_attributes(id):
    v.ctx(v.ALL_ROLES)
    limit, offset = v.pagination()
    family = svc.family_or_404(id)
    return env.page(svc.attributes_of(family['id']), ser.attribute, limit, offset)


@bp.post('/fare-families/<id>/submit')
def submit_family(id):
    uid, _role = v.ctx(('MerchandisingAnalyst',))
    v.fields(v.body(), [])
    family = svc.family_or_404(id)
    if uid != family['design_owner_user_id']:
        fail('ERR_ROLE_NOT_PERMITTED')
    if family['status'] != 'DRAFT':
        fail('ERR_FAMILY_STATE_INVALID')
    if not calc.active_attributes(family['id']):
        fail('ERR_FAMILY_HAS_NO_ATTRIBUTES')
    unbundled, _per = calc.bundle_valuation(family, 'override_basis')
    if family['bundle_price_cents'] > family['base_fare_cents'] + unbundled:
        fail('ERR_BUNDLE_DISCOUNT_FLOOR_BREACH')
    svc.recompute_family_valuation(family)
    drifted = svc.rebuild_fingerprint(family)
    family['status'] = 'IN_REVIEW'
    touch(family)
    if drifted:
        svc.drift_publications(family, 'ATTRIBUTE_REPRICED')
        svc.stale_bookings(family)
    return env.obj(ser.family(family))


@bp.post('/fare-families/<id>/review-decision')
def review_decision(id):
    uid, _role = v.ctx(('PricingApprover',))
    data = v.fields(v.body(), [
        ('decision', True, lambda x: v.v_enum(x, ('APPROVE', 'REJECT'))),
        ('review_note', False, v.nullable(lambda x: v.v_str(x))),
    ])
    family = svc.family_or_404(id)
    if uid == family['design_owner_user_id']:
        fail('ERR_SEGREGATION_OF_DUTIES')
    if family['status'] != 'IN_REVIEW':
        fail('ERR_FAMILY_STATE_INVALID')
    family['reviewer_user_id'] = uid
    if data['decision'] == 'REJECT':
        family['revision_no'] = family['revision_no'] + 1
        family['status'] = 'DRAFT'
        drifted = svc.rebuild_fingerprint(family)
        touch(family)
        if drifted:
            svc.drift_publications(family, 'FAMILY_REVISION_REJECTED')
            svc.stale_bookings(family)
    else:
        family['status'] = 'PUBLISHED'
        touch(family)
        for publication in svc.publications_of_family(family['id']):
            if publication['parity_state'] != 'PENDING':
                continue
            publication['parity_state'] = 'IN_PARITY'
            publication['published_fee_fingerprint'] = family['fee_fingerprint']
            publication['published_family_version'] = family['version']
            touch(publication)
        svc.recompute_publication_count(family)
    return env.obj(ser.family(family))


@bp.post('/fare-families/<id>/status-change')
def status_change(id):
    v.ctx(('PricingApprover',))
    data = v.fields(v.body(), [
        ('target_status', True, lambda x: v.v_enum(x, FAMILY_STATUS)),
        ('reason', True, lambda x: v.v_str(x)),
    ])
    family = svc.family_or_404(id)
    target = data['target_status']
    legal = {'PUBLISHED': ('SUSPENDED', 'RETIRED'),
             'SUSPENDED': ('PUBLISHED', 'RETIRED')}
    if target not in legal.get(family['status'], ()):
        fail('ERR_FAMILY_STATE_INVALID')
    if target == 'RETIRED':
        for booking in svc.bookings_of_family(family['id']):
            if booking['booking_status'] in ('HELD', 'TICKETED', 'CHANGE_PENDING'):
                fail('ERR_FAMILY_HAS_LIVE_BOOKINGS')
    family['status'] = target
    touch(family)
    if target == 'SUSPENDED':
        svc.drift_publications(family, 'FAMILY_SUSPENDED', force=True)
    elif target == 'RETIRED':
        svc.withdraw_publications(family)
        svc.recompute_publication_count(family)
    return env.obj(ser.family(family))


@bp.patch('/fare-families/<id>')
def patch_family(id):
    v.ctx(('MerchandisingAnalyst',))
    raw = v.body()
    data = v.fields(raw, [
        ('name', False, lambda x: v.v_str(x)),
        ('upsell_parent_family_id', False, v.nullable(v.v_id)),
    ])
    family = svc.family_or_404(id)
    reparent = 'upsell_parent_family_id' in raw
    parent_id = data.get('upsell_parent_family_id') if reparent else None
    if reparent and parent_id is not None:
        svc.family_or_404(parent_id)
    if family['status'] != 'DRAFT':
        fail('ERR_FAMILY_STATE_INVALID')
    if reparent and upsell_cycle(family['id'], parent_id):
        fail('ERR_UPSELL_CYCLE_DETECTED')
    if 'name' in raw:
        family['name'] = data['name']
    if reparent:
        family['upsell_parent_family_id'] = parent_id
    touch(family)
    return env.obj(ser.family(family))


# --------------------------------------------------------------------------
# family attributes
# --------------------------------------------------------------------------
def check_quantity(inclusion, quantity):
    if inclusion == 'INCLUDED' and quantity < 1:
        fail('ERR_INVALID_ATTRIBUTE_QUANTITY')
    if inclusion == 'CHARGEABLE' and quantity != 0:
        fail('ERR_INVALID_ATTRIBUTE_QUANTITY')


@bp.post('/fare-families/<id>/attributes')
def attach_attribute(id):
    v.ctx(('MerchandisingAnalyst',))
    data = v.fields(v.body(), [
        ('ancillary_product_id', True, v.v_id),
        ('inclusion', True, lambda x: v.v_enum(x, INCLUSION)),
        ('included_quantity', True, lambda x: v.v_int(x, 0, 9)),
        ('override_price_cents', False, v.nullable(lambda x: v.v_int(x, 0))),
        ('waiver_eligible', False, v.v_bool),
    ])
    family = svc.family_or_404(id)
    product = svc.product_or_404(data['ancillary_product_id'])
    if family['status'] != 'DRAFT':
        fail('ERR_FAMILY_STATE_INVALID')
    for existing in svc.attributes_of(family['id']):
        if (existing['ancillary_product_id'] == product['id']
                and existing['attribute_state'] == 'ACTIVE'):
            fail('ERR_ATTRIBUTE_DUPLICATE_PRODUCT')
    check_quantity(data['inclusion'], data['included_quantity'])
    record = common_fields()
    record.update({
        'fare_family_id': family['id'],
        'ancillary_product_id': product['id'],
        'inclusion': data['inclusion'],
        'included_quantity': data['included_quantity'],
        'override_price_cents': data.get('override_price_cents'),
        'waiver_eligible': data.get('waiver_eligible', False),
        'effective_unit_cents': 0, 'attr_value_cents': 0,
        'attribute_state': 'ACTIVE',
    })
    db.attributes[record['id']] = record
    svc.recompute_family_valuation(family)
    drifted = svc.rebuild_fingerprint(family)
    touch(family)
    if drifted:
        svc.drift_publications(family, 'ATTRIBUTE_REPRICED')
        svc.stale_bookings(family)
    return env.created(ser.attribute(record))


@bp.get('/family-attributes/<id>')
def read_attribute(id):
    v.ctx(v.ALL_ROLES)
    return env.obj(ser.attribute(svc.attribute_or_404(id)))


@bp.get('/family-attributes')
def list_attributes():
    v.ctx(v.ALL_ROLES)
    limit, offset = v.pagination()
    family_id = v.q_str('fare_family_id')
    product_id = v.q_str('ancillary_product_id')
    state = v.q_enum('attribute_state', ATTRIBUTE_STATE)
    rows = [a for a in db.attributes.values()
            if (family_id is None or a['fare_family_id'] == family_id)
            and (product_id is None or a['ancillary_product_id'] == product_id)
            and (state is None or a['attribute_state'] == state)]
    return env.page(by_created(rows), ser.attribute, limit, offset)


@bp.patch('/family-attributes/<id>')
def patch_attribute(id):
    v.ctx(('MerchandisingAnalyst',))
    raw = v.body()
    data = v.fields(raw, [
        ('inclusion', False, lambda x: v.v_enum(x, INCLUSION)),
        ('included_quantity', False, lambda x: v.v_int(x, 0, 9)),
        ('override_price_cents', False, v.nullable(lambda x: v.v_int(x, 0))),
        ('waiver_eligible', False, v.v_bool),
        ('attribute_state', False, lambda x: v.v_enum(x, ATTRIBUTE_STATE)),
    ])
    attribute = svc.attribute_or_404(id)
    family = db.families[attribute['fare_family_id']]
    if family['status'] not in ('DRAFT', 'PUBLISHED'):
        fail('ERR_FAMILY_STATE_INVALID')
    inclusion = data.get('inclusion', attribute['inclusion'])
    quantity = data.get('included_quantity', attribute['included_quantity'])
    check_quantity(inclusion, quantity)
    attribute['inclusion'] = inclusion
    attribute['included_quantity'] = quantity
    if 'override_price_cents' in raw:
        attribute['override_price_cents'] = data['override_price_cents']
    if 'waiver_eligible' in raw:
        attribute['waiver_eligible'] = data['waiver_eligible']
    if 'attribute_state' in raw:
        attribute['attribute_state'] = data['attribute_state']
    svc.recompute_family_valuation(family)
    touch(attribute)
    drifted = svc.rebuild_fingerprint(family)
    touch(family)
    if drifted:
        svc.drift_publications(family, 'ATTRIBUTE_REPRICED')
        svc.stale_bookings(family)
    return env.obj(ser.attribute(attribute))
