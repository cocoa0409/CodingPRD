"""Ring slots, judge assignment, placings, premium awards."""
from datetime import timedelta
from flask import Blueprint, request

import errors
import services
from db import store, new_record, touch
from middleware import require_roles, authenticate
from response import success_object, success_list
from util import (
    body, require, require_str, require_dt,
    pagination_params, sorted_created, apply_filters, is_int, AWARDS,
)
from views import ring_slot_view, placing_view, premium_award_view

bp = Blueprint('show', __name__)

JUDGE_GAP = timedelta(minutes=15)


def get_slot_or_404(slot_id):
    s = store.ring_slots.get(slot_id)
    if s is None:
        raise errors.not_found('RingSlot not found')
    return s


# ----------------------------------------------------------------- Ring slots

@bp.post('/v1/ring-slots')
def create_ring_slot():
    require_roles('ShowClerk')
    b = body()
    fair_id = require(b, 'fair_id')
    fair = store.fairs.get(fair_id)
    if fair is None:
        raise errors.not_found('Fair not found')
    class_id = require(b, 'class_id')
    cls = store.classes.get(class_id)
    if cls is None:
        raise errors.not_found('ShowClass not found')
    ring_name = require_str(b, 'ring_name')
    starts_at = require_dt(b, 'starts_at')
    ends_at = require_dt(b, 'ends_at')
    if ends_at <= starts_at:
        raise errors.invalid_request('ends_at must be strictly after starts_at')
    if cls['fair_id'] != fair_id:
        raise errors.invalid_request('class_id does not belong to the given fair')

    # One slot per class within the fair.
    for s in store.ring_slots.values():
        if s['fair_id'] == fair_id and s['class_id'] == class_id:
            raise errors.invalid_state('This class already has a ring slot in this fair')

    # Half-open [starts_at, ends_at) overlap within the same ring; touching ok.
    for s in store.ring_slots.values():
        if s['fair_id'] == fair_id and s['ring_name'] == ring_name:
            if s['starts_at'] < ends_at and starts_at < s['ends_at']:
                raise errors.err('ERR_RING_TIME_CONFLICT', 409,
                                 'Slot overlaps an existing slot in this ring')

    slot = new_record({
        'fair_id': fair_id,
        'class_id': class_id,
        'ring_name': ring_name,
        'starts_at': starts_at,
        'ends_at': ends_at,
        'judge_id': None,
        'status': 'SCHEDULED',
    })
    store.ring_slots[slot['id']] = slot
    return success_object(ring_slot_view(slot), status=201)


@bp.get('/v1/ring-slots/<slotId>')
def get_ring_slot(slotId):
    authenticate()
    return success_object(ring_slot_view(get_slot_or_404(slotId)))


@bp.get('/v1/ring-slots')
def list_ring_slots():
    authenticate()
    limit, offset = pagination_params()
    recs = apply_filters(store.ring_slots.values(), {
        'fair_id': request.args.get('fair_id'),
        'class_id': request.args.get('class_id'),
        'judge_id': request.args.get('judge_id'),
        'ring_name': request.args.get('ring_name'),
    })
    return success_list([ring_slot_view(s) for s in sorted_created(recs)], limit, offset)


@bp.post('/v1/ring-slots/<slotId>/assign-judge')
def assign_judge(slotId):
    require_roles('ShowClerk')
    slot = get_slot_or_404(slotId)
    b = body()
    judge_id = require(b, 'judge_id')
    judge = store.judges.get(judge_id)
    if judge is None:
        raise errors.not_found('Judge not found')
    # OCC on the slot: non-optional, stale values rejected.
    expected = require(b, 'expected_ring_slot_version')
    if not is_int(expected):
        raise errors.invalid_request('expected_ring_slot_version must be an integer')
    if expected != slot['version']:
        raise errors.stale_version('expected_ring_slot_version does not match the slot version')

    # Judge spacing (business_temporal, priority 13): every pair of the
    # judge's assignments must keep a >= 15 minute gap; bare adjacency is a
    # conflict. Evaluated before the qualification constraint per the ladder.
    for s in store.ring_slots.values():
        if s['judge_id'] != judge_id or s['id'] == slot['id']:
            continue
        if not (s['ends_at'] + JUDGE_GAP <= slot['starts_at']
                or slot['ends_at'] + JUDGE_GAP <= s['starts_at']):
            raise errors.err('ERR_JUDGE_TIME_CONFLICT', 409,
                             'Judge assignments must keep at least a 15 minute gap')

    cls = store.classes.get(slot['class_id'])
    if cls is not None and cls['species'] not in judge['qualified_species']:
        raise errors.err('ERR_JUDGE_NOT_QUALIFIED', 422,
                         'Judge is not qualified for this species')

    slot['judge_id'] = judge_id
    touch(slot)
    return success_object(ring_slot_view(slot))


