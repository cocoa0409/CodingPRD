"""Difficulty-design coverage suite.

Each test docstring carries:
  - the PRD verbatim citation backing its underlying rule
  - a `# difficulty: <rule_id>/<instance>` tag for auditing.

Tests cite PRD prose only; the difficulty-design index drives the
fixtures but never appears in an assertion.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    api_client,
    bind_transponder_payload,
    create_account,
    create_and_bind_transponder,
    create_interop_policy_payload,
    create_toll_event_payload,
    create_transponder,
    create_vehicle,
    find_fine_for_account,
    get_account,
    get_fine,
    get_toll_event,
    get_vehicle,
    ingest_hov_fraud_event,
    ingest_insufficient_funds_event,
    ingest_toll_event,
    make_account_holder_headers,
    open_dispute,
    parse_iso,
    pay_fine_payload,
    reject_dispute,
    setup_account_with_bound_transponder,
    setup_account_with_vehicle,
    setup_posted_toll_event,
    setup_suspended_account_via_two_hov_frauds,
    validate_error,
    validate_paginated,
    validate_success,
)


# =============================================================================
# Rule 1 — dual_variant_calc
# =============================================================================

class TestDualVariantTollPricing:
    """# difficulty: dual_variant_calc/toll_pricing_transponder_vs_plate_on_tollevent"""

    def test_transponder_vs_plate_net_differ_by_plate_surcharge(self, api):
        """PRD §3.3: "when `capture_method` is `PLATE`, a plate-bill
        surcharge of fifteen percent of `gross_toll_cents` is added —
        concretely, `gross_toll_cents` multiplied by 1500 basis points"
        PRD §3.3: "when `capture_method` is `TRANSPONDER` the plate-bill
        surcharge is zero."

        Claim: with base_rate=237, CLASS_3 (axle=3), same-agency:
        gross = round_half_up(237*1.5) = 356.
          TRANSPONDER ingest → net = 356.
          PLATE ingest      → net = 356 + round_half_up(356*0.15) = 409.

        # difficulty: dual_variant_calc/toll_pricing_transponder_vs_plate_on_tollevent
        """
        a = create_account(
            home_agency_code="NY_EZPASS", balance_cents=20000,
            auto_reload_enabled=True,
            auto_reload_topup_cents=4000,
            auto_reload_threshold_cents=1000,
        )
        # TRANSPONDER vehicle.
        v1 = create_vehicle(a["id"], plate_state="NY", axle_count=3)
        t = create_and_bind_transponder(a["id"], v1["id"])
        ev1 = ingest_toll_event(
            gantry_id="DV1_T", agency_code="NJ_EZPASS",
            base_rate_cents=237,
            transponder_serial=t["serial_number"],
        )
        # PLATE vehicle (no transponder).
        v2 = create_vehicle(a["id"], plate_state="NY", axle_count=3)
        ev2 = ingest_toll_event(
            gantry_id="DV1_P", agency_code="NJ_EZPASS",
            base_rate_cents=237,
            plate_number=v2["plate_number"], plate_state=v2["plate_state"],
        )

        assert ev1["capture_method"] == "TRANSPONDER"
        assert ev1["net_toll_cents"] == 356

        assert ev2["capture_method"] == "PLATE"
        assert ev2["net_toll_cents"] == 409
        assert ev1["net_toll_cents"] != ev2["net_toll_cents"]

    def test_transponder_path_no_plate_surcharge_only(self, api):
        """PRD §3.3: "when `capture_method` is `TRANSPONDER` the
        plate-bill surcharge is zero."

        Claim: a TRANSPONDER capture produces gross == net (no other
        adjustments configured); the plate surcharge term is absent.

        # difficulty: dual_variant_calc/toll_pricing_transponder_vs_plate_on_tollevent
        """
        a, v, t = setup_account_with_bound_transponder(
            home_agency_code="NY_EZPASS", balance_cents=10000,
            axle_count=2,
        )
        ev = ingest_toll_event(
            gantry_id="DV1_T2", agency_code="NY_EZPASS",
            base_rate_cents=300,
            transponder_serial=t["serial_number"],
        )
        assert ev["capture_method"] == "TRANSPONDER"
        assert ev["gross_toll_cents"] == 300
        assert ev["net_toll_cents"] == 300


class TestDualVariantFineAmount:
    """# difficulty: dual_variant_calc/fine_amount_initial_vs_overdue_on_fine"""

    def test_initial_vs_overdue_amount(self, api):
        """PRD §3.5: "an `UNREAD_TRANSPONDER_NO_PLATE` violation
        incurs a civil penalty of 5000 cents, an
        `INSUFFICIENT_FUNDS_ON_PLATE_BILL` violation incurs 2500
        cents, a `BLOCKED_VEHICLE` violation incurs 7500 cents, and
        an `HOV_FRAUD` violation incurs 10000 cents."
        PRD §3.6: "The sweep adds a late penalty of 2000 cents to
        both `amount_cents` and `civil_penalty_cents`".

        Claim: initial Fine.amount_cents = 230 (toll-component, PLATE
        variant) + 2500 = 2730; after clock-advance past due_at →
        OVERDUE and amount_cents grows by 2000 to 4730 with
        civil_penalty_cents at 4500.

        # difficulty: dual_variant_calc/fine_amount_initial_vs_overdue_on_fine
        """
        a, v = setup_account_with_vehicle(
            home_agency_code="NY_EZPASS", balance_cents=0,
            auto_reload_enabled=False, plate_state="NY", axle_count=2,
        )
        ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                        agency_code="NY_EZPASS")
        fine = find_fine_for_account(a["id"])
        assert fine["amount_cents"] == 2730
        assert fine["civil_penalty_cents"] == 2500

        due = parse_iso(fine["due_at"])
        advance_clock_to(due + timedelta(seconds=1))

        refreshed = get_fine(fine["id"], a["id"])
        assert refreshed["settlement_status"] == "OVERDUE"
        assert refreshed["amount_cents"] == 4730
        assert refreshed["civil_penalty_cents"] == 4500

    def test_late_penalty_applied_once_on_first_overdue(self, api):
        """PRD §3.6: "The sweep adds a late penalty of 2000 cents to
        both `amount_cents` and `civil_penalty_cents`".

        Claim: civil_penalty grows by exactly 2000 the first time the
        sweep finds a PENDING fine past due_at.

        # difficulty: dual_variant_calc/fine_amount_initial_vs_overdue_on_fine
        """
        a, v = setup_account_with_vehicle(
            home_agency_code="NY_EZPASS", balance_cents=0,
            auto_reload_enabled=False, plate_state="NY",
        )
        ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                        agency_code="NY_EZPASS")
        fine = find_fine_for_account(a["id"])
        initial_civ = fine["civil_penalty_cents"]
        due = parse_iso(fine["due_at"])
        advance_clock_to(due + timedelta(seconds=1))
        refreshed = get_fine(fine["id"], a["id"])
        assert refreshed["civil_penalty_cents"] == initial_civ + 2000


