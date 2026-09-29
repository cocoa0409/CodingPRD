"""Continuing-education credit: the two totals, quarter-hour quantisation, and caps."""
from test_helpers import (
    ANALYST,
    RENEWAL_CLOCK,
    ApiClient,
    assert_decimal_equals,
    assert_renewal_dimensions,
    pay_renewal,
    seed_active_license,
    seed_ce_record,
    seed_renewal,
    submit_renewal,
    validate_success,
)


def _diverging_ce_filing(api: ApiClient):
    """A submitted filing whose two credit totals cannot agree.

    Three claims are attached: an accredited live-contact claim inside the
    accounting window, an unaccredited live-contact claim, and an accredited
    self-study claim whose completion date falls before the window opens.
    """
    ctx = seed_active_license(
        api,
        program_overrides={
            "program_code": "OH-BSN-01",
            "program_name": "Buckeye BSN",
            "degree_level": "BSN",
            "nclex_first_time_pass_rate_bp": 8800,
        },
        nurse_overrides={"full_name": "Dana Reed", "birth_year": 1988, "ssn_last4": "4417"},
    )
    renewal = seed_renewal(api, ctx["license_id"], clock=RENEWAL_CLOCK,
                           attested_practice_hours=1800)
    seed_ce_record(api, renewal["id"], provider_code="OHNA-100", provider_accredited=True,
                   category="LIVE_CONTACT", minutes=1200,
                   completion_date="2027-03-15T00:00:00Z")
    seed_ce_record(api, renewal["id"], provider_code="UNACC-200", provider_accredited=False,
                   category="LIVE_CONTACT", minutes=600,
                   completion_date="2027-04-20T00:00:00Z")
    seed_ce_record(api, renewal["id"], provider_code="OHNA-300", provider_accredited=True,
                   category="SELF_STUDY", minutes=480,
                   completion_date="2026-07-15T00:00:00Z")
    pay_renewal(api, renewal["id"])
    ctx["renewal"] = submit_renewal(api, renewal["id"])
    ctx["renewal_id"] = renewal["id"]
    return ctx


def test_provisional_and_audited_ce_totals_diverge_by_eighteen_hours(api: ApiClient):
    """PRD §3.4: "The **provisional** total, written to
    `ce_credit_hours_provisional` at submit, admits a claim whose
    `verification_status` is `UNVERIFIED` or `VERIFIED`, does not look at
    `provider_accredited` at all, and does not check the accounting window; it
    is therefore an upper bound."

    PRD §3.4: "The **audited** total, written to `ce_credit_hours_audited` at
    continuing-education verification, admits a claim only when its
    `verification_status` is `VERIFIED`, its `provider_accredited` is true, and
    its `completion_date` falls inside the half-open accounting window — at or
    after `period_start_on` and strictly before `period_end_on`."

    PRD §3.4: "Over the same claim set the audited total is therefore always
    lower than or equal to the provisional one."

    Design: Difficulty/dual_variant_calc/ce_provisional_and_audited_variants_diverge_by_eighteen_hours
    """
    ctx = _diverging_ce_filing(api)
    assert_decimal_equals(ctx["renewal"]["ce_credit_hours_provisional"], 38.00,
                          "ce_credit_hours_provisional")

    verified = validate_success(api.verify_renewal_ce(ctx["renewal_id"], ANALYST))

    assert_decimal_equals(verified["ce_credit_hours_audited"], 20.00,
                          "ce_credit_hours_audited")
    assert_decimal_equals(verified["ce_credit_hours_provisional"], 38.00,
                          "ce_credit_hours_provisional")
    delta = float(verified["ce_credit_hours_provisional"]) - float(
        verified["ce_credit_hours_audited"]
    )
    assert abs(delta - 18.00) < 0.005, (
        f"The two variants must diverge by 18.00 hours over this claim set, got {delta}"
    )


