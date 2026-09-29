"""Shared route helpers: path resolution, ownership rungs, list serving."""
from db import db, ordered, public
from errors import fail
from middleware import paginate, role, user_id
from response import ok, ok_array, ok_list

NOT_FOUND = {
    "business_units": "ERR_BUSINESS_UNIT_NOT_FOUND",
    "tagging_policies": "ERR_TAGGING_POLICY_NOT_FOUND",
    "provisioning_requests": "ERR_PROVISIONING_REQUEST_NOT_FOUND",
    "cloud_resources": "ERR_CLOUD_RESOURCE_NOT_FOUND",
    "cost_records": "ERR_COST_RECORD_NOT_FOUND",
    "shared_cost_pools": "ERR_SHARED_COST_POOL_NOT_FOUND",
    "allocation_runs": "ERR_ALLOCATION_RUN_NOT_FOUND",
    "allocation_lines": "ERR_ALLOCATION_LINE_NOT_FOUND",
    "chargeback_invoices": "ERR_INVOICE_NOT_FOUND",
    "disputes": "ERR_DISPUTE_NOT_FOUND",
    "commitments": "ERR_COMMITMENT_NOT_FOUND",
    "remediation_tasks": "ERR_REMEDIATION_TASK_NOT_FOUND",
    "anomaly_alerts": "ERR_ANOMALY_ALERT_NOT_FOUND",
    "budgets": "ERR_BUDGET_NOT_FOUND",
    "unit_economics_drivers": "ERR_DRIVER_NOT_FOUND",
}


def lookup(collection_name, entity_id):
    """Resolve an identifier, raising this entity's own 404 when it is unknown."""
    collection = getattr(db, collection_name)
    entity = collection.get(entity_id)
    if entity is None:
        fail(NOT_FOUND[collection_name], "%s does not resolve to a known resource." % entity_id)
    return entity


def optional_ref(collection_name, entity_id):
    """Body reference existence (ladder rung 6); None passes through."""
    if entity_id is None:
        return None
    return lookup(collection_name, entity_id)


def require_bu_owner(business_unit_id):
    """Ladder rung 3."""
    if role() == "BusinessUnitOwner" and user_id() != business_unit_id:
        fail(
            "ERR_NOT_RESOURCE_OWNER",
            "The acting business unit owner does not own this resource.",
        )


def require_resource_owner(resource):
    """Ladder rung 4."""
    if role() == "ResourceOwner" and user_id() != resource.get("owner_user_id"):
        fail("ERR_NOT_RESOURCE_OWNER", "The acting user does not own this cloud resource.")


def serve(entity, status=200):
    return ok(public(entity), status)


def serve_many(entities, status=200):
    return ok_array([public(e) for e in entities], status)


def serve_list(entities, filters=None):
    """Apply conjunctive query filters, sort by created_at ASC and paginate."""
    from flask import request

    items = list(entities)
    for param, field in (filters or {}).items():
        raw = request.args.get(param)
        if raw is None or raw == "":
            continue
        items = [e for e in items if _matches(e.get(field), raw)]
    items = ordered(items)
    page, total, limit, offset = paginate(items)
    return ok_list([public(e) for e in page], total, limit, offset)


def _matches(value, raw):
    if value is None:
        return raw in ("null", "None")
    if isinstance(value, bool):
        return raw.lower() == ("true" if value else "false")
    return str(value) == raw
