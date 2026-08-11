"""Animal entries, deadline verification, weigh tickets, classes, classify."""
from flask import Blueprint, request

import errors
import services
from db import store, new_record, touch
from middleware import require_roles, authenticate
from response import success_object, success_list
from util import (
    body, require, require_str, require_enum, require_dt, require_num,
    pagination_params, sorted_created, apply_filters, is_int, is_num,
    SPECIES,
)
from views import entry_view, weigh_ticket_view, class_view

bp = Blueprint('entries', __name__)


def get_entry_or_404(entry_id):
    e = store.entries.get(entry_id)
    if e is None:
        raise errors.not_found('AnimalEntry not found')
    return e


def get_fair_or_404(fair_id):
    f = store.fairs.get(fair_id)
    if f is None:
        raise errors.not_found('Fair not found')
    return f


# -------------------------------------------------------------------- Entries

@bp.post('/v1/entries')
def create_entry():
    user_id, role = require_roles('FairBoardAdmin', 'Exhibitor')
    b = body()
    # Exhibitor ownership: may file only for themselves.
    if role == 'Exhibitor':
        exhibitor_id = b.get('exhibitor_id')
        if exhibitor_id is not None and exhibitor_id != user_id:
            raise errors.forbidden('Exhibitor may create entries only for themselves')
    fair_id = require(b, 'fair_id')
    fair = get_fair_or_404(fair_id)
    exhibitor_id = require(b, 'exhibitor_id')
    exhibitor = store.exhibitors.get(exhibitor_id)
    if exhibitor is None:
        raise errors.not_found('Exhibitor not found')
    if role == 'Exhibitor' and exhibitor_id != user_id:
        raise errors.forbidden('Exhibitor may create entries only for themselves')

    # Posture gate: entry creation only while ENTRIES_OPEN.
    if fair['posture'] != 'ENTRIES_OPEN':
        raise errors.posture_forbids('Entries may be created only while ENTRIES_OPEN')
    # Suspended exhibitors cannot file, no matter who files.
    if exhibitor['status'] == 'SUSPENDED':
        raise errors.err('ERR_EXHIBITOR_SUSPENDED', 409, 'Exhibitor is suspended')

    species = require_enum(b, 'species', SPECIES)
    tag_number = require_str(b, 'tag_number')
    ownership_acquired = require_dt(b, 'ownership_acquired_at')
    possession_start = require_dt(b, 'possession_start_at')

    for e in store.entries.values():
        if e['fair_id'] == fair_id and e['tag_number'] == tag_number:
            raise errors.err('ERR_DUPLICATE_TAG', 409, 'tag_number already used in this fair')

    entry = new_record({
        'fair_id': fair_id,
        'exhibitor_id': exhibitor_id,
        'species': species,
        'tag_number': tag_number,
        'ownership_acquired_at': ownership_acquired,
        'possession_start_at': possession_start,
        'official_weight_lbs': None,
        'class_id': None,
        'state_fair_qualified': False,
        'status': 'ENTERED',
        'disqualification_reason': None,
    })
    store.entries[entry['id']] = entry
    return success_object(entry_view(entry), status=201)


@bp.get('/v1/entries/<entryId>')
def get_entry(entryId):
    authenticate()
    return success_object(entry_view(get_entry_or_404(entryId)))


@bp.get('/v1/entries')
def list_entries():
    authenticate()
    limit, offset = pagination_params()
    recs = apply_filters(store.entries.values(), {
        'fair_id': request.args.get('fair_id'),
        'exhibitor_id': request.args.get('exhibitor_id'),
        'class_id': request.args.get('class_id'),
        'status': request.args.get('status'),
        'species': request.args.get('species'),
    })
    return success_list([entry_view(e) for e in sorted_created(recs)], limit, offset)


@bp.post('/v1/entries/<entryId>/verify')
def verify_entry(entryId):
    require_roles('FairBoardAdmin')
    entry = get_entry_or_404(entryId)
    if entry['status'] != 'ENTERED':
        raise errors.invalid_state('Only an ENTERED entry can be verified')
    fair = services.fair_of_entry(entry)
    if fair['posture'] not in ('ENTRIES_OPEN', 'ENTRIES_LOCKED'):
        raise errors.posture_forbids('Verification requires ENTRIES_OPEN or ENTRIES_LOCKED')
    b = body()
    decision = require(b, 'decision')
    if decision not in ('APPROVE', 'REJECT'):
        raise errors.invalid_request('decision must be APPROVE or REJECT')
    if decision == 'APPROVE':
        # Inclusive deadline boundaries, ownership first then possession.
        if entry['ownership_acquired_at'] > fair['ownership_deadline_at']:
            raise errors.err('ERR_OWNERSHIP_DEADLINE_MISSED', 422,
                             'ownership_acquired_at is after the fair ownership deadline')
        if entry['possession_start_at'] > fair['possession_deadline_at']:
            raise errors.err('ERR_POSSESSION_DEADLINE_MISSED', 422,
                             'possession_start_at is after the fair possession deadline')
        entry['status'] = 'VERIFIED'
    else:
        entry['status'] = 'REJECTED'
    touch(entry)
    return success_object(entry_view(entry))


