"""Error catalogue: dispute, plan, scorecard and ledger lifecycle refusals.

Every test builds its own world from an empty database using only endpoints the
PRD declares.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    REQ_LBL_01,
    add_allocation,
    add_requirement,
    allocation_payload,
    assess_violation,
    cap_close_payload,
    cap_decision_payload,
    cap_escalation_payload,
    cap_submit_payload,
    cash_application_payload,
    create_deduction,
    create_guide,
    create_po,
    create_scorecard,
    create_shipment,
    create_vendor,
    decide_cap,
    decide_dispute,
    dispute_payload,
    file_violation,
    finalize_scorecard,
    first_cap_for_scorecard,
    make_vendor_headers,
    measure_payload,
    measure_scorecard,
    open_dispute,
    post_deduction,
    publish_guide,
    read_cap,
    read_chargeback,
    read_deduction,
    read_scorecard,
    read_vendor,
    receive_shipment,
    request_info_payload,
    resubmit_payload,
    reversal_payload,
    set_clock,
    setup_assessed_chargeback,
    submit_cap,
    validate_error,
    validate_paginated,
    validate_success,
)

# The labelling requirement priced so that a 1000-unit receipt at 500 cents a
# unit with 100 units affected assesses 38000 cents.
_LBL_01 = dict(REQ_LBL_01, min_evidence_count=0)


def _assessed_chargeback_world(vendor_code: str, legal_name: str) -> dict:
    """One supplier, one PUBLISHED edition carrying LBL-01, one fully received
    1000-unit order and one chargeback assessed at 2026-08-10."""
    return setup_assessed_chargeback(
        schedule=_LBL_01,
        evidence_kinds=(),
        assessment_note="Assessed.",
        affected_units=100,
        affected_cartons=4,
        narrative="Unreadable labels.",
        vendor_overrides={
            "vendor_code": vendor_code,
            "legal_name": legal_name,
            "payment_terms_days": 30,
        },
    )


# ---------------------------------------------------------------------------
# Dispute lifecycle
# ---------------------------------------------------------------------------
def _submitted_dispute_world() -> dict:
    world = _assessed_chargeback_world("V2058", "Disputestate Decor")
    world["dispute"] = open_dispute(
        world["chargeback"]["id"],
        world["vendor"]["id"],
        reason_code="CARRIER_CAUSED",
        claimed_reversal_cents=10_000,
        narrative="Carrier mishandled the pallet.",
    )
    return world


def test_resubmitting_a_dispute_that_was_never_bounced_back_is_refused(api):
    """PRD §3.6: "Resubmission requires the dispute to be exactly
    `INFO_REQUESTED`, refused otherwise with `ERR_DISPUTE_NOT_INFO_REQUESTED`;
    requires `round_count` to be strictly less than 2, refused otherwise with
    `ERR_DISPUTE_ROUND_LIMIT_EXCEEDED`; and re-checks the claim against
    `gross_assessed_cents` less `reversal_cents`, refused otherwise with
    `ERR_CLAIM_EXCEEDS_ASSESSMENT`."
    PRD §3.6: "A successful opening creates the dispute in `SUBMITTED` with
    `round_count` 1, `submitted_at` from the current logical clock,
    `chargeback_id` taken from the path and `vendor_id` denormalised from the
    chargeback."
    PRD §3.6: "The supplier answers by resubmitting with a fresh
    `claimed_reversal_cents` and a fresh `narrative`, which replace the previous
    round's values; this takes the dispute `INFO_REQUESTED → SUBMITTED`, raises
    `round_count` by one, clears `information_request_note` and increments the
    dispute's `version`."

    Design: Corner/errors/corner_dispute_lifecycle_state_codes_are_triggerable
    """
    world = _submitted_dispute_world()
    dispute = world["dispute"]
    assert dispute["status"] == "SUBMITTED"
    assert dispute["round_count"] == 1

    validate_error(
        api.resubmit_dispute(
            dispute["id"],
            resubmit_payload(
                claimed_reversal_cents=12_000,
                narrative="Adding more detail before being asked.",
            ),
            make_vendor_headers(world["vendor"]["id"]),
        ),
        ApiErrorId.ERR_DISPUTE_NOT_INFO_REQUESTED,
    )

    unchanged = validate_success(
        api.get_dispute(dispute["id"], make_vendor_headers(world["vendor"]["id"]))
    )
    assert unchanged["status"] == "SUBMITTED", (
        f"a refused resubmission leaves the case SUBMITTED, got {unchanged['status']}"
    )
    assert unchanged["round_count"] == 1, (
        f"a refused resubmission must not raise round_count, got {unchanged['round_count']}"
    )
    assert unchanged["claimed_reversal_cents"] == 10000, (
        "a refused resubmission must not replace the round's claim, got "
        f"{unchanged['claimed_reversal_cents']}"
    )


def test_second_dispute_on_the_same_chargeback_is_refused(api, officer_headers):
    """PRD §3.6: "There may be at most one dispute per chargeback, so the
    chargeback's `dispute_status` must be `NONE`, and a second attempt is refused
    with `ERR_DISPUTE_ALREADY_EXISTS`."
    PRD §3.6: "The same request moves the chargeback's `dispute_status`
    `NONE → OPEN` and increments the chargeback's `version` by one; its
    `settlement_status` is untouched, so a chargeback that was
    `PARTIALLY_RECOVERED` or `RECOVERED` stays exactly where it was on that
    dimension."

    Design: Corner/errors/corner_dispute_lifecycle_state_codes_are_triggerable
    """
    world = _submitted_dispute_world()
    chargeback_id = world["chargeback"]["id"]

    validate_error(
        api.create_dispute(
            chargeback_id,
            dispute_payload(
                reason_code="NOT_OUR_LABEL",
                claimed_reversal_cents=5_000,
                narrative="Filing a second, parallel case.",
            ),
            make_vendor_headers(world["vendor"]["id"]),
        ),
        ApiErrorId.ERR_DISPUTE_ALREADY_EXISTS,
    )

    _rows, meta = validate_paginated(
        api.list_disputes(officer_headers, params={"chargeback_id": chargeback_id})
    )
    assert meta["total_count"] == 1, (
        f"no parallel case may be opened, got {meta['total_count']} disputes"
    )
    assert read_chargeback(chargeback_id)["dispute_status"] == "OPEN"


def test_officer_can_bounce_a_submitted_dispute_back_for_information(
    api, officer_headers
):
    """PRD §3.6: "A `ComplianceOfficer` who needs more from the supplier bounces
    the case back with a mandatory `information_request_note`, taking the dispute
    `SUBMITTED → INFO_REQUESTED` and storing the note."

    Design: Corner/errors/corner_dispute_lifecycle_state_codes_are_triggerable
    """
    world = _submitted_dispute_world()

    bounced = validate_success(
        api.request_dispute_info(
            world["dispute"]["id"],
            request_info_payload(
                information_request_note="Send the carrier exception report."
            ),
            officer_headers,
        )
    )
    assert bounced["status"] == "INFO_REQUESTED", (
        f"an information request moves the case to INFO_REQUESTED, got {bounced['status']}"
    )
    assert bounced["information_request_note"] == "Send the carrier exception report."


# ---------------------------------------------------------------------------
# A written-off chargeback is closed to cash
# ---------------------------------------------------------------------------
def test_written_off_chargeback_refuses_a_later_cash_application(
    api, officer_headers, accountant_headers
):
    """PRD §3.6: "The second link, caused by the first, adds
    `approved_reversal_cents` to the chargeback's `reversal_cents` and moves its
    dispute dimension: `OPEN → REVERSED` when the determination classified a full
    approval, `OPEN → PARTIALLY_REVERSED` when it classified a partial one, and
    `OPEN → UPHELD` on a denial. The chargeback's `outstanding_cents` and
    `settlement_status` are then re-derived by the settlement reconciliation
    described in §3.9; where the accumulated `reversal_cents` has reached or
    exceeded `gross_assessed_cents` the chargeback is driven to `WRITTEN_OFF` —
    `ASSESSED → WRITTEN_OFF` when nothing had been recovered, and
    `PARTIALLY_RECOVERED → WRITTEN_OFF` when cash or a deduction had already been
    applied — with `outstanding_cents` set to 0 in either case."
    PRD §3.6: "**Step seven** classifies the outcome from
    `approved_reversal_cents`: the dispute lands in `DENIED` when the approved
    amount is 0, in `APPROVED_FULL` when it equals the eligible cap exactly, and
    in `APPROVED_PARTIAL` in every other case."
    PRD §3.9: "The chargeback's `settlement_status` must not be `WRITTEN_OFF`,
    refused otherwise with `ERR_CHARGEBACK_WRITTEN_OFF`, and the amount may not
    exceed the chargeback's `outstanding_cents`: exact equality is accepted and
    drives the chargeback to full recovery, while one cent more is refused with
    `ERR_OVER_APPLICATION`. The application creates an allocation with
    `source_type` `CASH`, `deduction_id` null, `effective_status` `EFFECTIVE` and
    `applied_at` stamped from the logical clock at creation, storing the applied
    amount in the allocation's `allocated_cents` field and the supplied reference
    in `remittance_reference`."
    PRD §2.7: "The server evaluates rules in the following fixed order and
    returns the first failure it finds. Later rungs are never evaluated once an
    earlier rung has failed."
    PRD §3.9: "`open_chargeback_cents` is the sum, over the supplier's
    chargebacks whose `settlement_status` is `ASSESSED` or `PARTIALLY_RECOVERED`
    only, of `gross_assessed_cents` less `reversal_cents` less `recovered_cents`;
    chargebacks that are `RECOVERED` or `WRITTEN_OFF` are excluded from this
    figure entirely."
    PRD §3.9: "`refund_due_cents` is the sum, over every one of the supplier's
    chargebacks with no settlement filter at all, of the excess of
    `recovered_cents` over `gross_assessed_cents` less `reversal_cents`, counting
    zero where there is no excess — so a written-off chargeback that still holds
    the supplier's cash contributes its whole recovered amount to the refund
    owed."

    Design: Corner/errors/corner_written_off_chargeback_refuses_further_cash
    """
    world = _assessed_chargeback_world("V2059", "Writeoff Woodworks")
    chargeback_id = world["chargeback"]["id"]

    dispute = open_dispute(
        chargeback_id,
        world["vendor"]["id"],
        reason_code="NOT_OUR_LABEL",
        claimed_reversal_cents=38_000,
        narrative="Those are not our labels; the DC scanned another vendor's cartons.",
    )
    decided = decide_dispute(
        dispute["id"],
        "APPROVE",
        headers=officer_headers,
        review_note="Photographs confirm a third-party label.",
    )
    assert decided["status"] == "APPROVED_FULL", (
        f"a claim at the full eligible cap approves in full, got {decided['status']}"
    )
    assert decided["approved_reversal_cents"] == 38000

    chargeback = read_chargeback(chargeback_id)
    assert chargeback["reversal_cents"] == 38000
    assert chargeback["dispute_status"] == "REVERSED"
    assert chargeback["settlement_status"] == "WRITTEN_OFF", (
        f"a fully reversed assessment is written off, got {chargeback['settlement_status']}"
    )
    assert chargeback["outstanding_cents"] == 0

    validate_error(
        api.apply_cash(
            chargeback_id,
            cash_application_payload(1_000, chargeback["version"], remittance_reference="WIRE-9001"),
            accountant_headers,
        ),
        ApiErrorId.ERR_CHARGEBACK_WRITTEN_OFF,
    )

    _rows, meta = validate_paginated(
        api.list_allocations(
            accountant_headers, params={"chargeback_id": chargeback_id}
        )
    )
    assert meta["total_count"] == 0, (
        f"a refused application creates no allocation, got {meta['total_count']}"
    )

    vendor = read_vendor(world["vendor"]["id"])
    assert vendor["open_chargeback_cents"] == 0
    assert vendor["refund_due_cents"] == 0


# ---------------------------------------------------------------------------
# Corrective action plan lifecycle
# ---------------------------------------------------------------------------
def _issued_cap_world() -> dict:
    """A supplier whose July 2026 period scores a composite of 60.00, so
    finalization issues an escalation-level-2 plan at 2026-09-06."""
    set_clock("2026-06-01T00:00:00Z")
    vendor = create_vendor(
        vendor_code="V2060", legal_name="Planstate Plastics", payment_terms_days=30
    )
    guide = create_guide(
        guide_code="RG-2026-A",
        title="Domestic Routing Guide 2026-A",
        scope_code="ALL",
        effective_from="2026-06-05T00:00:00Z",
    )
    requirement = add_requirement(guide["id"], _LBL_01)
    publish_guide(guide["id"])

    orders = {}
    shipments = {}
    for po_number, asn in (("PO-FULL", "ASN-FULL"), ("PO-SHORT", "ASN-SHORT")):
        order = create_po(
            vendor["id"],
            po_number=po_number,
            ordered_units=1000,
            unit_cost_cents=500,
            ship_window_start="2026-07-10T00:00:00Z",
            ship_window_end="2026-07-17T00:00:00Z",
            must_arrive_by="2026-07-20T00:00:00Z",
        )
        orders[po_number] = order
        shipments[po_number] = create_shipment(
            order["id"], vendor["id"], asn_number=asn, shipped_units=1000, carton_count=40
        )

    set_clock("2026-07-19T00:00:00Z")
    receive_shipment(shipments["PO-FULL"]["id"], 1000)
    receive_shipment(shipments["PO-SHORT"]["id"], 500)
    violation = file_violation(
        shipments["PO-SHORT"]["id"],
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
    finalize_scorecard(scorecard["id"])
    return {
        "vendor": vendor,
        "scorecard": read_scorecard(scorecard["id"]),
        "cap": first_cap_for_scorecard(scorecard["id"]),
    }


def test_closing_a_plan_nobody_has_submitted_is_refused(api, officer_headers):
    """PRD §3.8: "It is permitted only from `ACCEPTED` or `ESCALATED`, refused
    otherwise with `ERR_CAP_NOT_CLOSABLE`."

    Design: Corner/errors/corner_corrective_action_plan_lifecycle_codes_are_triggerable
    """
    world = _issued_cap_world()

    validate_error(
        api.close_cap(
            world["cap"]["id"],
            cap_close_payload(
                "SUCCESS", closure_note="Closing before anything was submitted."
            ),
            officer_headers,
        ),
        ApiErrorId.ERR_CAP_NOT_CLOSABLE,
    )


def test_deciding_a_plan_nobody_has_submitted_is_refused(api, officer_headers):
    """PRD §3.8: "A `ComplianceOfficer` then rules on the submission with a
    `decision` of `ACCEPT` or `REJECT` and a `review_note`, permitted only while
    the plan is `VENDOR_SUBMITTED` and refused otherwise with
    `ERR_CAP_NOT_DECIDABLE`."

    Design: Corner/errors/corner_corrective_action_plan_lifecycle_codes_are_triggerable
    """
    world = _issued_cap_world()

    validate_error(
        api.decide_cap(
            world["cap"]["id"],
            cap_decision_payload("ACCEPT", review_note="Deciding on an unsubmitted plan."),
            officer_headers,
        ),
        ApiErrorId.ERR_CAP_NOT_DECIDABLE,
    )


def test_commitment_later_than_the_deadline_is_refused(api):
    """PRD §3.8: "It requires `submission_round` to be strictly less than 2,
    refused otherwise with `ERR_CAP_SUBMISSION_LIMIT_EXCEEDED`, and it requires
    `committed_completion_at` to be no later than `due_at`, refused otherwise
    with `ERR_CAP_COMMITMENT_PAST_DUE`."
    PRD §3.8: "The `escalation_level` is one plus the number of prior
    unremediated plans in the window, plus one more when the period's
    `composite_score` is strictly below 80.00, and the whole sum is capped at 3."
    PRD §3.8: "The deadline `due_at` is derived from `issued_at` plus a
    level-dependent allowance: 30 days at escalation level 1, 21 days at level 2
    and 14 days at level 3."

    Design: Corner/errors/corner_corrective_action_plan_lifecycle_codes_are_triggerable
    """
    world = _issued_cap_world()
    plan = world["cap"]
    assert plan["escalation_level"] == 2, (
        f"a composite below 80.00 adds the critical level, got {plan['escalation_level']}"
    )
    assert plan["due_at"].startswith("2026-09-27T00:00:00"), (
        f"a level-2 plan issued on 2026-09-06 is due 21 days later, got {plan['due_at']}"
    )

    validate_error(
        api.submit_cap(
            plan["id"],
            cap_submit_payload(
                milestone_text="Relabel by October.",
                committed_completion_at="2026-10-01T00:00:00Z",
            ),
            make_vendor_headers(world["vendor"]["id"]),
        ),
        ApiErrorId.ERR_CAP_COMMITMENT_PAST_DUE,
    )


def test_first_submission_inside_the_deadline_is_stored(api):
    """PRD §3.8: "A submission takes the plan `ISSUED → VENDOR_SUBMITTED` on the
    first attempt or `REJECTED → VENDOR_SUBMITTED` on the rework attempt, stores
    the supplied `milestone_text` and `committed_completion_at`, raises
    `submission_round` by one and increments the plan's `version`."

    Design: Corner/errors/corner_corrective_action_plan_lifecycle_codes_are_triggerable
    """
    world = _issued_cap_world()

    submitted = validate_success(
        api.submit_cap(
            world["cap"]["id"],
            cap_submit_payload(
                milestone_text="Relabel at origin by 2026-09-20.",
                committed_completion_at="2026-09-20T00:00:00Z",
            ),
            make_vendor_headers(world["vendor"]["id"]),
        )
    )
    assert submitted["status"] == "VENDOR_SUBMITTED", (
        f"the first submission moves the plan to VENDOR_SUBMITTED, got {submitted['status']}"
    )
    assert submitted["submission_round"] == 1, (
        f"the first submission raises submission_round to 1, got {submitted['submission_round']}"
    )
    assert submitted["committed_completion_at"].startswith("2026-09-20T00:00:00"), (
        f"the commitment date is stored, got {submitted['committed_completion_at']}"
    )


def test_resubmitting_a_plan_awaiting_review_is_refused(api):
    """PRD §3.8: "Submission is available in the `Vendor` role against the
    supplier's own plan — the plan's `vendor_id` must equal the caller's
    `X-User-ID`, or the answer is `ERR_VENDOR_SCOPE_VIOLATION` — and requires the
    plan to be in `ISSUED` or `REJECTED`, refused otherwise with
    `ERR_CAP_NOT_AWAITING_SUBMISSION`."

    Design: Corner/errors/corner_corrective_action_plan_lifecycle_codes_are_triggerable
    """
    world = _issued_cap_world()
    vendor_id = world["vendor"]["id"]
    submit_cap(
        world["cap"]["id"],
        vendor_id,
        milestone_text="Relabel at origin by 2026-09-20.",
        committed_completion_at="2026-09-20T00:00:00Z",
    )

    validate_error(
        api.submit_cap(
            world["cap"]["id"],
            cap_submit_payload(
                milestone_text="Same plan, sent twice.",
                committed_completion_at="2026-09-20T00:00:00Z",
            ),
            make_vendor_headers(vendor_id),
        ),
        ApiErrorId.ERR_CAP_NOT_AWAITING_SUBMISSION,
    )


def test_escalating_a_plan_still_under_review_is_refused(api, buyer_headers):
    """PRD §3.8: "It requires the plan to be `REJECTED`, refused otherwise with
    `ERR_CAP_NOT_ESCALATABLE`, and takes a `buying_decision` together with an
    `escalation_note` recording the rationale."

    Design: Corner/errors/corner_corrective_action_plan_lifecycle_codes_are_triggerable
    """
    world = _issued_cap_world()
    submit_cap(
        world["cap"]["id"],
        world["vendor"]["id"],
        milestone_text="Relabel at origin by 2026-09-20.",
        committed_completion_at="2026-09-20T00:00:00Z",
    )

    validate_error(
        api.escalate_cap(
            world["cap"]["id"],
            cap_escalation_payload(
                "RANGE_REVIEW",
                escalation_note="Escalating a plan still under review.",
            ),
            buyer_headers,
        ),
        ApiErrorId.ERR_CAP_NOT_ESCALATABLE,
    )


def test_third_submission_after_two_rejections_is_refused(api):
    """PRD §3.8: "It requires `submission_round` to be strictly less than 2,
    refused otherwise with `ERR_CAP_SUBMISSION_LIMIT_EXCEEDED`, and it requires
    `committed_completion_at` to be no later than `due_at`, refused otherwise
    with `ERR_CAP_COMMITMENT_PAST_DUE`."
    PRD §3.8: "An acceptance takes the plan `VENDOR_SUBMITTED → ACCEPTED`; a
    rejection takes it `VENDOR_SUBMITTED → REJECTED`."
    PRD §3.8: "The rework loop `VENDOR_SUBMITTED → REJECTED → VENDOR_SUBMITTED`
    closes once: the submission bound of two means a third submission is refused
    with `ERR_CAP_SUBMISSION_LIMIT_EXCEEDED`, leaving a twice-rejected plan with
    escalation as its only forward path."

    Design: Corner/errors/corner_corrective_action_plan_lifecycle_codes_are_triggerable
    """
    world = _issued_cap_world()
    cap_id = world["cap"]["id"]
    vendor_id = world["vendor"]["id"]

    submit_cap(
        cap_id,
        vendor_id,
        milestone_text="Relabel at origin by 2026-09-20.",
        committed_completion_at="2026-09-20T00:00:00Z",
    )
    decide_cap(cap_id, "REJECT", review_note="No measurable milestones.")
    second = submit_cap(
        cap_id,
        vendor_id,
        milestone_text="Second attempt with weekly audits.",
        committed_completion_at="2026-09-20T00:00:00Z",
    )
    assert second["submission_round"] == 2, (
        f"the rework attempt raises submission_round to 2, got {second['submission_round']}"
    )
    decide_cap(cap_id, "REJECT", review_note="Still not adequate.")

    validate_error(
        api.submit_cap(
            cap_id,
            cap_submit_payload(
                milestone_text="Third attempt.",
                committed_completion_at="2026-09-20T00:00:00Z",
            ),
            make_vendor_headers(vendor_id),
        ),
        ApiErrorId.ERR_CAP_SUBMISSION_LIMIT_EXCEEDED,
    )
    assert read_cap(cap_id)["status"] == "REJECTED"


# ---------------------------------------------------------------------------
# Sourcing hold demands escalation level two
# ---------------------------------------------------------------------------
def _rejected_first_offence_plan_world() -> dict:
    """A supplier whose July 2026 period scores a composite of 84.00, so the plan
    the finalisation issues sits at escalation level 1 and has been rejected
    once."""
    set_clock("2026-06-01T00:00:00Z")
    vendor = create_vendor(
        vendor_code="V2061", legal_name="Firstoffence Fixtures", payment_terms_days=30
    )
    guide = create_guide(
        guide_code="RG-2026-A",
        title="Domestic Routing Guide 2026-A",
        scope_code="ALL",
        effective_from="2026-06-05T00:00:00Z",
    )
    requirement = add_requirement(guide["id"], _LBL_01)
    publish_guide(guide["id"])

    shipments = {}
    for letter in ("A", "B", "C", "D"):
        order = create_po(
            vendor["id"],
            po_number=f"PO-{letter}",
            ordered_units=1000,
            unit_cost_cents=500,
            ship_window_start="2026-07-10T00:00:00Z",
            ship_window_end="2026-07-17T00:00:00Z",
            must_arrive_by="2026-07-20T00:00:00Z",
        )
        shipments[letter] = create_shipment(
            order["id"],
            vendor["id"],
            asn_number=f"ASN-{letter}",
            shipped_units=1000,
            carton_count=40,
        )

    set_clock("2026-07-19T00:00:00Z")
    receive_shipment(shipments["A"]["id"], 1000)
    receive_shipment(shipments["B"]["id"], 1000)
    receive_shipment(shipments["C"]["id"], 1000)
    receive_shipment(shipments["D"]["id"], 900)
    violation = file_violation(
        shipments["D"]["id"],
        requirement["id"],
        affected_units=100,
        affected_cartons=4,
        narrative="Unreadable labels on the short shipment.",
    )
    assess_violation(violation["id"], assessment_note="TIER_1 assessment.")

    set_clock("2026-09-05T00:00:00Z")
    scorecard = create_scorecard(
        vendor["id"],
        period_code="2026-07",
        period_start="2026-07-01T00:00:00Z",
        period_end="2026-07-31T00:00:00Z",
    )
    measure_scorecard(scorecard["id"], "ORDER_WEIGHTED")
    set_clock("2026-09-06T00:00:00Z")
    finalize_scorecard(scorecard["id"])
    cap = first_cap_for_scorecard(scorecard["id"])
    submit_cap(
        cap["id"],
        vendor["id"],
        milestone_text="We will review labels.",
        committed_completion_at="2026-09-30T00:00:00Z",
    )
    decide_cap(cap["id"], "REJECT", review_note="No measurable milestones.")
    return {
        "vendor": vendor,
        "scorecard": read_scorecard(scorecard["id"]),
        "cap": read_cap(cap["id"]),
    }


def test_sourcing_hold_is_refused_on_a_first_offence_plan(api, buyer_headers):
    """PRD §3.8: "A `buying_decision` of `SOURCING_HOLD` requires the plan's
    `escalation_level` to be at least 2, and additionally a `buying_decision` of
    `NONE` is never accepted at escalation; either failing is refused with
    `ERR_CAP_ESCALATION_LEVEL_TOO_LOW`."
    PRD §3.7: "`on_time_pct` is 100 multiplied by `on_time_count`, divided by
    `measured_po_count`, rounded half up to two decimals, and `otif_pct` is the
    same expression built from `otif_count`."
    PRD §3.7: "Under `ORDER_WEIGHTED` the rule is round-then-aggregate: each
    order's fill percentage is rounded to two decimals first, those
    already-rounded per-order values are summed, the sum is divided by
    `measured_po_count`, and the average is rounded half up to two decimals
    again."
    PRD §3.7: "The composite is 0.60 multiplied by `otif_pct` plus 0.40
    multiplied by `fill_rate_pct`, rounded half up to two decimals —
    on-time-in-full performance carries three fifths of the weight and raw fill
    rate the remaining two fifths."
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
    PRD §3.8: "Its `predecessor_cap_id` is set by explicit selection rather than
    by any identifier arithmetic: it points at the supplier's corrective action
    plan in `CLOSED_UNREMEDIATED` ranked first by `closed_at` descending and,
    where two share a closure instant, by `created_at` descending, and it is null
    when the supplier has never failed to remediate."

    Design: Corner/errors/corner_sourcing_hold_escalation_refused_below_level_two
    """
    world = _rejected_first_offence_plan_world()
    scorecard = world["scorecard"]
    assert scorecard["otif_pct"] == pytest.approx(75.00, abs=0.005)
    assert scorecard["fill_rate_pct"] == pytest.approx(97.50, abs=0.005)
    assert scorecard["composite_score"] == pytest.approx(84.00, abs=0.005)
    assert scorecard["cap_required"] is True

    plan = world["cap"]
    assert plan["escalation_level"] == 1, (
        f"a composite of 84.00 with no prior failed plan stays at level 1, "
        f"got {plan['escalation_level']}"
    )
    assert plan["due_at"].startswith("2026-10-06T00:00:00"), (
        f"a level-1 plan issued on 2026-09-06 is due 30 days later, got {plan['due_at']}"
    )
    assert plan["predecessor_cap_id"] is None

    validate_error(
        api.escalate_cap(
            plan["id"],
            cap_escalation_payload(
                "SOURCING_HOLD", escalation_note="Requesting a sourcing hold."
            ),
            buyer_headers,
        ),
        ApiErrorId.ERR_CAP_ESCALATION_LEVEL_TOO_LOW,
    )


def test_escalation_with_no_buying_decision_is_refused(api, buyer_headers):
    """PRD §3.8: "A `buying_decision` of `SOURCING_HOLD` requires the plan's
    `escalation_level` to be at least 2, and additionally a `buying_decision` of
    `NONE` is never accepted at escalation; either failing is refused with
    `ERR_CAP_ESCALATION_LEVEL_TOO_LOW`."

    Design: Corner/errors/corner_sourcing_hold_escalation_refused_below_level_two
    """
    world = _rejected_first_offence_plan_world()

    validate_error(
        api.escalate_cap(
            world["cap"]["id"],
            cap_escalation_payload(
                "NONE", escalation_note="Escalating with no decision at all."
            ),
            buyer_headers,
        ),
        ApiErrorId.ERR_CAP_ESCALATION_LEVEL_TOO_LOW,
    )


def test_range_review_escalation_is_accepted_at_level_one(api, buyer_headers):
    """PRD §3.8: "A `buying_decision` of `RANGE_REVIEW` is permitted at any
    escalation level and leaves the supplier's `status` untouched — the
    assortment is reconsidered but purchasing continues."
    PRD §3.8: "Escalation takes the plan `REJECTED → ESCALATED`, records the
    `buying_decision` and `escalation_note`, stamps `escalated_at`, increments the
    plan's `version`, and when the decision is `SOURCING_HOLD` moves the supplier
    `PROBATION → SOURCING_HOLD`, from which point new purchase orders against
    that supplier are refused with `ERR_VENDOR_SOURCING_HOLD`."
    PRD §3.7: "The fourth, caused by the third, moves an `ACTIVE` supplier to
    `PROBATION` because a plan is now open against it."

    Design: Corner/errors/corner_sourcing_hold_escalation_refused_below_level_two
    """
    world = _rejected_first_offence_plan_world()

    escalated = validate_success(
        api.escalate_cap(
            world["cap"]["id"],
            cap_escalation_payload(
                "RANGE_REVIEW", escalation_note="Refer to the category range review."
            ),
            buyer_headers,
        )
    )
    assert escalated["status"] == "ESCALATED", (
        f"a range review escalates the plan, got {escalated['status']}"
    )
    assert read_vendor(world["vendor"]["id"])["status"] == "PROBATION", (
        "a range review leaves the supplier's sourcing posture untouched"
    )


# ---------------------------------------------------------------------------
# Deduction ledger: the DRAFT and POSTED split
# ---------------------------------------------------------------------------
def _draft_deduction_world() -> dict:
    world = _assessed_chargeback_world("V2062", "Deductstate Denim")
    world["deduction"] = create_deduction(
        world["vendor"]["id"], invoice_reference="INV-2062"
    )
    return world


def test_posting_a_deduction_with_no_allocations_is_refused(api, accountant_headers):
    """PRD §3.9: "Posting turns intentions into money. It requires the deduction
    to be `DRAFT` — a deduction already `POSTED` or `REVERSED` is refused with
    `ERR_DEDUCTION_ALREADY_POSTED` — and it requires at least one allocation, so
    an `allocation_count` of 0 is refused with `ERR_DEDUCTION_NO_ALLOCATIONS`."

    Design: Corner/errors/corner_deduction_draft_and_posted_codes_are_triggerable
    """
    world = _draft_deduction_world()

    validate_error(
        api.post_deduction(world["deduction"]["id"], accountant_headers),
        ApiErrorId.ERR_DEDUCTION_NO_ALLOCATIONS,
    )


def test_reversing_a_deduction_that_was_never_posted_is_refused(
    api, accountant_headers
):
    """PRD §3.9: "Reversal unwinds a posting completely. It requires the deduction
    to be `POSTED`, refused otherwise with `ERR_DEDUCTION_NOT_POSTED`, and takes a
    `reversal_reason`."

    Design: Corner/errors/corner_deduction_draft_and_posted_codes_are_triggerable
    """
    world = _draft_deduction_world()

    validate_error(
        api.reverse_deduction(
            world["deduction"]["id"],
            reversal_payload(
                reversal_reason="Reversing something that was never posted."
            ),
            accountant_headers,
        ),
        ApiErrorId.ERR_DEDUCTION_NOT_POSTED,
    )


def test_allocation_one_cent_above_the_outstanding_balance_is_refused(
    api, accountant_headers
):
    """PRD §3.9: "The amount may not exceed the target chargeback's
    `outstanding_cents`, with exact equality permitted and an excess refused as
    `ERR_ALLOCATION_EXCEEDS_OUTSTANDING`."

    Design: Corner/errors/corner_deduction_draft_and_posted_codes_are_triggerable
    """
    world = _draft_deduction_world()

    validate_error(
        api.create_allocation(
            world["deduction"]["id"],
            allocation_payload(world["chargeback"]["id"], 38_001),
            accountant_headers,
        ),
        ApiErrorId.ERR_ALLOCATION_EXCEEDS_OUTSTANDING,
    )


def test_allocation_of_exactly_the_outstanding_balance_is_accepted(
    api, accountant_headers
):
    """PRD §3.9: "The amount may not exceed the target chargeback's
    `outstanding_cents`, with exact equality permitted and an excess refused as
    `ERR_ALLOCATION_EXCEEDS_OUTSTANDING`. A new allocation is stored with
    `source_type` `DEDUCTION`, `effective_status` `PENDING`,
    `remittance_reference` null, `applied_at` null and `applied_by_user_id` from
    the acting accountant, and it raises the deduction's `amount_cents` by the
    allocated amount and its `allocation_count` by one."

    Design: Corner/errors/corner_deduction_draft_and_posted_codes_are_triggerable
    """
    world = _draft_deduction_world()

    allocation = validate_success(
        api.create_allocation(
            world["deduction"]["id"],
            allocation_payload(world["chargeback"]["id"], 38_000),
            accountant_headers,
        ),
        expected_status=201,
    )
    assert allocation["allocated_cents"] == 38000
    assert allocation["effective_status"] == "PENDING", (
        f"an earmark is an intention, not a recovery, got {allocation['effective_status']}"
    )

    deduction = read_deduction(world["deduction"]["id"])
    assert deduction["amount_cents"] == 38000
    assert deduction["allocation_count"] == 1


def test_posting_an_exact_allocation_recovers_the_chargeback(api, accountant_headers):
    """PRD §3.9: "The first link moves the deduction `DRAFT → POSTED` and stamps
    `posted_at` and `posted_by_user_id`. The second link, caused by the first,
    flips every child allocation `PENDING → EFFECTIVE` and stamps each one's
    `applied_at` with the posting instant. The third link, caused by the second,
    makes each allocated chargeback recompute `recovered_cents` and
    `outstanding_cents`, set `deduction_posted` to true, and re-derive
    `settlement_status`. The fourth link, caused by the third, re-runs the
    exposure reconciliation over the supplier, lowering `open_chargeback_cents`,
    raising `recovered_lifetime_cents` and re-deriving `exposure_alert_flag`."
    PRD §3.9: "The `settlement_status` is then chosen by the first matching branch
    of four, tested in this order: the chargeback is `WRITTEN_OFF` when the net
    assessed balance is zero or below; otherwise `RECOVERED` when
    `recovered_cents` has reached or exceeded the net assessed balance; otherwise
    `PARTIALLY_RECOVERED` when `recovered_cents` is above zero; otherwise
    `ASSESSED`."

    Design: Corner/errors/corner_deduction_draft_and_posted_codes_are_triggerable
    """
    world = _draft_deduction_world()
    add_allocation(world["deduction"]["id"], world["chargeback"]["id"], 38_000)

    posted = validate_success(
        api.post_deduction(world["deduction"]["id"], accountant_headers)
    )
    assert posted["status"] == "POSTED", (
        f"posting moves the document to POSTED, got {posted['status']}"
    )

    chargeback = read_chargeback(world["chargeback"]["id"])
    assert chargeback["settlement_status"] == "RECOVERED"
    assert chargeback["outstanding_cents"] == 0

    vendor = read_vendor(world["vendor"]["id"])
    assert vendor["open_chargeback_cents"] == 0
    assert vendor["recovered_lifetime_cents"] == 38000


def test_allocating_against_a_posted_deduction_is_refused(api, accountant_headers):
    """PRD §3.9: "The deduction must still be `DRAFT`, refused otherwise with
    `ERR_DEDUCTION_NOT_DRAFT`; the `chargeback_id` must resolve, and a chargeback
    belonging to a different supplier than the deduction's is likewise answered
    with `ERR_CHARGEBACK_NOT_FOUND`, since a deduction may only net its own
    supplier's chargebacks. The amount may not exceed the target chargeback's
    `outstanding_cents`, with exact equality permitted and an excess refused as
    `ERR_ALLOCATION_EXCEEDS_OUTSTANDING`."
    PRD §2.7: "The server evaluates rules in the following fixed order and
    returns the first failure it finds. Later rungs are never evaluated once an
    earlier rung has failed."

    Design: Corner/errors/corner_deduction_draft_and_posted_codes_are_triggerable
    """
    world = _draft_deduction_world()
    add_allocation(world["deduction"]["id"], world["chargeback"]["id"], 38_000)
    post_deduction(world["deduction"]["id"])

    validate_error(
        api.create_allocation(
            world["deduction"]["id"],
            allocation_payload(world["chargeback"]["id"], 1),
            accountant_headers,
        ),
        ApiErrorId.ERR_DEDUCTION_NOT_DRAFT,
    )


# ---------------------------------------------------------------------------
# Scorecard lifecycle
# ---------------------------------------------------------------------------
def _two_scorecard_world() -> dict:
    """One supplier with no orders at all and an OPEN 2026-07 scorecard, and one
    supplier with a single on-time, in-full May order and an OPEN 2026-05
    scorecard."""
    set_clock("2026-05-01T00:00:00Z")
    orderless = create_vendor(
        vendor_code="V2063", legal_name="Orderless Optics", payment_terms_days=30
    )
    measurable = create_vendor(
        vendor_code="V2064", legal_name="Measured Mats", payment_terms_days=30
    )
    order = create_po(
        measurable["id"],
        po_number="PO-MAY",
        ordered_units=1000,
        unit_cost_cents=500,
        ship_window_start="2026-05-10T00:00:00Z",
        ship_window_end="2026-05-17T00:00:00Z",
        must_arrive_by="2026-05-20T00:00:00Z",
    )
    shipment = create_shipment(
        order["id"],
        measurable["id"],
        asn_number="ASN-MAY",
        shipped_units=1000,
        carton_count=40,
    )
    set_clock("2026-05-19T00:00:00Z")
    receive_shipment(shipment["id"], 1000)

    set_clock("2026-09-05T00:00:00Z")
    empty_scorecard = create_scorecard(
        orderless["id"],
        period_code="2026-07",
        period_start="2026-07-01T00:00:00Z",
        period_end="2026-07-31T00:00:00Z",
    )
    measurable_scorecard = create_scorecard(
        measurable["id"],
        period_code="2026-05",
        period_start="2026-05-01T00:00:00Z",
        period_end="2026-05-31T00:00:00Z",
    )
    return {
        "orderless_vendor": orderless,
        "measurable_vendor": measurable,
        "empty_scorecard": empty_scorecard,
        "measurable_scorecard": measurable_scorecard,
    }


def test_finalizing_an_unmeasured_scorecard_is_refused(api, officer_headers):
    """PRD §3.7: "It requires the scorecard to be `MEASURED`: a scorecard still
    `OPEN` is refused with `ERR_SCORECARD_NOT_MEASURED`, and one already
    `FINALIZED` with `ERR_SCORECARD_ALREADY_FINALIZED`."

    Design: Corner/errors/corner_scorecard_lifecycle_codes_are_triggerable
    """
    world = _two_scorecard_world()

    validate_error(
        api.finalize_scorecard(world["empty_scorecard"]["id"], officer_headers),
        ApiErrorId.ERR_SCORECARD_NOT_MEASURED,
    )


def test_measuring_a_period_with_no_orders_is_refused(api, officer_headers):
    """PRD §3.7: "The count of that set is `measured_po_count`, and a period
    containing no measurable orders is refused with
    `ERR_SCORECARD_NO_MEASURABLE_ORDERS`."
    PRD §3.7: "It is permitted from `OPEN` and from `MEASURED`, taking the
    scorecard `OPEN → MEASURED` on the first run and `MEASURED → MEASURED` on any
    re-run; a scorecard already `FINALIZED` is refused with
    `ERR_SCORECARD_ALREADY_FINALIZED`."

    Design: Corner/errors/corner_scorecard_lifecycle_codes_are_triggerable
    """
    world = _two_scorecard_world()

    validate_error(
        api.measure_scorecard(
            world["empty_scorecard"]["id"],
            measure_payload("ORDER_WEIGHTED"),
            officer_headers,
        ),
        ApiErrorId.ERR_SCORECARD_NO_MEASURABLE_ORDERS,
    )
    assert read_scorecard(world["empty_scorecard"]["id"])["status"] == "OPEN", (
        "a refused measurement leaves the scorecard OPEN"
    )


def test_measuring_a_period_with_one_perfect_order_scores_a_full_composite(
    api, officer_headers
):
    """PRD §3.7: "It is permitted from `OPEN` and from `MEASURED`, taking the
    scorecard `OPEN → MEASURED` on the first run and `MEASURED → MEASURED` on any
    re-run; a scorecard already `FINALIZED` is refused with
    `ERR_SCORECARD_ALREADY_FINALIZED`."
    PRD §3.7: "The count of that set is `measured_po_count`, and a period
    containing no measurable orders is refused with
    `ERR_SCORECARD_NO_MEASURABLE_ORDERS`."
    PRD §3.7: "The composite is 0.60 multiplied by `otif_pct` plus 0.40
    multiplied by `fill_rate_pct`, rounded half up to two decimals —
    on-time-in-full performance carries three fifths of the weight and raw fill
    rate the remaining two fifths."

    Design: Corner/errors/corner_scorecard_lifecycle_codes_are_triggerable
    """
    world = _two_scorecard_world()

    measured = validate_success(
        api.measure_scorecard(
            world["measurable_scorecard"]["id"],
            measure_payload("ORDER_WEIGHTED"),
            officer_headers,
        )
    )
    assert measured["status"] == "MEASURED", (
        f"the first measurement moves the scorecard to MEASURED, got {measured['status']}"
    )
    assert measured["measured_po_count"] == 1
    assert measured["composite_score"] == pytest.approx(100.00, abs=0.005)


def test_finalizing_a_measured_scorecard_needs_no_corrective_plan(
    api, officer_headers
):
    """PRD §3.7: "The first moves the scorecard `MEASURED → FINALIZED` and stamps
    `finalized_at`."
    PRD §3.8: "A plan is required — `cap_required` becomes true — only when the
    supplier is flagged as a repeat offender **and** the period's
    `composite_score` is strictly below 92.00, so a repeat offender that
    nonetheless scored 92.00 or better is flagged without being placed under a
    plan."
    PRD §3.7: "The fourth, caused by the third, moves an `ACTIVE` supplier to
    `PROBATION` because a plan is now open against it."

    Design: Corner/errors/corner_scorecard_lifecycle_codes_are_triggerable
    """
    world = _two_scorecard_world()
    measure_scorecard(world["measurable_scorecard"]["id"], "ORDER_WEIGHTED")

    finalized = validate_success(
        api.finalize_scorecard(world["measurable_scorecard"]["id"], officer_headers)
    )
    assert finalized["status"] == "FINALIZED", (
        f"finalization locks the figures, got {finalized['status']}"
    )
    assert finalized["cap_required"] is False, (
        "a clean period demands no corrective action plan"
    )
    assert read_vendor(world["measurable_vendor"]["id"])["status"] == "ACTIVE", (
        "with no plan issued the supplier stays ACTIVE"
    )


def test_measuring_a_finalized_scorecard_is_refused(api, officer_headers):
    """PRD §3.7: "It is permitted from `OPEN` and from `MEASURED`, taking the
    scorecard `OPEN → MEASURED` on the first run and `MEASURED → MEASURED` on any
    re-run; a scorecard already `FINALIZED` is refused with
    `ERR_SCORECARD_ALREADY_FINALIZED`."
    PRD §3.7: "Each measurement also stamps `measured_at` from the logical clock,
    records the requested `measurement_variant`, and re-derives `cap_required`
    from the repeat-offender rule of §3.8 without yet creating any plan."

    Design: Corner/errors/corner_scorecard_lifecycle_codes_are_triggerable
    """
    world = _two_scorecard_world()
    scorecard_id = world["measurable_scorecard"]["id"]
    measure_scorecard(scorecard_id, "ORDER_WEIGHTED")
    finalize_scorecard(scorecard_id)

    validate_error(
        api.measure_scorecard(
            scorecard_id, measure_payload("UNIT_WEIGHTED"), officer_headers
        ),
        ApiErrorId.ERR_SCORECARD_ALREADY_FINALIZED,
    )
    assert read_scorecard(scorecard_id)["measurement_variant"] == "ORDER_WEIGHTED", (
        "the refused re-run must not record the new variant"
    )
