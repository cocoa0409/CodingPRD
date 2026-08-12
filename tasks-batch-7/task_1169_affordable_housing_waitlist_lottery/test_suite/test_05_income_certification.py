"""Income certification: gating, the documentation cycle, pinned per-source
rounding, the inclusive income ceiling, and check ordering at CERTIFY."""
from test_helpers import (
    ApiErrorId, fixtures, get_success_data, make_applicant_headers,
    make_compliance_officer_headers, validate_error, validate_success,
)

OFFICER = fixtures.OFFICER


def _verified_pipeline(api, household_size=2, income=3_000_000,
                       ami_rows=((2, "AMI_50", 4_000_000),)):
    """Property with AMI rows + OPEN campaign + one VERIFIED application."""
    prop = fixtures.new_property(api)
    for hh, tier, limit in ami_rows:
        fixtures.new_ami_limit(api, prop["id"], household_size=hh,
                               ami_tier=tier, annual_limit_cents=limit)
    campaign = fixtures.new_open_campaign(api, prop["id"])
    applicant = fixtures.new_applicant(api)
    application = fixtures.submit_application(
        api, campaign["id"], applicant["id"], household_size=household_size,
        self_reported_annual_income_cents=income)
    return prop, campaign, applicant, application


def _cert_at_docs_received(api, application_id, applicant_id, sources,
                           required_docs=("SALARY",)):
    cert = fixtures.new_income_certification(api, application_id)
    fixtures.advance_certification(api, cert["id"], "REQUEST_DOCS", OFFICER,
                                   required_docs=list(required_docs))
    fixtures.advance_certification(api, cert["id"], "SUBMIT_DOCS",
                                   make_applicant_headers(applicant_id),
                                   income_sources=sources)
    return cert


def test_cert_create_rejected_while_application_submitted(api):
    """PRD §3.4: "A `ComplianceOfficer` opens an income certification against
    an `application_id`; the application must be `VERIFIED`, otherwise the
    attempt is rejected with `ERR_APPLICATION_NOT_VERIFIED`".

    Design: Difficulty/cross_entity_state_dependency/income_certification_gated_by_application_verified
    """
    _, _, _, application = _verified_pipeline(api)
    resp = api.create_income_certification(
        {"application_id": application["id"]}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_VERIFIED)


def test_cert_create_succeeds_once_application_verified(api):
    """PRD §3.4: "the application must be `VERIFIED`, otherwise the attempt
    is rejected with `ERR_APPLICATION_NOT_VERIFIED`, and at most one
    certification not in terminal `DENIED` status may exist per application".
    PRD §3.4: "The certification opens in `INITIATED`."

    Design: Difficulty/cross_entity_state_dependency/income_certification_gated_by_application_verified
    """
    _, _, _, application = _verified_pipeline(api)
    resp = api.create_income_certification(
        {"application_id": application["id"]}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_VERIFIED)
    fixtures.verify_application(api, application["id"])
    cert = validate_success(api.create_income_certification(
        {"application_id": application["id"]}, OFFICER), expected_status=201)
    assert cert["status"] == "INITIATED"


def _run_divergence_scenario(api):
    """Self-reported 2800000 (provisional screen) versus a documented SALARY
    source of 300020 cents x 12 (certified annualization)."""
    prop, campaign, applicant, application = _verified_pipeline(
        api, income=2_800_000)
    fixtures.verify_application(api, application["id"])
    cert = _cert_at_docs_received(
        api, application["id"], applicant["id"],
        sources=[fixtures.income_source(amount_per_period_cents=300020,
                                        periods_per_year=12)])
    return application, cert


def test_provisional_and_certified_variants_diverge(api):
    """PRD §2.7: "Income certification annualizes each income source to whole
    dollars first, rounding each source half-up to a whole dollar before any
    summation takes place, and only then sums the per-source figures and
    restates the total in integer cents; the provisional screen at application
    submit performs no rounding at all, comparing the declared integer-cent
    figure directly."

    Design: Difficulty/dual_variant_calc/provisional_vs_certified_income_divergence
    """
    application, cert = _run_divergence_scenario(api)
    certified = fixtures.advance_certification(api, cert["id"], "CERTIFY",
                                               OFFICER)
    assert certified["certified_annual_income_cents"] == 3600200, (
        "300020 x 12 = 3600240 cents = $36002.40, rounded half-up to 36002 "
        "whole dollars, restated as 3600200 cents"
    )
    fetched = get_success_data(api.get_application(application["id"],
                                                   fixtures.CLERK))
    assert fetched["provisional_determination"] == "PROVISIONALLY_ELIGIBLE"
    # The two valid algorithms diverge for the same household.
    assert certified["certified_annual_income_cents"] != 2800000