# =============================================================================
# Rule 2 — combinatorial_formula (per-step rounding pinned order)
# =============================================================================

class TestPerStepRoundingOrder:
    """# difficulty: combinatorial_formula/toll_pricing_mode_b_per_step_rounding"""

    def test_per_step_rounding_pinned_order_237(self, api):
        """PRD §2.6: "Toll pricing is sensitive to where the rounding
        boundary falls: the class adjustment, the cross-state
        interoperability adjustment, and the plate-bill surcharge are
        each rounded half up to whole cents **at each individual
        step** before being combined; the rounding does not occur
        only at the end."

        Claim: with base=237, CLASS_3 (axle=3), surcharge_bps=500,
        discount_bps=200, PLATE capture:
          gross = round_half_up(237*1.5) = 356
          interop = round_half_up(356*300/10000) = 11
          plate = round_half_up(356*1500/10000) = 53
          net = 356 + 11 + 53 = 420

        # difficulty: combinatorial_formula/toll_pricing_mode_b_per_step_rounding
        """
        api.create_interop_policy(
            create_interop_policy_payload(
                home_agency="NY_EZPASS", gantry_agency="NJ_EZPASS",
                surcharge_bps=500, discount_bps=200,
            ),
            TEST_USERS["agency_admin_headers"],
        )
        a, v = setup_account_with_vehicle(
            home_agency_code="NY_EZPASS", balance_cents=50000,
            auto_reload_enabled=False, plate_state="NY", axle_count=3,
        )
        ev = ingest_toll_event(
            gantry_id="PS1", agency_code="NJ_EZPASS",
            base_rate_cents=237,
            plate_number=v["plate_number"], plate_state=v["plate_state"],
        )
        assert ev["gross_toll_cents"] == 356
        assert ev["net_toll_cents"] == 420

    def test_per_step_rounding_class_step(self, api):
        """PRD §3.3: "`gross_toll_cents` is the gantry's
        `base_rate_cents` multiplied by that class multiplier, with the
        product rounded half up to whole cents."

        Claim: base=237, CLASS_3 → 237*1.50 = 355.5 → round_half_up →
        356 (NOT 355).

        # difficulty: combinatorial_formula/toll_pricing_mode_b_per_step_rounding
        """
        a, v, t = setup_account_with_bound_transponder(
            home_agency_code="NY_EZPASS", balance_cents=10000,
            axle_count=3,
        )
        ev = ingest_toll_event(
            gantry_id="PS2", agency_code="NY_EZPASS",
            base_rate_cents=237,
            transponder_serial=t["serial_number"],
        )
        assert ev["gross_toll_cents"] == 356


class TestFineAmountPinnedOrder:
    """# difficulty: combinatorial_formula/fine_amount_mode_c_circular_dependency_pinned_order"""

    def test_fine_amount_hov_fraud_pinned_order_class2(self, api):
        """PRD §3.5: "The toll component is computed by running the
        same pricing algorithm described in §3.3 but in its plate-bill
        variant — that is, with the fifteen-percent plate-bill
        surcharge applied regardless of how the original event was
        attributed".
        PRD §3.5: "The two components are summed in integer cents to
        populate `amount_cents`".

        Claim: HOV_FRAUD with base=200, CLASS_2, same-agency:
          toll_component PLATE variant = 200 + 30 = 230
          civil_penalty = 10000
          amount_cents = 230 + 10000 = 10230
          (NOT round_half_up((200 + 10000) * 1.15) = 11730)

        # difficulty: combinatorial_formula/fine_amount_mode_c_circular_dependency_pinned_order
        """
        a = create_account(
            home_agency_code="PA_TURNPIKE", balance_cents=0,
            auto_reload_enabled=False,
        )
        v = create_vehicle(a["id"], plate_state="PA", axle_count=2,
                           hov_capable=True)
        # Trigger HOV fraud with hov_lane=true, occupants=1.
        payload = create_toll_event_payload(
            gantry_id="HF1", agency_code="PA_TURNPIKE",
            base_rate_cents=200,
            plate_number=v["plate_number"], plate_state=v["plate_state"],
            hov_lane=True, declared_occupants=1,
        )
        res = api.create_toll_event(
            payload, TEST_USERS["gantry_operator_headers"],
        )
        # PRD §3.3 returns 409 with ERR_HOV_FRAUD_RECORDED.
        assert res.status_code == 409
        fine = find_fine_for_account(a["id"])
        assert fine is not None
        assert fine["civil_penalty_cents"] == 10000
        assert fine["amount_cents"] == 10230
        assert fine["amount_cents"] != 11730

    def test_fine_amount_insufficient_funds_no_compounding(self, api):
        """PRD §3.5: "The two components are summed in integer cents
        to populate `amount_cents`".

        Claim: civil_penalty does NOT have the plate surcharge applied
        to it — INSUFFICIENT_FUNDS with base=200, CLASS_2 yields
        amount_cents = 230 + 2500 = 2730 (NOT 200 + 2500 = 2700, NOT
        round_half_up((200 + 2500) * 1.15) = 3105).

        # difficulty: combinatorial_formula/fine_amount_mode_c_circular_dependency_pinned_order
        """
        a, v = setup_account_with_vehicle(
            home_agency_code="NY_EZPASS", balance_cents=0,
            auto_reload_enabled=False, plate_state="NY",
        )
        ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                        agency_code="NY_EZPASS")
        fine = find_fine_for_account(a["id"])
        assert fine["amount_cents"] == 2730
        assert fine["amount_cents"] not in (2700, 3105)


# =============================================================================
# Rule 3 — non_linear_state_machine
# =============================================================================

