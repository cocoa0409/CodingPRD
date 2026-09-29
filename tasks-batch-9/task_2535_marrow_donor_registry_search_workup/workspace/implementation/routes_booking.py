"""Collection bookings, product shipments, courier custody and claims
(PRD 3.7, 3.9)."""

from datetime import timedelta, timezone

from flask import Blueprint

import calc
import cascades
import claims as claim_engine
import serializers
import validate as v
from auth import (ROLE_CENTER, ROLE_COORDINATOR, ROLE_DIRECTOR, ROLE_OPS,
                  authenticate)
from envelope import read_pagination, success
from errors import ApiError
from guards import arg, find, render_list
from store import db, new_row, touch

bp = Blueprint("registry_bookings", __name__)

EVENT_TYPES = ("DEPARTED", "DELIVERED", "LOST")
SUPERSEDE_REASON = "SUPERSEDED_BY_NEW_BOOKING"


def _booking_sort(row):
    return (row["start_at"], row["created_at"], row["_seq"])


@bp.get("/registry/collection-bookings")
def list_bookings():
    authenticate(ROLE_CENTER, ROLE_OPS, ROLE_DIRECTOR, ROLE_COORDINATOR)
    limit, offset = read_pagination()
    case_id = arg("workup_case_id")
    center_id = arg("collection_center_id")
    status = arg("status")
    rows = []
    for row in db.bookings.values():
        if case_id is not None and row["workup_case_id"] != case_id:
            continue
        if center_id is not None and row["collection_center_id"] != center_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return render_list(rows, serializers.booking_dict, limit, offset,
                       _booking_sort)


@bp.get("/registry/collection-bookings/<bid>")
def get_booking(bid):
    authenticate(ROLE_CENTER, ROLE_OPS, ROLE_DIRECTOR, ROLE_COORDINATOR)
    row = find(db.bookings, bid, "ERR_BOOKING_NOT_FOUND")
    return success(serializers.booking_dict(row))


@bp.post("/registry/collection-bookings")
def create_booking():
    actor = authenticate(ROLE_CENTER)
    body = v.read_body()
    case_id = v.req_str(body, "workup_case_id", 1)
    center_id = v.req_str(body, "collection_center_id", 1)
    start_at = v.req_instant(body, "start_at")
    expected_version = v.req_int(body, "expected_workup_case_version", 0)

    case = find(db.workup_cases, case_id, "ERR_WORKUP_CASE_NOT_FOUND")
    center = find(db.centers, center_id, "ERR_COLLECTION_CENTER_NOT_FOUND")

    if center["id"] != actor.user_id:
        raise ApiError("ERR_CENTER_SCOPE_VIOLATION")

    if case["case_status"] != "OPEN":
        raise ApiError("ERR_WORKUP_CASE_NOT_OPEN")
    if case["collection_method"] is None:
        raise ApiError("ERR_METHOD_NOT_DECIDED")
    if case["clearance_status"] != "CLEARED":
        raise ApiError("ERR_CLEARANCE_NOT_COMPLETE")
    if expected_version != case["version"]:
        raise ApiError("ERR_STALE_WORKUP_VERSION")

    method = case["collection_method"]
    duration = calc.METHOD_DURATION_MINUTES[method]
    end_at = start_at + timedelta(minutes=duration)
    collection_date = start_at.astimezone(timezone.utc).date()

    panel = cascades.clearance_item(case["id"], "IDM_PANEL")
    if panel is None or panel["expires_at"] is None:
        raise ApiError("ERR_IDM_RESULT_EXPIRED")
    if collection_date > panel["expires_at"].astimezone(timezone.utc).date():
        raise ApiError("ERR_IDM_RESULT_EXPIRED")

    patient = cascades.patient_of_case(case)
    if patient is None or patient["conditioning_status"] not in ("SCHEDULED",
                                                                "STARTED") \
            or patient["conditioning_start_date"] is None:
        raise ApiError("ERR_COLLECTION_OUTSIDE_CONDITIONING_WINDOW")
    window_from = patient["conditioning_start_date"] + timedelta(
        days=calc.CONDITIONING_TO_COLLECTION_MIN_DAYS)
    window_to = patient["conditioning_start_date"] + timedelta(
        days=calc.CONDITIONING_TO_COLLECTION_MAX_DAYS)
    if not (window_from <= collection_date <= window_to):
        raise ApiError("ERR_COLLECTION_OUTSIDE_CONDITIONING_WINDOW")

    overlapping = 0
    for existing in db.bookings.values():
        if existing["collection_center_id"] != center["id"]:
            continue
        if existing["status"] not in calc.BOOKING_COMMITTED_STATUSES:
            continue
        if calc.buffered_overlap(start_at, end_at,
                                 existing["start_at"], existing["end_at"]):
            overlapping += 1
    if overlapping >= center["concurrent_collection_capacity"]:
        raise ApiError("ERR_CENTER_SLOT_CONFLICT")

    for existing in cascades.case_bookings(case["id"]):
        if existing["status"] == "HELD":
            existing["status"] = "SUPERSEDED"
            existing["cancel_reason"] = SUPERSEDE_REASON
            touch(existing)

    row = new_row(
        workup_case_id=case["id"],
        collection_center_id=center["id"],
        method=method,
        start_at=start_at,
        end_at=end_at,
        duration_minutes=duration,
        collection_date=collection_date,
        status="HELD",
        confirmed_at=None,
        cancel_reason=None,
    )
    db.bookings[row["id"]] = row

    case["logistics_status"] = "BOOKED"
    touch(case)

    return success(serializers.booking_dict(row), 201)


