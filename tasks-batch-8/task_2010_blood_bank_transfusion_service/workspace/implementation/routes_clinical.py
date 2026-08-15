"""Clinical-domain routes: type & screen lifecycle, transfusion orders,
crossmatches, issue records, and the massive transfusion protocol
(PRD 3.1, 3.3-3.6)."""

from datetime import timedelta

from flask import Blueprint, request

import errors as E
import logic
from common import (
    endpoint, get_body, req_str, opt_str, req_int, req_enum, req_bool,
    opt_bool, req_dt, opt_str_list,
    ts_by_path, order_by_path, xm_by_path, issue_by_path, mtp_by_path, fk_exists,
)
from constants import (
    ROLES, RBC_CLASS, ABO_TYPES, RH_TYPES, URGENCIES, TS_VALIDITY_HOURS,
    XM_HOLD_HOURS, TRANSFUSION_START_WINDOW_HOURS, EMERGENCY_ACK_WINDOW_HOURS,
    RETURN_RESTOCK_WINDOW_MINUTES,
)
from envelope import object_response, list_response
from errors import ApiError
from serializers import ser_ts, ser_order, ser_xm, ser_issue, ser_mtp
from store import DB, new_entity, touch, now

bp = Blueprint("clinical", __name__)

ALL = ROLES
TECH = ["BloodBankTechnologist"]
PHYSICIAN = ["OrderingPhysician"]


# ---------------------------------------------------------------------------
# Type & screen (PRD 3.1)
# ---------------------------------------------------------------------------

@bp.post("/blood-bank/type-and-screens")
@endpoint(TECH)
def ts_create(user_id, role):
    body = get_body()
    patient_id = req_str(body, "patient_id")
    specimen_collected_at = req_dt(body, "specimen_collected_at")
    expected_version = req_int(body, "expected_patient_version")
    patient = fk_exists(DB.patients, patient_id, "Patient")
    # OCC (pipeline stage 6) precedes business checks.
    if expected_version != patient["version"]:
        raise ApiError(
            E.ERR_STALE_VERSION, 412,
            f"expected_patient_version {expected_version} does not match current version {patient['version']}",
        )
    if specimen_collected_at > now():
        raise ApiError(E.ERR_SPECIMEN_TIME_INVALID, 400, "specimen_collected_at must not be in the future")
    for other in DB.type_and_screens.values():
        if (
            other["patient_id"] == patient["id"]
            and other["status"] != "REJECTED"
            and other["specimen_collected_at"] == specimen_collected_at
        ):
            raise ApiError(
                E.ERR_DUPLICATE_SPECIMEN, 409,
                "Patient already has a non-REJECTED type-and-screen with this specimen_collected_at",
            )
    ts = new_entity({
        "patient_id": patient["id"],
        "specimen_collected_at": specimen_collected_at,
        "expires_at": specimen_collected_at + timedelta(hours=TS_VALIDITY_HOURS),
        "abo_result": None,
        "rh_result": None,
        "antibody_screen": None,
        "antibody_identifications": [],
        "resulted_at": None,
        "resulted_by_user_id": None,
        "validated_at": None,
        "validated_by_user_id": None,
        "status": "COLLECTED",
        "reject_reason": None,
    })
    DB.type_and_screens[ts["id"]] = ts
    # A pending specimen changes the clinical picture: Patient.version +1.
    touch(patient)
    return object_response(ser_ts(ts), status=201)


@bp.get("/blood-bank/type-and-screens")
@endpoint(ALL)
def ts_list(user_id, role):
    rows = list(DB.type_and_screens.values())
    patient_id = request.args.get("patient_id")
    if patient_id is not None:
        rows = [t for t in rows if t["patient_id"] == patient_id]
    status = request.args.get("status")
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    return list_response(rows, request.args, ser_ts)


@bp.get("/blood-bank/type-and-screens/<tid>")
@endpoint(ALL)
def ts_get(tid, user_id, role):
    return object_response(ser_ts(ts_by_path(tid)))


@bp.post("/blood-bank/type-and-screens/<tid>/result")
@endpoint(TECH)
def ts_result(tid, user_id, role):
    ts = ts_by_path(tid)
    body = get_body()
    abo_result = req_enum(body, "abo_result", ABO_TYPES)
    rh_result = req_enum(body, "rh_result", RH_TYPES)
    antibody_screen = req_enum(body, "antibody_screen", ["NEGATIVE", "POSITIVE"])
    identifications = opt_str_list(body, "antibody_identifications")
    if ts["status"] != "COLLECTED":
        raise ApiError(E.ERR_TS_NOT_COLLECTED, 409, "result requires status COLLECTED")
    if antibody_screen == "POSITIVE" and len(identifications) == 0:
        raise ApiError(
            E.ERR_ANTIBODY_DETAIL_REQUIRED, 422,
            "antibody_screen POSITIVE requires a non-empty antibody_identifications array",
        )
    ts["abo_result"] = abo_result
    ts["rh_result"] = rh_result
    ts["antibody_screen"] = antibody_screen
    ts["antibody_identifications"] = identifications
    ts["resulted_at"] = now()
    ts["resulted_by_user_id"] = user_id
    ts["status"] = "RESULTED"
    touch(ts)
    return object_response(ser_ts(ts))


