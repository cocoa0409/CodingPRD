"""Shared domain logic: computed counters, payment ledger, cascades, event helpers.

Import order: this module must not import routes or serializers at module level.
Serializers import this module.
"""
from db import STORE, new_id, now_iso, CLOCK
from util import parse_dt

NON_TERMINAL_REG_STATUSES = ('PENDING_PAYMENT', 'CONFIRMED', 'CHECKED_IN')


# ---------------------------------------------------------------------------
# Computed counters
# ---------------------------------------------------------------------------

def compute_treasury(event_id):
    total = 0
    for p in STORE.payments.values():
        if payment_event_id(p) != event_id:
            continue
        if p['kind'] in ('ENTRY_FEE', 'BOOTH_FEE'):
            total += p['amount_cents']
        elif p['kind'] == 'REFUND':
            total -= p['amount_cents']
    return total


def compute_noise_exceedance_count(event_id):
    return sum(1 for r in STORE.noise_readings.values()
               if r['event_id'] == event_id and r['is_exceedance'])


def compute_class_confirmed_count(class_id):
    return sum(1 for r in STORE.registrations.values()
               if r['class_id'] == class_id and r['status'] in NON_TERMINAL_REG_STATUSES)


def compute_zone_assigned_count(zone_id):
    zone = STORE.zones.get(zone_id)
    if zone is None:
        return 0
    if zone['zone_type'] in ('SHOW_FIELD', 'OVERFLOW'):
        return sum(1 for r in STORE.registrations.values()
                   if r.get('assigned_zone_id') == zone_id and r['status'] == 'CHECKED_IN')
    # VENDOR_ROW: count of occupied booth spaces
    return sum(len(app['assigned_spaces'])
               for app in STORE.booth_applications.values()
               if app.get('assigned_zone_id') == zone_id and app['status'] == 'ASSIGNED')


def compute_refunded_cents_total(event_id):
    return sum(p['amount_cents'] for p in STORE.payments.values()
               if payment_event_id(p) == event_id and p['kind'] == 'REFUND')


def payment_event_id(payment):
    """Resolve an event id for a payment through whichever parent FK is set."""
    if payment.get('registration_id'):
        reg = STORE.registrations.get(payment['registration_id'])
        return reg['event_id'] if reg else None
    if payment.get('booth_application_id'):
        app = STORE.booth_applications.get(payment['booth_application_id'])
        return app['event_id'] if app else None
    return None


# ---------------------------------------------------------------------------
# Entity mutation helpers
# ---------------------------------------------------------------------------

def touch_entity(rec):
    rec['updated_at'] = now_iso()
    rec['version'] = rec.get('version', 1) + 1


def bump_event(event):
    touch_entity(event)


def create_payment(registration_id, booth_application_id, kind, amount_cents,
                   method, recorded_by_user_id):
    """Append a ledger row; update parent's paid/refunded aggregates; bump event version."""
    pay = {
        'id': new_id(),
        'registration_id': registration_id,
        'booth_application_id': booth_application_id,
        'kind': kind,
        'amount_cents': amount_cents,
        'method': method,
        'status': 'SUCCEEDED',
        'recorded_by_user_id': recorded_by_user_id,
        'created_at': now_iso(),
        '_seq': STORE.next_seq(),
    }
    STORE.payments[pay['id']] = pay

    event = None
    if registration_id:
        reg = STORE.registrations[registration_id]
        event = STORE.events.get(reg['event_id'])
        if kind == 'ENTRY_FEE':
            reg['paid_cents'] += amount_cents
        elif kind == 'REFUND':
            reg['refunded_cents'] += amount_cents
    elif booth_application_id:
        app = STORE.booth_applications[booth_application_id]
        event = STORE.events.get(app['event_id'])
        if kind == 'BOOTH_FEE':
            app['paid_cents'] += amount_cents
        elif kind == 'REFUND':
            app['paid_cents'] -= amount_cents
    if event is not None:
        bump_event(event)
    return pay


def find_event(event_id):
    return STORE.events.get(event_id)


def registrations_of_event(event_id):
    return [r for r in STORE.registrations.values() if r['event_id'] == event_id]


def classes_of_event(event_id):
    return [c for c in STORE.classes.values() if c['event_id'] == event_id]


def zones_of_event(event_id):
    return [z for z in STORE.zones.values() if z['event_id'] == event_id]


