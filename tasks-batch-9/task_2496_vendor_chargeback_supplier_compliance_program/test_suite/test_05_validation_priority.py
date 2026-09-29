"""The rejection ladder: which error a request that breaks two rules answers with.

Each scenario below arranges for two separate rungs of the ladder to fail on the
same request, and pins both the error the caller must see and the fact that the
refused request left every row exactly as it stood.
"""
from test_helpers import (
    REQ_SHP_04,
    ApiErrorId,
    add_allocation,
    add_evidence,
    add_requirement,
    assess_violation,
    create_deduction,
    create_guide,
    create_po,
    create_shipment,
    create_vendor,
    file_violation,
    make_vendor_headers,
    open_dispute,
    post_deduction,
    publish_guide,
    read_chargeback,
    read_deduction,
    read_dispute,
    read_shipment,
    read_vendor,
    receive_shipment,
    set_clock,
    validate_error,
    validate_paginated,
)

SHP_04_SCHEDULE = dict(REQ_SHP_04)


def _world_fully_recovered_posted_deduction() -> dict:
    """A supplier whose only chargeback of 425000 has been fully netted by a
    POSTED deduction, so open exposure now stands at zero."""
    set_clock("2026-08-01T00:00:00Z")
    vendor = create_vendor(
        vendor_code="V1101", legal_name="Doublepost Trading", payment_terms_days=60
    )
    guide = create_guide(
        guide_code="RG-2026-A",
        title="Domestic Routing Guide 2026-A",
        scope_code="ALL",
        effective_from="2026-08-05T00:00:00Z",
    )
    requirement = add_requirement(guide["id"], SHP_04_SCHEDULE)
    publish_guide(guide["id"])

    set_clock("2026-08-10T00:00:00Z")
    po = create_po(
        vendor["id"], po_number="PO-1", ordered_units=1000, unit_cost_cents=500
    )
    shipment = create_shipment(
        po["id"], vendor["id"], asn_number="ASN-1", shipped_units=1000, carton_count=40
    )
    receive_shipment(shipment["id"], 1000)
    violation = file_violation(
        shipment["id"],
        requirement["id"],
        affected_units=400,
        affected_cartons=16,
        narrative="ASN transmitted after trailer arrival.",
    )
    add_evidence(
        violation["id"], kind="DOCUMENT", reference_uri="s3://evidence/shp-04/asn.pdf"
    )
    add_evidence(
        violation["id"],
        kind="MEASUREMENT",
        reference_uri="s3://evidence/shp-04/gate.csv",
    )
    chargeback = assess_violation(violation["id"], assessment_note="Late ASN.")

    deduction = create_deduction(vendor["id"], invoice_reference="INV-88")
    add_allocation(deduction["id"], chargeback["id"], 425_000)
    post_deduction(deduction["id"])
    return {"vendor": vendor, "chargeback": chargeback, "deduction": deduction}


def _world_late_filing_against_a_guide_that_has_not_opened() -> dict:
    """A shipment that arrived on 2026-08-10, a published edition whose window does
    not open until 2026-08-20, and a clock standing at 2026-08-14 — four days after
    the 72-hour filing window closed."""
    set_clock("2026-08-01T00:00:00Z")
    vendor = create_vendor(
        vendor_code="V1102", legal_name="Futureguide Freight", payment_terms_days=60
    )
    guide = create_guide(
        guide_code="RG-2026-F",
        title="Domestic Routing Guide 2026-F",
        scope_code="ALL",
        effective_from="2026-08-20T00:00:00Z",
    )
    requirement = add_requirement(guide["id"], SHP_04_SCHEDULE)
    publish_guide(guide["id"])

    set_clock("2026-08-10T00:00:00Z")
    po = create_po(
        vendor["id"], po_number="PO-1", ordered_units=1000, unit_cost_cents=500
    )
    shipment = create_shipment(
        po["id"], vendor["id"], asn_number="ASN-1", shipped_units=1000, carton_count=40
    )
    shipment = receive_shipment(shipment["id"], 1000)

    set_clock("2026-08-14T00:00:00Z")
    return {"vendor": vendor, "requirement": requirement, "shipment": shipment}


