"""Non-linear lifecycles: a bounded review loop on a dispute, two state dimensions
on one chargeback advancing independently, and the two divergent side-effect sets a
detected finding can produce.

Every test builds its own world from an empty store, starting by pinning the
programme's logical clock.
"""
from test_helpers import (
    TEST_USERS,
    add_evidence,
    add_requirement,
    apply_cash,
    assess_violation,
    create_guide,
    create_po,
    create_shipment,
    create_vendor,
    decide_dispute,
    file_violation,
    open_dispute,
    publish_guide,
    read_chargeback,
    read_dispute,
    read_shipment,
    read_vendor,
    read_violation,
    receive_shipment,
    request_dispute_info,
    request_info_payload,
    resubmit_dispute,
    set_clock,
    validate_error,
    validate_paginated,
    void_violation,
)

OFFICER = TEST_USERS["officer_headers"]
SECOND_OFFICER = TEST_USERS["second_officer_headers"]

SHP_04_TIER_1 = {
    "requirement_code": "SHP-04",
    "domain": "SHIPMENT",
    "severity_tier": "TIER_1",
    "min_evidence_count": 2,
    "fixed_fee_cents": 200000,
    "per_unit_recovery_cents": 500,
    "handling_pct": 5.00,
    "min_fee_cents": 100000,
    "cap_cents": 900000,
}
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


def _received_load(vendor_code, legal_name, payment_terms_days, schedules):
    """Clock pinned, supplier registered, one PUBLISHED edition carrying the given
    fee-schedule rows, and one 1000-unit load received in full on its deadline."""
    set_clock("2026-08-01T00:00:00Z")
    vendor = create_vendor(
        vendor_code=vendor_code,
        legal_name=legal_name,
        payment_terms_days=payment_terms_days,
    )
    guide = create_guide(
        guide_code="RG-2026-A",
        title="Domestic Routing Guide 2026-A",
        scope_code="ALL",
        effective_from="2026-08-05T00:00:00Z",
    )
    requirements = [add_requirement(guide["id"], schedule) for schedule in schedules]
    publish_guide(guide["id"])
    set_clock("2026-08-10T00:00:00Z")
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
        po["id"], vendor["id"], asn_number="ASN-1", shipped_units=1000, carton_count=40
    )
    shipment = receive_shipment(shipment["id"], 1000)
    return vendor, requirements, shipment


def _late_asn_chargeback(vendor_code, legal_name):
    """A fully evidenced late-ASN finding assessed into a 425000-cent chargeback."""
    vendor, requirements, shipment = _received_load(
        vendor_code, legal_name, 60, [SHP_04_TIER_1]
    )
    violation = file_violation(
        shipment["id"],
        requirements[0]["id"],
        affected_units=400,
        affected_cartons=16,
        narrative="ASN transmitted after the trailer arrived.",
    )
    add_evidence(
        violation["id"],
        kind="DOCUMENT",
        reference_uri="s3://evidence/shp-04/asn-timestamp.pdf",
    )
    add_evidence(
        violation["id"],
        kind="MEASUREMENT",
        reference_uri="s3://evidence/shp-04/gate-log.csv",
    )
    chargeback = assess_violation(
        violation["id"], assessment_note="Late ASN on inbound load."
    )
    return vendor, violation, chargeback


# ---------------------------------------------------------------------------
# Bounded review loop
# ---------------------------------------------------------------------------
def _dispute_after_two_rounds(vendor_code, legal_name):
    """A dispute that has already been round-tripped once: opened, questioned by the
    reviewing officer and resubmitted with a revised claim."""
    vendor, violation, chargeback = _late_asn_chargeback(vendor_code, legal_name)
    set_clock("2026-08-12T00:00:00Z")
    dispute = open_dispute(
        chargeback["id"],
        vendor["id"],
        reason_code="CARRIER_CAUSED",
        claimed_reversal_cents=200000,
        narrative="Round one: carrier held the load.",
    )
    request_dispute_info(
        dispute["id"],
        information_request_note="Provide the carrier hold confirmation.",
    )
    resubmit_dispute(
        dispute["id"],
        vendor["id"],
        claimed_reversal_cents=220000,
        narrative="Round two: carrier hold confirmation attached.",
    )
    return vendor, chargeback, dispute


