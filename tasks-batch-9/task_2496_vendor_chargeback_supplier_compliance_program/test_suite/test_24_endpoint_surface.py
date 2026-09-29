"""The endpoint surface: what each declared operation answers with, and what it
leaves behind on the rows it touches.
"""
from datetime import datetime

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    REQ_LBL_01,
    ApiErrorId,
    add_requirement,
    allocation_payload,
    apply_cash,
    assess_violation,
    cap_close_payload,
    cap_escalation_payload,
    create_deduction,
    create_guide,
    create_po,
    create_scorecard,
    create_shipment,
    create_vendor,
    decide_cap,
    file_violation,
    finalize_scorecard,
    first_cap_for_scorecard,
    make_vendor_headers,
    measure_scorecard,
    publish_guide,
    purchase_order_payload,
    read_allocation,
    read_cap,
    read_deduction,
    read_vendor,
    receive_shipment,
    set_clock,
    setup_assessed_chargeback,
    submit_cap,
    validate_error,
    validate_paginated,
    validate_success,
    vendor_payload,
)

PROGRAMME_START = "2026-08-01T00:00:00Z"


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an instant for comparison."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _probation_supplier_with_a_level_two_plan() -> dict:
    """A supplier carrying one open corrective action plan at escalation level 2.

    Two orders share the 2026-07-20 deadline; one arrives complete and one
    arrives half short, and the short arrival also produces one TIER_1
    chargeback inside the repeat lookback.  The July period therefore measures
    on_time_pct 100.00, otif_pct 50.00 and fill_rate_pct 75.00, so the
    composite is 60.00 and finalization issues a plan.
    """
    set_clock("2026-06-01T00:00:00Z")
    vendor = create_vendor()
    guide = create_guide(effective_from="2026-06-05T00:00:00Z")
    requirement = add_requirement(guide["id"], REQ_LBL_01, min_evidence_count=0)
    publish_guide(guide["id"])

    order_window = {
        "ordered_units": 1000,
        "unit_cost_cents": 500,
        "ship_window_start": "2026-07-10T00:00:00Z",
        "ship_window_end": "2026-07-17T00:00:00Z",
        "must_arrive_by": "2026-07-20T00:00:00Z",
    }
    po_full = create_po(vendor["id"], po_number="PO-FULL", **order_window)
    po_short = create_po(vendor["id"], po_number="PO-SHORT", **order_window)
    shipment_full = create_shipment(
        po_full["id"], vendor["id"], asn_number="ASN-FULL", shipped_units=1000,
        carton_count=40,
    )
    shipment_short = create_shipment(
        po_short["id"], vendor["id"], asn_number="ASN-SHORT", shipped_units=1000,
        carton_count=40,
    )

    set_clock("2026-07-19T00:00:00Z")
    receive_shipment(shipment_full["id"], 1000)
    receive_shipment(shipment_short["id"], 500)
    violation = file_violation(
        shipment_short["id"],
        requirement["id"],
        affected_units=100,
        affected_cartons=4,
        narrative="Unreadable labels.",
    )
    assess_violation(
        violation["id"],
        assessment_note="TIER_1 assessment inside the lookback window.",
    )

    set_clock("2026-09-05T00:00:00Z")
    scorecard = create_scorecard(
        vendor["id"],
        period_code="2026-07",
        period_start="2026-07-01T00:00:00Z",
        period_end="2026-07-31T00:00:00Z",
    )
    measure_scorecard(scorecard["id"], "ORDER_WEIGHTED")
    set_clock("2026-09-06T00:00:00Z")
    scorecard = finalize_scorecard(scorecard["id"])
    return {
        "vendor": vendor,
        "scorecard": scorecard,
        "cap": first_cap_for_scorecard(scorecard["id"]),
    }


