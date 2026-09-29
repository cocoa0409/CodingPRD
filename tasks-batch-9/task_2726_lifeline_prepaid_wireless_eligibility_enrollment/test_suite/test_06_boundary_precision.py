"""Boundary precision on three different metrics: idle days, collection cardinality, money equality."""

from test_helpers import (
    AUDITOR_DRAWER,
    PROGRAM_ADMIN,
    ApiErrorId,
    assert_eligibility_check,
    assert_instant,
    assert_instant_null,
    expected_income_threshold,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

BENEFIT_START = "2026-08-01T00:00:00Z"
IDLE_29_INSTANT = "2026-08-30T23:59:59Z"
IDLE_30_INSTANT = "2026-08-31T00:00:00Z"
CURE_DEADLINE = "2026-09-15T23:59:59.999Z"
PAST_CURE_INSTANT = "2026-09-16T00:00:00Z"


def _two_never_used_benefits(api):
    """Two benefits at two dwellings, both starting 2026-08-01 and never used."""
    fx.set_clock(api, BENEFIT_START)
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
                benefit_start_date=BENEFIT_START,
            )
        )
    return {
        "provider": provider,
        "agent": fx.provider_headers(provider),
        "first": benefits[0],
        "second": benefits[1],
    }


def test_the_idle_day_count_flags_at_thirty_and_not_at_twenty_nine(api):
    """One second before the thirtieth day nothing happens; at the day boundary both flag.

    PRD: "For a benefit that started at `2026-08-01T00:00:00Z` and has never been used, a
    sweep at `2026-08-30T23:59:59Z` computes 29 idle days and does not flag it, while a
    sweep at `2026-08-31T00:00:00Z` computes 30 and flags it with a `cure_deadline_at` of
    `2026-09-15T23:59:59.999Z`."

    Design: Difficulty/boundary_precision_check/non_usage_thirtieth_day_and_inclusive_cure_instant_boundaries
    """
    context = _two_never_used_benefits(api)

    fx.set_clock(api, IDLE_29_INSTANT)
    early = fx.sweep(api, context["provider"]["id"])
    assert early["non_usage_flagged_enrollment_ids"] == [], (
        "a truncated idle count of 29 changes nothing"
    )
    assert early["evaluated_enrollment_count"] == 2, "both benefits were ACTIVE"
    assert_instant(early["swept_at"], IDLE_29_INSTANT, "swept_at")
    assert (
        fx.refresh_enrollment(api, context["first"]["id"])["usage_status"]
        == "PENDING_FIRST_USE"
    )

    fx.set_clock(api, IDLE_30_INSTANT)
    late = fx.sweep(api, context["provider"]["id"])
    assert late["non_usage_flagged_enrollment_ids"] == [
        context["first"]["id"],
        context["second"]["id"],
    ], "one more second reaches 30 idle days for both benefits, in visit order"
    assert late["cure_expired_de_enrolled_enrollment_ids"] == [], (
        "step one wrote a future cure deadline, so step two cannot fire in the same sweep"
    )

    flagged = fx.refresh_enrollment(api, context["first"]["id"])
    assert flagged["usage_status"] == "NON_USAGE_FLAGGED"
    assert_instant(flagged["non_usage_flagged_at"], IDLE_30_INSTANT, "non_usage_flagged_at")
    assert_instant(flagged["cure_deadline_at"], CURE_DEADLINE, "cure_deadline_at")
    assert flagged["benefit_status"] == "ACTIVE", "flagging alone does not stop the benefit"


def test_the_cure_instant_is_inclusive_and_one_millisecond_later_is_refused(api):
    """Activity at exactly cure_deadline_at cures; the next millisecond is refused.

    PRD: "An activity arriving after the cure deadline has passed but before the next sweep
    has run cannot retroactively cure: it is refused with `ERR_CURE_PERIOD_EXPIRED`."

    Design: Difficulty/boundary_precision_check/non_usage_thirtieth_day_and_inclusive_cure_instant_boundaries
    """
    context = _two_never_used_benefits(api)
    fx.set_clock(api, IDLE_30_INSTANT)
    fx.sweep(api, context["provider"]["id"])

    fx.set_clock(api, CURE_DEADLINE)
    cured = validate_success(
        api.record_usage(context["first"]["id"], f.usage_payload(), context["agent"])
    )
    assert cured["usage_status"] == "USING", (
        "a usage event at exactly cure_deadline_at still cures"
    )
    assert_instant(cured["last_usage_at"], CURE_DEADLINE, "last_usage_at")
    assert_instant_null(cured["cure_deadline_at"], "cure_deadline_at")
    assert_instant_null(cured["non_usage_flagged_at"], "non_usage_flagged_at")

    fx.set_clock(api, PAST_CURE_INSTANT)
    response = api.record_usage(
        context["second"]["id"], f.usage_payload(), context["agent"]
    )
    validate_error(response, ApiErrorId.CURE_PERIOD_EXPIRED.value, 409)

    stranded = fx.refresh_enrollment(api, context["second"]["id"])
    assert stranded["usage_status"] == "NON_USAGE_FLAGGED", (
        "the refused activity leaves the posture where the sweep left it"
    )
    assert_instant(stranded["cure_deadline_at"], CURE_DEADLINE, "cure_deadline_at")
    assert_instant_null(stranded["last_usage_at"], "last_usage_at")