@bp.post('/v1/ring-slots/<slotId>/start')
def start_slot(slotId):
    require_roles('ShowClerk')
    slot = get_slot_or_404(slotId)
    if slot['status'] != 'SCHEDULED':
        raise errors.invalid_state('Only a SCHEDULED slot can be started')
    if slot['judge_id'] is None:
        raise errors.invalid_state('A judge must be assigned before the slot starts')
    fair = store.fairs[slot['fair_id']]
    if fair['posture'] != 'SHOWING':
        raise errors.posture_forbids('Starting a slot requires SHOWING posture')
    slot['status'] = 'IN_PROGRESS'
    touch(slot)
    return success_object(ring_slot_view(slot))


# -------------------------------------------------------------------- Placing

@bp.post('/v1/ring-slots/<slotId>/placings')
def submit_placings(slotId):
    user_id, role = require_roles('Judge')
    slot = get_slot_or_404(slotId)
    if slot['judge_id'] != user_id:
        raise errors.not_assigned_judge()
    if slot['status'] != 'IN_PROGRESS':
        raise errors.invalid_state('Placings require an IN_PROGRESS slot')
    fair = store.fairs[slot['fair_id']]
    if fair['posture'] != 'SHOWING':
        raise errors.posture_forbids('Placings require SHOWING posture')
    cls = store.classes[slot['class_id']]

    b = body()
    placings_in = require(b, 'placings')
    if not isinstance(placings_in, list):
        raise errors.invalid_request('placings must be a list')

    # Payload well-formedness (priority 16).
    seen_entries = set()
    lines = []
    for line in placings_in:
        if not isinstance(line, dict):
            raise errors.invalid_request('Each placing line must be an object')
        entry_id = line.get('entry_id')
        if not isinstance(entry_id, str) or not entry_id:
            raise errors.invalid_request('Each placing line requires entry_id')
        if entry_id in seen_entries:
            raise errors.invalid_request('Duplicate entry_id in placing submission')
        seen_entries.add(entry_id)
        rank = line.get('rank')
        if not is_int(rank) or rank <= 0:
            raise errors.invalid_request('rank must be a positive integer')
        award = line.get('award', 'NONE')
        if award not in AWARDS:
            raise errors.invalid_request('award must be NONE, GRAND_CHAMPION or RESERVE_CHAMPION')
        lines.append({'entry_id': entry_id, 'rank': rank, 'award': award})

    # Existence of body FKs (priority 3): every referenced entry must exist.
    for line in lines:
        if line['entry_id'] not in store.entries:
            raise errors.not_found('Placing line references a non-existent entry')

    # Champion uniqueness (priority 23): at most one GRAND and one RESERVE
    # per species per fair, across existing RECORDED placings and this batch.
    batch_grand = sum(1 for l in lines if l['award'] == 'GRAND_CHAMPION')
    batch_reserve = sum(1 for l in lines if l['award'] == 'RESERVE_CHAMPION')
    existing_grand = 0
    existing_reserve = 0
    for p in store.placings.values():
        if p['status'] != 'RECORDED':
            continue
        p_cls = store.classes.get(p['class_id'])
        if p_cls is None or p_cls['fair_id'] != fair['id'] or p_cls['species'] != cls['species']:
            continue
        if p['award'] == 'GRAND_CHAMPION':
            existing_grand += 1
        elif p['award'] == 'RESERVE_CHAMPION':
            existing_reserve += 1
    if batch_grand > 1 or batch_grand + existing_grand > 1 \
            or batch_reserve > 1 or batch_reserve + existing_reserve > 1:
        raise errors.err('ERR_CHAMPION_ALREADY_AWARDED', 409,
                         'At most one GRAND_CHAMPION and one RESERVE_CHAMPION per species per fair')

    # Rank contiguity (priority 24): exactly the set 1..N.
    ranks = sorted(l['rank'] for l in lines)
    if ranks != list(range(1, len(lines) + 1)):
        raise errors.err('ERR_RANK_SEQUENCE_INVALID', 422,
                         'Ranks must be the contiguous set 1..N with no duplicates or gaps')

    # Completeness (priority 25): cover every CLASSIFIED entry of the class.
    classified = {e['id'] for e in store.entries.values()
                  if e.get('class_id') == cls['id'] and e['status'] == 'CLASSIFIED'}
    if not classified.issubset(seen_entries):
        raise errors.err('ERR_INCOMPLETE_PLACINGS', 422,
                         'Placing submission omits a CLASSIFIED entry of the class')

    # Membership (priority 29): every line belongs to the class, CLASSIFIED.
    for line in lines:
        e = store.entries[line['entry_id']]
        if e.get('class_id') != cls['id'] or e['status'] != 'CLASSIFIED':
            raise errors.err('ERR_ENTRY_NOT_IN_CLASS', 422,
                             'Placing line entry is not a CLASSIFIED member of this class')

    # ----- Atomic acceptance -----
    lines.sort(key=lambda l: l['rank'])
    for line in lines:
        e = store.entries[line['entry_id']]
        e['status'] = 'SHOWN'
        touch(e)
    # class_size is counted after the batch lands.
    class_size = services.placed_count(cls['id'])

    placing_ids = []
    award_ids = []
    for line in lines:
        e = store.entries[line['entry_id']]
        placing = new_record({
            'ring_slot_id': slot['id'],
            'class_id': cls['id'],
            'entry_id': e['id'],
            'rank': line['rank'],
            'award': line['award'],
            'status': 'RECORDED',
            'void_reason': None,
        })
        store.placings[placing['id']] = placing
        placing_ids.append(placing['id'])

        amount = services.premium_provisional(fair, e, class_size, line['rank'], line['award'])
        award = new_record({
            'entry_id': e['id'],
            'placing_id': placing['id'],
            'provisional_amount_cents': amount,
            'final_amount_cents': None,
            'status': 'ACCRUED',
            'approved_by_user_id': None,
            'paid_by_user_id': None,
        })
        store.premium_awards[award['id']] = award
        award_ids.append(award['id'])

        e['state_fair_qualified'] = services.compute_state_fair_qualified(
            fair, e, line['rank'], line['award'])
        touch(e)  # SHOWN + qualification settle as one mutation per placing
        touch(fair)  # pool debited by this accrual

    cls['status'] = 'FINALIZED'
    touch(cls)
    slot['status'] = 'COMPLETED'
    touch(slot)

    return success_object({'placing_ids': placing_ids, 'premium_award_ids': award_ids},
                          status=201)


