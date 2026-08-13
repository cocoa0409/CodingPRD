"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, cross-role denials).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "ProgramAdministrator"),
    "inspector_headers": build_user_headers("test-inspector-1", "VerificationInspector"),
    "processor_headers": build_user_headers("test-processor-1", "PaymentProcessor"),
    "regulator_headers": build_user_headers("test-regulator-1", "RegulatorAnalyst"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "trade_ally_headers": build_user_headers("test-ally-1", "TradeAlly"),
}


def make_trade_ally_headers(ally_id: str) -> dict:
    """For TradeAlly (entity_backed:TradeAlly). Pass the actual TradeAlly.id as
    ally_id whenever the call is ownership-gated (create/submit/withdraw
    application, add line item, attach savings claim)."""
    return build_user_headers(ally_id, "TradeAlly")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "ProgramAdministrator")


def make_inspector_headers(user_id: str = "test-inspector-1") -> dict:
    return build_user_headers(user_id, "VerificationInspector")


def make_processor_headers(user_id: str = "test-processor-1") -> dict:
    return build_user_headers(user_id, "PaymentProcessor")


def make_regulator_headers(user_id: str = "test-regulator-1") -> dict:
    return build_user_headers(user_id, "RegulatorAnalyst")
