"""Procedure cases: the room calendar, the clearance dimension and readiness."""

from flask import Blueprint, g

import constants
import db
import response
import util
import validate
from db import store
from errors import ApiError
from middleware import ALL, authenticate
from services import calc, cascades, query, serialize

bp = Blueprint("cases", __name__)

COMPUTED_CASE_FIELDS = [
    "procedure_minutes",
    "turnover_minutes",
    "scheduled_end_at",
    "block_end_at",
]


def _case(case_id):
    row = store.get("cases", case_id)
    if row is None:
        raise ApiError("ERR_CASE_NOT_FOUND")
    return row


def _refs(case):
    return (
        store.get("procedure_types", case["procedure_type_id"]),
        store.get("rooms", case["room_id"]),
        store.get("patients", case["patient_id"]),
        store.get("providers", case["primary_provider_id"]),
    )


def _lapsed(expires_on, clock_date):
    return expires_on is None or expires_on < clock_date


def _check_accreditation(room, provider):
    """Ladder rungs 42 and 43 — they bite at scheduling as well as at check-in."""
    if room is None or room["room_type"] not in constants.ACCREDITED_ROOM_TYPES:
        return
    clock_date = store.today()
    if _lapsed(room["accreditation_expires_on"], clock_date):
        raise ApiError("ERR_ROOM_ACCREDITATION_LAPSED")
    if provider is None or _lapsed(provider["ultrasound_accreditation_expires_on"], clock_date):
        raise ApiError("ERR_PROVIDER_ACCREDITATION_LAPSED")


# ------------------------------------------------------------------ case drafting
@bp.route("/procedure-cases", methods=["POST"])
@authenticate([constants.ROLE_SCHEDULER, constants.ROLE_UROLOGIST])
def draft_case():
    body = validate.get_body()
    validate.reject_computed(body, COMPUTED_CASE_FIELDS)
    patient_id = validate.str_field(body, "patient_id")
    procedure_type_id = validate.str_field(body, "procedure_type_id")
    room_id = validate.str_field(body, "room_id")
    primary_provider_id = validate.str_field(body, "primary_provider_id")
    scheduled_start_at = validate.instant_field(body, "scheduled_start_at")
    indication_note = validate.str_field(body, "indication_note", required=False, default=None)

    # Priority 10 — resolved in exactly the declared order.
    patient = store.get("patients", patient_id)
    if patient is None:
        raise ApiError("ERR_PATIENT_NOT_FOUND")
    ptype = store.get("procedure_types", procedure_type_id)
    if ptype is None:
        raise ApiError("ERR_PROCEDURE_TYPE_NOT_FOUND")
    room = store.get("rooms", room_id)
    if room is None:
        raise ApiError("ERR_ROOM_NOT_FOUND")
    provider = store.get("providers", primary_provider_id)
    if provider is None:
        raise ApiError("ERR_PROVIDER_NOT_FOUND")

    window = calc.compute_window(scheduled_start_at, ptype, room, patient)
    fields = {
        "patient_id": patient_id,
        "procedure_type_id": procedure_type_id,
        "room_id": room_id,
        "primary_provider_id": primary_provider_id,
        "schedule_status": "DRAFT",
        "clearance_status": "PENDING_PREP",
        "acknowledged_prep_codes": [],
        "clearance_block_reason": None,
        "scope_asset_id": None,
        "device_lot_id": None,
        "device_quantity": 0,
        "device_state": "NONE",
        "checked_in_at": None,
        "completed_at": None,
        "cancel_reason_code": None,
        "indication_note": indication_note,
    }
    fields.update(window)
    row = db.new_row("cases", fields)
    return response.created_response(serialize.dump("cases", row))


