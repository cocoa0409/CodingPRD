"""Catalog endpoints: boat models and option packages."""
from flask import Blueprint

from store import DB, new_rec, serialize
from util import (ApiError, respond, list_response, auth_context, require_roles,
                  json_body, present, need, as_str, as_int, as_num, as_enum,
                  invalid, get_or_404)

bp = Blueprint('catalog', __name__)

MODEL_STATUSES = {'ORDERABLE', 'DISCONTINUED'}


# ---------------------------------------------------------------- models
@bp.post('/boat-models')
def create_model():
    auth = auth_context()
    require_roles(auth[1], 'SystemAdmin')
    data = json_body()
    model_code = as_str(need(data, 'model_code'), 'model_code')
    model_name = as_str(need(data, 'model_name'), 'model_name')
    model_year = as_int(need(data, 'model_year'), 'model_year')
    base_price = as_int(need(data, 'base_price_cents'), 'base_price_cents')
    if base_price <= 0:
        invalid('base_price_cents must be > 0')
    length_feet = as_num(need(data, 'length_feet'), 'length_feet')
    hours = as_int(need(data, 'production_hours'), 'production_hours')
    if hours <= 0:
        invalid('production_hours must be > 0')
    status = 'ORDERABLE'
    if present(data, 'status'):
        status = as_enum(data['status'], 'status', MODEL_STATUSES)
    if any(m['model_code'] == model_code for m in DB['models'].values()):
        invalid('model_code must be unique across BoatModel')
    rec = new_rec({
        'model_code': model_code,
        'model_name': model_name,
        'model_year': model_year,
        'base_price_cents': base_price,
        'length_feet': length_feet,
        'production_hours': hours,
        'status': status,
    })
    DB['models'][rec['id']] = rec
    return respond(serialize(rec), 201)


@bp.get('/boat-models')
def list_models():
    auth_context()
    items = list(DB['models'].values())
    status = _q('status')
    if status is not None:
        items = [m for m in items if m['status'] == status]
    return list_response(items, serialize)


@bp.get('/boat-models/<mid>')
def get_model(mid):
    auth_context()
    rec = get_or_404(DB['models'], mid, 'ERR_MODEL_NOT_FOUND', 'BoatModel')
    return respond(serialize(rec), 200)


# ---------------------------------------------------------------- options
@bp.post('/option-packages')
def create_option():
    auth = auth_context()
    require_roles(auth[1], 'SystemAdmin')
    data = json_body()
    model_id = as_str(need(data, 'model_id'), 'model_id')
    option_code = as_str(need(data, 'option_code'), 'option_code')
    name = as_str(need(data, 'name'), 'name')
    price = as_int(need(data, 'price_cents'), 'price_cents')
    if price <= 0:
        invalid('price_cents must be > 0')
    hours = as_int(need(data, 'production_hours'), 'production_hours')
    if hours < 0:
        invalid('production_hours must be >= 0')
    incompat = None
    if present(data, 'incompatible_with_option_id'):
        incompat = as_str(data['incompatible_with_option_id'],
                          'incompatible_with_option_id')
    if any(o['option_code'] == option_code for o in DB['options'].values()):
        invalid('option_code must be unique across OptionPackage')
    # body FK existence (family 5)
    get_or_404(DB['models'], model_id, 'ERR_MODEL_NOT_FOUND', 'BoatModel')
    if incompat is not None:
        get_or_404(DB['options'], incompat, 'ERR_OPTION_NOT_FOUND',
                   'OptionPackage')
    rec = new_rec({
        'model_id': model_id,
        'option_code': option_code,
        'name': name,
        'price_cents': price,
        'production_hours': hours,
        'incompatible_with_option_id': incompat,
    })
    DB['options'][rec['id']] = rec
    return respond(serialize(rec), 201)


@bp.get('/option-packages')
def list_options():
    auth_context()
    items = list(DB['options'].values())
    model_id = _q('model_id')
    if model_id is not None:
        items = [o for o in items if o['model_id'] == model_id]
    incompat = _q('incompatible_with_option_id')
    if incompat is not None:
        items = [o for o in items if o['incompatible_with_option_id'] == incompat]
    return list_response(items, serialize)


@bp.get('/option-packages/<oid>')
def get_option(oid):
    auth_context()
    rec = get_or_404(DB['options'], oid, 'ERR_OPTION_NOT_FOUND',
                     'OptionPackage')
    return respond(serialize(rec), 200)


def _q(name):
    from flask import request
    v = request.args.get(name)
    return v if v is not None else None
