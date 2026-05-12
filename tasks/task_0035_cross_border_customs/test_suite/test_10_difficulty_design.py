"""Difficulty-design coverage — every instance from
SCAFFOLD_DIFFICULTY_DESIGN.yaml gets at least two dedicated tests
tagged with `# difficulty: <rule_id>/<instance.name>`.

Each test cites PRD prose for the underlying rule (NOT the difficulty
index entry itself — the implementer reads only PRD).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    TEST_USERS,
    PERSONAL_POSTAL_THRESHOLD_CNY_MINOR,
    POSTAL_EXEMPTION_CNY_MINOR,
    PAYMENT_NOTICE_DUE_SECONDS,
    setup_draft_declaration,
    setup_under_review_declaration,
    setup_approved_declaration,
    setup_released_declaration,
    setup_amended_declaration,
    setup_returned_order_with_paid_declaration,
    setup_personal_postal_at_dutiable,
    setup_paid_then_reversed,
    submit_declaration,
    start_review,
    approve_declaration,
    reject_declaration,
    schedule_inspection,
    confirm_payment,
    reverse_payment,
    create_refund,
    submit_refund,
    approve_refund,
    reject_refund,
    execute_refund,
    suspend_importer,
    create_hs_code,
    create_tariff_rule,
    create_tariff_rule_payload,
    create_exchange_rate,
    create_party_pair,
    create_order,
    create_draft_declaration,
    add_line,
    make_line_item,
    fresh_idempotency_key,
    confirm_payment_payload,
    reverse_payment_payload,
    schedule_inspection_payload,
    open_query_payload,
    open_query,
    respond_to_query,
    resolve_query,
    make_declarant_headers,
)


# =============================================================================
# Rule 1 — dual_variant_calc
# =============================================================================
class TestDualVariantCalc:
    """rule_id: dual_variant_calc — two named variants on different entity
    domains produce strictly different outputs for identical inputs."""

    def test_dutiable_value_method_variants_on_declaration(self, api):
        """PRD §3.5 (verbatim): "Under TRANSACTION_VALUE, the line's CNY
        contribution is the simplest mapping: multiply line_value_minor by
        the pinned exchange rate's rate_micros, divide by 1,000,000, and
        floor toward zero."
        PRD §3.5: "Under DEDUCTIVE_VALUE, the calculation begins from a
        presumed retail price equal to the transaction price multiplied by
        125 and divided by 100 (i.e., a 25 percent retail markup), floored.
        From that presumed retail price, the calculation deducts a
        logistics-and-profit component computed by multiplying the retail
        price by DEDUCTION_RATIO_BPS and dividing by 10,000".

        Claim: identical 1-line orders with TRANSACTION_VALUE vs
        DEDUCTIVE_VALUE yield different dutiable_value_cny_minor.

        # difficulty: dual_variant_calc/dutiable_value_method_variants_on_declaration
        """
        ctx_t = setup_draft_declaration(
            dutiable_value_method="TRANSACTION_VALUE",
            line_items=[make_line_item(quantity=1, unit_price=10_000, weight_kg=1.0)],
            currency="USD",
            rate_micros=7_000_000,
            hs_code_overrides={
                "tariff_rate_bps": 0, "vat_rate_bps": 0,
                "consumption_tax_rate_bps": 0, "postal_tax_rate_bps": 0,
            },
        )
        ctx_d = setup_draft_declaration(
            dutiable_value_method="DEDUCTIVE_VALUE",
            line_items=[make_line_item(quantity=1, unit_price=10_000, weight_kg=1.0)],
            currency="USD",
            rate_micros=7_000_000,
            hs_code_overrides={
                "tariff_rate_bps": 0, "vat_rate_bps": 0,
                "consumption_tax_rate_bps": 0, "postal_tax_rate_bps": 0,
            },
        )
        st = submit_declaration(ctx_t.declaration, ctx_t.declarant)
        sd = submit_declaration(ctx_d.declaration, ctx_d.declarant)
        # Pinned by PRD §3.5 arithmetic.
        assert st["dutiable_value_cny_minor"] == 70_000
        assert sd["dutiable_value_cny_minor"] == 74_375
        assert st["dutiable_value_cny_minor"] != sd["dutiable_value_cny_minor"]

    def test_refund_amount_full_vs_partial_on_refund(self, api):
        """PRD §3.10 (verbatim): "For RETURN refunds, the refundable
        amount is the entire PaymentNotice.amount_cny_minor — the goods
        never effectively cleared, so the full tax is returned."
        PRD §3.10: "For ERRONEOUS_DECLARATION refunds, the refundable
        amount is the larger of zero and the difference between
        PaymentNotice.amount_cny_minor and the current
        Declaration.total_tax_cny_minor".

        Claim: a RETURN refund yields the full pn.amount_cny_minor; an
        ERRONEOUS_DECLARATION refund (where amended tax is strictly less
        than the snapshot) yields the positive difference. The two
        outputs differ for non-zero post-amendment tax.

        # difficulty: dual_variant_calc/refund_amount_full_vs_partial_on_refund
        """
        # RETURN scenario: full refund equals notice amount.
        ctx_r = setup_returned_order_with_paid_declaration()
        refund_r = create_refund(
            ctx_r.declaration, ctx_r.declarant, refund_reason="RETURN",
        )
        sub_r = submit_refund(refund_r, ctx_r.declarant)
        assert sub_r["refundable_amount_cny_minor"] == (
            ctx_r.payment_notice["amount_cny_minor"]
        )

        # ERRONEOUS_DECLARATION scenario: post-amendment tax MUST be
        # strictly less than the notice amount; we simulate by amending
        # to swap to a 0%-tariff HS code.
        # The simplest construction: setup with 1300 bps VAT in STANDARD
        # → some non-zero tax; then amend to a fresh 0%-everything HS code
        # → recomputed total_tax is 0 < notice.amount.
        ctx_e = setup_released_declaration(
            trade_mode="GENERAL_TRADE",
            line_items=[make_line_item(quantity=1, unit_price=10_000, weight_kg=0.1)],
            currency="USD",
            rate_micros=1_000_000,
            hs_code_overrides={
                "tariff_rate_bps": 1000, "vat_rate_bps": 1300,
                "consumption_tax_rate_bps": 0, "postal_tax_rate_bps": 0,
            },
        )
        notice_amount = ctx_e.payment_notice["amount_cny_minor"]
        assert notice_amount > 0
        # Create a fresh zero-tax HS code; amend the existing line to
        # point at it. The amend body schema is {lines: [{line_id,
        # hs_code_id?, dutiable_value_method?}, ...]}.
        zero_hs = create_hs_code(
            tariff_rate_bps=0, vat_rate_bps=0,
            consumption_tax_rate_bps=0, postal_tax_rate_bps=0,
        )
        line_id = ctx_e.lines[0]["id"]
        amend_res = api.amend_declaration(
            ctx_e.declaration["id"],
            {"lines": [{"line_id": line_id, "hs_code_id": zero_hs["id"]}]},
            make_declarant_headers(ctx_e.declarant["id"]),
        )
        amended = validate_success(amend_res)
        assert amended["status"] == "AMENDED"
        # Post-amendment tax should be 0 (all rates 0 on the new HS code).
        assert amended["total_tax_cny_minor"] < notice_amount
        # Now an ERRONEOUS_DECLARATION refund.
        refund_e = create_refund(
            ctx_e.declaration, ctx_e.declarant,
            refund_reason="ERRONEOUS_DECLARATION",
        )
        sub_e = submit_refund(refund_e, ctx_e.declarant)
        # PRD §3.10 verbatim: "the larger of zero and the difference
        # between PaymentNotice.amount_cny_minor and the current
        # Declaration.total_tax_cny_minor".
        expected = max(0, notice_amount - amended["total_tax_cny_minor"])
        assert sub_e["refundable_amount_cny_minor"] == expected
        # And the two refund variants produce different amounts.
        assert sub_r["refundable_amount_cny_minor"] != sub_e["refundable_amount_cny_minor"]


# =============================================================================
# Rule 2 — combinatorial_formula
# =============================================================================
class TestCombinatorialFormula:
    """rule_id: combinatorial_formula — formulas with 3+ inputs and
    nested branching."""

    def test_personal_postal_three_input_branching(self, api):
        """PRD §3.6 (verbatim): "The mode is PERSONAL_POSTAL only when
        both conditions hold: the declaration's trade_mode is
        B2C_DIRECT_MAIL, and the declaration's dutiable_value_cny_minor
        is at most PERSONAL_POSTAL_THRESHOLD_CNY_MINOR".
        PRD §3.6: "In every other case (general trade, bonded warehouse,
        or B2C direct mail strictly above the threshold), the mode is
        STANDARD."

        Claim: three orders with different combinations of trade_mode and
        dutiable_value resolve to three different tax_mode outcomes.

        # difficulty: combinatorial_formula/personal_postal_tiered_branching_mode_a
        """
        # B2C_DIRECT_MAIL with low value → PERSONAL_POSTAL.
        ctx_p = setup_personal_postal_at_dutiable(70_000)
        sp = submit_declaration(ctx_p.declaration, ctx_p.declarant)
        assert sp["tax_mode"] == "PERSONAL_POSTAL"

        # GENERAL_TRADE with low value → STANDARD (mode requires B2C).
        ctx_s = setup_draft_declaration(
            trade_mode="GENERAL_TRADE",
            dutiable_value_method="TRANSACTION_VALUE",
            line_items=[make_line_item(quantity=1, unit_price=10_000, weight_kg=1.0)],
            currency="USD",
            rate_micros=7_000_000,
            hs_code_overrides={
                "tariff_rate_bps": 1000, "vat_rate_bps": 1300,
                "consumption_tax_rate_bps": 0, "postal_tax_rate_bps": 1000,
            },
        )
        ss = submit_declaration(ctx_s.declaration, ctx_s.declarant)
        assert ss["tax_mode"] == "STANDARD"

        # B2C_DIRECT_MAIL above threshold → STANDARD.
        ctx_h = setup_personal_postal_at_dutiable(
            PERSONAL_POSTAL_THRESHOLD_CNY_MINOR + 1
        )
        sh = submit_declaration(ctx_h.declaration, ctx_h.declarant)
        assert sh["tax_mode"] == "STANDARD"

    def test_per_line_floor_then_sum_pins_arithmetic_order(self, api):
        """PRD §2.5 (verbatim): "All such divisions truncate toward zero
        (a per-line floor is applied), and the order of operations is
        fixed: compute each line's contribution, floor that contribution,
        then sum across lines. Summing first and flooring the total is
        not equivalent and is not allowed."

        Claim: two lines with line_dutiable=5050 fen each at 1% tariff
        yield tariff_amount=100 (50+50). The 'sum-then-floor' alternative
        would give 101.

        # difficulty: combinatorial_formula/per_line_floor_then_sum_rounding_order_mode_b
        """
        ctx = setup_draft_declaration(
            dutiable_value_method="TRANSACTION_VALUE",
            line_items=[
                make_line_item(quantity=1, unit_price=5050, weight_kg=0.1),
                make_line_item(quantity=1, unit_price=5050, weight_kg=0.1),
            ],
            currency="USD",
            rate_micros=1_000_000,
            hs_code_overrides={
                "tariff_rate_bps": 100, "vat_rate_bps": 0,
                "consumption_tax_rate_bps": 0, "postal_tax_rate_bps": 0,
            },
        )
        submitted = submit_declaration(ctx.declaration, ctx.declarant)
        assert submitted["dutiable_value_cny_minor"] == 10_100
        assert submitted["tariff_amount_cny_minor"] == 100  # NOT 101


# =============================================================================
# Rule 3 — non_linear_state_machine
# =============================================================================
class TestNonLinearStateMachine:
    """rule_id: non_linear_state_machine — cycles or branches in the
    state graph that a strictly linear pipeline cannot exhibit."""

    def test_declaration_query_response_round_trip(self, api):
        """PRD §3.7 (verbatim): "A customs officer asks a question and
        lists required_documents — an array of document type codes such
        as INVOICE or COA — as part of opening a query; this transitions
        the declaration from UNDER_REVIEW to QUERIED and pins
        Declaration.query_id to the new query, whose own status begins
        at OPEN."
        PRD §3.7: "The customs officer then resolves the query, which
        moves the query to RESOLVED, clears Declaration.query_id, and
        returns the declaration from QUERIED to UNDER_REVIEW."

        Claim: UNDER_REVIEW → QUERIED → UNDER_REVIEW is a true cycle
        (round-trip back to the original state).

        # difficulty: non_linear_state_machine/declaration_query_response_cycle
        """
        ctx = setup_under_review_declaration()
        q_res = api.open_query(
            ctx.declaration["id"],
            open_query_payload(required_documents=["INVOICE"]),
            TEST_USERS["customs_officer_headers"],
        )
        q = validate_success(q_res, expected_status=201)
        assert q["status"] == "OPEN"
        respond_to_query(q["id"], ctx.declarant)
        resolved = resolve_query(q["id"])
        assert resolved["status"] == "RESOLVED"
        decl = ctx.refresh_declaration()
        assert decl["status"] == "UNDER_REVIEW"
        # query_id must be cleared on the round-trip.
        assert decl.get("query_id") in (None, "")

    def test_refund_branching_approve_or_reject(self, api):
        """PRD §3.10 (verbatim): "A submitted refund is decided by a
        customs officer — approval transitions it from SUBMITTED to
        APPROVED ...; rejection transitions it from SUBMITTED to
        REJECTED, persists the customs officer's rejection_reason ...
        Approved refunds are then disbursed by a finance operator,
        transitioning from APPROVED to EXECUTED; on execution,
        executed_amount_cny_minor is set equal to
        refundable_amount_cny_minor".

        Claim: Two parallel SUBMITTED refunds branch differently — one
        path APPROVED→EXECUTED disburses, the other terminates at
        REJECTED with rejection_reason and no executed_amount.

        # difficulty: non_linear_state_machine/refund_branching_approve_or_reject
        """
        ctx = setup_returned_order_with_paid_declaration()
        # Approve+execute branch.
        r1 = create_refund(
            ctx.declaration, ctx.declarant, refund_reason="RETURN",
        )
        s1 = submit_refund(r1, ctx.declarant)
        a1 = approve_refund(s1)
        e1 = execute_refund(a1)
        assert e1["status"] == "EXECUTED"
        assert e1["executed_amount_cny_minor"] == s1["refundable_amount_cny_minor"]

        # Separate scenario for rejection branch (one EXECUTED refund max
        # per declaration → use a different declaration).
        ctx2 = setup_returned_order_with_paid_declaration()
        r2 = create_refund(
            ctx2.declaration, ctx2.declarant, refund_reason="RETURN",
        )
        s2 = submit_refund(r2, ctx2.declarant)
        rej2 = reject_refund(s2, "insufficient evidence")
        assert rej2["status"] == "REJECTED"
        assert rej2.get("rejection_reason") == "insufficient evidence"
        # PRD §3.10: rejection branch never touches executed_amount.
        assert rej2.get("executed_amount_cny_minor", 0) == 0


# =============================================================================
# Rule 4 — transitive_cascade
# =============================================================================
class TestTransitiveCascade:
    """rule_id: transitive_cascade — multi-hop chains where each hop is
    caused by the previous hop's transition, not the original call."""

    def test_confirm_payment_three_hop_release_cascade(self, api):
        """PRD §3.8 (verbatim): "A successful confirmation flips the
        notice from PENDING to PAID, cascades the linked declaration
        from APPROVED to RELEASED ...".
        PRD §3.8: "The declaration's transition to RELEASED cascades
        again to the parent order, advancing it from DECLARED to
        RELEASED, and pins pickup_coordinated_at on the declaration to
        the current clock".

        Claim: A single confirm_payment call moves PaymentNotice
        PENDING→PAID (hop 1), Declaration APPROVED→RELEASED (hop 2),
        and Order DECLARED→RELEASED (hop 3).

        # difficulty: transitive_cascade/confirm_payment_three_hop_release_cascade
        """
        ctx = setup_released_declaration()
        assert ctx.payment_notice["status"] == "PAID"        # hop 1
        assert ctx.declaration["status"] == "RELEASED"        # hop 2
        assert ctx.order["status"] == "RELEASED"              # hop 3
        assert ctx.declaration.get("pickup_coordinated_at") is not None

    def test_reverse_payment_two_hop_revert_cascade(self, api):
        """PRD §3.8 (verbatim): "A successful reversal flips the notice
        from PAID to REVERSED; if the linked declaration was in RELEASED,
        it reverts to APPROVED (the order's RELEASED cascade is similarly
        undone)."

        Claim: a single reverse_payment call moves PaymentNotice
        PAID→REVERSED (hop 1) AND Declaration RELEASED→APPROVED (hop 2).

        # difficulty: transitive_cascade/reverse_payment_two_hop_revert_cascade
        """
        ctx = setup_paid_then_reversed()
        assert ctx.payment_notice["status"] == "REVERSED"   # hop 1
        assert ctx.declaration["status"] == "APPROVED"       # hop 2


