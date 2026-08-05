"""Insurance: the three-way predetermination answer, the two-stage coordination
of benefits, and the reversal that returns consumed benefit."""

from test_helpers import (
    ApiErrorId,
    assert_claim,
    assert_coverage_benefit_conserved,
    assert_money,
    assert_predetermination,
    assert_same_instant,
    fixtures as fx,
    validate_error,
    validate_success,
)


def _implant_case_with_predetermination(name, dob, phone):
    """One IMPLANT_RETAINED_OVERDENTURE case at 3600.00 with a SUBMITTED preauth."""
    fx.set_clock("2026-05-01T00:00:00Z")
    patient = fx.register_patient(full_name=name, date_of_birth=dob, phone=phone)
    coverage = fx.enrol_coverage(
        patient["id"],
        carrier_name="Meridian Dental",
        rank="PRIMARY",
        effective_date="2025-01-01T00:00:00Z",
        annual_maximum_amount=1500.00,
        coinsurance_major_rate=0.50,
        alternate_benefit_enabled=True,
    )
    case = fx.open_case(patient["id"], "IMPLANT_RETAINED_OVERDENTURE")
    fx.add_arch(case["id"], "MAXILLARY")
    case = fx.complete_exam(case["id"])
    predetermination = fx.submit_predetermination(case["id"], coverage["id"])
    return {
        "patient": patient,
        "coverage": coverage,
        "case": case,
        "predetermination": predetermination,
    }


class TestPredeterminationVariants:
    def test_an_approved_determination_prices_the_estimate_on_the_requested_amount(self, api, front_office_headers):
        """PRD §3.8: "- **`APPROVED`** sets `allowed_amount` equal to
        `requested_amount` and leaves `alternate_benefit_type` null. The plan pays
        coinsurance on what was actually requested."
        PRD §3.8: "The uncapped estimate is `allowed_amount` multiplied by the cited
        coverage's `coinsurance_major_rate`, rounded half up to two decimal places;
        `estimated_plan_payment` is then the lesser of that rounded figure and the
        coverage's `benefit_remaining` — the cap is applied **after** the rounding,
        never before. `estimated_patient_responsibility` is `requested_amount` minus
        `estimated_plan_payment`, rounded half up to two decimal places."

        Design: Difficulty/dual_variant_calc/alternate_benefit_downgrade_vs_standard_predetermination
        """
        ctx = _implant_case_with_predetermination("Adaeze Fenwick", "1957-03-14", "555-0142")
        assert_money(
            ctx["predetermination"]["requested_amount"],
            3600.00,
            "Predetermination.requested_amount",
        )

        determined = validate_success(
            api.determine_predetermination(
                ctx["predetermination"]["id"], {"determination": "APPROVED"}, front_office_headers
            ),
            200,
        )

        assert_predetermination(determined)
        assert determined["determination_status"] == "APPROVED"
        assert_money(determined["allowed_amount"], 3600.00, "allowed_amount")
        assert_money(determined["estimated_plan_payment"], 1500.00, "estimated_plan_payment")
        assert_money(
            determined["estimated_patient_responsibility"],
            2100.00,
            "estimated_patient_responsibility",
        )
        assert determined["alternate_benefit_type"] is None

    def test_an_alternate_benefit_determination_swaps_the_allowed_basis_to_the_downgrade(self, api, front_office_headers):
        """PRD §3.8: "When it can, `alternate_benefit_type` is set to the downgrade
        target and `allowed_amount` is set to the fee of that target type — 1800.00 for
        a complete denture, 1200.00 for a flexible partial — multiplied by the number
        of the case's arches whose `arch_status` is not `ARCH_ABANDONED`."
        PRD §3.8: "an implant-retained overdenture and a plain overdenture both
        downgrade to `COMPLETE_DENTURE`, and a cast partial downgrades to
        `FLEXIBLE_PARTIAL`, while the other three types have no declared target."
        PRD §3.1: "Thereafter `benefit_used_ytd` is the sum of `plan_paid_amount` over
        the claims that cite this coverage and whose `adjudication_status` is
        `PRIMARY_PAID`, `SECONDARY_PAID`, or `CLOSED`, and `benefit_remaining` is
        `annual_maximum_amount` minus `benefit_used_ytd`, floored at 0.00 so that it
        never goes negative."

        Design: Difficulty/dual_variant_calc/alternate_benefit_downgrade_vs_standard_predetermination
        """
        ctx = _implant_case_with_predetermination("Adaeze Fenwick", "1957-03-14", "555-0142")

        determined = validate_success(
            api.determine_predetermination(
                ctx["predetermination"]["id"],
                {"determination": "ALTERNATE_BENEFIT"},
                front_office_headers,
            ),
            200,
        )

        assert determined["determination_status"] == "ALTERNATE_BENEFIT"
        assert determined["alternate_benefit_type"] == "COMPLETE_DENTURE"
        assert_money(determined["allowed_amount"], 1800.00, "allowed_amount")
        assert_money(determined["estimated_plan_payment"], 900.00, "estimated_plan_payment")
        assert_money(
            determined["estimated_patient_responsibility"],
            2700.00,
            "estimated_patient_responsibility",
        )

        coverage = fx.read_coverage(ctx["coverage"]["id"])
        assert_money(
            coverage["benefit_used_ytd"],
            0.00,
            "a predetermination is an estimate and consumes no benefit",
        )
        assert_coverage_benefit_conserved(coverage)


