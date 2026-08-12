"""Title catalog & territory restrictions routes."""
from flask import Blueprint, request

import db
from errors import (
    err_not_found, err_invalid_request, err_invalid_temporal, err_invalid_state,
)
from middleware import require_roles
from response import ok_object, ok_list, parse_pagination
from services.serializers import title_out, restriction_out

bp = Blueprint("titles", __name__)

TITLE_KINDS = {"PLAY", "MUSICAL", "MUSICAL_WITH_SCORE"}
ROYALTY_BASES = {"PER_PERFORMANCE", "GROSS_PERCENT", "HYBRID"}
RESTRICTION_KINDS = {"BLACKOUT", "EXCLUSIVE_RUN", "PRO_TOUR_OVERLAP"}
BLOCKS_CLASSIFICATIONS = {"AMATEUR", "PROFESSIONAL", "BOTH"}

ALL_ROLES = ("RightsAdmin", "LicensingOfficer", "Applicant", "MaterialsClerk", "FinanceOfficer")


def _req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v:
        raise err_invalid_request(f"{field} is required and must be a non-empty string")
    return v


def _req_int(body, field, minimum=None):
    v = body.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise err_invalid_request(f"{field} is required and must be an integer")
    if minimum is not None and v < minimum:
        raise err_invalid_request(f"{field} must be >= {minimum}")
    return v


def _req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise err_invalid_request(f"{field} is required and must be a boolean")
    return v


def _parse_bool_query(args, field):
    raw = args.get(field)
    if raw is None:
        return None
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    raise err_invalid_request(f"{field} must be true or false")