@bp.post("/blood-bank/type-and-screens/<tid>/validate")
@endpoint(TECH)
def ts_validate(tid, user_id, role):
    ts = ts_by_path(tid)
    if ts["status"] != "RESULTED":
        raise ApiError(E.ERR_TS_NOT_RESULTED, 409, "validate requires status RESULTED")
    if user_id == ts["resulted_by_user_id"]:
        raise ApiError(
            E.ERR_SEGREGATION_OF_DUTIES, 403,
            "The validator must differ from the technologist who recorded the result",
        )
    ts["status"] = "ACTIVE"
    ts["validated_at"] = now()
    ts["validated_by_user_id"] = user_id
    touch(ts)
    patient = DB.patients[ts["patient_id"]]
    # Supersede every other ACTIVE specimen of this patient.
    for other in DB.type_and_screens.values():
        if other["id"] != ts["id"] and other["patient_id"] == patient["id"] and other["status"] == "ACTIVE":
            other["status"] = "SUPERSEDED"
            touch(other)
    # Two-specimen ABO confirmation latch (calculations.abo_confirmation_latch).
    if not patient["abo_confirmed"]:
        for other in DB.type_and_screens.values():
            if (
                other["id"] != ts["id"]
                and other["patient_id"] == patient["id"]
                and other["status"] in ("ACTIVE", "SUPERSEDED", "EXPIRED")
                and other["abo_result"] == ts["abo_result"]
                and other["specimen_collected_at"] != ts["specimen_collected_at"]
            ):
                patient["abo_confirmed"] = True
                break
    # Patient summary recompute from the newly validated specimen.
    patient["current_abo_type"] = ts["abo_result"]
    patient["current_rh_type"] = ts["rh_result"]
    patient["antibody_status"] = ts["antibody_screen"]
    patient["identified_antibodies"] = list(ts["antibody_identifications"])
    touch(patient)
    return object_response(ser_ts(ts))


@bp.post("/blood-bank/type-and-screens/<tid>/reject-specimen")
@endpoint(TECH)
def ts_reject(tid, user_id, role):
    ts = ts_by_path(tid)
    body = get_body()
    reason = req_str(body, "reason")
    if ts["status"] != "COLLECTED":
        raise ApiError(E.ERR_TS_NOT_COLLECTED, 409, "reject-specimen requires status COLLECTED")
    ts["status"] = "REJECTED"
    ts["reject_reason"] = reason
    touch(ts)
    return object_response(ser_ts(ts))


# ---------------------------------------------------------------------------
# Transfusion orders (PRD 3.3)
# ---------------------------------------------------------------------------

@bp.post("/blood-bank/transfusion-orders")
@endpoint(PHYSICIAN)
def order_create(user_id, role):
    body = get_body()
    patient_id = req_str(body, "patient_id")
    product_type = req_enum(body, "product_type", ["RBC", "WHOLE_BLOOD", "PLT_APHERESIS", "PLT_POOL", "FFP", "CRYO"])
    units_requested = req_int(body, "units_requested", min_value=1, max_value=20)
    urgency = req_enum(body, "urgency", URGENCIES)
    indication_code = req_str(body, "indication_code")
    patient = fk_exists(DB.patients, patient_id, "Patient")
    order = new_entity({
        "patient_id": patient["id"],
        "ordering_physician_id": user_id,
        "product_type": product_type,
        "units_requested": units_requested,
        "urgency": urgency,
        "indication_code": indication_code,
        "requires_crossmatch": product_type in RBC_CLASS,
        "type_restriction": "NONE",
        "demand_bucket": None,
        "special_requirements_snapshot": [],
        "units_crossmatched": 0,
        "units_issued_net": 0,
        "units_transfused": 0,
        "verified_by_user_id": None,
        "verified_at": None,
        "status": "PENDING_VERIFICATION",
        "rejection_reason": None,
        "cancel_reason": None,
    })
    DB.orders[order["id"]] = order
    return object_response(ser_order(order), status=201)


@bp.get("/blood-bank/transfusion-orders")
@endpoint(ALL)
def order_list(user_id, role):
    rows = list(DB.orders.values())
    for param in ("patient_id", "status", "product_type", "urgency"):
        value = request.args.get(param)
        if value is not None:
            rows = [o for o in rows if o[param] == value]
    return list_response(rows, request.args, ser_order)


