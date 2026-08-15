"""Shared business logic: serializers, computed-field recomputation, and
cross-entity cascades. Every mutation of a persisted entity goes through
touch() so version/updated_at stay consistent (PRD §2.5)."""
from datetime import timedelta

from db import db, touch
from errors import ApiError
from util import dec, fmt_dt, rhu, rhu1

# ---------------------------------------------------------------- constants
SEVERITY_WEIGHT = {'MINOR': 25, 'MAJOR': 60, 'TRIP_HAZARD': 100}
STREET_BONUS = {'ARTERIAL': 20, 'COLLECTOR': 10, 'LOCAL': 0}
HARDSHIP_BONUS = {'LOW_INCOME': 30, 'SENIOR_65': 20, 'NONE': 0}
BASE_CITY_SHARE = 50
SHARE_CAP = 90
ENGINEER_UNIT_RATE_CENTS = 1200
RAMP_FLAT_CENTS = 250000
PER_APPLICATION_CAP_CENTS = 400000
PER_PARCEL_LIFETIME_CAP_CENTS = 800000
ADMIN_FEE_MIN_CENTS = 15000
ADMIN_FEE_PCT = 10
HARDSHIP_EXTENSION_DAYS = 30
APPEAL_RESET_DAYS = 15
APPROVAL_EXPIRY_DAYS = 60
CURE_BUFFER_DAYS = 7
FORECLOSURE_MIN_DAYS = 90
PAYOFF_GOOD_THROUGH_DAYS = 15
DAYS_PER_YEAR_X10000 = 3650000

OPEN_DEFECT_STATUSES = {'OPEN', 'AWAITING_FORESTRY', 'UNDER_REPAIR'}
TERMINAL_NOTICE_STATUSES = {'COMPLIANT', 'VOID', 'CLOSED'}
DELINQUENT_FAMILY = {'DELINQUENT', 'CITY_REPAIR_SCHEDULED',
                     'CITY_REPAIR_COMPLETED', 'LIENED'}
IN_FLIGHT_APP_STATUSES = {'SUBMITTED', 'RETURNED', 'APPROVED', 'OBLIGATED'}
TERMINAL_LIEN_STATUSES = {'SATISFIED', 'FORECLOSURE_REFERRED'}
ACTIVE_WORK_ITEM_STATUSES = {'POOLED', 'SCHEDULED', 'WORK_COMPLETED', 'VERIFIED'}


# ---------------------------------------------------------------- serializers
def _common(e):
    return {'id': e['id'], 'created_at': e['created_at'],
            'updated_at': e['updated_at'], 'version': e['version']}


def ser_cycle(c):
    d = _common(c)
    d.update({
        'cycle_year': c['cycle_year'],
        'window_start_date': c['window_start_date'],
        'window_end_date': c['window_end_date'],
        'appropriation_cents': c['appropriation_cents'],
        'committed_cents': c['committed_cents'],
        'disbursed_cents': c['disbursed_cents'],
        'available_cents': c['available_cents'],
        'status': c['status'],
    })
    return d


def ser_owner(o):
    d = _common(o)
    d.update({'full_name': o['full_name'], 'mailing_address': o['mailing_address'],
              'hardship_tier': o['hardship_tier']})
    return d


def ser_parcel(p):
    d = _common(p)
    d.update({
        'parcel_number': p['parcel_number'], 'owner_id': p['owner_id'],
        'street_address': p['street_address'], 'street_class': p['street_class'],
        'is_corner_lot': p['is_corner_lot'], 'is_city_owned': p['is_city_owned'],
        'owner_responsibility_pct': p['owner_responsibility_pct'],
        'delinquency_flag': p['delinquency_flag'],
    })
    return d


def ser_segment(s):
    d = _common(s)
    d.update({
        'segment_code': s['segment_code'], 'parcel_id': s['parcel_id'],
        'length_ft': s['length_ft'], 'width_ft': s['width_ft'],
        'is_corner_segment': s['is_corner_segment'],
        'has_existing_curb_ramp': s['has_existing_curb_ramp'],
        'open_defect_count': s['open_defect_count'],
        'condition_screening': s['condition_screening'],
        'condition_area_weighted': s['condition_area_weighted'],
        'status': s['status'],
    })
    return d