def test_clock_capability_answers_with_the_instant_it_installs(api, officer_headers):
    """PRD §2.5: "A `ComplianceOfficer` may move the clock with a test-driving
    capability that accepts a single field, `to_iso8601`, carrying the instant to
    move to, and answers with the resulting `current_utc`."
    PRD §2.5: "Every timestamp the server stamps — `created_at`, `updated_at`,
    `published_at`, `arrived_at`, `detected_at`, `captured_at`, `assessed_at`,
    `submitted_at`, `decided_at`, `measured_at`, `finalized_at`, `issued_at`,
    `escalated_at`, `closed_at`, `posted_at`, `reversed_at` and `applied_at` —
    reads that clock, and every window comparison in the programme (the violation
    filing window, the dispute window, guide effectivity, scorecard periods,
    corrective-action due dates and the grace and repeat lookbacks) is evaluated
    against it."

    Design: Corner/endpoints/corner_clock_endpoint_returns_its_inline_output_schema
    """
    set_clock(PROGRAMME_START)

    moved = validate_success(api.set_clock("2026-08-15T00:00:00Z", officer_headers), 200)
    assert _instant(moved["current_utc"]) == _instant("2026-08-15T00:00:00Z"), (
        f"current_utc should echo the installed instant, got {moved['current_utc']!r}"
    )

    vendor = validate_success(
        api.create_vendor(vendor_payload(legal_name="Clockwise Cartons"), officer_headers),
        201,
    )
    assert _instant(vendor["created_at"]) == _instant("2026-08-15T00:00:00Z"), (
        f"created_at should read the moved clock, got {vendor['created_at']!r}"
    )
    assert _instant(vendor["updated_at"]) == _instant("2026-08-15T00:00:00Z"), (
        f"updated_at should read the moved clock, got {vendor['updated_at']!r}"
    )


def test_allocation_write_resolves_both_ends_of_the_recovery_link(
    api, accountant_headers
):
    """PRD §2.7: "Path existence — every identifier embedded in the URL resolves,
    checked left to right as described in §2.8; otherwise the not-found error for
    the first unresolved segment, at 404."
    PRD §2.7: "Body reference existence — every foreign key supplied in the
    request body resolves. This rung guards purchase-order creation
    (`vendor_id`), violation filing (`requirement_id`), scorecard creation
    (`vendor_id`), deduction creation (`vendor_id`) and deduction allocation
    (`chargeback_id`), answering with `ERR_VENDOR_NOT_FOUND`,
    `ERR_REQUIREMENT_NOT_FOUND` or `ERR_CHARGEBACK_NOT_FOUND` at 404."
    PRD §3.9: "The deduction opens in `DRAFT` with `amount_cents` 0,
    `allocation_count` 0, `over_allocated_cents` 0, and `posted_at`,
    `posted_by_user_id`, `reversed_at` and `reversal_reason` all null; creating it
    increments the supplier's `version` by one, which is exactly why a client
    drafting a second deduction must re-read the supplier first."
    PRD §3.9: "A new allocation is stored with `source_type` `DEDUCTION`,
    `effective_status` `PENDING`, `remittance_reference` null, `applied_at` null
    and `applied_by_user_id` from the acting accountant, and it raises the
    deduction's `amount_cents` by the allocated amount and its `allocation_count`
    by one."

    Design: Corner/endpoints/corner_allocation_link_requires_both_sides_to_exist
    """
    set_clock(PROGRAMME_START)
    vendor = create_vendor(legal_name="Danglinglink Distributors")
    deduction = create_deduction(vendor["id"], invoice_reference="INV-LINK")

    unknown_chargeback = api.create_allocation(
        deduction["id"], allocation_payload(NON_EXISTENT_UUID, 1000), accountant_headers
    )
    validate_error(unknown_chargeback, ApiErrorId.ERR_CHARGEBACK_NOT_FOUND.value, 404)

    unknown_deduction = api.create_allocation(
        NON_EXISTENT_UUID, allocation_payload(NON_EXISTENT_UUID, 1000), accountant_headers
    )
    validate_error(unknown_deduction, ApiErrorId.ERR_DEDUCTION_NOT_FOUND.value, 404)

    after = read_deduction(deduction["id"])
    assert after["allocation_count"] == 0, (
        f"a refused allocation must not be counted, got {after['allocation_count']}"
    )
    assert after["amount_cents"] == 0, (
        f"a refused allocation must not raise amount_cents, got {after['amount_cents']}"
    )
    assert after["status"] == "DRAFT", f"deduction should still be DRAFT, got {after['status']}"

    _, meta = validate_paginated(
        api.list_allocations(accountant_headers, params={"deduction_id": deduction["id"]})
    )
    assert meta["total_count"] == 0, (
        f"no allocation row should exist, got total_count {meta['total_count']}"
    )