def test_first_information_request_closes_the_loop_and_counts_a_second_round(api):
    """PRD §3.6: "A `ComplianceOfficer` who needs more from the supplier bounces
    the case back with a mandatory `information_request_note`, taking the dispute
    `SUBMITTED → INFO_REQUESTED` and storing the note."
    PRD §3.6: "The supplier answers by resubmitting with a fresh
    `claimed_reversal_cents` and a fresh `narrative`, which replace the previous
    round's values; this takes the dispute `INFO_REQUESTED → SUBMITTED`, raises
    `round_count` by one, clears `information_request_note` and increments the
    dispute's `version`."
    PRD §3.6: "A successful opening creates the dispute in `SUBMITTED` with
    `round_count` 1, `submitted_at` from the current logical clock, `chargeback_id`
    taken from the path and `vendor_id` denormalised from the chargeback."

    Design: Difficulty/non_linear_state_machine/vendor_dispute_revision_cycle_bounded_at_two_rounds
    """
    vendor, chargeback, dispute = _dispute_after_two_rounds(
        "V5005", "Loopback Logistics"
    )

    revised = read_dispute(dispute["id"])
    assert revised["status"] == "SUBMITTED", (
        f"the resubmission returns the dispute to the officer, got {revised['status']}"
    )
    assert revised["round_count"] == 2, (
        "the resubmission lifted the round count from 1 to 2, got "
        f"{revised['round_count']}"
    )
    assert revised["claimed_reversal_cents"] == 220000, (
        f"the resubmission replaces the claimed amount, got {revised['claimed_reversal_cents']}"
    )
    assert revised["information_request_note"] is None, (
        "the resubmission clears the outstanding question, got "
        f"{revised['information_request_note']}"
    )


def test_third_presentation_of_the_dispute_is_refused_at_the_round_bound(api):
    """PRD §3.6: "The review cycle is bounded at two rounds."
    PRD §3.6: "The loop `SUBMITTED → INFO_REQUESTED → SUBMITTED` therefore closes
    once and only once; a third presentation of the case is impossible."
    PRD §3.6: "This requires the dispute to be `SUBMITTED` — from
    `INFO_REQUESTED` or from any decided state the request is refused with
    `ERR_DISPUTE_NOT_AWAITING_DECISION` — and requires `round_count` to be strictly
    less than 2, with a second information request on the same case refused as
    `ERR_DISPUTE_ROUND_LIMIT_EXCEEDED`."
    PRD §2.7: "Dispute round bound — the dispute's `round_count` is strictly less
    than 2, checked on both information request and resubmission; otherwise
    `ERR_DISPUTE_ROUND_LIMIT_EXCEEDED` (422)."

    Design: Difficulty/non_linear_state_machine/vendor_dispute_revision_cycle_bounded_at_two_rounds
    """
    vendor, chargeback, dispute = _dispute_after_two_rounds(
        "V5005", "Loopback Logistics"
    )

    response = api.request_dispute_info(
        dispute["id"],
        request_info_payload(
            information_request_note="Third lap around the loop - must be refused."
        ),
        SECOND_OFFICER,
    )

    validate_error(response, "ERR_DISPUTE_ROUND_LIMIT_EXCEEDED", 422)


def test_refused_second_information_request_leaves_the_dispute_untouched(api):
    """PRD §3.6: "with a second information request on the same case refused as
    `ERR_DISPUTE_ROUND_LIMIT_EXCEEDED`."
    PRD §3.6: "The same request moves the chargeback's `dispute_status` `NONE →
    OPEN` and increments the chargeback's `version` by one; its `settlement_status`
    is untouched, so a chargeback that was `PARTIALLY_RECOVERED` or `RECOVERED`
    stays exactly where it was on that dimension."

    Design: Difficulty/non_linear_state_machine/vendor_dispute_revision_cycle_bounded_at_two_rounds
    """
    vendor, chargeback, dispute = _dispute_after_two_rounds(
        "V5005", "Loopback Logistics"
    )

    api.request_dispute_info(
        dispute["id"],
        request_info_payload(
            information_request_note="Third lap around the loop - must be refused."
        ),
        SECOND_OFFICER,
    )

    unchanged = read_dispute(dispute["id"])
    assert unchanged["status"] == "SUBMITTED", (
        f"a refused request writes nothing, got {unchanged['status']}"
    )
    assert unchanged["round_count"] == 2, (
        f"the round count must not creep past the bound, got {unchanged['round_count']}"
    )
    assert unchanged["claimed_reversal_cents"] == 220000
    assert unchanged["information_request_note"] is None, (
        "the refused note must not be stored, got "
        f"{unchanged['information_request_note']}"
    )

    parent = read_chargeback(chargeback["id"])
    assert parent["dispute_status"] == "OPEN", (
        f"the dispute is still live on the chargeback, got {parent['dispute_status']}"
    )
    assert parent["settlement_status"] == "ASSESSED", (
        f"no money moved, so the settlement dimension is untouched, got {parent['settlement_status']}"
    )


