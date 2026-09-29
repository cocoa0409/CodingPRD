"""Authentication, RBAC, ownership and the producer privacy gate.

PRD 2.1 (participants and RBAC), 2.5 bands 1/2/6/7, 2.7 (privacy).
"""
from flask import request

from db import store
from errors import (data_access_denied, forbidden_role, not_resource_owner,
                    unauthenticated)

PRODUCER = "Producer"
STATE_OFFICIAL = "StateAnimalHealthOfficial"
TRACE_ANALYST = "FederalTraceAnalyst"
SUPPLIER_REP = "DeviceSupplierRep"
HARVEST_OPERATOR = "HarvestFacilityOperator"
PROGRAM_ADMIN = "ProgramAdmin"

ROLES = (PRODUCER, STATE_OFFICIAL, TRACE_ANALYST, SUPPLIER_REP,
         HARVEST_OPERATOR, PROGRAM_ADMIN)


def require_roles(*allowed):
    """Bands 1-2: header presence/validity, then endpoint role membership."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise unauthenticated()
    if role not in allowed:
        raise forbidden_role()
    return uid, role


# --- ownership (band 6) ---------------------------------------------------
def premises_producer_id(premises_id):
    p = store.premises.get(premises_id)
    return p["producer_id"] if p else None


def require_producer_owns_premises(uid, premises_id):
    if premises_producer_id(premises_id) != uid:
        raise not_resource_owner()


def require_owner(condition):
    if not condition:
        raise not_resource_owner()


def animal_producer_ids(animal):
    out = []
    for pid in (animal.get("birth_premises_id"), animal.get("current_premises_id")):
        if pid:
            owner = premises_producer_id(pid)
            if owner:
                out.append(owner)
    return out


def owning_producer(animal):
    """The producer an animal is regarded as belonging to: the operator of the
    premises it currently stands at, falling back to its birth premises while
    it is in transit."""
    pid = animal.get("current_premises_id") or animal.get("birth_premises_id")
    producer_id = premises_producer_id(pid)
    return store.producers.get(producer_id) if producer_id else None


# --- privacy gate (band 7, PRD 2.7) --------------------------------------
def can_read_animal(uid, role, animal):
    if role == PROGRAM_ADMIN:
        return True
    if role == PRODUCER:
        return uid in animal_producer_ids(animal)
    if role == HARVEST_OPERATOR:
        return animal.get("current_premises_id") == uid
    if role == STATE_OFFICIAL:
        producer = owning_producer(animal)
        if producer is None or producer.get("privacy_level") != "RESTRICTED":
            return True
        return animal.get("trace_status") in ("TRACE_HIT", "CLEARED")
    if role == TRACE_ANALYST:
        aid = animal["id"]
        for tr in store.trace_requests.values():
            if tr.get("index_animal_id") == aid:
                return True
            for hit in tr.get("hits") or []:
                if hit.get("animal_id") == aid:
                    return True
        return False
    return False


def require_can_read_animal(uid, role, animal):
    if not can_read_animal(uid, role, animal):
        raise data_access_denied()