@bp.post("/registry/collection-bookings/<bid>/confirm")
def confirm_booking(bid):
    actor = authenticate(ROLE_CENTER)
    booking = find(db.bookings, bid, "ERR_BOOKING_NOT_FOUND")
    if booking["collection_center_id"] != actor.user_id:
        raise ApiError("ERR_CENTER_SCOPE_VIOLATION")
    if booking["status"] != "HELD":
        raise ApiError("ERR_BOOKING_NOT_HELD")

    case = db.workup_cases.get(booking["workup_case_id"])
    candidate = cascades.candidate_of(case) if case else None
    donor = cascades.donor_of_candidate(candidate) if candidate else None

    date_from, date_to = calc.collection_window_dates(booking["collection_date"],
                                                      booking["method"])
    if donor is not None:
        for window in cascades.active_windows(donor["id"]):
            if calc.windows_conflict(date_from, date_to,
                                     window["date_from"], window["date_to"]):
                raise ApiError("ERR_DONOR_CALENDAR_CONFLICT")

    booking["status"] = "CONFIRMED"
    booking["confirmed_at"] = db.now()
    touch(booking)
    if donor is not None:
        cascades.create_window(donor, date_from, date_to, "COLLECTION_WINDOW",
                               booking["id"])
    return success(serializers.booking_dict(booking))


@bp.post("/registry/collection-bookings/<bid>/cancel")
def cancel_booking(bid):
    actor = authenticate(ROLE_CENTER, ROLE_DIRECTOR)
    body = v.read_body()
    reason = v.req_str(body, "reason", 1)

    booking = find(db.bookings, bid, "ERR_BOOKING_NOT_FOUND")
    if actor.is_center and booking["collection_center_id"] != actor.user_id:
        raise ApiError("ERR_CENTER_SCOPE_VIOLATION")

    if booking["status"] not in ("HELD", "CONFIRMED") or \
            cascades.booking_shipments(booking["id"]):
        raise ApiError("ERR_BOOKING_NOT_CANCELLABLE")

    cascades.cancel_booking(booking, reason)
    case = db.workup_cases.get(booking["workup_case_id"])
    if case is not None:
        cascades.revert_logistics_when_unbooked(case)
    return success(serializers.booking_dict(booking))


# ------------------------------------------------------------- shipments ----
@bp.get("/registry/collection-bookings/<bid>/shipments")
def list_shipments(bid):
    authenticate(ROLE_CENTER, ROLE_OPS, ROLE_DIRECTOR, ROLE_COORDINATOR)
    limit, offset = read_pagination()
    find(db.bookings, bid, "ERR_BOOKING_NOT_FOUND")
    status = arg("status")
    rows = []
    for row in db.shipments.values():
        if row["collection_booking_id"] != bid:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return render_list(rows, serializers.shipment_dict, limit, offset)


@bp.post("/registry/collection-bookings/<bid>/shipments")
def create_shipment(bid):
    actor = authenticate(ROLE_CENTER)
    body = v.read_body()
    cd34 = v.req_num(body, "collected_cd34_e6_per_kg", gt=0, max_dp=2)
    volume = v.req_num(body, "collected_volume_ml", gt=0, max_dp=1)
    courier = v.req_str(body, "courier_reference", 1, 40)

    booking = find(db.bookings, bid, "ERR_BOOKING_NOT_FOUND")
    if booking["collection_center_id"] != actor.user_id:
        raise ApiError("ERR_CENTER_SCOPE_VIOLATION")
    if booking["status"] != "CONFIRMED" or cascades.booking_shipments(bid):
        raise ApiError("ERR_BOOKING_NOT_CONFIRMED")

    case = db.workup_cases.get(booking["workup_case_id"])
    patient = cascades.patient_of_case(case) if case else None
    if patient is None or patient["conditioning_status"] != "STARTED":
        raise ApiError("ERR_CONDITIONING_NOT_STARTED")

    collected_at = db.now()
    row = new_row(
        collection_booking_id=booking["id"],
        collected_at=collected_at,
        collected_cd34_e6_per_kg=cd34,
        collected_volume_ml=volume,
        courier_reference=courier,
        must_infuse_by=collected_at + timedelta(
            hours=calc.VIABILITY_HOURS[booking["method"]]),
        dose_adequacy="ADEQUATE" if cd34 >= calc.MIN_CD34_E6_PER_KG
        else "INADEQUATE",
        status="SCHEDULED",
        departed_at=None,
        delivered_at=None,
        transit_event_count=0,
    )
    db.shipments[row["id"]] = row

    booking["status"] = "COMPLETED"
    touch(booking)
    candidate = cascades.candidate_of(case)
    if candidate is not None:
        candidate["status"] = "COLLECTED"
        touch(candidate)
    case["logistics_status"] = "COLLECTED"
    touch(case)
    return success(serializers.shipment_dict(row), 201)


