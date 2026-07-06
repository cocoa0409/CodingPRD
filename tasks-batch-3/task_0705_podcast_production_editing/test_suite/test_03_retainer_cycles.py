"""Retainer cycle reconciliation: provisional projection vs final close (waterfall),
projection non-persistence, cycle-window overlap, and close validation.
Covers difficulty rules dual_variant_calc (retainer), resource_temporal_overlap (cycle).
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    make_producer_eng_headers,
    make_platform_admin_headers,
    ApiErrorId,
    create_show_with_active_contract,
    create_engineer,
    create_retainer_cycle_payload,
    drive_episode_to_scheduled,
    drive_episode_to_published,
    setup_retainer_cycle,
)

ADMIN = make_platform_admin_headers()


class TestRetainerReconciliationVariants:
    def test_projection_overcounts_then_close_authoritative(self, api):
        """PRD §3.8: "The provisional variant is a forward-looking projection that does
        not persist anything: its eligible set includes episodes in SCHEDULED or
        PUBLISHED status ... and it tends to over-count relative to the final figure. The
        final variant runs at cycle close and is authoritative: its eligible set includes
        only episodes in PUBLISHED status with a non-null published_at inside the window."
        PRD §3.8: "included_consumed is the smaller of the eligible count and the
        contract's monthly_included_episodes; overage_episode_count is the eligible count
        minus monthly_included_episodes, never below zero"

        Design: Difficulty/dual_variant_calc/retainer_reconciliation_projection_vs_close_diverge_on_cycle
        """
        show, contract, cycle, engineer = setup_retainer_cycle(
            monthly_included_episodes=2, tier="STANDARD")
        # Two PUBLISHED episodes in window + one SCHEDULED (not published).
        drive_episode_to_published(
            show, contract, engineer, record_start="2026-03-05T08:00:00Z",
            record_end="2026-03-05T09:00:00Z", title="P1")
        drive_episode_to_published(
            show, contract, engineer, record_start="2026-03-06T08:00:00Z",
            record_end="2026-03-06T09:00:00Z", title="P2")
        drive_episode_to_scheduled(
            show, contract, engineer, record_start="2026-03-07T08:00:00Z",
            record_end="2026-03-07T09:00:00Z", title="P3")

        proj = get_success_data(api_client.retainer_cycle_projection(cycle["id"], ADMIN))
        assert proj["overage_episode_count"] == 1, (
            f"provisional counts 2 PUBLISHED + 1 SCHEDULED = 3 eligible, included 2 -> "
            f"overage 1, got {proj['overage_episode_count']}")

        closed = validate_success(api_client.close_retainer_cycle(cycle["id"], ADMIN))
        assert closed["overage_episode_count"] == 0, (
            f"final counts only 2 PUBLISHED, included 2 -> overage 0, "
            f"got {closed['overage_episode_count']}")
        assert closed["included_consumed"] == 2, (
            f"included_consumed == 2 at close, got {closed['included_consumed']}")

    def test_close_with_overage_issues_overage_invoice(self, api):
        """PRD §3.8: "when the overage count is greater than zero, it creates and issues a
        RETAINER_OVERAGE invoice (recording show_id and retainer_cycle_id, with episode_id
        null and kind RETAINER_OVERAGE) whose subtotal is the overage subtotal above"
        PRD §3.8: "the overage subtotal is the overage count multiplied by the tier's
        overage rate — 12000 cents for STANDARD, 16000 cents for PRIORITY, and 22000 cents
        for RUSH."

        Design: Difficulty/dual_variant_calc/retainer_reconciliation_projection_vs_close_diverge_on_cycle
        """
        show, contract, cycle, engineer = setup_retainer_cycle(
            monthly_included_episodes=2, tier="STANDARD")
        # Three PUBLISHED episodes in window -> included 2, overage 1 at close.
        for i, day in enumerate(("05", "06", "07")):
            drive_episode_to_published(
                show, contract, engineer,
                record_start=f"2026-03-{day}T08:00:00Z",
                record_end=f"2026-03-{day}T09:00:00Z", title=f"R{i}")

        closed = validate_success(api_client.close_retainer_cycle(cycle["id"], ADMIN))
        assert closed["status"] == "CLOSED"
        assert closed["included_consumed"] == 2
        assert closed["overage_episode_count"] == 1, (
            f"3 published, included 2 -> overage 1, got {closed['overage_episode_count']}")

        invoices = get_success_data(api_client.list_invoices(
            ADMIN, params={"retainer_cycle_id": cycle["id"]}))
        overage = [inv for inv in invoices if inv["kind"] == "RETAINER_OVERAGE"]
        assert len(overage) == 1, "close with overage issues one RETAINER_OVERAGE invoice"
        assert overage[0]["subtotal_cents"] == 12000, (
            f"1 overage * STANDARD 12000, got {overage[0]['subtotal_cents']}")

    def test_projection_read_does_not_persist(self, api):
        """PRD §3.8: "A projection of the same numbers may be obtained at any time without
        closing, via the provisional variant, and that read does not persist."

        Design: Corner/endpoints/retainer_projection_computed_read_does_not_persist
        """
        show, contract, cycle, engineer = setup_retainer_cycle(
            monthly_included_episodes=2, tier="STANDARD")
        proj = get_success_data(api_client.retainer_cycle_projection(cycle["id"], ADMIN))
        assert proj["overage_episode_count"] == 0, (
            f"no eligible episodes -> overage 0, got {proj['overage_episode_count']}")

        after = get_success_data(api_client.get_retainer_cycle(cycle["id"], ADMIN))
        assert after["status"] == "OPEN", (
            f"projection must not close the cycle, got {after['status']}")


class TestRetainerCycleWindowOverlap:
    def test_overlapping_cycle_same_contract_rejected(self, api):
        """PRD §3.8: "The new window must not overlap any existing cycle of the same
        contract in any status; overlap is judged on the half-open interval, so touching
        windows (the earlier cycle's end equal to the later cycle's start) are allowed
        with no buffer, but any true overlap is rejected with ERR_CYCLE_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/retainer_cycle_window_overlap_same_contract
        """
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="RETAINER", billing_model="RETAINER",
            monthly_included_episodes=2)
        get_success_data(api_client.create_retainer_cycle(
            create_retainer_cycle_payload(contract["id"],
                                          "2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z"),
            ADMIN))
        # Touching window [04-01, 05-01) — earlier.end == later.start — allowed.
        touch = validate_success(api_client.create_retainer_cycle(
            create_retainer_cycle_payload(contract["id"],
                                          "2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z"),
            ADMIN), expected_status=201)
        assert touch["status"] == "OPEN"

        # Overlapping window [03-15, 04-15) — true overlap with first cycle.
        resp = api_client.create_retainer_cycle(
            create_retainer_cycle_payload(contract["id"],
                                          "2026-03-15T00:00:00Z", "2026-04-15T00:00:00Z"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_CYCLE_OVERLAP.value)

    def test_touching_cycle_window_allowed(self, api):
        """PRD §3.8: "touching windows (the earlier cycle's end equal to the later cycle's
        start) are allowed with no buffer, but any true overlap is rejected with
        ERR_CYCLE_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/retainer_cycle_window_overlap_same_contract
        """
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="RETAINER", billing_model="RETAINER",
            monthly_included_episodes=2)
        get_success_data(api_client.create_retainer_cycle(
            create_retainer_cycle_payload(contract["id"],
                                          "2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z"),
            ADMIN))
        touch = validate_success(api_client.create_retainer_cycle(
            create_retainer_cycle_payload(contract["id"],
                                          "2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z"),
            ADMIN), expected_status=201)
        assert touch["status"] == "OPEN", "touch at endpoint allowed"
