"""Shooting blocks and incidental releases."""

from datetime import timedelta

from flask import Blueprint

import calc
import services
import store
from clock import clock, parse_date, parse_iso
from envelope import list_response, object_response
from errors import ApiError
from store import serialize, serialize_all, touch
from validation import (
    OPERATOR_ROLES,
    authenticate,
    filter_arg,
    json_body,
    opt_bool,
    opt_int,
    opt_number,
    opt_string,
    pagination,
    paginate,
    req_datetime,
    req_enum,
    req_id_list,
    req_int,
    req_string,
    require_after,
)

bp = Blueprint("blocks", __name__)

BLOCK_KINDS = ("STUDIO", "LOCATION_EXTERIOR", "PUBLIC_SPACE")
PERMIT_REQUIRED_KINDS = ("LOCATION_EXTERIOR", "PUBLIC_SPACE")
SUBJECT_KINDS = (
    "INCIDENTAL_CROWD",
    "BYSTANDER_IDENTIFIABLE",
    "PROPERTY_OWNER",
    "MINOR_INCIDENTAL",
)
DISPOSITIONS = ("COLLECTED", "REFUSED", "BLURRED_WAIVER")


def _extended_end(block, location):
    return parse_iso(block["end_utc"]) + timedelta(minutes=location["turnaround_buffer_minutes"])


@bp.post("/casting/shoot-blocks")
def schedule_shoot_block():
    authenticate(("ProductionAdmin",))
    body = json_body()

    # rung 6 — body foreign keys, left to right
    production = None
    location = None
    if isinstance(body.get("production_id"), str):
        production = services.get_production(body["production_id"])
    if isinstance(body.get("location_id"), str):
        location = services.get_location(body["location_id"])
    raw_ids = body.get("participant_agreement_ids")
    if isinstance(raw_ids, list):
        for entry in raw_ids:
            if isinstance(entry, str):
                services.get_agreement(entry)

    # rung 7 — body shape
    production_id = req_string(body, "production_id")
    if production is None:
        production = services.get_production(production_id)
    location_id = req_string(body, "location_id")
    if location is None:
        location = services.get_location(location_id)
    block_kind = req_enum(body, "block_kind", BLOCK_KINDS)
    start_utc = req_datetime(body, "start_utc")
    end_utc = req_datetime(body, "end_utc")
    require_after(body, "end_utc", "start_utc", end_utc, start_utc)
    agreement_ids = req_id_list(body, "participant_agreement_ids", max_entries=40)
    expected_crowd_headcount = opt_int(
        body, "expected_crowd_headcount", default=0, minimum=0, maximum=5000
    )
    onset_minor_hours = opt_number(body, "onset_minor_hours", default=0, minimum=0, maximum=12)

    # rung 11
    if production["casting_posture"] == "FROZEN":
        raise ApiError("ERR_CASTING_FROZEN")

    agreements = [store.agreements[a] for a in agreement_ids]

    # rung 26 — every minor called to the block holds an unexpired work permit
    today = clock.today()
    minor_count = 0
    for agreement in agreements:
        applicant = store.applicants.get(agreement["applicant_id"])
        if applicant is None or not applicant["is_minor"]:
            continue
        minor_count += 1
        packets = [
            p
            for p in services.packets_of_applicant(applicant["id"])
            if p["status"] != "RELEASED"
        ]
        if not any(parse_date(p["permit_expires_on"]) > today for p in packets):
            raise ApiError("ERR_WORK_PERMIT_EXPIRED")

    # rung 39
    if block_kind in PERMIT_REQUIRED_KINDS and not location["filming_permit_number"]:
        raise ApiError("ERR_LOCATION_PERMIT_MISSING")

    # rung 40
    for agreement in agreements:
        if agreement["production_id"] != production["id"] or agreement["status"] != "EXECUTED":
            raise ApiError("ERR_PARTICIPANT_NOT_EXECUTED")

    # rung 41
    start = parse_iso(start_utc)
    end = parse_iso(end_utc)
    if (
        start < parse_iso(production["photography_start_utc"])
        or end > parse_iso(production["photography_end_utc"])
    ):
        raise ApiError("ERR_OUTSIDE_PHOTOGRAPHY_WINDOW")

    # rung 42 — half-open extended intervals at the same venue
    extended_end = end + timedelta(minutes=location["turnaround_buffer_minutes"])
    for other in services.blocks_of_location(location["id"]):
        if other["status"] not in ("SCHEDULED", "ROLLING"):
            continue
        other_start = parse_iso(other["start_utc"])
        other_extended_end = _extended_end(other, location)
        if start < other_extended_end and other_start < extended_end:
            raise ApiError("ERR_LOCATION_BLOCK_CONFLICT")

    record = store.new_record(
        "shoot_block",
        {
            "production_id": production["id"],
            "location_id": location["id"],
            "block_kind": block_kind,
            "start_utc": start_utc,
            "end_utc": end_utc,
            "expected_crowd_headcount": expected_crowd_headcount,
            "participant_agreement_ids": list(agreement_ids),
            "onset_minor_hours": onset_minor_hours,
            "status": "SCHEDULED",
            "minor_participant_count": minor_count,
            "covered_head_count": 0,
            "release_coverage_complete": False,
        },
    )
    store.shoot_blocks[record["id"]] = record
    return object_response(serialize(record), 201)


