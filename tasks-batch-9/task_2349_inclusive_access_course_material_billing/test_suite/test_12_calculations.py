"""Arithmetic with every intermediate value pinned: the three-step per-student
price, the four-decimal proration ratio, the three-candidate opt-out deadline,
per-line rounding of the publisher share before summation, band selection across
the 2-to-3 edge, and the scoping of a reconciliation invoice.
"""

from test_helpers import (
    AccessStatus,
    ApiErrorId,
    BillingStatus,
    LedgerEntryType,
    LedgerReasonCode,
    OptOutRequestStatus,
    ReconciliationMethod,
    ReconciliationRunStatus,
    ReconciliationStatus,
    RegistrationType,
    SectionIaStatus,
    assert_charge_ledger_conserved,
    assert_money,
    assert_ratio,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

ONE_STUDENT = fixtures.DEFAULT_STUDENTS[:1]
LATE_ROSTER = (
    ("S-1002", "Ben Ortiz"),
    ("S-1003", "Cara Wu"),
    ("S-1004", "Dana Ek"),
)
LATE_DATES = ("2026-09-04", "2026-09-05", "2026-09-18")
SECOND_SECTION = {"section_number": "002", "instructor_user_id": "fac-2"}
HIST_SECTION = {
    "subject_code": "HIST",
    "catalog_number": "201",
    "section_number": "001",
    "instructor_user_id": "fac-3",
}
LARGE_ROSTER = (
    ("S-1003", "Cara Wu"),
    ("S-1004", "Dana Ek"),
    ("S-1005", "Eli Park"),
)
LATIMER_AGREEMENT = {
    "publisher_name": "Latimer Learning",
    "agreement_code": "PUB-B",
    "max_list_price_pct": 0.80,
}
MACRO_TITLE = {
    "isbn": "978-0-11-000003-0",
    "title": "Macro Foundations",
    "list_price_cents": 18000,
}


class TestDayOnePricingChain:
    """Tier 9000, fee 9450, cap 10800, floor 2500, proration 1.0000, share 8316."""

    def test_every_intermediate_of_the_three_step_price_lands_on_9450_and_8316(
            self, api, bursar_officer):
        """PRD §3.5: "Step three layers the commercial terms on the band's
        `per_student_price_cents`. The band price is multiplied by one plus the
        agreement's `admin_fee_pct` and the product is rounded half up to whole
        cents, giving the fee-inclusive price. Independently, a list-price cap is
        formed by multiplying the title's `list_price_cents` by the agreement's
        `max_list_price_pct` and discarding any fractional cent — rounding down,
        not half up. The system then takes the lesser of the fee-inclusive price
        and the list-price cap, and finally takes the greater of that result and
        the agreement's `price_floor_cents`." And: "`net_billed_cents` is always
        the signed sum of the charge's ledger movements, and
        `publisher_share_cents` is that net amount multiplied by one minus the
        agreement's `bookstore_margin_pct`, rounded half up to whole cents."

        Design: Corner/calculations/calc_day_one_charge_priced_prorated_and_shared
        """
        scenario = fixtures.setup_billed_section(
            api, setup_clock="2026-07-01T00:00:00Z", roster=ONE_STUDENT
        )
        assert len(scenario["charges"]) == 1

        charge = fixtures.read_charge(api, scenario["charge_ids"][0])
        # 9000 * 1.05 = 9450, under the cap floor(18000 * 0.60) = 10800 and over 2500.
        assert_money(charge["gross_price_cents"], 9450)
        assert_ratio(charge["proration_pct"], 1.0000)
        assert_money(charge["billed_amount_cents"], 9450)
        assert_money(charge["refunded_amount_cents"], 0)
        assert_money(charge["net_billed_cents"], 9450)
        assert_money(charge["publisher_share_cents"], 8316)
        assert charge["billing_status"] == BillingStatus.POSTED.value
        assert charge["access_status"] == AccessStatus.PROVISIONED.value
        assert charge["rebill_count"] == 0
        assert charge["posted_at"] == "2026-08-24T09:00:00.000Z"
        assert charge["access_start_at"] == "2026-08-24T09:00:00.000Z"
        assert charge["opt_out_deadline_at"] == "2026-09-04T23:59:59.999Z"

        entries, meta = validate_paginated(
            api.list_charge_ledger_entries(scenario["charge_ids"][0], bursar_officer)
        )
        assert meta["total_count"] == 1
        assert entries[0]["entry_type"] == LedgerEntryType.CHARGE.value
        assert entries[0]["reason_code"] == LedgerReasonCode.INITIAL_POST.value
        assert_money(entries[0]["amount_cents"], 9450)
        assert_charge_ledger_conserved(charge, entries)

        student = fixtures.read_student(api, scenario["student_ids"][0])
        assert_money(student["bursar_balance_cents"], 9450)

    def test_the_first_posting_freezes_the_basis_and_stamps_the_section(self, api):
        """PRD §3.5: "On the section's *first* successful posting the section moves
        `FLAGGED` → `BILLED`, which freezes `billing_basis_enrollment_count` to the
        `enrolled_count` observed in that request, stamps `first_posted_at`,
        recomputes `provisioned_access_count`, `revoked_access_count` and
        `participation_rate`, and increments the section's `version`."

        Design: Corner/calculations/calc_day_one_charge_priced_prorated_and_shared
        """
        scenario = fixtures.setup_billed_section(
            api, setup_clock="2026-07-01T00:00:00Z", roster=ONE_STUDENT
        )

        section = fixtures.read_section(api, scenario["section_id"])
        assert section["ia_status"] == SectionIaStatus.BILLED.value
        assert section["billing_basis_enrollment_count"] == 1
        assert section["first_posted_at"] == "2026-08-24T09:00:00.000Z"
        assert section["enrolled_count"] == 1
        assert section["provisioned_access_count"] == 1
        assert section["revoked_access_count"] == 0
        assert_ratio(section["participation_rate"], 1.0000)


class TestProrationAcrossTheAddDropAndCutoffBoundaries:
    """2026-09-04 pays in full, 2026-09-05 and 2026-09-18 do not, 2026-09-19 cannot."""

    @staticmethod
    def _billed_section_with_three_later_registrations(api):
        scenario = fixtures.setup_billed_section(
            api, setup_clock="2026-07-01T00:00:00Z", roster=ONE_STUDENT
        )
        peers = fixtures.create_students(api, LATE_ROSTER)
        fixtures.set_clock(api, "2026-09-18T08:00:00Z")

        later = []
        for peer, enrolled_on in zip(peers, LATE_DATES):
            # Each charge posts before the next registration arrives, so the
            # section's participation rate never dips below one half.
            enrollment = fixtures.create_enrollment(
                api, scenario["section_id"], peer["id"], enrolled_on
            )
            charge = fixtures.post_single_charge(api, enrollment["id"])
            later.append((enrollment, charge))

        scenario["later"] = later
        return scenario

    def test_the_ratio_is_rounded_to_four_decimals_before_it_multiplies(self, api):
        """PRD §3.5: "For a late registration, the system counts the elapsed days
        from the term's `term_start_date` to `enrolled_on`, which is 0 for a
        student registering on the first instructional day, subtracts that elapsed
        count from `total_term_days` to get the remaining days, divides the
        remaining days by `total_term_days`, and rounds that ratio half up to 4
        decimal places. The rounding order is pinned: the ratio is rounded to four
        decimals *first*, then `gross_price_cents` is multiplied by the rounded
        ratio, and only that product is rounded half up to whole cents to give
        `billed_amount_cents`."

        Design: Corner/calculations/calc_threshold_proration_at_add_drop_and_late_cutoff_boundaries
        """
        scenario = self._billed_section_with_three_later_registrations(api)
        (regular, regular_charge), (first_late, first_charge), (last_late, last_charge) = \
            scenario["later"]

        assert regular["registration_type"] == RegistrationType.REGULAR.value
        assert first_late["registration_type"] == RegistrationType.LATE.value
        assert last_late["registration_type"] == RegistrationType.LATE.value

        # 2026-09-04 is the add/drop deadline itself, so nothing is prorated.
        assert_ratio(regular_charge["proration_pct"], 1.0000)
        assert_money(regular_charge["gross_price_cents"], 9450)
        assert_money(regular_charge["billed_amount_cents"], 9450)
        assert_money(regular_charge["publisher_share_cents"], 8316)

        # Elapsed 12 of 110 days: round_half_up(98/110, 4) = 0.8909, and
        # round_half_up(9450 * 0.8909) = 8419 — never 8418.
        assert_ratio(first_charge["proration_pct"], 0.8909)
        assert_money(first_charge["gross_price_cents"], 9450)
        assert_money(first_charge["billed_amount_cents"], 8419)
        assert_money(first_charge["publisher_share_cents"], 7409)

        # Elapsed 25 of 110 days: 0.7727 and round_half_up(9450 * 0.7727) = 7302.
        assert_ratio(last_charge["proration_pct"], 0.7727)
        assert_money(last_charge["gross_price_cents"], 9450)
        assert_money(last_charge["billed_amount_cents"], 7302)
        assert_money(last_charge["publisher_share_cents"], 6426)

    def test_a_single_posting_names_the_registration_it_bills(self, api):
        """PRD §3.5: "On that transition the server appends a `CHARGE` ledger
        movement whose `amount_cents` equals `billed_amount_cents`, carrying
        `reason_code` `INITIAL_POST` for a batch posting and
        `LATE_REGISTRATION_POST` for a single posting of a late-registered
        enrollment (a single posting of a regular registration also carries
        `INITIAL_POST`); stamps `posted_at` from the logical clock; computes
        `opt_out_deadline_at`; advances `access_status` `NOT_PROVISIONED` →
        `PROVISIONED` and stamps `access_start_at`, which increments the section's
        `provisioned_access_count`; and recomputes the owning student's
        `bursar_balance_cents`."

        Design: Corner/calculations/calc_threshold_proration_at_add_drop_and_late_cutoff_boundaries
        """
        scenario = self._billed_section_with_three_later_registrations(api)
        expected = (
            LedgerReasonCode.INITIAL_POST.value,
            LedgerReasonCode.LATE_REGISTRATION_POST.value,
            LedgerReasonCode.LATE_REGISTRATION_POST.value,
        )

        for (_, charge), reason_code in zip(scenario["later"], expected):
            entries = fixtures.read_charge_ledger(api, charge["id"])
            assert len(entries) == 1
            assert entries[0]["entry_type"] == LedgerEntryType.CHARGE.value
            assert entries[0]["reason_code"] == reason_code
            assert_money(entries[0]["amount_cents"], charge["billed_amount_cents"])
            assert charge["access_status"] == AccessStatus.PROVISIONED.value
            assert charge["access_start_at"] == "2026-09-18T08:00:00.000Z"
            assert charge["posted_at"] == "2026-09-18T08:00:00.000Z"

    def test_the_cutoff_date_itself_registers_and_the_day_after_it_does_not(
            self, api, registrar):
        """PRD §3.4: "Second, `enrolled_on` must be on or before the term's
        `late_registration_cutoff_date`; a registration attempt past that date is
        rejected with `ERR_LATE_REGISTRATION_CLOSED`."

        Design: Corner/calculations/calc_threshold_proration_at_add_drop_and_late_cutoff_boundaries
        """
        scenario = fixtures.setup_billed_section(
            api, setup_clock="2026-07-01T00:00:00Z", roster=ONE_STUDENT
        )
        fixtures.set_clock(api, "2026-09-18T08:00:00Z")
        newcomer = fixtures.create_student(api, "S-1005", "Eli Park")

        response = api.create_enrollment(
            factories.enrollment_payload(
                scenario["section_id"], newcomer["id"], "2026-09-19"
            ),
            registrar,
        )
        validate_error(response, ApiErrorId.LATE_REGISTRATION_CLOSED.value)

        _, meta = validate_paginated(
            api.list_student_enrollments(newcomer["id"], registrar)
        )
        assert meta["total_count"] == 0

        # The cutoff date is inclusive.
        accepted = fixtures.create_enrollment(
            api, scenario["section_id"], newcomer["id"], "2026-09-18"
        )
        assert accepted["registration_type"] == RegistrationType.LATE.value

    def test_the_summary_totals_add_up_the_four_prorated_charges(self, api):
        """PRD §3.5: "It returns the `section_id`, the `ia_status`, the frozen
        `billing_basis_enrollment_count`, `tier_basis_posting_count` (the
        production basis — the frozen count actually used for pricing),
        `tier_basis_census_count` (the audit basis — the number of enrollments on
        the section whose `enrolled_on` is on or before the term's `census_date`
        and which are either still `ENROLLED` or whose `dropped_on` is later than
        the census date), `gross_per_student_posting_cents` and
        `gross_per_student_census_cents` (the per-student price the three-step
        pricing rule yields under each of those two bases), `charge_count`,
        `posted_charge_count`, `refunded_charge_count`, `total_net_billed_cents`,
        `total_publisher_share_cents`, `provisioned_access_count`,
        `revoked_access_count` and `participation_rate`."

        Design: Corner/calculations/calc_threshold_proration_at_add_drop_and_late_cutoff_boundaries
        """
        scenario = self._billed_section_with_three_later_registrations(api)

        summary = fixtures.read_billing_summary(api, scenario["section_id"])
        assert summary["section_id"] == scenario["section_id"]
        assert summary["ia_status"] == SectionIaStatus.BILLED.value
        assert summary["charge_count"] == 4
        assert summary["posted_charge_count"] == 4
        # 9450 + 9450 + 8419 + 7302 and 8316 + 8316 + 7409 + 6426.
        assert_money(summary["total_net_billed_cents"], 34621)
        assert_money(summary["total_publisher_share_cents"], 30467)
        assert summary["provisioned_access_count"] == 4
        assert summary["revoked_access_count"] == 0
        assert_ratio(summary["participation_rate"], 1.0000)

        section = fixtures.read_section(api, scenario["section_id"])
        assert section["enrolled_count"] == 4
        assert section["provisioned_access_count"] == 4
        assert_ratio(section["participation_rate"], 1.0000)
        assert section["ia_status"] == SectionIaStatus.BILLED.value


class TestOptOutDeadlineCandidateMerge:
    """All three candidates win in turn on one term, and the instant is inclusive."""

    @staticmethod
    def _day_one_charge_plus_a_charge_posted_before_add_drop(api):
        scenario = fixtures.setup_billed_section(
            api, setup_clock="2026-07-01T00:00:00Z", roster=ONE_STUDENT
        )
        peers = fixtures.create_students(api, fixtures.DEFAULT_STUDENTS[1:3])

        fixtures.set_clock(api, "2026-08-31T20:00:00Z")
        enrollment = fixtures.create_enrollment(
            api, scenario["section_id"], peers[0]["id"], "2026-08-31"
        )
        scenario["second_charge"] = fixtures.post_single_charge(api, enrollment["id"])
        scenario["peers"] = peers
        return scenario

    def test_the_cap_binds_on_day_one_and_the_floor_overrides_it_a_week_later(
            self, api):
        """PRD §3.5: "The nominal window end is the charge's `posted_at` advanced
        by the term's `opt_out_window_days` days. The add/drop cap is the term's
        `add_drop_deadline` at 23:59:59.999Z. The minimum-window floor is
        `posted_at` advanced by five days. The system first takes the earlier of
        the nominal window end and the add/drop cap, then takes the later of that
        intermediate result and the minimum-window floor."

        Design: Corner/calculations/calc_opt_out_deadline_add_drop_cap_then_minimum_floor
        """
        scenario = self._day_one_charge_plus_a_charge_posted_before_add_drop(api)

        # Posted 2026-08-24T09:00Z: min(2026-09-07T09:00Z, 2026-09-04T23:59:59.999Z)
        # then max with the floor 2026-08-29T09:00Z — the add/drop cap binds.
        day_one = fixtures.read_charge(api, scenario["charge_ids"][0])
        assert day_one["posted_at"] == "2026-08-24T09:00:00.000Z"
        assert day_one["opt_out_deadline_at"] == "2026-09-04T23:59:59.999Z"

        # Posted 2026-08-31T20:00Z: the cap is still the earlier ceiling, but the
        # five-day floor 2026-09-05T20:00Z is later and therefore wins.
        second = scenario["second_charge"]
        assert second["posted_at"] == "2026-08-31T20:00:00.000Z"
        assert second["opt_out_deadline_at"] == "2026-09-05T20:00:00.000Z"
        assert_money(second["gross_price_cents"], 9450)
        assert_ratio(second["proration_pct"], 1.0000)

    def test_a_late_charge_still_gets_five_days_and_the_instant_is_inclusive(
            self, api):
        """PRD §3.5: "When the charge posts on or after the add/drop deadline — the
        ordinary situation for a late registrant — the five-day floor is later than
        both other candidates and binds instead, guaranteeing every student at
        least five days to decline the material no matter how late the charge
        lands. A request arriving at an instant exactly equal to
        `opt_out_deadline_at` is inside the window and accepted."

        Design: Corner/calculations/calc_opt_out_deadline_add_drop_cap_then_minimum_floor
        """
        scenario = self._day_one_charge_plus_a_charge_posted_before_add_drop(api)

        # The day-one charge's own deadline instant, to the millisecond.
        fixtures.set_clock(api, "2026-09-04T23:59:59.999Z")
        request = fixtures.file_opt_out(
            api, scenario["charge_ids"][0], scenario["student_ids"][0], "OWNS_COPY"
        )
        assert request["status"] == OptOutRequestStatus.SUBMITTED.value

        fixtures.set_clock(api, "2026-09-08T10:00:00Z")
        enrollment = fixtures.create_enrollment(
            api, scenario["section_id"], scenario["peers"][1]["id"], "2026-09-08"
        )
        late = fixtures.post_single_charge(api, enrollment["id"])

        assert late["posted_at"] == "2026-09-08T10:00:00.000Z"
        assert late["opt_out_deadline_at"] == "2026-09-13T10:00:00.000Z"
        # Elapsed 15 of 110 days: 0.8636 and round_half_up(9450 * 0.8636) = 8161.
        assert_money(late["gross_price_cents"], 9450)
        assert_ratio(late["proration_pct"], 0.8636)
        assert_money(late["billed_amount_cents"], 8161)


class TestPublisherShareRoundedPerLine:
    """Two nets of 2405 invoice 4232, which is what separates the two orders."""

    @staticmethod
    def _two_identical_charges_dropped_after_add_drop(api):
        scenario = fixtures.setup_billed_section(api, setup_clock="2026-07-01T00:00:00Z")
        fixtures.set_clock(api, "2026-09-21T13:00:00Z")
        for enrollment_id in scenario["enrollment_ids"]:
            fixtures.drop_enrollment(api, enrollment_id, "2026-09-21")
        return scenario

    def test_two_shares_of_2116_invoice_4232_and_never_4233(self, api):
        """PRD §3.4: "Otherwise the system computes a retained share by counting
        the days from the term's `term_start_date` to `dropped_on`, dividing by
        `total_term_days` and rounding half up to 4 decimal places; multiplies the
        charge's `net_billed_cents` by one minus that rounded retained share;
        rounds half up to whole cents; and caps the result at `net_billed_cents` so
        the institution never over-refunds." PRD §3.8: "`billable_count` is the
        size of that set, and `gross_invoice_cents` is the sum of the included
        charges' `publisher_share_cents`, each already rounded to whole cents per
        §2.6."

        Design: Corner/calculations/calc_publisher_share_rounded_per_charge_before_summation
        """
        scenario = self._two_identical_charges_dropped_after_add_drop(api)

        for charge_id in scenario["charge_ids"]:
            charge = fixtures.read_charge(api, charge_id)
            assert_money(charge["gross_price_cents"], 9450)
            # Retained round_half_up(28/110, 4) = 0.2545, refund
            # round_half_up(9450 * 0.7455) = 7045, leaving net 2405.
            assert_money(charge["refunded_amount_cents"], 7045)
            assert_money(charge["net_billed_cents"], 2405)
            # round_half_up(2405 * 0.88) = round_half_up(2116.4) = 2116.
            assert_money(charge["publisher_share_cents"], 2116)
            assert charge["billing_status"] == BillingStatus.PARTIALLY_REFUNDED.value

        run = fixtures.create_reconciliation_run(
            api, scenario["agreement_id"], scenario["term_id"],
            publisher_reported_count=2, publisher_reported_amount_cents=4232,
        )
        assert run["billable_count"] == 2
        # Summing first would give round_half_up(4810 * 0.88) = 4233.
        assert_money(run["gross_invoice_cents"], 4232)
        assert run["opted_out_count"] == 0

    def test_the_rebate_threshold_is_tested_against_the_gross_invoice(self, api):
        """PRD §3.8: "Second, `rebate_cents` is `gross_invoice_cents` multiplied by
        the agreement's `rebate_pct` and rounded half up to whole cents when
        `gross_invoice_cents` is at or above the agreement's
        `rebate_threshold_cents`, and 0 when it is below that threshold — the
        threshold is tested against the *gross* invoice." And: "Fourth, the two
        variances against the publisher's own numbers: `count_variance` is
        `publisher_reported_count` minus `billable_count`, and `variance_cents` is
        `publisher_reported_amount_cents` minus `settlement_amount_cents`."

        Design: Corner/calculations/calc_publisher_share_rounded_per_charge_before_summation
        """
        scenario = self._two_identical_charges_dropped_after_add_drop(api)

        run = fixtures.create_reconciliation_run(
            api, scenario["agreement_id"], scenario["term_id"],
            publisher_reported_count=2, publisher_reported_amount_cents=4232,
        )
        assert run["status"] == ReconciliationRunStatus.COMPUTED.value
        assert run["method"] == ReconciliationMethod.ENROLLMENT_SNAPSHOT.value
        # 4232 sits below the 16500 threshold.
        assert_money(run["rebate_cents"], 0)
        assert_money(run["settlement_amount_cents"], 4232)
        assert run["count_variance"] == 0
        assert_money(run["variance_cents"], 0)

        agreement = fixtures.read_agreement(api, scenario["agreement_id"])
        assert agreement["reconciliation_status"] == ReconciliationStatus.COMPUTED.value

    def test_the_section_rollup_repeats_the_per_line_rounding(self, api):
        """PRD §3.5: "A `ProgramAdmin`, `BursarOfficer` or `ComplianceOfficer` may
        pull a purely derived, no-mutation summary of a section that exposes both
        valid tier bases side by side."

        Design: Corner/calculations/calc_publisher_share_rounded_per_charge_before_summation
        """
        scenario = self._two_identical_charges_dropped_after_add_drop(api)

        summary = fixtures.read_billing_summary(api, scenario["section_id"])
        assert_money(summary["total_net_billed_cents"], 4810)
        # 2116 + 2116, not round_half_up(4810 * 0.88).
        assert_money(summary["total_publisher_share_cents"], 4232)
        assert summary["provisioned_access_count"] == 0
        assert summary["revoked_access_count"] == 2
        assert_ratio(summary["participation_rate"], 0.0000)
        assert summary["billing_basis_enrollment_count"] == 2


class TestBandSelectionAtTheTwoToThreeEdge:
    """Adjacent bands, and a larger section that is cheaper per head."""

    @staticmethod
    def _two_sections_on_opposite_sides_of_the_edge(api):
        catalog = fixtures.setup_catalog(api, setup_clock="2026-07-01T00:00:00Z")
        small = fixtures.add_section(api, catalog)
        large = fixtures.add_section(api, catalog, section_overrides=SECOND_SECTION)

        fixtures.enroll_roster(api, small["section_id"],
                               fixtures.DEFAULT_STUDENTS[:2])
        fixtures.enroll_roster(api, large["section_id"], LARGE_ROSTER)

        fixtures.set_clock(api, "2026-08-24T09:00:00Z")
        small["charges"] = fixtures.post_section_charges(api, small["section_id"])
        large["charges"] = fixtures.post_section_charges(api, large["section_id"])
        return catalog, small, large

    def test_the_live_headcount_picks_the_band_and_one_more_head_lowers_the_price(
            self, api):
        """PRD §3.5: "Step one establishes the tier basis, a single enrollment
        count called *n*: if the section's `billing_basis_enrollment_count` is
        already set, *n* is that frozen number; otherwise *n* is the section's live
        `enrolled_count` as observed in this request. Step two selects the pricing
        band: among the bands of the adopted title, the system finds the one band
        whose `min_enrollment` is less than or equal to *n* and whose
        `max_enrollment` is either null or greater than or equal to *n*."

        Design: Corner/calculations/calc_tiered_pricing_band_selection_at_the_two_to_three_boundary
        """
        catalog, small, large = self._two_sections_on_opposite_sides_of_the_edge(api)

        # The two bands are adjacent, so neither was rejected as overlapping.
        assert catalog["tiers"][0]["max_enrollment"] == 2
        assert catalog["tiers"][1]["min_enrollment"] == 3
        assert catalog["tiers"][1]["max_enrollment"] is None

        assert len(small["charges"]) == 2
        for charge in small["charges"]:
            # n = 2 selects [1,2]: round_half_up(9000 * 1.05) = 9450.
            assert_money(charge["gross_price_cents"], 9450)
            assert_money(charge["billed_amount_cents"], 9450)
            assert_money(charge["publisher_share_cents"], 8316)

        assert len(large["charges"]) == 3
        for charge in large["charges"]:
            # n = 3 selects [3,null]: round_half_up(7500 * 1.05) = 7875.
            assert_money(charge["gross_price_cents"], 7875)
            assert_money(charge["billed_amount_cents"], 7875)
            assert_money(charge["publisher_share_cents"], 6930)

        # Identical title, identical list price, identical agreement parameters.
        assert small["charges"][0]["gross_price_cents"] > \
            large["charges"][0]["gross_price_cents"]

    def test_both_bases_agree_on_each_section_and_the_totals_are_not_monotone(
            self, api):
        """PRD §3.5: "The census basis exists precisely so an auditor can see what
        a section that crossed a band boundary between day one and the census date
        *would* have cost — identical stored data, a different band, a different
        per-student price."

        Design: Corner/calculations/calc_tiered_pricing_band_selection_at_the_two_to_three_boundary
        """
        _, small, large = self._two_sections_on_opposite_sides_of_the_edge(api)

        small_summary = fixtures.read_billing_summary(api, small["section_id"])
        assert small_summary["billing_basis_enrollment_count"] == 2
        assert small_summary["tier_basis_posting_count"] == 2
        assert small_summary["tier_basis_census_count"] == 2
        assert_money(small_summary["gross_per_student_posting_cents"], 9450)
        assert_money(small_summary["gross_per_student_census_cents"], 9450)
        assert_money(small_summary["total_net_billed_cents"], 18900)

        large_summary = fixtures.read_billing_summary(api, large["section_id"])
        assert large_summary["billing_basis_enrollment_count"] == 3
        assert large_summary["tier_basis_posting_count"] == 3
        assert large_summary["tier_basis_census_count"] == 3
        assert_money(large_summary["gross_per_student_posting_cents"], 7875)
        assert_money(large_summary["gross_per_student_census_cents"], 7875)
        assert_money(large_summary["total_net_billed_cents"], 23625)

        # Cheaper per head, dearer in total.
        assert large_summary["gross_per_student_census_cents"] < \
            small_summary["gross_per_student_census_cents"]
        assert large_summary["total_net_billed_cents"] > \
            small_summary["total_net_billed_cents"]


class TestReconciliationScope:
    """One term, two agreements, and one charge that was fully reversed by a drop."""

    @staticmethod
    def _two_agreements_billing_one_term_with_one_reversal(api):
        catalog = fixtures.setup_catalog(
            api, setup_clock="2026-07-01T00:00:00Z", bands=((1, 2, 9000),)
        )
        latimer = fixtures.create_agreement(api, **LATIMER_AGREEMENT)
        macro, _ = fixtures.create_priced_title(
            api, latimer["id"], ((1, None, 12000),), **MACRO_TITLE
        )
        latimer = fixtures.activate_agreement(api, latimer["id"])

        econ = fixtures.add_section(api, catalog)
        hist = fixtures.add_section(
            api, catalog, section_overrides=HIST_SECTION, title_id=macro["id"]
        )

        econ_roster = fixtures.enroll_roster(api, econ["section_id"],
                                             fixtures.DEFAULT_STUDENTS[:2])
        fixtures.enroll_roster(api, hist["section_id"],
                               fixtures.DEFAULT_STUDENTS[2:3])

        fixtures.set_clock(api, "2026-08-24T09:00:00Z")
        econ["charges"] = fixtures.post_section_charges(api, econ["section_id"])
        hist["charges"] = fixtures.post_section_charges(api, hist["section_id"])

        fixtures.set_clock(api, "2026-09-01T09:00:00Z")
        fixtures.drop_enrollment(api, econ_roster["enrollment_ids"][1], "2026-09-01")

        return {
            "term_id": catalog["term_id"],
            "northgate_id": catalog["agreement_id"],
            "latimer_id": latimer["id"],
            "econ": econ,
            "hist": hist,
        }

    def test_a_fully_reversed_charge_leaves_the_invoice_without_being_an_opt_out(
            self, api):
        """PRD §3.4: "The refund is computed per charge: if `dropped_on` is on or
        before the term's `add_drop_deadline`, the refund is the charge's full
        `net_billed_cents` — a clean reversal." PRD §3.8: "The included set is
        every in-scope charge whose `billing_status` is `POSTED`,
        `PARTIALLY_REFUNDED` or `REBILLED`." And: "`opted_out_count` on the run is
        the number of in-scope charges whose `billing_status` is `REFUNDED` and
        against which at least one opt-out request has reached `GRANTED`."

        Design: Corner/calculations/calc_reconciliation_scope_excludes_other_agreement_and_refunded_charges
        """
        scenario = self._two_agreements_billing_one_term_with_one_reversal(api)

        kept = fixtures.read_charge(api, scenario["econ"]["charges"][0]["id"])
        assert kept["billing_status"] == BillingStatus.POSTED.value
        assert_money(kept["publisher_share_cents"], 8316)

        reversed_charge = fixtures.read_charge(
            api, scenario["econ"]["charges"][1]["id"]
        )
        assert_money(reversed_charge["refunded_amount_cents"], 9450)
        assert_money(reversed_charge["net_billed_cents"], 0)
        assert_money(reversed_charge["publisher_share_cents"], 0)
        assert reversed_charge["billing_status"] == BillingStatus.REFUNDED.value
        assert reversed_charge["access_status"] == AccessStatus.REVOKED.value

        run = fixtures.create_reconciliation_run(
            api, scenario["northgate_id"], scenario["term_id"],
            publisher_reported_count=1, publisher_reported_amount_cents=8316,
        )
        assert run["billable_count"] == 1
        assert_money(run["gross_invoice_cents"], 8316)
        # The exclusion came from a drop, not from a granted opt-out.
        assert run["opted_out_count"] == 0
        assert_money(run["rebate_cents"], 0)
        assert_money(run["settlement_amount_cents"], 8316)
        assert_money(run["variance_cents"], 0)

    def test_neither_agreement_invoices_the_other_agreement_s_charges(self, api,
                                                                     program_admin):
        """PRD §3.8: "A run's scope is every charge that is priced by a title of
        the run's agreement — traced from the charge's `adoption_id` to that
        adoption's `title_id` and from the title to its `agreement_id` — and whose
        enrollment's section belongs to the run's term and carries
        `inclusive_access_flag` true."

        Design: Corner/calculations/calc_reconciliation_scope_excludes_other_agreement_and_refunded_charges
        """
        scenario = self._two_agreements_billing_one_term_with_one_reversal(api)

        # round_half_up(12000 * 1.05) = 12600, under the cap floor(18000 * 0.80).
        history = fixtures.read_charge(api, scenario["hist"]["charges"][0]["id"])
        assert_money(history["gross_price_cents"], 12600)
        assert_money(history["publisher_share_cents"], 11088)

        northgate_run = fixtures.create_reconciliation_run(
            api, scenario["northgate_id"], scenario["term_id"],
            publisher_reported_count=1, publisher_reported_amount_cents=8316,
        )
        latimer_run = fixtures.create_reconciliation_run(
            api, scenario["latimer_id"], scenario["term_id"],
            publisher_reported_count=1, publisher_reported_amount_cents=11088,
        )

        assert latimer_run["billable_count"] == 1
        assert_money(latimer_run["gross_invoice_cents"], 11088)
        assert_money(latimer_run["variance_cents"], 0)
        # 8316 + 11088 = 19404 is what a term-wide sweep would have invoiced.
        assert northgate_run["gross_invoice_cents"] != 19404
        assert latimer_run["gross_invoice_cents"] != 19404

        _, one_agreement = validate_paginated(
            api.list_reconciliation_runs(
                program_admin, {"agreement_id": scenario["latimer_id"]}
            )
        )
        assert one_agreement["total_count"] == 1
        _, whole_term = validate_paginated(
            api.list_reconciliation_runs(
                program_admin, {"term_id": scenario["term_id"]}
            )
        )
        assert whole_term["total_count"] == 2

        for agreement_id in (scenario["northgate_id"], scenario["latimer_id"]):
            agreement = validate_success(api.get_agreement(agreement_id, program_admin))
            assert agreement["reconciliation_status"] == \
                ReconciliationStatus.COMPUTED.value
