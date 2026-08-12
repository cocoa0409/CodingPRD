"""Pre-built role headers for every role in the PRD.

Entity-backed roles (BuilderRep -> Builder, HomeownerResident -> Resident,
OwnerDirector -> Resident holding a FILLED OWNER_ELECTED seat) must use the
per-instance builders with the actual entity id whenever the call is
ownership-gated. The shared constants are safe for opaque roles and for
tests that never exercise an ownership check.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "declarant_executive_headers": build_user_headers("test-exec-1", "DeclarantExecutive"),
    "declarant_controller_headers": build_user_headers("test-controller-1", "DeclarantController"),
    "association_director_headers": build_user_headers("test-director-1", "AssociationDirector"),
    "design_reviewer_headers": build_user_headers("test-reviewer-1", "DesignReviewer"),
    "lifestyle_coordinator_headers": build_user_headers("test-lifestyle-1", "LifestyleCoordinator"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    # Entity-backed roles: shared constants for non-ownership tests only.
    "builder_rep_headers": build_user_headers("test-builder-1", "BuilderRep"),
    "homeowner_resident_headers": build_user_headers("test-resident-1", "HomeownerResident"),
    "owner_director_headers": build_user_headers("test-owner-dir-1", "OwnerDirector"),
}


def make_builder_rep_headers(builder_id: str) -> dict:
    """BuilderRep identity is entity_backed:Builder. Pass the real Builder.id
    whenever the call is ownership-gated (cure, application as applicant)."""
    return build_user_headers(builder_id, "BuilderRep")


def make_homeowner_resident_headers(resident_id: str) -> dict:
    """HomeownerResident identity is entity_backed:Resident. Pass the real
    Resident.id whenever the call is ownership-gated (rsvp, appeal, etc.)."""
    return build_user_headers(resident_id, "HomeownerResident")


def make_owner_director_headers(resident_id: str) -> dict:
    """OwnerDirector identity is an OWNER resident holding a FILLED
    OWNER_ELECTED seat. Pass the seat-holding Resident.id."""
    return build_user_headers(resident_id, "OwnerDirector")


def make_design_reviewer_headers(user_id: str) -> dict:
    """DesignReviewer is opaque, but the review workflow keys decisions to
    reviewer_user_id, so distinct reviewer identities need distinct ids."""
    return build_user_headers(user_id, "DesignReviewer")


def make_association_director_headers(user_id: str) -> dict:
    """AssociationDirector is opaque; segregation-of-duties tests need
    distinct director identities (e.g. dir-1 vs dir-2)."""
    return build_user_headers(user_id, "AssociationDirector")
