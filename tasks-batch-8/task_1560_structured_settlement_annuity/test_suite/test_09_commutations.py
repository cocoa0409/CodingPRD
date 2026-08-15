"""Commutation requests: valuation, rider/statute legality, eligible-set boundaries,
and the death-claim gate (PRD §3.7)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    setup_active_case, create_claim, settle_claim, create_commutation,
    set_clock, get_payment, get_policy, issue_payment,
    TEST_USERS,
)

COMPLIANCE = TEST_USERS["compliance_officer_headers"]
READER = TEST_USERS["reader_headers"]

LOW_CAP_CA = {"state_code": "CA", "sspa_max_discount_rate_bps": 400}
TWO_PAYMENTS = [{"due_date": "2030-01-01", "base_amount_cents": 100000},
                {"due_date": "2031-01-01", "base_amount_cents": 100000}]
RIDER_DH = {"commutation_rider": "DEATH_AND_HARDSHIP"}


def _setup_commutation_case(case_number, profile_overrides=None, policy_overrides=None,
                            payments=None, clock_to="2029-01-01T00:00:00Z",
                            payee_overrides=None):
    return setup_active_case(
        payments=payments if payments is not None else list(TWO_PAYMENTS),
        clock_to=clock_to,
        profile_overrides=profile_overrides,
        payee_overrides=payee_overrides,
        agreement_overrides={"case_number": case_number},
        policy_overrides=policy_overrides if policy_overrides is not None else dict(RIDER_DH))


# --- Valuation: min-of-rates, fee branch, per-payment rounding (PRD §3.7) ------------

def _setup_settled_death_case():
    """CA cap 400 (below the policy's 500): the DEATH claim is settled, the two
    certain-period payments survive, and the clock stands at 2029-01-01."""
    ctx = setup_active_case(
        payments=list(TWO_PAYMENTS),
        profile_overrides=LOW_CAP_CA,
        payee_overrides={"full_name": "Dee Senior", "date_of_birth": "1965-04-10",
                         "tax_id": "222-33-4444"},
        agreement_overrides={"case_number": "CM-001"},
        policy_overrides=dict(RIDER_DH))
    claim = create_claim(ctx, date_of_death="2028-12-20", claimant_name="Estate of Senior")
    settle_claim(claim["id"])
    set_clock("2029-01-01T00:00:00Z")
    return ctx, claim


def test_death_commutation_value_at_min_rate_zero_fee(api):
    """PRD §3.7: "The discount rate is the lesser of the policy's
    `contract_discount_rate_bps` and the payee-residence profile's
    `sspa_max_discount_rate_bps`."
    PRD §3.7: "The `fee_cents` is, for `HARDSHIP`, three percent of that present-value
    total rounded half up, capped at 250 dollars (25,000 cents); for `DEATH` it is zero.
    The `commuted_value_cents` is the present-value total minus the fee."

    Design: Difficulty/combinatorial_formula/commuted_value_min_rate_branch_cap
    """
    ctx, claim = _setup_settled_death_case()
    commutation = create_commutation(ctx, "DEATH", death_claim_id=claim["id"])
    # rate = min(500, 400) = 400 bps; round(100000/1.04)=96154 + round(100000/1.0816)=92456
    assert commutation["commuted_value_cents"] == 188610
    assert commutation["fee_cents"] == 0, "the DEATH reason zeroes the fee"
    assert commutation["covered_payment_count"] == 2
    assert commutation["status"] == "REQUESTED"


def test_commutation_creation_freezes_but_does_not_move_payments(api):
    """PRD §3.7: "Pay-out is the `OperationsSpecialist` step and requires `APPROVED`
    (`ERR_COMMUTATION_INVALID_STATE`): the request becomes `PAID_OUT`, and every covered
    payment — the eligible set frozen at creation — moves from `SCHEDULED` or `PAYABLE`
    to `COMMUTED`".

    Design: Difficulty/combinatorial_formula/commuted_value_min_rate_branch_cap
    """
    ctx, claim = _setup_settled_death_case()
    commutation = create_commutation(ctx, "DEATH", death_claim_id=claim["id"])
    assert commutation["covered_payment_count"] == 2
    for payment in ctx["payments"]:
        assert get_payment(payment["id"])["status"] == "SCHEDULED", (
            "creation freezes the eligible set but moves payments only at pay-out"
        )


def test_hardship_fee_applies_three_percent_cap(api):
    """PRD §3.7: "The `fee_cents` is, for `HARDSHIP`, three percent of that
    present-value total rounded half up, capped at 250 dollars (25,000 cents); for
    `DEATH` it is zero. The `commuted_value_cents` is the present-value total minus the
    fee."

    Design: Corner/calculations/hardship_fee_applies_three_percent_cap
    """
    ctx = _setup_commutation_case("CC-001", profile_overrides=LOW_CAP_CA,
                                  payee_overrides={"full_name": "Hank Ship"})
    commutation = create_commutation(ctx, "HARDSHIP")
    # pv_total = 188610 at the min(500, 400) = 400 bps rate; fee under the 25000 cap
    assert commutation["fee_cents"] == 5658, "round_half_up(0.03 * 188610) = 5658"
    assert commutation["commuted_value_cents"] == 182952
    assert commutation["covered_payment_count"] == 2


# --- Eligible-set boundary (PRD §3.7) -------------------------------------------------

def _setup_single_issued_payment_case():
    ctx = setup_active_case(
        payments=[{"due_date": "2026-08-15", "base_amount_cents": 50000}],
        clock_to="2026-08-15T00:00:00Z",
        agreement_overrides={"case_number": "BD-002"},
        policy_overrides=dict(RIDER_DH))
    return ctx


def test_commutation_empty_eligible_set_when_payment_issued(api):
    """PRD §3.7: "The eligible set is computed at creation: payments of the agreement's
    `ACTIVE` schedule in `SCHEDULED` or `PAYABLE` status with `due_date` strictly after
    the creation clock date. An empty set fails creation with
    `ERR_NO_COMMUTABLE_PAYMENTS`".

    Design: Difficulty/boundary_precision_check/commutation_empty_eligible_set
    """
    ctx = _setup_single_issued_payment_case()
    payment = ctx["payments"][0]
    issue_payment(payment["id"], method="EFT", user_id="ops-1")
    assert get_policy(ctx["policy"]["id"])["status"] == "IN_FORCE", (
        "an ISSUED payment is non-terminal, so no state error shadows the business error"
    )
    policy = get_policy(ctx["policy"]["id"])
    resp = api.create_commutation_request(
        {"annuity_policy_id": ctx["policy"]["id"],
         "settlement_agreement_id": ctx["agreement"]["id"], "reason": "HARDSHIP",
         "expected_annuity_policy_version": policy["version"]},
        TEST_USERS["case_manager_headers"])
    validate_error(resp, ApiErrorId.ERR_NO_COMMUTABLE_PAYMENTS)


def test_commutation_empty_set_when_due_date_not_strictly_after_clock(api):
    """PRD §3.7: "payments of the agreement's `ACTIVE` schedule in `SCHEDULED` or
    `PAYABLE` status with `due_date` strictly after the creation clock date. An empty
    set fails creation with `ERR_NO_COMMUTABLE_PAYMENTS`".

    Design: Difficulty/boundary_precision_check/commutation_empty_eligible_set
    """
    # The only payment matured exactly on its due date: PAYABLE but not strictly after
    # the clock, so the eligible set is empty.
    ctx = _setup_single_issued_payment_case()
    payment = ctx["payments"][0]
    assert payment["status"] == "PAYABLE"
    policy = get_policy(ctx["policy"]["id"])
    resp = api.create_commutation_request(
        {"annuity_policy_id": ctx["policy"]["id"],
         "settlement_agreement_id": ctx["agreement"]["id"], "reason": "HARDSHIP",
         "expected_annuity_policy_version": policy["version"]},
        TEST_USERS["case_manager_headers"])
    validate_error(resp, ApiErrorId.ERR_NO_COMMUTABLE_PAYMENTS)


# --- Legality and lifecycle guards (PRD §3.7) ------------------------------------------

def test_commutation_approve_twice_returns_invalid_state(api):
    """PRD §3.7: "A `ComplianceOfficer` approves or denies a `REQUESTED` commutation
    (`ERR_COMMUTATION_INVALID_STATE` from any other state), moving it to `APPROVED` or
    `DENIED`."

    Design: Corner/errors/commutation_approve_twice_returns_invalid_state
    """
    ctx = _setup_commutation_case("ER-010", payments=[
        {"due_date": "2030-01-01", "base_amount_cents": 100000}])
    commutation = create_commutation(ctx, "HARDSHIP")
    approved = validate_success(api.approve_commutation(commutation["id"], COMPLIANCE))
    assert approved["status"] == "APPROVED"
    resp = api.approve_commutation(commutation["id"], COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_COMMUTATION_INVALID_STATE)


def test_commutation_rider_none_forbids_death_reason(api):
    """PRD §3.7: "the policy's `commutation_rider` must allow the requested reason —
    `DEATH` requires `DEATH_ONLY` or `DEATH_AND_HARDSHIP`, `HARDSHIP` requires
    `DEATH_AND_HARDSHIP`, and `NONE` allows nothing — and the payee-residence profile's
    `commutation_permitted` must be true; either failure is `ERR_COMMUTATION_NOT_PERMITTED`
    (HTTP 403)."

    Design: Corner/errors/commutation_rider_or_statute_forbids
    """
    ctx = _setup_commutation_case("ER-011", payments=[
        {"due_date": "2030-01-01", "base_amount_cents": 100000}],
        policy_overrides={"commutation_rider": "NONE"})
    policy = get_policy(ctx["policy"]["id"])
    resp = api.create_commutation_request(
        {"annuity_policy_id": ctx["policy"]["id"],
         "settlement_agreement_id": ctx["agreement"]["id"], "reason": "DEATH",
         "expected_annuity_policy_version": policy["version"]},
        TEST_USERS["case_manager_headers"])
    validate_error(resp, ApiErrorId.ERR_COMMUTATION_NOT_PERMITTED)


# --- The DEATH reason's settled-claim gate (PRD §3.7) ----------------------------------

def _setup_death_gate_case():
    """Funded agreement, one certain-period payment due 2030-01-01, a REPORTED claim,
    clock at 2029-01-01."""
    ctx = setup_active_case(
        payments=[{"due_date": "2030-01-01", "base_amount_cents": 100000}],
        payee_overrides={"full_name": "Dee Claim", "date_of_birth": "1960-10-10",
                         "tax_id": "505-05-0505"},
        agreement_overrides={"case_number": "XD-003"},
        policy_overrides=dict(RIDER_DH))
    claim = create_claim(ctx, date_of_death="2028-12-20", claimant_name="Estate of Claim")
    set_clock("2029-01-01T00:00:00Z")
    return ctx, claim


def test_death_commutation_requires_settled_claim(api):
    """PRD §3.7: "When the reason is `DEATH`, `death_claim_id` must be supplied and must
    reference a `SETTLED` claim for the same agreement (`ERR_CLAIM_INVALID_STATE`
    otherwise)."

    Design: Difficulty/cross_entity_state_dependency/death_commutation_requires_settled_claim
    """
    ctx, claim = _setup_death_gate_case()
    assert claim["status"] == "REPORTED"
    policy = get_policy(ctx["policy"]["id"])
    resp = api.create_commutation_request(
        {"annuity_policy_id": ctx["policy"]["id"],
         "settlement_agreement_id": ctx["agreement"]["id"], "reason": "DEATH",
         "death_claim_id": claim["id"],
         "expected_annuity_policy_version": policy["version"]},
        TEST_USERS["case_manager_headers"])
    validate_error(resp, ApiErrorId.ERR_CLAIM_INVALID_STATE)


def test_death_commutation_succeeds_after_claim_settles(api):
    """PRD §3.7: "When the reason is `DEATH`, `death_claim_id` must be supplied and must
    reference a `SETTLED` claim for the same agreement (`ERR_CLAIM_INVALID_STATE`
    otherwise)."
    PRD §3.7: "otherwise `covered_payment_count` records its size."

    Design: Difficulty/cross_entity_state_dependency/death_commutation_requires_settled_claim
    """
    ctx, claim = _setup_death_gate_case()
    settle_claim(claim["id"])
    commutation = create_commutation(ctx, "DEATH", death_claim_id=claim["id"])
    assert commutation["status"] == "REQUESTED"
    # The 2030-01-01 payment sits within the certain period, so it survived the death
    # cascade and is the single eligible payment.
    assert commutation["covered_payment_count"] == 1
