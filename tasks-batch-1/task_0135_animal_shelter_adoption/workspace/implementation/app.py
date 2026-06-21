"""Animal Shelter & Adoption API — Flask entry point.

In-memory store only (db.py dicts). No entity seeding at startup. Reads $PORT,
binds 0.0.0.0, runs in the foreground. A short bind-retry loop guards against the
transient same-port bind race on rapid per-test-server restarts.
"""
import os
import socket
import time

from flask import Flask, request

import calculations
import clock
import db
import errors
import middleware
import response
import services
from serializers import serialize, serialize_microchip
from validation import (
    get_json_body,
    optional_bool,
    optional_enum,
    optional_int,
    optional_string,
    paginate,
    parse_pagination,
    require_enum,
    require_int,
    require_string,
)

app = Flask(__name__)

# ---- Enum domains ----
SPECIES = {"DOG", "CAT"}
INTAKE_SOURCES = {"STRAY", "SURRENDER", "TRANSFER"}
MEDICAL_RECORD_TYPES = {"EXAM", "SPAY_NEUTER", "VACCINATION"}
EXAM_OUTCOMES = {"CLEAR", "HOLD"}
EUTHANASIA_REASONS = {"MEDICAL_UNTREATABLE", "BEHAVIORAL", "COURT_ORDER"}
LIFECYCLE_STATES = {
    "INTAKE_PENDING", "IN_CUSTODY", "AVAILABLE", "FOSTERED",
    "ADOPTED", "RECLAIMED", "EUTHANIZED",
}
MEDICAL_STATES = {"UNEXAMINED", "EXAM_PENDING", "NEEDS_TREATMENT", "CLEARED"}
KENNEL_STATES = {"OPEN", "FULL"}
ASSIGNMENT_STATES = {"ACTIVE", "RELEASED"}
CLAIM_STATES = {"PENDING", "APPROVED", "DENIED"}
APPLICATION_STATES = {"SUBMITTED", "APPROVED", "REJECTED", "FINALIZED", "REFUNDED"}
PLACEMENT_STATES = {"ACTIVE", "RETURNED"}
EUTHANASIA_STATES = {"REQUESTED", "APPROVED", "REJECTED", "EXECUTED"}

# Read roles
ALL_OPERATIONAL = {
    "ShelterAdmin", "IntakeOfficer", "AdoptionCounselor",
    "Veterinarian", "FosterCoordinator",
}


# =====================================================================
# Error handling
# =====================================================================
@app.errorhandler(errors.ApiError)
def handle_api_error(exc):
    return response.error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(_exc):
    return response.error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_405(_exc):
    return response.error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, errors.ApiError):
        return handle_api_error(exc)
    return response.error_response("ERR_INTERNAL", str(exc), 500)


# =====================================================================
# Lookup helpers (existence -> 404, left to right)
# =====================================================================
def _lookup(coll, rid):
    rec = coll.get(rid)
    if rec is None:
        raise errors.not_found()
    return rec


def _require_shelter():
    shelter = services.get_shelter()
    if shelter is None:
        raise errors.not_found("Shelter is not configured")
    return shelter


# =====================================================================
# Clock (test-driving)
# =====================================================================
@app.route("/_clock/set", methods=["POST"])
def clock_set():
    middleware.require({"ShelterAdmin"})
    body = get_json_body()
    iso = require_string(body, "to_iso8601")
    try:
        dt = clock.parse_iso(iso)
    except ValueError:
        raise errors.invalid_request("to_iso8601 is not a valid ISO 8601 timestamp")
    with db.LOCK:
        clock.set_clock(dt)
    return response.object_response({"now": clock.to_iso(dt)}, 200)


# =====================================================================
# Shelter
# =====================================================================
@app.route("/shelters", methods=["POST"])
def create_shelter():
    # Bootstrap: no auth required (PRD §2.1). Body validated after.
    body = get_json_body()
    name = require_string(body, "name")
    stray_hold_days = optional_int(body, "stray_hold_days", default=5, minimum=0)
    promo_active = optional_bool(body, "promo_active", default=False)
    dog_rate = optional_int(body, "dog_daily_board_cents", default=1850, minimum=0)
    cat_rate = optional_int(body, "cat_daily_board_cents", default=1250, minimum=0)
    with db.LOCK:
        rec = {
            "name": name,
            "stray_hold_days": stray_hold_days,
            "promo_active": promo_active,
            "collected_fee_cents": 0,
            "dog_daily_board_cents": dog_rate,
            "cat_daily_board_cents": cat_rate,
        }
        db.stamp_create(rec)
        db.shelters[rec["id"]] = rec
        return response.object_response(serialize(rec), 201)


@app.route("/shelters/<sid>", methods=["GET"])
def get_shelter_route(sid):
    middleware.require(ALL_OPERATIONAL)
    with db.LOCK:
        rec = _lookup(db.shelters, sid)
        return response.object_response(serialize(rec), 200)


@app.route("/shelters/<sid>", methods=["PATCH"])
def patch_shelter(sid):
    middleware.require({"ShelterAdmin"})
    with db.LOCK:
        rec = _lookup(db.shelters, sid)
        body = get_json_body()
        stray_hold_days = optional_int(body, "stray_hold_days", default=None, minimum=0)
        promo_active = optional_bool(body, "promo_active", default=None)
        dog_rate = optional_int(body, "dog_daily_board_cents", default=None, minimum=0)
        cat_rate = optional_int(body, "cat_daily_board_cents", default=None, minimum=0)
        if stray_hold_days is not None:
            rec["stray_hold_days"] = stray_hold_days
        if promo_active is not None:
            rec["promo_active"] = promo_active
        if dog_rate is not None:
            rec["dog_daily_board_cents"] = dog_rate
        if cat_rate is not None:
            rec["cat_daily_board_cents"] = cat_rate
        db.touch(rec)
        return response.object_response(serialize(rec), 200)