def ser_defect(x):
    d = _common(x)
    d.update({
        'segment_id': x['segment_id'], 'defect_type': x['defect_type'],
        'measured_offset_inches': x['measured_offset_inches'],
        'area_sqft': x['area_sqft'], 'city_tree_involved': x['city_tree_involved'],
        'severity_class': x['severity_class'],
        'recorded_by_inspector_id': x['recorded_by_inspector_id'],
        'status': x['status'],
    })
    return d


def ser_notice(n):
    d = _common(n)
    d.update({
        'parcel_id': n['parcel_id'], 'defect_ids': list(n['defect_ids']),
        'base_deadline_days': n['base_deadline_days'],
        'issued_at': fmt_dt(n['issued_at']),
        'compliance_deadline': fmt_dt(n['compliance_deadline']),
        'prior_notice_id': n['prior_notice_id'],
        'issued_by_user_id': n['issued_by_user_id'],
        'appeal_status': n['appeal_status'],
        'appeal_grounds': n['appeal_grounds'],
        'appeal_decided_by_user_id': n['appeal_decided_by_user_id'],
        'appeal_decided_at': fmt_dt(n['appeal_decided_at']),
        'status': n['status'],
    })
    return d


def ser_application(a):
    d = _common(a)
    d.update({
        'notice_id': a['notice_id'], 'parcel_id': a['parcel_id'],
        'owner_id': a['owner_id'], 'cycle_id': a['cycle_id'],
        'estimated_qty_sqft': a['estimated_qty_sqft'],
        'ramp_upgrade_required': a['ramp_upgrade_required'],
        'share_pct': a['share_pct'],
        'provisional_award_cents': a['provisional_award_cents'],
        'final_award_cents': a['final_award_cents'],
        'approved_at': fmt_dt(a['approved_at']),
        'approval_expires_at': fmt_dt(a['approval_expires_at']),
        'review_status': a['review_status'],
        'payment_status': a['payment_status'],
    })
    return d


def ser_batch(b):
    d = _common(b)
    d.update({
        'neighborhood_code': b['neighborhood_code'],
        'work_window_start': b['work_window_start'],
        'work_window_end': b['work_window_end'],
        'bid_deadline': fmt_dt(b['bid_deadline']),
        'estimated_total_cents': b['estimated_total_cents'],
        'awarded_bid_id': b['awarded_bid_id'],
        'awarded_total_cents': b['awarded_total_cents'],
        'status': b['status'],
    })
    return d


def ser_work_item(w):
    d = _common(w)
    d.update({
        'batch_id': w['batch_id'], 'notice_id': w['notice_id'],
        'scope_sqft': w['scope_sqft'],
        'engineer_unit_rate_cents': w['engineer_unit_rate_cents'],
        'includes_ramp_upgrade': w['includes_ramp_upgrade'],
        'status': w['status'],
    })
    return d


def ser_contractor(c):
    d = _common(c)
    d.update({'company_name': c['company_name'],
              'license_number': c['license_number'],
              'insurance_valid_until': c['insurance_valid_until'],
              'is_suspended': c['is_suspended']})
    return d


def ser_bid(b):
    d = _common(b)
    d.update({
        'batch_id': b['batch_id'], 'contractor_id': b['contractor_id'],
        'unit_rate_cents': b['unit_rate_cents'],
        'ramp_flat_fee_cents': b['ramp_flat_fee_cents'],
        'submitted_at': fmt_dt(b['submitted_at']),
        'evaluated_total_cents': b['evaluated_total_cents'],
        'status': b['status'],
    })
    return d


def ser_forestry(r):
    d = _common(r)
    d.update({'defect_id': r['defect_id'], 'decision': r['decision'],
              'decided_by_user_id': r['decided_by_user_id'],
              'work_completed_at': fmt_dt(r['work_completed_at']),
              'status': r['status']})
    return d