@bp.get("/casting/shoot-blocks")
def list_shoot_blocks():
    authenticate(OPERATOR_ROLES)
    limit, offset = pagination()
    records = store.by_seq(list(store.shoot_blocks.values()))
    production_id = filter_arg("production_id")
    if production_id is not None:
        records = [r for r in records if r["production_id"] == production_id]
    location_id = filter_arg("location_id")
    if location_id is not None:
        records = [r for r in records if r["location_id"] == location_id]
    status = filter_arg("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page = paginate(records, limit, offset)
    return list_response(serialize_all(page), limit, offset, len(records))


@bp.get("/casting/shoot-blocks/<block_id>")
def read_shoot_block(block_id):
    authenticate(OPERATOR_ROLES)
    block = services.get_shoot_block(block_id)
    return object_response(serialize(block))


@bp.post("/casting/shoot-blocks/<block_id>/roll")
def roll_shoot_block(block_id):
    authenticate(("ProductionAdmin",))
    block = services.get_shoot_block(block_id)
    production = services.get_production(block["production_id"])

    # rung 11
    if production["casting_posture"] == "FROZEN":
        raise ApiError("ERR_CASTING_FROZEN")
    # rung 13
    if block["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    # rung 28 — aggregate daily on-set + education hours per called minor
    bucket_date = parse_iso(block["start_utc"]).date()
    for agreement_id in block["participant_agreement_ids"]:
        agreement = store.agreements.get(agreement_id)
        if agreement is None:
            continue
        applicant = store.applicants.get(agreement["applicant_id"])
        if applicant is None or not applicant["is_minor"]:
            continue
        onset = calc.dec(block["onset_minor_hours"])
        for other in services.blocks_of_production(production["id"]):
            if other["id"] == block["id"]:
                continue
            if other["status"] not in ("ROLLING", "WRAPPED"):
                continue
            if agreement_id not in other["participant_agreement_ids"]:
                continue
            if parse_iso(other["start_utc"]).date() != bucket_date:
                continue
            onset += calc.dec(other["onset_minor_hours"])
        packet = services.education_packet_for(applicant["id"])
        education = (
            calc.dec(packet["education_hours_scheduled_weekly"]) / calc.EDUCATION_DAYS_PER_WEEK
            if packet is not None
            else calc.dec(0)
        )
        total = calc.hours(onset + education)
        if total > calc.MINOR_DAILY_TOTAL_HOURS_CAP:
            raise ApiError("ERR_MINOR_DAILY_HOURS_EXCEEDED")

    # rung 29 — duty-of-care coverage over the whole block interval
    start = parse_iso(block["start_utc"])
    end = parse_iso(block["end_utc"])
    covered = False
    for protocol in services.protocols_of_production(production["id"]):
        if protocol["status"] != "ACTIVE" or protocol["kind"] != "DUTY_OF_CARE_OFFICER":
            continue
        if (
            parse_iso(protocol["coverage_start_utc"]) <= start
            and parse_iso(protocol["coverage_end_utc"]) >= end
        ):
            covered = True
            break
    if not covered:
        raise ApiError("ERR_DUTY_OF_CARE_UNCOVERED")

    # rung 30 — no called participant's medical clearance is EXPIRED or DEFERRED
    for agreement_id in block["participant_agreement_ids"]:
        agreement = store.agreements.get(agreement_id)
        if agreement is None:
            continue
        applicant = store.applicants.get(agreement["applicant_id"])
        if applicant is None:
            continue
        if applicant["medical_status"] in ("EXPIRED", "DEFERRED"):
            raise ApiError("ERR_MEDICAL_CLEARANCE_EXPIRED")

    block["status"] = "ROLLING"
    touch(block)
    return object_response(serialize(block))


@bp.post("/casting/shoot-blocks/<block_id>/wrap")
def wrap_shoot_block(block_id):
    authenticate(("ProductionAdmin",))
    block = services.get_shoot_block(block_id)
    # rung 13
    if block["status"] != "ROLLING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    # rung 32
    complete = services.recompute_release_coverage(block)
    if not complete:
        raise ApiError("ERR_RELEASE_COVERAGE_INCOMPLETE")
    block["status"] = "WRAPPED"
    touch(block)
    return object_response(serialize(block))


# ------------------------------------------------------------------- releases
@bp.post("/casting/shoot-blocks/<block_id>/releases")
def collect_release(block_id):
    authenticate(("ProductionAdmin",))
    block = services.get_shoot_block(block_id)
    body = json_body()
    subject_kind = req_enum(body, "subject_kind", SUBJECT_KINDS)
    head_count = req_int(body, "head_count", minimum=1, maximum=5000)
    disposition = req_enum(body, "disposition", DISPOSITIONS)
    subject_name = opt_string(body, "subject_name")
    guardian_signature = opt_bool(body, "guardian_signature", default=False)

    # rung 31
    if subject_kind == "MINOR_INCIDENTAL" and not guardian_signature:
        raise ApiError("ERR_GUARDIAN_SIGNATURE_REQUIRED")

    record = store.new_record(
        "release",
        {
            "shoot_block_id": block["id"],
            "subject_kind": subject_kind,
            "subject_name": subject_name,
            "head_count": head_count,
            "guardian_signature": guardian_signature,
            "disposition": disposition,
            "collected_at": clock.now_iso(),
        },
        versioned=False,
    )
    store.releases[record["id"]] = record

    services.recompute_release_coverage(block)
    touch(block)
    return object_response(serialize(record), 201)


@bp.get("/casting/shoot-blocks/<block_id>/releases")
def list_releases(block_id):
    authenticate(("ProductionAdmin", "CastingDirector", "BusinessAffairs", "WelfareOfficer"))
    block = services.get_shoot_block(block_id)
    limit, offset = pagination()
    records = services.releases_of_block(block["id"])
    subject_kind = filter_arg("subject_kind")
    if subject_kind is not None:
        records = [r for r in records if r["subject_kind"] == subject_kind]
    disposition = filter_arg("disposition")
    if disposition is not None:
        records = [r for r in records if r["disposition"] == disposition]
    page = paginate(records, limit, offset)
    return list_response(serialize_all(page), limit, offset, len(records))