# =====================================================================
# Kennel
# =====================================================================
@app.route("/kennels", methods=["POST"])
def create_kennel():
    middleware.require({"ShelterAdmin"})
    body = get_json_body()
    label = require_string(body, "label")
    capacity = optional_int(body, "capacity", default=1, minimum=1)
    with db.LOCK:
        rec = {
            "label": label,
            "capacity": capacity,
            "occupied_count": 0,
            "status": "OPEN",
        }
        db.stamp_create(rec)
        db.kennels[rec["id"]] = rec
        return response.object_response(serialize(rec), 201)


@app.route("/kennels/<kid>", methods=["GET"])
def get_kennel(kid):
    middleware.require(ALL_OPERATIONAL)
    with db.LOCK:
        rec = _lookup(db.kennels, kid)
        return response.object_response(serialize(rec), 200)


@app.route("/kennels", methods=["GET"])
def list_kennels():
    middleware.require(ALL_OPERATIONAL)
    status = request.args.get("status")
    if status is not None and status not in KENNEL_STATES:
        # Unknown filter -> no matches; pagination still validated.
        pass
    limit, offset = parse_pagination()
    with db.LOCK:
        items = [r for r in db.kennels.values()
                 if status is None or r["status"] == status]
        page, total = paginate(items, limit, offset)
        return response.array_response([serialize(r) for r in page], limit, offset, total, 200)


# =====================================================================
# Animal
# =====================================================================
@app.route("/animals", methods=["POST"])
def create_animal():
    middleware.require({"ShelterAdmin", "IntakeOfficer"})
    body = get_json_body()
    name = require_string(body, "name")
    species = require_enum(body, "species", SPECIES)
    age_months = require_int(body, "age_months", minimum=0)
    with db.LOCK:
        rec = {
            "name": name,
            "species": species,
            "age_months": age_months,
            "lifecycle_status": "INTAKE_PENDING",
            "medical_status": "UNEXAMINED",
            "microchipped": False,
            "stray_hold_release_at": None,
        }
        db.stamp_create(rec)
        db.animals[rec["id"]] = rec
        return response.object_response(serialize(rec), 201)


@app.route("/animals/<aid>", methods=["GET"])
def get_animal(aid):
    middleware.require(ALL_OPERATIONAL | {"Adopter"})
    with db.LOCK:
        rec = _lookup(db.animals, aid)
        return response.object_response(serialize(rec), 200)


@app.route("/animals", methods=["GET"])
def list_animals():
    middleware.require(ALL_OPERATIONAL | {"Adopter"})
    lifecycle = request.args.get("lifecycle_status")
    medical = request.args.get("medical_status")
    species = request.args.get("species")
    limit, offset = parse_pagination()
    with db.LOCK:
        items = []
        for r in db.animals.values():
            if lifecycle is not None and r["lifecycle_status"] != lifecycle:
                continue
            if medical is not None and r["medical_status"] != medical:
                continue
            if species is not None and r["species"] != species:
                continue
            items.append(r)
        page, total = paginate(items, limit, offset)
        return response.array_response([serialize(r) for r in page], limit, offset, total, 200)


@app.route("/animals/<aid>/make-available", methods=["POST"])
def make_available(aid):
    middleware.require({"AdoptionCounselor"})
    with db.LOCK:
        animal = _lookup(db.animals, aid)
        get_json_body()  # tolerate/validate empty body
        # State: must be IN_CUSTODY for this transition to be defined.
        if animal["lifecycle_status"] != "IN_CUSTODY":
            raise errors.invalid_state()
        # Business rules (priority order: medical clearance, stray hold, pending claim).
        if animal["medical_status"] != "CLEARED":
            raise errors.ApiError(errors.ERR_NOT_MEDICALLY_CLEARED, 409,
                                  "Animal is not medically cleared")
        _require_stray_hold_elapsed(animal)
        if _has_pending_claim(animal["id"]):
            raise errors.invalid_state("Animal has a PENDING owner claim")
        animal["lifecycle_status"] = "AVAILABLE"
        db.touch(animal)
        return response.object_response(serialize(animal), 200)


def _has_pending_claim(animal_id):
    return any(c["animal_id"] == animal_id and c["status"] == "PENDING"
               for c in db.owner_claims.values())


def _require_stray_hold_elapsed(animal):
    release_iso = animal.get("stray_hold_release_at")
    if release_iso is None:
        return
    release_at = clock.parse_iso(release_iso)
    if clock.now() < release_at:
        raise errors.ApiError(errors.ERR_STRAY_HOLD_ACTIVE, 409,
                              "Stray hold has not yet elapsed")


