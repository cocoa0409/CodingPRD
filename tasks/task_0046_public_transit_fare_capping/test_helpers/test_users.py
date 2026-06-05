"""Pre-built role headers for every role in the PRD (§2.1).

The Rider role is entity-backed: when a Rider acts, X-User-ID is the id of the
acting Rider entity, and ownership checks compare a resource's rider_id to that id.
Tests whose success depends on the caller owning the subject resource MUST build
Rider headers with the real rider id via make_rider_headers(rider_id).

The other four roles (FareAdmin, EmployerAdmin, PaymentGateway, Anonymous) are
opaque operator identities never matched against an entity id, so their shared
constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator identities — shared constants are canonical.
    "fare_admin_headers": build_user_headers("test-fare-admin-1", "FareAdmin"),
    "employer_admin_headers": build_user_headers("test-employer-admin-1", "EmployerAdmin"),
    "payment_gateway_headers": build_user_headers("test-payment-gateway-1", "PaymentGateway"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    # entity_backed Rider — shared constant is a fallback for non-ownership tests
    # only (it will never equal a real rider id, so ownership-gated calls must use
    # make_rider_headers below).
    "rider_headers": build_user_headers("test-rider-fallback-1", "Rider"),
}


def make_rider_headers(rider_id: str) -> dict:
    """Build Rider headers carrying the actual Rider.id as X-User-ID.

    Use this for every ownership-gated Rider call (POST /taps, GET /taps/{id},
    POST /funding-sources, POST /reduced-fare-cards, POST /fare-weeks,
    GET /taps/quote, etc.) so the §2.1 ownership check passes.
    """
    return build_user_headers(rider_id, "Rider")


def make_anonymous_headers() -> dict:
    """Anonymous caller — used for rider registration and public fare-product reads."""
    return build_user_headers("test-anon-1", "Anonymous")
