"""In-memory store.  Plain Python dicts keyed by id; nothing is persisted and
nothing is ever seeded.  A fresh process starts completely empty."""
import itertools
import uuid

from util import fmt_iso, now_iso, parse_iso
from datetime import datetime, timezone

CLOCK_DEFAULT_RAW = "2026-08-01T00:00:00Z"


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.projects = {}
        self.owners = {}
        self.facilities = {}
        self.investigations = {}
        self.conflicts = {}
        self.determinations = {}
        self.plans = {}
        self.permits = {}
        self.slots = {}
        self.commitments = {}
        self.agreements = {}
        self.documents = {}
        self.findings = {}
        self.claims = {}
        self._seq = itertools.count(1)
        self.clock_raw = CLOCK_DEFAULT_RAW
        self.clock_dt = parse_iso(CLOCK_DEFAULT_RAW)

    def seq(self):
        return next(self._seq)

    # ---- logical clock -------------------------------------------------------
    def set_clock(self, raw, dt):
        self.clock_raw = raw
        self.clock_dt = dt

    @property
    def clock(self):
        """The logical clock instant; never falls back to wall-clock time."""
        return self.clock_dt


db = Store()


def new_id():
    return str(uuid.uuid4())


def base_record(with_version=True):
    stamp = now_iso()
    rec = {"id": new_id(), "_seq": db.seq(), "created_at": stamp}
    if with_version:
        rec["updated_at"] = stamp
        rec["version"] = 1
    return rec


def ordered(collection):
    """All rows of a collection in created_at ascending order (insertion order)."""
    return sorted(collection.values(), key=lambda r: r["_seq"])


# ---------------------------------------------------------------- lookups -----

def conflicts_of_project(project_id):
    return [c for c in ordered(db.conflicts) if c["project_id"] == project_id]


def commitments_of_project(project_id):
    return [c for c in ordered(db.commitments) if c["project_id"] == project_id]


def commitments_of_owner(owner_id):
    return [c for c in ordered(db.commitments) if c["owner_id"] == owner_id]


def commitments_of_conflict(conflict_id):
    out = []
    for c in ordered(db.commitments):
        plan = db.plans.get(c["plan_id"])
        if plan is not None and plan["conflict_id"] == conflict_id:
            out.append(c)
    return out


def commitments_of_slot(slot_id):
    return [c for c in ordered(db.commitments) if c.get("joint_trench_slot_id") == slot_id]


def plans_of_conflict(conflict_id):
    return [p for p in ordered(db.plans) if p["conflict_id"] == conflict_id]


def determinations_of_conflict(conflict_id):
    return [d for d in ordered(db.determinations) if d["conflict_id"] == conflict_id]


def permits_of_conflict(conflict_id):
    return [p for p in ordered(db.permits) if p["conflict_id"] == conflict_id]


def agreements_of_plan(plan_id):
    return [a for a in ordered(db.agreements) if a["plan_id"] == plan_id]


def agreements_of_project(project_id):
    return [a for a in ordered(db.agreements) if a["project_id"] == project_id]


def agreements_of_owner(owner_id):
    return [a for a in ordered(db.agreements) if a["owner_id"] == owner_id]


def documents_of_agreement(agreement_id):
    return [d for d in ordered(db.documents) if d["agreement_id"] == agreement_id]


def findings_of_agreement(agreement_id):
    return [f for f in ordered(db.findings) if f["agreement_id"] == agreement_id]


def claims_of_project(project_id):
    return [k for k in ordered(db.claims) if k["project_id"] == project_id]


def investigations_of_facility(facility_id):
    return [i for i in ordered(db.investigations) if i["facility_id"] == facility_id]


def slots_of_project(project_id):
    return [s for s in ordered(db.slots) if s["project_id"] == project_id]


def facilities_of_owner(owner_id):
    return [f for f in ordered(db.facilities) if f["owner_id"] == owner_id]


# ---- graph walks -------------------------------------------------------------

def facility_of_conflict(conflict):
    return db.facilities.get(conflict["facility_id"])


def owner_of_conflict(conflict):
    facility = facility_of_conflict(conflict)
    if facility is None:
        return None
    return db.owners.get(facility["owner_id"])


def conflict_of_plan(plan):
    return db.conflicts.get(plan["conflict_id"])


def project_of_conflict(conflict):
    return db.projects.get(conflict["project_id"])


def plan_of_agreement(agreement):
    return db.plans.get(agreement["plan_id"])


def conflict_of_agreement(agreement):
    plan = plan_of_agreement(agreement)
    return None if plan is None else conflict_of_plan(plan)