@bp.get('/v1/placings/<placingId>')
def get_placing(placingId):
    authenticate()
    p = store.placings.get(placingId)
    if p is None:
        raise errors.not_found('Placing not found')
    return success_object(placing_view(p))


@bp.get('/v1/placings')
def list_placings():
    authenticate()
    limit, offset = pagination_params()
    recs = apply_filters(store.placings.values(), {
        'ring_slot_id': request.args.get('ring_slot_id'),
        'class_id': request.args.get('class_id'),
        'entry_id': request.args.get('entry_id'),
        'status': request.args.get('status'),
    })
    return success_list([placing_view(p) for p in sorted_created(recs)], limit, offset)


@bp.post('/v1/placings/<placingId>/void')
def void_placing(placingId):
    user_id, role = require_roles('Judge', 'FairBoardAdmin')
    p = store.placings.get(placingId)
    if p is None:
        raise errors.not_found('Placing not found')
    if role == 'Judge':
        slot = store.ring_slots.get(p['ring_slot_id'])
        if slot is None or slot['judge_id'] != user_id:
            raise errors.not_assigned_judge()
    if p['status'] != 'RECORDED':
        raise errors.invalid_state('Only a RECORDED placing can be voided')
    entry = store.entries[p['entry_id']]
    if entry['status'] != 'SHOWN':
        raise errors.invalid_state('Placing can be voided only while the entry is SHOWN')
    b = body()
    reason = require_str(b, 'reason')

    p['status'] = 'VOIDED'
    p['void_reason'] = reason
    touch(p)

    # Compensate: award forfeits back to the pool.
    award = None
    for a in store.premium_awards.values():
        if a['placing_id'] == p['id']:
            award = a
            break
    if award is not None and award['status'] in ('ACCRUED', 'APPROVED'):
        award['status'] = 'FORFEITED'
        touch(award)
        fair = services.fair_of_entry(entry)
        touch(fair)  # pool release mutates the fair

    entry['status'] = 'CLASSIFIED'
    entry['state_fair_qualified'] = False
    touch(entry)

    cls = store.classes.get(p['class_id'])
    if cls is not None and cls['status'] == 'FINALIZED':
        cls['status'] = 'OPEN'
        touch(cls)
    return success_object(placing_view(p))


