"""Pre-built role headers for every role in the PRD.

Four operator roles are opaque identities (RecoverySpecialist, RecoveryManager,
FinanceOfficer, System). CarrierUser is entity-backed: its X-User-ID must be the
acting Carrier's id, so ownership-gated calls MUST use make_carrier_user_headers().
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator identities — shared constants are the canonical form.
    "specialist_headers": build_user_headers("spec-1", "RecoverySpecialist"),
    "specialist2_headers": build_user_headers("spec-2", "RecoverySpecialist"),
    "manager_headers": build_user_headers("mgr-1", "RecoveryManager"),
    "manager2_headers": build_user_headers("mgr-2", "RecoveryManager"),
    "finance_headers": build_user_headers("fin-1", "FinanceOfficer"),
    "system_headers": build_user_headers("sys-1", "System"),
    # Any authenticated role may read; a specialist identity serves as reader.
    "reader_headers": build_user_headers("reader-1", "RecoverySpecialist"),
    # CarrierUser fallback constant — only for non-ownership tests (e.g. a
    # deliberately foreign carrier id). Ownership-gated calls use the builder below.
    "carrier_user_headers": build_user_headers("carrier-unowned", "CarrierUser"),
}


def make_carrier_user_headers(carrier_id: str) -> dict:
    """For CarrierUser (entity_backed:Carrier). Pass the acting Carrier.id as user_id
    whenever the call is ownership-gated (refer / withdraw / accept / add-document)."""
    return build_user_headers(carrier_id, "CarrierUser")