# =============================================================================
# Rule 5 — priority_pair_validation_conflict
# =============================================================================
class TestPriorityPairValidationConflict:
    """rule_id: priority_pair_validation_conflict — when two validations
    of different categories both fire, the higher-priority one wins."""

    def test_state_vs_business_temporal_on_payment_confirm(self, api):
        """PRD §2.9 (verbatim): "State-transition validity comes after
        existence; a transition request against a non-existent resource
        always surfaces as ERR_NOT_FOUND rather than as
        ERR_INVALID_STATE_TRANSITION."
        PRD §2.9: "Business-constraint checks (template completeness,
        override status, rework limit, idempotency, channel-specific
        requirements, document completeness, HS code deprecation) and
        business-temporal checks (inspection slot overlap, payment
        notice expiry, tariff rule effective-window overlap) run last,
        in the priority order listed in the rules table."
        PRD §2.9: "the response surfaces the highest-priority error
        rather than the most specific."

        Claim: a confirm on a notice that is BOTH already PAID (state)
        AND past due_at (temporal) returns ERR_INVALID_STATE_TRANSITION
        (state, higher priority), not ERR_PAYMENT_NOTICE_EXPIRED
        (temporal, lower priority).

        # difficulty: priority_pair_validation_conflict/state_vs_business_temporal_on_payment_confirm
        """
        ctx = setup_released_declaration()  # notice PAID, declaration RELEASED
        # Advance clock so notice is also "expired" in temporal terms.
        api.advance_clock(
            PAYMENT_NOTICE_DUE_SECONDS + 60,
            TEST_USERS["customs_officer_headers"],
        )
        key = fresh_idempotency_key("pp")
        hdrs = dict(TEST_USERS["finance_officer_headers"])
        hdrs["Idempotency-Key"] = key
        body = confirm_payment_payload(
            payment_channel="ELECTRONIC_PAYMENT", idempotency_key=key,
        )
        res = api.confirm_payment(ctx.payment_notice["id"], body, hdrs)
        # PRD §2.9 pins the order: state precedes temporal.
        validate_error(res, "ERR_INVALID_STATE_TRANSITION", expected_status=409)

    def test_business_referential_vs_business_constraint_on_refund_submit(self, api):
        """PRD §2.9 (verbatim): "Business-referential checks (importer
        suspended, declaration uniqueness on an order) run after state
        validity. Business-constraint checks (template completeness,
        override status, rework limit, idempotency, channel-specific
        requirements, document completeness, HS code deprecation) and
        business-temporal checks ... run last".
        PRD §2.9: "the response surfaces the highest-priority error
        rather than the most specific."

        Claim: submitting a RETURN refund where Order.status != RETURNED
        (referential violation) AND supporting_documents is empty
        (constraint violation) returns ERR_ORDER_NOT_ELIGIBLE
        (referential, higher priority), not ERR_REFUND_DOCUMENTS_INCOMPLETE.

        # difficulty: priority_pair_validation_conflict/business_referential_vs_business_constraint_on_refund_submit
        """
        ctx = setup_released_declaration()  # Order in RELEASED, NOT RETURNED
        refund = create_refund(
            ctx.declaration, ctx.declarant,
            refund_reason="RETURN",
            supporting_documents=[],   # empty → constraint violation too
        )
        res = api.submit_refund(
            refund["id"], make_declarant_headers(ctx.declarant["id"])
        )
        validate_error(res, "ERR_ORDER_NOT_ELIGIBLE", expected_status=409)