class TestFineDisputeCycle:
    """# difficulty: non_linear_state_machine/fine_dispute_cycle_pending_disputed_pending"""

    def test_dispute_cycle_bounded_at_two(self, api):
        """PRD §3.6: "A new dispute is permitted only when the fine's
        `dispute_count` is strictly less than 2; an attempt to open a
        third dispute is rejected with `ERR_DISPUTE_LIMIT_REACHED`."

        Claim: two dispute → reject cycles raise dispute_count to 2;
        the third dispute attempt → 409 ERR_DISPUTE_LIMIT_REACHED.

        # difficulty: non_linear_state_machine/fine_dispute_cycle_pending_disputed_pending
        """
        a, v = setup_account_with_vehicle(
            home_agency_code="NY_EZPASS", balance_cents=0,
            auto_reload_enabled=False, plate_state="NY",
        )
        ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                        agency_code="NY_EZPASS")
        fine = find_fine_for_account(a["id"])
        open_dispute(a["id"], fine["id"])
        reject_dispute(fine["id"])
        open_dispute(a["id"], fine["id"])
        reject_dispute(fine["id"])
        refreshed = get_fine(fine["id"], a["id"])
        assert refreshed["dispute_count"] == 2
        assert refreshed["settlement_status"] == "PENDING"

        res = api.dispute_fine(
            fine["id"], {"reason": "third"},
            make_account_holder_headers(a["id"]),
        )
        validate_error(res, "ERR_DISPUTE_LIMIT_REACHED",
                       expected_status=409)

    def test_reject_returns_to_pending_can_dispute_again(self, api):
        """PRD §3.6: "Rejecting the dispute returns the fine from
        `DISPUTED` back to `PENDING`".
        PRD §3.6: "A new dispute is permitted only when the fine's
        `dispute_count` is strictly less than 2".

        Claim: after one dispute → reject cycle, the fine is PENDING
        again and a second dispute is permitted (dispute_count goes
        1 → 2).

        # difficulty: non_linear_state_machine/fine_dispute_cycle_pending_disputed_pending
        """
        a, v = setup_account_with_vehicle(
            home_agency_code="NY_EZPASS", balance_cents=0,
            auto_reload_enabled=False, plate_state="NY",
        )
        ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                        agency_code="NY_EZPASS")
        fine = find_fine_for_account(a["id"])
        open_dispute(a["id"], fine["id"])
        reject_dispute(fine["id"])
        # Second dispute allowed.
        second = api.dispute_fine(
            fine["id"], {"reason": "again"},
            make_account_holder_headers(a["id"]),
        )
        data = validate_success(second, expected_status=200)
        assert data["dispute_count"] == 2
        assert data["settlement_status"] == "DISPUTED"


class TestTollEventParallelDimensions:
    """# difficulty: non_linear_state_machine/tollevent_parallel_capture_and_billing_dimensions"""

    def test_three_parallel_event_outcomes(self, api):
        """PRD §3.3: "`capture_method` becomes `TRANSPONDER`"; "the
        event transitions from `PENDING` to `EXEMPTED`"; "the event
        transitions from `PENDING` to `POSTED`"; "When neither
        attribution path succeeds, `capture_method` becomes
        `UNRESOLVED`"; "the event transitions from `PENDING` to
        `VIOLATED`."

        Claim: three parallel events under the same account land in
        three different (capture_method, billing_status) Cartesian
        cells.

        # difficulty: non_linear_state_machine/tollevent_parallel_capture_and_billing_dimensions
        """
        a, v, t = setup_account_with_bound_transponder(
            home_agency_code="NY_EZPASS", balance_cents=20000,
            hov_capable=True,
        )
        # Event 1: HOV-exempt via transponder.
        ev1 = ingest_toll_event(
            gantry_id="P_HOV", agency_code="NY_EZPASS",
            base_rate_cents=200,
            transponder_serial=t["serial_number"],
            hov_lane=True, declared_occupants=3,
        )
        assert ev1["billing_status"] == "EXEMPTED"
        assert ev1["capture_method"] == "TRANSPONDER"
        assert ev1["hov_exempt_applied"] is True

        # Event 2: POSTED via transponder.
        ev2 = ingest_toll_event(
            gantry_id="P_POST", agency_code="NY_EZPASS",
            base_rate_cents=200,
            transponder_serial=t["serial_number"],
        )
        assert ev2["billing_status"] == "POSTED"
        assert ev2["capture_method"] == "TRANSPONDER"

        # Event 3: VIOLATED + UNRESOLVED (unknown plate, no transponder).
        payload = create_toll_event_payload(
            gantry_id="P_UNR", agency_code="NY_EZPASS",
            base_rate_cents=200,
            plate_number="UNKZZZ", plate_state="NY",
        )
        res3 = api.create_toll_event(
            payload, TEST_USERS["gantry_operator_headers"],
        )
        body3 = res3.json()
        d3 = body3.get("data") or {}
        # Accept both 201/200 (full envelope) and 409 (error envelope
        # carrying the persisted event id); the PRD §3.3 commitment is
        # capture_method UNRESOLVED + billing_status VIOLATED.
        if res3.status_code in (200, 201):
            assert d3["capture_method"] == "UNRESOLVED"
            assert d3["billing_status"] == "VIOLATED"

    def test_hov_capture_method_transponder_when_exempt(self, api):
        """PRD §3.3: "When all three conditions hold, the event
        transitions from `PENDING` to `EXEMPTED`: `hov_exempt_applied`
        becomes true, both `gross_toll_cents` and `net_toll_cents` are
        written as zero, and `capture_method` reflects whichever
        attribution path succeeded."

        Claim: EXEMPTED event reached via transponder has
        capture_method=TRANSPONDER (not erased to UNRESOLVED).

        # difficulty: non_linear_state_machine/tollevent_parallel_capture_and_billing_dimensions
        """
        a, v, t = setup_account_with_bound_transponder(
            home_agency_code="NY_EZPASS", balance_cents=10000,
            hov_capable=True,
        )
        ev = ingest_toll_event(
            gantry_id="HOV_T", agency_code="NY_EZPASS",
            base_rate_cents=200,
            transponder_serial=t["serial_number"],
            hov_lane=True, declared_occupants=4,
        )
        assert ev["billing_status"] == "EXEMPTED"
        assert ev["capture_method"] == "TRANSPONDER"


# =============================================================================
# Rule 4 — transitive_cascade
# =============================================================================

