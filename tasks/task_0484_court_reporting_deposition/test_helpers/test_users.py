"""Pre-built role headers for every role in the PRD (§2.1).

Five roles. ScheduleCoordinator, BillingClerk, and PlatformAdmin are opaque
operators (X-User-ID is not compared to any entity), so the shared constant is
their canonical form. Reporter is entity_backed:Resource and Attorney is
entity_backed:Attorney — for any ownership-gated call (a reporter delivering or
certifying a transcript for a job they covered, or an attorney filing errata /
signing / cancelling on their own case) the per-instance builder MUST be used,
passing the acting Resource.id / Attorney.id as X-User-ID.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constant is canonical.
    "schedule_coordinator_headers": build_user_headers("test-coordinator-1", "ScheduleCoordinator"),
    "billing_clerk_headers": build_user_headers("test-billing-1", "BillingClerk"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    # entity_backed roles — fallback for non-ownership tests only (e.g. 403/404).
    "reporter_headers": build_user_headers("test-reporter-1", "Reporter"),
    "attorney_headers": build_user_headers("test-attorney-1", "Attorney"),
}


def make_schedule_coordinator_headers(user_id: str = "test-coordinator-1") -> dict:
    """ScheduleCoordinator headers (opaque operator id; not compared to entities)."""
    return build_user_headers(user_id, "ScheduleCoordinator")


def make_billing_clerk_headers(user_id: str = "test-billing-1") -> dict:
    """BillingClerk headers (opaque operator id; not compared to entities)."""
    return build_user_headers(user_id, "BillingClerk")


def make_platform_admin_headers(user_id: str = "test-admin-1") -> dict:
    """PlatformAdmin headers (opaque operator id; not compared to entities)."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_reporter_headers(user_id: str) -> dict:
    """For the Reporter role (entity_backed:Resource). Pass the acting
    Resource.id as user_id for any ownership-gated reporter call (deliver-rough,
    certify, go-live)."""
    return build_user_headers(user_id, "Reporter")


def make_attorney_headers(user_id: str) -> dict:
    """For the Attorney role (entity_backed:Attorney). Pass the acting
    Attorney.id as user_id for any case-party-gated call (errata, sign, cancel
    transcript, order own case's transcript)."""
    return build_user_headers(user_id, "Attorney")
