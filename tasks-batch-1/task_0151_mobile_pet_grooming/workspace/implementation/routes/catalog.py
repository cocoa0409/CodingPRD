"""Catalog/config routes: breeds, service-tiers, add-ons, vans, groomers."""
from flask import Blueprint, request

import db
import models
import validate as V
from middleware import get_identity, require_role
from errors import err, ERR_INVALID_REQUEST
import lookup
from response import object_response

bp = Blueprint("catalog", __name__)

COAT_TYPES = {"SMOOTH", "DOUBLE", "CURLY", "WIRE", "HAIRLESS"}
SIZE_CLASSES = {"TOY", "SMALL", "MEDIUM", "LARGE", "GIANT"}
TIER_CODES = {"BATH_ONLY", "FULL_GROOM", "SHOW_CUT"}
ADDON_CODES = {"DESHED", "NAIL_TRIM", "TEETH_CLEAN"}
SKILL_LEVELS = {"JUNIOR", "SENIOR"}
GROOMER_STATUS = {"AVAILABLE", "OFF_DUTY"}


def _check_unique(store, field, value):
    for r in store.values():
        if r.get(field) == value:
            raise err(ERR_INVALID_REQUEST, "%s must be unique: %s" % (field, value))


# ---- Breed ----
@bp.route("/breeds", methods=["POST"])
def create_breed():
    _, role = get_identity()
    require_role(role, {"PlatformAdmin"})
    body = V.require_body(request.get_json(silent=True))
    name = V.require_str(body, "name")
    coat_type = V.require_enum(body, "coat_type", COAT_TYPES)
    size_class = V.require_enum(body, "size_class", SIZE_CLASSES)
    base_service_minutes = V.require_int(body, "base_service_minutes", minimum=15, maximum=240)
    _check_unique(db.breeds, "name", name)
    rec = models.base_versioned()
    rec.update({
        "name": name, "coat_type": coat_type, "size_class": size_class,
        "base_service_minutes": base_service_minutes,
    })
    db.breeds[rec["id"]] = rec
    return object_response(models.ser_breed(rec), 201)


@bp.route("/breeds/<rid>", methods=["GET"])
def get_breed(rid):
    _, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Customer", "Groomer"})
    rec = lookup.get_breed(rid)
    return object_response(models.ser_breed(rec), 200)


# ---- ServiceTier ----
@bp.route("/service-tiers", methods=["POST"])
def create_service_tier():
    _, role = get_identity()
    require_role(role, {"PlatformAdmin"})
    body = V.require_body(request.get_json(silent=True))
    code = V.require_enum(body, "code", TIER_CODES)
    base_price_cents = V.require_int(body, "base_price_cents", minimum=0)
    duration_multiplier = V.require_number(body, "duration_multiplier", minimum=1.0, maximum=3.0)
    _check_unique(db.service_tiers, "code", code)
    rec = models.base_versioned()
    rec.update({
        "code": code, "base_price_cents": base_price_cents,
        "duration_multiplier": duration_multiplier,
    })
    db.service_tiers[rec["id"]] = rec
    return object_response(models.ser_service_tier(rec), 201)


# ---- AddOn ----
@bp.route("/add-ons", methods=["POST"])
def create_add_on():
    _, role = get_identity()
    require_role(role, {"PlatformAdmin"})
    body = V.require_body(request.get_json(silent=True))
    code = V.require_enum(body, "code", ADDON_CODES)
    price_cents = V.require_int(body, "price_cents", minimum=0)
    duration_minutes = V.require_int(body, "duration_minutes", minimum=0, maximum=60)
    requires_calm = V.opt_bool(body, "requires_calm", False)
    _check_unique(db.add_ons, "code", code)
    rec = models.base_versioned()
    rec.update({
        "code": code, "price_cents": price_cents,
        "duration_minutes": duration_minutes, "requires_calm": requires_calm,
    })
    db.add_ons[rec["id"]] = rec
    return object_response(models.ser_add_on(rec), 201)


# ---- Van ----
@bp.route("/vans", methods=["POST"])
def create_van():
    _, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher"})
    body = V.require_body(request.get_json(silent=True))
    label = V.require_str(body, "label")
    max_stops = V.require_int(body, "max_stops", minimum=1, maximum=20)
    has_show_equipment = V.opt_bool(body, "has_show_equipment", False)
    _check_unique(db.vans, "label", label)
    rec = models.base_versioned()
    rec.update({
        "label": label, "max_stops": max_stops,
        "has_show_equipment": has_show_equipment,
    })
    db.vans[rec["id"]] = rec
    return object_response(models.ser_van(rec), 201)


# ---- Groomer ----
@bp.route("/groomers", methods=["POST"])
def create_groomer():
    _, role = get_identity()
    require_role(role, {"PlatformAdmin"})
    body = V.require_body(request.get_json(silent=True))
    email = V.require_str(body, "email")
    full_name = V.require_str(body, "full_name")
    skill_level = V.require_enum(body, "skill_level", SKILL_LEVELS)
    handles_aggressive = V.opt_bool(body, "handles_aggressive", False)
    status = V.opt_enum(body, "status", GROOMER_STATUS, "AVAILABLE")
    _check_unique(db.groomers, "email", email)
    rec = models.base_versioned()
    rec.update({
        "email": email, "full_name": full_name, "skill_level": skill_level,
        "handles_aggressive": handles_aggressive, "status": status,
    })
    db.groomers[rec["id"]] = rec
    return object_response(models.ser_groomer(rec), 201)


@bp.route("/groomers/<rid>", methods=["GET"])
def get_groomer(rid):
    _, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Groomer"})
    rec = lookup.get_groomer(rid)
    return object_response(models.ser_groomer(rec), 200)
