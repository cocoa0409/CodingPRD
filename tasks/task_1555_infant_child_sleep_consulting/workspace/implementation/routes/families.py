from flask import Blueprint

from auth import user_context, require_role, forbidden
from db import store, base_fields, register
from domain import ser_family
from envelope import ok, paginate
from errors import ApiError
from validators import body, req_str

bp = Blueprint('families', __name__)


@bp.post('/families')
def create_family():
    _, role = user_context()
    require_role(role, 'Anonymous')
    data = body()
    full_name = req_str(data, 'full_name')
    email = req_str(data, 'email')
    f = base_fields()
    f.update({
        'full_name': full_name,
        'email': email,
        'credit_balance_cents': 0,
    })
    register(store.families, f)
    return ok(ser_family(f), status=201)


@bp.get('/families')
def list_families():
    _, role = user_context()
    require_role(role, 'PracticeAdmin', 'Consultant')
    return paginate(list(store.families.values()), ser_family)


@bp.get('/families/<familyId>')
def get_family(familyId):
    uid, role = user_context()
    require_role(role, 'PracticeAdmin', 'Consultant', 'Parent')
    f = store.families.get(familyId)
    if f is None:
        raise ApiError('ERR_FAMILY_NOT_FOUND', 404, 'Family not found')
    if role == 'Parent' and f['id'] != uid:
        forbidden('Parent may read only their own family record')
    return ok(ser_family(f))