@bp.get("/blood-bank/transfusion-orders/<oid>")
@endpoint(ALL)
def order_get(oid, user_id, role):
    return object_response(ser_order(order_by_path(oid)))


@bp.post("/blood-bank/transfusion-orders/<oid>/verify")
@endpoint(TECH)
def order_verify(oid, user_id, role):
    order = order_by_path(oid)
    if order["status"] != "PENDING_VERIFICATION":
        raise ApiError(E.ERR_ORDER_NOT_VERIFIABLE, 409, "verify requires PENDING_VERIFICATION")
    if user_id == order["ordering_physician_id"]:
        raise ApiError(
            E.ERR_SEGREGATION_OF_DUTIES, 403,
            "The verifying technologist must differ from the ordering physician",
        )
    patient = DB.patients[order["patient_id"]]
    has_active_ts = logic.patient_has_active_ts(patient["id"])
    if not has_active_ts and order["urgency"] != "EMERGENCY":
        raise ApiError(E.ERR_TS_NOT_ACTIVE, 409, "Patient lacks an ACTIVE type-and-screen")

    # Demand bucket: patient typing at verify time; UNKNOWN maps to O:NEG for
    # red-cell class and AB:NEG for plasma class.
    if order["product_type"] in RBC_CLASS:
        mapped = ("O", "NEG")
    else:
        mapped = ("AB", "NEG")
    abo = patient["current_abo_type"] if patient["current_abo_type"] != "UNKNOWN" else mapped[0]
    rh = patient["current_rh_type"] if patient["current_rh_type"] != "UNKNOWN" else mapped[1]
    demand_bucket = f"{order['product_type']}:{abo}:{rh}"

    # Scarcity gates (physical posture flavor) — ROUTINE orders only.
    posture = logic.physical_posture(order["product_type"], abo, rh)
    if order["urgency"] == "ROUTINE":
        if posture == "CRITICAL":
            raise ApiError(
                E.ERR_BUCKET_CRITICAL_ELECTIVE_BLOCKED, 409,
                f"Demand bucket {demand_bucket} posture is CRITICAL",
            )
        if logic.any_mtp_activated() and posture in ("SHORTAGE", "CRITICAL"):
            raise ApiError(
                E.ERR_BUCKET_SHORTAGE_MTP_PRIORITY, 409,
                f"An MTP is ACTIVATED and demand bucket {demand_bucket} posture is {posture}",
            )

    order["verified_by_user_id"] = user_id
    order["verified_at"] = now()
    order["special_requirements_snapshot"] = list(patient["special_requirements"])
    order["type_restriction"] = (
        "NONE" if has_active_ts else ("O_ONLY" if order["product_type"] in RBC_CLASS else "AB_ONLY")
    )
    order["demand_bucket"] = demand_bucket
    # VERIFIED is transient: auto-advance within the same call.
    order["status"] = "AWAITING_CROSSMATCH" if order["requires_crossmatch"] else "READY"
    touch(order)
    return object_response(ser_order(order))


@bp.post("/blood-bank/transfusion-orders/<oid>/reject")
@endpoint(TECH)
def order_reject(oid, user_id, role):
    order = order_by_path(oid)
    body = get_body()
    reason = req_str(body, "rejection_reason")
    if order["status"] != "PENDING_VERIFICATION":
        raise ApiError(E.ERR_ORDER_NOT_REJECTABLE, 409, "reject requires PENDING_VERIFICATION")
    order["status"] = "REJECTED"
    order["rejection_reason"] = reason
    touch(order)
    return object_response(ser_order(order))


@bp.post("/blood-bank/transfusion-orders/<oid>/cancel")
@endpoint(PHYSICIAN)
def order_cancel(oid, user_id, role):
    order = order_by_path(oid)
    body = get_body()
    cancel_reason = opt_str(body, "cancel_reason", default=None, allow_empty=True)
    if order["status"] not in ("PENDING_VERIFICATION", "AWAITING_CROSSMATCH", "READY", "PARTIALLY_ISSUED", "ON_HOLD"):
        raise ApiError(E.ERR_ORDER_NOT_CANCELLABLE, 409, "cancel requires a non-terminal status")
    # Compensate reservations: PENDING/COMPATIBLE crossmatches -> CANCELLED,
    # each RESERVED unit released to AVAILABLE. In-flight issues are untouched.
    for xm in list(DB.crossmatches.values()):
        if xm["order_id"] == order["id"] and xm["status"] in ("PENDING", "COMPATIBLE"):
            logic.cancel_crossmatch(xm, release_unit=True)
    order["status"] = "CANCELLED"
    order["cancel_reason"] = cancel_reason
    touch(order)
    return object_response(ser_order(order))


