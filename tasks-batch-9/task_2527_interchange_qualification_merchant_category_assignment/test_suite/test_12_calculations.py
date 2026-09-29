"""Interchange arithmetic: candidate ranking, the four-step assessment pipeline,
its pinned clamps, truncated clearing delay, incentive tiers, the
misrepresentation penalty and the two comparison edges of the clock sweep.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    add_record,
    board_merchant,
    canonical_environment,
    create_acquirer,
    create_incentive_program,
    create_mcc,
    create_platform,
    create_rate_program,
    draft_rate_version,
    enrol_merchant,
    evaluate_enrollment,
    finalize_batch,
    open_audit,
    open_batch,
    publish_rate_version,
    read_audit,
    read_batch,
    read_enrollment,
    read_merchant,
    read_record,
    set_clock,
    start_fieldwork,
    submit_batch,
    sustain_findings,
)
from test_helpers.test_users import TEST_USERS

NETWORK_ADMIN = TEST_USERS["network_admin_headers"]
CLOCK = "2026-09-03T00:00:00Z"
FOUR_ELEMENTS = ["AUTH_CODE", "TERMINAL_ID", "TRANSACTION_DATE", "CARDHOLDER_ZIP"]


def _standard_program(eligible_mcc_codes):
    return create_rate_program(
        "STANDARD_FALLBACK",
        "STANDARD",
        eligible_mcc_codes,
        name="Standard",
        base_rate_bps=254,
        per_item_fee_cents=10,
        requires_data_elements=[],
        max_clearing_delay_hours=720,
    )


def _cps_retail_program(eligible_mcc_codes):
    return create_rate_program(
        "CPS_RETAIL_STD",
        "CPS_RETAIL",
        eligible_mcc_codes,
        name="CPS Retail",
        base_rate_bps=145,
        per_item_fee_cents=10,
        requires_data_elements=FOUR_ELEMENTS,
        max_clearing_delay_hours=24,
    )


def _department_store_environment(clock, **acquirer_overrides):
    """A US/USD acquirer, category 5311 reaching no special program category, and
    the CPS_RETAIL and STANDARD tiers."""
    set_clock(clock)
    platform = create_platform()
    acquirer = create_acquirer(platform["id"], **acquirer_overrides)
    create_mcc(
        "5311",
        "DEPARTMENT_STORE",
        description="Department Stores",
        program_eligibility=[],
    )
    cps = _cps_retail_program(["5311"])
    standard = _standard_program(["5311"])
    return {
        "platform": platform,
        "acquirer": acquirer,
        "acquirer_id": acquirer["id"],
        "cps": cps,
        "standard": standard,
    }


class TestCandidateRankingAndClamps:
    def test_the_utility_tier_wins_on_amortised_cost_and_prices_to_its_flat_fee(self):
        """A 20000-cent utility record carrying the utility tier's two elements
        amortises that tier's 75-cent fee down to 38 basis points, which beats the
        fallback's 259, so the record qualifies for the flat fee alone.

        PRD 3.5: "For each candidate the service computes a comparable cost in
        basis points: take the program's `per_item_fee_cents`, multiply by ten
        thousand, divide by the record's `amount_cents`, round that quotient half up
        to a whole basis point, and add the result to the program's `base_rate_bps`."

        PRD 3.6: "Step one is the ad-valorem component: multiply the record's
        `amount_cents` by the program's `base_rate_bps`, divide by ten thousand,
        round half up to whole cents, and then add the program's
        `per_item_fee_cents`."

        PRD 3.6: "If the selected program's `category` is anything other than
        `STANDARD`, the record advances `PENDING → QUALIFIED`,
        `qualified_rate_program_id` and `assessed_interchange_cents` and
        `mcc_at_qualification` are written, `downgrade_reason` stays null, and
        `authorization_status` is not touched."

        Design: Corner/calculations/calc_correct_result_utility_program_wins_on_amortised_cost_bps
        """
        set_clock(CLOCK)
        platform = create_platform()
        acquirer = create_acquirer(platform["id"])
        create_mcc(
            "4900",
            "UTILITY_SERVICE",
            description="Utilities",
            program_eligibility=["UTILITY"],
            requires_documentation=True,
        )
        utility = create_rate_program(
            "UTILITY_STD",
            "UTILITY",
            ["4900"],
            name="Utility",
            base_rate_bps=0,
            per_item_fee_cents=75,
            requires_data_elements=["AUTH_CODE", "CUSTOMER_ACCOUNT_REF"],
            max_clearing_delay_hours=48,
        )
        _cps_retail_program(["4900"])
        _standard_program(["4900"])
        merchant = board_merchant(
            acquirer["id"], "UTILITY_SERVICE", legal_name="Riverside Power"
        )
        batch = open_batch(acquirer["id"], "2026-09-02", "USD")
        record = add_record(
            batch["id"],
            merchant["id"],
            20000,
            acquirer["id"],
            expected_batch_version=batch["version"],
            auth_code="A00300",
            auth_timestamp="2026-09-02T00:00:00Z",
            clearing_timestamp="2026-09-02T00:00:00Z",
            data_elements=["AUTH_CODE", "CUSTOMER_ACCOUNT_REF"],
        )
        assert record["clearing_delay_hours"] == 0
        submit_batch(batch["id"], acquirer["id"])

        response = api_client.finalize_settlement_batch(batch["id"], NETWORK_ADMIN)
        assert response.status_code == 200
        validate_success(response)

        priced = read_record(record["id"])
        assert priced["qualified_rate_program_id"] == utility["id"]
        assert priced["qualification_status"] == "QUALIFIED"
        assert priced["downgrade_reason"] is None
        assert priced["assessed_interchange_cents"] == 75
        assert priced["cross_border"] is False
        assert priced["cross_border_surcharge_cents"] == 0
        assert priced["fx_markup_cents"] == 0
        assert priced["mcc_at_qualification"] == "4900"
        assert read_batch(batch["id"])["total_assessed_cents"] == 75

    def test_the_eight_cent_floor_is_applied_after_the_ceiling_not_before(self):
        """A 200-cent charity record prices to 2 cents raw against a 7-cent
        ceiling; capping first and flooring second yields 8, while the reverse order
        would have yielded 7.

        PRD 3.6: "Step four is a **nested clamp whose order is pinned: cap first,
        then floor.**"

        PRD 3.6: "Cap that raw amount at the record's `amount_cents` multiplied by
        the assessment ceiling of 350 basis points, divided by ten thousand and
        rounded half up — meaning the assessment takes the smaller of the raw amount
        and that ceiling."

        PRD 3.6: "Then floor the capped result at 8 cents, meaning take the larger
        of the capped result and 8."

        Design: Corner/calculations/calc_constants_applied_assessment_floor_lifts_charity_record_to_eight_cents
        """
        set_clock(CLOCK)
        platform = create_platform()
        acquirer = create_acquirer(platform["id"])
        create_mcc(
            "8398",
            "CHARITABLE",
            description="Charitable Organizations",
            program_eligibility=["CHARITY"],
            requires_documentation=True,
        )
        charity = create_rate_program(
            "CHARITY_STD",
            "CHARITY",
            ["8398"],
            name="Charity",
            base_rate_bps=100,
            per_item_fee_cents=0,
            requires_data_elements=["AUTH_CODE"],
            max_clearing_delay_hours=168,
        )
        _cps_retail_program(["8398"])
        _standard_program(["8398"])
        merchant = board_merchant(
            acquirer["id"], "CHARITABLE", legal_name="Harborlight Trust"
        )
        batch = open_batch(acquirer["id"], "2026-09-02", "USD")
        record = add_record(
            batch["id"],
            merchant["id"],
            200,
            acquirer["id"],
            expected_batch_version=batch["version"],
            auth_code="A00310",
            auth_timestamp="2026-09-02T00:00:00Z",
            clearing_timestamp="2026-09-02T01:00:00Z",
            data_elements=["AUTH_CODE"],
        )
        submit_batch(batch["id"], acquirer["id"])
        finalize_batch(batch["id"])

        priced = read_record(record["id"])
        assert priced["qualified_rate_program_id"] == charity["id"]
        assert priced["qualification_status"] == "QUALIFIED"
        assert priced["assessed_interchange_cents"] == 8
        assert priced["assessed_interchange_cents"] != 7
        assert read_batch(batch["id"])["total_assessed_cents"] == 8
        assert read_merchant(merchant["id"])["lifetime_net_assessed_cents"] == 8

    def test_an_exact_half_cent_ad_valorem_component_rounds_upward(self):
        """1000 cents at 145 basis points is exactly 14.5 cents, and half-up
        rounding of the ad-valorem component before the flat fee makes the
        assessment 25 rather than 24.

        PRD 2.7: "Wherever a division or a rate application would produce a
        fraction, the result is rounded **half up** — a remainder of exactly one half
        rounds away from zero to the next whole unit."

        PRD 3.6: "Step one is the ad-valorem component: multiply the record's
        `amount_cents` by the program's `base_rate_bps`, divide by ten thousand,
        round half up to whole cents, and then add the program's
        `per_item_fee_cents`."

        PRD 3.6: "The rounding happens *before* the flat fee is added, not after."

        Design: Corner/calculations/calc_precision_round_half_up_lifts_an_exact_half_cent_upward
        """
        env = _department_store_environment(CLOCK)
        merchant = board_merchant(
            env["acquirer_id"],
            "DEPARTMENT_STORE",
            legal_name="Marlow Department Store",
        )
        batch = open_batch(env["acquirer_id"], "2026-09-02", "USD")
        record = add_record(
            batch["id"],
            merchant["id"],
            1000,
            env["acquirer_id"],
            expected_batch_version=batch["version"],
            auth_code="A00320",
            auth_timestamp="2026-09-02T00:00:00Z",
            clearing_timestamp="2026-09-02T01:00:00Z",
            data_elements=FOUR_ELEMENTS,
        )
        assert record["provisional_assessed_cents"] == 25
        submit_batch(batch["id"], env["acquirer_id"])
        finalize_batch(batch["id"])

        priced = read_record(record["id"])
        assert priced["qualified_rate_program_id"] == env["cps"]["id"]
        assert priced["qualification_status"] == "QUALIFIED"
        assert priced["assessed_interchange_cents"] == 25
        assert priced["assessed_interchange_cents"] != 24
        assert read_batch(batch["id"])["total_assessed_cents"] == 25

    def test_the_cross_border_floor_overrides_a_smaller_bps_component(self):
        """A Canadian merchant on a US acquirer makes the record cross-border, and
        at 3000 cents the 40-basis-point component of 12 cents loses to the
        fifteen-cent floor, lifting the downgraded assessment to 101.

        PRD 3.5: "`cross_border` is true exactly when the merchant's
        `home_country_code` differs from the `country_code` of the acquirer that owns
        this record's batch — note the comparison reaches through the batch to its
        acquirer, and it is frozen at intake even if either country is later
        restated."

        PRD 3.6: "Step one is the ad-valorem component: multiply the record's
        `amount_cents` by the program's `base_rate_bps`, divide by ten thousand,
        round half up to whole cents, and then add the program's
        `per_item_fee_cents`."

        PRD 3.6: "Step two is the cross-border component: when the record's
        `cross_border` is true, `cross_border_surcharge_cents` is the larger of a
        fifteen-cent floor and the record's `amount_cents` multiplied by the
        cross-border rate of 40 basis points, divided by ten thousand and rounded
        half up; when `cross_border` is false it is 0."

        PRD 3.6: "Against that reference the service then applies five checks **in
        this fixed order**, stopping at the first one that fires: if any element of
        the reference's `requires_data_elements` is missing from the record's
        `data_elements`, the reason is `MISSING_DATA_ELEMENTS`; otherwise if the
        record's `clearing_delay_hours` is greater than the reference's
        `max_clearing_delay_hours`, the reason is `LATE_CLEARING`; otherwise if the
        reference's `category` is `SMALL_TICKET` and the record's `amount_cents`
        exceeds the small-ticket ceiling of 1500 cents, the reason is
        `TICKET_SIZE_INELIGIBLE`; otherwise if the record's `authorization_status` is
        anything other than `AUTH_APPROVED`, the reason is `AUTH_MISSING`; otherwise
        the reason is `MCC_INELIGIBLE`."

        Design: Corner/calculations/calc_constants_applied_cross_border_minimum_of_fifteen_cents_overrides_the_bps_component
        """
        env = _department_store_environment(CLOCK)
        merchant = board_merchant(
            env["acquirer_id"],
            "DEPARTMENT_STORE",
            legal_name="Maple Row Retail",
            home_country_code="CA",
        )
        batch = open_batch(env["acquirer_id"], "2026-09-02", "USD")
        record = add_record(
            batch["id"],
            merchant["id"],
            3000,
            env["acquirer_id"],
            expected_batch_version=batch["version"],
            auth_code="A00330",
            auth_timestamp="2026-09-02T00:00:00Z",
            clearing_timestamp="2026-09-02T01:00:00Z",
            data_elements=["AUTH_CODE"],
        )
        submit_batch(batch["id"], env["acquirer_id"])
        finalize_batch(batch["id"])

        priced = read_record(record["id"])
        assert priced["cross_border"] is True
        assert priced["cross_border_surcharge_cents"] == 15
        assert priced["fx_markup_cents"] == 0
        assert priced["qualified_rate_program_id"] == env["standard"]["id"]
        assert priced["qualification_status"] == "DOWNGRADED"
        assert priced["downgrade_reason"] == "MISSING_DATA_ELEMENTS"
        assert priced["assessed_interchange_cents"] == 101
        assert read_batch(batch["id"])["total_assessed_cents"] == 101


class TestDerivedIntakeFigures:
    def test_a_pending_record_is_counted_but_not_summed(self):
        """The provisional estimate sits on the record while the batch counts the
        row and books nothing, so an open batch reports one member against a zero
        total and the merchant's ledger has not moved.

        PRD 3.5: "Accepting the record advances `record_count` by 1 and advances
        `SettlementBatch.version` by 1; because the response body is the record rather
        than the batch, a client adding a second record must re-read the batch to learn
        its new version."

        PRD 3.5: "Neither figure is ever posted to any ledger:
        `qualification_status` stays `PENDING`, `assessed_interchange_cents` stays at
        its default of 0, and neither the batch total nor the merchant's lifetime
        figure moves."

        PRD 2.10: "At all times `SettlementBatch.total_assessed_cents` must equal
        the sum of `assessed_interchange_cents` over the transaction records belonging
        to that batch whose `qualification_status` is `QUALIFIED` or `DOWNGRADED`;
        records in `PENDING` or `REVERSED` contribute nothing."

        Design: Corner/calculations/calc_input_set_filtering_pending_records_are_excluded_from_the_batch_total
        """
        env = _department_store_environment(CLOCK)
        merchant = board_merchant(
            env["acquirer_id"],
            "DEPARTMENT_STORE",
            legal_name="Marlow Department Store",
        )
        batch = open_batch(env["acquirer_id"], "2026-09-02", "USD")
        record = add_record(
            batch["id"],
            merchant["id"],
            10000,
            env["acquirer_id"],
            expected_batch_version=batch["version"],
            auth_code="A00340",
            auth_timestamp="2026-09-02T00:00:00Z",
            clearing_timestamp="2026-09-02T01:00:00Z",
            data_elements=FOUR_ELEMENTS,
        )
        assert record["qualification_status"] == "PENDING"
        assert record["provisional_rate_program_id"] == env["cps"]["id"]
        assert record["provisional_assessed_cents"] == 155
        assert record["assessed_interchange_cents"] == 0

        stored = read_batch(batch["id"])
        assert stored["status"] == "OPEN"
        assert stored["record_count"] == 1
        assert stored["total_assessed_cents"] == 0
        assert read_merchant(merchant["id"])["lifetime_net_assessed_cents"] == 0

    def test_a_partial_hour_of_clearing_delay_is_discarded(self):
        """Ninety minutes of delay truncates to one hour and 23 hours 59 minutes
        truncates to 23, so neither record is pushed past the preferential tier's
        24-hour tolerance.

        PRD 2.7: "`TransactionRecord.clearing_delay_hours` is the whole number of
        complete hours between `auth_timestamp` and `clearing_timestamp`: take the
        elapsed seconds, divide by 3600, and discard any remainder toward zero."

        PRD 2.7: "A delay of 23 hours 59 minutes 59 seconds is therefore 23, not
        24."

        Design: Corner/calculations/calc_precision_clearing_delay_hours_floors_a_partial_hour_downward
        """
        env = _department_store_environment(CLOCK)
        merchant = board_merchant(
            env["acquirer_id"],
            "DEPARTMENT_STORE",
            legal_name="Marlow Department Store",
        )
        batch = open_batch(env["acquirer_id"], "2026-09-02", "USD")

        ninety_minutes = add_record(
            batch["id"],
            merchant["id"],
            10000,
            env["acquirer_id"],
            expected_batch_version=batch["version"],
            auth_code="A00350",
            auth_timestamp="2026-09-02T00:00:00Z",
            clearing_timestamp="2026-09-02T01:30:00Z",
            data_elements=FOUR_ELEMENTS,
        )
        almost_a_day = add_record(
            batch["id"],
            merchant["id"],
            10000,
            env["acquirer_id"],
            auth_code="A00351",
            auth_timestamp="2026-09-01T00:00:00Z",
            clearing_timestamp="2026-09-01T23:59:00Z",
            data_elements=FOUR_ELEMENTS,
        )

        assert ninety_minutes["clearing_delay_hours"] == 1
        assert ninety_minutes["clearing_delay_hours"] != 2
        assert almost_a_day["clearing_delay_hours"] == 23
        assert almost_a_day["clearing_delay_hours"] != 24
        assert ninety_minutes["provisional_rate_program_id"] == env["cps"]["id"]
        assert almost_a_day["provisional_rate_program_id"] == env["cps"]["id"]


class TestTierAndPenaltyBreakpoints:
    def test_a_gross_landing_exactly_on_the_first_breakpoint_earns_the_tier_one_credit(self):
        """A single record assessing to exactly 5000000 cents puts the gross
        precisely on the first inclusive breakpoint, so the enrollment resolves to
        the first tier and its 25-basis-point credit rather than to the untiered
        floor.

        PRD 3.8: "Under the `TRAILING` basis, `achieved_volume_cents` is the prior
        aggregate alone — volume booked in the current, still-incomplete quarter is
        discarded entirely, so only completed quarters count."

        PRD 3.8: "`performance_score_pct` is then the achieved volume multiplied by
        one hundred, divided by the enrollment's `committed_volume_cents`, rounded
        half up to two decimal places."

        PRD 3.8: "Second, `tier_code` is resolved from that gross figure and from
        nothing else: `TIER_3` when the gross reaches 50000000 cents, otherwise
        `TIER_2` when it reaches 20000000 cents, otherwise `TIER_1` when it reaches
        5000000 cents, otherwise `TIER_0`."

        PRD 3.8: "The breakpoints are inclusive lower bounds."

        PRD 3.8: "Third, `incentive_credit_cents` is the gross multiplied by the
        tier's discount in basis points — 0 for `TIER_0`, 25 for `TIER_1`, 60 for
        `TIER_2` and 100 for `TIER_3` — divided by ten thousand and rounded half up to
        whole cents."

        PRD 3.8: "Fourth, `net_assessed_volume_cents` is the gross minus the credit,
        as exact integer subtraction."

        Design: Corner/calculations/calc_tiered_pricing_gross_exactly_at_the_tier_one_floor_grants_twenty_five_bps
        """
        env = _department_store_environment("2026-05-01T00:00:00Z")
        merchant = board_merchant(
            env["acquirer_id"],
            "DEPARTMENT_STORE",
            legal_name="Marlow Department Store",
        )
        assert merchant["mcc_status"] == "VERIFIED"
        program = create_incentive_program(
            program_name="Q2 Volume Accelerator",
            eligible_mcc_codes=["5311"],
            total_capacity_cents=1000000000,
            min_commitment_cents=5000000,
            reopen_threshold_cents=5000000,
            performance_threshold_pct=80.00,
        )
        enrollment = enrol_merchant(
            program["id"],
            merchant["id"],
            5000000,
            env["acquirer_id"],
            expected_incentive_program_version=program["version"],
        )

        set_clock("2026-05-16T00:00:00Z")
        batch = open_batch(env["acquirer_id"], "2026-05-15", "USD")
        record = add_record(
            batch["id"],
            merchant["id"],
            196850000,
            env["acquirer_id"],
            expected_batch_version=batch["version"],
            auth_code="A00360",
            auth_timestamp="2026-05-15T00:00:00Z",
            clearing_timestamp="2026-05-15T02:00:00Z",
            data_elements=["AUTH_CODE"],
        )
        submit_batch(batch["id"], env["acquirer_id"])
        finalized = finalize_batch(batch["id"])
        assert finalized["total_assessed_cents"] == 5000000

        priced = read_record(record["id"])
        assert priced["qualified_rate_program_id"] == env["standard"]["id"]
        assert priced["assessed_interchange_cents"] == 5000000

        set_clock("2026-08-16T00:00:00Z")
        evaluate_enrollment(enrollment["id"], "TRAILING")

        scored = read_enrollment(enrollment["id"])
        assert scored["gross_assessed_volume_cents"] == 5000000
        assert scored["tier_code"] == "TIER_1"
        assert scored["incentive_credit_cents"] == 12500
        assert scored["net_assessed_volume_cents"] == 4987500
        assert scored["achieved_volume_cents"] == 196850000
        assert float(scored["performance_score_pct"]) == 3937.00
        assert scored["last_evaluated_basis"] == "TRAILING"
        assert scored["status"] == "ENROLLED"

    def test_a_thin_ledger_still_carries_the_minimum_misrepresentation_penalty(self):
        """Two 1200-cent downgrades leave a lifetime ledger of 80 cents, whose
        quarter is 20 cents, so the fifty-dollar minimum governs the penalty the
        sustained audit assesses.

        PRD 2.7: "The two orders genuinely differ: two records of 1200 cents each on
        a program of 254 basis points with a 10-cent per-item fee yield 30 plus 10 plus
        30 plus 10, a total of 80 cents under round-then-sum, whereas summing first and
        rounding once yields 81."

        PRD 3.9: "The audit advances `FIELDWORK → FINDINGS_SUSTAINED` and a penalty
        is assessed: `penalty_assessed_cents` is the larger of a fifty-dollar minimum
        of 5000 cents and the merchant's `lifetime_net_assessed_cents` multiplied by
        the misrepresentation penalty rate of 2500 basis points — a quarter of the
        ledger — divided by ten thousand and rounded half up to whole cents."

        PRD 3.9: "Hop one rewrites the merchant: `assigned_mcc` becomes the audited
        `correct_mcc` and `mcc_status` advances `UNDER_REVIEW → MISREPRESENTED`, which
        is terminal."

        Design: Corner/calculations/calc_correct_result_misrepresentation_penalty_is_lifted_to_the_minimum_floor
        """
        env = canonical_environment(CLOCK, mcc_codes=("5411", "7995"))
        acquirer_id = env["acquirer"]["id"]
        merchant = board_merchant(acquirer_id, "GROCERY", legal_name="Corner Grocer")
        batch = open_batch(acquirer_id, "2026-09-02", "USD")
        add_record(
            batch["id"],
            merchant["id"],
            1200,
            acquirer_id,
            expected_batch_version=batch["version"],
            auth_code="A00370",
            auth_timestamp="2026-09-02T00:00:00Z",
            clearing_timestamp="2026-09-02T01:00:00Z",
            data_elements=["AUTH_CODE"],
        )
        add_record(
            batch["id"],
            merchant["id"],
            1200,
            acquirer_id,
            auth_code="A00371",
            auth_timestamp="2026-09-02T00:00:00Z",
            clearing_timestamp="2026-09-02T01:00:00Z",
            data_elements=["AUTH_CODE"],
        )
        submit_batch(batch["id"], acquirer_id)
        finalized = finalize_batch(batch["id"])
        assert finalized["total_assessed_cents"] == 80
        assert read_merchant(merchant["id"])["lifetime_net_assessed_cents"] == 80

        audit = open_audit(merchant["id"], "COMPLAINT", auditor_user_id="auditor-1")
        assert audit["mcc_at_audit_open"] == "5411"
        start_fieldwork(
            audit["id"],
            "2026-09-03T09:00:00Z",
            "2026-09-03T17:00:00Z",
            auditor_user_id="auditor-1",
        )

        sustained = sustain_findings(
            audit["id"],
            "7995",
            auditor_user_id="auditor-1",
            findings_note="Merchant is a betting operator posing as a grocer.",
        )
        assert sustained["penalty_assessed_cents"] == 5000
        assert sustained["penalty_assessed_cents"] != 20

        stored = read_audit(audit["id"])
        assert stored["status"] == "FINDINGS_SUSTAINED"
        assert stored["correct_mcc"] == "7995"

        after = read_merchant(merchant["id"])
        assert after["assigned_mcc"] == "7995"
        assert after["mcc_status"] == "MISREPRESENTED"


class TestClockSweepComparisonEdges:
    def test_authorization_expiry_needs_strictly_more_than_the_validity_horizon(self):
        """Moving the clock 744 hours past one authorization expires it while a
        second sitting at exactly 720 hours survives, and neither record's
        qualification dimension moves.

        PRD 2.6: "**Step three** expires stale authorizations: every
        `TransactionRecord` whose `authorization_status` is `AUTH_APPROVED` and whose
        `qualification_status` is `PENDING` and whose age measured from
        `auth_timestamp` to the new clock value is strictly greater than 30 days — the
        authorization validity horizon is 720 hours — moves to `AUTH_EXPIRED`."

        PRD 3.5: "`qualification_status` is the second dimension and holds
        `PENDING`, `QUALIFIED`, `DOWNGRADED` or `REVERSED`; it opens at `PENDING`,
        moves only on batch finalization or on a clearing reversal, and is **never**
        moved by an authorization reversal or by authorization expiry."

        Design: Corner/calculations/calc_threshold_auth_expiry_fires_strictly_beyond_seven_hundred_twenty_hours
        """
        env = _department_store_environment("2026-09-02T12:00:00Z")
        merchant = board_merchant(
            env["acquirer_id"],
            "DEPARTMENT_STORE",
            legal_name="Marlow Department Store",
        )
        batch = open_batch(env["acquirer_id"], "2026-09-02", "USD")
        older = add_record(
            batch["id"],
            merchant["id"],
            10000,
            env["acquirer_id"],
            expected_batch_version=batch["version"],
            auth_code="A00380",
            auth_timestamp="2026-09-01T00:00:00Z",
            clearing_timestamp="2026-09-01T01:00:00Z",
            data_elements=FOUR_ELEMENTS,
        )
        newer = add_record(
            batch["id"],
            merchant["id"],
            10000,
            env["acquirer_id"],
            auth_code="A00381",
            auth_timestamp="2026-09-02T00:00:00Z",
            clearing_timestamp="2026-09-02T01:00:00Z",
            data_elements=FOUR_ELEMENTS,
        )

        set_clock("2026-10-02T00:00:00Z")

        expired = read_record(older["id"])
        assert expired["authorization_status"] == "AUTH_EXPIRED"
        assert expired["qualification_status"] == "PENDING"

        survivor = read_record(newer["id"])
        assert survivor["authorization_status"] == "AUTH_APPROVED"
        assert survivor["qualification_status"] == "PENDING"

        stored = read_batch(batch["id"])
        assert stored["status"] == "OPEN"
        assert stored["record_count"] == 2
        assert stored["total_assessed_cents"] == 0

    def test_a_version_ending_exactly_at_the_new_clock_is_superseded(self):
        """The supersession comparison is inclusive, so a version whose effective
        interval closes exactly at the new clock ages out while one closing a
        millisecond later stays published.

        PRD 2.6: "**Step one** supersedes rate versions: every
        `RateProgramVersion` in status `PUBLISHED` whose `effective_to` is at or before
        the new clock value moves to `SUPERSEDED`."

        PRD 2.6: "Note the deliberate asymmetry in the three comparisons: step one
        uses "at or before" against `effective_to`, step two uses strictly-earlier
        against `window_end`, and step three uses strictly-greater against the
        720-hour horizon."

        Design: Corner/calculations/calc_chronological_sweep_supersedes_a_version_exactly_at_its_effective_to
        """
        set_clock("2026-09-01T12:00:00Z")
        platform = create_platform()
        create_acquirer(platform["id"])
        create_mcc(
            "5311",
            "DEPARTMENT_STORE",
            description="Department Stores",
            program_eligibility=[],
        )
        _standard_program(["5311"])
        first_program = create_rate_program(
            "CPS_RETAIL_STD",
            "CPS_RETAIL",
            ["5311"],
            name="CPS Retail",
            base_rate_bps=145,
            per_item_fee_cents=10,
            requires_data_elements=["AUTH_CODE"],
            max_clearing_delay_hours=24,
        )
        second_program = create_rate_program(
            "SMALL_TICKET_STD",
            "SMALL_TICKET",
            ["5311"],
            name="Small Ticket",
            base_rate_bps=165,
            per_item_fee_cents=4,
            requires_data_elements=["AUTH_CODE"],
            max_clearing_delay_hours=48,
        )
        closing_on_the_hour = draft_rate_version(
            first_program["id"],
            "2026Q4",
            "2026-10-01T00:00:00Z",
            "2027-01-01T00:00:00.000Z",
            "2026-09-30T00:00:00Z",
            base_rate_bps=150,
            per_item_fee_cents=10,
        )
        closing_a_millisecond_later = draft_rate_version(
            second_program["id"],
            "2026Q4",
            "2026-10-01T00:00:00Z",
            "2027-01-01T00:00:00.001Z",
            "2026-09-30T00:00:00Z",
            base_rate_bps=170,
            per_item_fee_cents=4,
        )
        first_published = publish_rate_version(closing_on_the_hour["id"])
        second_published = publish_rate_version(closing_a_millisecond_later["id"])
        assert first_published["status"] == "PUBLISHED"
        assert second_published["status"] == "PUBLISHED"
        assert first_published["published_at"] == "2026-09-01T12:00:00.000Z"

        set_clock("2027-01-01T00:00:00Z")

        aged_out = validate_success(
            api_client.get_rate_program_version(
                closing_on_the_hour["id"], NETWORK_ADMIN
            )
        )
        still_live = validate_success(
            api_client.get_rate_program_version(
                closing_a_millisecond_later["id"], NETWORK_ADMIN
            )
        )
        assert aged_out["status"] == "SUPERSEDED"
        assert still_live["status"] == "PUBLISHED"
