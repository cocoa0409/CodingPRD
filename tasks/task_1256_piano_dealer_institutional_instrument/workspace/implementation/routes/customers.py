from flask import Blueprint

import db
from errors import invalid, forbidden
from middleware import auth
from response import ok
from util import body, require, optional, as_str, as_enum, as_bool, as_int, find, serialize

bp = Blueprint('customers', __name__)


@bp.post('/piano-dealer/customers')
def create_customer():
    auth('SalesAssociate')
    d = body()
    customer_type = as_enum(require(d, 'customer_type'), 'customer_type', ('INDIVIDUAL', 'INSTITUTIONAL'))
    institution_type = optional(d, 'institution_type')
    if customer_type == 'INSTITUTIONAL':
        # required iff customer_type == INSTITUTIONAL
        institution_type = as_enum(require(d, 'institution_type'), 'institution_type',
                                   ('EDUCATION', 'GOVERNMENT', 'NONPROFIT', 'CORPORATE'))
    elif institution_type is not None:
        as_enum(institution_type, 'institution_type', ('EDUCATION', 'GOVERNMENT', 'NONPROFIT', 'CORPORATE'))
    ceiling = optional(d, 'state_contract_ceiling_cents')
    rec = db.base_fields()
    rec.update({
        'full_name': as_str(require(d, 'full_name'), 'full_name'),
        'email': as_str(require(d, 'email'), 'email'),
        'customer_type': customer_type,
        'institution_type': institution_type,
        'tax_exempt': as_bool(optional(d, 'tax_exempt', False), 'tax_exempt'),
        'state_contract_ceiling_cents': as_int(ceiling, 'state_contract_ceiling_cents') if ceiling is not None else None,
        'credit_limit_cents': as_int(optional(d, 'credit_limit_cents', 0), 'credit_limit_cents'),
        'risk_score': 700,
    })
    db.stores['customers'][rec['id']] = rec
    return ok(serialize(rec), 201)


@bp.get('/piano-dealer/customers/<rid>')
def get_customer(rid):
    uid, role = auth('SalesAssociate', 'StoreManager', 'FinanceOfficer',
                     'InstitutionalBidOfficer', 'Customer')
    if role == 'Customer' and uid != rid:
        raise forbidden('a customer may only read their own record')
    return ok(serialize(find(db.stores['customers'], rid, 'customer')))