def _world_disputed_chargeback_past_its_window() -> dict:
    """A chargeback assessed on 2026-08-10 that already carries one SUBMITTED
    dispute, read at a clock of 2026-09-15 — six days past the 30-day deadline."""
    set_clock("2026-08-01T00:00:00Z")
    vendor = create_vendor(
        vendor_code="V1103", legal_name="Latefile Sundries", payment_terms_days=60
    )
    guide = create_guide(
        guide_code="RG-2026-A",
        title="Domestic Routing Guide 2026-A",
        scope_code="ALL",
        effective_from="2026-08-05T00:00:00Z",
    )
    requirement = add_requirement(guide["id"], SHP_04_SCHEDULE)
    publish_guide(guide["id"])

    set_clock("2026-08-10T00:00:00Z")
    po = create_po(
        vendor["id"], po_number="PO-1", ordered_units=1000, unit_cost_cents=500
    )
    shipment = create_shipment(
        po["id"], vendor["id"], asn_number="ASN-1", shipped_units=1000, carton_count=40
    )
    receive_shipment(shipment["id"], 1000)
    violation = file_violation(
        shipment["id"],
        requirement["id"],
        affected_units=400,
        affected_cartons=16,
        narrative="ASN transmitted after trailer arrival.",
    )
    add_evidence(
        violation["id"], kind="DOCUMENT", reference_uri="s3://evidence/shp-04/asn.pdf"
    )
    add_evidence(
        violation["id"],
        kind="MEASUREMENT",
        reference_uri="s3://evidence/shp-04/gate.csv",
    )
    chargeback = assess_violation(violation["id"], assessment_note="Late ASN.")

    set_clock("2026-08-12T00:00:00Z")
    dispute = open_dispute(
        chargeback["id"],
        vendor["id"],
        reason_code="CARRIER_CAUSED",
        claimed_reversal_cents=200_000,
        narrative="First and only in-window dispute.",
    )

    set_clock("2026-09-15T00:00:00Z")
    return {
        "vendor": vendor,
        "chargeback": chargeback,
        "dispute": dispute,
    }


# ---------------------------------------------------------------------------
# Transition legality outranks the exposure ceiling on a repeat post
# ---------------------------------------------------------------------------
def test_second_post_of_a_posted_deduction_answers_already_posted_not_exposure(
    api, accountant_headers
):
    """PRD §2.7: "The server evaluates rules in the following fixed order and
    returns the first failure it finds. Later rungs are never evaluated once an
    earlier rung has failed."
    PRD §2.7: "Transition legality — the target resource is in a state from which
    the requested transition exists, per the state machines described throughout
    §3; otherwise the 409 conflict error appropriate to that resource and
    operation. This rung is the home of `ERR_GUIDE_NOT_DRAFT`,
    `ERR_SHIPMENT_ALREADY_RECEIVED`, `ERR_SHIPMENT_NOT_RECEIVED`,
    `ERR_VIOLATION_NOT_OPEN`, `ERR_CHARGEBACK_WRITTEN_OFF`,
    `ERR_DISPUTE_NOT_AWAITING_DECISION`, `ERR_DISPUTE_NOT_INFO_REQUESTED`,
    `ERR_SCORECARD_NOT_MEASURED`, `ERR_SCORECARD_ALREADY_FINALIZED`,
    `ERR_CAP_NOT_AWAITING_SUBMISSION`, `ERR_CAP_NOT_DECIDABLE`,
    `ERR_CAP_NOT_ESCALATABLE`, `ERR_CAP_NOT_CLOSABLE`, `ERR_DEDUCTION_NOT_DRAFT`,
    `ERR_DEDUCTION_ALREADY_POSTED` and `ERR_DEDUCTION_NOT_POSTED`."
    PRD §2.7: "Exposure ceiling — a deduction's `amount_cents` does not exceed the
    vendor's `open_chargeback_cents` at the instant of posting, with equality
    permitted; otherwise `ERR_DEDUCTION_EXCEEDS_EXPOSURE` (422)."
    PRD §3.9: "It requires the deduction to be `DRAFT` — a deduction already
    `POSTED` or `REVERSED` is refused with `ERR_DEDUCTION_ALREADY_POSTED` — and it
    requires at least one allocation, so an `allocation_count` of 0 is refused with
    `ERR_DEDUCTION_NO_ALLOCATIONS`."

    Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_business_fiscal_on_repeat_deduction_post
    """
    world = _world_fully_recovered_posted_deduction()

    vendor = read_vendor(world["vendor"]["id"])
    assert vendor["open_chargeback_cents"] == 0, (
        "the first posting must have taken open exposure to zero so that the "
        "exposure ceiling is breached too, got "
        f"{vendor['open_chargeback_cents']}"
    )

    response = api.post_deduction(world["deduction"]["id"], accountant_headers)
    error = validate_error(
        response, ApiErrorId.ERR_DEDUCTION_ALREADY_POSTED.value, 409
    )
    assert error["error_id"] != ApiErrorId.ERR_DEDUCTION_EXCEEDS_EXPOSURE.value, (
        "the exposure ceiling sits below transition legality on the ladder and must "
        "never be the reported failure here"
    )


