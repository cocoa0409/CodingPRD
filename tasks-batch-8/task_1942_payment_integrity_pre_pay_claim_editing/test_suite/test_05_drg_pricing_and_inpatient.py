"""DRG pricing (outlier add-on, cap, transfer proration), readmission window
boundaries, readmission denial cascade, and inpatient review state gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_drg_validation,
    create_inpatient_claim,
    create_provider,
    decide_inpatient,
    decide_inpatient_payload,
    get_claim,
    get_inpatient_review_by_type,
    get_success_data,
    list_inpatient_reviews,
    make_senior_reviewer_headers,
    record_findings,
    run_claim_edits,
    validate_error,
)

ADMIN = TEST_USERS["plan_admin_headers"]


def test_drg_payment_outlier_uncapped(api):
    """PRD §3.4: "The base amount is 1,000,000 cents ($10,000.00) multiplied
    by the weight of the claim's `drg_code` — the weight table holds 1.5 for
    DRG 470, 0.95 for DRG 193, and 0.72 for DRG 392 — rounded half-up to whole
    cents. When the length of stay exceeds ten days, an outlier add-on
    applies: it is the lesser of 50,000 cents ($500.00) for each day beyond
    the tenth and twenty percent of the base amount"
    PRD §3.4: "every inpatient claim auto-creates an inpatient review of type
    `DRG_VALIDATION`, copying the claim's DRG into `provider_drg_code`."

    Design: Difficulty/combinatorial_formula/drg_payment_outlier_and_transfer
    """
    provider = create_provider(npi="NPI-G1", name="General Hospital")
    claim = create_inpatient_claim(
        provider["id"], "M-I1", "470", "2026-07-01T00:00:00Z",
        "2026-07-14T00:00:00Z", 2000000, discharge_disposition="HOME",
        claim_number="I1")
    screened = run_claim_edits(claim["id"])
    # LOS 13: base 1500000 + outlier min(3*50000, round(0.20*1500000))=150000.
    assert screened["initial_allowed_cents"] == 1650000
    assert screened["allowed_amount_cents"] == 1650000
    assert screened["denied_amount_cents"] == 0
    assert screened["status"] == "PENDED", (
        "the auto-created DRG_VALIDATION review is an open gate"
    )
    review = get_inpatient_review_by_type(claim["id"], "DRG_VALIDATION")
    assert review["status"] == "OPEN"
    assert review["review_type"] == "DRG_VALIDATION"
    assert review["provider_drg_code"] == "470"


def test_drg_payment_transfer_proration(api):
    """PRD §3.4: "When `discharge_disposition` is `TRANSFER`, a per-diem is
    computed as the base amount divided by the DRG's mean length of stay —
    five days for DRG 470, four for 193, three for 392 — rounded half-up to
    whole cents, and the payment is the lesser of the gross payment and the
    per-diem multiplied by the length of stay; for `HOME` the payment is the
    gross amount."
    PRD §3.4: "Either way, `initial_allowed_cents` is set to that baseline"

    Design: Difficulty/combinatorial_formula/drg_payment_outlier_and_transfer
    """
    provider = create_provider(npi="NPI-G2", name="Transfer Hospital")
    claim = create_inpatient_claim(
        provider["id"], "M-I2", "470", "2026-07-01T00:00:00Z",
        "2026-07-03T00:00:00Z", 900000, discharge_disposition="TRANSFER",
        claim_number="I2")
    screened = run_claim_edits(claim["id"])
    # LOS 2, no outlier; per_diem = round(1500000/5) = 300000;
    # payment = min(1500000, 2 * 300000) = 600000.
    assert screened["initial_allowed_cents"] == 600000
    assert screened["allowed_amount_cents"] == 600000


def test_drg_outlier_cap_binds_at_twenty_percent(api):
    """PRD §3.4: "When the length of stay exceeds ten days, an outlier add-on
    applies: it is the lesser of 50,000 cents ($500.00) for each day beyond
    the tenth and twenty percent of the base amount, with that percentage cap
    itself rounded half-up to whole cents; a stay of ten days or fewer earns
    no add-on. The gross payment is the base plus the add-on."

    Design: Corner/calculations/drg_outlier_cap_binds_at_twenty_percent
    """
    provider = create_provider(npi="NPI-OC", name="Cap Prov")
    claim = create_inpatient_claim(
        provider["id"], "M-OC1", "470", "2026-07-01T00:00:00Z",
        "2026-07-21T00:00:00Z", 3000000, discharge_disposition="HOME",
        claim_number="OC1")
    screened = run_claim_edits(claim["id"])
    # LOS 20: naive (20-10)*50000 = 500000, but the 20% cap binds at
    # round(0.20 * 1500000) = 300000, so payment = 1500000 + 300000.
    assert screened["initial_allowed_cents"] == 1800000


def test_readmission_window_inclusive_30_exclusive_31(api):
    """PRD §3.4: "Readmission detection runs for inpatient claims: the
    candidates are the provider's other claims for the same `member_id`, of
    type `INSTITUTIONAL_INPATIENT`, already in `READY_TO_PAY`, `DENIED`, or
    `PAID`, and discharged on or before this claim's admission."
    PRD §3.4: "the first candidate's discharge date is subtracted from this
    claim's `admission_date` to give `gap_days` in whole days, and a gap from
    0 to 30 days inclusive flags a readmission — 30 flags, 31 does not."

    Design: Corner/calculations/readmission_window_inclusive_30_exclusive_31
    """
    provider = create_provider(npi="NPI-RW", name="Window Prov")
    prior = create_inpatient_claim(
        provider["id"], "M-RW", "193", "2026-06-28T00:00:00Z",
        "2026-07-01T00:00:00Z", 500000, claim_number="RW0")
    run_claim_edits(prior["id"])
    close_drg_validation(prior["id"])
    assert get_claim(prior["id"])["status"] == "READY_TO_PAY"

    # Gap exactly 30 days (2026-07-01 -> 2026-07-31): flags.
    claim_x = create_inpatient_claim(
        provider["id"], "M-RW", "193", "2026-07-31T00:00:00Z",
        "2026-08-02T00:00:00Z", 400000, claim_number="RWX")
    screened_x = run_claim_edits(claim_x["id"])
    assert screened_x["readmission_flag"] is True
    review_x = get_inpatient_review_by_type(claim_x["id"], "READMISSION")
    assert review_x["gap_days"] == 30
    assert review_x["prior_claim_id"] == prior["id"]

    # Gap 31 days (2026-07-01 -> 2026-08-01): does not flag. Claim X is still
    # PENDED, so it is excluded from the candidate set anyway.
    claim_y = create_inpatient_claim(
        provider["id"], "M-RW", "193", "2026-08-01T00:00:00Z",
        "2026-08-03T00:00:00Z", 400000, claim_number="RWY")
    screened_y = run_claim_edits(claim_y["id"])
    assert screened_y["readmission_flag"] is False
    reviews_y = list_inpatient_reviews(claim_y["id"], review_type="READMISSION")
    assert reviews_y == [], "gap 31 must not create a READMISSION review"


def test_readmission_denial_cascades_to_claim_denial(api):
    """PRD §3.8: "`DENIED_READMISSION` is available only on a `READMISSION`
    review, else `ERR_INVALID_REQUEST`; it sets `payment_delta_cents` to the
    negative of the claim's current `allowed_amount_cents`, driving allowed to
    zero and denied to the full initial amount, which lands the claim in
    `DENIED` once its gates are terminal."
    PRD §3.4: "A flag sets `readmission_flag` true and auto-creates an
    inpatient review of type `READMISSION` carrying the matched claim as
    `prior_claim_id` and the computed `gap_days`."

    Design: Corner/state_machines/readmission_denial_cascades_to_claim_denial
    """
    provider = create_provider(npi="NPI-RM", name="Readm Prov")
    prior = create_inpatient_claim(
        provider["id"], "M-RM", "193", "2026-07-01T00:00:00Z",
        "2026-07-05T00:00:00Z", 500000, claim_number="RM0")
    run_claim_edits(prior["id"])
    close_drg_validation(prior["id"])
    assert get_claim(prior["id"])["status"] == "READY_TO_PAY"

    # Gap 15 days (2026-07-05 -> 2026-07-20) <= 30: flags.
    claim = create_inpatient_claim(
        provider["id"], "M-RM", "193", "2026-07-20T00:00:00Z",
        "2026-07-24T00:00:00Z", 400000, claim_number="RM1")
    screened = run_claim_edits(claim["id"])
    assert screened["readmission_flag"] is True
    # DRG 193 at LOS 4: base = round(1000000 * 0.95) = 950000, no outlier.
    assert screened["initial_allowed_cents"] == 950000
    assert screened["allowed_amount_cents"] == 950000

    readm = get_inpatient_review_by_type(claim["id"], "READMISSION")
    assert readm["prior_claim_id"] == prior["id"]
    assert readm["gap_days"] == 15

    close_drg_validation(claim["id"])
    record_findings(readm["id"])
    decided = decide_inpatient(readm["id"], "DENIED_READMISSION")
    assert decided["outcome"] == "DENIED_READMISSION"
    assert decided["payment_delta_cents"] == -950000

    final = get_claim(claim["id"])
    assert final["status"] == "DENIED"
    assert final["allowed_amount_cents"] == 0
    assert final["denied_amount_cents"] == 950000
    assert final["initial_allowed_cents"] == 950000


def test_inpatient_decide_from_open_rejected(api):
    """PRD §3.8: "The decision, also a `SeniorReviewer` action, requires
    `FINDINGS_RECORDED`"
    PRD §3.8: "deciding a review that has no recorded findings is rejected
    with `ERR_INPATIENT_REVIEW_NOT_DECIDABLE`."

    Design: Corner/validations/inpatient_decide_from_open_rejected
    """
    provider = create_provider(npi="NPI-ID", name="Inp Prov")
    claim = create_inpatient_claim(
        provider["id"], "M-ID1", "193", "2026-07-01T00:00:00Z",
        "2026-07-05T00:00:00Z", 500000, claim_number="ID1")
    run_claim_edits(claim["id"])
    review = get_inpatient_review_by_type(claim["id"], "DRG_VALIDATION")
    assert review["status"] == "OPEN"

    resp = api.decide_inpatient_review(
        review["id"], decide_inpatient_payload("NO_CHANGE"),
        make_senior_reviewer_headers("senior-1"))
    validate_error(resp, ApiErrorId.ERR_INPATIENT_REVIEW_NOT_DECIDABLE,
                   expected_status=409)
    still_open = get_success_data(api.get_inpatient_review(review["id"], ADMIN))
    assert still_open["status"] == "OPEN"