# =====================================================================
# IntakeRecord
# =====================================================================
@app.route("/intake-records", methods=["POST"])
def create_intake():
    middleware.require({"IntakeOfficer"})
    body = get_json_body()
    with db.LOCK:
        animal_id = require_string(body, "animal_id")
        animal = _lookup(db.animals, animal_id)  # FK existence -> 404
        source = require_enum(body, "source", INTAKE_SOURCES)
        surrendering_party = optional_string(body, "surrendering_party")
        if source in ("SURRENDER", "TRANSFER") and (
            surrendering_party is None or surrendering_party.strip() == ""
        ):
            raise errors.invalid_request(
                "surrendering_party is required for SURRENDER and TRANSFER")
        # State: animal must be INTAKE_PENDING and have no prior intake.
        if animal["lifecycle_status"] != "INTAKE_PENDING":
            raise errors.invalid_state()
        if any(r["animal_id"] == animal_id for r in db.intake_records.values()):
            raise errors.invalid_state("Animal already has an intake record")
        shelter = _require_shelter()

        now = clock.now()
        release_at = calculations.stray_hold_release_at(
            source, now, shelter["stray_hold_days"])
        release_iso = clock.to_iso(release_at)

        rec = {
            "animal_id": animal_id,
            "source": source,
            "intake_at": clock.to_iso(now),
            "surrendering_party": surrendering_party if source != "STRAY" else None,
            "stray_hold_release_at": release_iso,
        }
        db.stamp_create(rec)
        db.intake_records[rec["id"]] = rec

        animal["stray_hold_release_at"] = release_iso
        animal["lifecycle_status"] = "IN_CUSTODY"
        db.touch(animal)
        return response.object_response(serialize(rec), 201)


@app.route("/intake-records/<rid>", methods=["GET"])
def get_intake(rid):
    middleware.require({"ShelterAdmin", "IntakeOfficer", "AdoptionCounselor", "Veterinarian"})
    with db.LOCK:
        rec = _lookup(db.intake_records, rid)
        return response.object_response(serialize(rec), 200)


@app.route("/intake-records", methods=["GET"])
def list_intakes():
    middleware.require({"ShelterAdmin", "IntakeOfficer", "AdoptionCounselor", "Veterinarian"})
    animal_id = request.args.get("animal_id")
    source = request.args.get("source")
    limit, offset = parse_pagination()
    with db.LOCK:
        items = [r for r in db.intake_records.values()
                 if (animal_id is None or r["animal_id"] == animal_id)
                 and (source is None or r["source"] == source)]
        page, total = paginate(items, limit, offset)
        return response.array_response([serialize(r) for r in page], limit, offset, total, 200)


# =====================================================================
# KennelAssignment
# =====================================================================
@app.route("/kennel-assignments", methods=["POST"])
def create_kennel_assignment():
    middleware.require({"IntakeOfficer"})
    body = get_json_body()
    with db.LOCK:
        # Existence: validate FKs left-to-right (kennel_id then animal_id).
        kennel_id = require_string(body, "kennel_id")
        kennel = _lookup(db.kennels, kennel_id)
        animal_id = require_string(body, "animal_id")
        animal = _lookup(db.animals, animal_id)
        # Body shape: expected_kennel_version is mandatory.
        expected_version = require_int(body, "expected_kennel_version")

        # State: animal must be IN_CUSTODY for an assignment to be defined.
        if animal["lifecycle_status"] != "IN_CUSTODY":
            raise errors.invalid_state()

        # Business: kennel occupancy / overlap (priority 10) before OCC? Per PRD §2.7,
        # transition legality (state) then business rules; kennel occupancy (10) is a
        # business constraint, OCC (15) is the last business rule. Both are 409/412.
        # PRD §2.9 says OCC is rejected "before any occupancy mutation"; we evaluate
        # occupancy/overlap then OCC, both before mutating.
        if kennel["status"] != "OPEN":
            raise errors.ApiError(errors.ERR_KENNEL_OCCUPIED, 409,
                                  "Kennel is not OPEN")
        # Overlap: any other ACTIVE assignment on this kennel overlaps the new
        # half-open interval [start_at, now()->null). A new ACTIVE assignment has an
        # open-ended interval, so any existing ACTIVE assignment on the kennel overlaps.
        if any(a["kennel_id"] == kennel_id and a["status"] == "ACTIVE"
               for a in db.kennel_assignments.values()):
            raise errors.ApiError(errors.ERR_KENNEL_OCCUPIED, 409,
                                  "An active assignment already occupies this kennel")
        # OCC (priority 15): expected_kennel_version must equal current version.
        if expected_version != kennel["version"]:
            raise errors.ApiError(errors.ERR_STALE_VERSION, 412,
                                  "expected_kennel_version does not match kennel version")

        now = clock.now()
        rec = {
            "kennel_id": kennel_id,
            "animal_id": animal_id,
            "start_at": clock.to_iso(now),
            "end_at": None,
            "status": "ACTIVE",
            "actual_board_cents": None,
        }
        db.stamp_create(rec)
        db.kennel_assignments[rec["id"]] = rec

        services.recompute_kennel(kennel)
        db.touch(kennel)
        return response.object_response(serialize(rec), 201)


@app.route("/kennel-assignments/<aid>", methods=["GET"])
def get_kennel_assignment(aid):
    middleware.require(ALL_OPERATIONAL)
    with db.LOCK:
        rec = _lookup(db.kennel_assignments, aid)
        return response.object_response(serialize(rec), 200)


@app.route("/kennel-assignments", methods=["GET"])
def list_kennel_assignments():
    middleware.require(ALL_OPERATIONAL)
    kennel_id = request.args.get("kennel_id")
    animal_id = request.args.get("animal_id")
    status = request.args.get("status")
    limit, offset = parse_pagination()
    with db.LOCK:
        items = [r for r in db.kennel_assignments.values()
                 if (kennel_id is None or r["kennel_id"] == kennel_id)
                 and (animal_id is None or r["animal_id"] == animal_id)
                 and (status is None or r["status"] == status)]
        page, total = paginate(items, limit, offset)
        return response.array_response([serialize(r) for r in page], limit, offset, total, 200)