@bp.post("/blood-bank/transfusion-orders/<oid>/reactivate")
@endpoint(TECH)
def order_reactivate(oid, user_id, role):
    order = order_by_path(oid)
    if order["status"] != "ON_HOLD":
        raise ApiError(E.ERR_ORDER_NOT_REACTIVATABLE, 409, "reactivate requires ON_HOLD")
    patient = DB.patients[order["patient_id"]]
    if not logic.patient_has_active_ts(patient["id"]):
        raise ApiError(E.ERR_TS_NOT_ACTIVE, 409, "Patient lacks an ACTIVE type-and-screen")
    # Target state derived from the live counters, not chosen by the caller.
    if logic.order_fulfillment(order) < order["units_requested"]:
        order["status"] = "AWAITING_CROSSMATCH"
    elif order["units_issued_net"] == 0:
        order["status"] = "READY"
    else:
        order["status"] = "PARTIALLY_ISSUED"
    touch(order)
    return object_response(ser_order(order))


# ---------------------------------------------------------------------------
# Crossmatches (PRD 3.4)
# ---------------------------------------------------------------------------

def _order_compat_ctx(order):
    return {
        "product_type": order["product_type"],
        "urgency": order["urgency"],
        "type_restriction": order["type_restriction"],
        "special_requirements": list(order["special_requirements_snapshot"]),
    }


@bp.post("/blood-bank/crossmatches")
@endpoint(TECH)
def xm_create(user_id, role):
    body = get_body()
    order_id = req_str(body, "order_id")
    unit_id = opt_str(body, "unit_id")
    order = fk_exists(DB.orders, order_id, "TransfusionOrder")
    unit = fk_exists(DB.units, unit_id, "BloodUnit") if unit_id is not None else None
    patient = DB.patients[order["patient_id"]]
    ctx = _order_compat_ctx(order)
    auto_selected = False
    # Unit compatibility for an explicitly selected unit (priority 8) precedes
    # the fulfillment ceiling (priority 22).
    if unit is not None and not logic.unit_compatible(unit, patient, ctx):
        raise ApiError(E.ERR_UNIT_INCOMPATIBLE, 422, "Unit fails the compatibility decision for this patient/order")
    if logic.order_fulfillment(order) >= order["units_requested"]:
        raise ApiError(E.ERR_ORDER_FULLY_CROSSMATCHED, 409, "Order fulfillment already meets units_requested")
    if unit is None:
        unit = logic.fefo_select(order["product_type"], patient, ctx)
        if unit is None:
            raise ApiError(E.ERR_NO_COMPATIBLE_UNIT, 409, "No compatible unit available for auto-selection")
        auto_selected = True
    method = (
        "ELECTRONIC"
        if patient["abo_confirmed"] and patient["antibody_status"] == "NEGATIVE"
        else "SEROLOGIC_AHG"
    )
    xm = new_entity({
        "order_id": order["id"],
        "unit_id": unit["id"],
        "patient_id": patient["id"],
        "method": method,
        "status": "PENDING",
        "auto_selected": auto_selected,
        "resulted_at": None,
        "resulted_by_user_id": None,
        "reserved_until": None,
    })
    DB.crossmatches[xm["id"]] = xm
    return object_response(ser_xm(xm), status=201)