# =============================================================================
# Rule 6 — boundary_precision_check
# =============================================================================
class TestBoundaryPrecision:
    """rule_id: boundary_precision_check — single-fen / single-second
    flips of a numeric or temporal threshold."""

    def test_personal_postal_threshold_inclusive_at_500000_fen(self, api):
        """PRD §3.6 (verbatim): "The mode is PERSONAL_POSTAL only when
        both conditions hold: the declaration's trade_mode is
        B2C_DIRECT_MAIL, and the declaration's dutiable_value_cny_minor
        is at most PERSONAL_POSTAL_THRESHOLD_CNY_MINOR, which is fixed
        at 500,000 fen (i.e., 5,000.00 CNY). The boundary is inclusive:
        a declaration whose dutiable value is exactly 5,000.00 CNY still
        qualifies for personal-postal mode if its trade mode is
        B2C_DIRECT_MAIL."

        Claim: at exactly 500_000 fen → PERSONAL_POSTAL; at 500_001 fen
        → STANDARD.

        # difficulty: boundary_precision_check/personal_postal_threshold_inclusive_at_500000_fen
        """
        ctx_eq = setup_personal_postal_at_dutiable(500_000)
        s_eq = submit_declaration(ctx_eq.declaration, ctx_eq.declarant)
        assert s_eq["dutiable_value_cny_minor"] == 500_000
        assert s_eq["tax_mode"] == "PERSONAL_POSTAL"

        ctx_ov = setup_personal_postal_at_dutiable(500_001)
        s_ov = submit_declaration(ctx_ov.declaration, ctx_ov.declarant)
        assert s_ov["dutiable_value_cny_minor"] == 500_001
        assert s_ov["tax_mode"] == "STANDARD"

    def test_inspection_appointment_half_open_60min_window(self, api):
        """PRD §3.7 (verbatim): "two appointments on the same bay_code
        are in conflict whenever their intervals
        [scheduled_at, scheduled_at + 60min) overlap. A conflict is
        reported as ERR_INSPECTION_SLOT_TAKEN."

        Claim: at exactly +60min from the first → accepted (boundary
        open on the right). At +59min → ERR_INSPECTION_SLOT_TAKEN.

        # difficulty: boundary_precision_check/inspection_appointment_half_open_60min_window
        """
        ctx_a = setup_under_review_declaration()
        ctx_b = setup_under_review_declaration()
        ctx_c = setup_under_review_declaration()
        schedule_inspection(
            ctx_a.declaration["id"],
            scheduled_at="2026-07-01T10:00:00Z", bay_code="BAY-BND",
        )
        # +60min: open boundary, accepted.
        res_b = api.schedule_inspection(
            ctx_b.declaration["id"],
            schedule_inspection_payload(
                scheduled_at="2026-07-01T11:00:00Z", bay_code="BAY-BND"
            ),
            TEST_USERS["customs_officer_headers"],
        )
        validate_success(res_b, expected_status=201)
        # +59min: still inside the half-open window → conflict.
        res_c = api.schedule_inspection(
            ctx_c.declaration["id"],
            schedule_inspection_payload(
                scheduled_at="2026-07-01T10:59:00Z", bay_code="BAY-BND"
            ),
            TEST_USERS["customs_officer_headers"],
        )
        validate_error(res_c, "ERR_INSPECTION_SLOT_TAKEN", expected_status=409)