@app.route("/kennel-assignments/<aid>/projected-board", methods=["GET"])
def projected_board(aid):
    middleware.require({"ShelterAdmin", "IntakeOfficer", "AdoptionCounselor"})
    with db.LOCK:
        rec = _lookup(db.kennel_assignments, aid)
        animal = db.animals[rec["animal_id"]]
        shelter = _require_shelter()
        daily_base = services._daily_base_for(animal, shelter)
        start_dt = clock.parse_iso(rec["start_at"])
        release_iso = animal.get("stray_hold_release_at")
        # Projects to expected earliest release; fall back to start (min 1 day) if null.
        release_dt = clock.parse_iso(release_iso) if release_iso else start_dt
        cents, days = calculations.projected_board(daily_base, start_dt, release_dt)
        return response.object_response(
            {"projected_board_cents": cents, "projected_occupied_days": days}, 200)


@app.route("/kennel-assignments/<aid>/release", methods=["POST"])
def release_kennel_assignment(aid):
    middleware.require({"ShelterAdmin", "IntakeOfficer"})
    with db.LOCK:
        rec = _lookup(db.kennel_assignments, aid)
        get_json_body()
        if rec["status"] != "ACTIVE":
            raise errors.invalid_state()
        services.release_assignment(rec)
        return response.object_response(serialize(rec), 200)


# =====================================================================
# MedicalRecord
# =====================================================================
@app.route("/medical-records", methods=["POST"])
def create_medical_record():
    middleware.require({"Veterinarian"})
    body = get_json_body()
    with db.LOCK:
        animal_id = require_string(body, "animal_id")
        animal = _lookup(db.animals, animal_id)
        record_type = require_enum(body, "record_type", MEDICAL_RECORD_TYPES)
        outcome = optional_enum(body, "outcome", EXAM_OUTCOMES, default=None)
        notes = optional_string(body, "notes")

        if record_type == "EXAM":
            if outcome is None:
                raise errors.invalid_request("EXAM records require an outcome")
            # State: exam allowed only while UNEXAMINED or NEEDS_TREATMENT.
            if animal["medical_status"] not in ("UNEXAMINED", "NEEDS_TREATMENT"):
                raise errors.invalid_state(
                    "Exam not permitted from current medical_status")

        rec = {
            "animal_id": animal_id,
            "record_type": record_type,
            "outcome": outcome if record_type == "EXAM" else None,
            "notes": notes,
        }
        db.stamp_create(rec)
        db.medical_records[rec["id"]] = rec

        if record_type == "EXAM":
            animal["medical_status"] = "CLEARED" if outcome == "CLEAR" else "NEEDS_TREATMENT"
            db.touch(animal)
        return response.object_response(serialize(rec), 201)


@app.route("/medical-records/<rid>", methods=["GET"])
def get_medical_record(rid):
    middleware.require({"ShelterAdmin", "Veterinarian", "AdoptionCounselor"})
    with db.LOCK:
        rec = _lookup(db.medical_records, rid)
        return response.object_response(serialize(rec), 200)


@app.route("/medical-records", methods=["GET"])
def list_medical_records():
    middleware.require({"ShelterAdmin", "Veterinarian", "AdoptionCounselor"})
    animal_id = request.args.get("animal_id")
    record_type = request.args.get("record_type")
    limit, offset = parse_pagination()
    with db.LOCK:
        items = [r for r in db.medical_records.values()
                 if (animal_id is None or r["animal_id"] == animal_id)
                 and (record_type is None or r["record_type"] == record_type)]
        page, total = paginate(items, limit, offset)
        return response.array_response([serialize(r) for r in page], limit, offset, total, 200)


# =====================================================================
# Microchip
# =====================================================================
@app.route("/microchips", methods=["POST"])
def create_microchip():
    middleware.require({"Veterinarian", "ShelterAdmin"})
    body = get_json_body()
    with db.LOCK:
        animal_id = require_string(body, "animal_id")
        animal = _lookup(db.animals, animal_id)
        chip_number = require_string(body, "chip_number")
        owner_name = optional_string(body, "owner_name")
        owner_phone = optional_string(body, "owner_phone")
        # Uniqueness (business): chip_number globally unique.
        if any(m["chip_number"] == chip_number for m in db.microchips.values()):
            raise errors.ApiError(errors.ERR_DUPLICATE_CHIP, 409,
                                  "chip_number already registered")
        rec = {
            "animal_id": animal_id,
            "chip_number": chip_number,
            "owner_name": owner_name,
            "owner_phone": owner_phone,
        }
        db.stamp_create(rec, versioned=False)  # immutable registry row
        db.microchips[rec["id"]] = rec

        if not animal["microchipped"]:
            animal["microchipped"] = True
            db.touch(animal)
        return response.object_response(serialize_microchip(rec), 201)


@app.route("/microchips/<mid>", methods=["GET"])
def get_microchip(mid):
    middleware.require({"ShelterAdmin", "Veterinarian", "AdoptionCounselor", "IntakeOfficer"})
    with db.LOCK:
        rec = _lookup(db.microchips, mid)
        return response.object_response(serialize_microchip(rec), 200)