def ser_lien(l, accrued=None, outstanding=None):
    d = _common(l)
    d.update({
        'notice_id': l['notice_id'], 'parcel_id': l['parcel_id'],
        'actual_repair_cost_cents': l['actual_repair_cost_cents'],
        'admin_fee_cents': l['admin_fee_cents'],
        'city_credit_cents': l['city_credit_cents'],
        'owner_principal_cents': l['owner_principal_cents'],
        'interest_rate_bp': l['interest_rate_bp'],
        'assessed_at': fmt_dt(l['assessed_at']),
        'principal_remaining_cents': l['principal_remaining_cents'],
        'accrued_interest_cents': l['accrued_interest_cents'] if accrued is None else accrued,
        'last_accrual_day': l['last_accrual_day'],
        'outstanding_balance_cents': l['outstanding_balance_cents'] if outstanding is None else outstanding,
        'status': l['status'],
    })
    return d


def ser_inspection(r):
    return {'id': r['id'], 'created_at': r['created_at'],
            'notice_id': r['notice_id'], 'inspector_id': r['inspector_id'],
            'result': r['result'], 'notes': r['notes']}


# ---------------------------------------------------------------- lookups
def parcel_owner_id_of_notice(notice):
    parcel = db.parcels.get(notice['parcel_id'])
    return parcel['owner_id'] if parcel else None


def owner_id_of_parcel(parcel_id):
    parcel = db.parcels.get(parcel_id)
    return parcel['owner_id'] if parcel else None


def owner_id_of_segment(segment):
    return owner_id_of_parcel(segment['parcel_id'])


def owner_id_of_defect(defect):
    seg = db.segments.get(defect['segment_id'])
    return owner_id_of_segment(seg) if seg else None


# ---------------------------------------------------------------- recomputes
def recompute_segment(segment):
    """open_defect_count + both condition index variants over non-verified defects."""
    members = [d for d in db.defects.values()
               if d['segment_id'] == segment['id'] and d['status'] in OPEN_DEFECT_STATUSES]
    segment['open_defect_count'] = len(members)
    if not members:
        segment['condition_screening'] = 0
        segment['condition_area_weighted'] = 0.0
    else:
        segment['condition_screening'] = max(SEVERITY_WEIGHT[d['severity_class']] for d in members)
        num = sum(SEVERITY_WEIGHT[d['severity_class']] * dec(d['area_sqft']) for d in members)
        den = sum(dec(d['area_sqft']) for d in members)
        segment['condition_area_weighted'] = rhu1(num / den)


def maybe_restore_segment(segment):
    """open_defect_count == 0 -> RESTORED from FLAGGED/UNDER_NOTICE/REPAIR_IN_PROGRESS."""
    if segment['open_defect_count'] == 0 and segment['status'] in (
            'FLAGGED', 'UNDER_NOTICE', 'REPAIR_IN_PROGRESS'):
        segment['status'] = 'RESTORED'
        touch(segment)


def recompute_delinquency_flag(parcel):
    flag = any(n['parcel_id'] == parcel['id'] and n['status'] in DELINQUENT_FAMILY
               for n in db.notices.values())
    if parcel['delinquency_flag'] != flag:
        parcel['delinquency_flag'] = flag
        touch(parcel)


def recompute_cycle_available(cycle):
    cycle['available_cents'] = (cycle['appropriation_cents'] - cycle['committed_cents']
                                - cycle['disbursed_cents'])


def recompute_batch_estimate(batch):
    """Sum over pooled-family items of round_half_up(scope_sqft * unit_rate)."""
    total = 0
    for w in db.work_items.values():
        if w['batch_id'] == batch['id'] and w['status'] in (
                'POOLED', 'SCHEDULED', 'WORK_COMPLETED'):
            total += rhu(dec(w['scope_sqft']) * dec(w['engineer_unit_rate_cents']))
    batch['estimated_total_cents'] = total


