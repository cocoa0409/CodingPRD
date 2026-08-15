"""Pre-built role headers for every role in PRD §2.1.

All four roles are opaque: `X-User-ID` is not tied to any persisted entity and
the server never compares it to a resource's `id`. It IS recorded for audit
and segregation-of-duties purposes (AssumptionSet.created_by_user_id /
approved_by_user_id; AlcoReport.submitted_by_user_id /
acknowledged_by_user_id), so tests exercising those boundaries must thread
deliberate user ids — use two distinct ids (e.g. an-1 vs ch-1) across the
approval boundary and the same id to probe the segregation violation.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "analyst_headers": build_user_headers("an-1", "TreasuryAnalyst"),
    "analyst2_headers": build_user_headers("an-2", "TreasuryAnalyst"),
    "validator_headers": build_user_headers("mv-1", "ModelRiskValidator"),
    "chair_headers": build_user_headers("ch-1", "ALCOChair"),
    "chair2_headers": build_user_headers("ch-2", "ALCOChair"),
    "regulator_headers": build_user_headers("reg-1", "Regulator"),
}

# A request carrying no X-User-ID / X-User-Role at all (PRD §2.1 violation).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_analyst_headers(user_id: str) -> dict:
    """TreasuryAnalyst identity is opaque but recorded on resources it
    creates; pass an explicit id when segregation-of-duties matters."""
    return build_user_headers(user_id, "TreasuryAnalyst")


def make_validator_headers(user_id: str) -> dict:
    """ModelRiskValidator identity is opaque."""
    return build_user_headers(user_id, "ModelRiskValidator")


def make_chair_headers(user_id: str) -> dict:
    """ALCOChair identity is opaque but recorded on approval / acknowledgement;
    pass an explicit id when segregation-of-duties matters."""
    return build_user_headers(user_id, "ALCOChair")


def make_regulator_headers(user_id: str) -> dict:
    """Regulator identity is opaque; the role is read-only."""
    return build_user_headers(user_id, "Regulator")
