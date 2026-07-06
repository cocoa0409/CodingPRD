"""MediaList endpoints (PRD 3.4 membership, 2.7 OCC supersede)."""
from flask import Blueprint, request

import db
from common import (get_json_body, get_or_404, new_record, paginate,
                    parse_pagination, ref_or_404, require_int, require_str, touch)
from errors import err
from middleware import authorize
from response import success
from services.serialize import media_list_out

bp = Blueprint("media_lists", __name__)

MEDIA_LIST_STATUSES = {"ACTIVE", "SUPERSEDED", "EXHAUSTED", "ARCHIVED"}


@bp.post("/agency/media-lists")
@authorize(["MediaSpecialist"])
def create_media_list():
    body = get_json_body()
    campaign_id = body.get("campaign_id")
    # Priority 4: FK existence.
    campaign = ref_or_404(db.campaigns, campaign_id, "campaign_id")

    # Priority 5: well-formedness.
    name = require_str(body, "name")
    journalist_ids = body.get("journalist_ids")
    if not isinstance(journalist_ids, list) or any(not isinstance(j, str) for j in journalist_ids):
        raise err("ERR_INVALID_REQUEST", "journalist_ids must be an array of ids")
    expected_version = require_int(body, "expected_campaign_version")

    # Priority 4 (continued): each journalist id in the body must reference an
    # existing journalist.
    for jid in journalist_ids:
        ref_or_404(db.journalists, jid, "journalist_ids")

    # Priority 6: OCC against campaign version.
    if expected_version != campaign["version"]:
        raise err("ERR_STALE_CAMPAIGN_VERSION",
                  "expected_campaign_version does not match current campaign version")

    # Supersede the campaign's current ACTIVE list.
    for ml in db.media_lists.values():
        if ml["campaign_id"] == campaign_id and ml["status"] == "ACTIVE":
            ml["status"] = "SUPERSEDED"
            touch(ml)

    rec = new_record({
        "campaign_id": campaign_id,
        "name": name,
        "journalist_ids": list(journalist_ids),
        "status": "ACTIVE",
    })
    db.media_lists[rec["id"]] = rec

    # Increment the campaign version by one on success (PRD 2.7).
    touch(campaign)
    return success(media_list_out(rec), status=201)


@bp.get("/agency/media-lists/<media_list_id>")
@authorize(["AccountManager", "MediaSpecialist", "PlatformAdmin"])
def get_media_list(media_list_id):
    rec = get_or_404(db.media_lists, media_list_id)
    return success(media_list_out(rec))


@bp.get("/agency/media-lists")
@authorize(["AccountManager", "MediaSpecialist", "PlatformAdmin"])
def list_media_lists():
    limit, offset = parse_pagination()
    campaign_id = request.args.get("campaign_id")
    status = request.args.get("status")
    if status is not None and status not in MEDIA_LIST_STATUSES:
        raise err("ERR_INVALID_REQUEST", "status filter invalid")
    records = []
    for r in db.media_lists.values():
        if campaign_id is not None and r["campaign_id"] != campaign_id:
            continue
        if status is not None and r["status"] != status:
            continue
        records.append(r)
    page, meta = paginate(records, limit, offset)
    return success([media_list_out(r) for r in page], pagination=meta)
