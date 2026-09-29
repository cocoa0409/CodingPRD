"""The gates a purchase request, a diligence file and an annual assessment must pass."""
import pytest
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.fixtures import (
    ANALYST,
    CLAIMS,
    RISK,
    TREASURY,
    add_allocation,
    approved_claim,
    authorized_carrier_with_product,
    compile_assessment,
    diligence_cleared_request,
    draft_consent,
    draft_purchase_request,
    file_capital_position,
    in_force_policy,
    insured_employee,
    move_clock,
    onboard_carrier,
    open_diligence_review,
    register_employee,
    register_product_type,
    reserved_capacity_request,
    submit_diligence_review,
    submitted_purchase_request,
)


SUMMIT = {
    "legal_name": "Summit Life",
    "naic_code": "71019",
    "am_best_rating": "A_PLUS",
    "statutory_surplus_usd": 400_000_000.00,
    "domicile_state": "UT",
}
TALON = {
    "legal_name": "Talon Life",
    "naic_code": "71020",
    "am_best_rating": "A_PLUS",
    "statutory_surplus_usd": 400_000_000.00,
    "domicile_state": "ID",
}
VELLUM = {
    "legal_name": "Vellum Life",
    "naic_code": "71022",
    "am_best_rating": "A_PLUS",
    "statutory_surplus_usd": 400_000_000.00,
    "domicile_state": "ME",
}

NOVAK = {
    "full_name": "Petr Novak",
    "employee_number": "E-8501",
    "annual_salary_usd": 3_000_000.00,
    "officer_flag": True,
}


class TestConsentEvidenceGate:
    def test_a_consent_that_was_never_executed_does_not_cover_the_request(self, api):
        """An unsigned consent form is no evidence at all.

        Submission requires that "an `EXECUTED` consent record must exist for the
        request's employee whose closed coverage interval contains the
        `requested_effective_date`", and "With no such record the submission fails
        with `ERR_CONSENT_MISSING` (HTTP 422)." A draft form is not executed, so
        the interval search finds nothing to test. Because "A request that is
        rejected changes nothing and bumps nothing", the request is left exactly
        as drafted, and the employee's posture is untouched too: the interest
        derivation "runs whenever a consent record for that employee is executed".

        Design: Corner/validations/submit_without_any_executed_consent_returns_consent_missing
        """
        carrier = onboard_carrier(
            api,
            legal_name="Quarry Life",
            naic_code="71017",
            am_best_rating="A",
            statutory_surplus_usd=500_000_000.00,
            domicile_state="TN",
        )
        product = register_product_type(
            api, carrier["id"], product_name="Quarry GA BOLI", account_type="GENERAL"
        )
        employee = register_employee(
            api,
            full_name="Cyd Vance",
            employee_number="E-8201",
            annual_salary_usd=500_000.00,
        )
        consent = draft_consent(
            api,
            employee["id"],
            coverage_start_date="2026-08-01T00:00:00Z",
            coverage_end_date="2027-07-31T00:00:00Z",
            consent_form_reference="CF-8201",
        )
        assert consent["status"] == "DRAFT"
        assert consent["executed_at"] is None

        request = draft_purchase_request(
            api,
            carrier["id"],
            product["id"],
            employee["id"],
            single_premium_usd=1_000_000.00,
            face_amount_usd=3_000_000.00,
            requested_effective_date="2026-09-01T00:00:00Z",
        )

        validate_error(
            api.submit_purchase_request(request["id"], ANALYST), "ERR_CONSENT_MISSING", 422
        )

        after = validate_success(api.get_purchase_request(request["id"], ANALYST))
        assert after["status"] == "DRAFT"
        assert after["version"] == 1, "the refused submission bumps nothing"
        assert after["submitted_by_user_id"] is None

        consent_after = validate_success(api.get_consent_record(consent["id"], ANALYST))
        assert consent_after["status"] == "DRAFT", "a failed submission never signs the form"

        employee_after = validate_success(api.get_employee(employee["id"], ANALYST))
        assert employee_after["insurable_interest_status"] == "NOT_ESTABLISHED", (
            "the derivation runs on execution, and no consent has been executed"
        )


