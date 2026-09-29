"""Shared route helpers: enum vocabularies, existence resolution, pagination."""

import re

import envelope
from db import db
from errors import ApiError

# ------------------------------------------------------------- vocabularies ---
CLIMATE_ZONES = ["HOT_HUMID", "HOT_DRY", "MIXED", "MARINE", "COLD"]
STORE_FORMATS = ["SUPERCENTER", "NEIGHBORHOOD", "EXPRESS"]
SEASONS = ["SUMMER", "WINTER"]
ENERGY_POSTURES = ["NORMAL", "CONSTRAINED", "CURTAILED", "LOCKED"]
BMS_STATUSES = ["NOT_DEPLOYED", "COMMISSIONING", "ACTIVE", "DEGRADED"]
STANDARD_STATUSES = ["DRAFT", "PUBLISHED", "SUPERSEDED"]
RATE_FAMILIES = ["TOU_DEMAND", "FLAT_DEMAND"]
TARIFF_STATES = ["STABLE", "PENDING_SWITCH", "SWITCHED"]
DR_ENROLLMENT_STATES = ["ENROLLED", "SUSPENDED"]
VALIDATION_STATES = ["RECEIVED", "VALIDATED", "VARIANCE_FLAGGED", "DISPUTED", "ADJUSTED"]
EVENT_STATES = ["SCHEDULED", "NOTIFIED", "ACTIVE", "COMPLETED", "OPTED_OUT"]
SETTLEMENT_STATES = ["PENDING", "SETTLED", "REVERSED"]
CASE_TYPES = ["MEDIUM_TEMP", "LOW_TEMP", "ICE_CREAM"]
PRODUCT_CLASSES = ["DAIRY", "MEAT", "FROZEN", "PRODUCE"]
MONITORING_STATES = ["ARMED", "ALARM", "BYPASSED"]
EXCURSION_STATES = ["OPEN", "ACKNOWLEDGED", "ESCALATED", "DISPOSITION_REQUIRED", "CLOSED"]
DISPOSITIONS = ["RETAIN", "DISCARD"]
MANDATORY_DISPOSITIONS = ["NONE", "DISCARD"]
ZONES = ["SALES_FLOOR", "PARKING", "BACKROOM", "EXTERIOR_SIGN"]
OVERRIDE_TYPES = ["SCHEDULE_EXTEND", "DAYLIGHT_HARVEST_DISABLE", "OCCUPANCY_DISABLE"]
OVERRIDE_STATES = ["SCHEDULED", "ACTIVE", "EXPIRED", "REVOKED"]
REVOKE_SOURCES = ["USER", "SYSTEM_POSTURE"]
EQUIPMENT_CLASSES = ["REFRIGERATION", "HVAC", "LIGHTING"]
SEVERITIES = ["INFO", "MINOR", "MAJOR", "CRITICAL"]
FAULT_STATES = ["DETECTED", "TRIAGED", "SUPPRESSED", "RESOLVED"]
WORK_ORDER_STATES = ["OPEN", "SCHEDULED", "COMPLETED"]
WORK_ORDER_PRIORITIES = ["URGENT", "ROUTINE"]
MEASURE_TYPES = ["LED_RETROFIT", "CASE_DOORS", "ECM_MOTORS", "HVAC_RTU_REPLACEMENT",
                 "EMS_UPGRADE"]
RETROFIT_STATES = ["PROPOSED", "APPROVED", "REJECTED", "VERIFIED", "SHORTFALL_REVIEW"]
PRIORITY_BASES = ["SIMPLE_PAYBACK", "RISK_ADJUSTED"]
TRIAGE_OUTCOMES = ["WORK_ORDER", "SUPPRESS"]
APPROVAL_DECISIONS = ["APPROVE", "REJECT"]

TIME_OF_DAY_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$")


# --------------------------------------------------------------- existence ----

def _find(bucket, row_id, error_id):
    row = bucket.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def get_store(row_id):
    return _find(db.stores, row_id, "ERR_STORE_NOT_FOUND")


def get_standard(row_id):
    return _find(db.standards, row_id, "ERR_STANDARD_NOT_FOUND")


def get_account(row_id):
    return _find(db.accounts, row_id, "ERR_ACCOUNT_NOT_FOUND")


def get_bill(row_id):
    return _find(db.bills, row_id, "ERR_BILL_NOT_FOUND")


def get_event(row_id):
    return _find(db.dr_events, row_id, "ERR_DR_EVENT_NOT_FOUND")


def get_case(row_id):
    return _find(db.cases, row_id, "ERR_CASE_NOT_FOUND")


def get_excursion(row_id):
    return _find(db.excursions, row_id, "ERR_EXCURSION_NOT_FOUND")


def get_override(row_id):
    return _find(db.overrides, row_id, "ERR_OVERRIDE_NOT_FOUND")


def get_fault(row_id):
    return _find(db.faults, row_id, "ERR_FAULT_NOT_FOUND")


def get_work_order(row_id):
    return _find(db.work_orders, row_id, "ERR_WORK_ORDER_NOT_FOUND")


def get_retrofit(row_id):
    return _find(db.retrofits, row_id, "ERR_RETROFIT_NOT_FOUND")


# ------------------------------------------------------------- constraints ----

def require_bms_commissioned(store):
    """A store's operational surface opens only once its BMS is deployed."""
    if store["bms_status"] not in ("ACTIVE", "DEGRADED"):
        raise ApiError("ERR_BMS_NOT_COMMISSIONED")


# -------------------------------------------------------------- pagination ----

def paginate(items, limit, offset):
    return items[offset:offset + limit], len(items)


def list_response(items, serializer, limit, offset):
    page, total = paginate(items, limit, offset)
    return envelope.ok_list([serializer(row) for row in page], limit, offset, total)


def apply_eq(items, field, value):
    if value is None:
        return items
    return [row for row in items if row[field] == value]
