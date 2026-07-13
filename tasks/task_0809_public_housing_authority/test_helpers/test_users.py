"""Pre-built role headers for every PHA role."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — the three staff roles are opaque, so a shared operator id is
# the canonical form. The Applicant shared constant is a fallback for tests that do
# NOT exercise ownership (e.g. non-owner denial where the acting id is deliberately
# a stranger); ownership-gated calls MUST use make_applicant_headers(applicant_id).
TEST_USERS = {
    "intake_clerk_headers": build_user_headers("op-intake-1", "IntakeClerk"),
    "housing_specialist_headers": build_user_headers("op-housing-1", "HousingSpecialist"),
    "property_manager_headers": build_user_headers("op-property-1", "PropertyManager"),
    "applicant_headers": build_user_headers("op-applicant-stranger", "Applicant"),
}


def make_applicant_headers(user_id: str) -> dict:
    """For the Applicant role (entity_backed:Applicant). Pass the actual Applicant.id
    as user_id whenever the call is ownership-gated (accept/refuse offer, report
    interim change, file grievance, read own resources)."""
    return build_user_headers(user_id, "Applicant")