class TestInsurableInterestGate:
    def test_a_low_paid_non_officer_is_refused_where_an_officer_passes(self, api):
        """Two identical requests part company on the employee's own attributes.

        Submission requires that "the employee's `insurable_interest_status` must
        read `ESTABLISHED`, which as described above requires salary of at least
        250,000.00 or an `officer_flag` of true; otherwise the submission fails
        with `ERR_INSURABLE_INTEREST_NOT_ESTABLISHED` (HTTP 422)." The derivation
        itself "has exactly two qualifying paths: the employee's
        `annual_salary_usd` is at least 250,000.00, **or** the employee's
        `officer_flag` is true. If either holds, the derived value is
        `ESTABLISHED`; if neither holds, it is `NOT_ESTABLISHED`."

        Design: Corner/validations/submit_for_a_low_salary_non_officer_returns_insurable_interest_not_established
        """
        carrier = onboard_carrier(
            api,
            legal_name="Ridge Life",
            naic_code="71018",
            am_best_rating="A",
            statutory_surplus_usd=500_000_000.00,
            domicile_state="CO",
        )
        product = register_product_type(
            api, carrier["id"], product_name="Ridge GA BOLI", account_type="GENERAL"
        )

        wells = insured_employee(
            api,
            employee_overrides={
                "full_name": "Ira Wells",
                "employee_number": "E-8301",
                "annual_salary_usd": 100_000.00,
                "officer_flag": False,
            },
            consent_overrides={
                "coverage_start_date": "2026-08-01T00:00:00Z",
                "coverage_end_date": "2027-07-31T00:00:00Z",
                "consent_form_reference": "CF-8301",
            },
        )
        yates = insured_employee(
            api,
            employee_overrides={
                "full_name": "Lena Yates",
                "employee_number": "E-8302",
                "annual_salary_usd": 100_000.00,
                "officer_flag": True,
            },
            consent_overrides={
                "coverage_start_date": "2026-08-01T00:00:00Z",
                "coverage_end_date": "2027-07-31T00:00:00Z",
                "consent_form_reference": "CF-8302",
            },
        )

        wells_employee = validate_success(api.get_employee(wells["employee_id"], ANALYST))
        assert wells_employee["insurable_interest_status"] == "NOT_ESTABLISHED", (
            "neither qualifying path holds for a 100,000.00 non-officer"
        )
        yates_employee = validate_success(api.get_employee(yates["employee_id"], ANALYST))
        assert yates_employee["insurable_interest_status"] == "ESTABLISHED", (
            "the officer flag alone qualifies at any salary"
        )

        refused = draft_purchase_request(
            api,
            carrier["id"],
            product["id"],
            wells["employee_id"],
            single_premium_usd=1_000_000.00,
            face_amount_usd=3_000_000.00,
            requested_effective_date="2026-09-01T00:00:00Z",
        )
        validate_error(
            api.submit_purchase_request(refused["id"], ANALYST),
            "ERR_INSURABLE_INTEREST_NOT_ESTABLISHED",
            422,
        )
        assert (
            validate_success(api.get_purchase_request(refused["id"], ANALYST))["status"]
            == "DRAFT"
        )

        accepted = draft_purchase_request(
            api,
            carrier["id"],
            product["id"],
            yates["employee_id"],
            single_premium_usd=1_000_000.00,
            face_amount_usd=3_000_000.00,
            requested_effective_date="2026-09-01T00:00:00Z",
        )
        response = api.submit_purchase_request(accepted["id"], ANALYST)
        assert response.status_code == 200
        submitted = validate_success(response)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_by_user_id"] == "analyst-1"