def test_chargeback_read_reflects_the_partial_settlement_derivation(api):
    """PRD §3.3: "On success the shipment advances `IN_TRANSIT → RECEIVED`, stores
    the counted `received_units`, stamps `arrived_at` with the current logical
    clock, and computes `invoice_value_cents` as the counted `received_units`
    multiplied by the owning order's `unit_cost_cents`."
    PRD §3.5: "The flat component, `fixed_fee_cents`, is copied straight from the
    pinned requirement's `fixed_fee_cents`. A unit-recovery amount is formed by
    multiplying the requirement's `per_unit_recovery_cents` by the violation's
    `affected_units`. A handling-recovery amount is formed by multiplying the
    shipment's `invoice_value_cents` by the requirement's `handling_pct`, dividing
    by 100, and rounding the result half up to a whole number of cents before it
    is used anywhere."
    PRD §3.5: "For a `TIER_1` requirement, `cost_recovery_cents` is the
    unit-recovery amount plus the handling-recovery amount — both components are
    charged."
    PRD §3.5: "Otherwise the variant is `STANDARD` — which is always the case for
    a `TIER_1` requirement, and is also the case for a `TIER_2` or `TIER_3`
    requirement once a matching prior chargeback exists inside that 180-day
    lookback. Under `STANDARD`, `cost_recovery_cents` keeps the value the
    severity-tier branch produced, the raw amount is the flat fee plus that cost
    recovery, the requirement's `min_fee_cents` is applied as a floor to the raw
    amount, and the requirement's `cap_cents` is applied as a ceiling to the
    floored result; `gross_assessed_cents` is that floored-then-capped figure."
    PRD §3.9: "Its net assessed balance is `gross_assessed_cents` less
    `reversal_cents`; its `recovered_cents` is the sum of `allocated_cents` over
    its allocations whose `effective_status` is `EFFECTIVE`, with pending
    allocations under a draft deduction and reversed allocations under a reversed
    deduction both contributing nothing; its `outstanding_cents` is the net
    assessed balance less `recovered_cents`, floored at 0 so it never reads
    negative; and its `deduction_posted` is true exactly when at least one of its
    allocations has `source_type` `DEDUCTION` and belongs to a deduction whose
    `status` is `POSTED`, a flag that is independent of the settlement dimension."
    PRD §3.9: "The `settlement_status` is then chosen by the first matching branch
    of four, tested in this order: the chargeback is `WRITTEN_OFF` when the net
    assessed balance is zero or below; otherwise `RECOVERED` when
    `recovered_cents` has reached or exceeded the net assessed balance; otherwise
    `PARTIALLY_RECOVERED` when `recovered_cents` is above zero; otherwise
    `ASSESSED`."
    PRD §3.9: "The application creates an allocation with `source_type` `CASH`,
    `deduction_id` null, `effective_status` `EFFECTIVE` and `applied_at` stamped
    from the logical clock at creation, storing the applied amount in the
    allocation's `allocated_cents` field and the supplied reference in
    `remittance_reference`."
    PRD §3.9: "`open_chargeback_cents` is the sum, over the supplier's
    chargebacks whose `settlement_status` is `ASSESSED` or `PARTIALLY_RECOVERED`
    only, of `gross_assessed_cents` less `reversal_cents` less `recovered_cents`;
    chargebacks that are `RECOVERED` or `WRITTEN_OFF` are excluded from this
    figure entirely."
    PRD §3.9: "`recovered_lifetime_cents` is the sum of `allocated_cents` over
    every allocation on any of the supplier's chargebacks whose `effective_status`
    is `EFFECTIVE`, with no filter on the chargeback's settlement state."

    Design: Corner/endpoints/corner_chargeback_read_reflects_partial_settlement_derivation
    """
    world = setup_assessed_chargeback(
        REQ_LBL_01,
        ("PHOTO", "SCAN"),
        affected_units=100,
        affected_cartons=4,
        narrative="Unreadable labels.",
    )
    chargeback_id = world["chargeback"]["id"]
    allocation = apply_cash(chargeback_id, 10_000, remittance_reference="WIRE-7001")

    read_back = validate_success(
        api.get_chargeback(chargeback_id, make_vendor_headers(world["vendor"]["id"])), 200
    )
    assert read_back["gross_assessed_cents"] == 38_000, (
        f"gross_assessed_cents should be 38000, got {read_back['gross_assessed_cents']}"
    )
    assert read_back["reversal_cents"] == 0
    assert read_back["recovered_cents"] == 10_000, (
        f"recovered_cents should be 10000, got {read_back['recovered_cents']}"
    )
    assert read_back["outstanding_cents"] == 28_000, (
        f"outstanding_cents should be 38000 - 0 - 10000 = 28000, "
        f"got {read_back['outstanding_cents']}"
    )
    assert read_back["settlement_status"] == "PARTIALLY_RECOVERED"
    assert read_back["dispute_status"] == "NONE"
    assert read_back["deduction_posted"] is False, (
        "the cash channel never touches a deduction, so deduction_posted stays false"
    )

    assert read_allocation(allocation["id"])["effective_status"] == "EFFECTIVE"

    vendor = read_vendor(world["vendor"]["id"])
    assert vendor["open_chargeback_cents"] == 28_000, (
        f"open exposure should be 28000, got {vendor['open_chargeback_cents']}"
    )
    assert vendor["recovered_lifetime_cents"] == 10_000, (
        f"lifetime recovery should be 10000, got {vendor['recovered_lifetime_cents']}"
    )


