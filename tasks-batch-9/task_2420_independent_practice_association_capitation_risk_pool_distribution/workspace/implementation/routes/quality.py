"""Quality scorecards (PRD 3.8)."""

from flask import Blueprint

import calc
import db
import middleware
import resolve
import response
import serialize
import validate
from errors import fail

bp = Blueprint("quality", __name__)

SCORECARD_STATES = ("DRAFT", "FINAL", "SUPERSEDED")
READ_ROLES = ("IpaAdmin", "NetworkManager", "PayerRepresentative", "PhysicianUser")
FINALISABLE_CREDENTIALS = ("ACTIVE", "NOTICE_GIVEN")


@bp.post("/ipa/quality-scorecards")
def create_scorecard():
    user_id, role = middleware.require("IpaAdmin", "PayerRepresentative")
    body = validate.body()
    physician_id = validate.req_str(body, "physician_id")
    measurement_period = validate.req_measurement_period(body)
    hedis_composite_bps = validate.req_int(body, "hedis_composite_bps", minimum=0,
                                           maximum=10000)
    access_score_bps = validate.req_int(body, "access_score_bps", minimum=0,
                                        maximum=10000)
    patient_experience_bps = validate.req_int(body, "patient_experience_bps", minimum=0,
                                              maximum=10000)
    attributed_member_months = validate.req_int(body, "attributed_member_months",
                                                minimum=0)
    expected_physician_version = validate.req_int(body, "expected_physician_version")

    # check 5
    physician = resolve.physician(physician_id)
    # check 6
    middleware.check_ownership(role, user_id,
                              agreement=db.agreement_of_physician(physician))
    # check 7 — optimistic concurrency on the parent physician
    if expected_physician_version != physician["version"]:
        fail("ERR_STALE_PHYSICIAN_VERSION")

    scorecard = db.create(
        db.scorecards,
        physician_id=physician["id"],
        measurement_period=measurement_period,
        hedis_composite_bps=hedis_composite_bps,
        access_score_bps=access_score_bps,
        patient_experience_bps=patient_experience_bps,
        attributed_member_months=attributed_member_months,
        composite_score_bps=0,
        withhold_release_bps=0,
        status="DRAFT",
    )

    # an earlier DRAFT for the same physician and period is superseded
    for other in db.scorecards_of_physician(physician["id"]):
        if (other["id"] != scorecard["id"]
                and other["measurement_period"] == measurement_period
                and other["status"] == "DRAFT"):
            other["status"] = "SUPERSEDED"
            db.touch(other)

    physician["latest_scorecard_period"] = measurement_period
    db.touch(physician)
    return response.ok(serialize.scorecard(scorecard), 201)


@bp.get("/ipa/physicians/<physician_id>/scorecards")
def list_physician_scorecards(physician_id):
    user_id, role = middleware.require(*READ_ROLES)
    status = validate.query_enum("status", SCORECARD_STATES)
    measurement_period = validate.query_measurement_period()
    limit, offset = validate.pagination()
    physician = resolve.physician(physician_id)
    middleware.check_ownership(role, user_id, physician_ids=[physician["id"]],
                              agreement=db.agreement_of_physician(physician))

    items = db.scorecards_of_physician(physician["id"])
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if measurement_period is not None:
        items = [s for s in items if s["measurement_period"] == measurement_period]
    window = validate.paginate(items, limit, offset)
    return response.ok_list([serialize.scorecard(s) for s in window], limit, offset,
                            len(items))


@bp.get("/ipa/quality-scorecards/<scorecard_id>")
def read_scorecard(scorecard_id):
    user_id, role = middleware.require(*READ_ROLES)
    scorecard = resolve.scorecard(scorecard_id)
    middleware.check_ownership(role, user_id,
                              physician_ids=[scorecard["physician_id"]],
                              agreement=db.agreement_of_scorecard(scorecard))
    return response.ok(serialize.scorecard(scorecard))


@bp.post("/ipa/quality-scorecards/<scorecard_id>/state")
def scorecard_state(scorecard_id):
    middleware.require("IpaAdmin")
    body = validate.body()
    to_state = validate.req_enum(body, "to_state", SCORECARD_STATES)
    scorecard = resolve.scorecard(scorecard_id)
    physician = db.physicians.get(scorecard["physician_id"])

    if to_state != "FINAL":
        fail("ERR_INVALID_STATE_TRANSITION")
    if scorecard["status"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION")
    if (physician is None
            or physician["credential_status"] not in FINALISABLE_CREDENTIALS):
        fail("ERR_INVALID_STATE_TRANSITION")

    composite, release = calc.quality_composite_and_withhold_release(scorecard)
    scorecard["composite_score_bps"] = composite
    scorecard["withhold_release_bps"] = release
    scorecard["status"] = "FINAL"
    db.touch(scorecard)

    for other in db.scorecards_of_physician(physician["id"]):
        if (other["id"] != scorecard["id"]
                and other["measurement_period"] == scorecard["measurement_period"]
                and other["status"] == "FINAL"):
            other["status"] = "SUPERSEDED"
            db.touch(other)

    physician["quality_composite_bps"] = composite
    db.touch(physician)
    return response.ok(serialize.scorecard(scorecard))
