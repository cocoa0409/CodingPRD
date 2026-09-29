"""Money that is booked but unpaid, and money that was never there to pay."""

from test_helpers import (
    OFFICER,
    OFFICER_THREE,
    ApiErrorId,
    accepted_report,
    licensed_quota,
    validate_error,
    validate_success,
)


class TestALicenceCannotBeClosedOverBookedButUnpaidRoyalties:
    """One accepted report worth 3500 cents, still unsettled."""

    def _accepted_and_unsettled(self, api):
        chain = licensed_quota(
            api, quality_tier="TIER_B", territory_class="DOMESTIC",
            allocated_units=5000, season_code="2026S1", basis="PER_PLANT",
            variety_overrides={
                "denomination": "Yewbrook Bramble",
                "species": "Rubus idaeus",
                "breeder_code": "YW",
                "base_royalty_cents_per_plant": 35,
                "base_royalty_cents_per_acre": 1200,
            },
            territory_codes=["US-WA"], propagator_name="Yewbrook Nursery",
            home_territory_code="US-WA",
        )
        chain.update(accepted_report(api, chain, 100))
        return chain

    def test_the_outstanding_amount_stands_on_both_the_report_and_the_ledger(self, api):
        """Acceptance books the amount and pushes it onto the propagator's payable,
        which is precisely the balance that has to be cleared before close-out.

        PRD 3.7: "`booked_amount_cents` is then `final_total_cents` plus `late_fee_cents`."

        Design: Corner/errors/terminating_with_an_accepted_unsettled_report_rejected
        """
        chain = self._accepted_and_unsettled(api)

        report = validate_success(api.get_royalty_report(chain["report_id"], OFFICER))
        assert report["review_status"] == "ACCEPTED"
        assert report["settlement_status"] == "UNSETTLED"
        assert report["booked_amount_cents"] == 3500
        assert validate_success(api.get_propagator(chain["propagator_id"], OFFICER))[
            "royalty_payable_cents"
        ] == 3500

    def test_termination_is_refused_and_no_cascade_runs(self, api):
        """The single financial condition blocks the terminal transition, and because
        it is refused outright neither the agreement nor its quota moves.

        PRD 3.5: "It is blocked by one financial condition: no royalty report of this agreement may be sitting with `review_status` `ACCEPTED` and `settlement_status` `UNSETTLED` at the same time."

        Design: Corner/errors/terminating_with_an_accepted_unsettled_report_rejected
        """
        chain = self._accepted_and_unsettled(api)

        validate_error(
            api.terminate_agreement(chain["agreement_id"], OFFICER),
            ApiErrorId.ERR_UNSETTLED_ROYALTY_OUTSTANDING.value,
            409,
        )

        assert validate_success(
            api.get_propagator_agreement(chain["agreement_id"], OFFICER)
        )["status"] == "ACTIVE"
        assert validate_success(api.get_production_quota(chain["quota_id"], OFFICER))[
            "status"
        ] == "ACTIVE"

    def test_settling_clears_the_block_and_the_close_out_cascade_then_runs(self, api):
        """It is the settlement dimension that gates close-out, so paying the booked
        amount unblocks the very same call, which closes the allocation beneath it.

        PRD 3.5: "On the quota branch, level one closes every production quota of the agreement whose status is `ACTIVE` or `FROZEN`, moving each to `CLOSED`; level two, caused by each closure, voids every tag order of that quota whose status is `REQUESTED`, setting each one's `voided_units` to its `requested_units`."

        Design: Corner/errors/terminating_with_an_accepted_unsettled_report_rejected
        """
        chain = self._accepted_and_unsettled(api)
        validate_error(
            api.terminate_agreement(chain["agreement_id"], OFFICER),
            ApiErrorId.ERR_UNSETTLED_ROYALTY_OUTSTANDING.value,
            409,
        )

        validate_success(api.settle_royalty_report(chain["report_id"], OFFICER_THREE))

        terminated = validate_success(
            api.terminate_agreement(chain["agreement_id"], OFFICER)
        )
        assert terminated["status"] == "TERMINATED"
        assert validate_success(api.get_production_quota(chain["quota_id"], OFFICER))[
            "status"
        ] == "CLOSED"