class TestNoticeWaitingPeriod:
    def test_approval_is_refused_one_day_early_and_granted_on_the_end_instant(self, api):
        """The regulatory waiting period is inclusive of its own end instant.

        "The server sets `notice_required` to true when the request's
        `single_premium_usd` is **strictly greater than** 25,000,000.00", and
        "Filing stamps `notice_filed_at` with the current logical clock instant
        and sets `notice_waiting_ends_at` to that instant advanced by 30 whole UTC
        days. It also increments the carrier's `regulatory_notice_count` by 1".
        At approval "the logical clock must have reached `notice_waiting_ends_at`,
        and an earlier clock value fails with `ERR_NOTICE_WAITING_PERIOD_ACTIVE`
        (HTTP 422). The comparison is inclusive, so a clock reading exactly equal
        to `notice_waiting_ends_at` passes."

        Design: Corner/validations/approve_before_the_notice_waiting_period_ends_then_succeeds_at_the_boundary
        """
        context = authorized_carrier_with_product(
            api,
            carrier_overrides=SUMMIT,
            product_overrides={"product_name": "Summit GA BOLI"},
        )
        insured = insured_employee(
            api,
            employee_overrides={
                "full_name": "Wei Zhao",
                "employee_number": "E-8401",
                "annual_salary_usd": 500_000.00,
            },
            consent_overrides={
                "coverage_start_date": "2026-08-01T00:00:00Z",
                "coverage_end_date": "2027-07-31T00:00:00Z",
                "consent_form_reference": "CF-8401",
            },
        )
        request = diligence_cleared_request(
            api,
            context["carrier_id"],
            context["product_type_id"],
            insured["employee_id"],
            single_premium_usd=30_000_000.00,
            face_amount_usd=90_000_000.00,
            requested_effective_date="2026-09-15T00:00:00Z",
        )
        assert request["notice_required"] is True, "30,000,000.00 is above the threshold"

        reserved = reserved_capacity_request(api, request["id"], context["carrier_id"])
        assert reserved["status"] == "CAPACITY_RESERVED"
        assert reserved["reserved_premium_usd"] == pytest.approx(30_000_000.00, abs=0.01)

        filed = validate_success(api.file_purchase_request_notice(request["id"], TREASURY))
        assert filed["status"] == "NOTICE_FILED"
        assert filed["notice_filed_at"].startswith("2026-08-01T00:00:00")
        assert filed["notice_waiting_ends_at"].startswith("2026-08-31T00:00:00"), (
            "thirty whole days after the filing instant"
        )
        carrier_after_notice = validate_success(
            api.get_carrier(context["carrier_id"], TREASURY)
        )
        assert carrier_after_notice["regulatory_notice_count"] == 1

        pending = validate_success(
            api.request_purchase_request_concurrence(request["id"], ANALYST)
        )
        assert pending["status"] == "CONCURRENCE_PENDING"

        move_clock(api, "2026-08-30T00:00:00Z")
        validate_error(
            api.approve_purchase_request(request["id"], RISK),
            "ERR_NOTICE_WAITING_PERIOD_ACTIVE",
            422,
        )
        still_pending = validate_success(api.get_purchase_request(request["id"], RISK))
        assert still_pending["status"] == "CONCURRENCE_PENDING"

        move_clock(api, "2026-08-31T00:00:00Z")
        response = api.approve_purchase_request(request["id"], RISK)
        assert response.status_code == 200
        approved = validate_success(response)
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "risk-1"

        carrier = validate_success(api.get_carrier(context["carrier_id"], TREASURY))
        assert carrier["reserved_premium_usd"] == pytest.approx(30_000_000.00, abs=0.01)
        assert carrier["in_force_premium_usd"] == pytest.approx(0.00, abs=0.01), (
            "premium only moves in force when the policy is issued"
        )


class TestBeneficiaryTotalGate:
    def test_the_total_is_capped_on_create_and_required_exactly_on_seal(self, api):
        """The same basis-point total is policed from above and from below.

        "The running total of `ACTIVE` allocations may never exceed 10000 basis
        points on a create, and an addition that would push it past that is
        rejected with `ERR_BENEFICIARY_TOTAL_INVALID` (HTTP 422)." Sealing then
        demands the other side of the same figure: "the `ACTIVE` allocations must
        sum to **exactly** 10000 basis points, with any other total refused as
        `ERR_BENEFICIARY_TOTAL_INVALID`." Until the seal prices them, "Each
        allocation opens in `ACTIVE` with `gross_amount_usd` at 0.00".

        Design: Corner/validations/allocations_over_ten_thousand_bps_rejected_on_create_and_seal_rejected_below_it
        """
        context = in_force_policy(
            api,
            carrier_overrides=TALON,
            product_overrides={"product_name": "Talon GA BOLI"},
            employee_overrides=NOVAK,
            consent_overrides={"consent_form_reference": "CF-8501"},
            request_overrides={
                "single_premium_usd": 1_200_000.00,
                "face_amount_usd": 5_000_000.00,
            },
            policy_overrides={"policy_number": "TL-0001"},
        )
        claim = approved_claim(
            api,
            context["policy_id"],
            date_of_death="2026-08-19T00:00:00Z",
            terminal_dividend_usd=0.00,
            proof_reference="DC-8501",
        )
        spouse = add_allocation(
            api,
            claim["id"],
            beneficiary_name="Eva Novak",
            relationship="SPOUSE",
            allocation_pct_bps=6000,
        )

        validate_error(
            api.create_beneficiary_allocation(
                {
                    "claim_id": claim["id"],
                    "beneficiary_name": "Jan Novak",
                    "relationship": "CHILD",
                    "allocation_pct_bps": 5000,
                },
                CLAIMS,
            ),
            "ERR_BENEFICIARY_TOTAL_INVALID",
            422,
        )
        rows, meta = validate_paginated(
            api.list_beneficiary_allocations(CLAIMS, params={"claim_id": claim["id"]})
        )
        assert meta["total_count"] == 1, "the refused create stores no second allocation"
        assert [r["beneficiary_name"] for r in rows] == ["Eva Novak"]

        after_refusal = validate_success(api.get_death_claim(claim["id"], CLAIMS))
        assert after_refusal["allocated_bps_total"] == 6000

        validate_error(
            api.seal_claim_allocations(claim["id"], CLAIMS),
            "ERR_BENEFICIARY_TOTAL_INVALID",
            422,
        )
        unsealed = validate_success(api.get_death_claim(claim["id"], CLAIMS))
        assert unsealed["distribution_status"] == "NOT_STARTED"
        assert unsealed["adjudication_status"] == "APPROVED"

        surviving = validate_success(api.get_beneficiary_allocation(spouse["id"], CLAIMS))
        assert surviving["status"] == "ACTIVE"
        assert surviving["gross_amount_usd"] == pytest.approx(0.00, abs=0.01), (
            "an allocation stays unpriced until the split is sealed"
        )


