"""Invoice computation (provisional vs final), contract draw-down, and the budget ledger."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_invoice, assert_contract_ledger,
    create_contract, create_approved_version, create_facilitator, create_scheduled_cohort,
    setup_open_cohort, setup_locked_cohort_with_confirmed, setup_delivered_cohort_with_attendance,
    register_learner, confirm_learner, register_and_confirm, lock_cohort, current_cohort_version,
    set_clock, invoice_by_variant, get_cohort_invoices, make_learner_headers,
    TEST_USERS,
)

DESIGNER = TEST_USERS["program_designer_headers"]
COORD = TEST_USERS["scheduling_coordinator_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]


def test_seat_price_flat_locked_zero(api):
    """PRD §3.6: "When a registration confirms, the system reads the cohort's program version:
    under `PER_SEAT` pricing the registration's `seat_price_cents` is set to the version's
    `per_seat_cents`; under `FLAT` pricing it is set to 0, because flat tuition is billed once at
    the cohort level rather than per seat."

    Design: Corner/calculations/seat_price_flat_locked_zero
    """
    ctx = setup_open_cohort(
        category="SALES", pricing_model="FLAT",
        version_overrides={"flat_fee_cents": 150000, "min_seats": 1},
    )
    reg = register_learner(ctx["cohort"]["id"], "sp@example.com")
    data = validate_success(api.confirm_registration(reg["id"], make_learner_headers("sp@example.com")))
    assert data["seat_price_cents"] == 0


class TestDualVariantInvoice:
    def test_provisional_vs_final_diverge_on_no_show(self, api):
        """PRD §3.6: "The `PROVISIONAL` invoice is produced at the lock transition and counts the
        seats then in `CONFIRMED` state — a snapshot of confirmed seats at lock time. The `FINAL`
        invoice is produced at the close transition and counts only the seats in `ATTENDED` state,
        deliberately excluding `NO_SHOW` seats."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_diverge_on_no_show
        """
        ctx = setup_delivered_cohort_with_attendance(
            num_confirmed=3, num_attended=2, delivery_mode="ONSITE", category="TECHNICAL",
            per_seat_cents=50000, materials_kit_cents=2500, travel_base_cents=10000,
            min_seats=2, seat_capacity=5,
        )
        coh_id = ctx["cohort"]["id"]
        prov = invoice_by_variant(coh_id, "PROVISIONAL")
        assert prov["total_cents"] == 167500, "150000 tuition + 7500 materials + 10000 travel"
        validate_success(api.close_cohort(coh_id, COORD))
        final = invoice_by_variant(coh_id, "FINAL")
        assert final["total_cents"] == 115000, "100000 tuition + 5000 materials + 10000 travel"
        assert prov["total_cents"] != final["total_cents"]
        assert_invoice(prov)
        assert_invoice(final)

    def test_provisional_invoice_components_at_lock(self, api):
        """PRD §3.6: "The `PROVISIONAL` invoice is produced at the lock transition and counts the
        seats then in `CONFIRMED` state — a snapshot of confirmed seats at lock time." PRD §3.6:
        "Tuition under `PER_SEAT` pricing is the version's `per_seat_cents` multiplied by the
        relevant seat count ... The materials charge is always the version's `materials_kit_cents`
        multiplied by the relevant seat count. The travel charge is the lead facilitator's
        `travel_base_cents` when the cohort's delivery mode is `ONSITE` or `HYBRID`".

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_diverge_on_no_show
        """
        ctx = setup_locked_cohort_with_confirmed(
            num_confirmed=3, delivery_mode="ONSITE", category="TECHNICAL", per_seat_cents=50000,
            materials_kit_cents=2500, travel_base_cents=10000, min_seats=2, seat_capacity=5,
        )
        prov = invoice_by_variant(ctx["cohort"]["id"], "PROVISIONAL")
        assert prov["variant"] == "PROVISIONAL"
        assert prov["tuition_cents"] == 150000, "50000 * 3 confirmed"
        assert prov["materials_cents"] == 7500, "2500 * 3 confirmed"
        assert prov["travel_cents"] == 10000, "ONSITE includes travel"
        assert prov["total_cents"] == 167500

    def test_contract_reserved_vs_committed_diverge(self, api):
        """PRD §3.7: "At lock, the provisional invoice total is reserved against the contract's
        available budget — a soft hold that decreases what new cohorts can draw on but leaves
        `committed_cents` at 0". PRD §3.7: "At close, the final invoice total (over attended seats
        only) is committed: `committed_cents` rises permanently".

        Design: Difficulty/dual_variant_calc/contract_reserved_vs_committed_diverge
        """
        contract = create_contract(budget_cents=500000, client_name="Acme")
        ctx = setup_delivered_cohort_with_attendance(
            num_confirmed=3, num_attended=2, delivery_mode="ONSITE", category="TECHNICAL",
            contract_id=contract["id"], per_seat_cents=50000, materials_kit_cents=2500,
            travel_base_cents=10000, min_seats=2, seat_capacity=5,
        )
        # NOTE: committed_cents is read after deliver but before close; it must still be 0
        # because the lock-time hold is a soft reservation, not a commitment.
        coh_id = ctx["cohort"]["id"]
        after_lock = validate_success(api.get_contract(contract["id"], FINANCE))
        assert after_lock["committed_cents"] == 0, "RESERVED hold leaves committed at 0"
        validate_success(api.close_cohort(coh_id, COORD))
        after_close = validate_success(api.get_contract(contract["id"], FINANCE))
        assert after_close["committed_cents"] == 115000, "COMMITTED = FINAL over 2 ATTENDED"
        assert after_close["remaining_cents"] == 385000
        assert_contract_ledger(after_close)


    def test_committed_zero_at_lock_for_contract_cohort(self, api):
        """PRD §3.7: "At lock, the provisional invoice total is reserved against the contract's
        available budget — a soft hold that decreases what new cohorts can draw on but leaves
        `committed_cents` at 0".

        Design: Difficulty/dual_variant_calc/contract_reserved_vs_committed_diverge
        """
        contract = create_contract(budget_cents=500000, client_name="Reserve Co")
        ctx = setup_locked_cohort_with_confirmed(
            num_confirmed=3, delivery_mode="ONSITE", category="TECHNICAL",
            contract_id=contract["id"], per_seat_cents=50000, materials_kit_cents=2500,
            travel_base_cents=10000, min_seats=1, seat_capacity=5,
        )
        after_lock = validate_success(api.get_contract(contract["id"], FINANCE))
        assert after_lock["committed_cents"] == 0, "lock-time hold leaves committed at 0"
        assert after_lock["status"] == "ACTIVE"
        assert_contract_ledger(after_lock)


class TestCombinatorialFormula:
    def test_invoice_three_input_branching_formula(self, api):
        """PRD §3.6: "Tuition under `PER_SEAT` pricing is the version's `per_seat_cents`
        multiplied by the relevant seat count; under `FLAT` pricing tuition is the version's
        `flat_fee_cents`, independent of seat count. The materials charge is always the version's
        `materials_kit_cents` multiplied by the relevant seat count. The travel charge is the lead
        facilitator's `travel_base_cents` when the cohort's delivery mode is `ONSITE` or `HYBRID`,
        and 0 otherwise."

        Design: Difficulty/combinatorial_formula/invoice_three_input_branching_formula
        """
        ctx = setup_locked_cohort_with_confirmed(
            num_confirmed=4, category="SALES", delivery_mode="VIRTUAL", pricing_model="FLAT",
            flat_fee_cents=200000, materials_kit_cents=3000, travel_base_cents=99999,
            min_seats=1, seat_capacity=6,
        )
        prov = invoice_by_variant(ctx["cohort"]["id"], "PROVISIONAL")
        assert prov["tuition_cents"] == 200000, "FLAT branch independent of 4 seats"
        assert prov["materials_cents"] == 12000, "3000 * 4 confirmed seats"
        assert prov["travel_cents"] == 0, "VIRTUAL suppresses travel"
        assert prov["total_cents"] == 212000

    def test_invoice_flat_tuition_independent_of_seat_count(self, api):
        """PRD §3.6: "under `FLAT` pricing tuition is the version's `flat_fee_cents`, independent
        of seat count." PRD §3.6: "The travel charge is the lead facilitator's `travel_base_cents`
        when the cohort's delivery mode is `ONSITE` or `HYBRID`, and 0 otherwise."

        Design: Difficulty/combinatorial_formula/invoice_three_input_branching_formula
        """
        # Two confirmed seats this time; FLAT tuition must still equal flat_fee, not scale.
        ctx = setup_locked_cohort_with_confirmed(
            num_confirmed=2, category="SALES", delivery_mode="VIRTUAL", pricing_model="FLAT",
            flat_fee_cents=200000, materials_kit_cents=3000, travel_base_cents=99999,
            min_seats=1, seat_capacity=6,
        )
        prov = invoice_by_variant(ctx["cohort"]["id"], "PROVISIONAL")
        assert prov["tuition_cents"] == 200000, "FLAT tuition independent of 2 seats"
        assert prov["materials_cents"] == 6000, "3000 * 2 seats"
        assert prov["travel_cents"] == 0, "VIRTUAL suppresses travel"

    def test_contract_drawdown_pinned_eval_order(self, api):
        """PRD §3.7: "The evaluation order is pinned: the `FINAL` invoice total is computed first,
        over attended seats, and only then drawn against the sponsoring contract." PRD §3.7: "If
        the draw would exceed the contract's `remaining_cents`, the close is rejected with
        `ERR_CONTRACT_BUDGET_EXCEEDED`; the comparison is strict, so a draw exactly equal to the
        remaining budget is allowed."

        Design: Difficulty/combinatorial_formula/contract_drawdown_pinned_eval_order
        """
        contract = create_contract(budget_cents=120000, client_name="Tight")
        ctx = setup_delivered_cohort_with_attendance(
            num_confirmed=3, num_attended=2, delivery_mode="ONSITE", category="TECHNICAL",
            contract_id=contract["id"], per_seat_cents=50000, materials_kit_cents=2500,
            travel_base_cents=10000, min_seats=2, seat_capacity=5,
        )
        # PROVISIONAL was 167500 > 120000; if the draw used provisional, close would wrongly fail.
        coh_id = ctx["cohort"]["id"]
        validate_success(api.close_cohort(coh_id, COORD))  # FINAL 115000 <= 120000 succeeds
        after = validate_success(api.get_contract(contract["id"], FINANCE))
        assert after["committed_cents"] == 115000
        assert after["remaining_cents"] == 5000


    def test_final_invoice_excludes_no_show_proves_eval_order(self, api):
        """PRD §3.7: "The evaluation order is pinned: the `FINAL` invoice total is computed first,
        over attended seats, and only then drawn against the sponsoring contract. The draw equals
        the final invoice's `total_cents`."

        Design: Difficulty/combinatorial_formula/contract_drawdown_pinned_eval_order
        """
        contract = create_contract(budget_cents=120000, client_name="Tight2")
        ctx = setup_delivered_cohort_with_attendance(
            num_confirmed=3, num_attended=2, delivery_mode="ONSITE", category="TECHNICAL",
            contract_id=contract["id"], per_seat_cents=50000, materials_kit_cents=2500,
            travel_base_cents=10000, min_seats=2, seat_capacity=5,
        )
        coh_id = ctx["cohort"]["id"]
        validate_success(api.close_cohort(coh_id, COORD))
        final = invoice_by_variant(coh_id, "FINAL")
        assert final["total_cents"] == 115000, "FINAL over 2 ATTENDED seats, NO_SHOW excluded"
        after = validate_success(api.get_contract(contract["id"], FINANCE))
        assert after["committed_cents"] == final["total_cents"], "draw equals FINAL total"


class TestTransitiveAndBoundary:
    def test_close_final_invoice_drives_contract_exhausted_chain(self, api):
        """PRD §3.7: "On a successful draw, the contract's `committed_cents` increases by the
        draw, its `remaining_cents` is recomputed as `budget_cents` minus `committed_cents`, and
        if the recomputed remaining reaches exactly 0 the contract automatically transitions to
        `EXHAUSTED`."

        Design: Difficulty/transitive_cascade/close_final_invoice_drives_contract_exhausted_chain
        """
        contract = create_contract(budget_cents=115000, client_name="Chain Co")
        ctx = setup_delivered_cohort_with_attendance(
            num_confirmed=2, num_attended=2, delivery_mode="ONSITE", category="TECHNICAL",
            contract_id=contract["id"], per_seat_cents=50000, materials_kit_cents=2500,
            travel_base_cents=10000, min_seats=1, seat_capacity=3,
        )
        coh_id = ctx["cohort"]["id"]
        validate_success(api.close_cohort(coh_id, COORD))
        final = invoice_by_variant(coh_id, "FINAL")
        assert final["total_cents"] == 115000, "L1: 2 ATTENDED * 50000 + 2 * 2500 + 10000"
        after = validate_success(api.get_contract(contract["id"], FINANCE))
        assert after["committed_cents"] == 115000, "L2: FINAL total drawn"
        assert after["remaining_cents"] == 0
        assert after["status"] == "EXHAUSTED", "L3: committed reaching budget flips status"

    def test_close_chain_remaining_recomputed(self, api):
        """PRD §3.7: "On a successful draw, the contract's `committed_cents` increases by the
        draw, its `remaining_cents` is recomputed as `budget_cents` minus `committed_cents`".

        Design: Difficulty/transitive_cascade/close_final_invoice_drives_contract_exhausted_chain
        """
        contract = create_contract(budget_cents=200000, client_name="Chain Co 2")
        ctx = setup_delivered_cohort_with_attendance(
            num_confirmed=2, num_attended=2, delivery_mode="ONSITE", category="TECHNICAL",
            contract_id=contract["id"], per_seat_cents=50000, materials_kit_cents=2500,
            travel_base_cents=10000, min_seats=1, seat_capacity=3,
        )
        validate_success(api.close_cohort(ctx["cohort"]["id"], COORD))
        after = validate_success(api.get_contract(contract["id"], FINANCE))
        assert after["committed_cents"] == 115000
        assert after["remaining_cents"] == 85000, "200000 - 115000"
        assert after["status"] == "ACTIVE", "budget not exhausted at 85000 remaining"

    def test_draw_equals_remaining_allowed_boundary(self, api):
        """PRD §3.7: "If the draw would exceed the contract's `remaining_cents`, the close is
        rejected with `ERR_CONTRACT_BUDGET_EXCEEDED`; the comparison is strict, so a draw exactly
        equal to the remaining budget is allowed." PRD §3.7: "if the recomputed remaining reaches
        exactly 0 the contract automatically transitions to `EXHAUSTED`."

        Design: Difficulty/boundary_precision_check/contract_draw_equals_remaining_allowed_boundary
        """
        contract = create_contract(budget_cents=115000, client_name="Exact")
        ctx = setup_delivered_cohort_with_attendance(
            num_confirmed=2, num_attended=2, delivery_mode="ONSITE", category="TECHNICAL",
            contract_id=contract["id"], per_seat_cents=50000, materials_kit_cents=2500,
            travel_base_cents=10000, min_seats=1, seat_capacity=3,
        )
        coh_id = ctx["cohort"]["id"]
        validate_success(api.close_cohort(coh_id, COORD))  # draw 115000 == remaining 115000
        after = validate_success(api.get_contract(contract["id"], FINANCE))
        assert after["remaining_cents"] == 0
        assert after["status"] == "EXHAUSTED"

    def test_draw_equals_remaining_close_succeeds_committed_full(self, api):
        """PRD §3.7: "the comparison is strict, so a draw exactly equal to the remaining budget is
        allowed." PRD §3.7: "On a successful draw, the contract's `committed_cents` increases by
        the draw".

        Design: Difficulty/boundary_precision_check/contract_draw_equals_remaining_allowed_boundary
        """
        contract = create_contract(budget_cents=115000, client_name="Exact2")
        ctx = setup_delivered_cohort_with_attendance(
            num_confirmed=2, num_attended=2, delivery_mode="ONSITE", category="TECHNICAL",
            contract_id=contract["id"], per_seat_cents=50000, materials_kit_cents=2500,
            travel_base_cents=10000, min_seats=1, seat_capacity=3,
        )
        coh = validate_success(api.close_cohort(ctx["cohort"]["id"], COORD))  # 200 OK, not rejected
        assert coh["status"] == "CLOSED"
        after = validate_success(api.get_contract(contract["id"], FINANCE))
        assert after["committed_cents"] == 115000, "exact draw committed in full"

    def test_budget_exceeded_on_close(self, api):
        """PRD §3.7: "If the draw would exceed the contract's `remaining_cents`, the close is
        rejected with `ERR_CONTRACT_BUDGET_EXCEEDED`".

        Design: Corner/errors/contract_budget_exceeded_on_close
        """
        contract = create_contract(budget_cents=50000, client_name="Over Co")
        ctx = setup_delivered_cohort_with_attendance(
            num_confirmed=2, num_attended=2, delivery_mode="ONSITE", category="TECHNICAL",
            contract_id=contract["id"], per_seat_cents=50000, materials_kit_cents=2500,
            travel_base_cents=10000, min_seats=1, seat_capacity=3,
        )
        resp = api.close_cohort(ctx["cohort"]["id"], COORD)  # FINAL 115000 > 50000
        validate_error(resp, ApiErrorId.ERR_CONTRACT_BUDGET_EXCEEDED.value)


class TestCompensatingInvariant:
    def test_cancel_restores_contract_reservation(self, api):
        """PRD §2.6: "if the cohort had reserved budget against a contract that reservation is
        released and the contract's available budget restored." PRD §3.7: "a soft hold ... that is
        fully released if the cohort is later cancelled."

        Design: Difficulty/compensating_invariant/cancel_restores_contract_reservation_committed_unchanged
        """
        contract = create_contract(budget_cents=300000, client_name="Inv1")
        ctx = setup_locked_cohort_with_confirmed(
            num_confirmed=2, category="TECHNICAL", delivery_mode="ONSITE", contract_id=contract["id"],
            per_seat_cents=50000, materials_kit_cents=2500, travel_base_cents=10000,
            min_seats=1, seat_capacity=4,
        )
        before = validate_success(api.get_contract(contract["id"], FINANCE))
        assert before["committed_cents"] == 0
        assert before["remaining_cents"] == 300000
        validate_success(api.cancel_cohort(ctx["cohort"]["id"], COORD))
        after = validate_success(api.get_contract(contract["id"], FINANCE))
        assert after["committed_cents"] == 0, "forward (lock) + compensating (cancel) leave it 0"
        assert after["remaining_cents"] == 300000, "full release"


    def test_cancel_voids_provisional_invoice(self, api):
        """PRD §2.6: "any `PROVISIONAL` or `FINAL` `Invoice` attached to the cohort transitions to
        `VOID`, and if the cohort had reserved budget against a contract that reservation is
        released and the contract's available budget restored."

        Design: Difficulty/compensating_invariant/cancel_restores_contract_reservation_committed_unchanged
        """
        contract = create_contract(budget_cents=300000, client_name="Inv2")
        ctx = setup_locked_cohort_with_confirmed(
            num_confirmed=2, category="TECHNICAL", delivery_mode="ONSITE", contract_id=contract["id"],
            per_seat_cents=50000, materials_kit_cents=2500, travel_base_cents=10000,
            min_seats=1, seat_capacity=4,
        )
        coh_id = ctx["cohort"]["id"]
        validate_success(api.cancel_cohort(coh_id, COORD))
        prov = invoice_by_variant(coh_id, "PROVISIONAL")
        assert prov is not None and prov["status"] == "VOID", "provisional invoice voided on cancel"
        after = validate_success(api.get_contract(contract["id"], FINANCE))
        assert after["remaining_cents"] == 300000, "reservation released, budget restored"


class TestContractLifecycle:
    def test_close_blocked_by_active_cohort(self, api):
        """PRD §3.9: "A close is blocked while any cohort referencing the contract is still in
        `OPEN`, `LOCKED`, `RUNNING`, or `DELIVERED`; such a request is rejected with
        `ERR_CONTRACT_HAS_OPEN_COHORTS`."

        Design: Difficulty/cross_entity_state_dependency/contract_close_blocked_by_active_cohort
        """
        contract = create_contract(budget_cents=100000, client_name="Block")
        ctx = setup_open_cohort(
            contract_id=contract["id"],
            version_overrides={"per_seat_cents": 10000, "min_seats": 1},
        )
        # cohort is OPEN and references the contract
        resp = api.close_contract(contract["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_HAS_OPEN_COHORTS.value)

    def test_close_blocked_by_locked_cohort(self, api):
        """PRD §3.9: "A close is blocked while any cohort referencing the contract is still in
        `OPEN`, `LOCKED`, `RUNNING`, or `DELIVERED`; such a request is rejected with
        `ERR_CONTRACT_HAS_OPEN_COHORTS`."

        Design: Difficulty/cross_entity_state_dependency/contract_close_blocked_by_active_cohort
        """
        contract = create_contract(budget_cents=200000, client_name="Block2")
        ctx = setup_locked_cohort_with_confirmed(
            num_confirmed=1, category="TECHNICAL", delivery_mode="VIRTUAL",
            contract_id=contract["id"], per_seat_cents=10000, min_seats=1, seat_capacity=3,
        )
        resp = api.close_contract(contract["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_HAS_OPEN_COHORTS.value)

    def test_close_from_closed_terminal_lockdown(self, api):
        """PRD §2.9: "for any state-transition endpoint, the target resource must currently be in
        a state from which the requested transition is defined; otherwise the request is rejected
        with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/contract_close_from_closed_terminal_lockdown
        """
        contract = create_contract(budget_cents=1000, client_name="Term Co")
        validate_success(api.close_contract(contract["id"], FINANCE))
        resp = api.close_contract(contract["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
