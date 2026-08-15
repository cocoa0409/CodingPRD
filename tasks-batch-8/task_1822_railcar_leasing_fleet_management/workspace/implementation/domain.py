"""Cross-entity domain helpers: serializers, balance ledger with
auto-suspension, lazy lease expiry, compliance posture, tariff lookups."""
from datetime import timedelta

from errors import ApiError
from store import db, new_entity, next_seq, today, touch

COMMON_OMIT = {"_created_seq", "_last_return_seq"}


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def serialize(ent):
    return {k: v for k, v in ent.items() if k not in COMMON_OMIT and not k.startswith("_")}


def serialize_lessee(l):
    return serialize(l)


def serialize_railcar(c):
    out = serialize(c)
    out["car_age_years"] = car_age(c)
    return out


def serialize_lease(lease):
    lazy_expire_lease(lease)
    return serialize(lease)


def serialize_tariff(t):
    return serialize(t)


def serialize_assignment(a):
    return serialize(a)


def serialize_report(r):
    return serialize(r)


def serialize_statement(s):
    return serialize(s)


def serialize_repair(r):
    return serialize(r)


def serialize_cleaning(c):
    return serialize(c)


def serialize_assessment(a):
    return serialize(a)


def serialize_directive(d):
    return serialize(d)


def serialize_retrofit(r):
    return serialize(r)


def serialize_retirement(r):
    return serialize(r)


def serialize_pool(p):
    recompute_pool(p)
    return serialize(p)


def serialize_commitment(c):
    return serialize(c)


# ---------------------------------------------------------------------------
# Derived attributes
# ---------------------------------------------------------------------------
def car_age(car):
    return db.clock_dt.year - car["built_year"]


def recompute_pool(pool):
    pool["available_cents"] = (
        pool["opening_balance_cents"]
        + pool["replenishment_cents"]
        - pool["committed_cents"]
        - pool["delivered_spend_cents"]
    )


# ---------------------------------------------------------------------------
# Lessee balance ledger + auto-suspension (PRD 3.1)
# ---------------------------------------------------------------------------
def balance_add(lessee, delta_cents):
    """Mutate outstanding_balance_cents and re-evaluate the credit rule."""
    lessee["outstanding_balance_cents"] += delta_cents
    if (
        lessee["status"] == "ACTIVE"
        and lessee["outstanding_balance_cents"] > lessee["credit_limit_cents"]
    ):
        lessee["status"] = "SUSPENDED"
    touch(lessee)


# ---------------------------------------------------------------------------
# Lease lazy expiry (PRD 3.3): ACTIVE -> EXPIRED when current date > end_date,
# evaluated whenever the lease is read or mutated.
# ---------------------------------------------------------------------------
def lazy_expire_lease(lease):
    if lease["status"] == "ACTIVE" and today() > lease["end_date"]:
        lease["status"] = "EXPIRED"
        touch(lease)


def load_lease(lease_id, error_id="ERR_LEASE_NOT_FOUND"):
    lease = db.leases.get(lease_id)
    if lease is None:
        raise ApiError(error_id, 404, f"Lease agreement {lease_id} not found")
    lazy_expire_lease(lease)
    return lease


# ---------------------------------------------------------------------------
# Compliance posture (PRD 3.11): NON_COMPLIANT if any EFFECTIVE directive
# covering the car type lacks a CERTIFIED retrofit for the car; else
# RETROFIT_DUE if any ANNOUNCED covering directive lacks one; else COMPLIANT.
# ---------------------------------------------------------------------------
def _covering_directives(car, status):
    return [
        d
        for d in db.directives.values()
        if d["status"] == status and car["car_type"] in d["applies_to_car_types"]
    ]


def _has_certified_retrofit(car_id, directive_id):
    return any(
        r["railcar_id"] == car_id
        and r["directive_id"] == directive_id
        and r["status"] == "CERTIFIED"
        for r in db.retrofits.values()
    )


def recompute_posture(car, bump=True):
    posture = "COMPLIANT"
    for d in _covering_directives(car, "EFFECTIVE"):
        if not _has_certified_retrofit(car["id"], d["id"]):
            posture = "NON_COMPLIANT"
            break
    if posture == "COMPLIANT":
        for d in _covering_directives(car, "ANNOUNCED"):
            if not _has_certified_retrofit(car["id"], d["id"]):
                posture = "RETROFIT_DUE"
                break
    if car["compliance_posture"] != posture:
        car["compliance_posture"] = posture
        if bump:
            touch(car)
    return posture


def open_directives_for_car(car):
    """EFFECTIVE directives covering the car type without CERTIFIED retrofit."""
    return [
        d
        for d in _covering_directives(car, "EFFECTIVE")
        if not _has_certified_retrofit(car["id"], d["id"])
    ]


# ---------------------------------------------------------------------------
# Tariffs (PRD 3.13): half-open [effective_from, effective_to)
# ---------------------------------------------------------------------------
def tariff_at(car_type, rate_kind, on_date):
    for t in db.tariffs.values():
        if (
            t["car_type"] == car_type
            and t["rate_kind"] == rate_kind
            and t["effective_from"] <= on_date < t["effective_to"]
        ):
            return t
    return None


def tariff_overlaps(car_type, rate_kind, frm, to, exclude_id=None):
    for t in db.tariffs.values():
        if t["id"] == exclude_id:
            continue
        if t["car_type"] != car_type or t["rate_kind"] != rate_kind:
            continue
        # half-open overlap: adjacency allowed
        if frm < t["effective_to"] and t["effective_from"] < to:
            return True
    return False


# ---------------------------------------------------------------------------
# Ownership resolution for LesseeRep (entity-backed identity; PRD 2.1)
# ---------------------------------------------------------------------------
def lessee_id_of_assignment(assignment):
    lease = db.leases.get(assignment["lease_id"])
    return lease["lessee_id"] if lease else None


def check_lessee_ownership(lessee_id):
    """LesseeRep's X-User-ID must equal the owning lessee id (priority 3)."""
    from flask import g

    if g.user_role == "LesseeRep" and g.user_id != lessee_id:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE", 403,
            "LesseeRep may only act on resources owned by its own lessee",
        )


# ---------------------------------------------------------------------------
# Misc lookups
# ---------------------------------------------------------------------------
def assignments_of_car(railcar_id):
    return [a for a in db.assignments.values() if a["railcar_id"] == railcar_id]


def most_recent_returned_assignment(railcar_id):
    cands = [
        a
        for a in db.assignments.values()
        if a["railcar_id"] == railcar_id and a["status"] in ("RETURNED", "SETTLED")
    ]
    if not cands:
        return None
    return max(
        cands,
        key=lambda a: (a["actual_off_lease_date"] or a["scheduled_end"], a["_created_seq"]),
    )
