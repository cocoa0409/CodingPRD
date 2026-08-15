"""Pre-built role headers for every role in PRD §2.1.

Staff roles (AdmissionDirector / AdmissionOfficer / FinancialAidOfficer) carry an
opaque X-User-ID never compared to any entity id. The Parent role is
family-scoped: X-User-ID IS the family identifier, so ownership-gated calls
(submit / decline / withdraw / aid actions / sign / pay / respond) MUST use
make_parent_headers(family_id) with the owning family's family_id. The shared
parent constant is a fallback only for negative RBAC probes.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "director_headers": build_user_headers("dir-1", "AdmissionDirector"),
    "officer_headers": build_user_headers("off-1", "AdmissionOfficer"),
    # Two distinct aid officers so segregation-of-duties flows can verify with
    # one user and finalize/revise with another (PRD §2.1, §3.4).
    "fao_1_headers": build_user_headers("fao-1", "FinancialAidOfficer"),
    "fao_2_headers": build_user_headers("fao-2", "FinancialAidOfficer"),
    # Family-scoped fallback — matches no created family; negative probes only.
    "parent_headers": build_user_headers("fam-orphan-1", "Parent"),
}

# A request carrying neither auth header (PRD §2.1 first pipeline layer).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_director_headers(user_id: str = "dir-1") -> dict:
    return build_user_headers(user_id, "AdmissionDirector")


def make_officer_headers(user_id: str = "off-1") -> dict:
    return build_user_headers(user_id, "AdmissionOfficer")


def make_fao_headers(user_id: str) -> dict:
    """FinancialAidOfficer identity is recorded as verified_by_user_id on
    verification and drives the segregation-of-duties checks (PRD §3.4)."""
    return build_user_headers(user_id, "FinancialAidOfficer")


def make_parent_headers(family_id: str) -> dict:
    """Parent X-User-ID IS the family account identifier (PRD §2.1). Pass the
    owning family's family_id whenever the call is ownership-gated."""
    return build_user_headers(family_id, "Parent")
