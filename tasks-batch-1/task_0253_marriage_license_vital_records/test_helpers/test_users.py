"""Pre-built role headers for every role in the PRD (§2.1).

Two roles are entity-backed (Applicant, Officiant): X-User-ID must be the id of
the persisted entity for ownership checks to pass — use the make_* builders.

Three roles are opaque operator identities (Clerk, Registrar, WaiverOfficer):
X-User-ID is a free-form operator id that the server records (approved_by_user_id,
accepted_by_user_id, adjudicated_by_user_id, issued_by_user_id) and compares only
against other recorded operator ids for segregation-of-duties.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# entity ownership (e.g. 400-on-bad-payload, 404-on-missing-resource, 403-on-role).
TEST_USERS = {
    # Opaque operator identities — distinct ids so segregation-of-duties separations
    # can be expressed by choosing which operator acts.
    "clerk_headers": build_user_headers("clerk-1", "Clerk"),
    "clerk2_headers": build_user_headers("clerk-2", "Clerk"),
    "registrar_headers": build_user_headers("registrar-1", "Registrar"),
    "registrar2_headers": build_user_headers("registrar-2", "Registrar"),
    "waiver_officer_headers": build_user_headers("wo-1", "WaiverOfficer"),
    # Entity-backed roles — shared constant is a fallback ONLY for non-ownership
    # tests (403/401 role checks); ownership-gated calls MUST use the builders below.
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
    "officiant_headers": build_user_headers("test-officiant-1", "Officiant"),
}


# ---------------------------------------------------------------------------
# Opaque-role builders — pick a specific operator identity (matters for
# segregation-of-duties tests, where two duties must be performed by different ids).
# ---------------------------------------------------------------------------
def make_clerk_headers(user_id: str) -> dict:
    """Clerk (opaque). user_id is the operator id recorded as approved_by_user_id /
    issued_by_user_id."""
    return build_user_headers(user_id, "Clerk")


def make_registrar_headers(user_id: str) -> dict:
    """Registrar (opaque). user_id is the operator id recorded as accepted_by_user_id /
    adjudicated_by_user_id."""
    return build_user_headers(user_id, "Registrar")


def make_waiver_officer_headers(user_id: str) -> dict:
    """WaiverOfficer (opaque). user_id is the operator id recorded as
    adjudicated_by_user_id on a fee waiver."""
    return build_user_headers(user_id, "WaiverOfficer")


# ---------------------------------------------------------------------------
# Entity-backed builders — MUST be called with the actual entity id when a call
# is ownership-gated (e.g. an Applicant acting on their own application, an
# Officiant filing their own return).
# ---------------------------------------------------------------------------
def make_applicant_headers(applicant_id: str) -> dict:
    """Applicant (entity_backed:Applicant). Pass the actual Applicant.id whenever
    the call is ownership-gated (submit, resubmit, create copy/amendment/apostille/waiver)."""
    return build_user_headers(applicant_id, "Applicant")


def make_officiant_headers(officiant_id: str) -> dict:
    """Officiant (entity_backed:Officiant). Pass the actual Officiant.id whenever
    the call is ownership-gated (file/read own returns)."""
    return build_user_headers(officiant_id, "Officiant")
