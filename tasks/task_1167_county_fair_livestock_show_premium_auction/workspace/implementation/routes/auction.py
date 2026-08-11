"""Auction lots, add-on pledges and buyer invoices."""
from decimal import Decimal
from flask import Blueprint, request

import errors
import services
from db import store, new_record, touch
from middleware import require_roles, authenticate
from response import success_object, success_list
from util import (
    body, require, require_int,
    pagination_params, sorted_created, apply_filters, is_int,
)
from views import auction_lot_view, add_on_view, invoice_view

bp = Blueprint('auction', __name__)


def get_lot_or_404(lot_id):
    l = store.auction_lots.get(lot_id)
    if l is None:
        raise errors.not_found('AuctionLot not found')
    return l


def _fair_of_lot(lot):
    return store.fairs[lot['fair_id']]


# --------------------------------------------------------------- Auction lots

@bp.post('/v1/auction-lots/generate')
def generate_lots():
    require_roles('Auctioneer')
    b = body()
    fair_id = require(b, 'fair_id')
    fair = store.fairs.get(fair_id)
    if fair is None:
        raise errors.not_found('Fair not found')
    if fair['posture'] != 'AUCTION':
        raise errors.posture_forbids('Sale order generation requires AUCTION posture')

    sale_order = fair.get('species_sale_order') or []
    thresholds = fair.get('sale_rank_threshold') or {}
    lots_by_entry = {l['entry_id'] for l in store.auction_lots.values()}

    eligible = []
    for e in store.entries.values():
        if e['fair_id'] != fair_id or e['status'] != 'SHOWN':
            continue
        if e['id'] in lots_by_entry:
            continue
        exhibitor = store.exhibitors.get(e['exhibitor_id'])
        if exhibitor is None or exhibitor['status'] != 'ACTIVE':
            continue
        # Health record must be clean: no FAIL ever; latest (if any) is PASS.
        inspections = [h for h in store.health_inspections.values()
                       if h['entry_id'] == e['id']]
        if any(h['result'] == 'FAIL' for h in inspections):
            continue
        latest = services.latest_inspection(e['id'])
        if latest is not None and latest['result'] != 'PASS':
            continue
        # Earned its way in via the entry's RECORDED placing.
        placing = next((p for p in store.placings.values()
                        if p['entry_id'] == e['id'] and p['status'] == 'RECORDED'), None)
        if placing is None:
            continue
        threshold = thresholds.get(e['species'])
        if not (placing['award'] != 'NONE'
                or (threshold is not None and placing['rank'] <= threshold)):
            continue
        tier = {'GRAND_CHAMPION': 0, 'RESERVE_CHAMPION': 1}.get(placing['award'], 2)
        try:
            species_idx = sale_order.index(e['species'])
        except ValueError:
            species_idx = len(sale_order)
        eligible.append((tier, species_idx, placing['rank'], e['created_at'], e['_seq'], e))

    eligible.sort(key=lambda t: (t[0], t[1], t[2], t[3], t[4]))

    existing_numbers = [l['lot_number'] for l in store.auction_lots.values()
                        if l['fair_id'] == fair_id]
    next_number = max(existing_numbers) + 1 if existing_numbers else 1

    lot_ids = []
    for i, (_, _, _, _, _, e) in enumerate(eligible):
        lot = new_record({
            'fair_id': fair_id,
            'entry_id': e['id'],
            'lot_number': next_number + i,
            'status': 'QUEUED',
            'buyer_id': None,
            'hammer_price_cents': None,
            'invoice_id': None,
            'reoffer_count': 0,
            'provisional_payout_cents': None,
            'final_payout_cents': None,
        })
        store.auction_lots[lot['id']] = lot
        lot_ids.append(lot['id'])

    return success_object({'lot_ids': lot_ids, 'lot_count': len(lot_ids)}, status=201)


@bp.get('/v1/auction-lots/<lotId>')
def get_lot(lotId):
    authenticate()
    return success_object(auction_lot_view(get_lot_or_404(lotId)))


@bp.get('/v1/auction-lots')
def list_lots():
    authenticate()
    limit, offset = pagination_params()
    recs = apply_filters(store.auction_lots.values(), {
        'fair_id': request.args.get('fair_id'),
        'entry_id': request.args.get('entry_id'),
        'buyer_id': request.args.get('buyer_id'),
        'invoice_id': request.args.get('invoice_id'),
        'status': request.args.get('status'),
    })
    return success_list([auction_lot_view(l) for l in sorted_created(recs)], limit, offset)


