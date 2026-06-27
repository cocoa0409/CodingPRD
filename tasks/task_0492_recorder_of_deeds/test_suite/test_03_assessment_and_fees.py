"""Fee assessment, transfer-tax, records-management surcharge, and escrow accounting.

Covers calculation rules at examination approval (recording fee, transfer tax,
records-management surcharge, round-then-sum total) and the settled-vs-available
escrow distinction.
"""
from test_helpers import (
    validate_success,
    fixtures,
)


# ===========================================================================
# Difficulty: dual_variant_calc / transfer_tax_estimated_vs_final_on_package
# ===========================================================================
def test_final_transfer_tax_uses_verified_consideration(api):
    """PRD Section 3.3: "Otherwise it is the verified consideration multiplied by
    the tax rate of 55 basis points, divided by 10,000, rounded half up to whole cents."
    PRD Section 3.3: "the records-management surcharge mirrors the transfer-tax threshold."
    PRD Section 3.2: "The authoritative value is always the final variant computed at
    examination approval from the verified consideration."

    Final transfer tax on verified_consideration_cents=250000 is round_half_up(250000*55/10000)
    = 1375; records-management is round_half_up(250000*13/10000) = 325.

    Design: Difficulty/dual_variant_calc/transfer_tax_estimated_vs_final_on_package
    """
    office, submitter = fixtures.setup_office_and_submitter()
    pkg = fixtures.create_package_in_examination(
        office["id"], submitter["id"], doc_type="DEED",
        declared_page_count=1, declared_consideration_cents=200000,
        grantors=("Alice Seller",), grantees=("Bob Buyer",),
    )
    resp = api.create_assessment(
        pkg["id"],
        {"verified_page_count": 1, "verified_consideration_cents": 250000,
         "expected_package_version": pkg["version"]},
        fixtures._examiner(),
    )
    fa = validate_success(resp, expected_status=201)
    assert fa["transfer_tax_cents"] == 1375, f"expected 1375, got {fa['transfer_tax_cents']}"
    assert fa["records_mgmt_cents"] == 325, f"expected 325, got {fa['records_mgmt_cents']}"


def test_final_transfer_tax_differs_from_estimate_on_declared(api):
    """PRD Section 3.2: "This estimate is informational only and is not persisted onto
    any FeeAssessment; it may differ from the final figure if the examiner verifies a
    different consideration."
    PRD Section 3.3: "Otherwise it is the verified consideration multiplied by the tax
    rate of 55 basis points, divided by 10,000, rounded half up to whole cents."

    The persisted FeeAssessment carries the FINAL transfer tax (1375 on verified 250000),
    not the estimate that declared 200000 would have produced (1100).

    Design: Difficulty/dual_variant_calc/transfer_tax_estimated_vs_final_on_package
    """
    office, submitter = fixtures.setup_office_and_submitter()
    pkg = fixtures.create_package_in_examination(
        office["id"], submitter["id"], doc_type="DEED",
        declared_page_count=1, declared_consideration_cents=200000,
        grantors=("Alice Seller",), grantees=("Bob Buyer",),
    )
    fa = fixtures.assess_package(pkg["id"], 1, 250000, pkg["version"])
    # 250000 * 55 / 10000 = 1375 (final); declared 200000 would estimate 1100.
    assert fa["transfer_tax_cents"] == 1375, (
        f"persisted transfer tax must be the final 1375 (not the estimate 1100), "
        f"got {fa['transfer_tax_cents']}"
    )


# ===========================================================================
# Difficulty: dual_variant_calc / escrow_settled_vs_available_on_submitter
# ===========================================================================
def test_escrow_settled_balance_reduced_only_by_captured_payment(api):
    """PRD Section 2.6: "The escrow_balance_cents is settled escrow — the deposited
    lifetime total minus the sum of amount_cents over this submitter's CAPTURED
    escrow-method payments. Settled balance is reduced only by captured payments and
    is never reduced by a mere hold."

    After one ESCROW capture of 4000 against a 50000 deposit, settled balance is 46000.

    Design: Difficulty/dual_variant_calc/escrow_settled_vs_available_on_submitter
    """
    office, submitter = fixtures.setup_office_and_submitter(escrow_cents=50000)
    # P1 paid via ESCROW (DEED 2 pages, exempt consideration -> total 4000).
    fixtures.create_paid_package(
        office["id"], submitter["id"], doc_type="DEED",
        declared_page_count=2, verified_page_count=2, verified_consideration_cents=0,
        amount_cents=4000, method="ESCROW",
    )
    # P2 ASSESSED only (held, not paid).
    fixtures.create_assessed_package(
        office["id"], submitter["id"], doc_type="DEED",
        declared_page_count=2, verified_page_count=2, verified_consideration_cents=0,
    )
    data = validate_success(api.get_submitter(submitter["id"], fixtures._clerk()))
    assert data["escrow_balance_cents"] == 46000, (
        f"settled balance must be 50000 - 4000 = 46000, got {data['escrow_balance_cents']}"
    )