@app.route("/microchips", methods=["GET"])
def list_microchips():
    middleware.require({"ShelterAdmin", "Veterinarian", "AdoptionCounselor", "IntakeOfficer"})
    animal_id = request.args.get("animal_id")
    chip_number = request.args.get("chip_number")
    limit, offset = parse_pagination()
    with db.LOCK:
        items = [r for r in db.microchips.values()
                 if (animal_id is None or r["animal_id"] == animal_id)
                 and (chip_number is None or r["chip_number"] == chip_number)]
        page, total = paginate(items, limit, offset)
        return response.array_response(
            [serialize_microchip(r) for r in page], limit, offset, total, 200)


# =====================================================================
# OwnerClaim
# =====================================================================
@app.route("/owner-claims", methods=["POST"])
def create_owner_claim():
    middleware.require({"ShelterAdmin", "IntakeOfficer"})
    body = get_json_body()
    with db.LOCK:
        animal_id = require_string(body, "animal_id")
        animal = _lookup(db.animals, animal_id)
        claimant_name = require_string(body, "claimant_name")
        proof_chip_number = optional_string(body, "proof_chip_number")
        if animal["lifecycle_status"] != "IN_CUSTODY":
            raise errors.invalid_state()
        rec = {
            "animal_id": animal_id,
            "claimant_name": claimant_name,
            "proof_chip_number": proof_chip_number,
            "status": "PENDING",
        }
        db.stamp_create(rec)
        db.owner_claims[rec["id"]] = rec
        return response.object_response(serialize(rec), 201)


@app.route("/owner-claims/<cid>", methods=["GET"])
def get_owner_claim(cid):
    middleware.require({"ShelterAdmin", "IntakeOfficer", "AdoptionCounselor"})
    with db.LOCK:
        rec = _lookup(db.owner_claims, cid)
        return response.object_response(serialize(rec), 200)


@app.route("/owner-claims", methods=["GET"])
def list_owner_claims():
    middleware.require({"ShelterAdmin", "IntakeOfficer", "AdoptionCounselor"})
    animal_id = request.args.get("animal_id")
    status = request.args.get("status")
    limit, offset = parse_pagination()
    with db.LOCK:
        items = [r for r in db.owner_claims.values()
                 if (animal_id is None or r["animal_id"] == animal_id)
                 and (status is None or r["status"] == status)]
        page, total = paginate(items, limit, offset)
        return response.array_response([serialize(r) for r in page], limit, offset, total, 200)


@app.route("/owner-claims/<cid>/approve", methods=["POST"])
def approve_owner_claim(cid):
    middleware.require({"ShelterAdmin"})
    with db.LOCK:
        claim = _lookup(db.owner_claims, cid)
        get_json_body()
        animal = db.animals[claim["animal_id"]]
        # State: claim must be PENDING and animal IN_CUSTODY.
        if claim["status"] != "PENDING":
            raise errors.invalid_state()
        if animal["lifecycle_status"] != "IN_CUSTODY":
            raise errors.invalid_state("Animal is no longer IN_CUSTODY")
        # Business referential: proof chip must match a microchip on this animal.
        proof = claim.get("proof_chip_number")
        match = proof is not None and any(
            m["animal_id"] == animal["id"] and m["chip_number"] == proof
            for m in db.microchips.values()
        )
        if not match:
            raise errors.ApiError(errors.ERR_CHIP_MISMATCH, 409,
                                  "proof_chip_number does not match a microchip on this animal")
        claim["status"] = "APPROVED"
        db.touch(claim)
        animal["lifecycle_status"] = "RECLAIMED"
        db.touch(animal)
        services.release_active_assignment_for_animal(animal["id"])
        return response.object_response(serialize(claim), 200)


@app.route("/owner-claims/<cid>/deny", methods=["POST"])
def deny_owner_claim(cid):
    middleware.require({"ShelterAdmin"})
    with db.LOCK:
        claim = _lookup(db.owner_claims, cid)
        get_json_body()
        if claim["status"] != "PENDING":
            raise errors.invalid_state()
        claim["status"] = "DENIED"
        db.touch(claim)
        return response.object_response(serialize(claim), 200)


# =====================================================================
# AdopterAccount
# =====================================================================
@app.route("/adopter-accounts", methods=["POST"])
def create_adopter_account():
    middleware.require({"ShelterAdmin", "AdoptionCounselor", "Adopter"})
    body = get_json_body()
    full_name = require_string(body, "full_name")
    email = require_string(body, "email")
    phone = optional_string(body, "phone")
    with db.LOCK:
        if any(a["email"] == email for a in db.adopter_accounts.values()):
            raise errors.ApiError(errors.ERR_DUPLICATE_EMAIL, 409,
                                  "email already registered")
        rec = {"full_name": full_name, "email": email, "phone": phone}
        db.stamp_create(rec)
        db.adopter_accounts[rec["id"]] = rec
        return response.object_response(serialize(rec), 201)


@app.route("/adopter-accounts/<aid>", methods=["GET"])
def get_adopter_account(aid):
    user_id, role = middleware.require({"ShelterAdmin", "AdoptionCounselor", "Adopter"})
    with db.LOCK:
        rec = _lookup(db.adopter_accounts, aid)
        # Ownership: an Adopter may read only their own account.
        if role == "Adopter" and user_id != rec["id"]:
            raise errors.forbidden("Adopters may only read their own account")
        return response.object_response(serialize(rec), 200)