def test_certified_variant_ami_percentage_and_determination(api):
    """PRD §3.4: "`ami_percentage_bp` records the certified income as a share
    of the tier limit in basis points: the certified cents are multiplied by
    ten thousand, divided by the limit, and rounded half-up to an integer."
    PRD §3.4: "A successful certification stamps `determination` as
    `ELIGIBLE`".

    Design: Difficulty/dual_variant_calc/provisional_vs_certified_income_divergence
    """
    _, cert = _run_divergence_scenario(api)
    certified = fixtures.advance_certification(api, cert["id"], "CERTIFY",
                                               OFFICER)
    # round_half_up(3600200 x 10000 / 4000000) = round_half_up(9000.5) = 9001
    assert certified["ami_percentage_bp"] == 9001
    assert certified["determination"] == "ELIGIBLE"


def _run_two_source_scenario(api):
    """The PRD §3.4 worked example: SALARY 100020c x 12 + BENEFITS 50020c x 12."""
    _, _, applicant, application = _verified_pipeline(api,
                                                      income=1_800_000)
    fixtures.verify_application(api, application["id"])
    cert = _cert_at_docs_received(
        api, application["id"], applicant["id"],
        sources=[fixtures.income_source(source_type="SALARY",
                                        amount_per_period_cents=100020,
                                        periods_per_year=12),
                 fixtures.income_source(source_type="BENEFITS",
                                        amount_per_period_cents=50020,
                                        periods_per_year=12)],
        required_docs=("SALARY", "BENEFITS"))
    return cert


def test_per_source_rounding_then_sum_order(api):
    """PRD §3.4: "Consider two sources, one paying 100020 cents per period
    across 12 periods and another paying 50020 cents across 12 periods: the
    first annualizes to 12002.40 dollars and rounds to 12002 whole dollars,
    the second to 6002.40 dollars and rounds to 6002, and the certified total
    is 18004 dollars, stored as 1800400 cents. Summing the exact amounts first
    and rounding once would produce 18005 dollars — that is not the specified
    behavior."

    Design: Difficulty/combinatorial_formula/per_source_rounding_then_sum_order
    """
    cert = _run_two_source_scenario(api)
    certified = fixtures.advance_certification(api, cert["id"], "CERTIFY",
                                               OFFICER)
    assert certified["certified_annual_income_cents"] == 1800400
    assert certified["certified_annual_income_cents"] != 1800500, (
        "the sum-then-round order is not the specified behavior"
    )


def test_per_source_rounding_drives_ami_percentage(api):
    """PRD §3.4: "the certified cents are multiplied by ten thousand, divided
    by the limit, and rounded half-up to an integer. A successful
    certification stamps `determination` as `ELIGIBLE`".

    Design: Difficulty/combinatorial_formula/per_source_rounding_then_sum_order
    """
    cert = _run_two_source_scenario(api)
    certified = fixtures.advance_certification(api, cert["id"], "CERTIFY",
                                               OFFICER)
    # round_half_up(1800400 x 10000 / 4000000) = 4501
    assert certified["ami_percentage_bp"] == 4501
    assert certified["determination"] == "ELIGIBLE"


def test_income_exactly_at_ami_limit_is_eligible(api):
    """PRD §3.4: "Fourth, the income ceiling: the certified income must not
    exceed that row's `annual_limit_cents` — the boundary is inclusive, so
    income exactly equal to the limit passes — else `ERR_OVER_INCOME`."

    Design: Difficulty/boundary_precision_check/income_exactly_at_ami_limit_is_eligible
    """
    _, _, applicant, application = _verified_pipeline(api, income=3_999_900)
    fixtures.verify_application(api, application["id"])
    cert = _cert_at_docs_received(
        api, application["id"], applicant["id"],
        sources=[fixtures.income_source(amount_per_period_cents=333333,
                                        periods_per_year=12)])
    certified = fixtures.advance_certification(api, cert["id"], "CERTIFY",
                                               OFFICER)
    # 333333 x 12 = 3999996 cents = $39999.96 -> round_half_up -> 40000
    # whole dollars -> 4000000 cents, exactly equal to the limit.
    assert certified["certified_annual_income_cents"] == 4000000
    assert certified["determination"] == "ELIGIBLE"


