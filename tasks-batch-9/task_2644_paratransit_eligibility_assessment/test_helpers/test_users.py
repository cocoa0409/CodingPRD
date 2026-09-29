"""Acting identities and their request headers.

Two kinds of identity exist in this contract and they must not be confused.

For the seven staff roles the acting ``X-User-ID`` is an opaque operator
identifier that is never resolved to a stored row, so a fixed constant per role
is exactly right, and a second identifier per role is provided wherever a test
needs two different operators to satisfy an independence comparison.

For a rider the acting ``X-User-ID`` is the identifier of that rider's own
record, which only exists once the record has been created. Rider headers must
therefore always be built per test with ``make_applicant_headers``; there is no
usable rider constant.
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --- Opaque staff operator identifiers --------------------------------------
INTAKE_CLERK_USER_ID = "clerk-1"
INTAKE_CLERK_2_USER_ID = "clerk-2"
EVALUATOR_USER_ID = "eval-1"
EVALUATOR_2_USER_ID = "eval-2"
SPECIALIST_USER_ID = "spec-1"
SPECIALIST_2_USER_ID = "spec-2"
REVIEWER_USER_ID = "rev-1"
REVIEWER_2_USER_ID = "rev-2"
CONDUCT_OFFICER_USER_ID = "co-1"
CONDUCT_OFFICER_2_USER_ID = "co-2"
TRAVEL_TRAINER_USER_ID = "tt-1"
TRAVEL_TRAINER_2_USER_ID = "tt-2"
ADMIN_USER_ID = "admin-1"
ADMIN_2_USER_ID = "admin-2"

# --- Ready-made staff header dictionaries -----------------------------------
CLERK_HEADERS = build_user_headers(INTAKE_CLERK_USER_ID, UserRole.INTAKE_CLERK.value)
CLERK_2_HEADERS = build_user_headers(INTAKE_CLERK_2_USER_ID, UserRole.INTAKE_CLERK.value)
EVALUATOR_HEADERS = build_user_headers(EVALUATOR_USER_ID, UserRole.EVALUATOR.value)
EVALUATOR_2_HEADERS = build_user_headers(EVALUATOR_2_USER_ID, UserRole.EVALUATOR.value)
SPECIALIST_HEADERS = build_user_headers(
    SPECIALIST_USER_ID, UserRole.ELIGIBILITY_SPECIALIST.value
)
SPECIALIST_2_HEADERS = build_user_headers(
    SPECIALIST_2_USER_ID, UserRole.ELIGIBILITY_SPECIALIST.value
)
REVIEWER_HEADERS = build_user_headers(REVIEWER_USER_ID, UserRole.INDEPENDENT_REVIEWER.value)
REVIEWER_2_HEADERS = build_user_headers(
    REVIEWER_2_USER_ID, UserRole.INDEPENDENT_REVIEWER.value
)
CONDUCT_OFFICER_HEADERS = build_user_headers(
    CONDUCT_OFFICER_USER_ID, UserRole.CONDUCT_OFFICER.value
)
CONDUCT_OFFICER_2_HEADERS = build_user_headers(
    CONDUCT_OFFICER_2_USER_ID, UserRole.CONDUCT_OFFICER.value
)
TRAINER_HEADERS = build_user_headers(TRAVEL_TRAINER_USER_ID, UserRole.TRAVEL_TRAINER.value)
TRAINER_2_HEADERS = build_user_headers(TRAVEL_TRAINER_2_USER_ID, UserRole.TRAVEL_TRAINER.value)
ADMIN_HEADERS = build_user_headers(ADMIN_USER_ID, UserRole.ACCESSIBILITY_OFFICE_ADMIN.value)
ADMIN_2_HEADERS = build_user_headers(ADMIN_2_USER_ID, UserRole.ACCESSIBILITY_OFFICE_ADMIN.value)

STAFF_HEADERS_BY_ROLE = {
    UserRole.INTAKE_CLERK.value: CLERK_HEADERS,
    UserRole.EVALUATOR.value: EVALUATOR_HEADERS,
    UserRole.ELIGIBILITY_SPECIALIST.value: SPECIALIST_HEADERS,
    UserRole.INDEPENDENT_REVIEWER.value: REVIEWER_HEADERS,
    UserRole.CONDUCT_OFFICER.value: CONDUCT_OFFICER_HEADERS,
    UserRole.TRAVEL_TRAINER.value: TRAINER_HEADERS,
    UserRole.ACCESSIBILITY_OFFICE_ADMIN.value: ADMIN_HEADERS,
}

STAFF_USER_ID_BY_ROLE = {
    UserRole.INTAKE_CLERK.value: INTAKE_CLERK_USER_ID,
    UserRole.EVALUATOR.value: EVALUATOR_USER_ID,
    UserRole.ELIGIBILITY_SPECIALIST.value: SPECIALIST_USER_ID,
    UserRole.INDEPENDENT_REVIEWER.value: REVIEWER_USER_ID,
    UserRole.CONDUCT_OFFICER.value: CONDUCT_OFFICER_USER_ID,
    UserRole.TRAVEL_TRAINER.value: TRAVEL_TRAINER_USER_ID,
    UserRole.ACCESSIBILITY_OFFICE_ADMIN.value: ADMIN_USER_ID,
}


def make_applicant_headers(applicant_id):
    """Headers for a rider acting on their own records.

    The acting identifier must be the rider's own record identifier, so this
    builder is the only correct way to obtain rider headers.
    """
    return build_user_headers(str(applicant_id), UserRole.APPLICANT.value)


def make_staff_headers(user_id, role):
    """Headers for an arbitrary staff operator identifier and role."""
    return build_user_headers(str(user_id), role)


def headers_without_role(user_id):
    """Headers carrying an acting identifier but no role at all."""
    return {"X-User-ID": str(user_id), "Content-Type": "application/json"}


def headers_without_user_id(role):
    """Headers carrying a role but no acting identifier at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_undeclared_role(user_id, role_name="Superintendent"):
    """Headers naming a role that is not one of the eight declared roles."""
    return build_user_headers(str(user_id), role_name)
