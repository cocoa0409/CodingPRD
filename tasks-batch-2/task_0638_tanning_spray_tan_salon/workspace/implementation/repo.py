"""Repository helpers: audit-field stamping + entity lookup (PRD §2.4, §2.7)."""
from clock import clock
from db import store, new_id
import errors
from errors import err


def _stamp_create_audited(record):
    """id, created_at, updated_at, version for audit-tracked entities (§2.4)."""
    now = clock.now()
    record["id"] = new_id()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    record["_seq"] = store.next_seq()
    return record


def _stamp_create_writeonce(record):
    """id, created_at only for write-once records (§2.4)."""
    record["id"] = new_id()
    record["created_at"] = clock.now()
    record["_seq"] = store.next_seq()
    return record


def touch(record):
    """Refresh updated_at and bump version on a mutation (§2.6)."""
    record["updated_at"] = clock.now()
    record["version"] += 1


# ---- existence lookups (§2.7) — return record or raise the 404 family ----

def get_member(member_id):
    m = store.members.get(member_id)
    if m is None:
        raise err(errors.ERR_MEMBER_NOT_FOUND, "Member not found")
    return m


def get_plan(plan_id):
    p = store.membership_plans.get(plan_id)
    if p is None:
        raise err(errors.ERR_PLAN_NOT_FOUND, "MembershipPlan not found")
    return p


def get_equipment(equipment_id):
    e = store.equipment.get(equipment_id)
    if e is None:
        raise err(errors.ERR_EQUIPMENT_NOT_FOUND, "Equipment not found")
    return e


def get_room(room_id):
    r = store.spray_rooms.get(room_id)
    if r is None:
        raise err(errors.ERR_ROOM_NOT_FOUND, "SprayRoom not found")
    return r


def get_session(session_id):
    s = store.sessions.get(session_id)
    if s is None:
        raise err(errors.ERR_SESSION_NOT_FOUND, "Session not found")
    return s


def get_product(product_id):
    p = store.products.get(product_id)
    if p is None:
        raise err(errors.ERR_PRODUCT_NOT_FOUND, "Product not found")
    return p


def get_order(order_id):
    o = store.retail_orders.get(order_id)
    if o is None:
        raise err(errors.ERR_ORDER_NOT_FOUND, "RetailOrder not found")
    return o


def get_or_create_ledger():
    """Singleton SalonLedger (§2.10). Created lazily, never seeded at boot."""
    if store.salon_ledger is None:
        ledger = {
            "singleton_key": "SALON",
            "deferred_revenue_cents": 0,
            "collected_dues_cents": 0,
            "collected_retail_cents": 0,
        }
        _stamp_create_audited(ledger)
        store.salon_ledger = ledger
    return store.salon_ledger


def sorted_by_created(records):
    """created_at ascending, ties broken on monotonic insertion sequence."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
