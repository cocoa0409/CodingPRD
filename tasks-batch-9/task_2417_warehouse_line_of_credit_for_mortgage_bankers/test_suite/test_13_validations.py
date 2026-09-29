"""Validation corners: conditional gates, ladder order and aggregate rules.

Each test pairs a refusal with the nearest passing request, so the assertion is
about which rule fired rather than merely that something failed.
"""

import pytest

from test_helpers import (
    COLLATERAL_ANALYST,
    CREDIT_OFFICER,
    WIRE_OPERATOR,
    ApiErrorId,
    api_client,
    make_borrower_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as asserts
from test_helpers import factories as make
from test_helpers import fixtures as fx


DRY_SCRATCH_AND_DENT_ROW = {
    "product_code": "SCRATCH_AND_DENT",
    "advance_rate": 0.85,
    "wet_funding_allowed": False,
    "dwell_limit_days": 20,
}


def _only_wire_of(advance_id):
    """The advance's single paired wire instruction, read as the operator."""
    wires, meta = validate_paginated(
        api_client.list_advance_wire_instructions(advance_id, WIRE_OPERATOR)
    )
    assert meta["total_count"] == 1
    return wires[0]


# ─── Conditional and cascading gates on advance creation ─────────────────────

class TestWetFundingIsAPerProductSwitch:
    def test_the_same_wet_request_is_refused_for_one_product_and_taken_for_another(self):
        """Only the rate row's own flag decides, and a refusal costs no version.

        PRD 2.8: "The product's `wet_funding_allowed` is true when `funding_type`
        is `WET`, failing advance creation with `ERR_WET_FUNDING_NOT_ALLOWED`
        (422). Some products, notably scratch-and-dent, are dry-only by policy."

        Design: Corner/validations/corner_val_wet_funding_gate_is_conditional_on_the_rate_row
        """
        scenario = fx.setup_facility_panel(
            extra_rate_rows=[DRY_SCRATCH_AND_DENT_ROW], with_commitment=False
        )
        facility_id = scenario.facility["id"]
        token = scenario.facility_version_before_booking

        validate_error(
            api_client.create_advance(
                make.advance_payload(
                    facility_id,
                    scenario.custodian["id"],
                    token,
                    product_code="SCRATCH_AND_DENT",
                    loan_amount_cents=500_000_000,
                    note_rate=0.0950,
                    funding_type="WET",
                ),
                COLLATERAL_ANALYST,
            ),
            ApiErrorId.ERR_WET_FUNDING_NOT_ALLOWED,
        )

        # The identical request in dry form is accepted, so the product itself is
        # fundable; reusing `token` proves the refusal wrote nothing.
        dry = validate_success(
            api_client.create_advance(
                make.advance_payload(
                    facility_id,
                    scenario.custodian["id"],
                    token,
                    product_code="SCRATCH_AND_DENT",
                    loan_amount_cents=500_000_000,
                    note_rate=0.0950,
                    funding_type="DRY",
                ),
                COLLATERAL_ANALYST,
            ),
            expected_status=201,
        )
        asserts.assert_advance(dry)
        assert dry["funding_type"] == "DRY"

        next_token = fx.facility_version(facility_id)
        assert next_token == token + 1

        wet = validate_success(
            api_client.create_advance(
                make.advance_payload(
                    facility_id,
                    scenario.custodian["id"],
                    next_token,
                    product_code="CONFORMING",
                    loan_amount_cents=500_000_000,
                    note_rate=0.0650,
                    funding_type="WET",
                ),
                COLLATERAL_ANALYST,
            ),
            expected_status=201,
        )
        assert wet["funding_type"] == "WET"

        advances, meta = validate_paginated(
            api_client.list_advances(
                COLLATERAL_ANALYST, {"facility_id": facility_id}
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in advances} == {dry["id"], wet["id"]}
        assert [row["funding_status"] for row in advances] == [
            "REQUESTED",
            "REQUESTED",
        ]

        # The rejected request paired no wire of its own.
        assert _only_wire_of(dry["id"])["status"] == "PENDING_VERIFICATION"
        assert _only_wire_of(wet["id"])["status"] == "PENDING_VERIFICATION"


class TestRateRowExistenceOutranksSchema:
    def test_a_request_that_breaks_three_rules_reports_the_lowest_priority_one(self):
        """The rate row is an existence question settled before the body is read.

        PRD 2.8: "A `ProductAdvanceRate` row exists on the facility for the
        requested `product_code`, failing advance creation with
        `ERR_ADVANCE_RATE_NOT_CONFIGURED` (422). Sizing is impossible without a
        rate row, so this is resolved as an existence question before any
        schema-independent business rule runs."

        PRD 2.8: "Where two rules could both plausibly describe a rejection, the
        ladder position decides which `error_id` the caller sees."

        Design: Corner/validations/corner_val_rate_row_existence_outranks_request_schema
        """
        scenario = fx.setup_facility_panel(with_commitment=False)
        facility_id = scenario.facility["id"]
        custodian_id = scenario.custodian["id"]
        token = scenario.facility_version_before_booking

        def book(product_code, funding_type, version):
            return api_client.create_advance(
                make.advance_payload(
                    facility_id,
                    custodian_id,
                    version,
                    product_code=product_code,
                    loan_amount_cents=500_000_000,
                    note_rate=0.0650,
                    funding_type=funding_type,
                ),
                COLLATERAL_ANALYST,
            )

        # Unconfigured product and an invalid enum member in one request.
        validate_error(
            book("JUMBO", "SEMI_WET", token),
            ApiErrorId.ERR_ADVANCE_RATE_NOT_CONFIGURED,
        )
        # With the rate row present the schema tier is now the first failure.
        validate_error(book("CONFORMING", "SEMI_WET", token), ApiErrorId.ERR_VALIDATION)
        # The rate-row question does not depend on the funding type either.
        validate_error(
            book("JUMBO", "DRY", token), ApiErrorId.ERR_ADVANCE_RATE_NOT_CONFIGURED
        )

        booked = validate_success(book("CONFORMING", "DRY", token), expected_status=201)
        assert fx.facility_version(facility_id) == token + 1

        # The same token is now stale, yet the missing rate row still wins.
        validate_error(
            book("JUMBO", "DRY", token), ApiErrorId.ERR_ADVANCE_RATE_NOT_CONFIGURED
        )

        advances, meta = validate_paginated(
            api_client.list_advances(
                COLLATERAL_ANALYST, {"facility_id": facility_id}
            )
        )
        assert meta["total_count"] == 1
        assert advances[0]["id"] == booked["id"]
        assert _only_wire_of(booked["id"])["status"] == "PENDING_VERIFICATION"


# ─── Two uniqueness scopes on the same parent ────────────────────────────────

class TestUniquenessScopes:
    def test_each_scope_is_keyed_on_its_own_column_not_on_the_parent(self):
        """A second product and a later quarter both fit the same facility.

        PRD 2.8: "No `ProductAdvanceRate` row already exists on the facility with
        the same `product_code`, failing with `ERR_DUPLICATE_ADVANCE_RATE` (409)."

        PRD 2.8: "No `CovenantTest` already exists on the facility with the same
        `period_end`, failing with `ERR_DUPLICATE_COVENANT_PERIOD` (409).
        Restating a quarter is a waiver, never a re-submission."

        Design: Corner/validations/corner_val_duplicate_rate_row_and_duplicate_covenant_period
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        facility = fx.book_facility()
        fx.add_rate_row(facility["id"])

        validate_error(
            api_client.create_product_advance_rate(
                facility["id"],
                make.product_advance_rate_payload(
                    product_code="CONFORMING", advance_rate=0.95, dwell_limit_days=25
                ),
                CREDIT_OFFICER,
            ),
            ApiErrorId.ERR_DUPLICATE_ADVANCE_RATE,
        )

        jumbo = validate_success(
            api_client.create_product_advance_rate(
                facility["id"],
                make.product_advance_rate_payload(
                    product_code="JUMBO", advance_rate=0.95, dwell_limit_days=25
                ),
                CREDIT_OFFICER,
            ),
            expected_status=201,
        )
        asserts.assert_product_advance_rate(jumbo)

        fx.approve_facility(facility["id"])
        second_quarter = fx.certify_covenants(facility["id"], "2026-06-30")
        asserts.assert_covenant_test(second_quarter)
        assert second_quarter["status"] == "PASS"

        # Every other field differs and the period alone still collides.
        validate_error(
            api_client.create_covenant_test(
                facility["id"],
                make.covenant_test_payload(
                    "2026-06-30",
                    tangible_net_worth_cents=2_100_000_000,
                    liquidity_cents=900_000_000,
                    net_income_cents=250_000_000,
                ),
                CREDIT_OFFICER,
            ),
            ApiErrorId.ERR_DUPLICATE_COVENANT_PERIOD,
        )

        third_quarter = fx.certify_covenants(facility["id"], "2026-09-30")
        assert third_quarter["status"] == "PASS"

        rows, meta = validate_paginated(
            api_client.list_product_advance_rates(facility["id"], CREDIT_OFFICER)
        )
        assert meta["total_count"] == 2
        conforming = [row for row in rows if row["product_code"] == "CONFORMING"]
        assert len(conforming) == 1
        # The rejected duplicate did not overwrite the surviving row.
        assert conforming[0]["advance_rate"] == pytest.approx(0.98, abs=1e-6)

        tests, meta = validate_paginated(
            api_client.list_covenant_tests(facility["id"], CREDIT_OFFICER)
        )
        assert meta["total_count"] == 2
        assert [row["period_end"] for row in tests] == ["2026-06-30", "2026-09-30"]
        for row in tests:
            # Neither certificate had three priors behind it.
            assert row["profitability_variant"] == "ANNUALIZED_QUARTER"
            assert row["breach_codes"] == []

        settled = fx.read_facility(facility["id"])
        assert settled["consecutive_breach_count"] == 0
        assert settled["last_covenant_status"] == "PASS"
        assert settled["status"] == "ACTIVE"


# ─── Cross-entity and aggregate money rules ──────────────────────────────────

def _panel_with_a_mismatched_and_a_matching_payee():
    """Two receipted advances, one wired to a foreign account, one to 4417."""
    scenario = fx.setup_facility_panel()
    rogue = fx.book_advance(
        scenario.facility["id"],
        scenario.custodian["id"],
        investor_commitment_id=scenario.commitment["id"],
        loan_amount_cents=500_000_000,
        payee_name="Rogue Escrow LLC",
        payee_account_last4="9999",
    )
    fx.file_receipt(rogue["id"], scenario.custodian["id"])
    clean = fx.book_advance(
        scenario.facility["id"],
        scenario.custodian["id"],
        investor_commitment_id=scenario.commitment["id"],
        loan_amount_cents=500_000_000,
    )
    fx.file_receipt(clean["id"], scenario.custodian["id"])
    scenario.rogue = rogue
    scenario.clean = clean
    return scenario


class TestPayeeAccountMustMatchTheFacility:
    def test_the_comparand_lives_on_the_facility_and_the_wire_state_rule_outranks_it(self):
        """A refused verification leaves a pending wire, which funding reports first.

        PRD 2.8: "The wire's `payee_account_last4` equals the owning facility's
        `settlement_account_last4`, failing with `ERR_PAYEE_ACCOUNT_MISMATCH`
        (422). This is the core wire-fraud control: funds leave only to the
        facility's pre-registered settlement account. It is enforced on the wire
        decision and again at funding time, so that a settlement account changed
        after verification cannot be exploited. On the decision endpoint the check
        applies only when the decision is to verify; a decision to block always
        succeeds."

        PRD 2.8: "The advance's wire instruction is `VERIFIED`, failing funding
        with `ERR_WIRE_NOT_VERIFIED` (409). No advance funds on an unverified or
        blocked wire, whatever the collateral looks like."

        Design: Corner/validations/corner_val_payee_account_must_match_facility_settlement_account
        """
        scenario = _panel_with_a_mismatched_and_a_matching_payee()
        assert scenario.facility["settlement_account_last4"] == "4417"

        rogue_wire = _only_wire_of(scenario.rogue["id"])
        assert rogue_wire["payee_account_last4"] == "9999"
        validate_error(
            api_client.decide_wire_instruction(
                rogue_wire["id"],
                make.wire_decision_payload("VERIFY", callback_reference="CB-991"),
                WIRE_OPERATOR,
            ),
            ApiErrorId.ERR_PAYEE_ACCOUNT_MISMATCH,
        )
        still_pending = _only_wire_of(scenario.rogue["id"])
        assert still_pending["status"] == "PENDING_VERIFICATION"
        assert still_pending["decided_by_user_id"] is None

        # Priority 19 speaks before priority 20 gets a second chance at funding.
        validate_error(
            api_client.fund_advance(scenario.rogue["id"], COLLATERAL_ANALYST),
            ApiErrorId.ERR_WIRE_NOT_VERIFIED,
        )
        assert fx.read_advance(scenario.rogue["id"])["funding_status"] == "REQUESTED"

        clean_wire = fx.verify_wire(
            _only_wire_of(scenario.clean["id"])["id"], callback_reference="CB-992"
        )
        asserts.assert_wire_instruction(clean_wire)
        assert clean_wire["status"] == "VERIFIED"
        assert clean_wire["decided_by_user_id"] == "wo_1"

        funded = fx.fund_advance(scenario.clean["id"])
        assert funded["advance_amount_cents"] == 490_000_000

        # Only the matched-payee advance moved money.
        assert fx.read_facility(scenario.facility["id"])[
            "outstanding_principal_cents"
        ] == 490_000_000


def _facility_with_a_capped_conforming_book():
    """CONFORMING capped at 1,960,000,000; SCRATCH_AND_DENT left uncapped."""
    fx.set_clock("2026-08-01T00:00:00Z")
    facility = fx.book_facility()
    fx.add_rate_row(facility["id"], product_sublimit_cents=1_960_000_000)
    # The payload omits `product_sublimit_cents` so the declared null default
    # applies and the per-product ceiling is disabled for this row.
    validate_success(
        api_client.create_product_advance_rate(
            facility["id"], dict(DRY_SCRATCH_AND_DENT_ROW), CREDIT_OFFICER
        ),
        expected_status=201,
    )
    fx.approve_facility(facility["id"])

    scenario = fx.Scenario(facility=fx.read_facility(facility["id"]))
    scenario.custodian = fx.register_custodian(facility["id"])
    scenario.investor = fx.register_investor(facility["id"])
    scenario.commitment = fx.record_commitment(
        facility["id"], scenario.investor["id"]
    )
    return scenario


class TestProductSublimitIsAnAggregateRule:
    def test_an_exhausted_product_bucket_refuses_while_an_uncapped_one_funds(self):
        """No single advance is at fault, and a null sublimit is not a zero one.

        PRD 2.8: "When the rate row declares a `product_sublimit_cents`, that
        sublimit less the product's current outstanding is strictly greater than
        zero, failing with `ERR_PRODUCT_SUBLIMIT_EXCEEDED` (422). A null
        `product_sublimit_cents` disables the rule entirely."

        PRD 3.4: "When the rate row declares a non-null `product_sublimit_cents`,
        the list also contains that sublimit less the product's current
        outstanding, where a product's current outstanding is the sum of
        `outstanding_balance_cents` over the facility's advances that share the
        same `product_code` and whose `funding_status` is `FUNDED` or `SHIPPED`."

        Design: Corner/validations/corner_val_product_sublimit_is_aggregate_and_null_disables_it
        """
        scenario = _facility_with_a_capped_conforming_book()
        facility_id = scenario.facility["id"]

        first = fx.book_advance_ready_to_fund(
            scenario,
            investor_commitment_id=scenario.commitment["id"],
            callback_reference="CB-992",
        )
        assert fx.fund_advance(first["id"])["advance_amount_cents"] == 1_960_000_000

        blocked = fx.book_advance_ready_to_fund(
            scenario,
            investor_commitment_id=scenario.commitment["id"],
            callback_reference="CB-993",
            loan_amount_cents=500_000_000,
        )
        uncapped = fx.book_advance_ready_to_fund(
            scenario,
            callback_reference="CB-994",
            product_code="SCRATCH_AND_DENT",
            loan_amount_cents=500_000_000,
            note_rate=0.0950,
        )

        before = fx.read_facility(facility_id)
        # The facility-level bucket still has ample headroom.
        assert before["availability_cents"] == 18_040_000_000
        assert before["outstanding_principal_cents"] == 1_960_000_000

        validate_error(
            api_client.fund_advance(blocked["id"], COLLATERAL_ANALYST),
            ApiErrorId.ERR_PRODUCT_SUBLIMIT_EXCEEDED,
        )
        refused = fx.read_advance(blocked["id"])
        assert refused["funding_status"] == "REQUESTED"
        assert refused["advance_amount_cents"] == 0
        assert _only_wire_of(blocked["id"])["status"] == "VERIFIED"

        funded = fx.fund_advance(uncapped["id"])
        assert funded["advance_amount_cents"] == 425_000_000
        # No commitment is named, so the commitment cap was skipped as well.
        assert funded["investor_commitment_id"] is None

        after = fx.read_facility(facility_id)
        assert after["scratch_and_dent_outstanding_cents"] == 425_000_000
        assert after["scratch_and_dent_sublimit_cents"] == 1_000_000_000
        assert after["outstanding_principal_cents"] == 2_385_000_000
        assert after["availability_cents"] == 17_615_000_000


def _book_standing_at_thirty_five_per_cent():
    """A 6,000,000,000 book in which investor Zulu holds exactly 0.35 of it."""
    scenario = fx.setup_facility_panel(with_commitment=False)
    facility_id = scenario.facility["id"]

    def approved_investor_with_a_commitment(name):
        investor = fx.register_investor(facility_id, investor_name=name)
        commitment = fx.record_commitment(facility_id, investor["id"])
        return investor, commitment

    scenario.yankee, scenario.yankee_commitment = approved_investor_with_a_commitment(
        "Yankee Aggregator"
    )
    scenario.zulu, scenario.zulu_commitment = approved_investor_with_a_commitment(
        "Zulu Master Trust"
    )
    scenario.whiskey, scenario.whiskey_commitment = (
        approved_investor_with_a_commitment("Whiskey Capital")
    )

    def wet_advance(commitment_id, loan_amount_cents, callback_reference):
        return fx.book_advance_ready_to_fund(
            scenario,
            investor_commitment_id=commitment_id,
            callback_reference=callback_reference,
            funding_type="WET",
            loan_amount_cents=loan_amount_cents,
        )

    scenario.yankee_advance = fx.fund_advance(
        wet_advance(scenario.yankee_commitment["id"], 4_062_500_000, "CB-995")["id"]
    )
    scenario.zulu_advance = fx.fund_advance(
        wet_advance(scenario.zulu_commitment["id"], 2_187_500_000, "CB-996")["id"]
    )
    scenario.zulu_second = wet_advance(
        scenario.zulu_commitment["id"], 1_000_000_000, "CB-997"
    )
    scenario.whiskey_advance = wet_advance(
        scenario.whiskey_commitment["id"], 1_000_000_000, "CB-998"
    )
    return scenario


class TestConcentrationSolveHasItsOwnError:
    def test_a_solved_headroom_of_zero_names_the_investor_not_the_minimum(self):
        """The same loan is refused for Zulu and funded in full for Whiskey.

        PRD 2.8: "The concentration solve returned at least the minimum advance
        size, failing funding with `ERR_INVESTOR_CONCENTRATION_EXCEEDED` (422).
        This fires only when the binding constraint was a take-out investor's
        concentration limit, so the borrower knows which knob to turn, and it is
        not evaluated at all while the hypothetical post-funding outstanding is at
        or below the de-minimis concentration floor."

        Design: Corner/validations/corner_val_concentration_solve_below_minimum_is_its_own_error
        """
        scenario = _book_standing_at_thirty_five_per_cent()

        # floor(4,062,500,000 * 0.96), solved below the de-minimis floor.
        assert scenario.yankee_advance["advance_amount_cents"] == 3_900_000_000
        # floor(2,187,500,000 * 0.96) coincides with the exact headroom, so the
        # solve returns the proposal unchanged rather than reducing it.
        assert scenario.zulu_advance["advance_amount_cents"] == 2_100_000_000
        assert scenario.zulu_advance["concentration_capped"] is False
        assert fx.read_investor(scenario.zulu["id"])["exposure_cents"] == 2_100_000_000
        assert fx.read_facility(scenario.facility["id"])[
            "outstanding_principal_cents"
        ] == 6_000_000_000

        # (0.35 * 6,000,000,000 - 2,100,000,000) / 0.65 solves to zero.
        validate_error(
            api_client.fund_advance(scenario.zulu_second["id"], COLLATERAL_ANALYST),
            ApiErrorId.ERR_INVESTOR_CONCENTRATION_EXCEEDED,
        )
        assert fx.read_advance(scenario.zulu_second["id"])["funding_status"] == (
            "REQUESTED"
        )
        assert fx.read_investor(scenario.zulu["id"])["exposure_cents"] == 2_100_000_000
        # Commitment capacity was never the binding constraint.
        assert fx.read_commitment(scenario.zulu_commitment["id"])[
            "remaining_amount_cents"
        ] == 2_900_000_000

        funded = fx.fund_advance(scenario.whiskey_advance["id"])
        assert funded["advance_amount_cents"] == 960_000_000
        assert funded["concentration_capped"] is False

        facility = fx.read_facility(scenario.facility["id"])
        assert facility["outstanding_principal_cents"] == 6_960_000_000
        assert facility["wet_outstanding_cents"] == 6_960_000_000
        assert fx.read_investor(scenario.whiskey["id"])["exposure_cents"] == 960_000_000
        assert fx.read_investor(scenario.yankee["id"])["exposure_cents"] == (
            3_900_000_000
        )


# ─── Exact-amount rules on cures and repurchases ─────────────────────────────

class TestCurePaymentCeilingSpansBothBuckets:
    def test_one_cent_over_the_two_bucket_sum_is_refused_and_the_sum_fully_cures(self):
        """The ceiling is fees plus remainder, not the call amount alone.

        PRD 2.8: "A cure payment's `amount_cents` is at most the facility's
        `accrued_fee_balance_cents` plus the call's remaining obligation, that
        remaining obligation being `call_amount_cents` less `cured_amount_cents`.
        Failure is `ERR_CURE_PAYMENT_EXCEEDS_OBLIGATION` (422). The waterfall has
        exactly two buckets and no overflow destination, so an over-payment is
        refused rather than credited somewhere."

        Design: Corner/validations/corner_val_cure_payment_overpayment_rejected_then_exact_cure
        """
        scenario = fx.setup_funded_dry_advance()
        facility_id = scenario.facility["id"]

        fx.set_clock("2026-08-11T00:00:00Z")
        run = fx.run_aging(facility_id)
        # 4,763,889 of advance interest plus 1,252,778 of unused-line fee.
        assert run["fee_accrual_cents"] == 6_016_667
        assert run["margin_calls_issued"] == 0
        aged = fx.read_advance(scenario.advance["id"])
        assert aged["dwell_days"] == 10
        assert aged["is_aged"] is False

        call = fx.raise_manual_margin_call(facility_id)
        assert call["call_amount_cents"] == 196_000_000
        _calls, meta = validate_paginated(
            api_client.list_facility_margin_calls(facility_id, CREDIT_OFFICER)
        )
        assert meta["total_count"] == 1

        borrower = make_borrower_headers(facility_id)
        validate_error(
            api_client.create_cure_payment(
                call["id"],
                make.cure_payment_payload(202_016_668, call["version"]),
                borrower,
            ),
            ApiErrorId.ERR_CURE_PAYMENT_EXCEEDS_OBLIGATION,
        )
        # The refusal applied nothing, so the same token is still current.
        assert fx.read_margin_call(call["id"])["version"] == call["version"]
        assert fx.read_facility(facility_id)["accrued_fee_balance_cents"] == 6_016_667

        payment = validate_success(
            api_client.create_cure_payment(
                call["id"],
                make.cure_payment_payload(202_016_667, call["version"]),
                borrower,
            ),
            expected_status=201,
        )
        asserts.assert_cure_payment(payment)
        assert payment["applied_to_fees_cents"] == 6_016_667
        assert payment["applied_to_principal_cents"] == 196_000_000
        assert payment["principal_allocation"] == [
            {"advance_id": scenario.advance["id"], "amount_cents": 196_000_000}
        ]

        cured = fx.read_margin_call(call["id"])
        assert cured["cured_amount_cents"] == cured["call_amount_cents"]
        assert cured["status"] == "CURED"

        facility = fx.read_facility(facility_id)
        # The last open call closing lifts the restriction.
        assert facility["status"] == "ACTIVE"
        assert facility["open_margin_call_count"] == 0
        assert facility["accrued_fee_balance_cents"] == 0
        assert facility["outstanding_principal_cents"] == 1_764_000_000
        assert facility["availability_cents"] == 18_236_000_000
        assert fx.read_advance(scenario.advance["id"])[
            "outstanding_balance_cents"
        ] == 1_764_000_000

        summary = fx.read_exposure_summary(facility_id)
        assert summary["ledger_debit_total_cents"] == 1_960_000_000
        assert summary["ledger_credit_total_cents"] == 196_000_000
        asserts.assert_both_conservation_invariants(summary)


class TestRepurchasePaysToTheCent:
    def test_a_cent_short_and_a_cent_over_are_both_refused_without_a_trace(self):
        """Equality, not sufficiency, and the rejections write nothing at all.

        PRD 2.8: "The supplied `payment_amount_cents` equals the advance's
        `outstanding_balance_cents` exactly, failing with
        `ERR_REPURCHASE_AMOUNT_MISMATCH` (422). Partial repurchases do not exist;
        this exactness is what makes the ledger conservation invariant exactly
        checkable."

        Design: Corner/validations/corner_val_repurchase_must_match_outstanding_to_the_cent
        """
        scenario = fx.setup_funded_dry_advance()
        borrower = make_borrower_headers(scenario.facility["id"])
        version_before = fx.advance_version(scenario.advance["id"])

        for attempt in (1_959_999_999, 1_960_000_001):
            validate_error(
                api_client.repurchase_advance(
                    scenario.advance["id"], make.repurchase_payload(attempt), borrower
                ),
                ApiErrorId.ERR_REPURCHASE_AMOUNT_MISMATCH,
            )

        _entries, meta = validate_paginated(
            api_client.list_advance_ledger_entries(
                scenario.advance["id"], CREDIT_OFFICER
            )
        )
        assert meta["total_count"] == 1
        untouched = fx.read_advance(scenario.advance["id"])
        assert untouched["version"] == version_before
        assert untouched["funding_status"] == "FUNDED"
        assert untouched["custody_status"] == "RECEIVED_CLEAR"

        repurchased = fx.repurchase_advance(scenario.advance["id"], 1_960_000_000)
        assert repurchased["funding_status"] == "REPURCHASED"
        assert repurchased["outstanding_balance_cents"] == 0

        entries, meta = validate_paginated(
            api_client.list_advance_ledger_entries(
                scenario.advance["id"], CREDIT_OFFICER
            )
        )
        assert meta["total_count"] == 2
        asserts.assert_entry_types_in_order(
            entries, [("ADVANCE_FUNDED", "DEBIT"), ("REPURCHASE", "CREDIT")]
        )

        facility = fx.read_facility(scenario.facility["id"])
        assert facility["outstanding_principal_cents"] == 0
        assert facility["availability_cents"] == 20_000_000_000

        released = fx.read_commitment(scenario.commitment["id"])
        assert released["allocated_amount_cents"] == 0
        assert released["remaining_amount_cents"] == 5_000_000_000
        assert released["status"] == "OPEN"
        # A repurchase is not an investor purchase.
        assert released["settled_amount_cents"] == 0
        assert fx.read_investor(scenario.investor["id"])["exposure_cents"] == 0


# ─── A temporal half hidden inside a status rule ─────────────────────────────

class TestBaileeLetterMustBeLive:
    def test_a_stale_letter_still_stored_as_issued_does_not_support_a_purchase(self):
        """Nothing expired the letter, and the clock alone defeats it.

        PRD 2.8: "The advance has a bailee letter in `ISSUED` status whose
        `expires_at` is strictly after the logical clock, failing purchase with
        `ERR_BAILEE_LETTER_REQUIRED` (409). An `EXPIRED` or `REVOKED` letter fails
        identically to a missing one."

        Design: Corner/validations/corner_val_bailee_letter_must_be_live_not_merely_issued
        """
        scenario = fx.setup_shipped_advance()
        stale_letter = scenario.bailee_letter
        asserts.assert_instant(stale_letter["effective_from"], "2026-08-01T00:00:00Z")
        asserts.assert_instant(stale_letter["expires_at"], "2026-08-31T00:00:00Z")
        assert stale_letter["status"] == "ISSUED"

        fx.set_clock("2026-09-05T00:00:00Z")
        second = fx.book_advance_ready_to_fund(
            scenario,
            investor_commitment_id=scenario.commitment["id"],
            callback_reference="CB-999",
            loan_amount_cents=1_000_000_000,
            note_rate=0.0625,
        )
        assert fx.fund_advance(second["id"])["advance_amount_cents"] == 980_000_000
        fresh_letter = fx.ship_advance(second["id"], scenario.investor["id"])
        asserts.assert_bailee_letter(fresh_letter)
        asserts.assert_instant(fresh_letter["effective_from"], "2026-09-05T00:00:00Z")
        asserts.assert_instant(fresh_letter["expires_at"], "2026-10-05T00:00:00Z")
        assert fresh_letter["bailee_period_days"] == 30

        # No aging run has touched the first letter, so its status is unchanged.
        validate_error(
            api_client.purchase_advance(
                scenario.advance["id"],
                COLLATERAL_ANALYST,
                make.purchase_payload("WIRE-IN-7781"),
            ),
            ApiErrorId.ERR_BAILEE_LETTER_REQUIRED,
        )
        held = fx.read_advance(scenario.advance["id"])
        assert held["funding_status"] == "SHIPPED"
        assert held["outstanding_balance_cents"] == 1_960_000_000
        assert fx.advance_bailee_letters(scenario.advance["id"])[-1]["status"] == (
            "ISSUED"
        )

        purchased = fx.purchase_advance(
            second["id"], scenario.investor["id"], proceeds_reference="WIRE-IN-7782"
        )
        assert purchased["funding_status"] == "PURCHASED"
        assert purchased["outstanding_balance_cents"] == 0
        assert fx.advance_bailee_letters(second["id"])[-1]["status"] == "HONORED"

        entries, meta = validate_paginated(
            api_client.list_advance_ledger_entries(second["id"], CREDIT_OFFICER)
        )
        assert meta["total_count"] == 2
        assert entries[1]["entry_type"] == "INVESTOR_PROCEEDS"
        assert entries[1]["direction"] == "CREDIT"
        assert entries[1]["amount_cents"] == 980_000_000

        commitment = fx.read_commitment(scenario.commitment["id"])
        assert commitment["settled_amount_cents"] == 980_000_000
        # The unsold advance remains allocated.
        assert commitment["allocated_amount_cents"] == 1_960_000_000
        assert fx.read_investor(scenario.investor["id"])["exposure_cents"] == (
            1_960_000_000
        )
        assert fx.read_facility(scenario.facility["id"])[
            "outstanding_principal_cents"
        ] == 1_960_000_000
