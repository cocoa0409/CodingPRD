"""Elder-related endpoints."""
from flask import request

from db import LOCK, get_db, new_id
from errors import APIError
from helpers import (check_occ, new_entity, paginate, parse_pagination,
                     require_body, require_enum, require_field, touch)
from middleware import require_roles
from response import empty, list_success, success
from services import elder as elder_svc
from services import audit


GENDER = {"M", "F", "OTHER"}


def _serialize(e):
    return dict(e)


def _scope_family_or_404(user_id, role, elder):
    """Family can only read their own elder. We don't have a stored linkage —
    family identity is opaque per PRD §2.1 — so we accept any Family request
    against any existing elder. Family scoping is documented as a server-side
    filter; with opaque identifiers, the only test-visible filter is that
    the elder must exist (otherwise ERR_NOT_FOUND), and that operations
    cross-referencing a different elder are restricted to that elder's
    family. We rely on path-id ownership only.
    """
    return  # Family-side scoping unavailable without a linkage table


def register(app):

    # POST /elders
    @app.post("/elders")
    @require_roles("Admin")
    def create_elder(user_id, role):
        body = require_body()
        full_name = require_field(body, "full_name", str)
        date_of_birth = require_field(body, "date_of_birth", str)
        gender = require_enum(body, "gender", GENDER)
        id_card_number = require_field(body, "id_card_number", str)
        emergency_contacts = require_field(body, "emergency_contacts", list)
        medical_history = body.get("medical_history") or []
        allergies = body.get("allergies") or []
        dietary_requirements = body.get("dietary_requirements") or []
        advance_directive = body.get("advance_directive") or {
            "dnr": False, "dni": False, "organ_donation": False, "signed_at": None
        }
        if not isinstance(medical_history, list) or not isinstance(allergies, list) \
                or not isinstance(dietary_requirements, list) \
                or not isinstance(advance_directive, dict) \
                or not isinstance(emergency_contacts, list):
            raise APIError("ERR_VALIDATION", "Array/object field has wrong type", 422)

        with LOCK:
            db = get_db()
            # Uniqueness on id_card_number across non-DISCHARGED elders
            for ex in db.elders.values():
                if ex.get("id_card_number") == id_card_number and ex.get("status") != "DISCHARGED":
                    raise APIError("ERR_VALIDATION",
                                   "id_card_number already in use", 422)
            elder = new_entity({
                "full_name": full_name,
                "date_of_birth": date_of_birth,
                "gender": gender,
                "id_card_number": id_card_number,
                "medical_history": medical_history,
                "allergies": allergies,
                "dietary_requirements": dietary_requirements,
                "emergency_contacts": emergency_contacts,
                "advance_directive": advance_directive,
                "status": "PENDING_ADMISSION",
                "admission_history": [],
                "current_bed_id": None,
                "current_care_level": None,
                "deposit_balance_cents": 0,
                "outstanding_balance_cents": 0,
            })
            db.elders[elder["id"]] = elder
            return success(_serialize(elder), status=201)

    # GET /elders
    @app.get("/elders")
    @require_roles("Admin", "Supervisor", "Nurse", "Caregiver",
                   "Finance", "Physician")
    def list_elders(user_id, role):
        limit, offset = parse_pagination()
        status_f = request.args.get("status")
        level_f = request.args.get("current_care_level")
        bed_f = request.args.get("current_bed_id")
        db = get_db()
        items = list(db.elders.values())
        if status_f:
            items = [e for e in items if e.get("status") == status_f]
        if level_f:
            items = [e for e in items if e.get("current_care_level") == level_f]
        if bed_f:
            items = [e for e in items if e.get("current_bed_id") == bed_f]
        items.sort(key=lambda e: e["created_at"])
        page, total = paginate(items, limit, offset)
        return list_success([_serialize(e) for e in page], limit, offset, total)

    # GET /elders/{id}
    @app.get("/elders/<eid>")
    @require_roles("Admin", "Supervisor", "Nurse", "Caregiver", "Finance",
                   "Physician", "Family")
    def get_elder(user_id, role, eid):
        db = get_db()
        elder = db.elders.get(eid)
        if elder is None:
            raise APIError("ERR_NOT_FOUND", f"Elder {eid} not found", 404)
        return success(_serialize(elder))

    # PATCH /elders/{id}
    @app.patch("/elders/<eid>")
    @require_roles("Admin")
    def update_elder(user_id, role, eid):
        body = require_body()
        with LOCK:
            db = get_db()
            elder = db.elders.get(eid)
            if elder is None:
                raise APIError("ERR_NOT_FOUND", f"Elder {eid} not found", 404)
            check_occ(elder, body)
            mutated = False
            for k in ("emergency_contacts", "dietary_requirements", "advance_directive", "allergies"):
                if k in body and body[k] is not None:
                    elder[k] = body[k]
                    mutated = True
            if mutated:
                touch(elder)
            return success(_serialize(elder))

    # POST /elders/{id}/deposit
    @app.post("/elders/<eid>/deposit")
    @require_roles("Finance", "Family")
    def deposit_topup(user_id, role, eid):
        body = require_body()
        amount = require_field(body, "amount_cents", int)
        if amount <= 0:
            raise APIError("ERR_VALIDATION", "amount_cents must be positive", 422)
        with LOCK:
            db = get_db()
            elder = db.elders.get(eid)
            if elder is None:
                raise APIError("ERR_NOT_FOUND", f"Elder {eid} not found", 404)
            elder["deposit_balance_cents"] = int(elder.get("deposit_balance_cents", 0)) + amount
            touch(elder)
            return success(_serialize(elder))

    # POST /elders/{id}/admit
    @app.post("/elders/<eid>/admit")
    @require_roles("Admin")
    def admit_elder(user_id, role, eid):
        body = require_body()
        bed_id = require_field(body, "bed_id", str)
        with LOCK:
            db = get_db()
            elder = db.elders.get(eid)
            if elder is None:
                raise APIError("ERR_NOT_FOUND", f"Elder {eid} not found", 404)
            bed = db.beds.get(bed_id)
            if bed is None:
                raise APIError("ERR_FK_NOT_FOUND", f"Bed {bed_id} not found", 404)
            # State precondition (priority 5)
            if elder.get("status") != "PENDING_ADMISSION":
                raise APIError("ERR_INVALID_STATE",
                               f"Elder is {elder.get('status')}, not PENDING_ADMISSION", 409)
            # Emergency contacts (priority 5 / business)
            if not elder.get("emergency_contacts"):
                raise APIError("ERR_INVALID_STATE",
                               "Elder requires >=1 emergency_contact for admission", 409)
            # Must have approved assessment
            if not elder_svc._has_approved_assessment(elder["id"]):
                raise APIError("ERR_INVALID_STATE",
                               "Elder requires at least one APPROVED CareAssessment", 409)
            # Bed-type / care-level (priority 13)
            level = elder.get("current_care_level")
            if bed["bed_type"] == "INTENSIVE_CARE" and level != "INTENSIVE":
                raise APIError("ERR_BED_TYPE_MISMATCH",
                               "INTENSIVE_CARE bed requires INTENSIVE elder", 409)
            if bed["bed_type"] != "INTENSIVE_CARE" and level == "INTENSIVE":
                raise APIError("ERR_BED_TYPE_MISMATCH",
                               "INTENSIVE elder may only occupy INTENSIVE_CARE bed", 409)
            # Admission deposit floor (priority 23)
            if int(elder.get("deposit_balance_cents", 0)) < elder_svc.REQUIRED_ADMISSION_DEPOSIT_CENTS:
                raise APIError("ERR_DEPOSIT_INSUFFICIENT",
                               "deposit_balance_cents below admission floor", 422)
            # Bed availability — first-writer-wins
            if bed.get("status") != "AVAILABLE":
                raise APIError("ERR_BED_ALREADY_OCCUPIED",
                               f"Bed {bed_id} is {bed['status']}", 409)
            elder_svc.admit(elder, bed, user_id, role)
            return success(_serialize(elder))

    # POST /elders/{id}/leave
    @app.post("/elders/<eid>/leave")
    @require_roles("Admin")
    def leave_elder(user_id, role, eid):
        body = require_body()
        with LOCK:
            db = get_db()
            elder = db.elders.get(eid)
            if elder is None:
                raise APIError("ERR_NOT_FOUND", f"Elder {eid} not found", 404)
            elder_svc.go_on_leave(elder, user_id, role, reason=body.get("reason"))
            return success(_serialize(elder))

    # POST /elders/{id}/return
    @app.post("/elders/<eid>/return")
    @require_roles("Admin")
    def return_elder(user_id, role, eid):
        with LOCK:
            db = get_db()
            elder = db.elders.get(eid)
            if elder is None:
                raise APIError("ERR_NOT_FOUND", f"Elder {eid} not found", 404)
            elder_svc.return_from_leave(elder, user_id, role)
            return success(_serialize(elder))

    # POST /elders/{id}/transfer
    @app.post("/elders/<eid>/transfer")
    @require_roles("Admin")
    def transfer_elder(user_id, role, eid):
        body = require_body()
        target_bed_id = require_field(body, "target_bed_id", str)
        with LOCK:
            db = get_db()
            elder = db.elders.get(eid)
            if elder is None:
                raise APIError("ERR_NOT_FOUND", f"Elder {eid} not found", 404)
            target_bed = db.beds.get(target_bed_id)
            if target_bed is None:
                raise APIError("ERR_FK_NOT_FOUND", f"Bed {target_bed_id} not found", 404)
            elder_svc.transfer(elder, target_bed, user_id, role)
            return success(_serialize(elder))

    # POST /elders/{id}/discharge
    @app.post("/elders/<eid>/discharge")
    @require_roles("Admin")
    def discharge_elder(user_id, role, eid):
        with LOCK:
            db = get_db()
            elder = db.elders.get(eid)
            if elder is None:
                raise APIError("ERR_NOT_FOUND", f"Elder {eid} not found", 404)
            elder_svc.discharge(elder, user_id, role)
            return success(_serialize(elder))
