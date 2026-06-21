"""Pre-built role headers for every role in the PRD.

All four roles use an opaque X-User-ID that is never compared to any entity id
(PRD §2.1): authorization is purely role-based. Shared constants are therefore
the canonical form for every role; there are no ownership-gated per-instance
builders in this domain.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "shipper_ops_headers": build_user_headers("test-shipper-1", "ShipperOps"),
    "carrier_ops_headers": build_user_headers("test-carrier-1", "CarrierOps"),
    "dock_ops_headers": build_user_headers("test-dock-1", "DockOps"),
    "freight_auditor_headers": build_user_headers("test-auditor-1", "FreightAuditor"),
}