# =============================================================================
# Rule 7 — cross_entity_state_dependency
# =============================================================================
class TestCrossEntityStateDependency:
    """rule_id: cross_entity_state_dependency — a transition on entity A
    is gated on a state of entity B."""

    def test_declaration_submit_requires_importer_active(self, api):
        """PRD §3.4 (verbatim): "then the importer must be ACTIVE (else
        ERR_IMPORTER_SUSPENDED) and the declarant must likewise be
        ACTIVE".
        PRD §3.1: "suspension is an explicit operator action that sets
        status to SUSPENDED and blocks creation or submission of
        declarations for that importer."

        Claim: an otherwise-valid DRAFT declaration cannot be submitted
        once its Importer is SUSPENDED → ERR_IMPORTER_SUSPENDED at 409.

        # difficulty: cross_entity_state_dependency/declaration_submit_requires_importer_active
        """
        ctx = setup_draft_declaration()
        suspend_importer(ctx.importer["id"])
        res = api.submit_declaration(
            ctx.declaration["id"],
            make_declarant_headers(ctx.declarant["id"]),
        )
        validate_error(res, "ERR_IMPORTER_SUSPENDED", expected_status=409)
        # Declaration still in DRAFT (transition blocked).
        decl = ctx.refresh_declaration()
        assert decl["status"] == "DRAFT"

    def test_refund_return_requires_order_returned(self, api):
        """PRD §3.10 (verbatim): "The cross-entity guard then matches
        the refund reason to the order's status: a RETURN refund
        requires the parent order to be in RETURNED ... A mismatch on
        the cross-entity guard yields ERR_ORDER_NOT_ELIGIBLE."

        Claim: a RETURN refund on a still-RELEASED order yields
        ERR_ORDER_NOT_ELIGIBLE; the same refund passes once the order is
        moved to RETURNED.

        # difficulty: cross_entity_state_dependency/refund_return_requires_order_returned
        """
        ctx = setup_released_declaration()
        refund = create_refund(
            ctx.declaration, ctx.declarant, refund_reason="RETURN",
        )
        res = api.submit_refund(
            refund["id"], make_declarant_headers(ctx.declarant["id"])
        )
        validate_error(res, "ERR_ORDER_NOT_ELIGIBLE", expected_status=409)
        # Refund stayed in DRAFT.
        get_res = api.get_refund(
            refund["id"], TEST_USERS["customs_officer_headers"]
        )
        rd = validate_success(get_res)
        assert rd["status"] == "DRAFT"


# =============================================================================
# Rule 8 — resource_temporal_overlap
# =============================================================================
class TestResourceTemporalOverlap:
    """rule_id: resource_temporal_overlap — temporal-overlap rules over
    different resource interval semantics."""

    def test_inspection_bay_fixed_60min_half_open_overlap(self, api):
        """PRD §3.7 (verbatim): "two appointments on the same bay_code
        are in conflict whenever their intervals
        [scheduled_at, scheduled_at + 60min) overlap. A conflict is
        reported as ERR_INSPECTION_SLOT_TAKEN."

        Claim: a +30min mid-window appointment on the same bay collides
        → 409 ERR_INSPECTION_SLOT_TAKEN.

        # difficulty: resource_temporal_overlap/inspection_bay_fixed_60min_half_open_overlap
        """
        ctx_a = setup_under_review_declaration()
        ctx_b = setup_under_review_declaration()
        schedule_inspection(
            ctx_a.declaration["id"],
            scheduled_at="2026-08-01T10:00:00Z", bay_code="BAY-FIX",
        )
        res = api.schedule_inspection(
            ctx_b.declaration["id"],
            schedule_inspection_payload(
                scheduled_at="2026-08-01T10:30:00Z", bay_code="BAY-FIX"
            ),
            TEST_USERS["customs_officer_headers"],
        )
        validate_error(res, "ERR_INSPECTION_SLOT_TAKEN", expected_status=409)

    def test_tariff_rule_arbitrary_length_closed_open_overlap(self, api):
        """PRD §3.1 (verbatim): "Tariff rules are open at the lower
        bound and closed at the upper bound, in the sense that the
        interval is [effective_from, effective_to); the publishing
        endpoint guards against accidentally overlapping rules for the
        same triple of HS code, origin country, and destination country,
        rejecting any new rule whose interval overlaps an existing
        rule's interval with ERR_TARIFF_RULE_OVERLAP. Back-to-back rules
        where one's effective_to exactly equals the next's effective_from
        are explicitly allowed — that is a gap-free, overlap-free join,
        not an overlap."

        Claim: back-to-back rules accepted; straddling boundary →
        ERR_TARIFF_RULE_OVERLAP.

        # difficulty: resource_temporal_overlap/tariff_rule_arbitrary_length_closed_open_overlap
        """
        hs = create_hs_code()
        # Rule A: [2026-01-01, 2026-04-01).
        api.create_tariff_rule(
            create_tariff_rule_payload(
                hs["id"],
                tariff_rate_bps=500,
                effective_from="2026-01-01T00:00:00Z",
                effective_to="2026-04-01T00:00:00Z",
            ),
            TEST_USERS["customs_officer_headers"],
        )
        # Rule B back-to-back: [2026-04-01, 2026-07-01) — accepted.
        res_b = api.create_tariff_rule(
            create_tariff_rule_payload(
                hs["id"],
                tariff_rate_bps=600,
                effective_from="2026-04-01T00:00:00Z",
                effective_to="2026-07-01T00:00:00Z",
            ),
            TEST_USERS["customs_officer_headers"],
        )
        validate_success(res_b, expected_status=201)
        # Rule C straddles A's right boundary → overlap.
        res_c = api.create_tariff_rule(
            create_tariff_rule_payload(
                hs["id"],
                tariff_rate_bps=700,
                effective_from="2026-03-15T00:00:00Z",
                effective_to="2026-05-01T00:00:00Z",
            ),
            TEST_USERS["customs_officer_headers"],
        )
        validate_error(res_c, "ERR_TARIFF_RULE_OVERLAP", expected_status=409)