def test_closing_the_only_open_plan_returns_the_supplier_to_active(api, officer_headers):
    """PRD §3.8: "A submission takes the plan `ISSUED → VENDOR_SUBMITTED` on the
    first attempt or `REJECTED → VENDOR_SUBMITTED` on the rework attempt, stores
    the supplied `milestone_text` and `committed_completion_at`, raises
    `submission_round` by one and increments the plan's `version`."
    PRD §3.8: "A `SUCCESS` outcome takes the plan `ACCEPTED → CLOSED_SUCCESS` or
    `ESCALATED → CLOSED_SUCCESS`, stamps `closed_at` and `closure_note`,
    recomputes the supplier's `open_cap_count`, and restores sourcing posture: a
    plan that had been escalated with a `SOURCING_HOLD` buying decision returns
    the supplier `SOURCING_HOLD → PROBATION` as a compensating restoration, and an
    accepted plan that was the supplier's only open plan returns the supplier
    `PROBATION → ACTIVE` with `open_cap_count` falling to 0."
    PRD §3.1: "`open_cap_count` is the number of corrective action plans for this
    supplier whose `status` is one of `ISSUED`, `VENDOR_SUBMITTED`, `REJECTED`,
    `ACCEPTED` or `ESCALATED`."
    PRD §3.7: "The second, caused by the first, copies `composite_score` into the
    supplier's `otif_score` and writes the supplier's `repeat_offender_flag` from
    the repeat-offender determination."
    PRD §3.7: "The composite is 0.60 multiplied by `otif_pct` plus 0.40
    multiplied by `fill_rate_pct`, rounded half up to two decimals — on-time-in-full
    performance carries three fifths of the weight and raw fill rate the remaining
    two fifths."
    PRD §3.8: "The supplier is flagged as a repeat offender when the
    charged-violation count has reached 3 or more, **or** when at least one
    `TIER_1` chargeback sits in the window and the period's `composite_score` is
    strictly below 90.00."

    Design: Corner/endpoints/corner_cap_close_action_returns_the_vendor_to_active
    """
    world = _probation_supplier_with_a_level_two_plan()
    vendor_id = world["vendor"]["id"]
    cap_id = world["cap"]["id"]

    submit_cap(
        cap_id,
        vendor_id,
        milestone_text="Relabel all cases at origin; weekly audit reports.",
        committed_completion_at="2026-09-20T00:00:00Z",
    )
    decide_cap(cap_id, "ACCEPT", review_note="Plan is adequate.")

    before_plan = read_cap(cap_id)
    before_vendor = read_vendor(vendor_id)
    assert before_plan["status"] == "ACCEPTED", (
        f"the plan should be ACCEPTED before closure, got {before_plan['status']}"
    )
    assert before_vendor["status"] == "PROBATION", (
        f"the supplier should be on PROBATION before closure, got {before_vendor['status']}"
    )
    assert before_vendor["open_cap_count"] == 1

    set_clock("2026-09-21T00:00:00Z")
    closed = validate_success(
        api.close_cap(
            cap_id,
            cap_close_payload("SUCCESS", closure_note="Remediation verified at the DC."),
            officer_headers,
        ),
        200,
    )
    assert closed["status"] == "CLOSED_SUCCESS", (
        f"a SUCCESS outcome should close the plan, got {closed['status']}"
    )
    assert _instant(closed["closed_at"]) == _instant("2026-09-21T00:00:00Z"), (
        f"closed_at should read the logical clock, got {closed['closed_at']!r}"
    )
    assert closed["closure_note"] == "Remediation verified at the DC."
    assert closed["submission_round"] == 1, (
        f"one submission was made, got submission_round {closed['submission_round']}"
    )

    after = read_vendor(vendor_id)
    assert after["status"] == "ACTIVE", (
        f"closing the only open plan should restore ACTIVE, got {after['status']}"
    )
    assert after["open_cap_count"] == 0, (
        f"open_cap_count should fall to 0, got {after['open_cap_count']}"
    )
    assert after["otif_score"] == pytest.approx(60.00, abs=0.01), (
        f"the finalized composite should stand at 60.00, got {after['otif_score']}"
    )
    assert after["repeat_offender_flag"] is True, (
        "the repeat-offender determination written at finalization must survive closure"
    )