# ---------------------------------------------------------------- commit to calendar
@bp.route("/procedure-cases/<case_id>/schedule", methods=["POST"])
@authenticate([constants.ROLE_SCHEDULER])
def schedule_case(case_id):
    body = validate.get_body()
    expected_room_version = validate.int_field(body, "expected_room_version")
    case = _case(case_id)
    ptype, room, patient, provider = _refs(case)

    # Priority 22 — declared only from DRAFT.
    if case["schedule_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_CASE_TRANSITION")
    # Priority 30 — the room's stale-version guard.
    if room is None or expected_room_version != room["version"]:
        raise ApiError("ERR_STALE_ROOM_VERSION")
    # Priorities 42 and 43.
    _check_accreditation(room, provider)
    # Priority 54.
    if room["room_status"] != "OPEN":
        raise ApiError("ERR_ROOM_CLOSED")
    # Priority 55.
    if room["room_type"] != ptype["allowed_room_type"]:
        raise ApiError("ERR_ROOM_TYPE_MISMATCH")

    window = calc.compute_window(case["scheduled_start_at"], ptype, room, patient)
    # Priority 58 — the room's half-open interval.
    if calc.room_conflict(case["id"], room["id"], window["scheduled_start_at"], window["block_end_at"]):
        raise ApiError("ERR_ROOM_WINDOW_CONFLICT")
    # Priority 59 — the provider's closed buffered interval.
    if calc.provider_conflict(
        case["id"],
        case["primary_provider_id"],
        window["scheduled_start_at"],
        window["scheduled_end_at"],
    ):
        raise ApiError("ERR_PROVIDER_DOUBLE_BOOKED")

    calc.apply_window(case, window)
    case["schedule_status"] = "SCHEDULED"
    db.touch(case)
    db.touch(room)
    return response.object_response(serialize.dump("cases", case))


@bp.route("/procedure-cases/<case_id>/reschedule", methods=["POST"])
@authenticate([constants.ROLE_SCHEDULER])
def reschedule_case(case_id):
    body = validate.get_body()
    scheduled_start_at = validate.instant_field(body, "scheduled_start_at")
    room_id = validate.str_field(body, "room_id", required=False, default=None)
    case = _case(case_id)
    ptype, current_room, patient, provider = _refs(case)

    target_room = current_room
    if room_id is not None:
        target_room = store.get("rooms", room_id)
        if target_room is None:
            raise ApiError("ERR_ROOM_NOT_FOUND")

    # Priority 22 — rescheduling is a self-loop on SCHEDULED.
    if case["schedule_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_CASE_TRANSITION")
    # Priority 54.
    if target_room is None or target_room["room_status"] != "OPEN":
        raise ApiError("ERR_ROOM_CLOSED")
    # Priority 55.
    if target_room["room_type"] != ptype["allowed_room_type"]:
        raise ApiError("ERR_ROOM_TYPE_MISMATCH")

    window = calc.compute_window(scheduled_start_at, ptype, target_room, patient)
    if calc.room_conflict(
        case["id"], target_room["id"], window["scheduled_start_at"], window["block_end_at"]
    ):
        raise ApiError("ERR_ROOM_WINDOW_CONFLICT")
    if calc.provider_conflict(
        case["id"],
        case["primary_provider_id"],
        window["scheduled_start_at"],
        window["scheduled_end_at"],
    ):
        raise ApiError("ERR_PROVIDER_DOUBLE_BOOKED")

    vacated_room = current_room
    case["room_id"] = target_room["id"]
    calc.apply_window(case, window)
    db.touch(case)
    # One increment for the room vacated and one for the room taken; a single
    # increment when they are the same room.
    db.touch(target_room)
    if vacated_room is not None and vacated_room["id"] != target_room["id"]:
        db.touch(vacated_room)
    return response.object_response(serialize.dump("cases", case))


# --------------------------------------------------------- preparation acknowledgements
@bp.route("/procedure-cases/<case_id>/prep-acknowledgements", methods=["POST"])
@authenticate([constants.ROLE_SCHEDULER, constants.ROLE_PROCEDURE_NURSE])
def acknowledge_prep(case_id):
    body = validate.get_body()
    instruction_code = validate.enum_field(body, "instruction_code", constants.PREP_CODES)
    validate.str_field(body, "channel")
    case = _case(case_id)
    ptype, _room, _patient, _provider = _refs(case)

    # Priority 22 — both dimensions gate the acknowledgement.
    if case["schedule_status"] not in ("DRAFT", "SCHEDULED"):
        raise ApiError("ERR_INVALID_CASE_TRANSITION")
    if case["clearance_status"] not in ("PENDING_PREP", "PREP_ACKNOWLEDGED"):
        raise ApiError("ERR_INVALID_CASE_TRANSITION")
    # Priority 36 — instruction relevance.
    if instruction_code not in ptype["required_prep_codes"]:
        raise ApiError("ERR_PREP_CODE_NOT_REQUIRED")

    # A repeat acknowledgement of the same code is idempotent and is not an error.
    if instruction_code not in case["acknowledged_prep_codes"]:
        case["acknowledged_prep_codes"] = case["acknowledged_prep_codes"] + [instruction_code]
    case["clearance_status"] = "PREP_ACKNOWLEDGED"
    db.touch(case)
    return response.object_response(serialize.dump("cases", case))