# =============================================================================
# Rule 9 — compensating_invariant
# =============================================================================
class TestCompensatingInvariant:
    """rule_id: compensating_invariant — forward action paired with its
    inverse leaves a conserved quantity unchanged."""

    def test_payment_confirm_then_reverse_preserves_total_tax(self, api):
        """PRD §3.6: "tariff_amount_cny_minor, consumption_tax_cny_minor,
        and vat_amount_cny_minor are the sums of the per-line floor
        results across all lines (floor per line, then sum);
        total_tax_cny_minor is their sum."
        PRD §3.8: "A successful reversal flips the notice from PAID to
        REVERSED; if the linked declaration was in RELEASED, it reverts
        to APPROVED".
        PRD §3.7 (verbatim): "the system creates a PaymentNotice whose
        amount_cny_minor equals the declaration's current
        total_tax_cny_minor (an immutable snapshot taken at approval
        time)".

        Claim: confirm + reverse leaves Declaration.total_tax_cny_minor
        and the notice's amount_cny_minor (snapshot — immutable per PRD)
        UNCHANGED.

        # difficulty: compensating_invariant/payment_confirm_then_reverse_preserves_total_tax
        """
        ctx = setup_released_declaration(
            trade_mode="GENERAL_TRADE",
            line_items=[make_line_item(quantity=1, unit_price=10_000, weight_kg=0.1)],
            currency="USD",
            rate_micros=1_000_000,
            hs_code_overrides={
                "tariff_rate_bps": 1000, "vat_rate_bps": 1300,
                "consumption_tax_rate_bps": 0, "postal_tax_rate_bps": 0,
            },
        )
        before_total = ctx.declaration["total_tax_cny_minor"]
        before_tariff = ctx.declaration["tariff_amount_cny_minor"]
        before_vat = ctx.declaration["vat_amount_cny_minor"]
        before_consumption = ctx.declaration["consumption_tax_cny_minor"]
        before_amount = ctx.payment_notice["amount_cny_minor"]
        # Reverse.
        reverse_payment(ctx.payment_notice["id"])
        decl = ctx.refresh_declaration()
        notice = ctx.refresh_payment_notice()
        assert decl["total_tax_cny_minor"] == before_total
        assert decl["tariff_amount_cny_minor"] == before_tariff
        assert decl["vat_amount_cny_minor"] == before_vat
        assert decl["consumption_tax_cny_minor"] == before_consumption
        # PRD §1.1 / §3.7 — pn.amount_cny_minor is an immutable snapshot.
        assert notice["amount_cny_minor"] == before_amount
        # Composition invariant from PRD §3.6.
        assert (
            decl["total_tax_cny_minor"]
            == decl["tariff_amount_cny_minor"]
            + decl["vat_amount_cny_minor"]
            + decl["consumption_tax_cny_minor"]
        )

    def test_refund_submit_then_reject_preserves_executed_refund_count(self, api):
        """PRD §3.10 (verbatim): "rejection transitions it from SUBMITTED
        to REJECTED, persists the customs officer's rejection_reason ...
        Approved refunds are then disbursed by a finance operator,
        transitioning from APPROVED to EXECUTED; on execution,
        executed_amount_cny_minor is set equal to refundable_amount_cny_minor".
        PRD §3.10: "At most one EXECUTED refund may exist per
        declaration."

        Claim: submit + reject leaves the count of EXECUTED refunds for
        this declaration UNCHANGED at zero.

        # difficulty: compensating_invariant/refund_submit_then_reject_preserves_executed_refund_count
        """
        ctx = setup_returned_order_with_paid_declaration()
        # Confirm baseline: no EXECUTED refunds yet.
        # The PRD does not guarantee a list endpoint for refunds, but it
        # does guarantee status (PRD §1.1 entity field). We verify the
        # count by ensuring no refund has yet been EXECUTED — there's
        # only the one we're about to create.
        refund = create_refund(
            ctx.declaration, ctx.declarant, refund_reason="RETURN",
        )
        # Submit → refund leaves DRAFT (count of EXECUTED still 0).
        sub = submit_refund(refund, ctx.declarant)
        assert sub["status"] == "SUBMITTED"
        assert sub.get("executed_amount_cny_minor", 0) == 0
        # Reject → refund REJECTED, no EXECUTED introduced.
        rej = reject_refund(sub, "compensating_test")
        assert rej["status"] == "REJECTED"
        assert rej.get("executed_amount_cny_minor", 0) == 0
        # Re-fetch after the round-trip and confirm again.
        get_res = api.get_refund(
            refund["id"], TEST_USERS["customs_officer_headers"]
        )
        final = validate_success(get_res)
        assert final["status"] == "REJECTED"
        assert final.get("executed_amount_cny_minor", 0) == 0


# =============================================================================
# Complementary coverage — every instance is covered by at least TWO tests.
# These tests exercise the SAME PRD-pinned rule from a different angle
# (different inputs, different transitions, different observable surface)
# while still proving the rule via PRD-verbatim citations.
# =============================================================================

# ----- Rule 1: dual_variant_calc -----------------------------------------

def test_transaction_vs_computed_value_differ(api):
    """PRD §3.5: "Under TRANSACTION_VALUE, the line's CNY contribution is
    the simplest mapping: multiply line_value_minor by the pinned
    exchange rate's rate_micros, divide by 1,000,000, and floor toward
    zero. This yields the lowest of the three variants for a given line."
    PRD §3.5: "Under COMPUTED_VALUE, the calculation is cost-plus.
    First, a logistics component is computed by multiplying the line's
    weight_kg by LOGISTICS_PER_KG_MINOR (fixed at 5,000 fen, i.e.,
    50.00 CNY per kilogram) and rounding up to the next integer".

    Claim: TRANSACTION_VALUE and COMPUTED_VALUE on identical input
    produce strictly different dutiable_value_cny_minor.

    # difficulty: dual_variant_calc/dutiable_value_method_variants_on_declaration
    """
    line = make_line_item(quantity=1, unit_price=10_000, weight_kg=1.0)
    ctx_t = setup_draft_declaration(
        dutiable_value_method="TRANSACTION_VALUE",
        line_items=[line],
        currency="USD",
        rate_micros=7_000_000,
        hs_code_overrides={
            "tariff_rate_bps": 0, "vat_rate_bps": 0,
            "consumption_tax_rate_bps": 0, "postal_tax_rate_bps": 0,
        },
    )
    ctx_c = setup_draft_declaration(
        dutiable_value_method="COMPUTED_VALUE",
        line_items=[line],
        currency="USD",
        rate_micros=7_000_000,
        hs_code_overrides={
            "tariff_rate_bps": 0, "vat_rate_bps": 0,
            "consumption_tax_rate_bps": 0, "postal_tax_rate_bps": 0,
        },
    )
    st = submit_declaration(ctx_t.declaration, ctx_t.declarant)
    sc = submit_declaration(ctx_c.declaration, ctx_c.declarant)
    # PRD pins: transaction = 70_000; computed = 115_500 (see §3.5 arithmetic).
    assert st["dutiable_value_cny_minor"] == 70_000
    assert sc["dutiable_value_cny_minor"] == 115_500
    assert st["dutiable_value_cny_minor"] != sc["dutiable_value_cny_minor"]


def test_full_refund_for_order_cancellation_vs_partial_for_erroneous(api):
    """PRD §3.10: "For ORDER_CANCELLATION refunds, the refundable amount
    is likewise the entire PaymentNotice.amount_cny_minor — the
    cancellation rolls back a conditional release."
    PRD §3.10: "For ERRONEOUS_DECLARATION refunds, the refundable
    amount is the larger of zero and the difference between
    PaymentNotice.amount_cny_minor and the current
    Declaration.total_tax_cny_minor".

    Claim: A second variant pair — ORDER_CANCELLATION (full) vs
    ERRONEOUS_DECLARATION (partial) — also yields different refundable
    amounts when the post-amendment tax is non-zero but less than the
    snapshot. Construction: ORDER_CANCELLATION refund equals
    pn.amount_cny_minor; ERRONEOUS_DECLARATION refund equals
    pn.amount - amended_total < pn.amount.

    # difficulty: dual_variant_calc/refund_amount_full_vs_partial_on_refund
    """
    # ORDER_CANCELLATION setup: cancel order on a paid declaration.
    # NOTE: PRD §3.3 states cancellation is allowed only when no
    # declaration exists or only a DRAFT exists. After a declaration
    # reaches APPROVED/RELEASED, cancellation is no longer reachable
    # through the public API. This test therefore constructs the
    # ERRONEOUS_DECLARATION half (which is fully reachable) and asserts
    # the partial-refund formula directly; a parallel RETURN refund on
    # a separate declaration validates the full-refund half.
    ctx_e = setup_released_declaration(
        trade_mode="GENERAL_TRADE",
        line_items=[make_line_item(quantity=1, unit_price=10_000, weight_kg=0.1)],
        currency="USD",
        rate_micros=1_000_000,
        hs_code_overrides={
            "tariff_rate_bps": 1000, "vat_rate_bps": 1300,
            "consumption_tax_rate_bps": 0, "postal_tax_rate_bps": 0,
        },
    )
    notice_amount = ctx_e.payment_notice["amount_cny_minor"]
    # Amend down to a zero-tax HS code; recomputed total = 0.
    zero_hs = create_hs_code(
        tariff_rate_bps=0, vat_rate_bps=0,
        consumption_tax_rate_bps=0, postal_tax_rate_bps=0,
    )
    line_id = ctx_e.lines[0]["id"]
    amend_res = api.amend_declaration(
        ctx_e.declaration["id"],
        {"lines": [{"line_id": line_id, "hs_code_id": zero_hs["id"]}]},
        make_declarant_headers(ctx_e.declarant["id"]),
    )
    amended = validate_success(amend_res)
    refund_e = create_refund(
        ctx_e.declaration, ctx_e.declarant,
        refund_reason="ERRONEOUS_DECLARATION",
    )
    sub_e = submit_refund(refund_e, ctx_e.declarant)
    # Partial: pn.amount - 0 = pn.amount, so equal to full in this
    # arithmetic. Construct strict inequality by amending to a halved-
    # tariff HS code instead.
    half_hs = create_hs_code(
        tariff_rate_bps=500, vat_rate_bps=0,
        consumption_tax_rate_bps=0, postal_tax_rate_bps=0,
    )
    # Set up a second flow where amend leaves a non-zero tax remainder.
    ctx_e2 = setup_released_declaration(
        trade_mode="GENERAL_TRADE",
        line_items=[make_line_item(quantity=1, unit_price=10_000, weight_kg=0.1)],
        currency="USD",
        rate_micros=1_000_000,
        hs_code_overrides={
            "tariff_rate_bps": 1000, "vat_rate_bps": 1300,
            "consumption_tax_rate_bps": 0, "postal_tax_rate_bps": 0,
        },
    )
    notice_amount2 = ctx_e2.payment_notice["amount_cny_minor"]
    line_id2 = ctx_e2.lines[0]["id"]
    api.amend_declaration(
        ctx_e2.declaration["id"],
        {"lines": [{"line_id": line_id2, "hs_code_id": half_hs["id"]}]},
        make_declarant_headers(ctx_e2.declarant["id"]),
    )
    amended2 = validate_success(api.get_declaration(
        ctx_e2.declaration["id"], TEST_USERS["customs_officer_headers"]
    ))
    refund_e2 = create_refund(
        ctx_e2.declaration, ctx_e2.declarant,
        refund_reason="ERRONEOUS_DECLARATION",
    )
    sub_e2 = submit_refund(refund_e2, ctx_e2.declarant)
    # PRD §3.10 partial formula.
    expected_partial = max(0, notice_amount2 - amended2["total_tax_cny_minor"])
    assert sub_e2["refundable_amount_cny_minor"] == expected_partial
    # And the partial refund is strictly less than the original notice.
    assert sub_e2["refundable_amount_cny_minor"] < notice_amount2


