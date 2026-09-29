"""Kitchen labour, sharps control and contraband (PRD 3.6)."""
from flask import Blueprint

from core import (
    ApiError, Field, ROLE_COMPLIANCE_AUDITOR, ROLE_CORRECTIONAL_OFFICER,
    ROLE_FOOD_SERVICE_SUPERVISOR, all_rows, authorize, base_row, body_json,
    filter_eq, insert, listing, now_logical, parse_instant, present, public,
    respond_object, touch, validate_fields,
)
from calc import (
    derive_posture, facility_incidents, facility_issuances, is_sharp,
    refresh_worker_strikes, rows_where, unaccounted_any_present,
)
from ops import (
    discard_batches_for_lockdown, need_facility, need_incident, need_inmate,
    need_issuance, need_worker, not_terminal, raise_system_incident,
    require_state, sync_facility, unassign_line_workers,
)

bp = Blueprint("security", __name__, url_prefix="/cfs")

WORK_AREAS = ("BAKERY", "COOK_CHILL", "SERVING_LINE", "SANITATION")
TOOL_CLASSES = ("SHARP_KNIFE", "MEAT_SAW", "SCISSORS", "NON_SHARP")
ITEM_CLASSES = ("SHARP", "YEAST_ALCOHOL", "FOOD_DIVERSION", "COMMISSARY_ITEM")
SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
SANCTION_TYPES = ("WARNING", "WORK_SUSPENSION", "WORK_BAR", "REFERRAL")
DISPOSITIONS = ("SANCTIONED", "CLEARED")
STRIKE_BAR_THRESHOLD = 2

SECURITY_READ_ROLES = (ROLE_FOOD_SERVICE_SUPERVISOR, ROLE_CORRECTIONAL_OFFICER,
                       ROLE_COMPLIANCE_AUDITOR)


def _has_open_hold(worker_id):
    return any(i["status"] == "OPEN" and i.get("inmate_worker_id") == worker_id
               for i in all_rows("contraband_incidents"))


# --------------------------------------------------------------------------
# Kitchen workers
# --------------------------------------------------------------------------
@bp.route("/inmate-workers", methods=["POST"])
def create_worker():
    authorize(ROLE_FOOD_SERVICE_SUPERVISOR)
    body = body_json()
    validate_fields(body, [
        Field("inmate_id", "string", required=True),
        Field("facility_id", "string", required=True),
        Field("medical_clearance_expires_at", "datetime", required=True),
        Field("sharps_eligible", "boolean"),
    ])
    inmate = need_inmate(body["inmate_id"])
    facility = need_facility(body["facility_id"])
    if inmate["facility_id"] != facility["id"]:
        raise ApiError("ERR_FACILITY_MISMATCH",
                       "The worker's facility must be the inmate's own facility.")
    if rows_where("inmate_workers", inmate_id=inmate["id"]):
        raise ApiError("ERR_DUPLICATE_RESOURCE",
                       "That inmate already holds a kitchen worker record.")
    row = base_row()
    row.update({
        "inmate_id": inmate["id"],
        "facility_id": facility["id"],
        "clearance_status": "CLEARED",
        "assignment_status": "UNASSIGNED",
        "work_area": None,
        "medical_clearance_expires_at": parse_instant(body["medical_clearance_expires_at"]),
        "sharps_eligible": body["sharps_eligible"] if present(body, "sharps_eligible") else False,
        "contraband_strike_count": 0,
    })
    insert("inmate_workers", row)
    return respond_object(public(row), 201)


@bp.route("/inmate-workers/<row_id>", methods=["GET"])
def read_worker(row_id):
    authorize(*SECURITY_READ_ROLES)
    return respond_object(public(need_worker(row_id)), 200)


@bp.route("/inmate-workers", methods=["GET"])
def list_workers():
    authorize(*SECURITY_READ_ROLES)
    rows = filter_eq(all_rows("inmate_workers"), "inmate_id")
    rows = filter_eq(rows, "facility_id")
    rows = filter_eq(rows, "clearance_status")
    rows = filter_eq(rows, "assignment_status")
    return listing(rows)


