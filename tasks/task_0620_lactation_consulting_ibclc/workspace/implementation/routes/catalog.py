"""Practice catalog: sliding-scale tiers, service packages, consultants."""
from flask import Blueprint, request

import db
from middleware import get_auth, require_roles
from response import object_response, array_response
from services.common import (
    init_full, serialize, get_body,
    require_str, require_int, optional_int, paginate,
)
from services.lookups import get_or_404, get_fk_or_404

bp = Blueprint("catalog", __name__)

READ_ROLES = {"PracticeAdmin", "BillingSpecialist", "Consultant", "FrontDesk"}


# ---------------------------------------------------------------------------
# Sliding-scale tiers (PRD §3.1)
# ---------------------------------------------------------------------------
@bp.post("/sliding-scale-tiers")
def create_tier():
    _, role = get_auth()
    require_roles(role, {"PracticeAdmin"})
    body = get_body()
    practice_id = require_str(body, "practice_id")
    name = require_str(body, "name")
    income_ceiling_cents = require_int(body, "income_ceiling_cents")
    discount_pct = require_int(body, "discount_pct")
    get_fk_or_404(db.practices, practice_id)
    record = {
        "practice_id": practice_id,
        "name": name,
        "income_ceiling_cents": income_ceiling_cents,
        "discount_pct": discount_pct,
    }
    init_full(record)
    db.sliding_scale_tiers[record["id"]] = record
    return object_response(serialize(record), 201)


@bp.get("/sliding-scale-tiers/<rid>")
def get_tier(rid):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    record = get_or_404(db.sliding_scale_tiers, rid)
    return object_response(serialize(record), 200)


@bp.get("/sliding-scale-tiers")
def list_tiers():
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    practice_id = request.args.get("practice_id")
    records = [
        r for r in db.sliding_scale_tiers.values()
        if practice_id is None or r["practice_id"] == practice_id
    ]
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Service packages (PRD §3.1)
# ---------------------------------------------------------------------------
@bp.post("/service-packages")
def create_package():
    _, role = get_auth()
    require_roles(role, {"PracticeAdmin"})
    body = get_body()
    practice_id = require_str(body, "practice_id")
    name = require_str(body, "name")
    # included_visits count of at least one (PRD §3.1).
    included_visits = require_int(body, "included_visits", min_value=1)
    price_cents = require_int(body, "price_cents")
    get_fk_or_404(db.practices, practice_id)
    record = {
        "practice_id": practice_id,
        "name": name,
        "included_visits": included_visits,
        "price_cents": price_cents,
        # per_visit_value_cents = floor(price / included_visits) (PRD §3.1).
        "per_visit_value_cents": price_cents // included_visits,
    }
    init_full(record)
    db.service_packages[record["id"]] = record
    return object_response(serialize(record), 201)


@bp.get("/service-packages/<rid>")
def get_package(rid):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    record = get_or_404(db.service_packages, rid)
    return object_response(serialize(record), 200)


@bp.get("/service-packages")
def list_packages():
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    practice_id = request.args.get("practice_id")
    records = [
        r for r in db.service_packages.values()
        if practice_id is None or r["practice_id"] == practice_id
    ]
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Consultants (PRD §3.1)
# ---------------------------------------------------------------------------
@bp.post("/consultants")
def create_consultant():
    _, role = get_auth()
    require_roles(role, {"PracticeAdmin"})
    body = get_body()
    practice_id = require_str(body, "practice_id")
    full_name = require_str(body, "full_name")
    standard_rate_cents = require_int(body, "standard_rate_cents")
    # travel_buffer_minutes defaults to 60 (PRD §3.1).
    travel_buffer_minutes = optional_int(body, "travel_buffer_minutes", 60)
    get_fk_or_404(db.practices, practice_id)
    record = {
        "practice_id": practice_id,
        "full_name": full_name,
        "standard_rate_cents": standard_rate_cents,
        "travel_buffer_minutes": travel_buffer_minutes,
    }
    init_full(record)
    db.consultants[record["id"]] = record
    return object_response(serialize(record), 201)


@bp.get("/consultants/<rid>")
def get_consultant(rid):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    record = get_or_404(db.consultants, rid)
    return object_response(serialize(record), 200)


@bp.get("/consultants")
def list_consultants():
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    practice_id = request.args.get("practice_id")
    records = [
        r for r in db.consultants.values()
        if practice_id is None or r["practice_id"] == practice_id
    ]
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)
