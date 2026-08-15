"""The 8 calculation rules from PRD Section 3 / scaffold Table 3.

All money in integer cents; Decimal + ROUND_HALF_UP everywhere; rounding order
pinned exactly as the PRD states.
"""
from decimal import Decimal, ROUND_HALF_UP

from db import STORE, CLOCK
from util import parse_dt, parse_hhmm
from services import domain

# Constants
MEMBER_DISCOUNT_PCT = Decimal('0.10')
MULTI_VEHICLE_DISCOUNT_PCT = Decimal('0.25')
REFUND_FULL_HOURS = Decimal('168')
REFUND_HALF_HOURS = Decimal('48')
POSTPONE_CREDIT_PCT = Decimal('0.25')
DAY_LIMIT_DB = Decimal('95.0')
CURFEW_LIMIT_DB = Decimal('85.0')
EXCEEDANCE_SUSPENSION_THRESHOLD = 3
MEMBER_BALLOT_WEIGHT = 2

TIER_FEE = {
    'SINGLE': 7500,
    'DOUBLE': 14000,
    'SPONSOR': 25000,
}
POWER_FEE_CENTS = 1500

CRITERION_WEIGHTS = {
    'EXTERIOR': Decimal('1.0'),
    'INTERIOR': Decimal('0.75'),
    'ENGINE': Decimal('1.5'),
    'AUTHENTICITY': Decimal('2.0'),
    'CONDITION': Decimal('1.25'),
}
CRITERIA = ('EXTERIOR', 'INTERIOR', 'ENGINE', 'AUTHENTICITY', 'CONDITION')


def _q(value, decimals):
    return value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# 1. entry_fee_calc (PRD 3.2)
# ---------------------------------------------------------------------------

def compute_entry_fee(event, cls, registrant):
    """Return (pricing_tier, fee_cents). Frozen at registration creation."""
    now = parse_dt(CLOCK.now())
    deadline = parse_dt(event['prereg_deadline'])
    tier = 'PREREG' if now < deadline else 'DAY_OF'
    if tier == 'DAY_OF':
        return tier, int(cls['day_of_fee_cents'])
    prior = [
        r for r in STORE.registrations.values()
        if r['registrant_id'] == registrant['id']
        and r['event_id'] == event['id']
        and r['status'] in domain.NON_TERMINAL_REG_STATUSES
    ]
    multi = len(prior) >= 1
    fee = Decimal(cls['prereg_fee_cents'])
    if registrant.get('club_member'):
        fee = fee * (Decimal(1) - MEMBER_DISCOUNT_PCT)
    if multi:
        fee = fee * (Decimal(1) - MULTI_VEHICLE_DISCOUNT_PCT)
    return tier, int(_q(fee, 0))


# ---------------------------------------------------------------------------
# 2. judged_score_tabulation (PRD 3.6)
# ---------------------------------------------------------------------------

def compute_sheet_total(criteria_scores):
    """sheet_total := round_half_up(sum(points * weight), 1 decimal)."""
    total = Decimal(0)
    for item in criteria_scores:
        total += Decimal(int(item['points'])) * CRITERION_WEIGHTS[item['criterion']]
    return float(_q(total, 1))


def compute_class_score(event, registration):
    """Average of LOCKED sheet_totals; DROP_EXTREMES with >= 3 sheets drops one
    highest and one lowest sheet_total before averaging. 2 decimals, round-half-up.
    Returns None when the registration has no LOCKED sheets."""
    locked = [s for s in domain.sheets_of_registration(registration['id'])
              if s['status'] == 'LOCKED']
    if not locked:
        return None
    totals = [Decimal(str(s['sheet_total'])) for s in locked]
    if event['tabulation_method'] == 'DROP_EXTREMES' and len(totals) >= 3:
        totals.remove(max(totals))
        totals.remove(min(totals))
    avg = sum(totals) / Decimal(len(totals))
    return float(_q(avg, 2))


def compute_condition_avg(registration):
    """Average of CONDITION points across LOCKED sheets, 2 decimals round-half-up."""
    locked = [s for s in domain.sheets_of_registration(registration['id'])
              if s['status'] == 'LOCKED']
    if not locked:
        return None
    pts = []
    for s in locked:
        for item in s['criteria_scores']:
            if item['criterion'] == 'CONDITION':
                pts.append(Decimal(int(item['points'])))
    if not pts:
        return None
    return float(_q(sum(pts) / Decimal(len(pts)), 2))


# ---------------------------------------------------------------------------
# 3. class_ranking_tiebreak (PRD 3.6)
# ---------------------------------------------------------------------------

