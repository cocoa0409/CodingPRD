from flask import Blueprint, g, request

import cardsvc
import cascades
import constants as C
import derive
import fees
import serializers
import subsvc
import validation as V
from envelope import object_response, paginate
from errors import ApiError
from lookups import (agency_of_ori, body_row, check_billing_freeze, check_ori_authority,
                     check_parent_version, check_segregation, freeze_for_site, path_row,
                     require_card_state, require_record_state)
from store import db

bp = Blueprint("submissions", __name__)


@bp.post("/livescan/submissions")
def transmit():
    data = V.body()
    card = body_row("cards", data["card_id"]) if data.get("card_id") else None
    retention_requested = V.req_bool(data, "retention_requested")
    expected_card_version = V.req_int(data, "expected_card_version")
    if card is None:
        V.bad_request("card_id is required")

    appointment = db.appointments[card["appointment_id"]]
    service_type = db.service_types[appointment["service_type_id"]]
    ori = db.oris[service_type["ori_id"]]
    site = db.sites[card["site_id"]]
    agency = agency_of_ori(ori)

    check_billing_freeze(agency, freeze_for_site(site))
    check_ori_authority(ori)
    check_parent_version(card, expected_card_version)
    require_card_state(card, ("READY_FOR_SUBMISSION",))

    if retention_requested and not (
        ori["retention_permitted"] and service_type["retention_offered"]
    ):
        raise ApiError("ERR_RETENTION_NOT_PERMITTED", "retention is not permitted here")

    if card["reprint_of_submission_id"] is not None:
        original = db.submissions[card["reprint_of_submission_id"]]
        if bool(retention_requested) != bool(original["retention_requested"]):
            raise ApiError(
                "ERR_RETENTION_IMMUTABLE", "the retention election may not change on a reprint"
            )

    submission = subsvc.create_submission(card, ori, retention_requested)

    card["status"] = "SUBMITTED"
    db.touch(card)
    if appointment["status"] == "IN_CAPTURE":
        appointment["status"] = "COMPLETED"
        db.touch(appointment)
    cardsvc.recompute_site_billable(site)

    kind = "REPRINT" if card["reprint_of_submission_id"] is not None else "SUBMISSION"
    fees.create_transmission_assessment(
        kind, agency, submission, appointment, service_type, site, card
    )
    return object_response(serializers.submission(submission), 201)


@bp.get("/livescan/submissions/<id>")
def read_submission(id):
    return object_response(serializers.submission(path_row("submissions", id)))


