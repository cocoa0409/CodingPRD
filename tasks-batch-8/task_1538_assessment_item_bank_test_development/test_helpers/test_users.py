"""Pre-built role headers for every role in the PRD.

All eight roles use opaque operator identities: per the PRD's access-control
section, `X-User-ID` is not tied to the `id` of any persisted entity.
Ownership-style checks (item author, verdict reviewer) compare the recorded
field against the caller's `X-User-ID` string, so tests that exercise
ownership or segregation-of-duties must thread a consistent user id via the
`make_*_headers(user_id)` builders.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for opaque roles. Safe for any test that does
# not depend on a specific user identity (author checks, SOD pairs).
TEST_USERS = {
    "program_director_headers": build_user_headers("test-director-1", "ProgramDirector"),
    "item_writer_headers": build_user_headers("test-writer-1", "ItemWriter"),
    "content_reviewer_headers": build_user_headers("test-cr-1", "ContentReviewer"),
    "bias_reviewer_headers": build_user_headers("test-br-1", "BiasSensitivityReviewer"),
    "psychometrician_headers": build_user_headers("test-psych-1", "Psychometrician"),
    "test_assembler_headers": build_user_headers("test-assembler-1", "TestAssembler"),
    "security_officer_headers": build_user_headers("test-officer-1", "SecurityOfficer"),
    "translation_specialist_headers": build_user_headers("test-translator-1", "TranslationSpecialist"),
}


def make_program_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramDirector")


def make_item_writer_headers(user_id: str) -> dict:
    """Item author identity: submit/discard/update compare X-User-ID against
    the item's recorded author_user_id, so pass the same user id used at
    creation."""
    return build_user_headers(user_id, "ItemWriter")


def make_content_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ContentReviewer")


def make_bias_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BiasSensitivityReviewer")


def make_psychometrician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Psychometrician")


def make_test_assembler_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TestAssembler")


def make_security_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SecurityOfficer")


def make_translation_specialist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TranslationSpecialist")
