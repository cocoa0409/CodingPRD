"""Domain thresholds and constants from PRD prose.

Numeric constants extracted from PRD §2.3, §2.7, §3.5, §3.8, §3.9. Generic
NON_EXISTENT_UUID comes from the framework.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.7)
# ---------------------------------------------------------------------------
DEFAULT_CLOCK_NOW_ISO = "2026-01-01T00:00:00.000Z"


# ---------------------------------------------------------------------------
# Priority scoring (PRD §3.5)
# ---------------------------------------------------------------------------
CRITICALITY_WEIGHTS = {"LOW": 1, "MEDIUM": 2, "HIGH": 4}
TEMPLATE_PRIORITY_WEIGHTS = {"P1": 8, "P2": 4, "P3": 2, "P4": 1}
SOURCE_BONUSES = {"ALARM": 4, "PLAN_TRIGGER": 2, "PLAN_PERIODIC": 1, "AD_HOC": 1}

# Priority bucket floors (PRD §3.5: ">= 30 → P1; >= 20 ... < 30 → P2; >= 8 ... < 20 → P3; < 8 → P4")
PRIORITY_BUCKET_P1_FLOOR = 30
PRIORITY_BUCKET_P2_FLOOR = 20
PRIORITY_BUCKET_P3_FLOOR = 8


# ---------------------------------------------------------------------------
# SLA minutes per priority (PRD §3.5)
# ---------------------------------------------------------------------------
SLA_MINUTES = {"P1": 240, "P2": 480, "P3": 1440, "P4": 4320}


# ---------------------------------------------------------------------------
# Parts-cost calculation (PRD §3.8)
# ---------------------------------------------------------------------------
BULK_QTY_THRESHOLD = 10
BULK_DISCOUNT_FACTOR = 0.90


# ---------------------------------------------------------------------------
# Fault recurrence (PRD §3.9)
# ---------------------------------------------------------------------------
DEFAULT_LOOK_BACK_DAYS = 30
RECURRENCE_GAP_DAYS = 7


# ---------------------------------------------------------------------------
# Time-arithmetic helpers (PRD §2.7, §2.8)
# ---------------------------------------------------------------------------
SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400


# ---------------------------------------------------------------------------
# Allowed enum value lists (PRD §3.2–§3.8)
# ---------------------------------------------------------------------------
EQUIPMENT_CATEGORIES = ["PUMP", "COMPRESSOR", "HVAC", "CONVEYOR", "BOILER"]
EQUIPMENT_CRITICALITIES = ["LOW", "MEDIUM", "HIGH"]
TEMPLATE_SKILLS = ["MECHANICAL", "ELECTRICAL", "HYDRAULIC", "HVAC_CERT", "CONTROLS"]
TEMPLATE_PRIORITIES = ["P1", "P2", "P3", "P4"]
PLAN_KINDS = ["PERIODIC_TIME", "PERIODIC_USAGE", "TRIGGER_ALARM", "TRIGGER_THRESHOLD"]
THRESHOLD_OPS = ["GTE", "GT", "LTE", "LT"]
PLAN_STATUSES = ["DRAFT", "ACTIVE", "PAUSED", "RETIRED"]
TECHNICIAN_STATUSES = ["ACTIVE", "OFF_DUTY"]
WORK_ORDER_STATUSES = [
    "PENDING", "IN_PROGRESS", "PAUSED", "COMPLETED", "CLOSED", "CANCELLED",
]
WORK_ORDER_SOURCES = ["PLAN_PERIODIC", "PLAN_TRIGGER", "ALARM", "AD_HOC"]
PAUSE_REASONS = ["WAIT_PARTS", "WAIT_VENDOR", "WAIT_INFO"]
REQUISITION_STATUSES = ["RESERVED", "ISSUED", "RETURNED", "CANCELLED"]
ALARM_SEVERITIES = ["INFO", "WARN", "CRITICAL"]
AUDIT_ACTIONS = [
    "WORK_ORDER_STATE_CHANGE", "PARTS_ISSUED", "PARTS_RETURNED",
    "TECHNICIAN_ASSIGNED",
]


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "DEFAULT_CLOCK_NOW_ISO",
    "CRITICALITY_WEIGHTS",
    "TEMPLATE_PRIORITY_WEIGHTS",
    "SOURCE_BONUSES",
    "PRIORITY_BUCKET_P1_FLOOR",
    "PRIORITY_BUCKET_P2_FLOOR",
    "PRIORITY_BUCKET_P3_FLOOR",
    "SLA_MINUTES",
    "BULK_QTY_THRESHOLD",
    "BULK_DISCOUNT_FACTOR",
    "DEFAULT_LOOK_BACK_DAYS",
    "RECURRENCE_GAP_DAYS",
    "SECONDS_PER_MINUTE",
    "SECONDS_PER_HOUR",
    "SECONDS_PER_DAY",
    "EQUIPMENT_CATEGORIES",
    "EQUIPMENT_CRITICALITIES",
    "TEMPLATE_SKILLS",
    "TEMPLATE_PRIORITIES",
    "PLAN_KINDS",
    "THRESHOLD_OPS",
    "PLAN_STATUSES",
    "TECHNICIAN_STATUSES",
    "WORK_ORDER_STATUSES",
    "WORK_ORDER_SOURCES",
    "PAUSE_REASONS",
    "REQUISITION_STATUSES",
    "ALARM_SEVERITIES",
    "AUDIT_ACTIONS",
]
