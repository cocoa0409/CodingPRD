"""Travel protection: quote, review, waiver, bind (PRD section 3.8)."""

from flask import Blueprint

import core
import response
from db import db, lock
from errors import err
from middleware import (ROLE_FINANCE_CONTROLLER, ROLE_PROGRAM_MANAGER,
                        ROLE_PROTECTION_ADMINISTRATOR, authorize)
from validate import (apply_filters, body_of, opt_bool, pagination, req_bool, req_enum, req_id,
                      req_int)

bp = Blueprint("protections", __name__)

READ_ROLES = (ROLE_PROTECTION_ADMINISTRATOR, ROLE_PROGRAM_MANAGER, ROLE_FINANCE_CONTROLLER)
BLOCKING_STATUSES = ("QUOTED", "MEDICAL_REVIEWED", "PURCHASED")


def _load(protection_id):
    row = db.protections.get(protection_id)
    if row is None:
        err("ERR_PROTECTION_NOT_FOUND", "Travel protection %s does not exist." % protection_id)
    return row


@bp.route("/travel-protections", methods=["POST"])
def create_protection():
    authorize((ROLE_PROTECTION_ADMINISTRATOR,))
    body = body_of()
    with lock:
        pilgrim_id = req_id(body, "pilgrim_id")
        plan_code = req_enum(body, "plan_code", core.PROTECTION_PLAN_CODES)
        medical_limit_cents = req_int(body, "medical_limit_cents", 100000)
        pre_existing_waiver_requested = opt_bool(body, "pre_existing_waiver_requested", False)

        pilgrim = db.pilgrims.get(pilgrim_id)
        if pilgrim is None:
            err("ERR_PILGRIM_NOT_FOUND", "Pilgrim %s does not exist." % pilgrim_id)
        if pilgrim["booking_status"] not in ("INQUIRY", "DEPOSITED", "CONFIRMED"):
            err("ERR_PILGRIM_NOT_ACTIVE", "A cancelled traveler cannot be insured.")
        for other in core.protections_of_pilgrim(pilgrim_id):
            if other["status"] in BLOCKING_STATUSES:
                err("ERR_PROTECTION_INVALID_STATE",
                    "The traveler already holds a protection record in %s." % other["status"])

        deposit_reference_date = pilgrim.get("_deposit_date")
        row = core.base_row()
        row.update({
            "pilgrim_id": pilgrim_id,
            "plan_code": plan_code,
            "medical_limit_cents": medical_limit_cents,
            "pre_existing_waiver_requested": pre_existing_waiver_requested,
            "insured_trip_cost_cents": 0,
            "age_band": "A",
            "base_premium_cents": 0,
            "medical_uplift_cents": 0,
            "waiver_surcharge_cents": 0,
            "premium_cents": 0,
            "questionnaire_complete": False,
            "stable_period_days": 0,
            "medical_review_by_user_id": None,
            "waiver_eligible": False,
            "status": "QUOTED",
            "deposit_reference_date": (core.date_str(deposit_reference_date)
                                       if deposit_reference_date else None),
        })
        db.protections[row["id"]] = row

        pilgrim_before = core.snap(pilgrim)
        pilgrim["protection_status"] = "QUOTED"
        core.recompute_premium(row)
        core.touch_if_changed(pilgrim, pilgrim_before)
        return response.ok(core.serialize(row), 201)


@bp.route("/travel-protections/<protection_id>", methods=["GET"])
def get_protection(protection_id):
    authorize(READ_ROLES)
    with lock:
        return response.ok(core.serialize(_load(protection_id)))


@bp.route("/travel-protections", methods=["GET"])
def list_protections():
    authorize(READ_ROLES)
    with lock:
        limit, offset = pagination()
        rows = core.order_rows(list(db.protections.values()))
        rows = apply_filters(rows, {
            "pilgrim_id": "pilgrim_id",
            "status": "status",
        })
        page, total = core.paginate(rows, limit, offset)
        return response.ok_list([core.serialize(r) for r in page], limit, offset, total)