def judges_of_event(event_id):
    return [j for j in STORE.judges.values() if j['event_id'] == event_id]


def awards_of_event(event_id):
    return [a for a in STORE.awards.values() if a['event_id'] == event_id]


def sound_slots_of_event(event_id):
    return [s for s in STORE.sound_slots.values() if s['event_id'] == event_id]


def sheets_of_registration(registration_id):
    return [s for s in STORE.score_sheets.values()
            if s['registration_id'] == registration_id]


def ballots_for_registration(registration_id):
    return [b for b in STORE.ballots.values()
            if b['registration_id'] == registration_id]


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def revert_awards_won_by(registration_id):
    """Awards in COMPUTED/FINALIZED won by this registration revert to PENDING."""
    for award in STORE.awards.values():
        if (award.get('winner_registration_id') == registration_id
                and award['status'] in ('COMPUTED', 'FINALIZED')
                and not award.get('overridden', False)):
            award['winner_registration_id'] = None
            award['winner_score'] = None
            award['tie_break_log'] = ''
            award['status'] = 'PENDING'
            touch_entity(award)


def void_ballots_for(registration_id):
    for ballot in ballots_for_registration(registration_id):
        if ballot['status'] == 'VALID':
            ballot['status'] = 'VOID'
            touch_entity(ballot)


def release_spot(registration):
    """Free the registration's spot; assigned_zone_id retained for audit."""
    registration['spot_number'] = None


def judged_classes(event_id):
    return [c for c in classes_of_event(event_id)
            if c['judging_mode'] in ('JUDGED', 'BOTH')]


def peoples_choice_classes(event_id):
    return [c for c in classes_of_event(event_id)
            if c['judging_mode'] in ('PEOPLES_CHOICE', 'BOTH')]


def judge_assigned_to_class(judge, class_id):
    return class_id in (judge.get('assigned_class_ids') or [])


def registration_has_sheet_from_judge(registration_id, judge_id):
    """A SUBMITTED or LOCKED sheet counts as fulfilling the judging requirement."""
    for s in STORE.score_sheets.values():
        if (s['registration_id'] == registration_id and s['judge_id'] == judge_id
                and s['status'] in ('SUBMITTED', 'LOCKED')):
            return True
    return False


def judged_class_complete(cls):
    """Every CHECKED_IN registration in cls has a SUBMITTED/LOCKED sheet from
    every judge assigned to the class."""
    checked_in = [r for r in STORE.registrations.values()
                  if r['class_id'] == cls['id'] and r['status'] == 'CHECKED_IN']
    assigned_judges = [j for j in judges_of_event(cls['event_id'])
                       if judge_assigned_to_class(j, cls['id'])]
    for reg in checked_in:
        for judge in assigned_judges:
            if not registration_has_sheet_from_judge(reg['id'], judge['id']):
                return False
    return True


def all_judged_classes_complete(event_id):
    for cls in judged_classes(event_id):
        if not judged_class_complete(cls):
            return False
    return True


def transition_event_to_tabulating(event):
    """JUDGING -> TABULATING with sheet lock cascade."""
    event['lifecycle_status'] = 'TABULATING'
    bump_event(event)
    for sheet in STORE.score_sheets.values():
        reg = STORE.registrations.get(sheet['registration_id'])
        if reg is None or reg['event_id'] != event['id']:
            continue
        if sheet['status'] == 'SUBMITTED':
            sheet['status'] = 'LOCKED'
            touch_entity(sheet)


def maybe_auto_advance_to_tabulating(event):
    """Auto-advance JUDGING -> TABULATING when all judged classes are complete."""
    if event['lifecycle_status'] != 'JUDGING':
        return
    if not judged_classes(event['id']):
        return
    if all_judged_classes_complete(event['id']):
        transition_event_to_tabulating(event)


def complete_elapsed_sound_slots():
    """On clock set: SCHEDULED slots with slot_end <= now become COMPLETED."""
    now = parse_dt(CLOCK.now())
    for slot in STORE.sound_slots.values():
        if slot['status'] == 'SCHEDULED':
            if parse_dt(slot['slot_end']) <= now:
                slot['status'] = 'COMPLETED'
                touch_entity(slot)


def sorted_created(items):
    return sorted(items, key=lambda r: (r.get('created_at', ''), r.get('_seq', 0)))