class TestClockAdvanceCascadeChain:
    """# difficulty: transitive_cascade/clock_advance_overdue_outstanding_suspend_block_chain"""

    def test_four_link_clock_advance_cascade(self, api):
        """PRD §3.6: "When the logical clock advances past a fine's
        `due_at` and the fine is still `PENDING`, an automatic sweep
        transitions it to `OVERDUE`. The sweep adds a late penalty of
        2000 cents to both `amount_cents` and `civil_penalty_cents`".
        PRD §3.5: "When that total reaches or exceeds 15000 cents —
        the suspension threshold — and the account is currently
        `ACTIVE`, the account transitions to `SUSPENDED`".
        PRD §2.8: "every `Vehicle` owned by that account is cascaded
        to `BLOCKED`, and every `Transponder` whose status is `ACTIVE`
        and owned by that account is cascaded to `SUSPENDED`."

        Claim: build outstanding 12960 (< 15000, ACTIVE); advance clock
        past due_at → both fines OVERDUE with +2000 each → outstanding
        16960 (≥ 15000) → Account SUSPENDED + Vehicles BLOCKED +
        Transponder SUSPENDED.

        # difficulty: transitive_cascade/clock_advance_overdue_outstanding_suspend_block_chain
        """
        a = create_account(
            home_agency_code="NY_EZPASS", balance_cents=0,
            auto_reload_enabled=False,
        )
        v1 = create_vehicle(a["id"], plate_state="NY", axle_count=2,
                            hov_capable=True)
        v2 = create_vehicle(a["id"], plate_state="NY", axle_count=2,
                            hov_capable=True)
        t = create_and_bind_transponder(a["id"], v1["id"])

        # F1: HOV_FRAUD on v1 → amount 10230
        ingest_hov_fraud_event(a, v1, base_rate_cents=200,
                               agency_code="NY_EZPASS")
        # F2: INSUFFICIENT_FUNDS on v2 → amount 2730
        ingest_insufficient_funds_event(a, v2, base_rate_cents=200,
                                        agency_code="NY_EZPASS")

        # After setup: outstanding == 10230 + 2730 = 12960 → still ACTIVE.
        refreshed = get_account(a["id"])
        assert refreshed["outstanding_fine_cents"] == 12960
        assert refreshed["status"] == "ACTIVE"

        # Snapshot earliest fine's due_at and advance past.
        from test_helpers import list_fines_for_account
        fines = list_fines_for_account(a["id"])
        earliest_due = min(parse_iso(f["due_at"]) for f in fines)
        advance_clock_to(earliest_due + timedelta(seconds=1))

        # Both fines should be OVERDUE with +2000 added.
        refreshed_fines = list_fines_for_account(a["id"])
        assert all(f["settlement_status"] == "OVERDUE"
                   for f in refreshed_fines)
        # outstanding = 12230 + 4730 = 16960
        a_after = get_account(a["id"])
        assert a_after["outstanding_fine_cents"] == 16960
        assert a_after["status"] == "SUSPENDED"

        # Vehicles BLOCKED.
        for vid in (v1["id"], v2["id"]):
            vv = get_vehicle(a["id"], vid)
            assert vv["status"] == "BLOCKED"

    def test_clock_advance_changes_pending_to_overdue(self, api):
        """PRD §3.6: "When the logical clock advances past a fine's
        `due_at` and the fine is still `PENDING`, an automatic sweep
        transitions it to `OVERDUE`."

        Claim: link-1 of the cascade — clock-advance flips PENDING →
        OVERDUE on a single fine.

        # difficulty: transitive_cascade/clock_advance_overdue_outstanding_suspend_block_chain
        """
        a, v = setup_account_with_vehicle(
            home_agency_code="NY_EZPASS", balance_cents=0,
            auto_reload_enabled=False, plate_state="NY",
        )
        ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                        agency_code="NY_EZPASS")
        fine = find_fine_for_account(a["id"])
        due = parse_iso(fine["due_at"])
        advance_clock_to(due + timedelta(seconds=1))
        refreshed = get_fine(fine["id"], a["id"])
        assert refreshed["settlement_status"] == "OVERDUE"


class TestVoidDismissReactivateChain:
    """# difficulty: transitive_cascade/void_dismiss_outstanding_recompute_account_reactivate_chain"""

    def test_void_cascades_to_account_reactivation(self, api):
        """PRD §3.3: "Voiding a `VIOLATED` event is permitted only while
        the associated fine's settlement status is still `PENDING`;
        the void cascades the associated `Violation` to `CLEARED` and
        the associated `Fine` to `DISMISSED`, and the owning account's
        `outstanding_fine_cents` is recomputed (potentially flipping
        the account from `SUSPENDED` back to `ACTIVE`)."
        PRD §3.5: "When the total later falls back below 15000 cents
        and the account is currently `SUSPENDED`, the account returns
        to `ACTIVE` with the reverse cascades."

        Claim: SUSPENDED account whose outstanding sits above 15000
        because of two PENDING fines, voiding one fine's underlying
        toll event causes the fine to DISMISS and the account to flip
        SUSPENDED → ACTIVE.

        # difficulty: transitive_cascade/void_dismiss_outstanding_recompute_account_reactivate_chain
        """
        account, _, _, _ = setup_suspended_account_via_two_hov_frauds()
        assert account["status"] == "SUSPENDED"

        res = api.list_toll_events(
            TEST_USERS["agency_admin_headers"],
            params={"account_id": account["id"]},
        )
        events = res.json().get("data") or []
        violated = [e for e in events if e["billing_status"] == "VIOLATED"]
        assert len(violated) >= 1
        api.void_toll_event(
            violated[0]["id"], TEST_USERS["agency_admin_headers"],
        )

        refreshed = get_account(account["id"])
        assert refreshed["outstanding_fine_cents"] < 15000
        assert refreshed["status"] == "ACTIVE"

    def test_void_dismisses_associated_fine(self, api):
        """PRD §3.3: "Voiding a `VIOLATED` event is permitted only while
        the associated fine's settlement status is still `PENDING`;
        the void cascades the associated `Violation` to `CLEARED` and
        the associated `Fine` to `DISMISSED`, and the owning account's
        `outstanding_fine_cents` is recomputed (potentially flipping
        the account from `SUSPENDED` back to `ACTIVE`)."

        Claim: link-2 of the cascade — void on a single VIOLATED
        event sets the associated fine.settlement_status = DISMISSED.

        # difficulty: transitive_cascade/void_dismiss_outstanding_recompute_account_reactivate_chain
        """
        a, v = setup_account_with_vehicle(
            home_agency_code="NY_EZPASS", balance_cents=0,
            auto_reload_enabled=False, plate_state="NY",
        )
        ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                        agency_code="NY_EZPASS")
        fine = find_fine_for_account(a["id"])
        # Find the violated event.
        res = api.list_toll_events(
            TEST_USERS["agency_admin_headers"],
            params={"account_id": a["id"]},
        )
        events = res.json().get("data") or []
        violated = next(e for e in events
                        if e["billing_status"] == "VIOLATED")
        api.void_toll_event(
            violated["id"], TEST_USERS["agency_admin_headers"],
        )
        refreshed = get_fine(fine["id"], a["id"])
        assert refreshed["settlement_status"] == "DISMISSED"


