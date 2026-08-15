"""Pre-built role headers for every role in the PRD.

All four roles use opaque identities (PRD §2.1): X-User-ID is never compared to
any persisted entity's id. For the Importer role, however, X-User-ID IS recorded
as the importer_ref ownership anchor on created resources, so ownership-gated
calls must use a consistent importer identity — the make_importer_headers()
builder provides that per test scenario.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for non-ownership tests.
TEST_USERS = {
    "zone_operator_headers": build_user_headers("test-zone-operator-1", "ZoneOperator"),
    "importer_headers": build_user_headers("imp-1", "Importer"),
    "customs_officer_headers": build_user_headers("test-customs-officer-1", "CustomsOfficer"),
    "gate_officer_headers": build_user_headers("test-gate-officer-1", "GateOfficer"),
}


def make_zone_operator_headers(user_id: str = "test-zone-operator-1") -> dict:
    """ZoneOperator (opaque identity) — authority to act only."""
    return build_user_headers(user_id, "ZoneOperator")


def make_importer_headers(user_id: str) -> dict:
    """Importer whose X-User-ID becomes the importer_ref ownership anchor on
    every admission, manipulation order, withdrawal, and weekly entry created.
    Ownership-gated follow-up calls MUST use the same user_id."""
    return build_user_headers(user_id, "Importer")


def make_customs_officer_headers(user_id: str = "test-customs-officer-1") -> dict:
    """CustomsOfficer (opaque identity) — authority to act only."""
    return build_user_headers(user_id, "CustomsOfficer")


def make_gate_officer_headers(user_id: str = "test-gate-officer-1") -> dict:
    """GateOfficer (opaque identity) — authority to act only."""
    return build_user_headers(user_id, "GateOfficer")
