"""Paid-promotion disclosure filing, ruling and remediation."""

from flask import Blueprint

import calc
import domain
import validation as V
from auth import require
from envelope import created, ok
from errors import ApiError
from store import db, new_record, touch

bp = Blueprint("disclosures", __name__)


def _chain(record):
    deliverable = db.deliverables.get(record["deliverable_id"])
    engagement = db.engagements.get(deliverable["engagement_id"]) if deliverable else None
    opportunity = db.opportunities.get(engagement["opportunity_id"]) if engagement else None
    return deliverable, engagement, opportunity


def _resync_athlete(engagement):
    athlete = db.athletes.get(engagement["athlete_id"]) if engagement else None
    if athlete is not None:
        domain.refresh_exposure_snapshot(athlete)
        touch(athlete)


@bp.post("/disclosure-records")
def create_disclosure():
    caller = require("Athlete")
    payload = V.body()
    deliverable_id = V.id_field(payload, "deliverable_id")
    platform = V.enum_field(payload, "platform", calc.PLATFORMS)
    disclosure_tag = V.str_field(payload, "disclosure_tag")
    posted_raw, _posted = V.datetime_field(payload, "posted_at")

    deliverable = domain.must_get("deliverables", deliverable_id)
    engagement = db.engagements[deliverable["engagement_id"]]

    if caller.user_id != engagement["athlete_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "caller is not the athlete on this engagement")

    live = [r for r in domain.deliverable_disclosures(deliverable_id)
            if r["status"] in ("PENDING_REVIEW", "COMPLIANT")]
    if live:
        raise ApiError("ERR_DUPLICATE_DISCLOSURE",
                       "a live disclosure record already exists for this deliverable")

    record = new_record({
        "deliverable_id": deliverable_id,
        "platform": platform,
        "disclosure_tag": disclosure_tag,
        "posted_at": posted_raw,
        "ruled_by_user_id": None,
        "finding_note": None,
        "remediation_count": 0,
        "status": "PENDING_REVIEW",
    })
    db.disclosure_records[record["id"]] = record
    return created(record)


@bp.post("/disclosure-records/<record_id>/rule")
def rule_disclosure(record_id):
    caller = require("ComplianceOfficer")
    record = domain.must_get("disclosure_records", record_id)
    payload = V.body()
    ruling = V.enum_field(payload, "ruling", calc.RULINGS)
    finding_note = V.str_field(payload, "finding_note", required=False)

    if record["status"] != "PENDING_REVIEW":
        raise ApiError("ERR_DISCLOSURE_INVALID_STATE", "record is not PENDING_REVIEW")

    _deliverable, engagement, opportunity = _chain(record)
    if opportunity is not None and opportunity.get("screened_by_user_id") is not None:
        if caller.user_id == opportunity["screened_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "the screening officer may not rule on this disclosure")

    if ruling == "COMPLIANT":
        if record["disclosure_tag"] not in calc.ACCEPTED_DISCLOSURE_TAGS:
            raise ApiError("ERR_DISCLOSURE_NOT_COMPLIANT",
                           "the disclosure tag is not an accepted marker")

    record["status"] = ruling
    record["ruled_by_user_id"] = caller.user_id
    record["finding_note"] = finding_note
    touch(record)

    _resync_athlete(engagement)
    return ok(record)


@bp.post("/disclosure-records/<record_id>/remediate")
def remediate_disclosure(record_id):
    caller = require("Athlete")
    record = domain.must_get("disclosure_records", record_id)
    payload = V.body()
    disclosure_tag = V.str_field(payload, "disclosure_tag")
    posted_raw, _posted = V.datetime_field(payload, "posted_at")

    _deliverable, engagement, _opportunity = _chain(record)
    if engagement is not None and caller.user_id != engagement["athlete_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "caller is not the athlete on this engagement")

    if record["status"] != "NON_COMPLIANT":
        raise ApiError("ERR_DISCLOSURE_INVALID_STATE", "record is not NON_COMPLIANT")

    record["disclosure_tag"] = disclosure_tag
    record["posted_at"] = posted_raw
    record["remediation_count"] += 1
    record["ruled_by_user_id"] = None
    record["status"] = "PENDING_REVIEW"
    touch(record)

    _resync_athlete(engagement)
    return ok(record)
