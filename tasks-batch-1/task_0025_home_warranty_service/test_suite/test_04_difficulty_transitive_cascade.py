"""Difficulty Rule 4 — transitive_cascade.

Depth-4 cascade from /dispatches/{id}/complete (stamps CoveredItem → next
/claims/{id}/dispatch reads it to pin is_return_visit → service_fee_charged_cents
follows from that pin → /claims/{id}/resolve reads the pinned SF into final_copay).
Plus a depth-2 cascade from /claims/{id}/resolve into the parent Contract aggregates.
"""
from test_helpers import (
    get_success_data,
    set_clock,
    setup_active_contract_with_item,
    file_claim,
    assess_claim,
    dispatch_claim,
    resolve_claim,
    get_dispatch_for_claim,
    start_dispatch,
    complete_dispatch,
    make_admin_headers,
    make_customer_headers,
)


_ADMIN = make_admin_headers()


class TestDispatchCompletePropagatesToNextClaimFinalCopay:
    """Cascade depth 4 from /dispatches/{d1}/complete."""

    def test_completion_stamps_covered_item_then_drives_return_visit_pin(self, api):
        """PRD §3.5: "A successful repair completes the dispatch (`IN_PROGRESS →
        COMPLETED`), which stamps `completed_utc` on the dispatch to the current clock,
        copies that timestamp into the parent covered item's `last_dispatch_completed_utc`,
        and writes the completing dispatch's `id` into the covered item's `last_dispatch_id`."
        PRD §3.5: "If the current clock is strictly earlier than that boundary,
        `is_return_visit` is pinned to true and `prior_dispatch_id` is pinned to the
        covered item's current `last_dispatch_id` — the dispatch that began the window."

        Design: Difficulty/transitive_cascade/dispatch_complete_propagates_to_next_claim_final_copay
        """
        # Build a setup with two sequential claims on the same item.
        package, customer, contract, item = setup_active_contract_with_item(
            activate_at="2026-01-01T00:00:00Z",
        )
        cust_h = make_customer_headers(customer["id"])
        # First claim: file → assess → dispatch → start. Then complete inside the test.
        c1 = file_claim(contract, customer, item, issue="First failure")
        assess_claim(c1, 20_000)
        set_clock("2026-02-01T08:00:00Z")
        dispatch_claim(c1, "tech-A", "2026-02-01T09:00:00Z")
        d1 = get_dispatch_for_claim(c1["id"])
        set_clock("2026-02-01T09:30:00Z")
        start_dispatch(d1)

        # ---- Trigger: complete d1, then dispatch a SECOND claim and watch the cascade.
        set_clock("2026-02-01T10:00:00Z")
        complete_dispatch(d1)
        # Link 1: completing the dispatch stamps the parent CoveredItem.
        item_after = get_success_data(api.get_covered_item(item["id"], _ADMIN))
        assert item_after["last_dispatch_completed_utc"] is not None, (
            "CoveredItem.last_dispatch_completed_utc must be stamped on dispatch complete"
        )
        # File a second claim on the same item, dispatched within the 30-day window.
        set_clock("2026-02-10T12:00:00Z")
        c2 = file_claim(contract, customer, item, issue="Same again")
        assess_claim(c2, 18_000)
        dispatched2 = dispatch_claim(c2, "tech-B", "2026-02-10T15:00:00Z")
        # Link 2: is_return_visit reads the stamped field on the CoveredItem.
        assert dispatched2["is_return_visit"] is True
        # Link 3: service_fee_charged_cents pinned to 0 because of the return-visit pin.
        assert dispatched2["service_fee_charged_cents"] == 0

    def test_resolve_uses_pinned_service_fee_to_drive_final_copay(self, api):
        """PRD §3.7: "The final co-pay uses the Trip Charge that was pinned at dispatch
        — the claim's `service_fee_charged_cents`, which is zero when `is_return_visit`
        is true and equals the package's `service_fee_cents` otherwise."
        PRD §3.7: "Return visit, under cap. When `is_return_visit` is true and the
        actual repair amount is at most `copay_cap_cents`, the final co-pay is zero:
        the Trip Charge is waived and there is no excess to share."

        Design: Difficulty/transitive_cascade/dispatch_complete_propagates_to_next_claim_final_copay
        """
        package, customer, contract, item = setup_active_contract_with_item(
            activate_at="2026-01-01T00:00:00Z",
        )
        c1 = file_claim(contract, customer, item, issue="First")
        assess_claim(c1, 20_000)
        set_clock("2026-02-01T08:00:00Z")
        dispatch_claim(c1, "tech-A", "2026-02-01T09:00:00Z")
        d1 = get_dispatch_for_claim(c1["id"])
        set_clock("2026-02-01T09:30:00Z")
        start_dispatch(d1)
        set_clock("2026-02-01T10:00:00Z")
        complete_dispatch(d1)
        # Second claim within window, R = 18000 <= C = 25000 (under cap, return visit).
        set_clock("2026-02-10T12:00:00Z")
        c2 = file_claim(contract, customer, item, issue="Second")
        assess_claim(c2, 18_000)
        dispatch_claim(c2, "tech-B", "2026-02-10T15:00:00Z")
        d2 = get_dispatch_for_claim(c2["id"])
        set_clock("2026-02-10T15:30:00Z")
        start_dispatch(d2)
        complete_dispatch(d2)
        resolved = resolve_claim(c2, 18_000)
        # Link 4: final_copay reads pinned SF=0; R<=C ⇒ final = 0.
        assert resolved["final_copay_cents"] == 0