def test_refused_repeat_post_leaves_the_document_chargeback_and_exposure_untouched(
    api, accountant_headers
):
    """PRD §2.7: "Several rules can be violated by one request at the same time,
    and which error the caller sees is part of the contract, not an implementation
    detail."
    PRD §3.9: "It requires the deduction to be `DRAFT` — a deduction already
    `POSTED` or `REVERSED` is refused with `ERR_DEDUCTION_ALREADY_POSTED` — and it
    requires at least one allocation, so an `allocation_count` of 0 is refused with
    `ERR_DEDUCTION_NO_ALLOCATIONS`."
    PRD §3.9: "Because the second branch tests "reached or exceeded" rather than
    "exceeded", an exact-payoff cash application lands on `RECOVERED` and not on
    `PARTIALLY_RECOVERED`."

    Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_business_fiscal_on_repeat_deduction_post
    """
    world = _world_fully_recovered_posted_deduction()

    response = api.post_deduction(world["deduction"]["id"], accountant_headers)
    validate_error(response, ApiErrorId.ERR_DEDUCTION_ALREADY_POSTED.value, 409)

    deduction = read_deduction(world["deduction"]["id"])
    assert deduction["status"] == "POSTED", (
        f"the refused repeat must leave the document POSTED, got "
        f"{deduction['status']}"
    )
    assert deduction["amount_cents"] == 425_000, (
        f"expected amount_cents 425000, got {deduction['amount_cents']}"
    )
    assert deduction["allocation_count"] == 1, (
        f"expected allocation_count 1, got {deduction['allocation_count']}"
    )

    chargeback = read_chargeback(world["chargeback"]["id"])
    assert chargeback["recovered_cents"] == 425_000, (
        f"expected recovered_cents 425000, got {chargeback['recovered_cents']}"
    )
    assert chargeback["outstanding_cents"] == 0, (
        f"expected outstanding_cents 0, got {chargeback['outstanding_cents']}"
    )
    assert chargeback["settlement_status"] == "RECOVERED", (
        f"expected settlement_status RECOVERED, got "
        f"{chargeback['settlement_status']}"
    )

    vendor = read_vendor(world["vendor"]["id"])
    assert vendor["open_chargeback_cents"] == 0, (
        f"expected open_chargeback_cents 0, got {vendor['open_chargeback_cents']}"
    )
    assert vendor["recovered_lifetime_cents"] == 425_000, (
        f"expected recovered_lifetime_cents 425000, got "
        f"{vendor['recovered_lifetime_cents']}"
    )


