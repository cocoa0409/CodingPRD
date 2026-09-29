"""Transfer ordering, superseding, acceptance, decline and completion."""

from flask import Blueprint

import constants as C
from db import base_row, db, row_key, touch
from domain import (
    agreement_status,
    declined_transfer_count,
    fire_disclosure_defect,
    get_agreement,
    get_encounter,
    get_mou,
    get_transfer_order,
    mou_units_available,
    record_defect,
    rows_of,
    transfer_order_view,
)
from errors import ApiError
from response import created, ok, ok_list, paginate
from validate import (
    auth,
    body,
    pagination,
    query_enum,
    query_str,
    req_bool,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("transfer_orders", __name__)

READ_ROLES = (
    "EmergencyPhysician",
    "HospitalTransferCoordinator",
    "ComplianceOfficer",
    "FacilityAdministrator",
)

LIVE_STATUSES = ("REQUESTED", "ACCEPTED")


def _newest_order(encounter):
    orders = rows_of(db.transfer_orders, encounter_id=encounter["id"])
    return orders[-1] if orders else None


@bp.post("/encounters/<eid>/transfer-orders")
def create_transfer_order(eid):
    user_id, _ = auth("EmergencyPhysician")
    data = body()
    expected = req_int(data, "expected_encounter_version", minimum=0)
    agreement_id = req_str(data, "transfer_agreement_id", 1, 64)
    mou_id = req_str(data, "ambulance_mou_id", 1, 64)
    certified = req_bool(data, "clinical_benefit_certified")

    encounter = get_encounter(eid)
    facility = db.facilities[encounter["facility_id"]]

    agreement = get_agreement(agreement_id)
    if agreement["facility_id"] != facility["id"]:
        raise ApiError("ERR_TRANSFER_AGREEMENT_NOT_FOUND")
    mou = get_mou(mou_id)
    if mou["facility_id"] != facility["id"]:
        raise ApiError("ERR_AMBULANCE_MOU_NOT_FOUND")

    if expected != encounter["version"]:
        raise ApiError("ERR_STALE_ENCOUNTER_VERSION")

    state = encounter["clinical_state"]
    if state in C.TERMINAL_CLINICAL_STATES:
        raise ApiError("ERR_INVALID_ENCOUNTER_STATE")
    if state in ("ARRIVED", "MSE_IN_PROGRESS"):
        raise ApiError("ERR_MSE_NOT_COMPLETE")

    if not certified:
        raise ApiError("ERR_TRANSFER_CERTIFICATION_REQUIRED")

    if encounter["stabilization_status"] == "UNSTABLE":
        if not agreement["accepts_unstable"] or mou["level_of_care"] != "CRITICAL_CARE":
            raise ApiError("ERR_STABILIZATION_REQUIRED")

    if agreement_status(agreement) != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")

    requested_at = db.clock
    if not (mou["coverage_start_at"] <= requested_at < mou["coverage_end_at"]):
        raise ApiError("ERR_MOU_WINDOW_NOT_COVERING")

    acuity = encounter["acuity_level"]
    if (
        agreement["service_line"] != encounter["presenting_service_line"]
        or agreement["capability_tier"] < C.REQUIRED_TIER_BY_ACUITY[acuity]
    ):
        raise ApiError("ERR_TRANSFER_CAPABILITY_INSUFFICIENT")

    if mou["level_of_care"] not in C.MOU_LEVEL_FLOOR_BY_ACUITY[acuity]:
        raise ApiError("ERR_MOU_LEVEL_INSUFFICIENT")

    if mou_units_available(mou) < 1:
        raise ApiError("ERR_AMBULANCE_CAPACITY_EXCEEDED")

    # Supersede any live order on the encounter, releasing its ambulance unit.
    for existing in rows_of(db.transfer_orders, encounter_id=encounter["id"]):
        if existing["status"] in LIVE_STATUSES:
            existing["status"] = "CANCELLED"
            existing["reserved_unit_count"] = 0
            touch(existing)

    order = base_row()
    order.update(
        {
            "encounter_id": encounter["id"],
            "transfer_agreement_id": agreement["id"],
            "ambulance_mou_id": mou["id"],
            "clinical_benefit_certified": True,
            "certifying_physician_user_id": user_id,
            "requested_at": requested_at,
            "round_index": 1 + declined_transfer_count(encounter),
            "reserved_unit_count": 1,
            "status": "REQUESTED",
            "decline_reason": None,
        }
    )
    db.transfer_orders[order["id"]] = order

    encounter["clinical_state"] = "TRANSFER_PENDING"
    touch(encounter)
    touch(facility)
    return created(transfer_order_view(order))


@bp.get("/transfer-orders")
def list_transfer_orders():
    auth(*READ_ROLES)
    encounter_id = query_str("encounter_id")
    agreement_id = query_str("transfer_agreement_id")
    mou_id = query_str("ambulance_mou_id")
    status = query_enum("status", C.TRANSFER_ORDER_STATUSES)
    limit, offset = pagination()

    rows = rows_of(db.transfer_orders)
    if encounter_id is not None:
        rows = [r for r in rows if r["encounter_id"] == encounter_id]
    if agreement_id is not None:
        rows = [r for r in rows if r["transfer_agreement_id"] == agreement_id]
    if mou_id is not None:
        rows = [r for r in rows if r["ambulance_mou_id"] == mou_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page = paginate(rows, limit, offset)
    return ok_list([transfer_order_view(r) for r in page], limit, offset, len(rows))


@bp.get("/transfer-orders/<oid>")
def read_transfer_order(oid):
    auth(*READ_ROLES)
    return ok(transfer_order_view(get_transfer_order(oid)))


@bp.post("/transfer-orders/<oid>/accept")
def accept_transfer_order(oid):
    auth("HospitalTransferCoordinator")
    data = body()
    req_str(data, "accepting_clinician_note", 1, 1000, required=False)

    order = get_transfer_order(oid)
    if order["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_TRANSFER_ORDER_STATE")

    agreement = db.agreements[order["transfer_agreement_id"]]
    if agreement_status(agreement) != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")

    order["status"] = "ACCEPTED"
    touch(order)
    return ok(transfer_order_view(order))


@bp.post("/transfer-orders/<oid>/decline")
def decline_transfer_order(oid):
    auth("HospitalTransferCoordinator")
    data = body()
    decline_reason = req_enum(data, "decline_reason", C.DECLINE_REASONS)

    order = get_transfer_order(oid)
    if order["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_TRANSFER_ORDER_STATE")

    encounter = db.encounters[order["encounter_id"]]
    facility = db.facilities[encounter["facility_id"]]

    order["status"] = "DECLINED"
    order["decline_reason"] = decline_reason
    order["reserved_unit_count"] = 0
    touch(order)

    newest = _newest_order(encounter)
    if newest is not None and row_key(newest) == row_key(order):
        # No observation bed re-check: the bed was never released.
        encounter["clinical_state"] = (
            "OBSERVATION" if encounter["observation_bed_held"] else "MSE_COMPLETE"
        )
    touch(encounter)
    touch(facility)

    if decline_reason == "INSURANCE":
        record_defect(
            facility,
            "TRANSFER_DECLINED_FOR_INSURANCE",
            "CRITICAL",
            "TRANSFER_ORDER",
            order["id"],
            "Receiving hospital declined the transfer for insurance reasons.",
        )
    return ok(transfer_order_view(order))


@bp.post("/transfer-orders/<oid>/complete")
def complete_transfer_order(oid):
    auth("HospitalTransferCoordinator")
    data = body()
    req_str(data, "arrival_confirmation_note", 1, 1000, required=False)

    order = get_transfer_order(oid)
    if order["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_TRANSFER_ORDER_STATE")

    encounter = db.encounters[order["encounter_id"]]
    facility = db.facilities[encounter["facility_id"]]

    order["status"] = "COMPLETED"
    order["reserved_unit_count"] = 0
    touch(order)

    encounter["clinical_state"] = "TRANSFERRED"
    encounter["observation_bed_held"] = False
    touch(encounter)
    touch(facility)
    fire_disclosure_defect(facility, encounter)
    return ok(transfer_order_view(order))
