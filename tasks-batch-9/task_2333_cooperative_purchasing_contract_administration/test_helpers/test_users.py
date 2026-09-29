"""Header builders for the five roles.

Operator roles (CoopAdministrator, LeadAgencyOfficer, MemberAuditor) carry opaque
identifiers, so the shared dictionary below is safe for them. The two entity-backed
roles are pinned to a persisted row's id, so callers must always mint their headers
from the row itself with make_supplier_headers / make_member_headers.
"""

from prd_bench_local_runner.testing import build_user_headers

COOP_ADMINISTRATOR = "CoopAdministrator"
LEAD_AGENCY_OFFICER = "LeadAgencyOfficer"
SUPPLIER_REPRESENTATIVE = "SupplierRepresentative"
MEMBER_REPRESENTATIVE = "MemberRepresentative"
MEMBER_AUDITOR = "MemberAuditor"

# Opaque operator identifiers. Distinct ids matter wherever duty segregation
# compares two recorded values against each other.
ADMIN_INTAKE_ID = "adm-intake-01"
ADMIN_REVIEW_ID = "adm-review-02"
ADMIN_INVESTIGATOR_ID = "adm-invest-03"
ADMIN_ADJUDICATOR_ID = "adm-adjud-04"
ADMIN_PIGGYBACK_ID = "adm-piggy-05"
ADMIN_APPEAL_ID = "adm-appeal-06"
OFFICER_CONDUCTOR_ID = "lao-conductor-01"
OFFICER_AWARDER_ID = "lao-awarder-02"
AUDITOR_ID = "aud-member-01"

TEST_USERS = {
    "admin_intake_headers": build_user_headers(ADMIN_INTAKE_ID, COOP_ADMINISTRATOR),
    "admin_review_headers": build_user_headers(ADMIN_REVIEW_ID, COOP_ADMINISTRATOR),
    "admin_investigator_headers": build_user_headers(ADMIN_INVESTIGATOR_ID, COOP_ADMINISTRATOR),
    "admin_adjudicator_headers": build_user_headers(ADMIN_ADJUDICATOR_ID, COOP_ADMINISTRATOR),
    "admin_piggyback_headers": build_user_headers(ADMIN_PIGGYBACK_ID, COOP_ADMINISTRATOR),
    "admin_appeal_headers": build_user_headers(ADMIN_APPEAL_ID, COOP_ADMINISTRATOR),
    "officer_conductor_headers": build_user_headers(OFFICER_CONDUCTOR_ID, LEAD_AGENCY_OFFICER),
    "officer_awarder_headers": build_user_headers(OFFICER_AWARDER_ID, LEAD_AGENCY_OFFICER),
    "auditor_headers": build_user_headers(AUDITOR_ID, MEMBER_AUDITOR),
}

ADMIN_INTAKE = TEST_USERS["admin_intake_headers"]
ADMIN_REVIEW = TEST_USERS["admin_review_headers"]
ADMIN_INVESTIGATOR = TEST_USERS["admin_investigator_headers"]
ADMIN_ADJUDICATOR = TEST_USERS["admin_adjudicator_headers"]
ADMIN_PIGGYBACK = TEST_USERS["admin_piggyback_headers"]
ADMIN_APPEAL = TEST_USERS["admin_appeal_headers"]
OFFICER_CONDUCTOR = TEST_USERS["officer_conductor_headers"]
OFFICER_AWARDER = TEST_USERS["officer_awarder_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def make_supplier_headers(supplier_id: str) -> dict:
    """Headers for a supplier representative acting for the supplier row itself."""
    return build_user_headers(supplier_id, SUPPLIER_REPRESENTATIVE)


def make_member_headers(member_agency_id: str) -> dict:
    """Headers for a member representative acting for the member agency row itself."""
    return build_user_headers(member_agency_id, MEMBER_REPRESENTATIVE)


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, COOP_ADMINISTRATOR)


def make_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, LEAD_AGENCY_OFFICER)


def make_auditor_headers(user_id: str = AUDITOR_ID) -> dict:
    return build_user_headers(user_id, MEMBER_AUDITOR)