def _case_with_two_coverages(name, dob, phone, secondary_convention, secondary_maximum=1000.00):
    fx.set_clock("2026-05-01T00:00:00Z")
    patient = fx.register_patient(full_name=name, date_of_birth=dob, phone=phone)
    primary = fx.enrol_coverage(
        patient["id"],
        carrier_name="Meridian Dental",
        rank="PRIMARY",
        effective_date="2024-01-01T00:00:00Z",
        annual_maximum_amount=1500.00,
        coinsurance_major_rate=0.50,
    )
    secondary = fx.enrol_coverage(
        patient["id"],
        carrier_name="Harborline Health",
        rank="SECONDARY",
        effective_date="2024-01-01T00:00:00Z",
        annual_maximum_amount=secondary_maximum,
        coinsurance_major_rate=0.60,
        cob_convention=secondary_convention,
    )
    case = fx.open_case(patient["id"], "FLEXIBLE_PARTIAL")
    fx.add_arch(case["id"], "MANDIBULAR")
    case = fx.complete_exam(case["id"])
    claim = fx.open_claim(case["id"], primary["id"])
    return {
        "patient": patient,
        "primary": primary,
        "secondary": secondary,
        "case": case,
        "claim": claim,
    }


class TestCoordinationOfBenefits:
    def test_a_standard_secondary_tops_the_patient_up_towards_the_allowed_amount(self, api, front_office_headers):
        """PRD §3.8: "- Under the **`STANDARD`** convention, the secondary tops the
        patient up towards the allowed amount: the raw figure is the lesser of (the
        claim's `allowed_amount` minus `primary_paid_amount`, rounded half up to two
        decimal places) and the patient's outstanding balance."
        PRD §3.8: "In both conventions, `secondary_paid_amount` is the raw figure
        floored at 0.00 and then capped at the secondary coverage's
        `benefit_remaining`. `plan_paid_amount` becomes `primary_paid_amount` plus
        `secondary_paid_amount`, rounded half up to two decimal places, and the claim's
        `patient_responsibility_amount` becomes `billed_amount` minus
        `plan_paid_amount`, rounded half up and floored at 0.00."

        Design: Difficulty/dual_variant_calc/cob_standard_vs_non_duplication_secondary_payment
        """
        ctx = _case_with_two_coverages("Sena Ruiz", "1951-06-09", "555-0201", "STANDARD")
        claim_id = ctx["claim"]["id"]

        fx.submit_claim(claim_id)
        fx.post_claim_payment(claim_id, "PAID")
        fx.submit_claim(claim_id)
        closed = validate_success(
            api.post_claim_payment(claim_id, {"adjudication_outcome": "PAID"}, front_office_headers),
            200,
        )

        assert_claim(closed)
        assert_money(closed["primary_paid_amount"], 600.00, "primary_paid_amount")
        assert closed["cob_convention_applied"] == "STANDARD"
        assert_money(closed["secondary_paid_amount"], 600.00, "secondary_paid_amount")
        assert_money(closed["plan_paid_amount"], 1200.00, "plan_paid_amount")
        assert_money(
            closed["patient_responsibility_amount"], 0.00, "Claim.patient_responsibility_amount"
        )
        assert closed["adjudication_status"] == "CLOSED"
        assert_money(
            fx.read_coverage(ctx["secondary"]["id"])["benefit_remaining"],
            400.00,
            "secondary benefit_remaining",
        )

    def test_a_non_duplication_secondary_pays_only_the_excess_over_the_primary(self, api, front_office_headers):
        """PRD §3.8: "- Under the **`NON_DUPLICATION`** convention, the secondary pays
        only the excess of what it would have paid over what the primary actually
        paid: the raw figure is the amount it would have paid as a primary minus
        `primary_paid_amount`, rounded half up to two decimal places and floored at
        0.00. Where the primary already paid at least as much, the secondary pays
        nothing."
        PRD §3.8: "Two intermediate quantities are computed first, both rounded half up
        to two decimal places: the amount the secondary *would have* paid as a primary,
        which is the claim's `allowed_amount` multiplied by the secondary coverage's
        `coinsurance_major_rate`; and the patient's outstanding balance, which is
        `billed_amount` minus `primary_paid_amount`, floored at 0.00."

        Design: Difficulty/dual_variant_calc/cob_standard_vs_non_duplication_secondary_payment
        """
        ctx = _case_with_two_coverages("Noor Vasquez", "1953-02-21", "555-0202", "NON_DUPLICATION")
        claim_id = ctx["claim"]["id"]

        fx.submit_claim(claim_id)
        fx.post_claim_payment(claim_id, "PAID")
        fx.submit_claim(claim_id)
        closed = validate_success(
            api.post_claim_payment(claim_id, {"adjudication_outcome": "PAID"}, front_office_headers),
            200,
        )

        assert_money(closed["primary_paid_amount"], 600.00, "primary_paid_amount")
        assert closed["cob_convention_applied"] == "NON_DUPLICATION"
        assert_money(closed["secondary_paid_amount"], 120.00, "secondary_paid_amount")
        assert_money(closed["plan_paid_amount"], 720.00, "plan_paid_amount")
        assert_money(
            closed["patient_responsibility_amount"], 480.00, "Claim.patient_responsibility_amount"
        )
        assert_money(
            fx.read_coverage(ctx["secondary"]["id"])["benefit_remaining"],
            880.00,
            "secondary benefit_remaining",
        )

    def test_the_secondary_cap_binds_after_the_non_duplication_floor(self, api, front_office_headers):
        """PRD §3.8: "- Under the **`NON_DUPLICATION`** convention, the secondary pays
        only the excess of what it would have paid over what the primary actually
        paid: the raw figure is the amount it would have paid as a primary minus
        `primary_paid_amount`, rounded half up to two decimal places and floored at
        0.00. Where the primary already paid at least as much, the secondary pays
        nothing."
        PRD §3.8: "In both conventions, `secondary_paid_amount` is the raw figure
        floored at 0.00 and then capped at the secondary coverage's
        `benefit_remaining`."

        Design: Difficulty/combinatorial_formula/non_duplication_cob_nested_min_max_with_binding_secondary_cap
        """
        ctx = _case_with_two_coverages(
            "Fenna Adeyemi", "1958-09-27", "555-0266", "NON_DUPLICATION", secondary_maximum=100.00
        )
        claim_id = ctx["claim"]["id"]

        fx.submit_claim(claim_id)
        fx.post_claim_payment(claim_id, "PAID")
        fx.submit_claim(claim_id)
        closed = validate_success(
            api.post_claim_payment(claim_id, {"adjudication_outcome": "PAID"}, front_office_headers),
            200,
        )

        assert_money(closed["allowed_amount"], 1200.00, "Claim.allowed_amount")
        assert_money(closed["primary_paid_amount"], 600.00, "primary_paid_amount")
        assert_money(
            closed["secondary_paid_amount"],
            100.00,
            "the excess of 120.00 is clamped down to the secondary's remaining benefit",
        )
        assert_money(closed["plan_paid_amount"], 700.00, "plan_paid_amount")
        assert_money(
            closed["patient_responsibility_amount"], 500.00, "Claim.patient_responsibility_amount"
        )

    def test_the_binding_secondary_cap_empties_the_pool_and_lands_on_the_case(self, api):
        """PRD §3.8: "The secondary coverage's `benefit_used_ytd` rises by
        `secondary_paid_amount` and its `benefit_remaining` falls by the same, the
        case's money fields are recomputed, `adjudicated_at` is stamped, the claim's
        `version` increments by 1, and the claim then moves on to `CLOSED` with a
        further increment."
        PRD §3.9: "5. `insurance_paid_amount` is the sum of `plan_paid_amount` over the
        case's claims whose `adjudication_status` is `PRIMARY_PAID`, `SECONDARY_PAID`,
        or `CLOSED`."
        PRD §3.9: "6. The **pre-discount responsibility** is `billed_amount` minus
        `insurance_paid_amount`, rounded half up to two decimal places and floored at
        0.00."

        Design: Difficulty/combinatorial_formula/non_duplication_cob_nested_min_max_with_binding_secondary_cap
        """
        ctx = _case_with_two_coverages(
            "Fenna Adeyemi", "1958-09-27", "555-0266", "NON_DUPLICATION", secondary_maximum=100.00
        )
        claim_id = ctx["claim"]["id"]

        fx.submit_claim(claim_id)
        fx.post_claim_payment(claim_id, "PAID")
        fx.submit_claim(claim_id)
        fx.post_claim_payment(claim_id, "PAID")

        secondary = fx.read_coverage(ctx["secondary"]["id"])
        assert_money(secondary["benefit_used_ytd"], 100.00, "secondary benefit_used_ytd")
        assert_money(secondary["benefit_remaining"], 0.00, "secondary benefit_remaining")
        assert_coverage_benefit_conserved(secondary)

        case = fx.read_case(ctx["case"]["id"])
        assert_money(case["insurance_paid_amount"], 700.00, "ProsthesisCase.insurance_paid_amount")
        assert_money(
            case["patient_responsibility_amount"],
            500.00,
            "ProsthesisCase.patient_responsibility_amount",
        )


