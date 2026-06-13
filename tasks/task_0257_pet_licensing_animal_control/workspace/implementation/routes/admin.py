"""Test-driving administrative endpoints (PRD §2.10, §4).

/_clock/set       — set logical current time
/_clock/advance   — advance time, re-evaluate auto-transitions
/_bulk/seed-kennel-licenses — synthesize fully-ACTIVE kennel licenses
"""
from datetime import timedelta

from flask import Blueprint

from db import db, iso, now_iso
from errors import err
from middleware import authenticate, require_role
from response import object_response
from services import license as lic_svc
from services.calc import license_fee
from services.core import (add_years, parse_iso, recompute_kennel_occupied_slots,
                          recompute_owner_active_license_count, stamp_create, touch)
from services.reqs import body, require_fields

bp = Blueprint("admin", __name__)


@bp.route("/_clock/set", methods=["POST"])
def clock_set():
    _, role = authenticate()
    require_role(role, {"LicensingClerk", "AnimalControlOfficer"})
    data = body()
    require_fields(data, ["to_iso8601"])
    target = parse_iso(data["to_iso8601"])
    if target is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant.")
    db.current_utc = target
    return object_response({})


@bp.route("/_clock/advance", methods=["POST"])
def clock_advance():
    _, role = authenticate()
    require_role(role, {"LicensingClerk", "AnimalControlOfficer"})
    data = body()
    require_fields(data, ["to_iso8601"])
    target = parse_iso(data["to_iso8601"])
    if target is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant.")
    db.current_utc = target
    lic_svc.evaluate_clock_transitions()
    return object_response({})


@bp.route("/_bulk/seed-kennel-licenses", methods=["POST"])
def seed_kennel_licenses():
    _, role = authenticate()
    require_role(role, {"LicensingClerk"})
    data = body()
    require_fields(data, ["kennel_id", "owner_id", "count"])
    kennel = db.kennels.get(data["kennel_id"])
    if kennel is None:
        raise err("ERR_NOT_FOUND", "Kennel not found.")
    owner = db.owners.get(data["owner_id"])
    if owner is None:
        raise err("ERR_NOT_FOUND", "Owner not found.")
    count = data["count"]
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise err("ERR_INVALID_REQUEST", "count must be a non-negative integer.")
    is_altered = data.get("is_altered", False)
    if not isinstance(is_altered, bool):
        raise err("ERR_INVALID_REQUEST", "is_altered must be a boolean.")

    now = db.current_utc
    for _ in range(count):
        # synthesize pet
        pet = {
            "owner_id": owner["id"],
            "name": "SeedPet",
            "species": "DOG",
            "breed": "Seed",
            "is_altered": is_altered,
            "birth_date": iso(now),
            "is_dangerous": False,
            "status": "ACTIVE",
        }
        stamp_create(pet)
        db.pets[pet["id"]] = pet

        # synthesize RABIES proof (unexpired)
        vr = {
            "pet_id": pet["id"],
            "vaccine_type": "RABIES",
            "administered_on": iso(now),
            "expires_on": iso(add_years(now, 5)),
            "vet_license_no": "SEED-VET",
        }
        stamp_create(vr, common_fields=False)
        db.vaccination_records[vr["id"]] = vr

        # synthesize a KENNEL license driven straight to ACTIVE
        occupied = kennel["occupied_slots"]
        final_fee = license_fee("KENNEL", is_altered, occupied, "final")
        serial = db.next_tag_serial()
        lic = {
            "owner_id": owner["id"],
            "pet_id": pet["id"],
            "kennel_id": kennel["id"],
            "license_kind": "KENNEL",
            "term_years": 1,
            "vaccination_record_id": vr["id"],
            "status": "ACTIVE",
            "provisional_fee_cents": final_fee,
            "final_fee_cents": final_fee,
            "late_penalty_cents": 0,
            "penalty_paid": False,
            "issued_on": now_iso(),
            "expires_on": iso(add_years(now, 1)),
            "tag_serial": serial,
        }
        stamp_create(lic)
        db.licenses[lic["id"]] = lic

        tag = {
            "license_id": lic["id"],
            "serial": serial,
            "status": "ISSUED",
            "issued_on": now_iso(),
        }
        stamp_create(tag)
        db.tags[tag["id"]] = tag

        # reconcile occupied_slots after each (so the next license sees the bump)
        recompute_kennel_occupied_slots(kennel["id"])

    recompute_owner_active_license_count(owner["id"])
    return object_response({})
