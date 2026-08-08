"""Billing: claim pricing, dual-variant reimbursement, denial/resubmit, void, statement.

Queue A (Difficulty): combinatorial_formula (pricing + statement rounding),
dual_variant_calc (reimbursement), non_linear_state_machine (denied/resubmit cycle),
transitive_cascade (denial -> outstanding balance), compensating_invariant (void
money identity). Queue B (Corner): initial state, reimbursement floor, visit limit,
cross-program reference, statement read.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_program_money_identity,
)
from test_helpers import factories as F
from test_helpers import fixtures as X


# ---------------------------------------------------------------------------
# Difficulty: session billed amount (tiered multiplier + surcharge + cap)
# ---------------------------------------------------------------------------
def test_session_billed_amount_high_risk_telemetry_capped(api):
    """PRD §3.7: "That base is multiplied by the risk multiplier for the program's
    `risk_stratification` — 1.00 for `LOW`, 1.10 for `MODERATE`, and 1.25 for `HIGH` —
    and the product is rounded half up to a whole number of cents. A telemetry surcharge
    of 3000 cents is then added when the billed session's station is of type `TELEMETRY`,
    and nothing is added for a standard station. Finally the amount is capped at 20000
    cents: `billed_amount_cents` is the smaller of the surcharged figure and 20000 cents."

    Design: Difficulty/combinatorial_formula/session_billed_amount_multifactor_cap
    """
    ctx = X.setup_active_program(api, risk_stratification="HIGH", station_type="TELEMETRY",
                                 allowed_amount_cents=25000)
    session = X.create_completed_session(ctx, session_type="MONITORED_EXERCISE")
    claim = X.create_claim(ctx, session["id"])
    # 15000 * 1.25 = 18750, + 3000 telemetry = 21750, capped to 20000
    assert claim["billed_amount_cents"] == 20000


def test_session_billed_amount_moderate_telemetry_uncapped(api):
    """PRD §3.7: "The base rate is chosen by the session's `session_type`: 15000 cents
    for `MONITORED_EXERCISE`, 8000 cents for `EDUCATION`, and 10000 cents for
    `ASSESSMENT`. That base is multiplied by the risk multiplier for the program's
    `risk_stratification` — 1.00 for `LOW`, 1.10 for `MODERATE`, and 1.25 for `HIGH` —
    and the product is rounded half up to a whole number of cents. A telemetry surcharge
    of 3000 cents is then added when the billed session's station is of type `TELEMETRY`,
    and nothing is added for a standard station."

    Design: Difficulty/combinatorial_formula/session_billed_amount_multifactor_cap
    """
    ctx = X.setup_active_program(api, risk_stratification="MODERATE", station_type="TELEMETRY")
    session = X.create_completed_session(ctx, session_type="MONITORED_EXERCISE")
    claim = X.create_claim(ctx, session["id"])
    # 15000 * 1.10 = 16500, + 3000 telemetry = 19500 (< 20000 cap)
    assert claim["billed_amount_cents"] == 19500


# ---------------------------------------------------------------------------
# Difficulty: estimated vs adjudicated reimbursement (dual variant)
# ---------------------------------------------------------------------------
def test_claim_estimated_then_adjudicated_reimbursement(api):
    """PRD §3.7: "The `estimated_reimbursement_cents` is the greater of zero and the
    quantity (the smaller of `billed_amount_cents` and the authorization's
    `allowed_amount_cents`, minus the `copay_cents`). The
    `estimated_patient_responsibility_cents` is `billed_amount_cents` minus
    `estimated_reimbursement_cents`."
    PRD §3.7: "On a `PAID` outcome, the payer returns an `adjudicated_allowed_cents`;
    the `adjudicated_reimbursement_cents` becomes the greater of zero and
    (`adjudicated_allowed_cents` minus `copay_cents`), and the claim's
    `patient_responsibility_cents` becomes `billed_amount_cents` minus
    `adjudicated_reimbursement_cents`."

    Design: Difficulty/dual_variant_calc/claim_estimated_vs_adjudicated_reimbursement
    """
    ctx = X.setup_active_program(api, allowed_amount_cents=18000, copay_cents=2000)
    session = X.create_completed_session(ctx)
    claim = X.create_claim(ctx, session["id"])
    assert claim["billed_amount_cents"] == 19500
    assert claim["estimated_reimbursement_cents"] == 16000
    assert claim["estimated_patient_responsibility_cents"] == 3500

    validate_success(api.submit_claim(claim["id"], ctx["billing"]))
    paid = validate_success(api.adjudicate_claim(
        claim["id"], {"outcome": "PAID", "adjudicated_allowed_cents": 17000}, ctx["billing"]
    ))
    assert paid["adjudicated_reimbursement_cents"] == 15000
    assert paid["patient_responsibility_cents"] == 4500


def test_claim_adjudicated_reimbursement_differs_from_estimate(api):
    """PRD §3.7: "On a `PAID` outcome, the payer returns an `adjudicated_allowed_cents`;
    the `adjudicated_reimbursement_cents` becomes the greater of zero and
    (`adjudicated_allowed_cents` minus `copay_cents`), and the claim's
    `patient_responsibility_cents` becomes `billed_amount_cents` minus
    `adjudicated_reimbursement_cents`."

    Design: Difficulty/dual_variant_calc/claim_estimated_vs_adjudicated_reimbursement
    """
    ctx = X.setup_active_program(api, allowed_amount_cents=18000, copay_cents=2000)
    session = X.create_completed_session(ctx)
    claim = X.create_claim(ctx, session["id"])
    assert claim["estimated_reimbursement_cents"] == 16000  # min(19500,18000)-2000

    validate_success(api.submit_claim(claim["id"], ctx["billing"]))
    paid = validate_success(api.adjudicate_claim(
        claim["id"], {"outcome": "PAID", "adjudicated_allowed_cents": 19000}, ctx["billing"]
    ))
    # 19000 - 2000 = 17000 reimbursed; 19500 - 17000 = 2500 responsibility
    assert paid["adjudicated_reimbursement_cents"] == 17000
    assert paid["patient_responsibility_cents"] == 2500


# ---------------------------------------------------------------------------
# Difficulty: denied -> resubmit cycle
# ---------------------------------------------------------------------------
def test_claim_denied_then_resubmitted_cycle(api):
    """PRD §3.7: "Adjudicating a `SUBMITTED` claim (else `ERR_CLAIM_NOT_ADJUDICABLE`)
    takes an `outcome` of either `PAID` or `DENIED`."
    PRD §3.7: "A `DENIED` claim may be resubmitted, moving it from `DENIED` back to
    `SUBMITTED` (only from `DENIED`, else `ERR_CLAIM_NOT_DENIED`)."

    Design: Difficulty/non_linear_state_machine/claim_denied_resubmit_cycle
    """
    ctx = X.setup_active_program(api)
    session = X.create_completed_session(ctx)
    claim = X.create_claim(ctx, session["id"])
    validate_success(api.submit_claim(claim["id"], ctx["billing"]))
    denied = validate_success(api.adjudicate_claim(
        claim["id"], {"outcome": "DENIED", "denial_reason": "coding error"}, ctx["billing"]
    ))
    assert denied["status"] == "DENIED"
    resubmitted = validate_success(api.resubmit_claim(claim["id"], ctx["billing"]))
    assert resubmitted["status"] == "SUBMITTED"


def test_resubmit_non_denied_claim_rejected(api):
    """PRD §3.7: "A `DENIED` claim may be resubmitted, moving it from `DENIED` back to
    `SUBMITTED` (only from `DENIED`, else `ERR_CLAIM_NOT_DENIED`)."

    Design: Difficulty/non_linear_state_machine/claim_denied_resubmit_cycle
    """
    ctx = X.setup_active_program(api)
    session = X.create_completed_session(ctx)
    claim = X.create_claim(ctx, session["id"])
    validate_success(api.submit_claim(claim["id"], ctx["billing"]))  # now SUBMITTED, not DENIED
    resp = api.resubmit_claim(claim["id"], ctx["billing"])
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_DENIED, expected_status=409)


# ---------------------------------------------------------------------------
# Difficulty: claim denial increases program outstanding balance
# ---------------------------------------------------------------------------
def test_claim_denial_increases_outstanding_balance(api):
    """PRD §3.7: "On a `DENIED` outcome, a `denial_reason` is recorded, the claim's
    `patient_responsibility_cents` becomes the full `billed_amount_cents`, and the
    program's `outstanding_balance_cents` increases by that `billed_amount_cents`."

    Design: Difficulty/transitive_cascade/claim_denial_increases_outstanding_balance
    """
    ctx = X.setup_active_program(api)
    session = X.create_completed_session(ctx)
    claim = X.create_claim(ctx, session["id"])
    validate_success(api.submit_claim(claim["id"], ctx["billing"]))
    denied = validate_success(api.adjudicate_claim(
        claim["id"], {"outcome": "DENIED", "denial_reason": "not medically necessary"}, ctx["billing"]
    ))
    assert denied["status"] == "DENIED"
    assert denied["patient_responsibility_cents"] == 19500
    prog = validate_success(api.get_program(ctx["program_id"], ctx["coord"]))
    assert prog["outstanding_balance_cents"] == 19500


def test_claim_resubmit_reverses_outstanding_balance(api):
    """PRD §3.7: "A `DENIED` claim may be resubmitted, moving it from `DENIED` back to
    `SUBMITTED` (only from `DENIED`, else `ERR_CLAIM_NOT_DENIED`); resubmission subtracts
    that claim's `billed_amount_cents` from the program's `outstanding_balance_cents`,
    reversing the denial's balance addition."

    Design: Difficulty/transitive_cascade/claim_denial_increases_outstanding_balance
    """
    ctx = X.setup_active_program(api)
    session = X.create_completed_session(ctx)
    claim = X.create_claim(ctx, session["id"])
    validate_success(api.submit_claim(claim["id"], ctx["billing"]))
    validate_success(api.adjudicate_claim(
        claim["id"], {"outcome": "DENIED", "denial_reason": "coding"}, ctx["billing"]
    ))
    prog_denied = validate_success(api.get_program(ctx["program_id"], ctx["coord"]))
    assert prog_denied["outstanding_balance_cents"] == 19500

    validate_success(api.resubmit_claim(claim["id"], ctx["billing"]))
    prog_after = validate_success(api.get_program(ctx["program_id"], ctx["coord"]))
    assert prog_after["outstanding_balance_cents"] == 0


# ---------------------------------------------------------------------------
# Difficulty: void claim conserves program money identity
# ---------------------------------------------------------------------------
def test_void_submitted_claim_zeroes_totals(api):
    """PRD §2.9: "over the set of non-void claims the billed total always equals the
    sum of reimbursed and patient-responsibility totals."
    PRD §3.7: "A claim may also be voided from `DRAFT`, `SUBMITTED`, or `DENIED` (else
    `ERR_CLAIM_NOT_VOIDABLE`), moving it to `VOID`; voiding decrements the
    authorization's `visits_billed` by one and recomputes the program's billing totals".

    Design: Difficulty/compensating_invariant/void_claim_conserves_program_money_identity
    """
    ctx = X.setup_active_program(api, allowed_amount_cents=18000, copay_cents=2000)
    session = X.create_completed_session(ctx)
    claim = X.create_claim(ctx, session["id"])
    validate_success(api.submit_claim(claim["id"], ctx["billing"]))

    before = validate_success(api.get_program(ctx["program_id"], ctx["coord"]))
    assert before["total_billed_cents"] == 19500
    assert before["total_reimbursed_cents"] == 16000
    assert before["total_patient_responsibility_cents"] == 3500
    assert_program_money_identity(before)

    voided = validate_success(api.void_claim(claim["id"], ctx["billing"]))
    assert voided["status"] == "VOID"
    after = validate_success(api.get_program(ctx["program_id"], ctx["coord"]))
    assert after["total_billed_cents"] == 0
    assert after["total_reimbursed_cents"] == 0
    assert after["total_patient_responsibility_cents"] == 0
    assert_program_money_identity(after)


def test_void_claim_restores_authorization_visits_billed(api):
    """PRD §3.7: "Creating a claim increments the authorization's `visits_billed` by
    one and starts the claim in `DRAFT`."
    PRD §3.7: "voiding decrements the authorization's `visits_billed` by one and
    recomputes the program's billing totals".

    Design: Difficulty/compensating_invariant/void_claim_conserves_program_money_identity
    """
    ctx = X.setup_active_program(api)
    session = X.create_completed_session(ctx)
    claim = X.create_claim(ctx, session["id"])
    validate_success(api.submit_claim(claim["id"], ctx["billing"]))

    auth_before = validate_success(api.get_authorization(ctx["authorization_id"], ctx["coord"]))
    assert auth_before["visits_billed"] == 1

    validate_success(api.void_claim(claim["id"], ctx["billing"]))
    auth_after = validate_success(api.get_authorization(ctx["authorization_id"], ctx["coord"]))
    assert auth_after["visits_billed"] == 0
    prog = validate_success(api.get_program(ctx["program_id"], ctx["coord"]))
    assert prog["total_billed_cents"] == 0


# ---------------------------------------------------------------------------
# Difficulty: patient statement dollar rounding order
# ---------------------------------------------------------------------------
def test_patient_statement_rounds_per_claim_then_sums(api):
    """PRD §2.7: "The patient statement dollar total (§3.7) rounds each individual
    claim's patient-responsibility cents to whole dollars — half up — and only then
    sums those per-claim dollar amounts; the order matters and must not be replaced by
    summing cents first and rounding once."
    PRD §3.7: "For each such claim, its `patient_responsibility_cents` is converted to
    whole dollars by rounding half up; these per-claim dollar figures are then summed to
    produce `statement_total_dollars`."

    Design: Difficulty/combinatorial_formula/patient_statement_dollar_rounding_order
    """
    ctx = X.setup_active_program(api, risk_stratification="LOW", station_type="STANDARD",
                                 allowed_amount_cents=20000, copay_cents=1250, authorized_visits=5)
    s1 = X.create_completed_session(ctx)
    s2 = X.create_completed_session(ctx)
    c1 = X.create_claim(ctx, s1["id"])
    c2 = X.create_claim(ctx, s2["id"])
    assert c1["patient_responsibility_cents"] == 1250
    assert c2["patient_responsibility_cents"] == 1250

    stmt = validate_success(api.get_statement(ctx["program_id"], ctx["billing"]))
    # round_half_up(12.50) + round_half_up(12.50) = 13 + 13 = 26 (sum-then-round would be 25)
    assert stmt["statement_total_dollars"] == 26
    assert stmt["total_patient_responsibility_cents"] == 2500


def test_patient_statement_single_claim_rounds_half_up(api):
    """PRD §3.7: "For each such claim, its `patient_responsibility_cents` is converted
    to whole dollars by rounding half up; these per-claim dollar figures are then summed
    to produce `statement_total_dollars`."

    Design: Difficulty/combinatorial_formula/patient_statement_dollar_rounding_order
    """
    ctx = X.setup_active_program(api, risk_stratification="LOW", station_type="STANDARD",
                                 allowed_amount_cents=20000, copay_cents=1250, authorized_visits=5)
    s1 = X.create_completed_session(ctx)
    c1 = X.create_claim(ctx, s1["id"])
    assert c1["patient_responsibility_cents"] == 1250

    stmt = validate_success(api.get_statement(ctx["program_id"], ctx["billing"]))
    assert stmt["statement_total_dollars"] == 13  # round_half_up(12.50) = 13
    assert stmt["total_patient_responsibility_cents"] == 1250
    assert stmt["claim_count"] == 1


# ---------------------------------------------------------------------------
# Corner
# ---------------------------------------------------------------------------
def test_claim_initial_state_is_draft(api):
    """PRD §3.7: "Creating a claim increments the authorization's `visits_billed` by
    one and starts the claim in `DRAFT`."

    Design: Corner/state_machines/claim_initial_state_is_draft
    """
    ctx = X.setup_active_program(api)
    session = X.create_completed_session(ctx)
    claim = X.create_claim(ctx, session["id"])
    assert claim["status"] == "DRAFT"


def test_estimated_reimbursement_floors_at_zero(api):
    """PRD §3.7: "The `estimated_reimbursement_cents` is the greater of zero and the
    quantity (the smaller of `billed_amount_cents` and the authorization's
    `allowed_amount_cents`, minus the `copay_cents`). The
    `estimated_patient_responsibility_cents` is `billed_amount_cents` minus
    `estimated_reimbursement_cents`."

    Design: Corner/calculations/estimated_reimbursement_floors_at_zero
    """
    ctx = X.setup_active_program(api, risk_stratification="LOW", station_type="STANDARD",
                                 allowed_amount_cents=1000, copay_cents=2000)
    session = X.create_completed_session(ctx)
    claim = X.create_claim(ctx, session["id"])
    assert claim["billed_amount_cents"] == 15000
    assert claim["estimated_reimbursement_cents"] == 0
    assert claim["estimated_patient_responsibility_cents"] == 15000


def test_claim_visit_limit_reached_returns_error(api):
    """PRD §3.7: "because a claim consumes a payer visit — creation is refused once the
    authorization's `visits_billed` has reached its `authorized_visits`, rejected as
    `ERR_VISIT_LIMIT_REACHED`."

    Design: Corner/validations/claim_visit_limit_reached_returns_error
    """
    ctx = X.setup_active_program(api, authorized_visits=1)
    s1 = X.create_completed_session(ctx)
    s2 = X.create_completed_session(ctx)
    X.create_claim(ctx, s1["id"])  # visits_billed -> 1 == authorized_visits
    resp = X.create_claim(ctx, s2["id"], return_response=True)
    validate_error(resp, ApiErrorId.ERR_VISIT_LIMIT_REACHED, expected_status=409)


def test_claim_session_from_other_program_returns_cross_program(api):
    """PRD §2.5: "When a claim is created, the referenced session and authorization
    must both belong to the same program as the claim; ... A reference that resolves but
    points into the wrong program (or otherwise fails cross-aggregate consistency) is
    rejected with `ERR_CROSS_PROGRAM_REFERENCE` (HTTP 409)."

    Design: Corner/validations/claim_session_from_other_program_returns_cross_program
    """
    ctx_a = X.setup_active_program(api)
    session_a = X.create_completed_session(ctx_a)
    ctx_b = X.setup_active_program(api)
    payload = F.create_claim_payload(ctx_b["program_id"], session_a["id"], ctx_b["authorization_id"])
    resp = api.create_claim(payload, ctx_b["billing"])
    validate_error(resp, ApiErrorId.ERR_CROSS_PROGRAM_REFERENCE, expected_status=409)


def test_statement_outstanding_balance_computed_read(api):
    """PRD §3.7: "The statement response also reports the `claim_count` of non-void
    claims, the program's `total_patient_responsibility_cents`, and its
    `outstanding_balance_cents`."
    PRD §3.7: "On a `DENIED` outcome, a `denial_reason` is recorded, the claim's
    `patient_responsibility_cents` becomes the full `billed_amount_cents`, and the
    program's `outstanding_balance_cents` increases by that `billed_amount_cents`."

    Design: Corner/endpoints/statement_outstanding_balance_computed_read
    """
    ctx = X.setup_active_program(api)
    session = X.create_completed_session(ctx)
    claim = X.create_claim(ctx, session["id"])
    validate_success(api.submit_claim(claim["id"], ctx["billing"]))
    validate_success(api.adjudicate_claim(
        claim["id"], {"outcome": "DENIED", "denial_reason": "coding"}, ctx["billing"]
    ))
    stmt = validate_success(api.get_statement(ctx["program_id"], ctx["billing"]))
    assert stmt["outstanding_balance_cents"] == 19500
    assert stmt["claim_count"] == 1
