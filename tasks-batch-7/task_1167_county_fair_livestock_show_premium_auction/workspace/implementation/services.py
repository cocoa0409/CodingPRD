"""Business logic: calculations (scaffold Table 3) and compensation cascades."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from db import store, new_record, touch
from util import PLACED_STATUSES


# --------------------------------------------------------------------------
# Numeric helpers: money is integer cents; Decimal everywhere, never float.
# --------------------------------------------------------------------------

def dnum(v):
    """Decimal view of a JSON number, exact for typical one-decimal inputs."""
    return Decimal(str(v))


def round_half_up_cents(d):
    return int(d.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def floor_cents(d):
    return int(d.quantize(Decimal('1'), rounding=ROUND_FLOOR))


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------

def fair_of_entry(entry):
    return store.fairs.get(entry['fair_id'])


def entries_of_fair(fair_id):
    return [e for e in store.entries.values() if e['fair_id'] == fair_id]


def awards_of_fair(fair_id):
    return [a for a in store.premium_awards.values()
            if store.entries[a['entry_id']]['fair_id'] == fair_id]


def affidavit_of_entry(entry_id):
    for a in store.affidavits.values():
        if a['entry_id'] == entry_id:
            return a
    return None


def signed_affidavit(entry_id):
    a = affidavit_of_entry(entry_id)
    return a if a is not None and a['status'] == 'SIGNED' else None


def latest_inspection(entry_id):
    cands = [h for h in store.health_inspections.values() if h['entry_id'] == entry_id]
    if not cands:
        return None
    return max(cands, key=lambda h: (h['created_at'], h['_seq']))


# --------------------------------------------------------------------------
# Calculation: official_weight_resolution
# --------------------------------------------------------------------------

def resolve_official_weight(entry):
    """Latest ACTIVE ticket wins: max created_at, then max weighed_at, then
    max weight_lbs. id never participates. None when no ACTIVE ticket."""
    cands = [t for t in store.weigh_tickets.values()
             if t['entry_id'] == entry['id'] and t['status'] == 'ACTIVE']
    if not cands:
        entry['official_weight_lbs'] = None
        return None
    best = max(cands, key=lambda t: (t['created_at'], t['weighed_at'], dnum(t['weight_lbs'])))
    entry['official_weight_lbs'] = best['weight_lbs']
    return best


# --------------------------------------------------------------------------
# Calculation: class_placed_count (derived count over placed statuses)
# --------------------------------------------------------------------------

def placed_count(class_id):
    return sum(1 for e in store.entries.values()
               if e.get('class_id') == class_id and e['status'] in PLACED_STATUSES)


# --------------------------------------------------------------------------
# Calculation: premium_pool_reconciliation
# available = budget - sum(provisional of awards in ACCRUED/APPROVED/PAID)
# --------------------------------------------------------------------------

def available_pool(fair):
    outstanding = sum(a['provisional_amount_cents'] for a in awards_of_fair(fair['id'])
                      if a['status'] in ('ACCRUED', 'APPROVED', 'PAID'))
    return fair['premium_budget_cents'] - outstanding


# --------------------------------------------------------------------------
# Calculation: premium_award_amount (provisional variant)
# --------------------------------------------------------------------------

def premium_provisional(fair, entry, class_size, rank, award):
    schedule = fair['premium_schedule'].get(entry['species'], {}) or {}
    if award == 'GRAND_CHAMPION':
        base = schedule.get('grand_champion_cents', 0)
    elif award == 'RESERVE_CHAMPION':
        base = schedule.get('reserve_champion_cents', 0)
    elif rank == 1:
        base = schedule.get('rank_1_cents', 0)
    elif rank == 2:
        base = schedule.get('rank_2_cents', 0)
    elif rank == 3:
        base = schedule.get('rank_3_cents', 0)
    else:
        base = schedule.get('other_rank_cents', 0)
    # Large-class bonus: placed_count after the placing batch lands; round
    # half-up to whole cents; cap applies AFTER the bonus.
    if class_size >= fair['large_class_min_entries']:
        bonus = round_half_up_cents(Decimal(base) * dnum(fair['large_class_bonus_rate']))
    else:
        bonus = 0
    return min(base + bonus, fair['premium_cap_cents'])


# --------------------------------------------------------------------------
# Calculation: state_fair_qualification (inclusive boundary)
# --------------------------------------------------------------------------

def compute_state_fair_qualified(fair, entry, rank, award):
    if award != 'NONE':
        return True
    threshold = (fair.get('state_qualify_rank') or {}).get(entry['species'])
    if threshold is None:
        return False
    return rank <= threshold


# --------------------------------------------------------------------------
# Calculation: buyer_exposure_check (inclusive boundary)
# --------------------------------------------------------------------------

def buyer_committed_cents(buyer_id):
    total = 0
    for lot in store.auction_lots.values():
        if lot['buyer_id'] == buyer_id and lot['status'] == 'SOLD':
            inv = store.invoices.get(lot['invoice_id']) if lot['invoice_id'] else None
            if inv is None or inv['status'] != 'PAID':
                total += lot['hammer_price_cents']
    for p in store.add_ons.values():
        if p['buyer_id'] == buyer_id and p['status'] in ('PLEDGED', 'INVOICED'):
            total += p['amount_cents']
    return total


# --------------------------------------------------------------------------
# Calculation: exhibitor_payout (provisional and final variants)
# --------------------------------------------------------------------------

def exhibitor_payout_provisional(fair, hammer_price_cents):
    commission = round_half_up_cents(Decimal(hammer_price_cents) * dnum(fair['commission_rate']))
    return hammer_price_cents - commission - fair['yardage_fee_cents']


def exhibitor_payout_final(fair, lot):
    commission = round_half_up_cents(Decimal(lot['hammer_price_cents']) * dnum(fair['commission_rate']))
    addons = sum(p['amount_cents'] for p in store.add_ons.values()
                 if p['lot_id'] == lot['id'] and p['status'] != 'VOIDED')
    return lot['hammer_price_cents'] + addons - commission - fair['yardage_fee_cents']


# --------------------------------------------------------------------------
# Calculation: invoice_totals — PINNED per-line premium rounding, then sum
# --------------------------------------------------------------------------

def invoice_line_totals(fair, lots, pledges):
    hammer_subtotal = sum(l['hammer_price_cents'] for l in lots)
    addon_subtotal = sum(p['amount_cents'] for p in pledges)
    buyer_premium = sum(
        round_half_up_cents(Decimal(l['hammer_price_cents']) * dnum(fair['buyer_premium_rate']))
        for l in lots
    )
    total_due = hammer_subtotal + addon_subtotal + buyer_premium
    line_count = len(lots) + len(pledges)
    return hammer_subtotal, addon_subtotal, buyer_premium, total_due, line_count


def draft_invoice_totals(invoice):
    """DRAFT invoices live-derive totals from the buyer's unswept lines."""
    fair = store.fairs[invoice['fair_id']]
    lots = [l for l in store.auction_lots.values()
            if l['buyer_id'] == invoice['buyer_id'] and l['status'] == 'SOLD'
            and l['invoice_id'] is None]
    pledges = [p for p in store.add_ons.values()
               if p['buyer_id'] == invoice['buyer_id'] and p['status'] == 'PLEDGED'
               and p['invoice_id'] is None]
    return invoice_line_totals(fair, lots, pledges)


