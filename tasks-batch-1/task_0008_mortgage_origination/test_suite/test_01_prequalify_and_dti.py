"""Pre-qualification, DTI computation, and DTI/LTV branching.

Every test in this file translates exactly one instance from
SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml. Each test's
docstring carries a verbatim PRD citation (C1/C2/C3) followed by exactly one
`Design:` tag (C4) naming the source instance.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    create_applicant_payload,
    create_loan_application_payload,
    setup_applicant_and_loan_application_draft,
    setup_prequalified_loan_application,
    TEST_USERS,
    ApiErrorId,
)


# =============================================================================
# Queue A — Difficulty
# =============================================================================

def test_dti_front_and_back_diverge_when_monthly_debt_is_added(api, lo_headers):
    """PRD §3.2: "The front_end_dti is then the housing payment divided by
    the monthly income, rounded half-up to four decimal places. The back_end_dti
    adds the applicant's monthly_debt_cents to the housing payment in the
    numerator and divides by the same monthly income, again rounded half-up to
    four decimal places."

    Design: Difficulty/dual_variant_calc/dti_front_vs_back_end_diverge_on_loan_application
    """
    applicant_payload = create_applicant_payload(
        full_name="Alice Q",
        email="alice.dti@test.com",
        ssn_last4="1234",
        annual_income_cents=7_726_104,
        monthly_debt_cents=50_000,
        credit_score=720,
        state_code="CA",
    )
    applicant = validate_success(api.create_applicant(applicant_payload, lo_headers), 201)

    app_payload = create_loan_application_payload(
        applicant["id"],
        property_address="123 Elm",
        property_state_code="CA",
        loan_purpose="PURCHASE",
        requested_loan_amount_cents=30_000_000,
        property_value_cents=31_578_948,
        loan_term_months=360,
    )
    app = validate_success(api.create_loan_application(app_payload, lo_headers), 201)

    res = api.prequalify_loan_application(app["id"], lo_headers)
    after = validate_success(res, 200)

    assert after["status"] == "PREQUALIFIED"
    assert after["prequal_decision"] == "APPROVED"
    assert after["front_end_dti"] == pytest.approx(0.31, abs=1e-4)
    assert after["back_end_dti"] == pytest.approx(0.3877, abs=1e-4)
    assert after["front_end_dti"] != after["back_end_dti"]


def test_prequalify_branches_to_pass_or_deny_on_back_end_dti(api, lo_headers, lo_alt_headers):
    """PRD §3.2: "when the back_end_dti is at most 0.43 and the ltv_ratio is at
    most 0.95, the prequal_decision is set to APPROVED and the loan application
    transitions from DRAFT to PREQUALIFIED. When either threshold is exceeded —
    back_end_dti strictly greater than 0.43 or ltv_ratio strictly greater than
    0.95 — the prequal_decision is set to DENIED and the loan application
    transitions from DRAFT directly to DENIED instead of PREQUALIFIED."

    Design: Difficulty/non_linear_state_machine/loan_application_prequalify_branching_approve_or_deny
    """
    # Applicant PASS — passes both DTI and LTV
    ap_pass = validate_success(
        api.create_applicant(
            create_applicant_payload(
                full_name="G-PASS",
                email="g.pass@test.com",
                ssn_last4="5555",
                annual_income_cents=7_726_104,
                monthly_debt_cents=50_000,
                credit_score=720,
            ),
            lo_headers,
        ),
        201,
    )
    # Applicant FAIL — same income (so front-end DTI stays at 0.31 ≤ ceiling)
    # but monthly debt large enough to push back-end DTI > 0.43.
    # housing ≈ 199_591; (199_591 + 100_000) / 643_842 ≈ 0.4653 > 0.43.
    # This isolates the back-end DTI breach branch from the front-end ceiling.
    ap_fail = validate_success(
        api.create_applicant(
            create_applicant_payload(
                full_name="H-FAIL",
                email="h.fail@test.com",
                ssn_last4="6666",
                annual_income_cents=7_726_104,
                monthly_debt_cents=100_000,
                credit_score=720,
            ),
            lo_headers,
        ),
        201,
    )

    la_pass = validate_success(
        api.create_loan_application(
            create_loan_application_payload(
                ap_pass["id"],
                property_address="PASS-1",
                requested_loan_amount_cents=30_000_000,
                property_value_cents=31_578_948,
                loan_term_months=360,
            ),
            lo_headers,
        ),
        201,
    )
    la_fail = validate_success(
        api.create_loan_application(
            create_loan_application_payload(
                ap_fail["id"],
                property_address="FAIL-1",
                requested_loan_amount_cents=30_000_000,
                property_value_cents=31_578_948,
                loan_term_months=360,
            ),
            lo_headers,
        ),
        201,
    )

    pass_result = validate_success(api.prequalify_loan_application(la_pass["id"], lo_headers), 200)
    assert pass_result["status"] == "PREQUALIFIED"
    assert pass_result["prequal_decision"] == "APPROVED"

    fail_result = validate_success(api.prequalify_loan_application(la_fail["id"], lo_alt_headers), 200)
    assert fail_result["status"] == "DENIED"
    assert fail_result["prequal_decision"] == "DENIED"


def test_dti_differs_across_two_principals_via_nonlinear_amortization(api, lo_headers):
    """PRD §3.2: "the housing payment is the monthly principal-and-interest
    payment computed from the standard amortization formula: the requested loan
    amount in cents is multiplied by the monthly rate, then divided by one minus
    the quantity (one plus the monthly rate) raised to the power of negative
    loan_term_months; the result is rounded half-up to whole cents and stored as
    the housing payment."

    Design: Difficulty/combinatorial_formula/dti_formula_three_plus_inputs_nonlinear_interaction
    """
    ap_a = validate_success(
        api.create_applicant(
            create_applicant_payload(
                full_name="C",
                email="c.combo@test.com",
                ssn_last4="1111",
                annual_income_cents=7_726_104,
                monthly_debt_cents=50_000,
            ),
            lo_headers,
        ),
        201,
    )
    ap_b = validate_success(
        api.create_applicant(
            create_applicant_payload(
                full_name="D",
                email="d.combo@test.com",
                ssn_last4="2222",
                annual_income_cents=7_726_104,
                monthly_debt_cents=50_000,
            ),
            lo_headers,
        ),
        201,
    )
    la_a = validate_success(
        api.create_loan_application(
            create_loan_application_payload(
                ap_a["id"],
                requested_loan_amount_cents=30_000_000,
                property_value_cents=31_578_948,
                loan_term_months=360,
            ),
            lo_headers,
        ),
        201,
    )
    la_b = validate_success(
        api.create_loan_application(
            create_loan_application_payload(
                ap_b["id"],
                requested_loan_amount_cents=25_000_000,
                property_value_cents=31_578_948,
                loan_term_months=360,
            ),
            lo_headers,
        ),
        201,
    )

    res_a = validate_success(api.prequalify_loan_application(la_a["id"], lo_headers), 200)
    res_b = validate_success(api.prequalify_loan_application(la_b["id"], lo_headers), 200)

    assert res_a["front_end_dti"] == pytest.approx(0.31, abs=1e-4)
    assert res_b["front_end_dti"] == pytest.approx(0.2583, abs=1e-4)
    assert res_a["back_end_dti"] == pytest.approx(0.3877, abs=1e-4)
    assert res_b["back_end_dti"] == pytest.approx(0.336, abs=1e-4)


def test_dti_front_end_at_exactly_031_passes_and_just_over_rejected(api, lo_headers):
    """PRD §3.2: "A front-end DTI strictly greater than 0.31 short-circuits
    pre-qualification with ERR_DTI_FRONTEND_TOO_HIGH, ahead of any approve/deny
    branching on back-end DTI or LTV — this is the front-end ceiling."

    Design: Difficulty/boundary_precision_check/dti_front_end_at_exact_031_vs_just_over_on_prequalify
    """
    ap_pass = validate_success(
        api.create_applicant(
            create_applicant_payload(
                full_name="M-PASS",
                email="m.pass@test.com",
                ssn_last4="9003",
                annual_income_cents=7_726_104,
                monthly_debt_cents=50_000,
            ),
            lo_headers,
        ),
        201,
    )
    ap_fail = validate_success(
        api.create_applicant(
            create_applicant_payload(
                full_name="N-FAIL",
                email="n.fail@test.com",
                ssn_last4="9004",
                annual_income_cents=7_716_104,
                monthly_debt_cents=50_000,
            ),
            lo_headers,
        ),
        201,
    )
    la_pass = validate_success(
        api.create_loan_application(
            create_loan_application_payload(
                ap_pass["id"],
                requested_loan_amount_cents=30_000_000,
                property_value_cents=31_578_948,
                loan_term_months=360,
            ),
            lo_headers,
        ),
        201,
    )
    la_fail = validate_success(
        api.create_loan_application(
            create_loan_application_payload(
                ap_fail["id"],
                requested_loan_amount_cents=30_000_000,
                property_value_cents=31_578_948,
                loan_term_months=360,
            ),
            lo_headers,
        ),
        201,
    )

    pass_result = validate_success(
        api.prequalify_loan_application(la_pass["id"], lo_headers), 200
    )
    assert pass_result["status"] == "PREQUALIFIED"
    assert pass_result["front_end_dti"] == pytest.approx(0.31, abs=1e-4)

    fail_res = api.prequalify_loan_application(la_fail["id"], lo_headers)
    validate_error(fail_res, ApiErrorId.ERR_DTI_FRONTEND_TOO_HIGH.value)

    fail_read = validate_success(api.get_loan_application(la_fail["id"], lo_headers), 200)
    assert fail_read["status"] == "DRAFT"


def test_dti_front_equals_back_when_monthly_debt_is_zero(api, lo_headers):
    """PRD §3.2: "The back_end_dti adds the applicant's `monthly_debt_cents`
    to the housing payment in the numerator and divides by the same monthly
    income, again rounded half-up to four decimal places."

    When monthly_debt_cents = 0, the only difference between the two
    variants disappears, so front_end_dti == back_end_dti. This pins the
    divergence at instance 1 to the monthly-debt addend, not to any other
    difference between the two formulas.

    Design: Difficulty/dual_variant_calc/dti_front_vs_back_end_diverge_on_loan_application
    """
    applicant = validate_success(
        api.create_applicant(
            create_applicant_payload(
                full_name="Zero-Debt",
                email="zero.debt@test.com",
                ssn_last4="0001",
                annual_income_cents=7_726_104,
                monthly_debt_cents=0,
                credit_score=720,
            ),
            lo_headers,
        ),
        201,
    )
    app = validate_success(
        api.create_loan_application(
            create_loan_application_payload(
                applicant["id"],
                requested_loan_amount_cents=30_000_000,
                property_value_cents=31_578_948,
                loan_term_months=360,
            ),
            lo_headers,
        ),
        201,
    )
    after = validate_success(api.prequalify_loan_application(app["id"], lo_headers), 200)
    assert after["front_end_dti"] == pytest.approx(after["back_end_dti"], abs=1e-4)


def test_prequalify_branch_to_denied_on_ltv_breach(api, lo_headers):
    """PRD §3.2: "When either threshold is exceeded — back_end_dti strictly
    greater than 0.43 or `ltv_ratio` strictly greater than 0.95 — the
    `prequal_decision` is set to DENIED and the loan application transitions
    from `DRAFT` directly to `DENIED` instead of `PREQUALIFIED`."

    The first instance test exercises the back-end DTI breach branch; this
    complementary test exercises the LTV-breach branch (ratio > 0.95).

    Design: Difficulty/non_linear_state_machine/loan_application_prequalify_branching_approve_or_deny
    """
    applicant = validate_success(
        api.create_applicant(
            create_applicant_payload(
                full_name="LTV-FAIL",
                email="ltv.fail@test.com",
                ssn_last4="9999",
                annual_income_cents=20_000_000,  # large income so DTI passes
                monthly_debt_cents=0,
            ),
            lo_headers,
        ),
        201,
    )
    # Principal=30M, property=30M → LTV = 1.0 > 0.95
    app = validate_success(
        api.create_loan_application(
            create_loan_application_payload(
                applicant["id"],
                requested_loan_amount_cents=30_000_000,
                property_value_cents=30_000_000,
                loan_term_months=360,
            ),
            lo_headers,
        ),
        201,
    )
    after = validate_success(api.prequalify_loan_application(app["id"], lo_headers), 200)
    assert after["status"] == "DENIED"
    assert after["prequal_decision"] == "DENIED"


def test_dti_back_end_differs_across_two_principals_too(api, lo_headers):
    """PRD §3.2: "the housing payment is the monthly principal-and-interest
    payment computed from the standard amortization formula: the requested
    loan amount in cents is multiplied by the monthly rate, then divided by
    one minus the quantity (one plus the monthly rate) raised to the power of
    negative loan_term_months; the result is rounded half-up to whole cents
    and stored as the housing payment."

    Companion to the front-end test in the same Difficulty instance — the
    PRD's amortization formula is non-linear in principal, so back-end DTI
    differs across two applications that differ only in
    `requested_loan_amount_cents`.

    Design: Difficulty/combinatorial_formula/dti_formula_three_plus_inputs_nonlinear_interaction
    """
    ap_a = validate_success(
        api.create_applicant(
            create_applicant_payload(
                full_name="C2",
                email="c2.combo@test.com",
                ssn_last4="1112",
                annual_income_cents=7_726_104,
                monthly_debt_cents=50_000,
            ),
            lo_headers,
        ),
        201,
    )
    ap_b = validate_success(
        api.create_applicant(
            create_applicant_payload(
                full_name="D2",
                email="d2.combo@test.com",
                ssn_last4="2223",
                annual_income_cents=7_726_104,
                monthly_debt_cents=50_000,
            ),
            lo_headers,
        ),
        201,
    )
    la_a = validate_success(
        api.create_loan_application(
            create_loan_application_payload(
                ap_a["id"],
                requested_loan_amount_cents=30_000_000,
                property_value_cents=31_578_948,
                loan_term_months=360,
            ),
            lo_headers,
        ),
        201,
    )
    la_b = validate_success(
        api.create_loan_application(
            create_loan_application_payload(
                ap_b["id"],
                requested_loan_amount_cents=25_000_000,
                property_value_cents=31_578_948,
                loan_term_months=360,
            ),
            lo_headers,
        ),
        201,
    )
    res_a = validate_success(api.prequalify_loan_application(la_a["id"], lo_headers), 200)
    res_b = validate_success(api.prequalify_loan_application(la_b["id"], lo_headers), 200)
    assert res_a["back_end_dti"] != res_b["back_end_dti"]


def test_dti_front_end_at_exact_031_passes_status_is_prequalified(api, lo_headers):
    """PRD §3.2: "If the front-end check passes, the system evaluates the
    auto-branch: when the `back_end_dti` is at most 0.43 and the `ltv_ratio`
    is at most 0.95, the `prequal_decision` is set to APPROVED and the loan
    application transitions from DRAFT to PREQUALIFIED."

    Companion to the just-over case — confirms exact 0.31 is accepted and
    drives the PREQUALIFIED branch.

    Design: Difficulty/boundary_precision_check/dti_front_end_at_exact_031_vs_just_over_on_prequalify
    """
    ap = validate_success(
        api.create_applicant(
            create_applicant_payload(
                full_name="Exact-031",
                email="exact031@test.com",
                ssn_last4="0031",
                annual_income_cents=7_726_104,
                monthly_debt_cents=50_000,
            ),
            lo_headers,
        ),
        201,
    )
    app = validate_success(
        api.create_loan_application(
            create_loan_application_payload(
                ap["id"],
                requested_loan_amount_cents=30_000_000,
                property_value_cents=31_578_948,
                loan_term_months=360,
            ),
            lo_headers,
        ),
        201,
    )
    after = validate_success(api.prequalify_loan_application(app["id"], lo_headers), 200)
    assert after["status"] == "PREQUALIFIED"
    assert after["front_end_dti"] == pytest.approx(0.31, abs=1e-4)
    assert after["prequal_decision"] == "APPROVED"


# =============================================================================
# Queue B — Corner
# =============================================================================

def test_ltv_provisional_recomputed_on_prequalify(api, lo_headers):
    """PRD §3.2: "The provisional ltv_ratio at this stage is the
    requested_loan_amount_cents divided by the applicant-stated
    property_value_cents, rounded half-up to four decimal places."

    Design: Corner/calculations/ltv_provisional_recomputed_on_prequalify_with_stated_value
    """
    applicant, app = setup_applicant_and_loan_application_draft(
        applicant_overrides={
            "full_name": "L",
            "email": "ltv.prov@test.com",
            "ssn_last4": "9020",
            "annual_income_cents": 7_726_104,
        },
        loan_overrides={
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 31_578_948,
            "loan_term_months": 360,
        },
    )
    res = api.prequalify_loan_application(app["id"], lo_headers)
    after = validate_success(res, 200)
    assert after["ltv_ratio"] == pytest.approx(0.95, abs=1e-4)


def test_loan_application_initial_state_is_draft(api, lo_headers):
    """PRD §3.1: "The newly created loan application has its `status` set to
    `DRAFT`, and the system permanently records the originating `LoanOfficer`'s
    `X-User-ID` against the application for use by the later
    segregation-of-duties check at approval time."

    Design: Corner/entities/loan_application_initial_state_draft
    """
    applicant = validate_success(
        api.create_applicant(
            create_applicant_payload(
                full_name="B",
                email="b1.init@test.com",
                ssn_last4="2010",
                annual_income_cents=8_000_000,
            ),
            lo_headers,
        ),
        201,
    )
    res = api.create_loan_application(
        create_loan_application_payload(
            applicant["id"],
            property_address="X",
            requested_loan_amount_cents=30_000_000,
            property_value_cents=35_000_000,
        ),
        lo_headers,
    )
    created = validate_success(res, 201)
    assert created["status"] == "DRAFT"
    assert created["prequal_decision"] is None
    # PRD §2.4 says `version` "begins at 1 (or at whatever the implementation
    # chooses for a freshly created resource)" — so any positive integer is
    # acceptable on initial create.
    assert isinstance(created["version"], int) and created["version"] >= 1


def test_prequalify_on_already_prequalified_returns_invalid_state(api, lo_headers):
    """PRD §3.2: "Pre-qualification is the gateway from `DRAFT` into the rest
    of the lifecycle. It is initiated by a `LoanOfficer` against an application
    that is still in `DRAFT` whose applicant carries a `credit_score` of at
    least 580 and whose `requested_loan_amount_cents` is at or below the
    conforming cap of four hundred million cents (four million dollars)."
    PRD §2.8: "then current-state legality (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/prequalify_from_already_prequalified_returns_invalid_state
    """
    applicant, app_after = setup_prequalified_loan_application()
    assert app_after["status"] == "PREQUALIFIED"

    second = api.prequalify_loan_application(app_after["id"], TEST_USERS["loan_officer_headers"])
    validate_error(second, ApiErrorId.ERR_INVALID_STATE.value)

    final = validate_success(api.get_loan_application(app_after["id"], lo_headers), 200)
    assert final["status"] == "PREQUALIFIED"
