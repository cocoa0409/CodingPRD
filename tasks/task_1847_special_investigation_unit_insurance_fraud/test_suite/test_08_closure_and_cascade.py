"""Case closure, substantiated cascade, terminal lockdown, segregation of duties."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_manager_headers,
    create_adjuster, create_investigator, create_claim, create_referral,
    triage_referral, accept_referral, open_case, assign_investigator,
    log_evidence, submit_evidence_review, admit_evidence,
    setup_case_under_investigation, setup_case_decision_pending,
    setup_case_closed_substantiated, setup_case_with_admitted_evidence,
)
from test_helpers.api_client import api_client


class TestSubstantiatedCloseCascade:
    """Difficulty/transitive_cascade/substantiated_close_cascade_depth3"""

    def test_close_substantiated_denies_claim_with_fraud_confirmed(self, api):
        """PRD §3.6: "the claim moves from `UNDER_SIU_REVIEW` or `PAYMENT_DELAYED`
        to `DENIED` with `payment_hold_reason` set to `FRAUD_CONFIRMED`"

        Design: Difficulty/transitive_cascade/substantiated_close_cascade_depth3
        """
        ctx = setup_case_closed_substantiated(
            state_code="CA", claimed_amount_cents=100_000_000,
            fraud_amount_cents=600_000)
        claim = get_success_data(api_client.get_claim(ctx["claim"]["id"],
                                                      ctx["manager_headers"]))
        assert claim["status"] == "DENIED"
        assert claim["payment_hold_reason"] == "FRAUD_CONFIRMED"

    def test_close_substantiated_auto_creates_ledger_and_bureau_referral(self, api):
        """PRD §3.6: "a restitution ledger is auto-created in `OPEN` with
        `target_amount_cents` locked to the substantiated total at closure; when
        `bureau_referral_required` is true, a bureau referral is auto-created in
        `DRAFT`, carrying the claim's `state_code` and a `deadline_at` computed
        from the closure timestamp"

        Design: Difficulty/transitive_cascade/substantiated_close_cascade_depth3
        """
        ctx = setup_case_closed_substantiated(
            state_code="CA", claimed_amount_cents=100_000_000,
            fraud_amount_cents=600_000)
        assert ctx["ledger"] is not None, "expected auto-created restitution ledger"
        assert ctx["ledger"]["target_amount_cents"] == 600_000
        assert ctx["ledger"]["status"] == "OPEN"
        assert ctx["bureau_referral"] is not None, "expected auto-created bureau referral"
        assert ctx["bureau_referral"]["status"] == "DRAFT"
        assert ctx["bureau_referral"]["state_code"] == "CA"


class TestSubstantiatedBoundary:
    """Difficulty/boundary_precision_check/substantiated_close_requires_nonzero_substantiated"""

    def test_close_substantiated_with_zero_substantiated_amount_rejected(self, api):
        """PRD §3.6: "A substantiated closure (`DECISION_PENDING` →
        `CLOSED_SUBSTANTIATED`) additionally requires `substantiated_fraud_cents`
        to be greater than zero."
        PRD §3.6: "Closure from any status other than `DECISION_PENDING` or — for
        the insufficient-evidence path — `OPEN` is rejected with
        `ERR_INVALID_STATE`." (The same error code carries the substantiated>0
        precondition failure per §2.6's state check.)

        Design: Difficulty/boundary_precision_check/substantiated_close_requires_nonzero_substantiated
        """
        # Case reaches DECISION_PENDING with only SUPPORTING admitted evidence
        ctx = setup_case_decision_pending(
            claimed_amount_cents=5_000_000,
            red_flag_codes=["UNWITNESSED_LOSS"],
            evidence_overrides={"materiality": "SUPPORTING", "fraud_amount_cents": 0})
        assert ctx["case"]["substantiated_fraud_cents"] == 0
        resp = api_client.close_case(ctx["case"]["id"],
                                     {"closed_reason": "SUBSTANTIATED"},
                                     ctx["manager_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_close_substantiated_with_positive_amount_succeeds(self, api):
        """PRD §3.6: "A substantiated closure (`DECISION_PENDING` →
        `CLOSED_SUBSTANTIATED`) additionally requires `substantiated_fraud_cents`
        to be greater than zero."

        Design: Difficulty/boundary_precision_check/substantiated_close_requires_nonzero_substantiated
        """
        ctx = setup_case_decision_pending(
            claimed_amount_cents=100_000_000,
            red_flag_codes=["PRIOR_FRAUD_CONVICTION"],
            evidence_overrides={"materiality": "SUBSTANTIVE",
                                "fraud_amount_cents": 100_000})
        assert ctx["case"]["substantiated_fraud_cents"] > 0
        resp = api_client.close_case(ctx["case"]["id"],
                                     {"closed_reason": "SUBSTANTIATED"},
                                     ctx["manager_headers"])
        data = validate_success(resp)
        assert data["status"] == "CLOSED_SUBSTANTIATED"


class TestTerminalLockdown:
    def test_assignment_against_closed_case_rejected(self, api):
        """PRD §3.6: "`CLOSED_SUBSTANTIATED`, `CLOSED_UNSUBSTANTIATED`,
        `CLOSED_INSUFFICIENT`, and — after a bureau filing — `REFERRED_TO_BUREAU`
        are the case's terminal states."
        PRD §3.3: "Assignment creation is valid only while the case is `OPEN` or
        `UNDER_INVESTIGATION`; against any other case status it is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/closed_case_terminal_lockdown
        """
        ctx = setup_case_decision_pending(
            evidence_overrides={"materiality": "SUPPORTING", "fraud_amount_cents": 0})
        resp = api_client.close_case(ctx["case"]["id"],
                                     {"closed_reason": "UNSUBSTANTIATED"},
                                     ctx["manager_headers"])
        case = validate_success(resp)
        assert case["status"] == "CLOSED_UNSUBSTANTIATED"
        # Try new assignment against the closed case
        resp2 = api_client.create_assignment(
            case["id"],
            {"investigator_id": ctx["investigator"]["id"],
             "expected_case_version": case["version"]},
            ctx["manager_headers"])
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)


class TestSegregationOfDutiesOnClose:
    def test_closing_manager_must_not_equal_assigned_investigator(self, api):
        """PRD §2.7: "A manager may not close a case on which they are the assigned
        investigator; the closure request's `X-User-ID` must differ from the case's
        assigned investigator."
        PRD §2.7: "each rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422) when
        violated"

        Design: Corner/errors/err_segregation_of_duties_on_close
        """
        ctx = setup_case_decision_pending(
            evidence_overrides={"materiality": "SUPPORTING", "fraud_amount_cents": 0})
        # Manager presents the investigator's user id as X-User-ID
        inv_id = ctx["investigator"]["id"]
        sod_headers = make_manager_headers(user_id=inv_id)
        resp = api_client.close_case(ctx["case"]["id"],
                                     {"closed_reason": "UNSUBSTANTIATED"},
                                     sod_headers)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


class TestClaimPayBlocked:
    """Difficulty/cross_entity_state_dependency/claim_pay_blocked_by_open_case"""

    def test_pay_claim_under_siu_review_rejected(self, api):
        """PRD §3.1: "The adjuster may mark it paid, which is permitted only while
        the claim is still `PENDING` and no non-terminal SIU case exists for it —
        a claim under active investigation cannot be paid. Attempting payment
        against a claim that is already `UNDER_SIU_REVIEW` or `PAYMENT_DELAYED` is
        rejected with `ERR_INVALID_STATE`"

        Design: Difficulty/cross_entity_state_dependency/claim_pay_blocked_by_open_case
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        claim = create_claim(adj)
        ref = create_referral(claim, headers=ah)
        triage_referral(ref, manager_headers=mh)
        accept_referral(ref, manager_headers=mh)
        # Claim now UNDER_SIU_REVIEW
        resp = api_client.pay_claim(claim["id"], ah)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_pay_pending_claim_without_case_succeeds(self, api):
        """PRD §3.1: "A successful payment moves the claim to `PAID` and sets
        `paid_amount_cents` equal to `claimed_amount_cents`, since payouts
        increment the paid total only at that transition."

        Design: Difficulty/cross_entity_state_dependency/claim_pay_blocked_by_open_case
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        claim = create_claim(adj, claimed_amount_cents=5_000_000)
        resp = api_client.pay_claim(claim["id"], ah)
        data = validate_success(resp)
        assert data["status"] == "PAID"
        assert data["paid_amount_cents"] == 5_000_000