# -------------------------------------------------------------- clearance review
CLEAR_FROM = ("PENDING_PREP", "PREP_ACKNOWLEDGED", "BLOCKED")
BLOCK_FROM = ("PENDING_PREP", "PREP_ACKNOWLEDGED", "CLEARED")
WAIVE_FROM = ("PENDING_PREP", "BLOCKED")


@bp.route("/procedure-cases/<case_id>/clearance-review", methods=["POST"])
@authenticate([constants.ROLE_PROCEDURE_NURSE, constants.ROLE_UROLOGIST])
def clearance_review(case_id):
    raw = validate.get_body()
    # Priority 4 — waiver authority, ahead of request shape and path resolution.
    if raw.get("decision") == "WAIVE" and g.user_role != constants.ROLE_UROLOGIST:
        raise ApiError("ERR_UNAUTHORIZED")

    decision = validate.enum_field(raw, "decision", constants.CLEARANCE_DECISIONS)
    block_reason_code = validate.str_field(raw, "block_reason_code", required=False, default=None)
    if decision == "BLOCK" and block_reason_code is None:
        raise validate.bad("Field 'block_reason_code' is required for a BLOCK decision.")

    case = _case(case_id)
    ptype, _room, _patient, _provider = _refs(case)

    # Priority 22.
    if case["schedule_status"] not in ("DRAFT", "SCHEDULED"):
        raise ApiError("ERR_INVALID_CASE_TRANSITION")
    declared = {"CLEAR": CLEAR_FROM, "BLOCK": BLOCK_FROM, "WAIVE": WAIVE_FROM}[decision]
    if case["clearance_status"] not in declared:
        raise ApiError("ERR_INVALID_CASE_TRANSITION")

    if decision == "CLEAR":
        # Priority 34 — vacuously satisfied by an empty required_prep_codes.
        for code in ptype["required_prep_codes"]:
            if code not in case["acknowledged_prep_codes"]:
                raise ApiError("ERR_PREP_INCOMPLETE")
        case["clearance_status"] = "CLEARED"
        case["clearance_block_reason"] = None
    elif decision == "BLOCK":
        case["clearance_status"] = "BLOCKED"
        case["clearance_block_reason"] = block_reason_code
    else:
        case["clearance_status"] = "PREP_WAIVED"
        case["clearance_block_reason"] = None
    db.touch(case)
    return response.object_response(serialize.dump("cases", case))


# ------------------------------------------------------------- scope assignment
@bp.route("/procedure-cases/<case_id>/scope-assignment", methods=["POST"])
@authenticate([constants.ROLE_PROCEDURE_NURSE])
def assign_scope(case_id):
    body = validate.get_body()
    scope_asset_id = validate.str_field(body, "scope_asset_id")
    expected_scope_asset_version = validate.int_field(body, "expected_scope_asset_version")
    case = _case(case_id)
    # Priority 10.
    scope = store.get("scopes", scope_asset_id)
    if scope is None:
        raise ApiError("ERR_SCOPE_NOT_FOUND")
    ptype, _room, _patient, _provider = _refs(case)

    # Priority 22 — the case's own state plus the type's scope obligation.
    if case["schedule_status"] not in ("DRAFT", "SCHEDULED"):
        raise ApiError("ERR_INVALID_CASE_TRANSITION")
    if not ptype["requires_scope"]:
        raise ApiError("ERR_INVALID_CASE_TRANSITION")
    # Priority 30.
    if expected_scope_asset_version != scope["version"]:
        raise ApiError("ERR_STALE_SCOPE_VERSION")
    # Priority 50 — the leak-test debt is checked before availability.
    if scope["leak_test_required"]:
        raise ApiError("ERR_SCOPE_LEAK_TEST_DUE")
    # Priority 51.
    if scope["status"] != "AVAILABLE":
        raise ApiError("ERR_SCOPE_NOT_AVAILABLE")

    case["scope_asset_id"] = scope["id"]
    scope["status"] = "IN_USE"
    db.touch(scope)
    db.touch(case)
    return response.object_response(serialize.dump("cases", case))


