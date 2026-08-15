"""Image endpoints: ingest, search, clear, archive, embargo, reuse-check."""

from flask import Blueprint, request
from db import (
    images, photographers, assignments, licenses, usage_runs,
    new_id, now_iso, parse_iso, logical_now,
)
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_IMAGE_NOT_FOUND,
    ERR_INVALID_STATE, ERR_INCOMPLETE_METADATA, ERR_FORBIDDEN,
    ERR_STALE_VERSION, ERR_IMAGE_NOT_CLEARED, ERR_RIGHTS_REVERTED,
)
from response import success_object, success_list
from middleware import get_auth, require_role
from serializers import serialize_image, serialize_license, _image_rights_reverted
from services.calculations import compute_license_fee, compute_rights_reversion

bp = Blueprint("images", __name__)


@bp.route("/images", methods=["POST"])
def ingest_image():
    user_id, role = get_auth()
    require_role(role, {"RightsManager"})

    body = request.get_json(force=True, silent=True) or {}

    source_type = body.get("source_type")
    if source_type not in ("WIRE", "STOCK"):
        if source_type == "ASSIGNMENT":
            raise ApiError(ERR_INVALID_REQUEST, "Cannot ingest ASSIGNMENT images directly", 400)
        raise ApiError(ERR_INVALID_REQUEST, "source_type must be WIRE or STOCK", 400)

    agency_name = body.get("agency_name")
    if not agency_name or not isinstance(agency_name, str):
        raise ApiError(ERR_INVALID_REQUEST, "agency_name is required for WIRE/STOCK ingest", 400)

    base_fee = body.get("base_license_fee_cents")
    if base_fee is None or not isinstance(base_fee, int) or isinstance(base_fee, bool):
        raise ApiError(ERR_INVALID_REQUEST, "base_license_fee_cents is required and must be an integer", 400)

    caption = body.get("caption")
    credit_line = body.get("credit_line")
    keywords = body.get("keywords", [])
    if not isinstance(keywords, list):
        raise ApiError(ERR_INVALID_REQUEST, "keywords must be an array", 400)
    has_people = body.get("has_identifiable_people", False)
    has_property = body.get("has_private_property", False)
    embargo_until = body.get("embargo_until")

    iid = new_id()
    now = now_iso()
    img = {
        "id": iid,
        "photographer_id": None,
        "assignment_id": None,
        "source_type": source_type,
        "agency_name": agency_name,
        "base_license_fee_cents": base_fee,
        "caption": caption,
        "credit_line": credit_line,
        "keywords": keywords,
        "has_identifiable_people": has_people,
        "has_private_property": has_property,
        "embargo_until": embargo_until,
        "status": "INGESTED",
        "restriction_status": "NONE",
        "times_used": 0,
        "first_published_at": None,
        "rights_reversion_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    images[iid] = img
    return success_object(serialize_image(img), 201)


@bp.route("/images", methods=["GET"])
def search_images():
    user_id, role = get_auth()
    require_role(role, {"PhotoEditor", "RightsManager", "Archivist", "FinanceAdmin", "Photographer"})

    # include_archived restricted to Archivist and RightsManager
    include_archived = request.args.get("include_archived", "false").lower() == "true"
    if include_archived and role not in ("Archivist", "RightsManager"):
        raise ApiError(ERR_FORBIDDEN, "include_archived=true is restricted to Archivist and RightsManager", 403)

    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "limit and offset must be integers", 400)
    limit = max(1, min(100, limit))
    offset = max(0, offset)

    # Filters
    q = request.args.get("q", "").lower()
    status_filter = request.args.get("status")
    source_type_filter = request.args.get("source_type")
    photographer_id_filter = request.args.get("photographer_id")
    assignment_id_filter = request.args.get("assignment_id")

    items = list(images.values())

    # ARCHIVED excluded unless include_archived=true
    if not include_archived:
        items = [i for i in items if i["status"] != "ARCHIVED"]

    if q:
        def matches(img):
            caption = (img.get("caption") or "").lower()
            keywords = " ".join(img.get("keywords") or []).lower()
            return q in caption or q in keywords
        items = [i for i in items if matches(i)]

    if status_filter:
        items = [i for i in items if i["status"] == status_filter]
    if source_type_filter:
        items = [i for i in items if i["source_type"] == source_type_filter]
    if photographer_id_filter:
        items = [i for i in items if i.get("photographer_id") == photographer_id_filter]
    if assignment_id_filter:
        items = [i for i in items if i.get("assignment_id") == assignment_id_filter]

    items.sort(key=lambda i: i["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_image(i) for i in page], limit, offset, total)


@bp.route("/images/<iid>", methods=["GET"])
def get_image(iid):
    user_id, role = get_auth()
    require_role(role, {"PhotoEditor", "RightsManager", "Archivist", "FinanceAdmin", "Photographer"})

    img = images.get(iid)
    if img is None:
        raise ApiError(ERR_IMAGE_NOT_FOUND, f"Image {iid} not found", 404)
    return success_object(serialize_image(img))


@bp.route("/images/<iid>/clear", methods=["POST"])
def clear_image(iid):
    user_id, role = get_auth()
    require_role(role, {"RightsManager"})

    img = images.get(iid)
    if img is None:
        raise ApiError(ERR_IMAGE_NOT_FOUND, f"Image {iid} not found", 404)

    if img["status"] != "INGESTED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot clear image in status {img['status']}", 409)

    # Metadata gate: caption >= 10 chars, credit_line non-empty
    caption = img.get("caption") or ""
    credit_line = img.get("credit_line") or ""
    if len(caption) < 10 or not credit_line.strip():
        raise ApiError(ERR_INCOMPLETE_METADATA,
                       "Caption must be >= 10 chars and credit_line must be non-empty", 422)

    img["status"] = "CLEARED"
    img["updated_at"] = now_iso()
    img["version"] += 1
    return success_object(serialize_image(img))


@bp.route("/images/<iid>/archive", methods=["POST"])
def archive_image(iid):
    user_id, role = get_auth()
    require_role(role, {"RightsManager"})

    img = images.get(iid)
    if img is None:
        raise ApiError(ERR_IMAGE_NOT_FOUND, f"Image {iid} not found", 404)

    if img["status"] not in ("CLEARED", "PUBLISHED"):
        raise ApiError(ERR_INVALID_STATE, f"Cannot archive image in status {img['status']}", 409)

    img["status"] = "ARCHIVED"
    img["updated_at"] = now_iso()
    img["version"] += 1
    return success_object(serialize_image(img))


@bp.route("/images/<iid>/embargo", methods=["PUT"])
def set_embargo(iid):
    user_id, role = get_auth()
    require_role(role, {"RightsManager"})

    img = images.get(iid)
    if img is None:
        raise ApiError(ERR_IMAGE_NOT_FOUND, f"Image {iid} not found", 404)

    body = request.get_json(force=True, silent=True) or {}
    embargo_until = body.get("embargo_until")

    # Validate embargo_until if not null
    if embargo_until is not None:
        if not isinstance(embargo_until, str) or parse_iso(embargo_until) is None:
            raise ApiError(ERR_INVALID_REQUEST, "embargo_until must be a valid ISO 8601 datetime or null", 400)

    img["embargo_until"] = embargo_until
    img["updated_at"] = now_iso()
    img["version"] += 1
    return success_object(serialize_image(img))


@bp.route("/images/<iid>/reuse-check", methods=["GET"])
def reuse_check(iid):
    user_id, role = get_auth()
    require_role(role, {"PhotoEditor", "RightsManager", "Archivist"})

    img = images.get(iid)
    if img is None:
        raise ApiError(ERR_IMAGE_NOT_FOUND, f"Image {iid} not found", 404)

    channel = request.args.get("channel")
    published_at_str = request.args.get("published_at")

    blocking_reasons = []
    eligible = True

    # Compute fee quote for current state
    usage_scope = channel if channel in ("PRINT", "DIGITAL", "SOCIAL", "SYNDICATION") else "PRINT"
    fee_cents, pricing_variant = compute_license_fee(img, usage_scope, "DOMESTIC", False)

    # Check image status
    if img["status"] not in ("CLEARED", "PUBLISHED", "ARCHIVED"):
        eligible = False
        blocking_reasons.append("IMAGE_NOT_CLEARED")

    # Check restriction
    if img["restriction_status"] == "RESTRICTED":
        eligible = False
        blocking_reasons.append("IMAGE_UNDER_CLAIM")

    # Check rights reversion
    if _image_rights_reverted(img):
        eligible = False
        blocking_reasons.append("RIGHTS_REVERTED")

    # Check embargo
    if published_at_str and img.get("embargo_until"):
        pa = parse_iso(published_at_str)
        eu = parse_iso(img["embargo_until"])
        if pa and eu and pa < eu:
            eligible = False
            blocking_reasons.append("EMBARGO_ACTIVE")

    # Release requirements
    from db import releases as releases_store
    requires_model = img.get("has_identifiable_people", False)
    requires_property = img.get("has_private_property", False)

    return success_object({
        "eligible": eligible,
        "blocking_reasons": blocking_reasons,
        "fee_quote_cents": fee_cents,
        "pricing_variant": pricing_variant,
        "requires_model_release": requires_model,
        "requires_property_release": requires_property,
    })


# ---------------------------------------------------------------------------
# POST /images/{id}/licenses — license creation (OCC-guarded)
# ---------------------------------------------------------------------------

@bp.route("/images/<iid>/licenses", methods=["POST"])
def create_license(iid):
    user_id, role = get_auth()
    require_role(role, {"RightsManager"})

    body = request.get_json(force=True, silent=True) or {}

    # Priority 3: request shape
    usage_scope = body.get("usage_scope")
    valid_from = body.get("valid_from")
    valid_to = body.get("valid_to")
    expected_image_version = body.get("expected_image_version")

    if usage_scope not in ("PRINT", "DIGITAL", "SOCIAL", "SYNDICATION"):
        raise ApiError(ERR_INVALID_REQUEST, "usage_scope must be PRINT, DIGITAL, SOCIAL, or SYNDICATION", 400)
    if not valid_from or not isinstance(valid_from, str):
        raise ApiError(ERR_INVALID_REQUEST, "valid_from is required", 400)
    if not valid_to or not isinstance(valid_to, str):
        raise ApiError(ERR_INVALID_REQUEST, "valid_to is required", 400)
    vf = parse_iso(valid_from)
    vt = parse_iso(valid_to)
    if vf is None or vt is None:
        raise ApiError(ERR_INVALID_REQUEST, "valid_from and valid_to must be valid ISO 8601 datetimes", 400)
    if vt < vf:
        raise ApiError(ERR_INVALID_REQUEST, "valid_to must be >= valid_from", 400)

    territory = body.get("territory", "DOMESTIC")
    if territory not in ("DOMESTIC", "INTERNATIONAL", "GLOBAL"):
        raise ApiError(ERR_INVALID_REQUEST, "territory must be DOMESTIC, INTERNATIONAL, or GLOBAL", 400)
    exclusive = body.get("exclusive", False)
    if not isinstance(exclusive, bool):
        raise ApiError(ERR_INVALID_REQUEST, "exclusive must be a boolean", 400)
    story_request_id = body.get("story_request_id")

    # Priority 4: existence
    img = images.get(iid)
    if img is None:
        raise ApiError(ERR_IMAGE_NOT_FOUND, f"Image {iid} not found", 404)

    # Priority 6: image must be in {CLEARED, PUBLISHED, ARCHIVED}
    if img["status"] not in ("CLEARED", "PUBLISHED", "ARCHIVED"):
        raise ApiError(ERR_IMAGE_NOT_CLEARED, "Image is not yet cleared", 409)

    # Priority 17: rights reversion gate
    if _image_rights_reverted(img):
        raise ApiError(ERR_RIGHTS_REVERTED, "Rights have reverted to the photographer", 409)

    # Priority 25: OCC
    if expected_image_version is not None and expected_image_version != img["version"]:
        raise ApiError(ERR_STALE_VERSION, "Image version mismatch", 412)

    # Compute fee
    fee_cents, pricing_variant = compute_license_fee(img, usage_scope, territory, exclusive)

    # Compute new license id first so we can stamp superseded_by_id correctly
    lid = new_id()
    now = now_iso()

    # Supersede ACTIVE same-scope license
    for old_lic in licenses.values():
        if old_lic["image_id"] == iid and old_lic["status"] == "ACTIVE" and old_lic["usage_scope"] == usage_scope:
            # Check lazy expiry first — if it reads as EXPIRED, skip
            from serializers import _license_effective_status
            if _license_effective_status(old_lic) == "EXPIRED":
                continue
            old_lic["status"] = "REVOKED"
            old_lic["superseded_by_id"] = lid
            old_lic["updated_at"] = now
            old_lic["version"] += 1
            # Release budget from story
            if old_lic.get("story_request_id"):
                from db import story_requests
                sr = story_requests.get(old_lic["story_request_id"])
                if sr:
                    sr["committed_cents"] -= old_lic["fee_cents"]
                    sr["updated_at"] = now
                    sr["version"] += 1

    # Increment image version
    img["version"] += 1
    img["updated_at"] = now

    lic = {
        "id": lid,
        "image_id": iid,
        "story_request_id": story_request_id,
        "usage_scope": usage_scope,
        "territory": territory,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "exclusive": exclusive,
        "pricing_variant": pricing_variant,
        "fee_cents": fee_cents,
        "superseded_by_id": None,
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    licenses[lid] = lic

    return success_object(serialize_license(lic), 201)


@bp.route("/images/<iid>/licenses", methods=["GET"])
def list_image_licenses(iid):
    user_id, role = get_auth()
    require_role(role, {"PhotoEditor", "RightsManager", "Archivist"})

    img = images.get(iid)
    if img is None:
        raise ApiError(ERR_IMAGE_NOT_FOUND, f"Image {iid} not found", 404)

    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "limit and offset must be integers", 400)
    limit = max(1, min(100, limit))
    offset = max(0, offset)

    status_filter = request.args.get("status")

    items = [l for l in licenses.values() if l["image_id"] == iid]
    if status_filter:
        from serializers import _license_effective_status
        items = [l for l in items if _license_effective_status(l) == status_filter]
    items.sort(key=lambda l: l["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_license(l) for l in page], limit, offset, total)


@bp.route("/images/<iid>/usage-runs", methods=["POST"])
def create_usage_run(iid):
    user_id, role = get_auth()
    require_role(role, {"PhotoEditor", "RightsManager"})

    body = request.get_json(force=True, silent=True) or {}

    # Priority 3: request shape
    license_id = body.get("license_id")
    channel = body.get("channel")
    story_slug = body.get("story_slug")
    published_at = body.get("published_at")

    if not license_id or not isinstance(license_id, str):
        raise ApiError(ERR_INVALID_REQUEST, "license_id is required", 400)
    if channel not in ("PRINT", "DIGITAL", "SOCIAL", "SYNDICATION"):
        raise ApiError(ERR_INVALID_REQUEST, "channel must be PRINT, DIGITAL, SOCIAL, or SYNDICATION", 400)
    if not story_slug or not isinstance(story_slug, str):
        raise ApiError(ERR_INVALID_REQUEST, "story_slug is required", 400)
    if not published_at or not isinstance(published_at, str):
        raise ApiError(ERR_INVALID_REQUEST, "published_at is required", 400)
    pa = parse_iso(published_at)
    if pa is None:
        raise ApiError(ERR_INVALID_REQUEST, "published_at must be a valid ISO 8601 datetime", 400)

    # Priority 4: existence
    img = images.get(iid)
    if img is None:
        raise ApiError(ERR_IMAGE_NOT_FOUND, f"Image {iid} not found", 404)
    lic = licenses.get(license_id)
    if lic is None:
        raise ApiError("ERR_LICENSE_NOT_FOUND", f"License {license_id} not found", 404)

    # Priority 6: image editorial gate
    if img["status"] not in ("CLEARED", "PUBLISHED", "ARCHIVED"):
        raise ApiError(ERR_IMAGE_NOT_CLEARED, "Image is not yet cleared", 409)

    # Priority 8: release gate
    from db import releases as releases_store
    from serializers import _release_effective_status
    if img.get("has_identifiable_people"):
        has_model = any(
            r["image_id"] == iid and r["subject_type"] == "MODEL" and _release_effective_status(r) == "ACTIVE"
            for r in releases_store.values()
        )
        if not has_model:
            raise ApiError("ERR_RELEASE_REQUIRED", "Image requires an ACTIVE MODEL release", 422)
    if img.get("has_private_property"):
        has_prop = any(
            r["image_id"] == iid and r["subject_type"] == "PROPERTY" and _release_effective_status(r) == "ACTIVE"
            for r in releases_store.values()
        )
        if not has_prop:
            raise ApiError("ERR_RELEASE_REQUIRED", "Image requires an ACTIVE PROPERTY release", 422)

    # Priority 15: embargo
    if img.get("embargo_until"):
        eu = parse_iso(img["embargo_until"])
        if eu and pa < eu:
            raise ApiError("ERR_EMBARGO_ACTIVE", "Publication is before embargo", 422)

    # Priority 16: license window (closed interval [valid_from, valid_to])
    vf = parse_iso(lic["valid_from"])
    vt = parse_iso(lic["valid_to"])
    if vf and pa < vf:
        raise ApiError("ERR_LICENSE_WINDOW_VIOLATION", "published_at is before valid_from", 422)
    if vt and pa > vt:
        raise ApiError("ERR_LICENSE_WINDOW_VIOLATION", "published_at is after valid_to", 422)

    # Priority 18: restriction gate
    if img["restriction_status"] != "NONE":
        raise ApiError("ERR_IMAGE_UNDER_CLAIM", "Image has an open claim", 409)

    # Priority 19: license belongs to image
    if lic["image_id"] != iid:
        raise ApiError("ERR_LICENSE_IMAGE_MISMATCH", "License does not belong to this image", 422)

    # Priority 20: channel must match license scope
    if channel != lic["usage_scope"]:
        raise ApiError("ERR_SCOPE_NOT_LICENSED", "Channel does not match license usage_scope", 422)

    # Priority 21: license must be ACTIVE
    from serializers import _license_effective_status
    eff_status = _license_effective_status(lic)
    if eff_status != "ACTIVE":
        raise ApiError("ERR_LICENSE_NOT_ACTIVE", f"License is {eff_status}", 409)

    # All gates passed — create usage run
    now = now_iso()

    # Compute royalty
    from services.calculations import compute_usage_royalty
    royalty = compute_usage_royalty(img, channel)

    # Update image
    img["times_used"] += 1
    is_first = img["status"] == "CLEARED"
    if is_first:
        img["status"] = "PUBLISHED"
        img["first_published_at"] = published_at
        # Rights reversion for ASSIGNMENT images
        if img["source_type"] == "ASSIGNMENT" and img.get("photographer_id"):
            photog = photographers.get(img["photographer_id"])
            if photog:
                img["rights_reversion_at"] = compute_rights_reversion(published_at, photog)

    img["updated_at"] = now
    img["version"] += 1

    # Credit royalty to photographer
    if royalty > 0 and img.get("photographer_id"):
        photog = photographers.get(img["photographer_id"])
        if photog:
            photog["accrued_earnings_cents"] += royalty
            photog["updated_at"] = now
            photog["version"] += 1

    # Story fulfillment
    if lic.get("story_request_id"):
        from db import story_requests
        sr = story_requests.get(lic["story_request_id"])
        if sr and sr["status"] == "DECIDED":
            sr["status"] = "FULFILLED"
            sr["updated_at"] = now
            sr["version"] += 1

    urid = new_id()
    ur = {
        "id": urid,
        "image_id": iid,
        "license_id": license_id,
        "channel": channel,
        "story_slug": story_slug,
        "published_at": published_at,
        "royalty_cents": royalty,
        "created_at": now,
    }
    usage_runs[urid] = ur

    from serializers import serialize_usage_run
    return success_object(serialize_usage_run(ur), 201)


@bp.route("/images/<iid>/usage-runs", methods=["GET"])
def list_image_usage_runs(iid):
    user_id, role = get_auth()
    require_role(role, {"PhotoEditor", "RightsManager", "Archivist", "FinanceAdmin"})

    img = images.get(iid)
    if img is None:
        raise ApiError(ERR_IMAGE_NOT_FOUND, f"Image {iid} not found", 404)

    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "limit and offset must be integers", 400)
    limit = max(1, min(100, limit))
    offset = max(0, offset)

    items = [u for u in usage_runs.values() if u["image_id"] == iid]
    items.sort(key=lambda u: u["created_at"])
    total = len(items)
    page = items[offset:offset + limit]

    from serializers import serialize_usage_run
    return success_list([serialize_usage_run(u) for u in page], limit, offset, total)
