"""Film endpoints and lifecycle transitions."""

from flask import Blueprint

from db import db, new_id
from clock import now_iso, now_dt
from middleware import (
    require_roles,
    get_auth,
    parse_json_body,
    require_fields,
    require_int,
    require_str,
    require_enum,
)
from response import success_object
from errors import (
    ERR_NOT_FOUND,
    ERR_REFERENCED_ENTITY_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_BAD_REQUEST,
    raise_error,
)
from datetime_utils import parse_iso8601
from services.audit import append_audit
from services.version_check import check_version, check_idempotent_action

bp = Blueprint("films", __name__)


FILM_RATINGS = {"G", "PG", "PG13", "R", "NC17"}
FILM_FORMATS = {"2D", "3D", "IMAX"}
TIER_KEYS = {"TIER_1", "TIER_2", "TIER_3"}


def _serialize(f):
    out = dict(f)
    return out


def _validate_region_strategy(rs):
    if not isinstance(rs, dict):
        raise_error(ERR_BAD_REQUEST, "region_strategy must be an object")
    if "allowed_regions" not in rs or "tier_caps" not in rs:
        raise_error(ERR_BAD_REQUEST, "region_strategy missing allowed_regions or tier_caps")
    allowed_regions = rs["allowed_regions"]
    tier_caps = rs["tier_caps"]
    if not isinstance(allowed_regions, list) or not all(isinstance(r, str) for r in allowed_regions):
        raise_error(ERR_BAD_REQUEST, "allowed_regions must be array of strings")
    if not isinstance(tier_caps, dict):
        raise_error(ERR_BAD_REQUEST, "tier_caps must be object")
    for k, v in tier_caps.items():
        if k not in TIER_KEYS:
            raise_error(ERR_BAD_REQUEST, f"tier_caps unknown key {k}")
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise_error(ERR_BAD_REQUEST, "tier_caps values must be non-negative integers")
    return {"allowed_regions": list(allowed_regions), "tier_caps": dict(tier_caps)}


