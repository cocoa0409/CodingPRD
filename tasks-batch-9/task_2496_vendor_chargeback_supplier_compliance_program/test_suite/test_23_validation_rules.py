"""Validation rules: the boundary ceilings that guard disputes, allocations,
assessment evidence and deduction posting.

Each ceiling is probed at the refusing side and, where the PRD makes equality
explicit, at the exactly-permitted side too, with the side effects of the refused
attempt shown to be absent.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_allocation,
    add_evidence,
    add_requirement,
    apply_cash,
    assess_violation,
    create_deduction,
    create_guide,
    create_po,
    create_shipment,
    create_vendor,
    file_violation,
    make_vendor_headers,
    publish_guide,
    read_allocation,
    read_chargeback,
    read_deduction,
    read_vendor,
    read_violation,
    receive_shipment,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]

LBL_01_TIER_1 = {
    "requirement_code": "LBL-01",
    "domain": "LABELING",
    "severity_tier": "TIER_1",
    "min_evidence_count": 2,
    "fixed_fee_cents": 25000,
    "per_unit_recovery_cents": 30,
    "handling_pct": 2.00,
    "min_fee_cents": 30000,
    "cap_cents": 40000,
}
DOC_03_TIER_3 = {
    "requirement_code": "DOC-03",
    "domain": "DOCUMENTATION",
    "severity_tier": "TIER_3",
    "min_evidence_count": 0,
    "fixed_fee_cents": 15000,
    "per_unit_recovery_cents": 10,
    "handling_pct": 1.00,
    "min_fee_cents": 15000,
    "cap_cents": 100000,
}


def _received_shipment(vendor_id, po_number="PO-1", asn_number="ASN-1"):
    """One order and one fully received shipment worth 500,000 cents."""
    po = create_po(
        vendor_id,
        po_number=po_number,
        ordered_units=1000,
        unit_cost_cents=500,
        ship_window_start="2026-08-06T00:00:00Z",
        ship_window_end="2026-08-09T00:00:00Z",
        must_arrive_by="2026-08-10T00:00:00Z",
    )
    shipment = create_shipment(
        po["id"], vendor_id, asn_number=asn_number, shipped_units=1000, carton_count=40
    )
    return receive_shipment(shipment["id"], 1000)


def _world_with_label_chargeback(vendor_code, legal_name):
    """A supplier carrying one assessed 38,000-cent TIER_1 chargeback."""
    set_clock("2026-08-01T00:00:00Z")
    vendor = create_vendor(
        vendor_code=vendor_code, legal_name=legal_name, payment_terms_days=30
    )
    guide = create_guide(
        guide_code="RG-2026-A",
        title="Domestic Routing Guide 2026-A",
        scope_code="ALL",
        effective_from="2026-08-05T00:00:00Z",
    )
    label_requirement = add_requirement(guide["id"], LBL_01_TIER_1)
    document_requirement = add_requirement(guide["id"], DOC_03_TIER_3)
    publish_guide(guide["id"])

    set_clock("2026-08-10T00:00:00Z")
    shipment = _received_shipment(vendor["id"])
    violation = file_violation(
        shipment["id"],
        label_requirement["id"],
        affected_units=100,
        affected_cartons=4,
        narrative="Unreadable GS1-128 labels.",
    )
    add_evidence(violation["id"], kind="PHOTO", reference_uri="s3://evidence/lbl/a.jpg")
    add_evidence(violation["id"], kind="SCAN", reference_uri="s3://evidence/lbl/b.txt")
    chargeback = assess_violation(violation["id"], assessment_note="Label scan failures.")
    assert chargeback["gross_assessed_cents"] == 38000
    return {
        "vendor": vendor,
        "shipment": shipment,
        "label_requirement": label_requirement,
        "document_requirement": document_requirement,
        "violation": violation,
        "chargeback": chargeback,
    }


def test_dispute_claim_above_the_net_assessment_is_refused_but_equality_passes(api):
    """PRD §3.6: "And the claim may not exceed what is still assessed:
    `claimed_reversal_cents` must be no greater than the chargeback's
    `gross_assessed_cents` less its `reversal_cents`, with an excess refused as
    `ERR_CLAIM_EXCEEDS_ASSESSMENT`."
    PRD §2.7: "30. Claim ceiling — the submitted `claimed_reversal_cents` does not
    exceed the chargeback's `gross_assessed_cents` less its `reversal_cents`,
    checked on both dispute creation and resubmission; otherwise
    `ERR_CLAIM_EXCEEDS_ASSESSMENT` (422)."
    PRD §3.6: "A successful opening creates the dispute in `SUBMITTED` with
    `round_count` 1, `submitted_at` from the current logical clock, `chargeback_id`
    taken from the path and `vendor_id` denormalised from the chargeback."
    PRD §3.6: "The same request moves the chargeback's `dispute_status` `NONE →
    OPEN` and increments the chargeback's `version` by one; its
    `settlement_status` is untouched, so a chargeback that was
    `PARTIALLY_RECOVERED` or `RECOVERED` stays exactly where it was on that
    dimension."

    Design: Corner/validations/corner_dispute_claim_above_the_net_assessment_is_rejected
    """
    world = _world_with_label_chargeback("V2040", "Overclaim Outfitters")
    vendor_id = world["vendor"]["id"]
    chargeback_id = world["chargeback"]["id"]
    supplier_headers = make_vendor_headers(vendor_id)

    over_by_one = api.create_dispute(
        chargeback_id,
        {
            "reason_code": "FEE_MISCALCULATED",
            "claimed_reversal_cents": 38001,
            "narrative": "We believe the whole assessment plus one cent is wrong.",
        },
        supplier_headers,
    )
    validate_error(over_by_one, ApiErrorId.ERR_CLAIM_EXCEEDS_ASSESSMENT.value)

    assert read_chargeback(chargeback_id)["dispute_status"] == "NONE", (
        "a refused claim must leave the adjudication dimension untouched"
    )
    _, meta = validate_paginated(
        api.list_disputes(OFFICER, params={"chargeback_id": chargeback_id})
    )
    assert meta["total_count"] == 0, (
        f"the refused attempt must not persist a dispute, got {meta['total_count']}"
    )

    at_the_ceiling = api.create_dispute(
        chargeback_id,
        {
            "reason_code": "FEE_MISCALCULATED",
            "claimed_reversal_cents": 38000,
            "narrative": "We believe the whole assessment is wrong.",
        },
        supplier_headers,
    )
    dispute = validate_success(at_the_ceiling, 201)

    assert dispute["status"] == "SUBMITTED"
    assert dispute["claimed_reversal_cents"] == 38000, (
        "a claim exactly equal to the net assessment is inside the ceiling"
    )
    assert dispute["round_count"] == 1
    assert read_chargeback(chargeback_id)["dispute_status"] == "OPEN"


def test_allocation_exactly_at_outstanding_is_accepted_and_stays_pending(api):
    """PRD §3.9: "The amount may not exceed the target chargeback's
    `outstanding_cents`, with exact equality permitted and an excess refused as
    `ERR_ALLOCATION_EXCEEDS_OUTSTANDING`. A new allocation is stored with
    `source_type` `DEDUCTION`, `effective_status` `PENDING`, `remittance_reference`
    null, `applied_at` null and `applied_by_user_id` from the acting accountant,
    and it raises the deduction's `amount_cents` by the allocated amount and its
    `allocation_count` by one. A pending allocation contributes nothing to any
    chargeback's recovery; it is an intention, not a recovery."
    PRD §2.7: "31. Allocation ceiling — the submitted `allocated_cents` does not
    exceed the target chargeback's `outstanding_cents`, with equality permitted;
    otherwise `ERR_ALLOCATION_EXCEEDS_OUTSTANDING` (422)."
    PRD §3.9: "The deduction opens in `DRAFT` with `amount_cents` 0,
    `allocation_count` 0, `over_allocated_cents` 0, and `posted_at`,
    `posted_by_user_id`, `reversed_at` and `reversal_reason` all null; creating it
    increments the supplier's `version` by one, which is exactly why a client
    drafting a second deduction must re-read the supplier first."

    Design: Corner/validations/corner_allocation_at_exactly_outstanding_passes
    """
    world = _world_with_label_chargeback("V2041", "Exactfit Apparel")
    vendor_id = world["vendor"]["id"]
    chargeback_id = world["chargeback"]["id"]

    assert read_chargeback(chargeback_id)["outstanding_cents"] == 38000
    deduction = create_deduction(vendor_id, invoice_reference="INV-EXACT")

    response = api.create_allocation(
        deduction["id"], {"chargeback_id": chargeback_id, "allocated_cents": 38000}, ACCOUNTANT
    )
    allocation = validate_success(response, 201)

    assert allocation["allocated_cents"] == 38000, (
        "earmarking exactly the outstanding balance sits on the permitted boundary"
    )
    assert allocation["effective_status"] == "PENDING"
    assert allocation["source_type"] == "DEDUCTION"
    assert allocation.get("applied_at") is None, (
        "a drafted earmark has not been applied to anything yet"
    )
    assert read_allocation(allocation["id"])["effective_status"] == "PENDING"

    reread_deduction = read_deduction(deduction["id"])
    assert reread_deduction["amount_cents"] == 38000
    assert reread_deduction["allocation_count"] == 1
    assert reread_deduction["status"] == "DRAFT"

    chargeback = read_chargeback(chargeback_id)
    assert chargeback["recovered_cents"] == 0, (
        "an intention is not a recovery, so nothing has been recovered yet"
    )
    assert chargeback["outstanding_cents"] == 38000
    assert chargeback["settlement_status"] == "ASSESSED"

    assert read_vendor(vendor_id)["open_chargeback_cents"] == 38000


def test_evidence_sufficiency_rung_passes_when_the_requirement_demands_no_evidence(api):
    """PRD §2.7: "10. Evidence sufficiency — on chargeback assessment, the
    violation's `evidence_count` is at least the pinned requirement's
    `min_evidence_count`; otherwise `ERR_EVIDENCE_INSUFFICIENT` (422). When
    `min_evidence_count` is 0 the violation was born `EVIDENCE_COMPLETE` and this
    rung passes on an empty evidence set."
    PRD §3.5: "A violation still in `DETECTED` deliberately passes that rung and is
    refused instead with `ERR_EVIDENCE_INSUFFICIENT` (422), because `DETECTED`
    means the pinned requirement's `min_evidence_count` has not yet been met and
    the caller should be told that rather than a generic conflict."
    PRD §3.5: "The first link moves the violation to `CHARGED` and lowers both the
    shipment's `open_violation_count` and the supplier's `open_violation_count` by
    one, restoring them to their pre-filing values just as a void would."
    PRD §3.5: "`evidence_at_assessment_count` as a snapshot of the violation's
    `evidence_count` at this instant"
    PRD §3.5: "For a `TIER_3` requirement, `cost_recovery_cents` is zero and only
    the flat fee survives."

    Design: Corner/validations/corner_evidence_sufficiency_applies_only_when_the_requirement_demands_evidence
    """
    set_clock("2026-08-01T00:00:00Z")
    vendor = create_vendor(
        vendor_code="V2042", legal_name="Evidencegate Enterprises", payment_terms_days=30
    )
    guide = create_guide(
        guide_code="RG-2026-A",
        title="Domestic Routing Guide 2026-A",
        scope_code="ALL",
        effective_from="2026-08-05T00:00:00Z",
    )
    label_requirement = add_requirement(guide["id"], LBL_01_TIER_1)
    document_requirement = add_requirement(guide["id"], DOC_03_TIER_3)
    publish_guide(guide["id"])

    set_clock("2026-08-10T00:00:00Z")
    shipment = _received_shipment(vendor["id"])

    # LBL-01 demands two artefacts and has only one, so it is still DETECTED.
    label_violation = file_violation(
        shipment["id"],
        label_requirement["id"],
        affected_units=100,
        affected_cartons=4,
        narrative="Unreadable GS1-128 labels.",
    )
    add_evidence(label_violation["id"], kind="PHOTO", reference_uri="s3://evidence/lbl/a.jpg")
    # DOC-03 demands nothing, so it was born assessable with an empty set.
    document_violation = file_violation(
        shipment["id"],
        document_requirement["id"],
        affected_units=100,
        affected_cartons=4,
        narrative="Missing packing list.",
    )

    refused = api.assess_violation(
        label_violation["id"], {"assessment_note": "Attempt on a thin file."}, OFFICER
    )
    validate_error(refused, ApiErrorId.ERR_EVIDENCE_INSUFFICIENT.value)

    still_detected = read_violation(label_violation["id"])
    assert still_detected["status"] == "DETECTED"
    assert still_detected["evidence_count"] == 1
    _, meta = validate_paginated(
        api.list_chargebacks(OFFICER, params={"violation_id": label_violation["id"]})
    )
    assert meta["total_count"] == 0, (
        f"the refused assessment must mint no chargeback, got {meta['total_count']}"
    )

    accepted = api.assess_violation(
        document_violation["id"], {"assessment_note": "No evidence demanded."}, OFFICER
    )
    document_chargeback = validate_success(accepted, 201)

    charged = read_violation(document_violation["id"])
    assert charged["status"] == "CHARGED", (
        "a requirement demanding no evidence clears the sufficiency rung on an "
        "empty set"
    )
    assert charged["evidence_count"] == 0
    assert document_chargeback["evidence_at_assessment_count"] == 0
    assert document_chargeback["gross_assessed_cents"] == 15000

    supplier = read_vendor(vendor["id"])
    assert supplier["open_chargeback_cents"] == 15000
    assert supplier["open_violation_count"] == 1, (
        "only the still-DETECTED label finding remains open, got "
        f"{supplier['open_violation_count']}"
    )


def test_posting_is_refused_once_recovery_elsewhere_drops_the_exposure(api):
    """PRD §3.9: "And the document may not net more than the supplier currently
    owes: the deduction's `amount_cents` must be no greater than the supplier's
    `open_chargeback_cents` at the instant of posting, with equality permitted and
    an excess refused as `ERR_DEDUCTION_EXCEEDS_EXPOSURE`."
    PRD §2.7: "33. Exposure ceiling — a deduction's `amount_cents` does not exceed
    the vendor's `open_chargeback_cents` at the instant of posting, with equality
    permitted; otherwise `ERR_DEDUCTION_EXCEEDS_EXPOSURE` (422)."
    PRD §3.9: "`open_chargeback_cents` is the sum, over the supplier's chargebacks
    whose `settlement_status` is `ASSESSED` or `PARTIALLY_RECOVERED` only, of
    `gross_assessed_cents` less `reversal_cents` less `recovered_cents`;
    chargebacks that are `RECOVERED` or `WRITTEN_OFF` are excluded from this figure
    entirely."

    Design: Corner/validations/corner_posting_is_refused_when_the_aggregate_exceeds_current_exposure
    """
    world = _world_with_label_chargeback("V2043", "Aggregate Apparel")
    vendor_id = world["vendor"]["id"]
    label_chargeback_id = world["chargeback"]["id"]

    document_violation = file_violation(
        world["shipment"]["id"],
        world["document_requirement"]["id"],
        affected_units=100,
        affected_cartons=4,
        narrative="Missing packing list.",
    )
    document_chargeback = assess_violation(
        document_violation["id"], assessment_note="Missing packing list."
    )
    assert document_chargeback["gross_assessed_cents"] == 15000
    assert read_vendor(vendor_id)["open_chargeback_cents"] == 53000

    deduction = create_deduction(vendor_id, invoice_reference="INV-AGG")
    allocation = add_allocation(deduction["id"], label_chargeback_id, 38000)

    # Cash arrives against the same chargeback first, retiring it outright and
    # shrinking what the supplier still owes below the drafted netting.
    apply_cash(label_chargeback_id, 38000, remittance_reference="WIRE-9001")
    assert read_vendor(vendor_id)["open_chargeback_cents"] == 15000

    refused = api.post_deduction(deduction["id"], ACCOUNTANT)
    validate_error(refused, ApiErrorId.ERR_DEDUCTION_EXCEEDS_EXPOSURE.value)

    unposted = read_deduction(deduction["id"])
    assert unposted["status"] == "DRAFT"
    assert unposted.get("posted_at") is None
    assert read_allocation(allocation["id"])["effective_status"] == "PENDING", (
        "a refused posting must not flip its earmarks effective"
    )

    settled = read_chargeback(label_chargeback_id)
    assert settled["settlement_status"] == "RECOVERED"
    assert settled["recovered_cents"] == 38000
    assert read_chargeback(document_chargeback["id"])["settlement_status"] == "ASSESSED"

    supplier = read_vendor(vendor_id)
    assert supplier["open_chargeback_cents"] == 15000
    assert supplier["recovered_lifetime_cents"] == 38000
