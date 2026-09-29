"""Role headers for the six recognized roles (PRD 2.1).

Two of the six roles are entity-backed: "When X-User-Role is
ProducerRepresentative, X-User-ID is the id of the acting CertificateHolder ...
The same rule applies when X-User-Role is BrandLicensee". Those two therefore
have no fixed constant - their headers must be built from the real holder id
returned by registration, which is what
``make_producer_representative_headers`` and ``make_brand_licensee_headers``
are for. The other four roles carry opaque operator identifiers that are never
compared against any entity's ``id``.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# ---------------------------------------------------------------------------
# Opaque-identifier roles: fixed constants are safe here.
# ---------------------------------------------------------------------------

OFFICER_1_ID = "officer-1"
OFFICER_2_ID = "officer-2"
OFFICER_7_ID = "officer-7"
AUDITOR_1_ID = "auditor-1"
AUDITOR_2_ID = "auditor-2"
AUDITOR_3_ID = "auditor-3"
CHAIR_1_ID = "chair-1"
CHAIR_2_ID = "chair-2"
MEMBER_1_ID = "member-1"
MEMBER_2_ID = "member-2"
MEMBER_3_ID = "member-3"
MEMBER_4_ID = "member-4"
MEMBER_5_ID = "member-5"

OFFICER = build_user_headers(OFFICER_1_ID, "CertificationOfficer")
OFFICER_2 = build_user_headers(OFFICER_2_ID, "CertificationOfficer")
OFFICER_7 = build_user_headers(OFFICER_7_ID, "CertificationOfficer")
AUDITOR = build_user_headers(AUDITOR_1_ID, "Auditor")
AUDITOR_2 = build_user_headers(AUDITOR_2_ID, "Auditor")
AUDITOR_3 = build_user_headers(AUDITOR_3_ID, "Auditor")
CHAIR = build_user_headers(CHAIR_1_ID, "CommitteeChair")
CHAIR_2 = build_user_headers(CHAIR_2_ID, "CommitteeChair")
MEMBER_1 = build_user_headers(MEMBER_1_ID, "CommitteeMember")
MEMBER_2 = build_user_headers(MEMBER_2_ID, "CommitteeMember")
MEMBER_3 = build_user_headers(MEMBER_3_ID, "CommitteeMember")
MEMBER_4 = build_user_headers(MEMBER_4_ID, "CommitteeMember")
MEMBER_5 = build_user_headers(MEMBER_5_ID, "CommitteeMember")

MEMBERS = (MEMBER_1, MEMBER_2, MEMBER_3, MEMBER_4, MEMBER_5)
MEMBER_IDS = (MEMBER_1_ID, MEMBER_2_ID, MEMBER_3_ID, MEMBER_4_ID, MEMBER_5_ID)


# ---------------------------------------------------------------------------
# Entity-backed roles: always built from a real CertificateHolder id.
# ---------------------------------------------------------------------------


def make_producer_representative_headers(holder_id: str) -> Dict[str, str]:
    """Headers for the representative acting on behalf of ``holder_id``."""
    return build_user_headers(holder_id, "ProducerRepresentative")


def make_brand_licensee_headers(holder_id: str) -> Dict[str, str]:
    """Headers for the licensee acting on behalf of the brand ``holder_id``."""
    return build_user_headers(holder_id, "BrandLicensee")


def make_officer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "CertificationOfficer")


def make_auditor_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "Auditor")


def make_chair_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "CommitteeChair")


def make_member_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "CommitteeMember")


# ---------------------------------------------------------------------------
# Malformed header sets (PRD 2.1: "If either header is absent or empty, or if
# X-User-Role is not one of the six roles enumerated below").
# ---------------------------------------------------------------------------

NO_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
MISSING_ROLE_HEADER = {"X-User-ID": OFFICER_1_ID, "Content-Type": "application/json"}
MISSING_USER_ID_HEADER = {
    "X-User-Role": "CertificationOfficer",
    "Content-Type": "application/json",
}
EMPTY_ROLE_HEADER = {
    "X-User-ID": OFFICER_1_ID,
    "X-User-Role": "",
    "Content-Type": "application/json",
}
EMPTY_USER_ID_HEADER = {
    "X-User-ID": "",
    "X-User-Role": "CertificationOfficer",
    "Content-Type": "application/json",
}
UNKNOWN_ROLE_HEADER = build_user_headers(OFFICER_1_ID, "FarmInspector")