# =====================================================================
# AdoptionApplication
# =====================================================================
@app.route("/adoption-applications", methods=["POST"])
def create_application():
    user_id, role = middleware.require({"Adopter", "AdoptionCounselor"})
    body = get_json_body()
    with db.LOCK:
        animal_id = require_string(body, "animal_id")
        animal = _lookup(db.animals, animal_id)
        adopter_id = require_string(body, "adopter_id")
        adopter = _lookup(db.adopter_accounts, adopter_id)
        # Ownership: an Adopter may only apply on their own behalf.
        if role == "Adopter" and user_id != adopter_id:
            raise errors.forbidden("Adopters may only apply for their own account")
        # State: animal AVAILABLE and no APPROVED/FINALIZED application exists.
        if animal["lifecycle_status"] != "AVAILABLE":
            raise errors.invalid_state()
        if any(app_["animal_id"] == animal_id and app_["status"] in ("APPROVED", "FINALIZED")
               for app_ in db.adoption_applications.values()):
            raise errors.invalid_state(
                "Another application for this animal is already APPROVED or FINALIZED")
        shelter = _require_shelter()
        estimated = calculations.adoption_fee_cents(
            animal["age_months"], animal["microchipped"], shelter["promo_active"])
        rec = {
            "animal_id": animal_id,
            "adopter_id": adopter_id,
            "status": "SUBMITTED",
            "estimated_fee_cents": estimated,
            "final_fee_cents": None,
            "refunded": False,
        }
        db.stamp_create(rec)
        db.adoption_applications[rec["id"]] = rec
        return response.object_response(serialize(rec), 201)


@app.route("/adoption-applications/<aid>", methods=["GET"])
def get_application(aid):
    user_id, role = middleware.require({"ShelterAdmin", "AdoptionCounselor", "Adopter"})
    with db.LOCK:
        rec = _lookup(db.adoption_applications, aid)
        if role == "Adopter" and user_id != rec["adopter_id"]:
            raise errors.forbidden("Adopters may only read their own applications")
        return response.object_response(serialize(rec), 200)


@app.route("/adoption-applications", methods=["GET"])
def list_applications():
    user_id, role = middleware.require({"ShelterAdmin", "AdoptionCounselor", "Adopter"})
    animal_id = request.args.get("animal_id")
    adopter_id = request.args.get("adopter_id")
    status = request.args.get("status")
    limit, offset = parse_pagination()
    with db.LOCK:
        items = []
        for r in db.adoption_applications.values():
            if animal_id is not None and r["animal_id"] != animal_id:
                continue
            if adopter_id is not None and r["adopter_id"] != adopter_id:
                continue
            if status is not None and r["status"] != status:
                continue
            # Adopters only see their own applications.
            if role == "Adopter" and r["adopter_id"] != user_id:
                continue
            items.append(r)
        page, total = paginate(items, limit, offset)
        return response.array_response([serialize(r) for r in page], limit, offset, total, 200)


@app.route("/adoption-applications/<aid>/approve", methods=["POST"])
def approve_application(aid):
    middleware.require({"AdoptionCounselor"})
    with db.LOCK:
        app_ = _lookup(db.adoption_applications, aid)
        get_json_body()
        animal = db.animals[app_["animal_id"]]
        # State: application SUBMITTED and animal AVAILABLE.
        if app_["status"] != "SUBMITTED":
            raise errors.invalid_state()
        if animal["lifecycle_status"] != "AVAILABLE":
            raise errors.invalid_state("Animal is not AVAILABLE")
        # Business: medical clearance (priority 9) then application conflict (13).
        if animal["medical_status"] != "CLEARED":
            raise errors.ApiError(errors.ERR_NOT_MEDICALLY_CLEARED, 409,
                                  "Animal is not medically cleared")
        if any(other["animal_id"] == app_["animal_id"]
               and other["id"] != app_["id"]
               and other["status"] in ("APPROVED", "FINALIZED")
               for other in db.adoption_applications.values()):
            raise errors.ApiError(errors.ERR_APPLICATION_CONFLICT, 409,
                                  "Another application for this animal is already APPROVED or FINALIZED")
        app_["status"] = "APPROVED"
        db.touch(app_)
        return response.object_response(serialize(app_), 200)


@app.route("/adoption-applications/<aid>/reject", methods=["POST"])
def reject_application(aid):
    middleware.require({"AdoptionCounselor"})
    with db.LOCK:
        app_ = _lookup(db.adoption_applications, aid)
        get_json_body()
        if app_["status"] != "SUBMITTED":
            raise errors.invalid_state()
        app_["status"] = "REJECTED"
        db.touch(app_)
        return response.object_response(serialize(app_), 200)


@app.route("/adoption-applications/<aid>/finalize", methods=["POST"])
def finalize_application(aid):
    middleware.require({"AdoptionCounselor"})
    with db.LOCK:
        app_ = _lookup(db.adoption_applications, aid)
        get_json_body()
        animal = db.animals[app_["animal_id"]]
        # State: application APPROVED and animal AVAILABLE.
        if app_["status"] != "APPROVED":
            raise errors.invalid_state()
        if animal["lifecycle_status"] != "AVAILABLE":
            raise errors.invalid_state("Animal is not AVAILABLE")
        shelter = _require_shelter()
        final_fee = calculations.adoption_fee_cents(
            animal["age_months"], animal["microchipped"], shelter["promo_active"])
        app_["final_fee_cents"] = final_fee
        app_["status"] = "FINALIZED"
        db.touch(app_)
        # Ledger debit.
        shelter["collected_fee_cents"] += final_fee
        db.touch(shelter)
        # Cascade: animal -> ADOPTED, release ACTIVE kennel assignment.
        animal["lifecycle_status"] = "ADOPTED"
        db.touch(animal)
        services.release_active_assignment_for_animal(animal["id"])
        return response.object_response(serialize(app_), 200)


