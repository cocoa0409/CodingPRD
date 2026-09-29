"""Opening states, terminal locks, non-idempotent actions, cascades and the board loop."""
import pytest
from test_helpers import validate_error, validate_success
from test_helpers.test_users import (
    make_benefits_analyst_headers,
    make_risk_officer_headers,
)
from test_helpers.fixtures import (
    ADMIN,
    ANALYST,
    BOARD,
    CLAIMS,
    RISK,
    TREASURY,
    add_allocation,
    add_liability,
    approved_claim,
    authorized_carrier_with_product,
    create_plan,
    execute_consent,
    file_capital_position,
    in_force_policy,
    insured_employee,
    move_clock,
    onboard_carrier,
    open_diligence_review,
    register_employee,
    submitted_purchase_request,
)


NIMBUS = {
    "legal_name": "Nimbus Life",
    "naic_code": "71014",
    "am_best_rating": "A_PLUS",
    "statutory_surplus_usd": 400_000_000.00,
    "domicile_state": "VT",
}
ONYX = {
    "legal_name": "Onyx Life",
    "naic_code": "71015",
    "am_best_rating": "A_PLUS",
    "statutory_surplus_usd": 400_000_000.00,
    "domicile_state": "SC",
}

KRAUSS = {
    "full_name": "Emil Krauss",
    "employee_number": "E-7401",
    "annual_salary_usd": 3_000_000.00,
    "officer_flag": True,
}


class TestDiligenceFileLifecycle:
    def test_a_fresh_diligence_file_opens_in_draft_with_nothing_decided(self, api):
        """Opening a file records the intent to review and nothing more.

        "A fresh file sits in `DRAFT` with `info_request_count` at 0 and both
        `submitted_by_user_id` and `decided_by_user_id` unset." Scoring only
        happens later, because "On success the server recomputes `rating_points`,
        `surplus_points`, `concentration_points` and `financial_strength_score`
        from scratch" on the submission, and "Authorization comes only from an
        approved due diligence file", so the carrier is still where onboarding
        left it.

        Design: Corner/state_machines/diligence_review_starts_in_draft_with_zero_info_requests
        """
        carrier = onboard_carrier(
            api,
            legal_name="Lantern Life",
            naic_code="71012",
            am_best_rating="A_PLUS",
            statutory_surplus_usd=400_000_000.00,
            domicile_state="IN",
        )

        response = api.create_diligence_review(
            {"carrier_id": carrier["id"], "review_year": 2026}, ANALYST
        )
        review = validate_success(response, 201)
        assert review["status"] == "DRAFT"
        assert review["info_request_count"] == 0
        assert review["submitted_by_user_id"] is None
        assert review["decided_by_user_id"] is None
        assert review["review_year"] == 2026

        unchanged = validate_success(api.get_carrier(carrier["id"], RISK))
        assert unchanged["status"] == "PENDING_DILIGENCE"
        assert unchanged["last_approved_review_year"] is None

    def test_an_approved_file_refuses_both_further_decisions(self, api):
        """Both decisions are terminal, so neither can be replayed or reversed.

        "Both `APPROVED` and `DECLINED` are terminal for the diligence dimension,
        and a further action against a file in either state reports
        `ERR_TERMINAL_STATE_LOCKED`." The terminal guard fires ahead of the
        transition guard, since "an attempt to advance a resource already sitting
        in a terminal state for the dimension the action drives reports
        `ERR_TERMINAL_STATE_LOCKED` (HTTP 409)". A rejected request changes
        nothing, because "A request that is rejected changes nothing and bumps
        nothing."

        Design: Corner/state_machines/approved_review_rejects_a_second_approve_as_terminal
        """
        file_capital_position(api)
        carrier = onboard_carrier(
            api,
            legal_name="Mistral Life",
            naic_code="71013",
            am_best_rating="A_PLUS",
            statutory_surplus_usd=400_000_000.00,
            domicile_state="NM",
        )
        review = open_diligence_review(api, carrier["id"], review_year=2026)
        validate_success(
            api.submit_diligence_review(review["id"], make_benefits_analyst_headers("analyst-1"))
        )
        approved = validate_success(
            api.approve_diligence_review(review["id"], make_risk_officer_headers("risk-1"))
        )
        assert approved["financial_strength_score"] == 65, (
            "an A_PLUS carrier below the first surplus step scores exactly the threshold"
        )

        authorized = validate_success(api.get_carrier(carrier["id"], RISK))
        version_after_approval = authorized["version"]

        validate_error(
            api.approve_diligence_review(review["id"], make_risk_officer_headers("risk-2")),
            "ERR_TERMINAL_STATE_LOCKED",
            409,
        )
        validate_error(
            api.decline_diligence_review(review["id"], make_risk_officer_headers("risk-2")),
            "ERR_TERMINAL_STATE_LOCKED",
            409,
        )

        still_approved = validate_success(api.get_diligence_review(review["id"], RISK))
        assert still_approved["status"] == "APPROVED"
        assert still_approved["financial_strength_score"] == 65
        assert still_approved["decided_by_user_id"] == "risk-1", (
            "the refused decisions do not overwrite the recorded decider"
        )

        carrier_after = validate_success(api.get_carrier(carrier["id"], RISK))
        assert carrier_after["status"] == "AUTHORIZED"
        assert carrier_after["last_approved_review_year"] == 2026
        assert carrier_after["version"] == version_after_approval, (
            "no cascade re-fires on the carrier for a refused decision"
        )


