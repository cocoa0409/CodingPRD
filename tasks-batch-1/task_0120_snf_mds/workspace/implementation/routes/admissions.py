"""Admission endpoints: create, fetch, list, activate, plan-discharge, discharge
(PRD §3.3, §3.8)."""
from flask import request

import db
import errors
import response
import serialize
import validation as V
from gate import gate
from services import lookups, transitions


def register(app):
    @app.route("/snf/admissions", methods=["POST"])
    def create_admission():
        gate(["AdmissionsCoordinator"])
        body = V.get_body()
        resident_id = V.as_str(V.require(body, "resident_id"), "resident_id")
        facility_id = V.as_str(V.require(body, "facility_id"), "facility_id")
        pasrr_screening_id = V.as_str(V.require(body, "pasrr_screening_id"), "pasrr_screening_id")
        payer_source = V.as_enum(V.require(body, "payer_source"), "payer_source",
                                 {"MEDICARE_A", "MEDICAID", "PRIVATE", "MANAGED_CARE"})
        admit_at = V.require(body, "admit_at")
        V.as_datetime(admit_at, "admit_at")
        qualifying_stay_id = V.opt(body, "qualifying_stay_id", None)
        if qualifying_stay_id is not None:
            qualifying_stay_id = V.as_str(qualifying_stay_id, "qualifying_stay_id")
        # Existence checks for body FKs (PRD §2.5/§2.7 step 3).
        lookups.get_resident(resident_id)
        lookups.get_facility(facility_id)
        lookups.get_pasrr(pasrr_screening_id)
        if qualifying_stay_id is not None:
            lookups.get_qualifying_stay(qualifying_stay_id)
        obj = {
            "resident_id": resident_id,
            "facility_id": facility_id,
            "pasrr_screening_id": pasrr_screening_id,
            "qualifying_stay_id": qualifying_stay_id,
            "payer_source": payer_source,
            "admit_at": admit_at,
            "medicare_covered": False,
            "covered_day_count": 0,
            "status": "PENDING",
            "discharge_at": None,
        }
        db.stamp_create(obj)
        db.admissions[obj["id"]] = obj
        return response.success(serialize.public(obj), 201)

    @app.route("/snf/admissions/<aid>", methods=["GET"])
    def get_admission(aid):
        gate(["AdmissionsCoordinator", "MdsCoordinator", "BillingAnalyst",
              "Physician", "Therapist"])
        obj = lookups.get_admission(aid)
        return response.success(serialize.public(obj), 200)

    @app.route("/snf/admissions", methods=["GET"])
    def list_admissions():
        gate(["AdmissionsCoordinator", "BillingAnalyst"])
        limit, offset = V.pagination(request.args)
        rows = list(db.admissions.values())
        for key in ("resident_id", "facility_id", "pasrr_screening_id",
                    "qualifying_stay_id", "status"):
            val = request.args.get(key)
            if val is not None:
                rows = [r for r in rows if r.get(key) == val]
        page, total = V.paginate(rows, limit, offset)
        return response.success_list(serialize.public_list(page), limit, offset, total, 200)

    @app.route("/snf/admissions/<aid>/activate", methods=["POST"])
    def activate_admission(aid):
        gate(["AdmissionsCoordinator"])
        adm = lookups.get_admission(aid)
        body = V.get_body()
        allow_non_covered = V.opt(body, "allow_non_covered", False)
        allow_non_covered = V.as_bool(allow_non_covered, "allow_non_covered")
        transitions.activate_admission(adm, allow_non_covered)
        return response.success(serialize.public(adm), 200)

    @app.route("/snf/admissions/<aid>/plan-discharge", methods=["POST"])
    def plan_discharge(aid):
        gate(["AdmissionsCoordinator"])
        adm = lookups.get_admission(aid)
        transitions.plan_discharge(adm)
        return response.success(serialize.public(adm), 200)

    @app.route("/snf/admissions/<aid>/discharge", methods=["POST"])
    def discharge(aid):
        gate(["AdmissionsCoordinator"])
        adm = lookups.get_admission(aid)
        body = V.get_body()
        discharge_at = V.require(body, "discharge_at")
        V.as_datetime(discharge_at, "discharge_at")
        transitions.discharge_admission(adm, discharge_at)
        return response.success(serialize.public(adm), 200)
