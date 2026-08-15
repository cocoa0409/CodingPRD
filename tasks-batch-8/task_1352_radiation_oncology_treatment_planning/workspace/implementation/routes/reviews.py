"""Chart-round peer reviews (PRD 3.7)."""
from flask import Blueprint

from db import store, new_entity, touch, sorted_all
from errors import err, ERR_NOT_FOUND
from middleware import require_roles, ALL_ROLES, get_body
from response import success, paginate
from serializers import review_json
from timeutil import new_id
from validate import req_enum, opt_str

bp = Blueprint("reviews", __name__)

OUTCOMES = {"PASS", "FAIL"}


@bp.post("/oncology/treatment-courses/<cid>/chart-reviews")
@require_roles("MedicalPhysicist")
def create_review(cid, user_id):
    course = store.courses.get(cid)
    if course is None:
        err(ERR_NOT_FOUND, "treatment course not found")
    body = get_body()
    outcome = req_enum(body, "outcome", OUTCOMES)
    notes = opt_str(body, "notes")
    r = new_entity(common=False)
    r.update({
        "id": new_id(), "course_id": cid, "reviewer_id": user_id,
        "outcome": outcome, "notes": notes,
        "delivered_fractions_at_review": course["delivered_fractions"],
    })
    store.reviews[r["id"]] = r
    # PASS resets the chart-review gate; FAIL leaves the counter unchanged
    if outcome == "PASS":
        course["fractions_since_chart_review"] = 0
        touch(course)
    return success(review_json(r), 201)


@bp.get("/oncology/treatment-courses/<cid>/chart-reviews")
@require_roles(*ALL_ROLES)
def list_reviews(cid, user_id):
    if cid not in store.courses:
        err(ERR_NOT_FOUND, "treatment course not found")
    items = sorted_all(r for r in store.reviews.values() if r["course_id"] == cid)
    page, meta = paginate(items)
    return success([review_json(r) for r in page], 200, pagination=meta)