def test_income_exactly_at_limit_yields_full_ami_percentage(api):
    """PRD §3.4: "the certified cents are multiplied by ten thousand, divided
    by the limit, and rounded half-up to an integer."

    Design: Difficulty/boundary_precision_check/income_exactly_at_ami_limit_is_eligible
    """
    _, _, applicant, application = _verified_pipeline(api, income=3_999_900)
    fixtures.verify_application(api, application["id"])
    cert = _cert_at_docs_received(
        api, application["id"], applicant["id"],
        sources=[fixtures.income_source(amount_per_period_cents=333333,
                                        periods_per_year=12)])
    certified = fixtures.advance_certification(api, cert["id"], "CERTIFY",
                                               OFFICER)
    assert certified["ami_percentage_bp"] == 10000, (
        "income exactly at the limit is 100.00% of the limit in basis points"
    )


def _run_segregated_over_income_scenario(api):
    """Lottery run sealed/executed/published by operator "shared-1"; a
    certification at DOCS_RECEIVED whose income (500000c x 12 = 6000000)
    exceeds the 4000000 limit. Returns (cert, applicant)."""
    prop = fixtures.new_property(api)
    fixtures.new_ami_limit(api, prop["id"])
    campaign = fixtures.new_open_campaign(api, prop["id"])
    applicant = fixtures.new_applicant(api, full_name="Jon J",
                                       email="j@x.com")
    application = fixtures.submit_application(api, campaign["id"],
                                              applicant["id"])
    fixtures.verify_application(api, application["id"])
    fixtures.close_campaign_at(api, campaign["id"])
    fixtures.run_published_lottery(api, campaign["id"], seed="SEED-SOD",
                                   admin_user="shared-1")
    cert = _cert_at_docs_received(
        api, application["id"], applicant["id"],
        sources=[fixtures.income_source(amount_per_period_cents=500000,
                                        periods_per_year=12)])
    return cert


def test_certify_segregated_and_over_income_safety_beats_fiscal(api):
    """PRD §3.4: "Certification is the decisive act, and its four checks are
    evaluated in a fixed order, so an earlier failure masks later ones. First,
    segregation of duties: the certifying officer's `X-User-ID` must not
    appear as `sealed_by`, `executed_by`, or `published_by` of any lottery run
    of the same campaign, else `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/priority_pair_validation_conflict/certify_segregated_and_over_income_safety_beats_fiscal
    """
    cert = _run_segregated_over_income_scenario(api)
    resp = api.advance_income_certification(
        cert["id"], {"action": "CERTIFY"},
        make_compliance_officer_headers("shared-1"))
    # Both the segregation violation and the income-ceiling violation hold;
    # the earlier (segregation) check masks the later (fiscal) one.
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


def test_certify_segregation_rejection_writes_nothing(api):
    """PRD §3.4: "Fourth, the income ceiling: the certified income must not
    exceed that row's `annual_limit_cents` — the boundary is inclusive, so
    income exactly equal to the limit passes — else `ERR_OVER_INCOME`."

    Design: Difficulty/priority_pair_validation_conflict/certify_segregated_and_over_income_safety_beats_fiscal
    """
    cert = _run_segregated_over_income_scenario(api)
    resp = api.advance_income_certification(
        cert["id"], {"action": "CERTIFY"},
        make_compliance_officer_headers("shared-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    fetched = get_success_data(api.get_income_certification(cert["id"],
                                                            OFFICER))
    assert fetched["status"] == "DOCS_RECEIVED", (
        "the rejected CERTIFY writes nothing"
    )
    # Control: an uninvolved officer's CERTIFY hits the fiscal wall, proving
    # the income violation was genuinely live in the first attempt.
    control = api.advance_income_certification(
        cert["id"], {"action": "CERTIFY"},
        make_compliance_officer_headers("co-1"))
    validate_error(control, ApiErrorId.ERR_OVER_INCOME)


