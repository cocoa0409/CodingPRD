"""In-memory data store.  Starts empty on every boot; nothing is ever seeded."""
from core import CLOCK, DEFAULT_CLOCK, fail, new_id, now

# entity name -> {id: record}
TABLES = {
    "Customer": {},
    "ComponentLot": {},
    "ProductSpec": {},
    "BlendRecipe": {},
    "RecipeComponent": {},
    "BlendTank": {},
    "BlendBatch": {},
    "ComponentDraw": {},
    "QCResult": {},
    "RetainSample": {},
    "ApprovalClaim": {},
    "PackageConfiguration": {},
    "PackagingLine": {},
    "PackagingRun": {},
    "Order": {},
    "OrderLine": {},
    "TakebackCollection": {},
    "SpecChangeRequest": {},
}

NOT_FOUND = {
    "Customer": "ERR_CUSTOMER_NOT_FOUND",
    "ComponentLot": "ERR_COMPONENT_LOT_NOT_FOUND",
    "ProductSpec": "ERR_PRODUCT_SPEC_NOT_FOUND",
    "BlendRecipe": "ERR_BLEND_RECIPE_NOT_FOUND",
    "BlendTank": "ERR_BLEND_TANK_NOT_FOUND",
    "BlendBatch": "ERR_BLEND_BATCH_NOT_FOUND",
    "RetainSample": "ERR_RETAIN_SAMPLE_NOT_FOUND",
    "ApprovalClaim": "ERR_APPROVAL_CLAIM_NOT_FOUND",
    "PackageConfiguration": "ERR_PACKAGE_CONFIGURATION_NOT_FOUND",
    "PackagingLine": "ERR_PACKAGING_LINE_NOT_FOUND",
    "PackagingRun": "ERR_PACKAGING_RUN_NOT_FOUND",
    "Order": "ERR_ORDER_NOT_FOUND",
    "TakebackCollection": "ERR_TAKEBACK_COLLECTION_NOT_FOUND",
    "SpecChangeRequest": "ERR_SPEC_CHANGE_REQUEST_NOT_FOUND",
}

_SEQ = {"n": 0}


def reset():
    for table in TABLES.values():
        table.clear()
    _SEQ["n"] = 0
    CLOCK.current = DEFAULT_CLOCK


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def insert(entity, record, versioned=True):
    """Attach identity/common fields and store the record."""
    stamp = now()
    full = {"id": new_id()}
    full.update(record)
    full["created_at"] = stamp
    if versioned:
        full["updated_at"] = stamp
        full["version"] = 1
    full["_seq"] = next_seq()
    full["_entity"] = entity
    TABLES[entity][full["id"]] = full
    return full


def touch(record):
    record["updated_at"] = now()
    record["version"] = record.get("version", 1) + 1
    return record


def get(entity, record_id):
    if not isinstance(record_id, str):
        return None
    return TABLES[entity].get(record_id)


def must_get(entity, record_id):
    record = get(entity, record_id)
    if record is None:
        fail(NOT_FOUND[entity])
    return record


def all_rows(entity):
    return sorted(TABLES[entity].values(), key=lambda r: r["_seq"])


def where(entity, **filters):
    rows = []
    for record in all_rows(entity):
        match = True
        for key, value in filters.items():
            if value is None:
                continue
            if record.get(key) != value:
                match = False
                break
        if match:
            rows.append(record)
    return rows


def find(entity, predicate):
    return [r for r in all_rows(entity) if predicate(r)]
