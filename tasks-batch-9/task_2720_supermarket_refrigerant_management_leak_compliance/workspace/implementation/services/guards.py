"""Business-rule gates shared by service records and repair attempts."""
from decimal import Decimal

import constants
import db
import util
from errors import ApiError
from services import ledger

ZERO = Decimal("0")


def require_not_suspended(technician):
    """Validation priority 14."""
    if technician["status"] == "SUSPENDED":
        raise ApiError("ERR_TECHNICIAN_SUSPENDED")


def require_certification_current(technician, work_instant):
    """Validation priority 15: expiry must be on or after the work instant."""
    if technician["certification_expires_on"] < work_instant:
        raise ApiError("ERR_TECHNICIAN_CERT_EXPIRED")


def require_certification_class(technician, system):
    """Validation priority 16: UNIVERSAL satisfies every requirement."""
    required = system["required_certification_type"]
    held = technician["certification_type"]
    if held == "UNIVERSAL" or held == required:
        return
    raise ApiError("ERR_TECHNICIAN_CERT_TYPE_INVALID")


def equipment_lapsed_at(equipment, instant):
    horizon = util.add_days(
        equipment["last_verification_on"],
        constants.EQUIPMENT_VERIFICATION_WINDOW_DAYS,
    )
    return horizon < instant


def require_equipment_certified(equipment, work_instant=None):
    """Validation priority 17."""
    if equipment["status"] != "CERTIFIED":
        raise ApiError("ERR_RECOVERY_EQUIPMENT_NOT_CERTIFIED")
    if work_instant is not None and equipment_lapsed_at(equipment, work_instant):
        raise ApiError("ERR_RECOVERY_EQUIPMENT_NOT_CERTIFIED")


def require_equipment_pressure_class(equipment, refrigerant_type):
    """Validation priority 18."""
    if equipment["certified_for_pressure_class"] != refrigerant_type["pressure_class"]:
        raise ApiError("ERR_RECOVERY_EQUIPMENT_INCOMPATIBLE")


def require_same_store(resource, store_id):
    """Validation priority 23."""
    if resource["store_id"] != store_id:
        raise ApiError("ERR_CROSS_STORE_RESOURCE")


def governing_retrofit_plan(system_id):
    """The APPROVED (else IN_PROGRESS) retrofit plan governing a conversion."""
    candidates = [
        plan for plan in db.values("retrofit_plans")
        if plan["system_id"] == system_id
        and plan["plan_type"] == "RETROFIT"
        and plan["status"] in ("APPROVED", "IN_PROGRESS")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p["created_at"], p["_seq"]))
    approved = [plan for plan in candidates if plan["status"] == "APPROVED"]
    if approved:
        return approved[-1]
    return candidates[-1]


def handled_refrigerant_type_id(system, service_type):
    """The chemistry actually handled by a record (PRD 3.3)."""
    if service_type == "RETROFIT_CONVERSION":
        plan = governing_retrofit_plan(system["id"])
        if plan is not None and plan["target_refrigerant_type_id"]:
            return plan["target_refrigerant_type_id"]
    return system["refrigerant_type_id"]


def require_chemistry_match(cylinder, expected_type_id):
    """Validation priority 21."""
    if cylinder["refrigerant_type_id"] != expected_type_id:
        raise ApiError("ERR_REFRIGERANT_TYPE_MISMATCH")


def require_reclaimed_before_reuse(cylinder):
    """Validation priority 22: a shipped cylinder may never be charged."""
    if cylinder["disposition"] == "SENT_FOR_RECLAIM":
        raise ApiError("ERR_UNRECLAIMED_REFRIGERANT_REUSE")


def technician_intervals(technician_id, exclude_record_id=None):
    """Half-open [performed_at, occupies_until) labour intervals (PRD 3.3)."""
    intervals = []
    for record in db.values("service_records"):
        if record["technician_id"] != technician_id or record["voided"]:
            continue
        if exclude_record_id is not None and record["id"] == exclude_record_id:
            continue
        intervals.append((record["performed_at"], record["occupies_until"]))
    return intervals


def require_no_technician_conflict(technician_id, start, end):
    """Validation priority 32: half-open overlap; abutment is accepted."""
    for other_start, other_end in technician_intervals(technician_id):
        if start < other_end and other_start < end:
            raise ApiError("ERR_TECHNICIAN_SCHEDULE_CONFLICT")


def require_instant_free_for_technician(technician_id, instant):
    """The same rule applied to a repair attempt, which occupies an instant."""
    for other_start, other_end in technician_intervals(technician_id):
        if other_start <= instant < other_end:
            raise ApiError("ERR_TECHNICIAN_SCHEDULE_CONFLICT")


def require_no_equipment_conflict(equipment_id, start, end):
    """Validation priority 33: closed intervals -- abutment DOES conflict."""
    for record in db.values("service_records"):
        if record["recovery_equipment_id"] != equipment_id or record["voided"]:
            continue
        other_start = record["performed_at"]
        other_end = record["equipment_released_at"]
        if start <= other_end and other_start <= end:
            raise ApiError("ERR_EQUIPMENT_DECONTAMINATION_CONFLICT")


def check_mass_movements(system, cylinder, added, recovered, lost, record):
    """Validation priorities 39, 40, 41 and 42, in that order."""
    if cylinder is not None:
        if recovered > ZERO:
            projected = util.q1(cylinder["current_contents_lbs"] + recovered)
            if projected > cylinder["fill_limit_lbs"]:
                raise ApiError("ERR_CYLINDER_FILL_LIMIT_EXCEEDED")
        if added > ZERO:
            projected = util.q1(cylinder["current_contents_lbs"] - added)
            if projected < ZERO:
                raise ApiError("ERR_INSUFFICIENT_CYLINDER_CONTENTS")
    projected_charge = ledger.projected_charge(system, extra=record)
    if projected_charge > system["full_charge_lbs"]:
        raise ApiError("ERR_CHARGE_EXCEEDS_NAMEPLATE")
    if projected_charge < ZERO:
        raise ApiError("ERR_NEGATIVE_SYSTEM_CHARGE")
    return projected_charge


def require_unique(collection, field, value):
    """Validation priority 47: globally unique business identifiers."""
    for existing in db.values(collection):
        if existing.get(field) == value:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER")


def require_not_after_clock(instant):
    """Validation priority 29: a supplied instant may not exceed the clock."""
    if instant is not None and instant > db.now():
        raise ApiError("ERR_TIMESTAMP_AFTER_CLOCK")


def require_active_system(system):
    """Validation priority 10."""
    if system["operational_status"] == "RETIRED":
        raise ApiError("ERR_SYSTEM_RETIRED")


def require_event_not_terminal(event):
    """Validation priority 11."""
    if event["status"] in constants.TERMINAL_LEAK_EVENT_STATUSES:
        raise ApiError("ERR_LEAK_EVENT_TERMINAL")


def require_state(condition):
    """Validation priority 9."""
    if not condition:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
