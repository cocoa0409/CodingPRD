"""Shared route helpers: existence lookups in ladder order, list plumbing."""

from flask import request

import db
import response
import validators
from errors import ApiError
from services import serialize

# ------------------------------------------------- rungs 5..17 (existence)

NOT_FOUND = {
    "source_systems": "ERR_SOURCE_SYSTEM_NOT_FOUND",
    "ingest_batches": "ERR_INGEST_BATCH_NOT_FOUND",
    "profiles": "ERR_PROFILE_NOT_FOUND",
    "households": "ERR_HOUSEHOLD_NOT_FOUND",
    "match_rules": "ERR_MATCH_RULE_NOT_FOUND",
    "identity_links": "ERR_IDENTITY_LINK_NOT_FOUND",
    "consent_records": "ERR_CONSENT_RECORD_NOT_FOUND",
    "suppression_entries": "ERR_SUPPRESSION_ENTRY_NOT_FOUND",
    "segments": "ERR_SEGMENT_NOT_FOUND",
    "destinations": "ERR_DESTINATION_NOT_FOUND",
    "activations": "ERR_ACTIVATION_NOT_FOUND",
    "deletion_requests": "ERR_DELETION_REQUEST_NOT_FOUND",
    "vendor_deletion_tasks": "ERR_VENDOR_TASK_NOT_FOUND",
}


def fetch(collection, entity_id):
    return db.get_or_404(collection, entity_id, NOT_FOUND[collection])


def source(entity_id):
    return fetch("source_systems", entity_id)


def batch(entity_id):
    return fetch("ingest_batches", entity_id)


def profile(entity_id):
    return fetch("profiles", entity_id)


def household(entity_id):
    return fetch("households", entity_id)


def rule(entity_id):
    return fetch("match_rules", entity_id)


def link(entity_id):
    return fetch("identity_links", entity_id)


def consent(entity_id):
    return fetch("consent_records", entity_id)


def suppression(entity_id):
    return fetch("suppression_entries", entity_id)


def segment(entity_id):
    return fetch("segments", entity_id)


def destination(entity_id):
    return fetch("destinations", entity_id)


def activation(entity_id):
    return fetch("activations", entity_id)


def deletion_request(entity_id):
    return fetch("deletion_requests", entity_id)


def vendor_task(entity_id):
    return fetch("vendor_deletion_tasks", entity_id)


# ------------------------------------------------------- rungs 18..20 (OCC)

def check_version(entity, expected, error_id):
    if entity["version"] != expected:
        raise ApiError(error_id)


# ------------------------------------------------------------ rung 21 state

def require_status(entity, allowed):
    if entity["status"] not in allowed:
        raise ApiError("ERR_INVALID_STATE")


def invalid_state():
    return ApiError("ERR_INVALID_STATE")


# ---------------------------------------------------------------- responses

def one(collection, entity, status=200):
    return response.object_response(serialize.SERIALIZERS[collection](entity), status)


def listed(collection, items, limit, offset, total):
    payload = [serialize.SERIALIZERS[collection](entity) for entity in items]
    return response.list_response(payload, limit, offset, total)


BOOLEAN_TRUE = ("true", "True", "TRUE", "1")
BOOLEAN_FALSE = ("false", "False", "FALSE", "0")


def _matches(entity, field, raw):
    value = entity.get(field)
    if isinstance(value, bool):
        if raw in BOOLEAN_TRUE:
            return value is True
        if raw in BOOLEAN_FALSE:
            return value is False
        return False
    if value is None:
        return False
    return str(value) == raw


def collection_list(collection, filters, sort_key):
    """Filter by the declared query parameters, sort, then paginate."""
    limit, offset = validators.query_pagination()
    items = []
    for entity in db.all_of(collection):
        keep = True
        for name, field in filters.items():
            raw = request.args.get(name)
            if raw is None:
                continue
            if not _matches(entity, field, raw):
                keep = False
                break
        if keep:
            items.append(entity)
    items.sort(key=sort_key)
    page, total = db.paginate(items, limit, offset)
    return listed(collection, page, limit, offset, total)


def seq_sort(entity):
    return (entity["created_at"], entity["_seq"])


def seq_sort_desc(entity):
    return (-entity["created_at"].timestamp(), entity["_seq"])