def rank_judged_class(event, cls):
    """Rank CHECKED_IN registrations with >= 1 LOCKED sheet by the 5-level chain.
    Returns list of (registration, class_score) best-first."""
    candidates = []
    for reg in domain.registrations_of_event(event['id']):
        if reg['class_id'] != cls['id'] or reg['status'] != 'CHECKED_IN':
            continue
        score = compute_class_score(event, reg)
        if score is None:
            continue
        candidates.append((reg, score))

    def key(item):
        reg, score = item
        cond = compute_condition_avg(reg)
        sheet_count = sum(1 for s in domain.sheets_of_registration(reg['id'])
                          if s['status'] == 'LOCKED')
        vehicle = STORE.vehicles.get(reg['vehicle_id'])
        year = vehicle['year'] if vehicle else 0
        checked_in_at = reg.get('checked_in_at') or ''
        return (
            -Decimal(str(score)),
            -Decimal(str(cond if cond is not None else 0)),
            -sheet_count,
            checked_in_at,  # ASC: earlier wins
            -year,          # DESC: newer wins
        )

    candidates.sort(key=key)
    return candidates


def tie_break_log_for(sorted_candidates, index):
    """Which level of the chain decided this place (vs the next-ranked entry)."""
    if index + 1 < len(sorted_candidates):
        a_reg, a_score = sorted_candidates[index]
        b_reg, b_score = sorted_candidates[index + 1]
        if Decimal(str(a_score)) != Decimal(str(b_score)):
            return 'CLASS_SCORE'
        a_cond = compute_condition_avg(a_reg) or 0
        b_cond = compute_condition_avg(b_reg) or 0
        if Decimal(str(a_cond)) != Decimal(str(b_cond)):
            return 'CONDITION_AVG'
        a_cnt = sum(1 for s in domain.sheets_of_registration(a_reg['id'])
                    if s['status'] == 'LOCKED')
        b_cnt = sum(1 for s in domain.sheets_of_registration(b_reg['id'])
                    if s['status'] == 'LOCKED')
        if a_cnt != b_cnt:
            return 'SHEET_COUNT'
        if (a_reg.get('checked_in_at') or '') != (b_reg.get('checked_in_at') or ''):
            return 'CHECKED_IN_AT'
        return 'VEHICLE_YEAR'
    return 'CLASS_SCORE'


# ---------------------------------------------------------------------------
# 4. peoples_choice_tally (PRD 3.6)
# ---------------------------------------------------------------------------

def tally_peoples_choice(event, cls):
    """Per-registration tally of VALID ballot weights (voted reg must be
    CHECKED_IN at finalize). Returns (sorted [(reg, tally, member_ballots)], total_valid)."""
    per_reg = {}
    total_valid = 0
    for ballot in STORE.ballots.values():
        if ballot['event_id'] != event['id'] or ballot['status'] != 'VALID':
            continue
        reg = STORE.registrations.get(ballot['registration_id'])
        if reg is None or reg['class_id'] != cls['id']:
            continue
        if reg['status'] != 'CHECKED_IN':
            continue
        total_valid += 1
        tally, members = per_reg.get(reg['id'], (0, 0))
        tally += ballot['weight']
        if ballot['weight'] == MEMBER_BALLOT_WEIGHT:
            members += 1
        per_reg[reg['id']] = (tally, members)

    ranked = []
    for reg_id, (tally, members) in per_reg.items():
        ranked.append((STORE.registrations[reg_id], tally, members))

    def key(item):
        reg, tally, members = item
        vehicle = STORE.vehicles.get(reg['vehicle_id'])
        year = vehicle['year'] if vehicle else 0
        return (
            -tally,
            -members,
            reg.get('checked_in_at') or '',
            -year,
        )

    ranked.sort(key=key)
    return ranked, total_valid


def pc_tie_break_log(ranked, index):
    if index + 1 < len(ranked):
        a_reg, a_tally, a_members = ranked[index]
        b_reg, b_tally, b_members = ranked[index + 1]
        if a_tally != b_tally:
            return 'TALLY'
        if a_members != b_members:
            return 'MEMBER_BALLOTS'
        if (a_reg.get('checked_in_at') or '') != (b_reg.get('checked_in_at') or ''):
            return 'CHECKED_IN_AT'
        return 'VEHICLE_YEAR'
    return 'TALLY'


# ---------------------------------------------------------------------------
# 5. withdrawal_refund_calc (PRD 3.4)
# ---------------------------------------------------------------------------

def withdrawal_refund_pct(event, withdrawn_at_iso):
    hours_before = Decimal(str(
        (parse_dt(event['gates_open_at']) - parse_dt(withdrawn_at_iso)).total_seconds()
    )) / Decimal('3600')
    if hours_before >= REFUND_FULL_HOURS:
        return Decimal('1.00')
    if hours_before >= REFUND_HALF_HOURS:
        return Decimal('0.50')
    return Decimal('0.00')


