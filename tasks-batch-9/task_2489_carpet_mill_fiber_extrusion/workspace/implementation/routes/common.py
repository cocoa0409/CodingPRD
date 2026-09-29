"""Shared route helpers: lookups, uniqueness and list plumbing."""

from db import ordered, store
from errors import ApiError
from middleware import authenticate
from response import collection, obj
from serializers import dump, dump_all
from validators import filter_enum, filter_value, pagination

NOT_FOUND = {
    "accounts": "ERR_ACCOUNT_NOT_FOUND",
    "polymer_lots": "ERR_POLYMER_LOT_NOT_FOUND",
    "reclamation_batches": "ERR_RECLAMATION_BATCH_NOT_FOUND",
    "fiber_batches": "ERR_FIBER_BATCH_NOT_FOUND",
    "styles": "ERR_STYLE_NOT_FOUND",
    "machines": "ERR_MACHINE_NOT_FOUND",
    "vessels": "ERR_VESSEL_NOT_FOUND",
    "runs": "ERR_PRODUCTION_RUN_NOT_FOUND",
    "dye_lots": "ERR_DYE_LOT_NOT_FOUND",
    "roll_goods": "ERR_ROLL_GOOD_NOT_FOUND",
    "product_tests": "ERR_PRODUCT_TEST_NOT_FOUND",
    "certifications": "ERR_CERTIFICATION_NOT_FOUND",
    "cut_orders": "ERR_CUT_ORDER_NOT_FOUND",
    "cut_allocations": "ERR_CUT_ALLOCATION_NOT_FOUND",
}


def fetch(table_name, record_id):
    table = getattr(store, table_name)
    rec = table.get(record_id)
    if rec is None:
        raise ApiError(NOT_FOUND[table_name], "No such record: %s" % record_id)
    return rec


def unique(table_name, field, value):
    table = getattr(store, table_name)
    for rec in table.values():
        if rec.get(field) == value:
            raise ApiError(
                "ERR_DUPLICATE_CODE", "%s '%s' is already in use" % (field, value)
            )


def created(kind, rec):
    return obj(dump(kind, rec), 201)


def ok(kind, rec):
    return obj(dump(kind, rec))


def listing(kind, table_name, enum_filters=None, value_filters=None, predicate=None):
    """Apply declared filters, sort by created_at ASC and paginate."""
    limit, offset = pagination()
    wanted = {}
    for name, allowed in (enum_filters or {}).items():
        value = filter_enum(name, allowed)
        if value is not None:
            wanted[name] = value
    for name in value_filters or ():
        value = filter_value(name)
        if value is not None:
            wanted[name] = value

    records = []
    for rec in getattr(store, table_name).values():
        if any(rec.get(field) != value for field, value in wanted.items()):
            continue
        if predicate is not None and not predicate(rec):
            continue
        records.append(rec)

    records = ordered(records)
    total = len(records)
    page = records[offset : offset + limit]
    return collection(dump_all(kind, page), limit, offset, total)


__all__ = [
    "authenticate",
    "collection",
    "created",
    "dump",
    "dump_all",
    "fetch",
    "listing",
    "obj",
    "ok",
    "unique",
]
