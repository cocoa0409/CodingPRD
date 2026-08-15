"""Repair work orders: quoted/actual pricing variants, evaluation order,
revision loop, part reserve/release conservation, fiscal gates, OCC, RBAC."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    assert_work_order,
    api_client,
    TEST_USERS,
    make_supervisor_headers,
    make_operator_headers,
    create_program,
    create_zone,
    create_hydrant,
    create_part,
    get_part,
    create_draft_work_order,
    create_submitted_work_order,
    create_approved_work_order,
    add_part_line,
    get_work_order,
    approve_work_order,
    setup_program_zone_hydrant,
)

ADMIN = TEST_USERS["admin_headers"]
OP1 = TEST_USERS["operator_headers"]
SUP1 = TEST_USERS["supervisor_headers"]
LIAISON = TEST_USERS["liaison_headers"]


class TestQuotedVsActual:
    def test_work_order_quoted_variant_at_approve(self, api):
        """PRD §3.7: "At approval, each part line's `unit_price_cents` is
        snapshot from the part's current `unit_price_cents` and stored on the
        line, the four quoted totals — `quoted_subtotal_cents`,
        `quoted_discount_cents`, `quoted_fee_cents`, `quoted_total_cents` — are
        written, every line's `status` moves to `RESERVED`, each affected
        part's `available_qty` is recomputed, the order's `version` increments,
        and `approved_by_user_id` is recorded."

        Design: Difficulty/dual_variant_calc/work_order_quoted_vs_actual_price_drift
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        part = create_part(sku="GASKET-6", name="6in gasket",
                           unit_price_cents=6500, on_hand_qty=100)
        wo = create_approved_work_order(hydrant["id"], part=part, qty=4)
        # subtotal 26000; 5% discount 1300; discounted 24700 < 25000 -> fee 1500
        assert wo["quoted_subtotal_cents"] == 26000
        assert wo["quoted_discount_cents"] == 1300
        assert wo["quoted_fee_cents"] == 1500
        assert wo["quoted_total_cents"] == 26200, (
            f"quoted total must be 26200 at the approve-time price, "
            f"got {wo['quoted_total_cents']}"
        )

        # Drift the price, then complete.
        validate_success(api.restock_part(
            part["id"], {"add_qty": 10, "new_unit_price_cents": 7000}, ADMIN
        ))
        completed = validate_success(api.complete_work_order(wo["id"], OP1))
        assert completed["quoted_total_cents"] == 26200, (
            "quoted totals are pinned at approval and must not drift"
        )

    def test_work_order_actual_variant_uses_current_price(self, api):
        """PRD §3.7: "The order's `actual_total_cents` is computed by the same
        pricing pipeline as the quoted variant, but with each line's unit price
        taken as the *current* `Part.unit_price_cents` at completion time — so
        a restock that changed a price between approve and complete yields a
        different actual total even when the quantities are identical."
        PRD §3.7: "Each part line's `status` moves to `CONSUMED`, each
        referenced part's `on_hand_qty` is decremented by the line's `qty`, and
        each affected part's `available_qty` is recomputed."

        Design: Difficulty/dual_variant_calc/work_order_quoted_vs_actual_price_drift
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        part = create_part(sku="GASKET-6", name="6in gasket",
                           unit_price_cents=6500, on_hand_qty=100)
        wo = create_approved_work_order(hydrant["id"], part=part, qty=4)
        validate_success(api.restock_part(
            part["id"], {"add_qty": 10, "new_unit_price_cents": 7000}, ADMIN
        ))

        completed = validate_success(api.complete_work_order(wo["id"], OP1))
        # actual at price 7000: subtotal 28000; 5% discount 1400; discounted
        # 26600 >= 25000 -> fee 0
        assert completed["actual_total_cents"] == 26600, (
            f"actual total must be 26600 at the completion-time price, "
            f"got {completed['actual_total_cents']}"
        )
        assert completed["status"] == "COMPLETED"

        part_after = get_part(part["id"])
        assert part_after["on_hand_qty"] == 106, (
            f"on_hand 100 - 4 consumed + 10 restocked = 106, got {part_after['on_hand_qty']}"
        )
        assert part_after["available_qty"] == 106, (
            f"no RESERVED lines remain, so available must equal on_hand, "
            f"got {part_after['available_qty']}"
        )


class TestEvaluationOrder:
    def test_work_order_total_evaluation_order_tiers(self, api):
        """PRD §3.7: "The discount percentage is tiered by subtotal: 10 percent
        when the subtotal is at least 100000 cents, otherwise 5 percent when
        the subtotal is at least 20000 cents, otherwise 0 — and the boundaries
        are inclusive, so a subtotal of exactly 20000 cents earns 5 percent and
        exactly 100000 cents earns 10 percent."
        PRD §3.7: "The handling fee is 1500 cents when the discounted amount is
        strictly less than 25000 cents and zero otherwise — a discounted amount
        of exactly 25000 cents carries no fee."

        Design: Difficulty/combinatorial_formula/work_order_total_evaluation_order
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        part = create_part(sku="VALVE-6", name="6in gate valve",
                           unit_price_cents=13158, on_hand_qty=10)
        wo = create_submitted_work_order(hydrant["id"], part=part, qty=2)
        approved = approve_work_order(wo["id"], approver_headers=SUP1)
        # subtotal 26316 -> 5% discount 1316 -> discounted exactly 25000
        assert approved["quoted_subtotal_cents"] == 26316
        assert approved["quoted_discount_cents"] == 1316

    def test_work_order_total_evaluation_order_fee_boundary(self, api):
        """PRD §3.7: "The handling fee is 1500 cents when the discounted amount
        is strictly less than 25000 cents and zero otherwise — a discounted
        amount of exactly 25000 cents carries no fee. The quoted total is the
        discounted amount plus the fee."

        Design: Difficulty/combinatorial_formula/work_order_total_evaluation_order
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        part = create_part(sku="VALVE-6", name="6in gate valve",
                           unit_price_cents=13158, on_hand_qty=10)
        wo = create_submitted_work_order(hydrant["id"], part=part, qty=2)
        approved = approve_work_order(wo["id"], approver_headers=SUP1)
        # discounted == 25000 is NOT strictly < 25000 -> no fee
        assert approved["quoted_fee_cents"] == 0, (
            f"discounted exactly 25000 carries no fee, got {approved['quoted_fee_cents']}"
        )
        assert approved["quoted_total_cents"] == 25000


class TestRejectRevisionLoop:
    def test_work_order_reject_revision_loop_reaches_approved(self, api):
        """PRD §3.7: "Rejection is the revision loop: a `UtilitySupervisor`
        rejects a `SUBMITTED` order (else `ERR_WORK_ORDER_NOT_SUBMITTED`) with
        a `rejection_reason` that is stored into `last_rejection_reason`,
        moving the order back to `DRAFT` where its lines become editable
        again."

        Design: Difficulty/non_linear_state_machine/work_order_reject_revision_loop
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        part = create_part(sku="GASKET-6", name="6in gasket",
                           unit_price_cents=6500, on_hand_qty=100)
        wo = create_submitted_work_order(hydrant["id"], part=part, qty=2)

        rejected = validate_success(api.reject_work_order(
            wo["id"], {"rejection_reason": "scope incomplete"}, SUP1
        ))
        assert rejected["status"] == "DRAFT"
        assert rejected["last_rejection_reason"] == "scope incomplete"

        # Lines editable again: append, resubmit, approve.
        add_part_line(wo["id"], part["id"], 1)
        validate_success(api.submit_work_order(wo["id"], OP1))
        approved = approve_work_order(wo["id"], approver_headers=SUP1)
        assert approved["status"] == "APPROVED", (
            f"the revised order must reach APPROVED, got {approved['status']}"
        )

    def test_work_order_reject_revision_loop_lines_reserved(self, api):
        """PRD §3.7: "At approval, each part line's `unit_price_cents` is
        snapshot from the part's current `unit_price_cents` and stored on the
        line, the four quoted totals — `quoted_subtotal_cents`,
        `quoted_discount_cents`, `quoted_fee_cents`, `quoted_total_cents` — are
        written, every line's `status` moves to `RESERVED`, each affected
        part's `available_qty` is recomputed, the order's `version` increments,
        and `approved_by_user_id` is recorded."

        Design: Difficulty/non_linear_state_machine/work_order_reject_revision_loop
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        part = create_part(sku="GASKET-6", name="6in gasket",
                           unit_price_cents=6500, on_hand_qty=100)
        wo = create_submitted_work_order(hydrant["id"], part=part, qty=2)
        validate_success(api.reject_work_order(
            wo["id"], {"rejection_reason": "scope incomplete"}, SUP1
        ))
        add_part_line(wo["id"], part["id"], 1)
        validate_success(api.submit_work_order(wo["id"], OP1))
        approved = approve_work_order(wo["id"], approver_headers=SUP1)

        assert approved["last_rejection_reason"] == "scope incomplete", (
            "the stored rejection reason survives the revision loop"
        )
        assert len(approved["part_lines"]) == 2, (
            f"the revised order must carry 2 part lines, got {len(approved['part_lines'])}"
        )
        for line in approved["part_lines"]:
            assert line["status"] == "RESERVED", (
                f"every line must be RESERVED after approval, got {line['status']}"
            )


class TestReserveReleaseConservation:
    def test_parts_reserve_release_conserves_available_after_approve(self, api):
        """PRD §3.7: "A part's `available_qty` is derived continuously as its
        `on_hand_qty` minus the sum of `qty` over every part line in `RESERVED`
        status across all work orders that reference the part."

        Design: Difficulty/compensating_invariant/parts_reserve_release_conserves_available
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        part = create_part(sku="GASKET-6", name="6in gasket",
                           unit_price_cents=6500, on_hand_qty=100)
        wo = create_submitted_work_order(hydrant["id"], part=part, qty=30)
        approve_work_order(wo["id"], approver_headers=SUP1)

        part_after = get_part(part["id"])
        assert part_after["available_qty"] == 70, (
            f"available must be 100 - 30 RESERVED = 70, got {part_after['available_qty']}"
        )
        assert part_after["on_hand_qty"] == 100, (
            "approval reserves but does not consume physical stock"
        )

    def test_parts_reserve_release_conserves_available_after_cancel(self, api):
        """PRD §3.7: "The reservation invariant is that an approve followed by
        a cancel-from-approved leaves `available_qty` identical to its value
        before the pair — the reserve and release exactly offset."
        PRD §3.7: "From `APPROVED` it is a compensation: each part line's
        `status` moves to `RELEASED` and each affected part's `available_qty`
        is recomputed, while `on_hand_qty` is left untouched — only completion
        consumes physical stock."

        Design: Difficulty/compensating_invariant/parts_reserve_release_conserves_available
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        part = create_part(sku="GASKET-6", name="6in gasket",
                           unit_price_cents=6500, on_hand_qty=100)
        wo = create_approved_work_order(hydrant["id"], part=part, qty=30)
        assert get_part(part["id"])["available_qty"] == 70

        cancelled = validate_success(api.cancel_work_order(wo["id"], OP1))
        assert cancelled["status"] == "CANCELLED"
        for line in cancelled["part_lines"]:
            assert line["status"] == "RELEASED", (
                f"cancel-from-approved must release lines, got {line['status']}"
            )

        part_after = get_part(part["id"])
        assert part_after["available_qty"] == 100 == part_after["on_hand_qty"], (
            f"reserve/release must conserve availability at 100, "
            f"got available {part_after['available_qty']}"
        )


class TestStateBeforeFiscal:
    def test_approve_state_before_fiscal_error(self, api):
        """PRD §2.11: "When multiple validations apply to a single request,
        they are evaluated in a fixed priority order so that the surfaced error
        is deterministic."
        PRD §2.11: "8. State preconditions — the entity-specific
        `ERR_*_NOT_*` family at HTTP 409." and "13. Fiscal checks on work-order
        approval — part availability first (`ERR_INSUFFICIENT_PART_QUANTITY`),
        then budget cap (`ERR_WORK_ORDER_BUDGET_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/approve_state_before_fiscal
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        part = create_part(sku="VALVE-6", name="6in gate valve",
                           unit_price_cents=13158, on_hand_qty=10)
        # DRAFT order whose quoted total (25000) would exceed cap 10000.
        wo = create_draft_work_order(hydrant["id"], description="Valve replacement",
                                     budget_cap_cents=10000)
        add_part_line(wo["id"], part["id"], 2)
        wo_live = get_work_order(wo["id"])

        resp = api.approve_work_order(
            wo["id"], {"expected_work_order_version": wo_live["version"]}, SUP1
        )
        validate_error(resp, ApiErrorId.ERR_WORK_ORDER_NOT_SUBMITTED, 409)

    def test_approve_state_before_fiscal_no_mutation(self, api):
        """PRD §3.7: "Submitting the order moves it from `DRAFT` to
        `SUBMITTED`; a submit on a non-draft order is rejected with
        `ERR_WORK_ORDER_NOT_DRAFT`."
        PRD §3.7: "The order must be `SUBMITTED` (else
        `ERR_WORK_ORDER_NOT_SUBMITTED`)."

        Design: Difficulty/priority_pair_validation_conflict/approve_state_before_fiscal
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        part = create_part(sku="VALVE-6", name="6in gate valve",
                           unit_price_cents=13158, on_hand_qty=10)
        wo = create_draft_work_order(hydrant["id"], description="Valve replacement",
                                     budget_cap_cents=10000)
        add_part_line(wo["id"], part["id"], 2)
        wo_live = get_work_order(wo["id"])

        resp = api.approve_work_order(
            wo["id"], {"expected_work_order_version": wo_live["version"]}, SUP1
        )
        validate_error(resp, ApiErrorId.ERR_WORK_ORDER_NOT_SUBMITTED, 409)

        after = get_work_order(wo["id"])
        assert after["status"] == "DRAFT", "rejected approve must leave the order DRAFT"
        for line in after["part_lines"]:
            assert line["status"] == "PENDING", (
                f"no line may leave PENDING on a failed approve, got {line['status']}"
            )


class TestFiscalGates:
    def test_approve_budget_exceeded_rejected(self, api):
        """PRD §3.7: "Then the fiscal checks, in order: for every part line,
        the referenced part's `available_qty` must be at least the line's `qty`
        (else `ERR_INSUFFICIENT_PART_QUANTITY`, HTTP 422); and if
        `budget_cap_cents` is non-null, the computed `quoted_total_cents` must
        be at most the cap (else `ERR_WORK_ORDER_BUDGET_EXCEEDED`, HTTP 422)."

        Design: Corner/validations/approve_budget_exceeded_rejected
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        part = create_part(sku="VALVE-6", name="6in gate valve",
                           unit_price_cents=13158, on_hand_qty=10)
        wo = create_submitted_work_order(hydrant["id"], part=part, qty=2,
                                         budget_cap_cents=20000)
        wo_live = get_work_order(wo["id"])

        resp = api.approve_work_order(
            wo["id"], {"expected_work_order_version": wo_live["version"]}, SUP1
        )
        validate_error(resp, ApiErrorId.ERR_WORK_ORDER_BUDGET_EXCEEDED, 422)

        part_after = get_part(part["id"])
        assert part_after["available_qty"] == 10, (
            "a rejected approve must not reserve any stock"
        )
        assert get_work_order(wo["id"])["status"] == "SUBMITTED"

    def test_approve_insufficient_parts_rejected(self, api):
        """PRD §3.7: "Then the fiscal checks, in order: for every part line,
        the referenced part's `available_qty` must be at least the line's `qty`
        (else `ERR_INSUFFICIENT_PART_QUANTITY`, HTTP 422); and if
        `budget_cap_cents` is non-null, the computed `quoted_total_cents` must
        be at most the cap (else `ERR_WORK_ORDER_BUDGET_EXCEEDED`, HTTP 422).
        Part availability is checked before the budget cap."

        Design: Corner/validations/approve_insufficient_parts_rejected
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        part = create_part(sku="GASKET-6", name="6in gasket",
                           unit_price_cents=6500, on_hand_qty=5)
        wo = create_submitted_work_order(hydrant["id"], part=part, qty=10)
        wo_live = get_work_order(wo["id"])

        resp = api.approve_work_order(
            wo["id"], {"expected_work_order_version": wo_live["version"]}, SUP1
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PART_QUANTITY, 422)
        assert get_work_order(wo["id"])["status"] == "SUBMITTED", (
            "rejected approve must leave the order SUBMITTED"
        )


class TestApproveSegregationOfDuties:
    def test_sod_approve_own_work_order_rejected(self, api):
        """PRD §3.7: "The supervisor's `X-User-ID` must differ from the order's
        `created_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/sod_approve_own_work_order_rejected
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        part = create_part(sku="GASKET-6", name="6in gasket",
                           unit_price_cents=6500, on_hand_qty=100)
        wo = create_submitted_work_order(hydrant["id"], part=part, qty=1)
        wo_live = get_work_order(wo["id"])

        # Supervisor role, but the same X-User-ID as the creator op_1.
        resp = api.approve_work_order(
            wo["id"], {"expected_work_order_version": wo_live["version"]},
            make_supervisor_headers("op_1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        after = get_work_order(wo["id"])
        assert after["status"] == "SUBMITTED"
        for line in after["part_lines"]:
            assert line["status"] == "PENDING"


class TestApproveOptimisticConcurrency:
    def test_occ_stale_version_on_work_order_approve(self, api):
        """PRD §2.6: "Approving a work order requires the request to carry
        `expected_work_order_version`, matching the work order's current
        `version`. If another writer has advanced the work order's version
        since the approver last read it — for example by adding a part line
        after the approver reviewed the order — the approval is rejected with
        `ERR_STALE_VERSION` (HTTP 412), so an approval never rests on a stale
        view of the line set."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_work_order_approve
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        part = create_part(sku="GASKET-6", name="6in gasket",
                           unit_price_cents=6500, on_hand_qty=100)
        wo = create_submitted_work_order(hydrant["id"], part=part, qty=1)
        observed = get_work_order(wo["id"])["version"]
        approve_work_order(wo["id"], approver_headers=SUP1)  # advances the version

        # A second approve carrying the previously observed version is stale.
        resp = api.approve_work_order(
            wo["id"], {"expected_work_order_version": observed},
            make_supervisor_headers("sup_2"),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


class TestRbacDenials:
    def test_fire_dept_liaison_cannot_approve_work_order(self, api):
        """PRD §2.1: "`FireDeptLiaison` — fire department contact; acknowledges
        out-of-service notifications."
        PRD §2.1: "Once headers are present, the role value must appear in the
        endpoint's authorized role list; a role outside the list is rejected
        with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: POST /work-orders/{id}/approve is authorized for
        UtilitySupervisor only.

        Design: Corner/rbac/fire_dept_liaison_cannot_approve_work_order
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        part = create_part(sku="GASKET-6", name="6in gasket",
                           unit_price_cents=6500, on_hand_qty=100)
        wo = create_submitted_work_order(hydrant["id"], part=part, qty=1)
        observed = get_work_order(wo["id"])["version"]

        resp = api.approve_work_order(
            wo["id"], {"expected_work_order_version": observed}, LIAISON
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
        assert get_work_order(wo["id"])["status"] == "SUBMITTED", (
            "a role-denied approve must not mutate the order"
        )

    def test_field_operator_cannot_create_part(self, api):
        """PRD §2.1: "`ProgramAdmin` — utility program administrator; owns
        configuration, programs, inventory, the parts catalog, ISO
        documentation, and the operational sweep."
        PRD §2.1: "a role outside the list is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: POST /parts is authorized for ProgramAdmin only.

        Design: Corner/rbac/field_operator_cannot_create_part
        """
        resp = api.create_part(
            {"sku": "GASKET-6", "name": "6in gasket",
             "unit_price_cents": 6500, "on_hand_qty": 100},
            OP1,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