def withdrawal_refund_amount(registration, pct):
    net = Decimal(registration['paid_cents'] - registration['refunded_cents'])
    return int(_q(net * pct, 0))


# ---------------------------------------------------------------------------
# 6. weather_refund_calc (PRD 3.7)
# ---------------------------------------------------------------------------

def postponement_refunds(event, actor_user_id):
    """POSTPONED: 25% goodwill credit of gross paid_cents for CONFIRMED/CHECKED_IN."""
    targets = [r for r in domain.registrations_of_event(event['id'])
               if r['status'] in ('CONFIRMED', 'CHECKED_IN')]
    for reg in domain.sorted_created(targets):
        amount = int(_q(Decimal(reg['paid_cents']) * POSTPONE_CREDIT_PCT, 0))
        if amount > 0:
            domain.create_payment(reg['id'], None, 'REFUND', amount, 'CASH',
                                  actor_user_id)
            domain.touch_entity(reg)


def cancellation_refunds(event, actor_user_id):
    """CANCELLED cascade L1-L4 with pinned two-pass pro-rata cap."""
    targets = [r for r in domain.registrations_of_event(event['id'])
               if r['status'] in ('CONFIRMED', 'CHECKED_IN')]
    targets = domain.sorted_created(targets)

    # L1: CONFIRMED/CHECKED_IN -> REFUND_REQUESTED
    for reg in targets:
        reg['status'] = 'REFUND_REQUESTED'
        reg['withdrawn_at'] = reg.get('withdrawn_at') or CLOCK.now()
        domain.touch_entity(reg)

    # L2: two-pass policy refunds against treasury snapshot T0
    t0 = domain.compute_treasury(event['id'])
    policy = {reg['id']: reg['paid_cents'] for reg in targets}
    total_policy = sum(policy.values())
    if total_policy > t0 and total_policy > 0:
        amounts = {}
        for reg in targets:
            amounts[reg['id']] = (policy[reg['id']] * t0) // total_policy
        remainder = t0 - sum(amounts.values())
        i = 0
        while remainder > 0 and targets:
            amounts[targets[i % len(targets)]['id']] += 1
            remainder -= 1
            i += 1
    else:
        amounts = policy

    # L3 + L4: post refunds, flip to REFUNDED, cascade ballots/awards/spot
    for reg in targets:
        was_checked_in = reg.get('assigned_zone_id') is not None and \
            reg.get('spot_number') is not None
        amount = amounts.get(reg['id'], 0)
        if amount > 0:
            domain.create_payment(reg['id'], None, 'REFUND', amount, 'CASH',
                                  actor_user_id)
        reg['status'] = 'REFUNDED'
        if was_checked_in:
            domain.release_spot(reg)
        domain.touch_entity(reg)
        domain.void_ballots_for(reg['id'])
        domain.revert_awards_won_by(reg['id'])


# ---------------------------------------------------------------------------
# 7. booth_fee_calc (PRD 3.9)
# ---------------------------------------------------------------------------

def compute_booth_fee(booth_tier, power_requested):
    fee = TIER_FEE[booth_tier]
    if power_requested:
        fee += POWER_FEE_CENTS
    return fee


# ---------------------------------------------------------------------------
# 8. noise_compliance_eval (PRD 3.8)
# ---------------------------------------------------------------------------

def evaluate_noise_reading(event, reading_db, recorded_at_iso):
    """Return (is_curfew, limit_db, is_exceedance)."""
    dt = parse_dt(recorded_at_iso)
    t_hhmm = f'{dt.hour:02d}:{dt.minute:02d}'
    cs = event['curfew_start']
    ce = event['curfew_end']
    if cs <= ce:
        is_curfew = cs <= t_hhmm < ce
    else:  # wraps midnight
        is_curfew = t_hhmm >= cs or t_hhmm < ce
    limit = CURFEW_LIMIT_DB if is_curfew else DAY_LIMIT_DB
    is_exceedance = Decimal(str(reading_db)) > limit
    return is_curfew, float(limit), bool(is_exceedance)


def maybe_suspend_permit(event):
    """Tripwire: when exceedance count reaches exactly 3, suspend permit and
    cancel future-scheduled sound slots."""
    if event['sound_permit_status'] != 'ACTIVE':
        return
    count = domain.compute_noise_exceedance_count(event['id'])
    if count >= EXCEEDANCE_SUSPENSION_THRESHOLD:
        event['sound_permit_status'] = 'SUSPENDED'
        domain.bump_event(event)
        now = parse_dt(CLOCK.now())
        for slot in domain.sound_slots_of_event(event['id']):
            if slot['status'] == 'SCHEDULED' and parse_dt(slot['slot_start']) > now:
                slot['status'] = 'CANCELLED'
                domain.touch_entity(slot)
