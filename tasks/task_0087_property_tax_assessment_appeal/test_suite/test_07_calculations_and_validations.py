"""Exemption deduction math, taxable recompute, accrual/waterfall, and validation errors.

Covers corner queue (B) sections: calculations, validations.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_taxpayer_headers,
    make_hearing_officer_headers,
    create_owner,
    create_open_roll,
    create_parcel,
    create_assessment,
    claim_exemption,
    setup_draft_assessment,
    setup_under_review_appeal,
    setup_deferral_with_principal,
    setup_deferral_with_accrual,
)
from test_helpers import factories as f

ASSESSOR = TEST_USERS["assessor_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]


# --- calculations ----------------------------------------------------------
def test_homestead_exemption_flat_amount_correct(api):
    """PRD §3.4: "A homestead deduction is a flat 7,000 dollars."
    PRD §3.5: "The `taxable_value` is then the greater of 0 and `assessed_value` minus
    `exemption_total`."

    Design: Corner/calculations/homestead_exemption_flat_amount_correct
    """
    # assessed_value 90000 (first-ever NONE -> market rebase), HOMESTEAD on primary residence.
    owner, roll, parcel, asmt = setup_draft_assessment(
        market_value=90000, reassessment_event="NONE", parcel_overrides={"is_primary_residence": True}
    )
    exm = claim_exemption(asmt["id"], "HOMESTEAD")
    data = validate_success(api.approve_exemption(exm["id"], REVIEWER))
    assert data["claimed_amount"] == 7000
    asmt_after = validate_success(api.get_assessment(asmt["id"], ASSESSOR))
    assert asmt_after["exemption_total"] == 7000
    assert asmt_after["taxable_value"] == 83000


def test_disability_exemption_proportional_amount(api):
    """PRD §3.4: "A disability deduction is the assessment's `assessed_value` multiplied by
    the owner's `disability_pct` divided by 100, then multiplied by a factor of one-half, the
    whole rounded half-up to whole dollars."

    Design: Corner/calculations/disability_exemption_proportional_amount
    """
    # disability_pct 80 on assessed 90000: round(90000 * 0.80 * 0.50) = 36000.
    owner, roll, parcel, asmt = setup_draft_assessment(
        market_value=90000, reassessment_event="NONE",
        owner_overrides={"disability_pct": 80},
    )
    exm = claim_exemption(asmt["id"], "DISABILITY")
    data = validate_success(api.approve_exemption(exm["id"], REVIEWER))
    assert data["claimed_amount"] == 36000
    asmt_after = validate_success(api.get_assessment(asmt["id"], ASSESSOR))
    assert asmt_after["taxable_value"] == 54000


def test_exemption_total_clipped_at_assessed_value(api):
    """PRD §3.4: "In every case the per-exemption `claimed_amount` is finally clamped to no
    more than the assessment's `assessed_value`, since a single exemption can never wipe out
    more than the assessed value itself."
    PRD §3.5: "The `taxable_value` is then the greater of 0 and `assessed_value` minus
    `exemption_total`."

    Design: Corner/calculations/exemption_total_clipped_at_assessed_value
    """
    # assessed 6000 (market rebase), HOMESTEAD flat 7000 > AV -> clipped to 6000.
    owner, roll, parcel, asmt = setup_draft_assessment(
        market_value=6000, reassessment_event="NONE", parcel_overrides={"is_primary_residence": True}
    )
    exm = claim_exemption(asmt["id"], "HOMESTEAD")
    data = validate_success(api.approve_exemption(exm["id"], REVIEWER))
    assert data["claimed_amount"] == 6000, \
        f"flat 7000 must clip to AV 6000, got {data['claimed_amount']}"
    asmt_after = validate_success(api.get_assessment(asmt["id"], ASSESSOR))
    assert asmt_after["exemption_total"] == 6000
    assert asmt_after["taxable_value"] == 0


def test_interest_accrual_first_period_full_principal(api):
    """PRD §3.9: "the period's interest is that outstanding principal multiplied by the
    `annual_interest_rate`, rounded half-up to a whole cent; this period interest is added to
    `accrued_interest_cents`, and `outstanding_balance_cents` is recomputed."

    Design: Corner/calculations/interest_accrual_first_period_full_principal
    """
    owner, roll, parcel, final, bill, deferral = setup_deferral_with_principal(
        principal_market=200000, annual_interest_rate=0.05
    )
    after = validate_success(api.accrue_interest(deferral["id"], ASSESSOR))
    assert after["accrued_interest_cents"] == 10000, \
        f"first accrual round(200000*0.05)=10000, got {after['accrued_interest_cents']}"
    assert after["outstanding_balance_cents"] == 210000


def test_waterfall_partial_payment_interest_first(api):
    """PRD §3.9: "`applied_to_interest_cents` is the smaller of the payment's `amount_cents`
    and that remaining interest."
    PRD §3.9: "Whatever of the payment is left after interest is `applied_to_principal_cents`,
    capped at the principal not yet retired."
    PRD §3.9: "The interest bucket is always exhausted before any cent touches principal, so a
    partial payment never reduces principal while interest remains."

    Design: Corner/calculations/waterfall_partial_payment_interest_first
    """
    owner, roll, parcel, final, bill, deferral = setup_deferral_with_accrual(
        principal_market=200000, annual_interest_rate=0.05
    )  # accrued 10000, outstanding 210000
    payment = validate_success(
        api.create_payment(deferral["id"], f.create_payment_payload(3000, deferral["version"]), ASSESSOR),
        expected_status=201,
    )
    assert payment["applied_to_interest_cents"] == 3000
    assert payment["applied_to_principal_cents"] == 0
    after = validate_success(api.get_deferral(deferral["id"], ASSESSOR))
    assert after["outstanding_balance_cents"] == 207000


# --- validations -----------------------------------------------------------
def test_settlement_below_requested_out_of_range(api):
    """PRD §3.6: "A **settlement** moves the appeal `UNDER_REVIEW → SETTLED` at an
    officer-supplied `settled_value`; that value must lie between the `requested_taxable_value`
    (inclusive) and the assessment's current `taxable_value` (inclusive), and a value outside
    that closed range is rejected with `ERR_SETTLEMENT_OUT_OF_RANGE`."

    Design: Corner/validations/settlement_below_requested_out_of_range
    """
    owner, roll, parcel, asmt, appeal, ho_id = setup_under_review_appeal(
        requested_taxable_value=80000, market_value=100000
    )
    ho = make_hearing_officer_headers(ho_id)
    resp = api.settle_appeal(appeal["id"], {"settled_value": 70000}, ho)  # below requested 80000
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_OUT_OF_RANGE)


def test_max_rounds_reached_on_third_evidence_request(api):
    """PRD §3.6: "this is permitted only while `round_no` is below 3, and a request once
    `round_no` has reached 3 is refused with `ERR_MAX_ROUNDS_REACHED`."
    PRD §3.6: "The petitioning taxpayer then submits evidence, moving the appeal
    `EVIDENCE_REQUESTED → UNDER_REVIEW` and incrementing `round_no` by 1; the submitting
    taxpayer's `X-User-ID` must equal the appeal's `filed_by_owner_id`."

    Design: Corner/validations/max_rounds_reached_on_third_evidence_request
    """
    owner, roll, parcel, asmt, appeal, ho_id = setup_under_review_appeal(
        requested_taxable_value=80000, market_value=100000
    )
    ho = make_hearing_officer_headers(ho_id)
    tp = make_taxpayer_headers(owner["id"])
    # round 1 -> request/submit -> round 2
    validate_success(api.request_evidence(appeal["id"], {"counter_value": 95000}, ho))
    validate_success(api.submit_evidence(appeal["id"], tp))
    # round 2 -> request/submit -> round 3
    validate_success(api.request_evidence(appeal["id"], {"counter_value": 92000}, ho))
    after = validate_success(api.submit_evidence(appeal["id"], tp))
    assert after["round_no"] == 3
    # round_no is now 3 -> a further request is refused.
    resp = api.request_evidence(appeal["id"], {"counter_value": 90000}, ho)
    validate_error(resp, ApiErrorId.ERR_MAX_ROUNDS_REACHED)


def test_sale_reassessment_required_on_sold_parcel(api):
    """PRD §3.3: "If the parcel is currently `SOLD`, the assessment being created must carry
    `reassessment_event` equal to `SALE`; an attempt to create the post-sale assessment under
    any other event is rejected with `ERR_SALE_REASSESSMENT_REQUIRED` (HTTP 422)."

    Design: Corner/validations/sale_reassessment_required_on_sold_parcel
    """
    o1 = create_owner()
    o2 = create_owner()
    roll = create_open_roll()
    parcel = create_parcel(o1["id"])
    validate_success(api.record_sale(parcel["id"], {"new_owner_id": o2["id"]}, ASSESSOR))
    resp = api.create_assessment(
        f.create_assessment_payload(parcel["id"], roll["id"], 150000, reassessment_event="NONE"),
        ASSESSOR,
    )
    validate_error(resp, ApiErrorId.ERR_SALE_REASSESSMENT_REQUIRED)


def test_duplicate_exemption_same_type_rejected(api):
    """PRD §3.4: "no other exemption of the same `exemption_type` may already be `APPROVED`
    on that assessment, or the approval is rejected with `ERR_DUPLICATE_EXEMPTION`."

    Design: Corner/validations/duplicate_exemption_same_type_rejected
    """
    owner, roll, parcel, asmt = setup_draft_assessment(
        market_value=100000, reassessment_event="NONE", parcel_overrides={"is_primary_residence": True}
    )
    ex1 = claim_exemption(asmt["id"], "HOMESTEAD")
    ex2 = claim_exemption(asmt["id"], "HOMESTEAD")
    validate_success(api.approve_exemption(ex1["id"], REVIEWER))
    resp = api.approve_exemption(ex2["id"], REVIEWER)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EXEMPTION)


def test_senior_exemption_ineligible_under_age_threshold(api):
    """PRD §3.4: "a `SENIOR` exemption requires the owner's age, computed from `birth_date`,
    to be at least the roll's `senior_age_threshold`".
    PRD §3.4: "the owner or parcel must actually satisfy the claimed type's eligibility, or
    the approval is rejected with `ERR_EXEMPTION_INELIGIBLE`".

    Design: Corner/validations/senior_exemption_ineligible_under_age_threshold
    """
    # Owner born 2000 is under the default senior_age_threshold 65.
    owner, roll, parcel, asmt = setup_draft_assessment(
        market_value=100000, reassessment_event="NONE",
        owner_overrides={"birth_date": "2000-01-01T00:00:00.000Z"},
        roll_overrides={"senior_age_threshold": 65},
    )
    exm = claim_exemption(asmt["id"], "SENIOR")
    resp = api.approve_exemption(exm["id"], REVIEWER)
    validate_error(resp, ApiErrorId.ERR_EXEMPTION_INELIGIBLE)


def test_certify_with_nonfinal_assessment_rejected(api):
    """PRD §3.1: "Certifying a roll is permitted only when every `Assessment` belonging to it
    has reached `FINAL`; if any assessment is not yet final, certification fails with
    `ERR_ASSESSMENTS_NOT_FINAL`."

    Design: Corner/validations/certify_with_nonfinal_assessment_rejected
    """
    owner, roll, parcel, asmt = setup_draft_assessment(market_value=100000, reassessment_event="NONE")
    resp = api.certify_tax_roll(roll["id"], ASSESSOR)
    validate_error(resp, ApiErrorId.ERR_ASSESSMENTS_NOT_FINAL)
