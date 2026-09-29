"""Lead-capture licences and badge ingestion (PRD §3.8)."""
from flask import Blueprint

import db
import guards
import response
from errors import ApiError
from middleware import own_exhibitor, require_roles
from services import calc
from validation import json_body, require_row

bp = Blueprint("leads", __name__)
store = db.store


def _booth_exhibitor(license_row):
    if not license_row:
        return None
    booth = store.booths.get(license_row["booth_id"])
    return booth["exhibitor_id"] if booth else None


@bp.post("/lead-capture-licenses")
def provision():
    require_roles("Exhibitor")
    body = json_body()
    peeked = store.booths.get(body.peek_str("booth_id"))
    own_exhibitor(peeked["exhibitor_id"] if peeked else None)

    booth_id = body.string("booth_id")
    device_count = body.integer("device_count")
    included_leads = body.integer("included_leads", required=False, default=250)

    require_row(store.booths, booth_id, "ERR_BOOTH_NOT_FOUND", "Booth")

    license_row = {
        "id": db.new_id(),
        "booth_id": booth_id,
        "device_count": device_count,
        "included_leads": included_leads,
        "ingested_badge_ids": [],
        "leads_ingested_count": 0,
        "billable_overage_leads": 0,
        "lead_overage_cents": 0,
        "license_total_cents": device_count * calc.DEVICE_FEE_CENTS,
        "status": "PROVISIONED",
    }
    db.stamp_common(license_row)
    store.licenses[license_row["id"]] = license_row
    return response.created(license_row)


@bp.post("/lead-capture-licenses/<license_id>/lead-batches")
def lead_batch(license_id):
    require_roles("Exhibitor")
    body = json_body()
    license_row = store.licenses.get(license_id)
    own_exhibitor(_booth_exhibitor(license_row))

    badge_ids = body.string_array("badge_ids")
    body.datetime_str("captured_at")
    license_row = require_row(store.licenses, license_id, "ERR_LICENSE_NOT_FOUND",
                              "Lead capture licence")
    booth = store.booths.get(license_row["booth_id"])
    show = store.shows.get(booth["show_id"]) if booth else None

    guards.show_accepting(show, ("ON_SITE", "MOVE_OUT"))
    if booth is not None:
        guards.booth_not_frozen(booth)
    guards.not_empty(badge_ids, "badge_ids")
    if license_row["status"] == "CLOSED":
        raise ApiError("ERR_LICENSE_CLOSED", "The licence is closed to further batches")

    accepted = 0
    seen = set(license_row["ingested_badge_ids"])
    for badge in badge_ids:
        if badge in seen:
            continue
        seen.add(badge)
        license_row["ingested_badge_ids"].append(badge)
        accepted += 1

    calc.license_billing(license_row)
    if accepted > 0 and license_row["status"] == "PROVISIONED":
        license_row["status"] = "ACTIVE"
    db.touch(license_row)
    return response.ok(license_row)
