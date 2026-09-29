"""Holds, the confirmation fork, release for transplant and unit disposal."""
from datetime import timedelta

from flask import Blueprint

import calc
import services as svc
from errors import fail
from middleware import (endpoint, get_body, v_date, v_enum, v_int, v_num,
                        v_str, v_ts)
from response import object_response
from store import base_row, db, iso, now, pdt, public, touch

bp = Blueprint("holds", __name__)

HOLDABLE = ("LISTED", "PRIVATE_STORED")
DISPOSAL_REASONS = ("ABANDONED_NONPAYMENT", "QUALITY_FAILURE", "MATERNAL_INELIGIBLE",
                    "CONSENT_REVOKED", "EXCURSION_LOSS")


@bp.route("/cbb/reservations", methods=["POST"])
@endpoint("TransplantCenter", "PlatformAdmin")
def place_hold(user_id, role):
    body = get_body()
    unit_id = v_str(body, "unit_id", min_len=1)
    center_name = v_str(body, "requesting_center_name", min_len=1, max_len=120)
    weight = v_num(body, "patient_weight_kg", gt=0)
    match_count = v_int(body, "patient_hla_match_count", ge=0, le=6)
    hold_from = v_ts(body, "hold_from")
    hold_until = v_ts(body, "hold_until")
    expected = v_int(body, "expected_unit_version", ge=0)
    if hold_until <= hold_from:
        fail("ERR_VALIDATION_FAILED", "hold_until must be later than hold_from.")
    unit = svc.get_unit(unit_id)

    # rung 8 -- optimistic concurrency on the unit
    if expected != unit["version"]:
        fail("ERR_STALE_UNIT_VERSION")
    # rung 9 -- the unit must be holdable
    if unit["availability_status"] not in HOLDABLE:
        fail("ERR_INVALID_UNIT_STATE")
    # rung 18 -- eligibility
    if unit["eligibility_status"] != "ELIGIBLE":
        fail("ERR_UNIT_NOT_ELIGIBLE")
    # rung 31 -- the 24-hour-buffered exclusive hold window
    buffer = timedelta(hours=calc.RESERVATION_HOLD_BUFFER_HOURS)
    incumbents = svc.unit_reservations(unit_id)
    incumbents = [r for r in incumbents
                  if r["status"] in ("PENDING_CONFIRMATORY", "CONFIRMED")]
    incumbents.sort(key=lambda r: (r["hold_from"], r["created_at"], r["_seq"]))
    for incumbent in incumbents:
        other_from = pdt(incumbent["hold_from"])
        other_until = pdt(incumbent["hold_until"])
        if hold_from < other_until + buffer and other_from < hold_until + buffer:
            fail("ERR_HOLD_WINDOW_CONFLICT")
    # rung 33 -- account standing
    account = svc.unit_account(unit)
    if account is not None and account["status"] in svc.DELINQUENT_ACCOUNT_STATES:
        fail("ERR_ACCOUNT_DELINQUENT")

    unit_tnc = unit.get("post_processing_tnc_millions")
    dose = calc.pre_cryo_dose(unit_tnc, weight) if unit_tnc else None
    row = base_row()
    row.update({
        "unit_id": unit_id,
        "superseded_by_reservation_id": None,
        "confirmatory_test_id": None,
        "requesting_center_user_id": user_id,
        "requesting_center_name": center_name,
        "patient_weight_kg": calc.num(weight),
        "patient_hla_match_count": match_count,
        "hold_from": iso(hold_from),
        "hold_until": iso(hold_until),
        "intended_transplant_date": None,
        "pre_cryo_dose_x1e7_per_kg": calc.num(dose),
        "post_thaw_dose_x1e7_per_kg": None,
        "dose_variant_applied": "PRE_CRYO",
        "settlement_total_cents": None,
        "released_at": None,
        "cancellation_reason_code": None,
        "status": "PENDING_CONFIRMATORY",
    })
    db.reservations[row["id"]] = row
    touch(unit)
    return object_response(public(row), 201)


@bp.route("/cbb/reservations/<rid>/confirm", methods=["POST"])
@endpoint("TransplantCenter", "PlatformAdmin")
def confirm_hold(user_id, role, rid):
    svc.require_tc_reservation(user_id, role, rid)
    body = get_body()
    intended = v_date(body, "intended_transplant_date")
    reservation = svc.get_reservation(rid)
    unit = db.units.get(reservation["unit_id"])

    if reservation["status"] != "PENDING_CONFIRMATORY":
        fail("ERR_INVALID_RESERVATION_STATE")
    if unit is None or unit["availability_status"] not in HOLDABLE:
        fail("ERR_INVALID_UNIT_STATE")
    if unit["eligibility_status"] != "ELIGIBLE":
        fail("ERR_UNIT_NOT_ELIGIBLE")
    deadline = pdt(reservation["created_at"]) + timedelta(
        hours=calc.CONFIRM_WINDOW_HOURS)
    if now() > deadline:
        fail("ERR_CONFIRMATION_WINDOW_EXPIRED")

    reservation["status"] = "CONFIRMED"
    reservation["intended_transplant_date"] = iso(intended)
    touch(reservation)
    unit["availability_status"] = "RESERVED"
    touch(unit)
    for listing in svc.unit_listings(unit["id"]):
        if listing["listing_status"] == "ACTIVE":
            listing["listing_status"] = "MATCHED"
            touch(listing)
    for sibling in svc.unit_reservations(unit["id"]):
        if sibling["id"] == reservation["id"]:
            continue
        if sibling["status"] == "PENDING_CONFIRMATORY":
            sibling["status"] = "DECLINED"
            sibling["cancellation_reason_code"] = "SUPERSEDED_BY_CONFIRMED_HOLD"
            sibling["superseded_by_reservation_id"] = reservation["id"]
            touch(sibling)
    return object_response(public(reservation))