@bp.post('/v1/auction-lots/<lotId>/open')
def open_lot(lotId):
    require_roles('Auctioneer')
    lot = get_lot_or_404(lotId)
    if lot['status'] != 'QUEUED':
        raise errors.invalid_state('Only a QUEUED lot can be opened')
    # Strict sale order: every smaller-numbered lot must be past QUEUED.
    for other in store.auction_lots.values():
        if (other['fair_id'] == lot['fair_id']
                and other['lot_number'] < lot['lot_number']
                and other['status'] == 'QUEUED'):
            raise errors.invalid_state('Lots must open in strict lot_number order')
    fair = _fair_of_lot(lot)
    if fair['posture'] != 'AUCTION':
        raise errors.posture_forbids('Lot operations require AUCTION posture')
    lot['status'] = 'OPEN'
    touch(lot)
    return success_object(auction_lot_view(lot))


@bp.post('/v1/auction-lots/<lotId>/close-sold')
def close_sold(lotId):
    require_roles('Auctioneer')
    lot = get_lot_or_404(lotId)
    b = body()
    buyer_id = require(b, 'buyer_id')
    buyer = store.buyers.get(buyer_id)
    if buyer is None:
        raise errors.not_found('Buyer not found')
    if lot['status'] != 'OPEN':
        raise errors.invalid_state('Only an OPEN lot can be closed as sold')
    fair = _fair_of_lot(lot)
    if fair['posture'] != 'AUCTION':
        raise errors.posture_forbids('Lot operations require AUCTION posture')

    hammer = require(b, 'hammer_price_cents')
    if not is_int(hammer):
        raise errors.invalid_request('hammer_price_cents must be an integer')
    # Fiscal ladder: credit exposure before amount positivity (inclusive bound).
    committed = services.buyer_committed_cents(buyer_id)
    if committed + hammer > buyer['credit_limit_cents']:
        raise errors.err('ERR_CREDIT_LIMIT_EXCEEDED', 422,
                         'Buyer credit limit would be exceeded')
    if hammer <= 0:
        raise errors.err('ERR_INVALID_AMOUNT', 422, 'hammer_price_cents must be > 0')

    # cascade_close_sold link 1: the lot itself.
    lot['buyer_id'] = buyer_id
    lot['hammer_price_cents'] = hammer
    lot['provisional_payout_cents'] = services.exhibitor_payout_provisional(fair, hammer)
    lot['status'] = 'SOLD'
    touch(lot)

    # Link 2: entry SHOWN -> SOLD.
    entry = store.entries[lot['entry_id']]
    if entry['status'] == 'SHOWN':
        entry['status'] = 'SOLD'
        touch(entry)

    # Link 3: sale requires harvest — reject pending RETURN orders, then
    # auto-create a HARVEST order recorded as created by SYSTEM.
    for d in store.dispositions.values():
        if (d['entry_id'] == entry['id'] and d['disposition_type'] == 'RETURN'
                and d['status'] in ('REQUESTED', 'APPROVED')):
            d['status'] = 'REJECTED'
            d['reject_reason'] = 'SALE_REQUIRES_HARVEST'
            touch(d)
    auto = new_record({
        'entry_id': entry['id'],
        'disposition_type': 'HARVEST',
        'destination': None,
        'scheduled_date': None,
        'status': 'REQUESTED',
        'created_by_user_id': 'SYSTEM',
        'approved_by_user_id': None,
        'reject_reason': None,
    })
    store.dispositions[auto['id']] = auto

    # Link 4: buyer DRAFT invoice upsert; totals live-derive from here on.
    services.get_or_create_draft_invoice(fair['id'], buyer_id)

    return success_object(auction_lot_view(lot))


@bp.post('/v1/auction-lots/<lotId>/close-passed')
def close_passed(lotId):
    require_roles('Auctioneer')
    lot = get_lot_or_404(lotId)
    if lot['status'] != 'OPEN':
        raise errors.invalid_state('Only an OPEN lot can be passed')
    fair = _fair_of_lot(lot)
    if fair['posture'] != 'AUCTION':
        raise errors.posture_forbids('Lot operations require AUCTION posture')
    lot['status'] = 'PASSED'
    touch(lot)
    return success_object(auction_lot_view(lot))


