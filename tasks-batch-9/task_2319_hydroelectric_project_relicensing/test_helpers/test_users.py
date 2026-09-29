"""Pre-built request headers for every role the PRD defines.

`Licensee`, `StateCertifier` and `Regulator` identities are opaque: the header
value only has to name a known user. `AgencyReviewer` and `Stakeholder`
identities resolve to a registered settlement party through the party's
`contact_user_id`, so those callers must always use the same user id that was
handed to `POST /relicensing/parties`.
"""
from prd_bench_local_runner.testing import build_user_headers

# ---- canonical user ids ----------------------------------------------------
U_REGULATOR = "u_reg_1"
U_LICENSEE_A = "u_lic_a"
U_LICENSEE_B = "u_lic_b"
U_LICENSEE_REPORT = "u_lic_report"
U_LICENSEE_CERT = "u_lic_cert"
U_AGENCY = "u_agency"
U_AGENCY_B = "u_agency_b"
U_TRIBE = "u_tribe"
U_NGO = "u_ngo"
U_NGO_2 = "u_ngo2"
U_STATE_CERTIFIER = "u_state_1"

TEST_USERS = {
    "regulator_headers": build_user_headers(U_REGULATOR, "Regulator"),
    "licensee_headers": build_user_headers(U_LICENSEE_A, "Licensee"),
    "licensee_b_headers": build_user_headers(U_LICENSEE_B, "Licensee"),
    "licensee_reporter_headers": build_user_headers(U_LICENSEE_REPORT, "Licensee"),
    "licensee_certifier_headers": build_user_headers(U_LICENSEE_CERT, "Licensee"),
    "state_certifier_headers": build_user_headers(U_STATE_CERTIFIER, "StateCertifier"),
    # Party-backed roles: these shared constants are only safe once a party with
    # the matching contact_user_id has been registered on the project.
    "agency_reviewer_headers": build_user_headers(U_AGENCY, "AgencyReviewer"),
    "stakeholder_headers": build_user_headers(U_TRIBE, "Stakeholder"),
}


def make_licensee_headers(user_id: str) -> dict:
    """Headers for a `Licensee` staff user id (segregation-of-duties tests)."""
    return build_user_headers(user_id, "Licensee")


def make_agency_reviewer_headers(user_id: str) -> dict:
    """Headers for an `AgencyReviewer`.

    Pass the exact `contact_user_id` recorded on the AGENCY party of the project
    being acted on; any other value is either unauthorized or not permitted.
    """
    return build_user_headers(user_id, "AgencyReviewer")


def make_stakeholder_headers(user_id: str) -> dict:
    """Headers for a `Stakeholder`.

    Pass the exact `contact_user_id` recorded on the TRIBE or NGO party of the
    project being acted on.
    """
    return build_user_headers(user_id, "Stakeholder")


def make_state_certifier_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "StateCertifier")


def make_regulator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Regulator")


def headers_without_user_id(role: str = "Licensee") -> dict:
    """A request that carries no `X-User-ID` header at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
