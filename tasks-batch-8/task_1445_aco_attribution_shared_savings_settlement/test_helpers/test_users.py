"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles carry an operator identifier in X-User-ID. The
ParticipantRepresentative role is entity-backed: its X-User-ID must be the id
of the acting Participant, so ownership-gated calls MUST be made through
make_participant_representative_headers(participant["id"]) — never through a
shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Stable operator ids referenced throughout the suite.
ADMIN_USER = "aa-1"
CLAIMS_USER = "cp-1"
QUALITY_REPORTER_1 = "qr-1"
QUALITY_REPORTER_2 = "qr-2"
QUALITY_AUDITOR_1 = "qa-1"
SETTLEMENT_ACTUARY_1 = "sa-1"
DISTRIBUTION_APPROVER_1 = "da-1"
MEDICAL_REVIEW_OFFICER_1 = "mr-1"
APPEALS_OFFICER_1 = "ao-1"
PLATFORM_ADMIN_USER = "padm-1"

# Shared constants — safe for opaque roles and for tests that do not exercise
# entity-backed ownership.
TEST_USERS = {
    "admin_headers": build_user_headers(ADMIN_USER, "AcoAdministrator"),
    "claims_headers": build_user_headers(CLAIMS_USER, "ClaimsProcessor"),
    "quality_reporter_headers": build_user_headers(QUALITY_REPORTER_1, "QualityReporter"),
    "quality_auditor_headers": build_user_headers(QUALITY_AUDITOR_1, "QualityAuditor"),
    "actuary_headers": build_user_headers(SETTLEMENT_ACTUARY_1, "SettlementActuary"),
    "approver_headers": build_user_headers(DISTRIBUTION_APPROVER_1, "DistributionApprover"),
    "review_officer_headers": build_user_headers(MEDICAL_REVIEW_OFFICER_1, "MedicalReviewOfficer"),
    "appeals_officer_headers": build_user_headers(APPEALS_OFFICER_1, "AppealsOfficer"),
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_USER, "PlatformAdmin"),
}


def make_admin_headers(user_id: str = ADMIN_USER) -> dict:
    return build_user_headers(user_id, "AcoAdministrator")


def make_claims_processor_headers(user_id: str = CLAIMS_USER) -> dict:
    return build_user_headers(user_id, "ClaimsProcessor")


def make_quality_reporter_headers(user_id: str) -> dict:
    """QualityReporter with a specific operator id (segregation-of-duties anchor)."""
    return build_user_headers(user_id, "QualityReporter")


def make_quality_auditor_headers(user_id: str) -> dict:
    """QualityAuditor with a specific operator id (must differ from the reporter)."""
    return build_user_headers(user_id, "QualityAuditor")


def make_actuary_headers(user_id: str = SETTLEMENT_ACTUARY_1) -> dict:
    """SettlementActuary with a specific operator id (distribution-runner anchor)."""
    return build_user_headers(user_id, "SettlementActuary")


def make_approver_headers(user_id: str = DISTRIBUTION_APPROVER_1) -> dict:
    """DistributionApprover with a specific operator id (must differ from the runner)."""
    return build_user_headers(user_id, "DistributionApprover")


def make_review_officer_headers(user_id: str = MEDICAL_REVIEW_OFFICER_1) -> dict:
    return build_user_headers(user_id, "MedicalReviewOfficer")


def make_appeals_officer_headers(user_id: str = APPEALS_OFFICER_1) -> dict:
    return build_user_headers(user_id, "AppealsOfficer")


def make_participant_representative_headers(participant_id: str) -> dict:
    """ParticipantRepresentative is entity-backed: X-User-ID MUST be the acting
    Participant's id whenever the call is ownership-gated (appeals, rebuttals,
    narrowed reads)."""
    return build_user_headers(participant_id, "ParticipantRepresentative")


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_USER) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
