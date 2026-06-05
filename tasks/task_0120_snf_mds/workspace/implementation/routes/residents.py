"""Resident, QualifyingStay, and PasrrScreening endpoints (PRD §3.2)."""
from flask import request

import db
import errors
import response
import serialize
import validation as V
from gate import gate
from services import calc, lookups


def register(app):
    # ---- Resident ----
    @app.route("/snf/residents", methods=["POST"])
    def create_resident():
        gate(["AdmissionsCoordinator"])
        body = V.get_body()
        full_name = V.as_str(V.require(body, "full_name"), "full_name")
        mrn = V.as_str(V.require(body, "medical_record_number"), "medical_record_number")
        dob = V.require(body, "date_of_birth")
        V.as_datetime(dob, "date_of_birth")
        primary_facility_id = V.as_str(V.require(body, "primary_facility_id"), "primary_facility_id")
        # primary_facility_id is an FK -> Facility (existence, PRD §2.5/§2.7).
        lookups.get_facility(primary_facility_id)
        # medical_record_number unique across all Resident.
        for r in db.residents.values():
            if r["medical_record_number"] == mrn:
                raise errors.err(errors.ERR_INVALID_REQUEST,
                                 "medical_record_number must be unique")
        obj = {
            "full_name": full_name,
            "medical_record_number": mrn,
            "date_of_birth": dob,
            "primary_facility_id": primary_facility_id,
            "status": "PROSPECTIVE",
        }
        db.stamp_create(obj)
        db.residents[obj["id"]] = obj
        return response.success(serialize.public(obj), 201)

    @app.route("/snf/residents/<rid>", methods=["GET"])
    def get_resident(rid):
        gate(["AdmissionsCoordinator", "MdsCoordinator", "Physician",
              "BillingAnalyst", "Therapist"])
        obj = lookups.get_resident(rid)
        return response.success(serialize.public(obj), 200)

    @app.route("/snf/residents", methods=["GET"])
    def list_residents():
        gate(["AdmissionsCoordinator", "MdsCoordinator"])
        limit, offset = V.pagination(request.args)
        rows = list(db.residents.values())
        pfid = request.args.get("primary_facility_id")
        if pfid is not None:
            rows = [r for r in rows if r["primary_facility_id"] == pfid]
        status = request.args.get("status")
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        page, total = V.paginate(rows, limit, offset)
        return response.success_list(serialize.public_list(page), limit, offset, total, 200)

    # ---- QualifyingStay ----
    @app.route("/snf/residents/<rid>/qualifying-stays", methods=["POST"])
    def create_qualifying_stay(rid):
        gate(["AdmissionsCoordinator"])
        lookups.get_resident(rid)
        body = V.get_body()
        admit = V.require(body, "hospital_admit_at")
        discharge = V.require(body, "hospital_discharge_at")
        admit_dt = V.as_datetime(admit, "hospital_admit_at")
        disc_dt = V.as_datetime(discharge, "hospital_discharge_at")
        # discharge strictly after admit (PRD §3.2).
        if not (disc_dt > admit_dt):
            raise errors.err(errors.ERR_INVALID_REQUEST,
                             "hospital_discharge_at must be strictly after hospital_admit_at")
        midnights, qualifies = calc.qualifying_stay_midnights(admit, discharge)
        obj = {
            "resident_id": rid,
            "hospital_admit_at": admit,
            "hospital_discharge_at": discharge,
            "midnights_count": midnights,
            "qualifies": qualifies,
        }
        # QualifyingStay is lightweight: id + created_at only (PRD §2.4).
        db.stamp_create(obj, versioned=False)
        db.qualifying_stays[obj["id"]] = obj
        return response.success(serialize.public(obj), 201)

    @app.route("/snf/qualifying-stays/<qid>", methods=["GET"])
    def get_qualifying_stay(qid):
        gate(["AdmissionsCoordinator", "BillingAnalyst"])
        obj = lookups.get_qualifying_stay(qid)
        return response.success(serialize.public(obj), 200)

    @app.route("/snf/qualifying-stays", methods=["GET"])
    def list_qualifying_stays():
        gate(["AdmissionsCoordinator", "BillingAnalyst"])
        limit, offset = V.pagination(request.args)
        rows = list(db.qualifying_stays.values())
        rid = request.args.get("resident_id")
        if rid is not None:
            rows = [r for r in rows if r["resident_id"] == rid]
        page, total = V.paginate(rows, limit, offset)
        return response.success_list(serialize.public_list(page), limit, offset, total, 200)

    # ---- PasrrScreening ----
    @app.route("/snf/residents/<rid>/pasrr-screenings", methods=["POST"])
    def create_pasrr(rid):
        gate(["AdmissionsCoordinator"])
        lookups.get_resident(rid)
        body = V.get_body()
        level = V.as_enum(V.require(body, "level"), "level", {"LEVEL_I", "LEVEL_II"})
        smi = V.opt(body, "has_serious_mental_illness_indicator", False)
        smi = V.as_bool(smi, "has_serious_mental_illness_indicator")
        obj = {
            "resident_id": rid,
            "level": level,
            "has_serious_mental_illness_indicator": smi,
            "status": "PENDING",
            "outcome_note": None,
        }
        db.stamp_create(obj)
        db.pasrr_screenings[obj["id"]] = obj
        return response.success(serialize.public(obj), 201)

    @app.route("/snf/pasrr-screenings/<pid>/resolve", methods=["POST"])
    def resolve_pasrr(pid):
        gate(["AdmissionsCoordinator", "Physician"])
        obj = lookups.get_pasrr(pid)
        body = V.get_body()
        resolution = V.as_enum(V.require(body, "resolution"), "resolution",
                               {"CLEARED", "DENIED", "ESCALATED"})
        outcome_note = V.opt(body, "outcome_note", None)
        if outcome_note is not None:
            outcome_note = V.as_str(outcome_note, "outcome_note")
        # State: only a PENDING screening may be resolved.
        if obj["status"] != "PENDING":
            raise errors.err(errors.ERR_INVALID_STATE,
                             "screening is not PENDING")
        # Hard clinical guard: Level I + positive SMI may not clear directly (PRD §3.2).
        if (resolution == "CLEARED" and obj["level"] == "LEVEL_I"
                and obj["has_serious_mental_illness_indicator"]):
            raise errors.err(errors.ERR_PASRR_LEVEL_II_REQUIRED,
                             "Level I screening with positive SMI indicator must escalate to Level II")
        obj["status"] = resolution
        if outcome_note is not None:
            obj["outcome_note"] = outcome_note
        db.touch(obj)
        return response.success(serialize.public(obj), 200)

    @app.route("/snf/pasrr-screenings/<pid>", methods=["GET"])
    def get_pasrr(pid):
        gate(["AdmissionsCoordinator", "Physician"])
        obj = lookups.get_pasrr(pid)
        return response.success(serialize.public(obj), 200)

    @app.route("/snf/pasrr-screenings", methods=["GET"])
    def list_pasrr():
        gate(["AdmissionsCoordinator", "Physician"])
        limit, offset = V.pagination(request.args)
        rows = list(db.pasrr_screenings.values())
        rid = request.args.get("resident_id")
        if rid is not None:
            rows = [r for r in rows if r["resident_id"] == rid]
        status = request.args.get("status")
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        page, total = V.paginate(rows, limit, offset)
        return response.success_list(serialize.public_list(page), limit, offset, total, 200)
