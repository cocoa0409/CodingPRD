"""In-memory data store, logical clock, id/timestamp minting.

The store starts EMPTY on every boot.  Nothing is seeded, preloaded or
hardcoded: every entity a test needs is created through the declared API.
"""

import datetime
import threading
import uuid

from flask import g

UTC = datetime.timezone.utc

# PRD 2.4 — before the clock is ever set it reads exactly this instant and it
# never falls back to real wall-clock time.
DEFAULT_CLOCK = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

LOCK = threading.RLock()


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.partnerships = {}
        self.programs = {}
        self.courses = {}
        self.service_scope_assignments = {}
        self.counselors = {}
        self.leads = {}
        self.enrollments = {}
        self.tuition_payments = {}
        self.marketing_entries = {}
        self.statements = {}
        self.teach_out_plans = {}
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


# --------------------------------------------------------------------------- #
# logical clock                                                               #
# --------------------------------------------------------------------------- #

def current_utc():
    return store.clock


def current_date():
    return store.clock.date()


def set_clock(dt):
    previous = store.clock
    store.clock = dt
    return previous


def iso_ms(dt):
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return iso_ms(store.clock)


# --------------------------------------------------------------------------- #
# identity / common fields                                                    #
# --------------------------------------------------------------------------- #

def new_id():
    return str(uuid.uuid4())


def base_entity(full=True):
    """Common fields.  ``full`` is False for the two append-only ledgers, which
    carry only ``id`` and ``created_at`` (PRD 2.4)."""
    ts = now_iso()
    ent = {"id": new_id(), "created_at": ts, "_seq": store.next_seq()}
    if full:
        ent["updated_at"] = ts
        ent["version"] = 1
    return ent


def _touched():
    reg = getattr(g, "_touched_ids", None)
    if reg is None:
        reg = set()
        g._touched_ids = reg
    return reg


def touch(ent):
    """Mutation of an entity: refresh updated_at and advance version.

    Idempotent inside one request so a single logical write never advances a
    version twice.
    """
    if ent is None:
        return
    reg = _touched()
    key = ent["id"]
    if key in reg:
        ent["updated_at"] = now_iso()
        return
    reg.add(key)
    ent["updated_at"] = now_iso()
    if "version" in ent:
        ent["version"] = ent["version"] + 1


def touch_soft(ent):
    """Derived-total recomputation on a Partnership: refresh updated_at without
    advancing version (PRD 2.4, narrow partnership-version rule)."""
    if ent is None:
        return
    ent["updated_at"] = now_iso()


def bump_partnership_version(p):
    """The four writes that genuinely restate the contract or the settlement
    history: contract action, terms amendment, program creation, statement
    creation (PRD 2.4)."""
    touch(p)


# --------------------------------------------------------------------------- #
# ordered collection helpers                                                  #
# --------------------------------------------------------------------------- #

def sort_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def programs_of(partnership_id):
    return sort_created([p for p in store.programs.values()
                         if p["partnership_id"] == partnership_id])


def courses_of(program_id):
    return sort_created([c for c in store.courses.values()
                         if c["program_id"] == program_id])


def assignments_of(program_id):
    return sort_created([a for a in store.service_scope_assignments.values()
                         if a["program_id"] == program_id])


def counselors_of(partnership_id):
    return sort_created([c for c in store.counselors.values()
                         if c["partnership_id"] == partnership_id])


def leads_of_program(program_id):
    return sort_created([l for l in store.leads.values()
                         if l["program_id"] == program_id])


def leads_of_counselor(counselor_id):
    return sort_created([l for l in store.leads.values()
                         if l["counselor_id"] == counselor_id])


def enrollments_of_program(program_id):
    return sort_created([e for e in store.enrollments.values()
                         if e["program_id"] == program_id])


def payments_of(enrollment_id):
    return sort_created([t for t in store.tuition_payments.values()
                         if t["enrollment_id"] == enrollment_id])


def marketing_of(program_id):
    return sort_created([m for m in store.marketing_entries.values()
                         if m["program_id"] == program_id])


def statements_of(partnership_id):
    return sort_created([s for s in store.statements.values()
                         if s["partnership_id"] == partnership_id])


def plans_of(program_id):
    return sort_created([t for t in store.teach_out_plans.values()
                         if t["program_id"] == program_id])


def enrollments_of_partnership(partnership_id):
    out = []
    for prog in programs_of(partnership_id):
        out.extend(enrollments_of_program(prog["id"]))
    return sort_created(out)


def partnership_of_program(program):
    return store.partnerships.get(program["partnership_id"])


def program_of_lead(lead):
    return store.programs.get(lead["program_id"])


def partnership_id_of_program(program_id):
    prog = store.programs.get(program_id)
    return prog["partnership_id"] if prog else None