def test_certify_over_income_rejected_cleanly(api):
    """PRD §3.4: "Fourth, the income ceiling: the certified income must not
    exceed that row's `annual_limit_cents` — the boundary is inclusive, so
    income exactly equal to the limit passes — else `ERR_OVER_INCOME`."

    Design: Corner/validations/certify_over_income_rejected_cleanly
    """
    _, _, applicant, application = _verified_pipeline(api)
    fixtures.verify_application(api, application["id"])
    cert = _cert_at_docs_received(
        api, application["id"], applicant["id"],
        sources=[fixtures.income_source(amount_per_period_cents=500000,
                                        periods_per_year=12)])
    resp = api.advance_income_certification(cert["id"], {"action": "CERTIFY"},
                                            OFFICER)
    validate_error(resp, ApiErrorId.ERR_OVER_INCOME)
    fetched = get_success_data(api.get_income_certification(cert["id"],
                                                            OFFICER))
    assert fetched["status"] == "DOCS_RECEIVED", (
        "6000000 > 4000000 strictly; the failed CERTIFY leaves the "
        "certification in DOCS_RECEIVED"
    )


def test_certify_missing_ami_row_returns_not_defined(api):
    """PRD §3.4: "Third, configuration: an AMI limit row must exist for the
    property, the application's `household_size`, and the campaign's
    `target_ami_tier`, else `ERR_AMI_LIMIT_NOT_DEFINED`." PRD §3.3: "if no
    such row exists the `provisional_determination` is `UNASSESSED`".

    Design: Corner/validations/certify_missing_ami_row_returns_not_defined
    """
    _, _, applicant, application = _verified_pipeline(api, household_size=3)
    assert application["provisional_determination"] == "UNASSESSED", (
        "no AMI row exists for household_size 3 at submit time"
    )
    fixtures.verify_application(api, application["id"])
    cert = _cert_at_docs_received(
        api, application["id"], applicant["id"],
        sources=[fixtures.income_source()])
    resp = api.advance_income_certification(cert["id"], {"action": "CERTIFY"},
                                            OFFICER)
    validate_error(resp, ApiErrorId.ERR_AMI_LIMIT_NOT_DEFINED)


def test_certify_with_missing_doc_coverage_returns_docs_incomplete(api):
    """PRD §3.4: "Second, documentation coverage: every source type named in
    `required_docs` must be covered by at least one submitted
    `income_sources` entry, else `ERR_CERT_DOCS_INCOMPLETE`." PRD §3.4: "If
    the paperwork is insufficient, the officer requests documents again — from
    `DOCS_RECEIVED` back to `DOCS_REQUESTED` — and the new `required_docs`
    list replaces the old one."

    Design: Corner/validations/certify_with_missing_doc_coverage_returns_docs_incomplete
    """
    _, _, applicant, application = _verified_pipeline(api)
    fixtures.verify_application(api, application["id"])
    cert = _cert_at_docs_received(
        api, application["id"], applicant["id"],
        sources=[fixtures.income_source(source_type="SALARY",
                                        amount_per_period_cents=250000,
                                        periods_per_year=12)],
        required_docs=("SALARY", "BENEFITS"))
    resp = api.advance_income_certification(cert["id"], {"action": "CERTIFY"},
                                            OFFICER)
    validate_error(resp, ApiErrorId.ERR_CERT_DOCS_INCOMPLETE)

    # Documentation review cycle: request again, submit the missing source.
    fixtures.advance_certification(api, cert["id"], "REQUEST_DOCS", OFFICER,
                                   required_docs=["SALARY", "BENEFITS"])
    fixtures.advance_certification(
        api, cert["id"], "SUBMIT_DOCS",
        make_applicant_headers(applicant["id"]),
        income_sources=[fixtures.income_source(source_type="BENEFITS",
                                               amount_per_period_cents=40000,
                                               periods_per_year=12)])
    certified = fixtures.advance_certification(api, cert["id"], "CERTIFY",
                                               OFFICER)
    assert certified["status"] == "CERTIFIED"
    # Sources are appended across submissions: 30000 + 4800 whole dollars.
    assert certified["certified_annual_income_cents"] == 3480000