# ---------------------------------------------------------------------------
# Two independent state dimensions
# ---------------------------------------------------------------------------
def _cash_then_denied_dispute():
    """One 425000-cent chargeback that takes a 100000-cent remittance and then
    loses a fee-miscalculation dispute."""
    vendor, violation, chargeback = _late_asn_chargeback("V6006", "Twin Axis Imports")
    set_clock("2026-08-12T00:00:00Z")
    apply_cash(chargeback["id"], 100000, remittance_reference="RA-9001")
    dispute = open_dispute(
        chargeback["id"],
        vendor["id"],
        reason_code="FEE_MISCALCULATED",
        claimed_reversal_cents=50000,
        narrative="Handling percentage applied to the wrong invoice value.",
    )
    return vendor, chargeback, dispute


def test_cash_remittance_moves_only_the_settlement_dimension(api):
    """PRD §3.9: "The application creates an allocation with `source_type` `CASH`,
    `deduction_id` null, `effective_status` `EFFECTIVE` and `applied_at` stamped
    from the logical clock at creation, storing the applied amount in the
    allocation's `allocated_cents` field and the supplied reference in
    `remittance_reference`."
    PRD §3.9: "The `settlement_status` is then chosen by the first matching branch
    of four, tested in this order: the chargeback is `WRITTEN_OFF` when the net
    assessed balance is zero or below; otherwise `RECOVERED` when `recovered_cents`
    has reached or exceeded the net assessed balance; otherwise
    `PARTIALLY_RECOVERED` when `recovered_cents` is above zero; otherwise
    `ASSESSED`."

    Design: Difficulty/non_linear_state_machine/chargeback_parallel_dimensions_evolve_independently
    """
    vendor, violation, chargeback = _late_asn_chargeback("V6006", "Twin Axis Imports")
    set_clock("2026-08-12T00:00:00Z")

    apply_cash(chargeback["id"], 100000, remittance_reference="RA-9001")

    rows, meta = validate_paginated(
        api.list_allocations(OFFICER, params={"chargeback_id": chargeback["id"]})
    )
    assert meta["total_count"] == 1, (
        f"one remittance produces exactly one allocation, got {meta['total_count']}"
    )
    allocation = rows[0]
    assert allocation["source_type"] == "CASH", (
        f"a remittance bypasses payables, got {allocation['source_type']}"
    )
    assert allocation["deduction_id"] is None, (
        f"a cash allocation hangs off no deduction, got {allocation['deduction_id']}"
    )
    assert allocation["effective_status"] == "EFFECTIVE", (
        f"cash is effective immediately, got {allocation['effective_status']}"
    )

    recovered = read_chargeback(chargeback["id"])
    assert recovered["recovered_cents"] == 100000
    assert recovered["outstanding_cents"] == 325000, (
        "425000 assessed less 100000 recovered leaves 325000, got "
        f"{recovered['outstanding_cents']}"
    )
    assert recovered["settlement_status"] == "PARTIALLY_RECOVERED", (
        f"part payment lands on the third branch, got {recovered['settlement_status']}"
    )
    assert recovered["dispute_status"] == "NONE", (
        f"paying money does not raise a dispute, got {recovered['dispute_status']}"
    )


def test_denied_dispute_moves_only_the_dispute_dimension(api):
    """PRD §3.6: "A `DENY` decision short-circuits the arithmetic:
    `reason_ceiling_pct` is set to 0.00, `goodwill_cents` to 0 and
    `approved_reversal_cents` to 0, the dispute lands in `DENIED`, and the
    chargeback moves `OPEN → UPHELD` on its dispute dimension with `reversal_cents`
    left exactly as it was."
    PRD §3.6: "No money field on the supplier changes, and the `settlement_status`
    dimension does not move."

    Design: Difficulty/non_linear_state_machine/chargeback_parallel_dimensions_evolve_independently
    """
    vendor, chargeback, dispute = _cash_then_denied_dispute()

    decide_dispute(
        dispute["id"],
        "DENY",
        review_note="Handling base verified against the receipt; fee stands.",
    )

    decided = read_dispute(dispute["id"])
    assert decided["status"] == "DENIED", (
        f"the denial is terminal on the dispute, got {decided['status']}"
    )
    assert decided["approved_reversal_cents"] == 0, (
        f"a denial reverses nothing, got {decided['approved_reversal_cents']}"
    )

    upheld = read_chargeback(chargeback["id"])
    assert upheld["dispute_status"] == "UPHELD", (
        f"a denial upholds the assessment, got {upheld['dispute_status']}"
    )
    assert upheld["reversal_cents"] == 0, (
        f"no reversal reaches the chargeback, got {upheld['reversal_cents']}"
    )
    assert upheld["settlement_status"] == "PARTIALLY_RECOVERED", (
        "the adjudication must not disturb the money already applied, got "
        f"{upheld['settlement_status']}"
    )
    assert upheld["outstanding_cents"] == 325000, (
        f"the balance owed is unchanged by the denial, got {upheld['outstanding_cents']}"
    )


