"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque IrsGateway role, and for tests that do NOT
# exercise ownership (401-on-bad-auth, 404-on-missing-resource).
#
# Taxpayer and Preparer are both identity entity_backed:Taxpayer (PRD §2.1): their
# X-User-ID is the id of the acting/represented Taxpayer entity, and ownership checks
# compare the resource's owning taxpayer_id to X-User-ID. Ownership-gated calls MUST
# use make_taxpayer_headers / make_preparer_headers with the real Taxpayer.id.
TEST_USERS = {
    "taxpayer_headers": build_user_headers("test-taxpayer-1", "Taxpayer"),
    "preparer_headers": build_user_headers("test-preparer-1", "Preparer"),
    # opaque role: shared constant is the canonical form.
    "irs_gateway_headers": build_user_headers("test-irs-gateway-1", "IrsGateway"),
}


def make_taxpayer_headers(taxpayer_id: str) -> dict:
    """For Taxpayer (entity_backed:Taxpayer). Pass the actual Taxpayer.id as X-User-ID
    whenever the call is ownership-gated (PRD §2.1: ownership checks compare the
    resource's owning taxpayer to X-User-ID)."""
    return build_user_headers(taxpayer_id, "Taxpayer")


def make_preparer_headers(taxpayer_id: str) -> dict:
    """For Preparer (entity_backed:Taxpayer). X-User-ID is the represented Taxpayer.id;
    the same ownership checks apply (PRD §2.1)."""
    return build_user_headers(taxpayer_id, "Preparer")


def make_irs_gateway_headers(operator_id: str = "irs-op-1") -> dict:
    """For IrsGateway (opaque). X-User-ID is an opaque operator identifier."""
    return build_user_headers(operator_id, "IrsGateway")