def test_range_review_escalation_leaves_the_supplier_status_untouched(
    api, officer_headers, buyer_headers
):
    """PRD §3.8: "Escalation takes the plan `REJECTED → ESCALATED`, records the
    `buying_decision` and `escalation_note`, stamps `escalated_at`, increments the
    plan's `version`, and when the decision is `SOURCING_HOLD` moves the supplier
    `PROBATION → SOURCING_HOLD`, from which point new purchase orders against that
    supplier are refused with `ERR_VENDOR_SOURCING_HOLD`."
    PRD §3.8: "A `buying_decision` of `RANGE_REVIEW` is permitted at any
    escalation level and leaves the supplier's `status` untouched — the assortment
    is reconsidered but purchasing continues."
    PRD §3.8: "The `escalation_level` is one plus the number of prior
    unremediated plans in the window, plus one more when the period's
    `composite_score` is strictly below 80.00, and the whole sum is capped at 3."
    PRD §3.1: "`open_cap_count` is the number of corrective action plans for this
    supplier whose `status` is one of `ISSUED`, `VENDOR_SUBMITTED`, `REJECTED`,
    `ACCEPTED` or `ESCALATED`."
    PRD §3.3: "A new order is `OPEN`, with `received_units` 0 and
    `first_receipt_at` null."

    Design: Corner/endpoints/corner_range_review_escalation_leaves_vendor_status_untouched
    """
    world = _probation_supplier_with_a_level_two_plan()
    vendor_id = world["vendor"]["id"]
    cap_id = world["cap"]["id"]

    submit_cap(
        cap_id,
        vendor_id,
        milestone_text="We will look into it.",
        committed_completion_at="2026-09-20T00:00:00Z",
    )
    decide_cap(cap_id, "REJECT", review_note="No measurable milestones.")

    set_clock("2026-09-10T00:00:00Z")
    escalated = validate_success(
        api.escalate_cap(
            cap_id,
            cap_escalation_payload(
                "RANGE_REVIEW", escalation_note="Refer to the category range review."
            ),
            buyer_headers,
        ),
        200,
    )
    assert escalated["status"] == "ESCALATED", (
        f"the plan should move REJECTED to ESCALATED, got {escalated['status']}"
    )
    assert escalated["buying_decision"] == "RANGE_REVIEW"
    assert _instant(escalated["escalated_at"]) == _instant("2026-09-10T00:00:00Z"), (
        f"escalated_at should read the logical clock, got {escalated['escalated_at']!r}"
    )
    assert escalated["escalation_level"] == 2, (
        f"a composite below 80.00 with no prior unremediated plan gives level 2, "
        f"got {escalated['escalation_level']}"
    )

    vendor = read_vendor(vendor_id)
    assert vendor["status"] == "PROBATION", (
        f"a RANGE_REVIEW escalation must leave the supplier on PROBATION, "
        f"got {vendor['status']}"
    )
    assert vendor["open_cap_count"] == 1, (
        f"an escalated plan is still open, got {vendor['open_cap_count']}"
    )

    later_order = validate_success(
        api.create_purchase_order(
            purchase_order_payload(
                vendor_id,
                po_number="PO-AFTER",
                ordered_units=100,
                unit_cost_cents=500,
                ship_window_start="2026-09-12T00:00:00Z",
                ship_window_end="2026-09-15T00:00:00Z",
                must_arrive_by="2026-09-18T00:00:00Z",
            ),
            buyer_headers,
        ),
        201,
    )
    assert later_order["status"] == "OPEN", (
        f"purchasing continues after a range review, got {later_order['status']}"
    )
