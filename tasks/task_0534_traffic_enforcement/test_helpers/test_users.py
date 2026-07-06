"""Pre-built role headers for every role in the PRD (Section 2.1).

Five roles carry an opaque identity (SystemAdmin, ProgramAdmin, ReviewOfficer,
Adjudicator, Auditor): X-User-ID is an operator identifier not tied to any entity.
RegisteredOwner is entity-backed: owner-portal calls authenticate by
registered_owner_id + portal_access_pin in the body, and the acting owner is the
RegisteredOwner whose id is supplied — so owner headers must carry the real owner id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque roles use these as the canonical form. The
# ReviewOfficer default id "ro-1" matches the review_officer_ref used in the
# design-index recipes so segregation-of-duties setups line up.
TEST_USERS = {
    "system_admin_headers": build_user_headers("sys-1", "SystemAdmin"),
    "program_admin_headers": build_user_headers("pa-1", "ProgramAdmin"),
    "review_officer_headers": build_user_headers("ro-1", "ReviewOfficer"),
    "adjudicator_headers": build_user_headers("adj-9", "Adjudicator"),
    "auditor_headers": build_user_headers("aud-1", "Auditor"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "registered_owner_headers": build_user_headers("owner-placeholder", "RegisteredOwner"),
}


def make_review_officer_headers(user_id: str) -> dict:
    """ReviewOfficer with a specific X-User-ID (recorded as review_officer_ref)."""
    return build_user_headers(user_id, "ReviewOfficer")


def make_adjudicator_headers(user_id: str) -> dict:
    """Adjudicator with a specific X-User-ID (segregation of duties: must differ
    from the citation's review_officer_ref)."""
    return build_user_headers(user_id, "Adjudicator")


def make_registered_owner_headers(owner_id: str) -> dict:
    """For RegisteredOwner (entity_backed). Pass the actual RegisteredOwner.id as
    X-User-ID for owner-portal / owner-payment calls."""
    return build_user_headers(owner_id, "RegisteredOwner")