@bp.route("/cbb/reservations/<rid>/decline", methods=["POST"])
@endpoint("TransplantCenter", "PlatformAdmin")
def decline_hold(user_id, role, rid):
    svc.require_tc_reservation(user_id, role, rid)
    body = get_body()
    reason = v_str(body, "reason_code", min_len=1, max_len=60)
    reservation = svc.get_reservation(rid)

    if reservation["status"] != "PENDING_CONFIRMATORY":
        fail("ERR_INVALID_RESERVATION_STATE")

    reservation["status"] = "DECLINED"
    reservation["cancellation_reason_code"] = reason
    touch(reservation)
    return object_response(public(reservation))


@bp.route("/cbb/reservations/<rid>/cancel", methods=["POST"])
@endpoint("TransplantCenter", "PlatformAdmin")
def cancel_hold(user_id, role, rid):
    svc.require_tc_reservation(user_id, role, rid)
    body = get_body()
    reason = v_str(body, "reason_code", min_len=1, max_len=60)
    reservation = svc.get_reservation(rid)

    if reservation["status"] != "CONFIRMED":
        fail("ERR_INVALID_RESERVATION_STATE")

    reservation["status"] = "CANCELLED"
    reservation["cancellation_reason_code"] = reason
    touch(reservation)
    unit = db.units.get(reservation["unit_id"])
    if unit is not None:
        if unit["availability_status"] == "RESERVED":
            unit["availability_status"] = ("LISTED"
                                          if unit["program_type"] == "PUBLIC_DONATION"
                                          else "PRIVATE_STORED")
            touch(unit)
        for listing in svc.unit_listings(unit["id"]):
            if listing["listing_status"] == "MATCHED":
                listing["listing_status"] = "ACTIVE"
                listing["suspension_reason_code"] = None
                touch(listing)
    return object_response(public(reservation))


@bp.route("/cbb/reservations/<rid>/release", methods=["POST"])
@endpoint("MedicalDirector", "PlatformAdmin")
def release_hold(user_id, role, rid):
    body = get_body()
    v_str(body, "release_note", required=False, min_len=0, max_len=500)
    reservation = svc.get_reservation(rid)

    blocking = svc.release_blocking_error(reservation, user_id)
    if blocking is not None:
        fail(blocking)

    unit = db.units.get(reservation["unit_id"])
    account = svc.unit_account(unit)
    reservation["status"] = "RELEASED"
    reservation["released_at"] = iso(now())
    reservation["dose_variant_applied"] = "POST_THAW"
    reservation["settlement_total_cents"] = svc.post_settlement(account)
    touch(reservation)

    unit["availability_status"] = "RELEASED"
    unit["disposition_reason"] = "TRANSPLANT_RELEASED"
    unit["disposed_at"] = iso(now())
    touch(unit)
    for listing in svc.unit_listings(unit["id"]):
        if listing["listing_status"] == "MATCHED":
            listing["listing_status"] = "WITHDRAWN"
            touch(listing)
    svc.recompute_occupancy(db.tanks.get(unit.get("tank_id")))
    svc.maybe_close_enrollment(svc.unit_enrollment(unit))
    return object_response(public(reservation))


@bp.route("/cbb/units/<uid>/dispose", methods=["POST"])
@endpoint("MedicalDirector", "PlatformAdmin")
def dispose_unit(user_id, role, uid):
    body = get_body()
    reason = v_enum(body, "reason", DISPOSAL_REASONS)
    v_str(body, "note", required=False, min_len=0, max_len=500)
    unit = svc.get_unit(uid)

    if unit["availability_status"] in ("RELEASED", "DISPOSED", "RESERVED"):
        fail("ERR_INVALID_UNIT_STATE")
    if reason == "ABANDONED_NONPAYMENT":
        account = svc.unit_account(unit)
        if account is None or account["status"] not in ("ABANDONMENT_NOTICE",
                                                       "ABANDONED"):
            fail("ERR_INVALID_UNIT_STATE")

    svc.dispose_unit_cascade(unit, reason)
    return object_response(public(unit))
