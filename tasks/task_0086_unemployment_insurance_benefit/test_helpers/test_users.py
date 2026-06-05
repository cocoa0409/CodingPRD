"""Pre-built role headers for every role in the PRD.

Opaque operator roles (ProgramAdmin, Adjudicator, BenefitPaymentOfficer,
AppealsClerk, Referee) use a shared constant header — their X-User-ID is never
compared to any entity id. Anonymous is likewise opaque.

Claimant and Employer are entity-backed: their X-User-ID must equal the acting
entity's id for ownership-gated calls, so use the per-instance builders below
(make_claimant_headers / make_employer_headers) once the entity exists.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operator roles — shared constant is the canonical form.
    "program_admin_headers": build_user_headers("op-program-admin-1", "ProgramAdmin"),
    "adjudicator_headers": build_user_headers("op-adjudicator-1", "Adjudicator"),
    "benefit_payment_officer_headers": build_user_headers("op-bpo-1", "BenefitPaymentOfficer"),
    "appeals_clerk_headers": build_user_headers("op-appeals-clerk-1", "AppealsClerk"),
    "referee_headers": build_user_headers("op-referee-1", "Referee"),
    "anonymous_headers": build_user_headers("anon-public-1", "Anonymous"),
    # Entity-backed roles — shared constant is a fallback for non-ownership tests
    # only (e.g. 400-on-bad-payload, 403 forbidden-role checks where ownership is
    # not the gate). Ownership-gated calls MUST use the builders below.
    "claimant_headers": build_user_headers("entity-backed-claimant-fallback", "Claimant"),
    "employer_headers": build_user_headers("entity-backed-employer-fallback", "Employer"),
}


def make_claimant_headers(claimant_id: str) -> dict:
    """For Claimant (entity_backed:Claimant). Pass the actual Claimant.id as the
    X-User-ID whenever the call is ownership-gated (file/submit claim, certify a
    week, log a work-search contact, file/withdraw an appeal, read own resources)."""
    return build_user_headers(claimant_id, "Claimant")


def make_employer_headers(employer_id: str) -> dict:
    """For Employer (entity_backed:Employer). Pass the actual Employer.id as the
    X-User-ID whenever the call is ownership-gated (protest a charge the employer
    owns)."""
    return build_user_headers(employer_id, "Employer")


def make_adjudicator_headers(user_id: str) -> dict:
    """Adjudicator with an explicit operator id — used to pin issuing_adjudicator_id
    for segregation-of-duties scenarios."""
    return build_user_headers(user_id, "Adjudicator")


def make_appeals_clerk_headers(user_id: str = "op-appeals-clerk-1") -> dict:
    return build_user_headers(user_id, "AppealsClerk")