# ---------------------------------------------------------------- calculations
def classify_defect(defect_type, offset, area):
    """defect_severity_classification: inclusive lower-bound thresholds."""
    if defect_type in ('VERTICAL_SEPARATION', 'TREE_ROOT_UPHEAVAL'):
        o = dec(offset)
        if o >= dec('0.5'):
            return 'TRIP_HAZARD'
        if o >= dec('0.25'):
            return 'MAJOR'
        return 'MINOR'
    if defect_type == 'HORIZONTAL_OPENING':
        return 'MAJOR' if dec(offset) >= dec('0.5') else 'MINOR'
    if defect_type == 'SETTLEMENT':
        return 'MAJOR' if dec(area) >= dec(9) else 'MINOR'
    # SPALLING or CRUMBLED_JOINT
    return 'MAJOR' if dec(area) >= dec(16) else 'MINOR'


def compute_share_pct(parcel, owner):
    pct = (BASE_CITY_SHARE + STREET_BONUS[parcel['street_class']]
           + HARDSHIP_BONUS[owner['hardship_tier']])
    return min(SHARE_CAP, pct)


def ramp_trigger_for_notice(notice):
    """True iff any covered defect sits on a corner segment without a curb ramp."""
    for did in notice['defect_ids']:
        defect = db.defects.get(did)
        if not defect:
            continue
        seg = db.segments.get(defect['segment_id'])
        if seg and seg['is_corner_segment'] and not seg['has_existing_curb_ramp']:
            return True
    return False


def parcel_lifetime_remaining(parcel_id):
    """800000 - (provisionals of APPROVED/OBLIGATED + finals of REIMBURSED)."""
    absorbed = 0
    for a in db.applications.values():
        if a['parcel_id'] != parcel_id:
            continue
        if a['review_status'] in ('APPROVED', 'OBLIGATED'):
            absorbed += a['provisional_award_cents']
        elif a['review_status'] == 'REIMBURSED':
            absorbed += a['final_award_cents'] or 0
    return PER_PARCEL_LIFETIME_CAP_CENTS - absorbed


def compute_provisional_award(estimated_qty_sqft, share_pct, ramp_required, parcel_id):
    """Engineer-estimate variant, per-component round-half-up in pinned order."""
    repair_estimate = rhu(dec(estimated_qty_sqft) * dec(ENGINEER_UNIT_RATE_CENTS))
    ramp_allowance = RAMP_FLAT_CENTS if ramp_required else 0
    city_repair_share = rhu(dec(repair_estimate) * dec(share_pct) / dec(100))
    uncapped = city_repair_share + ramp_allowance
    lifetime_remaining = parcel_lifetime_remaining(parcel_id)
    if lifetime_remaining <= 0:
        raise ApiError('ERR_PARCEL_LIFETIME_CAP_REACHED', 422,
                       'Parcel lifetime cost-share cap is exhausted')
    return min(PER_APPLICATION_CAP_CENTS, uncapped, lifetime_remaining)


def compute_final_award(final_repair_cost_cents, ramp_receipt_cents, app):
    """Actual-invoice variant at reimbursement time."""
    repair_part = rhu(dec(final_repair_cost_cents) * dec(app['share_pct']) / dec(100))
    if app['ramp_upgrade_required']:
        ramp_part = min(ramp_receipt_cents or 0, RAMP_FLAT_CENTS)
    else:
        ramp_part = 0
    uncapped = repair_part + ramp_part
    lifetime_remaining = parcel_lifetime_remaining(app['parcel_id'])
    return min(PER_APPLICATION_CAP_CENTS, uncapped, lifetime_remaining)