def test_both_dimensions_hold_their_own_positions_after_cash_and_denial(api):
    """PRD §3.6: "A chargeback carries two state dimensions on the same row, and
    they evolve independently of one another. The `dispute_status` dimension records
    the adjudication story and moves only through dispute handling; the
    `settlement_status` dimension records the money story and moves only through
    deduction posting, deduction reversal and cash application."
    PRD §3.9: "and its `deduction_posted` is true exactly when at least one of its
    allocations has `source_type` `DEDUCTION` and belongs to a deduction whose
    `status` is `POSTED`, a flag that is independent of the settlement dimension."
    PRD §3.9: "`recovered_lifetime_cents` is the sum of `allocated_cents` over
    every allocation on any of the supplier's chargebacks whose `effective_status`
    is `EFFECTIVE`, with no filter on the chargeback's settlement state."

    Design: Difficulty/non_linear_state_machine/chargeback_parallel_dimensions_evolve_independently
    """
    vendor, chargeback, dispute = _cash_then_denied_dispute()

    decide_dispute(
        dispute["id"],
        "DENY",
        review_note="Handling base verified against the receipt; fee stands.",
    )

    final = read_chargeback(chargeback["id"])
    assert final["settlement_status"] == "PARTIALLY_RECOVERED"
    assert final["dispute_status"] == "UPHELD"
    assert final["recovered_cents"] == 100000
    assert final["reversal_cents"] == 0
    assert final["deduction_posted"] is False, (
        "cash recovery never sets the payables flag, got "
        f"{final['deduction_posted']}"
    )

    supplier = read_vendor(vendor["id"])
    assert supplier["open_chargeback_cents"] == 325000, (
        "a partially recovered chargeback still counts its net balance towards "
        f"exposure, got {supplier['open_chargeback_cents']}"
    )
    assert supplier["recovered_lifetime_cents"] == 100000, (
        f"the remittance is recorded for life, got {supplier['recovered_lifetime_cents']}"
    )


# ---------------------------------------------------------------------------
# Divergent side-effect sets on one detected finding
# ---------------------------------------------------------------------------
def _two_findings_one_load():
    """One received load carrying two independently evidenced findings: a late ASN
    and a labeling failure."""
    vendor, requirements, shipment = _received_load(
        "V7007", "Forkpath Distributors", 60, [SHP_04_TIER_1, LBL_01_TIER_1]
    )
    shipment_requirement, labeling_requirement = requirements
    late_asn = file_violation(
        shipment["id"],
        shipment_requirement["id"],
        affected_units=400,
        affected_cartons=16,
        narrative="ASN transmitted after the trailer arrived.",
    )
    add_evidence(
        late_asn["id"], kind="DOCUMENT", reference_uri="s3://evidence/shp-04/asn.pdf"
    )
    add_evidence(
        late_asn["id"], kind="MEASUREMENT", reference_uri="s3://evidence/shp-04/gate.csv"
    )
    mislabeling = file_violation(
        shipment["id"],
        labeling_requirement["id"],
        affected_units=500,
        affected_cartons=20,
        narrative="GS1-128 carton labels missing on half the load.",
    )
    add_evidence(
        mislabeling["id"], kind="PHOTO", reference_uri="s3://evidence/lbl-01/face.jpg"
    )
    add_evidence(
        mislabeling["id"], kind="SCAN", reference_uri="s3://evidence/lbl-01/scan-fail.txt"
    )
    return vendor, shipment, late_asn, mislabeling


def _resolve_both_findings(late_asn, mislabeling):
    """Send one finding down the void branch and the other down the charge branch."""
    void_violation(
        mislabeling["id"],
        void_reason="Labels were present on the pallet placard; detection was in error.",
    )
    return assess_violation(
        late_asn["id"], assessment_note="Late ASN confirmed by the gate log."
    )