# ---------------------------------------------------------- device reservation
@bp.route("/procedure-cases/<case_id>/device-reservation", methods=["POST"])
@authenticate([constants.ROLE_PROCEDURE_NURSE, constants.ROLE_PRACTICE_ADMIN])
def reserve_devices(case_id):
    body = validate.get_body()
    consignment_lot_id = validate.str_field(body, "consignment_lot_id")
    quantity = validate.int_field(body, "quantity")
    expected_lot_version = validate.int_field(body, "expected_lot_version")
    case = _case(case_id)
    # Priority 10.
    lot = store.get("lots", consignment_lot_id)
    if lot is None:
        raise ApiError("ERR_LOT_NOT_FOUND")
    ptype, _room, _patient, _provider = _refs(case)

    # Priority 30.
    if expected_lot_version != lot["version"]:
        raise ApiError("ERR_STALE_LOT_VERSION")
    # Priority 64 — an expired lot that is also short reports the expiry.
    if lot["lot_expires_on"] < store.today():
        raise ApiError("ERR_LOT_EXPIRED")
    # Priority 66.
    if lot["sku"] != ptype["single_use_device_sku"]:
        raise ApiError("ERR_DEVICE_SKU_MISMATCH")
    # Priority 67.
    if case["device_state"] not in ("NONE", "RELEASED"):
        raise ApiError("ERR_DEVICE_ALREADY_RESERVED")
    # Priority 70.
    if quantity > lot["quantity_available"]:
        raise ApiError("ERR_CONSIGNMENT_INSUFFICIENT")

    case["device_lot_id"] = lot["id"]
    case["device_quantity"] = quantity
    case["device_state"] = "RESERVED"
    lot["quantity_available"] -= quantity
    lot["quantity_reserved"] += quantity
    calc.rebill(lot, "PROVISIONAL")
    db.touch(lot)
    db.touch(case)
    return response.object_response(serialize.dump("cases", case))


# ------------------------------------------------------------------- check-in
@bp.route("/procedure-cases/<case_id>/check-in", methods=["POST"])
@authenticate([constants.ROLE_PROCEDURE_NURSE])
def check_in(case_id):
    case = _case(case_id)
    # Priority 22 — a second check-in of an IN_ROOM case fails here.
    if case["schedule_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_CASE_TRANSITION")
    # Priorities 40, 42, 43, 48, 52, 60 and 68, in the fixed gate order.
    failures = calc.blocking_reason_codes(case)
    if failures:
        raise ApiError(constants.GATE_TO_ERROR[failures[0]])

    case["schedule_status"] = "IN_ROOM"
    case["checked_in_at"] = store.now()
    db.touch(case)
    return response.object_response(serialize.dump("cases", case))


# ------------------------------------------------------------------ completion
@bp.route("/procedure-cases/<case_id>/complete", methods=["POST"])
@authenticate([constants.ROLE_PROCEDURE_NURSE, constants.ROLE_UROLOGIST])
def complete_case(case_id):
    body = validate.get_body()
    validate.str_field(body, "outcome_note", required=False, default=None)
    case = _case(case_id)

    # Priority 22 — only IN_ROOM, and only with every container out of the room.
    if case["schedule_status"] != "IN_ROOM":
        raise ApiError("ERR_INVALID_CASE_TRANSITION")
    for specimen in store.all_rows("specimens"):
        if specimen["case_id"] == case["id"] and specimen["chain_status"] == "COLLECTED":
            raise ApiError("ERR_INVALID_CASE_TRANSITION")

    case["schedule_status"] = "COMPLETED"
    case["completed_at"] = store.now()
    # CASCADE A hops 2 and 3.
    cascades.satisfy_recall(case)
    # Scope soiling and device consumption.
    cascades.soil_scope(case)
    cascades.move_device_units(case, "CONSUMED", "FINAL")
    db.touch(case)
    return response.object_response(serialize.dump("cases", case))


