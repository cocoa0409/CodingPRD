"""Shared route plumbing: row lookup, code uniqueness, response shortcuts and
the enum vocabularies the PRD declares."""
import core
import serial
from core import S, paginate, respond, sorted_rows
from errors import fail

SIZE_CLASSES = ("COMPACT", "MID", "TANDEM", "OVERSIZE")
HULL_TYPES = ("KAYAK", "CANOE")
RESIN_GRADES = ("HDPE_LINEAR", "HDPE_XL", "MDPE")
AIRFLOW_MODES = ("AMBIENT", "FORCED_AIR", "WATER_MIST")
WARRANTY_BASES = ("PRO_RATA_AGE", "FLAT_SCHEDULE")
ROLE_CODES = ("RESIN_TECH", "MOLDING_OPERATOR", "ASSEMBLY_TECH", "QUALITY_INSPECTOR")
CERTIFICATIONS = ("RESIN_BLENDING", "FIXTURE_ASSEMBLY", "WALL_GAUGE", "IMPACT_RIG")
MOLD_STATUSES = ("AVAILABLE", "IN_CYCLE", "MAINTENANCE", "RETIRED")
EQUIP_STATUSES = ("OPERATIONAL", "DOWN")
PERSON_STATUSES = ("ACTIVE", "SUSPENDED")
POSTURES = ("NORMAL", "RESTRICTED", "FROZEN")
LOT_STATUSES = ("AVAILABLE", "DEPLETED", "QUARANTINED", "EXPIRED")
CHARGE_STATUSES = ("RESERVED", "CONSUMED", "RELEASED")
RELEASED_REASONS = ("CYCLE_ABORTED", "LOT_QUARANTINED", "LOT_EXPIRED",
                    "ORDER_CANCELLED", "STATION_DOWN", "MOLD_SERVICE_DUE")
ORDER_STATUSES = ("DRAFT", "READY_TO_SCHEDULE", "BLOCKED_RESIN",
                  "BLOCKED_WAREHOUSE", "IN_PRODUCTION", "COMPLETE", "CANCELLED")
BLOCKED_REASONS = ("NO_QUALIFIED_RESIN_LOT", "WAREHOUSE_FROZEN")
CYCLE_STATUSES = ("SCHEDULED", "OVEN_RUNNING", "COOLING", "DEMOLDED", "ABORTED")
ABORT_REASONS = ("OPERATOR_ABORT", "LOT_QUARANTINED", "LOT_EXPIRED",
                 "ORDER_CANCELLED", "STATION_DOWN", "BAY_DOWN", "MOLD_SERVICE_DUE")
BUILD_STATUSES = ("DEMOLDED", "TRIMMED", "OUTFITTED", "SELLABLE", "REWORK", "SCRAPPED")
LOGISTICS_STATUSES = ("UNALLOCATED", "STORED", "LOADED", "IN_TRANSIT", "DELIVERED")
VERDICTS = ("PENDING", "PASS", "REWORK", "SCRAP")
COSMETIC_GRADES = ("A", "B", "C", "REJECT")
DEST_ZONES = ("Z1", "Z2", "Z3")
SHIPMENT_STATUSES = ("PLANNED", "LOADING", "SEALED", "IN_TRANSIT", "DELIVERED", "CANCELLED")
LINE_STATUSES = ("LOADED", "REMOVED")
CLAIM_TYPES = ("HULL_DEFORMATION", "HARDWARE", "COSMETIC")
CLAIM_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED", "WITHDRAWN", "VOIDED")
STORAGE_REVIEW_STATUSES = ("NOT_STARTED", "GUIDANCE_VERIFIED", "GUIDANCE_VIOLATED", "WAIVED")
DENIAL_REASONS = ("STORAGE_GUIDANCE_VIOLATED", "NOT_A_MANUFACTURING_DEFECT",
                  "TERM_EXPIRED", "APPROVAL_VOIDED")

NOT_FOUND = {
    "product_models": "ERR_PRODUCT_MODEL_NOT_FOUND",
    "molds": "ERR_MOLD_NOT_FOUND",
    "oven_stations": "ERR_OVEN_STATION_NOT_FOUND",
    "cooling_bays": "ERR_COOLING_BAY_NOT_FOUND",
    "technicians": "ERR_TECHNICIAN_NOT_FOUND",
    "customers": "ERR_CUSTOMER_NOT_FOUND",
    "warehouses": "ERR_WAREHOUSE_NOT_FOUND",
    "demand_buckets": "ERR_DEMAND_BUCKET_NOT_FOUND",
    "resin_lots": "ERR_RESIN_LOT_NOT_FOUND",
    "resin_charges": "ERR_RESOURCE_NOT_FOUND",
    "production_orders": "ERR_PRODUCTION_ORDER_NOT_FOUND",
    "molding_cycles": "ERR_MOLDING_CYCLE_NOT_FOUND",
    "finished_units": "ERR_FINISHED_UNIT_NOT_FOUND",
    "shipments": "ERR_SHIPMENT_NOT_FOUND",
    "shipment_lines": "ERR_RESOURCE_NOT_FOUND",
    "warranty_claims": "ERR_RESOURCE_NOT_FOUND",
}


def find(collection, row_id, error_id=None):
    """Existence check.  Returns the row or raises the entity-specific 404."""
    row = S.coll(collection).get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail(error_id or NOT_FOUND[collection],
             "No %s with id '%s'." % (collection[:-1], row_id))
    return row


def unique_code(collection, field, value, scope=None):
    for row in S.coll(collection).values():
        if row.get(field) != value:
            continue
        if scope is not None and not scope(row):
            continue
        fail("ERR_DUPLICATE_CODE", "%s '%s' is already registered." % (field, value))


def one(collection, row, status=200):
    return respond(serial.dump(collection, row), status)


def many(collection, items):
    page, meta = paginate(sorted_rows(items))
    return respond(serial.dump_list(collection, page), 200, "array", meta)


def filter_eq(items, field, value):
    if value is None:
        return items
    return [r for r in items if r.get(field) == value]