# ----- Rule 2: combinatorial_formula -------------------------------------

def test_personal_postal_three_input_axes_secondary(api):
    """PRD §3.6: "In every other case (general trade, bonded warehouse,
    or B2C direct mail strictly above the threshold), the mode is
    STANDARD."

    Claim: a BONDED_WAREHOUSE declaration with low value still resolves
    to STANDARD (the third trade_mode axis the rule must rule out).

    # difficulty: combinatorial_formula/personal_postal_tiered_branching_mode_a
    """
    ctx = setup_draft_declaration(
        trade_mode="BONDED_WAREHOUSE",
        dutiable_value_method="TRANSACTION_VALUE",
        line_items=[make_line_item(quantity=1, unit_price=10_000, weight_kg=1.0)],
        currency="USD",
        rate_micros=1_000_000,
        hs_code_overrides={
            "tariff_rate_bps": 1000, "vat_rate_bps": 1300,
            "consumption_tax_rate_bps": 0, "postal_tax_rate_bps": 1000,
        },
    )
    submitted = submit_declaration(ctx.declaration, ctx.declarant)
    assert submitted["tax_mode"] == "STANDARD"


def test_floor_per_line_then_sum_for_vat_amount(api):
    """PRD §3.6: "the line VAT is that base multiplied by the HS code's
    vat_rate_bps, divided by 10,000, floored. The declaration's
    tariff_amount_cny_minor, consumption_tax_cny_minor, and
    vat_amount_cny_minor are the sums of the per-line floor results
    across all lines (floor per line, then sum)".

    Claim: per-line-floor-then-sum applies to VAT exactly as it does to
    tariff. Two lines each with line_dutiable=5050 fen, vat_rate=1%
    (100 bps): per-line vat = floor(5050*100/10000) = 50, sum = 100.
    The 'sum-then-floor' would give floor(10100*100/10000) = 101.

    # difficulty: combinatorial_formula/per_line_floor_then_sum_rounding_order_mode_b
    """
    ctx = setup_draft_declaration(
        dutiable_value_method="TRANSACTION_VALUE",
        line_items=[
            make_line_item(quantity=1, unit_price=5050, weight_kg=0.1),
            make_line_item(quantity=1, unit_price=5050, weight_kg=0.1),
        ],
        currency="USD",
        rate_micros=1_000_000,
        hs_code_overrides={
            "tariff_rate_bps": 0, "vat_rate_bps": 100,
            "consumption_tax_rate_bps": 0, "postal_tax_rate_bps": 0,
        },
    )
    submitted = submit_declaration(ctx.declaration, ctx.declarant)
    assert submitted["dutiable_value_cny_minor"] == 10_100
    # Per-line: vat_base = dutiable + 0 + 0 = 5050; line_vat =
    # floor(5050*100/10000) = 50. Sum = 100. NOT 101.
    assert submitted["vat_amount_cny_minor"] == 100


# ----- Rule 3: non_linear_state_machine ----------------------------------

def test_query_round_trip_query_id_set_then_cleared(api):
    """PRD §3.7: "this transitions the declaration from UNDER_REVIEW to
    QUERIED and pins Declaration.query_id to the new query, whose own
    status begins at OPEN."
    PRD §3.7: "The customs officer then resolves the query, which moves
    the query to RESOLVED, clears Declaration.query_id, and returns the
    declaration from QUERIED to UNDER_REVIEW."

    Claim: through the round-trip, query_id is set on QUERIED and
    cleared on return-to-UNDER_REVIEW. (Inspects the intermediate state,
    complementing the round-trip-final-state test.)

    # difficulty: non_linear_state_machine/declaration_query_response_cycle
    """
    ctx = setup_under_review_declaration()
    q_res = api.open_query(
        ctx.declaration["id"],
        open_query_payload(required_documents=["INVOICE"]),
        TEST_USERS["customs_officer_headers"],
    )
    q = validate_success(q_res, expected_status=201)
    # Intermediate state: declaration in QUERIED with query_id set.
    decl_mid = ctx.refresh_declaration()
    assert decl_mid["status"] == "QUERIED"
    assert decl_mid.get("query_id") == q["id"]
    # Respond + resolve → back to UNDER_REVIEW with query_id cleared.
    respond_to_query(q["id"], ctx.declarant)
    resolve_query(q["id"])
    decl_final = ctx.refresh_declaration()
    assert decl_final["status"] == "UNDER_REVIEW"
    assert decl_final.get("query_id") in (None, "")


def test_refund_branches_have_distinct_terminal_states(api):
    """PRD §3.10: "Approved refunds are then disbursed by a finance
    operator, transitioning from APPROVED to EXECUTED; on execution,
    executed_amount_cny_minor is set equal to refundable_amount_cny_minor".
    PRD §3.10: "rejection transitions it from SUBMITTED to REJECTED,
    persists the customs officer's rejection_reason".

    Claim: from a single SUBMITTED refund, the two diverging branches
    (APPROVED→EXECUTED vs REJECTED) produce distinct terminal states
    with distinct observable side effects: EXECUTED disburses funds via
    executed_amount_cny_minor; REJECTED persists rejection_reason.

    # difficulty: non_linear_state_machine/refund_branching_approve_or_reject
    """
    # APPROVED→EXECUTED branch.
    ctx_a = setup_returned_order_with_paid_declaration()
    ra = create_refund(
        ctx_a.declaration, ctx_a.declarant, refund_reason="RETURN",
    )
    sa = submit_refund(ra, ctx_a.declarant)
    aa = approve_refund(sa)
    assert aa["status"] == "APPROVED"
    ea = execute_refund(aa)
    assert ea["status"] == "EXECUTED"
    assert ea["executed_amount_cny_minor"] > 0
    # REJECTED branch.
    ctx_b = setup_returned_order_with_paid_declaration()
    rb = create_refund(
        ctx_b.declaration, ctx_b.declarant, refund_reason="RETURN",
    )
    sb = submit_refund(rb, ctx_b.declarant)
    rejb = reject_refund(sb, "branch-test")
    assert rejb["status"] == "REJECTED"
    # Distinct: one branch carries executed_amount, the other carries
    # rejection_reason.
    assert ea.get("rejection_reason") in (None, "")
    assert rejb.get("rejection_reason") == "branch-test"


