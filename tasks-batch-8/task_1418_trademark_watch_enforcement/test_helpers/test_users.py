"""Pre-built role headers for every role in the PRD.

Shared constants are safe for opaque roles and for tests that do not exercise
ownership. For the entity-backed ClientContact role, ALWAYS build headers with
make_client_contact_headers(client["id"]) when the call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin_1", "PlatformAdmin"),
    "paralegal_headers": build_user_headers("para_1", "Paralegal"),
    "associate_headers": build_user_headers("assoc_1", "AssociateAttorney"),
    "partner_headers": build_user_headers("partner_1", "PartnerAttorney"),
    "watch_service_headers": build_user_headers("watch_svc_1", "WatchService"),
    # Fallback only for non-ownership calls; the id matches no real Client.
    "client_contact_headers": build_user_headers("test-client-contact-1", "ClientContact"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_paralegal_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Paralegal")


def make_associate_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AssociateAttorney")


def make_partner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PartnerAttorney")


def make_watch_service_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "WatchService")


def make_client_contact_headers(user_id: str) -> dict:
    """For ClientContact (entity-backed by Client). Pass the actual Client.id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "ClientContact")