class TestClaimResolveRecomputesContractAggregates:
    """Cascade depth 2: /claims/{id}/resolve → parent Contract.total_paid_out_cents
    and Contract.claims_in_period_count both update. PRD §2.9, §2.10, §3.6."""

    def test_resolve_updates_total_paid_out_cents(self, api):
        """PRD §3.6: "On resolution, the server updates `repair_cost_cents` to
        `actual_repair_cost_cents`, computes the final co-pay (see §3.7), and
        recomputes the parent contract's `total_paid_out_cents` and `claims_in_period_count`."
        PRD §2.9: "A claim that has been resolved contributes to `total_paid_out_cents`
        the difference between its final `repair_cost_cents` and its `final_copay_cents`,
        which represents the portion the warranty paid."

        Design: Difficulty/transitive_cascade/claim_resolve_recomputes_contract_aggregates
        """
        package, customer, contract, item = setup_active_contract_with_item(
            activate_at="2026-01-01T00:00:00Z",
            category="OVEN",
        )
        claim = file_claim(contract, customer, item, issue="No heat")
        assess_claim(claim, 20_000)
        set_clock("2026-02-01T08:00:00Z")
        dispatch_claim(claim, "tech-Q", "2026-02-01T09:00:00Z")
        d = get_dispatch_for_claim(claim["id"])
        set_clock("2026-02-01T09:30:00Z")
        start_dispatch(d)
        complete_dispatch(d)
        # Before resolve.
        pre = get_success_data(api.get_contract(contract["id"], _ADMIN))
        assert pre["total_paid_out_cents"] == 0
        # Resolve at R=20000; first visit under cap → final_copay = SF = 7500.
        resolve_claim(claim, 20_000)
        post = get_success_data(api.get_contract(contract["id"], _ADMIN))
        # warranty paid = R - final = 20000 - 7500 = 12500.
        assert post["total_paid_out_cents"] == 12_500

    def test_resolve_keeps_claims_in_period_count_consistent(self, api):
        """PRD §3.6: "recomputes the parent contract's `total_paid_out_cents` and
        `claims_in_period_count`."
        PRD §2.10: "The contract's `claims_in_period_count` counts every `ClaimTicket`
        on the contract whose `status` is any of `SUBMITTED`, `ASSESSED`, `DISPATCHED`,
        `RESOLVED`, or `REJECTED` and whose `created_at` falls inside the same half-open window."

        Design: Difficulty/transitive_cascade/claim_resolve_recomputes_contract_aggregates
        """
        package, customer, contract, item = setup_active_contract_with_item(
            activate_at="2026-01-01T00:00:00Z",
            category="HVAC",
        )
        claim = file_claim(contract, customer, item, issue="Test")
        # After filing the count includes this claim (SUBMITTED is in the set).
        mid = get_success_data(api.get_contract(contract["id"], _ADMIN))
        assert mid["claims_in_period_count"] == 1
        assess_claim(claim, 20_000)
        set_clock("2026-02-01T08:00:00Z")
        dispatch_claim(claim, "tech-Q2", "2026-02-01T09:00:00Z")
        d = get_dispatch_for_claim(claim["id"])
        set_clock("2026-02-01T09:30:00Z")
        start_dispatch(d)
        complete_dispatch(d)
        resolve_claim(claim, 20_000)
        post = get_success_data(api.get_contract(contract["id"], _ADMIN))
        # Same ClaimTicket transitioning through statuses; count stays at 1.
        assert post["claims_in_period_count"] == 1