@bp.route("/inmate-workers/<row_id>/assign", methods=["POST"])
def assign_worker(row_id):
    authorize(ROLE_FOOD_SERVICE_SUPERVISOR)
    body = body_json()
    validate_fields(body, [Field("work_area", "string", required=True, enum=WORK_AREAS)])
    worker = need_worker(row_id)
    not_terminal(worker, "clearance_status", ("BARRED",))
    require_state(worker, "assignment_status", ("UNASSIGNED",))
    facility = need_facility(worker["facility_id"])
    if facility["kitchen_posture"] != "OPEN":
        raise ApiError("ERR_KITCHEN_POSTURE_BLOCKED")
    if worker["clearance_status"] != "CLEARED":
        raise ApiError("ERR_WORKER_NOT_CLEARED")
    if worker["medical_clearance_expires_at"] <= now_logical():
        raise ApiError("ERR_MEDICAL_CLEARANCE_EXPIRED")
    if _has_open_hold(worker["id"]):
        raise ApiError("ERR_OPEN_CONTRABAND_HOLD")
    worker["assignment_status"] = "ASSIGNED"
    worker["work_area"] = body["work_area"]
    touch(worker)
    return respond_object(public(worker), 200)


# --------------------------------------------------------------------------
# Tool issuances
# --------------------------------------------------------------------------
@bp.route("/tool-issuances", methods=["POST"])
def create_issuance():
    actor = authorize(ROLE_FOOD_SERVICE_SUPERVISOR)
    body = body_json()
    validate_fields(body, [
        Field("facility_id", "string", required=True),
        Field("issued_to_worker_id", "string", required=True),
        Field("tool_class", "string", required=True, enum=TOOL_CLASSES),
        Field("tool_serial", "string", required=True),
        Field("shadow_board_slot", "integer", required=True, min_inclusive=1),
    ])
    facility = need_facility(body["facility_id"])
    worker = need_worker(body["issued_to_worker_id"])
    if worker["facility_id"] != facility["id"]:
        raise ApiError("ERR_FACILITY_MISMATCH",
                       "The tool's facility must be the worker's own facility.")
    for existing in facility_issuances(facility["id"]):
        if existing["status"] in ("ISSUED", "UNACCOUNTED") \
                and existing["tool_serial"] == body["tool_serial"]:
            raise ApiError("ERR_DUPLICATE_RESOURCE", "That tool serial is already out.")
    for existing in facility_issuances(facility["id"]):
        if existing["status"] == "ISSUED" \
                and int(existing["shadow_board_slot"]) == int(body["shadow_board_slot"]):
            raise ApiError("ERR_DUPLICATE_RESOURCE", "That shadow board slot is already out.")

    # The posture gate applies here in its carved-out form: the unaccounted-tool
    # clauses are reported one priority later, as ERR_SHARPS_DISCREPANCY_OPEN.
    if derive_posture(facility, skip_unaccounted_clauses=True) != "OPEN":
        raise ApiError("ERR_KITCHEN_POSTURE_BLOCKED")
    if unaccounted_any_present(facility["id"]):
        raise ApiError("ERR_SHARPS_DISCREPANCY_OPEN")
    sharp = is_sharp(body["tool_class"])
    if sharp and not worker["sharps_eligible"]:
        raise ApiError("ERR_WORKER_NOT_SHARPS_ELIGIBLE")
    if worker["clearance_status"] != "CLEARED":
        raise ApiError("ERR_WORKER_NOT_CLEARED")
    if worker["medical_clearance_expires_at"] <= now_logical():
        raise ApiError("ERR_MEDICAL_CLEARANCE_EXPIRED")
    if _has_open_hold(worker["id"]):
        raise ApiError("ERR_OPEN_CONTRABAND_HOLD")

    row = base_row()
    row.update({
        "facility_id": facility["id"],
        "issued_to_worker_id": worker["id"],
        "tool_class": body["tool_class"],
        "tool_serial": body["tool_serial"],
        "shadow_board_slot": int(body["shadow_board_slot"]),
        "status": "ISSUED",
        "issued_by_user_id": actor.user_id,
        "issued_at": now_logical(),
        "returned_at": None,
        "return_certified_by_user_id": None,
        "unaccounted_at": None,
        "recovered": False,
    })
    insert("tool_issuances", row)
    if sharp:
        facility["sharps_on_board_count"] = int(facility["sharps_on_board_count"]) - 1
    sync_facility(facility, force=True)
    return respond_object(public(row), 201)


