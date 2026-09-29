"""Calculation details: rate ladders, selection windows, rounding, ranking, tiers and hashes."""

from test_helpers import (
    AUDITOR_DRAWER_ID,
    address_hash_for,
    assert_device,
    assert_device_counters,
    assert_household_address,
    assert_instant,
    assert_ledger_tuple,
    assert_reimbursement_claim,
    expected_income_threshold,
    expected_recoupment,
    expected_risk_score,
    expected_support_line,
    factories as f,
    fixtures as fx,
    monthly_support_rate,
    validate_success,
)

JUNE_START = "2026-06-01T00:00:00Z"
JULY_START = "2026-07-01T00:00:00Z"
JULY_FILING = "2026-07-02T00:00:00Z"
MID_JUNE = "2026-06-16T00:00:00Z"
DRAFT_INSTANT = "2026-06-15T00:00:00Z"
AUGUST_CLOCK = "2026-08-01T00:00:00Z"


def _carrier_with_a_voice_and_a_broadband_benefit(api):
    """One carrier, two dwellings, one VOICE benefit and one BROADBAND benefit from 2026-06-01."""
    fx.set_clock(api, JUNE_START)
    provider = fx.register_provider(api)
    benefits = {}
    for index, service_type in ((1, "VOICE"), (2, "BROADBAND")):
        address = fx.register_distinct_address(api, index)
        applicant = fx.eligible_applicant(api, address["id"])
        benefits[service_type] = fx.enroll(
            api,
            provider,
            applicant["subscriber"],
            applicant["check"],
            address,
            service_type=service_type,
            benefit_start_date=JUNE_START,
        )
    return {
        "provider": provider,
        "voice": benefits["VOICE"],
        "broadband": benefits["BROADBAND"],
    }


def test_a_voice_line_and_a_broadband_line_price_at_their_declared_rates(api):
    """Two service types in one full-month claim: 925 plus 1200 makes exactly 2125.

    PRD: "The four rates that result are: non-tribal `VOICE` 925, non-tribal `BROADBAND`
    1200, tribal `VOICE` 3425, and tribal `BROADBAND` or `BUNDLED` 3700."

    Design: Corner/calculations/claim_final_amount_sums_voice_and_broadband_lines_at_declared_rates
    """
    context = _carrier_with_a_voice_and_a_broadband_benefit(api)
    provider = context["provider"]

    assert monthly_support_rate("VOICE", False) == 925
    assert monthly_support_rate("BROADBAND", False) == 1200
    assert context["voice"]["service_type"] == "VOICE"
    assert context["broadband"]["service_type"] == "BROADBAND"

    fx.set_clock(api, JULY_FILING)
    draft = fx.draft_claim(api, provider, "2026-06")
    assert draft["provisional_amount_cents"] == 2125, (
        "both benefits ran the whole of June, so the snapshot already prices the full month, "
        f"got {draft['provisional_amount_cents']}"
    )

    filed = fx.file_claim(api, draft["id"], provider, certifying_officer_ref="OFFICER-11")
    assert_reimbursement_claim(filed)
    assert filed["final_amount_cents"] == 925 + 1200, (
        f"the two declared rates sum to 2125, got {filed['final_amount_cents']}"
    )
    assert filed["covered_enrollment_count"] == 2
    assert filed["variance_cents"] == 0, (
        "no proration means the two pricings agree, so the variance closes at zero"
    )
    assert filed["status"] == "FILED"

    carrier = fx.refresh_provider(api, provider["id"])
    assert carrier["claim_gross_cents"] == 2125
    assert carrier["net_reimbursed_cents"] == 2125
    assert carrier["recouped_cents"] == 0


