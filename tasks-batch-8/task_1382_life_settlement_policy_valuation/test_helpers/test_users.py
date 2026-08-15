"""Pre-built role headers for every role in the PRD (§2.1).

Broker and Investor are entity-backed roles: their X-User-ID must equal the
acting Broker/Investor entity's id for ownership-gated calls. Use the
per-instance builders for those calls; the shared constants are only safe for
non-ownership tests (400s, 404s, role-forbidden probes)."""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constant is the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "underwriter_headers": build_user_headers("test-uw-1", "Underwriter"),
    "case_manager_headers": build_user_headers("test-cm-1", "CaseManager"),
    "compliance_headers": build_user_headers("co_1", "ComplianceOfficer"),
    "finance_headers": build_user_headers("fo_1", "FinanceOfficer"),
    "portfolio_manager_headers": build_user_headers("test-pm-1", "PortfolioManager"),
    # Entity-backed roles: fallback for non-ownership tests only.
    "broker_headers": build_user_headers("test-broker-1", "Broker"),
    "investor_headers": build_user_headers("test-investor-1", "Investor"),
}


def make_broker_headers(broker_id: str) -> dict:
    """Broker is entity-backed: X-User-ID must be the Broker.id for any
    ownership-gated call (case create/submit/withdraw, counter, accept, reject,
    policy create/amend)."""
    return build_user_headers(broker_id, "Broker")


def make_investor_headers(investor_id: str) -> dict:
    """Investor is entity-backed: X-User-ID must be the Investor.id for
    allocation-gated portfolio/snapshot reads."""
    return build_user_headers(investor_id, "Investor")


def make_finance_headers(user_id: str) -> dict:
    """FinanceOfficer is opaque, but escrow release compares X-User-ID against
    the closing package's approved_by_user_id (segregation of duties, PRD §3.5);
    pick a distinct id for release paths."""
    return build_user_headers(user_id, "FinanceOfficer")


def make_compliance_headers(user_id: str) -> dict:
    """ComplianceOfficer is opaque; the user id is recorded as
    approved_by_user_id on closing approval (PRD §3.4)."""
    return build_user_headers(user_id, "ComplianceOfficer")
