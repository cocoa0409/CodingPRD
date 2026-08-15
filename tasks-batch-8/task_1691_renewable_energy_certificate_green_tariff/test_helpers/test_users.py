"""Pre-built role headers for every role in the PRD (§2.1).

RegistryAdmin, MeterAttester, ProgramManager, ComplianceOfficer, and Auditor
are opaque roles: their X-User-ID is never compared to any entity id, so the
shared constants are canonical. GeneratorOperator is entity-backed by
Generator (X-User-ID must equal the Generator.id) and BrokerTrader is
entity-backed by BROKER Account (X-User-ID must equal the Account.id): use
the make_* builders with the real entity id for any ownership-gated call;
the shared constants for those two roles are fallbacks only for tests that
do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "registry_admin_headers": build_user_headers("test-admin-1", "RegistryAdmin"),
    "meter_attester_headers": build_user_headers("att-1", "MeterAttester"),
    "program_manager_headers": build_user_headers("pm-1", "ProgramManager"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "auditor_headers": build_user_headers("aud-1", "Auditor"),
    # Entity-backed roles: shared constants are fallbacks for non-ownership tests only.
    "generator_operator_headers": build_user_headers("test-operator-1", "GeneratorOperator"),
    "broker_trader_headers": build_user_headers("test-broker-1", "BrokerTrader"),
}


def make_generator_operator_headers(generator_id: str) -> dict:
    """For GeneratorOperator (entity-backed by Generator). Pass the actual
    Generator.id whenever the call is ownership-gated (submit-verification,
    meter-reading creation, resubmit)."""
    return build_user_headers(generator_id, "GeneratorOperator")


def make_broker_trader_headers(account_id: str) -> dict:
    """For BrokerTrader (entity-backed by BROKER Account). Pass the actual
    Account.id whenever the call is ownership-gated (trade propose/cancel as
    seller, accept/settle as buyer, wholesale retirement, transfer)."""
    return build_user_headers(account_id, "BrokerTrader")


def make_meter_attester_headers(user_id: str) -> dict:
    """For MeterAttester (opaque). A custom user id matters only for
    segregation-of-duties scenarios (must differ from the reading submitter)."""
    return build_user_headers(user_id, "MeterAttester")


def make_program_manager_headers(user_id: str) -> dict:
    """For ProgramManager (opaque). A custom user id matters only for
    report segregation-of-duties scenarios (submitter vs deciding auditor)."""
    return build_user_headers(user_id, "ProgramManager")


def make_auditor_headers(user_id: str) -> dict:
    """For Auditor (opaque). A custom user id matters only for report
    segregation-of-duties scenarios."""
    return build_user_headers(user_id, "Auditor")