def test_audited_total_below_requirement_moves_filing_to_ce_deficient(api: ApiClient):
    """PRD §3.4: "Whatever it computes is written to `ce_credit_hours_audited`,
    and the result branches the filing dimension: a total at or above the
    board's `ce_hours_required` moves `renewal_status` from `SUBMITTED` to
    `CE_VERIFIED`, while a total below it moves `SUBMITTED` to `CE_DEFICIENT`."

    PRD §3.4: "`fee_paid_cents` is set equal to `fee_applied_cents`, because
    assessment and receipt happen in the same act."

    PRD §3.4: "The system first computes `late_days` as the number of whole days
    from the credential's `expires_on` to the logical clock, floored at 0 — a
    renewal filed before expiry has zero late days."

    Design: Difficulty/dual_variant_calc/ce_provisional_and_audited_variants_diverge_by_eighteen_hours
    """
    ctx = _diverging_ce_filing(api)

    verified = validate_success(api.verify_renewal_ce(ctx["renewal_id"], ANALYST))

    assert_renewal_dimensions(verified, "CE_DEFICIENT", "NOT_SELECTED")
    assert verified["fee_applied_cents"] == 12000, (
        f"Expected the base fee of 12000 cents, got {verified['fee_applied_cents']}"
    )
    assert verified["fee_paid_cents"] == 12000, (
        f"Expected 12000 cents received, got {verified['fee_paid_cents']}"
    )
    assert verified["late_days"] == 0, (
        f"A filing opened before expiry has 0 late days, got {verified['late_days']}"
    )


def _quarter_hour_boundary_filing(api: ApiClient):
    """A filing whose four claims land on 30.00 only if each is quantised first."""
    ctx = seed_active_license(
        api,
        program_overrides={
            "program_code": "OH-ADN-07",
            "program_name": "Miami Valley ADN",
            "degree_level": "ADN",
            "nclex_first_time_pass_rate_bp": 8400,
        },
        nurse_overrides={"full_name": "Priya Anand", "birth_year": 1985, "ssn_last4": "3301"},
    )
    renewal = seed_renewal(api, ctx["license_id"], clock=RENEWAL_CLOCK,
                           attested_practice_hours=2000)
    ctx["ce_records"] = [
        seed_ce_record(api, renewal["id"], provider_code="OHNA-701",
                       provider_accredited=True, category="LIVE_CONTACT", minutes=1485,
                       completion_date="2027-05-10T00:00:00Z"),
        seed_ce_record(api, renewal["id"], provider_code="OHNA-702",
                       provider_accredited=True, category="LIVE_CONTACT", minutes=100,
                       completion_date="2027-05-10T00:00:00Z"),
        seed_ce_record(api, renewal["id"], provider_code="OHNA-703",
                       provider_accredited=True, category="LIVE_CONTACT", minutes=100,
                       completion_date="2027-05-10T00:00:00Z"),
        seed_ce_record(api, renewal["id"], provider_code="OHNA-704",
                       provider_accredited=True, category="LIVE_CONTACT", minutes=100,
                       completion_date="2027-05-10T00:00:00Z"),
    ]
    pay_renewal(api, renewal["id"])
    ctx["renewal"] = submit_renewal(api, renewal["id"])
    ctx["renewal_id"] = renewal["id"]
    return ctx


def test_per_record_quantisation_lands_audited_total_on_thirty_not_twenty_nine_point_seven_five(
    api: ApiClient,
):
    """PRD §2.9: "Crucially, the quantisation happens once per record, before
    any summation — never after."

    PRD §3.4: "This per-record quantisation happens **before any summing**, and
    never after: three hundred-minute claims total 5.25 credit hours when each
    is quantised first, but only 5.00 if the minutes are summed and quantised
    once, and at the requirement boundary those two answers give opposite
    renewal outcomes."

    PRD §3.4: "a total at or above the board's `ce_hours_required` moves
    `renewal_status` from `SUBMITTED` to `CE_VERIFIED`"

    Design: Difficulty/combinatorial_formula/ce_quarter_hour_rounding_order_decides_thirty_hour_boundary
    """
    ctx = _quarter_hour_boundary_filing(api)

    verified = validate_success(api.verify_renewal_ce(ctx["renewal_id"], ANALYST))

    assert_decimal_equals(verified["ce_credit_hours_audited"], 30.00,
                          "ce_credit_hours_audited")
    assert_renewal_dimensions(verified, "CE_VERIFIED", "NOT_SELECTED")


def test_each_ce_claim_carries_its_own_quantised_credit_hours(api: ApiClient):
    """PRD §3.4: "Every claim is converted to credit on its own, at creation,
    and the conversion is quantised: divide `minutes` by 60 to obtain hours,
    divide that by 0.25, round the result half up to a whole number, and
    multiply by 0.25 again."

    PRD §3.4: "A ninety-minute activity therefore yields 1.50 credit hours, and
    a hundred-minute activity yields 1.75 — one and two-thirds hours quantised
    up to the nearest quarter hour."

    Design: Difficulty/combinatorial_formula/ce_quarter_hour_rounding_order_decides_thirty_hour_boundary
    """
    ctx = _quarter_hour_boundary_filing(api)
    records = ctx["ce_records"]

    assert_decimal_equals(records[0]["credit_hours"], 24.75, "credit_hours of 1485 minutes")
    for record in records[1:]:
        assert_decimal_equals(record["credit_hours"], 1.75,
                              "credit_hours of 100 minutes")
    raw_sum = sum(float(record["credit_hours"]) for record in records)
    assert abs(raw_sum - 30.00) < 0.005, (
        f"Four separately quantised claims sum to 30.00, got {raw_sum}"
    )


