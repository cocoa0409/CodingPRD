"""Business logic: patronage waterfall, per-unit retains, redemption pro-rata,
certificate lifecycle, tax form issuance, and cross-entity helpers."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_FLOOR

from common import (db, base_fields, touch, now, iso, parse_dt, D, cents_half_up,
                    gregorian_years, MIN_HOLDING_YEARS, APPOINTMENT_SLOT_SECONDS,
                    ESTATE_CLAIM_WINDOW_DAYS, APPEAL_WINDOW_DAYS, ApiError, err)

RETAIN_RATES = {'CORN': 8, 'SOYBEAN': 10, 'WHEAT': 6, 'SORGHUM': 7, 'SUNFLOWER': 9}
COMMODITIES = list(RETAIN_RATES.keys())
MEMBER_CLASSES = ['INDIVIDUAL', 'PARTNERSHIP', 'CORPORATION', 'LLC', 'ESTATE']
EQUITY_CLASSES = ['QUALIFIED', 'NONQUALIFIED']
REQUEST_KINDS = ['ESTATE', 'RETIREMENT', 'SPECIAL_HARDSHIP', 'CYCLE_REDEMPTION']
RESOLUTION_KINDS = ['OPEN_REVOLVEMENT', 'APPROVE_ESTATE', 'APPROVE_RETIREMENT',
                    'APPROVE_SPECIAL_REDEMPTION', 'AMEND_ALLOCATION', 'AUTHORIZE_ESCHEAT']
KIND_TO_RESOLUTION = {
    'ESTATE': 'APPROVE_ESTATE',
    'RETIREMENT': 'APPROVE_RETIREMENT',
    'SPECIAL_HARDSHIP': 'APPROVE_SPECIAL_REDEMPTION',
    'CYCLE_REDEMPTION': 'OPEN_REVOLVEMENT',
}
QUALIFIED_FRACTION = Decimal('0.70')
TIER_T2_MIN_BU = 1000
TIER_T3_MIN_BU = 10000
EQUITY_COUNTED_STATUSES = ('ISSUED', 'ACTIVE', 'PARTIALLY_REDEEMED', 'FROZEN')
OPEN_REQUEST_STATUSES = ('PENDING', 'UNDER_REVIEW', 'APPROVED')


# ---------------------------------------------------------------- deliveries
def delivery_net_bushels(gross_bushels, dockage_pct):
    return int((D(gross_bushels) * (1 - D(dockage_pct))).to_integral_value(rounding=ROUND_FLOOR))


def delivery_retain_cents(net_bushels, commodity):
    return cents_half_up(D(net_bushels) * RETAIN_RATES[commodity])


# ---------------------------------------------------------------- members / equity
def recompute_member_equity(member_id):
    m = db.members.get(member_id)
    if not m:
        return
    q = sum(c['outstanding_cents'] for c in db.certificates.values()
            if c['member_id'] == member_id and c['equity_class'] == 'QUALIFIED'
            and c['status'] in EQUITY_COUNTED_STATUSES)
    nq = sum(c['outstanding_cents'] for c in db.certificates.values()
             if c['member_id'] == member_id and c['equity_class'] == 'NONQUALIFIED'
             and c['status'] in EQUITY_COUNTED_STATUSES)
    if m['qualified_equity_cents'] != q or m['nonqualified_equity_cents'] != nq:
        m['qualified_equity_cents'] = q
        m['nonqualified_equity_cents'] = nq
        touch(m)


def is_executor_of(uid, member_id):
    return any(c['executor_member_id'] == uid and c['deceased_member_id'] == member_id
               for c in db.estate_claims.values())


def delegate_is_seated(delegate):
    m = db.members.get(delegate['member_id'])
    try:
        start = parse_dt(delegate['term_start'])
        end = parse_dt(delegate['term_end'])
    except (ValueError, TypeError):
        return False
    return start <= now() < end and m is not None and m['status'] == 'ACTIVE'


def seated_delegate_ids():
    return [d['id'] for d in db.delegates.values() if delegate_is_seated(d)]


# ---------------------------------------------------------------- resolutions
def check_resolution_ref(resolution_id, kind, subject_id):
    """Validate a body-supplied resolution reference. Returns the resolution."""
    res = db.resolutions.get(resolution_id)
    if res is None:
        err('ERR_REFERENTIAL', 'Referenced resolution does not exist')
    if res['kind'] != kind or res['subject_ref_id'] != subject_id:
        err('ERR_REFERENTIAL', 'Resolution kind or subject does not match')
    if res['status'] != 'PASSED':
        err('ERR_INVALID_STATE', 'Resolution has not PASSED')
    return res


def has_passed_resolution(kind, subject_id):
    return any(r['kind'] == kind and r['subject_ref_id'] == subject_id and r['status'] == 'PASSED'
               for r in db.resolutions.values())


def subject_exists(subject_id):
    for store in (db.members, db.districts, db.delegates, db.fiscal_years, db.deliveries,
                  db.allocations, db.certificates, db.cycles, db.resolutions,
                  db.redemption_requests, db.estate_claims, db.lots, db.tax_forms):
        if subject_id in store:
            return True
    return False


# ---------------------------------------------------------------- certificates
def issue_certificate(member_id, fy_id, allocation_id, equity_class, face_value, replaces=None):
    cert = base_fields()
    cert.update({
        'member_id': member_id,
        'fiscal_year_id': fy_id,
        'allocation_id': allocation_id,
        'equity_class': equity_class,
        'face_value_cents': face_value,
        'outstanding_cents': face_value,
        'status': 'ISSUED',
        'issued_at': iso(now()),
        'redeemable_at': None,
        'revolvement_cycle_id': None,
        'replaces_certificate_id': replaces,
    })
    db.certificates[cert['id']] = cert
    return cert


def revoke_certificate(cert):
    cert['status'] = 'REVOKED'
    cert['outstanding_cents'] = 0
    touch(cert)


def freeze_member_certificates(member_id, statuses):
    for c in db.certificates.values():
        if c['member_id'] == member_id and c['status'] in statuses:
            c['status'] = 'FROZEN'
            touch(c)


def unfreeze_member_certificates(member_id):
    for c in db.certificates.values():
        if c['member_id'] == member_id and c['status'] == 'FROZEN':
            c['status'] = 'ACTIVE'
            touch(c)


# ---------------------------------------------------------------- patronage waterfall
def tier_for(volume_bu):
    if volume_bu >= TIER_T3_MIN_BU:
        return 'T3', Decimal('1.10')
    if volume_bu >= TIER_T2_MIN_BU:
        return 'T2', Decimal('1.05')
    return 'T1', Decimal('1.00')


def compute_allocations(fy):
    """Returns (pool_cents, [row dicts]). Used for both PROVISIONAL and FINAL passes."""
    pool = cents_half_up(D(fy['net_margin_cents']) * (1 - D(fy['retained_reserve_pct'])))
    vols = {}
    for d in db.deliveries.values():
        if (d['fiscal_year_id'] == fy['id'] and d['status'] == 'SETTLED'
                and d['is_patron_sourced']):
            vols[d['member_id']] = vols.get(d['member_id'], 0) + d['net_bushels']
    total = sum(vols.values())
    rows = []
    for member_id, v in vols.items():
        if v <= 0 or total <= 0:
            continue
        share = (D(v) / D(total)).quantize(Decimal('0.00000001'), rounding=ROUND_HALF_EVEN)
        gross = cents_half_up(D(pool) * share)
        tier, mod = tier_for(v)
        qualified = cents_half_up(D(gross) * mod * QUALIFIED_FRACTION)
        nonqualified = gross - qualified
        cash = cents_half_up(D(qualified) * D(fy['qualified_payout_pct']))
        qual_equity = qualified - cash
        rows.append({
            'member_id': member_id,
            'allocated_volume_bu': v,
            'pool_share_ratio': share,
            'gross_alloc_cents': gross,
            'qualified_allocation_cents': qualified,
            'nonqualified_allocation_cents': nonqualified,
            'cash_paid_cents': cash,
            'qualified_equity_issued_cents': qual_equity,
            'tier_code': tier,
        })
    # Rounding-drift reconciliation: post drift to the largest-volume member,
    # ties broken by earliest joined_at.
    drift = pool - sum(r['gross_alloc_cents'] for r in rows)
    if rows and drift != 0:
        target = sorted(
            rows,
            key=lambda r: (-r['allocated_volume_bu'],
                           parse_dt(db.members[r['member_id']]['joined_at']),
                           db.members[r['member_id']]['_seq']))[0]
        target['nonqualified_allocation_cents'] += drift
    return pool, rows


def _spawn_allocation(fy, row, variant):
    alloc = base_fields()
    alloc.update({
        'fiscal_year_id': fy['id'],
        'member_id': row['member_id'],
        'allocated_volume_bu': row['allocated_volume_bu'],
        'pool_share_ratio': float(row['pool_share_ratio']),
        'qualified_allocation_cents': row['qualified_allocation_cents'],
        'nonqualified_allocation_cents': row['nonqualified_allocation_cents'],
        'cash_paid_cents': row['cash_paid_cents'],
        'qualified_equity_issued_cents': row['qualified_equity_issued_cents'],
        'tier_code': row['tier_code'],
        'status': 'PROVISIONAL',
        'variant': variant,
    })
    db.allocations[alloc['id']] = alloc
    issue_certificate(row['member_id'], fy['id'], alloc['id'],
                      'QUALIFIED', row['qualified_equity_issued_cents'])
    issue_certificate(row['member_id'], fy['id'], alloc['id'],
                      'NONQUALIFIED', row['nonqualified_allocation_cents'])
    recompute_member_equity(row['member_id'])
    return alloc


def run_provisional_close(fy):
    pool, rows = compute_allocations(fy)
    fy['patronage_pool_cents'] = pool
    for row in rows:
        _spawn_allocation(fy, row, 'PROVISIONAL')
    fy['status'] = 'CLOSED_PROVISIONAL'
    fy['closed_at'] = iso(now())
    touch(fy)


_ALLOC_COMPARE_FIELDS = ('allocated_volume_bu', 'qualified_allocation_cents',
                         'nonqualified_allocation_cents', 'cash_paid_cents',
                         'qualified_equity_issued_cents', 'tier_code')


def run_finalize_close(fy):
    pool, rows = compute_allocations(fy)
    fy['patronage_pool_cents'] = pool
    was_reopened = (fy['status'] == 'REOPENED')
    new_by_member = {r['member_id']: r for r in rows}
    existing = [a for a in db.allocations.values()
                if a['fiscal_year_id'] == fy['id'] and a['status'] == 'PROVISIONAL']
    for alloc in existing:
        row = new_by_member.get(alloc['member_id'])
        diverges = row is not None and any(alloc[f] != (float(row[f]) if f == 'pool_share_ratio' else row[f])
                                           for f in _ALLOC_COMPARE_FIELDS)
        if row is not None and diverges:
            # AMENDED path: revoke original certificates, reissue replacements.
            old_certs = [c for c in db.certificates.values()
                         if c['allocation_id'] == alloc['id'] and c['status'] in ('ISSUED', 'ACTIVE')]
            for f in _ALLOC_COMPARE_FIELDS:
                alloc[f] = row[f]
            alloc['pool_share_ratio'] = float(row['pool_share_ratio'])
            alloc['status'] = 'AMENDED'
            alloc['variant'] = 'FINAL'
            touch(alloc)
            for old in old_certs:
                revoke_certificate(old)
                issue_certificate(old['member_id'], fy['id'], alloc['id'],
                                  old['equity_class'],
                                  row['qualified_equity_issued_cents'] if old['equity_class'] == 'QUALIFIED'
                                  else row['nonqualified_allocation_cents'],
                                  replaces=old['id'])
            recompute_member_equity(alloc['member_id'])
        else:
            alloc['status'] = 'FINALIZED'
            touch(alloc)
    # Certificates ISSUED -> ACTIVE; fix redeemable_at.
    for cert in db.certificates.values():
        if cert['fiscal_year_id'] == fy['id'] and cert['status'] == 'ISSUED':
            cert['status'] = 'ACTIVE'
            cert['redeemable_at'] = iso(parse_dt(cert['issued_at']) + gregorian_years(MIN_HOLDING_YEARS))
            touch(cert)
            recompute_member_equity(cert['member_id'])
    # Issue patron tax forms for patrons with allocation > 0.
    for alloc in db.allocations.values():
        if alloc['fiscal_year_id'] != fy['id'] or alloc['status'] not in ('FINALIZED', 'AMENDED'):
            continue
        if (alloc['cash_paid_cents'] + alloc['qualified_equity_issued_cents']
                + alloc['nonqualified_allocation_cents']) <= 0:
            continue
        issue_tax_form(fy, alloc['member_id'], corrected=was_reopened)
    fy['status'] = 'CLOSED_FINAL'
    fy['final_audit_locked'] = True
    fy['closed_at'] = iso(now())
    touch(fy)


def run_reopen(fy):
    for a in db.allocations.values():
        if a['fiscal_year_id'] == fy['id'] and a['status'] == 'FINALIZED':
            a['status'] = 'PROVISIONAL'
            touch(a)
    for f in db.tax_forms.values():
        if f['fiscal_year_id'] == fy['id'] and f['status'] == 'ISSUED':
            f['status'] = 'VOID'
            touch(f)
    fy['final_audit_locked'] = False
    fy['status'] = 'REOPENED'
    touch(fy)


# ---------------------------------------------------------------- tax forms
def issue_tax_form(fy, member_id, corrected=False):
    box1 = sum(a['cash_paid_cents'] + a['qualified_equity_issued_cents']
               for a in db.allocations.values()
               if a['fiscal_year_id'] == fy['id'] and a['member_id'] == member_id
               and a['status'] in ('FINALIZED', 'AMENDED'))
    box3 = sum(d['per_unit_retain_cents'] for d in db.deliveries.values()
               if d['fiscal_year_id'] == fy['id'] and d['member_id'] == member_id
               and d['status'] == 'SETTLED')
    box5 = sum(x['amount_cents'] for x in db.disbursements
               if x['member_id'] == member_id and x['fiscal_year_id'] == fy['id']
               and x['equity_class'] == 'NONQUALIFIED')
    form = base_fields()
    corrects_form_id = None
    if corrected:
        voided = [f for f in db.tax_forms.values()
                  if f['fiscal_year_id'] == fy['id'] and f['member_id'] == member_id
                  and f['status'] == 'VOID']
        if voided:
            corrects_form_id = sorted(voided, key=lambda f: f['_seq'])[-1]['id']
    form.update({
        'member_id': member_id,
        'fiscal_year_id': fy['id'],
        'form_type': 'CORRECTED_1099_PATR' if corrected else 'FORM_1099_PATR',
        'box_1_patronage_dividends_cents': box1,
        'box_3_per_unit_retains_cents': box3,
        'box_4_federal_withheld_cents': 0,
        'box_5_redemption_cents': box5,
        'is_corrected': bool(corrected),
        'corrects_form_id': corrects_form_id,
        'issued_at': iso(now()),
        'status': 'ISSUED',
    })
    db.tax_forms[form['id']] = form
    return form


# ---------------------------------------------------------------- redemption
def appointment_conflicts(appointment_iso, exclude_id=None, statuses=('UNDER_REVIEW', 'APPROVED')):
    a_start = parse_dt(appointment_iso)
    a_end = a_start + timedelta(seconds=APPOINTMENT_SLOT_SECONDS)
    for r in db.redemption_requests.values():
        if r['id'] == exclude_id or r['status'] not in statuses:
            continue
        b_start = parse_dt(r['appointment_at'])
        b_end = b_start + timedelta(seconds=APPOINTMENT_SLOT_SECONDS)
        if a_start < b_end and b_start < a_end:
            return True
    return False


def find_cycle_for_request(req):
    certs = [db.certificates[cid] for cid in req['certificate_ids'] if cid in db.certificates]
    for c in certs:
        if c.get('revolvement_cycle_id') and c['revolvement_cycle_id'] in db.cycles:
            return db.cycles[c['revolvement_cycle_id']]
    if certs:
        cls = certs[0]['equity_class']
        for cyc in db.cycles.values():
            if cyc['equity_class'] == cls and cyc['status'] == 'OPEN':
                return cyc
    return None


def run_disburse(req):
    certs = [db.certificates[cid] for cid in req['certificate_ids']]
    total = sum(c['outstanding_cents'] for c in certs)
    amount = req['requested_amount_cents']
    if amount >= total:
        pays = {c['id']: c['outstanding_cents'] for c in certs}
    else:
        pays = {}
        for c in certs:
            pays[c['id']] = int((D(c['outstanding_cents']) * amount / D(total))
                                .to_integral_value(rounding=ROUND_FLOOR))
        remainder = amount - sum(pays.values())
        ordered = sorted(certs, key=lambda c: (c['issued_at'], c['created_at'], c['_seq']))
        for c in ordered:
            if remainder <= 0:
                break
            pays[c['id']] += 1
            remainder -= 1
    for c in certs:
        pay = pays.get(c['id'], 0)
        if pay <= 0:
            continue
        c['outstanding_cents'] -= pay
        c['status'] = 'REDEEMED' if c['outstanding_cents'] == 0 else 'PARTIALLY_REDEEMED'
        touch(c)
        db.disbursements.append({
            'certificate_id': c['id'],
            'member_id': c['member_id'],
            'fiscal_year_id': c['fiscal_year_id'],
            'equity_class': c['equity_class'],
            'amount_cents': pay,
            'at': iso(now()),
        })
    recompute_member_equity(req['member_id'])
    if req['kind'] == 'CYCLE_REDEMPTION':
        cyc = find_cycle_for_request(req)
        if cyc is not None:
            cyc['redeemed_cents'] += amount
            touch(cyc)
    req['status'] = 'PAID'
    touch(req)
    maybe_distribute_estate(req)


def maybe_distribute_estate(req):
    if req['kind'] != 'ESTATE':
        return
    claim = None
    for c in db.estate_claims.values():
        if c['deceased_member_id'] == req['member_id'] and c['status'] == 'APPROVED':
            claim = c
            break
    if claim is None:
        return
    open_estate = [r for r in db.redemption_requests.values()
                   if r['member_id'] == req['member_id'] and r['kind'] == 'ESTATE'
                   and r['status'] in OPEN_REQUEST_STATUSES]
    if not open_estate:
        claim['status'] = 'DISTRIBUTED'
        touch(claim)


def check_request_actor(req, uid):
    """Members act on their own requests; estate executors act for a DECEASED member."""
    if uid == req['member_id']:
        return
    m = db.members.get(req['member_id'])
    if m is not None and m['status'] == 'DECEASED' and is_executor_of(uid, req['member_id']):
        return
    err('ERR_FORBIDDEN', 'Members may only act on their own redemption requests')