def test_escrow_available_subtracts_finalized_unpaid_hold(api):
    """PRD Section 2.6: "The escrow_held_cents is a forward-looking hold — the sum of
    total_due_cents for this submitter's packages whose assessment is FINALIZED and
    whose package is still in ASSESSED status."
    PRD Section 2.6: "The escrow_available_cents is the spendable figure: it is the
    settled escrow_balance_cents minus the escrow_held_cents."

    With settled 46000 and a 4000 FINALIZED-unpaid hold, available is 42000.

    Design: Difficulty/dual_variant_calc/escrow_settled_vs_available_on_submitter
    """
    office, submitter = fixtures.setup_office_and_submitter(escrow_cents=50000)
    fixtures.create_paid_package(
        office["id"], submitter["id"], doc_type="DEED",
        declared_page_count=2, verified_page_count=2, verified_consideration_cents=0,
        amount_cents=4000, method="ESCROW",
    )
    fixtures.create_assessed_package(
        office["id"], submitter["id"], doc_type="DEED",
        declared_page_count=2, verified_page_count=2, verified_consideration_cents=0,
    )
    data = validate_success(api.get_submitter(submitter["id"], fixtures._clerk()))
    assert data["escrow_held_cents"] == 4000, f"held must be 4000, got {data['escrow_held_cents']}"
    assert data["escrow_available_cents"] == 42000, (
        f"available must be 46000 - 4000 = 42000, got {data['escrow_available_cents']}"
    )
    assert data["escrow_balance_cents"] != data["escrow_available_cents"], (
        "settled balance (46000) must differ from available (42000)"
    )


# ===========================================================================
# Difficulty: combinatorial_formula / recording_fee_tiered_page_index_doctype
# ===========================================================================
def test_recording_fee_combines_page_index_doctype(api):
    """PRD Section 3.3: "The page part is a base first-page fee of 2,500 cents plus an
    additional-page fee of 500 cents for each page beyond the first." PRD Section 3.3:
    "The index part is an index surcharge of 200 cents for each non-VOIDED party entry
    beyond the first four free entries." PRD Section 3.3: "The doc-type part is a
    surcharge that depends on the package's doc_type: 1,000 cents for DEED."

    DEED, 3 verified pages, 6 party entries: page 2500+500*2=3500, index 200*(6-4)=400,
    doctype 1000 -> recording_fee 4900.

    Design: Difficulty/combinatorial_formula/recording_fee_tiered_page_index_doctype
    """
    office, submitter = fixtures.setup_office_and_submitter()
    pkg = fixtures.create_package_in_examination(
        office["id"], submitter["id"], doc_type="DEED", declared_page_count=3,
        grantors=("G1", "G2", "G3"), grantees=("E1", "E2", "E3"),
    )
    fa = fixtures.assess_package(pkg["id"], 3, 0, pkg["version"])
    assert fa["recording_fee_cents"] == 4900, (
        f"recording_fee must be 3500+400+1000=4900, got {fa['recording_fee_cents']}"
    )


def test_recording_fee_only_total_when_consideration_exempt(api):
    """PRD Section 3.3: "The recording_fee_cents is the sum of these three parts; all
    terms are integer cents and no rounding is applied."
    PRD Section 3.3: "The total due is assembled with the pinned round-then-sum order ...
    total_due_cents is the integer sum of recording_fee_cents, transfer_tax_cents, and
    records_mgmt_cents."

    With exempt consideration (transfer tax and surcharge both 0), total_due equals the
    recording fee 4900.

    Design: Difficulty/combinatorial_formula/recording_fee_tiered_page_index_doctype
    """
    office, submitter = fixtures.setup_office_and_submitter()
    pkg = fixtures.create_package_in_examination(
        office["id"], submitter["id"], doc_type="DEED", declared_page_count=3,
        grantors=("G1", "G2", "G3"), grantees=("E1", "E2", "E3"),
    )
    fa = fixtures.assess_package(pkg["id"], 3, 0, pkg["version"])
    assert fa["total_due_cents"] == 4900, (
        f"total_due with exempt consideration must equal recording_fee 4900, got {fa['total_due_cents']}"
    )


