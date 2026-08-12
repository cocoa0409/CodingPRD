"""Entity serializers: shape each stored record for the API envelope."""
from db import store
from services import available_pool, placed_count, draft_invoice_totals
from util import serialize


def fair_view(f):
    out = serialize(f, dt_fields=('ownership_deadline_at', 'possession_deadline_at'))
    out['available_premium_pool_cents'] = available_pool(f)
    return out


def exhibitor_view(e):
    return serialize(e)


def entry_view(e):
    return serialize(e, dt_fields=('ownership_acquired_at', 'possession_start_at'))


def weigh_ticket_view(t):
    return serialize(t, dt_fields=('weighed_at',))


def class_view(c):
    out = serialize(c)
    out['placed_count'] = placed_count(c['id'])
    return out


def judge_view(j):
    return serialize(j)


def ring_slot_view(s):
    return serialize(s, dt_fields=('starts_at', 'ends_at'))


def placing_view(p):
    return serialize(p)


def premium_award_view(a):
    return serialize(a)


def buyer_view(b):
    return serialize(b)


def auction_lot_view(l):
    return serialize(l)


def add_on_view(p):
    return serialize(p)


def invoice_view(inv):
    out = serialize(inv)
    if inv['status'] == 'DRAFT':
        hammer, addon, premium, total, lines = draft_invoice_totals(inv)
        out['hammer_subtotal_cents'] = hammer
        out['addon_subtotal_cents'] = addon
        out['buyer_premium_cents'] = premium
        out['total_due_cents'] = total
        out['amount_paid_cents'] = 0
        out['balance_cents'] = total
        out['line_count'] = lines
    return out


def disposition_view(d):
    return serialize(d, dt_fields=('scheduled_date',))


def health_inspection_view(h):
    # Immutable record: only id + created_at audit fields, no updated_at/version.
    return serialize(h)


def affidavit_view(a):
    return serialize(a, dt_fields=('signed_at', 'withdrawal_end_date'))
