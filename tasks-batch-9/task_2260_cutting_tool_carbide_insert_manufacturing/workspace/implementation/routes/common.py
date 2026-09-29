"""Shared helpers for the route modules."""

import db
import validation as v
from errors import ApiError
from middleware import ALL_ROLES, STAFF_ROLES, authenticate
from response import array_response, object_response
from services import derive, serialize

ANY_ROLE = ALL_ROLES

WORKPIECE_GROUPS = ["P", "M", "K", "N", "S", "H"]
APPLICATION_CLASSES = ["ROUGHING", "MEDIUM", "FINISHING"]
EDGE_PREPS = ["SHARP", "HONED", "CHAMFERED", "T_LAND"]
DEPOSITION_TYPES = ["PVD", "CVD"]
LAYER_MATERIALS = ["TiN", "TiAlN", "AlCrN", "Al2O3", "TiCN"]
CHAMBERS = ["CH1", "CH2", "CH3"]
CELLS = ["CELL_A", "CELL_B"]
TOOL_TYPES = ["INSERT", "SOLID_CARBIDE_ENDMILL", "SOLID_CARBIDE_DRILL"]
ORDER_CLASSES = ["CATALOG", "SPECIAL"]
COOLANTS = ["FLOOD", "THROUGH_TOOL", "DRY"]
RIGIDITIES = ["RIGID", "MEDIUM", "WEAK"]
TIERS = ["STANDARD", "PREFERRED", "STRATEGIC"]

GRADE_STATUSES = ["DRAFT", "PILOT", "QUALIFIED", "RETIRED"]
BATCH_STAGES = ["BLENDED", "PRESSED", "SINTERED", "CONSUMED"]
BATCH_QC = ["PENDING", "PASSED", "FAILED", "QUARANTINED"]
GEOMETRY_STATUSES = ["DRAFT", "RELEASED"]
COATING_RUN_STATUSES = ["SCHEDULED", "COMPLETED"]
WHEEL_STATUSES = ["AVAILABLE", "DRESSING", "EXPIRED"]
GRINDING_RUN_STATUSES = ["SCHEDULED", "COMPLETED", "VOIDED"]
RELEASE_STATUSES = ["DEVELOPMENT", "QUALIFICATION", "RELEASED", "RESTRICTED", "WITHDRAWN"]
SUPPLY_STATUSES = ["UNAVAILABLE", "MAKE_TO_ORDER", "STOCKED"]
DOSSIER_STATUSES = ["OPEN", "SUBMITTED", "APPROVED", "REJECTED"]
TRIAL_STATUSES = ["RUNNING", "COMPLETED", "INVALIDATED"]
VERDICTS = ["PASS", "FAIL"]
ACCOUNT_STATUSES = ["ACTIVE", "CREDIT_HOLD", "CLOSED"]
ORDER_STATUSES = [
    "DRAFT",
    "SUBMITTED",
    "ENGINEERING_REVIEW",
    "CONFIRMED",
    "SHIPPED",
    "ON_HOLD",
    "CANCELLED",
]
JOB_STATUSES = ["RECEIVED", "INSPECTED", "REFURBISHED", "RETURNED", "SCRAPPED"]

OPEN_ORDER_STATES = ("SUBMITTED", "ENGINEERING_REVIEW", "CONFIRMED", "ON_HOLD")


def listing(name, roles, filters):
    """Runs the standard list pipeline for a collection.

    `filters` maps query-parameter name to either a list of allowed enum
    values (validated) or None (free-form identifier match).
    """
    authenticate(roles)
    limit, offset = v.pagination()
    active = {}
    for key, allowed in filters.items():
        if allowed is None:
            value = v.query_value(key)
        else:
            value = v.query_enum(key, allowed)
        if value is not None:
            active[key] = value
    rows = derive.where(name, **active)
    return rows, limit, offset


def list_response(name, rows, limit, offset):
    total = len(rows)
    page = derive.paginate(rows, limit, offset)
    return array_response(serialize.many(name, page), limit, offset, total)


def read_one(name, row_id, roles):
    authenticate(roles)
    v.pagination()
    row = derive.must_exist(name, row_id)
    return object_response(serialize.SERIALIZERS[name](row))


def state_error(code, message):
    raise ApiError(code, message)