@bp.get("/blood-bank/crossmatches")
@endpoint(ALL)
def xm_list(user_id, role):
    rows = list(DB.crossmatches.values())
    for param in ("order_id", "unit_id", "patient_id", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [x for x in rows if x[param] == value]
    return list_response(rows, request.args, ser_xm)


@bp.get("/blood-bank/crossmatches/<xid>")
@endpoint(ALL)
def xm_get(xid, user_id, role):
    return object_response(ser_xm(xm_by_path(xid)))


@bp.post("/blood-bank/crossmatches/<xid>/record-result")
@endpoint(TECH)
def xm_record_result(xid, user_id, role):
    xm = xm_by_path(xid)
    body = get_body()
    result = req_enum(body, "result", ["COMPATIBLE", "INCOMPATIBLE"])
    if xm["status"] != "PENDING":
        raise ApiError(E.ERR_XM_NOT_PENDING, 409, "record-result requires PENDING")
    xm["resulted_at"] = now()
    xm["resulted_by_user_id"] = user_id
    if result == "INCOMPATIBLE":
        # Terminal and gentle: the unit was never reserved, counters unmoved.
        xm["status"] = "INCOMPATIBLE"
        touch(xm)
        return object_response(ser_xm(xm))
    unit = DB.units[xm["unit_id"]]
    if unit["status"] != "AVAILABLE" or not (unit["expires_at"] > now()):
        raise ApiError(E.ERR_UNIT_NOT_AVAILABLE, 409, "Unit is not AVAILABLE for reservation")
    patient = DB.patients[xm["patient_id"]]
    active_ts = logic.patient_active_ts(patient["id"])
    if active_ts is None:
        raise ApiError(E.ERR_TS_NOT_ACTIVE, 409, "Patient lacks an ACTIVE type-and-screen")
    unit["status"] = "RESERVED"
    touch(unit)
    xm["reserved_until"] = min(
        now() + timedelta(hours=XM_HOLD_HOURS),
        unit["expires_at"],
        active_ts["expires_at"],
    )
    xm["status"] = "COMPATIBLE"
    touch(xm)
    logic.on_xm_compatible_added(DB.orders[xm["order_id"]])
    return object_response(ser_xm(xm))


@bp.post("/blood-bank/crossmatches/<xid>/cancel")
@endpoint(TECH)
def xm_cancel(xid, user_id, role):
    xm = xm_by_path(xid)
    if xm["status"] not in ("PENDING", "COMPATIBLE"):
        raise ApiError(E.ERR_XM_NOT_CANCELLABLE, 409, "cancel requires PENDING or COMPATIBLE")
    logic.cancel_crossmatch(xm, release_unit=True)
    return object_response(ser_xm(xm))


# ---------------------------------------------------------------------------
# Issue records (PRD 3.5)
# ---------------------------------------------------------------------------

def _compatible_xm_for_order_unit(order_id, unit_id):
    for xm in DB.crossmatches.values():
        if xm["order_id"] == order_id and xm["unit_id"] == unit_id and xm["status"] == "COMPATIBLE":
            return xm
    return None


@bp.post("/blood-bank/issue-records")
@endpoint(TECH)
def issue_create(user_id, role):
    body = get_body()
    order_id = req_str(body, "order_id")
    verified_by = req_str(body, "verified_by_user_id")
    unit_id = opt_str(body, "unit_id")
    is_emergency = opt_bool(body, "is_emergency_release", default=False)
    justification = opt_str(body, "emergency_justification", default=None, allow_empty=True)
    order = fk_exists(DB.orders, order_id, "TransfusionOrder")
    unit = fk_exists(DB.units, unit_id, "BloodUnit") if unit_id is not None else None
    patient = DB.patients[order["patient_id"]]

    # Standard red-cell-class issues require an explicit unit (schema stage).
    if order["product_type"] in RBC_CLASS and not is_emergency and unit is None:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "Field 'unit_id': is required for standard RBC/WHOLE_BLOOD issues")

    # State: order must be issuable.
    issuable = order["status"] in ("READY", "PARTIALLY_ISSUED") or (
        order["status"] == "AWAITING_CROSSMATCH" and is_emergency
    )
    if not issuable:
        raise ApiError(E.ERR_ORDER_NOT_ISSUABLE, 409, "issue requires READY or PARTIALLY_ISSUED (AWAITING_CROSSMATCH only for emergency release)")

    # Unit state/linkage: standard flow needs the unit RESERVED via a
    # COMPATIBLE crossmatch for this very order; plasma/emergency flows draw
    # from AVAILABLE (or consume a reservation for this order).
    xm_to_consume = None
    if unit is not None:
        xm = _compatible_xm_for_order_unit(order["id"], unit["id"])
        if order["product_type"] in RBC_CLASS and not is_emergency:
            if xm is None or unit["status"] != "RESERVED":
                raise ApiError(E.ERR_UNIT_NOT_AVAILABLE, 409, "Unit must be RESERVED via a COMPATIBLE crossmatch for this order")
            xm_to_consume = xm
        else:
            if xm is not None and unit["status"] == "RESERVED":
                xm_to_consume = xm
            elif unit["status"] == "AVAILABLE":
                xm_to_consume = None
            else:
                raise ApiError(E.ERR_UNIT_NOT_AVAILABLE, 409, "Unit is not AVAILABLE for issue")

    # Unit compatibility re-run for explicit selections (priority 8).
    ctx = _order_compat_ctx(order)
    if unit is not None and not logic.unit_compatible(unit, patient, ctx):
        raise ApiError(E.ERR_UNIT_INCOMPATIBLE, 422, "Unit fails the compatibility decision for this patient/order")

    # Segregation of duties on issuing (priority 9).
    if verified_by == user_id:
        raise ApiError(E.ERR_SEGREGATION_OF_DUTIES, 403, "verified_by_user_id must differ from the issuing technologist")

    # Two-specimen rule (priority 10).
    if (
        unit is not None
        and order["product_type"] in RBC_CLASS
        and unit["abo_type"] != "O"
        and not patient["abo_confirmed"]
        and not is_emergency
    ):
        raise ApiError(E.ERR_SECOND_SPECIMEN_REQUIRED, 409, "Non-O red-cell issue requires a confirmed ABO type (two specimens)")

    # Emergency-release eligibility and justification (priority 11).
    if is_emergency:
        if order["urgency"] != "EMERGENCY" and not logic.patient_has_activated_mtp(patient["id"]):
            raise ApiError(
                E.ERR_EMERGENCY_RELEASE_NOT_ALLOWED, 409,
                "is_emergency_release requires EMERGENCY urgency or an ACTIVATED MTP for the patient",
            )
        if justification is None or len(justification) < 20:
            raise ApiError(
                E.ERR_EMERGENCY_JUSTIFICATION_REQUIRED, 422,
                "Emergency release requires a justification of at least 20 characters",
            )

    # Issue quota (priority 23).
    if order["units_issued_net"] >= order["units_requested"]:
        raise ApiError(E.ERR_ORDER_ISSUE_QUOTA_MET, 409, "units_issued_net already equals units_requested")

    # FEFO auto-selection (priority 31, last).
    if unit is None:
        unit = logic.fefo_select(order["product_type"], patient, ctx)
        if unit is None:
            raise ApiError(E.ERR_NO_COMPATIBLE_UNIT, 409, "No compatible unit available for auto-selection")

    # Commit: unit -> ISSUED (consuming the crossmatch when present).
    if xm_to_consume is not None:
        xm_to_consume["status"] = "CONSUMED"
        touch(xm_to_consume)
    unit["status"] = "ISSUED"
    touch(unit)
    issue = new_entity({
        "order_id": order["id"],
        "unit_id": unit["id"],
        "patient_id": patient["id"],
        "mtp_activation_id": None,
        "is_emergency_release": is_emergency,
        "emergency_justification": justification if is_emergency else None,
        "verified_by_user_id": verified_by,
        "issued_by_user_id": user_id,
        "issued_at": now(),
        "transfusion_started_at": None,
        "completed_at": None,
        "returned_at": None,
        "return_seal_intact": None,
        "return_temperature_excursion": None,
        "return_disposition": None,
        "physician_acknowledged_at": None,
        "lookback_notified": False,
        "status": "ISSUED",
        "_consumed_xm_id": xm_to_consume["id"] if xm_to_consume is not None else None,
    })
    DB.issues[issue["id"]] = issue
    logic.on_issue_added(order)
    return object_response(ser_issue(issue), status=201)


