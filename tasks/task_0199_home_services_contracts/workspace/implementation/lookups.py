"""Existence resolution (priority 4) and Customer-ownership checks (priority 3)."""
import db
from errors import err


def _get(coll, ident):
    rec = coll.get(ident)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found: %s" % ident)
    return rec


def plan(ident):
    return _get(db.service_plans, ident)


def customer(ident):
    return _get(db.customers, ident)


def site(ident):
    return _get(db.sites, ident)


def membership(ident):
    return _get(db.memberships, ident)


def equipment(ident):
    return _get(db.equipment, ident)


def technician(ident):
    return _get(db.technicians, ident)


def visit(ident):
    return _get(db.service_visits, ident)


def refrigerant_log(ident):
    return _get(db.refrigerant_logs, ident)


def part_usage(ident):
    return _get(db.part_usages, ident)


def claim(ident):
    return _get(db.warranty_claims, ident)


def offer(ident):
    return _get(db.renewal_offers, ident)


# ---------------------------------------------------------------------------
# Customer ownership (PRD §2.1, §2.9 priority 3): the Customer's X-User-ID must
# own the resource via its customer_id chain, else ERR_NOT_RESOURCE_OWNER.
# ---------------------------------------------------------------------------
def owner_customer_id_of_site(s):
    return s["customer_id"]


def owner_customer_id_of_membership(m):
    return m["customer_id"]


def owner_customer_id_of_visit(v):
    m = db.memberships.get(v["membership_id"])
    return m["customer_id"] if m else None


def owner_customer_id_of_offer(o):
    m = db.memberships.get(o["membership_id"])
    return m["customer_id"] if m else None


def owner_customer_id_of_claim(c):
    # claim -> equipment -> site -> customer
    e = db.equipment.get(c["equipment_id"])
    if not e:
        return None
    s = db.sites.get(e["site_id"])
    return s["customer_id"] if s else None


def require_customer_owns(user_id, owner_customer_id):
    if owner_customer_id != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER",
                  "Customer does not own the requested resource")
