"""Record lifecycle: creation with common fields, mutation (version bump),
serialization with computed fields, existence checks, ownership chains."""
from db import db, next_seq
from errors import raise_error
from util import CLOCK, new_id

def create_record(collection, fields, common=True):
    """Mint a record. common=True adds id/created_at/updated_at/version
    (PRD 2.5); WarrantyRegistration passes common=False (id + created_at)."""
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = CLOCK.now_ts()
    if common:
        rec["updated_at"] = CLOCK.now_ts()
        rec["version"] = 1
    rec["_seq"] = next_seq()
    db[collection][rec["id"]] = rec
    return rec


def mutate(rec):
    """Any property change refreshes updated_at and increments version
    (PRD 2.5 — including recomputation of derived figures)."""
    rec["updated_at"] = CLOCK.now_ts()
    rec["version"] = rec.get("version", 1) + 1


def get_or_404(collection, rid, spec):
    rec = db[collection].get(rid)
    if rec is None:
        raise_error(spec, f"{collection} id {rid} does not exist")
    return rec


def available_bundles(lot) -> int:
    """Read-only computed: on_hand - reserved, floored at 0 (PRD 2.7)."""
    return max(0, lot["on_hand_bundles"] - lot["reserved_bundles"])


def credit_available(account) -> int:
    """with_pending_deliveries variant (PRD 2.8): limit - open - pending - lien."""
    return (account["credit_limit_cents"]
            - account["open_balance_cents"]
            - account["pending_delivery_hold_cents"]
            - account["lien_hold_cents"])


def credit_available_invoiced_only(account) -> int:
    """invoiced_only variant for the statement endpoint (PRD 2.8)."""
    return (account["credit_limit_cents"]
            - account["open_balance_cents"]
            - account["lien_hold_cents"])


def remaining_pool(event) -> int:
    return event["allocation_pool_bundles"] - event["allocated_bundles"]


def pub(collection, rec):
    """Serialize: strip private fields, inject read-only computed fields."""
    if rec is None:
        return None
    out = {k: v for k, v in rec.items() if not k.startswith("_")}
    if collection == "inventory_lots":
        out["available_bundles"] = available_bundles(rec)
    elif collection == "contractor_accounts":
        out["credit_available_cents"] = credit_available(rec)
    elif collection == "surge_events":
        out["remaining_pool_bundles"] = remaining_pool(rec)
    return out


def contractor_of(collection, rec):
    """Resolve the owning ContractorAccount id for a record, or None when the
    entity is not contractor-owned (branches, products, lots, slots, events)."""
    if rec is None:
        return None
    if collection == "contractor_accounts":
        return rec["id"]
    if collection == "job_accounts":
        return rec["contractor_account_id"]
    if collection == "allocations":
        return rec["contractor_account_id"]
    if collection == "takeoffs":
        job = db["job_accounts"].get(rec["job_account_id"])
        return job["contractor_account_id"] if job else None
    if collection == "orders":
        job = db["job_accounts"].get(rec["job_account_id"])
        return job["contractor_account_id"] if job else None
    if collection == "order_lines":
        order = db["orders"].get(rec["order_id"])
        return contractor_of("orders", order)
    if collection == "deliveries":
        order = db["orders"].get(rec["order_id"])
        return contractor_of("orders", order)
    if collection == "returns":
        order = db["orders"].get(rec["order_id"])
        return contractor_of("orders", order)
    if collection == "damage_claims":
        delivery = db["deliveries"].get(rec["delivery_id"])
        return contractor_of("deliveries", delivery)
    if collection == "warranty_registrations":
        order = db["orders"].get(rec["order_id"])
        return contractor_of("orders", order)
    return None
