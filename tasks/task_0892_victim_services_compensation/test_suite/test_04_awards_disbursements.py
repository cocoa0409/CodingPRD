"""Award calculation, approval/payment axes, and disbursement cascades
(PRD §3.6, §3.7)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    assert_award, assert_disbursement,
)
from test_helpers import fixtures as fx
from test_helpers import factories as fac

ADMIN = TEST_USERS["program_admin_headers"]
ADJ = TEST_USERS["adjudicator_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


# --------------------------------------------------------------------------
# Difficulty — combinatorial_formula: nested category + overall caps
# --------------------------------------------------------------------------
def _award_over_two_caps(api):
    """Eligible case with three APPROVED claims: MEDICAL 1.5M + MEDICAL 2.0M
    (cat total 3.5M > medical_cap 3.0M) and FUNERAL 1.2M (> funeral_cap 1.0M).
    Returns the created award."""
    program = fx.make_program(api)  # medical_cap 3M, funeral_cap 1M, overall_cap 5M
    _, case = fx.make_eligible_case(api, program=program, crime_type="HOMICIDE")
    fx.make_approved_claim(api, case["id"], "MEDICAL", claimed_amount_cents=1500000, verified_amount_cents=1500000)
    fx.make_approved_claim(api, case["id"], "MEDICAL", claimed_amount_cents=2000000, verified_amount_cents=2000000)
    fx.make_approved_claim(api, case["id"], "FUNERAL", claimed_amount_cents=1200000, verified_amount_cents=1200000)
    version = fx.program_version(api, program["id"])
    return validate_success(api.create_award(fac.create_award_payload(case["id"], version), ADJ), 201)


def test_award_gross_applies_per_category_caps(api):
    """PRD §3.6: "For each of the four categories, the system sums the
    `net_claim_cents` of that case's approved claims in the category, then caps that
    per-category total at the program's matching cap ... taking the smaller of the
    total and the cap. The `gross_award_cents` is the sum of these four capped
    per-category subtotals."

    Design: Difficulty/combinatorial_formula/award_net_nested_category_and_overall_caps
    """
    award = _award_over_two_caps(api)
    # medical 3.5M -> capped 3.0M; funeral 1.2M -> capped 1.0M; gross = 4.0M.
    assert award["gross_award_cents"] == 4000000


def test_award_net_applies_overall_case_cap(api):
    """PRD §3.6: "The `net_award_cents` is the gross award capped a second time at the
    program's `overall_case_cap_cents` — the smaller of the gross award and the overall
    case cap — and floored at 0. This is a nested cap: each category is limited first,
    then the whole award is limited by the per-case ceiling."

    Design: Difficulty/combinatorial_formula/award_net_nested_category_and_overall_caps
    """
    award = _award_over_two_caps(api)
    # overall cap 5M is non-binding; net = min(4M, 5M) = 4M.
    assert award["net_award_cents"] == 4000000


# --------------------------------------------------------------------------
# Difficulty — boundary_precision_check: award approve on empty approved-claim set
# --------------------------------------------------------------------------
def _award_with_only_denied_claim(api):
    """Eligible case whose single claim is DENIED; award created (net 0).
    Returns (program, award)."""
    program = fx.make_program(api)
    _, case = fx.make_eligible_case(api, program=program)
    claim = fx.make_claim(api, case["id"], "MEDICAL", claimed_amount_cents=500000)
    fx.claim_transition(api, claim["id"], "SUBMITTED", role="IntakeCounselor")
    fx.claim_transition(api, claim["id"], "UNDER_REVIEW")
    fx.claim_transition(api, claim["id"], "DENIED", user_id="adj-1")
    version = fx.program_version(api, program["id"])
    award = validate_success(api.create_award(fac.create_award_payload(case["id"], version), ADJ), 201)
    return program, award


def test_award_net_zero_when_only_claim_denied(api):
    """PRD §3.6: "The award figure is built from the case's `APPROVED` claims only;
    claims still in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, or `DENIED` contribute
    nothing."

    Design: Difficulty/boundary_precision_check/award_approve_zero_net_empty_claim_set_rejected
    """
    _, award = _award_with_only_denied_claim(api)
    assert award["net_award_cents"] == 0


def test_award_approve_zero_net_rejected(api):
    """PRD §3.6: "an `Adjudicator` approves a calculated award (`CALCULATED →
    APPROVED`), which is permitted only when `net_award_cents` is greater than 0; an
    award with nothing eligible to pay is rejected with `ERR_NO_ELIGIBLE_CLAIMS` (HTTP
    422)."

    Design: Difficulty/boundary_precision_check/award_approve_zero_net_empty_claim_set_rejected
    """
    _, award = _award_with_only_denied_claim(api)
    resp = api.transition_award(award["id"], {"to_status": "APPROVED"}, ADJ)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_CLAIMS.value)


# --------------------------------------------------------------------------
# Difficulty — non_linear_state_machine: parallel approval & payment axes
# --------------------------------------------------------------------------
def test_award_approval_axis_reaches_finalized_independently(api):
    """PRD §3.6: "A `FinanceOfficer` then finalizes an approved award (`APPROVED →
    FINALIZED`), which carries no precondition and sets `approval_status` to
    `FINALIZED`. The **payment axis** (`payment_status`) is derived from disbursements
    and is described in §3.7."

    Design: Difficulty/non_linear_state_machine/award_parallel_approval_and_payment_axes
    """
    program, case, claim, award, disb = fx.setup_finalized_award_with_disbursement(
        api, claimed_amount_cents=1000000, verified_amount_cents=1000000,
        disbursement_amount_cents=400000, payee_type="VICTIM",
    )
    fx.disbursement_transition(api, disb["id"], "PAID")
    got = validate_success(api.get_award(award["id"], FINANCE))
    assert got["approval_status"] == "FINALIZED"


def test_award_payment_axis_partially_paid_independently(api):
    """PRD §3.7: "The `payment_status` derivation compares `amount_paid_cents` to
    `net_award_cents`: nothing paid leaves it `UNPAID`, a positive amount below the net
    award makes it `PARTIALLY_PAID`, and an amount at or above the net award makes it
    `FULLY_PAID`."

    Design: Difficulty/non_linear_state_machine/award_parallel_approval_and_payment_axes
    """
    program, case, claim, award, disb = fx.setup_finalized_award_with_disbursement(
        api, claimed_amount_cents=1000000, verified_amount_cents=1000000,
        disbursement_amount_cents=400000, payee_type="VICTIM",
    )
    fx.disbursement_transition(api, disb["id"], "PAID")
    got = validate_success(api.get_award(award["id"], FINANCE))
    assert got["payment_status"] == "PARTIALLY_PAID"
    assert got["amount_paid_cents"] == 400000


# --------------------------------------------------------------------------
# Difficulty — cross_entity_state_dependency: disbursement requires approved award
# --------------------------------------------------------------------------
def test_disbursement_blocked_when_award_calculated(api):
    """PRD §3.7: "the parent award's `approval_status` must be `APPROVED` or
    `FINALIZED`; scheduling against a merely calculated award is rejected with
    `ERR_AWARD_NOT_APPROVED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/disbursement_requires_award_approved
    """
    program = fx.make_program(api)
    _, case = fx.make_eligible_case(api, program=program)
    fx.make_approved_claim(api, case["id"], "MEDICAL", claimed_amount_cents=1000000, verified_amount_cents=1000000)
    version = fx.program_version(api, program["id"])
    award = fx.make_award(api, case["id"], version)  # CALCULATED, not approved
    resp = api.create_disbursement(fac.create_disbursement_payload(award["id"], amount_cents=100000), FINANCE)
    validate_error(resp, ApiErrorId.ERR_AWARD_NOT_APPROVED.value)


def test_disbursement_allowed_when_award_approved(api):
    """PRD §3.7: "the parent award's `approval_status` must be `APPROVED` or
    `FINALIZED`; scheduling against a merely calculated award is rejected with
    `ERR_AWARD_NOT_APPROVED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/disbursement_requires_award_approved
    """
    program = fx.make_program(api)
    _, case = fx.make_eligible_case(api, program=program)
    fx.make_approved_claim(api, case["id"], "MEDICAL", claimed_amount_cents=1000000, verified_amount_cents=1000000)
    version = fx.program_version(api, program["id"])
    award = fx.make_award(api, case["id"], version)
    fx.award_transition(api, award["id"], "APPROVED")
    resp = api.create_disbursement(fac.create_disbursement_payload(award["id"], amount_cents=100000), FINANCE)
    disb = validate_success(resp, 201)
    assert_disbursement(disb)
    assert disb["status"] == "SCHEDULED"


# --------------------------------------------------------------------------
# Corner — validations: disbursement over-scheduling
# --------------------------------------------------------------------------
def test_disbursement_exceeds_award_net_rejected(api):
    """PRD §3.7: "the new amount together with the amounts of the award's existing
    disbursements that are in `SCHEDULED` or `PAID` status may not exceed the award's
    `net_award_cents`; an over-scheduling is rejected with
    `ERR_DISBURSEMENT_EXCEEDS_AWARD` (HTTP 422)."

    Design: Corner/validations/disbursement_exceeds_award_net_rejected
    """
    program = fx.make_program(api)
    _, case = fx.make_eligible_case(api, program=program)
    fx.make_approved_claim(api, case["id"], "MEDICAL", claimed_amount_cents=1000000, verified_amount_cents=1000000)
    version = fx.program_version(api, program["id"])
    award = fx.make_award(api, case["id"], version)
    fx.award_transition(api, award["id"], "APPROVED")
    fx.make_disbursement(api, award["id"], amount_cents=700000, payee_type="VICTIM")
    # 700,000 + 400,000 = 1,100,000 > net 1,000,000.
    resp = api.create_disbursement(
        fac.create_disbursement_payload(award["id"], amount_cents=400000, pay_run_date="2026-05-11"), FINANCE
    )
    validate_error(resp, ApiErrorId.ERR_DISBURSEMENT_EXCEEDS_AWARD.value)


# --------------------------------------------------------------------------
# Difficulty — transitive_cascade: PAID bubbles disbursement -> award -> program
# --------------------------------------------------------------------------
def test_pay_bubbles_award_to_fully_paid(api):
    """PRD §3.7: "the award's `amount_paid_cents` is recomputed as the sum of its
    `PAID` disbursements, the award's `payment_status` is re-derived ... an amount at
    or above the net award makes it `FULLY_PAID`."

    Design: Difficulty/transitive_cascade/disbursement_pay_bubbles_to_award_then_program_depth3
    """
    program, case, claim, award, disb = fx.setup_finalized_award_with_disbursement(
        api, claimed_amount_cents=1000000, verified_amount_cents=1000000,
        disbursement_amount_cents=1000000, payee_type="MEDICAL_PROVIDER",
    )
    fx.disbursement_transition(api, disb["id"], "PAID")
    got = validate_success(api.get_award(award["id"], FINANCE))
    assert got["payment_status"] == "FULLY_PAID"
    assert got["amount_paid_cents"] == 1000000


def test_pay_bubbles_program_budget_disbursed(api):
    """PRD §3.7: "Payment cascades: the program's `budget_disbursed_cents` increases
    by the disbursement's `amount_cents`, the award's `amount_paid_cents` is
    recomputed as the sum of its `PAID` disbursements ..."

    Design: Difficulty/transitive_cascade/disbursement_pay_bubbles_to_award_then_program_depth3
    """
    program, case, claim, award, disb = fx.setup_finalized_award_with_disbursement(
        api, claimed_amount_cents=1000000, verified_amount_cents=1000000,
        disbursement_amount_cents=1000000, payee_type="MEDICAL_PROVIDER",
    )
    fx.disbursement_transition(api, disb["id"], "PAID")
    prog = validate_success(api.get_program(program["id"], ADMIN))
    assert prog["budget_disbursed_cents"] == 1000000


# --------------------------------------------------------------------------
# Difficulty — compensating_invariant: clawback conserves budget_disbursed
# --------------------------------------------------------------------------
def test_clawback_restores_program_budget_disbursed(api):
    """PRD §3.7: "A paid disbursement may later be clawed back (`PAID →
    CLAWED_BACK`): the program's `budget_disbursed_cents` is decreased by the
    `amount_cents`, and the award's `amount_paid_cents` and `payment_status` are
    recomputed ..."

    Design: Difficulty/compensating_invariant/disbursement_clawback_conserves_budget_disbursed
    """
    program, case, claim, award, disb = fx.setup_finalized_award_with_disbursement(
        api, claimed_amount_cents=1000000, verified_amount_cents=1000000,
        disbursement_amount_cents=1000000, payee_type="MEDICAL_PROVIDER",
    )
    fx.disbursement_transition(api, disb["id"], "PAID")
    fx.disbursement_transition(api, disb["id"], "CLAWED_BACK")
    prog = validate_success(api.get_program(program["id"], ADMIN))
    assert prog["budget_disbursed_cents"] == 0


def test_clawback_reverts_award_payment_to_unpaid(api):
    """PRD §3.7: "which may revert the award from `FULLY_PAID` back to
    `PARTIALLY_PAID` if the paid total drops below the net award. The payment axis is
    thus fully re-derived from the currently-paid disbursements on every disbursement
    mutation."

    Design: Difficulty/compensating_invariant/disbursement_clawback_conserves_budget_disbursed
    """
    program, case, claim, award, disb = fx.setup_finalized_award_with_disbursement(
        api, claimed_amount_cents=1000000, verified_amount_cents=1000000,
        disbursement_amount_cents=1000000, payee_type="MEDICAL_PROVIDER",
    )
    fx.disbursement_transition(api, disb["id"], "PAID")
    fx.disbursement_transition(api, disb["id"], "CLAWED_BACK")
    got = validate_success(api.get_award(award["id"], FINANCE))
    assert got["amount_paid_cents"] == 0
    assert got["payment_status"] == "UNPAID"
