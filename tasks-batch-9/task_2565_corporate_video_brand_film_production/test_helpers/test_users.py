"""Pre-built request headers for the six roles of PRD §2.1.

Identity in this API is split. "Five of the six roles carry an opaque identity.
When `X-User-Role` is `ProductionCoordinator`, `LineProducer`, `PostSupervisor`,
`ClientApprover`, or `ComplianceOfficer`, `X-User-ID` is an opaque operator
identifier that is not tied to any persisted entity" — so those five get fixed,
*distinct* constants, which is what the three segregation-of-duties comparisons
of §2.1 need.

"The sixth role is different: when `X-User-Role` is `CrewMember`, `X-User-ID` is
the `id` of the acting `CrewMember` roster row" — so a crew caller's headers can
only be built once the roster row exists, which is what
:func:`make_crew_member_headers` is for.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CLIENT_APPROVER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_CREW_MEMBER,
    ROLE_LINE_PRODUCER,
    ROLE_POST_SUPERVISOR,
    ROLE_PRODUCTION_COORDINATOR,
)

# ─── Canonical opaque operator ids ─────────────────────────────────────────
USER_PRODUCER_1 = "producer-1"
USER_PRODUCER_2 = "producer-2"
USER_COORDINATOR_1 = "coord-1"
USER_COORDINATOR_2 = "coord-2"
USER_POST_1 = "post-1"
USER_POST_2 = "post-2"
USER_CLIENT_1 = "client-1"
USER_CLIENT_2 = "client-2"
USER_OFFICER_1 = "officer-1"
USER_OFFICER_2 = "officer-2"

# ─── One header set per opaque role ────────────────────────────────────────
LINE_PRODUCER = build_user_headers(USER_PRODUCER_1, ROLE_LINE_PRODUCER)
LINE_PRODUCER_2 = build_user_headers(USER_PRODUCER_2, ROLE_LINE_PRODUCER)
COORDINATOR = build_user_headers(USER_COORDINATOR_1, ROLE_PRODUCTION_COORDINATOR)
COORDINATOR_2 = build_user_headers(USER_COORDINATOR_2, ROLE_PRODUCTION_COORDINATOR)
POST_SUPERVISOR = build_user_headers(USER_POST_1, ROLE_POST_SUPERVISOR)
POST_SUPERVISOR_2 = build_user_headers(USER_POST_2, ROLE_POST_SUPERVISOR)
CLIENT_APPROVER = build_user_headers(USER_CLIENT_1, ROLE_CLIENT_APPROVER)
CLIENT_APPROVER_2 = build_user_headers(USER_CLIENT_2, ROLE_CLIENT_APPROVER)
COMPLIANCE_OFFICER = build_user_headers(USER_OFFICER_1, ROLE_COMPLIANCE_OFFICER)
COMPLIANCE_OFFICER_2 = build_user_headers(USER_OFFICER_2, ROLE_COMPLIANCE_OFFICER)

# Role name → default header set, for the endpoint role sweeps of §4.
HEADERS_BY_OPAQUE_ROLE = {
    ROLE_LINE_PRODUCER: LINE_PRODUCER,
    ROLE_PRODUCTION_COORDINATOR: COORDINATOR,
    ROLE_POST_SUPERVISOR: POST_SUPERVISOR,
    ROLE_CLIENT_APPROVER: CLIENT_APPROVER,
    ROLE_COMPLIANCE_OFFICER: COMPLIANCE_OFFICER,
}


def make_crew_member_headers(crew_member_id: str) -> dict:
    """Headers for a `CrewMember` caller acting as the given roster row.

    PRD §2.1: "when `X-User-Role` is `CrewMember`, `X-User-ID` is the `id` of the
    acting `CrewMember` roster row, and ownership checks on any resource that
    references a `CrewMember` compare that resource's `crew_member_id` to
    `X-User-ID`."
    """
    return build_user_headers(crew_member_id, ROLE_CREW_MEMBER)


# A crew caller whose id is a well-formed UUID that names no roster row, used to
# probe the ownership comparison rather than the role check.
def make_foreign_crew_headers(other_crew_member_id: str) -> dict:
    """Headers for a crew caller who is *not* the owner of the row under test."""
    return make_crew_member_headers(other_crew_member_id)


# ─── Malformed authentication (PRD §2.1) ───────────────────────────────────
# "If either header is missing, empty, or if `X-User-Role` names anything outside
# those six values, the request is rejected with `ERR_UNAUTHENTICATED`".
NO_AUTH_HEADERS: dict = {"Content-Type": "application/json"}
MISSING_ROLE_HEADERS = {
    "X-User-ID": USER_PRODUCER_1,
    "Content-Type": "application/json",
}
MISSING_USER_ID_HEADERS = {
    "X-User-Role": ROLE_LINE_PRODUCER,
    "Content-Type": "application/json",
}
EMPTY_USER_ID_HEADERS = build_user_headers("", ROLE_LINE_PRODUCER)
EMPTY_ROLE_HEADERS = build_user_headers(USER_PRODUCER_1, "")
UNKNOWN_ROLE_HEADERS = build_user_headers(USER_PRODUCER_1, "GafferInChief")