def _carry_over_capped_filing(api: ApiClient):
    """A filing claiming nine carry-over hours against a five-hour cap."""
    ctx = seed_active_license(
        api,
        program_overrides={
            "program_code": "OH-BSN-81",
            "program_name": "Findlay BSN",
            "degree_level": "BSN",
            "nclex_first_time_pass_rate_bp": 8200,
        },
        nurse_overrides={"full_name": "Sofia Bergeron", "birth_year": 1986,
                         "ssn_last4": "4402"},
    )
    renewal = seed_renewal(api, ctx["license_id"], clock=RENEWAL_CLOCK,
                           attested_practice_hours=1400,
                           carry_over_hours_claimed=9.00)
    seed_ce_record(api, renewal["id"], provider_code="OHNA-800", provider_accredited=True,
                   category="LIVE_CONTACT", minutes=1500,
                   completion_date="2027-08-08T00:00:00Z")
    pay_renewal(api, renewal["id"])
    ctx["renewal"] = submit_renewal(api, renewal["id"])
    ctx["renewal_id"] = renewal["id"]
    return ctx


def test_carry_over_cap_lands_audited_total_exactly_on_the_requirement(api: ApiClient):
    """PRD §3.4: "Carry-over is capped the same way: the allowed carry-over is
    the filing's `carry_over_hours_claimed`, reduced to the board's
    `ce_carry_over_cap_hours` if it exceeds it."

    PRD §3.4: "The total is the sum of the four capped category subtotals plus
    the allowed carry-over, rounded half up to two decimal places."

    PRD §3.4: "a total at or above the board's `ce_hours_required` moves
    `renewal_status` from `SUBMITTED` to `CE_VERIFIED`"

    Design: Difficulty/boundary_precision_check/carry_over_cap_lands_ce_total_exactly_on_requirement
    """
    ctx = _carry_over_capped_filing(api)
    assert_decimal_equals(ctx["renewal"]["ce_credit_hours_provisional"], 30.00,
                          "ce_credit_hours_provisional")

    verified = validate_success(api.verify_renewal_ce(ctx["renewal_id"], ANALYST))

    assert_decimal_equals(verified["ce_credit_hours_audited"], 30.00,
                          "ce_credit_hours_audited")
    assert_renewal_dimensions(verified, "CE_VERIFIED", "NOT_SELECTED")


def test_carry_over_claim_is_stored_uncapped_while_the_total_applies_the_cap(
    api: ApiClient,
):
    """PRD §3.4: "may pre-populate `attested_practice_hours` — the practice
    hours the licensee asserts for the period, defaulting to 0 — and
    `carry_over_hours_claimed`, the continuing-education hours the licensee
    claims to import from the prior period, also defaulting to 0."

    PRD §3.4: "Carry-over is capped the same way: the allowed carry-over is the
    filing's `carry_over_hours_claimed`, reduced to the board's
    `ce_carry_over_cap_hours` if it exceeds it."

    PRD §3.4: "`fee_paid_cents` is set equal to `fee_applied_cents`, because
    assessment and receipt happen in the same act."

    Design: Difficulty/boundary_precision_check/carry_over_cap_lands_ce_total_exactly_on_requirement
    """
    ctx = _carry_over_capped_filing(api)

    verified = validate_success(api.verify_renewal_ce(ctx["renewal_id"], ANALYST))

    assert_decimal_equals(verified["carry_over_hours_claimed"], 9.00,
                          "carry_over_hours_claimed")
    audited = float(verified["ce_credit_hours_audited"])
    assert abs(audited - 34.00) > 0.005, (
        "The uncapped nine-hour claim must not reach the audited total"
    )
    assert abs(audited - 25.00) > 0.005, (
        "The capped five hours of carry-over must still be added to the total"
    )
    assert verified["fee_applied_cents"] == 12000, (
        f"Expected the base fee of 12000 cents, got {verified['fee_applied_cents']}"
    )
    assert verified["late_days"] == 0, (
        f"A filing opened before expiry has 0 late days, got {verified['late_days']}"
    )