class TestConsentExecutionIsNotIdempotent:
    def test_executing_an_already_executed_consent_is_an_illegal_transition(self, api):
        """There is no second signature to record, so the replay is refused.

        "Executing the consent records the employee's signature and advances the
        record `DRAFT → EXECUTED`", and "an attempt to take a transition that the
        resource's current state does not offer reports
        `ERR_INVALID_STATE_TRANSITION` (HTTP 409)." The first execution "stamps
        `executed_at` with the current logical clock instant" and "increments the
        consent record's `version` by 1", and the refused replay leaves both
        alone.

        Design: Corner/state_machines/second_execute_on_an_executed_consent_returns_invalid_state
        """
        employee = register_employee(
            api,
            full_name="Rin Sato",
            employee_number="E-7301",
            annual_salary_usd=400_000.00,
            officer_flag=False,
        )
        consent = execute_consent(
            api,
            employee["id"],
            coverage_start_date="2026-08-01T00:00:00Z",
            coverage_end_date="2027-07-31T00:00:00Z",
            consent_form_reference="CF-7301",
        )
        assert consent["status"] == "EXECUTED"
        assert consent["executed_at"].startswith("2026-08-01T00:00:00")
        assert consent["version"] == 2, "creation makes version 1 and execution makes it 2"

        validate_error(
            api.execute_consent_record(consent["id"], ANALYST),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )

        after = validate_success(api.get_consent_record(consent["id"], ANALYST))
        assert after["status"] == "EXECUTED"
        assert after["executed_at"] == consent["executed_at"]
        assert after["version"] == 2, "the refused replay bumps nothing"


