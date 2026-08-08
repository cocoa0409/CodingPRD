"""Insurance-claim lifecycle: billed-total, estimated vs final allowed, per-line
patient responsibility, claim uniqueness, and billing-axis independence.

Translates queue-A difficulty instances (dual-variant claim amount, per-line rounding,
parallel clinical/billing axes) and queue-B corner instances (billed-total sum, second
claim rejected).
"""
from test_helpers import (
    validate_success, validate_error, make_counselor_headers,
    create_claim_payload,
    setup_case_with_order, setup_claim_authorized, setup_claim_submitted,
    create_claim,
)
from test_helpers import api_client as _client
from test_helpers.test_users import TEST_USERS

BILLING = TEST_USERS["billing_headers"]


# --------------------------------------------------------------------------- #
# Difficulty: claim_allowed_estimated_vs_final_on_claim
# --------------------------------------------------------------------------- #
def test_claim_estimated_allowed_at_authorization(api):
    """PRD 3.8: "Authorizing a DRAFT claim computes estimated_allowed_cents as
    billed_total_cents multiplied by estimated_allowed_rate, rounded half up to whole
    cents, moves the claim to AUTHORIZED, and sets the case billing_status to
    AUTHORIZED."

    Design: Difficulty/dual_variant_calc/claim_allowed_estimated_vs_final_on_claim
    """
    ctx = setup_claim_authorized(coverage_pct=0.8, estimated_allowed_rate=0.7,
                                 billed_cents=300000)
    # 300000 * 0.7 = 210000
    assert ctx["claim"]["estimated_allowed_cents"] == 210000


def test_claim_final_allowed_and_patient_share_at_adjudication(api):
    """PRD 3.8: "An outcome of PAID sets final_allowed_cents to the sum of the
    adjudicated per-line allowed amounts and computes patient_responsibility_cents".
    PRD 3.8: "For each line in the adjudication payload, the patient's share is that
    line's allowed amount multiplied by one minus coverage_pct, rounded half up to whole
    cents; the per-line rounded shares are then summed to give
    patient_responsibility_cents."

    Design: Difficulty/dual_variant_calc/claim_allowed_estimated_vs_final_on_claim
    """
    ctx = setup_claim_submitted(coverage_pct=0.8, estimated_allowed_rate=0.7,
                                billed_cents=300000)
    res = api.adjudicate_claim(ctx["claim_id"],
                               {"outcome": "PAID", "line_allowed_cents": [250000]}, BILLING)
    claim = validate_success(res, 200)
    assert claim["final_allowed_cents"] == 250000
    # round_half_up(250000 * (1 - 0.8)) = 50000
    assert claim["patient_responsibility_cents"] == 50000


# --------------------------------------------------------------------------- #
# Difficulty: patient_responsibility_perline_round_then_sum
# --------------------------------------------------------------------------- #
def test_patient_responsibility_per_line_round_then_sum(api):
    """PRD 3.8: "For each line in the adjudication payload, the patient's share is that
    line's allowed amount multiplied by one minus coverage_pct, rounded half up to whole
    cents; the per-line rounded shares are then summed to give
    patient_responsibility_cents. Rounding each line before summing is required and
    differs from summing first when fractional cents accumulate across lines."

    Design: Difficulty/combinatorial_formula/patient_responsibility_perline_round_then_sum
    """
    ctx = setup_claim_submitted(coverage_pct=0.85, estimated_allowed_rate=0.5,
                                billed_cents=30404)
    res = api.adjudicate_claim(
        ctx["claim_id"], {"outcome": "PAID", "line_allowed_cents": [10101, 20303]}, BILLING)
    claim = validate_success(res, 200)
    # round(10101*0.15)=1515 ; round(20303*0.15)=3045 ; sum = 4560
    assert claim["patient_responsibility_cents"] == 4560


def test_final_allowed_sums_adjudicated_lines(api):
    """PRD 3.8: "An outcome of PAID sets final_allowed_cents to the sum of the
    adjudicated per-line allowed amounts and computes patient_responsibility_cents".

    Design: Difficulty/combinatorial_formula/patient_responsibility_perline_round_then_sum
    """
    ctx = setup_claim_submitted(coverage_pct=0.85, estimated_allowed_rate=0.5,
                                billed_cents=30404)
    res = api.adjudicate_claim(
        ctx["claim_id"], {"outcome": "PAID", "line_allowed_cents": [10101, 20303]}, BILLING)
    claim = validate_success(res, 200)
    assert claim["final_allowed_cents"] == 30404


