from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_roles
from response import success, success_list, parse_pagination
from services import (
    SPECIALTIES, get_body, req_str, req_enum, get_provider, pub, sort_created,
    compute_trend, trigger_fires, active_focused_review, iso, make_versioned,
)

bp = Blueprint("providers", __name__)

ALL_ROLES = ("QualityDirector", "PeerReviewCoordinator", "CommitteeMember", "Provider")
STAFF_ROLES = ("QualityDirector", "PeerReviewCoordinator", "CommitteeMember")


def _list_response(records):
    limit, offset = parse_pagination()
    total = len(records)
    page = records[offset:offset + limit]
    return success_list([pub(r) for r in page], limit, offset, total)


@bp.post("/peer-review/providers")
def create_provider():
    require_roles("QualityDirector")
    b = get_body()
    full_name = req_str(b, "full_name")
    specialty = req_enum(b, "specialty", SPECIALTIES)
    rec = make_versioned()
    rec.update({"full_name": full_name, "specialty": specialty})
    store.providers[rec["id"]] = rec
    return success(pub(rec), 201)


@bp.get("/peer-review/providers")
def list_providers():
    require_roles(*ALL_ROLES)
    items = sort_created(list(store.providers.values()))
    specialty = request.args.get("specialty")
    if specialty is not None:
        items = [p for p in items if p["specialty"] == specialty]
    return _list_response(items)


@bp.get("/peer-review/providers/<pid>")
def get_one_provider(pid):
    require_roles(*ALL_ROLES)
    return success(pub(get_provider(pid)))


@bp.get("/peer-review/providers/<pid>/cases")
def list_provider_cases(pid):
    actor = require_roles(*ALL_ROLES)
    provider = get_provider(pid)
    if actor.role == "Provider" and actor.id != provider["id"]:
        raise ApiError("ERR_FORBIDDEN_RESOURCE", 403, "providers may only list their own cases")
    items = sort_created([c for c in store.cases.values() if c["subject_provider_id"] == pid])
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return _list_response(items)


@bp.get("/peer-review/providers/<pid>/conflict-declarations")
def list_provider_conflicts(pid):
    require_roles(*STAFF_ROLES)
    get_provider(pid)
    items = sort_created([c for c in store.conflicts.values() if c["provider_id"] == pid])
    return _list_response(items)


@bp.get("/peer-review/providers/<pid>/focused-reviews")
def list_provider_focused_reviews(pid):
    require_roles(*STAFF_ROLES)
    get_provider(pid)
    items = sort_created([f for f in store.focused_reviews.values() if f["provider_id"] == pid])
    status = request.args.get("status")
    if status is not None:
        items = [f for f in items if f["status"] == status]
    return _list_response(items)


@bp.get("/peer-review/providers/<pid>/quality-trend")
def provider_quality_trend(pid):
    require_roles("QualityDirector", "PeerReviewCoordinator")
    get_provider(pid)
    t = compute_trend(pid)
    fr = active_focused_review(pid)
    data = {
        "provider_id": pid,
        "window_start": iso(t["window_start"]),
        "window_end": iso(t["window_end"]),
        "rated_case_count": t["rated_case_count"],
        "avg_care_appropriateness": float(t["avg"]) if t["avg"] is not None else None,
        "major_ofi_case_count": t["major_ofi_case_count"],
        "unacceptable_case_count": t["unacceptable_case_count"],
        "focused_review_would_trigger": trigger_fires(t),
        "active_focused_review_id": fr["id"] if fr is not None else None,
    }
    return success(data)
