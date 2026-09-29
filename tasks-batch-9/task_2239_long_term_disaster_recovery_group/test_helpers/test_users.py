"""Pre-built role headers for every role named in the PRD.

`MemberOrgDelegate` is the only role whose `X-User-ID` is a resource key: it is the
`id` of the acting member organization. Every ownership-gated delegate call must
therefore use `make_member_org_delegate_headers(<member_organization id>)`; the
shared constant below exists only for delegate calls that never reach an ownership
comparison (bad payload, unknown resource, wrong-role rejection).
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers reused across setups. These match the actor ids the
# segregation-of-duties rules compare against, so keep them distinct per role.
INTAKE_SPECIALIST_USER_ID = "u_intake_1"
CASE_MANAGER_USER_ID = "u_cm_1"
CASE_MANAGER_ALT_USER_ID = "u_cm_2"
CHAIR_USER_ID = "u_chair_1"
DISBURSEMENT_OFFICER_USER_ID = "u_do_1"
CONSTRUCTION_MANAGER_USER_ID = "u_cn_1"
VOLUNTEER_COORDINATOR_USER_ID = "u_vc_1"
LTRG_ADMIN_USER_ID = "u_admin_1"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "intake_specialist_headers": build_user_headers(
        INTAKE_SPECIALIST_USER_ID, "IntakeSpecialist"
    ),
    "case_manager_headers": build_user_headers(CASE_MANAGER_USER_ID, "CaseManager"),
    "case_manager_alt_headers": build_user_headers(CASE_MANAGER_ALT_USER_ID, "CaseManager"),
    "unmet_needs_chair_headers": build_user_headers(CHAIR_USER_ID, "UnmetNeedsChair"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "member_org_delegate_headers": build_user_headers(
        "test-member-org-delegate-1", "MemberOrgDelegate"
    ),
    "disbursement_officer_headers": build_user_headers(
        DISBURSEMENT_OFFICER_USER_ID, "DisbursementOfficer"
    ),
    "construction_manager_headers": build_user_headers(
        CONSTRUCTION_MANAGER_USER_ID, "ConstructionManager"
    ),
    "volunteer_coordinator_headers": build_user_headers(
        VOLUNTEER_COORDINATOR_USER_ID, "VolunteerCoordinator"
    ),
    "ltrg_admin_headers": build_user_headers(LTRG_ADMIN_USER_ID, "LTRGAdmin"),
}


def make_raw_headers(user_id: str = None, role: str = None) -> Dict[str, str]:
    """Headers with either identity field deliberately omitted or unrecognized.

    Passing `None` for `user_id` or `role` leaves that header out entirely, which is how
    the PRD's "either header is absent" case is exercised; passing a role name that is not
    one of the eight recognized roles exercises the unrecognized-role case.
    """
    headers = {"Content-Type": "application/json"}
    if user_id is not None:
        headers["X-User-ID"] = user_id
    if role is not None:
        headers["X-User-Role"] = role
    return headers


def make_member_org_delegate_headers(member_org_id: str) -> Dict[str, str]:
    """Headers for the delegate of one member organization.

    Pass the member organization's own `id`: for this role `X-User-ID` *is* that id,
    and every ownership comparison on pledges is made against it.
    """
    return build_user_headers(member_org_id, "MemberOrgDelegate")


def make_case_manager_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary case-manager operator identifier."""
    return build_user_headers(user_id, "CaseManager")


def make_chair_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary chair operator identifier."""
    return build_user_headers(user_id, "UnmetNeedsChair")


def make_admin_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary administrator operator identifier."""
    return build_user_headers(user_id, "LTRGAdmin")


def make_disbursement_officer_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary disbursement-officer operator identifier."""
    return build_user_headers(user_id, "DisbursementOfficer")
