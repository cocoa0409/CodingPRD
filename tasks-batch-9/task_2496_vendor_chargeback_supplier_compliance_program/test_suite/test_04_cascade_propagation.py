"""Numbered cascades: the chain of links one write fires downstream.

Assessment and deduction posting are each declared as a four-link cascade whose
later links are caused by the earlier ones, and every link has to land before the
call answers.  Each test below pins one grouping of links from one cascade.
"""
from test_helpers import (
    REQ_SHP_04,
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
    publish_guide,
    read_allocation,
    read_chargeback,
    read_deduction,
    read_shipment,
    read_vendor,
    read_violation,
    receive_shipment,
    set_clock,
    validate_success,
)

SHP_04_SCHEDULE = dict(REQ_SHP_04)


def _world_second_breach_awaiting_assessment() -> dict:
    """One supplier, one published edition holding TIER_1 SHP-04, a first SHP-04
    chargeback of 425000 already assessed, and a second fully evidenced SHP-04
    breach on 200 affected units still awaiting assessment."""
    set_clock("2026-08-01T00:00:00Z")
    vendor = create_vendor(
        vendor_code="V8008", legal_name="Chainlink Wholesale", payment_terms_days=60
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
    po1 = create_po(
        vendor["id"], po_number="PO-1", ordered_units=1000, unit_cost_cents=500
    )
    shipment1 = create_shipment(
        po1["id"], vendor["id"], asn_number="ASN-1", shipped_units=1000, carton_count=40
    )
    receive_shipment(shipment1["id"], 1000)
    violation1 = file_violation(
        shipment1["id"],
        requirement["id"],
        affected_units=400,
        affected_cartons=16,
        narrative="ASN late on load one.",
    )
    add_evidence(
        violation1["id"],
        kind="DOCUMENT",
        reference_uri="s3://evidence/shp-04/asn-1.pdf",
    )
    add_evidence(
        violation1["id"],
        kind="MEASUREMENT",
        reference_uri="s3://evidence/shp-04/gate-1.csv",
    )
    chargeback1 = assess_violation(
        violation1["id"], assessment_note="Load one late ASN."
    )

    po2 = create_po(
        vendor["id"], po_number="PO-2", ordered_units=1000, unit_cost_cents=500
    )
    shipment2 = create_shipment(
        po2["id"], vendor["id"], asn_number="ASN-2", shipped_units=1000, carton_count=40
    )
    receive_shipment(shipment2["id"], 1000)
    violation2 = file_violation(
        shipment2["id"],
        requirement["id"],
        affected_units=200,
        affected_cartons=8,
        narrative="ASN late on load two.",
    )
    add_evidence(
        violation2["id"],
        kind="DOCUMENT",
        reference_uri="s3://evidence/shp-04/asn-2.pdf",
    )
    add_evidence(
        violation2["id"],
        kind="MEASUREMENT",
        reference_uri="s3://evidence/shp-04/gate-2.csv",
    )
    return {
        "vendor": vendor,
        "requirement": requirement,
        "shipment2": shipment2,
        "violation2": violation2,
        "chargeback1": chargeback1,
    }


def _world_draft_deduction_ready_to_post() -> dict:
    """One supplier carrying a single TIER_1 SHP-04 chargeback of 425000, and a
    DRAFT deduction against invoice INV-77 holding one PENDING allocation of
    100000 cents against that chargeback."""
    set_clock("2026-08-01T00:00:00Z")
    vendor = create_vendor(
        vendor_code="V9009", legal_name="Netoff Provisions", payment_terms_days=60
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

    deduction = create_deduction(vendor["id"], invoice_reference="INV-77")
    allocation = add_allocation(deduction["id"], chargeback["id"], 100_000)
    return {
        "vendor": vendor,
        "chargeback": chargeback,
        "deduction": deduction,
        "allocation": allocation,
    }


# ---------------------------------------------------------------------------
# Assessment: violation -> chargeback -> supplier exposure -> alert flag
# ---------------------------------------------------------------------------
def test_assess_first_two_links_charge_the_violation_and_mint_the_chargeback(
    api, officer_headers
):
    """PRD §3.5: "A successful assessment is a four-link cascade. The first link
    moves the violation to `CHARGED` and lowers both the shipment's
    `open_violation_count` and the supplier's `open_violation_count` by one,
    restoring them to their pre-filing values just as a void would."
    PRD §3.5: "For a `TIER_1` requirement, `cost_recovery_cents` is the
    unit-recovery amount plus the handling-recovery amount — both components are
    charged."
    PRD §3.5: "Under `STANDARD`, `cost_recovery_cents` keeps the value the
    severity-tier branch produced, the raw amount is the flat fee plus that cost
    recovery, the requirement's `min_fee_cents` is applied as a floor to the raw
    amount, and the requirement's `cap_cents` is applied as a ceiling to the
    floored result; `gross_assessed_cents` is that floored-then-capped figure."

    Design: Difficulty/transitive_cascade/assess_cascade_depth_four_violation_to_vendor_exposure_alert
    """
    world = _world_second_breach_awaiting_assessment()

    response = api.assess_violation(
        world["violation2"]["id"],
        {
            "assessment_note": (
                "Load two late ASN; exposure now above the alert threshold."
            )
        },
        officer_headers,
    )
    chargeback2 = validate_success(response, 201)

    assert chargeback2["fixed_fee_cents"] == 200_000, (
        f"the flat component is copied from the pinned requirement, expected "
        f"200000, got {chargeback2['fixed_fee_cents']}"
    )
    assert chargeback2["cost_recovery_cents"] == 125_000, (
        f"TIER_1 charges unit recovery plus handling recovery, expected 125000, "
        f"got {chargeback2['cost_recovery_cents']}"
    )
    assert chargeback2["gross_assessed_cents"] == 325_000, (
        f"expected gross_assessed_cents 325000, got "
        f"{chargeback2['gross_assessed_cents']}"
    )

    violation2 = read_violation(world["violation2"]["id"])
    assert violation2["status"] == "CHARGED", (
        f"link one takes the violation to CHARGED, got {violation2['status']}"
    )

    shipment2 = read_shipment(world["shipment2"]["id"])
    assert shipment2["open_violation_count"] == 0, (
        f"link one restores the shipment's open_violation_count to its pre-filing "
        f"value, expected 0, got {shipment2['open_violation_count']}"
    )


def test_assess_last_two_links_recompute_exposure_and_raise_the_alert_flag(
    api, officer_headers
):
    """PRD §3.5: "The third link, caused by the second, recomputes the supplier's
    `open_chargeback_cents`. The fourth link, caused by the third, re-derives
    `exposure_alert_flag` as true exactly when `open_chargeback_cents` has reached
    500,000 cents or more, and increments the supplier's `version` by one."
    PRD §3.9: "`open_chargeback_cents` is the sum, over the supplier's chargebacks
    whose `settlement_status` is `ASSESSED` or `PARTIALLY_RECOVERED` only, of
    `gross_assessed_cents` less `reversal_cents` less `recovered_cents`;
    chargebacks that are `RECOVERED` or `WRITTEN_OFF` are excluded from this figure
    entirely."

    Design: Difficulty/transitive_cascade/assess_cascade_depth_four_violation_to_vendor_exposure_alert
    """
    world = _world_second_breach_awaiting_assessment()

    vendor_before = read_vendor(world["vendor"]["id"])
    assert vendor_before["exposure_alert_flag"] is False, (
        "the supplier must still be below the alert threshold before the second "
        f"assessment, got open_chargeback_cents "
        f"{vendor_before['open_chargeback_cents']}"
    )

    response = api.assess_violation(
        world["violation2"]["id"],
        {
            "assessment_note": (
                "Load two late ASN; exposure now above the alert threshold."
            )
        },
        officer_headers,
    )
    validate_success(response, 201)

    vendor = read_vendor(world["vendor"]["id"])
    assert vendor["open_chargeback_cents"] == 750_000, (
        f"exposure is recomputed from both chargebacks, expected 750000, got "
        f"{vendor['open_chargeback_cents']}"
    )
    assert vendor["exposure_alert_flag"] is True, (
        "exposure of 750000 cents has reached the 500,000 cent alert threshold, so "
        "exposure_alert_flag must read true"
    )
    assert vendor["open_violation_count"] == 0, (
        f"both findings have left the open set, expected 0, got "
        f"{vendor['open_violation_count']}"
    )

    chargeback1 = read_chargeback(world["chargeback1"]["id"])
    assert chargeback1["gross_assessed_cents"] == 425_000, (
        f"the earlier chargeback is not re-priced, expected 425000, got "
        f"{chargeback1['gross_assessed_cents']}"
    )


# ---------------------------------------------------------------------------
# Deduction posting: document -> allocation -> chargeback -> supplier exposure
# ---------------------------------------------------------------------------
def test_post_first_two_links_post_the_document_and_make_the_allocation_effective(
    api, accountant_headers
):
    """PRD §3.9: "Posting is a four-link cascade. The first link moves the
    deduction `DRAFT → POSTED` and stamps `posted_at` and `posted_by_user_id`. The
    second link, caused by the first, flips every child allocation `PENDING →
    EFFECTIVE` and stamps each one's `applied_at` with the posting instant."
    PRD §3.9: "Its `amount_cents` is the sum of `allocated_cents` over its
    allocations whose `effective_status` is anything other than `REVERSED`. Its
    `allocation_count` is simply the number of allocations it holds, reversed ones
    included."

    Design: Difficulty/transitive_cascade/deduction_post_cascade_depth_four_allocation_to_vendor_exposure
    """
    world = _world_draft_deduction_ready_to_post()

    response = api.post_deduction(world["deduction"]["id"], accountant_headers)
    validate_success(response, 200)

    deduction = read_deduction(world["deduction"]["id"])
    assert deduction["status"] == "POSTED", (
        f"link one moves the deduction to POSTED, got {deduction['status']}"
    )
    assert deduction["amount_cents"] == 100_000, (
        f"expected amount_cents 100000, got {deduction['amount_cents']}"
    )
    assert deduction["allocation_count"] == 1, (
        f"expected allocation_count 1, got {deduction['allocation_count']}"
    )
    assert deduction["over_allocated_cents"] == 0, (
        f"nothing is over-allocated, expected 0, got "
        f"{deduction['over_allocated_cents']}"
    )

    allocation = read_allocation(world["allocation"]["id"])
    assert allocation["effective_status"] == "EFFECTIVE", (
        f"link two flips the allocation PENDING to EFFECTIVE, got "
        f"{allocation['effective_status']}"
    )
    assert allocation["source_type"] == "DEDUCTION", (
        f"expected source_type DEDUCTION, got {allocation['source_type']}"
    )


def test_post_last_two_links_recover_the_chargeback_and_lower_supplier_exposure(
    api, accountant_headers
):
    """PRD §3.9: "The third link, caused by the second, makes each allocated
    chargeback recompute `recovered_cents` and `outstanding_cents`, set
    `deduction_posted` to true, and re-derive `settlement_status`. The fourth link,
    caused by the third, re-runs the exposure reconciliation over the supplier,
    lowering `open_chargeback_cents`, raising `recovered_lifetime_cents` and
    re-deriving `exposure_alert_flag`."
    PRD §3.9: "The `settlement_status` is then chosen by the first matching branch
    of four, tested in this order: the chargeback is `WRITTEN_OFF` when the net
    assessed balance is zero or below; otherwise `RECOVERED` when `recovered_cents`
    has reached or exceeded the net assessed balance; otherwise
    `PARTIALLY_RECOVERED` when `recovered_cents` is above zero; otherwise
    `ASSESSED`."

    Design: Difficulty/transitive_cascade/deduction_post_cascade_depth_four_allocation_to_vendor_exposure
    """
    world = _world_draft_deduction_ready_to_post()

    response = api.post_deduction(world["deduction"]["id"], accountant_headers)
    validate_success(response, 200)

    chargeback = read_chargeback(world["chargeback"]["id"])
    assert chargeback["recovered_cents"] == 100_000, (
        f"expected recovered_cents 100000, got {chargeback['recovered_cents']}"
    )
    assert chargeback["outstanding_cents"] == 325_000, (
        f"expected outstanding_cents 325000, got {chargeback['outstanding_cents']}"
    )
    assert chargeback["settlement_status"] == "PARTIALLY_RECOVERED", (
        f"expected settlement_status PARTIALLY_RECOVERED, got "
        f"{chargeback['settlement_status']}"
    )
    assert chargeback["deduction_posted"] is True, (
        "the chargeback holds an effective deduction-sourced allocation, so "
        "deduction_posted must read true"
    )

    vendor = read_vendor(world["vendor"]["id"])
    assert vendor["open_chargeback_cents"] == 325_000, (
        f"expected open_chargeback_cents 325000, got "
        f"{vendor['open_chargeback_cents']}"
    )
    assert vendor["recovered_lifetime_cents"] == 100_000, (
        f"expected recovered_lifetime_cents 100000, got "
        f"{vendor['recovered_lifetime_cents']}"
    )
    assert vendor["exposure_alert_flag"] is False, (
        "open exposure of 325000 cents is below the 500,000 cent alert threshold, "
        "so exposure_alert_flag must read false"
    )
