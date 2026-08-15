"""Registry reconciliation endpoints (PRD §3.8) and test-driving clock/registry endpoints."""

from flask import request

import db
from db import clock, parse_iso, format_iso, stamp_new, touch, new_id
from errors import ApiError, ERR_VALIDATION
from middleware import require_roles
from response import success_object
from services.evaluation import (
    VACCINE_CODES,
    deficiency_codes,
    sync_run_view,
)
from services.validate import req_datetime, req_enum, req_int, req_string, require_body


def register(app):

    @app.post("/api/registry-sync-runs")
    def create_sync_run():
        require_roles("RegistryCoordinator")
        body = require_body(request.get_json(silent=True))
        school_code = req_string(body, "school_code")

        run = {
            "school_code": school_code,
            "status": "RUNNING",
            "registry_doses_seen": 0,
            "imported_count": 0,
            "matched_count": 0,
            "discrepancy_count": 0,
        }
        stamp_new(run)
        db.registry_sync_runs[run["id"]] = run

        # Find students of this school
        school_students = {s["id"]: s for s in db.students.values() if s["school_code"] == school_code}

        seen = 0
        imported = 0
        matched = 0
        discrepancy = 0
        affected_students = set()

        for seed in list(db.registry_seeds.values()):
            sid = seed["student_id"]
            if sid not in school_students:
                continue
            seen += 1
            vaccine_code = seed["vaccine_code"]
            dose_number = seed["dose_number"]
            seed_date = seed["administered_date"]
            # Find local non-VOIDED record on (student, vaccine_code, dose_number)
            local = None
            for r in db.immunization_records.values():
                if r["student_id"] == sid and r["vaccine_code"] == vaccine_code \
                        and r["dose_number"] == dose_number and r["status"] != "VOIDED":
                    local = r
                    break
            if local is None:
                # Import as VERIFIED REGISTRY_IMPORT
                rec = {
                    "student_id": sid,
                    "vaccine_code": vaccine_code,
                    "dose_number": dose_number,
                    "administered_date": seed_date,
                    "source": "REGISTRY_IMPORT",
                    "clinic_appointment_id": None,
                    "status": "VERIFIED",
                    "verified_by_user_id": None,
                }
                stamp_new(rec)
                db.immunization_records[rec["id"]] = rec
                imported += 1
                affected_students.add(sid)
            else:
                if local["administered_date"] == seed_date:
                    matched += 1
                else:
                    discrepancy += 1

        run["status"] = "COMPLETED"
        run["registry_doses_seen"] = seen
        run["imported_count"] = imported
        run["matched_count"] = matched
        run["discrepancy_count"] = discrepancy
        touch(run)

        # Recompute each affected student's evaluation (LOCAL_RECORDS unchanged;
        # but deficiency list is driven by LOCAL_RECORDS so it's still just a recompute).
        for sid in affected_students:
            student = db.students[sid]
            student["deficiency_vaccine_codes"] = deficiency_codes(student)
            touch(student)

        return success_object(sync_run_view(run), status=201)

    @app.post("/_clock/set_current_utc")
    def set_clock():
        require_roles("DistrictHealthOfficer")
        body = require_body(request.get_json(silent=True))
        to = req_datetime(body, "to_iso8601")
        clock.set(to)
        return success_object({"current_utc": format_iso(clock.now())})

    @app.post("/_registry/seed-doses")
    def seed_doses():
        require_roles("RegistryCoordinator")
        body = require_body(request.get_json(silent=True))
        student_id = req_string(body, "student_id")
        vaccine_code = req_enum(body, "vaccine_code", VACCINE_CODES)
        dose_number = req_int(body, "dose_number", minimum=1)
        administered = req_datetime(body, "administered_date")
        seed_id = new_id()
        db.registry_seeds[seed_id] = {
            "seed_id": seed_id,
            "student_id": student_id,
            "vaccine_code": vaccine_code,
            "dose_number": dose_number,
            "administered_date": format_iso(administered),
        }
        return success_object({"seed_id": seed_id}, status=201)