class TestCapitalDenominatorGate:
    def test_a_review_cannot_be_scored_before_any_snapshot_exists(self, api):
        """The score needs a denominator that lives on another entity entirely.

        Submitting a review requires "at least one capital snapshot must exist,
        failing which the submission reports `ERR_NO_CAPITAL_POSITION`", and the
        guarded set is closed: "Reserving capacity for a purchase request, reading
        the what-if capacity projection for a request, submitting a diligence
        review for decision, and compiling an annual risk assessment all fail with
        `ERR_NO_CAPITAL_POSITION` (HTTP 422) when the snapshot series is empty."
        Once a snapshot exists the identical call succeeds and "records the acting
        `X-User-ID` as `submitted_by_user_id`".

        Design: Corner/validations/diligence_submit_without_a_capital_position_returns_no_capital_position
        """
        carrier = onboard_carrier(
            api,
            legal_name="Umber Life",
            naic_code="71021",
            am_best_rating="A_PLUS",
            statutory_surplus_usd=400_000_000.00,
            domicile_state="WI",
        )
        review = open_diligence_review(api, carrier["id"], review_year=2026)

        validate_error(
            api.submit_diligence_review(review["id"], ANALYST), "ERR_NO_CAPITAL_POSITION", 422
        )
        blocked = validate_success(api.get_diligence_review(review["id"], ANALYST))
        assert blocked["status"] == "DRAFT"
        assert blocked["version"] == 1, "the refused submission bumps nothing"
        assert blocked["submitted_by_user_id"] is None, "no submitter was recorded"

        file_capital_position(
            api,
            as_of_date="2026-06-30T00:00:00Z",
            tier1_capital_usd=1_000_000_000.00,
            total_assets_usd=12_000_000_000.00,
        )

        response = api.submit_diligence_review(review["id"], ANALYST)
        assert response.status_code == 200
        submitted = validate_success(response)
        assert submitted["status"] == "UNDER_REVIEW"
        assert submitted["financial_strength_score"] == 65
        assert submitted["submitted_by_user_id"] == "analyst-1"