@app.route("/adoption-applications/<aid>/refund", methods=["POST"])
def refund_application(aid):
    middleware.require({"ShelterAdmin"})
    with db.LOCK:
        app_ = _lookup(db.adoption_applications, aid)
        get_json_body()
        if app_["status"] != "FINALIZED":
            raise errors.invalid_state()
        shelter = _require_shelter()
        app_["refunded"] = True
        app_["status"] = "REFUNDED"
        db.touch(app_)
        shelter["collected_fee_cents"] -= app_["final_fee_cents"]
        db.touch(shelter)
        return response.object_response(serialize(app_), 200)


# =====================================================================
# FosterHome
# =====================================================================
@app.route("/foster-homes", methods=["POST"])
def create_foster_home():
    middleware.require({"ShelterAdmin", "FosterCoordinator"})
    body = get_json_body()
    contact_name = require_string(body, "contact_name")
    max_concurrent = optional_int(body, "max_concurrent", default=2, minimum=1)
    cooldown_days = optional_int(body, "cooldown_days", default=3, minimum=0)
    with db.LOCK:
        rec = {
            "contact_name": contact_name,
            "max_concurrent": max_concurrent,
            "cooldown_days": cooldown_days,
            "active_placement_count": 0,
        }
        db.stamp_create(rec)
        db.foster_homes[rec["id"]] = rec
        return response.object_response(serialize(rec), 201)


@app.route("/foster-homes/<hid>", methods=["GET"])
def get_foster_home(hid):
    middleware.require({"ShelterAdmin", "FosterCoordinator"})
    with db.LOCK:
        rec = _lookup(db.foster_homes, hid)
        return response.object_response(serialize(rec), 200)


@app.route("/foster-homes", methods=["GET"])
def list_foster_homes():
    middleware.require({"ShelterAdmin", "FosterCoordinator"})
    limit, offset = parse_pagination()
    with db.LOCK:
        items = list(db.foster_homes.values())
        page, total = paginate(items, limit, offset)
        return response.array_response([serialize(r) for r in page], limit, offset, total, 200)


# =====================================================================
# FosterPlacement
# =====================================================================
@app.route("/foster-placements", methods=["POST"])
def create_foster_placement():
    middleware.require({"FosterCoordinator"})
    body = get_json_body()
    with db.LOCK:
        foster_home_id = require_string(body, "foster_home_id")
        home = _lookup(db.foster_homes, foster_home_id)
        animal_id = require_string(body, "animal_id")
        animal = _lookup(db.animals, animal_id)
        # State: animal must be AVAILABLE.
        if animal["lifecycle_status"] != "AVAILABLE":
            raise errors.invalid_state()
        # Business: aggregate capacity (priority 11).
        if home["active_placement_count"] >= home["max_concurrent"]:
            raise errors.ApiError(errors.ERR_FOSTER_HOME_FULL, 409,
                                  "Foster home is at aggregate capacity")
        now = clock.now()
        # Business: cooldown (priority 12). New start_at must be >= cooldown_days after
        # the most recent RETURNED placement's end_at at this home.
        cooldown = home["cooldown_days"]
        latest_returned_end = None
        for p in db.foster_placements.values():
            if p["foster_home_id"] == foster_home_id and p["status"] == "RETURNED" and p.get("end_at"):
                end_dt = clock.parse_iso(p["end_at"])
                if latest_returned_end is None or end_dt > latest_returned_end:
                    latest_returned_end = end_dt
        if latest_returned_end is not None:
            from datetime import timedelta
            earliest_allowed = latest_returned_end + timedelta(hours=cooldown * 24)
            if now < earliest_allowed:
                raise errors.ApiError(errors.ERR_FOSTER_COOLDOWN, 409,
                                      "Foster home cooldown has not elapsed")
        rec = {
            "foster_home_id": foster_home_id,
            "animal_id": animal_id,
            "start_at": clock.to_iso(now),
            "end_at": None,
            "status": "ACTIVE",
        }
        db.stamp_create(rec)
        db.foster_placements[rec["id"]] = rec
        services.recompute_foster_home(home)
        db.touch(home)
        animal["lifecycle_status"] = "FOSTERED"
        db.touch(animal)
        return response.object_response(serialize(rec), 201)


@app.route("/foster-placements/<pid>", methods=["GET"])
def get_foster_placement(pid):
    middleware.require({"ShelterAdmin", "FosterCoordinator"})
    with db.LOCK:
        rec = _lookup(db.foster_placements, pid)
        return response.object_response(serialize(rec), 200)


@app.route("/foster-placements", methods=["GET"])
def list_foster_placements():
    middleware.require({"ShelterAdmin", "FosterCoordinator"})
    foster_home_id = request.args.get("foster_home_id")
    animal_id = request.args.get("animal_id")
    status = request.args.get("status")
    limit, offset = parse_pagination()
    with db.LOCK:
        items = [r for r in db.foster_placements.values()
                 if (foster_home_id is None or r["foster_home_id"] == foster_home_id)
                 and (animal_id is None or r["animal_id"] == animal_id)
                 and (status is None or r["status"] == status)]
        page, total = paginate(items, limit, offset)
        return response.array_response([serialize(r) for r in page], limit, offset, total, 200)