@bp.get("/blood-bank/issue-records")
@endpoint(ALL)
def issue_list(user_id, role):
    rows = list(DB.issues.values())
    for param in ("order_id", "unit_id", "patient_id", "mtp_activation_id", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [i for i in rows if i[param] == value]
    return list_response(rows, request.args, ser_issue)


@bp.get("/blood-bank/issue-records/<iid>")
@endpoint(ALL)
def issue_get(iid, user_id, role):
    return object_response(ser_issue(issue_by_path(iid)))


@bp.post("/blood-bank/issue-records/<iid>/start-transfusion")
@endpoint(TECH)
def issue_start(iid, user_id, role):
    issue = issue_by_path(iid)
    if issue["status"] != "ISSUED":
        raise ApiError(E.ERR_ISSUE_NOT_STARTABLE, 409, "start-transfusion requires ISSUED")
    # Four-hour window, boundary inclusive: exactly issued_at + 4h is allowed.
    if now() > issue["issued_at"] + timedelta(hours=TRANSFUSION_START_WINDOW_HOURS):
        raise ApiError(E.ERR_TRANSFUSION_START_WINDOW_LAPSED, 409, "More than 4h have elapsed since issue")
    issue["transfusion_started_at"] = now()
    issue["status"] = "TRANSFUSION_STARTED"
    touch(issue)
    return object_response(ser_issue(issue))


@bp.post("/blood-bank/issue-records/<iid>/complete-transfusion")
@endpoint(TECH)
def issue_complete(iid, user_id, role):
    issue = issue_by_path(iid)
    if issue["status"] != "TRANSFUSION_STARTED":
        raise ApiError(E.ERR_ISSUE_NOT_COMPLETABLE, 409, "complete-transfusion requires TRANSFUSION_STARTED")
    issue["completed_at"] = now()
    issue["status"] = "TRANSFUSED"
    touch(issue)
    unit = DB.units.get(issue["unit_id"])
    if unit is not None and unit["status"] == "ISSUED":
        unit["status"] = "TRANSFUSED"
        touch(unit)
    patient = DB.patients[issue["patient_id"]]
    order = DB.orders.get(issue["order_id"]) if issue["order_id"] else None
    if order is not None:
        logic.on_transfusion_completed(order, patient)
    else:
        patient["total_units_transfused"] += 1
        touch(patient)
    return object_response(ser_issue(issue))


@bp.post("/blood-bank/issue-records/<iid>/return")
@endpoint(TECH)
def issue_return(iid, user_id, role):
    issue = issue_by_path(iid)
    body = get_body()
    seal_intact = req_bool(body, "seal_intact")
    temperature_excursion = req_bool(body, "temperature_excursion")
    if issue["status"] != "ISSUED":
        raise ApiError(E.ERR_ISSUE_NOT_RETURNABLE, 409, "return requires ISSUED — a started transfusion can never be returned")
    returned_at = now()
    # calculations.return_disposition — the 30-minute rule, boundary inclusive.
    within_window = returned_at <= issue["issued_at"] + timedelta(minutes=RETURN_RESTOCK_WINDOW_MINUTES)
    if within_window and seal_intact and not temperature_excursion:
        disposition = "RESTOCKED"
    elif not seal_intact or temperature_excursion:
        disposition = "DISCARDED_COMPROMISED"
    else:
        disposition = "DISCARDED_OVER_30MIN"
    issue["returned_at"] = returned_at
    issue["return_seal_intact"] = seal_intact
    issue["return_temperature_excursion"] = temperature_excursion
    issue["return_disposition"] = disposition
    issue["status"] = "RETURNED"
    touch(issue)
    unit = DB.units[issue["unit_id"]]
    if disposition == "RESTOCKED":
        # The consumed crossmatch is NOT revived.
        unit["status"] = "AVAILABLE"
        touch(unit)
    else:
        unit["status"] = "DISCARDED"
        unit["hold_origin_state"] = None
        unit["hold_reason"] = None
        touch(unit)
        logic.add_wastage(
            unit,
            "RETURNED_OVER_30MIN" if disposition == "DISCARDED_OVER_30MIN" else "RETURNED_COMPROMISED",
            user_id,
        )
    order = DB.orders.get(issue["order_id"]) if issue["order_id"] else None
    if order is not None:
        logic.on_issue_removed(order, issue)
    return object_response(ser_issue(issue))


@bp.post("/blood-bank/issue-records/<iid>/stop-transfusion")
@endpoint(TECH)
def issue_stop(iid, user_id, role):
    issue = issue_by_path(iid)
    if issue["status"] != "TRANSFUSION_STARTED":
        raise ApiError(E.ERR_ISSUE_NOT_STOPPABLE, 409, "stop-transfusion requires TRANSFUSION_STARTED")
    issue["status"] = "TRANSFUSION_STOPPED"
    touch(issue)
    unit = DB.units[issue["unit_id"]]
    unit["status"] = "DISCARDED"
    touch(unit)
    logic.add_wastage(unit, "PARTIAL_TRANSFUSION", user_id)
    order = DB.orders.get(issue["order_id"]) if issue["order_id"] else None
    if order is not None:
        logic.on_issue_removed(order, issue)
    return object_response(ser_issue(issue))


@bp.post("/blood-bank/issue-records/<iid>/acknowledge-emergency")
@endpoint(PHYSICIAN)
def issue_acknowledge(iid, user_id, role):
    issue = issue_by_path(iid)
    if not issue["is_emergency_release"] or issue["physician_acknowledged_at"] is not None:
        raise ApiError(E.ERR_ISSUE_NOT_ACKNOWLEDGABLE, 409, "acknowledge-emergency requires an unacknowledged emergency release")
    # Only the ordering physician of the issue's order may acknowledge; for
    # MTP-dispatched issues (no order) the activating physician owns the duty.
    if issue["order_id"] is not None:
        order = DB.orders[issue["order_id"]]
        physician = order["ordering_physician_id"]
    else:
        activation = DB.mtps.get(issue["mtp_activation_id"])
        physician = activation["activated_by_physician_id"] if activation else None
    if user_id != physician:
        raise ApiError(E.ERR_NOT_ORDERING_PHYSICIAN, 403, "Caller is not the ordering physician for this issue")
    if now() > issue["issued_at"] + timedelta(hours=EMERGENCY_ACK_WINDOW_HOURS):
        raise ApiError(E.ERR_EMERGENCY_ACK_WINDOW_LAPSED, 409, "More than 24h have elapsed since issue")
    issue["physician_acknowledged_at"] = now()
    touch(issue)
    return object_response(ser_issue(issue))


# ---------------------------------------------------------------------------
# Massive transfusion protocol (PRD 3.6)
# ---------------------------------------------------------------------------

@bp.post("/blood-bank/mtp-activations")
@endpoint(PHYSICIAN)
def mtp_create(user_id, role):
    body = get_body()
    patient_id = req_str(body, "patient_id")
    reason = req_str(body, "activation_reason")
    if len(reason) < 10:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "Field 'activation_reason': must be at least 10 characters")
    patient = fk_exists(DB.patients, patient_id, "Patient")
    if logic.patient_has_activated_mtp(patient["id"]):
        raise ApiError(E.ERR_MTP_ALREADY_ACTIVE, 409, "Patient already has an ACTIVATED MTP")
    activation = new_entity({
        "patient_id": patient["id"],
        "activated_by_physician_id": user_id,
        "activation_reason": reason,
        "status": "ACTIVATED",
        "packs_dispatched": 0,
        "units_issued_total": 0,
        "units_wasted_total": 0,
        "activated_at": now(),
        "stood_down_at": None,
        "deactivated_at": None,
    })
    DB.mtps[activation["id"]] = activation
    touch(patient)  # active_mtp flips true
    return object_response(ser_mtp(activation), status=201)