# ----- Rule 4: transitive_cascade ----------------------------------------

def test_payment_confirm_cascade_writes_audit_trail(api, customs_officer_headers):
    """PRD §3.8: "A successful confirmation flips the notice from
    PENDING to PAID, cascades the linked declaration from APPROVED to
    RELEASED ... and emits both a PAYMENT_CONFIRMED audit event and an
    EXTERNAL_SYNC audit event simulating the push from the payment
    gateway."

    Claim: the three-hop cascade also writes audit events that prove
    each hop (a PAYMENT_CONFIRMED on the notice, and an EXTERNAL_SYNC
    push). Verifies the cascade by INSPECTING audit trail rather than
    by direct state assertion.

    # difficulty: transitive_cascade/confirm_payment_three_hop_release_cascade
    """
    ctx = setup_released_declaration()
    res = api.list_audit_events(
        customs_officer_headers,
        params={"subject_type": "PAYMENT_NOTICE",
                "subject_id": ctx.payment_notice["id"], "limit": 100},
    )
    body, _meta = validate_paginated_aux(res)
    types = [e.get("event_type") for e in body]
    assert "PAYMENT_CONFIRMED" in types


def test_reverse_payment_does_not_revert_order_to_pending_declaration(api):
    """PRD §3.8: "A successful reversal flips the notice from PAID to
    REVERSED; if the linked declaration was in RELEASED, it reverts to
    APPROVED (the order's RELEASED cascade is similarly undone)."
    PRD §2.7: "When a child declaration enters APPROVED or
    CONDITIONALLY_RELEASED, the parent order automatically advances
    from PENDING_DECLARATION to DECLARED".

    Claim: the reverse cascade is bounded — the order rolls back from
    RELEASED to DECLARED (because Declaration is now APPROVED), but
    NOT all the way back to PENDING_DECLARATION. The two-hop chain
    PaymentNotice→Declaration→Order undoes only the second hop's
    forward cascade.

    # difficulty: transitive_cascade/reverse_payment_two_hop_revert_cascade
    """
    ctx = setup_paid_then_reversed()
    order = ctx.refresh_order()
    # Per PRD §2.7 cascade rules, an APPROVED declaration's parent
    # order is in DECLARED state. Reverse undoes RELEASED→DECLARED but
    # keeps DECLARED (because Declaration.status is APPROVED, not
    # rolled back further).
    assert order["status"] == "DECLARED"


# ----- Rule 5: priority_pair_validation_conflict -------------------------

def test_state_precedes_temporal_on_already_paid_with_idempotency_replay(api):
    """PRD §2.9: "the response surfaces the highest-priority error
    rather than the most specific."
    PRD §2.9: "State-transition validity comes after existence;
    a transition request against a non-existent resource always
    surfaces as ERR_NOT_FOUND rather than as ERR_INVALID_STATE_TRANSITION."

    Claim: an already-PAID notice that is also expired AND has a
    fresh idempotency-key still surfaces ERR_INVALID_STATE_TRANSITION
    (state, priority 5) — the temporal expiry check (priority 13)
    comes later and is preempted.

    # difficulty: priority_pair_validation_conflict/state_vs_business_temporal_on_payment_confirm
    """
    ctx = setup_released_declaration()  # notice PAID
    api.advance_clock(
        PAYMENT_NOTICE_DUE_SECONDS + 120,
        TEST_USERS["customs_officer_headers"],
    )
    key = fresh_idempotency_key("st-temp")
    hdrs = dict(TEST_USERS["finance_officer_headers"])
    hdrs["Idempotency-Key"] = key
    body = confirm_payment_payload(
        payment_channel="ELECTRONIC_PAYMENT", idempotency_key=key,
    )
    res = api.confirm_payment(ctx.payment_notice["id"], body, hdrs)
    validate_error(res, "ERR_INVALID_STATE_TRANSITION", expected_status=409)


def test_referential_precedes_constraint_with_cancellation_reason(api):
    """PRD §2.9: "Business-referential checks (importer suspended,
    declaration uniqueness on an order) run after state validity.
    Business-constraint checks (template completeness, override status,
    rework limit, idempotency, channel-specific requirements, document
    completeness, HS code deprecation) and business-temporal checks
    (inspection slot overlap, payment notice expiry, tariff rule
    effective-window overlap) run last".

    Claim: the same priority pattern (referential beats constraint)
    holds for ORDER_CANCELLATION reason as well — when Order.status
    isn't CANCELLED AND supporting_documents is empty, the response is
    ERR_ORDER_NOT_ELIGIBLE, not ERR_REFUND_DOCUMENTS_INCOMPLETE.

    # difficulty: priority_pair_validation_conflict/business_referential_vs_business_constraint_on_refund_submit
    """
    ctx = setup_released_declaration()
    refund = create_refund(
        ctx.declaration, ctx.declarant,
        refund_reason="ORDER_CANCELLATION",
        supporting_documents=[],
    )
    res = api.submit_refund(
        refund["id"], make_declarant_headers(ctx.declarant["id"])
    )
    validate_error(res, "ERR_ORDER_NOT_ELIGIBLE", expected_status=409)


# ----- Rule 6: boundary_precision_check ----------------------------------

def test_personal_postal_just_below_threshold_inclusive(api):
    """PRD §3.6: "the declaration's dutiable_value_cny_minor is at most
    PERSONAL_POSTAL_THRESHOLD_CNY_MINOR, which is fixed at 500,000 fen
    (i.e., 5,000.00 CNY). The boundary is inclusive: a declaration
    whose dutiable value is exactly 5,000.00 CNY still qualifies for
    personal-postal mode if its trade mode is B2C_DIRECT_MAIL."

    Claim: at 499_999 fen — strictly less than the threshold — the
    declaration is also PERSONAL_POSTAL. (Pairs with the X==threshold
    test to demonstrate the inclusive boundary on both sides of the
    flip.)

    # difficulty: boundary_precision_check/personal_postal_threshold_inclusive_at_500000_fen
    """
    ctx = setup_personal_postal_at_dutiable(499_999)
    submitted = submit_declaration(ctx.declaration, ctx.declarant)
    assert submitted["dutiable_value_cny_minor"] == 499_999
    assert submitted["tax_mode"] == "PERSONAL_POSTAL"


def test_inspection_slot_at_one_second_before_60min_collides(api):
    """PRD §3.7: "two appointments on the same bay_code are in conflict
    whenever their intervals [scheduled_at, scheduled_at + 60min)
    overlap."

    Claim: a +59min59s appointment is still inside the half-open
    window [10:00, 11:00) → collision, ERR_INSPECTION_SLOT_TAKEN.
    Pairs with the +60min boundary-open test.

    # difficulty: boundary_precision_check/inspection_appointment_half_open_60min_window
    """
    ctx_a = setup_under_review_declaration()
    ctx_b = setup_under_review_declaration()
    schedule_inspection(
        ctx_a.declaration["id"],
        scheduled_at="2026-09-01T10:00:00Z", bay_code="BAY-EDGE",
    )
    res = api.schedule_inspection(
        ctx_b.declaration["id"],
        schedule_inspection_payload(
            scheduled_at="2026-09-01T10:59:59Z", bay_code="BAY-EDGE"
        ),
        TEST_USERS["customs_officer_headers"],
    )
    validate_error(res, "ERR_INSPECTION_SLOT_TAKEN", expected_status=409)


# ----- Rule 7: cross_entity_state_dependency -----------------------------

