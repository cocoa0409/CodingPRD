"""Pre-built role headers for every role in the PRD (§2.1).

All seven roles use the opaque identity model: `X-User-ID` is not tied to any
persisted entity's `id`. The shared constants below are therefore canonical for
all roles. Per-instance builders are provided so tests can thread a specific
`X-User-ID` (needed for segregation-of-duties scenarios, where two calls must
carry different opaque user IDs — PRD §2.7).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "captive_manager_headers": build_user_headers("test-captive-manager-1", "CaptiveManager"),
    "domicile_regulator_headers": build_user_headers("test-domicile-regulator-1", "DomicileRegulator"),
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    "actuary_headers": build_user_headers("test-actuary-1", "Actuary"),
    "claims_adjuster_headers": build_user_headers("test-claims-adjuster-1", "ClaimsAdjuster"),
    "board_director_headers": build_user_headers("test-board-director-1", "BoardDirector"),
    "tax_advisor_headers": build_user_headers("test-tax-advisor-1", "TaxAdvisor"),
}


def make_captive_manager_headers(user_id: str) -> dict:
    """CaptiveManager headers with a specific opaque user id."""
    return build_user_headers(user_id, "CaptiveManager")


def make_domicile_regulator_headers(user_id: str) -> dict:
    """DomicileRegulator headers with a specific opaque user id."""
    return build_user_headers(user_id, "DomicileRegulator")


def make_underwriter_headers(user_id: str) -> dict:
    """Underwriter headers with a specific opaque user id."""
    return build_user_headers(user_id, "Underwriter")


def make_actuary_headers(user_id: str) -> dict:
    """Actuary headers with a specific opaque user id (segregation of duties, PRD §2.7)."""
    return build_user_headers(user_id, "Actuary")


def make_claims_adjuster_headers(user_id: str) -> dict:
    """ClaimsAdjuster headers with a specific opaque user id."""
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_board_director_headers(user_id: str) -> dict:
    """BoardDirector headers with a specific opaque user id (segregation of duties, PRD §2.7)."""
    return build_user_headers(user_id, "BoardDirector")


def make_tax_advisor_headers(user_id: str) -> dict:
    """TaxAdvisor headers with a specific opaque user id."""
    return build_user_headers(user_id, "TaxAdvisor")