class TestAGenuineZeroPeriodIsAcceptableButNotSettleable:
    """A period with nothing produced: reported units 0, on time.
    """

    def _accepted_zero_report(self, api):
        chain = licensed_quota(
            api, quality_tier="TIER_B", territory_class="DOMESTIC",
            allocated_units=5000, season_code="2026S1", basis="PER_PLANT",
            variety_overrides={
                "denomination": "Ashgrove Bramble",
                "species": "Rubus idaeus",
                "breeder_code": "AG",
                "base_royalty_cents_per_plant": 35,
                "base_royalty_cents_per_acre": 1200,
            },
            territory_codes=["US-WA"], propagator_name="Ashgrove Nursery",
            home_territory_code="US-WA",
        )
        chain.update(accepted_report(api, chain, 0))
        return chain

    def test_the_zero_survives_acceptance_because_there_is_no_late_fee(self, api):
        """A zero-unit line is a legal declaration, and with the report on time no
        fee is added, so the audited total and the booked amount are both nothing.

        PRD 3.7: "When `is_late` is true, `late_fee_cents` is `final_total_cents` multiplied by 0.02, rounded half-up to whole cents; when `is_late` is false, `late_fee_cents` is 0."

        Design: Corner/errors/settling_a_report_with_a_zero_booked_amount_rejected
        """
        chain = self._accepted_zero_report(api)

        report = validate_success(api.get_royalty_report(chain["report_id"], OFFICER))
        assert report["review_status"] == "ACCEPTED"
        assert report["is_late"] is False
        assert report["final_total_cents"] == 0
        assert report["late_fee_cents"] == 0
        assert report["booked_amount_cents"] == 0

        line = validate_success(
            api.get_royalty_line_item(chain["line_item_id"], OFFICER)
        )
        assert line["billable_units"] == 0
        assert line["overrun_flagged"] is False
        assert line["final_amount_cents"] == 0

    def test_there_is_nothing_to_disburse_so_settlement_is_refused(self, api):
        """The booked amount must be strictly positive to be paid out, so this
        report cannot be settled and no payer is recorded against it.

        PRD 3.7: "Three conditions apply beyond the state itself: `review_status` must be `ACCEPTED`, `booked_amount_cents` must be strictly greater than 0 — a zero booked amount, including one zeroed by a dispute, has nothing to disburse and is rejected with `ERR_NOTHING_TO_SETTLE` (HTTP 422) — and the acting `X-User-ID` must differ from `accepted_by_user_id`, or the settlement is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/errors/settling_a_report_with_a_zero_booked_amount_rejected
        """
        chain = self._accepted_zero_report(api)

        validate_error(
            api.settle_royalty_report(chain["report_id"], OFFICER_THREE),
            ApiErrorId.ERR_NOTHING_TO_SETTLE.value,
            422,
        )

        report = validate_success(api.get_royalty_report(chain["report_id"], OFFICER))
        assert report["settlement_status"] == "UNSETTLED"
        assert report["settled_by_user_id"] is None

    def test_the_ledger_holds_at_zero_and_the_record_is_unblemished(self, api):
        """Both halves of the propagator's royalty ledger are nothing, and an on-time
        report with no overrun feeds the penalty set nothing at all.

        PRD 3.7: "Among those accepted reports, `royalty_payable_cents` is the sum of `booked_amount_cents` over the ones whose `settlement_status` is `UNSETTLED` or `REVERSED`, and `royalty_settled_cents` is the sum of `booked_amount_cents` over the ones whose `settlement_status` is `SETTLED`."

        Design: Corner/errors/settling_a_report_with_a_zero_booked_amount_rejected
        """
        chain = self._accepted_zero_report(api)
        validate_error(
            api.settle_royalty_report(chain["report_id"], OFFICER_THREE),
            ApiErrorId.ERR_NOTHING_TO_SETTLE.value,
            422,
        )

        propagator = validate_success(api.get_propagator(chain["propagator_id"], OFFICER))
        assert propagator["royalty_payable_cents"] == 0
        assert propagator["royalty_settled_cents"] == 0
        assert propagator["compliance_score"] == 100