@bp.post('/v1/auction-lots/<lotId>/reoffer')
def reoffer_lot(lotId):
    require_roles('Auctioneer')
    lot = get_lot_or_404(lotId)
    if lot['status'] != 'PASSED':
        raise errors.invalid_state('Only a PASSED lot can be reoffered')
    fair = _fair_of_lot(lot)
    if fair['posture'] != 'AUCTION':
        raise errors.posture_forbids('Lot operations require AUCTION posture')
    if lot['reoffer_count'] >= 2:
        raise errors.err('ERR_REOFFER_LIMIT_REACHED', 409,
                         'A lot may be reoffered at most twice')
    lot['reoffer_count'] += 1
    lot['status'] = 'OPEN'
    touch(lot)
    return success_object(auction_lot_view(lot))


@bp.post('/v1/auction-lots/<lotId>/no-sale')
def no_sale_lot(lotId):
    require_roles('Auctioneer')
    lot = get_lot_or_404(lotId)
    if lot['status'] != 'PASSED':
        raise errors.invalid_state('Only a PASSED lot can be declared no-sale')
    fair = _fair_of_lot(lot)
    if fair['posture'] != 'AUCTION':
        raise errors.posture_forbids('Lot operations require AUCTION posture')
    lot['status'] = 'NO_SALE'
    touch(lot)
    entry = store.entries[lot['entry_id']]
    if entry['status'] == 'SHOWN':
        entry['status'] = 'NOT_SOLD'
        touch(entry)
    return success_object(auction_lot_view(lot))


# --------------------------------------------------------------- Add-on pledges

@bp.post('/v1/add-ons')
def create_add_on():
    user_id, role = require_roles('Buyer', 'FairBoardAdmin')
    b = body()
    if role == 'Buyer':
        buyer_id = b.get('buyer_id')
        if buyer_id is not None and buyer_id != user_id:
            raise errors.forbidden('Buyers may pledge only for themselves')
    lot_id = require(b, 'lot_id')
    lot = store.auction_lots.get(lot_id)
    if lot is None:
        raise errors.not_found('AuctionLot not found')
    buyer_id = require(b, 'buyer_id')
    buyer = store.buyers.get(buyer_id)
    if buyer is None:
        raise errors.not_found('Buyer not found')
    if role == 'Buyer' and buyer_id != user_id:
        raise errors.forbidden('Buyers may pledge only for themselves')

    # Referential rule before the fiscal amount rule.
    if lot['status'] != 'SOLD' or lot['invoice_id'] is not None:
        raise errors.err('ERR_LOT_NOT_SOLD', 409,
                         'Add-on pledges require a SOLD lot not yet swept into an ISSUED invoice')
    amount = require(b, 'amount_cents')
    if not is_int(amount):
        raise errors.invalid_request('amount_cents must be an integer')
    if amount <= 0:
        raise errors.err('ERR_INVALID_AMOUNT', 422, 'amount_cents must be > 0')

    pledge = new_record({
        'lot_id': lot_id,
        'buyer_id': buyer_id,
        'invoice_id': None,
        'amount_cents': amount,
        'status': 'PLEDGED',
    })
    store.add_ons[pledge['id']] = pledge
    # The pledging buyer's DRAFT invoice picks the line up via live totals.
    services.get_or_create_draft_invoice(lot['fair_id'], buyer_id)
    return success_object(add_on_view(pledge), status=201)


@bp.get('/v1/add-ons/<addonId>')
def get_add_on(addonId):
    authenticate()
    p = store.add_ons.get(addonId)
    if p is None:
        raise errors.not_found('AddOnPledge not found')
    return success_object(add_on_view(p))


@bp.get('/v1/add-ons')
def list_add_ons():
    authenticate()
    limit, offset = pagination_params()
    recs = apply_filters(store.add_ons.values(), {
        'lot_id': request.args.get('lot_id'),
        'buyer_id': request.args.get('buyer_id'),
        'invoice_id': request.args.get('invoice_id'),
        'status': request.args.get('status'),
    })
    return success_list([add_on_view(p) for p in sorted_created(recs)], limit, offset)


@bp.post('/v1/add-ons/<addonId>/void')
def void_add_on(addonId):
    user_id, role = require_roles('Buyer', 'FairBoardAdmin')
    p = store.add_ons.get(addonId)
    if p is None:
        raise errors.not_found('AddOnPledge not found')
    if role == 'Buyer' and p['buyer_id'] != user_id:
        raise errors.forbidden('Buyers may void only their own pledges')
    if p['status'] != 'PLEDGED':
        raise errors.invalid_state('Only a PLEDGED add-on can be voided')
    p['status'] = 'VOIDED'
    touch(p)
    return success_object(add_on_view(p))


