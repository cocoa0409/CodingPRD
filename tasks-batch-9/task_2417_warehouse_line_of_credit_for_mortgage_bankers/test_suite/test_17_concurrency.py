"""Optimistic-concurrency corners: three tokens, three namespaces, one tier.

Each of the three guarded writes is replayed with the token it already consumed.
The refusal must name that write's own 412 code, must leave the parent row
untouched so the retry succeeds, and must outrank every state check while still
yielding to schema validation.
"""

from test_helpers import (
    COLLATERAL_ANALYST,
    CREDIT_OFFICER,
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


class TestAdvanceCreateStaleFacilityVersion:
    def test_the_facility_token_moves_on_booking_and_funding_and_on_nothing_else(self):
        """A consumed token is refused, and the rejection consumes nothing itself.

        PRD 2.7: "A `POST /advances` request must carry
        `expected_facility_version` matching the target `WarehouseFacility`'s
        current `version`."

        PRD 2.10: "Because a cascade bumps versions, it is also the mechanism by
        which an optimistic-concurrency token held by another client goes stale:
        booking an advance advances the facility's `version`, and funding it
        advances the facility's `version` again along with the advance's, the
        wire's and the commitment's."

        PRD 2.8: "Where the endpoint declares a version token it equals the parent
        row's current `version`, failing with the 412 code of §2.7 that matches
        the parent."

        Design: Corner/cross_cutting_complexity_layers/corner_occ_advance_create_stale_facility_version
        """
        scenario = fx.setup_funded_dry_advance()
        facility_id = scenario.facility["id"]
        custodian_id = scenario.custodian["id"]
        commitment_id = scenario.commitment["id"]
        # The token the first booking itself consumed.
        stale_version = scenario.facility_version_before_booking

        second_booking = make.advance_payload(
            facility_id,
            custodian_id,
            stale_version,
            investor_commitment_id=commitment_id,
            loan_amount_cents=1_000_000_000,
            note_rate=0.0625,
        )
        validate_error(
            api_client.create_advance(second_booking, COLLATERAL_ANALYST),
            ApiErrorId.ERR_STALE_FACILITY_VERSION,
        )

        # Read after the rejection: the booking and the funding each moved the
        # facility once, while the receipt and the wire decision moved it not at all.
        fresh_version = fx.facility_version(facility_id)
        assert fresh_version == stale_version + 2

        second_booking["expected_facility_version"] = fresh_version
        booked = validate_success(
            api_client.create_advance(second_booking, COLLATERAL_ANALYST), 201
        )
        asserts.assert_advance(booked)
        assert booked["funding_status"] == "REQUESTED"

        advances, advance_meta = validate_paginated(
            api_client.list_advances(CREDIT_OFFICER)
        )
        # The 412 left no orphan row behind.
        assert advance_meta["total_count"] == 2
        assert {row["id"] for row in advances} == {scenario.advance["id"], booked["id"]}

        # Schema failure at priority 7 outranks the token check at priority 8.
        malformed = dict(second_booking)
        malformed["expected_facility_version"] = stale_version
        del malformed["loan_amount_cents"]
        validate_error(
            api_client.create_advance(malformed, COLLATERAL_ANALYST),
            ApiErrorId.ERR_VALIDATION,
        )

        # The token check in turn outranks every state check below it.
        token_before_suspension = fx.facility_version(facility_id)
        assert fx.suspend_facility(facility_id)["status"] == "SUSPENDED"
        third_booking = make.advance_payload(
            facility_id,
            custodian_id,
            token_before_suspension,
            investor_commitment_id=commitment_id,
            loan_amount_cents=1_000_000_000,
            note_rate=0.0625,
        )
        validate_error(
            api_client.create_advance(third_booking, COLLATERAL_ANALYST),
            ApiErrorId.ERR_STALE_FACILITY_VERSION,
        )


class TestValuationStaleAdvanceVersion:
    def test_the_valuation_token_is_scoped_to_the_advance_alone(self):
        """A replayed mark stores nothing, and 412 still wins on a terminal advance.

        PRD 2.7: "A `POST /advances/{id}/valuation` request must carry
        `expected_advance_version` matching the target `Advance`'s current
        `version`. Re-marking collateral is likewise repeatable, so the token
        exists to stop a client from overwriting a valuation that has already
        driven a margin call. A mismatch is rejected with
        `ERR_STALE_ADVANCE_VERSION` (HTTP 412)."

        PRD 2.7: "No other endpoint takes a version field, and no other endpoint
        may reject a request on version grounds."

        PRD 2.8: "`funding_status` permits the trigger: `REQUESTED` for funding;
        `FUNDED` or `SHIPPED` for shipment, valuation, repurchase and raising a
        repurchase demand; `SHIPPED` for purchase; and `REQUESTED`, `FUNDED` or
        `SHIPPED` for filing a receipt."

        Design: Corner/cross_cutting_complexity_layers/corner_occ_valuation_stale_advance_version
        """
        scenario = fx.setup_funded_dry_advance()
        advance_id = scenario.advance["id"]
        first_token = fx.advance_version(advance_id)
        facility_version_before = fx.facility_version(scenario.facility["id"])

        valued = validate_success(
            api_client.value_advance(
                advance_id,
                make.valuation_payload(2_050_000_000, first_token),
                COLLATERAL_ANALYST,
            )
        )
        # min(2,000,000,000 loan, 2,050,000,000 market) is the loan amount.
        assert valued["eligible_collateral_value_cents"] == 1_960_000_000
        assert valued["required_paydown_cents"] == 0
        assert fx.read_facility(scenario.facility["id"])["status"] == "ACTIVE"
        assert fx.read_facility(scenario.facility["id"])["open_margin_call_count"] == 0

        # Replaying the consumed token names the advance's own code.
        validate_error(
            api_client.value_advance(
                advance_id,
                make.valuation_payload(2_020_000_000, first_token),
                COLLATERAL_ANALYST,
            ),
            ApiErrorId.ERR_STALE_ADVANCE_VERSION,
        )

        after_rejection = fx.read_advance(advance_id)
        assert after_rejection["version"] == first_token + 1
        # Not even the market value of the rejected mark was stored.
        assert after_rejection["market_value_cents"] == 2_050_000_000
        # A valuation is scoped to the advance: the facility did not move.
        assert fx.facility_version(scenario.facility["id"]) == facility_version_before

        re_valued = validate_success(
            api_client.value_advance(
                advance_id,
                make.valuation_payload(2_020_000_000, after_rejection["version"]),
                COLLATERAL_ANALYST,
            )
        )
        assert re_valued["market_value_cents"] == 2_020_000_000

        fx.ship_advance(advance_id, scenario.investor["id"])
        purchased = validate_success(
            api_client.purchase_advance(
                advance_id, COLLATERAL_ANALYST, make.purchase_payload("SETL-OCC2")
            )
        )
        assert purchased["funding_status"] == "PURCHASED"

        # Priority 8 precedes priority 11, so staleness is reported first.
        validate_error(
            api_client.value_advance(
                advance_id,
                make.valuation_payload(1_000_000_000, first_token),
                COLLATERAL_ANALYST,
            ),
            ApiErrorId.ERR_STALE_ADVANCE_VERSION,
        )
        # With a fresh token the state check below it finally speaks.
        validate_error(
            api_client.value_advance(
                advance_id,
                make.valuation_payload(
                    1_000_000_000, fx.advance_version(advance_id)
                ),
                COLLATERAL_ANALYST,
            ),
            ApiErrorId.ERR_ADVANCE_INVALID_STATE,
        )


class TestCurePaymentStaleMarginCallVersion:
    def test_a_repeatable_partial_cure_can_only_be_refused_on_staleness(self):
        """Nothing but the token stands between the borrower and a double payment.

        PRD 2.7: "A `POST /margin-calls/{id}/cure-payments` request must carry
        `expected_margin_call_version` matching the target `MarginCall`'s current
        `version`. Partial cures are legitimately repeatable, so a later payment
        can never be refused on state grounds; the token instead protects the
        borrower from sizing a payment against an obsolete `cured_amount_cents`. A
        mismatch is rejected with `ERR_STALE_MARGIN_CALL_VERSION` (HTTP 412)."

        PRD 3.6: "The call's `cured_amount_cents` rises by
        `applied_to_principal_cents`, and its status becomes `CURED` when
        `cured_amount_cents` has reached or passed `call_amount_cents` and
        `PARTIALLY_CURED` while it is still short."

        PRD 2.8: "The addressed call is `ISSUED` or `PARTIALLY_CURED`, failing
        both cure payments and waiver with `ERR_MARGIN_CALL_NOT_OPEN` (409).
        `CURED`, `WAIVED` and `DEFAULTED` calls accept no payment and cannot be
        waived."

        Design: Corner/cross_cutting_complexity_layers/corner_occ_cure_payment_stale_margin_call_version
        """
        scenario = fx.setup_funded_dry_advance()
        facility_id = scenario.facility["id"]
        borrower = make_borrower_headers(facility_id)

        call = fx.raise_manual_margin_call(facility_id)
        assert call["call_amount_cents"] == 196_000_000
        assert fx.read_facility(facility_id)["status"] == "RESTRICTED"
        first_token = call["version"]

        first_payment = validate_success(
            api_client.create_cure_payment(
                call["id"], make.cure_payment_payload(96_000_000, first_token), borrower
            ),
            201,
        )
        asserts.assert_cure_payment(first_payment)
        # No fee balance has accrued, so the first bucket of the waterfall is empty.
        assert first_payment["applied_to_fees_cents"] == 0
        assert first_payment["applied_to_principal_cents"] == 96_000_000
        partially_cured = fx.read_margin_call(call["id"])
        assert partially_cured["status"] == "PARTIALLY_CURED"
        assert partially_cured["cured_amount_cents"] == 96_000_000
        assert fx.read_advance(scenario.advance["id"])[
            "outstanding_balance_cents"
        ] == 1_864_000_000

        # 50,000,000 is well inside the remaining obligation of 100,000,000 and the
        # call is still open, so staleness is the only possible ground for refusal.
        validate_error(
            api_client.create_cure_payment(
                call["id"], make.cure_payment_payload(50_000_000, first_token), borrower
            ),
            ApiErrorId.ERR_STALE_MARGIN_CALL_VERSION,
        )
        unchanged = fx.read_margin_call(call["id"])
        assert unchanged["version"] == first_token + 1
        assert unchanged["cured_amount_cents"] == 96_000_000
        payments, payment_meta = validate_paginated(
            api_client.list_cure_payments(call["id"], CREDIT_OFFICER)
        )
        # The rejected payment created no row.
        assert payment_meta["total_count"] == 1

        facility_version_before = fx.facility_version(facility_id)
        second_payment = validate_success(
            api_client.create_cure_payment(
                call["id"],
                make.cure_payment_payload(100_000_000, unchanged["version"]),
                borrower,
            ),
            201,
        )
        assert second_payment["applied_to_principal_cents"] == 100_000_000
        cured = fx.read_margin_call(call["id"])
        assert cured["status"] == "CURED"
        assert cured["cured_amount_cents"] == 196_000_000
        assert fx.read_facility(facility_id)["status"] == "ACTIVE"
        # A cure payment is the one guarded write that also moves the facility.
        assert fx.facility_version(facility_id) > facility_version_before

        # Priority 8 precedes both the open-state check and the amount ceiling.
        validate_error(
            api_client.create_cure_payment(
                call["id"], make.cure_payment_payload(10_000_000, first_token), borrower
            ),
            ApiErrorId.ERR_STALE_MARGIN_CALL_VERSION,
        )
        validate_error(
            api_client.create_cure_payment(
                call["id"],
                make.cure_payment_payload(10_000_000, cured["version"]),
                borrower,
            ),
            ApiErrorId.ERR_MARGIN_CALL_NOT_OPEN,
        )

        assert fx.read_advance(scenario.advance["id"])[
            "outstanding_balance_cents"
        ] == 1_764_000_000
        principal_entries, principal_meta = validate_paginated(
            api_client.list_facility_ledger_entries(
                facility_id, CREDIT_OFFICER, {"entry_type": "CURE_PRINCIPAL"}
            )
        )
        assert principal_meta["total_count"] == 2
        assert [entry["amount_cents"] for entry in principal_entries] == [
            96_000_000,
            100_000_000,
        ]
        assert [entry["direction"] for entry in principal_entries] == ["CREDIT", "CREDIT"]
        summary = fx.read_exposure_summary(facility_id)
        asserts.assert_both_conservation_invariants(summary)
        assert summary["outstanding_principal_cents"] == 1_764_000_000
        assert summary["accrued_fee_balance_cents"] == 0