# ===========================================================================
# Difficulty: combinatorial_formula / total_amount_due_round_each_component_then_sum
# ===========================================================================
def test_total_due_rounds_each_component_before_summing(api):
    """PRD Section 3.3: "the transfer_tax_cents and records_mgmt_cents are each rounded
    half up to whole cents independently as just described, and then total_due_cents is
    the integer sum of recording_fee_cents, transfer_tax_cents, and records_mgmt_cents.
    The system never sums the raw fractional tax and surcharge before rounding."

    consideration 100074: transfer 550.407->550, surcharge 130.0962->130, recording 3500
    -> total 4180. Sum-then-round of raws (681) is forbidden and would give 4181.

    Design: Difficulty/combinatorial_formula/total_amount_due_round_each_component_then_sum
    """
    office, submitter = fixtures.setup_office_and_submitter()
    pkg = fixtures.create_package_in_examination(
        office["id"], submitter["id"], doc_type="DEED", declared_page_count=1,
        declared_consideration_cents=100074, grantors=("G1",), grantees=("E1",),
    )
    fa = fixtures.assess_package(pkg["id"], 1, 100074, pkg["version"])
    assert fa["recording_fee_cents"] == 3500, f"recording_fee {fa['recording_fee_cents']}"
    assert fa["transfer_tax_cents"] == 550, f"transfer_tax {fa['transfer_tax_cents']}"
    assert fa["records_mgmt_cents"] == 130, f"records_mgmt {fa['records_mgmt_cents']}"
    assert fa["total_due_cents"] == 4180, f"total_due {fa['total_due_cents']}"


def test_total_due_is_integer_sum_of_rounded_components(api):
    """PRD Section 3.3: "and then total_due_cents is the integer sum of
    recording_fee_cents, transfer_tax_cents, and records_mgmt_cents."

    The persisted total equals the integer sum of its three already-rounded components.

    Design: Difficulty/combinatorial_formula/total_amount_due_round_each_component_then_sum
    """
    office, submitter = fixtures.setup_office_and_submitter()
    pkg = fixtures.create_package_in_examination(
        office["id"], submitter["id"], doc_type="DEED", declared_page_count=1,
        declared_consideration_cents=100074, grantors=("G1",), grantees=("E1",),
    )
    fa = fixtures.assess_package(pkg["id"], 1, 100074, pkg["version"])
    assert fa["total_due_cents"] == (
        fa["recording_fee_cents"] + fa["transfer_tax_cents"] + fa["records_mgmt_cents"]
    ), "total_due must be the integer sum of the three rounded components"


# ===========================================================================
# Difficulty: boundary_precision_check / transfer_tax_exempt_threshold_inclusive
# ===========================================================================
def test_transfer_tax_exempt_at_threshold_inclusive(api):
    """PRD Section 3.3: "If the verified consideration is at most the exempt threshold of
    10,000 cents (that is, one hundred dollars or less is exempt), the transfer_tax_cents
    is 0." PRD Section 3.3: "The records-management surcharge mirrors the transfer-tax
    threshold. If the verified consideration is at most the same exempt threshold of
    10,000 cents, the records_mgmt_cents is 0."

    verified_consideration_cents == 10000 is exactly at the inclusive boundary: both
    transfer tax and surcharge are 0.

    Design: Difficulty/boundary_precision_check/transfer_tax_exempt_threshold_inclusive
    """
    office, submitter = fixtures.setup_office_and_submitter()
    pkg = fixtures.create_package_in_examination(
        office["id"], submitter["id"], doc_type="DEED", declared_page_count=1,
        declared_consideration_cents=10000, grantors=("G",), grantees=("E",),
    )
    fa = fixtures.assess_package(pkg["id"], 1, 10000, pkg["version"])
    assert fa["transfer_tax_cents"] == 0, f"transfer_tax at 10000 must be 0, got {fa['transfer_tax_cents']}"
    assert fa["records_mgmt_cents"] == 0, f"records_mgmt at 10000 must be 0, got {fa['records_mgmt_cents']}"


