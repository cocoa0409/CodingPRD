"""Mutating cascades and cross-entity side effects (SCAFFOLD §1.2)."""
from datetime import timedelta

import db
from services import calc


def recompute_book(tank):
    """Recompute a tank's derived book inventory; bump version on change."""
    new_book = calc.book_inventory_gallons(tank)
    if new_book != tank['book_inventory_gallons']:
        tank['book_inventory_gallons'] = new_book
        db.touch(tank)


def apply_credit_band(station):
    """Band re-eval on every exposure recompute. HOLD is never touched."""
    if station['credit_status'] == 'HOLD':
        return
    station['credit_status'] = calc.credit_band_for(
        station['current_exposure_cents'], station['credit_limit_cents'])


def recompute_exposure(station):
    """Invoice create / void / draft settle: exposure + band, one version bump
    when anything actually changed."""
    before = (station['current_exposure_cents'], station['credit_status'])
    station['current_exposure_cents'] = calc.station_exposure_cents(
        station['id'])
    apply_credit_band(station)
    if (station['current_exposure_cents'], station['credit_status']) != before:
        db.touch(station)


def _create_auto_loss(recon, variance_net):
    """Cascade hop 4: auto shrinkage LossEvent on transition into
    VARIANCE_FLAGGED."""
    rec = {
        'id': db.new_id(),
        'station_id': recon['station_id'],
        'tank_id': None,
        'reconciliation_id': recon['id'],
        'loss_type': 'SHRINKAGE',
        'gallons': abs(int(variance_net)),
        'occurred_at': db.clock_now(),
        'auto_generated': True,
        'status': 'REPORTED',
    }
    db.stamp_new(rec)
    db.STORE['losses'][rec['id']] = rec
    return rec


def recompute_open_recon(station_id):
    """Cascade hops 2-3 (+4 on flag): recompute the station's OPEN /
    VARIANCE_FLAGGED reconciliation, flip vs threshold, auto-loss on flag."""
    recon = None
    for r in db.STORE['recons'].values():
        if (r['station_id'] == station_id
                and r['status'] in ('OPEN', 'VARIANCE_FLAGGED')):
            recon = r
            break
    if recon is None:
        return
    figs = calc.recon_figures(station_id)
    changed = False
    for k, v in figs.items():
        if recon[k] != v:
            recon[k] = v
            changed = True
    flagged = abs(figs['variance_net_gallons']) > recon['threshold_gallons']
    if flagged and recon['status'] == 'OPEN':
        recon['status'] = 'VARIANCE_FLAGGED'
        changed = True
        _create_auto_loss(recon, figs['variance_net_gallons'])
    elif not flagged and recon['status'] == 'VARIANCE_FLAGGED':
        recon['status'] = 'OPEN'
        changed = True
    if changed:
        db.touch(recon)


def station_default_cascade(station):
    """CURE_PERIOD -> DEFAULT: every ACTIVE agreement -> DEFAULT_NOTICE."""
    station['compliance_status'] = 'DEFAULT'
    station['cure_started_at'] = None
    db.touch(station)
    for ag in db.STORE['agreements'].values():
        if ag['station_id'] == station['id'] and ag['status'] == 'ACTIVE':
            ag['status'] = 'DEFAULT_NOTICE'
            db.touch(ag)


def evaluate_clock_transitions():
    """Auto-transitions evaluated whenever the logical clock is set."""
    clock_date = db.clock_date_str()
    for inv in db.STORE['invoices'].values():
        if inv['status'] == 'ISSUED' and inv['due_date'] < clock_date:
            inv['status'] = 'OVERDUE'
            db.touch(inv)
    for ag in db.STORE['agreements'].values():
        if (ag['status'] in ('ACTIVE', 'RENEWAL_PENDING')
                and ag['term_end_date'] < clock_date):
            ag['status'] = 'EXPIRED'
            db.touch(ag)
    now = db.clock_now()
    for st in db.STORE['stations'].values():
        if st['compliance_status'] != 'CURE_PERIOD':
            continue
        if st['cure_started_at'] is None:
            continue
        if now > st['cure_started_at'] + timedelta(days=30):
            station_default_cascade(st)


def recompute_meter_deltas(tank_id):
    """metered_gallons_delta: order by (reading_at, created_at); each reading's
    delta vs its chronological predecessor (0 for the first)."""
    readings = sorted(
        (m for m in db.STORE['meters'].values() if m['tank_id'] == tank_id),
        key=lambda m: (m['reading_at'], m['_seq']))
    prev = None
    for m in readings:
        m['metered_gallons'] = (0 if prev is None
                                else m['totalizer_gallons']
                                - prev['totalizer_gallons'])
        prev = m
