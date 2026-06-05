"""Difficulty Rule 3 — non_linear_state_machine.

Two non-linear topologies:
  (A) Tenant.liveaboard_status cycle REVOKED -> PENDING (re-application loop).
  (B) Slip branches from AVAILABLE: one edge to RESERVED via lease creation,
      another edge to OUT_OF_SERVICE via decommission.
"""
from test_helpers import (
    validate_success,
    create_marina,
    create_slip,
    create_tenant,
    apply_liveaboard,
    approve_liveaboard,
    revoke_liveaboard,
    TEST_USERS,
    make_tenant_headers,
)


class TestTenantLiveaboardCycleRevokedToPending:
    """After APPROVED -> REVOKED, a re-application transitions REVOKED -> PENDING,
    closing the cycle and proving the Tenant machine is non-linear.
    """

    def _walk_to_revoked(self):
        marina = create_marina(liveaboard_cap=3)
        tenant = create_tenant()
        apply_liveaboard(tenant["id"], marina["id"])
        approve_liveaboard(tenant["id"], marina["id"])
        revoke_liveaboard(tenant["id"], marina["id"])
        return marina, tenant

    def test_reapplication_from_revoked_returns_status_pending(self, api):
        """PRD §3.3: "A tenant whose status is `NONE` or `REVOKED` may submit a liveaboard application; the application names the `marina_id` for which approval is sought."
        PRD §3.3: "From `NONE` this transitions the tenant's `liveaboard_status` to `PENDING`; from `REVOKED` the same operation re-enters the review queue, also producing `PENDING`."

        Design: Difficulty/non_linear_state_machine/tenant_liveaboard_cycle_revoked_to_pending
        """
        marina, tenant = self._walk_to_revoked()
        res = api.apply_liveaboard(
            tenant["id"],
            {"marina_id": marina["id"]},
            make_tenant_headers(tenant["id"]),
        )
        data = validate_success(res, expected_status=200)
        assert data["liveaboard_status"] == "PENDING", \
            f"REVOKED + re-apply -> PENDING (cycle), got {data['liveaboard_status']}"

    def test_reapplication_loop_is_cyclic_for_revoked_tenant(self, api):
        """PRD §3.3: "This re-application loop makes the tenant's liveaboard machine cyclic: a previously revoked tenant can return to the queue and be approved again."

        Design: Difficulty/non_linear_state_machine/tenant_liveaboard_cycle_revoked_to_pending
        """
        marina, tenant = self._walk_to_revoked()
        # Re-apply from REVOKED.
        res1 = api.apply_liveaboard(
            tenant["id"],
            {"marina_id": marina["id"]},
            make_tenant_headers(tenant["id"]),
        )
        d1 = validate_success(res1, expected_status=200)
        assert d1["liveaboard_status"] == "PENDING"
        # Approve again — the cycle closes.
        res2 = api.approve_liveaboard(
            tenant["id"],
            {"marina_id": marina["id"]},
            TEST_USERS["harbor_master_headers"],
        )
        d2 = validate_success(res2, expected_status=200)
        assert d2["liveaboard_status"] == "APPROVED"


class TestSlipBranchesToAvailableOrOutOfService:
    """Slip.status branches from AVAILABLE: one outgoing edge to OUT_OF_SERVICE
    via decommission (terminal), confirming the machine is not a linear chain.
    """

    def test_decommission_from_available_transitions_slip_to_out_of_service(self, api):
        """PRD §3.1: "A slip's lifecycle runs `AVAILABLE → RESERVED → OCCUPIED → AVAILABLE` for routine business, with a terminal `OUT_OF_SERVICE` branch reachable from `AVAILABLE` via decommissioning."
        PRD §3.1: "A successful decommission sets the slip's `status` to `OUT_OF_SERVICE` and bumps its `version`."

        Design: Difficulty/non_linear_state_machine/slip_branches_to_available_or_out_of_service
        """
        marina = create_marina(liveaboard_cap=1)
        slip = create_slip(
            marina["id"],
            slip_number="F-1",
            length_ft=40,
            beam_ft=12,
            power_amp="A30",
            base_daily_rate_cents=4000,
        )
        res = api.decommission_slip(slip["id"], TEST_USERS["harbor_master_headers"])
        data = validate_success(res, expected_status=200)
        assert data["status"] == "OUT_OF_SERVICE", \
            f"decommission -> OUT_OF_SERVICE, got {data['status']}"

    def test_decommission_bumps_slip_version(self, api):
        """PRD §3.1: "A successful decommission sets the slip's `status` to `OUT_OF_SERVICE` and bumps its `version`."

        Design: Difficulty/non_linear_state_machine/slip_branches_to_available_or_out_of_service
        """
        marina = create_marina(liveaboard_cap=1)
        slip = create_slip(
            marina["id"],
            slip_number="F-2",
            length_ft=40,
            beam_ft=12,
            power_amp="A30",
            base_daily_rate_cents=4000,
        )
        v0 = slip["version"]
        res = api.decommission_slip(slip["id"], TEST_USERS["harbor_master_headers"])
        data = validate_success(res, expected_status=200)
        assert data["version"] == v0 + 1, \
            f"version must bump by 1 on decommission: {v0} -> {v0 + 1}, got {data['version']}"