def test_the_claim_excludes_another_carriers_benefit_and_one_that_had_not_started(api):
    """Three ACTIVE benefits exist and only one earns a line on the June claim.

    PRD: "every benefit of the carrier that had at least one day of `ACTIVE` benefit inside
    the service month"

    Design: Corner/calculations/claim_excludes_other_carrier_and_not_yet_started_enrollments
    """
    fx.set_clock(api, JUNE_START)
    first_carrier, second_carrier = fx.register_provider_pair(api)

    own_address = fx.register_distinct_address(api, 1)
    own_applicant = fx.eligible_applicant(api, own_address["id"])
    own_benefit = fx.enroll(
        api,
        first_carrier,
        own_applicant["subscriber"],
        own_applicant["check"],
        own_address,
        service_type="VOICE",
        benefit_start_date=JUNE_START,
    )

    rival_address = fx.register_distinct_address(api, 2)
    rival_applicant = fx.eligible_applicant(api, rival_address["id"])
    rival_benefit = fx.enroll(
        api,
        second_carrier,
        rival_applicant["subscriber"],
        rival_applicant["check"],
        rival_address,
        service_type="VOICE",
        benefit_start_date=JUNE_START,
    )

    fx.set_clock(api, JULY_START)
    late_address = fx.register_distinct_address(api, 3)
    late_applicant = fx.eligible_applicant(api, late_address["id"])
    late_benefit = fx.enroll(
        api,
        first_carrier,
        late_applicant["subscriber"],
        late_applicant["check"],
        late_address,
        service_type="VOICE",
        benefit_start_date=JULY_START,
    )

    fx.set_clock(api, JULY_FILING)
    draft = fx.draft_claim(api, first_carrier, "2026-06")
    assert draft["provisional_amount_cents"] == 925, (
        "the July benefit starts after the last day of the service month, so the snapshot "
        f"prices one line, got {draft['provisional_amount_cents']}"
    )
    assert draft["covered_enrollment_count"] == 1

    filed = fx.file_claim(api, draft["id"], first_carrier, certifying_officer_ref="OFFICER-12")
    assert filed["final_amount_cents"] == 925, (
        "only the carrier's own benefit with a June day earns a line, got "
        f"{filed['final_amount_cents']}"
    )
    assert filed["covered_enrollment_count"] == 1

    assert fx.refresh_enrollment(api, own_benefit["id"])["benefit_status"] == "ACTIVE"
    rival = fx.refresh_enrollment(api, rival_benefit["id"])
    assert rival["benefit_status"] == "ACTIVE", "the other carrier's benefit is untouched"
    assert rival["provider_id"] == second_carrier["id"]
    assert_instant(
        fx.refresh_enrollment(api, late_benefit["id"])["benefit_start_date"],
        JULY_START,
        "benefit_start_date",
    )

    owner = fx.refresh_provider(api, first_carrier["id"])
    assert owner["claim_gross_cents"] == 925
    assert owner["active_enrollment_count"] == 2, (
        f"the July benefit still counts as live, got {owner['active_enrollment_count']}"
    )
    assert fx.refresh_provider(api, second_carrier["id"])["claim_gross_cents"] == 0, (
        "one carrier's filing never moves another carrier's ledger"
    )


