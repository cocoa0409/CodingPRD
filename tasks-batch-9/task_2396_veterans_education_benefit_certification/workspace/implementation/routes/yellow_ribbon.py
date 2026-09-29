"""YellowRibbonAgreement and YellowRibbonAward endpoints (CALC-3 step S8)."""

from calc import calc3_step8
from common import (
    ListQuery,
    ROLE_BURSAR,
    ROLE_SCO,
    ROLE_SUPERVISORY,
    ROLE_VA,
    append_audit,
    authenticate,
    get_agreement,
    get_award,
    get_certification,
    new_row,
    require_official,
    serialize,
    touch,
)
from db import db, lock
from errors import fail
from response import object_response
from validation import body, enum_field, int_field, string_field

DEGREE_LEVELS = ("UNDERGRAD", "GRADUATE", "CERTIFICATE")
AGREEMENT_STATUSES = ("ACTIVE", "CLOSED")
AWARD_STATUSES = ("PROVISIONAL", "FINAL", "REVERSED")
AWARD_LIVE = ("PROVISIONAL", "FINAL")

READ_ROLES = (ROLE_SCO, ROLE_SUPERVISORY, ROLE_BURSAR, ROLE_VA)


def register(app):
    # ---------------------------------------------------------- agreements
    @app.post("/yellow-ribbon-agreements")
    def create_agreement():
        with lock:
            actor = authenticate((ROLE_SUPERVISORY,))
            data = body()
            academic_year = string_field(data, "academic_year")
            degree_level = enum_field(data, "degree_level", DEGREE_LEVELS)
            per_student_cap = int_field(data, "per_student_annual_cap_cents", minimum=0)
            annual_pool = int_field(data, "annual_pool_cents", minimum=0)
            max_participants = int_field(data, "max_participants", minimum=1)
            require_official(actor)

            row = new_row()
            row["academic_year"] = academic_year
            row["degree_level"] = degree_level
            row["per_student_annual_cap_cents"] = per_student_cap
            row["annual_pool_cents"] = annual_pool
            row["max_participants"] = max_participants
            row["pool_remaining_cents"] = annual_pool
            row["participant_count"] = 0
            row["status"] = "ACTIVE"
            db.agreements[row["id"]] = row
            return object_response(serialize(row), 201)

    @app.get("/yellow-ribbon-agreements/<agreement_id>")
    def read_agreement(agreement_id):
        with lock:
            actor = authenticate(READ_ROLES)
            require_official(actor)
            return object_response(serialize(get_agreement(agreement_id)))

    @app.get("/yellow-ribbon-agreements")
    def list_agreements():
        with lock:
            actor = authenticate(READ_ROLES)
            query = ListQuery((("academic_year", None),
                               ("degree_level", DEGREE_LEVELS),
                               ("status", AGREEMENT_STATUSES)))
            require_official(actor)
            return query.emit(db.agreements.values())

    @app.post("/yellow-ribbon-agreements/<agreement_id>/close")
    def close_agreement(agreement_id):
        with lock:
            actor = authenticate((ROLE_SUPERVISORY,))
            require_official(actor)
            agreement = get_agreement(agreement_id)
            if agreement["status"] != "ACTIVE":
                fail("ERR_AGREEMENT_ALREADY_CLOSED",
                     "This Yellow Ribbon agreement is already closed.")
            agreement["status"] = "CLOSED"
            touch(agreement)
            return object_response(serialize(agreement))

    # --------------------------------------------------------------- awards
    @app.post("/yellow-ribbon-awards")
    def create_award():
        with lock:
            actor = authenticate((ROLE_SUPERVISORY,))
            data = body()
            certification_id = string_field(data, "certification_id")
            agreement_id = string_field(data, "agreement_id")
            expected_version = int_field(data, "expected_agreement_version", minimum=0)
            require_official(actor)

            cert = get_certification(certification_id)
            agreement = get_agreement(agreement_id)

            if expected_version != agreement["version"]:
                fail("ERR_STALE_AGREEMENT_VERSION",
                     "The Yellow Ribbon agreement has been modified since it was read.")

            if cert["status"] != "CERTIFIED":
                fail("ERR_CERTIFICATION_NOT_CERTIFIED",
                     "Only a CERTIFIED certification may draw a Yellow Ribbon award.")
            if agreement["status"] != "ACTIVE":
                fail("ERR_AGREEMENT_CLOSED",
                     "This Yellow Ribbon agreement is closed to new awards.")

            term = db.terms.get(cert["term_id"])
            program = db.programs.get(cert["program_id"])
            term_year = term["academic_year"] if term is not None else None
            program_level = program["degree_level"] if program is not None else None
            if (agreement["academic_year"] != term_year
                    or agreement["degree_level"] != program_level):
                fail("ERR_AGREEMENT_SCOPE_MISMATCH",
                     "The agreement's academic year and degree level must match the "
                     "certified term and program.")

            student = db.students[cert["student_id"]]
            if not (student["chapter"] == "CH33" and student["benefit_level_pct"] == 100):
                fail("ERR_YR_INELIGIBLE_STUDENT",
                     "Yellow Ribbon requires a CH33 student at the 100 percent benefit level.")

            for award in db.awards.values():
                if award["certification_id"] == cert["id"] and award["status"] in AWARD_LIVE:
                    fail("ERR_AWARD_ALREADY_EXISTS",
                         "A live Yellow Ribbon award already exists for this certification.")

            if agreement["participant_count"] >= agreement["max_participants"]:
                fail("ERR_YR_PARTICIPANT_LIMIT_REACHED",
                     "This agreement has reached its participant limit.")
            if agreement["pool_remaining_cents"] <= 0:
                fail("ERR_YR_POOL_EXHAUSTED",
                     "This agreement's annual pool is exhausted.")

            split = calc3_step8(cert, agreement)

            row = new_row()
            row["certification_id"] = cert["id"]
            row["agreement_id"] = agreement["id"]
            row["yr_gap_basis_cents"] = split["yr_gap_basis_cents"]
            row["per_student_remaining_before_cents"] = split["per_student_remaining_before_cents"]
            row["pool_remaining_before_cents"] = split["pool_remaining_before_cents"]
            row["school_share_cents"] = split["school_share_cents"]
            row["va_match_cents"] = split["va_match_cents"]
            row["student_out_of_pocket_cents"] = split["student_out_of_pocket_cents"]
            row["reversal_reason"] = None
            row["status"] = "PROVISIONAL"
            db.awards[row["id"]] = row

            agreement["pool_remaining_cents"] -= split["school_share_cents"]
            agreement["participant_count"] += 1
            touch(agreement)

            return object_response(serialize(row), 201)

    @app.get("/yellow-ribbon-awards/<award_id>")
    def read_award(award_id):
        with lock:
            actor = authenticate(READ_ROLES)
            require_official(actor)
            return object_response(serialize(get_award(award_id)))

    @app.get("/yellow-ribbon-awards")
    def list_awards():
        with lock:
            actor = authenticate(READ_ROLES)
            query = ListQuery((("certification_id", None),
                               ("agreement_id", None),
                               ("status", AWARD_STATUSES)))
            require_official(actor)
            return query.emit(db.awards.values())

    @app.post("/yellow-ribbon-awards/<award_id>/finalize")
    def finalize_award(award_id):
        with lock:
            actor = authenticate((ROLE_SUPERVISORY,))
            require_official(actor)
            award = get_award(award_id)
            if award["status"] != "PROVISIONAL":
                fail("ERR_AWARD_NOT_PROVISIONAL",
                     "Only a PROVISIONAL award may be finalized.")
            award["status"] = "FINAL"
            touch(award)
            return object_response(serialize(award))

    @app.post("/yellow-ribbon-awards/<award_id>/reverse")
    def reverse_award(award_id):
        with lock:
            actor = authenticate((ROLE_SUPERVISORY,))
            data = body()
            reversal_reason = string_field(data, "reversal_reason")
            require_official(actor)
            award = get_award(award_id)

            if award["status"] not in AWARD_LIVE:
                fail("ERR_AWARD_ALREADY_REVERSED", "This award is already reversed.")

            award["status"] = "REVERSED"
            award["reversal_reason"] = reversal_reason
            touch(award)

            agreement = db.agreements.get(award["agreement_id"])
            if agreement is not None:
                agreement["pool_remaining_cents"] += award["school_share_cents"]
                agreement["participant_count"] -= 1
                touch(agreement)

            append_audit(
                award["certification_id"],
                "AWARD_REVERSED",
                actor.role,
                actor.user_id,
                "Award %s reversed: %s" % (award["id"], reversal_reason),
            )

            return object_response(serialize(award))
