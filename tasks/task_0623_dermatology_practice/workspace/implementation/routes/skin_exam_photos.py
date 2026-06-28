"""SkinExamPhoto: append-only mole-map documentation (PRD 2.4, 3.5)."""
from flask import Blueprint, request

import db
import errors
import helpers
import response
from middleware import require

bp = Blueprint("skin_exam_photos", __name__)


@bp.post("/skin-exam-photos")
@require("Provider", "PracticeAdmin")
def create_photo():
    data = helpers.body()
    encounter_id = helpers.require_str(data, "encounter_id")
    body_site = helpers.require_str(data, "body_site")
    x = helpers.require_number(data, "mole_map_x")
    y = helpers.require_number(data, "mole_map_y")
    image_ref = helpers.require_str(data, "image_ref")
    if not (0 <= x <= 1):
        raise errors.invalid_request("mole_map_x must be between 0 and 1")
    if not (0 <= y <= 1):
        raise errors.invalid_request("mole_map_y must be between 0 and 1")
    helpers.get_or_404(db.encounters, encounter_id, "encounter")
    # Append-only: id + created_at only (no updated_at, no version).
    row = {
        "encounter_id": encounter_id,
        "body_site": body_site,
        "mole_map_x": x,
        "mole_map_y": y,
        "image_ref": image_ref,
    }
    db.stamp_new(row, common=False)
    db.skin_exam_photos[row["id"]] = row
    return response.created(row)


@bp.get("/skin-exam-photos/<sid>")
@require("Provider", "PracticeAdmin", "FrontDesk")
def get_photo(sid):
    row = db.skin_exam_photos.get(sid)
    if row is None:
        # No catalogued resource-specific not-found exists for SkinExamPhoto;
        # a missing photo on a path identifier is a 404.
        raise errors.ApiError("ERR_PHOTO_NOT_FOUND", 404, "photo not found")
    return response.ok(row)


@bp.get("/skin-exam-photos")
@require("Provider", "PracticeAdmin", "FrontDesk")
def list_photos():
    rows = list(db.skin_exam_photos.values())
    eid = request.args.get("encounter_id")
    if eid is not None:
        rows = [p for p in rows if p["encounter_id"] == eid]
    page, limit, offset, total = helpers.paginate(rows)
    return response.listing(page, limit, offset, total)
