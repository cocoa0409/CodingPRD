"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, listing reads).
# For the entity_backed VendorRep role, prefer make_vendor_rep_headers(vendor_id)
# whenever the call is ownership-gated (bid submit/withdraw, turnover ack/return).
TEST_USERS = {
    "post_supervisor_headers": build_user_headers("ps-1", "PostSupervisor"),
    "media_manager_headers": build_user_headers("mm-1", "MediaManager"),
    "dailies_coordinator_headers": build_user_headers("dc-1", "DailiesCoordinator"),
    "conform_editor_headers": build_user_headers("ce-1", "ConformEditor"),
    "reviewer_lead_headers": build_user_headers("rl-1", "ReviewerLead"),
    "qc_operator_headers": build_user_headers("qc-1", "QCOperator"),
    "facility_admin_headers": build_user_headers("fa-1", "FacilityAdmin"),
    # entity_backed: shared constant is a fallback for non-ownership tests only.
    "vendor_rep_headers": build_user_headers("test-vendor-1", "VendorRep"),
    "artist_headers": build_user_headers("art@x.com", "Artist"),
}


def make_post_supervisor_headers(user_id: str = "ps-1") -> dict:
    """PostSupervisor is an opaque role; user_id is any operator identifier."""
    return build_user_headers(user_id, "PostSupervisor")


def make_media_manager_headers(user_id: str = "mm-1") -> dict:
    """MediaManager is an opaque role."""
    return build_user_headers(user_id, "MediaManager")


def make_dailies_coordinator_headers(user_id: str = "dc-1") -> dict:
    """DailiesCoordinator is an opaque role."""
    return build_user_headers(user_id, "DailiesCoordinator")


def make_conform_editor_headers(user_id: str = "ce-1") -> dict:
    """ConformEditor is an opaque role."""
    return build_user_headers(user_id, "ConformEditor")


def make_reviewer_lead_headers(user_id: str = "rl-1") -> dict:
    """ReviewerLead is an opaque role."""
    return build_user_headers(user_id, "ReviewerLead")


def make_qc_operator_headers(user_id: str = "qc-1") -> dict:
    """QCOperator is an opaque role; recorded as issued_by on QC reports."""
    return build_user_headers(user_id, "QCOperator")


def make_facility_admin_headers(user_id: str = "fa-1") -> dict:
    """FacilityAdmin is an opaque role."""
    return build_user_headers(user_id, "FacilityAdmin")


def make_vendor_rep_headers(user_id: str) -> dict:
    """VendorRep is entity_backed:Vendor. Pass the actual Vendor.id as user_id
    whenever the call is ownership-gated (bid submit/withdraw, turnover
    ack/return)."""
    return build_user_headers(user_id, "VendorRep")


def make_artist_headers(user_id: str) -> dict:
    """Artist is opaque at the identity layer, but booking check-in / complete /
    artist-cancel compare X-User-ID to the booking's artist_email — pass the
    booking's artist_email as user_id for those calls."""
    return build_user_headers(user_id, "Artist")
