"""Composed money formulas: per-line rounding order, the penalty tier source, and the FPG clamps."""

from test_helpers import (
    assert_de_enrollment_cascade,
    assert_ledger_tuple,
    assert_subscriber,
    expected_income_threshold,
    expected_recoupment,
    expected_support_line,
    factories as f,
    fixtures as fx,
    validate_success,
)

AUDITOR_ADJUDICATOR_REF = "AUD-2"


def _two_identical_voice_benefits(api):
    """Two identical non-tribal VOICE benefits that each earn a fractional line."""
    fx.set_clock(api, "2026-06-20T00:00:00Z")
    provider = fx.register_provider(api)
    benefits = []
    for index in (1, 2):
        address = fx.register_distinct_address(api, index)
        applicant = fx.eligible_applicant(api, address["id"])
        benefits.append(
            fx.enroll(
                api,
                provider,
                applicant["subscriber"],
                applicant["check"],
                address,
                service_type="VOICE",
                benefit_start_date="2026-06-15T00:00:00Z",
            )
        )
    return provider, benefits


def test_support_lines_are_rounded_individually_before_they_are_summed(api):
    """Two 493.333 cent lines must total 986, never the sum-then-round 987.

    PRD: "Every line is rounded to an integer *first*, and the integer lines are *then*
    summed."

    Design: Difficulty/combinatorial_formula/claim_line_rounding_order_pinned_per_line_not_per_claim
    """
    provider, _benefits = _two_identical_voice_benefits(api)
    draft = fx.draft_claim(api, provider, "2026-06")

    fx.set_clock(api, "2026-07-02T00:00:00Z")
    filed = validate_success(
        api.file_claim(
            draft["id"], f.claim_file_payload("OFFICER-4"), fx.provider_headers(provider)
        )
    )

    assert expected_support_line(925, 16, 30) == 493, (
        "one 16 of 30 day non-tribal voice line rounds to 493"
    )
    assert filed["final_amount_cents"] == 986, (
        f"expected 493 + 493 = 986, got {filed['final_amount_cents']}"
    )
    assert filed["final_amount_cents"] != 987, (
        "987 is the forbidden sum-then-round result"
    )
    assert filed["covered_enrollment_count"] == 2, "both benefits contributed a line"


def test_provisional_pass_rounds_per_line_and_variance_reports_the_gap(api):
    """The mid-month snapshot prices six days per line and the variance reports the gap.

    PRD: "Each selected benefit then contributes a line equal to the monthly rate
    multiplied by its support days, divided by the number of calendar days in the service
    month, rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/claim_line_rounding_order_pinned_per_line_not_per_claim
    """
    provider, _benefits = _two_identical_voice_benefits(api)
    draft = fx.draft_claim(api, provider, "2026-06")

    assert draft["provisional_amount_cents"] == 370, (
        f"expected 185 + 185 = 370 for six support days each, got {draft['provisional_amount_cents']}"
    )
    assert draft["covered_enrollment_count"] == 2

    fx.set_clock(api, "2026-07-02T00:00:00Z")
    filed = validate_success(
        api.file_claim(
            draft["id"], f.claim_file_payload("OFFICER-4"), fx.provider_headers(provider)
        )
    )
    assert filed["variance_cents"] == 616, (
        f"expected final 986 minus provisional 370, got {filed['variance_cents']}"
    )

    carrier = fx.refresh_provider(api, provider["id"])
    assert_ledger_tuple(carrier, 986, 0, 986, False)


