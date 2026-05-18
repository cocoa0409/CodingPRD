"""Difficulty-design coverage — at least two tests per declared instance.

Each test docstring carries a `# difficulty: <rule_id>/<instance>` tag
so coverage can be audited mechanically. Each test pins to a verbatim
PRD sentence stating the underlying rule.
"""
from __future__ import annotations

import math

import pytest

from test_helpers import (
    DRAW_PERIOD_DAYS,
    EARLY_CLOSURE_WINDOW_DAYS,
    advance_clock_days,
    api_client,
    create_borrower,
    create_heloc,
    create_insurance_event_payload,
    create_property,
    create_rate_reset_payload,
    create_senior_lien,
    get_heloc,
    make_borrower_headers,
    post_bankruptcy_event,
    post_draw,
    post_insurance_event,
    post_payment,
    post_rate_reset,
    post_senior_lien_default_event,
    run_annual_fees_sweep,
    run_billing_cycle_sweep,
    setup_active_heloc,
    setup_active_heloc_with_balance,
    setup_borrower_property_lien,
    setup_borrower_with_two_helocs,
    setup_heloc_at_delinquency_days,
    setup_heloc_closed_no_balance,
    setup_heloc_default_via_bankruptcy,
    setup_heloc_default_via_senior_lien,
    setup_heloc_in_repay,
    setup_heloc_with_accrued_interest,
    setup_pending_heloc,
    setup_two_helocs_for_close_branch_outcomes,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Rule 1: dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:

    def test_minimum_payment_due_in_draw_equals_accrued(self, api):
        """# difficulty: dual_variant_calc/minimum_payment_due_draw_vs_repay

        PRD §3.4: "When the HELOC is in DRAW, the minimum is exactly
        the accrued_interest_cents carried since the last
        billing-cycle reset — the draw period requires nothing more
        than interest service."
        """
        borrower, _, _, heloc = setup_heloc_with_accrued_interest(
            draw_amount_cents=1_000_000, cycles_to_accrue=1,
        )
        h = get_heloc(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        assert h["status"] == "DRAW"
        assert (
            h["minimum_payment_due_cents"]
            == h["accrued_interest_cents"]
        )

    def test_minimum_payment_due_in_repay_exceeds_accrued(self, api):
        """# difficulty: dual_variant_calc/minimum_payment_due_draw_vs_repay

        PRD §3.4: "When the HELOC is in REPAY, the minimum is the
        standard amortizing monthly payment-and-interest combined with
        the carried accrued_interest_cents".

        After DRAW→REPAY rollover with non-zero principal_balance_cents,
        the minimum strictly exceeds accrued because the amortizing
        principal-and-interest component is positive.
        """
        borrower, _, _, heloc = setup_heloc_in_repay(
            draw_amount_cents=1_000_000,
        )
        # Read once in REPAY.
        h = get_heloc(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        assert h["status"] == "REPAY"
        assert h["principal_balance_cents"] > 0
        # PRD §3.4 amortization always >= accrued when principal>0.
        assert (
            h["minimum_payment_due_cents"]
            > h["accrued_interest_cents"]
        ), (
            f"REPAY minimum must strictly exceed accrued "
            f"({h['accrued_interest_cents']}); got "
            f"{h['minimum_payment_due_cents']}"
        )

    def test_periodic_then_lifetime_clamp_with_lifetime_active(
        self, api, servicer_headers,
    ):
        """# difficulty: dual_variant_calc/applied_rate_periodic_vs_lifetime_clamp

        PRD §3.5: "The applied_rate_bps is the same value after two
        successive clamps. The first clamp is the periodic cap ... The
        second clamp is the lifetime bound: the periodic-clamped value
        is then bounded below by lifetime_floor_bps and above by
        lifetime_cap_bps to produce applied_rate_bps."

        Recipe (§2.1.A rule 1 instance applied_rate_periodic_vs_lifetime_clamp):
        with margin=200, periodic_cap=300, lifetime_cap=2100,
        floor=100, activate at prime=1800 (initial_rate=clamp(2000,
        100, 2100)=2000). First reset prime=2000 → requested=2200,
        periodic_clamped=min(2000+300, 2200)=2200 (delta 200 NOT > 300
        → unclamped at periodic), lifetime → 2100.
        """
        _, _, _, heloc = setup_active_heloc(
            margin_bps=200,
            periodic_cap_bps=300,
            lifetime_cap_bps=2100,
            lifetime_floor_bps=100,
            prime_rate_bps_at_origination=1800,
        )
        assert heloc["current_rate_bps"] == 2000
        reset = post_rate_reset(
            heloc["id"], prime_rate_bps=2000,
            servicer_headers=servicer_headers,
        )
        assert reset["requested_rate_bps"] == 2200
        assert reset["applied_rate_bps"] == 2100
        h = get_heloc(heloc["id"])
        assert h["current_rate_bps"] == 2100

    def test_periodic_clamp_active_independent_of_lifetime(
        self, api, servicer_headers,
    ):
        """# difficulty: dual_variant_calc/applied_rate_periodic_vs_lifetime_clamp

        PRD §3.5: "the difference between requested_rate_bps and the
        HELOC's current_rate_bps immediately before the reset is
        compared to periodic_cap_bps; if the difference is strictly
        greater than periodic_cap_bps, the periodic-clamped value is
        current_rate_bps + periodic_cap_bps".

        Configure margin=200, periodic=300, lifetime_cap=2500 (high
        so it never binds), floor=100. Start current=2000; prime=2400
        → requested=2600; delta=600 > 300 → periodic_clamped=
        2000+300=2300; lifetime cap 2500 not active → applied=2300.
        Distinguishes periodic-only path from lifetime-only path.
        """
        _, _, _, heloc = setup_active_heloc(
            margin_bps=200,
            periodic_cap_bps=300,
            lifetime_cap_bps=2500,
            lifetime_floor_bps=100,
            prime_rate_bps_at_origination=1800,  # current=2000
        )
        reset = post_rate_reset(
            heloc["id"], prime_rate_bps=2400,
            servicer_headers=servicer_headers,
        )
        assert reset["requested_rate_bps"] == 2600
        assert reset["applied_rate_bps"] == 2300


# ===========================================================================
# Rule 2: combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:

    def test_repay_minimum_payment_is_higher_at_higher_rate(self, api):
        """# difficulty: combinatorial_formula/amortizing_payment_three_input_nonlinear

        PRD §3.4: "the system derives a monthly decimal rate by
        taking current_rate_bps, dividing by 10000 to convert basis
        points to a decimal annual rate, and dividing by 12 to convert
        to a monthly rate ... the principal-and-interest component is
        principal_balance_cents multiplied by the monthly rate,
        divided by the quantity one minus the monthly factor (one
        plus the monthly rate) raised to the negative power of
        months_remaining — the standard mortgage amortization formula."

        Higher current_rate_bps must produce a higher
        minimum_payment_due_cents at the same principal and
        months_remaining.
        """
        from test_helpers import advance_clock_days
        borrower, _, _, heloc = setup_heloc_in_repay(
            draw_amount_cents=1_200_000,
            margin_bps=300,
            periodic_cap_bps=200,
            lifetime_cap_bps=2000,
            lifetime_floor_bps=100,
            prime_rate_bps_at_origination=500,
            # initial_rate=800; in REPAY post-rollover.
        )
        h_high = get_heloc(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        payment_high = h_high["minimum_payment_due_cents"]
        # Drop the rate via a rate reset (current 800 → 600, delta
        # |200| == periodic cap, allowed since not strictly greater).
        from test_helpers import post_rate_reset
        post_rate_reset(heloc["id"], prime_rate_bps=300)
        h_low = get_heloc(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        # Same principal_balance_cents, same months_remaining (same
        # observation point), just lower current_rate_bps → lower min.
        assert h_low["current_rate_bps"] < h_high["current_rate_bps"]
        payment_low = h_low["minimum_payment_due_cents"]
        assert payment_low < payment_high, (
            f"amortizing payment must drop when rate drops; "
            f"payment_low={payment_low}, payment_high={payment_high}"
        )

    def test_repay_minimum_payment_exceeds_pure_principal_slice(
        self, api,
    ):
        """# difficulty: combinatorial_formula/amortizing_payment_three_input_nonlinear

        PRD §3.4: "the principal-and-interest component is
        principal_balance_cents multiplied by the monthly rate,
        divided by the quantity one minus the monthly factor (one
        plus the monthly rate) raised to the negative power of
        months_remaining".

        With a positive monthly_rate, the amortizing payment must be
        STRICTLY GREATER than the pure principal slice
        (principal_balance / months_remaining) because the formula
        adds an interest contribution.
        """
        borrower, _, _, heloc = setup_heloc_in_repay(
            draw_amount_cents=1_000_000,
            margin_bps=300,
            periodic_cap_bps=200,
            lifetime_cap_bps=2000,
            lifetime_floor_bps=100,
            prime_rate_bps_at_origination=500,
        )
        h = get_heloc(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        # months_remaining: we'd need to know repayment_period_end_date
        # exactly to compute, but we can derive a SAFE lower bound:
        # months_remaining <= 12 * repayment_term_years = 120 (10 yr).
        # Lower bound on pure-principal slice: principal / 120.
        lower_slice = h["principal_balance_cents"] // 120
        # The amortizing minimum must exceed lower_slice strictly
        # because the formula adds accrued_interest_cents (>=0) and
        # the amortizing P&I exceeds principal/months for any rate>0.
        assert h["minimum_payment_due_cents"] > lower_slice

    def test_payment_split_waterfall_pinned_order(self, api):
        """# difficulty: combinatorial_formula/payment_split_waterfall_with_caps

        PRD §3.4: "the system applies a waterfall allocation that
        settles accrued interest before principal. The
        interest_component_cents is the smaller of the payment's
        amount_cents and the HELOC's accrued_interest_cents
        immediately before the payment; the principal_component_cents
        is the payment's amount_cents minus the
        interest_component_cents."

        Recipe (rule 2 instance payment_split_waterfall_with_caps):
        principal=1_000_000, one cycle at 800 bps → accrued=6575.
        Payment=10000 → interest=6575, principal=3425.
        """
        borrower, _, _, heloc = setup_heloc_with_accrued_interest(
            draw_amount_cents=1_000_000, cycles_to_accrue=1,
            margin_bps=300,
            periodic_cap_bps=200,
            lifetime_cap_bps=2000,
            lifetime_floor_bps=100,
            prime_rate_bps_at_origination=500,
        )
        assert heloc["accrued_interest_cents"] == 6_575
        pay = post_payment(
            heloc["id"], amount_cents=10_000,
            headers=make_borrower_headers(borrower["id"]),
        )
        assert pay["interest_component_cents"] == 6_575
        assert pay["principal_component_cents"] == 3_425
        h = get_heloc(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        assert h["accrued_interest_cents"] == 0
        assert h["principal_balance_cents"] == 996_575

    def test_payment_split_cap_on_interest_at_accrued(self, api):
        """# difficulty: combinatorial_formula/payment_split_waterfall_with_caps

        PRD §3.4: "The interest_component_cents is the smaller of the
        payment's amount_cents and the HELOC's accrued_interest_cents
        immediately before the payment".

        Cap behavior: when payment EXACTLY equals accrued, interest
        component caps at accrued and principal component is 0.
        """
        borrower, _, _, heloc = setup_heloc_with_accrued_interest(
            draw_amount_cents=500_000, cycles_to_accrue=1,
        )
        accrued = heloc["accrued_interest_cents"]
        assert accrued > 0
        pay = post_payment(
            heloc["id"], amount_cents=accrued,
            headers=make_borrower_headers(borrower["id"]),
        )
        assert pay["interest_component_cents"] == accrued
        assert pay["principal_component_cents"] == 0


# ===========================================================================
# Rule 3: non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:

    def test_three_paths_to_closed_with_divergent_fees(
        self, api, servicer_headers,
    ):
        """# difficulty: non_linear_state_machine/heloc_branching_three_terminal_paths_to_closed

        PRD §3.9: "Because REPAY only begins after draw_period_end_date
        has passed and draw_period_end_date is exactly 3650 days after
        origination_date, an early-closure fee is structurally
        impossible on a REPAY → CLOSED transition; it remains possible
        on DRAW → CLOSED and on DEFAULT → CLOSED."

        - h_a closed from DRAW at tenure 0 → EARLY_CLOSURE fee.
        - h_b closed from REPAY (after 3650 days) → NO EARLY_CLOSURE.
        - h_c closed from DEFAULT (default via bankruptcy at tenure
          ~0) → EARLY_CLOSURE fee.
        """
        # Path A — DRAW → CLOSED at tenure 0.
        borrower_a, _, _, heloc_a = setup_active_heloc(
            early_closure_fee_cents=10_000,
        )
        close_a = api.close_heloc(
            heloc_a["id"], make_borrower_headers(borrower_a["id"]),
        )
        validate_success(close_a, 200)
        fees_a, _ = validate_paginated(api.list_fees(
            heloc_a["id"], make_borrower_headers(borrower_a["id"]),
        ))
        ec_a = [f for f in fees_a if f["fee_type"] == "EARLY_CLOSURE"]
        assert len(ec_a) == 1
        assert ec_a[0]["amount_cents"] == 10_000

        # Path B — DRAW → REPAY → CLOSED at tenure 3650+ days.
        borrower_b, _, _, heloc_b = setup_active_heloc(
            early_closure_fee_cents=10_000,
        )
        advance_clock_days(days=DRAW_PERIOD_DAYS)
        run_billing_cycle_sweep()
        h_b_repay = get_heloc(
            heloc_b["id"], make_borrower_headers(borrower_b["id"]),
        )
        assert h_b_repay["status"] == "REPAY"
        close_b = api.close_heloc(
            heloc_b["id"], make_borrower_headers(borrower_b["id"]),
        )
        validate_success(close_b, 200)
        fees_b, _ = validate_paginated(api.list_fees(
            heloc_b["id"], make_borrower_headers(borrower_b["id"]),
        ))
        ec_b = [f for f in fees_b if f["fee_type"] == "EARLY_CLOSURE"]
        assert len(ec_b) == 0

        # Path C — DRAW → DEFAULT → CLOSED at tenure ~0.
        borrower_c, _, _, heloc_c, _ = (
            setup_heloc_default_via_bankruptcy(
                early_closure_fee_cents=10_000,
            )
        )
        close_c = api.close_heloc(
            heloc_c["id"], make_borrower_headers(borrower_c["id"]),
        )
        validate_success(close_c, 200)
        fees_c, _ = validate_paginated(api.list_fees(
            heloc_c["id"], make_borrower_headers(borrower_c["id"]),
        ))
        ec_c = [f for f in fees_c if f["fee_type"] == "EARLY_CLOSURE"]
        assert len(ec_c) == 1
        assert ec_c[0]["amount_cents"] == 10_000

    def test_default_to_closed_transitions_succeeds(self, api):
        """# difficulty: non_linear_state_machine/heloc_branching_three_terminal_paths_to_closed

        PRD §3.9: "Closure is permitted from DRAW, REPAY, or DEFAULT".

        DEFAULT → CLOSED is a declared transition; the resulting
        Heloc.status must be CLOSED.
        """
        borrower, _, _, heloc, _ = setup_heloc_default_via_bankruptcy()
        assert heloc["status"] == "DEFAULT"
        closed = validate_success(api.close_heloc(
            heloc["id"], make_borrower_headers(borrower["id"]),
        ), 200)
        assert closed["status"] == "CLOSED"

    def test_property_insurance_cycle_lapsed_to_active_to_lapsed(
        self, api, servicer_headers,
    ):
        """# difficulty: non_linear_state_machine/property_insurance_cyclic_active_lapsed

        PRD §2.8: "If the same property's insurance is subsequently
        reinstated, the insurance_status returns to ACTIVE and
        insurance_lapsed_at is cleared to null, but any HELOC that
        was already cascaded to DEFAULT because of the lapse is not
        automatically reactivated".

        Cycle: ACTIVE → LAPSED → ACTIVE → LAPSED. Final state LAPSED.
        """
        _, prop, _, heloc = setup_active_heloc()
        # Lapse.
        post_insurance_event(prop["id"], event_type="LAPSE")
        # Reinstate.
        post_insurance_event(prop["id"], event_type="REINSTATE")
        # Lapse again.
        post_insurance_event(prop["id"], event_type="LAPSE")
        p2 = validate_success(
            api.get_property(prop["id"], servicer_headers), 200,
        )
        assert p2["insurance_status"] == "LAPSED"

    def test_already_defaulted_heloc_not_re_defaulted_by_second_lapse(
        self, api, servicer_headers,
    ):
        """# difficulty: non_linear_state_machine/property_insurance_cyclic_active_lapsed

        PRD §2.8: "once a HELOC enters DEFAULT, that state is sticky
        regardless of the underlying trigger being subsequently cured."

        A re-LAPSE on a property whose HELOC is already DEFAULT must
        not produce a second DefaultEvent on that HELOC — the cascade
        only affects HELOCs whose status is in DRAW or REPAY.
        """
        _, prop, _, heloc = setup_active_heloc()
        post_insurance_event(prop["id"], event_type="LAPSE")
        post_insurance_event(prop["id"], event_type="REINSTATE")
        # Count DefaultEvents before second lapse.
        de_resp = api.list_default_events(
            heloc["id"], servicer_headers,
        )
        events_before, _ = validate_paginated(de_resp)
        post_insurance_event(prop["id"], event_type="LAPSE")
        de_resp2 = api.list_default_events(
            heloc["id"], servicer_headers,
        )
        events_after, _ = validate_paginated(de_resp2)
        # PRD §3.6 cascade only applies to HELOCs in DRAW or REPAY;
        # the second LAPSE must NOT add a new DefaultEvent.
        assert len(events_after) == len(events_before), (
            f"second LAPSE must not re-default an already-DEFAULT "
            f"HELOC; before={len(events_before)}, after="
            f"{len(events_after)}"
        )


# ===========================================================================
# Rule 4: transitive_cascade
# ===========================================================================
class TestTransitiveCascade:

    def test_bankruptcy_cascades_default_and_suppresses_future_fee(
        self, api, servicer_headers,
    ):
        """# difficulty: transitive_cascade/bankruptcy_cascades_three_hops

        PRD §3.6: "every HELOC with that borrower_id whose status is
        in DRAW or REPAY is cascaded into DEFAULT with default_trigger
        of BANKRUPTCY and a DefaultEvent whose source_event_id is the
        id of the BankruptcyEvent just recorded."
        PRD §3.8: "if the HELOC's status is DEFAULT or CLOSED, the
        assessment is suppressed and no Fee is written at all."

        HOP 1 → HOP 2 → HOP 3 chain.
        """
        borrower, _, _, heloc_a, _, _, heloc_b = (
            setup_borrower_with_two_helocs(annual_fee_cents=5_000)
        )
        # HOP 1.
        advance_clock_days(days=200)
        post_bankruptcy_event(borrower["id"])
        # HOP 2: both HELOCs must be in DEFAULT.
        h_a = get_heloc(heloc_a["id"], servicer_headers)
        h_b = get_heloc(heloc_b["id"], servicer_headers)
        assert h_a["status"] == "DEFAULT"
        assert h_a["default_trigger"] == "BANKRUPTCY"
        assert h_b["status"] == "DEFAULT"
        assert h_b["default_trigger"] == "BANKRUPTCY"
        # HOP 3: advance past anniversary; annual-fee sweep must
        # suppress because status==DEFAULT at sweep time.
        advance_clock_days(days=200)
        run_annual_fees_sweep()
        for h_id in (heloc_a["id"], heloc_b["id"]):
            fees, _ = validate_paginated(
                api.list_fees(h_id, servicer_headers),
            )
            annual = [
                f for f in fees if f["fee_type"] == "ANNUAL"
            ]
            assert len(annual) == 0, (
                f"PRD §3.8 suppression: DEFAULT HELOC must have ZERO "
                f"ANNUAL fees; got {len(annual)} for {h_id}"
            )

    def test_bankruptcy_default_event_source_event_id_equals_event_id(
        self, api, servicer_headers,
    ):
        """# difficulty: transitive_cascade/bankruptcy_cascades_three_hops

        PRD §3.6: "a DefaultEvent whose source_event_id is the id of
        the BankruptcyEvent just recorded."
        """
        borrower, _, _, heloc, event = (
            setup_heloc_default_via_bankruptcy()
        )
        de, _ = validate_paginated(
            api.list_default_events(heloc["id"], servicer_headers),
        )
        last = de[-1]
        assert last["trigger"] == "BANKRUPTCY"
        assert last["source_event_id"] == event["id"]

    def test_senior_lien_default_cascades_two_hops(
        self, api, servicer_headers,
    ):
        """# difficulty: transitive_cascade/senior_lien_default_cascade_two_hops

        PRD §3.6: "The senior lien's status flips to DEFAULTED, its
        defaulted_at is set, and every HELOC on the same property
        whose status is in DRAW or REPAY is cascaded into DEFAULT
        with default_trigger of SENIOR_LIEN_DEFAULT and
        DefaultEvent.source_event_id pointing at the
        senior-lien-default event."
        """
        _, _, sl, heloc, event = setup_heloc_default_via_senior_lien()
        # HOP 1: senior lien now DEFAULTED.
        sl2 = validate_success(
            api.get_senior_lien(sl["id"], servicer_headers), 200,
        )
        assert sl2["status"] == "DEFAULTED"
        # HOP 2: HELOC now DEFAULT with right trigger and source.
        assert heloc["status"] == "DEFAULT"
        assert heloc["default_trigger"] == "SENIOR_LIEN_DEFAULT"
        de, _ = validate_paginated(api.list_default_events(
            heloc["id"], servicer_headers,
        ))
        last = de[-1]
        assert last["source_event_id"] == event["id"]

    def test_senior_lien_default_only_cascades_drawing_helocs(
        self, api, servicer_headers,
    ):
        """# difficulty: transitive_cascade/senior_lien_default_cascade_two_hops

        PRD §3.6: "every HELOC on the same property whose status is
        in DRAW or REPAY is cascaded into DEFAULT".

        A PENDING HELOC on the same property must NOT be cascaded —
        only DRAW/REPAY HELOCs are affected.
        """
        borrower, prop, sl = setup_borrower_property_lien()
        heloc_pending = create_heloc(
            borrower_id=borrower["id"], property_id=prop["id"],
        )
        assert heloc_pending["status"] == "PENDING"
        post_senior_lien_default_event(sl["id"])
        h = get_heloc(heloc_pending["id"], servicer_headers)
        # PRD §3.6: only DRAW/REPAY HELOCs are cascaded. PENDING
        # stays PENDING — though the activation path now also fails
        # the §3.2 lien-CURRENT gate.
        assert h["status"] == "PENDING"


# ===========================================================================
# Rule 5: priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:

    def test_double_close_returns_heloc_closed(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_close_balance

        PRD §2.10: "more specific state errors take precedence over
        generic ones — for example ... any mutation attempted against
        a CLOSED HELOC returns ERR_HELOC_CLOSED."

        A second close on an already-CLOSED HELOC fires ERR_HELOC_CLOSED
        rather than the generic ERR_INVALID_STATE, satisfying the
        priority pair (state-specific vs state-generic).
        """
        borrower, _, _, closed = setup_heloc_closed_no_balance()
        assert closed["status"] == "CLOSED"
        resp = api.close_heloc(
            closed["id"], make_borrower_headers(borrower["id"]),
        )
        # PRD §2.10 pins ERR_HELOC_CLOSED for the closed-state case.
        validate_error(resp, "ERR_HELOC_CLOSED")

    def test_close_on_pending_returns_invalid_state_not_balance(
        self, api,
    ):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_close_balance

        PRD §2.10: "Only after existence is established does the
        server evaluate state preconditions, then business-safety
        rules ... then business-temporal rules ... and finally
        fiscal/capacity rules (... balance-zero checks at close ...)."

        On a PENDING HELOC, both the state precondition (priority
        11/14: PENDING not allowed for close → ERR_INVALID_STATE) and
        the fiscal precondition (priority 31:
        principal_balance_cents and accrued_interest_cents must be
        zero) are conceptually applicable; PRD §2.10 ordering pins
        the state error.
        """
        borrower, _, _, heloc = setup_pending_heloc()
        assert heloc["principal_balance_cents"] == 0
        resp = api.close_heloc(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        # PRD pins state-class error here.
        body = resp.json()
        assert resp.status_code == 409, (
            f"state error must be 409; got {resp.status_code}"
        )
        assert body["data"]["error_id"] == "ERR_INVALID_STATE", (
            f"PRD §2.10: state precedes fiscal; got "
            f"{body['data']['error_id']!r}"
        )

    def test_occupancy_check_precedes_borrower_property_mismatch(
        self, api, originator_headers,
    ):
        """# difficulty: priority_pair_validation_conflict/business_safety_vs_business_referential_creation

        PRD §2.10: "then business-safety rules (occupancy, lien
        position, bankruptcy gate, CLTV) ... then referential rules
        (the borrower-property match)".

        With BOTH violations simultaneously, business-safety
        (occupancy != PRIMARY → ERR_OCCUPANCY_NOT_PRIMARY) precedes
        business-referential (mismatched borrower-property →
        ERR_BORROWER_PROPERTY_MISMATCH).
        """
        owner = create_borrower()
        stranger = create_borrower()
        prop = create_property(
            borrower_id=owner["id"], occupancy="SECONDARY",
        )
        create_senior_lien(property_id=prop["id"])
        # Both violations: occupancy and borrower-property mismatch.
        from test_helpers import create_heloc_payload
        resp = api.create_heloc(
            create_heloc_payload(
                borrower_id=stranger["id"],
                property_id=prop["id"],
            ),
            originator_headers,
        )
        validate_error(resp, "ERR_OCCUPANCY_NOT_PRIMARY")

    def test_no_senior_lien_check_precedes_borrower_property_mismatch(
        self, api, originator_headers,
    ):
        """# difficulty: priority_pair_validation_conflict/business_safety_vs_business_referential_creation

        PRD §2.10: "then business-safety rules (occupancy, lien
        position, bankruptcy gate, CLTV) ... then referential rules
        (the borrower-property match)".

        With BOTH violations (no senior lien AND borrower-property
        mismatch), business-safety (lien position) precedes
        business-referential.
        """
        owner = create_borrower()
        stranger = create_borrower()
        prop = create_property(borrower_id=owner["id"])
        # NO senior lien.
        from test_helpers import create_heloc_payload
        resp = api.create_heloc(
            create_heloc_payload(
                borrower_id=stranger["id"],
                property_id=prop["id"],
            ),
            originator_headers,
        )
        validate_error(resp, "ERR_NO_SENIOR_LIEN")


# ===========================================================================
# Rule 6: boundary_precision_check
# ===========================================================================
class TestBoundaryPrecisionCheck:

    def test_delinquency_exactly_90_triggers_default(self, api):
        """# difficulty: boundary_precision_check/delinquency_90_day_boundary

        PRD §3.7: "if delinquency_days is at least 90 and the HELOC's
        status is still in DRAW or REPAY, the system records a
        DefaultEvent with trigger of DELINQUENCY_90".

        Inclusive lower bound (>= 90). Exactly 90 fires DEFAULT.
        """
        borrower, _, _, h = setup_heloc_at_delinquency_days(
            target_days=90,
        )
        assert h["status"] == "DEFAULT"
        assert h["default_trigger"] == "DELINQUENCY_90"
        assert h["delinquency_days"] >= 90

    def test_delinquency_60_days_does_not_trigger_default(self, api):
        """# difficulty: boundary_precision_check/delinquency_90_day_boundary

        PRD §3.7: "if delinquency_days is at least 90 and the HELOC's
        status is still in DRAW or REPAY, the system records a
        DefaultEvent with trigger of DELINQUENCY_90".

        Below threshold: 60 days must NOT trigger DEFAULT.
        """
        borrower, _, _, h = setup_heloc_at_delinquency_days(
            target_days=60,
        )
        # Below the 90-day inclusive threshold, the HELOC must NOT be
        # in DEFAULT and must NOT have a DELINQUENCY_90 trigger.
        assert h["status"] == "DRAW"
        assert h["delinquency_days"] < 90
        assert h.get("default_trigger") is None

    def test_close_at_1094_days_assesses_early_closure_fee(self, api):
        """# difficulty: boundary_precision_check/early_closure_1095_day_boundary

        PRD §3.9: "If that tenure is strictly less than 1095 days
        (three years) and the HELOC's early_closure_fee_cents is
        strictly greater than zero, the system inserts a Fee".

        Boundary: 1094 < 1095 → fee fires.
        """
        borrower, _, _, closed = setup_heloc_closed_no_balance(
            early_closure_fee_cents=15_000,
            days_to_advance_before_close=1094,
        )
        fees, _ = validate_paginated(api.list_fees(
            closed["id"], make_borrower_headers(borrower["id"]),
        ))
        ec = [f for f in fees if f["fee_type"] == "EARLY_CLOSURE"]
        assert len(ec) == 1
        assert ec[0]["amount_cents"] == 15_000

    def test_close_at_exactly_1095_days_does_not_assess_fee(self, api):
        """# difficulty: boundary_precision_check/early_closure_1095_day_boundary

        PRD §3.9: "If that tenure is strictly less than 1095 days
        (three years) and the HELOC's early_closure_fee_cents is
        strictly greater than zero, the system inserts a Fee".

        Boundary: 1095 is NOT strictly less than 1095 → no fee.
        """
        borrower, _, _, closed = setup_heloc_closed_no_balance(
            early_closure_fee_cents=15_000,
            days_to_advance_before_close=EARLY_CLOSURE_WINDOW_DAYS,
        )
        fees, _ = validate_paginated(api.list_fees(
            closed["id"], make_borrower_headers(borrower["id"]),
        ))
        ec = [f for f in fees if f["fee_type"] == "EARLY_CLOSURE"]
        assert len(ec) == 0


# ===========================================================================
# Rule 7: cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:

    # DELETED: test_activation_requires_senior_lien_current
    #
    # Per PRD §3.2: "Activation ... requires the HELOC to be in PENDING
    # — any other state yields ERR_INVALID_STATE — and re-evaluates the
    # CLTV gate so that an in-flight change to the senior lien's balance
    # cannot slip past the origination check; failure here likewise
    # yields ERR_CLTV_EXCEEDED."
    #
    # PRD names ONLY the CLTV gate as re-evaluated at activation. It is
    # silent on whether the lien-currency gate (ERR_NO_SENIOR_LIEN) is
    # re-run.  A PRD-faithful reader could equally well:
    #   (a) re-run the lien gate, returning ERR_NO_SENIOR_LIEN, OR
    #   (b) only re-run CLTV — and with a DEFAULTED senior lien the
    #       CLTV sum drops to zero so CLTV passes, activation succeeds.
    # Both readings are valid PRD-faithful implementations, and a HELOC
    # whose only lien is DEFAULTED has no PRD-stated re-evaluation that
    # would force a 4xx at activation.  This is a unique-derivability
    # failure (STEP 1b: BRANCH-ASYMMETRIC SIDE EFFECT — PRD enumerates
    # one re-check explicitly; reader cannot infer that other gates are
    # also re-checked).  Test deleted per the PRD-First contract.
    # Scaffold rule: cross_entity_state_dependency/heloc_activate_requires_senior_lien_current

    def test_heloc_creation_requires_senior_lien_current(
        self, api, originator_headers,
    ):
        """# difficulty: cross_entity_state_dependency/heloc_activate_requires_senior_lien_current

        PRD §3.2: "There must be at least one existing SeniorLien on
        the same property whose status equals CURRENT, or the request
        is rejected with ERR_NO_SENIOR_LIEN (this enforces the
        second-lien position)."

        Same cross-entity dependency PAIR = (Heloc, SeniorLien)
        exercised at HELOC creation: if the only SeniorLien on the
        property has status=DEFAULTED, the lien gate fails immediately
        with ERR_NO_SENIOR_LIEN. This complements the activation-time
        re-check test above with the create-time leg of the same
        dependency.
        """
        borrower, prop, sl = setup_borrower_property_lien()
        # Default the senior lien BEFORE creating a HELOC.
        post_senior_lien_default_event(sl["id"])
        from test_helpers import create_heloc_payload
        resp = api.create_heloc(
            create_heloc_payload(
                borrower_id=borrower["id"], property_id=prop["id"],
            ),
            originator_headers,
        )
        validate_error(resp, "ERR_NO_SENIOR_LIEN")

    def test_heloc_creation_requires_borrower_solvent(
        self, api, originator_headers,
    ):
        """# difficulty: cross_entity_state_dependency/heloc_creation_requires_borrower_solvent

        PRD §3.2: "The owning borrower's bankruptcy_flag must equal
        false or the request is rejected with ERR_BORROWER_BANKRUPT."
        """
        borrower, prop, _ = setup_borrower_property_lien()
        post_bankruptcy_event(borrower["id"])
        from test_helpers import create_heloc_payload
        resp = api.create_heloc(
            create_heloc_payload(
                borrower_id=borrower["id"], property_id=prop["id"],
            ),
            originator_headers,
        )
        validate_error(resp, "ERR_BORROWER_BANKRUPT")

    def test_bankrupt_borrower_blocks_subsequent_heloc(
        self, api, originator_headers,
    ):
        """# difficulty: cross_entity_state_dependency/heloc_creation_requires_borrower_solvent

        PRD §3.2: "The owning borrower's bankruptcy_flag must equal
        false or the request is rejected with ERR_BORROWER_BANKRUPT."
        PRD §3.6: "The bankruptcy_flag and bankruptcy_filed_at never
        reset to their prior values."
        """
        # First HELOC created and active.
        borrower, prop, _, heloc = setup_active_heloc()
        # Cascade defaults via bankruptcy.
        post_bankruptcy_event(borrower["id"])
        # Create a second property + lien for the same borrower.
        from test_helpers import (
            create_property, create_senior_lien, create_heloc_payload,
        )
        prop2 = create_property(borrower_id=borrower["id"])
        create_senior_lien(property_id=prop2["id"])
        # Attempt to create a second HELOC for the now-bankrupt
        # borrower.
        resp = api.create_heloc(
            create_heloc_payload(
                borrower_id=borrower["id"], property_id=prop2["id"],
            ),
            originator_headers,
        )
        validate_error(resp, "ERR_BORROWER_BANKRUPT")


# ===========================================================================
# Rule 8: resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:

    def test_annual_fee_idempotent_within_anniversary_window(
        self, api,
    ):
        """# difficulty: resource_temporal_overlap/annual_fee_anniversary_window_idempotency

        PRD §3.8: "The annual-fee sweep is idempotent per (heloc_id,
        anniversary_index): for each HELOC, if the current clock time
        has reached or passed origination_date plus 365 days times
        the anniversary index, and no Fee record with fee_type of
        ANNUAL has yet been written for that
        (heloc_id, anniversary_index) pair, the sweep inserts one."
        """
        borrower, _, _, heloc = setup_active_heloc(
            annual_fee_cents=5_000,
            annual_fee_waived_first_year=False,
        )
        advance_clock_days(days=365)
        run_annual_fees_sweep()
        run_annual_fees_sweep()  # second sweep, same window
        fees, _ = validate_paginated(api.list_fees(
            heloc["id"], make_borrower_headers(borrower["id"]),
        ))
        annual = [f for f in fees if f["fee_type"] == "ANNUAL"]
        assert len(annual) == 1
        assert annual[0]["amount_cents"] == 5_000

    def test_annual_fee_second_sweep_returns_zero_fees_created(
        self, api,
    ):
        """# difficulty: resource_temporal_overlap/annual_fee_anniversary_window_idempotency

        PRD §4: "POST /_sweep/annual-fees ... returns the number of
        fees created."
        PRD §3.8: idempotency per (heloc_id, anniversary_index) means
        a repeat sweep in the same window must report 0 fees_created.
        """
        borrower, _, _, heloc = setup_active_heloc(
            annual_fee_cents=5_000,
            annual_fee_waived_first_year=False,
        )
        advance_clock_days(days=365)
        first = run_annual_fees_sweep()
        assert first.get("fees_created", 0) >= 1
        second = run_annual_fees_sweep()
        assert second.get("fees_created", 0) == 0

    def test_billing_cycle_sweep_idempotent_within_cycle(self, api):
        """# difficulty: resource_temporal_overlap/billing_cycle_30day_window_idempotency

        PRD §3.7: "The sweep is idempotent per (heloc_id, cycle_index)
        pair, so re-running the sweep without advancing the clock
        does not double-accrue interest or double-increment
        delinquency."
        """
        borrower, _, _, heloc, _ = setup_active_heloc_with_balance(
            draw_amount_cents=1_000_000,
        )
        advance_clock_days(days=30)
        run_billing_cycle_sweep()
        h1 = get_heloc(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        # Second call, no clock advance.
        run_billing_cycle_sweep()
        h2 = get_heloc(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        assert h2["accrued_interest_cents"] == h1["accrued_interest_cents"]
        assert h2["delinquency_days"] == h1["delinquency_days"]

    def test_billing_cycle_second_sweep_returns_zero_cycles(self, api):
        """# difficulty: resource_temporal_overlap/billing_cycle_30day_window_idempotency

        PRD §4: "POST /_sweep/billing-cycle ... returns the number of
        cycles processed and the number of default transitions it
        triggered."
        PRD §3.7 idempotency per (heloc_id, cycle_index) implies a
        repeat sweep in the same cycle must report 0 cycles_run.
        """
        _borrower, _, _, _heloc, _ = setup_active_heloc_with_balance(
            draw_amount_cents=1_000_000,
        )
        advance_clock_days(days=30)
        first = run_billing_cycle_sweep()
        assert first.get("cycles_run", 0) >= 1
        second = run_billing_cycle_sweep()
        assert second.get("cycles_run", 0) == 0


# ===========================================================================
# Rule 9: compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:

    def test_draw_then_full_repay_restores_available_credit(self, api):
        """# difficulty: compensating_invariant/draw_plus_payment_conserves_available_credit_when_full_repaid

        PRD §3.3: "it adds amount_cents to the HELOC's
        principal_balance_cents and subtracts amount_cents from its
        available_credit_cents".
        PRD §3.4: "the system applies a waterfall allocation that
        settles accrued interest before principal ... its
        principal_balance_cents is reduced by the principal component
        but never permitted to drop below zero".

        Draw 750_000 + accrue one cycle + pay exactly
        (750_000 + accrued) → principal back to 0, available back to
        credit_limit.
        """
        borrower, _, _, heloc = setup_active_heloc(
            credit_limit_cents=2_000_000,
        )
        avail_pre = heloc["available_credit_cents"]
        assert avail_pre == 2_000_000
        # Take a draw.
        bh = make_borrower_headers(borrower["id"])
        post_draw(
            heloc["id"], amount_cents=750_000, borrower_headers=bh,
        )
        # Advance and sweep to accrue one cycle of interest.
        advance_clock_days(days=30)
        run_billing_cycle_sweep()
        h_mid = get_heloc(heloc["id"], bh)
        accrued_mid = h_mid["accrued_interest_cents"]
        # Compensating payment.
        post_payment(
            heloc["id"], amount_cents=750_000 + accrued_mid,
            headers=bh,
        )
        h_after = get_heloc(heloc["id"], bh)
        assert h_after["principal_balance_cents"] == 0
        assert h_after["available_credit_cents"] == 2_000_000
        assert h_after["accrued_interest_cents"] == 0

    def test_credit_conservation_invariant_at_every_observation(
        self, api,
    ):
        """# difficulty: compensating_invariant/draw_plus_payment_conserves_available_credit_when_full_repaid

        PRD §3.3: "it adds amount_cents to the HELOC's
        principal_balance_cents and subtracts amount_cents from its
        available_credit_cents".

        Invariant: available_credit_cents + principal_balance_cents
        == credit_limit_cents at every observation while status in
        {DRAW, REPAY, DEFAULT}.
        """
        from test_helpers import assert_credit_conservation
        borrower, _, _, heloc = setup_active_heloc(
            credit_limit_cents=1_500_000,
        )
        bh = make_borrower_headers(borrower["id"])
        # Take three draws and verify invariant after each.
        for amt in (500_000, 250_000, 100_000):
            post_draw(heloc["id"], amount_cents=amt, borrower_headers=bh)
            h = get_heloc(heloc["id"], bh)
            assert_credit_conservation(h)

    def test_rate_reset_round_trip_returns_to_starting_rate(
        self, api, servicer_headers,
    ):
        """# difficulty: compensating_invariant/rate_reset_round_trip_conserves_current_rate

        PRD §3.5: "The first clamp is the periodic cap: the
        difference between requested_rate_bps and the HELOC's
        current_rate_bps immediately before the reset is compared to
        periodic_cap_bps; if the difference is strictly greater than
        periodic_cap_bps, the periodic-clamped value is
        current_rate_bps + periodic_cap_bps; if the difference is
        strictly less than the negative of periodic_cap_bps, the
        periodic-clamped value is current_rate_bps - periodic_cap_bps;
        otherwise the periodic-clamped value is exactly the
        requested_rate_bps."
        PRD §3.5: "The resulting applied_rate_bps becomes the HELOC's
        new current_rate_bps".

        When NO clamp is active on either leg, a P → P0 round trip
        leaves current_rate_bps equal to its starting value.
        Start current=800; leg 1: prime=700 → req=1000, delta=200 <
        cap 500 → applied=1000. Leg 2: prime=500 → req=800,
        delta=-200, |delta|<500 → applied=800.
        """
        _, _, _, heloc = setup_active_heloc(
            margin_bps=300,
            periodic_cap_bps=500,
            lifetime_cap_bps=2500,
            lifetime_floor_bps=100,
            prime_rate_bps_at_origination=500,  # current=800
        )
        assert heloc["current_rate_bps"] == 800
        post_rate_reset(
            heloc["id"], prime_rate_bps=700,
            servicer_headers=servicer_headers,
        )
        post_rate_reset(
            heloc["id"], prime_rate_bps=500,
            servicer_headers=servicer_headers,
        )
        h = get_heloc(heloc["id"])
        assert h["current_rate_bps"] == 800

    def test_rate_reset_round_trip_three_legs_unchanged(
        self, api, servicer_headers,
    ):
        """# difficulty: compensating_invariant/rate_reset_round_trip_conserves_current_rate

        PRD §3.5: same clamp formula; with three resets that each
        respect the periodic cap and never touch lifetime bounds, the
        composite path is order-independent in the sense that
        compensating moves balance.

        Path: 800 → 900 (+100) → 1000 (+100) → 800 (-200). Each leg
        respects cap=500. End current_rate==800.
        """
        _, _, _, heloc = setup_active_heloc(
            margin_bps=300,
            periodic_cap_bps=500,
            lifetime_cap_bps=2500,
            lifetime_floor_bps=100,
            prime_rate_bps_at_origination=500,
        )
        # +100 to 900: prime=600 → req=900 → applied=900
        post_rate_reset(
            heloc["id"], prime_rate_bps=600,
            servicer_headers=servicer_headers,
        )
        # +100 to 1000: prime=700 → req=1000 → applied=1000
        post_rate_reset(
            heloc["id"], prime_rate_bps=700,
            servicer_headers=servicer_headers,
        )
        # -200 to 800: prime=500 → req=800 → applied=800
        post_rate_reset(
            heloc["id"], prime_rate_bps=500,
            servicer_headers=servicer_headers,
        )
        h = get_heloc(heloc["id"])
        assert h["current_rate_bps"] == 800