def compute_lien_principal(notice, actual_repair_cost_cents):
    """admin fee, city-tree credit, owner principal — multiply/divide/round pinned."""
    admin_fee = max(ADMIN_FEE_MIN_CENTS,
                    rhu(dec(actual_repair_cost_cents) * dec(ADMIN_FEE_PCT) / dec(100)))
    city_caused = dec(0)
    total_scope = dec(0)
    for did in notice['defect_ids']:
        defect = db.defects.get(did)
        if not defect:
            continue
        total_scope += dec(defect['area_sqft'])
        if (defect['defect_type'] == 'TREE_ROOT_UPHEAVAL'
                and defect['city_tree_involved']):
            review = next((r for r in db.forestry_reviews.values()
                           if r['defect_id'] == defect['id']), None)
            if review and review['decision'] in ('PRUNE_APPROVED', 'REMOVAL_ORDERED'):
                city_caused += dec(defect['area_sqft'])
    if total_scope == 0:
        raise ApiError('ERR_ZERO_SCOPE_AREA', 422,
                       'Notice defect areas sum to zero')
    city_credit = rhu(dec(actual_repair_cost_cents) * city_caused / total_scope)
    owner_principal = actual_repair_cost_cents - city_credit + admin_fee
    return admin_fee, city_credit, owner_principal


def lien_day(lien, at_dt):
    """Whole days between the assessed date (day 0) and the given instant's date."""
    return max((at_dt.date() - lien['assessed_at'].date()).days, 0)


def project_interest(lien, day):
    """Interest from last_accrual_day through `day` on current principal."""
    days = day - lien['last_accrual_day']
    if days <= 0 or lien['principal_remaining_cents'] <= 0:
        return 0
    return rhu(dec(lien['principal_remaining_cents']) * dec(lien['interest_rate_bp'])
               * dec(days) / dec(DAYS_PER_YEAR_X10000))


# ---------------------------------------------------------------- cascades
def cancel_applications_for_notice(notice):
    """Delinquency cascade onto applications (and the cycle for OBLIGATED)."""
    for a in sorted(db.applications.values(), key=lambda x: x['_seq']):
        if a['notice_id'] != notice['id'] or a['review_status'] not in IN_FLIGHT_APP_STATUSES:
            continue
        was_obligated = a['review_status'] == 'OBLIGATED'
        a['review_status'] = 'CANCELLED'
        touch(a)
        if was_obligated:
            a['payment_status'] = 'RELEASED'
            cycle = db.cycles.get(a['cycle_id'])
            if cycle:
                cycle['committed_cents'] -= a['provisional_award_cents']
                recompute_cycle_available(cycle)
                touch(cycle)


def transition_notice_to_delinquent(notice):
    """ISSUED -> DELINQUENT with the depth-3 cascade."""
    notice['status'] = 'DELINQUENT'
    touch(notice)
    cancel_applications_for_notice(notice)
    parcel = db.parcels.get(notice['parcel_id'])
    if parcel:
        recompute_delinquency_flag(parcel)


def release_notice_defects(notice):
    """Appeal REVERSED: defects UNDER_REPAIR -> OPEN; lonely segments -> FLAGGED."""
    affected_segments = set()
    for did in notice['defect_ids']:
        defect = db.defects.get(did)
        if defect and defect['status'] == 'UNDER_REPAIR':
            defect['status'] = 'OPEN'
            touch(defect)
            recompute_segment(db.segments[defect['segment_id']])
            affected_segments.add(defect['segment_id'])
    for sid in affected_segments:
        seg = db.segments[sid]
        if seg['status'] == 'UNDER_NOTICE':
            has_under_repair = any(
                d['segment_id'] == sid and d['status'] == 'UNDER_REPAIR'
                for d in db.defects.values())
            if not has_under_repair:
                seg['status'] = 'FLAGGED'
                touch(seg)


def verify_notice_defects(notice):
    """Every covered defect UNDER_REPAIR -> VERIFIED; restore drained segments."""
    affected_segments = set()
    for did in notice['defect_ids']:
        defect = db.defects.get(did)
        if defect and defect['status'] == 'UNDER_REPAIR':
            defect['status'] = 'VERIFIED'
            touch(defect)
            affected_segments.add(defect['segment_id'])
    for sid in affected_segments:
        seg = db.segments[sid]
        recompute_segment(seg)
        maybe_restore_segment(seg)
