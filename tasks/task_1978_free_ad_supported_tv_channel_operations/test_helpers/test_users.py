"""Pre-built role headers for every role in the PRD (§2.1).

Seven roles are opaque operator identities; DistributorPartner is entity-backed:
its X-User-ID must equal the acting DistributorPlatform's id (PRD §2.1), so
ownership-gated calls MUST use make_distributor_partner_headers(platform_id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "programmer_headers": build_user_headers("prog-1", "ChannelProgrammer"),
    "licensing_headers": build_user_headers("lic-1", "ContentLicensing"),
    # AdOps default identity doubles as the canonical creative creator ("ops-1").
    "adops_headers": build_user_headers("ops-1", "AdOps"),
    # Reviewer default identity is distinct from the creator so segregation passes.
    "reviewer_headers": build_user_headers("rev-1", "AdQualityReviewer"),
    "analyst_headers": build_user_headers("fin-1", "FinanceAnalyst"),
    "controller_headers": build_user_headers("ctl-1", "FinanceController"),
    # Shared fallback for DistributorPartner — usable only where the call is not
    # ownership-gated. Ownership-gated calls must use the builder below.
    "partner_headers": build_user_headers("test-partner-1", "DistributorPartner"),
}


def make_distributor_partner_headers(platform_id: str) -> dict:
    """DistributorPartner is entity-backed (X-User-ID == DistributorPlatform.id).
    Pass the actual platform id for any ownership-gated call (reports, events,
    disputes)."""
    return build_user_headers(platform_id, "DistributorPartner")


def make_adops_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AdOps")


def make_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AdQualityReviewer")


def make_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinanceAnalyst")


def make_controller_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinanceController")
