"""Shared side effects: escrow dispositions, title supersession, attempt
release, referral synthesis and the substantiation cascade."""

import db
from services import calc, derive


# ------------------------------------------------------------------- escrow


def capture_escrow(application, rebuilder):
    """Title issued or final denial: the escrow becomes consumed."""
    amount = application["fee_escrowed_cents"]
    if amount:
        rebuilder["fees_consumed_cents"] = rebuilder["fees_consumed_cents"] + amount
    application["fee_escrowed_cents"] = 0


def refund_escrow(application, rebuilder):
    """Withdrawal or fraud void: the escrow becomes spendable again."""
    application["fee_escrowed_cents"] = 0


# -------------------------------------------------------------------- titles


def _end_pending_recognition(title):
    for request in derive.recognitions_of_title(title["id"]):
        if request["status"] == "PENDING":
            request["status"] = "SUPERSEDED"
            db.touch(request)


def leave_active(title, new_status):
    """Drive a title out of ACTIVE, carrying the recognition dimension with it."""
    title["status"] = new_status
    title["is_current"] = False
    if title["recognition_state"] == "RECOGNITION_PENDING":
        title["recognition_state"] = "STALE"
        _end_pending_recognition(title)
    derive.recompute_title(title, touch_row=False)
    db.touch(title)


# ---------------------------------------------------------------- attempts


def cancel_attempt(inspection, reason):
    inspection["status"] = "CANCELLED"
    inspection["cancellation_reason"] = reason
    derive.recompute_inspection(inspection, touch_row=False)
    db.touch(inspection)
    inspector = db.db.inspectors.get(inspection["inspector_id"])
    station = db.db.stations.get(inspection["station_id"])
    if inspector is not None:
        derive.recompute_inspector(inspector, touch_row=True)
    if station is not None:
        derive.recompute_station(station, touch_row=True)


# ---------------------------------------------------------------- licensing


def apply_license_cascades(rebuilder):
    """Referral counters can move a licence on their own."""
    derive.recompute_rebuilder(rebuilder, touch_row=False)
    changed = False
    if (
        rebuilder["substantiated_referral_count"] >= calc.SUSPEND_SUBSTANTIATED_THRESHOLD
        and rebuilder["license_status"] in ("ACTIVE", "PROBATION")
    ):
        rebuilder["license_status"] = "SUSPENDED"
        changed = True
    elif (
        rebuilder["open_referral_count"] >= calc.PROBATION_REFERRAL_THRESHOLD
        and rebuilder["license_status"] == "ACTIVE"
    ):
        rebuilder["license_status"] = "PROBATION"
        changed = True
    return changed


def open_referral(vehicle, referral_type, origin, opened_by_user_id, evidence_summary,
                  application_id=None, inspection_id=None):
    row = db.new_row()
    row.update(
        {
            "vehicle_id": vehicle["id"],
            "application_id": application_id,
            "inspection_id": inspection_id,
            "referral_type": referral_type,
            "origin": origin,
            "status": "OPEN",
            "evidence_summary": evidence_summary,
            "opened_by_user_id": opened_by_user_id,
            "investigator_user_id": None,
            "resolved_at": None,
        }
    )
    db.db.referrals[row["id"]] = row
    derive.recompute_vehicle(vehicle, touch_row=True)
    if application_id:
        application = db.db.applications.get(application_id)
        if application is not None:
            rebuilder = db.db.rebuilders.get(application["rebuilder_id"])
            if rebuilder is not None:
                changed = apply_license_cascades(rebuilder)
                derive.recompute_rebuilder(rebuilder, touch_row=not changed)
                if changed:
                    db.touch(rebuilder)
    return row


def substantiation_cascade(referral):
    """Everything a substantiated referral drags with it, in one request."""
    vehicle = db.db.vehicles.get(referral["vehicle_id"])
    if vehicle is None:
        return
    derive.recompute_vehicle(vehicle, touch_row=True)

    for title in derive.titles_of_vehicle(vehicle["id"]):
        if title["status"] == "ACTIVE":
            leave_active(title, "VOID")

    # a conveyance only ever becomes VOID because the chain it sits on was voided
    for transfer in derive.transfers_of_vehicle(vehicle["id"]):
        if transfer["status"] == "RECORDED":
            transfer["status"] = "VOID"
            db.touch(transfer)

    touched_rebuilders = {}
    # the referral's own application decides whose substantiated counter moves
    if referral.get("application_id"):
        owning = db.db.applications.get(referral["application_id"])
        if owning is not None:
            owner = db.db.rebuilders.get(owning["rebuilder_id"])
            if owner is not None:
                touched_rebuilders[owner["id"]] = owner
    for application in derive.apps_of_vehicle(vehicle["id"]):
        if application["status"] in derive.TERMINAL_APP:
            continue
        rebuilder = db.db.rebuilders.get(application["rebuilder_id"])
        for inspection in derive.inspections_of_app(application["id"]):
            if inspection["status"] in ("SCHEDULED", "IN_PROGRESS"):
                cancel_attempt(inspection, "FRAUD_HOLD")
        if rebuilder is not None:
            refund_escrow(application, rebuilder)
            touched_rebuilders[rebuilder["id"]] = rebuilder
        else:
            application["fee_escrowed_cents"] = 0
        application["status"] = "VOID_FRAUD"
        application["terminal_at"] = db.now_iso()
        derive.recompute_application(application, touch_row=False)
        db.touch(application)

    for rebuilder in touched_rebuilders.values():
        changed = apply_license_cascades(rebuilder)
        derive.recompute_rebuilder(rebuilder, touch_row=not changed)
        if changed:
            db.touch(rebuilder)

    derive.recompute_vehicle(vehicle, touch_row=True)
