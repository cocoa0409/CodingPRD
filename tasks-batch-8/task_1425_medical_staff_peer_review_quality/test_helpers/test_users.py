"""Pre-built role headers for every role in the PRD (§2.1).

QualityDirector and PeerReviewCoordinator are opaque identities: the server
never compares their X-User-ID to any entity id, so the shared constants are
canonical. CommitteeMember and Provider are entity-backed: X-User-ID must equal
the acting CommitteeMember / Provider record's id on every ownership-gated
call, so those calls MUST use the per-instance builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: canonical shared form.
    "quality_director_headers": build_user_headers("qd-operator-1", "QualityDirector"),
    "peer_review_coordinator_headers": build_user_headers("prc-operator-1", "PeerReviewCoordinator"),
    # Entity-backed roles: fallback constants only for tests that do not
    # exercise ownership (e.g. role-list denials, 404s, 400s).
    "committee_member_headers": build_user_headers("member-fallback-1", "CommitteeMember"),
    "provider_headers": build_user_headers("provider-fallback-1", "Provider"),
}


def make_quality_director_headers(user_id: str = "qd-operator-1") -> dict:
    """QualityDirector is opaque; any X-User-ID works."""
    return build_user_headers(user_id, "QualityDirector")


def make_peer_review_coordinator_headers(user_id: str = "prc-operator-1") -> dict:
    """PeerReviewCoordinator is opaque; any X-User-ID works."""
    return build_user_headers(user_id, "PeerReviewCoordinator")


def make_committee_member_headers(member_id: str) -> dict:
    """CommitteeMember is entity-backed: pass the CommitteeMember.id whenever
    the call is ownership-gated (conflict declare/rescind, submit, revise,
    notes, chair actions)."""
    return build_user_headers(member_id, "CommitteeMember")


def make_provider_headers(provider_id: str) -> dict:
    """Provider is entity-backed: pass the Provider.id whenever the call is
    ownership-gated (own cases, notifications, responses)."""
    return build_user_headers(provider_id, "Provider")