def _single_primary_coverage_case(name, dob, phone, annual_maximum=1500.00, effective="2024-01-01T00:00:00Z", waiting_period_days=None):
    fx.set_clock("2026-05-01T00:00:00Z")
    patient = fx.register_patient(full_name=name, date_of_birth=dob, phone=phone)
    coverage_kwargs = {
        "carrier_name": "Meridian Dental",
        "rank": "PRIMARY",
        "effective_date": effective,
        "annual_maximum_amount": annual_maximum,
        "coinsurance_major_rate": 0.50,
    }
    if waiting_period_days is not None:
        coverage_kwargs["waiting_period_days"] = waiting_period_days
    coverage = fx.enrol_coverage(patient["id"], **coverage_kwargs)
    case = fx.open_case(patient["id"], "FLEXIBLE_PARTIAL")
    fx.add_arch(case["id"], "MANDIBULAR")
    case = fx.complete_exam(case["id"])
    claim = fx.open_claim(case["id"], coverage["id"])
    return {"patient": patient, "coverage": coverage, "case": case, "claim": claim}


class TestBenefitConservation:
    def test_posting_the_primary_payment_consumes_exactly_that_much_benefit(self, api, front_office_headers):
        """PRD §2.13: "**Coverage benefit.** On any coverage, `benefit_used_ytd` plus
        `benefit_remaining` always equals `annual_maximum_amount`. Posting a payment
        consumes benefit; reversing the claim returns it."
        PRD §3.8: "**Primary paid.** The uncapped payment is the claim's
        `allowed_amount` multiplied by the primary coverage's `coinsurance_major_rate`,
        rounded half up to two decimal places; `primary_paid_amount` is the lesser of
        that rounded figure and the primary coverage's `benefit_remaining`, the cap
        again applied after the rounding."
        PRD §3.8: "When the patient holds no coverage at `SECONDARY`, the claim then
        moves straight on to `CLOSED` with a further `version` increment."

        Design: Difficulty/compensating_invariant/coverage_benefit_conserved_across_payment_and_claim_reversal
        """
        ctx = _single_primary_coverage_case("Viggo Amankwah", "1957-07-07", "555-0444")
        before = fx.read_coverage(ctx["coverage"]["id"])
        assert_money(before["benefit_used_ytd"], 0.00, "benefit_used_ytd before")
        assert_money(before["benefit_remaining"], 1500.00, "benefit_remaining before")
        assert_coverage_benefit_conserved(before)

        fx.submit_claim(ctx["claim"]["id"])
        paid = validate_success(
            api.post_claim_payment(
                ctx["claim"]["id"], {"adjudication_outcome": "PAID"}, front_office_headers
            ),
            200,
        )

        assert paid["adjudication_status"] == "CLOSED"
        assert_money(paid["plan_paid_amount"], 600.00, "Claim.plan_paid_amount")
        after = fx.read_coverage(ctx["coverage"]["id"])
        assert_money(after["benefit_used_ytd"], 600.00, "benefit_used_ytd after")
        assert_money(after["benefit_remaining"], 900.00, "benefit_remaining after")
        assert_coverage_benefit_conserved(after)

    def test_reversing_the_closed_claim_returns_the_benefit_and_the_balance(self, api, front_office_headers):
        """PRD §3.8: "It decreases the primary coverage's `benefit_used_ytd` by
        `primary_paid_amount` and the secondary coverage's `benefit_used_ytd` by
        `secondary_paid_amount`, restoring both `benefit_remaining` figures to their
        pre-adjudication values; sets `primary_paid_amount`, `secondary_paid_amount`,
        and `plan_paid_amount` all to 0.00; recomputes the case's
        `insurance_paid_amount` and `patient_responsibility_amount`; stamps
        `reversed_at`; and increments the claim's `version` by 1."
        PRD §3.8: "`CLOSED` is deliberately **not** a terminal state of the
        adjudication axis, precisely so that reversal stays reachable; every trigger
        other than reversal attempted from `CLOSED` is refused with
        `ERR_INVALID_STATE`. `DENIED` and `REVERSED` are the two terminal states."

        Design: Difficulty/compensating_invariant/coverage_benefit_conserved_across_payment_and_claim_reversal
        """
        ctx = _single_primary_coverage_case("Viggo Amankwah", "1957-07-07", "555-0444")
        fx.submit_claim(ctx["claim"]["id"])
        fx.post_claim_payment(ctx["claim"]["id"], "PAID")

        reversed_claim = validate_success(
            api.reverse_claim(
                ctx["claim"]["id"],
                front_office_headers,
                {"reversal_reason": "Carrier recouped the payment after an eligibility audit"},
            ),
            200,
        )

        assert reversed_claim["adjudication_status"] == "REVERSED"
        assert_money(reversed_claim["plan_paid_amount"], 0.00, "Claim.plan_paid_amount")
        assert_money(reversed_claim["primary_paid_amount"], 0.00, "Claim.primary_paid_amount")

        coverage = fx.read_coverage(ctx["coverage"]["id"])
        assert_money(coverage["benefit_used_ytd"], 0.00, "benefit_used_ytd after reversal")
        assert_money(coverage["benefit_remaining"], 1500.00, "benefit_remaining after reversal")
        assert_coverage_benefit_conserved(coverage)

        case = fx.read_case(ctx["case"]["id"])
        assert_money(case["insurance_paid_amount"], 0.00, "ProsthesisCase.insurance_paid_amount")
        assert_money(
            case["patient_responsibility_amount"],
            1200.00,
            "ProsthesisCase.patient_responsibility_amount",
        )