class TestClaimVoidReversesFiling:
    def test_voiding_the_claim_undoes_the_policy_employee_and_allocation_effects(self, api):
        """One void walks back every write that filing and allocation made.

        "Voiding reverses everything filing did and everything allocation did:
        the policy returns `CLAIM_PENDING → IN_FORCE`, the employee's
        `employment_status` returns to `ACTIVE`, every `ACTIVE` beneficiary
        allocation is set to `VOIDED` with its `gross_amount_usd` zeroed, the
        claim's `allocated_bps_total` is reset to 0, and the claim's `version` is
        incremented by 1 along with one increment on each other resource the
        reversal touched."

        Design: Corner/state_machines/claim_void_reverses_every_filing_side_effect
        """
        context = in_force_policy(
            api,
            carrier_overrides=NIMBUS,
            product_overrides={"product_name": "Nimbus GA BOLI"},
            employee_overrides=KRAUSS,
            request_overrides={
                "single_premium_usd": 1_200_000.00,
                "face_amount_usd": 5_000_000.00,
            },
            policy_overrides={"policy_number": "NB-0001"},
        )
        claim = approved_claim(
            api,
            context["policy_id"],
            date_of_death="2026-08-18T00:00:00Z",
            terminal_dividend_usd=0.00,
            proof_reference="DC-7401",
        )
        assert claim["total_death_benefit_usd"] == pytest.approx(5_000_000.00, abs=0.01)
        assert claim["survivor_entitlement_usd"] == pytest.approx(3_000_000.00, abs=0.01)
        assert claim["bank_portion_usd"] == pytest.approx(2_000_000.00, abs=0.01)

        allocation = add_allocation(
            api,
            claim["id"],
            beneficiary_name="Marta Krauss",
            relationship="SPOUSE",
            allocation_pct_bps=6000,
        )

        pending = validate_success(api.get_policy(context["policy_id"], TREASURY))
        assert pending["status"] == "CLAIM_PENDING"
        insured = validate_success(api.get_employee(context["employee_id"], ANALYST))
        assert insured["employment_status"] == "DECEASED"

        voided = validate_success(api.void_death_claim(claim["id"], CLAIMS))
        assert voided["adjudication_status"] == "VOIDED"
        assert voided["distribution_status"] == "NOT_STARTED"
        assert voided["allocated_bps_total"] == 0

        share = validate_success(api.get_beneficiary_allocation(allocation["id"], CLAIMS))
        assert share["status"] == "VOIDED"
        assert share["gross_amount_usd"] == pytest.approx(0.00, abs=0.01)

        restored_policy = validate_success(api.get_policy(context["policy_id"], TREASURY))
        assert restored_policy["status"] == "IN_FORCE"
        assert restored_policy["cash_surrender_value_usd"] == pytest.approx(
            1_200_000.00, abs=0.01
        )

        restored_employee = validate_success(api.get_employee(context["employee_id"], ANALYST))
        assert restored_employee["employment_status"] == "ACTIVE"

        carrier = validate_success(api.get_carrier(context["carrier_id"], TREASURY))
        assert carrier["in_force_premium_usd"] == pytest.approx(1_200_000.00, abs=0.01)
        assert carrier["in_force_cash_value_usd"] == pytest.approx(1_200_000.00, abs=0.01)
        assert carrier["concentration_bps"] == 12, (
            "the reversal leaves the carrier's live exposure exactly as issuance set it"
        )


class TestCarrierTerminationCascade:
    def test_terminating_a_suspended_carrier_closes_products_and_rejects_requests(self, api):
        """The end of the relationship sweeps everything still pointing at the carrier.

        "When it succeeds the cascade is broad: every product type of that
        carrier currently in `OPEN` or `ON_WATCH` is driven to `CLOSED_TO_NEW`;
        every purchase request naming that carrier and sitting in `SUBMITTED`,
        `DILIGENCE_CLEARED`, `CAPACITY_RESERVED`, `NOTICE_FILED`,
        `CONCURRENCE_PENDING` or `APPROVED` is driven to `REJECTED`, and each such
        request's `reserved_premium_usd` is subtracted from the carrier's
        `reserved_premium_usd` and then zeroed on the request itself".
        Termination "is the end of the relationship and only available from
        `SUSPENDED`."

        Design: Corner/state_machines/carrier_terminate_cascades_products_closed_and_requests_rejected
        """
        context = authorized_carrier_with_product(
            api,
            carrier_overrides=ONYX,
            product_overrides={"product_name": "Onyx GA BOLI"},
        )
        insured = insured_employee(
            api,
            employee_overrides={
                "full_name": "Bao Pham",
                "employee_number": "E-7501",
                "annual_salary_usd": 500_000.00,
                "officer_flag": False,
            },
            consent_overrides={"consent_form_reference": "CF-7501"},
        )
        request = submitted_purchase_request(
            api,
            context["carrier_id"],
            context["product_type_id"],
            insured["employee_id"],
            single_premium_usd=1_000_000.00,
            face_amount_usd=3_000_000.00,
        )
        assert request["status"] == "SUBMITTED"

        suspended = validate_success(api.suspend_carrier(context["carrier_id"], RISK))
        assert suspended["status"] == "SUSPENDED"

        terminated = validate_success(api.terminate_carrier(context["carrier_id"], RISK))
        assert terminated["status"] == "TERMINATED"
        assert terminated["reserved_premium_usd"] == pytest.approx(0.00, abs=0.01)
        assert terminated["in_force_premium_usd"] == pytest.approx(0.00, abs=0.01)

        product = validate_success(api.get_product_type(context["product_type_id"], ADMIN))
        assert product["status"] == "CLOSED_TO_NEW"

        rejected = validate_success(api.get_purchase_request(request["id"], ANALYST))
        assert rejected["status"] == "REJECTED"
        assert rejected["reserved_premium_usd"] == pytest.approx(0.00, abs=0.01)

        review = validate_success(api.get_diligence_review(context["review_id"], RISK))
        assert review["status"] == "APPROVED", "the cascade does not touch the diligence file"


