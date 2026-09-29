"""Schools, programs and partner agreements."""

import re

import domain
import serialize
from auth import employer_scope, endpoint, school_scope
from errors import fail, invalid
from store import db, new_record, touch
from validate import (
    ACCREDITATION_STATUSES,
    CREDENTIAL_TYPES,
    SKILL_TRACKS,
    bool_field,
    body,
    date_field,
    email_field,
    enum_field,
    int_field,
    number_field,
    pagination,
    query_enum,
    query_str,
    string_field,
)

from .common import filter_eq, object_response, paged

AGREEMENT_STATUSES = ["PENDING", "ACTIVE", "TERMINATED"]
_STATE_CODE = re.compile(r"^[A-Z]{2}$")


def register(app):
    # ------------------------------------------------------------------- schools
    @app.post("/schools")
    @endpoint(["PlatformAdmin"])
    def create_school():
        data = body()
        state_code = string_field(data, "state_code", min_len=2, max_len=2)
        if not _STATE_CODE.match(state_code):
            invalid("'state_code' must be exactly two uppercase letters")
        row = new_record(
            {
                "legal_name": string_field(data, "legal_name", max_len=160),
                "state_code": state_code,
                "contact_email": email_field(data, "contact_email"),
                "accreditation_status": enum_field(
                    data,
                    "accreditation_status",
                    ACCREDITATION_STATUSES,
                    required=False,
                    default="ACCREDITED",
                ),
            }
        )
        db.schools[row["id"]] = row
        return object_response(serialize.school(row), 201)

    @app.get("/schools/<school_id>")
    @endpoint(["PlatformAdmin", "BenefitAdministrator", "SchoolPartner"])
    def read_school(school_id):
        school = domain.must(db.schools, school_id, "ERR_SCHOOL_NOT_FOUND")
        school_scope(school_id)
        return object_response(serialize.school(school))

    # ------------------------------------------------------------------ programs
    @app.post("/schools/<school_id>/programs")
    @endpoint(["SchoolPartner", "PlatformAdmin"])
    def create_program(school_id):
        data = body()
        fields = {
            "school_id": school_id,
            "name": string_field(data, "name", max_len=160),
            "credential_type": enum_field(data, "credential_type", CREDENTIAL_TYPES),
            "skill_track": enum_field(data, "skill_track", SKILL_TRACKS),
            "list_tuition_per_credit_cents": int_field(
                data, "list_tuition_per_credit_cents", minimum=1
            ),
            "total_credits": int_field(data, "total_credits", minimum=1),
            "term_length_weeks": int_field(data, "term_length_weeks", minimum=1),
        }
        domain.must(db.schools, school_id, "ERR_SCHOOL_NOT_FOUND")
        school_scope(school_id)
        row = new_record(fields)
        db.programs[row["id"]] = row
        return object_response(serialize.program(row), 201)

    @app.get("/schools/<school_id>/programs")
    @endpoint(["PlatformAdmin", "BenefitAdministrator", "SchoolPartner", "Employee"])
    def list_programs(school_id):
        limit, offset = pagination()
        credential_type = query_enum("credential_type", CREDENTIAL_TYPES)
        skill_track = query_enum("skill_track", SKILL_TRACKS)
        domain.must(db.schools, school_id, "ERR_SCHOOL_NOT_FOUND")
        school_scope(school_id)
        rows = [p for p in db.programs.values() if p["school_id"] == school_id]
        rows = filter_eq(rows, "credential_type", credential_type)
        rows = filter_eq(rows, "skill_track", skill_track)
        return paged(rows, serialize.program, limit, offset)

    # ---------------------------------------------------------------- agreements
    @app.post("/partner-agreements")
    @endpoint(["PlatformAdmin"])
    def create_agreement():
        data = body()
        school_id = string_field(data, "school_id")
        employer_id = string_field(data, "employer_id")
        negotiated_discount_pct = number_field(
            data, "negotiated_discount_pct", minimum=0, maximum=0.60, decimals=4
        )
        direct_bill_enabled = bool_field(
            data, "direct_bill_enabled", required=False, default=False
        )
        effective_from = date_field(data, "effective_from")
        effective_to = date_field(data, "effective_to")
        if effective_to <= effective_from:
            invalid("'effective_to' must be strictly after 'effective_from'")

        # rule 15: employer_id is resolved before school_id
        domain.must(db.employers, employer_id, "ERR_EMPLOYER_NOT_FOUND")
        domain.must(db.schools, school_id, "ERR_SCHOOL_NOT_FOUND")

        row = new_record(
            {
                "school_id": school_id,
                "employer_id": employer_id,
                "negotiated_discount_pct": negotiated_discount_pct,
                "direct_bill_enabled": direct_bill_enabled,
                "effective_from": effective_from.isoformat(),
                "effective_to": effective_to.isoformat(),
                "status": "PENDING",
                "terminated_on": None,
            }
        )
        db.agreements[row["id"]] = row
        return object_response(serialize.agreement(row), 201)

    @app.get("/partner-agreements")
    @endpoint(["PlatformAdmin", "BenefitAdministrator", "SchoolPartner"])
    def list_agreements():
        limit, offset = pagination()
        status = query_enum("status", AGREEMENT_STATUSES)
        rows = list(db.agreements.values())
        rows = filter_eq(rows, "school_id", query_str("school_id"))
        rows = filter_eq(rows, "employer_id", query_str("employer_id"))
        rows = filter_eq(rows, "status", status)
        return paged(rows, serialize.agreement, limit, offset)

    @app.get("/partner-agreements/<agreement_id>")
    @endpoint(["PlatformAdmin", "BenefitAdministrator", "SchoolPartner"])
    def read_agreement(agreement_id):
        agreement = domain.must(db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
        employer_scope(agreement["employer_id"])
        school_scope(agreement["school_id"])
        return object_response(serialize.agreement(agreement))

    @app.post("/partner-agreements/<agreement_id>/activate")
    @endpoint(["BenefitAdministrator"])
    def activate_agreement(agreement_id):
        agreement = domain.must(db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
        employer_scope(agreement["employer_id"])
        if agreement["status"] != "PENDING":
            fail(
                "ERR_AGREEMENT_INVALID_STATE",
                "agreement is %s, not PENDING" % agreement["status"],
            )
        school = db.schools[agreement["school_id"]]
        if school["accreditation_status"] == "UNACCREDITED":
            fail("ERR_SCHOOL_NOT_ACCREDITED", "the school is UNACCREDITED")
        agreement["status"] = "ACTIVE"
        touch(agreement)
        return object_response(serialize.agreement(agreement))

    @app.post("/partner-agreements/<agreement_id>/terminate")
    @endpoint(["BenefitAdministrator"])
    def terminate_agreement(agreement_id):
        agreement = domain.must(db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
        employer_scope(agreement["employer_id"])
        if agreement["status"] != "ACTIVE":
            fail(
                "ERR_AGREEMENT_INVALID_STATE",
                "agreement is %s, not ACTIVE" % agreement["status"],
            )
        agreement["status"] = "TERMINATED"
        agreement["terminated_on"] = domain.clock_date().isoformat()
        touch(agreement)
        domain.cascade_agreement_termination(agreement)
        return object_response(serialize.agreement(agreement))