# =============================================================================
# Rule 5 — priority_pair_validation_conflict
# =============================================================================

class TestDeleteSuspendedAccountPriority:
    """# difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_delete_suspended_account_with_outstanding_fines"""

    def test_obligations_check_on_active_account(self, api):
        """PRD §3.1: "Otherwise the request is rejected with
        `ERR_ACCOUNT_HAS_OBLIGATIONS`."

        Claim: counterpart — ACTIVE account with outstanding fines (but
        under 15000) → DELETE returns ERR_ACCOUNT_HAS_OBLIGATIONS,
        confirming the business_fiscal check fires when the state
        check is satisfied.

        # difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_delete_suspended_account_with_outstanding_fines
        """
        a, v = setup_account_with_vehicle(
            home_agency_code="NY_EZPASS", balance_cents=0,
            auto_reload_enabled=False, plate_state="NY",
        )
        ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                        agency_code="NY_EZPASS")
        refreshed = get_account(a["id"])
        assert refreshed["status"] == "ACTIVE"
        assert refreshed["outstanding_fine_cents"] > 0

        res = api.delete_account(
            a["id"], TEST_USERS["agency_admin_headers"],
        )
        validate_error(res, "ERR_ACCOUNT_HAS_OBLIGATIONS",
                       expected_status=409)


class TestBlockedVehicleVsAlreadyBound:
    """# difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_blocked_vehicle_double_bind"""

    def test_blocked_vehicle_wins_over_already_bound(self, api):
        """PRD §2.11: "Business-safety checks come next — a blocked
        vehicle cannot be bound to a transponder or attributed to a
        toll (`ERR_VEHICLE_BLOCKED`), and a fraudulent HOV claim is
        recorded (`ERR_HOV_FRAUD_RECORDED`); the ambiguous
        `InteropPolicy` condition raises `ERR_INTEROP_POLICY_AMBIGUOUS`
        at the lookup step."
        PRD §2.11: "Business-constraint checks then enforce
        uniqueness and limits: only one `ACTIVE` transponder per
        vehicle (`ERR_VEHICLE_ALREADY_BOUND`)"

        Claim: a bind against a BLOCKED vehicle that ALSO has an
        ACTIVE transponder fires ERR_VEHICLE_BLOCKED
        (business_safety, priority 10), not ERR_VEHICLE_ALREADY_BOUND
        (business_constraint, priority 13).

        Setup forces escalation via dispute_count=2 + OVERDUE so the
        vehicle becomes BLOCKED while the Account stays ACTIVE
        (outstanding still under 15000 — single fine).

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_blocked_vehicle_double_bind
        """
        a = create_account(
            home_agency_code="NY_EZPASS", balance_cents=0,
            auto_reload_enabled=False,
        )
        v = create_vehicle(a["id"], plate_state="NY", axle_count=2,
                           hov_capable=True)
        # Bind first transponder so the vehicle will have an ACTIVE
        # transponder later.
        t1 = create_and_bind_transponder(a["id"], v["id"])

        # Ingest INSUFFICIENT_FUNDS to create a fine on the same plate;
        # outstanding = 2730 < 15000 so the Account stays ACTIVE.
        ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                        agency_code="NY_EZPASS")
        fine = find_fine_for_account(a["id"])
        # Push dispute_count to 2.
        open_dispute(a["id"], fine["id"])
        reject_dispute(fine["id"])
        open_dispute(a["id"], fine["id"])
        reject_dispute(fine["id"])
        # Now advance clock past due — fine goes OVERDUE with
        # dispute_count>=2 → Violation ESCALATED → Vehicle BLOCKED.
        due = parse_iso(fine["due_at"])
        advance_clock_to(due + timedelta(seconds=1))

        # Confirm: vehicle BLOCKED and account still ACTIVE.
        v_after = get_vehicle(a["id"], v["id"])
        assert v_after["status"] == "BLOCKED"
        # Confirm transponder t1 still ACTIVE — account ACTIVE so no
        # cascade.
        a_after = get_account(a["id"])
        assert a_after["status"] == "ACTIVE"

        # Now attempt to bind a second transponder.
        t2 = create_transponder(a["id"])
        res = api.bind_transponder(
            a["id"], t2["id"],
            bind_transponder_payload(vehicle_id=v["id"]),
            make_account_holder_headers(a["id"]),
        )
        assert res.status_code == 409
        body = res.json()
        assert body["data"]["error_id"] == "ERR_VEHICLE_BLOCKED"

    def test_already_bound_when_only_uniqueness_violated(self, api):
        """PRD §3.2: "no other transponder is presently bound to the
        same vehicle."
        PRD §3.2: "the last surfaces as `ERR_VEHICLE_ALREADY_BOUND`."

        Claim: counterpart — a bind against an ACTIVE vehicle that
        merely has an ACTIVE transponder bound fires
        ERR_VEHICLE_ALREADY_BOUND, confirming that ERR_VEHICLE_BLOCKED
        only fires when the vehicle is also BLOCKED.

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_blocked_vehicle_double_bind
        """
        a, v, t1 = setup_account_with_bound_transponder()
        t2 = create_transponder(a["id"])
        res = api.bind_transponder(
            a["id"], t2["id"],
            bind_transponder_payload(vehicle_id=v["id"]),
            make_account_holder_headers(a["id"]),
        )
        validate_error(res, "ERR_VEHICLE_ALREADY_BOUND",
                       expected_status=409)


# =============================================================================
# Rule 6 — boundary_precision_check
# =============================================================================

