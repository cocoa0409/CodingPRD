"""Pre-built role headers for every role named in the PRD.

The acting user is carried in ``X-User-ID`` and the acting capacity in the role
header.  No role is backed by a persisted entity, so the shared constants below
are the canonical form for almost every call.  The per-role builders exist for
the one rule that keys on the identifier rather than the role: the user that
filed a warranty claim may not adjudicate that same claim.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants — one opaque operator identifier per role.
TEST_USERS = {
    "mill_admin_headers": build_user_headers("u_mill_admin", "MillAdmin"),
    "procurement_clerk_headers": build_user_headers(
        "u_procurement_clerk", "ProcurementClerk"
    ),
    "kiln_operator_headers": build_user_headers("u_kiln_operator", "KilnOperator"),
    "mill_supervisor_headers": build_user_headers(
        "u_mill_supervisor", "MillSupervisor"
    ),
    "grade_inspector_headers": build_user_headers(
        "u_grade_inspector", "GradeInspector"
    ),
    "prefinish_scheduler_headers": build_user_headers(
        "u_prefinish_scheduler", "PrefinishScheduler"
    ),
    "byproduct_broker_headers": build_user_headers(
        "u_byproduct_broker", "ByproductBroker"
    ),
    "warranty_adjudicator_headers": build_user_headers(
        "u_warranty_adjudicator", "WarrantyAdjudicator"
    ),
    # The reserved role value that marks an unauthenticated caller.
    "anonymous_headers": build_user_headers("u_anonymous", "Anonymous"),
}

# A request that carries no role header at all is also an unauthenticated caller.
NO_ROLE_HEADERS = {
    "X-User-ID": "u_no_role",
    "Content-Type": "application/json",
}

# Distinct identifiers used by the segregation-of-duties workflow.
CLAIM_SUBMITTER_USER_ID = "u_intake"
CLAIM_ADJUDICATOR_USER_ID = "u_adjudicator"


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary operator identifier and role."""
    return build_user_headers(user_id, role)


def make_mill_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MillAdmin")


def make_procurement_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProcurementClerk")


def make_kiln_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "KilnOperator")


def make_mill_supervisor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MillSupervisor")


def make_grade_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "GradeInspector")


def make_prefinish_scheduler_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PrefinishScheduler")


def make_byproduct_broker_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ByproductBroker")


def make_warranty_adjudicator_headers(user_id: str) -> dict:
    """For WarrantyAdjudicator.

    Pass the operator identifier that must be recorded as
    ``submitted_by_user_id`` or ``adjudicated_by_user_id``; the two must differ
    on one claim.
    """
    return build_user_headers(user_id, "WarrantyAdjudicator")


__all__ = [
    "TEST_USERS",
    "NO_ROLE_HEADERS",
    "CLAIM_SUBMITTER_USER_ID",
    "CLAIM_ADJUDICATOR_USER_ID",
    "make_headers",
    "make_mill_admin_headers",
    "make_procurement_clerk_headers",
    "make_kiln_operator_headers",
    "make_mill_supervisor_headers",
    "make_grade_inspector_headers",
    "make_prefinish_scheduler_headers",
    "make_byproduct_broker_headers",
    "make_warranty_adjudicator_headers",
]