def test_charge_branch_mints_a_chargeback_and_the_void_branch_mints_none(api):
    """PRD §3.4: "The void takes the violation `DETECTED → VOIDED` or
    `EVIDENCE_COMPLETE → VOIDED` with an identical side-effect set from either
    origin: the recorded `void_reason` is stored, the shipment's
    `open_violation_count` and the supplier's `open_violation_count` each fall by
    one to exactly their pre-filing values, and the violation's `version`
    increments."
    PRD §3.4: "Voiding mints no chargeback and touches no money field on the
    supplier; that asymmetry with the other terminal branch is the whole point of
    the fork."
    PRD §3.5: "Assessment is the `ComplianceOfficer`'s decision to turn an
    evidenced finding into money owed, and it takes the violation
    `EVIDENCE_COMPLETE → CHARGED`."

    Design: Difficulty/non_linear_state_machine/violation_branch_void_versus_charge_divergent_side_effect_sets
    """
    vendor, shipment, late_asn, mislabeling = _two_findings_one_load()

    chargeback = _resolve_both_findings(late_asn, mislabeling)

    voided = read_violation(mislabeling["id"])
    assert voided["status"] == "VOIDED", (
        f"the void branch is terminal, got {voided['status']}"
    )
    assert (
        voided["void_reason"]
        == "Labels were present on the pallet placard; detection was in error."
    ), f"the void reason is recorded verbatim, got {voided['void_reason']}"

    charged = read_violation(late_asn["id"])
    assert charged["status"] == "CHARGED", (
        f"the charge branch is terminal, got {charged['status']}"
    )

    minted = read_chargeback(chargeback["id"])
    assert minted["violation_id"] == late_asn["id"], (
        "the minted chargeback belongs to the charged finding only"
    )
    assert minted["gross_assessed_cents"] == 425000, (
        f"the TIER_1 shipment breach prices at 425000, got {minted['gross_assessed_cents']}"
    )

    rows, meta = validate_paginated(
        api.list_chargebacks(OFFICER, params={"violation_id": mislabeling["id"]})
    )
    assert meta["total_count"] == 0, (
        f"a voided finding must mint no chargeback, got {meta['total_count']}"
    )
    assert rows == []


def test_both_branches_clear_the_shipment_and_supplier_open_counts(api):
    """PRD §3.5: "The first link moves the violation to `CHARGED` and lowers both
    the shipment's `open_violation_count` and the supplier's `open_violation_count`
    by one, restoring them to their pre-filing values just as a void would."
    PRD §3.9: "`open_chargeback_cents` is the sum, over the supplier's chargebacks
    whose `settlement_status` is `ASSESSED` or `PARTIALLY_RECOVERED` only, of
    `gross_assessed_cents` less `reversal_cents` less `recovered_cents`;
    chargebacks that are `RECOVERED` or `WRITTEN_OFF` are excluded from this figure
    entirely."

    Design: Difficulty/non_linear_state_machine/violation_branch_void_versus_charge_divergent_side_effect_sets
    """
    vendor, shipment, late_asn, mislabeling = _two_findings_one_load()

    _resolve_both_findings(late_asn, mislabeling)

    load = read_shipment(shipment["id"])
    assert load["open_violation_count"] == 0, (
        "both branches close their finding on the load, got "
        f"{load['open_violation_count']}"
    )
    supplier = read_vendor(vendor["id"])
    assert supplier["open_violation_count"] == 0, (
        "both branches close their finding on the supplier, got "
        f"{supplier['open_violation_count']}"
    )
    assert supplier["open_chargeback_cents"] == 425000, (
        "only the charged finding contributes exposure, got "
        f"{supplier['open_chargeback_cents']}"
    )


def test_void_does_not_retract_the_evidence_captured_at_the_door(api):
    """PRD §3.4: "The shipment's `evidence_capture_count` is pointedly not
    decremented — the evidence remains, and so does the count of it."
    PRD §2.12: "Monotonic audit counters never fall. A shipment's
    `evidence_capture_count` counts every evidence item ever captured against any
    violation on that shipment, and it is deliberately not decremented when a
    violation is voided — the photographs were taken, the inspection happened, and
    the audit record of that work survives the withdrawal of the finding."

    Design: Difficulty/non_linear_state_machine/violation_branch_void_versus_charge_divergent_side_effect_sets
    """
    vendor, shipment, late_asn, mislabeling = _two_findings_one_load()

    _resolve_both_findings(late_asn, mislabeling)

    load = read_shipment(shipment["id"])
    assert load["evidence_capture_count"] == 4, (
        "all four captures survive the void, got "
        f"{load['evidence_capture_count']}"
    )