# ---------------------------------------------------------------------------
# Guide effectivity outranks the filing window on a late filing
# ---------------------------------------------------------------------------
def test_late_filing_against_an_unopened_guide_answers_guide_not_effective(
    api, inspector_headers
):
    """PRD §2.7: "The server evaluates rules in the following fixed order and
    returns the first failure it finds. Later rungs are never evaluated once an
    earlier rung has failed."
    PRD §2.7: "Guide effectivity — the requirement pinned by the violation belongs
    to a guide whose `status` is `PUBLISHED` or `SUPERSEDED` and whose effectivity
    window contains the shipment's `arrived_at`; otherwise
    `ERR_GUIDE_NOT_EFFECTIVE` (422). This rung guards both violation filing and
    chargeback assessment."
    PRD §2.7: "Filing window — violation filing occurs strictly earlier than 72
    hours after the shipment's `arrived_at`; otherwise
    `ERR_VIOLATION_FILING_WINDOW_CLOSED` (422)."

    Design: Difficulty/priority_pair_validation_conflict/priority_business_referential_beats_business_temporal_on_late_filing_of_future_guide
    """
    world = _world_late_filing_against_a_guide_that_has_not_opened()

    response = api.create_violation(
        world["shipment"]["id"],
        {
            "requirement_id": world["requirement"]["id"],
            "affected_units": 400,
            "affected_cartons": 16,
            "narrative": (
                "Filed four days late against a guide that has not opened."
            ),
        },
        inspector_headers,
    )
    error = validate_error(response, ApiErrorId.ERR_GUIDE_NOT_EFFECTIVE.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_VIOLATION_FILING_WINDOW_CLOSED.value, (
        "the filing window sits one rung below guide effectivity and must never be "
        "the reported failure here"
    )


def test_refused_late_filing_writes_no_violation_and_moves_no_counter(
    api, inspector_headers
):
    """PRD §2.7: "Several rules can be violated by one request at the same time,
    and which error the caller sees is part of the contract, not an implementation
    detail."
    PRD §3.4: "A newly filed violation records `detected_at` from the current
    logical clock and `detected_by_user_id` from the acting inspector's
    `X-User-ID`, takes its `shipment_id` from the path, pins the supplied
    `requirement_id`, starts with `evidence_count` 0 and `void_reason` null, and
    raises both the shipment's `open_violation_count` and the supplier's
    `open_violation_count` by one."
    PRD §3.4: "Each capture raises the violation's `evidence_count` by one and the
    shipment's `evidence_capture_count` by one."

    Design: Difficulty/priority_pair_validation_conflict/priority_business_referential_beats_business_temporal_on_late_filing_of_future_guide
    """
    world = _world_late_filing_against_a_guide_that_has_not_opened()

    response = api.create_violation(
        world["shipment"]["id"],
        {
            "requirement_id": world["requirement"]["id"],
            "affected_units": 400,
            "affected_cartons": 16,
            "narrative": (
                "Filed four days late against a guide that has not opened."
            ),
        },
        inspector_headers,
    )
    validate_error(response, ApiErrorId.ERR_GUIDE_NOT_EFFECTIVE.value, 422)

    shipment = read_shipment(world["shipment"]["id"])
    assert shipment["open_violation_count"] == 0, (
        f"the refused filing must not raise the shipment's open_violation_count, "
        f"got {shipment['open_violation_count']}"
    )
    assert shipment["evidence_capture_count"] == 0, (
        f"expected evidence_capture_count 0, got "
        f"{shipment['evidence_capture_count']}"
    )

    listing = api.list_violations(
        inspector_headers, params={"shipment_id": world["shipment"]["id"]}
    )
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 0, (
        f"no violation row may exist on this shipment, got total_count "
        f"{meta['total_count']}"
    )

    vendor = read_vendor(world["vendor"]["id"])
    assert vendor["open_violation_count"] == 0, (
        f"expected the supplier's open_violation_count to stay 0, got "
        f"{vendor['open_violation_count']}"
    )


# ---------------------------------------------------------------------------
# The dispute window outranks the one-dispute-per-chargeback rule
# ---------------------------------------------------------------------------
def test_second_dispute_after_the_window_answers_window_closed_not_already_exists(
    api,
):
    """PRD §2.7: "The server evaluates rules in the following fixed order and
    returns the first failure it finds. Later rungs are never evaluated once an
    earlier rung has failed."
    PRD §2.7: "Dispute window — dispute creation occurs strictly earlier than 30
    days after the chargeback's `assessed_at`; otherwise
    `ERR_DISPUTE_WINDOW_CLOSED` (422)."
    PRD §2.7: "One dispute per chargeback — the chargeback's `dispute_status` is
    `NONE`; otherwise `ERR_DISPUTE_ALREADY_EXISTS` (409)."

    Design: Difficulty/priority_pair_validation_conflict/priority_business_temporal_beats_business_constraint_on_second_dispute_after_window
    """
    world = _world_disputed_chargeback_past_its_window()

    response = api.create_dispute(
        world["chargeback"]["id"],
        {
            "reason_code": "DUPLICATE_ASSESSMENT",
            "claimed_reversal_cents": 425_000,
            "narrative": "Second bite, filed after the window closed.",
        },
        make_vendor_headers(world["vendor"]["id"]),
    )
    error = validate_error(response, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_DISPUTE_ALREADY_EXISTS.value, (
        "the one-dispute-per-chargeback rule sits three rungs below the dispute "
        "window and must never be the reported failure here"
    )


def test_refused_second_dispute_leaves_the_first_dispute_and_chargeback_untouched(
    api, officer_headers
):
    """PRD §2.7: "Several rules can be violated by one request at the same time,
    and which error the caller sees is part of the contract, not an implementation
    detail."
    PRD §3.6: "A successful opening creates the dispute in `SUBMITTED` with
    `round_count` 1, `submitted_at` from the current logical clock,
    `chargeback_id` taken from the path and `vendor_id` denormalised from the
    chargeback."
    PRD §3.6: "The same request moves the chargeback's `dispute_status` `NONE →
    OPEN` and increments the chargeback's `version` by one; its
    `settlement_status` is untouched, so a chargeback that was
    `PARTIALLY_RECOVERED` or `RECOVERED` stays exactly where it was on that
    dimension."

    Design: Difficulty/priority_pair_validation_conflict/priority_business_temporal_beats_business_constraint_on_second_dispute_after_window
    """
    world = _world_disputed_chargeback_past_its_window()

    response = api.create_dispute(
        world["chargeback"]["id"],
        {
            "reason_code": "DUPLICATE_ASSESSMENT",
            "claimed_reversal_cents": 425_000,
            "narrative": "Second bite, filed after the window closed.",
        },
        make_vendor_headers(world["vendor"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED.value, 422)

    listing = api.list_disputes(
        officer_headers, params={"chargeback_id": world["chargeback"]["id"]}
    )
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 1, (
        f"the chargeback must still carry exactly one dispute, got total_count "
        f"{meta['total_count']}"
    )

    dispute = read_dispute(world["dispute"]["id"])
    assert dispute["status"] == "SUBMITTED", (
        f"the first dispute must remain SUBMITTED, got {dispute['status']}"
    )
    assert dispute["reason_code"] == "CARRIER_CAUSED", (
        f"the refused attempt must not overwrite the reason_code, got "
        f"{dispute['reason_code']}"
    )
    assert dispute["round_count"] == 1, (
        f"expected round_count 1, got {dispute['round_count']}"
    )

    chargeback = read_chargeback(world["chargeback"]["id"])
    assert chargeback["dispute_status"] == "OPEN", (
        f"expected dispute_status OPEN, got {chargeback['dispute_status']}"
    )
    assert chargeback["reversal_cents"] == 0, (
        f"expected reversal_cents 0, got {chargeback['reversal_cents']}"
    )
