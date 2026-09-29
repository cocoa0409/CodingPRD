"""Endpoint corners: the reconciliation view, the batch, filters and links.

These endpoints are the ones whose contract lives in their response shape
rather than in a single stored row — the summary that must publish both sides
of both invariants, the batch that must be safe to run twice, the list that
must compose three filters with a page window, and the two action endpoints
whose behaviour is conditional on state the request body never mentions.
"""

import pytest

from test_helpers import (
    COLLATERAL_ANALYST,
    CONTENT_TYPE_ONLY,
    CREDIT_OFFICER,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    make_investor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as asserts
from test_helpers import fixtures as fx


def _ledger_page(facility_id, **params):
    """One page of the facility ledger together with its pagination `meta`."""
    return validate_paginated(
        api_client.list_facility_ledger_entries(
            facility_id, CREDIT_OFFICER, params or None
        )
    )


# ─── The reconciliation view ──────────────────────────────────────────────────

def _one_live_advance_and_one_purchased_advance():
    """A1 stays on the book; AE2 is funded, shipped and settled the same day.

    Both advances post an `ADVANCE_FUNDED` debit, so the purchased one keeps
    its footprint in the ledger totals while dropping out of both outstanding
    figures.
    """
    scenario = fx.setup_funded_dry_advance()
    scenario.exited_advance = fx.book_and_fund_additional_advance(
        scenario,
        investor_commitment_id=scenario.commitment["id"],
        callback_reference="CB-810",
        loan_amount_cents=1_000_000_000,
        note_rate=0.0625,
    )
    fx.ship_advance(scenario.exited_advance["id"], scenario.investor["id"])
    scenario.exited_advance = fx.purchase_advance(
        scenario.exited_advance["id"],
        scenario.investor["id"],
        proceeds_reference="WIRE-IN-8810",
    )
    return scenario


class TestExposureSummary:
    def test_one_read_publishes_both_sides_of_both_conservation_invariants(self):
        """A settled advance leaves the ledger totals but not the balances.

        PRD 2.6: "The first is a ledger invariant: `outstanding_principal_cents`
        equals `ledger_debit_total_cents` minus `ledger_credit_total_cents`,
        where those two figures are the debit and credit sums of `amount_cents`
        over the facility's principal-moving entries."

        PRD 2.6: "The second is an aggregation invariant:
        `outstanding_principal_cents` equals `advance_outstanding_sum_cents`, the
        sum of `outstanding_balance_cents` over the facility's advances whose
        `funding_status` is `FUNDED` or `SHIPPED`."

        PRD 3.7: "The facility's `outstanding_principal_cents` and
        `availability_cents` are re-projected; the commitment moves the amount
        from `allocated_amount_cents` into `settled_amount_cents`, leaving
        `remaining_amount_cents` untouched and its status at
        `PARTIALLY_ALLOCATED` when remaining capacity is still positive; and the
        investor's `exposure_cents` drops by the settled amount."

        Design: Corner/endpoints/corner_ep_exposure_summary_projects_both_conservation_invariants
        """
        scenario = _one_live_advance_and_one_purchased_advance()
        facility_id = scenario.facility["id"]
        assert scenario.exited_advance["funding_status"] == "PURCHASED"
        assert scenario.exited_advance["outstanding_balance_cents"] == 0

        version_before_read = fx.read_facility(facility_id)["version"]
        summary = fx.read_exposure_summary(facility_id)

        assert summary["facility_id"] == facility_id
        assert summary["committed_amount_cents"] == 20_000_000_000
        # Only A1 is still drawn against the line.
        assert summary["outstanding_principal_cents"] == 1_960_000_000
        assert summary["availability_cents"] == 18_040_000_000
        asserts.assert_availability_projection(summary)
        # No aging run has ever run, so nothing has accrued.
        assert summary["accrued_fee_balance_cents"] == 0
        assert summary["wet_outstanding_cents"] == 0
        assert summary["aged_outstanding_cents"] == 0
        assert summary["scratch_and_dent_outstanding_cents"] == 0

        # 1,960,000,000 + 980,000,000: the settled advance's debit is never removed.
        assert summary["ledger_debit_total_cents"] == 2_940_000_000
        # The single INVESTOR_PROCEEDS credit.
        assert summary["ledger_credit_total_cents"] == 980_000_000
        assert summary["advance_outstanding_sum_cents"] == 1_960_000_000
        asserts.assert_both_conservation_invariants(summary)
        assert summary["open_margin_call_count"] == 0

        exposures = summary["investor_exposures"]
        assert len(exposures) == 1
        assert exposures[0]["investor_id"] == scenario.investor["id"]
        # The purchase released 980,000,000 of the 2,940,000,000 allocated.
        assert exposures[0]["exposure_cents"] == 1_960_000_000

        commitment = fx.read_commitment(scenario.commitment["id"])
        assert commitment["allocated_amount_cents"] == 1_960_000_000
        assert commitment["settled_amount_cents"] == 980_000_000
        assert commitment["remaining_amount_cents"] == 2_060_000_000
        assert commitment["status"] == "PARTIALLY_ALLOCATED"
        asserts.assert_commitment_capacity_conserved(commitment)

        # The reconciliation view is a projection, not a write.
        assert fx.read_facility(facility_id)["version"] == version_before_read


# ─── The nightly batch ────────────────────────────────────────────────────────

class TestAgingRunIdempotence:
    def test_a_second_run_at_the_same_instant_walks_the_book_and_changes_nothing(self):
        """Skip-not-fail: the advance is still evaluated, but nothing accrues twice.

        PRD 3.9: "First it refreshes `dwell_days` and `is_aged` for every advance
        of the facility whose `funding_status` is `FUNDED` or `SHIPPED`, and the
        count of those advances is what `advances_evaluated` reports."

        PRD 3.9: "That accrual rule is what makes the whole job idempotent at a
        single clock instant."

        PRD 3.9: "A second run at the same logical clock value finds
        `accrual_days` at zero, so it accrues nothing and writes no fee entry;
        it also issues no duplicate margin call, because every advance that
        needed one received it on the first pass and now has an open call."

        Design: Corner/endpoints/corner_ep_aging_run_is_idempotent_within_one_clock_instant
        """
        scenario = fx.setup_shipped_advance()
        facility_id = scenario.facility["id"]
        advance_id = scenario.advance["id"]
        letter = scenario.bailee_letter
        asserts.assert_instant(letter["expires_at"], "2026-08-31T00:00:00Z")

        # Thirty-five days of dwell against a dwell limit of thirty.
        fx.set_clock("2026-09-05T00:00:00Z")
        first = fx.run_aging(facility_id)
        asserts.assert_aging_run_summary(first)

        assert first["advances_evaluated"] == 1
        assert first["accrual_days"] == 35
        # 16,673,611 of interest at 0.0650 + 0.0225 on a 360-day basis, plus
        # 4,384,722 of unused-line fee on the undrawn 18,040,000,000.
        assert first["fee_accrual_cents"] == 21_058_333
        assert first["margin_calls_issued"] == 1
        assert first["bailee_letters_expired"] == 1
        assert first["repurchase_demands_raised"] == 1
        assert first["curtailed_advance_ids"] == [advance_id]

        advance = fx.read_advance(advance_id)
        assert advance["dwell_days"] == 35
        assert advance["is_aged"] is True
        # One curtailment step for ceil(5 / 15) takes 0.98 down to 0.975.
        assert advance["effective_advance_rate"] == pytest.approx(0.975, abs=1e-6)
        assert advance["eligible_collateral_value_cents"] == 1_950_000_000
        assert advance["required_paydown_cents"] == 10_000_000

        calls = fx.advance_margin_calls(advance_id)
        assert len(calls) == 1
        assert calls[0]["trigger_reason"] == "DWELL_EXCEEDED"
        assert calls[0]["call_amount_cents"] == 10_000_000
        assert calls[0]["status"] == "ISSUED"

        expired_letter = fx.advance_bailee_letters(advance_id)[-1]
        assert expired_letter["id"] == letter["id"]
        assert expired_letter["status"] == "EXPIRED"

        demands, demand_meta = validate_paginated(
            api_client.list_advance_repurchase_demands(advance_id, CREDIT_OFFICER)
        )
        assert demand_meta["total_count"] == 1
        asserts.assert_repurchase_demand(demands[0])
        assert demands[0]["reason"] == "BAILEE_EXPIRED"
        assert demands[0]["demand_amount_cents"] == 1_960_000_000
        asserts.assert_instant(demands[0]["deadline_at"], "2026-09-15T00:00:00Z")

        facility = fx.read_facility(facility_id)
        assert facility["status"] == "RESTRICTED"
        assert facility["accrued_fee_balance_cents"] == 21_058_333

        # The run is also available to a CollateralAnalyst.
        second = validate_success(api_client.run_aging(facility_id, COLLATERAL_ANALYST))
        asserts.assert_aging_run_summary(second)
        # The book is still walked, so this is a skip rather than a short-circuit.
        assert second["advances_evaluated"] == 1
        assert second["accrual_days"] == 0
        assert second["fee_accrual_cents"] == 0
        assert second["margin_calls_issued"] == 0
        assert second["bailee_letters_expired"] == 0
        assert second["repurchase_demands_raised"] == 0

        assert len(fx.facility_margin_calls(facility_id)) == 1
        fee_entries, fee_meta = _ledger_page(facility_id, entry_type="FEE_ACCRUAL")
        assert fee_meta["total_count"] == 1
        assert fee_entries[0]["amount_cents"] == 21_058_333
        assert fee_entries[0]["advance_id"] is None

        after = fx.read_facility(facility_id)
        assert after["accrued_fee_balance_cents"] == 21_058_333
        assert after["status"] == "RESTRICTED"
        # The open call's cure window still runs, so the posture stays RESTRICTED.
        asserts.assert_instant(
            fx.read_margin_call(calls[0]["id"])["cure_deadline_at"],
            "2026-09-07T00:00:00Z",
        )
        assert fx.read_margin_call(calls[0]["id"])["status"] == "ISSUED"


# ─── Shipment as a three-way link ─────────────────────────────────────────────

class TestShipLinksAdvanceInvestorAndCommitment:
    def test_only_the_commitment_s_own_investor_receives_the_collateral_file(self):
        """An approved investor with no commitment to this advance is refused.

        PRD 3.7: "The advance must be `FUNDED`, its `custody_status` must be
        `RECEIVED_CLEAR` or `EXCEPTION_CURED`, the named investor must be
        `APPROVED` (failing with `ERR_INVESTOR_NOT_APPROVED`), the advance must
        actually have an `investor_commitment_id` and that commitment's
        `investor_id` must equal the `investor_id` in the request (failing with
        `ERR_COMMITMENT_INVESTOR_MISMATCH`), and the advance must have no margin
        call in `ISSUED` or `PARTIALLY_CURED`."

        PRD 3.7: "A `BaileeLetter` is created in `ISSUED` naming the advance and
        the investor, with `effective_from` equal to the logical clock,
        `bailee_period_days` copied as a snapshot from the facility's own
        `bailee_period_days` at the moment of issuance, and `expires_at` equal to
        `effective_from` advanced by that many days."

        PRD 3.7: "Shipment moves documents rather than money, so the
        commitment's `allocated_amount_cents` does not change and no ledger entry
        is written."

        Design: Corner/endpoints/corner_ep_ship_links_advance_to_investor_through_the_commitment
        """
        # Priority 5 of the ladder covers advance creation, commitment creation
        # and manual margin-call creation only, so the code owed to a shipment
        # naming an identifier that resolves to nothing is not asserted here.
        scenario = fx.setup_funded_dry_advance()
        advance_id = scenario.advance["id"]
        uncommitted_investor = fx.register_investor(
            scenario.facility["id"],
            investor_name="Echo Loan Purchasers",
            concentration_limit_pct=0.50,
        )
        assert uncommitted_investor["status"] == "APPROVED"

        validate_error(
            api_client.ship_advance(
                advance_id,
                {"investor_id": uncommitted_investor["id"]},
                COLLATERAL_ANALYST,
            ),
            ApiErrorId.ERR_COMMITMENT_INVESTOR_MISMATCH,
        )

        # Existence was satisfied; the association was not, so nothing moved.
        unshipped = fx.read_advance(advance_id)
        assert unshipped["funding_status"] == "FUNDED"
        assert unshipped["custody_status"] == "RECEIVED_CLEAR"
        assert fx.advance_bailee_letters(advance_id) == []

        letter = validate_success(
            api_client.ship_advance(
                advance_id,
                {"investor_id": scenario.investor["id"]},
                COLLATERAL_ANALYST,
            ),
            201,
        )
        asserts.assert_bailee_letter(letter)
        assert letter["advance_id"] == advance_id
        assert letter["investor_id"] == scenario.investor["id"]
        assert letter["status"] == "ISSUED"
        assert letter["bailee_period_days"] == 30
        asserts.assert_instant(letter["effective_from"], "2026-08-01T00:00:00Z")
        asserts.assert_instant(letter["expires_at"], "2026-08-31T00:00:00Z")

        shipped = fx.read_advance(advance_id)
        assert shipped["funding_status"] == "SHIPPED"
        assert shipped["custody_status"] == "RELEASED_TO_INVESTOR"
        asserts.assert_instant(shipped["shipped_at"], "2026-08-01T00:00:00Z")

        letters, letter_meta = validate_paginated(
            api_client.list_advance_bailee_letters(advance_id, CREDIT_OFFICER)
        )
        # The refused arm created nothing.
        assert letter_meta["total_count"] == 1
        assert letters[0]["id"] == letter["id"]

        commitment = fx.read_commitment(scenario.commitment["id"])
        assert commitment["allocated_amount_cents"] == 1_960_000_000
        facility = fx.read_facility(scenario.facility["id"])
        assert facility["outstanding_principal_cents"] == 1_960_000_000
        entries, entry_meta = _ledger_page(scenario.facility["id"])
        assert entry_meta["total_count"] == 1
        assert entries[0]["entry_type"] == "ADVANCE_FUNDED"


# ─── The logical clock ────────────────────────────────────────────────────────

class TestLogicalClockEndpoint:
    def test_it_reports_the_value_it_replaced_and_rewrites_no_business_row(self):
        """The default is in force before the first set, and setting it is not a write.

        PRD 2.4: "The server's mandatory default clock value before any call is
        `2026-08-01T00:00:00Z`."

        PRD 2.4: "The harness moves the clock by supplying `current_utc`; the
        response reports the new `current_utc` together with the `previous_utc`
        value it replaced."

        PRD 2.4: "Setting the clock changes no business state and recomputes
        nothing — the new instant takes effect on the next business call."

        PRD 2.4: "Uniquely among all endpoints, the clock endpoint requires no
        authentication headers."

        Design: Corner/endpoints/corner_ep_clock_endpoint_returns_previous_value_and_mutates_nothing
        """
        # No clock call at all, so every timestamp below is written at the default.
        facility = fx.book_facility()
        fx.add_rate_row(facility["id"])
        facility = fx.approve_facility(facility["id"])
        asserts.assert_facility(facility)
        version_before_clock = facility["version"]
        # PRD 2.4 enumerates the datetimes that read the logical clock and
        # `created_at`/`updated_at` are not among them, so only the enumerated
        # fields are pinned to the instant here.
        asserts.assert_instant(facility["approved_at"], "2026-08-01T00:00:00Z")

        # Headers omitted entirely: this endpoint is exempt from authentication.
        first = validate_success(
            api_client.set_clock("2026-09-10T12:00:00Z", CONTENT_TYPE_ONLY)
        )
        asserts.assert_instant(first["previous_utc"], "2026-08-01T00:00:00Z")
        asserts.assert_instant(first["current_utc"], "2026-09-10T12:00:00Z")

        # An `Investor` identity that resolves to no take-out investor row.
        second = validate_success(
            api_client.set_clock(
                "2026-09-11T00:00:00Z", make_investor_headers(NON_EXISTENT_UUID)
            )
        )
        asserts.assert_instant(second["previous_utc"], "2026-09-10T12:00:00Z")
        asserts.assert_instant(second["current_utc"], "2026-09-11T00:00:00Z")

        unchanged = fx.read_facility(facility["id"])
        assert unchanged["created_at"] == facility["created_at"]
        asserts.assert_instant(unchanged["approved_at"], "2026-08-01T00:00:00Z")
        assert unchanged["version"] == version_before_clock
        assert unchanged["status"] == "ACTIVE"
        assert unchanged["outstanding_principal_cents"] == 0
        # Nothing accrues until a business call reads the new instant.
        assert unchanged["accrued_fee_balance_cents"] == 0


# ─── Ledger filters and paging ────────────────────────────────────────────────

def _three_entries_on_three_separate_days():
    """A1 funded on the 1st; AL2 funded on the 2nd and repurchased on the 3rd."""
    scenario = fx.setup_funded_dry_advance()
    fx.set_clock("2026-08-02T00:00:00Z")
    scenario.second_advance = fx.book_and_fund_additional_advance(
        scenario,
        investor_commitment_id=scenario.commitment["id"],
        callback_reference="CB-820",
        loan_amount_cents=1_000_000_000,
        note_rate=0.0625,
    )
    fx.set_clock("2026-08-03T00:00:00Z")
    fx.repurchase_advance(scenario.second_advance["id"], 980_000_000)
    return scenario


class TestLedgerListFiltersAndPaging:
    def test_three_filters_compose_with_each_other_and_with_the_page_window(self):
        """The declared order is falsifiable across three clock instants.

        PRD 2.3: "Three collections order differently and the ordering is part
        of the contract: the advance list is ordered by `created_at` ascending
        with `id` ascending as the tie-break; covenant test history is ordered by
        `period_end` ascending; and ledger entries are ordered by `posted_at`
        ascending with `created_at` ascending as the tie-break."

        PRD 2.3: "Filters are supplied as query parameters and combine
        conjunctively."

        PRD 2.3: "A facility's ledger view accepts `entry_type`, `direction` and
        `advance_id`; an advance's ledger view accepts `entry_type`."

        PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and
        `has_more` inside `meta`, where `total_count` is the number of rows
        matching the filters before pagination is applied and `has_more` is true
        when rows remain beyond the current page."

        PRD 2.3: "A `limit` outside the inclusive range from 1 to 100, or a
        negative `offset`, is a schema failure reported as `ERR_VALIDATION`
        (HTTP 422)."

        Design: Corner/endpoints/corner_ep_ledger_list_filters_compose_with_pagination
        """
        scenario = _three_entries_on_three_separate_days()
        facility_id = scenario.facility["id"]
        first_advance = scenario.advance["id"]
        second_advance = scenario.second_advance["id"]

        entries, meta = _ledger_page(facility_id)
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        for entry in entries:
            asserts.assert_ledger_entry(entry)
        asserts.assert_entry_types_in_order(
            entries,
            [
                ("ADVANCE_FUNDED", "DEBIT"),
                ("ADVANCE_FUNDED", "DEBIT"),
                ("REPURCHASE", "CREDIT"),
            ],
        )
        assert [e["advance_id"] for e in entries] == [
            first_advance,
            second_advance,
            second_advance,
        ]
        assert [e["direction"] for e in entries] == ["DEBIT", "DEBIT", "CREDIT"]
        assert [e["amount_cents"] for e in entries] == [
            1_960_000_000,
            980_000_000,
            980_000_000,
        ]
        asserts.assert_instant(entries[0]["posted_at"], "2026-08-01T00:00:00Z")
        asserts.assert_instant(entries[1]["posted_at"], "2026-08-02T00:00:00Z")
        asserts.assert_instant(entries[2]["posted_at"], "2026-08-03T00:00:00Z")

        debits, debit_meta = _ledger_page(facility_id, direction="DEBIT")
        assert debit_meta["total_count"] == 2
        assert all(e["entry_type"] == "ADVANCE_FUNDED" for e in debits)

        # The filter reads the entry's own attribution, not the addressed facility.
        by_advance, advance_meta = _ledger_page(facility_id, advance_id=second_advance)
        assert advance_meta["total_count"] == 2
        assert [e["direction"] for e in by_advance] == ["DEBIT", "CREDIT"]

        composed, composed_meta = _ledger_page(
            facility_id,
            entry_type="ADVANCE_FUNDED",
            direction="DEBIT",
            advance_id=second_advance,
        )
        assert composed_meta["total_count"] == 1
        assert composed[0]["amount_cents"] == 980_000_000
        assert composed[0]["advance_id"] == second_advance

        page_two, page_two_meta = _ledger_page(facility_id, limit=1, offset=1)
        # The total is the match count, not the page size.
        assert page_two_meta["total_count"] == 3
        assert page_two_meta["limit"] == 1
        assert page_two_meta["offset"] == 1
        assert page_two_meta["has_more"] is True
        assert len(page_two) == 1
        assert page_two[0]["entry_type"] == "ADVANCE_FUNDED"
        assert page_two[0]["amount_cents"] == 980_000_000
        asserts.assert_instant(page_two[0]["posted_at"], "2026-08-02T00:00:00Z")

        page_three, page_three_meta = _ledger_page(facility_id, limit=1, offset=2)
        assert page_three_meta["has_more"] is False
        assert len(page_three) == 1
        assert page_three[0]["entry_type"] == "REPURCHASE"
        assert page_three[0]["direction"] == "CREDIT"
        asserts.assert_instant(page_three[0]["posted_at"], "2026-08-03T00:00:00Z")

        # Zero is out of the inclusive range, so it is rejected rather than coerced.
        validate_error(
            api_client.list_facility_ledger_entries(
                facility_id, COLLATERAL_ANALYST, {"limit": 0}
            ),
            ApiErrorId.ERR_VALIDATION,
        )

        summary = fx.read_exposure_summary(facility_id)
        assert summary["ledger_debit_total_cents"] == 2_940_000_000
        assert summary["ledger_credit_total_cents"] == 980_000_000
        assert summary["outstanding_principal_cents"] == 1_960_000_000
        asserts.assert_both_conservation_invariants(summary)


# ─── Curing a defect receipt ──────────────────────────────────────────────────

class TestReceiptCureIsConditionalOnFullCoverage:
    def test_the_same_request_shape_changes_nothing_until_the_last_code_is_covered(self):
        """Two identical-looking cures: the first lifts nothing, the second lifts everything.

        PRD 3.6: "This is the crucial difference between the sizing waterfall and
        the ongoing valuation: sizing charges the wet haircut on every wet
        advance, whereas the valuation charges it only while the file is
        genuinely still outstanding, so a clear receipt lifts it."

        PRD 3.6: "The third step is the document-exception haircut: when
        `custody_status` is `RECEIVED_EXCEPTION`, a further 0.05 is subtracted."

        PRD 3.5: "A cure is complete only when the union of the codes already
        stored in `cured_exception_codes` and the codes in this request covers
        every code in the receipt's `exception_codes`."

        PRD 3.5: "A partial cure — one whose union still leaves a code
        uncovered — leaves both the receipt's status and the advance's custody
        status exactly where they were and merely appends the newly-cleared codes
        to `cured_exception_codes`."

        Design: Corner/endpoints/corner_ep_receipt_cure_is_conditional_on_full_exception_coverage
        """
        scenario = fx.setup_funded_wet_advance(
            advance_overrides={"loan_amount_cents": 1_000_000_000}
        )
        facility_id = scenario.facility["id"]
        advance_id = scenario.advance["id"]
        # Sizing charged the wet haircut: floor(1,000,000,000 * (0.98 - 0.02)).
        assert scenario.advance["advance_amount_cents"] == 960_000_000
        assert scenario.advance["custody_status"] == "PENDING_RECEIPT"

        receipt = fx.file_receipt(
            advance_id,
            scenario.custodian["id"],
            document_types=["NOTE", "MORTGAGE"],
            exception_codes=["UNSIGNED_ASSIGNMENT", "STALE_TITLE"],
        )
        asserts.assert_receipt(receipt)
        assert receipt["status"] == "EXCEPTION"
        assert receipt["cured_exception_codes"] == []

        # The wet haircut lifts as the exception haircut lands: 0.98 - 0.05.
        with_exception = fx.read_advance(advance_id)
        assert with_exception["custody_status"] == "RECEIVED_EXCEPTION"
        assert with_exception["effective_advance_rate"] == pytest.approx(
            0.93, abs=1e-6
        )
        assert with_exception["eligible_collateral_value_cents"] == 930_000_000
        assert with_exception["required_paydown_cents"] == 30_000_000

        calls = fx.advance_margin_calls(advance_id)
        assert len(calls) == 1
        exception_call = calls[0]
        assert exception_call["trigger_reason"] == "CUSTODY_EXCEPTION"
        assert exception_call["call_amount_cents"] == 30_000_000
        assert exception_call["status"] == "ISSUED"
        assert fx.read_facility(facility_id)["status"] == "RESTRICTED"

        partial = fx.cure_receipt(
            receipt["id"], scenario.custodian["id"], ["UNSIGNED_ASSIGNMENT"]
        )
        # The endpoint appends rather than replaces, and stops there.
        assert partial["cured_exception_codes"] == ["UNSIGNED_ASSIGNMENT"]
        assert partial["status"] == "EXCEPTION"

        midway = fx.read_advance(advance_id)
        assert midway["custody_status"] == "RECEIVED_EXCEPTION"
        # The haircut is all-or-nothing, never pro-rated across the two codes.
        assert midway["effective_advance_rate"] == pytest.approx(0.93, abs=1e-6)
        assert fx.read_margin_call(exception_call["id"])["status"] == "ISSUED"
        assert fx.read_facility(facility_id)["status"] == "RESTRICTED"

        complete = fx.cure_receipt(
            receipt["id"], scenario.custodian["id"], ["STALE_TITLE"]
        )
        assert complete["cured_exception_codes"] == [
            "UNSIGNED_ASSIGNMENT",
            "STALE_TITLE",
        ]
        assert complete["status"] == "CURED"

        cured_advance = fx.read_advance(advance_id)
        assert cured_advance["custody_status"] == "EXCEPTION_CURED"
        # Both haircuts are off now, so the base rate stands.
        assert cured_advance["effective_advance_rate"] == pytest.approx(0.98, abs=1e-6)
        assert cured_advance["eligible_collateral_value_cents"] == 980_000_000
        assert cured_advance["required_paydown_cents"] == 0
        assert cured_advance["outstanding_balance_cents"] == 960_000_000

        closed_call = fx.read_margin_call(exception_call["id"])
        assert closed_call["status"] == "CURED"
        # The closure is a compensation, not a payment.
        assert closed_call["cured_amount_cents"] == 0

        facility = fx.read_facility(facility_id)
        assert facility["status"] == "ACTIVE"
        assert facility["open_margin_call_count"] == 0
        assert facility["outstanding_principal_cents"] == 960_000_000

        entries, meta = _ledger_page(facility_id)
        # Only the original funding entry exists: the cure posted nothing.
        assert meta["total_count"] == 1
        assert entries[0]["entry_type"] == "ADVANCE_FUNDED"
