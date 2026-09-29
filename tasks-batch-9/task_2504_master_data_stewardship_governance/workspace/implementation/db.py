"""In-memory data store and the logical clock.

The store is a set of plain Python dicts and starts completely EMPTY on every
boot.  Nothing is seeded, preloaded or hardcoded -- every entity is created by
an API call.
"""

import uuid
from datetime import datetime, timezone

from flask import g

CLOCK_ORIGIN = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "domains",
    "source_systems",
    "stewards",
    "source_registrations",
    "steward_assignments",
    "quality_rules",
    "scorecard_runs",
    "quality_findings",
    "master_records",
    "merge_proposals",
    "change_requests",
    "consumer_subscriptions",
)


class Store(object):
    def __init__(self):
        self.clock = CLOCK_ORIGIN
        self._seq = 0
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def now():
    """The logical clock.  Never falls back to wall-clock time."""
    return store.clock


def new_id():
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# entity lifecycle helpers
# --------------------------------------------------------------------------

def create(kind, fields, common=True):
    """Mint a new entity dict with the shared resource properties."""
    entity = {"_kind": kind, "_seq": store.next_seq(), "id": new_id()}
    entity["created_at"] = now()
    if common:
        entity["updated_at"] = now()
        entity["version"] = 1
    entity.update(fields)
    return entity


def bump(entity):
    """Refresh updated_at and increment version on a mutated resource."""
    if "version" in entity:
        entity["updated_at"] = now()
        entity["version"] += 1


def touch_domain(domain):
    """Mark a domain as mutated by this request.

    Domain.version increments EXACTLY ONCE per HTTP request that mutates the
    domain row or any row the domain's derived posture/counters read -- never
    once per declared side effect (PRD 2.5).
    """
    touched = getattr(g, "touched_domains", None)
    if touched is None:
        touched = []
        g.touched_domains = touched
    if domain["id"] not in touched:
        touched.append(domain["id"])


def finalize():
    """Apply the once-per-request Domain.version bumps."""
    touched = getattr(g, "touched_domains", None)
    if not touched:
        return
    for domain_id in touched:
        domain = store.domains.get(domain_id)
        if domain is not None:
            domain["updated_at"] = now()
            domain["version"] += 1
    g.touched_domains = []


def resolve(collection, identifier, error_id):
    """Path / body identifier resolution with the declared 404 (PRD 2.9)."""
    row = collection.get(identifier) if isinstance(identifier, str) else None
    if row is None:
        from errors import fail
        fail(error_id, "The referenced resource does not exist.")
    return row


# --------------------------------------------------------------------------
# ordered scans -- list results are ordered by created_at ASC (never by id);
# the insertion sequence is the stable tie-break for identical instants.
# --------------------------------------------------------------------------

def ordered(collection):
    return sorted(collection.values(), key=lambda row: (row["created_at"], row["_seq"]))


def registrations_of(domain_id):
    return [r for r in ordered(store.source_registrations) if r["domain_id"] == domain_id]


def active_authoritative_registration(domain_id):
    for reg in registrations_of(domain_id):
        if reg["role"] == "AUTHORITATIVE" and reg["status"] == "ACTIVE":
            return reg
    return None


def rules_of(domain_id):
    return [r for r in ordered(store.quality_rules) if r["domain_id"] == domain_id]


def active_rules_of(domain_id):
    return [r for r in rules_of(domain_id) if r["status"] == "ACTIVE"]


def findings_of_rule(rule_id):
    return [f for f in ordered(store.quality_findings) if f["quality_rule_id"] == rule_id]


def rule_of_finding(finding):
    return store.quality_rules[finding["quality_rule_id"]]


def domain_of_finding(finding):
    return store.domains[rule_of_finding(finding)["domain_id"]]


OPEN_FINDING_STATUSES = ("OPEN", "REMEDIATION_PLANNED")


def open_findings_of_domain(domain_id):
    result = []
    for finding in ordered(store.quality_findings):
        rule = store.quality_rules.get(finding["quality_rule_id"])
        if rule is None or rule["domain_id"] != domain_id:
            continue
        if finding["status"] in OPEN_FINDING_STATUSES:
            result.append(finding)
    return result


def records_of(domain_id):
    return [r for r in ordered(store.master_records) if r["domain_id"] == domain_id]


def subscriptions_of(domain_id):
    return [s for s in ordered(store.consumer_subscriptions) if s["domain_id"] == domain_id]


def change_requests_of(domain_id):
    return [c for c in ordered(store.change_requests) if c["domain_id"] == domain_id]


def assignments_of(domain_id):
    return [a for a in ordered(store.steward_assignments) if a["domain_id"] == domain_id]


def assignment_covers_clock(assignment):
    clock = now()
    if assignment["effective_from"] > clock:
        return False
    if assignment["effective_to"] is not None and clock >= assignment["effective_to"]:
        return False
    return True


def has_active_assignment(domain_id, steward_id, roles):
    for assignment in assignments_of(domain_id):
        if assignment["status"] != "ACTIVE":
            continue
        if assignment["steward_id"] != steward_id:
            continue
        if assignment["steward_role"] not in roles:
            continue
        if assignment_covers_clock(assignment):
            return True
    return False
