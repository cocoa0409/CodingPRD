"""Entity-shape contracts: declared fields, defaults, computed figures, scoping.

Nothing here exercises a business rule for its own sake. Each test pins one
promise the specification makes about the *shape* of a row — what a create
echoes, what a read re-derives, what an omitted optional becomes, which fields
the client may never supply, and which rows a given identity may see at all.
"""

import pytest

from test_helpers import (
    COLLATERAL_ANALYST,
    CREDIT_OFFICER,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    make_borrower_headers,
    make_custodian_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as asserts
from test_helpers import factories as make
from test_helpers import fixtures as fx


# ─── Creation, retrieval and listing shapes ───────────────────────────────────

class TestFacilityCreationShape:
    def test_a_booked_facility_returns_every_declared_field_materialised(self):
        """No computed rollup is left null on the way out of the create.

        PRD 3.1: "Every computed figure starts empty:
        `outstanding_principal_cents`, `accrued_fee_balance_cents`,
        `wet_outstanding_cents`, `aged_outstanding_cents`,
        `scratch_and_dent_outstanding_cents`, `open_margin_call_count`,
        `consecutive_breach_count` and `escalated_demand_count` are all zero,
        `availability_cents` equals the committed line size, and
        `last_covenant_status` reads `NOT_TESTED` because no covenant test exists
        yet."

        Design: Corner/entities/corner_entity_facility_creation_returns_full_declared_shape
        """
        fx.set_clock("2026-08-01T00:00:00Z")

        response = api_client.create_facility(make.facility_payload(), CREDIT_OFFICER)
        facility = validate_success(response, expected_status=201)

        envelope = response.json()
        assert envelope["response_type"] == "object"
        assert envelope["meta"]["api_request_id"].startswith("req_")

        asserts.assert_facility(facility)

        # Every input field is echoed back verbatim.
        assert facility["borrower_legal_name"] == "Meridian Mortgage Bankers LLC"
        assert facility["committed_amount_cents"] == 20_000_000_000
        assert facility["wet_sublimit_cents"] == 20_000_000_000
        assert facility["aged_sublimit_cents"] == 2_000_000_000
        assert facility["scratch_and_dent_sublimit_cents"] == 1_000_000_000
        assert facility["min_tangible_net_worth_cents"] == 1_500_000_000
        assert facility["min_liquidity_cents"] == 500_000_000
        assert facility["min_ttm_net_income_cents"] == 100_000_000
        assert facility["max_investor_concentration_pct"] == pytest.approx(
            0.35, abs=1e-6
        )
        assert facility["unused_line_fee_rate"] == pytest.approx(0.0025, abs=1e-6)
        assert facility["bailee_period_days"] == 30
        assert facility["settlement_account_last4"] == "4417"

        assert facility["status"] == "PENDING_APPROVAL"
        assert facility["version"] == 1
        assert facility["created_by_user_id"] == "co_1"
        assert facility["approved_by_user_id"] is None
        assert facility["approved_at"] is None
        assert facility["last_accrual_at"] is None

        for zeroed in (
            "outstanding_principal_cents",
            "accrued_fee_balance_cents",
            "wet_outstanding_cents",
            "aged_outstanding_cents",
            "scratch_and_dent_outstanding_cents",
            "open_margin_call_count",
            "consecutive_breach_count",
            "escalated_demand_count",
        ):
            assert facility[zeroed] == 0, f"{zeroed} starts empty"
        assert facility["availability_cents"] == 20_000_000_000
        assert facility["last_covenant_status"] == "NOT_TESTED"


class TestAdvanceRetrievalShape:
    def test_the_same_row_reports_more_dwell_at_a_later_clock_with_no_write(self):
        """Dwell is derived on read, so a bare clock move changes the answer.

        PRD 3.6: "Otherwise `dwell_days` is the number of complete
        twenty-four-hour periods — each of 86,400 seconds — that have elapsed
        from `funded_at` to the logical clock, with any partial period
        discarded, and `is_aged` is true exactly when `dwell_days` is strictly
        greater than the applicable `dwell_limit_days`."

        Design: Corner/entities/corner_entity_advance_retrieval_recomputes_derived_fields
        """
        scenario = fx.setup_funded_dry_advance()

        at_funding = fx.read_advance(scenario.advance["id"])
        asserts.assert_advance(at_funding)
        assert at_funding["dwell_days"] == 0
        assert at_funding["funding_status"] == "FUNDED"
        assert at_funding["custody_status"] == "RECEIVED_CLEAR"
        assert at_funding["loan_amount_cents"] == 2_000_000_000
        assert at_funding["advance_amount_cents"] == 1_960_000_000
        assert at_funding["market_value_cents"] == 2_000_000_000

        fx.set_clock("2026-08-11T00:00:00Z")
        ten_days_later = fx.read_advance(scenario.advance["id"])

        assert ten_days_later["dwell_days"] == 10
        # Ten days is well inside the thirty-day limit, so nothing curtails.
        assert ten_days_later["is_aged"] is False
        assert at_funding["is_aged"] is False
        for read in (at_funding, ten_days_later):
            assert read["effective_advance_rate"] == pytest.approx(0.98, abs=1e-6)
            assert read["eligible_collateral_value_cents"] == 1_960_000_000

        # A read is not a mutation: the OCC token never moved.
        assert ten_days_later["version"] == at_funding["version"]


def _book_three_advances_on_one_line():
    """A1 dry and funded, A2 wet and funded, A3 wet and still merely requested."""
    scenario = fx.setup_funded_dry_advance()

    scenario.second_advance = fx.book_and_fund_additional_advance(
        scenario,
        investor_commitment_id=scenario.commitment["id"],
        callback_reference="CB-902",
        funding_type="WET",
        loan_amount_cents=1_000_000_000,
        note_rate=0.0625,
    )
    scenario.third_advance = fx.book_advance(
        scenario.facility["id"],
        scenario.custodian["id"],
        investor_commitment_id=scenario.commitment["id"],
        funding_type="WET",
        loan_amount_cents=300_000_000,
        note_rate=0.0700,
    )
    return scenario


class TestAdvanceListingEnvelope:
    def test_the_filter_narrows_the_total_and_the_page_reports_what_remains(self):
        """`total_count` counts filter matches, not page rows.

        PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and
        `has_more` inside `meta`, where `total_count` is the number of rows
        matching the filters before pagination is applied and `has_more` is true
        when rows remain beyond the current page."

        Design: Corner/entities/corner_entity_advance_listing_filter_and_pagination_envelope
        """
        scenario = _book_three_advances_on_one_line()
        facility_id = scenario.facility["id"]
        expected_order = [
            scenario.advance["id"],
            scenario.second_advance["id"],
            scenario.third_advance["id"],
        ]

        rows, meta = validate_paginated(
            api_client.list_advances(CREDIT_OFFICER, {"facility_id": facility_id})
        )
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(rows) == 3
        # The advance list is ordered by created_at ascending.
        assert [row["id"] for row in rows] == expected_order

        funded, funded_meta = validate_paginated(
            api_client.list_advances(
                CREDIT_OFFICER,
                {"facility_id": facility_id, "funding_status": "FUNDED"},
            )
        )
        assert funded_meta["total_count"] == 2
        assert {row["id"] for row in funded} == set(expected_order[:2])

        first_page, first_meta = validate_paginated(
            api_client.list_advances(
                CREDIT_OFFICER, {"facility_id": facility_id, "limit": 1, "offset": 0}
            )
        )
        assert len(first_page) == 1
        assert first_page[0]["id"] == expected_order[0]
        assert first_meta["total_count"] == 3
        assert first_meta["limit"] == 1
        assert first_meta["offset"] == 0
        assert first_meta["has_more"] is True

        last_page, last_meta = validate_paginated(
            api_client.list_advances(
                CREDIT_OFFICER, {"facility_id": facility_id, "limit": 1, "offset": 2}
            )
        )
        assert len(last_page) == 1
        assert last_page[0]["id"] == expected_order[2]
        assert last_meta["has_more"] is False

        assert last_page[0]["funding_status"] == "REQUESTED"
        assert last_page[0]["outstanding_balance_cents"] == 0


class TestPerEntityNotFoundCodes:
    def test_each_collection_segment_reports_its_own_not_found_code(self):
        """The 404 names the addressed collection, never a generic code.

        PRD 2.8: "Every path-parameter identifier resolves to an existing row of
        the addressed collection, failing with 404 and the code that matches the
        addressed collection segment: a facility segment yields
        `ERR_FACILITY_NOT_FOUND`, an advance segment `ERR_ADVANCE_NOT_FOUND`, an
        investor segment `ERR_INVESTOR_NOT_FOUND`, a custodian segment
        `ERR_CUSTODIAN_NOT_FOUND`, a commitment segment
        `ERR_COMMITMENT_NOT_FOUND`, a margin-call segment
        `ERR_MARGIN_CALL_NOT_FOUND`, a wire-instruction segment
        `ERR_WIRE_INSTRUCTION_NOT_FOUND`, a receipt segment
        `ERR_RECEIPT_NOT_FOUND`, a covenant-test segment
        `ERR_COVENANT_TEST_NOT_FOUND`, and a repurchase-demand segment
        `ERR_REPURCHASE_DEMAND_NOT_FOUND`."

        Design: Corner/entities/corner_entity_advance_not_found_for_unknown_id
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        facility = fx.book_facility()
        fx.add_rate_row(facility["id"])
        fx.approve_facility(facility["id"])

        missing_advance = api_client.get_advance(NON_EXISTENT_UUID, COLLATERAL_ANALYST)
        validate_error(missing_advance, ApiErrorId.ERR_ADVANCE_NOT_FOUND)
        body = missing_advance.json()
        assert body["response_type"] == "error"
        assert body["meta"]["api_request_id"].startswith("req_")

        validate_error(
            api_client.get_margin_call(NON_EXISTENT_UUID, CREDIT_OFFICER),
            ApiErrorId.ERR_MARGIN_CALL_NOT_FOUND,
        )


# ─── Required fields, defaults and computed fields ────────────────────────────

class TestRequiredFieldsAndDefaults:
    def test_omitting_a_field_with_no_default_rejects_and_persists_nothing(self):
        """`settlement_account_last4` has no default, so its absence is fatal.

        PRD 2.8: "All required body fields are present; types, enum members,
        string formats and numeric ranges are valid; `limit` lies in the
        inclusive range 1 to 100 and `offset` is not negative. Failure is
        `ERR_VALIDATION` (422)."

        Design: Corner/entities/corner_entity_facility_missing_required_field_rejected
        """
        fx.set_clock("2026-08-01T00:00:00Z")

        incomplete = make.facility_payload(
            borrower_legal_name="Incomplete Funding Corp"
        )
        del incomplete["settlement_account_last4"]

        validate_error(
            api_client.create_facility(incomplete, CREDIT_OFFICER),
            ApiErrorId.ERR_VALIDATION,
        )

        _rows, meta = validate_paginated(api_client.list_facilities(CREDIT_OFFICER))
        assert meta["total_count"] == 0

    def test_every_declared_default_materialises_when_the_field_is_omitted(self):
        """An omitted optional takes its declared default, not null.

        PRD 3.1: "`wet_funding_allowed` says whether wet funding is permitted
        for the product at all and defaults to true; `wet_haircut` is the rate
        reduction applied while a wet advance's collateral file is still
        outstanding, defaults to 0.02, and must be at least zero and strictly
        less than the row's own `advance_rate`."

        Design: Corner/entities/corner_entity_declared_defaults_applied_on_omission
        """
        fx.set_clock("2026-08-01T00:00:00Z")

        bare_facility = make.facility_payload(
            borrower_legal_name="Defaults Mortgage LLC"
        )
        del bare_facility["bailee_period_days"]
        facility = validate_success(
            api_client.create_facility(bare_facility, CREDIT_OFFICER),
            expected_status=201,
        )
        asserts.assert_facility(facility)
        assert facility["bailee_period_days"] == 30
        assert facility["status"] == "PENDING_APPROVAL"

        rate_row = validate_success(
            api_client.create_product_advance_rate(
                facility["id"],
                {
                    "product_code": "CONFORMING",
                    "advance_rate": 0.98,
                    "dwell_limit_days": 30,
                },
                CREDIT_OFFICER,
            ),
            expected_status=201,
        )
        asserts.assert_product_advance_rate(rate_row)
        assert rate_row["wet_funding_allowed"] is True
        assert rate_row["wet_haircut"] == pytest.approx(0.02, abs=1e-6)
        assert rate_row["aging_step_days"] == 15
        assert rate_row["curtailment_step_rate"] == pytest.approx(0.005, abs=1e-6)
        # An omitted optional with no declared default stays null.
        assert rate_row["product_sublimit_cents"] is None

        # PRD 2.8 priority 10 gates custodian registration on an `ACTIVE`
        # facility, so the line is approved by a second officer first.
        active = fx.approve_facility(facility["id"])
        assert active["status"] == "ACTIVE"

        custodian = validate_success(
            api_client.create_custodian(
                facility["id"],
                {"custodian_name": "Default Custody Trust"},
                CREDIT_OFFICER,
            ),
            expected_status=201,
        )
        asserts.assert_custodian(custodian)
        assert custodian["wet_receipt_deadline_hours"] == 72
        assert custodian["status"] == "APPROVED"

    def test_an_omitted_exception_array_defaults_to_empty_and_reads_as_clear(self):
        """No `exception_codes` key at all still means a clear file.

        PRD 3.5: "An optional `exception_codes` array, defaulting to empty,
        reports document defects found on intake and is drawn from
        `MISSING_NOTE`, `UNSIGNED_ASSIGNMENT`, `STALE_TITLE` and
        `NAME_MISMATCH`. An empty array means a clear file."

        Design: Corner/entities/corner_entity_receipt_exception_codes_default_empty_yields_clear
        """
        scenario = fx.setup_requested_advance()

        payload = {
            "custodian_id": scenario.custodian["id"],
            "document_types": ["NOTE", "MORTGAGE", "ASSIGNMENT", "TITLE_POLICY"],
        }
        receipt = validate_success(
            api_client.create_receipt(
                scenario.advance["id"],
                payload,
                make_custodian_headers(scenario.custodian["id"]),
            ),
            expected_status=201,
        )
        asserts.assert_receipt(receipt)
        assert receipt["exception_codes"] == []
        assert receipt["cured_exception_codes"] == []
        assert receipt["status"] == "CLEAR"

        advance = fx.read_advance(scenario.advance["id"])
        assert advance["custody_status"] == "RECEIVED_CLEAR"
        # A receipt is not a funding event, and an unfunded advance owes nothing.
        assert advance["funding_status"] == "REQUESTED"
        assert advance["required_paydown_cents"] == 0

        _rows, meta = validate_paginated(
            api_client.list_custodian_receipts(
                scenario.custodian["id"], CREDIT_OFFICER
            )
        )
        assert meta["total_count"] == 1

    def test_the_money_fields_of_an_advance_are_never_client_supplied(self):
        """They are seeded at creation and only the funding waterfall writes them.

        PRD 3.3: "`market_value_cents` initialises to the loan amount,
        `advance_amount_cents` is zero, `concentration_capped` is false,
        `dwell_days` is zero, `is_aged` is false, and `rejected_reason`,
        `funded_at`, `wet_receipt_deadline_at`, `shipped_at` and `purchased_at`
        are all null."

        Design: Corner/entities/corner_entity_advance_computed_fields_derived_not_supplied
        """
        scenario = fx.setup_advance_ready_to_fund()

        at_creation = fx.read_advance(scenario.advance["id"])
        assert at_creation["market_value_cents"] == 2_000_000_000
        assert at_creation["advance_amount_cents"] == 0
        assert at_creation["outstanding_balance_cents"] == 0
        assert at_creation["concentration_capped"] is False
        assert at_creation["dwell_days"] == 0
        assert at_creation["is_aged"] is False
        assert at_creation["funded_at"] is None
        assert at_creation["shipped_at"] is None
        assert at_creation["purchased_at"] is None
        assert at_creation["rejected_reason"] is None

        funded = validate_success(
            api_client.fund_advance(scenario.advance["id"], COLLATERAL_ANALYST)
        )
        asserts.assert_advance(funded)
        assert funded["provisional_advance_amount_cents"] == 1_960_000_000
        assert funded["advance_amount_cents"] == 1_960_000_000
        assert funded["outstanding_balance_cents"] == 1_960_000_000
        assert funded["concentration_capped"] is False

        assert fx.read_facility(scenario.facility["id"])[
            "outstanding_principal_cents"
        ] == 1_960_000_000


# ─── Append-only rows: system fields, ordering and immutability ───────────────

class TestLedgerEntrySystemFields:
    def test_the_funding_debit_precedes_the_later_fee_accrual_debit(self):
        """Both rows are entirely system-minted and replay in posting order.

        PRD 2.6: "Every movement of money writes one `LedgerEntry` naming the
        `facility_id` it moves, the `advance_id` it is attributable to (null for
        facility-level entries), an `entry_type`, a `direction`, an
        `amount_cents` magnitude that is never negative, the `posted_at`
        logical-clock instant, and a human-readable `memo` recording provenance
        such as funding an advance, applying cure principal, or receiving
        investor proceeds."

        Design: Corner/entities/corner_entity_ledger_entry_system_fields_and_ordering
        """
        scenario = fx.setup_funded_dry_advance()

        fx.set_clock("2026-08-11T00:00:00Z")
        run = fx.run_aging(scenario.facility["id"])
        asserts.assert_aging_run_summary(run)
        # 1,960,000,000 * 0.0875 / 360 * 10 = 4,763,889 interest, plus
        # 18,040,000,000 * 0.0025 / 360 * 10 = 1,252,778 of unused-line fee.
        assert run["fee_accrual_cents"] == 6_016_667

        entries, meta = validate_paginated(
            api_client.list_facility_ledger_entries(
                scenario.facility["id"], CREDIT_OFFICER
            )
        )
        assert meta["total_count"] == 2
        asserts.assert_entry_types_in_order(
            entries, [("ADVANCE_FUNDED", "DEBIT"), ("FEE_ACCRUAL", "DEBIT")]
        )
        for entry in entries:
            asserts.assert_ledger_entry(entry)
            asserts.assert_append_only_common_fields(entry)
            assert entry["facility_id"] == scenario.facility["id"]
            assert entry["amount_cents"] > 0
            assert isinstance(entry["memo"], str) and entry["memo"]

        assert entries[0]["advance_id"] == scenario.advance["id"]
        assert entries[0]["amount_cents"] == 1_960_000_000
        asserts.assert_instant(entries[0]["posted_at"], "2026-08-01T00:00:00Z")
        # The unused-line fee is facility-level, so it names no advance.
        assert entries[1]["advance_id"] is None
        assert entries[1]["amount_cents"] == 6_016_667
        asserts.assert_instant(entries[1]["posted_at"], "2026-08-11T00:00:00Z")

        fees, fee_meta = validate_paginated(
            api_client.list_facility_ledger_entries(
                scenario.facility["id"], CREDIT_OFFICER, {"entry_type": "FEE_ACCRUAL"}
            )
        )
        assert fee_meta["total_count"] == 1
        assert fees[0]["amount_cents"] == 6_016_667


class TestCurePaymentImmutability:
    def test_a_cure_payment_carries_no_version_and_no_updated_at(self):
        """It is a record of an event, so there is nothing to revise.

        PRD 2.4: "Two resources are append-only records rather than mutable
        entities, and they are deliberately thinner: a `CurePayment` and a
        `LedgerEntry` carry only `id` and `created_at`. Neither has an
        `updated_at` and neither has a `version`, because neither is ever
        modified after it is written."

        Design: Corner/entities/corner_entity_cure_payment_is_immutable_append_only
        """
        scenario = fx.setup_advance_with_valuation_margin_call(
            market_value_cents=1_900_000_000
        )
        assert scenario.margin_call["call_amount_cents"] == 98_000_000

        payment = fx.post_cure_payment(
            scenario.margin_call["id"], scenario.facility["id"], 40_000_000
        )
        asserts.assert_cure_payment(payment)
        assert "version" not in payment
        assert "updated_at" not in payment

        assert payment["amount_cents"] == 40_000_000
        # No aging run has posted a fee, so the whole payment is principal.
        assert payment["applied_to_fees_cents"] == 0
        assert payment["applied_to_principal_cents"] == 40_000_000
        # One covered advance, so the whole allocation is a single row.
        assert len(payment["principal_allocation"]) == 1
        allocation = payment["principal_allocation"][0]
        assert allocation["advance_id"] == scenario.advance["id"]
        assert allocation["amount_cents"] == 40_000_000

        payments, meta = validate_paginated(
            api_client.list_cure_payments(scenario.margin_call["id"], CREDIT_OFFICER)
        )
        assert meta["total_count"] == 1
        assert payments[0]["id"] == payment["id"]

        call = fx.read_margin_call(scenario.margin_call["id"])
        assert call["cured_amount_cents"] == 40_000_000
        assert call["status"] == "PARTIALLY_CURED"
        assert fx.read_advance(scenario.advance["id"])[
            "outstanding_balance_cents"
        ] == 1_920_000_000


# ─── Type constraints and referential scoping ─────────────────────────────────

class TestTypeAndRangeConstraints:
    def test_four_different_constraint_families_all_report_one_code(self):
        """Enum, range, positivity and pagination bounds are all schema failures.

        PRD 2.3: "A `limit` outside the inclusive range from 1 to 100, or a
        negative `offset`, is a schema failure reported as `ERR_VALIDATION`
        (HTTP 422)."

        Design: Corner/entities/corner_entity_enum_and_range_constraints_rejected
        """
        scenario = fx.setup_facility_panel(with_commitment=False)
        facility_id = scenario.facility["id"]

        # An off-vocabulary enum member never reaches the rate-row lookup.
        validate_error(
            api_client.create_advance(
                make.advance_payload(
                    facility_id,
                    scenario.custodian["id"],
                    scenario.facility_version_before_booking,
                    product_code="SUPER_JUMBO",
                ),
                COLLATERAL_ANALYST,
            ),
            ApiErrorId.ERR_VALIDATION,
        )

        validate_error(
            api_client.create_commitment(
                facility_id,
                make.commitment_payload(scenario.investor["id"], price_pct=1.5),
                CREDIT_OFFICER,
            ),
            ApiErrorId.ERR_VALIDATION,
        )
        validate_error(
            api_client.create_commitment(
                facility_id,
                make.commitment_payload(
                    scenario.investor["id"], committed_amount_cents=0
                ),
                CREDIT_OFFICER,
            ),
            ApiErrorId.ERR_VALIDATION,
        )

        validate_error(
            api_client.list_advances(
                CREDIT_OFFICER, {"facility_id": facility_id, "limit": 101}
            ),
            ApiErrorId.ERR_VALIDATION,
        )

        # Four refusals, four empty books.
        _commitments, commitment_meta = validate_paginated(
            api_client.list_facility_commitments(facility_id, CREDIT_OFFICER)
        )
        assert commitment_meta["total_count"] == 0
        _advances, advance_meta = validate_paginated(
            api_client.list_advances(CREDIT_OFFICER, {"facility_id": facility_id})
        )
        assert advance_meta["total_count"] == 0


def _two_facilities_each_with_their_own_custodian():
    """Facility one is the canonical panel; facility two is a stranger to it."""
    scenario = fx.setup_facility_panel(with_commitment=False)
    scenario.second_facility = fx.create_active_facility(
        facility_overrides={
            "borrower_legal_name": "Keystone Home Loans Inc",
            "settlement_account_last4": "8802",
        }
    )
    scenario.second_custodian = fx.register_custodian(
        scenario.second_facility["id"], custodian_name="Second Doc Custody NA"
    )
    return scenario


class TestBodyForeignKeyScoping:
    def test_a_custodian_of_another_facility_is_reported_as_not_found(self):
        """Readable everywhere, usable only on its own line.

        PRD 2.8: "Every identifier supplied in a request body resolves, and
        resolves within the addressed facility, failing with the same 404 codes
        as priority 3."

        Design: Corner/entities/corner_entity_body_fk_must_resolve_within_addressed_facility
        """
        scenario = _two_facilities_each_with_their_own_custodian()
        facility_id = scenario.facility["id"]
        version_before = fx.facility_version(facility_id)

        readable = validate_success(
            api_client.get_custodian(scenario.second_custodian["id"], CREDIT_OFFICER)
        )
        asserts.assert_custodian(readable)
        assert readable["facility_id"] == scenario.second_facility["id"]

        validate_error(
            api_client.create_advance(
                make.advance_payload(
                    facility_id, scenario.second_custodian["id"], version_before
                ),
                COLLATERAL_ANALYST,
            ),
            ApiErrorId.ERR_CUSTODIAN_NOT_FOUND,
        )

        _rows, meta = validate_paginated(
            api_client.list_advances(CREDIT_OFFICER, {"facility_id": facility_id})
        )
        assert meta["total_count"] == 0
        # A rejected booking persists nothing, so the OCC token is unmoved.
        assert fx.facility_version(facility_id) == version_before


class TestEntityBackedIdentityScoping:
    def test_a_borrower_reading_another_facility_is_told_it_is_not_found(self):
        """The role is authorised; only the aggregate is wrong.

        PRD 2.1: "For all three, a supplied `X-User-ID` that does not resolve to
        a row of the backing entity at all is itself an authorisation failure
        and yields `ERR_UNAUTHORIZED`; an identity that resolves but addresses a
        row belonging to a different aggregate yields `ERR_RESOURCE_MISMATCH`
        with HTTP 404, deliberately reported as a not-found so that the
        existence of another counterparty's data is never disclosed."

        Design: Corner/entities/corner_entity_entity_backed_role_cross_aggregate_read_mismatch
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        first = fx.create_active_facility()
        second = fx.create_active_facility(
            facility_overrides={
                "borrower_legal_name": "Keystone Home Loans Inc",
                "settlement_account_last4": "8802",
            }
        )
        stranger = make_borrower_headers(second["id"])

        validate_error(
            api_client.get_facility(first["id"], stranger),
            ApiErrorId.ERR_RESOURCE_MISMATCH,
        )
        validate_error(
            api_client.get_exposure_summary(first["id"], stranger),
            ApiErrorId.ERR_RESOURCE_MISMATCH,
        )

        own = validate_success(api_client.get_facility(second["id"], stranger))
        asserts.assert_facility(own)
        assert own["id"] == second["id"]