# ------------------------------------------------------------- Premium awards

@bp.get('/v1/premium-awards/<awardId>')
def get_premium_award(awardId):
    authenticate()
    a = store.premium_awards.get(awardId)
    if a is None:
        raise errors.not_found('PremiumAward not found')
    return success_object(premium_award_view(a))


@bp.get('/v1/premium-awards')
def list_premium_awards():
    authenticate()
    limit, offset = pagination_params()
    recs = apply_filters(store.premium_awards.values(), {
        'entry_id': request.args.get('entry_id'),
        'placing_id': request.args.get('placing_id'),
        'status': request.args.get('status'),
    })
    return success_list([premium_award_view(a) for a in sorted_created(recs)], limit, offset)


def _award_and_fair(award_id):
    a = store.premium_awards.get(award_id)
    if a is None:
        raise errors.not_found('PremiumAward not found')
    fair = services.fair_of_entry(store.entries[a['entry_id']])
    return a, fair


@bp.post('/v1/premium-awards/<awardId>/approve')
def approve_premium_award(awardId):
    user_id, _ = require_roles('Treasurer')
    a, fair = _award_and_fair(awardId)
    if a['status'] != 'ACCRUED':
        raise errors.invalid_state('Only an ACCRUED award can be approved')
    if fair['posture'] != 'SETTLEMENT':
        raise errors.posture_forbids('Premium approval requires SETTLEMENT posture')
    if services.signed_affidavit(a['entry_id']) is None:
        raise errors.err('ERR_AFFIDAVIT_MISSING', 409,
                         'Entry has no SIGNED affidavit')
    a['status'] = 'APPROVED'
    a['approved_by_user_id'] = user_id
    touch(a)
    return success_object(premium_award_view(a))


@bp.post('/v1/premium-awards/<awardId>/pay')
def pay_premium_award(awardId):
    user_id, _ = require_roles('Treasurer')
    a, fair = _award_and_fair(awardId)
    if a['status'] != 'APPROVED':
        raise errors.invalid_state('Only an APPROVED award can be paid')
    if fair['posture'] != 'SETTLEMENT':
        raise errors.posture_forbids('Premium payment requires SETTLEMENT posture')
    if user_id == a['approved_by_user_id']:
        raise errors.segregation('Payer must differ from approver')
    a['status'] = 'PAID'
    a['paid_by_user_id'] = user_id
    touch(a)
    return success_object(premium_award_view(a))


@bp.post('/v1/premium-awards/<awardId>/forfeit')
def forfeit_premium_award(awardId):
    require_roles('Treasurer')
    a, fair = _award_and_fair(awardId)
    if a['status'] not in ('ACCRUED', 'APPROVED'):
        raise errors.invalid_state('Only an ACCRUED or APPROVED award can be forfeited')
    b = body()
    require_str(b, 'reason')
    a['status'] = 'FORFEITED'
    touch(a)
    touch(fair)  # reservation returns to the pool
    return success_object(premium_award_view(a))
