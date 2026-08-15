"""In-memory data store. Everything lives in module-level dicts keyed by id.
No disk persistence of any kind; every process boot starts empty."""

import itertools
import uuid

# entity name -> {id: row dict}
campaigns = {}
agencies = {}
families = {}
children = {}
wish_items = {}
donors = {}
adoptions = {}
gifts = {}
backfill_purchases = {}
distribution_events = {}
distribution_slots = {}
duplicate_flags = {}
thank_you_notes = {}
family_audit_events = {}
season_settings = {}  # singleton keyed by 'GLOBAL'

# monotonic insertion sequence for stable created_at ordering
_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())
