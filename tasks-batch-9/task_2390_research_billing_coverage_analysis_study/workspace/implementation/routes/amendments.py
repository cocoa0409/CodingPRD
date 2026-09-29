"""Protocol amendments and the five-link implementation cascade."""

from flask import Blueprint

import derive
import envelope
import lookup
import serializers
import store
import validation as v
from auth import require
from errors import ApiError

bp = Blueprint("amendments", __name__, url_prefix="/research-billing")

SCOPES = ("ADMINISTRATIVE", "ITEM_CHANGE", "VISIT_SCHEDULE_CHANGE",
          "ITEM_AND_SCHEDULE_CHANGE")
REBUILD_SCOPES = ("VISIT_SCHEDULE_CHANGE", "ITEM_AND_SCHEDULE_CHANGE")


@bp.post("/amendments")
@require("ResearchBillingManager")
def create_amendment():
    body = v.body()
    study_id = v.req_id(body, "study_id")
    scope = v.req_enum(body, "scope", SCOPES)
    effective_date = v.req_date(body, "effective_date")

    study = lookup.study(study_id)

    rec = store.base_record()
    rec.update({
        "study_id": study["id"],
        "amendment_number": len(derive.amendments_of(study["id"])) + 1,
        "scope": scope,
        "effective_date": effective_date,
        "status": "SUBMITTED",
        "reanalysis_required": scope != "ADMINISTRATIVE",
        "calendar_rebuild_required": scope in REBUILD_SCOPES,
    })
    store.amendments[rec["id"]] = rec
    return envelope.created(serializers.amendment(rec))


@bp.post("/amendments/<amendment_id>/implement")
@require("ResearchBillingManager")
def implement_amendment(amendment_id):
    rec = lookup.amendment(amendment_id)
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_AMENDMENT_NOT_SUBMITTED")

    study = lookup.study(rec["study_id"])
    if study["lifecycle_status"] not in ("COVERAGE_APPROVED", "OPEN_TO_ACCRUAL"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    if rec["effective_date"] > store.today():
        raise ApiError("ERR_AMENDMENT_NOT_YET_EFFECTIVE")

    # link 1
    rec["status"] = "IMPLEMENTED"
    store.touch(rec)

    # link 2
    if rec["reanalysis_required"]:
        study["lifecycle_status"] = "COVERAGE_PENDING"
        if study["budget_status"] == "EXECUTED":
            study["budget_status"] = "SUPERSEDED"

    # link 3 / 4
    rebuilt = 0
    if rec["reanalysis_required"] and rec["calendar_rebuild_required"]:
        for calendar in derive.calendars_of(study["id"]):
            if calendar["status"] == "PUBLISHED":
                calendar["status"] = "REBUILD_REQUIRED"
                store.touch(calendar)
                rebuilt += 1

    # link 5
    if rebuilt >= 1:
        for charge in derive.charges_of(study["id"]):
            if charge["billing_state"] == "UNBILLED" and charge["routing_state"] == "UNROUTED":
                charge["hold_reason"] = "CALENDAR_REBUILD"
                charge["hold_applied_at"] = store.now()
                store.touch(charge)

    store.touch(study)
    return envelope.ok(serializers.amendment(rec))