@app.route("/foster-placements/<pid>/return", methods=["POST"])
def return_foster_placement(pid):
    middleware.require({"FosterCoordinator"})
    with db.LOCK:
        rec = _lookup(db.foster_placements, pid)
        get_json_body()
        if rec["status"] != "ACTIVE":
            raise errors.invalid_state()
        rec["end_at"] = clock.to_iso(clock.now())
        rec["status"] = "RETURNED"
        db.touch(rec)
        home = db.foster_homes[rec["foster_home_id"]]
        services.recompute_foster_home(home)
        db.touch(home)
        animal = db.animals[rec["animal_id"]]
        animal["lifecycle_status"] = "AVAILABLE"
        db.touch(animal)
        return response.object_response(serialize(rec), 200)


# =====================================================================
# EuthanasiaDecision
# =====================================================================
@app.route("/euthanasia-decisions", methods=["POST"])
def create_euthanasia():
    user_id, role = middleware.require({"AdoptionCounselor", "ShelterAdmin"})
    body = get_json_body()
    with db.LOCK:
        animal_id = require_string(body, "animal_id")
        animal = _lookup(db.animals, animal_id)
        reason = require_enum(body, "reason", EUTHANASIA_REASONS)
        if animal["lifecycle_status"] != "IN_CUSTODY":
            raise errors.invalid_state()
        rec = {
            "animal_id": animal_id,
            "requested_by_user_id": user_id,
            "reason": reason,
            "approved_by_user_id": None,
            "status": "REQUESTED",
        }
        db.stamp_create(rec)
        db.euthanasia_decisions[rec["id"]] = rec
        return response.object_response(serialize(rec), 201)


@app.route("/euthanasia-decisions/<did>", methods=["GET"])
def get_euthanasia(did):
    middleware.require({"ShelterAdmin", "AdoptionCounselor", "Veterinarian"})
    with db.LOCK:
        rec = _lookup(db.euthanasia_decisions, did)
        return response.object_response(serialize(rec), 200)


@app.route("/euthanasia-decisions", methods=["GET"])
def list_euthanasia():
    middleware.require({"ShelterAdmin", "AdoptionCounselor", "Veterinarian"})
    animal_id = request.args.get("animal_id")
    status = request.args.get("status")
    limit, offset = parse_pagination()
    with db.LOCK:
        items = [r for r in db.euthanasia_decisions.values()
                 if (animal_id is None or r["animal_id"] == animal_id)
                 and (status is None or r["status"] == status)]
        page, total = paginate(items, limit, offset)
        return response.array_response([serialize(r) for r in page], limit, offset, total, 200)


@app.route("/euthanasia-decisions/<did>/approve", methods=["POST"])
def approve_euthanasia(did):
    user_id, role = middleware.require({"Veterinarian"})
    with db.LOCK:
        rec = _lookup(db.euthanasia_decisions, did)
        get_json_body()
        if rec["status"] != "REQUESTED":
            raise errors.invalid_state()
        # Segregation of duties (priority 7): approver != requester.
        if user_id == rec["requested_by_user_id"]:
            raise errors.ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 409,
                                  "Approver must differ from the requester")
        rec["approved_by_user_id"] = user_id
        rec["status"] = "APPROVED"
        db.touch(rec)
        return response.object_response(serialize(rec), 200)


@app.route("/euthanasia-decisions/<did>/reject", methods=["POST"])
def reject_euthanasia(did):
    middleware.require({"Veterinarian"})
    with db.LOCK:
        rec = _lookup(db.euthanasia_decisions, did)
        get_json_body()
        if rec["status"] != "REQUESTED":
            raise errors.invalid_state()
        rec["status"] = "REJECTED"
        db.touch(rec)
        return response.object_response(serialize(rec), 200)


@app.route("/euthanasia-decisions/<did>/execute", methods=["POST"])
def execute_euthanasia(did):
    middleware.require({"Veterinarian"})
    with db.LOCK:
        rec = _lookup(db.euthanasia_decisions, did)
        get_json_body()
        animal = db.animals[rec["animal_id"]]
        # State: decision APPROVED and animal IN_CUSTODY.
        if rec["status"] != "APPROVED":
            raise errors.invalid_state()
        if animal["lifecycle_status"] != "IN_CUSTODY":
            raise errors.invalid_state("Animal is not IN_CUSTODY")
        # Business temporal: stray hold must have elapsed.
        _require_stray_hold_elapsed(animal)
        rec["status"] = "EXECUTED"
        db.touch(rec)
        animal["lifecycle_status"] = "EUTHANIZED"
        db.touch(animal)
        services.release_active_assignment_for_animal(animal["id"])
        return response.object_response(serialize(rec), 200)


# =====================================================================
# Boot
# =====================================================================
def _bind_and_run():
    """Run the server, retrying briefly against a transient same-port bind race.

    8 stability rounds restart the server (per-test-server isolation) concurrently;
    a freshly-killed predecessor may still hold the port for a few ms. Retry briefly.
    """
    port = int(os.environ.get("PORT", "10000"))
    host = "0.0.0.0"
    deadline = time.time() + 30.0
    last_err = None
    while time.time() < deadline:
        # Probe the port with SO_REUSEADDR; if bindable, hand off to Flask/Werkzeug.
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((host, port))
            probe.close()
            break
        except OSError as exc:
            last_err = exc
            time.sleep(0.1)
    else:
        if last_err is not None:
            raise last_err
    app.run(host=host, port=port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    _bind_and_run()