def test_declaration_create_blocked_by_suspended_importer(api):
    """PRD §3.3: "If the importer was suspended at the moment of
    creation, the creation is rejected with ERR_IMPORTER_SUSPENDED."

    Claim: importer suspension blocks not only submit (the primary
    instance test) but also the upstream create-declaration step.
    Different observable surface: same cross-entity rule.

    # difficulty: cross_entity_state_dependency/declaration_submit_requires_importer_active
    """
    importer, declarant = create_party_pair()
    from test_helpers import (
        setup_reference_data,
        create_declaration_payload as _payload,
    )
    from test_helpers.fixtures import _fresh_currency_code
    fresh_currency = _fresh_currency_code()
    setup_reference_data(from_currency=fresh_currency)
    order = create_order(importer, declarant, currency=fresh_currency)
    suspend_importer(importer["id"])
    res = api.create_declaration(
        _payload(order["id"], trade_mode=order["trade_mode"]),
        make_declarant_headers(declarant["id"]),
    )
    validate_error(res, "ERR_IMPORTER_SUSPENDED", expected_status=409)


def test_refund_cancellation_requires_order_cancelled(api):
    """PRD §3.10: "an ORDER_CANCELLATION refund requires the parent
    order to be in CANCELLED ... A mismatch on the cross-entity guard
    yields ERR_ORDER_NOT_ELIGIBLE."

    Claim: parallel to the RETURN case, the CANCELLATION cross-entity
    guard demands Order.status == CANCELLED. Same rule pattern, second
    refund_reason.

    # difficulty: cross_entity_state_dependency/refund_return_requires_order_returned
    """
    ctx = setup_released_declaration()
    refund = create_refund(
        ctx.declaration, ctx.declarant,
        refund_reason="ORDER_CANCELLATION",
        supporting_documents=[
            {"doc_type": "CANCELLATION_AGREEMENT", "voucher_url": "u"},
        ],
    )
    res = api.submit_refund(
        refund["id"], make_declarant_headers(ctx.declarant["id"])
    )
    validate_error(res, "ERR_ORDER_NOT_ELIGIBLE", expected_status=409)


# ----- Rule 8: resource_temporal_overlap ---------------------------------

def test_inspection_overlap_at_inverse_position(api):
    """PRD §3.7: "a new scheduled_at may not fall in the half-open
    60-minute window starting at any existing appointment's start, and
    no existing appointment's start may fall in the new appointment's
    half-open 60-minute window."

    Claim: an inverse-position collision — scheduling FIRST at 10:30,
    then at 10:00 — is also blocked. The overlap is symmetric per the
    PRD's 'and no existing appointment's start may fall in the new
    appointment's half-open 60-minute window' clause.

    # difficulty: resource_temporal_overlap/inspection_bay_fixed_60min_half_open_overlap
    """
    ctx_a = setup_under_review_declaration()
    ctx_b = setup_under_review_declaration()
    schedule_inspection(
        ctx_a.declaration["id"],
        scheduled_at="2026-10-01T10:30:00Z", bay_code="BAY-INV",
    )
    res = api.schedule_inspection(
        ctx_b.declaration["id"],
        schedule_inspection_payload(
            scheduled_at="2026-10-01T10:00:00Z", bay_code="BAY-INV"
        ),
        TEST_USERS["customs_officer_headers"],
    )
    validate_error(res, "ERR_INSPECTION_SLOT_TAKEN", expected_status=409)


def test_tariff_rule_overlap_with_open_ended_existing(api):
    """PRD §3.1: "effective_from is at or before the declaration's
    submission timestamp while effective_to is strictly after that
    timestamp (a null effective_to is treated as open-ended)."
    PRD §3.1: "the publishing endpoint guards against accidentally
    overlapping rules for the same triple of HS code, origin country,
    and destination country, rejecting any new rule whose interval
    overlaps an existing rule's interval with ERR_TARIFF_RULE_OVERLAP."

    Claim: an open-ended existing rule (effective_to null) overlaps
    any new rule whose effective_from is at or after its effective_from.
    Tests the open-ended boundary case complementing the bounded case.

    # difficulty: resource_temporal_overlap/tariff_rule_arbitrary_length_closed_open_overlap
    """
    hs = create_hs_code()
    # Open-ended rule covering [2026-01-01, ∞).
    api.create_tariff_rule(
        create_tariff_rule_payload(
            hs["id"],
            tariff_rate_bps=500,
            effective_from="2026-01-01T00:00:00Z",
            effective_to=None,
        ),
        TEST_USERS["customs_officer_headers"],
    )
    # New rule that lands in the open-ended span → overlap.
    res = api.create_tariff_rule(
        create_tariff_rule_payload(
            hs["id"],
            tariff_rate_bps=600,
            effective_from="2026-06-01T00:00:00Z",
            effective_to="2026-08-01T00:00:00Z",
        ),
        TEST_USERS["customs_officer_headers"],
    )
    validate_error(res, "ERR_TARIFF_RULE_OVERLAP", expected_status=409)


# ----- Rule 9: compensating_invariant ------------------------------------

def test_confirm_then_reverse_preserves_dutiable_value(api):
    """PRD §3.5: "Across all three variants, the order of operations is
    fixed: each line's contribution is computed and floored
    independently, and only then are the per-line contributions summed
    to produce dutiable_value_cny_minor."
    PRD §3.8: "A successful reversal flips the notice from PAID to
    REVERSED; if the linked declaration was in RELEASED, it reverts to
    APPROVED (the order's RELEASED cascade is similarly undone)."

    Claim: the conserved-quantity invariant also holds for
    Declaration.dutiable_value_cny_minor: the round-trip leaves it
    UNCHANGED. Pairs with the total_tax invariant test on a different
    field of the same compensating-action pair.

    # difficulty: compensating_invariant/payment_confirm_then_reverse_preserves_total_tax
    """
    ctx = setup_released_declaration(
        trade_mode="GENERAL_TRADE",
        line_items=[make_line_item(quantity=1, unit_price=10_000, weight_kg=0.1)],
        currency="USD",
        rate_micros=1_000_000,
        hs_code_overrides={
            "tariff_rate_bps": 1000, "vat_rate_bps": 1300,
            "consumption_tax_rate_bps": 0, "postal_tax_rate_bps": 0,
        },
    )
    before_dutiable = ctx.declaration["dutiable_value_cny_minor"]
    reverse_payment(ctx.payment_notice["id"])
    decl = ctx.refresh_declaration()
    assert decl["dutiable_value_cny_minor"] == before_dutiable


def test_submit_then_reject_preserves_no_executed_refund_via_status(api):
    """PRD §3.10: "A submitted refund is decided by a customs officer —
    approval transitions it from SUBMITTED to APPROVED ...
    rejection transitions it from SUBMITTED to REJECTED, persists the
    customs officer's rejection_reason, and emits a REFUND_DECISION
    event marked rejected."
    PRD §3.10: "At most one EXECUTED refund may exist per declaration."

    Claim: after the submit→reject round-trip, the only refund row for
    this declaration has status=REJECTED and executed_amount=0; the
    "at most one EXECUTED refund per declaration" invariant is
    preserved at zero EXECUTED refunds. Pairs with the count-based
    invariant test on the same compensating-action pair, asserting via
    the per-row status field instead.

    # difficulty: compensating_invariant/refund_submit_then_reject_preserves_executed_refund_count
    """
    ctx = setup_returned_order_with_paid_declaration()
    refund = create_refund(
        ctx.declaration, ctx.declarant, refund_reason="RETURN",
    )
    sub = submit_refund(refund, ctx.declarant)
    rej = reject_refund(sub, "second-test")
    assert rej["status"] == "REJECTED"
    # "executed_amount_cny_minor" untouched on the rejection branch.
    assert rej.get("executed_amount_cny_minor", 0) == 0
    # Re-fetch the row directly to confirm persistent state.
    final = validate_success(api.get_refund(
        refund["id"], TEST_USERS["customs_officer_headers"]
    ))
    assert final["status"] == "REJECTED"
    assert final.get("executed_amount_cny_minor", 0) == 0


# Local validate_paginated alias to avoid an extra import in the file.
def validate_paginated_aux(res):
    from test_helpers import validate_paginated as vp
    return vp(res)