class TestSubmissionRungs:
    def test_the_primary_payment_is_capped_by_the_annual_maximum(self, api, front_office_headers):
        """PRD §3.8: "**Primary paid.** The uncapped payment is the claim's
        `allowed_amount` multiplied by the primary coverage's `coinsurance_major_rate`,
        rounded half up to two decimal places; `primary_paid_amount` is the lesser of
        that rounded figure and the primary coverage's `benefit_remaining`, the cap
        again applied after the rounding. `plan_paid_amount` is set equal to
        `primary_paid_amount`. The claim's own `patient_responsibility_amount` is
        `billed_amount` minus `plan_paid_amount`, rounded half up to two decimal places
        and floored at 0.00."

        Design: Corner/calculations/primary_claim_payment_capped_by_the_annual_maximum
        """
        ctx = _single_primary_coverage_case(
            "Wojtek Ilori", "1946-12-24", "555-1021", annual_maximum=400.00
        )
        fx.submit_claim(ctx["claim"]["id"])

        paid = validate_success(
            api.post_claim_payment(
                ctx["claim"]["id"], {"adjudication_outcome": "PAID"}, front_office_headers
            ),
            200,
        )

        assert_money(paid["allowed_amount"], 1200.00, "Claim.allowed_amount")
        assert_money(paid["primary_paid_amount"], 400.00, "Claim.primary_paid_amount")
        assert_money(paid["plan_paid_amount"], 400.00, "Claim.plan_paid_amount")
        assert_money(
            paid["patient_responsibility_amount"], 800.00, "Claim.patient_responsibility_amount"
        )
        assert paid["adjudication_status"] == "CLOSED"
        coverage = fx.read_coverage(ctx["coverage"]["id"])
        assert_money(coverage["benefit_used_ytd"], 400.00, "benefit_used_ytd")
        assert_money(coverage["benefit_remaining"], 0.00, "benefit_remaining")

    def test_a_claim_submitted_inside_the_waiting_period_is_refused(self, api, front_office_headers):
        """PRD §3.8: "1. **Waiting period.** The logical clock must be at or after the
        primary coverage's `effective_date` plus its `waiting_period_days` days;
        earlier is `ERR_WAITING_PERIOD`. On a coverage left at its default of 180 days,
        a claim submitted 179 days after enrolment fails and one submitted on day 180
        passes."

        Design: Corner/validations/claim_submitted_inside_the_waiting_period_is_rejected
        """
        ctx = _single_primary_coverage_case(
            "Goran Petrov", "1951-11-03", "555-1031",
            effective="2026-04-01T00:00:00Z", waiting_period_days=180,
        )

        refused = api.submit_claim(ctx["claim"]["id"], front_office_headers)
        validate_error(refused, ApiErrorId.ERR_WAITING_PERIOD.value, 422)

        parked = fx.read_claim(ctx["claim"]["id"])
        assert parked["adjudication_status"] == "DRAFT"
        assert parked["submitted_at"] is None

        fx.set_clock("2026-09-28T00:00:00Z")
        submitted = validate_success(
            api.submit_claim(ctx["claim"]["id"], front_office_headers), 200
        )
        assert submitted["adjudication_status"] == "SUBMITTED_PRIMARY"

    def test_a_claim_against_an_exhausted_annual_maximum_is_refused(self, api, front_office_headers):
        """PRD §3.8: "4. **Annual maximum.** The primary coverage's
        `benefit_remaining` must be strictly greater than 0.00; a coverage at exactly
        0.00 yields `ERR_ANNUAL_MAX_EXHAUSTED`."
        PRD §2.10: "**Rung 31 — annual maximum.** The coverage the current submission
        targets has `benefit_remaining` strictly greater than 0.00. Failure:
        `ERR_ANNUAL_MAX_EXHAUSTED`, HTTP 422."

        Design: Corner/validations/claim_submitted_against_an_exhausted_annual_maximum_is_rejected
        """
        ctx = _single_primary_coverage_case(
            "Hedda Lindroos", "1949-12-04", "555-1032", annual_maximum=200.00
        )
        fx.submit_claim(ctx["claim"]["id"])
        fx.post_claim_payment(ctx["claim"]["id"], "PAID")

        second_case = fx.open_case(ctx["patient"]["id"], "FLEXIBLE_PARTIAL")
        fx.add_arch(second_case["id"], "MAXILLARY")
        fx.complete_exam(second_case["id"])
        second_claim = fx.open_claim(second_case["id"], ctx["coverage"]["id"])

        coverage = fx.read_coverage(ctx["coverage"]["id"])
        assert_money(coverage["benefit_used_ytd"], 200.00, "benefit_used_ytd")
        assert_money(coverage["benefit_remaining"], 0.00, "benefit_remaining")

        response = api.submit_claim(second_claim["id"], front_office_headers)
        validate_error(response, ApiErrorId.ERR_ANNUAL_MAX_EXHAUSTED.value, 422)
        assert fx.read_claim(second_claim["id"])["adjudication_status"] == "DRAFT"

    def test_a_prior_appliance_blocks_the_second_cases_claim_but_not_its_own(self, api, front_office_headers):
        """PRD §3.8: "2. **Replacement frequency.** Consider the appliances belonging
        to this patient through cases **other than** this claim's own case. When that
        set is non-empty, the logical clock must be at or after the greatest
        `replacement_eligible_date` across it; earlier is `ERR_FREQUENCY_LIMIT`."
        PRD §3.6: "`replacement_eligible_date` is `frequency_anchor_at` plus 60
        calendar months, keeping the day-of-month and clamping to the last day of a
        shorter target month."

        Design: Corner/validations/replacement_frequency_limit_blocks_a_second_cases_claim
        """
        ctx = fx.setup_delivered_prosthesis(
            patient_overrides={
                "full_name": "Ivo Marchetti", "date_of_birth": "1943-01-05", "phone": "555-1033"
            },
            coverage_overrides={
                "carrier_name": "Meridian Dental",
                "rank": "PRIMARY",
                "effective_date": "2024-01-01T00:00:00Z",
                "annual_maximum_amount": 1500.00,
                "coinsurance_major_rate": 0.50,
            },
        )
        assert_same_instant(
            ctx["prosthesis"]["replacement_eligible_date"],
            "2031-05-01T00:00:00.000Z",
            "Prosthesis.replacement_eligible_date",
        )

        second_case = fx.open_case(ctx["patient"]["id"], "FLEXIBLE_PARTIAL")
        fx.add_arch(second_case["id"], "MANDIBULAR")
        fx.complete_exam(second_case["id"])
        second_claim = fx.open_claim(second_case["id"], ctx["coverage"]["id"])

        response = api.submit_claim(second_claim["id"], front_office_headers)
        validate_error(response, ApiErrorId.ERR_FREQUENCY_LIMIT.value, 422)
        assert fx.read_claim(second_claim["id"])["adjudication_status"] == "DRAFT"

        own_claims = fx.claims_of(ctx["case"]["id"])
        assert len(own_claims) == 1
        own = validate_success(api.submit_claim(own_claims[0]["id"], front_office_headers), 200)
        assert own["adjudication_status"] == "SUBMITTED_PRIMARY", (
            "the case's own prosthesis is excluded from the prior set"
        )
