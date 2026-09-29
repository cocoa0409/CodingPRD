"""Every declared formula evaluated on its own inputs.

Reported ratios are carried to four decimal places while the tests they support
are exact integer cross-multiplications; caps are floored and then compared; the
two exchange clocks run from a calendar date; and the exit's proceeds formula
branches on the mode alone.
"""

import pytest

from test_helpers import (
    CANONICAL_CAPITAL_STACK,
    CANONICAL_LOAN_METRICS,
    CANONICAL_OPERATING_TRUST,
    EXCHANGE_FILE_A,
    EXCHANGE_FILE_B,
    INVESTOR_A,
    INVESTOR_B,
    INVESTOR_E,
    QI,
    SPONSOR,
    TRUSTEE,
    api_client,
    create_exchange_file,
    create_identification_payload,
    create_investor,
    create_loan_facility,
    create_property,
    file_identification,
    list_ledger_entries,
    read_exchange_file,
    read_exit_event,
    read_loan_facility,
    read_property,
    read_trust,
    record_exit_consent,
    review_suitability,
    set_clock,
    setup_closed_exit,
    setup_offering_effective,
    setup_proposed_exit,
    setup_trust_forming,
    tally_consents,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestLoanRatiosReportedAtCommitment:
    def test_the_reported_leverage_reads_as_a_percentage(self):
        """720,000,000 of principal against a 1,200,000,000 appraisal.

        PRD: "The first is `ltv_pct`, the reported loan-to-value: the
        `principal_cents` multiplied by ten thousand, divided by the property's
        `appraised_value_cents`, rounded half up, and then divided by one
        hundred so the result reads as a percentage carried to four decimal
        places."

        Design: Corner/calculations/loan_dscr_and_ltv_reported_from_declared_constants
        """
        deal = setup_trust_forming()

        facility = create_loan_facility(deal["trust"]["id"])

        assert facility["status"] == "COMMITTED"
        assert facility["principal_cents"] == 720_000_000
        assert facility["ltv_pct"] == pytest.approx(
            CANONICAL_LOAN_METRICS["ltv_pct"], abs=0.0001
        )
        assert facility["repriced_count"] == 0
        assert facility["funded_at"] is None

    def test_the_reported_coverage_divides_noi_by_interest_only_debt_service(self):
        """425 basis points on 720,000,000 is 30,600,000 of annual service.

        PRD: "The reported `dscr` is the property's `annual_noi_cents`
        multiplied by ten thousand, divided by that annual debt service, rounded
        half up, and then divided by ten thousand so it reads to four decimal
        places."

        Design: Corner/calculations/loan_dscr_and_ltv_reported_from_declared_constants
        """
        deal = setup_trust_forming()

        facility = create_loan_facility(deal["trust"]["id"])

        assert facility["rate_bps"] == 425
        assert facility["dscr"] == pytest.approx(
            CANONICAL_LOAN_METRICS["dscr"], abs=0.0001
        )
        stored = read_loan_facility(facility["id"])
        assert stored["dscr"] == pytest.approx(
            CANONICAL_LOAN_METRICS["dscr"], abs=0.0001
        )


class TestSuitabilityCapIsTheMinimumOfThreeCaps:
    def test_the_deal_cap_governs_an_investor_with_ample_liquidity(self):
        """Sixty percent of 598,901,099 is the binding limb for investor A.

        PRD: "On `APPROVED` the `suitability_cap_cents` is the smallest of three
        caps, each computed by flooring — never by rounding half up — and then
        compared:"

        Design: Corner/calculations/investor_suitability_cap_takes_minimum_of_three_caps
        """
        deal = setup_offering_effective()
        investor = create_investor(**INVESTOR_A)

        reviewed = review_suitability(investor["id"], deal["offering"]["id"])

        assert reviewed["suitability_status"] == "APPROVED"
        assert reviewed["suitability_cap_cents"] == 359_340_659
        assert reviewed["suitability_offering_id"] == deal["offering"]["id"]
        assert reviewed["suitability_reviewed_by_user_id"] == "compliance-1"
        assert reviewed["accreditation_status"] == "UNVERIFIED"
        assert CANONICAL_CAPITAL_STACK["target_equity_cents"] == 598_901_099

    def test_the_liquidity_band_governs_a_thinner_self_certifying_investor(self):
        """Twenty-five percent of 200,000,000 undercuts both other limbs.

        PRD: "The **liquidity cap** is the investor's `liquid_net_worth_cents`
        multiplied by the concentration band its `entity_type` earns, floored."

        Design: Corner/calculations/investor_suitability_cap_takes_minimum_of_three_caps
        """
        deal = setup_offering_effective()
        investor = create_investor(**INVESTOR_E)

        reviewed = review_suitability(investor["id"], deal["offering"]["id"])

        assert reviewed["entity_type"] == "INDIVIDUAL"
        assert reviewed["accreditation_method"] == "SELF_CERT_INCOME"
        assert reviewed["suitability_status"] == "APPROVED"
        assert reviewed["suitability_cap_cents"] == 50_000_000
        assert reviewed["suitability_offering_id"] == deal["offering"]["id"]
        assert reviewed["accreditation_status"] == "UNVERIFIED"

    def test_a_declined_review_zeroes_the_cap_without_any_arithmetic(self):
        """No limb is evaluated, so the wealthiest investor is capped at zero.

        PRD: "On `DECLINED` the `suitability_cap_cents` is set to zero and no cap
        arithmetic is performed at all."

        Design: Corner/calculations/investor_suitability_declined_sets_cap_to_zero
        """
        deal = setup_offering_effective()
        investor = create_investor(**INVESTOR_A)

        reviewed = review_suitability(
            investor["id"], deal["offering"]["id"], "DECLINED"
        )

        assert reviewed["suitability_status"] == "DECLINED"
        assert reviewed["suitability_cap_cents"] == 0
        assert reviewed["suitability_offering_id"] == deal["offering"]["id"]
        assert reviewed["accreditation_status"] == "UNVERIFIED"


class TestExchangeFileDeadlineArithmetic:
    def test_both_clocks_run_from_the_relinquished_closing_date(self):
        """Two files closed five days apart carry deadlines five days apart.

        PRD: "The `identification_deadline` is forty-five days after that date,
        snapped to `23:59:59.999Z` on the forty-fifth day; the
        `exchange_deadline` is one hundred eighty days after that date, snapped
        to `23:59:59.999Z` on the one-hundred-eightieth day."

        Design: Corner/calculations/exchange_file_deadlines_45_and_180_days_from_relinquishment
        """
        set_clock("2026-08-20T00:00:00Z")
        investor = create_investor(**INVESTOR_A)

        early = create_exchange_file(
            investor["id"],
            qi_reference="QI-EARLY-2026",
            relinquished_closed_on="2026-08-05T00:00:00.000Z",
        )
        later = create_exchange_file(
            investor["id"],
            qi_reference="QI-LATER-2026",
            relinquished_closed_on="2026-08-10T00:00:00.000Z",
        )

        assert early["status"] == "OPEN"
        assert early["identification_deadline"] == "2026-09-19T23:59:59.999Z"
        assert early["exchange_deadline"] == "2027-02-01T23:59:59.999Z"

        assert later["status"] == "OPEN"
        assert later["identification_deadline"] == "2026-09-24T23:59:59.999Z"
        assert later["exchange_deadline"] == "2027-02-06T23:59:59.999Z"


class TestThreePropertyCapacityCountsActiveRowsOnly:
    def _file_with_three_active_rows(self) -> dict:
        set_clock("2026-08-20T00:00:00Z")
        properties = [
            create_property(name=f"Candidate {index}") for index in range(1, 5)
        ]
        investor = create_investor(**INVESTOR_A)
        exchange_file = create_exchange_file(investor["id"], **EXCHANGE_FILE_A)
        rows = [
            file_identification(exchange_file["id"], prop["id"])
            for prop in properties[:3]
        ]
        return {
            "properties": properties,
            "exchange_file": exchange_file,
            "identifications": rows,
        }

    def test_a_fourth_active_row_is_one_too_many(self):
        """Three is the whole candidate set the rule allows.

        PRD: "Under `THREE_PROPERTY` the filing is refused when that candidate
        set would hold more than three rows — a fourth active identification is
        one too many."

        Design: Corner/calculations/identification_rule_capacity_counts_only_active_identifications
        """
        ctx = self._file_with_three_active_rows()
        assert [row["sequence_no"] for row in ctx["identifications"]] == [1, 2, 3]
        assert read_exchange_file(ctx["exchange_file"]["id"])["status"] == "IDENTIFIED"

        response = api_client.create_identification(
            create_identification_payload(
                ctx["exchange_file"]["id"], ctx["properties"][3]["id"]
            ),
            QI,
        )
        validate_error(response, "ERR_IDENTIFICATION_RULE_VIOLATION", 422)

        _, meta = validate_paginated(
            api_client.list_identifications(
                QI, params={"exchange_file_id": ctx["exchange_file"]["id"]}
            )
        )
        assert meta["total_count"] == 3

    def test_revoking_a_row_frees_the_slot_it_was_holding(self):
        """A revoked row is invisible to the capacity test but keeps its place.

        PRD: "The new row is created in status `ACTIVE`, and only `ACTIVE` rows
        count for anything; a `REVOKED` row is invisible to every capacity
        test."

        Design: Corner/calculations/identification_rule_capacity_counts_only_active_identifications
        """
        ctx = self._file_with_three_active_rows()
        api_client.create_identification(
            create_identification_payload(
                ctx["exchange_file"]["id"], ctx["properties"][3]["id"]
            ),
            QI,
        )

        revoked = validate_success(
            api_client.revoke_identification(
                ctx["identifications"][1]["id"], QI, {"reason": "seller relisted"}
            )
        )
        assert revoked["status"] == "REVOKED"
        assert read_exchange_file(ctx["exchange_file"]["id"])["status"] == "IDENTIFIED"

        replacement = validate_success(
            api_client.create_identification(
                create_identification_payload(
                    ctx["exchange_file"]["id"], ctx["properties"][3]["id"]
                ),
                QI,
            ),
            201,
        )
        assert replacement["status"] == "ACTIVE"
        assert replacement["sequence_no"] == 4

        _, active_meta = validate_paginated(
            api_client.list_identifications(
                QI,
                params={
                    "exchange_file_id": ctx["exchange_file"]["id"],
                    "status": "ACTIVE",
                },
            )
        )
        assert active_meta["total_count"] == 3

        _, all_meta = validate_paginated(
            api_client.list_identifications(
                QI, params={"exchange_file_id": ctx["exchange_file"]["id"]}
            )
        )
        assert all_meta["total_count"] == 4


class TestTwoHundredPercentThreshold:
    def test_a_candidate_set_exactly_at_twice_the_relinquished_price_is_accepted(self):
        """Landing on the line is accepted; one cent above it is not.

        PRD: "Under `TWO_HUNDRED_PCT` the filing is refused when the candidate
        set's total `fair_market_value_cents`, multiplied by one hundred, would
        exceed the file's `relinquished_sale_price_cents` multiplied by two
        hundred; the test is an exact integer cross-multiplication, so a
        candidate set landing precisely at twice the relinquished sale price is
        accepted, and only a set above it is refused."

        Design: Corner/calculations/identification_two_hundred_pct_exactly_at_limit_then_one_cent_over_rejected
        """
        set_clock("2026-08-20T00:00:00Z")
        at_limit_property = create_property(name="Twice The Price")
        one_cent_property = create_property(name="One Cent Over")
        investor = create_investor(**INVESTOR_B)
        exchange_file = create_exchange_file(investor["id"], **EXCHANGE_FILE_B)
        assert exchange_file["identification_rule"] == "TWO_HUNDRED_PCT"
        assert exchange_file["relinquished_sale_price_cents"] == 600_000_000

        at_limit = validate_success(
            api_client.create_identification(
                create_identification_payload(
                    exchange_file["id"],
                    at_limit_property["id"],
                    fair_market_value_cents=1_200_000_000,
                ),
                QI,
            ),
            201,
        )
        assert at_limit["status"] == "ACTIVE"
        assert at_limit["sequence_no"] == 1
        assert read_exchange_file(exchange_file["id"])["status"] == "IDENTIFIED"

        over_limit = api_client.create_identification(
            create_identification_payload(
                exchange_file["id"],
                one_cent_property["id"],
                fair_market_value_cents=1,
            ),
            QI,
        )
        validate_error(over_limit, "ERR_IDENTIFICATION_RULE_VIOLATION", 422)

        _, meta = validate_paginated(
            api_client.list_identifications(
                QI,
                params={"exchange_file_id": exchange_file["id"], "status": "ACTIVE"},
            )
        )
        assert meta["total_count"] == 1


class TestConsentTallyAtTheThreshold:
    def _tally_at_exactly_one_half(self) -> dict:
        deal = setup_proposed_exit(exit_event={"consent_threshold_pct": 0.5})
        deal["consent_a"] = record_exit_consent(
            deal["exit_event"]["id"],
            deal["subscription_a"]["id"],
            deal["investor_a"]["id"],
            "CONSENT",
        )
        deal["exit_event"] = tally_consents(deal["exit_event"]["id"])
        return deal

    def test_three_hundred_of_six_hundred_units_meets_a_one_half_threshold(self):
        """Equality passes because the enforced test never rounds.

        PRD: "The enforced test is exact integer cross-multiplication and does
        not round: the `consented_units` multiplied by ten thousand must be at
        least the threshold in basis points — the `consent_threshold_pct`
        multiplied by ten thousand and rounded half up — multiplied by the
        trust's `units_issued`."

        Design: Corner/calculations/exit_consent_tally_exactly_at_threshold_approves
        """
        deal = self._tally_at_exactly_one_half()

        assert deal["exit_event"]["status"] == "APPROVED"
        assert deal["exit_event"]["consented_units"] == 300
        assert deal["exit_event"]["consent_pct"] == pytest.approx(0.5, abs=0.0001)
        assert read_exit_event(deal["exit_event"]["id"])["consented_units"] == 300

    def test_the_approved_tally_freezes_the_trust_without_arming_the_conversion(self):
        """An asset sale leaves the springing flag false.

        PRD: "A successful tally sets `consented_units` and `consent_pct` and
        reaches through to the trust: the trust moves `OPERATING →
        WINDING_DOWN`, its `springing_llc_armed` flag is set true when the
        `exit_mode` is `SECTION_721_CONVERSION` and false otherwise, and its
        `posture` is recomputed to `FROZEN` because an `APPROVED` exit event now
        exists on it."

        Design: Corner/calculations/exit_consent_tally_exactly_at_threshold_approves
        """
        deal = self._tally_at_exactly_one_half()

        trust = read_trust(deal["trust"]["id"])
        assert trust["status"] == "WINDING_DOWN"
        assert trust["posture"] == "FROZEN"
        assert trust["springing_llc_armed"] is False
        assert trust["units_issued"] == CANONICAL_OPERATING_TRUST["units_issued"]
        assert read_property(deal["property"]["id"])["status"] == "ACQUIRED"


class TestSectionSevenTwoOneCloseProceeds:
    def test_the_conversion_deducts_no_principal_and_writes_no_payoff_leg(self):
        """Gross minus selling costs, with the debt travelling with the asset.

        PRD: "Under **`SECTION_721_CONVERSION`** the asset is contributed
        *subject to* the existing debt, so no payoff occurs and the principal is
        **not** deducted: `net_proceeds_cents` is simply the `gross_price_cents`
        minus the `selling_costs_cents`."

        Design: Corner/calculations/exit_net_proceeds_section_721_variant_selected_by_exit_mode
        """
        deal = setup_closed_exit("SECTION_721_CONVERSION")

        event = deal["exit_event"]
        assert event["status"] == "CLOSED"
        assert event["net_proceeds_cents"] == 1_413_750_000
        assert event["net_proceeds_per_unit_cents"] == 2_356_250
        assert event["closed_at"] == "2027-03-01T00:00:00.000Z"

        assert list_ledger_entries(deal["trust"]["id"], entry_type="LOAN_PAYOFF") == []
        sale_legs = list_ledger_entries(
            deal["trust"]["id"], entry_type="SALE_PROCEEDS"
        )
        assert len(sale_legs) == 1
        assert sale_legs[0]["amount_cents"] == 1_413_750_000
        assert sale_legs[0]["bucket"] == "OPERATING"
        assert sale_legs[0]["source_kind"] == "EXIT"

        assert read_loan_facility(deal["loan"]["id"])["status"] == "PAID_OFF"
        assert read_property(deal["property"]["id"])["status"] == "DISPOSED"

        trust = read_trust(deal["trust"]["id"])
        assert trust["status"] == "CONVERTED_LLC"
        assert trust["springing_llc_armed"] is True

    def test_the_reserve_sweep_sets_the_liquidating_amount(self):
        """Everything left after the sale and the sweep becomes the declaration.

        PRD: "The reserve bucket is swept into operating as a two-legged pair: a
        `REVERSAL` entry in the `RESERVE` bucket for the negative of the trust's
        remaining `reserve_balance_cents`, with `reversal_of_entry_id` **empty**
        and `source_kind` `EXIT`, and an equal positive entry in the `OPERATING`
        bucket."

        Design: Corner/calculations/exit_net_proceeds_section_721_variant_selected_by_exit_mode
        """
        deal = setup_closed_exit("SECTION_721_CONVERSION")

        sweep_out = list_ledger_entries(
            deal["trust"]["id"], entry_type="REVERSAL", bucket="RESERVE"
        )
        assert len(sweep_out) == 1
        assert sweep_out[0]["amount_cents"] == -30_000_000
        assert sweep_out[0]["reversal_of_entry_id"] is None
        assert sweep_out[0]["source_kind"] == "EXIT"

        sweep_in = list_ledger_entries(
            deal["trust"]["id"], entry_type="REVERSAL", bucket="OPERATING"
        )
        assert len(sweep_in) == 1
        assert sweep_in[0]["amount_cents"] == 30_000_000

        trust = read_trust(deal["trust"]["id"])
        assert trust["reserve_balance_cents"] == 0
        assert trust["operating_balance_cents"] == 1_444_848_901

        rows, meta = validate_paginated(
            api_client.list_distributions(
                TRUSTEE, params={"trust_id": deal["trust"]["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["kind"] == "LIQUIDATING"
        assert rows[0]["status"] == "DECLARED"
        assert rows[0]["period_start"] == "2027-03-01T00:00:00.000Z"
        assert rows[0]["period_end"] == "2027-03-01T00:00:00.001Z"
        assert rows[0]["provisional_amount_cents"] == 1_444_848_901

    def test_one_successor_file_is_seeded_per_closed_subscription(self):
        """Each closed subscription's share of three figures, and two new clocks.

        PRD: "One successor exchange file is seeded per `CLOSED` subscription on
        the trust, taken in `closing_sequence_no` ascending order."

        Design: Corner/calculations/exit_net_proceeds_section_721_variant_selected_by_exit_mode
        """
        deal = setup_closed_exit("SECTION_721_CONVERSION")
        successors = sorted(deal["successor_files"], key=lambda row: row["qi_reference"])

        assert len(successors) == 2
        assert [row["qi_reference"] for row in successors] == [
            "SUCCESSOR-1",
            "SUCCESSOR-2",
        ]
        assert {row["investor_id"] for row in successors} == {
            deal["investor_a"]["id"],
            deal["investor_b"]["id"],
        }
        for row in successors:
            assert row["source_exit_event_id"] == deal["exit_event"]["id"]
            assert row["status"] == "OPEN"
            assert row["identification_rule"] == "THREE_PROPERTY"
            assert row["boot_tolerance_cents"] == 0
            assert row["relinquished_sale_price_cents"] == 725_000_000
            assert row["net_proceeds_cents"] == 722_424_451
            assert row["debt_retired_cents"] == 360_000_000
            assert row["identification_deadline"] == "2027-04-15T23:59:59.999Z"
            assert row["exchange_deadline"] == "2027-08-28T23:59:59.999Z"

        _, meta = validate_paginated(
            api_client.list_exchange_files(
                SPONSOR,
                params={
                    "source_exit_event_id": deal["exit_event"]["id"],
                    "limit": 100,
                },
            )
        )
        assert meta["total_count"] == 2