@bp.get("/registry/shipments/<sid>")
def get_shipment(sid):
    authenticate(ROLE_CENTER, ROLE_OPS, ROLE_DIRECTOR, ROLE_COORDINATOR)
    row = find(db.shipments, sid, "ERR_SHIPMENT_NOT_FOUND")
    return success(serializers.shipment_dict(row))


@bp.post("/registry/shipments/<sid>/events")
def shipment_event(sid):
    actor = authenticate(ROLE_CENTER, ROLE_OPS)
    body = v.read_body()
    event_type = v.req_enum(body, "event_type", EVENT_TYPES)
    v.opt_str(body, "note", 0, 400)

    shipment = find(db.shipments, sid, "ERR_SHIPMENT_NOT_FOUND")
    booking = db.bookings.get(shipment["collection_booking_id"])
    if actor.is_center and (booking is None or
                            booking["collection_center_id"] != actor.user_id):
        raise ApiError("ERR_CENTER_SCOPE_VIOLATION")

    if event_type == "DEPARTED":
        if shipment["status"] != "SCHEDULED":
            raise ApiError("ERR_SHIPMENT_EVENT_NOT_ALLOWED")
    elif shipment["status"] != "IN_TRANSIT":
        raise ApiError("ERR_SHIPMENT_EVENT_NOT_ALLOWED")

    case = db.workup_cases.get(booking["workup_case_id"]) if booking else None
    shipment["transit_event_count"] += 1

    if event_type == "DEPARTED":
        shipment["status"] = "IN_TRANSIT"
        shipment["departed_at"] = db.now()
        if case is not None:
            case["logistics_status"] = "IN_TRANSIT"
            touch(case)
    elif event_type == "DELIVERED":
        shipment["delivered_at"] = db.now()
        if db.now() > shipment["must_infuse_by"]:
            shipment["status"] = "DISCARDED"
            if case is not None:
                case["logistics_status"] = "PRODUCT_LOST"
                touch(case)
        else:
            shipment["status"] = "DELIVERED"
            if case is not None:
                case["logistics_status"] = "DELIVERED"
                touch(case)
    else:
        shipment["status"] = "DISCARDED"
        if case is not None:
            case["logistics_status"] = "PRODUCT_LOST"
            touch(case)
    touch(shipment)
    return success(serializers.shipment_dict(shipment))


# ----------------------------------------------------------------- claims ----
@bp.get("/registry/reimbursement-claims")
def list_claims():
    authenticate(ROLE_OPS, ROLE_COORDINATOR, ROLE_DIRECTOR)
    limit, offset = read_pagination()
    case_id = arg("workup_case_id")
    patient_id = arg("patient_id")
    registry_id = arg("billing_registry_id")
    status = arg("status")
    rows = []
    for row in db.claims.values():
        if case_id is not None and row["workup_case_id"] != case_id:
            continue
        if patient_id is not None and row["patient_id"] != patient_id:
            continue
        if registry_id is not None and row["billing_registry_id"] != registry_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return render_list(rows, serializers.claim_dict, limit, offset)


@bp.get("/registry/reimbursement-claims/<cid>")
def get_claim(cid):
    authenticate(ROLE_OPS, ROLE_COORDINATOR, ROLE_DIRECTOR)
    row = find(db.claims, cid, "ERR_CLAIM_NOT_FOUND")
    return success(serializers.claim_dict(row))


@bp.post("/registry/reimbursement-claims/<cid>/finalize")
def finalize_claim(cid):
    authenticate(ROLE_OPS)
    claim = find(db.claims, cid, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] != "PROVISIONAL":
        raise ApiError("ERR_CLAIM_NOT_PROVISIONAL")

    case = db.workup_cases.get(claim["workup_case_id"])
    finalizable = False
    if case is not None:
        if case["case_status"] == "COMPLETED":
            finalizable = True
        else:
            for booking in cascades.case_bookings(case["id"]):
                if booking["status"] == "CANCELLED" and \
                        booking["confirmed_at"] is not None:
                    finalizable = True
    if not finalizable:
        raise ApiError("ERR_CLAIM_NOT_FINALIZABLE")

    claim_engine.apply_final(claim, case)
    return success(serializers.claim_dict(claim))
