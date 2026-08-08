"""Pre-built role headers for the seven departmental roles."""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Applicant, DesignProfessional, EnvironmentalHealthSpecialist,
# HealthOfficer and RecordsClerk all carry opaque operator identifiers, so these
# constants are the canonical form for those roles. Installer and Pumper identify
# the acting Contractor row, so their shared constants are only safe for calls
# that never resolve X-User-ID against a Contractor (authorization-only checks).
TEST_USERS = {
    "applicant_headers": build_user_headers("u-app-1", "Applicant"),
    "other_applicant_headers": build_user_headers("u-app-2", "Applicant"),
    "design_professional_headers": build_user_headers("u-dp-1", "DesignProfessional"),
    "other_design_professional_headers": build_user_headers(
        "u-dp-2", "DesignProfessional"
    ),
    "installer_headers": build_user_headers("u-installer-1", "Installer"),
    "pumper_headers": build_user_headers("u-pumper-1", "Pumper"),
    "ehs_reviewer_headers": build_user_headers(
        "u-ehs-review", "EnvironmentalHealthSpecialist"
    ),
    "ehs_field_headers": build_user_headers(
        "u-ehs-field", "EnvironmentalHealthSpecialist"
    ),
    "health_officer_headers": build_user_headers("u-ho-1", "HealthOfficer"),
    "records_clerk_headers": build_user_headers("u-rc-1", "RecordsClerk"),
}

# Convenient aliases for the identifiers the shared headers carry.
APPLICANT_USER_ID = "u-app-1"
OTHER_APPLICANT_USER_ID = "u-app-2"
DESIGN_PROFESSIONAL_USER_ID = "u-dp-1"
OTHER_DESIGN_PROFESSIONAL_USER_ID = "u-dp-2"
EHS_REVIEWER_USER_ID = "u-ehs-review"
EHS_FIELD_USER_ID = "u-ehs-field"
HEALTH_OFFICER_USER_ID = "u-ho-1"
RECORDS_CLERK_USER_ID = "u-rc-1"

# Headers with neither identity header present, for the authentication check.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_applicant_headers(user_id: str) -> dict:
    """Applicant headers for an arbitrary opaque operator identifier."""
    return build_user_headers(user_id, "Applicant")


def make_design_professional_headers(user_id: str) -> dict:
    """DesignProfessional headers for an arbitrary opaque operator identifier."""
    return build_user_headers(user_id, "DesignProfessional")


def make_ehs_headers(user_id: str) -> dict:
    """EnvironmentalHealthSpecialist headers for an arbitrary operator identifier."""
    return build_user_headers(user_id, "EnvironmentalHealthSpecialist")


def make_health_officer_headers(user_id: str) -> dict:
    """HealthOfficer headers for an arbitrary opaque operator identifier."""
    return build_user_headers(user_id, "HealthOfficer")


def make_records_clerk_headers(user_id: str) -> dict:
    """RecordsClerk headers for an arbitrary opaque operator identifier."""
    return build_user_headers(user_id, "RecordsClerk")


def make_installer_headers(contractor_id: str) -> dict:
    """Installer headers. Pass the acting Contractor row's id as X-User-ID."""
    return build_user_headers(contractor_id, "Installer")


def make_pumper_headers(contractor_id: str) -> dict:
    """Pumper headers. Pass the acting Contractor row's id as X-User-ID."""
    return build_user_headers(contractor_id, "Pumper")