def test_the_tribal_flag_moves_both_the_support_rate_and_the_income_bar(api):
    """One input flag reaches two constant tables: the 3700 cent line and the 1.50 multiplier.

    PRD: "The monthly rate starts at 925 cents, adds 2500 cents when the subscriber's
    `tribal_lands_flag` is true, and adds a further 275 cents when the benefit's
    `service_type` is `BROADBAND` or `BUNDLED`."

    Design: Corner/calculations/tribal_and_broadband_constants_stack_into_a_3700_cent_line
    """
    fx.set_clock(api, JUNE_START)
    provider = fx.register_provider(api)
    address = fx.register_distinct_address(api, 1)
    applicant = fx.eligible_applicant(
        api,
        address["id"],
        subscriber_overrides={
            "household_size": 4,
            "tribal_lands_flag": True,
            "annual_income_cents": 3000000,
        },
    )

    assert applicant["subscriber"]["tribal_lands_flag"] is True
    assert applicant["subscriber"]["income_threshold_cents"] == 4824000, (
        "the 1.50 multiplier lifts the household-of-four guideline to 4824000, got "
        f"{applicant['subscriber']['income_threshold_cents']}"
    )
    assert applicant["subscriber"]["income_threshold_cents"] != 4341600, (
        "the 1.35 multiplier is the wrong table for a Tribal household"
    )
    assert applicant["subscriber"]["income_threshold_cents"] == expected_income_threshold(4, True)
    assert applicant["check"]["income_threshold_cents"] == 4824000, (
        "the check snapshots the same raised bar"
    )

    benefit = fx.enroll(
        api,
        provider,
        applicant["subscriber"],
        applicant["check"],
        address,
        service_type="BUNDLED",
        benefit_start_date=JUNE_START,
    )
    assert benefit["service_type"] == "BUNDLED"
    assert monthly_support_rate("BUNDLED", True) == 3700

    fx.set_clock(api, JULY_FILING)
    filed = fx.file_claim(
        api,
        fx.draft_claim(api, provider, "2026-06")["id"],
        provider,
        certifying_officer_ref="OFFICER-13",
    )
    assert filed["final_amount_cents"] == 925 + 2500 + 275, (
        f"both addends stack onto the base rate, got {filed['final_amount_cents']}"
    )
    assert filed["covered_enrollment_count"] == 1
    assert fx.refresh_provider(api, provider["id"])["claim_gross_cents"] == 3700


def test_an_exact_half_cent_line_rounds_up_not_down_and_not_to_even(api):
    """A 2026-06-16 start earns 15 of 30 days, landing the only line on 462.5 exactly.

    PRD: "Each selected benefit then contributes a line equal to the monthly rate multiplied
    by its support days, divided by the number of calendar days in the service month, rounded
    half up to a whole cent."

    Design: Corner/calculations/line_cents_rounds_half_up_on_an_exact_half_cent
    """
    fx.set_clock(api, MID_JUNE)
    provider = fx.register_provider(api)
    address = fx.register_distinct_address(api, 1)
    applicant = fx.eligible_applicant(api, address["id"])
    benefit = fx.enroll(
        api,
        provider,
        applicant["subscriber"],
        applicant["check"],
        address,
        service_type="VOICE",
        benefit_start_date=MID_JUNE,
    )
    assert_instant(benefit["benefit_start_date"], MID_JUNE, "benefit_start_date")

    assert expected_support_line(925, 15, 30) == 463, (
        "the helper pins the arithmetic the endpoint must reproduce"
    )

    fx.set_clock(api, JULY_FILING)
    filed = fx.file_claim(
        api,
        fx.draft_claim(api, provider, "2026-06")["id"],
        provider,
        certifying_officer_ref="OFFICER-14",
    )
    assert filed["final_amount_cents"] == 463, (
        f"925 times 15 over 30 is 462.5, which rounds up, got {filed['final_amount_cents']}"
    )
    assert filed["final_amount_cents"] != 462, (
        "truncation and round-half-to-even both produce 462 and are both wrong"
    )
    assert filed["covered_enrollment_count"] == 1

    carrier = fx.refresh_provider(api, provider["id"])
    assert carrier["claim_gross_cents"] == 463
    assert carrier["net_reimbursed_cents"] == 463


