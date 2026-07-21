"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers
from .constants import (
    ADMIN_USER, OPS_USER, FIN_RECONCILER, FIN_CLOSER, FIN_APPROVER, FIN_PAYER,
)

# Shared constants.
# PlatformAdmin, DistributionOps, FinanceOps and Fan carry opaque X-User-ID values that
# the server never compares to any entity id, so a shared constant is the canonical form.
# Artist and Collaborator are entity-backed: the shared entries below are usable ONLY for
# calls that do not exercise ownership (e.g. a 404 on a non-existent resource).
TEST_USERS = {
    "admin_headers": build_user_headers(ADMIN_USER, "PlatformAdmin"),
    "ops_headers": build_user_headers(OPS_USER, "DistributionOps"),
    "finance_headers": build_user_headers(FIN_RECONCILER, "FinanceOps"),
    "finance_closer_headers": build_user_headers(FIN_CLOSER, "FinanceOps"),
    "finance_approver_headers": build_user_headers(FIN_APPROVER, "FinanceOps"),
    "finance_payer_headers": build_user_headers(FIN_PAYER, "FinanceOps"),
    "fan_headers": build_user_headers("fan-1", "Fan"),
    "artist_headers": build_user_headers("test-artist-1", "Artist"),
    "collaborator_headers": build_user_headers("test-collaborator-1", "Collaborator"),
}


# --- Per-instance builders: mandatory for the two entity-backed roles ---

def make_artist_headers(artist_id: str) -> dict:
    """For the Artist role. Pass the acting artist's own id: every ownership check
    compares the owning artist reference of the addressed resource to X-User-ID."""
    return build_user_headers(artist_id, "Artist")


def make_collaborator_headers(collaborator_id: str) -> dict:
    """For the Collaborator role. Pass the acting payee's own id: ownership checks
    compare a share's or payout's collaborator_id to X-User-ID."""
    return build_user_headers(collaborator_id, "Collaborator")


def make_finance_headers(user_id: str) -> dict:
    """FinanceOps operator with an explicit opaque id, for segregation-of-duties scenarios."""
    return build_user_headers(user_id, "FinanceOps")


def make_ops_headers(user_id: str = OPS_USER) -> dict:
    return build_user_headers(user_id, "DistributionOps")


def make_admin_headers(user_id: str = ADMIN_USER) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_fan_headers(fan_reference: str) -> dict:
    """Fan registration accepts any X-User-ID value whatsoever."""
    return build_user_headers(fan_reference, "Fan")