# --------------------------------------------------------- cancellation, no-show
@bp.route("/procedure-cases/<case_id>/cancel", methods=["POST"])
@authenticate([constants.ROLE_SCHEDULER, constants.ROLE_UROLOGIST])
def cancel_case(case_id):
    body = validate.get_body()
    cancel_reason_code = validate.str_field(body, "cancel_reason_code")
    case = _case(case_id)
    if case["schedule_status"] not in ("DRAFT", "SCHEDULED"):
        raise ApiError("ERR_INVALID_CASE_TRANSITION")

    was_scheduled = case["schedule_status"] == "SCHEDULED"
    case["schedule_status"] = "CANCELLED"
    case["cancel_reason_code"] = cancel_reason_code
    cascades.release_scope(case)
    cascades.move_device_units(case, "RELEASED", "PROVISIONAL")
    cascades.cancel_open_antibiotic_orders(case)
    db.touch(case)
    # A cancelled draft touches no room.
    if was_scheduled:
        cascades.bump_room(store.get("rooms", case["room_id"]))
    return response.object_response(serialize.dump("cases", case))


@bp.route("/procedure-cases/<case_id>/no-show", methods=["POST"])
@authenticate([constants.ROLE_SCHEDULER])
def no_show_case(case_id):
    case = _case(case_id)
    if case["schedule_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_CASE_TRANSITION")
    # Priority 61 — strictly after the grace allowance.
    grace_end = util.add_minutes(case["scheduled_start_at"], constants.NO_SHOW_GRACE_MINUTES)
    if not store.now() > grace_end:
        raise ApiError("ERR_NO_SHOW_GRACE_NOT_ELAPSED")

    case["schedule_status"] = "NO_SHOW"
    case["cancel_reason_code"] = constants.NO_SHOW_CANCEL_REASON
    cascades.release_scope(case)
    # The package was opened: the units are wasted, not released.
    cascades.move_device_units(case, "WASTED", "PROVISIONAL")
    cascades.cancel_open_antibiotic_orders(case)
    db.touch(case)
    cascades.bump_room(store.get("rooms", case["room_id"]))
    return response.object_response(serialize.dump("cases", case))


# ----------------------------------------------------------------------- reads
@bp.route("/procedure-cases/<case_id>", methods=["GET"])
@authenticate(ALL)
def get_case(case_id):
    return response.object_response(serialize.dump("cases", _case(case_id)))


@bp.route("/procedure-cases/<case_id>/readiness", methods=["GET"])
@authenticate(ALL)
def case_readiness(case_id):
    case = _case(case_id)
    failures = calc.blocking_reason_codes(case)
    return response.object_response(
        {
            "case_id": case["id"],
            "schedule_status": case["schedule_status"],
            "clearance_status": case["clearance_status"],
            "blocking_reason_codes": failures,
            "first_blocking_reason_code": failures[0] if failures else None,
            "check_in_allowed": case["schedule_status"] == "SCHEDULED" and not failures,
        }
    )


@bp.route("/procedure-cases", methods=["GET"])
@authenticate(ALL)
def list_cases():
    return query.collection(
        "cases",
        {
            "patient_id": validate.query_str("patient_id"),
            "procedure_type_id": validate.query_str("procedure_type_id"),
            "room_id": validate.query_str("room_id"),
            "primary_provider_id": validate.query_str("primary_provider_id"),
            "scope_asset_id": validate.query_str("scope_asset_id"),
            "device_lot_id": validate.query_str("device_lot_id"),
            "schedule_status": validate.query_enum(
                "schedule_status", constants.CASE_SCHEDULE_STATUSES
            ),
            "clearance_status": validate.query_enum(
                "clearance_status", constants.CASE_CLEARANCE_STATUSES
            ),
        },
    )