def get_or_create_draft_invoice(fair_id, buyer_id):
    for inv in store.invoices.values():
        if inv['buyer_id'] == buyer_id and inv['status'] == 'DRAFT':
            return inv
    inv = new_record({
        'fair_id': fair_id,
        'buyer_id': buyer_id,
        'status': 'DRAFT',
        'hammer_subtotal_cents': 0,
        'addon_subtotal_cents': 0,
        'buyer_premium_cents': 0,
        'total_due_cents': 0,
        'amount_paid_cents': 0,
        'balance_cents': 0,
        'line_count': 0,
    })
    store.invoices[inv['id']] = inv
    return inv


# --------------------------------------------------------------------------
# Cascade: cascade_disqualify_entry (PRD §3.8)
# --------------------------------------------------------------------------

def cascade_disqualify_entry(entry, reason):
    """Compensates everything the entry touched. Call only from a valid
    from-state (VERIFIED, WEIGHED, CLASSIFIED, SHOWN, NOT_SOLD)."""
    fair = fair_of_entry(entry)
    was = entry['status']

    # Link 1: entry itself.
    entry['status'] = 'DISQUALIFIED'
    entry['disqualification_reason'] = reason
    entry['state_fair_qualified'] = False
    old_class_id = entry.get('class_id')
    if was in ('CLASSIFIED', 'SHOWN'):
        entry['class_id'] = None
    touch(entry)

    # Class compensation: placed_count is derived, so a status change is
    # enough for the count; a FINALIZED class reopens to OPEN.
    if was in ('CLASSIFIED', 'SHOWN') and old_class_id:
        cls = store.classes.get(old_class_id)
        if cls is not None:
            if cls['status'] == 'FINALIZED':
                cls['status'] = 'OPEN'
            touch(cls)

    # Link 2: RECORDED placings -> VOIDED.
    for p in store.placings.values():
        if p['entry_id'] == entry['id'] and p['status'] == 'RECORDED':
            p['status'] = 'VOIDED'
            p['void_reason'] = 'ENTRY_DISQUALIFIED'
            touch(p)

    # Link 3: ACCRUED/APPROVED awards -> FORFEITED (reservation returns).
    forfeited = False
    for a in store.premium_awards.values():
        if a['entry_id'] == entry['id'] and a['status'] in ('ACCRUED', 'APPROVED'):
            a['status'] = 'FORFEITED'
            touch(a)
            forfeited = True
    if forfeited and fair is not None:
        touch(fair)  # pool reconciliation mutates the fair

    # Link 4: QUEUED/PASSED lots -> NO_SALE.
    for lot in store.auction_lots.values():
        if lot['entry_id'] == entry['id'] and lot['status'] in ('QUEUED', 'PASSED'):
            lot['status'] = 'NO_SALE'
            touch(lot)

    # Link 5: REQUESTED/APPROVED dispositions -> REJECTED.
    for d in store.dispositions.values():
        if d['entry_id'] == entry['id'] and d['status'] in ('REQUESTED', 'APPROVED'):
            d['status'] = 'REJECTED'
            d['reject_reason'] = 'ENTRY_DISQUALIFIED'
            touch(d)