@bp.route("/travel-protections/<protection_id>/medical-review", methods=["POST"])
def medical_review(protection_id):
    caller = authorize((ROLE_PROTECTION_ADMINISTRATOR,))
    body = body_of()
    with lock:
        protection = _load(protection_id)
        questionnaire_complete = req_bool(body, "questionnaire_complete")
        stable_period_days = req_int(body, "stable_period_days", 0)

        pilgrim = db.pilgrims[protection["pilgrim_id"]]
        if pilgrim["booking_status"] == "CANCELLED":
            err("ERR_PILGRIM_NOT_ACTIVE", "A cancelled traveler's protection cannot be reviewed.")
        if protection["status"] != "QUOTED":
            err("ERR_PROTECTION_INVALID_STATE", "Only a QUOTED record can be medically reviewed.")

        protection["questionnaire_complete"] = questionnaire_complete
        protection["stable_period_days"] = stable_period_days
        protection["medical_review_by_user_id"] = caller.user_id
        protection["status"] = "MEDICAL_REVIEWED"

        pilgrim_before = core.snap(pilgrim)
        pilgrim["protection_status"] = "MEDICAL_REVIEWED"
        core.recompute_waiver_eligibility(protection)
        core.recompute_premium(protection)
        core.touch(protection)
        core.touch_if_changed(pilgrim, pilgrim_before)
        return response.ok(core.serialize(protection))


@bp.route("/travel-protections/<protection_id>/waiver-decision", methods=["POST"])
def waiver_decision(protection_id):
    caller = authorize((ROLE_PROTECTION_ADMINISTRATOR,))
    body = body_of()
    with lock:
        protection = _load(protection_id)
        reviewer = protection["medical_review_by_user_id"]
        if reviewer is not None and reviewer == caller.user_id:
            err("ERR_SEGREGATION_OF_DUTIES",
                "The medical reviewer may not decide the waiver.")
        decision = req_enum(body, "decision", core.WAIVER_DECISIONS)

        pilgrim = db.pilgrims[protection["pilgrim_id"]]
        if pilgrim["booking_status"] == "CANCELLED":
            err("ERR_PILGRIM_NOT_ACTIVE", "A cancelled traveler's waiver cannot be decided.")
        if protection["status"] != "MEDICAL_REVIEWED":
            err("ERR_PROTECTION_INVALID_STATE",
                "A waiver decision requires a MEDICAL_REVIEWED record.")

        core.recompute_waiver_eligibility(protection)
        if decision == "APPROVE":
            reference = protection["deposit_reference_date"]
            if reference is not None:
                days = core.whole_days(core.clock_date(), core.as_date(reference))
                if days > core.WAIVER_PURCHASE_WINDOW_DAYS:
                    err("ERR_WAIVER_WINDOW_CLOSED",
                        "The post-deposit waiver purchase window has closed.")
            if not protection["waiver_eligible"]:
                err("ERR_WAIVER_NOT_ELIGIBLE",
                    "The traveler does not meet the pre-existing condition waiver conditions.")
            protection["status"] = "WAIVER_APPROVED"
            new_pilgrim_status = "WAIVER_APPROVED"
        else:
            protection["status"] = "WAIVER_DECLINED"
            new_pilgrim_status = "WAIVER_DECLINED"

        pilgrim_before = core.snap(pilgrim)
        pilgrim["protection_status"] = new_pilgrim_status
        core.recompute_premium(protection)
        if decision == "DECLINE":
            protection["waiver_surcharge_cents"] = 0
            protection["premium_cents"] = (protection["base_premium_cents"]
                                           + protection["medical_uplift_cents"])
        core.touch(protection)
        core.touch_if_changed(pilgrim, pilgrim_before)
        return response.ok(core.serialize(protection))


@bp.route("/travel-protections/<protection_id>/purchase", methods=["POST"])
def purchase(protection_id):
    authorize((ROLE_PROTECTION_ADMINISTRATOR,))
    with lock:
        protection = _load(protection_id)
        pilgrim = db.pilgrims[protection["pilgrim_id"]]
        if pilgrim["booking_status"] == "CANCELLED":
            err("ERR_PILGRIM_NOT_ACTIVE", "A cancelled traveler's protection cannot be bound.")
        if protection["status"] not in ("QUOTED", "WAIVER_APPROVED", "WAIVER_DECLINED"):
            err("ERR_PROTECTION_INVALID_STATE",
                "A %s record cannot be purchased." % protection["status"])
        if protection["pre_existing_waiver_requested"] and protection["status"] == "QUOTED":
            err("ERR_PROTECTION_INVALID_STATE",
                "A requested waiver must be reviewed and decided before purchase.")

        # The premium is re-derived before the traveler's protection_status is
        # mirrored, so a declined waiver keeps its zero surcharge.
        core.recompute_premium(protection)
        protection["status"] = "PURCHASED"
        core.touch(protection)

        pilgrim_before = core.snap(pilgrim)
        pilgrim["protection_status"] = "PURCHASED"
        pilgrim["protection_premium_cents"] = protection["premium_cents"]
        core.touch_if_changed(pilgrim, pilgrim_before)
        return response.ok(core.serialize(protection))
