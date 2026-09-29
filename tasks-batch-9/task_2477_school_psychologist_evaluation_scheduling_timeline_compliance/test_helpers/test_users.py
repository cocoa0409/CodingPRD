"""Pre-built role headers for every role in the requirements.

Every request carries `X-User-ID` and `X-User-Role`. For a `SchoolPsychologist`
the `X-User-ID` is the `id` of the acting `Psychologist` record, so any call made
in that capacity against an ownership-gated operation must use the per-instance
builder with a real psychologist id. The other four roles carry an opaque
operator identifier that is never compared against an entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "intake_coordinator_headers": build_user_headers(
        "intake-coordinator-1", "IntakeCoordinator"
    ),
    "psych_services_supervisor_headers": build_user_headers(
        "supervisor-1", "PsychServicesSupervisor"
    ),
    "compliance_officer_headers": build_user_headers(
        "compliance-officer-1", "ComplianceOfficer"
    ),
    "district_admin_headers": build_user_headers("district-admin-1", "DistrictAdmin"),
    # SchoolPsychologist: the shared constant is a non-ownership fallback only —
    # it does not resolve to any psychologist record.
    "school_psychologist_headers": build_user_headers(
        "school-psychologist-1", "SchoolPsychologist"
    ),
}


def make_intake_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IntakeCoordinator")


def make_psych_services_supervisor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PsychServicesSupervisor")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_district_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DistrictAdmin")


def make_school_psychologist_headers(psychologist_id: str) -> dict:
    """Headers for a `SchoolPsychologist` acting as a specific psychologist.

    Pass the real `Psychologist.id`: ownership checks compare the addressed
    resource's psychologist reference against this `X-User-ID`.
    """
    return build_user_headers(psychologist_id, "SchoolPsychologist")


ROLE_HEADER_BUILDERS = {
    "IntakeCoordinator": make_intake_coordinator_headers,
    "SchoolPsychologist": make_school_psychologist_headers,
    "PsychServicesSupervisor": make_psych_services_supervisor_headers,
    "ComplianceOfficer": make_compliance_officer_headers,
    "DistrictAdmin": make_district_admin_headers,
}
