"""Pre-built role headers for every role the PRD declares (PRD §2.1)."""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ADMIN_USER_ID,
    ADMIN_USER_ID_ALT,
    APPRAISER_USER_ID,
    APPRAISER_USER_ID_ALT,
    MONITOR_USER_ID,
    OFFICER_USER_ID,
    OFFICER_USER_ID_ALT,
    REVIEWER_USER_ID,
)

# Shared constants.
#
# For the five roles whose X-User-ID is an opaque operator identifier not tied
# to any persisted entity, these are the canonical form. For Landowner — whose
# X-User-ID is the id of the acting Landowner record — the shared constant is a
# fallback usable ONLY by tests that never reach an ownership check (missing
# header, unknown role, forbidden role, unknown path id).
TEST_USERS = {
    "program_admin_headers": build_user_headers(ADMIN_USER_ID, "ProgramAdmin"),
    "program_admin_alt_headers": build_user_headers(ADMIN_USER_ID_ALT, "ProgramAdmin"),
    "acquisition_officer_headers": build_user_headers(
        OFFICER_USER_ID, "AcquisitionOfficer"
    ),
    "acquisition_officer_alt_headers": build_user_headers(
        OFFICER_USER_ID_ALT, "AcquisitionOfficer"
    ),
    "appraisal_reviewer_headers": build_user_headers(REVIEWER_USER_ID, "AppraisalReviewer"),
    "appraiser_headers": build_user_headers(APPRAISER_USER_ID, "Appraiser"),
    "appraiser_alt_headers": build_user_headers(APPRAISER_USER_ID_ALT, "Appraiser"),
    "stewardship_monitor_headers": build_user_headers(
        MONITOR_USER_ID, "StewardshipMonitor"
    ),
    "landowner_headers": build_user_headers("landowner-unbound", "Landowner"),
}


def make_landowner_headers(user_id: str) -> dict:
    """Headers for the Landowner role.

    Pass the actual Landowner record's `id`: when `X-User-Role` is `Landowner`,
    `X-User-ID` is the id of the acting `Landowner` record and every ownership
    check compares a resource's landowner foreign key against it.
    """
    return build_user_headers(user_id, "Landowner")


def make_program_admin_headers(user_id: str) -> dict:
    """Headers for the ProgramAdmin role with a caller-chosen operator id."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_acquisition_officer_headers(user_id: str) -> dict:
    """Headers for the AcquisitionOfficer role with a caller-chosen operator id."""
    return build_user_headers(user_id, "AcquisitionOfficer")


def make_appraisal_reviewer_headers(user_id: str) -> dict:
    """Headers for the AppraisalReviewer role with a caller-chosen operator id."""
    return build_user_headers(user_id, "AppraisalReviewer")


def make_appraiser_headers(user_id: str) -> dict:
    """Headers for the Appraiser role.

    Pass the `appraiser_user_id` nominated on the appraisal at engagement: an
    appraisal submission requires `X-User-ID` to equal it.
    """
    return build_user_headers(user_id, "Appraiser")


def make_stewardship_monitor_headers(user_id: str) -> dict:
    """Headers for the StewardshipMonitor role with a caller-chosen operator id."""
    return build_user_headers(user_id, "StewardshipMonitor")


ROLE_HEADER_BUILDERS = {
    "ProgramAdmin": make_program_admin_headers,
    "Landowner": make_landowner_headers,
    "AcquisitionOfficer": make_acquisition_officer_headers,
    "AppraisalReviewer": make_appraisal_reviewer_headers,
    "Appraiser": make_appraiser_headers,
    "StewardshipMonitor": make_stewardship_monitor_headers,
}

ALL_ROLE_NAMES = (
    "ProgramAdmin",
    "Landowner",
    "AcquisitionOfficer",
    "AppraisalReviewer",
    "Appraiser",
    "StewardshipMonitor",
)
