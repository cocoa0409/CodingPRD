"""Pre-built role headers for every role in the PRD (§2.1).

All seven roles use the opaque identity model: X-User-ID is never resolved
against an entity primary key, but it IS recorded and compared for ownership
and segregation-of-duties checks (PRD §2.1, §2.8). Use make_<role>_headers(user_id)
whenever a test or fixture needs a specific operator id (e.g. the run submitter
vs. the certifier, or the abstraction author vs. the over-reader).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe whenever the exact operator id does not matter.
TEST_USERS = {
    "quality_admin_headers": build_user_headers("test-admin-1", "QualityAdmin"),
    "quality_analyst_headers": build_user_headers("test-analyst-1", "QualityAnalyst"),
    "abstractor_headers": build_user_headers("test-abstractor-1", "Abstractor"),
    "overreader_headers": build_user_headers("test-overreader-1", "OverReader"),
    "provider_relations_headers": build_user_headers("test-pr-1", "ProviderRelations"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    "quality_director_headers": build_user_headers("test-director-1", "QualityDirector"),
}


def make_quality_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualityAdmin")


def make_quality_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualityAnalyst")


def make_abstractor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Abstractor")


def make_overreader_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OverReader")


def make_provider_relations_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProviderRelations")


def make_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Auditor")


def make_quality_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualityDirector")