def test_the_selector_reads_tier_before_cost_and_created_at_last(api):
    """With device_id omitted the pool of five must yield the older of the two 2100 BASIC units.

    PRD: "Otherwise the pool is ranked by `model_tier` ascending along the fixed ladder
    `BASIC`, then `STANDARD`, then `SMART`; ties broken by `unit_cost_cents` ascending; and
    remaining ties broken by `created_at` ascending as the final key."

    Design: Corner/calculations/device_selection_ranks_tier_then_cost_then_created_at
    """
    fx.set_clock(api, AUGUST_CLOCK)
    provider = fx.register_provider(api)
    smart, dear_basic, older_basic, newer_basic, standard = fx.stock_devices(
        api,
        provider,
        [("SMART", 4500), ("BASIC", 3900), ("BASIC", 2100), ("BASIC", 2100), ("STANDARD", 1200)],
    )

    address = fx.register_distinct_address(api, 1)
    applicant = fx.eligible_applicant(api, address["id"])
    benefit = fx.enroll(
        api,
        provider,
        applicant["subscriber"],
        applicant["check"],
        address,
        service_type="VOICE",
        benefit_start_date=AUGUST_CLOCK,
    )
    assert benefit["device_status"] == "AWAITING_DEVICE"
    assert benefit["last_device_issued_at"] is None, "no freeze can apply to a first issuance"

    chosen = validate_success(
        api.issue_device(
            benefit["id"], f.device_issuance_payload(), fx.provider_headers(provider)
        )
    )
    assert_device(chosen)
    assert chosen["id"] == older_basic["id"], (
        "tier wins before cost, and created_at breaks the 2100 cent tie in favour of the "
        f"earlier row, got {chosen['id']}"
    )
    assert chosen["status"] == "ISSUED"
    assert chosen["issued_enrollment_id"] == benefit["id"]
    assert chosen["model_tier"] == "BASIC"
    assert chosen["unit_cost_cents"] == 2100
    assert_instant(chosen["issued_at"], AUGUST_CLOCK, "issued_at")

    for spare, label in (
        (smart, "a 4500 cent SMART handset"),
        (dear_basic, "a 3900 cent BASIC handset"),
        (newer_basic, "the later of the two 2100 cent BASIC handsets"),
        (standard, "a 1200 cent STANDARD handset"),
    ):
        assert fx.refresh_device(api, spare["id"])["status"] == "IN_STOCK", (
            f"{label} was not selected"
        )

    issued = fx.refresh_enrollment(api, benefit["id"])
    assert issued["device_status"] == "DEVICE_ISSUED"
    assert issued["device_issuance_count"] == 1
    assert_instant(issued["last_device_issued_at"], AUGUST_CLOCK, "last_device_issued_at")
    assert issued["audit_risk_score"] == 10, (
        f"one handset carries ten points of risk, got {issued['audit_risk_score']}"
    )
    assert issued["audit_risk_score"] == expected_risk_score(device_issuance_count=1)

    assert_device_counters(fx.refresh_provider(api, provider["id"]), 5, 4, 1, 0, 0)


