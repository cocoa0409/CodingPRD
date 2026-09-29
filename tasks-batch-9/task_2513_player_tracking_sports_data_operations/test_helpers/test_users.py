"""
Header builders for the six roles.

Four roles carry opaque identities (PRD 2.1): their X-User-ID is never resolved
against a stored row, so a fixed literal per role is enough and the identifiers
matter only to the segregation-of-duties comparisons. The two entity-backed
roles must present the id of a live Club or DataLicensee row, so they get
per-instance builders instead of a shared constant.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CALIBRATION_ENGINEER,
    ROLE_CLUB_DATA_OFFICER,
    ROLE_LEAGUE_DATA_OPS,
    ROLE_LICENSEE,
    ROLE_QUALITY_REVIEWER,
    ROLE_STATISTICIAN,
)

# Opaque operator identifiers.
OPS_PRIMARY = "ops-01"
OPS_SECONDARY = "ops-02"
ENGINEER_PRIMARY = "eng-01"
ENGINEER_SECONDARY = "eng-02"
STATISTICIAN_PRIMARY = "stat-01"
STATISTICIAN_SECONDARY = "stat-02"
REVIEWER_PRIMARY = "qr-01"
REVIEWER_SECONDARY = "qr-02"
# Correction reviewers are sometimes named on the quality-assurance desk.
REVIEWER_QA = "qa-01"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "league_data_ops": build_user_headers(OPS_PRIMARY, ROLE_LEAGUE_DATA_OPS),
    "league_data_ops_alt": build_user_headers(OPS_SECONDARY, ROLE_LEAGUE_DATA_OPS),
    "calibration_engineer": build_user_headers(ENGINEER_PRIMARY, ROLE_CALIBRATION_ENGINEER),
    "calibration_engineer_alt": build_user_headers(ENGINEER_SECONDARY, ROLE_CALIBRATION_ENGINEER),
    "statistician": build_user_headers(STATISTICIAN_PRIMARY, ROLE_STATISTICIAN),
    "statistician_alt": build_user_headers(STATISTICIAN_SECONDARY, ROLE_STATISTICIAN),
    "quality_reviewer": build_user_headers(REVIEWER_PRIMARY, ROLE_QUALITY_REVIEWER),
    "quality_reviewer_alt": build_user_headers(REVIEWER_SECONDARY, ROLE_QUALITY_REVIEWER),
    "quality_reviewer_qa": build_user_headers(REVIEWER_QA, ROLE_QUALITY_REVIEWER),
}

OPS_HEADERS = TEST_USERS["league_data_ops"]
OPS_ALT_HEADERS = TEST_USERS["league_data_ops_alt"]
ENGINEER_HEADERS = TEST_USERS["calibration_engineer"]
ENGINEER_ALT_HEADERS = TEST_USERS["calibration_engineer_alt"]
STATISTICIAN_HEADERS = TEST_USERS["statistician"]
STATISTICIAN_ALT_HEADERS = TEST_USERS["statistician_alt"]
REVIEWER_HEADERS = TEST_USERS["quality_reviewer"]
REVIEWER_ALT_HEADERS = TEST_USERS["quality_reviewer_alt"]
REVIEWER_QA_HEADERS = TEST_USERS["quality_reviewer_qa"]


def make_club_data_officer_headers(club_id: str) -> Dict[str, str]:
    """A ClubDataOfficer acts as the club whose id it presents in X-User-ID."""
    return build_user_headers(club_id, ROLE_CLUB_DATA_OFFICER)


def make_licensee_headers(licensee_id: str) -> Dict[str, str]:
    """A Licensee acts as the DataLicensee whose id it presents in X-User-ID."""
    return build_user_headers(licensee_id, ROLE_LICENSEE)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Escape hatch for tests that need an arbitrary identifier/role pairing."""
    return build_user_headers(user_id, role)


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers that omit X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers that omit X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
