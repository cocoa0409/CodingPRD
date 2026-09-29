"""Threshold arithmetic: the exact value on a boundary and the value one notch off.

Every comparison exercised here is declared inclusive, so the value sitting exactly
on the limit must pass and only the next value along may fail.
"""
from test_helpers import (
    REQ_DOC_03,
    REQ_SHP_04,
    ApiErrorId,
    add_evidence,
    add_requirement,
    assess_violation,
    chargeback_version,
    create_guide,
    create_po,
    create_scorecard,
    create_shipment,
    create_vendor,
    file_violation,
    publish_guide,
    read_chargeback,
    read_scorecard,
    read_shipment,
    read_vendor,
    read_violation,
    receive_shipment,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

SHP_04_SCHEDULE = dict(REQ_SHP_04)
DOC_03_SCHEDULE = dict(REQ_DOC_03)


def _world_two_orders_straddling_the_fill_floor() -> dict:
    """One supplier with two 1000-unit orders, both received on their deadline: the
    first at 980 units (a fill of 98.00, exactly the tolerated floor) and the second
    at 979 units (97.90, one unit short of it). The scorecard takes all three
    tolerance defaults."""
    set_clock("2026-08-01T00:00:00Z")
    vendor = create_vendor(
        vendor_code="V1201", legal_name="Threshold Goods", payment_terms_days=45
    )
    po1 = create_po(
        vendor["id"],
        po_number="PO-1",
        ordered_units=1000,
        unit_cost_cents=500,
        ship_window_start="2026-08-06T00:00:00Z",
        ship_window_end="2026-08-09T00:00:00Z",
        must_arrive_by="2026-08-10T00:00:00Z",
    )
    po2 = create_po(
        vendor["id"],
        po_number="PO-2",
        ordered_units=1000,
        unit_cost_cents=500,
        ship_window_start="2026-08-06T00:00:00Z",
        ship_window_end="2026-08-10T00:00:00Z",
        must_arrive_by="2026-08-11T00:00:00Z",
    )
    shipment1 = create_shipment(
        po1["id"], vendor["id"], asn_number="ASN-1", shipped_units=980, carton_count=40
    )
    shipment2 = create_shipment(
        po2["id"], vendor["id"], asn_number="ASN-2", shipped_units=979, carton_count=40
    )

    set_clock("2026-08-10T00:00:00Z")
    receive_shipment(shipment1["id"], 980)

    set_clock("2026-08-11T00:00:00Z")
    receive_shipment(shipment2["id"], 979)

    set_clock("2026-09-01T00:00:00Z")
    scorecard = create_scorecard(
        vendor["id"],
        period_code="2026-08",
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-31T00:00:00Z",
    )
    return {"vendor": vendor, "scorecard": scorecard}


def _world_chargeback_outstanding_425000() -> dict:
    """One supplier with a single TIER_1 SHP-04 chargeback whose figures stand at
    gross 425000, nothing reversed and nothing recovered, so outstanding_cents is
    exactly 425000."""
    set_clock("2026-08-01T00:00:00Z")
    vendor = create_vendor(
        vendor_code="V1202", legal_name="Exactpay Mercantile", payment_terms_days=60
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
    return {"vendor": vendor, "chargeback": chargeback}


def _world_receipt_under_a_documentation_requirement(min_evidence_count: int) -> dict:
    """One supplier with a published edition carrying TIER_3 DOC-03 priced at a flat
    15000, and a 1000-unit / 500-cent receipt not yet cited for anything. The number
    of evidence items the requirement demands is the caller's choice."""
    set_clock("2026-08-01T00:00:00Z")
    vendor = create_vendor(
        vendor_code="V1203", legal_name="Paperless Provisions", payment_terms_days=30
    )
    guide = create_guide(
        guide_code="RG-2026-A",
        title="Domestic Routing Guide 2026-A",
        scope_code="ALL",
        effective_from="2026-08-05T00:00:00Z",
    )
    requirement = add_requirement(
        guide["id"], DOC_03_SCHEDULE, min_evidence_count=min_evidence_count
    )
    publish_guide(guide["id"])

    set_clock("2026-08-10T00:00:00Z")
    po = create_po(
        vendor["id"], po_number="PO-1", ordered_units=1000, unit_cost_cents=500
    )
    shipment = create_shipment(
        po["id"], vendor["id"], asn_number="ASN-1", shipped_units=1000, carton_count=40
    )
    shipment = receive_shipment(shipment["id"], 1000)
    return {"vendor": vendor, "requirement": requirement, "shipment": shipment}


def _world_two_suppliers_straddling_the_alert_threshold() -> dict:
    """Two suppliers driven by identical machinery that differs only in affected
    units: 549 for the first, 550 for the second. Each carries one 1000-unit /
    500-cent receipt, so the handling component is 25000, and one fully evidenced
    TIER_1 SHP-04 finding awaiting assessment."""
    set_clock("2026-08-01T00:00:00Z")
    vendor_a = create_vendor(
        vendor_code="V1204A", legal_name="Justunder Supply", payment_terms_days=60
    )
    vendor_b = create_vendor(
        vendor_code="V1204B", legal_name="Dead-On Supply", payment_terms_days=60
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
    violations = {}
    for key, vendor, affected_units in (
        ("a", vendor_a, 549),
        ("b", vendor_b, 550),
    ):
        po = create_po(
            vendor["id"],
            po_number=f"PO-{key.upper()}1",
            ordered_units=1000,
            unit_cost_cents=500,
        )
        shipment = create_shipment(
            po["id"],
            vendor["id"],
            asn_number=f"ASN-{key.upper()}1",
            shipped_units=1000,
            carton_count=40,
        )
        receive_shipment(shipment["id"], 1000)
        violation = file_violation(
            shipment["id"],
            requirement["id"],
            affected_units=affected_units,
            affected_cartons=22,
            narrative=(
                f"Routing guide shipment breach, {affected_units} units affected."
            ),
        )
        add_evidence(
            violation["id"],
            kind="DOCUMENT",
            reference_uri=f"s3://evidence/{key}/asn.pdf",
        )
        add_evidence(
            violation["id"],
            kind="MEASUREMENT",
            reference_uri=f"s3://evidence/{key}/count.csv",
        )
        violations[key] = violation

    return {
        "vendor_a": vendor_a,
        "vendor_b": vendor_b,
        "violation_a": violations["a"],
        "violation_b": violations["b"],
    }


# ---------------------------------------------------------------------------
# The in-full fill floor
# ---------------------------------------------------------------------------
def test_order_landing_exactly_on_the_fill_floor_counts_as_in_full(
    api, officer_headers
):
    """PRD §3.7: "It is in full when its fill percentage reaches the tolerated
    floor: the order's fill percentage is 100 multiplied by its `received_units`,
    divided by its `ordered_units`, rounded half up to two decimals, and the order
    passes when that value is at or above 100.00 less `fill_tolerance_pct` — at
    exactly the floor the order passes."
    PRD §3.7: "`on_time_count`, `in_full_count` and `otif_count` are the counts of
    orders passing the first test, the second test and both tests respectively."

    Design: Difficulty/boundary_precision_check/boundary_in_full_at_exactly_the_fill_tolerance_threshold
    """
    world = _world_two_orders_straddling_the_fill_floor()

    response = api.measure_scorecard(
        world["scorecard"]["id"], {"measurement_variant": "ORDER_WEIGHTED"}, officer_headers
    )
    scorecard = validate_success(response, 200)

    assert scorecard["fill_tolerance_pct"] == 2.00, (
        f"the tolerance default puts the in-full floor at 98.00, expected "
        f"fill_tolerance_pct 2.00, got {scorecard['fill_tolerance_pct']}"
    )
    assert scorecard["measured_po_count"] == 2, (
        f"expected measured_po_count 2, got {scorecard['measured_po_count']}"
    )
    assert scorecard["on_time_count"] == 2, (
        f"both orders arrived on their deadline, expected on_time_count 2, got "
        f"{scorecard['on_time_count']}"
    )
    assert scorecard["in_full_count"] == 1, (
        f"the order sitting exactly on the 98.00 floor passes and the one at 97.90 "
        f"does not, expected in_full_count 1, got {scorecard['in_full_count']}"
    )
    assert scorecard["otif_count"] == 1, (
        f"expected otif_count 1, got {scorecard['otif_count']}"
    )
    assert scorecard["on_time_pct"] == 100.00, (
        f"expected on_time_pct 100.00, got {scorecard['on_time_pct']}"
    )
    assert scorecard["status"] == "MEASURED", (
        f"expected status MEASURED, got {scorecard['status']}"
    )


def test_order_one_unit_below_the_fill_floor_is_left_out_of_the_headline_figures(
    api, officer_headers
):
    """PRD §3.7: "It is in full when its fill percentage reaches the tolerated
    floor: the order's fill percentage is 100 multiplied by its `received_units`,
    divided by its `ordered_units`, rounded half up to two decimals, and the order
    passes when that value is at or above 100.00 less `fill_tolerance_pct` — at
    exactly the floor the order passes."
    PRD §3.7: "Under `ORDER_WEIGHTED` the rule is round-then-aggregate: each order's
    fill percentage is rounded to two decimals first, those already-rounded
    per-order values are summed, the sum is divided by `measured_po_count`, and the
    average is rounded half up to two decimals again."
    PRD §3.7: "The composite is 0.60 multiplied by `otif_pct` plus 0.40 multiplied
    by `fill_rate_pct`, rounded half up to two decimals — on-time-in-full
    performance carries three fifths of the weight and raw fill rate the remaining
    two fifths."

    Design: Difficulty/boundary_precision_check/boundary_in_full_at_exactly_the_fill_tolerance_threshold
    """
    world = _world_two_orders_straddling_the_fill_floor()

    response = api.measure_scorecard(
        world["scorecard"]["id"], {"measurement_variant": "ORDER_WEIGHTED"}, officer_headers
    )
    validate_success(response, 200)

    scorecard = read_scorecard(world["scorecard"]["id"])
    assert scorecard["otif_pct"] == 50.00, (
        f"only one of the two orders clears both tests, expected otif_pct 50.00, got "
        f"{scorecard['otif_pct']}"
    )
    assert scorecard["fill_rate_pct"] == 97.95, (
        f"the two rounded per-order fills average to 97.95, got "
        f"{scorecard['fill_rate_pct']}"
    )
    assert scorecard["composite_score"] == 69.18, (
        f"expected composite_score 69.18, got {scorecard['composite_score']}"
    )
    assert scorecard["measured_po_count"] == 2, (
        f"the failing order stays in scope, expected measured_po_count 2, got "
        f"{scorecard['measured_po_count']}"
    )


# ---------------------------------------------------------------------------
# The cash ceiling at outstanding_cents
# ---------------------------------------------------------------------------
def test_cash_one_cent_over_the_outstanding_balance_is_refused(api, accountant_headers):
    """PRD §3.9: "The chargeback's `settlement_status` must not be `WRITTEN_OFF`,
    refused otherwise with `ERR_CHARGEBACK_WRITTEN_OFF`, and the amount may not
    exceed the chargeback's `outstanding_cents`: exact equality is accepted and
    drives the chargeback to full recovery, while one cent more is refused with
    `ERR_OVER_APPLICATION`."
    PRD §2.7: "Cash ceiling — the submitted `amount_cents` does not exceed the
    target chargeback's `outstanding_cents`. Exact equality is accepted and drives
    the chargeback to `RECOVERED`; one cent more than `outstanding_cents` is refused
    with `ERR_OVER_APPLICATION` (422)."

    Design: Difficulty/boundary_precision_check/boundary_cash_application_exact_payoff_versus_one_cent_over
    """
    world = _world_chargeback_outstanding_425000()
    chargeback_id = world["chargeback"]["id"]

    before = read_chargeback(chargeback_id)
    assert before["outstanding_cents"] == 425_000, (
        f"the balance the ceiling is measured against must be 425000, got "
        f"{before['outstanding_cents']}"
    )

    response = api.apply_cash(
        chargeback_id,
        {
            "remittance_reference": "RA-OVER",
            "amount_cents": 425_001,
            "expected_chargeback_version": chargeback_version(chargeback_id),
        },
        accountant_headers,
    )
    validate_error(response, ApiErrorId.ERR_OVER_APPLICATION.value, 422)

    listing = api.list_allocations(
        accountant_headers, params={"chargeback_id": chargeback_id}
    )
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 0, (
        f"the refused remittance must write no allocation row, got total_count "
        f"{meta['total_count']}"
    )

    chargeback = read_chargeback(chargeback_id)
    assert chargeback["recovered_cents"] == 0, (
        f"expected recovered_cents 0, got {chargeback['recovered_cents']}"
    )
    assert chargeback["settlement_status"] == "ASSESSED", (
        f"expected settlement_status ASSESSED, got "
        f"{chargeback['settlement_status']}"
    )


def test_cash_at_exactly_the_outstanding_balance_pays_the_chargeback_off(
    api, accountant_headers
):
    """PRD §3.9: "The chargeback's `settlement_status` must not be `WRITTEN_OFF`,
    refused otherwise with `ERR_CHARGEBACK_WRITTEN_OFF`, and the amount may not
    exceed the chargeback's `outstanding_cents`: exact equality is accepted and
    drives the chargeback to full recovery, while one cent more is refused with
    `ERR_OVER_APPLICATION`."
    PRD §3.9: "Because the second branch tests "reached or exceeded" rather than
    "exceeded", an exact-payoff cash application lands on `RECOVERED` and not on
    `PARTIALLY_RECOVERED`."
    PRD §3.9: "The application creates an allocation with `source_type` `CASH`,
    `deduction_id` null, `effective_status` `EFFECTIVE` and `applied_at` stamped
    from the logical clock at creation, storing the applied amount in the
    allocation's `allocated_cents` field and the supplied reference in
    `remittance_reference`."

    Design: Difficulty/boundary_precision_check/boundary_cash_application_exact_payoff_versus_one_cent_over
    """
    world = _world_chargeback_outstanding_425000()
    chargeback_id = world["chargeback"]["id"]

    response = api.apply_cash(
        chargeback_id,
        {
            "remittance_reference": "RA-EXACT",
            "amount_cents": 425_000,
            "expected_chargeback_version": chargeback_version(chargeback_id),
        },
        accountant_headers,
    )
    allocation = validate_success(response, 201)

    assert allocation["allocated_cents"] == 425_000, (
        f"expected allocated_cents 425000, got {allocation['allocated_cents']}"
    )
    assert allocation["source_type"] == "CASH", (
        f"expected source_type CASH, got {allocation['source_type']}"
    )
    assert allocation["effective_status"] == "EFFECTIVE", (
        f"a cash allocation is effective at creation, got "
        f"{allocation['effective_status']}"
    )

    listing = api.list_allocations(
        accountant_headers, params={"chargeback_id": chargeback_id}
    )
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 1, (
        f"expected exactly one allocation row, got total_count {meta['total_count']}"
    )

    chargeback = read_chargeback(chargeback_id)
    assert chargeback["recovered_cents"] == 425_000, (
        f"expected recovered_cents 425000, got {chargeback['recovered_cents']}"
    )
    assert chargeback["outstanding_cents"] == 0, (
        f"expected outstanding_cents 0, got {chargeback['outstanding_cents']}"
    )
    assert chargeback["settlement_status"] == "RECOVERED", (
        f"an exact payoff reaches the net assessed balance, so the branch tested "
        f"with 'reached or exceeded' selects RECOVERED, got "
        f"{chargeback['settlement_status']}"
    )
    assert chargeback["deduction_posted"] is False, (
        "the recovery came through the cash channel, so deduction_posted must read "
        "false"
    )

    vendor = read_vendor(world["vendor"]["id"])
    assert vendor["open_chargeback_cents"] == 0, (
        f"expected open_chargeback_cents 0, got {vendor['open_chargeback_cents']}"
    )
    assert vendor["recovered_lifetime_cents"] == 425_000, (
        f"expected recovered_lifetime_cents 425000, got "
        f"{vendor['recovered_lifetime_cents']}"
    )
    assert vendor["refund_due_cents"] == 0, (
        f"nothing was over-recovered, expected refund_due_cents 0, got "
        f"{vendor['refund_due_cents']}"
    )


# ---------------------------------------------------------------------------
# The degenerate lower bound of the evidence requirement
# ---------------------------------------------------------------------------
def test_zero_min_evidence_count_births_the_violation_evidence_complete(
    api, inspector_headers
):
    """PRD §3.4: "Its initial state depends on the requirement it cites: when the
    pinned requirement's `min_evidence_count` is 0 the violation is born directly in
    `EVIDENCE_COMPLETE`, and otherwise it starts in `DETECTED`."
    PRD §3.2: "`min_evidence_count`, an integer from 0 to 5, is the number of
    evidence items that must exist before a breach of this requirement may be
    assessed; a value of 0 means evidence is optional for this requirement."
    PRD §3.4: "Each capture raises the violation's `evidence_count` by one and the
    shipment's `evidence_capture_count` by one."

    Design: Difficulty/boundary_precision_check/boundary_zero_min_evidence_count_admits_an_empty_evidence_set
    """
    world = _world_receipt_under_a_documentation_requirement(0)

    response = api.create_violation(
        world["shipment"]["id"],
        {
            "requirement_id": world["requirement"]["id"],
            "affected_units": 100,
            "affected_cartons": 4,
            "narrative": "Packing list absent from the lead carton.",
        },
        inspector_headers,
    )
    violation = validate_success(response, 201)

    assert violation["status"] == "EVIDENCE_COMPLETE", (
        f"a requirement demanding no evidence is already satisfied by the empty set, "
        f"so the finding is born EVIDENCE_COMPLETE, got {violation['status']}"
    )
    assert violation["evidence_count"] == 0, (
        f"expected evidence_count 0, got {violation['evidence_count']}"
    )

    listing = api.list_violation_evidence(violation["id"], inspector_headers)
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 0, (
        f"no evidence item was captured, got total_count {meta['total_count']}"
    )

    shipment = read_shipment(world["shipment"]["id"])
    assert shipment["evidence_capture_count"] == 0, (
        f"expected evidence_capture_count 0, got "
        f"{shipment['evidence_capture_count']}"
    )


def test_assessment_on_an_empty_evidence_set_succeeds_when_none_is_required(
    api, officer_headers
):
    """PRD §2.7: "Evidence sufficiency — on chargeback assessment, the violation's
    `evidence_count` is at least the pinned requirement's `min_evidence_count`;
    otherwise `ERR_EVIDENCE_INSUFFICIENT` (422). When `min_evidence_count` is 0 the
    violation was born `EVIDENCE_COMPLETE` and this rung passes on an empty evidence
    set."
    PRD §3.5: "Under `GRACE_FIRST_OCCURRENCE`, `cost_recovery_cents` is forced to
    zero and the `min_fee_cents` floor is not applied at all, so
    `gross_assessed_cents` is simply whichever is smaller of the flat fee and
    `cap_cents`."
    PRD §3.5: "`evidence_at_assessment_count` as a snapshot of the violation's
    `evidence_count` at this instant"

    Design: Difficulty/boundary_precision_check/boundary_zero_min_evidence_count_admits_an_empty_evidence_set
    """
    world = _world_receipt_under_a_documentation_requirement(0)
    violation = file_violation(
        world["shipment"]["id"],
        world["requirement"]["id"],
        affected_units=100,
        affected_cartons=4,
        narrative="Packing list absent from the lead carton.",
    )

    response = api.assess_violation(
        violation["id"],
        {
            "assessment_note": (
                "Documentation miss; no photographic evidence required."
            )
        },
        officer_headers,
    )
    chargeback = validate_success(response, 201)

    assert chargeback["evidence_at_assessment_count"] == 0, (
        f"expected evidence_at_assessment_count 0, got "
        f"{chargeback['evidence_at_assessment_count']}"
    )
    assert chargeback["assessment_variant"] == "GRACE_FIRST_OCCURRENCE", (
        f"a TIER_3 requirement with no matching prior chargeback is priced under "
        f"grace, got {chargeback['assessment_variant']}"
    )
    assert chargeback["fixed_fee_cents"] == 15_000, (
        f"expected fixed_fee_cents 15000, got {chargeback['fixed_fee_cents']}"
    )
    assert chargeback["cost_recovery_cents"] == 0, (
        f"grace forces cost recovery to zero, got "
        f"{chargeback['cost_recovery_cents']}"
    )
    assert chargeback["gross_assessed_cents"] == 15_000, (
        f"expected gross_assessed_cents 15000, got "
        f"{chargeback['gross_assessed_cents']}"
    )

    charged = read_violation(violation["id"])
    assert charged["status"] == "CHARGED", (
        f"expected status CHARGED, got {charged['status']}"
    )


def test_one_required_evidence_item_leaves_the_violation_detected_and_unassessable(
    api, inspector_headers, officer_headers
):
    """PRD §3.4: "Its initial state depends on the requirement it cites: when the
    pinned requirement's `min_evidence_count` is 0 the violation is born directly in
    `EVIDENCE_COMPLETE`, and otherwise it starts in `DETECTED`."
    PRD §3.5: "A violation still in `DETECTED` deliberately passes that rung and is
    refused instead with `ERR_EVIDENCE_INSUFFICIENT` (422), because `DETECTED` means
    the pinned requirement's `min_evidence_count` has not yet been met and the caller
    should be told that rather than a generic conflict."

    Design: Difficulty/boundary_precision_check/boundary_zero_min_evidence_count_admits_an_empty_evidence_set
    """
    world = _world_receipt_under_a_documentation_requirement(1)

    filing = api.create_violation(
        world["shipment"]["id"],
        {
            "requirement_id": world["requirement"]["id"],
            "affected_units": 100,
            "affected_cartons": 4,
            "narrative": "Packing list absent from the lead carton.",
        },
        inspector_headers,
    )
    violation = validate_success(filing, 201)
    assert violation["status"] == "DETECTED", (
        f"one required item is one more than the empty set holds, so the finding "
        f"starts in DETECTED, got {violation['status']}"
    )
    assert violation["evidence_count"] == 0, (
        f"expected evidence_count 0, got {violation['evidence_count']}"
    )

    response = api.assess_violation(
        violation["id"],
        {
            "assessment_note": (
                "Documentation miss; no photographic evidence required."
            )
        },
        officer_headers,
    )
    validate_error(response, ApiErrorId.ERR_EVIDENCE_INSUFFICIENT.value, 422)

    unchanged = read_violation(violation["id"])
    assert unchanged["status"] == "DETECTED", (
        f"the refused assessment leaves the finding in DETECTED, got "
        f"{unchanged['status']}"
    )


# ---------------------------------------------------------------------------
# The supplier exposure alert threshold
# ---------------------------------------------------------------------------
def test_exposure_one_cent_band_below_the_alert_threshold_leaves_the_flag_down(
    api, officer_headers
):
    """PRD §3.1: "`exposure_alert_flag` is recomputed every single time
    `open_chargeback_cents` changes and is true exactly when that figure has reached
    500,000 cents — five thousand currency units of unrecovered assessment — or
    more."
    PRD §3.5: "For a `TIER_1` requirement, `cost_recovery_cents` is the unit-recovery
    amount plus the handling-recovery amount — both components are charged."
    PRD §3.5: "Otherwise the variant is `STANDARD` — which is always the case for a
    `TIER_1` requirement, and is also the case for a `TIER_2` or `TIER_3` requirement
    once a matching prior chargeback exists inside that 180-day lookback."

    Design: Difficulty/boundary_precision_check/boundary_vendor_exposure_alert_at_exactly_the_alert_threshold
    """
    world = _world_two_suppliers_straddling_the_alert_threshold()

    response = api.assess_violation(
        world["violation_a"]["id"],
        {"assessment_note": "Assessment one cent-band below the alert threshold."},
        officer_headers,
    )
    chargeback = validate_success(response, 201)

    assert chargeback["assessment_variant"] == "STANDARD", (
        f"expected assessment_variant STANDARD, got "
        f"{chargeback['assessment_variant']}"
    )
    assert chargeback["cost_recovery_cents"] == 299_500, (
        f"expected cost_recovery_cents 299500, got "
        f"{chargeback['cost_recovery_cents']}"
    )
    assert chargeback["gross_assessed_cents"] == 499_500, (
        f"expected gross_assessed_cents 499500, got "
        f"{chargeback['gross_assessed_cents']}"
    )

    vendor = read_vendor(world["vendor_a"]["id"])
    assert vendor["open_chargeback_cents"] == 499_500, (
        f"expected open_chargeback_cents 499500, got "
        f"{vendor['open_chargeback_cents']}"
    )
    assert vendor["exposure_alert_flag"] is False, (
        "exposure of 499500 cents has not reached 500,000, so exposure_alert_flag "
        "must stay false"
    )


def test_exposure_at_exactly_the_alert_threshold_raises_the_flag(api, officer_headers):
    """PRD §3.1: "`exposure_alert_flag` is recomputed every single time
    `open_chargeback_cents` changes and is true exactly when that figure has reached
    500,000 cents — five thousand currency units of unrecovered assessment — or
    more."
    PRD §3.5: "The fourth link, caused by the third, re-derives `exposure_alert_flag`
    as true exactly when `open_chargeback_cents` has reached 500,000 cents or more,
    and increments the supplier's `version` by one."

    Design: Difficulty/boundary_precision_check/boundary_vendor_exposure_alert_at_exactly_the_alert_threshold
    """
    world = _world_two_suppliers_straddling_the_alert_threshold()

    response = api.assess_violation(
        world["violation_b"]["id"],
        {"assessment_note": "Assessment landing exactly on the alert threshold."},
        officer_headers,
    )
    chargeback = validate_success(response, 201)

    assert chargeback["assessment_variant"] == "STANDARD", (
        f"expected assessment_variant STANDARD, got "
        f"{chargeback['assessment_variant']}"
    )
    assert chargeback["cost_recovery_cents"] == 300_000, (
        f"expected cost_recovery_cents 300000, got "
        f"{chargeback['cost_recovery_cents']}"
    )
    assert chargeback["gross_assessed_cents"] == 500_000, (
        f"expected gross_assessed_cents 500000, got "
        f"{chargeback['gross_assessed_cents']}"
    )

    vendor = read_vendor(world["vendor_b"]["id"])
    assert vendor["open_chargeback_cents"] == 500_000, (
        f"expected open_chargeback_cents 500000, got "
        f"{vendor['open_chargeback_cents']}"
    )
    assert vendor["exposure_alert_flag"] is True, (
        "exposure of exactly 500000 cents has reached the threshold, so "
        "exposure_alert_flag must read true"
    )