class TestClockSweep:
    def test_moving_the_clock_past_a_window_expires_it_and_clears_the_posture(self, api):
        """The sweep is part of the move, and it is reported in the response.

        "the response reports the resulting `current_utc` together with
        `expired_consent_count`, the number of consent records the move swept into
        expiry." "Moving the clock is not a passive operation. Each move sweeps
        the consent population: every consent record currently in `EXECUTED`
        whose `coverage_end_date` now lies before the new clock value is moved to
        `EXPIRED`, and for every employee left with no remaining `EXECUTED`
        consent record the employee's `insurable_interest_status` is reset to
        `NOT_ESTABLISHED`."

        Design: Corner/state_machines/clock_advance_expires_consent_and_clears_insurable_interest
        """
        employee = register_employee(
            api,
            full_name="Mei Quan",
            employee_number="E-7601",
            annual_salary_usd=450_000.00,
            officer_flag=False,
        )
        consent = execute_consent(
            api,
            employee["id"],
            coverage_start_date="2026-08-01T00:00:00Z",
            coverage_end_date="2026-08-31T00:00:00Z",
            consent_form_reference="CF-7601",
        )
        established = validate_success(api.get_employee(employee["id"], ANALYST))
        assert established["insurable_interest_status"] == "ESTABLISHED"

        moved = move_clock(api, "2026-09-15T00:00:00Z")
        assert moved["current_utc"].startswith("2026-09-15T00:00:00")
        assert moved["expired_consent_count"] == 1

        swept = validate_success(api.get_consent_record(consent["id"], ANALYST))
        assert swept["status"] == "EXPIRED"
        assert swept["executed_at"].startswith("2026-08-01T00:00:00"), (
            "expiry does not disturb the recorded signature instant"
        )

        after = validate_success(api.get_employee(employee["id"], ANALYST))
        assert after["insurable_interest_status"] == "NOT_ESTABLISHED"


class TestFrozenPlanBlocksParticipants:
    def test_a_frozen_plan_takes_no_new_liability_until_it_is_unfrozen(self, api):
        """Freezing exists precisely to stop the participant population growing.

        "A plan in `FROZEN` or `TERMINATED` accepts no new participant
        liabilities at all, and the attempt is rejected with
        `ERR_INVALID_STATE_TRANSITION`; that is exactly what freezing a plan is
        for." "Unfreezing takes it `FROZEN → ACTIVE`, but only after a fresh
        recomputation shows the accrual-basis posture to be `FUNDED` or
        `UNDERFUNDED`", which an empty plan satisfies, and the liability then
        lands with its discounted amount and drives the plan to `CRITICAL`.

        Design: Corner/state_machines/frozen_nqdc_plan_rejects_a_new_participant_liability
        """
        plan = create_plan(
            api, plan_name="Frozen Bonus Plan", plan_type="DEFERRED_BONUS", discount_rate_bps=500
        )
        employee = register_employee(
            api,
            full_name="Yara Bloom",
            employee_number="E-7701",
            annual_salary_usd=800_000.00,
            officer_flag=False,
        )
        frozen = validate_success(api.freeze_nqdc_plan(plan["id"], TREASURY))
        assert frozen["status"] == "FROZEN"

        payload = {
            "nqdc_plan_id": plan["id"],
            "employee_id": employee["id"],
            "accrued_to_date_usd": 500_000.00,
            "projected_benefit_usd": 700_000.00,
            "years_to_payout": 5,
        }
        validate_error(
            api.create_nqdc_liability(payload, TREASURY), "ERR_INVALID_STATE_TRANSITION", 409
        )

        still_empty = validate_success(api.get_nqdc_plan(plan["id"], TREASURY))
        assert still_empty["accrual_liability_usd"] == pytest.approx(0.00, abs=0.01)
        assert still_empty["pbo_liability_usd"] == pytest.approx(0.00, abs=0.01)

        thawed = validate_success(api.unfreeze_nqdc_plan(plan["id"], TREASURY))
        assert thawed["status"] == "ACTIVE"

        liability = validate_success(api.create_nqdc_liability(payload, TREASURY), 201)
        assert liability["discounted_benefit_usd"] == pytest.approx(548_468.32, abs=0.01)

        loaded = validate_success(api.get_nqdc_plan(plan["id"], TREASURY))
        assert loaded["accrual_liability_usd"] == pytest.approx(500_000.00, abs=0.01)
        assert loaded["pbo_liability_usd"] == pytest.approx(548_468.32, abs=0.01)
        assert loaded["matched_cash_value_usd"] == pytest.approx(0.00, abs=0.01)
        assert loaded["funded_ratio_bps"] == 0
        assert loaded["funding_posture"] == "CRITICAL"


