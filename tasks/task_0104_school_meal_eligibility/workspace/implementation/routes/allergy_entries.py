"""AllergyProfileEntry endpoints. PRD §3.2."""

from flask import Blueprint, request, g

from core.auth import require_roles
from core.envelope import success_object
from core.errors import raise_error
from core.store import STORE, stamp_append_only, lock
from core.validation import require_body, require_field, require_enum

from services.constants import ALLERGENS, SEVERITIES
from services.relationships import (
    get_district_or_404, get_student_in_district,
    get_allergy_entry_for_student,
)
from services.views import allergy_entry_view


bp = Blueprint("allergy_entries", __name__)


@bp.post("/districts/<district_id>/students/<student_id>/allergy-entries")
@require_roles("Parent")
def create_allergy_entry(district_id, student_id):
    with lock():
        get_district_or_404(district_id)
        s = get_student_in_district(district_id, student_id)
        # Parent must own the student.
        if s["parent_account_id"] != g.user_id:
            raise_error("ERR_FORBIDDEN",
                        "Parent may only manage allergy entries on their own student")
        body = require_body(request)
        allergen = require_enum(body, "allergen", ALLERGENS)
        severity = require_enum(body, "severity", SEVERITIES)
        doctor_note = require_field(body, "doctor_note_attached", kind="bool")
        # SEVERE requires doctor_note_attached == true (priority 6).
        if severity == "SEVERE" and not doctor_note:
            raise_error("ERR_DOCTOR_NOTE_REQUIRED",
                        "Severity=SEVERE requires doctor_note_attached=true")
        # Duplicate-allergen check (priority 12).
        for e in STORE.allergy_entries.values():
            if (e["student_id"] == student_id
                    and e["allergen"] == allergen
                    and e["status"] == "ACTIVE"):
                raise_error("ERR_DUPLICATE_ALLERGEN",
                            "An ACTIVE AllergyProfileEntry already exists for this allergen")
        e = {
            "student_id": student_id,
            "allergen": allergen,
            "severity": severity,
            "status": "ACTIVE",
            "doctor_note_attached": doctor_note,
        }
        stamp_append_only(e)
        STORE.allergy_entries[e["id"]] = e
        return success_object(allergy_entry_view(e), status=201)


@bp.delete("/districts/<district_id>/students/<student_id>/allergy-entries/<entry_id>")
@require_roles("Parent")
def revoke_allergy_entry(district_id, student_id, entry_id):
    with lock():
        get_district_or_404(district_id)
        s = get_student_in_district(district_id, student_id)
        if s["parent_account_id"] != g.user_id:
            raise_error("ERR_FORBIDDEN",
                        "Parent may only manage allergy entries on their own student")
        e = get_allergy_entry_for_student(student_id, entry_id)
        if e["status"] != "ACTIVE":
            raise_error("ERR_INVALID_STATE",
                        "AllergyProfileEntry is not ACTIVE")
        e["status"] = "REVOKED"
        return success_object(allergy_entry_view(e))