def test_an_extrapolated_error_below_five_hundred_takes_the_lowest_penalty_rate(api):
    """A 986 cent claim with one of two samples failed extrapolates to 493, seven cents under the cut-off.

    PRD: "Step three selects the penalty rate **from the extrapolated figure**, not from
    `final_amount_cents`: 0.05 while the extrapolated error is below 500 cents, 0.10 while it
    is at least 500 and below 1500, and 0.20 once it reaches 1500."

    Design: Corner/calculations/low_penalty_tier_applies_seven_cents_below_the_first_cut_off
    """
    fx.set_clock(api, DRAFT_INSTANT)
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
                benefit_start_date=DRAFT_INSTANT,
            )
        )

    assert expected_support_line(925, 16, 30) == 493, (
        "2026-06-15 through 2026-06-30 is 16 of June's 30 days"
    )

    fx.set_clock(api, JULY_FILING)
    claim = fx.file_claim(
        api,
        fx.draft_claim(api, provider, "2026-06")["id"],
        provider,
        certifying_officer_ref="OFFICER-15",
    )
    assert claim["final_amount_cents"] == 986, (
        f"two 493 cent lines summed after rounding, got {claim['final_amount_cents']}"
    )
    assert claim["covered_enrollment_count"] == 2

    samples = fx.draw_samples(api, claim["id"], sample_size=2)
    assert len(samples) == 2
    assert samples[0]["claimed_line_cents"] == 493
    assert samples[1]["claimed_line_cents"] == 493
    assert samples[0]["selection_rank"] == 1
    assert samples[0]["enrollment_id"] == benefits[0]["id"], (
        "equal risk scores and equal start dates leave created_at ascending as the ranking key"
    )

    failed = fx.adjudicate(
        api,
        samples[0]["id"],
        finding="NON_USAGE_UNCURED",
        finding_note="no usage evidence for the sampled month",
    )
    assert failed["status"] == "ADJUDICATED_FAIL"
    assert failed["disallowed_support_cents"] == 493

    untouched = fx.refresh_sample(api, samples[1]["id"])
    assert untouched["status"] == "DRAWN", (
        f"a failing finding does not wait for its siblings, got {untouched['status']}"
    )
    assert untouched["disallowed_support_cents"] is None

    expected = expected_recoupment(986, 1, 2)
    assert expected["extrapolated_cents"] == 493
    assert expected["penalty_rate"] == 0.05
    assert expected["penalty_cents"] == 25
    assert expected["recoupment_amount_cents"] == 518

    settled = fx.refresh_claim(api, claim["id"])
    assert settled["status"] == "AUDIT_FAILED"
    assert settled["audit_sample_count"] == 2
    assert settled["failed_sample_count"] == 1
    assert settled["sample_drawn_by_ref"] == AUDITOR_DRAWER_ID
    assert settled["penalty_cents"] == 25, (
        f"the low band takes five percent of 493, which is 24.65 rounding up, got {settled['penalty_cents']}"
    )
    assert settled["recoupment_amount_cents"] == 518
    assert settled["net_payable_cents"] == 468
    assert settled["final_amount_cents"] == 986, "the gross figure is never rewritten"

    assert_ledger_tuple(fx.refresh_provider(api, provider["id"]), 986, 518, 468, True)

    for benefit in benefits:
        assert fx.refresh_enrollment(api, benefit["id"])["benefit_status"] == "ACTIVE", (
            "an uncured non-usage finding disallows money without ending the benefit"
        )


def test_only_the_canonical_form_collides_and_the_zip_plus_four_truncates(api):
    """Three dwellings, two hashes: punctuation, case and a nine-digit postal code all collapse.

    PRD: "The five normalized parts are finally joined into a single string with one
    vertical-bar character between consecutive parts, in the order street line, unit
    designator, city, state code, shortened postal component."

    Design: Corner/calculations/address_hash_normalization_collides_only_on_the_canonical_form
    """
    fx.set_clock(api, AUGUST_CLOCK)

    first = fx.register_address(
        api,
        address_line1="1200  N. Main St.",
        unit_designator="Apt 4-B",
        city="El Paso",
        state_code="TX",
        postal_code="799012214",
    )
    assert_household_address(first)
    assert first["address_hash"] == "1200NMAINST|APT4B|ELPASO|TX|79901", (
        f"the nine-digit postal code is cut to its first five, got {first['address_hash']}"
    )
    assert first["address_hash"] == address_hash_for(
        "1200  N. Main St.", "Apt 4-B", "El Paso", "TX", "799012214"
    )
    assert first["cohort_address_count"] == 1, "the first arrival stands alone in its cohort"
    assert first["status"] == "UNVERIFIED"

    second = fx.register_address(
        api,
        address_line1="1200 n main st",
        unit_designator="apt. 4b",
        city="EL PASO",
        state_code="TX",
        postal_code="79901",
    )
    assert second["address_hash"] == first["address_hash"], (
        "mixed case and different punctuation normalise to the identical canonical form"
    )
    assert second["cohort_address_count"] == 2
    assert second["status"] == "DUPLICATE_FLAGGED", (
        f"the arriving row is born flagged rather than passing through UNVERIFIED, got {second['status']}"
    )

    third = fx.register_address(
        api,
        address_line1="1200 N Main St",
        unit_designator="Apt 4-C",
        city="El Paso",
        state_code="TX",
        postal_code="79901",
    )
    assert third["address_hash"] == "1200NMAINST|APT4C|ELPASO|TX|79901", (
        f"one letter of the unit designator changes the key, got {third['address_hash']}"
    )
    assert third["address_hash"] != first["address_hash"]
    assert third["cohort_address_count"] == 1
    assert third["status"] == "UNVERIFIED", "a dwelling with its own key is never flagged"

    reread_first = fx.refresh_address(api, first["id"])
    assert reread_first["status"] == "DUPLICATE_FLAGGED", (
        "the second create pulled the earlier row into the cohort"
    )
    assert reread_first["cohort_address_count"] == 2
    assert reread_first["max_permitted_benefit_slots"] == 1
    assert reread_first["occupied_benefit_slots"] == 0
    assert fx.refresh_address(api, third["id"])["cohort_address_count"] == 1, (
        "the third create joined nobody"
    )


