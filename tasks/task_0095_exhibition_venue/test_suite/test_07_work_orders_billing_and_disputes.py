"""Work order billing, branching dispute path, and validations —
PRD §3.6.

Covers:
- per-line rounding precedes aggregation (Rule 2 instance 2 boundary)
- 6% tax round-half-up
- the EXECUTED → BILLED vs EXECUTED → DISPUTED → RESOLVED branching
  state machine (Rule 3 instance 2)
- ERR_DISPUTE_RESOLUTION_INVALID on out-of-band resolved_total_cents
- ERR_INVALID_INPUT on non-positive line shape
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    create_draft_work_order,
    create_work_order_payload,
    dispute_work_order_payload,
    iso_offset,
    make_exhibitor_headers,
    progress_work_order_to_executed,
    resolve_work_order_payload,
    setup_executed_work_order,
    setup_exhibition_in_setup_with_confirmed_allocation,
    submit_work_order,
    validate_error,
    validate_success,
    work_order_line,
)


# ===========================================================================
# Per-line rounding precedes aggregation (PRD §3.6)
# ===========================================================================
class TestWorkOrderBillingPinnedOrdering:
    # difficulty: combinatorial_formula/work_order_per_line_then_sum_rounding

    def test_three_cleaning_lines_per_line_round_then_sum(
        self, api, venue_admin_headers,
    ):
        """PRD §3.6: "For each line, multiply unit_price_cents by
        quantity to obtain an exact integer line gross; if the line's
        service_code equals CLEANING, multiply the line gross by
        ninety-five hundredths (a five percent per-line discount
        applied before rounding); for every other service code use the
        line gross unchanged; then round the per-line amount half-up
        to integer cents. Sum the per-line rounded amounts to produce
        subtotal_cents."
        PRD §3.6: "Compute tax_cents as subtotal_cents multiplied by
        six hundredths and rounded half-up to integer cents. Compute
        total_cents as the integer sum of subtotal_cents and tax_cents."

        Claim: three CLEANING lines each (qty=1, unit_price_cents=111)
        produce subtotal=315 (per-line round(111*0.95)=105, x3),
        tax=19 (round_half_up(315*0.06)=round(18.9)=19), total=334.
        """
        # difficulty: combinatorial_formula/work_order_per_line_then_sum_rounding
        ctx = setup_exhibition_in_setup_with_confirmed_allocation()
        wo = create_draft_work_order(
            exhibition_id=ctx["exhibition"]["id"],
            allocation_id=ctx["allocation"]["id"],
            exhibitor_id=ctx["exhibitor_id"],
            lines=[
                work_order_line(
                    service_code="CLEANING", quantity=1, unit_price_cents=111,
                ),
                work_order_line(
                    service_code="CLEANING", quantity=1, unit_price_cents=111,
                ),
                work_order_line(
                    service_code="CLEANING", quantity=1, unit_price_cents=111,
                ),
            ],
        )
        wo = submit_work_order(wo["id"], ctx["exhibitor_id"])
        assert wo["subtotal_cents"] == 315, (
            f"per-line rounding rule pins subtotal at 315 (105*3), "
            f"not 316 (sum-then-round); got {wo['subtotal_cents']}"
        )
        assert wo["tax_cents"] == 19
        assert wo["total_cents"] == 334

    def test_non_cleaning_line_no_discount(
        self, api, venue_admin_headers,
    ):
        """PRD §3.6: "for every other service code use the line gross
        unchanged."

        Claim: one FURNITURE line qty=1 unit_price=10000 produces
        subtotal=10000, tax=600, total=10600.
        """
        ctx = setup_exhibition_in_setup_with_confirmed_allocation()
        wo = create_draft_work_order(
            exhibition_id=ctx["exhibition"]["id"],
            allocation_id=ctx["allocation"]["id"],
            exhibitor_id=ctx["exhibitor_id"],
            lines=[work_order_line(
                service_code="FURNITURE", quantity=1, unit_price_cents=10000,
            )],
        )
        wo = submit_work_order(wo["id"], ctx["exhibitor_id"])
        assert wo["subtotal_cents"] == 10000
        assert wo["tax_cents"] == 600
        assert wo["total_cents"] == 10600

    def test_cleaning_with_non_cleaning_lines_per_line_rounding_still_applies(
        self, api, venue_admin_headers,
    ):
        """PRD §3.6: "For each line, multiply unit_price_cents by
        quantity to obtain an exact integer line gross; if the line's
        service_code equals CLEANING, multiply the line gross by
        ninety-five hundredths ... for every other service code use
        the line gross unchanged; then round the per-line amount
        half-up to integer cents. Sum the per-line rounded amounts to
        produce subtotal_cents."

        Claim: mixed lines — two CLEANING qty=1 unit=111 plus one
        FURNITURE qty=1 unit=500 — produce subtotal =
        round(111*0.95)+round(111*0.95)+500 = 105+105+500 = 710.
        """
        # difficulty: combinatorial_formula/work_order_per_line_then_sum_rounding
        ctx = setup_exhibition_in_setup_with_confirmed_allocation()
        wo = create_draft_work_order(
            exhibition_id=ctx["exhibition"]["id"],
            allocation_id=ctx["allocation"]["id"],
            exhibitor_id=ctx["exhibitor_id"],
            lines=[
                work_order_line(
                    service_code="CLEANING", quantity=1, unit_price_cents=111,
                ),
                work_order_line(
                    service_code="CLEANING", quantity=1, unit_price_cents=111,
                ),
                work_order_line(
                    service_code="FURNITURE",
                    quantity=1, unit_price_cents=500,
                ),
            ],
        )
        wo = submit_work_order(wo["id"], ctx["exhibitor_id"])
        assert wo["subtotal_cents"] == 710, (
            f"expected subtotal=710 (per-line rounded); got "
            f"{wo['subtotal_cents']}"
        )


# ===========================================================================
# Validation: empty / non-positive lines (PRD §3.6)
# ===========================================================================
class TestWorkOrderInputValidation:

    def test_empty_lines_array_rejected(
        self, api, venue_admin_headers,
    ):
        """PRD §3.6: "the system requires that ... the lines array is
        non-empty — failures of those input shapes surface as
        ERR_INVALID_INPUT."

        Claim: submit with lines=[] → ERR_INVALID_INPUT.
        """
        ctx = setup_exhibition_in_setup_with_confirmed_allocation()
        # We need create_work_order to accept an empty lines array
        # at creation time — if the API rejects on create, that's also
        # fine, since it's a constraint either way; we test submit.
        wo_res = api.create_work_order(
            create_work_order_payload(
                exhibition_id=ctx["exhibition"]["id"],
                allocation_id=ctx["allocation"]["id"],
                lines=[],
            ),
            make_exhibitor_headers(ctx["exhibitor_id"]),
        )
        # Either creation or submission must reject with
        # ERR_INVALID_INPUT — PRD attaches the rule to /submit. We try
        # /submit if creation succeeded, otherwise observe rejection
        # on /work-orders.
        if wo_res.status_code in (200, 201):
            wo = wo_res.json()["data"]
            res = api.submit_work_order(
                wo["id"], make_exhibitor_headers(ctx["exhibitor_id"]),
            )
            validate_error(res, ApiErrorId.ERR_INVALID_INPUT.value)
        else:
            validate_error(wo_res, ApiErrorId.ERR_INVALID_INPUT.value)

    def test_zero_quantity_line_rejected_on_submit(
        self, api, venue_admin_headers,
    ):
        """PRD §3.6: "the system requires that ... every line has a
        strictly positive quantity and a strictly positive
        unit_price_cents."

        Claim: submitting a work order with a quantity=0 line →
        ERR_INVALID_INPUT.
        """
        ctx = setup_exhibition_in_setup_with_confirmed_allocation()
        wo = create_draft_work_order(
            exhibition_id=ctx["exhibition"]["id"],
            allocation_id=ctx["allocation"]["id"],
            exhibitor_id=ctx["exhibitor_id"],
            lines=[work_order_line(
                service_code="FURNITURE", quantity=0, unit_price_cents=10000,
            )],
        )
        res = api.submit_work_order(
            wo["id"], make_exhibitor_headers(ctx["exhibitor_id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_INPUT.value)

    def test_zero_unit_price_rejected_on_submit(
        self, api, venue_admin_headers,
    ):
        """PRD §3.6: "the system requires that ... every line has a
        strictly positive quantity and a strictly positive
        unit_price_cents."

        Claim: submitting a work order with unit_price_cents=0 →
        ERR_INVALID_INPUT.
        """
        ctx = setup_exhibition_in_setup_with_confirmed_allocation()
        wo = create_draft_work_order(
            exhibition_id=ctx["exhibition"]["id"],
            allocation_id=ctx["allocation"]["id"],
            exhibitor_id=ctx["exhibitor_id"],
            lines=[work_order_line(
                service_code="FURNITURE", quantity=1, unit_price_cents=0,
            )],
        )
        res = api.submit_work_order(
            wo["id"], make_exhibitor_headers(ctx["exhibitor_id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_INPUT.value)


# ===========================================================================
# EXECUTED → BILLED vs EXECUTED → DISPUTED → RESOLVED (PRD §3.6)
# ===========================================================================
class TestExecutedBranchingStateMachine:
    # difficulty: non_linear_state_machine/work_order_dispute_branch

    def test_bill_path_refreshes_resolved_total_to_total(
        self, api, venue_admin_headers, venue_ops_headers,
    ):
        """PRD §3.6: "operations bills it (moving it from EXECUTED to
        the terminal BILLED, refreshing resolved_total_cents to
        total_cents and emitting a payment-system sync event with
        total_cents)."

        Claim: a single FURNITURE qty=1 unit_price=10000 work order at
        EXECUTED → BILLED has resolved_total_cents == total_cents ==
        10600.
        """
        # difficulty: non_linear_state_machine/work_order_dispute_branch
        ctx = setup_executed_work_order(lines=[work_order_line(
            service_code="FURNITURE", quantity=1, unit_price_cents=10000,
        )])
        res = api.bill_work_order(
            ctx["work_order"]["id"], venue_ops_headers,
        )
        billed = validate_success(res, expected_status=200)
        assert billed["status"] == "BILLED"
        assert billed["total_cents"] == 10600
        assert billed["resolved_total_cents"] == 10600

    def test_dispute_path_resolves_with_concession(
        self, api, venue_admin_headers, venue_ops_headers,
    ):
        """PRD §3.6: "The exhibitor may instead dispute an executed
        work order by supplying a non-empty dispute_reason, moving it
        from EXECUTED to DISPUTED. Operations resolves a disputed
        work order by supplying a resolved_total_cents value that
        must be greater than or equal to zero and less than or equal
        to the pinned total_cents."

        Claim: EXECUTED → DISPUTED → RESOLVED yields status='RESOLVED'
        and resolved_total_cents == 6000 (< total_cents 10600).
        """
        # difficulty: non_linear_state_machine/work_order_dispute_branch
        ctx = setup_executed_work_order(lines=[work_order_line(
            service_code="FURNITURE", quantity=1, unit_price_cents=10000,
        )])
        # Dispute.
        api.dispute_work_order(
            ctx["work_order"]["id"],
            dispute_work_order_payload(dispute_reason="Wrong color"),
            make_exhibitor_headers(ctx["exhibitor_id"]),
        )
        # Resolve with concession.
        res = api.resolve_work_order(
            ctx["work_order"]["id"],
            resolve_work_order_payload(resolved_total_cents=6000),
            venue_ops_headers,
        )
        resolved = validate_success(res, expected_status=200)
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolved_total_cents"] == 6000
        assert resolved["total_cents"] == 10600

    def test_resolve_out_of_band_rejected(
        self, api, venue_admin_headers, venue_ops_headers,
    ):
        """PRD §3.6: "an out-of-band value surfaces as
        ERR_DISPUTE_RESOLUTION_INVALID."

        Claim: resolve with resolved_total_cents > total_cents →
        ERR_DISPUTE_RESOLUTION_INVALID.
        """
        ctx = setup_executed_work_order(lines=[work_order_line(
            service_code="FURNITURE", quantity=1, unit_price_cents=10000,
        )])
        api.dispute_work_order(
            ctx["work_order"]["id"],
            dispute_work_order_payload(dispute_reason="X"),
            make_exhibitor_headers(ctx["exhibitor_id"]),
        )
        res = api.resolve_work_order(
            ctx["work_order"]["id"],
            resolve_work_order_payload(resolved_total_cents=99999999),
            venue_ops_headers,
        )
        validate_error(res, ApiErrorId.ERR_DISPUTE_RESOLUTION_INVALID.value)

    def test_resolve_negative_rejected(
        self, api, venue_admin_headers, venue_ops_headers,
    ):
        """PRD §3.6: "a resolved_total_cents value that must be greater
        than or equal to zero and less than or equal to the pinned
        total_cents; an out-of-band value surfaces as
        ERR_DISPUTE_RESOLUTION_INVALID."

        Claim: resolve with resolved_total_cents < 0 →
        ERR_DISPUTE_RESOLUTION_INVALID.
        """
        ctx = setup_executed_work_order(lines=[work_order_line(
            service_code="FURNITURE", quantity=1, unit_price_cents=10000,
        )])
        api.dispute_work_order(
            ctx["work_order"]["id"],
            dispute_work_order_payload(dispute_reason="X"),
            make_exhibitor_headers(ctx["exhibitor_id"]),
        )
        res = api.resolve_work_order(
            ctx["work_order"]["id"],
            resolve_work_order_payload(resolved_total_cents=-1),
            venue_ops_headers,
        )
        validate_error(res, ApiErrorId.ERR_DISPUTE_RESOLUTION_INVALID.value)


# ===========================================================================
# Utility load constraint (PRD §3.6)
# ===========================================================================
class TestUtilityCapacityExceeded:

    def test_extra_power_quantity_exceeding_booth_power_kw_rejected(
        self, api, venue_admin_headers,
    ):
        """PRD §3.6: "The work order also enforces a utility-load
        constraint at submit time: the sum of quantity across lines
        whose service_code is EXTRA_POWER (interpreted in kilowatts)
        on this booth must not exceed the booth's power_kw_capacity;
        an exceedance surfaces as ERR_UTILITY_CAPACITY_EXCEEDED."

        Claim: a single-cell booth has power_kw_capacity == 2.0 (per
        the active plan default 2.0 kW/cell). A work order with
        EXTRA_POWER quantity=5 (i.e. 5 kW > 2.0 kW) →
        ERR_UTILITY_CAPACITY_EXCEEDED.
        """
        ctx = setup_exhibition_in_setup_with_confirmed_allocation()
        # Booth was created with one cell — power_kw_capacity == 2.0.
        wo = create_draft_work_order(
            exhibition_id=ctx["exhibition"]["id"],
            allocation_id=ctx["allocation"]["id"],
            exhibitor_id=ctx["exhibitor_id"],
            lines=[work_order_line(
                service_code="EXTRA_POWER", quantity=5,
                unit_price_cents=1000,
            )],
        )
        res = api.submit_work_order(
            wo["id"], make_exhibitor_headers(ctx["exhibitor_id"]),
        )
        validate_error(res, ApiErrorId.ERR_UTILITY_CAPACITY_EXCEEDED.value)