class TestBoardReturnLoop:
    def test_resubmitting_a_returned_assessment_recompiles_the_whole_report(self, api):
        """A report sent back is measured against the world as it now stands.

        "submitting from `COMPILED` carries the figures forward as compiled,
        while submitting from `RETURNED` **recompiles** every one of the six
        counts, `risk_points` and `risk_rating` before submitting". A plan that
        became critical in the meantime counts, since "`critical_plan_count` and
        `underfunded_plan_count` count the deferred compensation plans whose
        `status` is not `TERMINATED` and whose funding posture on the
        **projected-benefit basis** is `CRITICAL` and `UNDERFUNDED`
        respectively", "each critical plan 25", and "`MODERATE` when it is at
        least 15 but below 35".

        Design: Corner/state_machines/returned_assessment_resubmitted_recompiles_counts_and_rating
        """
        capital = file_capital_position(api)
        assessment = validate_success(
            api.create_risk_assessment(
                {"capital_position_id": capital["id"], "assessment_year": 2026}, RISK
            ),
            201,
        )
        assert assessment["status"] == "COMPILED"
        assert assessment["compiled_at"].startswith("2026-08-01T00:00:00")
        assert assessment["board_note"] is None
        for count in (
            "restricted_carrier_count",
            "watch_list_carrier_count",
            "on_watch_product_count",
            "closed_product_count",
            "critical_plan_count",
            "underfunded_plan_count",
        ):
            assert assessment[count] == 0, f"{count} opens at zero on an empty platform"
        assert assessment["risk_points"] == 0
        assert assessment["risk_rating"] == "LOW"

        validate_success(api.submit_risk_assessment_to_board(assessment["id"], RISK))
        returned = validate_success(
            api.return_risk_assessment(
                assessment["id"],
                {"board_note": "Please restate with the NQDC funding exhibit."},
                BOARD,
            )
        )
        assert returned["status"] == "RETURNED"
        assert returned["board_note"] == "Please restate with the NQDC funding exhibit."

        plan = create_plan(api, plan_name="Late SERP", plan_type="SERP", discount_rate_bps=500)
        employee = register_employee(
            api,
            full_name="Iva Sorenson",
            employee_number="E-7801",
            annual_salary_usd=900_000.00,
            officer_flag=False,
        )
        liability = add_liability(
            api,
            plan["id"],
            employee["id"],
            accrued_to_date_usd=1_000_000.00,
            projected_benefit_usd=1_200_000.00,
            years_to_payout=5,
        )
        assert liability["discounted_benefit_usd"] == pytest.approx(940_231.40, abs=0.01)

        resubmitted = validate_success(
            api.submit_risk_assessment_to_board(assessment["id"], RISK)
        )
        assert resubmitted["status"] == "BOARD_SUBMITTED"
        assert resubmitted["critical_plan_count"] == 1
        assert resubmitted["underfunded_plan_count"] == 0
        assert resubmitted["risk_points"] == 25
        assert resubmitted["risk_rating"] == "MODERATE"

        accepted = validate_success(
            api.accept_risk_assessment(
                assessment["id"], {"board_note": "Accepted with the restated exhibit."}, BOARD
            )
        )
        assert accepted["status"] == "BOARD_ACCEPTED"
        assert accepted["board_note"] == "Accepted with the restated exhibit."
