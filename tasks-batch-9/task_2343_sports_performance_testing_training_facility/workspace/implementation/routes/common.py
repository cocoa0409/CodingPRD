"""Shared lookup helpers.

Tier 3 (path existence) and tier 4 (body foreign keys) of the validation
ladder share one code set, so both go through these resolvers.
"""

from db import store
from errors import ApiError

_LOOKUPS = (
    ("athletes", "ERR_ATHLETE_NOT_FOUND", "Athlete"),
    ("injury_records", "ERR_INJURY_RECORD_NOT_FOUND", "InjuryRecord"),
    ("test_sessions", "ERR_TEST_SESSION_NOT_FOUND", "TestSession"),
    ("training_programs", "ERR_TRAINING_PROGRAM_NOT_FOUND", "TrainingProgram"),
    ("program_blocks", "ERR_PROGRAM_BLOCK_NOT_FOUND", "ProgramBlock"),
    ("group_sessions", "ERR_GROUP_SESSION_NOT_FOUND", "GroupSession"),
    ("enrollments", "ERR_ENROLLMENT_NOT_FOUND", "Enrollment"),
    ("staff_members", "ERR_STAFF_MEMBER_NOT_FOUND", "StaffMember"),
    ("certifications", "ERR_CERTIFICATION_NOT_FOUND", "Certification"),
    ("membership_packages", "ERR_MEMBERSHIP_PACKAGE_NOT_FOUND", "MembershipPackage"),
    ("team_contracts", "ERR_TEAM_CONTRACT_NOT_FOUND", "TeamContract"),
    ("rts_plans", "ERR_RTS_PLAN_NOT_FOUND", "ReturnToSportPlan"),
    ("clearance_documents", "ERR_CLEARANCE_DOCUMENT_NOT_FOUND", "ClearanceDocument"),
)


def _resolver(collection_name, error_id, label):
    def resolve(row_id):
        collection = getattr(store, collection_name)
        record = collection.get(row_id) if isinstance(row_id, str) else None
        if record is None:
            raise ApiError(error_id, "%s %r was not found" % (label, row_id))
        return record

    return resolve


get_athlete = _resolver(*_LOOKUPS[0])
get_injury_record = _resolver(*_LOOKUPS[1])
get_test_session = _resolver(*_LOOKUPS[2])
get_training_program = _resolver(*_LOOKUPS[3])
get_program_block = _resolver(*_LOOKUPS[4])
get_group_session = _resolver(*_LOOKUPS[5])
get_enrollment = _resolver(*_LOOKUPS[6])
get_staff_member = _resolver(*_LOOKUPS[7])
get_certification = _resolver(*_LOOKUPS[8])
get_membership_package = _resolver(*_LOOKUPS[9])
get_team_contract = _resolver(*_LOOKUPS[10])
get_rts_plan = _resolver(*_LOOKUPS[11])
get_clearance_document = _resolver(*_LOOKUPS[12])


# ------------------------------------------------------------ tier 8 state ----
def state_error(current, terminal_states, message):
    """ERR_ALREADY_TERMINAL for terminal source states, ERR_INVALID_STATE
    for any other undeclared source state (PRD 2.8 tier 8)."""
    if current in terminal_states:
        return ApiError("ERR_ALREADY_TERMINAL", message)
    return ApiError("ERR_INVALID_STATE", message)


def require_state(record, field, allowed, terminal_states, label):
    current = record[field]
    if current in allowed:
        return
    raise state_error(
        current,
        terminal_states,
        "%s in state %s does not permit this transition" % (label, current),
    )
