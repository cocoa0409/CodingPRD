"""Death claims: the deny/resubmit revision loop and the settle cascade
(PRD §3.7)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    setup_draft_agreement, setup_active_case, create_claim, settle_claim,
    get_agreement, get_payee, get_payment,
    TEST_USERS,
)

CASE_MGR = TEST_USERS["case_manager_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
READER = TEST_USERS["reader_headers"]


# --- The REPORTED -> DENIED -> REPORTED revision loop (PRD §3.7) --------------------

def _setup_draft_claim(dod="2026-03-01", payee_overrides=None, case_number="DC-001"):
    ctx = setup_draft_agreement(payee_overrides=payee_overrides,
                                agreement_overrides={"case_number": case_number})
    claim = create_claim(ctx, date_of_death=dod, claimant_type="BENEFICIARY",
                         claimant_name="Junior Able")
    return ctx, claim


def test_death_claim_deny_clears_reason_on_resubmit(api):
    """PRD §3.7: "Denial is the quiet sibling branch: a `ComplianceOfficer` moves
    `REPORTED` → `DENIED`, supplying a `denial_reason`."
    PRD §3.7: "a `CaseManager` may resubmit the claim with a new evidence package,
    moving `DENIED` → `REPORTED` (`ERR_CLAIM_INVALID_STATE` from any other state) and
    clearing `denial_reason` to null."

    Design: Difficulty/non_linear_state_machine/death_claim_deny_resubmit_cycle
    """
    _ctx, claim = _setup_draft_claim()
    assert claim["status"] == "REPORTED"

    denied = validate_success(api.deny_death_claim(
        claim["id"], {"denial_reason": "insufficient documentation"}, COMPLIANCE))
    assert denied["status"] == "DENIED"
    assert denied["denial_reason"] == "insufficient documentation"

    resubmitted = validate_success(api.resubmit_death_claim(claim["id"], CASE_MGR))
    assert resubmitted["status"] == "REPORTED"
    assert resubmitted["denial_reason"] is None, "the cycle cleared the denial"


def test_resubmitted_claim_settles_and_marks_payee_deceased(api):
    """PRD §3.7: "The payee moves `ACTIVE` → `DECEASED`, with `deceased_date` set to
    the claim's `date_of_death` and a version bump."

    Design: Difficulty/non_linear_state_machine/death_claim_deny_resubmit_cycle
    """
    ctx, claim = _setup_draft_claim()
    validate_success(api.deny_death_claim(
        claim["id"], {"denial_reason": "insufficient documentation"}, COMPLIANCE))
    validate_success(api.resubmit_death_claim(claim["id"], CASE_MGR))

    settled = settle_claim(claim["id"])
    assert settled["status"] == "SETTLED", "the same claim (same id) settles after resubmission"
    payee = get_payee(ctx["payee"]["id"])
    assert payee["status"] == "DECEASED"
    assert payee["deceased_date"] == "2026-03-01"


# --- The settle cascade: payments, policy, agreement (PRD §3.7) ----------------------

def _setup_life_contingent_case():
    """Both payments fall after the certain-period end 2027-12-31, so both are
    life-contingent; the clock at 2028-06-01 has matured p1 to PAYABLE."""
    return setup_active_case(
        payments=[{"due_date": "2028-06-01", "base_amount_cents": 60000},
                  {"due_date": "2029-06-01", "base_amount_cents": 70000}],
        clock_to="2028-06-01T00:00:00Z",
        payee_overrides={"full_name": "Don Cascade", "date_of_birth": "1958-01-01",
                         "tax_id": "777-88-9999"},
        agreement_overrides={"case_number": "DX-001"},
        policy_overrides={"commutation_rider": "DEATH_ONLY",
                          "certain_period_end_date": "2027-12-31"})


def test_death_settle_cancels_life_contingent_payments(api):
    """PRD §3.7: "among the agreement's payments for this payee in `SCHEDULED` or
    `PAYABLE`, those with `due_date` strictly after the policy's
    `certain_period_end_date` are cancelled with `cancel_reason` = `DEATH`".

    Design: Difficulty/transitive_cascade/death_settle_cancellation_chain
    """
    ctx = _setup_life_contingent_case()
    claim = create_claim(ctx, date_of_death="2028-07-01",
                         claimant_name="Estate of Cascade")

    settled = settle_claim(claim["id"])
    assert settled["status"] == "SETTLED"
    assert get_payee(ctx["payee"]["id"])["status"] == "DECEASED", "link 1"
    for payment in ctx["payments"]:
        row = get_payment(payment["id"])
        assert row["status"] == "CANCELLED", "link 2: both due after the certain-period end"
        assert row["cancel_reason"] == "DEATH"


def test_death_settle_exhausts_policy_and_closes_agreement(api):
    """PRD §3.7: "The exhaustion cascade follows: if no non-terminal payments remain,
    the policy becomes `EXHAUSTED` and the agreement follows `ACTIVE` → `CLOSED`."

    Design: Difficulty/transitive_cascade/death_settle_cancellation_chain
    """
    ctx = _setup_life_contingent_case()
    assert get_agreement(ctx["agreement"]["id"])["status"] == "ACTIVE"
    claim = create_claim(ctx, date_of_death="2028-07-01",
                         claimant_name="Estate of Cascade")
    settle_claim(claim["id"])

    policy = validate_success(api.get_annuity_policy(ctx["policy"]["id"], READER))
    assert policy["status"] == "EXHAUSTED", "link 3: no non-terminal payments remain"
    agreement = get_agreement(ctx["agreement"]["id"])
    assert agreement["status"] == "CLOSED", "link 4"
    assert agreement["outstanding_liability_cents"] == 0


def test_death_settle_preserves_certain_period_payments(api):
    """PRD §3.7: "while payments due on or before the certain-period end survive for
    the estate or beneficiary."
    PRD §3.7: "those with `due_date` strictly after the policy's
    `certain_period_end_date` are cancelled with `cancel_reason` = `DEATH`".

    Design: Corner/state_machines/death_settle_preserves_certain_period_payments
    """
    ctx = setup_active_case(
        payments=[{"due_date": "2027-06-01", "base_amount_cents": 45000},
                  {"due_date": "2028-06-01", "base_amount_cents": 55000}],
        payee_overrides={"full_name": "Cer Tain", "date_of_birth": "1957-09-09",
                         "tax_id": "181-18-1818"},
        agreement_overrides={"case_number": "EN-005"},
        policy_overrides={"commutation_rider": "DEATH_ONLY",
                          "certain_period_end_date": "2027-12-31"})
    claim = create_claim(ctx, date_of_death="2027-01-15", claimant_name="Estate of Tain")
    settle_claim(claim["id"])

    p1 = get_payment(ctx["payments"][0]["id"])
    assert p1["status"] == "SCHEDULED", (
        "due 2027-06-01 <= certain end 2027-12-31: the guaranteed payment survives"
    )
    p2 = get_payment(ctx["payments"][1]["id"])
    assert p2["status"] == "CANCELLED"
    assert p2["cancel_reason"] == "DEATH"

    policy = validate_success(api.get_annuity_policy(ctx["policy"]["id"], READER))
    assert policy["status"] == "IN_FORCE", "no exhaustion while p1 remains"
    assert get_agreement(ctx["agreement"]["id"])["status"] == "FUNDED"


def test_settle_denied_claim_returns_invalid_state(api):
    """PRD §3.7: "Settlement, performed by a `ComplianceOfficer` on a `REPORTED` claim
    (`ERR_CLAIM_INVALID_STATE` otherwise), detonates the widest cascade in the system."

    Design: Corner/errors/settle_denied_claim_returns_invalid_state
    """
    _ctx, claim = _setup_draft_claim(case_number="ER-009")
    validate_success(api.deny_death_claim(
        claim["id"], {"denial_reason": "unverified certificate"}, COMPLIANCE))
    resp = api.settle_death_claim(claim["id"], COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_CLAIM_INVALID_STATE)
