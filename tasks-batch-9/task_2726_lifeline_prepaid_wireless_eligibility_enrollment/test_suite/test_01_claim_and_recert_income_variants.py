"""Dual-variant arithmetic: provisional versus final claim pricing, and the two income readings."""

from test_helpers import (
    ApiErrorId,
    assert_date_component,
    assert_instant,
    assert_reimbursement_claim,
    expected_support_line,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)

SERVICE_MONTH = "2026-06"
DRAFT_INSTANT = "2026-06-16T00:00:00Z"
FILE_INSTANT = "2026-07-02T00:00:00Z"


def _carrier_with_two_benefits(api):
    """A carrier holding one long-running VOICE benefit and one that starts late in the month."""
    fx.set_clock(api, DRAFT_INSTANT)
    provider = fx.register_provider(api, licensed_state_codes=["TX", "NM"])

    address_one = fx.register_distinct_address(api, 1)
    applicant_one = fx.eligible_applicant(api, address_one["id"])
    early_benefit = fx.enroll(
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
    late_benefit = fx.enroll(
        api,
        provider,
        applicant_two["subscriber"],
        applicant_two["check"],
        address_two,
        service_type="BROADBAND",
        benefit_start_date="2026-06-21T00:00:00Z",
    )
    return {
        "provider": provider,
        "early_benefit": early_benefit,
        "late_benefit": late_benefit,
    }


def test_draft_prices_only_the_month_so_far_and_filing_reprices_the_whole_month(api):
    """The provisional snapshot and the final repricing must disagree on identical rows.

    PRD: "The two pricings diverge substantially, and `variance_cents`, written at file
    time as `final_amount_cents` minus `provisional_amount_cents`, is the observable
    difference."

    Design: Difficulty/dual_variant_calc/claim_provisional_vs_final_support_diverges_on_reimbursement_claim
    """
    context = _carrier_with_two_benefits(api)
    provider = context["provider"]
    agent = fx.provider_headers(provider)

    draft = validate_success(
        api.create_claim(
            f.claim_payload(
                provider_id=provider["id"],
                service_month=SERVICE_MONTH,
                expected_provider_version=fx.provider_version(api, provider["id"]),
            ),
            agent,
        ),
        201,
    )
    assert_reimbursement_claim(draft)
    assert draft["status"] == "DRAFT", f"a new claim is born DRAFT, got {draft['status']}"
    assert draft["provisional_amount_cents"] == expected_support_line(925, 16, 30) == 493, (
        "the provisional pass prices 16 of 30 days for the only started benefit"
    )
    assert draft["covered_enrollment_count"] == 1, (
        "the benefit starting after the draft instant is not yet covered"
    )
    assert draft["final_amount_cents"] == 0, "final_amount_cents initialises to 0"
    assert draft["variance_cents"] == 0, "variance_cents initialises to 0"

    fx.set_clock(api, FILE_INSTANT)
    filed = validate_success(
        api.file_claim(draft["id"], f.claim_file_payload("OFFICER-9"), agent)
    )
    assert filed["status"] == "FILED", f"filing moves the claim to FILED, got {filed['status']}"
    assert filed["provisional_amount_cents"] == 493, "the provisional figure is not rewritten"
    assert filed["final_amount_cents"] == 2158, (
        "the final pass earns 925 for the full-month benefit and 1233 for the 10-day tribal broadband line"
    )
    assert filed["covered_enrollment_count"] == 2, "the final pass covers both benefits"
    assert filed["variance_cents"] == 1665, (
        "variance_cents is final 2158 minus provisional 493"
    )
    assert filed["provisional_amount_cents"] != filed["final_amount_cents"], (
        "the two variants must be numerically distinct on these rows"
    )
    assert_instant(filed["filed_at"], FILE_INSTANT, "filed_at")
    assert filed["certifying_officer_ref"] == "OFFICER-9"


def test_carrier_ledger_absorbs_the_final_variant_when_the_claim_is_filed(api):
    """Filing pushes the final figure, not the provisional snapshot, into the carrier ledger.

    PRD: "The carrier's `claim_gross_cents`, `net_reimbursed_cents` and `open_claim_count`
    are then recomputed and its `version` advances by one."

    Design: Difficulty/dual_variant_calc/claim_provisional_vs_final_support_diverges_on_reimbursement_claim
    """
    context = _carrier_with_two_benefits(api)
    provider = context["provider"]
    agent = fx.provider_headers(provider)

    before_draft = fx.refresh_provider(api, provider["id"])
    assert before_draft["open_claim_count"] == 0, "no claim exists yet"

    draft = fx.draft_claim(api, provider, SERVICE_MONTH)
    after_draft = fx.refresh_provider(api, provider["id"])
    assert after_draft["open_claim_count"] == 1, "a DRAFT claim is an open claim"
    assert after_draft["claim_gross_cents"] == 0, (
        "a draft contributes nothing to claim_gross_cents"
    )
    assert after_draft["version"] > before_draft["version"], (
        "drafting a claim advances the carrier version"
    )

    fx.set_clock(api, FILE_INSTANT)
    validate_success(api.file_claim(draft["id"], f.claim_file_payload(), agent))

    after_file = fx.refresh_provider(api, provider["id"])
    assert after_file["claim_gross_cents"] == 2158, (
        "the ledger records the final variant, not the 493-cent provisional snapshot"
    )
    assert after_file["recouped_cents"] == 0, "nothing has been recouped"
    assert after_file["net_reimbursed_cents"] == 2158, (
        "net_reimbursed_cents is the gross less recoupments"
    )
    assert after_file["open_claim_count"] == 1, "a FILED claim is still an open claim"
    assert after_file["version"] > after_draft["version"], (
        "filing advances the carrier version again"
    )


def _noticed_benefit_and_unscreened_applicant(api):
    """One benefit carried to a NOTICED recertification, plus an applicant on the same income."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    provider = fx.register_provider(api)
    address = fx.register_distinct_address(api, 1)
    applicant = fx.eligible_applicant(api, address["id"])
    enrollment = fx.enroll(
        api, provider, applicant["subscriber"], applicant["check"], address
    )

    other_address = fx.register_distinct_address(api, 2)
    unscreened = fx.create_subscriber(
        api,
        other_address["id"],
        household_size=4,
        annual_income_cents=4400000,
        last_3mo_income_cents=1050000,
        tribal_lands_flag=False,
    )

    fx.set_clock(api, "2027-06-02T00:00:00Z")
    fx.record_usage(api, enrollment["id"], fx.provider_headers(provider))
    fx.sweep(api, provider["id"])
    return {
        "provider": provider,
        "subscriber": applicant["subscriber"],
        "enrollment": fx.refresh_enrollment(api, enrollment["id"]),
        "unscreened": unscreened,
    }


def test_recertification_annualizes_the_trailing_quarter_and_qualifies(api):
    """The trailing-quarter reading passes a household the strict reading would reject.

    PRD: "Initial screening takes `annual_income_cents` verbatim; recertification instead
    annualizes the trailing quarter, computing `recert_evaluated_income_cents` as
    `last_3mo_income_cents` multiplied by 4, rounded half up to a whole cent."

    Design: Difficulty/dual_variant_calc/recert_income_annualized_vs_three_month_averaged_on_subscriber
    """
    context = _noticed_benefit_and_unscreened_applicant(api)
    enrollment = context["enrollment"]
    assert enrollment["recert_status"] == "NOTICED", (
        f"the sweep should have issued the notice, got {enrollment['recert_status']}"
    )

    responded = validate_success(
        api.recertify(
            enrollment["id"],
            f.recertify_payload(
                household_size=4,
                annual_income_cents=4400000,
                last_3mo_income_cents=1050000,
                attested_qualifying_benefit="NONE",
                attestation_ref="ATT-1",
            ),
            fx.subscriber_headers(context["subscriber"]),
        )
    )

    assert responded["recert_evaluated_income_cents"] == 4200000, (
        "1050000 times 4 is the annualized trailing quarter"
    )
    assert responded["recert_income_threshold_cents"] == 4341600, (
        "the threshold snapshot is taken with the attested household size"
    )
    assert responded["recert_evaluated_income_cents"] <= responded["recert_income_threshold_cents"], (
        "the attestation qualifies on the income arm"
    )
    assert responded["recert_status"] == "NOT_DUE", (
        f"the eligible arm returns the dimension to NOT_DUE, got {responded['recert_status']}"
    )
    assert responded["benefit_status"] == "ACTIVE", "the benefit survives an eligible recert"
    assert_instant(
        responded["recert_last_responded_at"],
        "2027-06-02T00:00:00Z",
        "recert_last_responded_at",
    )
    assert responded["recert_notice_sent_at"] is None, "the notice fields are cleared"
    assert responded["recert_response_deadline_at"] is None, "the notice fields are cleared"
    assert_date_component(responded["recert_due_date"], "2028-06-01", "recert_due_date")

    applicant = fx.refresh_subscriber(api, context["subscriber"]["id"])
    assert applicant["annual_income_cents"] == 4400000, (
        "the attestation overwrites the applicant's annual income"
    )
    assert applicant["income_threshold_cents"] == 4341600
    assert applicant["status"] == "ENROLLED", "the applicant keeps the benefit"


def test_initial_screening_reads_annual_income_verbatim_and_rejects_the_same_household(api):
    """The identical figure the recert arm accepted fails the strict annualized reading.

    PRD: "Initial screening takes `annual_income_cents` verbatim; recertification instead
    annualizes the trailing quarter, computing `recert_evaluated_income_cents` as
    `last_3mo_income_cents` multiplied by 4, rounded half up to a whole cent."

    Design: Difficulty/dual_variant_calc/recert_income_annualized_vs_three_month_averaged_on_subscriber
    """
    context = _noticed_benefit_and_unscreened_applicant(api)
    unscreened = context["unscreened"]
    assert unscreened["annual_income_cents"] == 4400000
    assert unscreened["income_threshold_cents"] == 4341600

    response = api.create_eligibility_check(
        unscreened["id"],
        f.eligibility_check_payload(claimed_basis="INCOME", proof_document_ref="DOC-B2"),
        fx.provider_headers(context["provider"]),
    )
    validate_error(response, ApiErrorId.SUBSCRIBER_INCOME_ABOVE_THRESHOLD.value, 409)

    unchanged = fx.refresh_subscriber(api, unscreened["id"])
    assert unchanged["status"] == "PROSPECT", (
        f"a refused screening leaves the applicant PROSPECT, got {unchanged['status']}"
    )
