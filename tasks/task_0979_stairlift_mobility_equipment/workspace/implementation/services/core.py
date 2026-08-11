"""Core helpers: timestamps, audit trail, common-field plumbing, rollup."""

from datetime import datetime, timezone

import db

COMMON_FIELD_ENTITIES = {
    "Customer", "HomeAssessment", "EquipmentUnit", "Quote",
    "FundingApplication", "Agreement", "InstallJob", "ServicePlan",
    "WarrantyClaim", "RemovalJob",
}


def stamp_new(entity):
    """Set id/created_at/updated_at/version on a new common-field entity."""
    entity["id"] = db.new_id()
    now = db.now_iso()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1


def stamp_lean(entity):
    """ProductModel and AuditEvent: only id and created_at."""
    entity["id"] = db.new_id()
    entity["created_at"] = db.now_iso()


def touch(entity):
    """Bump updated_at and version on mutation."""
    entity["updated_at"] = db.now_iso()
    entity["version"] = entity.get("version", 1) + 1


def audit(entity_kind, entity_id, event_kind, actor_role, payload=None):
    evt = {
        "entity_kind": entity_kind,
        "entity_id": entity_id,
        "event_kind": event_kind,
        "actor_role": actor_role,
        "payload": payload or {},
    }
    stamp_lean(evt)
    db.audit_events[evt["id"]] = evt
    return evt


def recompute_customer_outstanding(customer_id):
    """customer_outstanding_rollup: sum over ACTIVE/REMOVAL_REQUESTED agreements."""
    customer = db.customers.get(customer_id)
    if customer is None:
        return
    total = 0
    for ag in db.agreements.values():
        if ag["customer_id"] != customer_id:
            continue
        if ag["status"] in ("ACTIVE", "REMOVAL_REQUESTED"):
            total += (ag["list_price_cents"]
                      - ag.get("funding_applied_cents", 0)
                      - ag.get("paid_to_date_cents", 0))
    if total < 0:
        total = 0
    if customer.get("lifetime_outstanding_cents") != total:
        customer["lifetime_outstanding_cents"] = total
        touch(customer)


def parse_iso8601(value):
    """Parse an ISO 8601 datetime or date string into an aware UTC datetime."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        # try date-only
        try:
            dt = datetime.fromisoformat(v + "T00:00:00+00:00")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def serialize(entity):
    """Shallow copy for output; datetimes are stored as ISO strings already."""
    return dict(entity)