@bp.post("/licensing/titles")
def create_title():
    require_roles("RightsAdmin")
    body = request.get_json(silent=True) or {}
    name = _req_str(body, "name")
    author = _req_str(body, "author")
    title_kind = _req_str(body, "title_kind")
    if title_kind not in TITLE_KINDS:
        raise err_invalid_request("title_kind must be PLAY, MUSICAL, or MUSICAL_WITH_SCORE")
    royalty_basis = _req_str(body, "royalty_basis")
    if royalty_basis not in ROYALTY_BASES:
        raise err_invalid_request("royalty_basis must be PER_PERFORMANCE, GROSS_PERCENT, or HYBRID")
    base_flat_fee_cents = _req_int(body, "base_flat_fee_cents", 0)
    gross_percent_bp = _req_int(body, "gross_percent_bp", 0)
    restricted_material = _req_bool(body, "restricted_material")
    perusal_fee_cents = _req_int(body, "perusal_fee_cents", 0)
    rental_deposit_cents = _req_int(body, "rental_deposit_cents", 0)
    late_fee_per_day_cents = _req_int(body, "late_fee_per_day_cents", 0)
    restricted_late_fee_per_day_cents = _req_int(body, "restricted_late_fee_per_day_cents", 0)
    recording_royalty_flat_cents = _req_int(body, "recording_royalty_flat_cents", 0)

    now = db.clock_now()
    t = {
        "id": db.new_id(),
        "name": name,
        "author": author,
        "title_kind": title_kind,
        "royalty_basis": royalty_basis,
        "base_flat_fee_cents": base_flat_fee_cents,
        "gross_percent_bp": gross_percent_bp,
        "restricted_material": restricted_material,
        "perusal_fee_cents": perusal_fee_cents,
        "rental_deposit_cents": rental_deposit_cents,
        "late_fee_per_day_cents": late_fee_per_day_cents,
        "restricted_late_fee_per_day_cents": restricted_late_fee_per_day_cents,
        "recording_royalty_flat_cents": recording_royalty_flat_cents,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.titles[t["id"]] = t
    return ok_object(title_out(t), 201)


@bp.get("/licensing/titles/<title_id>")
def get_title(title_id):
    require_roles(*ALL_ROLES)
    t = db.titles.get(title_id)
    if not t:
        raise err_not_found("Title not found")
    return ok_object(title_out(t))


@bp.get("/licensing/titles")
def list_titles():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    title_kind = request.args.get("title_kind")
    restricted = _parse_bool_query(request.args, "restricted_material")
    if status is not None and status not in ("ACTIVE", "WITHDRAWN"):
        raise err_invalid_request("status filter invalid")
    if title_kind is not None and title_kind not in TITLE_KINDS:
        raise err_invalid_request("title_kind filter invalid")
    items = list(db.titles.values())
    if status is not None:
        items = [t for t in items if t["status"] == status]
    if title_kind is not None:
        items = [t for t in items if t["title_kind"] == title_kind]
    if restricted is not None:
        items = [t for t in items if t["restricted_material"] == restricted]
    items.sort(key=lambda t: (t["created_at"], t["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([title_out(t) for t in page], limit, offset, total)


@bp.post("/licensing/titles/<title_id>/withdraw")
def withdraw_title(title_id):
    require_roles("RightsAdmin")
    t = db.titles.get(title_id)
    if not t:
        raise err_not_found("Title not found")
    if t["status"] != "ACTIVE":
        raise err_invalid_state("Title is not ACTIVE")
    t["status"] = "WITHDRAWN"
    t["updated_at"] = db.clock_now()
    t["version"] += 1
    return ok_object(title_out(t))


@bp.post("/licensing/titles/<title_id>/restrictions")
def create_restriction(title_id):
    require_roles("RightsAdmin")
    t = db.titles.get(title_id)
    if not t:
        raise err_not_found("Title not found")
    body = request.get_json(silent=True) or {}
    territory_code = _req_str(body, "territory_code")
    restriction_kind = _req_str(body, "restriction_kind")
    if restriction_kind not in RESTRICTION_KINDS:
        raise err_invalid_request("restriction_kind invalid")
    blocks_classification = _req_str(body, "blocks_classification")
    if blocks_classification not in BLOCKS_CLASSIFICATIONS:
        raise err_invalid_request("blocks_classification invalid")
    ws_raw = body.get("window_start")
    we_raw = body.get("window_end")
    ws = db.parse_ts(ws_raw) if ws_raw is not None else None
    we = db.parse_ts(we_raw) if we_raw is not None else None
    if ws is None or we is None:
        raise err_invalid_temporal("window_start and window_end must be valid ISO8601 UTC datetimes")
    if not ws < we:
        raise err_invalid_temporal("window_start must be strictly before window_end")

    now = db.clock_now()
    r = {
        "id": db.new_id(),
        "title_id": title_id,
        "territory_code": territory_code,
        "restriction_kind": restriction_kind,
        "window_start": ws,
        "window_end": we,
        "blocks_classification": blocks_classification,
        "active": True,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.restrictions[r["id"]] = r
    return ok_object(restriction_out(r), 201)


@bp.get("/licensing/titles/<title_id>/restrictions")
def list_title_restrictions(title_id):
    require_roles(*ALL_ROLES)
    t = db.titles.get(title_id)
    if not t:
        raise err_not_found("Title not found")
    limit, offset = parse_pagination(request.args)
    territory_code = request.args.get("territory_code")
    items = [r for r in db.restrictions.values() if r["title_id"] == title_id]
    if territory_code is not None:
        items = [r for r in items if r["territory_code"] == territory_code]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([restriction_out(r) for r in page], limit, offset, total)


@bp.get("/licensing/restrictions/<restriction_id>")
def get_restriction(restriction_id):
    require_roles("RightsAdmin", "LicensingOfficer")
    r = db.restrictions.get(restriction_id)
    if not r:
        raise err_not_found("Restriction not found")
    return ok_object(restriction_out(r))


@bp.get("/licensing/restrictions")
def list_restrictions():
    require_roles("RightsAdmin", "LicensingOfficer", "Applicant")
    limit, offset = parse_pagination(request.args)
    title_id = request.args.get("title_id")
    territory_code = request.args.get("territory_code")
    active = _parse_bool_query(request.args, "active")
    items = list(db.restrictions.values())
    if title_id is not None:
        items = [r for r in items if r["title_id"] == title_id]
    if territory_code is not None:
        items = [r for r in items if r["territory_code"] == territory_code]
    if active is not None:
        items = [r for r in items if r["active"] == active]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([restriction_out(r) for r in page], limit, offset, total)


@bp.post("/licensing/restrictions/<restriction_id>/lift")
def lift_restriction(restriction_id):
    require_roles("RightsAdmin")
    r = db.restrictions.get(restriction_id)
    if not r:
        raise err_not_found("Restriction not found")
    if not r["active"]:
        raise err_invalid_state("Restriction already lifted")
    r["active"] = False
    r["updated_at"] = db.clock_now()
    r["version"] += 1
    return ok_object(restriction_out(r))