def _claim_with_an_empty_candidate_pool(api):
    """A claim for a month that entirely precedes the carrier's only benefit."""
    fx.set_clock(api, "2026-07-02T00:00:00Z")
    provider = fx.register_provider(api)
    address = fx.register_distinct_address(api, 1)
    applicant = fx.eligible_applicant(api, address["id"])
    fx.enroll(
        api,
        provider,
        applicant["subscriber"],
        applicant["check"],
        address,
        service_type="VOICE",
        benefit_start_date="2026-07-01T00:00:00Z",
    )
    claim = fx.file_claim(
        api, fx.draft_claim(api, provider, "2026-06")["id"], provider
    )
    assert claim["final_amount_cents"] == 0, (
        f"no benefit was live in June, got {claim['final_amount_cents']}"
    )
    assert claim["covered_enrollment_count"] == 0
    return {"provider": provider, "claim": claim}


def test_a_draw_against_an_empty_candidate_pool_is_refused(api):
    """The zero-cardinality pool boundary: a legal sample size cannot save an empty pool.

    PRD: "An empty pool is refused with `ERR_EMPTY_SAMPLE_POOL` and no sample row is
    created."

    Design: Difficulty/boundary_precision_check/audit_draw_zero_size_and_empty_pool_cardinality_boundaries
    """
    context = _claim_with_an_empty_candidate_pool(api)

    response = api.draw_audit_sample(
        context["claim"]["id"], f.audit_draw_payload(sample_size=1), AUDITOR_DRAWER
    )
    validate_error(response, ApiErrorId.EMPTY_SAMPLE_POOL.value, 409)

    claim = fx.refresh_claim(api, context["claim"]["id"])
    assert claim["status"] == "FILED", (
        f"a refused draw leaves the claim FILED, got {claim['status']}"
    )
    assert claim["audit_sample_count"] == 0, "no sample row was created"
    assert claim["failed_sample_count"] == 0

    listed, _meta = validate_paginated(
        api.list_audit_samples(PROGRAM_ADMIN, {"claim_id": context["claim"]["id"]})
    )
    assert listed == [], "the claim has no audit samples at all"


