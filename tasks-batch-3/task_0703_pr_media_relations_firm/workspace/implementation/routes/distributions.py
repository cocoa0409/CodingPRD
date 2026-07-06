"""Distribution endpoints (PRD 3.5)."""
from flask import Blueprint, request

import db
from common import (get_json_body, get_or_404, new_record, paginate,
                    parse_pagination, ref_or_404)
from errors import err
from middleware import authorize
from response import success
from services.serialize import distribution_out

bp = Blueprint("distributions", __name__)

DISTRIBUTION_STATUSES = {"QUEUED", "DELIVERED", "BOUNCED"}


@bp.post("/agency/distributions")
@authorize(["MediaSpecialist"])
def create_distribution():
    body = get_json_body()
    press_release_id = body.get("press_release_id")
    journalist_id = body.get("journalist_id")
    # Priority 4: FK existence.
    press_release = ref_or_404(db.press_releases, press_release_id, "press_release_id")
    ref_or_404(db.journalists, journalist_id, "journalist_id")

    # Priority 8: business referential — the journalist must belong to a media
    # list of the release's campaign.
    campaign_id = press_release["campaign_id"]
    in_a_list = any(
        ml["campaign_id"] == campaign_id and journalist_id in ml["journalist_ids"]
        for ml in db.media_lists.values())
    if not in_a_list:
        raise err("ERR_JOURNALIST_NOT_IN_LIST",
                  "Journalist is not in any media list of the release's campaign")

    # Release must still be open to new recipients (DRAFT or SCHEDULED).
    if press_release["status"] not in ("DRAFT", "SCHEDULED"):
        raise err("ERR_DISTRIBUTION_RELEASE_LOCKED",
                  "Release is RELEASED or WITHDRAWN and locked to new recipients")

    rec = new_record({
        "press_release_id": press_release_id,
        "journalist_id": journalist_id,
        "status": "QUEUED",
        "delivered_at": None,
    })
    db.distributions[rec["id"]] = rec
    return success(distribution_out(rec), status=201)


@bp.get("/agency/distributions/<distribution_id>")
@authorize(["AccountManager", "MediaSpecialist", "PlatformAdmin"])
def get_distribution(distribution_id):
    rec = get_or_404(db.distributions, distribution_id)
    return success(distribution_out(rec))


@bp.get("/agency/distributions")
@authorize(["AccountManager", "MediaSpecialist", "PlatformAdmin"])
def list_distributions():
    limit, offset = parse_pagination()
    press_release_id = request.args.get("press_release_id")
    journalist_id = request.args.get("journalist_id")
    status = request.args.get("status")
    if status is not None and status not in DISTRIBUTION_STATUSES:
        raise err("ERR_INVALID_REQUEST", "status filter invalid")
    records = []
    for r in db.distributions.values():
        if press_release_id is not None and r["press_release_id"] != press_release_id:
            continue
        if journalist_id is not None and r["journalist_id"] != journalist_id:
            continue
        if status is not None and r["status"] != status:
            continue
        records.append(r)
    page, meta = paginate(records, limit, offset)
    return success([distribution_out(r) for r in page], pagination=meta)