def _filed_claim_worth_2158(api):
    """The 2158 cent claim: a full-month voice line of 925 and a ten day tribal line of 1233."""
    fx.set_clock(api, "2026-06-16T00:00:00Z")
    provider = fx.register_provider(api, licensed_state_codes=["TX", "NM"])

    address_one = fx.register_distinct_address(api, 1)
    applicant_one = fx.eligible_applicant(api, address_one["id"])
    voice_benefit = fx.enroll(
        api,
        provider,
        applicant_one["subscriber"],
        applicant_one["check"],
        address_one,
        service_type="VOICE",
        benefit_start_date="2026-01-10T00:00:00Z",
    )

    address_two = fx.register_distinct_address(api, 2)
    applicant_two = fx.eligible_applicant(
        api, address_two["id"], subscriber_overrides={"tribal_lands_flag": True}
    )
    fx.enroll(
        api,
        provider,
        applicant_two["subscriber"],
        applicant_two["check"],
        address_two,
        service_type="BROADBAND",
        benefit_start_date="2026-06-21T00:00:00Z",
    )

    draft = fx.draft_claim(api, provider, "2026-06")
    fx.set_clock(api, "2026-07-02T00:00:00Z")
    filed = fx.file_claim(api, draft["id"], provider, "OFFICER-9")
    assert filed["final_amount_cents"] == 2158, (
        f"the fixture must reach 2158 cents, got {filed['final_amount_cents']}"
    )
    return {
        "provider": provider,
        "claim": filed,
        "voice_benefit": voice_benefit,
        "voice_subscriber": applicant_one["subscriber"],
    }


def test_penalty_tier_is_selected_from_the_extrapolated_error_not_the_claim_total(api):
    """A 1079 cent extrapolation takes the middle tier even though the claim total is above 1500.

    PRD: "Step three selects the penalty rate **from the extrapolated figure**, not from
    `final_amount_cents`: 0.05 while the extrapolated error is below 500 cents, 0.10 while
    it is at least 500 and below 1500, and 0.20 once it reaches 1500."

    Design: Difficulty/combinatorial_formula/recoupment_penalty_tier_read_from_extrapolated_not_from_final_amount
    """
    context = _filed_claim_worth_2158(api)
    samples = fx.draw_samples(api, context["claim"]["id"], sample_size=2)
    assert len(samples) == 2, f"expected two drawn samples, got {len(samples)}"

    first, second = samples[0], samples[1]
    assert first["selection_rank"] == 1
    assert first["enrollment_id"] == context["voice_benefit"]["id"], (
        "the earlier starting benefit ranks first when both risk scores are 0"
    )
    assert first["claimed_line_cents"] == 925

    adjudicated = fx.adjudicate(
        api,
        first["id"],
        finding="INELIGIBLE_SUBSCRIBER",
        finding_note="no qualifying benefit on file",
    )
    assert adjudicated["status"] == "ADJUDICATED_FAIL"
    assert adjudicated["disallowed_support_cents"] == 925, (
        "a failed sample disallows its own claimed line"
    )
    assert fx.refresh_sample(api, second["id"])["status"] == "DRAWN", (
        "the untouched sample is still awaiting adjudication"
    )

    expected = expected_recoupment(2158, 1, 2)
    assert expected["extrapolated_cents"] == 1079
    assert expected["penalty_rate"] == 0.10

    claim = fx.refresh_claim(api, context["claim"]["id"])
    assert claim["audit_sample_count"] == 2
    assert claim["failed_sample_count"] == 1
    assert claim["penalty_cents"] == 108, (
        f"expected 1079 times 0.10 rounded half up, got {claim['penalty_cents']}"
    )
    assert claim["recoupment_amount_cents"] == 1187, (
        f"expected 1079 plus 108, got {claim['recoupment_amount_cents']}"
    )
    assert claim["recoupment_amount_cents"] != 1295, (
        "1295 is what reading the 0.20 tier off the 2158 cent claim total would give"
    )
    assert claim["net_payable_cents"] == 971, (
        f"expected 2158 minus 1187, got {claim['net_payable_cents']}"
    )
    assert claim["status"] == "AUDIT_FAILED"


