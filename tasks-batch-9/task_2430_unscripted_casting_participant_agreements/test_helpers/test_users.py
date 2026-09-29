"""Pre-built role headers for every role in the PRD (§2.1).

Five of the six roles carry an opaque operator identifier that "is not tied to
any persisted entity"; for those the shared constants below are the canonical
form.  Several rules compare one operator's identifier against another's — the
four-eyes screening rule and the four-eyes execution rule of §2.10 — so this
module exposes two distinct operator identities for the ComplianceOfficer,
BusinessAffairs and WelfareOfficer roles.

The ``Applicant`` role is different: `X-User-ID` is the `id` of the acting
`Applicant` record, and every ownership check compares the resource's applicant
reference against it.  Ownership-gated participant calls MUST therefore use
``make_applicant_headers(applicant["id"])`` and never a shared constant.
"""

from prd_bench_local_runner.testing import build_user_headers

# Operator identifiers used across the suite.
PRODUCTION_ADMIN_USER_ID = "pa_1"
CASTING_DIRECTOR_USER_ID = "cd_1"
COMPLIANCE_OFFICER_1_USER_ID = "co_1"
COMPLIANCE_OFFICER_2_USER_ID = "co_2"
BUSINESS_AFFAIRS_1_USER_ID = "ba_1"
BUSINESS_AFFAIRS_2_USER_ID = "ba_2"
WELFARE_OFFICER_1_USER_ID = "wo_1"
WELFARE_OFFICER_2_USER_ID = "wo_2"


TEST_USERS = {
    # Opaque operator roles — shared constants are the canonical form.
    "production_admin_headers": build_user_headers(
        PRODUCTION_ADMIN_USER_ID, "ProductionAdmin"
    ),
    "production_admin_2_headers": build_user_headers("pa_2", "ProductionAdmin"),
    "casting_director_headers": build_user_headers(
        CASTING_DIRECTOR_USER_ID, "CastingDirector"
    ),
    "casting_director_2_headers": build_user_headers("cd_2", "CastingDirector"),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_1_USER_ID, "ComplianceOfficer"
    ),
    "compliance_officer_2_headers": build_user_headers(
        COMPLIANCE_OFFICER_2_USER_ID, "ComplianceOfficer"
    ),
    "business_affairs_headers": build_user_headers(
        BUSINESS_AFFAIRS_1_USER_ID, "BusinessAffairs"
    ),
    "business_affairs_2_headers": build_user_headers(
        BUSINESS_AFFAIRS_2_USER_ID, "BusinessAffairs"
    ),
    "welfare_officer_headers": build_user_headers(
        WELFARE_OFFICER_1_USER_ID, "WelfareOfficer"
    ),
    "welfare_officer_2_headers": build_user_headers("wo_2", "WelfareOfficer"),
    # Participant role: fallback for tests that do NOT exercise ownership
    # (for example a 401/403/404 probe).  Never use this where the call is
    # ownership-gated.
    "applicant_headers": build_user_headers("applicant-not-an-entity", "Applicant"),
}


def make_applicant_headers(applicant_id: str) -> dict:
    """Headers for the participant role.

    `X-User-ID` must be the acting applicant record's own `id`; pass the real
    applicant id whenever the addressed call is ownership-gated (reading one
    applicant, withdrawal, counter-offer, filing a complaint, reading one
    agreement).
    """
    return build_user_headers(applicant_id, "Applicant")


def make_production_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionAdmin")


def make_casting_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CastingDirector")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_business_affairs_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BusinessAffairs")


def make_welfare_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "WelfareOfficer")