@bp.get("/blood-bank/mtp-activations")
@endpoint(ALL)
def mtp_list(user_id, role):
    rows = list(DB.mtps.values())
    patient_id = request.args.get("patient_id")
    if patient_id is not None:
        rows = [m for m in rows if m["patient_id"] == patient_id]
    status = request.args.get("status")
    if status is not None:
        rows = [m for m in rows if m["status"] == status]
    return list_response(rows, request.args, ser_mtp)


@bp.get("/blood-bank/mtp-activations/<mid>")
@endpoint(ALL)
def mtp_get(mid, user_id, role):
    return object_response(ser_mtp(mtp_by_path(mid)))


@bp.post("/blood-bank/mtp-activations/<mid>/dispatch-pack")
@endpoint(TECH)
def mtp_dispatch(mid, user_id, role):
    activation = mtp_by_path(mid)
    body = get_body()
    verified_by = req_str(body, "verified_by_user_id")
    if activation["status"] != "ACTIVATED":
        raise ApiError(E.ERR_MTP_NOT_ACTIVE, 409, "dispatch-pack requires ACTIVATED")
    if verified_by == user_id:
        raise ApiError(E.ERR_SEGREGATION_OF_DUTIES, 403, "verified_by_user_id must differ from the dispatching technologist")
    patient = DB.patients[activation["patient_id"]]
    selections, shortfalls = logic.dispatch_mtp_pack(activation, patient, verified_by, user_id)
    issue_ids = []
    for unit, _ctx in selections:
        issue = new_entity({
            "order_id": None,
            "unit_id": unit["id"],
            "patient_id": patient["id"],
            "mtp_activation_id": activation["id"],
            "is_emergency_release": True,
            "emergency_justification": activation["activation_reason"],
            "verified_by_user_id": verified_by,
            "issued_by_user_id": user_id,
            "issued_at": now(),
            "transfusion_started_at": None,
            "completed_at": None,
            "returned_at": None,
            "return_seal_intact": None,
            "return_temperature_excursion": None,
            "return_disposition": None,
            "physician_acknowledged_at": None,
            "lookback_notified": False,
            "status": "ISSUED",
            "_consumed_xm_id": None,
        })
        DB.issues[issue["id"]] = issue
        issue_ids.append(issue["id"])
    activation["packs_dispatched"] += 1
    activation["units_issued_total"] += len(issue_ids)
    touch(activation)
    return object_response({
        "pack_number": activation["packs_dispatched"],
        "issue_record_ids": issue_ids,
        "shortfalls": shortfalls,
    })