@bp.route("/tool-issuances/<row_id>", methods=["GET"])
def read_issuance(row_id):
    authorize(*SECURITY_READ_ROLES)
    return respond_object(public(need_issuance(row_id)), 200)


@bp.route("/tool-issuances", methods=["GET"])
def list_issuances():
    authorize(*SECURITY_READ_ROLES)
    rows = filter_eq(all_rows("tool_issuances"), "facility_id")
    rows = filter_eq(rows, "issued_to_worker_id")
    rows = filter_eq(rows, "status")
    rows = filter_eq(rows, "tool_class")
    return listing(rows)


@bp.route("/tool-issuances/<row_id>/return", methods=["POST"])
def return_issuance(row_id):
    actor = authorize(ROLE_CORRECTIONAL_OFFICER)
    body = body_json()
    validate_fields(body, [Field("returned_count_verified", "integer", required=True)])
    if int(body["returned_count_verified"]) != 1:
        raise ApiError("ERR_INVALID_REQUEST",
                       "returned_count_verified must be exactly 1.")
    issuance = need_issuance(row_id)
    not_terminal(issuance, "status", ("RETURNED",))
    if actor.user_id == issuance.get("issued_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    facility = need_facility(issuance["facility_id"])
    was_unaccounted = issuance["status"] == "UNACCOUNTED"
    issuance["status"] = "RETURNED"
    issuance["returned_at"] = now_logical()
    issuance["return_certified_by_user_id"] = actor.user_id
    if was_unaccounted:
        issuance["recovered"] = True
    touch(issuance)
    if is_sharp(issuance["tool_class"]):
        facility["sharps_on_board_count"] = int(facility["sharps_on_board_count"]) + 1
    # Discarded batches and cleared work details are deliberately NOT restored.
    sync_facility(facility, force=True)
    return respond_object(public(issuance), 200)


@bp.route("/tool-issuances/<row_id>/declare-unaccounted", methods=["POST"])
def declare_unaccounted(row_id):
    authorize(ROLE_CORRECTIONAL_OFFICER)
    body = body_json()
    validate_fields(body, [Field("narrative", "string", required=True)])
    issuance = need_issuance(row_id)
    not_terminal(issuance, "status", ("RETURNED",))
    require_state(issuance, "status", ("ISSUED",))
    facility = need_facility(issuance["facility_id"])
    issuance["status"] = "UNACCOUNTED"
    issuance["unaccounted_at"] = now_logical()
    touch(issuance)

    # Fan-out: the automatically raised incident, reported by 'system'.
    raise_system_incident(facility, issuance, body["narrative"])

    # Hops 1 and 2: the sharps counters move and the posture is recomputed.
    sync_facility(facility, force=True)
    # Hops 3 and 4 fire only on the LOCKDOWN (sharp) branch.
    if facility["kitchen_posture"] == "LOCKDOWN":
        discard_batches_for_lockdown(facility)
        unassign_line_workers(facility)
    return respond_object(public(issuance), 200)


# --------------------------------------------------------------------------
# Contraband incidents
# --------------------------------------------------------------------------
@bp.route("/contraband-incidents", methods=["POST"])
def create_incident():
    actor = authorize(ROLE_CORRECTIONAL_OFFICER)
    body = body_json()
    validate_fields(body, [
        Field("facility_id", "string", required=True),
        Field("item_class", "string", required=True, enum=ITEM_CLASSES),
        Field("severity", "string", required=True, enum=SEVERITIES),
        Field("narrative", "string", required=True),
        Field("inmate_worker_id", "string"),
        Field("related_tool_issuance_id", "string"),
    ])
    facility = need_facility(body["facility_id"])
    worker = None
    if present(body, "inmate_worker_id"):
        worker = need_worker(body["inmate_worker_id"])
    issuance = None
    if present(body, "related_tool_issuance_id"):
        issuance = need_issuance(body["related_tool_issuance_id"])
    row = base_row()
    row.update({
        "facility_id": facility["id"],
        "inmate_worker_id": worker["id"] if worker is not None else None,
        "related_tool_issuance_id": issuance["id"] if issuance is not None else None,
        "item_class": body["item_class"],
        "severity": body["severity"],
        "narrative": body["narrative"],
        "status": "OPEN",
        "sanction_type": None,
        "discovered_by_user_id": actor.user_id,
        "discovered_at": now_logical(),
        "disposition_by_user_id": None,
    })
    insert("contraband_incidents", row)
    sync_facility(facility, force=True)
    return respond_object(public(row), 201)


@bp.route("/contraband-incidents/<row_id>", methods=["GET"])
def read_incident(row_id):
    authorize(ROLE_CORRECTIONAL_OFFICER, ROLE_FOOD_SERVICE_SUPERVISOR,
              ROLE_COMPLIANCE_AUDITOR)
    return respond_object(public(need_incident(row_id)), 200)


@bp.route("/contraband-incidents", methods=["GET"])
def list_incidents():
    authorize(ROLE_CORRECTIONAL_OFFICER, ROLE_FOOD_SERVICE_SUPERVISOR,
              ROLE_COMPLIANCE_AUDITOR)
    rows = filter_eq(all_rows("contraband_incidents"), "facility_id")
    rows = filter_eq(rows, "inmate_worker_id")
    rows = filter_eq(rows, "related_tool_issuance_id")
    rows = filter_eq(rows, "status")
    return listing(rows)


@bp.route("/contraband-incidents/<row_id>/disposition", methods=["POST"])
def disposition_incident(row_id):
    actor = authorize(ROLE_CORRECTIONAL_OFFICER)
    body = body_json()
    validate_fields(body, [
        Field("disposition", "string", required=True, enum=DISPOSITIONS),
        Field("sanction_type", "string", enum=SANCTION_TYPES),
    ])
    disposition = body["disposition"]
    if disposition == "SANCTIONED" and not present(body, "sanction_type"):
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'sanction_type' is required on a SANCTIONED disposition.")
    if disposition == "CLEARED" and present(body, "sanction_type"):
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'sanction_type' must be absent on a CLEARED disposition.")
    incident = need_incident(row_id)
    not_terminal(incident, "status", ("SANCTIONED", "CLEARED"))
    require_state(incident, "status", ("OPEN",))
    if disposition == "SANCTIONED" and not incident.get("inmate_worker_id"):
        raise ApiError("ERR_INVALID_STATE",
                       "An unattributed incident cannot be sanctioned.")
    if actor.user_id == incident.get("discovered_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    facility = need_facility(incident["facility_id"])
    incident["status"] = disposition
    incident["disposition_by_user_id"] = actor.user_id
    if disposition == "SANCTIONED":
        incident["sanction_type"] = body["sanction_type"]
    touch(incident)

    if disposition == "SANCTIONED":
        worker = need_worker(incident["inmate_worker_id"])
        changed = refresh_worker_strikes(worker)
        sanction = incident["sanction_type"]
        strikes = int(worker["contraband_strike_count"])
        new_clearance = None
        if sanction == "WORK_BAR" or strikes >= STRIKE_BAR_THRESHOLD:
            new_clearance = "BARRED"
        elif sanction == "WORK_SUSPENSION":
            new_clearance = "SUSPENDED"
        if new_clearance is not None:
            if worker["clearance_status"] != new_clearance:
                worker["clearance_status"] = new_clearance
                changed = True
            if worker["assignment_status"] != "UNASSIGNED" or worker.get("work_area") is not None:
                worker["assignment_status"] = "UNASSIGNED"
                worker["work_area"] = None
                changed = True
        if changed:
            touch(worker)

    sync_facility(facility, force=True)
    return respond_object(public(incident), 200)