def test_failed_adjudication_pushes_the_recoupment_into_the_carrier_ledger(api):
    """The clawback lands on the ledger and the sampled benefit stops.

    PRD: "Carrier ledger writes always use the **gross** `final_amount_cents` for
    `claim_gross_cents` and `recoupment_amount_cents` for `recouped_cents`."

    Design: Difficulty/combinatorial_formula/recoupment_penalty_tier_read_from_extrapolated_not_from_final_amount
    """
    context = _filed_claim_worth_2158(api)
    samples = fx.draw_samples(api, context["claim"]["id"], sample_size=2)
    fx.adjudicate(api, samples[0]["id"], finding="INELIGIBLE_SUBSCRIBER")

    carrier = fx.refresh_provider(api, context["provider"]["id"])
    assert_ledger_tuple(carrier, 2158, 1187, 971, True)

    stopped = fx.refresh_enrollment(api, context["voice_benefit"]["id"])
    assert_de_enrollment_cascade(
        stopped,
        reason="AUDIT_INELIGIBLE",
        de_enrolled_at="2026-07-02T00:00:00Z",
        by_ref=AUDITOR_ADJUDICATOR_REF,
    )


def test_income_threshold_composes_household_size_the_tribal_multiplier_and_two_clamps(api):
    """Five households pin the guideline, both multipliers and the ceiling clamp at once.

    PRD: "First, a poverty-guideline figure is built as a base annual amount of 1560000
    cents plus 552000 cents for each household member beyond the first; a household of one
    takes the base alone, a household of four takes the base plus three increments."

    Design: Difficulty/combinatorial_formula/fpg_threshold_combines_household_size_tribal_flag_and_two_clamps
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    fx.register_provider(api)

    cases = [
        (1, False, 2106000),
        (4, False, 4341600),
        (4, True, 4824000),
        (8, True, 6000000),
        (9, False, 6000000),
    ]
    for index, (household_size, tribal, expected) in enumerate(cases, start=1):
        address = fx.register_distinct_address(api, index)
        subscriber = fx.create_subscriber(
            api,
            address["id"],
            household_size=household_size,
            annual_income_cents=900000,
            tribal_lands_flag=tribal,
        )
        assert_subscriber(subscriber)
        assert subscriber["income_threshold_cents"] == expected, (
            f"household of {household_size} with tribal_lands_flag {tribal} must record "
            f"{expected}, got {subscriber['income_threshold_cents']}"
        )
        assert expected_income_threshold(household_size, tribal) == expected
        assert subscriber["status"] == "PROSPECT"
        assert subscriber["eligibility_basis"] == "NONE"


def test_program_ceiling_collapses_two_different_households_onto_one_threshold(api):
    """Two households whose raw guideline products differ report the same clamped threshold.

    PRD: "Fourth, the rounded figure is clamped, **ceiling first and floor second**: it is
    reduced to the program income ceiling of 6000000 cents if it exceeds it, and the result
    of that reduction is then raised to the program minimum of 2106000 cents if it falls
    below it."

    Design: Difficulty/combinatorial_formula/fpg_threshold_combines_household_size_tribal_flag_and_two_clamps
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")

    tribal_address = fx.register_distinct_address(api, 11)
    tribal_household = fx.create_subscriber(
        api,
        tribal_address["id"],
        household_size=8,
        annual_income_cents=900000,
        tribal_lands_flag=True,
    )

    standard_address = fx.register_distinct_address(api, 12)
    standard_household = fx.create_subscriber(
        api,
        standard_address["id"],
        household_size=9,
        annual_income_cents=900000,
        tribal_lands_flag=False,
    )

    unclamped_tribal = int((1560000 + 552000 * 7) * 1.5)
    unclamped_standard = int((1560000 + 552000 * 8) * 1.35)
    assert unclamped_tribal != unclamped_standard, (
        "the two households differ before the clamp is applied"
    )

    assert tribal_household["income_threshold_cents"] == 6000000
    assert standard_household["income_threshold_cents"] == 6000000
    assert (
        tribal_household["income_threshold_cents"]
        == standard_household["income_threshold_cents"]
    ), "the ceiling collapses both households onto the same threshold"
