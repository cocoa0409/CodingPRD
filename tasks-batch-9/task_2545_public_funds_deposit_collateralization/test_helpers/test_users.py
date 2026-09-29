"""Pre-built role headers for every role named in PRD §2.1.

Four roles carry opaque operator identities, so a shared constant is the canonical
form for them. Two roles are entity-backed — a `Custodian` acts as a `Custodian`
record's `id` and a `PublicUnitTreasurer` acts as a `PublicUnit` record's `id` — so
any ownership-gated call MUST use the per-instance builder with the real entity id.
"""

from prd_bench_local_runner.testing import build_user_headers

# ─── Opaque operator identities ───────────────────────
REGULATOR_USER_ID = "regulator-1"
OFFICER_USER_ID = "officer-1"
COMPLIANCE_USER_ID = "compliance-1"
SECOND_OFFICER_USER_ID = "officer-2"
SECOND_COMPLIANCE_USER_ID = "compliance-2"
OPERATOR_USER_ID = "operator-1"
PRICING_FEED_USER_ID = "pricing-feed"
BATCH_USER_ID = "batch-1"

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "state_regulator_headers": build_user_headers(REGULATOR_USER_ID, "StateRegulator"),
    "bank_collateral_officer_headers": build_user_headers(
        OFFICER_USER_ID, "BankCollateralOfficer"
    ),
    "bank_compliance_officer_headers": build_user_headers(
        COMPLIANCE_USER_ID, "BankComplianceOfficer"
    ),
    "system_operator_headers": build_user_headers(OPERATOR_USER_ID, "SystemOperator"),
    # Second opaque identities, for segregation-of-duties scenarios.
    "second_bank_collateral_officer_headers": build_user_headers(
        SECOND_OFFICER_USER_ID, "BankCollateralOfficer"
    ),
    "second_bank_compliance_officer_headers": build_user_headers(
        SECOND_COMPLIANCE_USER_ID, "BankComplianceOfficer"
    ),
    # Entity-backed roles — these shared constants are ONLY safe for tests that do
    # not depend on the caller owning the subject resource (401/403/404/400 probes).
    "custodian_headers": build_user_headers("test-custodian-1", "Custodian"),
    "public_unit_treasurer_headers": build_user_headers(
        "test-public-unit-1", "PublicUnitTreasurer"
    ),
}


def make_state_regulator_headers(user_id: str = REGULATOR_USER_ID) -> dict:
    """Headers for a StateRegulator (opaque identity)."""
    return build_user_headers(user_id, "StateRegulator")


def make_bank_collateral_officer_headers(user_id: str = OFFICER_USER_ID) -> dict:
    """Headers for a BankCollateralOfficer (opaque identity)."""
    return build_user_headers(user_id, "BankCollateralOfficer")


def make_bank_compliance_officer_headers(user_id: str = COMPLIANCE_USER_ID) -> dict:
    """Headers for a BankComplianceOfficer (opaque identity)."""
    return build_user_headers(user_id, "BankComplianceOfficer")


def make_system_operator_headers(user_id: str = OPERATOR_USER_ID) -> dict:
    """Headers for a SystemOperator (opaque identity)."""
    return build_user_headers(user_id, "SystemOperator")


def make_custodian_headers(custodian_id: str) -> dict:
    """Headers for a Custodian. Pass the acting Custodian record's `id`, because
    ownership checks compare an agreement's `custodian_id` to `X-User-ID`."""
    return build_user_headers(custodian_id, "Custodian")


def make_public_unit_treasurer_headers(public_unit_id: str) -> dict:
    """Headers for a PublicUnitTreasurer. Pass the acting PublicUnit record's `id`,
    because ownership checks compare an account's `public_unit_id` to `X-User-ID`."""
    return build_user_headers(public_unit_id, "PublicUnitTreasurer")


ALL_ROLE_NAMES = [
    "StateRegulator",
    "BankCollateralOfficer",
    "BankComplianceOfficer",
    "Custodian",
    "PublicUnitTreasurer",
    "SystemOperator",
]
