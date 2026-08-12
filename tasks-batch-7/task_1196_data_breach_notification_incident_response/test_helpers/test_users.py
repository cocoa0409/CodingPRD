"""Pre-built role headers for every role in the PRD (PRD §2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership. For the entity-backed AffectedSubjectRole, ALWAYS prefer
# make_affected_subject_headers(subject["id"]) for ownership-gated calls.
TEST_USERS = {
    "incident_commander_headers": build_user_headers(
        "test-ic-1", "IncidentCommander"
    ),
    "forensic_lead_headers": build_user_headers("test-fl-1", "ForensicLead"),
    "privacy_counsel_headers": build_user_headers("test-pc-1", "PrivacyCounsel"),
    "general_counsel_headers": build_user_headers("test-gc-1", "GeneralCounsel"),
    "data_analyst_headers": build_user_headers("test-da-1", "DataAnalyst"),
    "auditor_headers": build_user_headers("test-aud-1", "Auditor"),
    # Fallback for non-ownership tests only; never for redeem/decline.
    "affected_subject_headers": build_user_headers(
        "test-subj-fallback", "AffectedSubjectRole"
    ),
}


def make_incident_commander_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IncidentCommander")


def make_forensic_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ForensicLead")


def make_privacy_counsel_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PrivacyCounsel")


def make_general_counsel_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "GeneralCounsel")


def make_data_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DataAnalyst")


def make_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Auditor")


def make_affected_subject_headers(subject_id: str) -> dict:
    """AffectedSubjectRole is entity_backed on AffectedSubject — pass the
    subject's actual id so the server-side ownership check on
    CreditMonitoringOffer.affected_subject_id matches."""
    return build_user_headers(subject_id, "AffectedSubjectRole")
