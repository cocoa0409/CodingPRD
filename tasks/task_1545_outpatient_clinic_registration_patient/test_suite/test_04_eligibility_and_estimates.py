"""Eligibility verification results and the two copay-estimate variants (PRD §3.2, §3.5)."""
from test_helpers import (
    ApiErrorId,
    assert_copay_estimate,
    create_patient_payload,
    create_policy_for,
    create_prechecked_visit,
    create_registered_patient,
    get_success_data,
    post_eligibility_check,
    schedule_appointment,
    set_clock,
    setup_dual_variant_estimates,
    setup_oop_capped_estimate,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

REG = TEST_USERS["registrar_headers"]
FC = TEST_USERS["financial_counselor_headers"]


class TestCopayEstimateVariants:
    def test_payer_verified_variant_uses_payer_fields(self, api):
        """PRD §3.5: "`PAYER_VERIFIED` applies when a usable verification
        exists: an eligibility check for this appointment and policy whose
        result is not `STALE` and whose `coverage_status` is `ACTIVE`."
        PRD §3.5: "When that copay is zero, the estimate instead follows the
        deductible-then-coinsurance path: the deductible portion is the lesser
        of `allowed_amount_cents` and the policy's
        `deductible_remaining_cents`, and the responsibility becomes that
        deductible portion plus the coinsurance increment — the allowed amount
        beyond the deductible portion, multiplied by `coinsurance_pct` and
        divided by one hundred, rounded half up to a whole cent."

        Design: Difficulty/dual_variant_calc/copay_estimate_payer_verified_vs_fee_schedule
        """
        estimate_verified, _ = setup_dual_variant_estimates()
        assert_copay_estimate(estimate_verified)
        assert estimate_verified["method"] == "PAYER_VERIFIED"
        # ded = min(100000, 30000) = 30000; coinsurance = (100000-30000)*20/100
        # = 14000; responsibility = 44000; capped at oop_max 500000.
        assert estimate_verified["estimated_patient_responsibility_cents"] == 44000

    def test_fee_schedule_variant_uses_flat_schedule(self, api):
        """PRD §3.5: "`FEE_SCHEDULE` applies when no usable verification
        exists, and it ignores payer-reported fields entirely."
        PRD §3.5: "Under `FEE_SCHEDULE`, a flat base fee is selected by
        `visit_type`: 22000 cents for a `NEW` visit, 14000 cents for
        `ESTABLISHED`, 45000 cents for `PROCEDURE`, and 38000 cents for
        `IMAGING`. The base is then multiplied by a loading factor — 1.0 for
        `ESTABLISHED` visits, and the new-patient loading of 1.2 for every
        other visit type — and the product is rounded half up to a whole cent."

        Design: Difficulty/dual_variant_calc/copay_estimate_payer_verified_vs_fee_schedule
        """
        estimate_verified, estimate_fee = setup_dual_variant_estimates()
        assert_copay_estimate(estimate_fee)
        assert estimate_fee["method"] == "FEE_SCHEDULE"
        # NEW visit: round_half_up(22000 * 1.2) = 26400.
        assert estimate_fee["estimated_patient_responsibility_cents"] == 26400
        assert (
            estimate_verified["estimated_patient_responsibility_cents"]
            != estimate_fee["estimated_patient_responsibility_cents"]
        )


class TestOopCapInteraction:
    def test_oop_cap_binds_payer_verified_estimate(self, api):
        """PRD §3.5: "In either case the responsibility is then capped at the
        policy's `oop_max_remaining_cents`."

        Design: Difficulty/combinatorial_formula/copay_estimate_deductible_coinsurance_oop_interaction
        """
        ctx = setup_oop_capped_estimate()
        estimate = ctx["estimate"]
        assert_copay_estimate(estimate)
        assert estimate["method"] == "PAYER_VERIFIED"
        # Raw path yields 30000 + 14000 = 44000; capped at oop_max 2000.
        assert estimate["estimated_patient_responsibility_cents"] == 2000

    def test_deposit_quarter_of_capped_estimate(self, api):
        """PRD §3.5: "Below that threshold, a `NEW` visit owes fifty percent of
        the estimate, and any other visit type owes twenty-five percent."
        PRD §3.5: "The target is stored on the estimate as
        `deposit_required_cents`, the estimate's own result as
        `estimated_patient_responsibility_cents`, and both are whole-cent
        figures produced by a single final round-half-up."

        Design: Difficulty/combinatorial_formula/copay_estimate_deductible_coinsurance_oop_interaction
        """
        ctx = setup_oop_capped_estimate()
        # ESTABLISHED visit, zero strikes: 25% of 2000 = 500.
        assert ctx["estimate"]["deposit_required_cents"] == 500


class TestEligibilityResults:
    def test_eligibility_stale_boundary_30_vs_31_days(self, api):
        """PRD §3.2: "A stored check flips to `STALE` when the current logical
        date falls strictly more than thirty days after the date of its
        `checked_at`; a check exactly thirty days old is still fresh."
        PRD §3.2: "Staleness is recomputed lazily — when the check is read and
        again during clearance sweeps — rather than by any batch job."

        Design: Corner/calculations/eligibility_result_stale_after_30_days
        """
        set_clock("2026-08-01T00:00:00Z")
        ctx = create_prechecked_visit(
            run_pre_check=False,
            scheduled_start="2026-09-05T09:00:00Z",
            provider_code="DRST",
            copay_cents=3500,
            coinsurance_pct=0,
            auth_required=False,
        )
        appointment_id = ctx["appointment"]["id"]

        set_clock("2026-08-31T00:00:00Z")
        checks = get_success_data(
            api.list_appointment_eligibility_checks(appointment_id, REG)
        )
        assert len(checks) == 1
        assert checks[0]["result"] == "VERIFIED"

        set_clock("2026-09-01T00:00:00Z")
        checks = get_success_data(
            api.list_appointment_eligibility_checks(appointment_id, REG)
        )
        assert len(checks) == 1
        assert checks[0]["result"] == "STALE"

    def test_eligibility_failed_on_inactive_coverage(self, api):
        """PRD §3.2: "The server stamps `checked_at` with the transaction time
        and derives the check's `result`: any `coverage_status` other than
        `ACTIVE` yields `FAILED`; otherwise an `auth_required` flag yields
        `VERIFIED_WITH_AUTH`; a clean active response yields `VERIFIED`."

        Design: Corner/calculations/eligibility_result_failed_on_inactive_coverage
        """
        patient = get_success_data(
            api.create_patient(
                create_patient_payload(
                    first_name="Fail",
                    last_name="Ed",
                    date_of_birth="1997-07-07",
                    sex_at_birth="F",
                    primary_phone="+15551300002",
                ),
                REG,
            )
        )
        policy = create_policy_for(patient["id"])
        appt = schedule_appointment(
            patient["id"], scheduled_start="2026-09-06T09:00:00Z", provider_code="DRFA"
        )
        res = api.create_eligibility_check(
            {
                "policy_id": policy["id"],
                "appointment_id": appt["id"],
                "coverage_status": "INACTIVE",
                "copay_cents": 0,
                "coinsurance_pct": 0,
                "auth_required": False,
            },
            REG,
        )
        check = validate_success(res, 201)
        assert check["result"] == "FAILED"


class TestCrossPatientReference:
    def test_cross_patient_policy_reference_rejected(self, api):
        """PRD §3.5: "The named policy must belong to the appointment's
        patient — a mismatch is rejected with `ERR_CROSS_PATIENT_REFERENCE`
        (HTTP 422) — and must be `ACTIVE`."

        Design: Corner/validations/cross_patient_policy_reference_rejected
        """
        p1 = get_success_data(
            api.create_patient(
                create_patient_payload(
                    first_name="Xp",
                    last_name="One",
                    date_of_birth="1983-03-23",
                    sex_at_birth="M",
                    primary_phone="+15551400004",
                ),
                REG,
            )
        )
        p2 = get_success_data(
            api.create_patient(
                create_patient_payload(
                    first_name="Xp",
                    last_name="Two",
                    date_of_birth="1984-04-24",
                    sex_at_birth="F",
                    primary_phone="+15551400005",
                ),
                REG,
            )
        )
        policy2 = create_policy_for(p2["id"])
        appt1 = schedule_appointment(
            p1["id"], scheduled_start="2026-09-10T09:00:00Z", provider_code="DRXP"
        )
        res = api.create_copay_estimate(
            appt1["id"], {"policy_id": policy2["id"], "allowed_amount_cents": 10000}, FC
        )
        validate_error(res, ApiErrorId.ERR_CROSS_PATIENT_REFERENCE)
