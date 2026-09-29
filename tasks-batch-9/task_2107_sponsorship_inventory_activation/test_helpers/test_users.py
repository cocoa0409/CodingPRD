"""Pre-built operator headers for every role in the PRD."""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers. For PropertyAdmin, SponsorshipSeller,
# ContractApprover, ActivationManager and PerformanceAuditor the X-User-ID is
# never compared against any entity id -- it is only recorded on audit trails.
PROPERTY_ADMIN_USER_ID = "u-admin-01"
SELLER_USER_ID = "u-seller-01"
APPROVER_USER_ID = "u-approver-01"
SECOND_APPROVER_USER_ID = "u-approver-02"
ACTIVATION_USER_ID = "u-act-01"
AUDITOR_USER_ID = "u-audit-01"
SECOND_ACTIVATION_USER_ID = "u-act-02"
DUAL_ROLE_USER_ID = "u-dual-01"

TEST_USERS = {
    "property_admin_headers": build_user_headers(
        PROPERTY_ADMIN_USER_ID, "PropertyAdmin"
    ),
    "seller_headers": build_user_headers(SELLER_USER_ID, "SponsorshipSeller"),
    "approver_headers": build_user_headers(APPROVER_USER_ID, "ContractApprover"),
    "activation_headers": build_user_headers(ACTIVATION_USER_ID, "ActivationManager"),
    "auditor_headers": build_user_headers(AUDITOR_USER_ID, "PerformanceAuditor"),
    # SponsorContact is entity backed: the shared constant is only safe for
    # calls that are not sponsor-scoped. Ownership-gated calls must use
    # make_sponsor_contact_headers() with the real Sponsor id.
    "sponsor_contact_headers": build_user_headers(
        "test-sponsor-contact-1", "SponsorContact"
    ),
}


def make_property_admin_headers(user_id: str) -> dict:
    """PropertyAdmin acting under a specific operator identifier."""
    return build_user_headers(user_id, "PropertyAdmin")


def make_seller_headers(user_id: str) -> dict:
    """SponsorshipSeller acting under a specific operator identifier."""
    return build_user_headers(user_id, "SponsorshipSeller")


def make_approver_headers(user_id: str) -> dict:
    """ContractApprover acting under a specific operator identifier."""
    return build_user_headers(user_id, "ContractApprover")


def make_activation_headers(user_id: str) -> dict:
    """ActivationManager acting under a specific operator identifier."""
    return build_user_headers(user_id, "ActivationManager")


def make_auditor_headers(user_id: str) -> dict:
    """PerformanceAuditor acting under a specific operator identifier."""
    return build_user_headers(user_id, "PerformanceAuditor")


def make_sponsor_contact_headers(sponsor_id: str) -> dict:
    """SponsorContact headers for a real Sponsor.

    X-User-ID is the id of the acting Sponsor, so every sponsor-scoped call
    must be built with the actual Sponsor id.
    """
    return build_user_headers(sponsor_id, "SponsorContact")
