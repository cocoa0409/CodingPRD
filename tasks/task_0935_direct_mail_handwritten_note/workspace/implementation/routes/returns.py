"""Return events and reprint requests."""
from flask import Blueprint, request

import derive
import envelope
import ladder
import serial
import store
from errors import ApiError
from ladder import Ctx
from model import new_row, touch
from store import db

bp = Blueprint("returns", __name__)

RETURN_READ_ROLES = ["PlatformAdmin", "AccountOwner", "ListOperator", "CampaignManager"]
REPRINT_READ_ROLES = ["PlatformAdmin", "CampaignManager", "ListOperator", "ProductionOperator"]


@bp.route("/mail/return-events/<return_event_id>", methods=["GET"])
def get_return_event(return_event_id):
    ctx = Ctx(RETURN_READ_ROLES)
    ctx.path("return_event", return_event_id)
    ctx.scope(lambda: ladder.account_of_record(
        db.list_records.get(ctx.get("return_event")["list_record_id"])))
    ctx.run()
    return envelope.object_response(serial.return_event(ctx.get("return_event")), 200)


@bp.route("/mail/return-events", methods=["GET"])
def list_return_events():
    ctx = Ctx(RETURN_READ_ROLES)
    ctx.run()
    rows = list(db.return_events.values())
    for field in ("list_record_id", "mail_job_id", "entitlement"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    rows = envelope.sort_rows(rows)
    page, limit, offset, total = envelope.paginate(rows, request.args)
    return envelope.list_response([serial.return_event(r) for r in page], limit, offset, total)


@bp.route("/mail/reprint-requests", methods=["POST"])
def create_reprint():
    ctx = Ctx(["PlatformAdmin", "CampaignManager", "ListOperator"])
    ctx.fk("list_record", "list_record_id")
    ctx.fk("return_event", "return_event_id")
    ctx.fk("campaign", "campaign_id")
    ctx.fields(required=[("list_record_id", "str"), ("return_event_id", "str"),
                         ("campaign_id", "str"),
                         ("expected_list_record_version", "int")])
    ctx.gate(lambda: ctx.get("campaign"))
    ctx.occ("expected_list_record_version", lambda: ctx.get("list_record"))
    ctx.at(13, lambda: _reject_eddm(ladder.job_of_record(ctx.get("list_record"))))
    ctx.at(37, lambda: _entitled(ctx.get("return_event")))
    ctx.run()
    row = new_row({
        "list_record_id": ctx.body["list_record_id"],
        "return_event_id": ctx.body["return_event_id"],
        "campaign_id": ctx.body["campaign_id"],
        "status": "REQUESTED",
        "deny_reason": None,
    })
    db.reprint_requests[row["id"]] = row
    touch(ctx.get("list_record"))
    return envelope.object_response(serial.reprint_request(row), 201)


def _reject_eddm(job):
    if job is not None and job["job_kind"] == "EDDM":
        raise ApiError("ERR_EDDM_NOT_APPLICABLE")


def _entitled(event):
    if event is None or event["entitlement"] != "REPRINT":
        raise ApiError("ERR_REPRINT_NOT_ENTITLED")


@bp.route("/mail/reprint-requests/<reprint_request_id>", methods=["GET"])
def get_reprint(reprint_request_id):
    ctx = Ctx(REPRINT_READ_ROLES)
    ctx.path("reprint_request", reprint_request_id)
    ctx.run()
    return envelope.object_response(serial.reprint_request(ctx.get("reprint_request")), 200)


@bp.route("/mail/reprint-requests", methods=["GET"])
def list_reprints():
    ctx = Ctx(REPRINT_READ_ROLES)
    ctx.run()
    rows = list(db.reprint_requests.values())
    for field in ("list_record_id", "return_event_id", "campaign_id", "status"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    rows = envelope.sort_rows(rows)
    page, limit, offset, total = envelope.paginate(rows, request.args)
    return envelope.list_response([serial.reprint_request(r) for r in page], limit, offset, total)


def _requested(reprint):
    if reprint["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE")


@bp.route("/mail/reprint-requests/<reprint_request_id>/fulfill", methods=["POST"])
def fulfill_reprint(reprint_request_id):
    ctx = Ctx(["PlatformAdmin", "ProductionOperator"])
    ctx.path("reprint_request", reprint_request_id)
    ctx.gate(lambda: db.campaigns.get(ctx.get("reprint_request")["campaign_id"]))
    ctx.at(20, lambda: _requested(ctx.get("reprint_request")))
    ctx.at(37, lambda: _entitled(
        db.return_events.get(ctx.get("reprint_request")["return_event_id"])))
    ctx.at(38, lambda: _cap(ctx.get("reprint_request")))
    ctx.run()
    reprint = ctx.get("reprint_request")
    reprint["status"] = "FULFILLED"
    touch(reprint)
    record = db.list_records.get(reprint["list_record_id"])
    if record is not None and record["mail_status"] == "RETURNED":
        record["mail_status"] = "QUEUED"
        touch(record)
    return envelope.object_response(serial.reprint_request(reprint), 200)


def _cap(reprint):
    # Adjudication of friction 9 (enforcement side): the allowance is counted
    # against the campaign the request names.
    used = derive.reprint_count_in_campaign(reprint["list_record_id"], reprint["campaign_id"])
    if used >= store.REPRINT_CAP_PER_CAMPAIGN_PER_RECORD:
        raise ApiError("ERR_REPRINT_CAP_EXCEEDED")


@bp.route("/mail/reprint-requests/<reprint_request_id>/deny", methods=["POST"])
def deny_reprint(reprint_request_id):
    ctx = Ctx(["PlatformAdmin", "ProductionOperator"])
    ctx.path("reprint_request", reprint_request_id)
    ctx.fields(required=[("deny_reason", "str")])
    ctx.gate(lambda: db.campaigns.get(ctx.get("reprint_request")["campaign_id"]))
    ctx.at(20, lambda: _requested(ctx.get("reprint_request")))
    ctx.run()
    reprint = ctx.get("reprint_request")
    reprint["status"] = "DENIED"
    reprint["deny_reason"] = ctx.body["deny_reason"]
    touch(reprint)
    return envelope.object_response(serial.reprint_request(reprint), 200)
