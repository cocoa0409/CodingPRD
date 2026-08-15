"""Route calendars: delivery windows, weekly fuel surcharge rates, tax-stamp supplies."""
from datetime import timedelta

from flask import Blueprint, request

from db import STORE, new_record, public
from errors import (
    ApiError, validation, not_found,
    ERR_DUPLICATE_RATE_WEEK, ERR_DUPLICATE_JURISDICTION,
    ERR_DELIVERY_WINDOW_OVERLAP,
)
from middleware import (
    authenticate, require_role, parse_body, req_str, req_int, req_num,
    req_date, req_datetime, parse_datetime_str, parse_pagination, list_page,
)
from response import ok_object, ok_list

bp = Blueprint('supply', __name__)


# ------------------------------------------------------------ delivery windows

@bp.post('/delivery-windows')
def create_delivery_window():
    uid, role = authenticate()
    body = parse_body()
    route_code = req_str(body, 'route_code')
    window_start = req_datetime(body, 'window_start')
    window_end = req_datetime(body, 'window_end')
    buffer_minutes = req_int(body, 'turnaround_buffer_minutes', minimum=0)
    start_dt = parse_datetime_str(window_start, 'window_start')
    end_dt = parse_datetime_str(window_end, 'window_end')
    if not start_dt < end_dt:
        raise validation('window_start must be before window_end')
    require_role(role, ('WholesaleAdmin',))

    for w in STORE['delivery_windows'].values():
        if w['route_code'] != route_code:
            continue
        ws = w['_start_dt']
        we = w['_end_dt']
        wb = timedelta(minutes=w['turnaround_buffer_minutes'])
        nb = timedelta(minutes=buffer_minutes)
        if ((start_dt < we and ws < end_dt)
                or (start_dt >= ws and start_dt < we + wb)
                or (ws >= start_dt and ws < end_dt + nb)):
            raise ApiError(ERR_DELIVERY_WINDOW_OVERLAP, 409,
                           'new window overlaps an existing window on the same route')

    rec = new_record()
    rec.update({
        'route_code': route_code,
        'window_start': window_start,
        'window_end': window_end,
        'turnaround_buffer_minutes': buffer_minutes,
        '_start_dt': start_dt,
        '_end_dt': end_dt,
    })
    STORE['delivery_windows'][rec['id']] = rec
    return ok_object(public(rec), 201)


@bp.get('/delivery-windows')
def list_delivery_windows():
    uid, role = authenticate()
    require_role(role, ('WholesaleAdmin',))
    limit, offset = parse_pagination()
    items = list(STORE['delivery_windows'].values())
    route_code = request.args.get('route_code')
    if route_code is not None:
        items = [w for w in items if w['route_code'] == route_code]
    page, total = list_page(items, public, limit, offset)
    return ok_list(page, limit, offset, total)


# ---------------------------------------------------------- fuel surcharge rates

@bp.post('/fuel-surcharge-rates')
def create_fuel_rate():
    uid, role = authenticate()
    body = parse_body()
    week_start_date = req_date(body, 'week_start_date')
    doe_index_usd = req_num(body, 'doe_index_usd', minimum=0, exclusive_minimum=True)
    require_role(role, ('WholesaleAdmin',))

    for r in STORE['fuel_surcharge_rates'].values():
        if r['week_start_date'] == week_start_date:
            raise ApiError(ERR_DUPLICATE_RATE_WEEK, 409,
                           'fuel surcharge rate already published for that week_start_date')

    rec = new_record()
    rec.update({
        'week_start_date': week_start_date,
        'doe_index_usd': doe_index_usd,
    })
    STORE['fuel_surcharge_rates'][rec['id']] = rec
    return ok_object(public(rec), 201)


@bp.get('/fuel-surcharge-rates')
def list_fuel_rates():
    uid, role = authenticate()
    require_role(role, ('WholesaleAdmin', 'SalesRep'))
    limit, offset = parse_pagination()
    items = list(STORE['fuel_surcharge_rates'].values())
    page, total = list_page(items, public, limit, offset)
    return ok_list(page, limit, offset, total)


# ------------------------------------------------------------- tax stamp supplies

@bp.post('/tax-stamp-supplies')
def create_tax_stamp_supply():
    uid, role = authenticate()
    body = parse_body()
    jurisdiction_code = req_str(body, 'jurisdiction_code')
    stamp_rate = req_int(body, 'stamp_rate_cents_per_pack')
    handling_fee = req_int(body, 'handling_fee_per_roll_cents')
    packs_per_roll = req_int(body, 'packs_per_roll', minimum=1)
    min_charge = req_int(body, 'min_charge_cents')
    require_role(role, ('WholesaleAdmin',))

    for s in STORE['tax_stamp_supplies'].values():
        if s['jurisdiction_code'] == jurisdiction_code:
            raise ApiError(ERR_DUPLICATE_JURISDICTION, 409,
                           'tax stamp supply already exists for jurisdiction_code')

    rec = new_record()
    rec.update({
        'jurisdiction_code': jurisdiction_code,
        'stamp_rate_cents_per_pack': stamp_rate,
        'handling_fee_per_roll_cents': handling_fee,
        'packs_per_roll': packs_per_roll,
        'min_charge_cents': min_charge,
        'rolls_on_hand': 0,
        'status': 'ACTIVE',
    })
    STORE['tax_stamp_supplies'][rec['id']] = rec
    return ok_object(public(rec), 201)


@bp.get('/tax-stamp-supplies')
def list_tax_stamp_supplies():
    uid, role = authenticate()
    require_role(role, ('WholesaleAdmin', 'SalesRep'))
    limit, offset = parse_pagination()
    items = list(STORE['tax_stamp_supplies'].values())
    jurisdiction = request.args.get('jurisdiction_code')
    if jurisdiction is not None:
        items = [s for s in items if s['jurisdiction_code'] == jurisdiction]
    page, total = list_page(items, public, limit, offset)
    return ok_list(page, limit, offset, total)