@bp.route("/films", methods=["POST"])
@require_roles({"DistributorOps"})
def create_film():
    body = parse_json_body()
    require_fields(body, ["title", "distributor_id", "duration_minutes", "rating", "format", "release_date", "region_strategy"])
    title = require_str(body.get("title"), "title")
    distributor_id = require_str(body.get("distributor_id"), "distributor_id")
    duration_minutes = require_int(body.get("duration_minutes"), "duration_minutes", min_v=1)
    rating = require_enum(body.get("rating"), "rating", FILM_RATINGS)
    fmt = require_enum(body.get("format"), "format", FILM_FORMATS)
    release_date_raw = require_str(body.get("release_date"), "release_date")
    # parse to validate ISO8601
    parse_iso8601(release_date_raw, "release_date")
    region_strategy = _validate_region_strategy(body.get("region_strategy"))

    # Foreign key existence
    distributor = db.distributors.get(distributor_id)
    if not distributor:
        raise_error(ERR_REFERENCED_ENTITY_NOT_FOUND, "distributor not found")

    now = now_iso()
    film = {
        "id": new_id(),
        "title": title,
        "distributor_id": distributor_id,
        "duration_minutes": duration_minutes,
        "rating": rating,
        "format": fmt,
        "release_date": release_date_raw,
        "region_strategy": region_strategy,
        "status": "PLANNED",
        "shelved_reason": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.films[film["id"]] = film
    return success_object(_serialize(film), http_status=201)


@bp.route("/films/<film_id>", methods=["GET"])
@require_roles({"PlatformAdmin", "DistributorOps", "CinemaOps", "FinanceOps", "Auditor"})
def get_film(film_id):
    f = db.films.get(film_id)
    if not f:
        raise_error(ERR_NOT_FOUND, "film not found")
    return success_object(_serialize(f))


def _reopen_showtime_after_release(s, film):
    """When a film is re-RELEASED, reopen showtimes that are SCHEDULED with sale_status=CLOSED
    purely due to shelving. Restore to PRESALE or ON_SALE based on presale_opens_at."""
    if s["lifecycle_status"] != "SCHEDULED":
        return
    if s["sale_status"] != "CLOSED":
        return
    presale_opens = parse_iso8601(s["presale_opens_at"], "presale_opens_at")
    if now_dt() >= presale_opens:
        s["sale_status"] = "ON_SALE"
    else:
        s["sale_status"] = "PRESALE"
    s["updated_at"] = now_iso()
    s["version"] = s.get("version", 1) + 1


@bp.route("/films/<film_id>/release", methods=["POST"])
@require_roles({"DistributorOps"})
def release_film(film_id):
    role, user_id = get_auth()
    film = db.films.get(film_id)
    if not film:
        raise_error(ERR_NOT_FOUND, "film not found")
    body = parse_json_body()
    requested_version = body.get("version")
    if requested_version is not None and (isinstance(requested_version, bool) or not isinstance(requested_version, int)):
        raise_error(ERR_BAD_REQUEST, "version must be integer")

    # State check: only PLANNED or SHELVED can release
    if film["status"] not in ("PLANNED", "SHELVED"):
        check_idempotent_action(film["version"], requested_version, film["status"] == "RELEASED")
        raise_error(ERR_INVALID_STATE, "film cannot be released from current state")

    # version + idempotency: if already RELEASED but caller used an older version, signal duplicate
    # film not in RELEASED state here, so just regular version check
    check_version(film["version"], requested_version)

    # Preconditions
    release_dt = parse_iso8601(film["release_date"], "release_date")
    if now_dt() < release_dt:
        raise_error(ERR_INVALID_STATE, "release_date not yet reached")

    distributor = db.distributors.get(film["distributor_id"])
    if film["status"] == "PLANNED":
        # PLANNED -> RELEASED requires distributor ACTIVE
        if not distributor or distributor.get("status") != "ACTIVE":
            raise_error(ERR_INVALID_STATE, "distributor not active")

    # Apply
    was_shelved = film["status"] == "SHELVED"
    film["status"] = "RELEASED"
    film["shelved_reason"] = None
    film["updated_at"] = now_iso()
    film["version"] = film["version"] + 1

    if was_shelved:
        for s in db.showtimes.values():
            if s["film_id"] == film_id:
                _reopen_showtime_after_release(s, film)

    append_audit(role, user_id, "FILM_RELEASE", "Film", film_id, {"status": "RELEASED"})

    return success_object(_serialize(film))


@bp.route("/films/<film_id>/shelve", methods=["POST"])
@require_roles({"DistributorOps"})
def shelve_film(film_id):
    role, user_id = get_auth()
    film = db.films.get(film_id)
    if not film:
        raise_error(ERR_NOT_FOUND, "film not found")
    body = parse_json_body()
    requested_version = body.get("version")
    if requested_version is not None and (isinstance(requested_version, bool) or not isinstance(requested_version, int)):
        raise_error(ERR_BAD_REQUEST, "version must be integer")
    reason = body.get("reason")
    if reason is None or not isinstance(reason, str) or not reason.strip():
        raise_error(ERR_BAD_REQUEST, "reason required")

    if film["status"] != "RELEASED":
        check_idempotent_action(film["version"], requested_version, film["status"] == "SHELVED")
        raise_error(ERR_INVALID_STATE, "film must be RELEASED to shelve")

    check_version(film["version"], requested_version)

    # Precondition: at least one Showtime in SCHEDULED or IN_PROGRESS
    has_active = any(
        s["film_id"] == film_id and s["lifecycle_status"] in ("SCHEDULED", "IN_PROGRESS")
        for s in db.showtimes.values()
    )
    if not has_active:
        raise_error(ERR_INVALID_STATE, "film has no active showtimes to shelve")

    film["status"] = "SHELVED"
    film["shelved_reason"] = reason
    film["updated_at"] = now_iso()
    film["version"] = film["version"] + 1

    # Side effect: every future SCHEDULED Showtime sale_status flips to CLOSED
    for s in db.showtimes.values():
        if s["film_id"] != film_id:
            continue
        if s["lifecycle_status"] == "SCHEDULED" and s["sale_status"] in ("PRESALE", "ON_SALE"):
            s["sale_status"] = "CLOSED"
            s["updated_at"] = now_iso()
            s["version"] = s.get("version", 1) + 1

    append_audit(role, user_id, "FILM_SHELVE", "Film", film_id, {"status": "SHELVED", "reason": reason})

    return success_object(_serialize(film))


@bp.route("/films/<film_id>/delist", methods=["POST"])
@require_roles({"DistributorOps"})
def delist_film(film_id):
    role, user_id = get_auth()
    film = db.films.get(film_id)
    if not film:
        raise_error(ERR_NOT_FOUND, "film not found")
    body = parse_json_body()
    requested_version = body.get("version")
    if requested_version is not None and (isinstance(requested_version, bool) or not isinstance(requested_version, int)):
        raise_error(ERR_BAD_REQUEST, "version must be integer")

    if film["status"] == "DELISTED":
        check_idempotent_action(film["version"], requested_version, True)
        raise_error(ERR_INVALID_STATE, "film already DELISTED")

    check_version(film["version"], requested_version)

    # No additional preconditions; cascade fires
    film["status"] = "DELISTED"
    film["updated_at"] = now_iso()
    film["version"] = film["version"] + 1

    # Cascade
    from services.cascade import cascade_film_delist
    cascade_film_delist(film, role, user_id)

    append_audit(role, user_id, "FILM_DELIST", "Film", film_id, {"status": "DELISTED"})
    return success_object(_serialize(film))