@bp.post("/blood-bank/mtp-activations/<mid>/stand-down")
@endpoint(PHYSICIAN)
def mtp_stand_down(mid, user_id, role):
    activation = mtp_by_path(mid)
    if activation["status"] != "ACTIVATED":
        raise ApiError(E.ERR_MTP_NOT_ACTIVE, 409, "stand-down requires ACTIVATED")
    activation["status"] = "STANDING_DOWN"
    activation["stood_down_at"] = now()
    touch(activation)
    return object_response(ser_mtp(activation))


@bp.post("/blood-bank/mtp-activations/<mid>/deactivate")
@endpoint(PHYSICIAN)
def mtp_deactivate(mid, user_id, role):
    activation = mtp_by_path(mid)
    if activation["status"] != "STANDING_DOWN":
        raise ApiError(E.ERR_MTP_NOT_STANDING_DOWN, 409, "deactivate requires STANDING_DOWN")
    outstanding = any(
        i["mtp_activation_id"] == activation["id"] and i["status"] in ("ISSUED", "TRANSFUSION_STARTED")
        for i in DB.issues.values()
    )
    if outstanding:
        raise ApiError(E.ERR_MTP_UNITS_OUTSTANDING, 409, "MTP issue records still ISSUED or TRANSFUSION_STARTED")
    activation["status"] = "DEACTIVATED"
    activation["deactivated_at"] = now()
    mtp_unit_ids = {
        i["unit_id"] for i in DB.issues.values() if i["mtp_activation_id"] == activation["id"]
    }
    activation["units_wasted_total"] = sum(
        1 for w in DB.wastage.values() if w["unit_id"] in mtp_unit_ids
    )
    touch(activation)
    patient = DB.patients[activation["patient_id"]]
    touch(patient)  # active_mtp flips false
    return object_response(ser_mtp(activation))
