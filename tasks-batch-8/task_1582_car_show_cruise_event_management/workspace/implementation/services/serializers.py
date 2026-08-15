"""Entity -> public JSON serializers (strip internal fields, recompute live counters)."""
from db import STORE
from services import domain


def _strip(rec):
    return {k: v for k, v in rec.items() if not k.startswith('_')}


def event_json(ev):
    out = _strip(ev)
    out['treasury_cents'] = domain.compute_treasury(ev['id'])
    out['noise_exceedance_count'] = domain.compute_noise_exceedance_count(ev['id'])
    return out


def class_json(cls):
    out = _strip(cls)
    out['confirmed_count'] = domain.compute_class_confirmed_count(cls['id'])
    return out


def zone_json(zone):
    out = _strip(zone)
    out['assigned_count'] = domain.compute_zone_assigned_count(zone['id'])
    return out


def registrant_json(reg):
    return _strip(reg)


def vehicle_json(veh):
    return _strip(veh)


def registration_json(reg):
    return _strip(reg)


def payment_json(pay):
    return _strip(pay)


def waiver_json(w):
    return _strip(w)


def booth_json(app):
    return _strip(app)


def judge_json(judge):
    out = _strip(judge)
    out['submitted_sheet_count'] = sum(
        1 for s in STORE.score_sheets.values()
        if s['judge_id'] == judge['id'] and s['status'] in ('SUBMITTED', 'LOCKED'))
    return out


def score_sheet_json(sheet):
    return _strip(sheet)


def ballot_json(ballot):
    return _strip(ballot)


def award_json(award):
    return _strip(award)


def noise_reading_json(reading):
    return _strip(reading)


def sound_slot_json(slot):
    return _strip(slot)