# ------------------------------------------------------------------ Invoices

@bp.get('/v1/invoices/<invoiceId>')
def get_invoice(invoiceId):
    authenticate()
    inv = store.invoices.get(invoiceId)
    if inv is None:
        raise errors.not_found('Invoice not found')
    return success_object(invoice_view(inv))


@bp.get('/v1/invoices')
def list_invoices():
    authenticate()
    limit, offset = pagination_params()
    recs = apply_filters(store.invoices.values(), {
        'fair_id': request.args.get('fair_id'),
        'buyer_id': request.args.get('buyer_id'),
        'status': request.args.get('status'),
    })
    return success_list([invoice_view(i) for i in sorted_created(recs)], limit, offset)


@bp.post('/v1/invoices/<invoiceId>/issue')
def issue_invoice(invoiceId):
    require_roles('Treasurer')
    inv = store.invoices.get(invoiceId)
    if inv is None:
        raise errors.not_found('Invoice not found')
    if inv['status'] != 'DRAFT':
        raise errors.invalid_state('Only a DRAFT invoice can be issued')
    fair = store.fairs[inv['fair_id']]
    if fair['posture'] != 'SETTLEMENT':
        raise errors.posture_forbids('Invoice issue requires SETTLEMENT posture')

    lots = [l for l in store.auction_lots.values()
            if l['buyer_id'] == inv['buyer_id'] and l['status'] == 'SOLD'
            and l['invoice_id'] is None]
    pledges = [p for p in store.add_ons.values()
               if p['buyer_id'] == inv['buyer_id'] and p['status'] == 'PLEDGED'
               and p['invoice_id'] is None]
    if not lots and not pledges:
        raise errors.invalid_state('At least one unswept line is required to issue')

    # Freeze totals with the pinned per-line premium rounding order.
    hammer, addon, premium, total, lines = services.invoice_line_totals(fair, lots, pledges)
    for lot in sorted_created(lots):
        lot['invoice_id'] = inv['id']
        touch(lot)
    for p in sorted_created(pledges):
        p['status'] = 'INVOICED'
        p['invoice_id'] = inv['id']
        touch(p)
    inv['hammer_subtotal_cents'] = hammer
    inv['addon_subtotal_cents'] = addon
    inv['buyer_premium_cents'] = premium
    inv['total_due_cents'] = total
    inv['balance_cents'] = total - inv['amount_paid_cents']
    inv['line_count'] = lines
    inv['status'] = 'ISSUED'
    touch(inv)
    return success_object(invoice_view(inv))


@bp.post('/v1/invoices/<invoiceId>/payments')
def post_payment(invoiceId):
    require_roles('Treasurer')
    inv = store.invoices.get(invoiceId)
    if inv is None:
        raise errors.not_found('Invoice not found')
    if inv['status'] not in ('ISSUED', 'PARTIALLY_PAID'):
        raise errors.invalid_state('Payments require an ISSUED or PARTIALLY_PAID invoice')
    fair = store.fairs[inv['fair_id']]
    if fair['posture'] != 'SETTLEMENT':
        raise errors.posture_forbids('Invoice payments require SETTLEMENT posture')
    b = body()
    amount = require(b, 'amount_cents')
    if not is_int(amount):
        raise errors.invalid_request('amount_cents must be an integer')
    if amount <= 0:
        raise errors.err('ERR_INVALID_AMOUNT', 422, 'amount_cents must be > 0')
    balance = inv['total_due_cents'] - inv['amount_paid_cents']
    if amount > balance:
        raise errors.err('ERR_OVERPAYMENT', 422, 'Payment exceeds the invoice balance')

    inv['amount_paid_cents'] += amount
    inv['balance_cents'] = inv['total_due_cents'] - inv['amount_paid_cents']
    if inv['balance_cents'] == 0:
        inv['status'] = 'PAID'
        for p in store.add_ons.values():
            if p['invoice_id'] == inv['id'] and p['status'] == 'INVOICED':
                p['status'] = 'PAID'
                touch(p)
    else:
        inv['status'] = 'PARTIALLY_PAID'
    touch(inv)
    return success_object(invoice_view(inv))