def test_transfer_tax_exempt_below_threshold(api):
    """PRD Section 3.3: "If the verified consideration is at most the exempt threshold of
    10,000 cents (that is, one hundred dollars or less is exempt), the transfer_tax_cents
    is 0." PRD Section 3.3: "If the verified consideration is at most the same exempt
    threshold of 10,000 cents, the records_mgmt_cents is 0."

    verified_consideration_cents == 9999 is below the inclusive boundary: both transfer
    tax and surcharge remain 0 (the X-1 side of the threshold).

    Design: Difficulty/boundary_precision_check/transfer_tax_exempt_threshold_inclusive
    """
    office, submitter = fixtures.setup_office_and_submitter()
    pkg = fixtures.create_package_in_examination(
        office["id"], submitter["id"], doc_type="DEED", declared_page_count=1,
        declared_consideration_cents=9999, grantors=("G",), grantees=("E",),
    )
    fa = fixtures.assess_package(pkg["id"], 1, 9999, pkg["version"])
    assert fa["transfer_tax_cents"] == 0, f"transfer_tax at 9999 must be 0, got {fa['transfer_tax_cents']}"
    assert fa["records_mgmt_cents"] == 0, f"records_mgmt at 9999 must be 0, got {fa['records_mgmt_cents']}"


def test_transfer_tax_taxed_one_cent_over_threshold(api):
    """PRD Section 3.3: "Otherwise it is the verified consideration multiplied by the tax
    rate of 55 basis points, divided by 10,000, rounded half up to whole cents."
    PRD Section 3.3: "Otherwise it is the verified consideration multiplied by the
    records-management rate of 13 basis points, divided by 10,000, rounded half up to
    whole cents."

    verified_consideration_cents == 10001 is one cent over the exempt threshold:
    transfer tax round_half_up(10001*55/10000)=55, surcharge round_half_up(10001*13/10000)=13.

    Design: Corner/calculations/transfer_tax_taxed_just_over_threshold
    """
    office, submitter = fixtures.setup_office_and_submitter()
    pkg = fixtures.create_package_in_examination(
        office["id"], submitter["id"], doc_type="DEED", declared_page_count=1,
        declared_consideration_cents=10001, grantors=("G",), grantees=("E",),
    )
    fa = fixtures.assess_package(pkg["id"], 1, 10001, pkg["version"])
    assert fa["transfer_tax_cents"] == 55, f"transfer_tax at 10001 must be 55, got {fa['transfer_tax_cents']}"
    assert fa["records_mgmt_cents"] == 13, f"records_mgmt at 10001 must be 13, got {fa['records_mgmt_cents']}"


# ===========================================================================
# Corner: consistency_model / immediate_visibility_of_assessment_fields
# ===========================================================================
def test_assessment_response_immediately_carries_total_due(api):
    """PRD Section 2.8: "the system commits all such effects together." PRD Section 3.3:
    "a new FeeAssessment is created in FINALIZED status with its component fees computed."
    PRD Section 4: "the assessment, rejection, and payment creations, which mint new
    child resources, return 201 Created."

    A DEED, 1 page, exempt consideration assessment immediately returns total_due 3500
    (recording fee 2500+0+1000) in FINALIZED status with HTTP 201.

    Design: Corner/consistency_model/immediate_visibility_of_assessment_fields
    """
    office, submitter = fixtures.setup_office_and_submitter()
    pkg = fixtures.create_package_in_examination(
        office["id"], submitter["id"], doc_type="DEED", declared_page_count=1,
        declared_consideration_cents=0, grantors=("G",), grantees=("E",),
    )
    resp = api.create_assessment(
        pkg["id"],
        {"verified_page_count": 1, "verified_consideration_cents": 0,
         "expected_package_version": pkg["version"]},
        fixtures._examiner(),
    )
    fa = validate_success(resp, expected_status=201)
    assert fa["total_due_cents"] == 3500, f"total_due must be 3500, got {fa['total_due_cents']}"
    assert fa["status"] == "FINALIZED", f"status must be FINALIZED, got {fa['status']}"