def _claim_with_a_single_candidate(api):
    """A filed claim whose candidate pool holds exactly one benefit."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    provider = fx.register_provider(api)
    address = fx.register_distinct_address(api, 1)
    applicant = fx.eligible_applicant(api, address["id"])
    fx.enroll(
        api,
        provider,
        applicant["subscriber"],
        applicant["check"],
        address,
        service_type="VOICE",
        benefit_start_date="2026-06-01T00:00:00Z",
    )
    fx.set_clock(api, "2026-07-02T00:00:00Z")
    claim = fx.file_claim(api, fx.draft_claim(api, provider, "2026-06")["id"], provider)
    assert claim["covered_enrollment_count"] == 1, "the pool holds exactly one candidate"
    return {"provider": provider, "claim": claim}


def test_sample_size_must_sit_inside_one_to_fifty(api):
    """The cardinality boundaries of sample_size itself: 0 and 51 both fail.

    PRD: "`sample_size` must be between 1 and 50 inclusive, or the request is refused with
    `ERR_INVALID_SAMPLE_SIZE`; a `sample_size` of 0 and a `sample_size` of 51 both fail."

    Design: Difficulty/boundary_precision_check/audit_draw_zero_size_and_empty_pool_cardinality_boundaries
    """
    context = _claim_with_a_single_candidate(api)
    claim_id = context["claim"]["id"]

    for illegal_size in (0, 51):
        response = api.draw_audit_sample(
            claim_id, f.audit_draw_payload(sample_size=illegal_size), AUDITOR_DRAWER
        )
        validate_error(response, ApiErrorId.INVALID_SAMPLE_SIZE.value, 422)

    refused = fx.refresh_claim(api, claim_id)
    assert refused["status"] == "FILED", "the refusals left the claim untouched"
    assert refused["audit_sample_count"] == 0

    drawn = fx.draw_samples(api, claim_id, sample_size=1)
    assert len(drawn) == 1, "the smallest legal size draws one sample"
    assert drawn[0]["selection_rank"] == 1


def test_income_exactly_equal_to_the_threshold_qualifies_and_one_cent_over_does_not(api):
    """The money equality boundary on the screening endpoint, in both directions.

    PRD: "An income-claimed check whose evaluated figure is strictly greater than the
    snapshotted threshold is refused with `ERR_SUBSCRIBER_INCOME_ABOVE_THRESHOLD`; a figure
    exactly equal to the threshold qualifies."

    Design: Difficulty/boundary_precision_check/income_threshold_equality_boundary_on_eligibility_check_endpoint
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    threshold = expected_income_threshold(4, False)
    assert threshold == 4341600, "the pinned threshold for a non-tribal household of four"

    exact_address = fx.register_distinct_address(api, 1)
    exact = fx.create_subscriber(
        api,
        exact_address["id"],
        household_size=4,
        annual_income_cents=threshold,
        tribal_lands_flag=False,
    )
    over_address = fx.register_distinct_address(api, 2)
    over = fx.create_subscriber(
        api,
        over_address["id"],
        household_size=4,
        annual_income_cents=threshold + 1,
        tribal_lands_flag=False,
    )

    accepted = validate_success(
        api.create_eligibility_check(
            exact["id"],
            f.eligibility_check_payload(claimed_basis="INCOME", proof_document_ref="DOC-1"),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert_eligibility_check(accepted)
    assert accepted["status"] == "PENDING_VERIFIER"
    assert accepted["income_variant"] == "STRICT_ANNUALIZED"
    assert accepted["evaluated_income_cents"] == threshold, (
        "the applicant's annual income is taken verbatim"
    )
    assert accepted["income_threshold_cents"] == threshold
    assert (
        fx.refresh_subscriber(api, exact["id"])["status"] == "ELIGIBILITY_PENDING"
    ), "opening a check advances the applicant"

    response = api.create_eligibility_check(
        over["id"],
        f.eligibility_check_payload(claimed_basis="INCOME", proof_document_ref="DOC-2"),
        PROGRAM_ADMIN,
    )
    validate_error(response, ApiErrorId.SUBSCRIBER_INCOME_ABOVE_THRESHOLD.value, 409)
    assert fx.refresh_subscriber(api, over["id"])["status"] == "PROSPECT", (
        "one cent over the threshold leaves the applicant a PROSPECT"
    )


def test_both_applicants_carry_the_same_threshold_snapshot_and_only_the_income_differs(api):
    """The bar is a snapshot of household size and tribal status, never of the income itself.

    PRD: "The resulting figure is stored on the applicant as `income_threshold_cents` and is
    recomputed whenever the applicant's `household_size` or `tribal_lands_flag` is written —
    which happens at creation and again on every accepted recertification attestation."

    Design: Difficulty/boundary_precision_check/income_threshold_equality_boundary_on_eligibility_check_endpoint
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    threshold = expected_income_threshold(4, False)

    exact = fx.create_subscriber(
        api,
        fx.register_distinct_address(api, 1)["id"],
        household_size=4,
        annual_income_cents=threshold,
        last_3mo_income_cents=1085400,
        tribal_lands_flag=False,
    )
    over = fx.create_subscriber(
        api,
        fx.register_distinct_address(api, 2)["id"],
        household_size=4,
        annual_income_cents=threshold + 1,
        last_3mo_income_cents=1085401,
        tribal_lands_flag=False,
    )

    assert exact["income_threshold_cents"] == 4341600, (
        f"the snapshot is taken at creation, got {exact['income_threshold_cents']}"
    )
    assert over["income_threshold_cents"] == exact["income_threshold_cents"], (
        "one cent more income does not move the applicant's own threshold"
    )
    assert over["annual_income_cents"] == exact["annual_income_cents"] + 1

    check = validate_success(
        api.create_eligibility_check(
            exact["id"],
            f.eligibility_check_payload(claimed_basis="INCOME", proof_document_ref="DOC-N1"),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert check["claimed_basis"] == "INCOME"
    assert check["income_threshold_cents"] == exact["income_threshold_cents"], (
        "the check copies the applicant's snapshot rather than recomputing it"
    )
    assert check["evaluated_income_cents"] == exact["annual_income_cents"]

    response = api.create_eligibility_check(
        over["id"],
        f.eligibility_check_payload(claimed_basis="INCOME", proof_document_ref="DOC-N2"),
        PROGRAM_ADMIN,
    )
    validate_error(response, ApiErrorId.SUBSCRIBER_INCOME_ABOVE_THRESHOLD.value, 409)

    listed, _meta = validate_paginated(
        api.list_subscriber_eligibility_checks(over["id"], PROGRAM_ADMIN)
    )
    assert listed == [], "the refused screening created no certification row"