class TestAssessmentYearUniqueness:
    def test_a_year_is_claimed_once_across_every_capital_snapshot(self, api):
        """The uniqueness key is the year, not the snapshot the report cites.

        "No two assessments may carry the same `assessment_year`, and a duplicate
        is rejected with `ERR_ASSESSMENT_YEAR_DUPLICATE` (HTTP 409)". A fresh year
        against the same snapshot is accepted: "Compilation responds with HTTP 201,
        opens the assessment in `COMPILED`, stamps `compiled_at` with the current
        logical clock instant, and leaves `board_note` unset", and with nothing on
        the platform to count, "`risk_rating` is then `SEVERE` when `risk_points`
        is 60 or more" down to "`LOW` when it is below 15".

        Design: Corner/validations/a_second_assessment_for_the_same_year_returns_assessment_year_duplicate
        """
        first_snapshot = file_capital_position(
            api,
            as_of_date="2026-06-30T00:00:00Z",
            tier1_capital_usd=1_000_000_000.00,
            total_assets_usd=12_000_000_000.00,
        )
        second_snapshot = file_capital_position(
            api,
            as_of_date="2026-09-30T00:00:00Z",
            tier1_capital_usd=1_050_000_000.00,
            total_assets_usd=12_500_000_000.00,
        )
        first = compile_assessment(api, first_snapshot["id"], assessment_year=2026)
        assert first["status"] == "COMPILED"

        validate_error(
            api.create_risk_assessment(
                {"capital_position_id": second_snapshot["id"], "assessment_year": 2026},
                RISK,
            ),
            "ERR_ASSESSMENT_YEAR_DUPLICATE",
            409,
        )
        rows, meta = validate_paginated(
            api.list_risk_assessments(RISK, params={"assessment_year": 2026})
        )
        assert meta["total_count"] == 1, "the year is still claimed by exactly one report"
        assert rows[0]["id"] == first["id"]

        later = validate_success(
            api.create_risk_assessment(
                {"capital_position_id": second_snapshot["id"], "assessment_year": 2027},
                RISK,
            ),
            201,
        )
        assert later["assessment_year"] == 2027
        assert later["status"] == "COMPILED"
        assert later["board_note"] is None
        assert later["risk_points"] == 0
        assert later["risk_rating"] == "LOW"


class TestDiligenceClearanceGate:
    def test_the_same_clearance_call_flips_once_the_review_is_approved(self, api):
        """Clearance depends on the carrier's posture, not on the request.

        Clearing diligence requires that "The carrier must currently be
        `AUTHORIZED` — a carrier in any other posture, including `RESTRICTED`,
        blocks clearance", and that among the approved files "the one with the
        greatest `review_year` must carry a `financial_strength_score` of at least
        65; if the carrier has no approved file at all, or the most recent approved
        year's score falls below 65, the clearance fails with
        `ERR_DILIGENCE_NOT_CLEARED` (HTTP 422)." Approval supplies both, and then
        "On success only the request's `version` moves, incremented by 1."

        Design: Corner/validations/clear_diligence_fails_before_approval_and_passes_after_it
        """
        file_capital_position(
            api,
            as_of_date="2026-06-30T00:00:00Z",
            tier1_capital_usd=1_000_000_000.00,
            total_assets_usd=12_000_000_000.00,
        )
        carrier = onboard_carrier(api, **VELLUM)
        product = register_product_type(
            api, carrier["id"], product_name="Vellum GA BOLI", account_type="GENERAL"
        )
        review = open_diligence_review(api, carrier["id"], review_year=2026)
        under_review = submit_diligence_review(api, review["id"])
        assert under_review["status"] == "UNDER_REVIEW"
        assert (
            validate_success(api.get_carrier(carrier["id"], RISK))["status"]
            == "PENDING_DILIGENCE"
        ), "a file still under review authorizes nothing"

        insured = insured_employee(
            api,
            employee_overrides={
                "full_name": "Ken Ohara",
                "employee_number": "E-8601",
                "annual_salary_usd": 600_000.00,
            },
            consent_overrides={
                "coverage_start_date": "2026-08-01T00:00:00Z",
                "coverage_end_date": "2027-07-31T00:00:00Z",
                "consent_form_reference": "CF-8601",
            },
        )
        request = submitted_purchase_request(
            api,
            carrier["id"],
            product["id"],
            insured["employee_id"],
            single_premium_usd=1_000_000.00,
            face_amount_usd=3_000_000.00,
            requested_effective_date="2026-08-15T00:00:00Z",
        )

        validate_error(
            api.clear_purchase_request_diligence(request["id"], RISK),
            "ERR_DILIGENCE_NOT_CLEARED",
            422,
        )
        assert (
            validate_success(api.get_purchase_request(request["id"], RISK))["status"]
            == "SUBMITTED"
        )

        approved_review = validate_success(api.approve_diligence_review(review["id"], RISK))
        assert approved_review["status"] == "APPROVED"
        assert approved_review["financial_strength_score"] == 65
        authorized = validate_success(api.get_carrier(carrier["id"], RISK))
        assert authorized["status"] == "AUTHORIZED"
        assert authorized["last_approved_review_year"] == 2026

        cleared = validate_success(api.clear_purchase_request_diligence(request["id"], RISK))
        assert cleared["status"] == "DILIGENCE_CLEARED"

        carrier_after = validate_success(api.get_carrier(carrier["id"], TREASURY))
        assert carrier_after["reserved_premium_usd"] == pytest.approx(0.00, abs=0.01), (
            "clearing diligence claims nothing against the balance sheet"
        )