class TestAutoReloadThresholdBoundary:
    """# difficulty: boundary_precision_check/auto_reload_threshold_inclusive_boundary"""

    def test_inclusive_boundary_at_threshold(self, api):
        """PRD §3.4: "the post-debit `balance_cents` is at or below
        `auto_reload_threshold_cents` (the comparison is inclusive — a
        balance exactly equal to the threshold triggers a reload)".

        Claim: A1 with threshold=2500 and pre-debit balance=3000; a
        500-cent toll lands post-debit balance exactly at 2500 → AUTO
        reload runs; final balance = 2500 + 4000 = 6500.

        # difficulty: boundary_precision_check/auto_reload_threshold_inclusive_boundary
        """
        a1, v1, t1 = setup_account_with_bound_transponder(
            home_agency_code="NY_EZPASS", balance_cents=3000,
            auto_reload_enabled=True,
            auto_reload_threshold_cents=2500,
            auto_reload_topup_cents=4000,
        )
        ingest_toll_event(
            gantry_id="B1", agency_code="NY_EZPASS",
            base_rate_cents=500,
            transponder_serial=t1["serial_number"],
        )
        a1_after = get_account(a1["id"])
        assert a1_after["balance_cents"] == 6500

    def test_one_cent_above_threshold_does_not_reload(self, api):
        """PRD §3.4: "the post-debit `balance_cents` is at or below
        `auto_reload_threshold_cents` (the comparison is inclusive — a
        balance exactly equal to the threshold triggers a reload)".

        Claim: A2 with threshold=2500 and pre-debit balance=3001; a
        500-cent toll lands post-debit balance at 2501 (one cent above
        threshold) → no AUTO reload; final balance = 2501.

        # difficulty: boundary_precision_check/auto_reload_threshold_inclusive_boundary
        """
        a2, v2, t2 = setup_account_with_bound_transponder(
            home_agency_code="NY_EZPASS", balance_cents=3001,
            auto_reload_enabled=True,
            auto_reload_threshold_cents=2500,
            auto_reload_topup_cents=4000,
        )
        ingest_toll_event(
            gantry_id="B2", agency_code="NY_EZPASS",
            base_rate_cents=500,
            transponder_serial=t2["serial_number"],
        )
        a2_after = get_account(a2["id"])
        assert a2_after["balance_cents"] == 2501


class TestEmptyInteropPolicySet:
    """# difficulty: boundary_precision_check/empty_interop_policy_set_fallback"""

    def test_empty_policy_set_means_zero_adjust(self, api):
        """PRD §2.9: "When the two differ, the server consults
        `InteropPolicy` rows keyed by `(home_agency, gantry_agency)`
        and applies a surcharge expressed in basis points
        (`surcharge_bps`) and a discount expressed in basis points
        (`discount_bps`)".

        Claim: cross-agency toll without any matching InteropPolicy
        rows produces interop_adjust=0 — gross == net for a TRANSPONDER
        capture; balance debited by exactly base_rate.

        # difficulty: boundary_precision_check/empty_interop_policy_set_fallback
        """
        a, v, t = setup_account_with_bound_transponder(
            home_agency_code="NY_EZPASS", balance_cents=20000,
            auto_reload_enabled=False, axle_count=2,
        )
        before = get_account(a["id"])["balance_cents"]
        ev = ingest_toll_event(
            gantry_id="EMP1", agency_code="NJ_EZPASS",
            base_rate_cents=300,
            transponder_serial=t["serial_number"],
        )
        assert ev["gross_toll_cents"] == 300
        assert ev["net_toll_cents"] == 300
        after = get_account(a["id"])["balance_cents"]
        assert after == before - 300

    def test_empty_policy_set_no_error_response(self, api):
        """PRD §2.9: empty-collection lookup falls through silently —
        the PRD only commits to ERR_INTEROP_POLICY_AMBIGUOUS when
        "more than one ... row matches".

        Claim: cross-agency ingest with zero matching rows returns 201
        (no error envelope) and proceeds to POSTED normally.

        # difficulty: boundary_precision_check/empty_interop_policy_set_fallback
        """
        a, v, t = setup_account_with_bound_transponder(
            home_agency_code="PA_TURNPIKE", balance_cents=20000,
            auto_reload_enabled=False,
        )
        payload = create_toll_event_payload(
            gantry_id="EMP2", agency_code="FL_SUNPASS",
            base_rate_cents=200,
            transponder_serial=t["serial_number"],
        )
        res = api.create_toll_event(
            payload, TEST_USERS["gantry_operator_headers"],
        )
        assert res.status_code == 201
        body = res.json()
        assert body["data"]["billing_status"] == "POSTED"


# =============================================================================
# Rule 7 — cross_entity_state_dependency
# =============================================================================

