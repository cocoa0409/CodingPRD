"""Incentive programme participation and credit netting."""
from flask import Blueprint

import derive
import serializers as ser
from auth import actor
from constants import CLAIM_STATUSES, MAX_REVISION_ROUNDS, PROGRAMS
from envelope import created, listing, ok
from errors import raise_error
from helpers import get_claim, get_lot, get_station
from store import base_row, db, touch
from validate import (
    bad,
    f_date,
    f_enum,
    f_id_list,
    f_str,
    json_body,
    pagination,
    paginate,
    q_enum,
)

bp = Blueprint("incentives", __name__)


@bp.get("/incentive-claims/<claim_id>")
def read_claim(claim_id):
    actor("PlatformAdmin", "ComplianceAdmin", "ProgramAuditor")
    return ok(ser.incentive_claim(get_claim(claim_id)))


@bp.get("/stations/<station_id>/incentive-claims")
def list_claims(station_id):
    actor("PlatformAdmin", "ComplianceAdmin", "ProgramAuditor")
    station = get_station(station_id)
    limit, offset = pagination()
    program = q_enum("program", PROGRAMS)
    status = q_enum("status", CLAIM_STATUSES)
    rows = derive.claims_of(station["id"])
    if program is not None:
        rows = [r for r in rows if r["program"] == program]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page = paginate(rows, limit, offset)
    return listing([ser.incentive_claim(r) for r in page], limit, offset, len(rows))


def _require_certified(lots):
    for lot in lots:
        if lot["ci_status"] != "CERTIFIED":
            raise_error("ERR_LOT_CI_NOT_CERTIFIED")


def _require_delivered_in_period(station_id, lots, period_start, period_end):
    for lot in lots:
        found = False
        for delivery in derive.deliveries_of_lot(lot["id"]):
            if delivery["station_id"] != station_id:
                continue
            if delivery["status"] != "ACCEPTED" or delivery["accepted_at"] is None:
                continue
            if period_start <= delivery["accepted_at"].date() <= period_end:
                found = True
                break
        if not found:
            raise_error("ERR_LOT_NOT_DELIVERED_IN_PERIOD")


def _apply_netting(claim):
    figures = derive.credit_netting(claim)
    claim.update(figures)


@bp.post("/incentive-claims")
def submit_claim():
    user_id, _role = actor("ComplianceAdmin")
    body = json_body()
    station_id = f_str(body, "station_id")
    program = f_enum(body, "program", PROGRAMS)
    period_start = f_date(body, "period_start")
    period_end = f_date(body, "period_end")
    lot_ids = f_id_list(body, "production_lot_ids")
    if period_end < period_start:
        bad("Field 'period_end' must not be earlier than 'period_start'.")

    station = get_station(station_id)
    lots = [get_lot(lot_id) for lot_id in lot_ids]

    _require_certified(lots)
    _require_delivered_in_period(station["id"], lots, period_start, period_end)

    for other in derive.claims_of(station["id"]):
        if other["program"] != program or other["status"] == "DENIED":
            continue
        if other["period_start"] <= period_end and period_start <= other["period_end"]:
            raise_error("ERR_CLAIM_PERIOD_OVERLAP")

    row = base_row()
    row.update({
        "station_id": station["id"],
        "program": program,
        "period_start": period_start,
        "period_end": period_end,
        "production_lot_ids": lot_ids,
        "revision_round": 0,
        "submitted_by_user_id": user_id,
        "certified_by_user_id": None,
        "revision_note": None,
        "status": "SUBMITTED",
    })
    _apply_netting(row)
    db.incentive_claims[row["id"]] = row
    return created(ser.incentive_claim(row))


@bp.post("/incentive-claims/<claim_id>/request-revision")
def request_revision(claim_id):
    actor("ProgramAuditor")
    claim = get_claim(claim_id)
    body = json_body()
    revision_note = f_str(body, "revision_note")

    if claim["status"] != "SUBMITTED":
        raise_error("ERR_INVALID_STATE_TRANSITION")

    rounds_before = claim["revision_round"]
    claim["revision_note"] = revision_note
    claim["revision_round"] = rounds_before + 1
    claim["status"] = ("REVISION_REQUESTED" if rounds_before < MAX_REVISION_ROUNDS
                       else "DENIED")
    touch(claim)
    return ok(ser.incentive_claim(claim))


@bp.post("/incentive-claims/<claim_id>/resubmit")
def resubmit_claim(claim_id):
    actor("ComplianceAdmin")
    claim = get_claim(claim_id)
    body = json_body()
    lot_ids = f_id_list(body, "production_lot_ids")
    lots = [get_lot(lot_id) for lot_id in lot_ids]

    if claim["status"] != "REVISION_REQUESTED":
        raise_error("ERR_INVALID_STATE_TRANSITION")

    _require_certified(lots)
    _require_delivered_in_period(claim["station_id"], lots,
                                 claim["period_start"], claim["period_end"])

    claim["production_lot_ids"] = lot_ids
    claim["status"] = "SUBMITTED"
    _apply_netting(claim)
    touch(claim)
    return ok(ser.incentive_claim(claim))


@bp.post("/incentive-claims/<claim_id>/certify")
def certify_claim(claim_id):
    user_id, _role = actor("ProgramAuditor")
    claim = get_claim(claim_id)
    if claim["status"] != "SUBMITTED":
        raise_error("ERR_INVALID_STATE_TRANSITION")
    if user_id == claim["submitted_by_user_id"]:
        raise_error("ERR_SEGREGATION_OF_DUTIES")

    claim["certified_by_user_id"] = user_id
    claim["status"] = "CERTIFIED"
    touch(claim)
    return ok(ser.incentive_claim(claim))


@bp.post("/incentive-claims/<claim_id>/issue-credits")
def issue_credits(claim_id):
    actor("ProgramAuditor")
    claim = get_claim(claim_id)
    if claim["status"] != "CERTIFIED":
        raise_error("ERR_INVALID_STATE_TRANSITION")
    if claim["net_credits_mt"] <= 0:
        raise_error("ERR_NO_CREDITS_TO_ISSUE")

    claim["status"] = "CREDITS_ISSUED"
    touch(claim)
    touch(db.stations[claim["station_id"]])
    return ok(ser.incentive_claim(claim))
