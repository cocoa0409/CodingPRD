from db import db
from util import new_id, fmt_ts, fmt_date, now


def new_entity():
    t = fmt_ts(now())
    return {'id': new_id(), 'created_at': t, 'updated_at': t, 'version': 1}


def new_evidence():
    """WeightTicket: immutable scale evidence carries only id and created_at."""
    return {'id': new_id(), 'created_at': fmt_ts(now())}


def touch(e):
    e['updated_at'] = fmt_ts(now())
    e['version'] += 1


# ---------------------------------------------------------------------------
# Serializers (datetimes stored internally as datetime; serialized ISO 8601)
# ---------------------------------------------------------------------------

def agent_view(a):
    return dict(a)


def customer_view(c):
    return dict(c)


def tariff_view(t):
    out = dict(t)
    out['effective_start'] = fmt_ts(t['effective_start'])
    out['effective_end'] = fmt_ts(t['effective_end'])
    out['mileage_bands'] = [dict(b) for b in t['mileage_bands']]
    return out


def order_view(o):
    out = dict(o)
    out['pickup_date'] = fmt_date(o['pickup_date'])
    out['earliest_delivery_date'] = fmt_date(o['earliest_delivery_date'])
    out['latest_delivery_date'] = fmt_date(o['latest_delivery_date'])
    out['delivered_at'] = fmt_ts(o['delivered_at'])
    return out


def estimate_view(e):
    out = dict(e)
    out['issued_at'] = fmt_ts(e['issued_at'])
    out['expires_at'] = fmt_ts(e['expires_at'])
    return out


def assignment_view(a):
    return dict(a)


def coverage_view(c):
    return dict(c)


def weight_ticket_view(t):
    out = dict(t)
    out['weighed_at'] = fmt_ts(t['weighed_at'])
    return out


def reweigh_view(r):
    return dict(r)


def warehouse_view(w):
    return dict(w)


def sit_lot_view(lot):
    from services.lifecycle import sit_lot_live_fields
    out = dict(lot)
    days, accrual = sit_lot_live_fields(lot)
    out['days_stored'] = days
    out['accrued_storage_cents'] = accrual
    out['checked_in_at'] = fmt_ts(lot['checked_in_at'])
    out['released_at'] = fmt_ts(lot['released_at'])
    return out


def crew_view(c):
    out = dict(c)
    out['service_date'] = fmt_date(c['service_date'])
    return out


def statement_view(s):
    return dict(s)


def claim_view(c):
    out = dict(c)
    out['filed_at'] = fmt_ts(c['filed_at'])
    return out


def dispute_view(d):
    out = dict(d)
    out['responded_at'] = fmt_ts(d['responded_at'])
    out['escalated_at'] = fmt_ts(d['escalated_at'])
    return out
