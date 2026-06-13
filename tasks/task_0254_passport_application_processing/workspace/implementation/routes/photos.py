"""Photos: attach (immediate validation), read, list, revalidate.

Photo is a lighter-weight entity: only id + created_at (no updated_at/version).
"""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_VALIDATION
from middleware import require_auth
from response import ok_array, ok_object
from routes._helpers import (
    get_body,
    order_by_created,
    paginate,
    parse_pagination,
    serialize,
    serialize_list,
    stamp_create,
)
from services import calculations as calc

bp = Blueprint("photos", __name__)


def _app_or_404(rid: str) -> dict:
    rec = db.applications.get(rid)
    if rec is None:
        raise APIError(ERR_NOT_FOUND, 404, "Application not found")
    return rec


def _photo_or_404(rid: str) -> dict:
    rec = db.photos.get(rid)
    if rec is None:
        raise APIError(ERR_NOT_FOUND, 404, "Photo not found")
    return rec


def _validate_dimension(body: dict, field: str) -> int:
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field} must be an integer")
    if v <= 0:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field} must be > 0")
    return v


def _validate_fraction(body: dict, field: str) -> float:
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field} must be a number")
    if not (0 < v < 1):
        raise APIError(ERR_VALIDATION, 422, f"{field} must be strictly between 0 and 1")
    return v


def _validate_bool(body: dict, field: str) -> bool:
    v = body.get(field)
    if not isinstance(v, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field} must be a boolean")
    return v


@bp.route("/applications/<rid>/photos", methods=["POST"])
def attach_photo(rid):
    require_auth(["Applicant"])
    _app_or_404(rid)
    body = get_body()
    for f in ("width_px", "height_px", "head_height_fraction", "background_is_white"):
        if f not in body or body.get(f) is None:
            raise APIError(ERR_INVALID_REQUEST, 400, f"Missing required field: {f}")

    width_px = _validate_dimension(body, "width_px")
    height_px = _validate_dimension(body, "height_px")
    head_fraction = _validate_fraction(body, "head_height_fraction")
    bg_white = _validate_bool(body, "background_is_white")

    result, reasons = calc.validate_photo(width_px, height_px, head_fraction, bg_white)

    photo = {
        "application_id": rid,
        "width_px": width_px,
        "height_px": height_px,
        "head_height_fraction": head_fraction,
        "background_is_white": bg_white,
        "validation_result": result,
        "failure_reasons": reasons,
    }
    stamp_create(photo, full=False)  # lighter-weight: id + created_at only
    db.photos[photo["id"]] = photo

    _maybe_refresh_risk(rid)
    return ok_object(serialize(photo), 201)


@bp.route("/applications/<rid>/photos", methods=["GET"])
def list_photos(rid):
    require_auth(["Applicant", "AcceptanceAgent", "Adjudicator"])
    _app_or_404(rid)
    limit, offset = parse_pagination()
    items = [p for p in db.photos.values() if p["application_id"] == rid]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.route("/photos/<rid>/revalidate", methods=["POST"])
def revalidate_photo(rid):
    require_auth(["Applicant", "AcceptanceAgent"])
    photo = _photo_or_404(rid)
    body = get_body()

    # Each of the four inputs may be overridden; absent ones keep current value.
    if "width_px" in body and body["width_px"] is not None:
        photo["width_px"] = _validate_dimension(body, "width_px")
    if "height_px" in body and body["height_px"] is not None:
        photo["height_px"] = _validate_dimension(body, "height_px")
    if "head_height_fraction" in body and body["head_height_fraction"] is not None:
        photo["head_height_fraction"] = _validate_fraction(body, "head_height_fraction")
    if "background_is_white" in body and body["background_is_white"] is not None:
        photo["background_is_white"] = _validate_bool(body, "background_is_white")

    result, reasons = calc.validate_photo(
        photo["width_px"],
        photo["height_px"],
        photo["head_height_fraction"],
        photo["background_is_white"],
    )
    photo["validation_result"] = result
    photo["failure_reasons"] = reasons

    _maybe_refresh_risk(photo["application_id"])
    return ok_object(serialize(photo), 200)


def _maybe_refresh_risk(application_id: str) -> None:
    """A photo validation_result change is a verification-status change that
    triggers a FINAL risk recompute on the owning applicant (PRD §3.6).

    We recompute the applicant's stored score. We do NOT fire the verification
    auto-advance from a photo change (that cascade is keyed off document accepts),
    but the IN_VERIFICATION > 50 risk gate still applies.
    """
    app_rec = db.applications.get(application_id)
    if app_rec is None:
        return
    from services import domain

    applicant = db.applicants.get(app_rec["applicant_id"])
    if applicant is None:
        return
    score = domain.recompute_risk_final(applicant)
    domain.maybe_review_hold_on_risk(app_rec, score)
