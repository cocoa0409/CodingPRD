"""Role identities and header builders (PRD §2.1).

Every request carries `X-User-ID` and `X-User-Role`. Two of the five roles are
entity-backed, which means their `X-User-ID` is *not* a free-form string:

* `Operator`    — `X-User-ID` must be the `Restaurant.id` they own; any other
                  value is `ERR_RESTAURANT_SCOPE_MISMATCH`.
* `ShiftLeader` — `X-User-ID` must be a `StaffMember.id` whose `restaurant_id`
                  equals the target store; any other value is
                  `ERR_STAFF_SCOPE_MISMATCH`.

For those two roles ALWAYS use `make_operator_headers(restaurant_id)` /
`make_shift_leader_headers(staff_member_id)` with a real id created by the test.
The remaining three roles (`ProgramAdmin`, `AccuracyAuditor`, `MarketCoach`) are
opaque, so a stable literal identifier is enough.
"""

from prd_bench_local_runner.testing import build_user_headers

# --- Role names ---------------------------------------------------------------
ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_OPERATOR = "Operator"
ROLE_SHIFT_LEADER = "ShiftLeader"
ROLE_ACCURACY_AUDITOR = "AccuracyAuditor"
ROLE_MARKET_COACH = "MarketCoach"

ALL_ROLES = (
    ROLE_PROGRAM_ADMIN,
    ROLE_OPERATOR,
    ROLE_SHIFT_LEADER,
    ROLE_ACCURACY_AUDITOR,
    ROLE_MARKET_COACH,
)

# A role value outside the five declared roles (PRD §2.1: unknown role is 401).
UNKNOWN_ROLE = "LaneTrainer"


# --- Opaque identities --------------------------------------------------------
PROGRAM_ADMIN_ID = "admin-1"
ACCURACY_AUDITOR_ID = "auditor-1"
MARKET_COACH_ID = "coach-1"
SECOND_MARKET_COACH_ID = "coach-2"


# --- Pre-built headers for the three opaque roles ------------------------------
ADMIN_HEADERS = build_user_headers(PROGRAM_ADMIN_ID, ROLE_PROGRAM_ADMIN)
AUDITOR_HEADERS = build_user_headers(ACCURACY_AUDITOR_ID, ROLE_ACCURACY_AUDITOR)
COACH_HEADERS = build_user_headers(MARKET_COACH_ID, ROLE_MARKET_COACH)
SECOND_COACH_HEADERS = build_user_headers(SECOND_MARKET_COACH_ID, ROLE_MARKET_COACH)

# Opaque roles only. Entity-backed roles are deliberately absent from this map so
# that no test can accidentally send a placeholder id where a real entity id is
# required.
TEST_USERS = {
    ROLE_PROGRAM_ADMIN: ADMIN_HEADERS,
    ROLE_ACCURACY_AUDITOR: AUDITOR_HEADERS,
    ROLE_MARKET_COACH: COACH_HEADERS,
}


# --- Header builders ----------------------------------------------------------
def make_admin_headers(user_id: str = PROGRAM_ADMIN_ID) -> dict:
    """ProgramAdmin headers (opaque identity)."""
    return build_user_headers(user_id, ROLE_PROGRAM_ADMIN)


def make_operator_headers(restaurant_id: str) -> dict:
    """Operator headers. `restaurant_id` MUST be the store this operator owns."""
    return build_user_headers(restaurant_id, ROLE_OPERATOR)


def make_shift_leader_headers(staff_member_id: str) -> dict:
    """ShiftLeader headers. `staff_member_id` MUST be a StaffMember of the store."""
    return build_user_headers(staff_member_id, ROLE_SHIFT_LEADER)


def make_auditor_headers(user_id: str = ACCURACY_AUDITOR_ID) -> dict:
    """AccuracyAuditor headers (opaque identity)."""
    return build_user_headers(user_id, ROLE_ACCURACY_AUDITOR)


def make_coach_headers(user_id: str = MARKET_COACH_ID) -> dict:
    """MarketCoach headers (opaque identity, recorded as issued_by_user_id)."""
    return build_user_headers(user_id, ROLE_MARKET_COACH)


def headers_without_user_id(role: str) -> dict:
    """Headers that name a role but omit `X-User-ID` entirely (PRD §2.1: 401)."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> dict:
    """Headers that carry an identity but omit `X-User-Role` (PRD §2.1: 401)."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def all_role_headers(restaurant_id: str, staff_member_id: str) -> dict:
    """Headers for all five roles against one store, keyed by role name.

    Used by the shared-read checks: PRD §2.1 says every GET endpoint is readable
    by all five roles.
    """
    return {
        ROLE_PROGRAM_ADMIN: ADMIN_HEADERS,
        ROLE_OPERATOR: make_operator_headers(restaurant_id),
        ROLE_SHIFT_LEADER: make_shift_leader_headers(staff_member_id),
        ROLE_ACCURACY_AUDITOR: AUDITOR_HEADERS,
        ROLE_MARKET_COACH: COACH_HEADERS,
    }