def test_the_handset_weight_stops_at_two_while_the_dwelling_weight_still_lands(api):
    """The score is read after every contributing write: 0, 10, 20, still 20, then 60.

    PRD: "It is the sum of five weights: 40 when the certified dwelling's status is
    `DUPLICATE_FLAGGED`; 30 when `usage_status` is `NON_USAGE_FLAGGED` or `CURE_EXPIRED`; 20
    when `recert_status` is `NON_RESPONSIVE` or `RESPONDED_INELIGIBLE`; 10 for each handset
    ever issued, counting `device_issuance_count` but capped at 2 handsets, so at most 20; and
    15 when `transfer_count` is 1 or more."

    Design: Corner/calculations/audit_risk_score_caps_device_weight_and_adds_duplicate_address_weight
    """
    fx.set_clock(api, AUGUST_CLOCK)
    provider = fx.register_provider(api)
    first, second, third = fx.stock_devices(
        api, provider, [("BASIC", 2100), ("BASIC", 2200), ("BASIC", 2300)]
    )

    dwelling = fx.register_address(api)
    assert dwelling["status"] == "UNVERIFIED", "the dwelling starts alone in its cohort"
    applicant = fx.eligible_applicant(api, dwelling["id"])
    benefit = fx.enroll(
        api,
        provider,
        applicant["subscriber"],
        applicant["check"],
        dwelling,
        service_type="VOICE",
        benefit_start_date=AUGUST_CLOCK,
    )
    assert benefit["audit_risk_score"] == 0, (
        f"a fresh benefit at a clean dwelling scores nothing, got {benefit['audit_risk_score']}"
    )

    for handset, expected_count, expected_score in (
        (first, 1, 10),
        (second, 2, 20),
        (third, 3, 20),
    ):
        issued = fx.issue_device(api, benefit["id"], provider, device_id=handset["id"])
        assert issued["id"] == handset["id"]
        assert issued["status"] == "ISSUED"

        scored = fx.refresh_enrollment(api, benefit["id"])
        assert scored["device_issuance_count"] == expected_count, (
            f"handset {expected_count} was recorded, got {scored['device_issuance_count']}"
        )
        assert scored["audit_risk_score"] == expected_score, (
            f"after {expected_count} handsets the score is {expected_score}, got "
            f"{scored['audit_risk_score']}"
        )
        assert scored["audit_risk_score"] == expected_risk_score(
            device_issuance_count=expected_count
        )

        if handset is not third:
            fx.return_device(api, handset["id"], return_condition="DAMAGED")

    colliding = fx.register_address(
        api,
        address_line1="1200  N. Main St.",
        unit_designator="apt. 4b",
        city="EL PASO",
        state_code="TX",
        postal_code="799012214",
    )
    assert colliding["address_hash"] == dwelling["address_hash"]
    assert colliding["status"] == "DUPLICATE_FLAGGED"
    assert fx.refresh_address(api, dwelling["id"])["status"] == "DUPLICATE_FLAGGED", (
        "the certified dwelling is pulled back into an unresolved cohort"
    )

    final = fx.refresh_enrollment(api, benefit["id"])
    assert final["usage_status"] == "PENDING_FIRST_USE"
    assert final["transfer_count"] == 0
    assert final["device_issuance_count"] == 3
    assert final["audit_risk_score"] == 60, (
        "forty for the flagged dwelling plus the capped twenty for handsets, got "
        f"{final['audit_risk_score']}"
    )
    assert final["audit_risk_score"] == expected_risk_score(
        address_duplicate_flagged=True, device_issuance_count=3
    )
    assert final["device_status"] == "DEVICE_ISSUED"

    for retired in (first, second):
        row = fx.refresh_device(api, retired["id"])
        assert row["status"] == "RETIRED", (
            f"a DAMAGED return retires the handset, got {row['status']}"
        )
        assert row["return_condition"] == "DAMAGED"
    assert fx.refresh_device(api, third["id"])["status"] == "ISSUED"

    assert_device_counters(fx.refresh_provider(api, provider["id"]), 3, 0, 1, 0, 2)


