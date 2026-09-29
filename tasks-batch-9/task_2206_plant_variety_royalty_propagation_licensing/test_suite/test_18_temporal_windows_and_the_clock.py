"""Well-ordered intervals, containment in the licence term, and the clock itself."""

from test_helpers import (
    BREEDER,
    COORDINATOR,
    OFFICER,
    ApiErrorId,
    active_agreement,
    advance_clock,
    assert_instant_equals,
    create_filing,
    create_propagator,
    create_propagator_agreement_payload,
    create_royalty_report_payload,
    create_trial_site,
    create_variety,
    create_variety_trial_payload,
    pay_annuity_payload,
    schedule_annuity_payload,
    set_clock_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTheClockOnlyEverMovesForward:
    """Re-sending an instant would replay a sweep, so equality is refused too."""

    def test_resending_the_present_instant_is_refused(self, api):
        """The requested instant must be strictly later than the present value, so
        restating the instant just set is rejected rather than treated as a no-op.

        PRD 2.5: "That instant must be strictly later than the clock's present value; an equal or earlier instant is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422), which guarantees that a sweep already performed is never replayed."

        Design: Corner/validations/clock_set_to_an_earlier_or_equal_instant_rejected
        """
        advance_clock(api, "2026-09-15T00:00:00Z")

        validate_error(
            api.set_current_utc(set_clock_payload("2026-09-15T00:00:00Z"), BREEDER),
            ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value,
            422,
        )
        validate_error(
            api.set_current_utc(set_clock_payload("2026-08-20T00:00:00Z"), BREEDER),
            ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value,
            422,
        )

    def test_one_second_forward_is_enough_to_be_accepted(self, api):
        """Strictly later is the whole of the rule, so a single second's advance is
        accepted and the capability reports the instant it landed on.

        PRD 2.5: "The clock capability answers with the resulting `current_utc` plus four counters describing what the sweep did: `lapsed_filing_count`, `brand_renewal_due_count`, `expired_grant_count` and `compliance_recompute_count`."

        Design: Corner/validations/clock_set_to_an_earlier_or_equal_instant_rejected
        """
        advance_clock(api, "2026-09-15T00:00:00Z")

        body = validate_success(
            api.set_current_utc(set_clock_payload("2026-09-15T00:00:01Z"), BREEDER)
        )
        assert_instant_equals(body["current_utc"], "2026-09-15T00:00:01Z",
                              "current_utc")

    def test_the_startup_instant_cannot_be_set_on_a_fresh_database(self, api):
        """The clock already holds the startup value before anyone touches it, so
        setting exactly that value is an equal instant and is refused.

        PRD 2.5: "All temporal reasoning — lateness, grace windows, trial calendars, expiry — is evaluated against a server-held **logical clock** whose startup value is exactly `2026-08-01T00:00:00Z`."

        Design: Corner/validations/clock_set_to_an_earlier_or_equal_instant_rejected
        """
        validate_error(
            api.set_current_utc(set_clock_payload("2026-08-01T00:00:00Z"), BREEDER),
            ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value,
            422,
        )


class TestOccupancyAndTermWindowsMustBeNonEmpty:
    """Half-open windows have to contain at least one instant."""

    def _variety_and_site(self, api):
        variety = create_variety(
            api, denomination="Delphine Bramble", species="Rubus idaeus",
            breeder_code="DL", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        site = create_trial_site(api, site_name="Delphine Station", region_code="PNW",
                                 plot_capacity=60)
        return variety, site

    def test_a_harvest_before_the_planting_books_nothing(self, api):
        """A reversed occupancy window is rejected outright, and the site's booking
        calendar is left with no trial on it at all.

        PRD 3.4: "The window is **half-open**: `plant_date` is the inclusive start and `harvest_date` the exclusive end, and `harvest_date` must be strictly later than `plant_date` or the booking is rejected with `ERR_INVALID_INTERVAL`."

        Design: Corner/validations/trial_interval_with_harvest_before_plant_rejected
        """
        variety, site = self._variety_and_site(api)

        validate_error(
            api.create_variety_trial(
                create_variety_trial_payload(
                    variety["id"], site["id"], plot_count=10,
                    plant_date="2026-09-20T00:00:00Z",
                    harvest_date="2026-08-05T00:00:00Z",
                ),
                COORDINATOR,
            ),
            ApiErrorId.ERR_INVALID_INTERVAL.value,
            422,
        )

        _rows, meta = validate_paginated(api.list_variety_trials(COORDINATOR))
        assert meta["total_count"] == 0

    def test_equal_endpoints_are_refused_for_the_trial_and_for_the_term_alike(self, api):
        """Strictly later leaves no room for a zero-length window, and the same
        requirement governs the head licence term.

        PRD 3.5: "The term is half-open: `term_start` is the inclusive first instant and `term_end` the exclusive last, and `term_end` must be strictly later than `term_start` or the draft is rejected with `ERR_INVALID_INTERVAL`."

        Design: Corner/validations/trial_interval_with_harvest_before_plant_rejected
        """
        variety, site = self._variety_and_site(api)

        validate_error(
            api.create_variety_trial(
                create_variety_trial_payload(
                    variety["id"], site["id"], plot_count=10,
                    plant_date="2026-09-20T00:00:00Z",
                    harvest_date="2026-09-20T00:00:00Z",
                ),
                COORDINATOR,
            ),
            ApiErrorId.ERR_INVALID_INTERVAL.value,
            422,
        )

        propagator = create_propagator(api, legal_name="Delphine Nursery",
                                       home_territory_code="US-WA")
        validate_error(
            api.create_propagator_agreement(
                create_propagator_agreement_payload(
                    propagator["id"], territory_codes=["US-WA"],
                    term_start="2026-08-01T00:00:00Z",
                    term_end="2026-08-01T00:00:00Z",
                ),
                OFFICER,
            ),
            ApiErrorId.ERR_INVALID_INTERVAL.value,
            422,
        )


class TestTheReportPeriodMustSitInsideTheLicenceTerm:
    """An agreement running 2026-08-01 to 2027-08-01, and periods around it."""

    def _active_agreement(self, api):
        return active_agreement(
            api, quality_tier="TIER_B", territory_codes=["US-WA"],
            propagator_name="Fernwood Nursery", home_territory_code="US-WA",
        )

    def test_a_period_starting_before_the_term_is_refused(self, api):
        """A period reaching back before the licence began is not containable, and
        the rejection leaves no report behind.

        PRD 3.7: "Separately the period must sit inside the licence term: `period_start` must be at or after the agreement's `term_start` and `period_end` must be at or before its `term_end`, and a period straying outside is rejected with `ERR_PERIOD_OUTSIDE_TERM` (HTTP 422)."

        Design: Corner/validations/report_period_outside_the_agreement_term_rejected
        """
        chain = self._active_agreement(api)

        validate_error(
            api.create_royalty_report(
                create_royalty_report_payload(
                    chain["agreement_id"], period_code="2026Q2",
                    period_start="2026-07-01T00:00:00Z",
                    period_end="2026-10-01T00:00:00Z",
                    due_at="2026-10-15T00:00:00Z",
                ),
                chain["propagator_headers"],
            ),
            ApiErrorId.ERR_PERIOD_OUTSIDE_TERM.value,
            422,
        )

        _rows, meta = validate_paginated(api.list_royalty_reports(OFFICER))
        assert meta["total_count"] == 0

    def test_the_containment_is_inclusive_at_the_start_of_the_term(self, api):
        """A period beginning at exactly `term_start` is inside the term, so the
        report opens normally.

        PRD 3.7: "A new report begins with `review_status` `DRAFT`, `settlement_status` `UNSETTLED`, `is_late` false, `revision_no` 0, `submitted_at`, `accepted_at`, `accepted_by_user_id` and `settled_by_user_id` all null, all four money fields — `provisional_total_cents`, `final_total_cents`, `late_fee_cents` and `booked_amount_cents` — at 0, and `version` 1."

        Design: Corner/validations/report_period_outside_the_agreement_term_rejected
        """
        chain = self._active_agreement(api)

        report = validate_success(
            api.create_royalty_report(
                create_royalty_report_payload(
                    chain["agreement_id"], period_code="2026Q3",
                    period_start="2026-08-01T00:00:00Z",
                    period_end="2026-11-01T00:00:00Z",
                    due_at="2026-11-15T00:00:00Z",
                ),
                chain["propagator_headers"],
            ),
            201,
        )
        assert report["review_status"] == "DRAFT"
        assert report["version"] == 1

    def test_the_check_binds_at_the_far_end_and_the_deadline_rule_is_separate(self, api):
        """A period running past `term_end` is refused by the containment rule,
        while a deadline falling before the period even closes breaks the
        well-orderedness rule instead and carries its own code.

        PRD 3.7: "Three temporal rules apply together: `period_end` must be strictly later than `period_start`, and `due_at` must be at or after `period_end` — violating either is rejected with `ERR_INVALID_INTERVAL` (HTTP 422)."

        Design: Corner/validations/report_period_outside_the_agreement_term_rejected
        """
        chain = self._active_agreement(api)

        validate_error(
            api.create_royalty_report(
                create_royalty_report_payload(
                    chain["agreement_id"], period_code="2027Q3",
                    period_start="2027-06-01T00:00:00Z",
                    period_end="2027-09-01T00:00:00Z",
                    due_at="2027-09-15T00:00:00Z",
                ),
                chain["propagator_headers"],
            ),
            ApiErrorId.ERR_PERIOD_OUTSIDE_TERM.value,
            422,
        )
        validate_error(
            api.create_royalty_report(
                create_royalty_report_payload(
                    chain["agreement_id"], period_code="2026Q4",
                    period_start="2026-08-01T00:00:00Z",
                    period_end="2026-11-01T00:00:00Z",
                    due_at="2026-10-01T00:00:00Z",
                ),
                chain["propagator_headers"],
            ),
            ApiErrorId.ERR_INVALID_INTERVAL.value,
            422,
        )


class TestTheGraceBoundaryAndWhatLiesOneSecondPastIt:
    """An instalment due 2026-09-01 with 90 grace days, watched at the edge."""

    def _filing_in_maintenance(self, api):
        variety = create_variety(
            api, denomination="Harrow Bramble", species="Rubus idaeus",
            breeder_code="HR", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        filing = create_filing(
            api, variety["id"], instrument_type="PLANT_PATENT",
            jurisdiction_code="US", annuity_base_cents=200000,
        )
        validate_success(api.file_protection_filing(filing["id"], BREEDER))
        validate_success(api.grant_protection_filing(filing["id"], BREEDER))
        validate_success(
            api.schedule_annuity(
                filing["id"],
                schedule_annuity_payload(annuity_due_date="2026-09-01T00:00:00Z",
                                         annuity_grace_days=90),
                BREEDER,
            )
        )
        return variety, filing

    def test_at_exactly_the_boundary_the_filing_is_still_maintainable(self, api):
        """The boundary instant is inside the window, so the filing has not lapsed
        and the payment is judged on its amount, which here is wrong.

        PRD 3.2: "The boundary is **inclusive**: a payment landing at exactly that instant is accepted, and the very next instant is not."

        Design: Corner/validations/annuity_grace_check_runs_before_the_annuity_amount_check
        """
        _variety, filing = self._filing_in_maintenance(api)

        advance_clock(api, "2026-11-30T00:00:00Z")

        assert validate_success(api.get_protection_filing(filing["id"], BREEDER))[
            "status"
        ] == "MAINTENANCE_DUE"
        validate_error(
            api.pay_annuity(filing["id"], pay_annuity_payload(1), BREEDER),
            ApiErrorId.ERR_ANNUITY_AMOUNT_MISMATCH.value,
            422,
        )

    def test_one_second_later_the_sweep_has_already_taken_the_filing(self, api):
        """Advancing strictly beyond the boundary lapses the filing on the way in,
        so a payment then finds the record in a terminal state of the machine it
        drives and is told so by the specific terminal code.

        PRD 2.8: "The terminal states are: a `RETIRED` variety lifecycle; a `BRAND_ABANDONED` brand; a filing that is `LAPSED` or `ABANDONED`; a trial that is `PASSED` or `FAILED`; a `TERMINATED` agreement; a `CLOSED` quota; a tag order that is `RECONCILED` or `VOIDED`; a report whose settlement dimension is `REVERSED`, for settlement actions; a grant that is `REVOKED` or `EXPIRED`; a `RESOLVED` surveillance case; and an audit engagement that is `FINDINGS_ISSUED` or `CLOSED_NO_FINDING`."

        Design: Corner/validations/annuity_grace_check_runs_before_the_annuity_amount_check
        """
        variety, filing = self._filing_in_maintenance(api)
        advance_clock(api, "2026-11-30T00:00:00Z")

        advance_clock(api, "2026-11-30T00:00:01Z")

        lapsed = validate_success(api.get_protection_filing(filing["id"], BREEDER))
        assert lapsed["status"] == "LAPSED"
        assert lapsed["lapse_reason"] == "GRACE_EXPIRED"
        validate_error(
            api.pay_annuity(filing["id"], pay_annuity_payload(1), BREEDER),
            ApiErrorId.ERR_TERMINAL_STATE.value,
            409,
        )
        assert validate_success(api.get_variety(variety["id"], BREEDER))[
            "protection_posture"
        ] == "LAPSED_PROTECTION"

    def test_no_rejected_payment_ever_records_an_instalment(self, api):
        """Refusals are total rather than partial, so the maintenance record shows
        no instalment paid and no amount computed onto it.

        PRD 3.2: "If `paid_amount_cents` differs from that figure in either direction, the payment is rejected with `ERR_ANNUITY_AMOUNT_MISMATCH` (HTTP 422)."

        Design: Corner/validations/annuity_grace_check_runs_before_the_annuity_amount_check
        """
        _variety, filing = self._filing_in_maintenance(api)
        advance_clock(api, "2026-11-30T00:00:00Z")
        validate_error(
            api.pay_annuity(filing["id"], pay_annuity_payload(1), BREEDER),
            ApiErrorId.ERR_ANNUITY_AMOUNT_MISMATCH.value,
            422,
        )

        unchanged = validate_success(api.get_protection_filing(filing["id"], BREEDER))
        assert unchanged["installments_paid_count"] == 0
        assert unchanged["annuity_total_due_cents"] == 0
