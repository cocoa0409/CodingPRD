"""The logical clock and the append-only revenue ledger reads."""
from flask import Blueprint

import envelope as env
import ser
import svc
import validate as v
from errors import ApiError
from store import by_created, db, iso, set_clock

bp = Blueprint('revenue', __name__)

ENTRY_CATEGORIES = ('BAGGAGE', 'SEAT', 'CHANGE', 'BOARDING', 'ONBOARD',
                    'AIR_TRANSPORT')
ENTRY_TYPES = ('ALLOCATION', 'SALE', 'REFUND', 'WAIVER_CREDIT',
               'WAIVER_REVERSAL')


@bp.post('/_clock/set_current_utc')
def set_current_utc():
    v.ctx(v.ALL_ROLES)
    data = v.fields(v.body(), [('to_iso8601', True, v.v_datetime)])
    set_clock(v.parse_iso(data['to_iso8601']))
    swept = svc.sweep_expired_offers()
    return env.obj({'current_utc': iso(db.clock),
                    'expired_offer_count': swept})


@bp.get('/revenue-entries/<id>')
def read_entry(id):
    v.ctx(('RevenueAccountant',))
    entry = db.revenue.get(id) if isinstance(id, str) else None
    if entry is None:
        # the PRD catalogue declares no not-found id for the ledger itself;
        # the read still answers 404 by path per 2.7 step 4.
        error = ApiError('ERR_REVENUE_ENTRY_NOT_FOUND')
        error.http_status = 404
        raise error
    return env.obj(ser.revenue_entry(entry))


@bp.get('/revenue-entries')
def list_entries():
    v.ctx(('RevenueAccountant',))
    limit, offset = v.pagination()
    booking_id = v.q_str('booking_id')
    category = v.q_enum('category', ENTRY_CATEGORIES)
    entry_type = v.q_enum('entry_type', ENTRY_TYPES)
    period = v.q_str('accounting_period')
    rows = [e for e in db.revenue.values()
            if (booking_id is None or e['booking_id'] == booking_id)
            and (category is None or e['category'] == category)
            and (entry_type is None or e['entry_type'] == entry_type)
            and (period is None or e['accounting_period'] == period)]
    return env.page(by_created(rows), ser.revenue_entry, limit, offset)


@bp.get('/bookings/<id>/revenue-entries')
def booking_entries(id):
    v.ctx(('RevenueAccountant',))
    limit, offset = v.pagination()
    entry_type = v.q_enum('entry_type', ENTRY_TYPES)
    booking = svc.booking_or_404(id)
    rows = [e for e in svc.entries_of_booking(booking['id'])
            if entry_type is None or e['entry_type'] == entry_type]
    return env.page(by_created(rows), ser.revenue_entry, limit, offset)
