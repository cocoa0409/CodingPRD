"""Digital clip and redemption-event endpoints (PRD 3.9)."""

from flask import Blueprint

import db
import middleware as mw
import response
import validate
from db import touch, sort_rows
from errors import ApiError
from services import calc, domain

bp = Blueprint("digital", __name__)

DIGITAL_READ_ROLES = ["Manufacturer", "Retailer", "FraudAnalyst", "ClearinghouseAdmin"]


@bp.route("/digital-clips", methods=["POST"])
def create_clip():
    mw.authenticate(["Retailer", "ClearinghouseAdmin"])
    values = validate.parse(
        mw.body(),
        {
            "offer_id": {"type": "string", "required": True, "min_len": 1},
            "consumer_ref": {
                "type": "string",
                "required": True,
                "min_len": 1,
                "max_len": 40,
            },
        },
    )
    offer = mw.fetch("offers", values["offer_id"], "ERR_OFFER_NOT_FOUND")
    if not offer["digital_enabled"]:
        raise ApiError("ERR_OFFER_NOT_DIGITAL", "Offer is not digitally enabled")
    clip_date = db.today()
    live = 0
    for clip in db.db.clips.values():
        if clip["offer_id"] != offer["id"]:
            continue
        if clip["consumer_ref"] != values["consumer_ref"]:
            continue
        if clip["status"] != "CLIPPED":
            continue
        if db.parse_date(clip["clip_expires_at"]) >= clip_date:
            live += 1
    if live >= calc.CLIP_CONCURRENCY_LIMIT:
        raise ApiError(
            "ERR_CLIP_CONCURRENCY_LIMIT",
            "This consumer already holds the maximum live clips for the offer",
        )
    validity_end = db.add_days(clip_date, offer["clip_validity_days"])
    grace_end = db.add_days(
        db.parse_date(offer["expiration_date"]), offer["redemption_grace_days"]
    )
    expires = validity_end if validity_end <= grace_end else grace_end
    row = db.base_row()
    row.update(
        {
            "offer_id": offer["id"],
            "consumer_ref": values["consumer_ref"],
            "clipped_at": db.fmt_date(clip_date),
            "clip_expires_at": db.fmt_date(expires),
            "status": "CLIPPED",
            "matched_event_id": None,
        }
    )
    db.db.clips[row["id"]] = row
    return response.object_response(row, 201)


@bp.route("/digital-clips/<cid>", methods=["GET"])
def get_clip(cid):
    mw.authenticate(DIGITAL_READ_ROLES)
    row = mw.fetch("clips", cid, "ERR_CLIP_NOT_FOUND")
    return response.object_response(row)


@bp.route("/digital-clips", methods=["GET"])
def list_clips():
    mw.authenticate(DIGITAL_READ_ROLES)
    limit, offset = mw.pagination()
    offer_id = mw.str_arg("offer_id")
    consumer_ref = mw.str_arg("consumer_ref")
    status = mw.str_arg("status")
    matched_event_id = mw.str_arg("matched_event_id")
    rows = [
        c
        for c in db.db.clips.values()
        if (offer_id is None or c["offer_id"] == offer_id)
        and (consumer_ref is None or c["consumer_ref"] == consumer_ref)
        and (status is None or c["status"] == status)
        and (matched_event_id is None or c["matched_event_id"] == matched_event_id)
    ]
    rows = sort_rows(rows)
    page, total = mw.paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.route("/digital-redemption-events", methods=["POST"])
def create_event():
    ctx = mw.authenticate(["Retailer"])
    values = validate.parse(
        mw.body(),
        {
            "offer_id": {"type": "string", "required": True, "min_len": 1},
            "retailer_id": {"type": "string", "required": True, "min_len": 1},
            "consumer_ref": {
                "type": "string",
                "required": True,
                "min_len": 1,
                "max_len": 40,
            },
        },
    )
    retailer = mw.fetch("retailers", values["retailer_id"], "ERR_RETAILER_NOT_FOUND")
    mw.own_retailer(ctx, retailer["id"])
    offer = mw.fetch("offers", values["offer_id"], "ERR_OFFER_NOT_FOUND")
    if retailer["status"] == "SUSPENDED":
        raise ApiError("ERR_RETAILER_SUSPENDED", "Retailer is suspended")
    if not offer["digital_enabled"]:
        raise ApiError("ERR_OFFER_NOT_DIGITAL", "Offer is not digitally enabled")
    if offer["accepted_redemption_count"] + 1 > offer["max_redemptions"]:
        raise ApiError(
            "ERR_MAX_REDEMPTIONS_EXCEEDED",
            "Offer redemption ceiling has been reached",
        )
    redeemed_on = db.today()
    pool = []
    for clip in db.db.clips.values():
        if clip["offer_id"] != offer["id"]:
            continue
        if clip["consumer_ref"] != values["consumer_ref"]:
            continue
        if clip["status"] != "CLIPPED":
            continue
        if db.parse_date(clip["clipped_at"]) > redeemed_on:
            continue
        if db.parse_date(clip["clip_expires_at"]) < redeemed_on:
            continue
        pool.append(clip)
    pool.sort(
        key=lambda c: (
            c["clip_expires_at"],
            c.get("created_at") or "",
            c.get("_seq") or 0,
        )
    )
    row = db.base_row()
    row.update(
        {
            "offer_id": offer["id"],
            "retailer_id": retailer["id"],
            "consumer_ref": values["consumer_ref"],
            "redeemed_at": db.fmt_date(redeemed_on),
            "face_value_cents": offer["face_value_cents"],
            "matched_clip_id": None,
            "status": "UNMATCHED",
            "reject_code": None,
        }
    )
    if pool:
        winner = pool[0]
        row["status"] = "MATCHED"
        row["matched_clip_id"] = winner["id"]
        db.db.events[row["id"]] = row
        winner["status"] = "MATCHED"
        winner["matched_event_id"] = row["id"]
        touch(winner)
        offer["accepted_redemption_count"] = offer["accepted_redemption_count"] + 1
        touch(offer)
    else:
        row["reject_code"] = "NO_ELIGIBLE_CLIP"
        db.db.events[row["id"]] = row
    return response.object_response(row, 201)


@bp.route("/digital-redemption-events/<eid>", methods=["GET"])
def get_event(eid):
    ctx = mw.authenticate(DIGITAL_READ_ROLES)
    row = mw.fetch("events", eid, "ERR_REDEMPTION_EVENT_NOT_FOUND")
    mw.own_retailer(ctx, row["retailer_id"])
    return response.object_response(row)


@bp.route("/digital-redemption-events", methods=["GET"])
def list_events():
    mw.authenticate(DIGITAL_READ_ROLES)
    limit, offset = mw.pagination()
    offer_id = mw.str_arg("offer_id")
    retailer_id = mw.str_arg("retailer_id")
    consumer_ref = mw.str_arg("consumer_ref")
    status = mw.str_arg("status")
    matched_clip_id = mw.str_arg("matched_clip_id")
    rows = [
        e
        for e in db.db.events.values()
        if (offer_id is None or e["offer_id"] == offer_id)
        and (retailer_id is None or e["retailer_id"] == retailer_id)
        and (consumer_ref is None or e["consumer_ref"] == consumer_ref)
        and (status is None or e["status"] == status)
        and (matched_clip_id is None or e["matched_clip_id"] == matched_clip_id)
    ]
    rows = sort_rows(rows)
    page, total = mw.paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)
