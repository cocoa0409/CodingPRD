"""Preconditions a write inherits from the state of a *different* resource.

Filing a finding depends on its shipment having been received; posting a
deduction depends on the dispute posture of the chargebacks it earmarks; raising
a purchase order depends on the supplier's sourcing posture, which is itself
driven by the scorecard and corrective-action pipeline.  In each case the payload
under test never changes — only the other resource's state does.
"""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    REQ_SHP_04,
    add_allocation,
    add_evidence,
    add_requirement,
    assess_violation,
    close_cap,
    create_deduction,
    create_guide,
    create_po,
    create_scorecard,
    create_shipment,
    create_vendor,
    decide_cap,
    decide_dispute,
    file_violation,
    finalize_scorecard,
    first_cap_for_scorecard,
    escalate_cap,
    measure_scorecard,
    open_dispute,
    publish_guide,
    purchase_order_payload,
    read_allocation,
    read_cap,
    read_chargeback,
    read_deduction,
    read_scorecard,
    read_shipment,
    read_vendor,
    receive_shipment,
    set_clock,
    setup_assessed_chargeback,
    setup_program,
    submit_cap,
    validate_error,
    validate_paginated,
    validate_success,
)

PROGRAMME_START = "2026-08-01T00:00:00Z"
RECEIPT_DAY = "2026-08-10T00:00:00Z"
GUIDE_EFFECTIVE = "2026-08-05T00:00:00Z"


def _instant(value: str) -> datetime:
    """Compare two ISO 8601 UTC instants without depending on their spelling."""
    assert value is not None, "expected a timestamp, got null"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _sourcing_hold_world():
    """A supplier driven all the way to `SOURCING_HOLD`.

    One short-shipped order measured into a failing period, finalized into a
    level-2 corrective action plan, submitted once, rejected, then escalated with
    a `SOURCING_HOLD` buying decision.
    """
    set_clock(PROGRAMME_START)
    vendor = create_vendor(
        vendor_code="V1303",
        legal_name="Sourcinghold Sundries",
        payment_terms_days=60,
    )
    guide = create_guide(
        guide_code="RG-2026-A",
        title="Domestic Routing Guide 2026-A",
        scope_code="ALL",
        effective_from=GUIDE_EFFECTIVE,
    )
    requirement = add_requirement(guide["id"], REQ_SHP_04)
    publish_guide(guide["id"])
    po = create_po(
        vendor["id"],
        po_number="PO-1",
        ordered_units=1000,
        unit_cost_cents=500,
        ship_window_start="2026-08-06T00:00:00Z",
        ship_window_end="2026-08-09T00:00:00Z",
        must_arrive_by="2026-08-10T00:00:00Z",
    )
    shipment = create_shipment(
        po["id"], vendor["id"], asn_number="ASN-1", shipped_units=500, carton_count=20
    )
    set_clock(RECEIPT_DAY)
    shipment = receive_shipment(shipment["id"], 500)
    violation = file_violation(
        shipment["id"],
        requirement["id"],
        affected_units=400,
        affected_cartons=16,
        narrative="ASN transmitted after trailer arrival on a short load.",
    )
    add_evidence(violation["id"], kind="DOCUMENT")
    add_evidence(violation["id"], kind="MEASUREMENT")
    chargeback = assess_violation(
        violation["id"], assessment_note="Late ASN on a short load."
    )

    set_clock("2026-09-06T00:00:00Z")
    scorecard = create_scorecard(
        vendor["id"],
        period_code="2026-08",
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-31T00:00:00Z",
    )
    measure_scorecard(scorecard["id"], "ORDER_WEIGHTED")
    scorecard = finalize_scorecard(scorecard["id"])
    cap = first_cap_for_scorecard(scorecard["id"])
    submit_cap(
        cap["id"],
        vendor["id"],
        milestone_text="Install an ASN gateway with automated pre-arrival transmission.",
        committed_completion_at="2026-09-20T00:00:00Z",
    )
    decide_cap(
        cap["id"],
        "REJECT",
        review_note="Milestone lacks a dated cutover and a fallback process.",
    )
    cap = escalate_cap(
        cap["id"],
        "SOURCING_HOLD",
        escalation_note=(
            "Category buyer places the vendor on sourcing hold pending a credible plan."
        ),
    )
    return {
        "vendor": vendor,
        "po": po,
        "shipment": shipment,
        "violation": violation,
        "chargeback": chargeback,
        "scorecard": scorecard,
        "cap": cap,
    }