def test_the_ledger_takes_the_final_figure_not_the_snapshot_and_not_the_delta(api):
    """A 463 cent draft and a 925 cent filing: the carrier ledger picks up only the 925.

    PRD: "The ledger always sums the **gross** final amount; the per-claim `net_payable_cents`
    figure is for display only and is never added into any carrier counter, because doing so
    would double-count the recoupment."

    Design: Corner/calculations/provider_ledger_records_the_final_variant_not_the_provisional_snapshot
    """
    fx.set_clock(api, JUNE_START)
    provider = fx.register_provider(api)
    address = fx.register_distinct_address(api, 1)
    applicant = fx.eligible_applicant(api, address["id"])
    benefit = fx.enroll(
        api,
        provider,
        applicant["subscriber"],
        applicant["check"],
        address,
        service_type="VOICE",
        benefit_start_date=JUNE_START,
    )

    fx.set_clock(api, DRAFT_INSTANT)
    draft = fx.draft_claim(api, provider, "2026-06")
    assert draft["status"] == "DRAFT"
    assert draft["provisional_amount_cents"] == 463, (
        "2026-06-01 through 2026-06-15 is 15 of 30 days, so 462.5 rounds up, got "
        f"{draft['provisional_amount_cents']}"
    )
    assert draft["covered_enrollment_count"] == 1
    assert draft["variance_cents"] == 0, "the variance is only written at file time"
    assert draft["final_amount_cents"] == 0

    mid = fx.refresh_provider(api, provider["id"])
    assert_ledger_tuple(mid, 0, 0, 0, False)
    assert mid["open_claim_count"] == 1, (
        f"a draft counts as open, got {mid['open_claim_count']}"
    )

    fx.set_clock(api, JULY_FILING)
    filed = fx.file_claim(api, draft["id"], provider, certifying_officer_ref="OFFICER-16")
    assert filed["final_amount_cents"] == 925, (
        f"the closed month pays all 30 days, got {filed['final_amount_cents']}"
    )
    assert filed["variance_cents"] == 925 - 463, (
        f"the delta is the observable divergence, got {filed['variance_cents']}"
    )
    assert filed["covered_enrollment_count"] == 1
    assert filed["provisional_amount_cents"] == 463, (
        "both figures stay side by side so the delta remains auditable"
    )
    assert filed["status"] == "FILED"
    assert_instant(filed["filed_at"], JULY_FILING, "filed_at")

    after = fx.refresh_provider(api, provider["id"])
    assert after["claim_gross_cents"] == 925, (
        "the ledger takes the final figure, not the 463 snapshot and not the 462 delta, got "
        f"{after['claim_gross_cents']}"
    )
    assert after["claim_gross_cents"] != 463
    assert after["claim_gross_cents"] != 462
    assert_ledger_tuple(after, 925, 0, 925, False)

    assert fx.refresh_enrollment(api, benefit["id"])["benefit_status"] == "ACTIVE"
