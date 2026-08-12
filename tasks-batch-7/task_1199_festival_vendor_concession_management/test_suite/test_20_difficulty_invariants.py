"""Difficulty: compensating_invariant — zone amps conservation; settlement money conservation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_settlement_conservation,
    create_settlement,
    finalize_settlement,
    get_booth,
    get_zone,
    issue_fine,
    make_vendor_headers,
    move_to_settlement_phase,
    reconcile_settlement,
    release_assignment,
    report_sale,
    respond_fine,
    setup_active_assignment,
    setup_reserved_assignment,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["ops_headers"]


class TestZoneConservation:
    def test_assign_then_release_returns_zone_to_baseline(self, api):
        """PRD §3.1: "`reserved_power_amps`, the sum of `power_draw_amps` over the
        zone's assignments in `RESERVED`, `CONFIRMED`, or `ACTIVE`, and
        `reserved_water_hookups`, the count of those assignments whose
        `requires_water` is true; assignments in `RELEASED`, `FORFEITED`, or
        `COMPLETED` never count."
        PRD §3.3: "Releasing an assignment from `RESERVED` or `CONFIRMED` moves
        it to `RELEASED`, returns the booth to `AVAILABLE`, decrements the zone's
        reserved totals".

        Design: Difficulty/compensating_invariant/zone_power_conservation_assign_release
        """
        scen = setup_reserved_assignment(
            name="Conserve Fest", draw=45, water=True,
            requires_water=True, booth_overrides={"has_water_hookup": True},
        )
        zone_id, booth_id = scen["zone"]["id"], scen["booth"]["id"]
        assert scen["zone"]["reserved_power_amps"] == 0
        assert scen["zone"]["reserved_water_hookups"] == 0

        zone = get_zone(zone_id)
        assert zone["reserved_power_amps"] == 45 and zone["reserved_water_hookups"] == 1
        assert get_booth(booth_id)["status"] == "RESERVED"

        release_assignment(scen["assignment"]["id"])
        zone = get_zone(zone_id)
        assert zone["reserved_power_amps"] == 0 and zone["reserved_water_hookups"] == 0, (
            "compensated exactly to baseline — zero drift"
        )
        assert get_booth(booth_id)["status"] == "AVAILABLE"

    def test_release_compensation_is_not_rerunnable(self, api):
        """PRD §2.10: "Eighth, state-machine legality of the requested transition,
        including terminal-state lockdown, together with request-shape validity —
        missing required fields, malformed values, and enum violations surface as
        `ERR_INVALID_REQUEST` (HTTP 400), while an illegal transition surfaces as
        `ERR_INVALID_STATE_TRANSITION` (HTTP 409) (8)."
        PRD §3.3: "Releasing an assignment from `RESERVED` or `CONFIRMED` moves
        it to `RELEASED`".

        Design: Difficulty/compensating_invariant/zone_power_conservation_assign_release
        """
        scen = setup_reserved_assignment(name="Conserve Fest", draw=45, water=True,
                                         requires_water=True,
                                         booth_overrides={"has_water_hookup": True})
        release_assignment(scen["assignment"]["id"])
        assert get_zone(scen["zone"]["id"])["reserved_power_amps"] == 0
        resp = api.release_assignment(scen["assignment"]["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_zone(scen["zone"]["id"])["reserved_power_amps"] == 0, "no double-decrement"


def _setup_money_conservation():
    """ACTIVE REVENUE_SHARE 1000bp MARGINAL assignment with two 100000-cent
    sales; settlement reconciled (fin-1); a 25000-cent fine ACKNOWLEDGED."""
    scen = setup_active_assignment(
        name="Money Fest", fee_model="REVENUE_SHARE",
        terms={"revenue_share_pct_bp": 1000, "tier_mode": "MARGINAL"},
    )
    asg_id = scen["assignment"]["id"]
    report_sale(asg_id, scen["vendor"], 100000, "mc1")
    report_sale(asg_id, scen["vendor"], 100000, "mc2", occurred_at="2026-07-10T15:00:00Z")
    stl = create_settlement(asg_id)
    scen["settlement"] = reconcile_settlement(stl["id"])
    fine = issue_fine(asg_id, type="WASTE_SORTING", amount_cents=25000)
    respond_fine(fine["id"], scen["vendor"], "ACKNOWLEDGED")
    return scen


class TestMoneyConservation:
    def test_gross_conserved_across_dispute_cycle(self, api):
        """PRD §3.6: "A vendor who disagrees with a reconciliation disputes it,
        moving the settlement from `RECONCILING` to `DISPUTED`; the caller must
        own the settlement's vendor (`ERR_NOT_RESOURCE_OWNER`) and supplies a
        `reason`, which is recorded as `dispute_reason`. The loop back to
        `RECONCILING` is another reconcile."

        Design: Difficulty/compensating_invariant/settlement_money_conservation_through_dispute_cycle
        """
        scen = _setup_money_conservation()
        stl = scen["settlement"]
        assert stl["provisional_gross_cents"] == 200000, "before the loop"

        disputed = validate_success(
            api.dispute_settlement(stl["id"], {"reason": "audit"},
                                   make_vendor_headers(scen["vendor"]["id"]))
        )
        assert disputed["status"] == "DISPUTED"
        rec = reconcile_settlement(stl["id"])
        assert rec["provisional_gross_cents"] == 200000, (
            "the dispute loop mutates no transactions — gross is conserved"
        )

    def test_final_figures_obey_the_conservation_identity(self, api):
        """PRD §3.6: "Net after share is gross minus share and may be negative;
        the deductions actually applied are the lesser of the fine deduction and
        the positive part of net after share; `vendor_payout_cents` is the
        positive part of net after share minus the deductions applied; and
        `vendor_balance_due_cents` — the amount the vendor still owes the
        festival — is the positive part of share plus fine deductions minus
        gross. Consequently, gross plus balance due always equals share plus
        payout plus deductions applied, exactly."

        Design: Difficulty/compensating_invariant/settlement_money_conservation_through_dispute_cycle
        """
        scen = _setup_money_conservation()
        stl = scen["settlement"]
        validate_success(
            api.dispute_settlement(stl["id"], {"reason": "audit"},
                                   make_vendor_headers(scen["vendor"]["id"]))
        )
        reconcile_settlement(stl["id"])
        move_to_settlement_phase(scen)
        fin = finalize_settlement(stl["id"])
        assert fin["gross_sales_cents"] == 200000
        assert fin["festival_share_cents"] == 20000
        assert fin["fine_deduction_cents"] == 25000
        assert fin["vendor_payout_cents"] == 155000
        assert fin["vendor_balance_due_cents"] == 0
        assert_settlement_conservation(200000, 20000, 155000, 0, 25000)