DISQUALIFIABLE = ('VERIFIED', 'WEIGHED', 'CLASSIFIED', 'SHOWN', 'NOT_SOLD')


@bp.post('/v1/entries/<entryId>/disqualify')
def disqualify_entry(entryId):
    require_roles('FairBoardAdmin')
    entry = get_entry_or_404(entryId)
    b = body()
    reason = require_str(b, 'reason')
    if entry['status'] not in DISQUALIFIABLE:
        raise errors.invalid_state('Entry cannot be disqualified from its current state')
    services.cascade_disqualify_entry(entry, reason)
    return success_object(entry_view(entry))


# -------------------------------------------------------------- Weigh tickets

@bp.post('/v1/weigh-tickets')
def create_weigh_ticket():
    require_roles('WeighMaster')
    b = body()
    entry_id = require(b, 'entry_id')
    entry = get_entry_or_404(entry_id)
    # OCC on the parent entry: non-optional, stale values rejected.
    expected = require(b, 'expected_entry_version')
    if not is_int(expected):
        raise errors.invalid_request('expected_entry_version must be an integer')
    if expected != entry['version']:
        raise errors.stale_version('expected_entry_version does not match the entry version')
    # PRD §3.3: creating a ticket supersedes the entry's prior ACTIVE ticket;
    # a fresh ticket is accepted from VERIFIED (first ticket), WEIGHED
    # (superseding the prior ACTIVE ticket), or CLASSIFIED (reweigh).
    if entry['status'] not in ('VERIFIED', 'WEIGHED', 'CLASSIFIED'):
        raise errors.invalid_state('Weigh-in requires a VERIFIED, WEIGHED, or CLASSIFIED entry')
    fair = services.fair_of_entry(entry)
    if fair['posture'] != 'WEIGH_IN':
        raise errors.posture_forbids('Weigh-in requires WEIGH_IN posture')

    weight_lbs = require_num(b, 'weight_lbs')
    if weight_lbs <= 0:
        raise errors.invalid_request('weight_lbs must be greater than zero')
    weighed_at = require_dt(b, 'weighed_at')
    scale_identifier = b.get('scale_identifier')
    if scale_identifier is not None and not isinstance(scale_identifier, str):
        raise errors.invalid_request('scale_identifier must be a string')

    # Supersede: prior ACTIVE ticket is voided.
    for t in store.weigh_tickets.values():
        if t['entry_id'] == entry['id'] and t['status'] == 'ACTIVE':
            t['status'] = 'VOIDED'
            t['void_reason'] = 'SUPERSEDED'
            touch(t)

    # Reweigh of a CLASSIFIED entry un-classifies it.
    if entry['status'] == 'CLASSIFIED' and entry.get('class_id'):
        cls = store.classes.get(entry['class_id'])
        entry['class_id'] = None
        if cls is not None:
            touch(cls)  # placed_count is derived from entries

    ticket = new_record({
        'entry_id': entry['id'],
        'weight_lbs': weight_lbs,
        'weighed_at': weighed_at,
        'scale_identifier': scale_identifier,
        'status': 'ACTIVE',
        'void_reason': None,
    })
    store.weigh_tickets[ticket['id']] = ticket

    entry['status'] = 'WEIGHED'
    services.resolve_official_weight(entry)
    touch(entry)
    return success_object(weigh_ticket_view(ticket), status=201)


@bp.get('/v1/weigh-tickets/<ticketId>')
def get_weigh_ticket(ticketId):
    authenticate()
    t = store.weigh_tickets.get(ticketId)
    if t is None:
        raise errors.not_found('WeighTicket not found')
    return success_object(weigh_ticket_view(t))


@bp.get('/v1/weigh-tickets')
def list_weigh_tickets():
    authenticate()
    limit, offset = pagination_params()
    recs = apply_filters(store.weigh_tickets.values(), {
        'entry_id': request.args.get('entry_id'),
        'status': request.args.get('status'),
    })
    return success_list([weigh_ticket_view(t) for t in sorted_created(recs)], limit, offset)


@bp.post('/v1/weigh-tickets/<ticketId>/void')
def void_weigh_ticket(ticketId):
    require_roles('WeighMaster')
    t = store.weigh_tickets.get(ticketId)
    if t is None:
        raise errors.not_found('WeighTicket not found')
    if t['status'] != 'ACTIVE':
        raise errors.invalid_state('Only an ACTIVE ticket can be voided')
    entry = store.entries[t['entry_id']]
    # Manual void only while the entry is WEIGHED; CLASSIFIED-or-later entries
    # are corrected by recording a new ticket instead.
    if entry['status'] != 'WEIGHED':
        raise errors.invalid_state('Manual void requires the entry to be WEIGHED')
    b = body()
    reason = b.get('reason')
    if reason is not None and not isinstance(reason, str):
        raise errors.invalid_request('reason must be a string')
    t['status'] = 'VOIDED'
    t['void_reason'] = reason
    touch(t)
    services.resolve_official_weight(entry)
    if not any(x['entry_id'] == entry['id'] and x['status'] == 'ACTIVE'
               for x in store.weigh_tickets.values()):
        entry['status'] = 'VERIFIED'
    touch(entry)
    return success_object(weigh_ticket_view(t))