# --------------------------------------------------------------------------- #
# Difficulty: case_clinical_and_billing_axes_advance_independently
# --------------------------------------------------------------------------- #
def _assessed_case_with_authorized_claim():
    ctx = setup_case_with_order(
        assess=True,
        members=[{"relationship": "SIBLING", "degree": 1, "affected": True,
                  "age_of_onset": 60}],
        order_overrides={"list_price_cents": 200000,
                         "processing_end": "2026-05-09T09:00:00Z"})
    claim = create_claim(ctx["case_id"], ctx["order_id"], coverage_pct=0.8,
                         estimated_allowed_rate=0.7,
                         line_items=[{"cpt": "81162", "billed_cents": 200000}])
    claim = validate_success(api_client_authorize(claim["id"]), 200)
    ctx["claim"] = claim
    return ctx


def api_client_authorize(claim_id):
    return _client.authorize_claim(claim_id, BILLING)


def test_clinical_axis_unaffected_by_billing_progress(api):
    """PRD 2.6: "A counseling case advances along two wholly independent state axes that
    never share a transition." PRD 3.4: "Assessment computes the pre-test carrier
    probability from the pedigree and moves the case from INTAKE to RISK_ASSESSED."

    Design: Difficulty/non_linear_state_machine/case_clinical_and_billing_axes_advance_independently
    """
    ctx = _assessed_case_with_authorized_claim()
    hdr = make_counselor_headers(ctx["counselor_id"])
    case = validate_success(api.get_case(ctx["case_id"], hdr), 200)
    assert case["clinical_status"] == "RISK_ASSESSED"


def test_billing_axis_reaches_authorized_independently(api):
    """PRD 2.6: "The two axes evolve on their own; a case can be fully disclosed
    clinically while its claim is still unbilled, or paid while clinically still in
    testing." PRD 3.8: "Authorizing a DRAFT claim ... sets the case billing_status to
    AUTHORIZED."

    Design: Difficulty/non_linear_state_machine/case_clinical_and_billing_axes_advance_independently
    """
    ctx = _assessed_case_with_authorized_claim()
    hdr = make_counselor_headers(ctx["counselor_id"])
    case = validate_success(api.get_case(ctx["case_id"], hdr), 200)
    assert case["billing_status"] == "AUTHORIZED"


# --------------------------------------------------------------------------- #
# Corner: claim_billed_total_sums_line_items
# --------------------------------------------------------------------------- #
def test_claim_billed_total_sums_line_items(api):
    """PRD 3.8: "On creation the claim is DRAFT, its billed_total_cents is computed as
    the sum of the line items' billed_cents, and the case's billing_status moves from
    UNBILLED to PENDING_AUTH, incrementing the case version."

    Design: Corner/calculations/claim_billed_total_sums_line_items
    """
    ctx = setup_case_with_order(order_overrides={"list_price_cents": 150000,
                                                 "processing_end": "2026-05-08T09:00:00Z"})
    res = api.create_claim(
        create_claim_payload(ctx["case_id"], ctx["order_id"], coverage_pct=0.8,
                             estimated_allowed_rate=0.7,
                             line_items=[{"cpt": "81162", "billed_cents": 100000},
                                         {"cpt": "81216", "billed_cents": 50000}]),
        BILLING)
    claim = validate_success(res, 201)
    assert claim["billed_total_cents"] == 150000


# --------------------------------------------------------------------------- #
# Corner: second_claim_on_case_rejected
# --------------------------------------------------------------------------- #
def test_second_claim_on_case_rejected(api):
    """PRD 3.8: "At most one non-void claim may exist for a case; a second is rejected
    with ERR_CLAIM_ALREADY_EXISTS."

    Design: Corner/state_machines/second_claim_on_case_rejected
    """
    ctx = setup_case_with_order(order_overrides={"list_price_cents": 100000,
                                                 "processing_end": "2026-05-08T09:00:00Z"})
    create_claim(ctx["case_id"], ctx["order_id"], coverage_pct=0.8,
                 estimated_allowed_rate=0.7,
                 line_items=[{"cpt": "81162", "billed_cents": 100000}])
    res = api.create_claim(
        create_claim_payload(ctx["case_id"], ctx["order_id"], payer_name="Other",
                             member_number="M2", coverage_pct=0.8,
                             estimated_allowed_rate=0.7,
                             line_items=[{"cpt": "81162", "billed_cents": 100000}]),
        BILLING)
    validate_error(res, "ERR_CLAIM_ALREADY_EXISTS", expected_status=409)
