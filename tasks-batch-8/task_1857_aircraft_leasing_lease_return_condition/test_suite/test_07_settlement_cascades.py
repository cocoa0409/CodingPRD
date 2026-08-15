"""Settlement netting (pinned evaluation order), the settlement 3-link
cascade with slot auto-confirm, and the repossession 3-link cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_lease_reserve_invariants,
    create_active_lease,
    create_default_case,
    create_lease_with_return_initiated,
    create_reserve_claim_payload,
    create_return_case_agreed,
    make_legal_approver_headers,
    make_lessee_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["lessor_admin_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]


class TestSettlementNetting:
    def test_evaluation_order_offset_then_forfeit(self, api):
        """PRD §3.6: "It runs the reserve netting in one pinned order: first
        the current `reserve_balance_cents` is taken as the balance; second,
        `reserve_applied_cents` is set to the lesser of that balance and
        `agreed_total_cents`; third, `settlement_cash_due_cents` is set to
        `agreed_total_cents` minus `reserve_applied_cents` — the cash the
        lessee still owes; fourth, the forfeiture is the balance minus
        `reserve_applied_cents`, added into the lease's
        `reserve_forfeited_cents`; and fifth, the lease's
        `reserve_balance_cents` is zeroed. Reordering these steps — say,
        forfeiting the balance before offsetting it — yields different
        applied and cash-due figures, so the order above is normative."

        Design: Difficulty/combinatorial_formula/settlement_netting_evaluation_order
        """
        # Reserve ledger: accrued 560000 (100.0h/20 cycles), paid claim 60000
        # -> balance 500000. Agreed total 300000 < balance.
        lease, aircraft, lessee, rc, _insp = create_return_case_agreed(
            proposal_cents=300000,
            non_compliant={"ENGINE": 80000},
            reserve_report={"period_month": "2026-08", "flight_hours": 100.0,
                            "flight_cycles": 20},
            paid_claim_cents=60000)
        lease_mid = validate_success(api.get_lease(lease["id"], ADMIN))
        assert lease_mid["reserve_balance_cents"] == 500000

        settled = validate_success(api.settle_return_case(rc["id"], FINANCE))
        # min(balance 500000, agreed 300000), computed BEFORE forfeiture.
        assert settled["reserve_applied_cents"] == 300000
        assert settled["settlement_cash_due_cents"] == 0

        lease_now = validate_success(api.get_lease(lease["id"], ADMIN))
        assert lease_now["reserve_forfeited_cents"] == 200000, (
            f"balance 500000 - applied 300000 = 200000, got "
            f"{lease_now['reserve_forfeited_cents']}")
        # §3.6 step five zeroes the balance outright; the §2.9 derived
        # invariant is not re-asserted here because the pinned netting order
        # (forfeiture = balance - applied; balance := 0) deliberately leaves
        # accrued - reimbursed - forfeited != 0 once the reserve is closed.
        assert lease_now["reserve_balance_cents"] == 0

    def test_settlement_with_empty_reserve_pays_full_cash(self, api):
        """PRD §3.6: "It runs the reserve netting in one pinned order: first
        the current `reserve_balance_cents` is taken as the balance; second,
        `reserve_applied_cents` is set to the lesser of that balance and
        `agreed_total_cents`; third, `settlement_cash_due_cents` is set to
        `agreed_total_cents` minus `reserve_applied_cents` — the cash the
        lessee still owes"

        Design: Difficulty/combinatorial_formula/settlement_netting_evaluation_order
        """
        lease, _aircraft, _lessee, rc, _insp = create_return_case_agreed(
            proposal_cents=50000, non_compliant={"ENGINE": 80000})
        settled = validate_success(api.settle_return_case(rc["id"], FINANCE))
        assert settled["reserve_applied_cents"] == 0
        assert settled["settlement_cash_due_cents"] == 50000
        lease_now = validate_success(api.get_lease(lease["id"], ADMIN))
        assert lease_now["reserve_balance_cents"] == 0
        assert_lease_reserve_invariants(lease_now)


class TestSettlementCascade:
    def test_settlement_cascade_depth3_and_slot_autoconfirm(self, api):
        """PRD §3.6: "Finally the handback cascade fires: the lease moves
        `RETURN_INITIATED → RETURNED`; because that lease is the one
        currently on the aircraft, the aircraft moves `ON_LEASE →
        IN_TRANSITION`; and that aircraft change auto-confirms a transition
        slot — among the aircraft's slots in `TENTATIVE` whose window covers
        the settle date (window start on or before the date and window end on
        or after it), the one with the earliest `window_start` wins, ties
        broken by `created_at` ascending, and if no slot qualifies none is
        confirmed."
        PRD §3.6: "Settlement then closes out the case's loose ends: every
        checklist item still `NON_COMPLIANT` cascades to `COMPENSATED`, and
        every reserve claim of the lease still `SUBMITTED` or `APPROVED`
        cascades to `REJECTED` while `PAID` claims are left untouched."

        Design: Difficulty/transitive_cascade/settlement_cascade_depth3_and_slot_autoconfirm
        """
        # Agreed at 50000 with an empty reserve; the settle date is the
        # logical-clock default 2026-08-01, covered by the slot window.
        lease, aircraft, _lessee, rc, _insp = create_return_case_agreed(
            proposal_cents=50000, non_compliant={"ENGINE": 80000})
        slot = validate_success(
            api.create_transition_slot(
                aircraft["id"],
                {"window_start": "2026-08-01", "window_end": "2026-08-15"},
                ADMIN),
            expected_status=201)
        assert slot["status"] == "TENTATIVE"

        settled = validate_success(api.settle_return_case(rc["id"], FINANCE))
        assert settled["status"] == "SETTLED"
        assert settled["settlement_cash_due_cents"] == 50000

        lease_now = validate_success(api.get_lease(lease["id"], ADMIN))
        assert lease_now["status"] == "RETURNED", (
            f"cascade link 1: lease must be RETURNED, got {lease_now['status']!r}")
        aircraft_now = validate_success(api.get_aircraft(aircraft["id"], ADMIN))
        assert aircraft_now["status"] == "IN_TRANSITION", (
            f"cascade link 2: aircraft must be IN_TRANSITION, got {aircraft_now['status']!r}")
        slots, _meta = validate_paginated(api.list_transition_slots(aircraft["id"], ADMIN))
        assert slots[0]["status"] == "CONFIRMED", (
            f"cascade link 3: covering TENTATIVE slot auto-confirmed, got {slots[0]['status']!r}")

        items, _meta = validate_paginated(api.list_checklist_items(rc["id"], ADMIN))
        by_code = {i["item_code"]: i for i in items}
        assert by_code["ENGINE"]["status"] == "COMPENSATED", (
            "conditional cascade: NON_COMPLIANT item -> COMPENSATED")

    def test_settlement_rejects_open_claims_and_keeps_paid(self, api):
        """PRD §3.6: "Settlement then closes out the case's loose ends: every
        checklist item still `NON_COMPLIANT` cascades to `COMPENSATED`, and
        every reserve claim of the lease still `SUBMITTED` or `APPROVED`
        cascades to `REJECTED` while `PAID` claims are left untouched."

        Design: Difficulty/transitive_cascade/settlement_cascade_depth3_and_slot_autoconfirm
        """
        # PAID claim of 60000 against accrued 560000 leaves balance 500000;
        # a second claim is left SUBMITTED (never decided) into settlement.
        lease, aircraft, lessee, rc, _insp = create_return_case_agreed(
            proposal_cents=300000,
            non_compliant={"ENGINE": 80000},
            reserve_report={"period_month": "2026-08", "flight_hours": 100.0,
                            "flight_cycles": 20},
            paid_claim_cents=60000)
        open_claim = validate_success(
            api.create_reserve_claim(
                lease["id"],
                create_reserve_claim_payload(claimed_amount_cents=12345),
                make_lessee_rep_headers(lessee["id"])),
            expected_status=201)
        assert open_claim["status"] == "SUBMITTED"

        settled = validate_success(api.settle_return_case(rc["id"], FINANCE))
        assert settled["status"] == "SETTLED"

        claims, _meta = validate_paginated(api.list_reserve_claims(lease["id"], ADMIN))
        by_amount = {c["claimed_amount_cents"]: c["status"] for c in claims}
        assert by_amount[60000] == "PAID", (
            "PAID claims are untouched by settlement")
        assert by_amount[12345] == "REJECTED", (
            "SUBMITTED claims cascade to REJECTED at settlement")


class TestRepossessionCascade:
    def test_repossession_cascade_depth3(self, api):
        """PRD §3.8: "A `LessorAdmin` executing on a `REPOSSESSION_AUTHORIZED`
        case moves it to `REPOSSESSED` and fires a three-link cascade: the
        lease moves `DEFAULTED → TERMINATED`; because that lease is the one
        currently on the aircraft, the aircraft moves `ON_LEASE →
        REPOSSESSED`; and that seizure conditionally releases the aircraft's
        future — every transition slot of the aircraft in `TENTATIVE` or
        `CONFIRMED` moves to `RELEASED`, while `COMPLETED` or
        already-`RELEASED` slots are untouched — and any return case of the
        lease not yet `SETTLED` or `CANCELLED` is cascaded to `CANCELLED`."

        Design: Difficulty/transitive_cascade/repossession_cascade_depth3
        """
        # ACTIVE lease with a return under way and a TENTATIVE slot on the
        # aircraft; default declared 2026-08-01 with a 30-day cure.
        lease, aircraft, _lessee, rc = create_lease_with_return_initiated()
        slot = validate_success(
            api.create_transition_slot(
                aircraft["id"],
                {"window_start": "2026-09-10", "window_end": "2026-09-20",
                 "next_operator_ref": "NEXT-OP-1"},
                ADMIN),
            expected_status=201)
        case = create_default_case(lease["id"], declared_by="cred_1",
                                   reason="rent arrears 2 months", cure_period_days=30)
        # Move the clock strictly past the cure deadline and authorize with a
        # distinct legal approver.
        validate_success(api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, ADMIN))
        authorized = validate_success(
            api.authorize_repossession(case["id"], make_legal_approver_headers("legal_1")))
        assert authorized["status"] == "REPOSSESSION_AUTHORIZED"

        executed = validate_success(api.execute_repossession(case["id"], ADMIN))
        assert executed["status"] == "REPOSSESSED"

        lease_now = validate_success(api.get_lease(lease["id"], ADMIN))
        assert lease_now["status"] == "TERMINATED", (
            f"link 1: lease must be TERMINATED, got {lease_now['status']!r}")
        aircraft_now = validate_success(api.get_aircraft(aircraft["id"], ADMIN))
        assert aircraft_now["status"] == "REPOSSESSED", (
            f"link 2: aircraft must be REPOSSESSED, got {aircraft_now['status']!r}")
        slots, _meta = validate_paginated(api.list_transition_slots(aircraft["id"], ADMIN))
        assert slots[0]["status"] == "RELEASED", (
            f"link 3: slot must be RELEASED, got {slots[0]['status']!r}")
        cases, _meta = validate_paginated(api.list_return_cases(lease["id"], ADMIN))
        assert cases[0]["status"] == "CANCELLED", (
            f"open return case must be cascaded to CANCELLED, got {cases[0]['status']!r}")

    def test_repossession_requires_authorized_state(self, api):
        """PRD §3.8: "A `LessorAdmin` executing on a `REPOSSESSION_AUTHORIZED`
        case moves it to `REPOSSESSED`"
        PRD §2.8 (5): "State preconditions — the target resource is in a
        from-state the transition allows, including terminal-state lockdown
        and the one-open-child rules (else `ERR_INVALID_STATE`, HTTP 409; ...)"

        Design: Difficulty/transitive_cascade/repossession_cascade_depth3
        """
        lease, _aircraft, _lessee = create_active_lease()
        case = create_default_case(lease["id"], declared_by="cred_1")
        # Executing straight from DECLARED is not a legal transition.
        resp = api.execute_repossession(case["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