def _second_order_payload(vendor_id: str) -> dict:
    return purchase_order_payload(
        vendor_id,
        po_number="PO-2",
        ordered_units=800,
        unit_cost_cents=500,
        ship_window_start="2026-09-10T00:00:00Z",
        ship_window_end="2026-09-14T00:00:00Z",
        must_arrive_by="2026-09-16T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# A finding may only be filed against a shipment that has been received
# ---------------------------------------------------------------------------
def test_violation_filing_refused_while_the_shipment_is_still_in_transit(
    api, inspector_headers, officer_headers
):
    """PRD §3.4: "The shipment must already be `RECEIVED`; a finding against a
    shipment still `IN_TRANSIT` is refused with `ERR_SHIPMENT_NOT_RECEIVED`,
    because there is no counted quantity and no arrival instant to reason about."
    PRD §3.4: "A newly filed violation records `detected_at` from the current
    logical clock and `detected_by_user_id` from the acting inspector's
    `X-User-ID`, takes its `shipment_id` from the path, pins the supplied
    `requirement_id`, starts with `evidence_count` 0 and `void_reason` null, and
    raises both the shipment's `open_violation_count` and the supplier's
    `open_violation_count` by one."

    Design: Difficulty/cross_entity_state_dependency/violation_creation_depends_on_shipment_receipt_state
    """
    world = setup_program(
        REQ_SHP_04,
        vendor_overrides={
            "vendor_code": "V1301",
            "legal_name": "Intransit Traders",
            "payment_terms_days": 60,
        },
        guide_overrides={
            "guide_code": "RG-2026-A",
            "title": "Domestic Routing Guide 2026-A",
        },
        receive=False,
    )
    shipment = world["shipment"]
    assert shipment["status"] == "IN_TRANSIT", (
        f"the shipment must still be IN_TRANSIT, got {shipment['status']}"
    )

    validate_error(
        api.create_violation(
            shipment["id"],
            {
                "requirement_id": world["requirement"]["id"],
                "affected_units": 400,
                "affected_cartons": 16,
                "narrative": "Filed before the trailer was checked in.",
            },
            inspector_headers,
        ),
        ApiErrorId.ERR_SHIPMENT_NOT_RECEIVED,
        409,
    )

    refused = read_shipment(shipment["id"])
    assert refused["open_violation_count"] == 0, (
        "a refused filing must not raise the shipment's open_violation_count, got "
        f"{refused['open_violation_count']}"
    )
    _, meta = validate_paginated(
        api.list_violations(officer_headers, params={"shipment_id": shipment["id"]})
    )
    assert meta["total_count"] == 0, (
        f"a refused filing must mint no violation row, got {meta['total_count']}"
    )


def test_violation_filing_accepted_once_the_shipment_has_been_received(
    api, inspector_headers
):
    """PRD §3.3: "On success the shipment advances `IN_TRANSIT → RECEIVED`, stores
    the counted `received_units`, stamps `arrived_at` with the current logical
    clock, and computes `invoice_value_cents` as the counted `received_units`
    multiplied by the owning order's `unit_cost_cents`."
    PRD §3.4: "Its initial state depends on the requirement it cites: when the
    pinned requirement's `min_evidence_count` is 0 the violation is born directly
    in `EVIDENCE_COMPLETE`, and otherwise it starts in `DETECTED`."
    PRD §3.4: "A newly filed violation records `detected_at` from the current
    logical clock and `detected_by_user_id` from the acting inspector's
    `X-User-ID`, takes its `shipment_id` from the path, pins the supplied
    `requirement_id`, starts with `evidence_count` 0 and `void_reason` null, and
    raises both the shipment's `open_violation_count` and the supplier's
    `open_violation_count` by one."

    Design: Difficulty/cross_entity_state_dependency/violation_creation_depends_on_shipment_receipt_state
    """
    world = setup_program(
        REQ_SHP_04,
        vendor_overrides={
            "vendor_code": "V1301",
            "legal_name": "Intransit Traders",
            "payment_terms_days": 60,
        },
        guide_overrides={
            "guide_code": "RG-2026-A",
            "title": "Domestic Routing Guide 2026-A",
        },
        receive=False,
    )
    shipment_id = world["shipment"]["id"]

    received = receive_shipment(shipment_id, 1000)
    assert received["status"] == "RECEIVED", (
        f"receipt must advance the shipment to RECEIVED, got {received['status']}"
    )
    assert received["invoice_value_cents"] == 500000, (
        "invoice_value_cents is the counted units times the order's unit cost, "
        f"expected 500000, got {received['invoice_value_cents']}"
    )

    violation = validate_success(
        api.create_violation(
            shipment_id,
            {
                "requirement_id": world["requirement"]["id"],
                "affected_units": 400,
                "affected_cartons": 16,
                "narrative": "Filed before the trailer was checked in.",
            },
            inspector_headers,
        ),
        201,
    )
    assert violation["status"] == "DETECTED", (
        "a requirement demanding two evidence items starts the finding in "
        f"DETECTED, got {violation['status']}"
    )
    assert violation["evidence_count"] == 0, (
        f"a fresh finding carries no evidence, got {violation['evidence_count']}"
    )

    after = read_shipment(shipment_id)
    assert after["open_violation_count"] == 1, (
        "filing raises the shipment's open_violation_count by one, got "
        f"{after['open_violation_count']}"
    )


# ---------------------------------------------------------------------------
# A deduction may only be posted while none of its chargebacks is under dispute
# ---------------------------------------------------------------------------
def _deduction_awaiting_a_dispute_decision():
    """One assessed chargeback of 425000, a DRAFT deduction earmarking 100000 of
    it, and a live dispute that freezes the document."""
    world = setup_assessed_chargeback(
        REQ_SHP_04,
        vendor_overrides={
            "vendor_code": "V1302",
            "legal_name": "Holdback Housewares",
            "payment_terms_days": 60,
        },
        guide_overrides={
            "guide_code": "RG-2026-A",
            "title": "Domestic Routing Guide 2026-A",
        },
    )
    deduction = create_deduction(world["vendor"]["id"], invoice_reference="INV-91")
    allocation = add_allocation(deduction["id"], world["chargeback"]["id"], 100_000)
    set_clock("2026-08-12T00:00:00Z")
    dispute = open_dispute(
        world["chargeback"]["id"],
        world["vendor"]["id"],
        reason_code="CARRIER_CAUSED",
        claimed_reversal_cents=100_000,
        narrative="Carrier detained the trailer at the yard.",
    )
    world["deduction"] = deduction
    world["allocation"] = allocation
    world["dispute"] = dispute
    return world


def test_deduction_posting_refused_while_an_allocated_chargeback_is_under_dispute(
    api, accountant_headers
):
    """PRD §3.9: "Every allocated chargeback must be free of a live dispute: each
    must have a `dispute_status` of `NONE`, `UPHELD` or `PARTIALLY_REVERSED`, and
    any chargeback whose `dispute_status` is `OPEN` freezes the whole document
    with `ERR_CHARGEBACK_DISPUTE_OPEN`."
    PRD §3.9: "A new allocation is stored with `source_type` `DEDUCTION`,
    `effective_status` `PENDING`, `remittance_reference` null, `applied_at` null
    and `applied_by_user_id` from the acting accountant, and it raises the
    deduction's `amount_cents` by the allocated amount and its `allocation_count`
    by one."

    Design: Difficulty/cross_entity_state_dependency/deduction_posting_depends_on_allocated_chargeback_dispute_state
    """
    world = _deduction_awaiting_a_dispute_decision()
    frozen = read_chargeback(world["chargeback"]["id"])
    assert frozen["dispute_status"] == "OPEN", (
        f"opening a dispute moves the chargeback to OPEN, got {frozen['dispute_status']}"
    )

    validate_error(
        api.post_deduction(world["deduction"]["id"], accountant_headers),
        ApiErrorId.ERR_CHARGEBACK_DISPUTE_OPEN,
        409,
    )

    deduction = read_deduction(world["deduction"]["id"])
    assert deduction["status"] == "DRAFT", (
        f"a frozen document stays DRAFT, got {deduction['status']}"
    )
    allocation = read_allocation(world["allocation"]["id"])
    assert allocation["effective_status"] == "PENDING", (
        "an unposted earmark stays PENDING, got "
        f"{allocation['effective_status']}"
    )


def test_deduction_posting_accepted_once_the_dispute_is_decided(
    api, accountant_headers, second_officer_headers
):
    """PRD §3.6: "A `DENY` decision short-circuits the arithmetic:
    `reason_ceiling_pct` is set to 0.00, `goodwill_cents` to 0 and
    `approved_reversal_cents` to 0, the dispute lands in `DENIED`, and the
    chargeback moves `OPEN → UPHELD` on its dispute dimension with
    `reversal_cents` left exactly as it was."
    PRD §3.9: "Every allocated chargeback must be free of a live dispute: each
    must have a `dispute_status` of `NONE`, `UPHELD` or `PARTIALLY_REVERSED`, and
    any chargeback whose `dispute_status` is `OPEN` freezes the whole document
    with `ERR_CHARGEBACK_DISPUTE_OPEN`."
    PRD §3.9: "The second link, caused by the first, flips every child allocation
    `PENDING → EFFECTIVE` and stamps each one's `applied_at` with the posting
    instant."
    PRD §3.9: "`open_chargeback_cents` is the sum, over the supplier's
    chargebacks whose `settlement_status` is `ASSESSED` or `PARTIALLY_RECOVERED`
    only, of `gross_assessed_cents` less `reversal_cents` less `recovered_cents`;
    chargebacks that are `RECOVERED` or `WRITTEN_OFF` are excluded from this
    figure entirely."

    Design: Difficulty/cross_entity_state_dependency/deduction_posting_depends_on_allocated_chargeback_dispute_state
    """
    world = _deduction_awaiting_a_dispute_decision()
    validate_error(
        api.post_deduction(world["deduction"]["id"], accountant_headers),
        ApiErrorId.ERR_CHARGEBACK_DISPUTE_OPEN,
        409,
    )

    decide_dispute(
        world["dispute"]["id"],
        "DENY",
        headers=second_officer_headers,
        review_note="Carrier detention is a vendor-managed risk under the guide.",
    )
    released = read_chargeback(world["chargeback"]["id"])
    assert released["dispute_status"] == "UPHELD", (
        f"a denial upholds the assessment, got {released['dispute_status']}"
    )
    assert released["reversal_cents"] == 0, (
        f"a denial reverses nothing, got {released['reversal_cents']}"
    )

    posted = validate_success(
        api.post_deduction(world["deduction"]["id"], accountant_headers), 200
    )
    assert posted["status"] == "POSTED", (
        f"posting moves the document to POSTED, got {posted['status']}"
    )
    assert posted["amount_cents"] == 100000, (
        f"the document nets its single earmark, expected 100000, got {posted['amount_cents']}"
    )

    allocation = read_allocation(world["allocation"]["id"])
    assert allocation["effective_status"] == "EFFECTIVE", (
        f"posting makes the earmark EFFECTIVE, got {allocation['effective_status']}"
    )

    chargeback = read_chargeback(world["chargeback"]["id"])
    assert chargeback["recovered_cents"] == 100000, (
        f"expected recovered_cents 100000, got {chargeback['recovered_cents']}"
    )
    assert chargeback["outstanding_cents"] == 325000, (
        f"expected outstanding_cents 325000, got {chargeback['outstanding_cents']}"
    )
    assert chargeback["settlement_status"] == "PARTIALLY_RECOVERED", (
        f"expected PARTIALLY_RECOVERED, got {chargeback['settlement_status']}"
    )

    vendor = read_vendor(world["vendor"]["id"])
    assert vendor["open_chargeback_cents"] == 325000, (
        "expected open_chargeback_cents 325000, got "
        f"{vendor['open_chargeback_cents']}"
    )


# ---------------------------------------------------------------------------
# A purchase order may only be raised against a supplier that is not on hold
# ---------------------------------------------------------------------------
def test_escalation_chain_places_the_supplier_on_sourcing_hold_at_level_two(api):
    """PRD §3.7: "Under `ORDER_WEIGHTED` the rule is round-then-aggregate: each
    order's fill percentage is rounded to two decimals first, those
    already-rounded per-order values are summed, the sum is divided by
    `measured_po_count`, and the average is rounded half up to two decimals
    again."
    PRD §3.7: "The composite is 0.60 multiplied by `otif_pct` plus 0.40
    multiplied by `fill_rate_pct`, rounded half up to two decimals — on-time-in-full
    performance carries three fifths of the weight and raw fill rate the remaining
    two fifths."
    PRD §3.8: "The supplier is flagged as a repeat offender when the
    charged-violation count has reached 3 or more, **or** when at least one
    `TIER_1` chargeback sits in the window and the period's `composite_score` is
    strictly below 90.00."
    PRD §3.8: "A plan is required — `cap_required` becomes true — only when the
    supplier is flagged as a repeat offender **and** the period's
    `composite_score` is strictly below 92.00, so a repeat offender that
    nonetheless scored 92.00 or better is flagged without being placed under a
    plan."
    PRD §3.8: "The `escalation_level` is one plus the number of prior
    unremediated plans in the window, plus one more when the period's
    `composite_score` is strictly below 80.00, and the whole sum is capped at 3."
    PRD §3.8: "The deadline `due_at` is derived from `issued_at` plus a
    level-dependent allowance: 30 days at escalation level 1, 21 days at level 2
    and 14 days at level 3."
    PRD §3.8: "Escalation takes the plan `REJECTED → ESCALATED`, records the
    `buying_decision` and `escalation_note`, stamps `escalated_at`, increments the
    plan's `version`, and when the decision is `SOURCING_HOLD` moves the supplier
    `PROBATION → SOURCING_HOLD`, from which point new purchase orders against that
    supplier are refused with `ERR_VENDOR_SOURCING_HOLD`."

    Design: Difficulty/cross_entity_state_dependency/purchase_order_creation_depends_on_vendor_sourcing_hold_state
    """
    world = _sourcing_hold_world()

    chargeback = read_chargeback(world["chargeback"]["id"])
    assert chargeback["gross_assessed_cents"] == 412500, (
        f"expected gross_assessed_cents 412500, got {chargeback['gross_assessed_cents']}"
    )

    scorecard = read_scorecard(world["scorecard"]["id"])
    assert scorecard["fill_rate_pct"] == 50.00, (
        f"expected fill_rate_pct 50.00, got {scorecard['fill_rate_pct']}"
    )
    assert scorecard["otif_pct"] == 0.00, (
        f"expected otif_pct 0.00, got {scorecard['otif_pct']}"
    )
    assert scorecard["composite_score"] == 20.00, (
        f"expected composite_score 20.00, got {scorecard['composite_score']}"
    )
    assert scorecard["cap_required"] is True, (
        f"expected cap_required true, got {scorecard['cap_required']}"
    )
    assert scorecard["status"] == "FINALIZED", (
        f"expected FINALIZED, got {scorecard['status']}"
    )

    vendor = read_vendor(world["vendor"]["id"])
    assert vendor["otif_score"] == 20.00, (
        f"expected otif_score 20.00, got {vendor['otif_score']}"
    )
    assert vendor["repeat_offender_flag"] is True, (
        f"expected repeat_offender_flag true, got {vendor['repeat_offender_flag']}"
    )
    assert vendor["status"] == "SOURCING_HOLD", (
        f"expected SOURCING_HOLD, got {vendor['status']}"
    )
    assert vendor["open_cap_count"] == 1, (
        f"expected open_cap_count 1, got {vendor['open_cap_count']}"
    )

    cap = read_cap(world["cap"]["id"])
    assert cap["escalation_level"] == 2, (
        f"expected escalation_level 2, got {cap['escalation_level']}"
    )
    assert cap["repeat_count"] == 1, (
        f"expected repeat_count 1, got {cap['repeat_count']}"
    )
    assert cap["predecessor_cap_id"] is None, (
        f"a first failure has no predecessor, got {cap['predecessor_cap_id']}"
    )
    assert _instant(cap["due_at"]) == _instant("2026-09-27T00:00:00Z"), (
        f"expected due_at 2026-09-27T00:00:00Z, got {cap['due_at']}"
    )
    assert cap["submission_round"] == 1, (
        f"expected submission_round 1, got {cap['submission_round']}"
    )
    assert cap["status"] == "ESCALATED", (
        f"expected ESCALATED, got {cap['status']}"
    )
    assert cap["buying_decision"] == "SOURCING_HOLD", (
        f"expected buying_decision SOURCING_HOLD, got {cap['buying_decision']}"
    )


def test_purchase_order_creation_refused_while_the_supplier_is_on_sourcing_hold(
    api, buyer_headers, officer_headers
):
    """PRD §3.1: "While a supplier's `status` is `SOURCING_HOLD` the buying
    organisation may not raise new purchase orders against it, and any attempt is
    refused with `ERR_VENDOR_SOURCING_HOLD`."
    PRD §3.3: "An unresolvable `vendor_id` answers `ERR_VENDOR_NOT_FOUND`, and a
    supplier on sourcing hold answers `ERR_VENDOR_SOURCING_HOLD`."

    Design: Difficulty/cross_entity_state_dependency/purchase_order_creation_depends_on_vendor_sourcing_hold_state
    """
    world = _sourcing_hold_world()
    assert read_vendor(world["vendor"]["id"])["status"] == "SOURCING_HOLD", (
        "the escalation chain must have placed the supplier on sourcing hold"
    )

    validate_error(
        api.create_purchase_order(
            _second_order_payload(world["vendor"]["id"]), buyer_headers
        ),
        ApiErrorId.ERR_VENDOR_SOURCING_HOLD,
        409,
    )

    _, meta = validate_paginated(
        api.list_purchase_orders(
            officer_headers, params={"vendor_id": world["vendor"]["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        "the refused order must not have been created, so only the original order "
        f"remains; expected total_count 1, got {meta['total_count']}"
    )


def test_purchase_order_creation_accepted_once_closure_restores_probation(
    api, buyer_headers
):
    """PRD §3.8: "A `SUCCESS` outcome takes the plan `ACCEPTED → CLOSED_SUCCESS`
    or `ESCALATED → CLOSED_SUCCESS`, stamps `closed_at` and `closure_note`,
    recomputes the supplier's `open_cap_count`, and restores sourcing posture: a
    plan that had been escalated with a `SOURCING_HOLD` buying decision returns
    the supplier `SOURCING_HOLD → PROBATION` as a compensating restoration, and an
    accepted plan that was the supplier's only open plan returns the supplier
    `PROBATION → ACTIVE` with `open_cap_count` falling to 0."
    PRD §3.1: "While a supplier's `status` is `SOURCING_HOLD` the buying
    organisation may not raise new purchase orders against it, and any attempt is
    refused with `ERR_VENDOR_SOURCING_HOLD`."

    Design: Difficulty/cross_entity_state_dependency/purchase_order_creation_depends_on_vendor_sourcing_hold_state
    """
    world = _sourcing_hold_world()
    validate_error(
        api.create_purchase_order(
            _second_order_payload(world["vendor"]["id"]), buyer_headers
        ),
        ApiErrorId.ERR_VENDOR_SOURCING_HOLD,
        409,
    )

    closed = close_cap(
        world["cap"]["id"],
        "SUCCESS",
        closure_note="Remediation verified at the distribution centre.",
    )
    assert closed["status"] == "CLOSED_SUCCESS", (
        f"expected CLOSED_SUCCESS, got {closed['status']}"
    )
    restored = read_vendor(world["vendor"]["id"])
    assert restored["status"] == "PROBATION", (
        "closing an escalated sourcing-hold plan successfully returns the supplier "
        f"to PROBATION, got {restored['status']}"
    )

    order = validate_success(
        api.create_purchase_order(
            _second_order_payload(world["vendor"]["id"]), buyer_headers
        ),
        201,
    )
    assert order["status"] == "OPEN", (
        f"a new order opens in OPEN, got {order['status']}"
    )
    assert order["vendor_id"] == world["vendor"]["id"], (
        "the order must name the supplier it was raised against"
    )