@bp.get("/livescan/submissions")
def list_submissions():
    rows = list(db.submissions.values())
    for field in ("card_id", "ori_id", "original_submission_id", "state_status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    disposition = request.args.get("composite_disposition")
    if disposition is not None:
        rows = [r for r in rows if derive.composite_disposition(r) == disposition]
    return paginate(rows, serializers.submission)


@bp.post("/livescan/submissions/<id>/destination-results")
def destination_result(id):
    submission = path_row("submissions", id)
    data = V.body()
    destination = V.req_string(data, "destination")
    result_code = V.req_string(data, "result_code")
    record_count = V.opt_int(data, "record_count", default=0, minimum=0, maximum=99)
    disqualifying = V.opt_int(
        data, "disqualifying_offense_count", default=0, minimum=0, maximum=99
    )
    record_detail = V.opt_string(data, "record_detail")
    V.opt_string(data, "rejection_reason")
    if disqualifying > record_count:
        V.bad_request("disqualifying_offense_count may not exceed record_count")

    V.enum_value("destination", destination, C.DESTINATIONS)
    V.enum_value("result_code", result_code, C.RESULT_CODES)

    axis = "state_status" if destination == "STATE" else "fbi_status"
    current = submission[axis]
    # rung 10 carve-out (a): NOT_REQUIRED is ignored here; the rung fires only
    # when the named axis has already reached a terminal value.
    if current in ("ACCEPTED", "REJECTED_TECHNICAL", "REJECTED_ADMIN"):
        raise ApiError("ERR_RECORD_STATE_INVALID", "%s already resulted" % destination)

    if destination not in submission["destinations"]:
        raise ApiError("ERR_DESTINATION_NOT_AUTHORIZED", "%s is not a destination" % destination)

    submission[axis] = result_code
    stamp = "state_resulted_at" if destination == "STATE" else "fbi_resulted_at"
    submission[stamp] = db.now()

    if result_code == "ACCEPTED":
        subsvc.create_and_route_response(
            submission, destination, record_count, disqualifying, record_detail
        )
    subsvc.sync_composite(submission)
    db.touch(submission)
    subsvc.close_card_when_complete(submission)
    return object_response(serializers.submission(submission), 201)


@bp.get("/livescan/submissions/<id>/responses")
def list_responses(id):
    submission = path_row("submissions", id)
    rows = [r for r in db.chr_responses.values() if r["submission_id"] == submission["id"]]
    destination = request.args.get("destination")
    if destination is not None:
        rows = [r for r in rows if r["destination"] == destination]
    # Friction point 3: the submission-scoped listing declares no projection and
    # the StateRepository role appears in no projection mapping, so the stored
    # rows are returned unprojected here.
    return paginate(rows, serializers.chr_response)


@bp.post("/livescan/submissions/<id>/reprints")
def authorize_reprint(id):
    submission = path_row("submissions", id)
    data = V.body()
    device_id = V.req_string(data, "device_id")
    device = body_row("devices", device_id)

    ori = db.oris[submission["ori_id"]]
    original_card = db.cards.get(submission["card_id"])
    site = db.sites.get(original_card["site_id"]) if original_card else None

    check_billing_freeze(agency_of_ori(ori), freeze_for_site(site))
    check_ori_authority(ori)
    if original_card is not None and original_card["status"] == "SUPERSEDED":
        require_card_state(original_card, ("SUBMITTED", "REJECTED_CLOSED"))

    rejected = [
        submission["state_status"] in ("REJECTED_TECHNICAL", "REJECTED_ADMIN"),
        submission["fbi_status"] in ("REJECTED_TECHNICAL", "REJECTED_ADMIN"),
    ]
    if not any(rejected):
        raise ApiError("ERR_REPRINT_NOT_ENTITLED", "no destination rejected this transmission")
    if submission["reprint_count"] >= C.REPRINT_MAX_PER_SUBMISSION:
        raise ApiError("ERR_REPRINT_LIMIT_REACHED", "three reprints already authorized")

    replacement = cascades.authorize_reprint(submission, device, g.user_id)
    return object_response(serializers.card(replacement), 201)


@bp.post("/livescan/submissions/<id>/purge-requests")
def purge_request(id):
    submission = path_row("submissions", id)
    data = V.body()
    V.req_string(data, "reason")

    require_record_state(
        submission["retention_status"] in ("GRANTED", "PURGE_DENIED"),
        "retention_status is %s" % submission["retention_status"],
    )

    submission["retention_status"] = "PURGE_REQUESTED"
    submission["purge_requested_at"] = db.now()
    submission["purge_requested_by_user_id"] = g.user_id
    submission["purge_decided_by_user_id"] = None
    db.touch(submission)
    return object_response(serializers.submission(submission))


@bp.post("/livescan/submissions/<id>/purge-decisions")
def purge_decision(id):
    submission = path_row("submissions", id)
    data = V.body()
    decision = V.req_string(data, "decision")
    V.enum_value("decision", decision, C.PURGE_DECISIONS)

    require_record_state(
        submission["retention_status"] == "PURGE_REQUESTED",
        "retention_status is %s" % submission["retention_status"],
    )
    check_segregation(submission["purge_requested_by_user_id"])

    if decision == "GRANT":
        cascades.grant_purge(submission, g.user_id)
    else:
        submission["retention_status"] = "PURGE_DENIED"
        submission["purge_decided_by_user_id"] = g.user_id
        db.touch(submission)
    return object_response(serializers.submission(submission))