# ------------------------------------------------------------- Show classes

@bp.post('/v1/classes')
def create_class():
    require_roles('FairBoardAdmin')
    b = body()
    fair_id = require(b, 'fair_id')
    get_fair_or_404(fair_id)
    species = require_enum(b, 'species', SPECIES)
    class_code = require_str(b, 'class_code')
    weight_min = require_num(b, 'weight_min_lbs')
    weight_max = require_num(b, 'weight_max_lbs')
    capacity = require(b, 'capacity')
    if not is_int(capacity) or capacity <= 0:
        raise errors.invalid_request('capacity must be a positive integer')
    if services.dnum(weight_max) <= services.dnum(weight_min):
        raise errors.invalid_request('weight_max_lbs must be greater than weight_min_lbs')

    for c in store.classes.values():
        if c['fair_id'] == fair_id and c['species'] == species:
            if c['class_code'] == class_code:
                raise errors.err('ERR_CLASS_RANGE_OVERLAP', 409,
                                 'class_code already used for this fair and species')
            # Half-open [min, max) overlap; touching boundaries are allowed.
            if (services.dnum(c['weight_min_lbs']) < services.dnum(weight_max)
                    and services.dnum(weight_min) < services.dnum(c['weight_max_lbs'])):
                raise errors.err('ERR_CLASS_RANGE_OVERLAP', 409,
                                 'Weight range overlaps an existing class')

    cls = new_record({
        'fair_id': fair_id,
        'species': species,
        'class_code': class_code,
        'weight_min_lbs': weight_min,
        'weight_max_lbs': weight_max,
        'capacity': capacity,
        'status': 'OPEN',
    })
    store.classes[cls['id']] = cls
    return success_object(class_view(cls), status=201)


def get_class_or_404(class_id):
    c = store.classes.get(class_id)
    if c is None:
        raise errors.not_found('ShowClass not found')
    return c


@bp.get('/v1/classes/<classId>')
def get_class(classId):
    authenticate()
    return success_object(class_view(get_class_or_404(classId)))


@bp.get('/v1/classes')
def list_classes():
    authenticate()
    limit, offset = pagination_params()
    recs = apply_filters(store.classes.values(), {
        'fair_id': request.args.get('fair_id'),
        'species': request.args.get('species'),
        'status': request.args.get('status'),
    })
    return success_list([class_view(c) for c in sorted_created(recs)], limit, offset)


@bp.post('/v1/entries/<entryId>/classify')
def classify_entry(entryId):
    require_roles('ShowClerk')
    entry = get_entry_or_404(entryId)
    b = body()
    explicit_id = b.get('class_id')
    target = None
    if explicit_id is not None:
        target = store.classes.get(explicit_id)
        if target is None:
            raise errors.not_found('ShowClass not found')
    if entry['status'] != 'WEIGHED':
        raise errors.invalid_state('Only a WEIGHED entry can be classified')
    fair = services.fair_of_entry(entry)
    if fair['posture'] != 'WEIGH_IN':
        raise errors.posture_forbids('Classification requires WEIGH_IN posture')

    w = services.dnum(entry['official_weight_lbs'])
    if target is not None:
        # Explicit target: specific failure mapping, in order.
        if target['status'] != 'OPEN':
            raise errors.err('ERR_CLASS_NOT_OPEN', 409, 'Target class is not OPEN')
        if services.placed_count(target['id']) >= target['capacity']:
            raise errors.err('ERR_CLASS_CAPACITY_FULL', 409, 'Target class is at capacity')
        in_range = (target['fair_id'] == entry['fair_id']
                    and target['species'] == entry['species']
                    and services.dnum(target['weight_min_lbs']) <= w < services.dnum(target['weight_max_lbs']))
        if not in_range:
            raise errors.err('ERR_NO_CLASS_FOR_WEIGHT', 422,
                             'Entry weight or species does not match the target class')
    else:
        eligible = []
        for c in store.classes.values():
            if (c['fair_id'] == entry['fair_id'] and c['species'] == entry['species']
                    and c['status'] == 'OPEN'
                    and services.dnum(c['weight_min_lbs']) <= w < services.dnum(c['weight_max_lbs'])
                    and services.placed_count(c['id']) < c['capacity']):
                eligible.append(c)
        if not eligible:
            raise errors.err('ERR_NO_CLASS_FOR_WEIGHT', 422,
                             'No OPEN class covers this weight for the species')
        # Lowest weight_min wins; created_at breaks ties; id never does.
        eligible.sort(key=lambda c: (services.dnum(c['weight_min_lbs']), c['created_at'], c['_seq']))
        target = eligible[0]

    entry['status'] = 'CLASSIFIED'
    entry['class_id'] = target['id']
    touch(entry)
    touch(target)  # placed_count derived from entries changed
    return success_object(entry_view(entry))
