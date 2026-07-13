"""Derelict-vessel enforcement: estimated vs actual cost, the RESOLVED/IMPOUNDED
branch fork, and the impound → revoke → berth-release → waitlist-promotion cascade."""
from test_helpers import (
    validate_success,
    TEST_USERS,
    set_clock,
    create_marina,
    create_boater,
    create_vessel,
    apply_permit,
    setup_active_permit,
    setup_served_derelict,
    get_invoice,
    get_permit,
    get_vessel,
    get_berth,
)

HARBOR = TEST_USERS["harbormaster_headers"]


class TestDerelictCostVariants:
    def _serve(self, api):
        set_clock(api, "2026-06-01T00:00:00Z")
        create_marina(api)
        boater = create_boater(api, full_name="Dana D", email="dana@example.com")
        vessel = create_vessel(api, boater["id"], length_ft=26, has_holding_tank=False)
        served = setup_served_derelict(api, "2026-06-01T00:00:00Z", vessel["id"])
        return served

    def test_estimated_cost_is_flat_notice_fee_at_serve(self, api):
        """PRD §3.8: "The estimate at notice is a flat notice fee of 15,000 cents,
        with no tow or storage charges."

        Design: Difficulty/dual_variant_calc/derelict_cost_estimated_vs_actual
        """
        served = self._serve(api)
        report = served["report"]
        assert report["estimated_cost_cents"] == 15000
        assert report["status"] == "NOTICE_SERVED"

    def test_actual_cost_adds_tow_and_storage_at_impound(self, api):
        """PRD §3.8: "the actual cost is the 15,000-cent notice fee plus a
        40,000-cent tow fee plus a per-day storage charge of 3,000 cents for each
        storage day, where storage days is the number of whole days between
        `notice_served_date` and `closed_date`, taken as zero if that difference
        would be negative, rounded up to a whole day."
        PRD §3.8: "The `DERELICT` invoice's `amount_due_cents` is raised from the
        estimate to this actual cost."

        Design: Difficulty/dual_variant_calc/derelict_cost_estimated_vs_actual
        """
        served = self._serve(api)
        set_clock(api, "2026-06-11T00:00:00Z")  # 10 storage days
        data = validate_success(
            api.close_report(served["report"]["id"], {"disposition": "IMPOUNDED"}, HARBOR)
        )
        # 15000 + 40000 + 3000*10 = 85000
        assert data["actual_cost_cents"] == 85000
        assert data["status"] == "IMPOUNDED"
        invoice = get_invoice(api, served["invoice_id"])
        assert invoice["amount_due_cents"] == 85000


class TestDerelictBranchFork:
    def _two_served_reports(self, api):
        set_clock(api, "2026-06-01T00:00:00Z")
        create_marina(api)
        boater = create_boater(api, full_name="Owner A", email="ownera@example.com")
        vessel_a = create_vessel(api, boater["id"], length_ft=22, has_holding_tank=False)
        vessel_b = create_vessel(api, boater["id"], length_ft=22, has_holding_tank=False)
        served_a = setup_served_derelict(api, "2026-06-01T00:00:00Z", vessel_a["id"])
        served_b = setup_served_derelict(api, "2026-06-01T00:00:00Z", vessel_b["id"])
        return vessel_a, vessel_b, served_a, served_b

    def test_resolved_branch_leaves_vessel_registered(self, api):
        """PRD §3.8: "Closing as `RESOLVED` — the owner having cured the problem
        — advances the report from `NOTICE_SERVED` to the terminal `RESOLVED`
        state, stamps its `closed_date`, and changes nothing about the vessel or
        any permit; the `DERELICT` invoice remains payable."

        Design: Difficulty/non_linear_state_machine/derelict_report_branch_resolved_vs_impounded
        """
        vessel_a, _, served_a, _ = self._two_served_reports(api)
        data = validate_success(
            api.close_report(served_a["report"]["id"], {"disposition": "RESOLVED"}, HARBOR)
        )
        assert data["status"] == "RESOLVED"
        assert get_vessel(api, vessel_a["id"])["registration_status"] == "REGISTERED"

    def test_impounded_branch_revokes_vessel_registration(self, api):
        """PRD §3.8: "An impound then sets off a cascade: the vessel's
        `registration_status` becomes `REVOKED`; because of that, any `ACTIVE` or
        `SUSPENDED` permit on the vessel is revoked with its refund computed; that
        permit's berth moves from `OCCUPIED` to `AVAILABLE` with occupancy
        recomputed; and the freed berth in turn triggers waitlist promotion, which
        may offer the berth to the next ranked `WAITLISTED` permit."

        Design: Difficulty/non_linear_state_machine/derelict_report_branch_resolved_vs_impounded
        """
        _, vessel_b, _, served_b = self._two_served_reports(api)
        data = validate_success(
            api.close_report(served_b["report"]["id"], {"disposition": "IMPOUNDED"}, HARBOR)
        )
        assert data["status"] == "IMPOUNDED"
        assert get_vessel(api, vessel_b["id"])["registration_status"] == "REVOKED"


class TestImpoundCascade:
    def _setup_cascade(self, api):
        b1 = setup_active_permit(
            api, clock="2026-05-15T00:00:00Z", vessel_overrides={"length_ft": 30}
        )
        marina_id = b1["marina"]["id"]
        berth_id = b1["berth"]["id"]
        boater2 = create_boater(api, full_name="Holder Two", email="h2@example.com")
        vessel2 = create_vessel(api, boater2["id"], length_ft=28)
        permit2 = apply_permit(api, marina_id, boater2["id"], vessel2["id"])
        served = setup_served_derelict(api, "2026-05-15T00:00:00Z", b1["vessel"]["id"])
        validate_success(
            api.close_report(served["report"]["id"], {"disposition": "IMPOUNDED"}, HARBOR)
        )
        return b1, berth_id, permit2

    def test_impound_revokes_vessel_and_its_active_permit(self, api):
        """PRD §3.8: "An impound then sets off a cascade: the vessel's
        `registration_status` becomes `REVOKED`; because of that, any `ACTIVE` or
        `SUSPENDED` permit on the vessel is revoked with its refund computed; that
        permit's berth moves from `OCCUPIED` to `AVAILABLE` with occupancy
        recomputed; and the freed berth in turn triggers waitlist promotion, which
        may offer the berth to the next ranked `WAITLISTED` permit."

        Design: Difficulty/transitive_cascade/derelict_impound_revoke_release_promote_depth4
        """
        b1, _, _ = self._setup_cascade(api)
        assert get_vessel(api, b1["vessel"]["id"])["registration_status"] == "REVOKED"
        assert get_permit(api, b1["permit"]["id"])["status"] == "REVOKED"

    def test_freed_berth_promotes_waitlisted_permit_to_offered(self, api):
        """PRD §3.5: "The winning permit moves from `WAITLISTED` to `OFFERED`: it
        is assigned the freed berth, the berth moves to `RESERVED`, its provisional
        fee is computed and a `PERMIT` invoice issued `UNPAID`, `offer_expires_at`
        is set, and `waitlist_length` falls by one."

        Design: Difficulty/transitive_cascade/derelict_impound_revoke_release_promote_depth4
        """
        _, berth_id, permit2 = self._setup_cascade(api)
        promoted = get_permit(api, permit2["id"])
        assert promoted["status"] == "OFFERED"
        assert promoted["berth_id"] == berth_id
        assert get_berth(api, berth_id)["status"] == "RESERVED"
