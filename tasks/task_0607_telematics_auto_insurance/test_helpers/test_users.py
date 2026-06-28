"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants.
#   - DriverUser is entity-backed: this shared constant is a fallback usable only by tests
#     that do NOT exercise ownership (e.g. a forbidden-role attempt that fails before the
#     ownership check, or a bad-payload/404 path). Ownership-gated calls MUST instead use
#     make_driver_headers(<the actual Driver.id>).
#   - UnderwritingOps and ClaimsAdjuster carry opaque operator identifiers not tied to any
#     persisted entity, so the shared constant is their canonical form.
TEST_USERS = {
    "driver_headers": build_user_headers("test-driver-1", "DriverUser"),
    "underwriting_headers": build_user_headers("test-underwriting-1", "UnderwritingOps"),
    "claims_headers": build_user_headers("test-claims-1", "ClaimsAdjuster"),
}


def make_driver_headers(driver_id: str) -> dict:
    """For DriverUser (entity_backed:Driver). Pass the actual Driver.id as user_id
    whenever the call is ownership-gated (enrollments, quotes, trips, privacy-consents,
    claims that resolve to this driver)."""
    return build_user_headers(driver_id, "DriverUser")


def make_underwriting_headers(user_id: str = "test-underwriting-1") -> dict:
    """For UnderwritingOps (opaque operator identifier)."""
    return build_user_headers(user_id, "UnderwritingOps")


def make_claims_headers(user_id: str = "test-claims-1") -> dict:
    """For ClaimsAdjuster (opaque operator identifier)."""
    return build_user_headers(user_id, "ClaimsAdjuster")