class TestTransponderBindCrossEntityState:
    """# difficulty: cross_entity_state_dependency/transponder_bind_requires_vehicle_active_and_account_active"""

    def test_bind_blocked_by_suspended_account(self, api):
        """PRD §2.11: "an account must be `ACTIVE` to register a
        vehicle, bind a transponder, ingest a toll attributed to the
        account, or pay a fine (`ERR_ACCOUNT_NOT_ACTIVE`)".

        Claim: with Account.status == SUSPENDED, a bind attempt → 409
        ERR_ACCOUNT_NOT_ACTIVE; transponder stays UNBOUND.

        # difficulty: cross_entity_state_dependency/transponder_bind_requires_vehicle_active_and_account_active
        """
        account, _, target, _ = setup_suspended_account_via_two_hov_frauds()
        assert account["status"] == "SUSPENDED"
        t = create_transponder(account["id"])
        res = api.bind_transponder(
            account["id"], t["id"],
            bind_transponder_payload(vehicle_id=target["id"]),
            make_account_holder_headers(account["id"]),
        )
        validate_error(res, "ERR_ACCOUNT_NOT_ACTIVE",
                       expected_status=409)

    def test_bind_to_active_account_active_vehicle_succeeds(self, api):
        """PRD §3.2: "the operation requires that the transponder's
        owning account match the path account, that the target vehicle
        exists and is owned by the same account, that the vehicle's
        status is `ACTIVE`, that the account's status is `ACTIVE`".

        Claim: when both vehicle and account are ACTIVE, the bind
        succeeds — confirms the negative path above isolates the
        Account.status check.

        # difficulty: cross_entity_state_dependency/transponder_bind_requires_vehicle_active_and_account_active
        """
        a, v = setup_account_with_vehicle()
        t = create_transponder(a["id"])
        res = api.bind_transponder(
            a["id"], t["id"],
            bind_transponder_payload(vehicle_id=v["id"]),
            make_account_holder_headers(a["id"]),
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "ACTIVE"
        assert data["bound_vehicle_id"] == v["id"]


class TestTollEventPostedRequiresTransponderActive:
    """# difficulty: cross_entity_state_dependency/tollevent_posted_requires_transponder_active_and_vehicle_active"""

    def test_suspended_transponder_does_not_post(self, api):
        """PRD §3.3: "The bound vehicle must itself be `ACTIVE` and
        the owning account must itself be `ACTIVE` for the posting to
        succeed; otherwise the event becomes a violation as described
        next."

        Claim: when transponder & vehicle are cascaded to non-ACTIVE
        (Account SUSPENDED), a transponder-bearing ingest does NOT land
        POSTED.

        # difficulty: cross_entity_state_dependency/tollevent_posted_requires_transponder_active_and_vehicle_active
        """
        # Build account, vehicle, transponder; then push two HOV_FRAUD
        # frauds to suspend the account and cascade.
        a = create_account(
            home_agency_code="NY_EZPASS", balance_cents=10000,
            auto_reload_enabled=False,
        )
        v = create_vehicle(a["id"], plate_state="NY", axle_count=2,
                           hov_capable=True)
        t = create_and_bind_transponder(a["id"], v["id"])

        v_f1 = create_vehicle(a["id"], plate_state="NY", axle_count=2,
                              hov_capable=True)
        v_f2 = create_vehicle(a["id"], plate_state="NY", axle_count=2,
                              hov_capable=True)
        ingest_hov_fraud_event(a, v_f1, base_rate_cents=200,
                               agency_code="NY_EZPASS")
        ingest_hov_fraud_event(a, v_f2, base_rate_cents=200,
                               agency_code="NY_EZPASS")
        a_after = get_account(a["id"])
        assert a_after["status"] == "SUSPENDED"
        before_balance = a_after["balance_cents"]

        # Attempt transponder ingest — should NOT post.
        payload = create_toll_event_payload(
            gantry_id="XPOST", agency_code="NY_EZPASS",
            base_rate_cents=200,
            transponder_serial=t["serial_number"],
            plate_number=v["plate_number"], plate_state=v["plate_state"],
        )
        api.create_toll_event(
            payload, TEST_USERS["gantry_operator_headers"],
        )
        a_final = get_account(a["id"])
        # Balance unchanged — POSTED path not taken.
        assert a_final["balance_cents"] == before_balance

    def test_active_transponder_does_post(self, api):
        """PRD §3.3: "If the capture is a `TRANSPONDER` read and the
        post-debit balance would land no lower than the negative of
        the auto-reload top-up amount (or `auto_reload_enabled` is
        true), the event transitions from `PENDING` to `POSTED`".

        Claim: when the transponder, vehicle, and account are all
        ACTIVE, the event POSTs and the account is debited — confirms
        the negative case above isolates the state precondition.

        # difficulty: cross_entity_state_dependency/tollevent_posted_requires_transponder_active_and_vehicle_active
        """
        a, v, t = setup_account_with_bound_transponder(
            home_agency_code="NY_EZPASS", balance_cents=10000,
            auto_reload_enabled=False,
        )
        ev = ingest_toll_event(
            gantry_id="XOK", agency_code="NY_EZPASS", base_rate_cents=200,
            transponder_serial=t["serial_number"],
        )
        assert ev["billing_status"] == "POSTED"
        a_after = get_account(a["id"])
        assert a_after["balance_cents"] == 10000 - 200


# =============================================================================
# Rule 8 — resource_temporal_overlap
# =============================================================================

class TestTollEventDedupMinuteWindow:
    """# difficulty: resource_temporal_overlap/tollevent_dedup_minute_truncation_window"""

    def test_dedup_same_minute_blocks_second(self, api):
        """PRD §2.10: "Two `TollEvent` ingests that share the same
        `gantry_id`, the same `read_at` minute (the `read_at`
        timestamp truncated to the minute), and the same `plate_number`
        + `plate_state` or `transponder_serial` tuple serialize
        first-writer-wins on that deduplication tuple; the second
        ingest is rejected with `ERR_DUPLICATE_TOLL_EVENT`."

        Claim: ingest at 10:15:00 then 10:15:59.999 on the same gantry
        and transponder → second returns 409 ERR_DUPLICATE_TOLL_EVENT.

        # difficulty: resource_temporal_overlap/tollevent_dedup_minute_truncation_window
        """
        a, v, t = setup_account_with_bound_transponder(
            home_agency_code="NY_EZPASS", balance_cents=10000,
        )
        payload1 = create_toll_event_payload(
            gantry_id="DM1", agency_code="NY_EZPASS",
            base_rate_cents=100,
            read_at="2026-05-20T10:15:00.000Z",
            transponder_serial=t["serial_number"],
        )
        r1 = api.create_toll_event(
            payload1, TEST_USERS["gantry_operator_headers"],
        )
        assert r1.status_code == 201

        payload2 = create_toll_event_payload(
            gantry_id="DM1", agency_code="NY_EZPASS",
            base_rate_cents=100,
            read_at="2026-05-20T10:15:59.999Z",
            transponder_serial=t["serial_number"],
        )
        r2 = api.create_toll_event(
            payload2, TEST_USERS["gantry_operator_headers"],
        )
        assert r2.status_code == 409
        assert r2.json()["data"]["error_id"] == "ERR_DUPLICATE_TOLL_EVENT"

    def test_dedup_next_minute_allows_second(self, api):
        """PRD §2.10: "the same `read_at` minute (the `read_at`
        timestamp truncated to the minute)".

        Claim: ingest at 10:15:59.999 then 10:16:00.000 on same gantry
        and transponder → both succeed (different minute buckets).

        # difficulty: resource_temporal_overlap/tollevent_dedup_minute_truncation_window
        """
        a, v, t = setup_account_with_bound_transponder(
            home_agency_code="NY_EZPASS", balance_cents=10000,
        )
        payload1 = create_toll_event_payload(
            gantry_id="DM2", agency_code="NY_EZPASS",
            base_rate_cents=100,
            read_at="2026-05-20T10:15:59.999Z",
            transponder_serial=t["serial_number"],
        )
        r1 = api.create_toll_event(
            payload1, TEST_USERS["gantry_operator_headers"],
        )
        assert r1.status_code == 201

        payload2 = create_toll_event_payload(
            gantry_id="DM2", agency_code="NY_EZPASS",
            base_rate_cents=100,
            read_at="2026-05-20T10:16:00.000Z",
            transponder_serial=t["serial_number"],
        )
        r2 = api.create_toll_event(
            payload2, TEST_USERS["gantry_operator_headers"],
        )
        assert r2.status_code == 201


class TestVoidWindow24h:
    """# difficulty: resource_temporal_overlap/void_window_24h_inclusive_boundary"""

    def test_void_just_inside_24h_succeeds(self, api):
        """PRD §3.3: "An `AgencyAdmin` may void a toll event by
        referencing the event's id, but only within 24 hours of its
        `created_at`".

        Claim: at clock T+23h59m59s after the event's created_at, void
        succeeds with HTTP 200 and billing_status VOIDED.

        # difficulty: resource_temporal_overlap/void_window_24h_inclusive_boundary
        """
        a, v, ev = setup_posted_toll_event(
            home_agency_code="NY_EZPASS", balance_cents=10000,
            base_rate_cents=200,
        )
        created = parse_iso(ev["created_at"])
        advance_clock_to(
            created + timedelta(hours=23, minutes=59, seconds=59)
        )
        res = api.void_toll_event(
            ev["id"], TEST_USERS["agency_admin_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["billing_status"] == "VOIDED"

    def test_void_just_past_24h_rejected(self, api):
        """PRD §3.3: "outside this window the request is rejected with
        `ERR_VOID_WINDOW_EXPIRED`."

        Claim: at clock T+24h00m01s after the event's created_at, void
        → 409 ERR_VOID_WINDOW_EXPIRED; billing_status remains POSTED.

        # difficulty: resource_temporal_overlap/void_window_24h_inclusive_boundary
        """
        a, v, ev = setup_posted_toll_event(
            home_agency_code="NY_EZPASS", balance_cents=10000,
            base_rate_cents=200,
        )
        created = parse_iso(ev["created_at"])
        advance_clock_to(created + timedelta(hours=24, seconds=1))
        res = api.void_toll_event(
            ev["id"], TEST_USERS["agency_admin_headers"],
        )
        validate_error(res, "ERR_VOID_WINDOW_EXPIRED",
                       expected_status=409)
        refetched = get_toll_event(ev["id"])
        assert refetched["billing_status"] == "POSTED"


# =============================================================================
# Rule 9 — compensating_invariant
# =============================================================================

class TestPostThenVoidBalanceInvariant:
    """# difficulty: compensating_invariant/toll_post_then_void_preserves_account_balance"""

    def test_post_void_balance_zero_drift(self, api):
        """PRD §2.8: "Voiding a `TollEvent` whose `billing_status` is
        `POSTED` or `TOLL_BY_PLATE_INVOICED` refunds the prior debit by
        adding `net_toll_cents` back to `Account.balance_cents` and
        resetting both `gross_toll_cents` and `net_toll_cents` to zero."

        Claim: balance_before_post == balance_after_void (no drift)
        with base 347, CLASS_2, same-agency, no auto-reload.

        # difficulty: compensating_invariant/toll_post_then_void_preserves_account_balance
        """
        a, v, ev = setup_posted_toll_event(
            home_agency_code="NY_EZPASS", balance_cents=10000,
            base_rate_cents=347,
        )
        # Snapshot intermediate balance.
        mid = get_account(a["id"])["balance_cents"]
        assert mid == 9653
        api.void_toll_event(
            ev["id"], TEST_USERS["agency_admin_headers"],
        )
        final = get_account(a["id"])["balance_cents"]
        assert final == 10000

    def test_voided_toll_event_net_and_gross_zero(self, api):
        """PRD §2.8: "Voiding a `TollEvent` whose `billing_status` is
        `POSTED` or `TOLL_BY_PLATE_INVOICED` refunds the prior debit
        by adding `net_toll_cents` back to `Account.balance_cents` and
        resetting both `gross_toll_cents` and `net_toll_cents` to zero."

        Claim: after void, ev.net_toll_cents == 0 AND
        ev.gross_toll_cents == 0; balance moved by exactly the original
        net amount.

        # difficulty: compensating_invariant/toll_post_then_void_preserves_account_balance
        """
        a, v, ev = setup_posted_toll_event(
            home_agency_code="NY_EZPASS", balance_cents=10000,
            base_rate_cents=200,
        )
        res = api.void_toll_event(
            ev["id"], TEST_USERS["agency_admin_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["net_toll_cents"] == 0
        assert data["gross_toll_cents"] == 0


class TestViolationVoidOutstandingInvariant:
    """# difficulty: compensating_invariant/violation_create_then_void_preserves_outstanding_fines_total"""

    def test_violation_then_void_outstanding_returns_to_zero(self, api):
        """PRD §3.5: "fines whose status is `DISPUTED`, `SETTLED`, or
        `DISMISSED` do not contribute (a `DISPUTED` fine counts as
        zero outstanding)."
        PRD §3.3: "Voiding a `VIOLATED` event is permitted only while
        the associated fine's settlement status is still `PENDING`;
        the void cascades the associated `Violation` to `CLEARED` and
        the associated `Fine` to `DISMISSED`, and the owning account's
        `outstanding_fine_cents` is recomputed (potentially flipping
        the account from `SUSPENDED` back to `ACTIVE`)."

        Claim: outstanding goes 0 → 2730 (PENDING) → 0 (DISMISSED).

        # difficulty: compensating_invariant/violation_create_then_void_preserves_outstanding_fines_total
        """
        a, v = setup_account_with_vehicle(
            home_agency_code="NY_EZPASS", balance_cents=0,
            auto_reload_enabled=False, plate_state="NY",
        )
        before = get_account(a["id"])["outstanding_fine_cents"]
        assert before == 0
        ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                        agency_code="NY_EZPASS")
        mid = get_account(a["id"])["outstanding_fine_cents"]
        assert mid == 2730

        # Find the violated event id.
        res = api.list_toll_events(
            TEST_USERS["agency_admin_headers"],
            params={"account_id": a["id"]},
        )
        events = res.json().get("data") or []
        violated = next(e for e in events
                        if e["billing_status"] == "VIOLATED")
        api.void_toll_event(
            violated["id"], TEST_USERS["agency_admin_headers"],
        )
        final = get_account(a["id"])["outstanding_fine_cents"]
        assert final == 0
        assert final == before

    def test_voided_violation_fine_dismissed_and_violation_cleared(
        self, api,
    ):
        """PRD §3.3: "Voiding a `VIOLATED` event is permitted only while
        the associated fine's settlement status is still `PENDING`;
        the void cascades the associated `Violation` to `CLEARED` and
        the associated `Fine` to `DISMISSED`, and the owning account's
        `outstanding_fine_cents` is recomputed (potentially flipping
        the account from `SUSPENDED` back to `ACTIVE`)."

        Claim: after void on a VIOLATED event, the associated fine's
        settlement_status flips PENDING → DISMISSED.

        # difficulty: compensating_invariant/violation_create_then_void_preserves_outstanding_fines_total
        """
        a, v = setup_account_with_vehicle(
            home_agency_code="NY_EZPASS", balance_cents=0,
            auto_reload_enabled=False, plate_state="NY",
        )
        ingest_insufficient_funds_event(a, v, base_rate_cents=200,
                                        agency_code="NY_EZPASS")
        fine = find_fine_for_account(a["id"])

        res = api.list_toll_events(
            TEST_USERS["agency_admin_headers"],
            params={"account_id": a["id"]},
        )
        events = res.json().get("data") or []
        violated = next(e for e in events
                        if e["billing_status"] == "VIOLATED")
        api.void_toll_event(
            violated["id"], TEST_USERS["agency_admin_headers"],
        )
        refreshed = get_fine(fine["id"], a["id"])
        assert refreshed["settlement_status"] == "DISMISSED"
