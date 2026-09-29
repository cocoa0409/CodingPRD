"""Role corners: exclusive ladders, row-scoped identities and the four-eyes gates.

Authorisation here is proven to be per-endpoint rather than per-tier, to be
resolved before existence and before state, and — for the three counterparty
roles — to be a primary-key lookup with two distinguishable failure modes.
"""

from test_helpers import (
    COLLATERAL_ANALYST,
    CREDIT_OFFICER,
    NON_EXISTENT_UUID,
    SECOND_CREDIT_OFFICER,
    WIRE_OPERATOR,
    ApiErrorId,
    api_client,
    make_borrower_headers,
    make_credit_officer_headers,
    make_custodian_headers,
    make_investor_headers,
    make_wire_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as asserts
from test_helpers import factories as make
from test_helpers import fixtures as fx


def _officer_exclusive_requests(scenario, demand_id):
    """The officer-only requests of this facility's lifetime, as callables."""
    facility_id = scenario.facility["id"]
    investor_id = scenario.second_investor["id"]
    return (
        (
            "register an investor",
            lambda h: api_client.create_investor(
                facility_id,
                make.investor_payload(investor_name="Gamma Whole Loan Trust"),
                h,
            ),
        ),
        ("approve an investor", lambda h: api_client.approve_investor(investor_id, h)),
        (
            "suspend an investor",
            lambda h: api_client.suspend_investor(
                investor_id, {"reason": "Rating downgrade below policy floor"}, h
            ),
        ),
        (
            "issue a margin call by hand",
            lambda h: api_client.create_margin_call(
                make.margin_call_payload(facility_id, "COVENANT_BREACH"), h
            ),
        ),
        (
            "waive a margin call",
            lambda h: api_client.waive_margin_call(
                scenario.margin_call["id"], {"reason": "Cross-role waiver attempt"}, h
            ),
        ),
        (
            "suspend the facility",
            lambda h: api_client.suspend_facility(
                facility_id, {"reason": "Cross-role suspension attempt"}, h
            ),
        ),
        ("reinstate the facility", lambda h: api_client.reinstate_facility(facility_id, h)),
        (
            "demand a repurchase",
            lambda h: api_client.create_repurchase_demand(
                scenario.advance["id"], {"reason": "DWELL_EXCEEDED"}, h
            ),
        ),
        (
            "escalate a demand",
            lambda h: api_client.escalate_repurchase_demand(demand_id, h),
        ),
        (
            "suspend the custodian",
            lambda h: api_client.suspend_custodian(
                scenario.custodian["id"], {"reason": "Cross-role suspension attempt"}, h
            ),
        ),
    )


class TestCreditOfficerExclusiveLadder:
    def test_every_officer_only_step_succeeds_and_no_neighbouring_role_may_take_it(self):
        """The whole credit ladder in one facility lifetime, then ten refusals.

        PRD 2.1: "It books facilities, configures advance-rate grids and
        sublimits, curates the approved-investor list, records take-out
        commitments, issues and waives margin calls, waives covenant breaches, and
        escalates repurchase demands."

        PRD 2.1: "`CollateralAnalyst` is middle-office collateral operations: it
        values collateral, ships files under bailee letters, drives purchases and
        repurchases, may act on wire decisions and on funding, and shares receipt
        filing and cure with the custodian — but it approves nothing and waives
        nothing."

        PRD 2.1: "Its read access reaches only the facility, the advance and the
        advance's wire instructions."

        PRD 3.8: "Returning from `SUSPENDED` is a deliberate manual act by a
        `CreditOfficer`, and it demands a fully clean facility:
        `open_margin_call_count` zero, no margin call of the facility in
        `DEFAULTED`, `last_covenant_status` one of `NOT_TESTED`, `PASS` or
        `WAIVED`, and `escalated_demand_count` zero."

        PRD 3.8: "From `ACTIVE`, the facility moves to `RESTRICTED` whenever any
        margin call reaches `ISSUED`, any covenant test is stored in `BREACH`, or
        any repurchase demand reaches `ESCALATED`."

        Design: Corner/rbac/corner_rbac_credit_officer_exclusive_ladder_is_permitted
        """
        # The panel already spent seven officer-only steps: booking the facility,
        # configuring a rate row, approving the facility, registering a custodian,
        # registering an investor, approving it and recording its commitment.
        scenario = fx.setup_funded_dry_advance()
        facility_id = scenario.facility["id"]

        second = fx.register_investor(
            facility_id,
            approve=False,
            investor_name="Beta Conduit Partners",
            counterparty_rating="B",
            concentration_limit_pct=0.20,
        )
        assert second["status"] == "PENDING_APPROVAL"
        # Suspension needs an APPROVED investor, so this approve is a precondition.
        approved = validate_success(api_client.approve_investor(second["id"], CREDIT_OFFICER))
        assert approved["status"] == "APPROVED"
        scenario.second_investor = fx.suspend_investor(second["id"])
        assert scenario.second_investor["status"] == "SUSPENDED"

        call = fx.raise_manual_margin_call(facility_id)
        # floor(1,960,000,000 * 0.10) for a covenant-breach call.
        assert call["call_amount_cents"] == 196_000_000
        assert call["issued_by_user_id"] == "co_1"
        assert fx.read_facility(facility_id)["status"] == "RESTRICTED"

        scenario.margin_call = fx.waive_margin_call(call["id"])
        assert scenario.margin_call["status"] == "WAIVED"
        assert scenario.margin_call["waived_by_user_id"] == "co_2"
        assert fx.read_facility(facility_id)["status"] == "ACTIVE"

        assert fx.suspend_facility(facility_id)["status"] == "SUSPENDED"
        # All four reinstatement preconditions hold: the call is waived, none is
        # defaulted, no covenant test exists and nothing is escalated yet.
        reinstated = fx.reinstate_facility(facility_id)
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["open_margin_call_count"] == 0
        assert reinstated["last_covenant_status"] == "NOT_TESTED"
        assert reinstated["escalated_demand_count"] == 0

        demand = fx.raise_repurchase_demand(
            scenario.advance["id"], "CUSTODY_EXCEPTION_UNCURED"
        )
        asserts.assert_repurchase_demand(demand)
        assert demand["status"] == "OPEN"
        assert demand["demand_amount_cents"] == 1_960_000_000
        asserts.assert_instant(demand["raised_at"], "2026-08-01T00:00:00Z")
        # Ten days is the borrower's, and escalation waits for it.
        asserts.assert_instant(demand["deadline_at"], "2026-08-11T00:00:00Z")

        fx.set_clock("2026-08-11T00:00:00Z")
        escalated = fx.escalate_repurchase_demand(demand["id"])
        assert escalated["status"] == "ESCALATED"
        after_escalation = fx.read_facility(facility_id)
        assert after_escalation["escalated_demand_count"] == 1
        assert after_escalation["status"] == "RESTRICTED"

        assert fx.suspend_custodian(scenario.custodian["id"])["status"] == "SUSPENDED"

        # Every one of those officer-only steps is refused to the two neighbouring
        # internal roles, whatever the addressed row's current state.
        requests = _officer_exclusive_requests(scenario, demand["id"])
        facility_before = fx.read_facility(facility_id)
        _, ledger_before = validate_paginated(
            api_client.list_facility_ledger_entries(facility_id, CREDIT_OFFICER)
        )
        for label, send in requests:
            for headers in (COLLATERAL_ANALYST, WIRE_OPERATOR):
                response = send(headers)
                assert response.status_code == 403, (
                    f"only a CreditOfficer may {label}"
                )
                validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)

        facility_after = fx.read_facility(facility_id)
        assert facility_after["version"] == facility_before["version"]
        assert facility_after["status"] == "RESTRICTED"
        assert facility_after["escalated_demand_count"] == 1
        assert fx.read_investor(scenario.second_investor["id"])["status"] == "SUSPENDED"
        assert fx.read_margin_call(scenario.margin_call["id"])["status"] == "WAIVED"
        _, ledger_after = validate_paginated(
            api_client.list_facility_ledger_entries(facility_id, CREDIT_OFFICER)
        )
        assert ledger_after["total_count"] == ledger_before["total_count"]
        demands, demand_meta = validate_paginated(
            api_client.list_advance_repurchase_demands(
                scenario.advance["id"], CREDIT_OFFICER
            )
        )
        assert demand_meta["total_count"] == 1
        assert demands[0]["status"] == "ESCALATED"


class TestAnalystExclusivesAndCrossRoleDenials:
    def test_authorisation_outranks_both_existence_and_lifecycle_state(self):
        """Valuation and shipment belong to one role, and 403 hides everything else.

        PRD 2.1: "If the supplied role is not among the roles authorised for the
        addressed endpoint in §4, the request fails with `ERR_UNAUTHORIZED` (HTTP
        403) — and role authorisation likewise precedes existence, so a
        `CollateralAnalyst` attempting a facility approval receives 403 even when
        the facility identifier does not exist."

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

        PRD 2.1: "`WireOperator` is the treasury wire desk; it exists so that the
        four-eyes rule is testable, because it shares both the wire-decision
        capability and the funding capability with `CollateralAnalyst`, meaning
        authorisation alone never guarantees that the two steps were performed by
        two different people."

        Design: Corner/rbac/corner_rbac_analyst_exclusives_and_cross_role_denials
        """
        scenario = fx.setup_funded_dry_advance()
        facility_id = scenario.facility["id"]
        advance_id = scenario.advance["id"]
        stale_facility_version = scenario.facility_version_before_booking
        advance_version = fx.advance_version(advance_id)

        valuation_body = make.valuation_payload(2_100_000_000, advance_version)
        valued = validate_success(
            api_client.value_advance(advance_id, valuation_body, COLLATERAL_ANALYST)
        )
        # floor(min(2,000,000,000, 2,100,000,000) * 0.98): the loan amount caps it.
        assert valued["eligible_collateral_value_cents"] == 1_960_000_000
        assert valued["required_paydown_cents"] == 0
        assert fx.read_facility(facility_id)["status"] == "ACTIVE"
        assert fx.read_facility(facility_id)["open_margin_call_count"] == 0

        ship_body = make.ship_payload(scenario.investor["id"])
        letter = validate_success(
            api_client.ship_advance(advance_id, ship_body, COLLATERAL_ANALYST), 201
        )
        asserts.assert_bailee_letter(letter)
        assert letter["status"] == "ISSUED"
        assert fx.read_advance(advance_id)["funding_status"] == "SHIPPED"

        # The five roles that are not CollateralAnalyst, including the three
        # entity-backed ones addressing their own rows.
        other_roles = (
            CREDIT_OFFICER,
            WIRE_OPERATOR,
            make_borrower_headers(facility_id),
            make_custodian_headers(scenario.custodian["id"]),
            make_investor_headers(scenario.investor["id"]),
        )
        for headers in other_roles:
            validate_error(
                api_client.value_advance(advance_id, valuation_body, headers),
                ApiErrorId.ERR_UNAUTHORIZED,
            )
            validate_error(
                api_client.ship_advance(advance_id, ship_body, headers),
                ApiErrorId.ERR_UNAUTHORIZED,
            )

        # Priority 2 precedes priority 3: no 404 escapes.
        validate_error(
            api_client.value_advance(NON_EXISTENT_UUID, valuation_body, CREDIT_OFFICER),
            ApiErrorId.ERR_UNAUTHORIZED,
        )
        # Priority 2 also precedes the optimistic-concurrency check at priority 8,
        # even though this facility token went stale two operations ago.
        validate_error(
            api_client.create_advance(
                make.advance_payload(
                    facility_id, scenario.custodian["id"], stale_facility_version
                ),
                WIRE_OPERATOR,
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
        )
        # And it precedes the funding-axis state check at priority 11.
        validate_error(
            api_client.fund_advance(advance_id, CREDIT_OFFICER),
            ApiErrorId.ERR_UNAUTHORIZED,
        )
        # The positive control in the other direction: the wire desk is authorised
        # for funding, so its refusal is about the advance's state, not its role.
        validate_error(
            api_client.fund_advance(advance_id, make_wire_operator_headers("wo_2")),
            ApiErrorId.ERR_ADVANCE_INVALID_STATE,
        )

        untouched = fx.read_advance(advance_id)
        assert untouched["funding_status"] == "SHIPPED"
        assert untouched["outstanding_balance_cents"] == 1_960_000_000
        letters, letter_meta = validate_paginated(
            api_client.list_advance_bailee_letters(advance_id, CREDIT_OFFICER)
        )
        assert letter_meta["total_count"] == 1
        assert letters[0]["status"] == "ISSUED"


class TestEntityBackedIdentitiesAreRowScoped:
    def test_an_unknown_identity_is_403_and_a_foreign_row_is_404(self):
        """The two counterparty failure modes are never collapsed into one code.

        PRD 2.1: "For all three, a supplied `X-User-ID` that does not resolve to
        a row of the backing entity at all is itself an authorisation failure and
        yields `ERR_UNAUTHORIZED`; an identity that resolves but addresses a row
        belonging to a different aggregate yields `ERR_RESOURCE_MISMATCH` with
        HTTP 404, deliberately reported as a not-found so that the existence of
        another counterparty's data is never disclosed."

        PRD 2.1: "When `X-User-Role` is `Custodian`, `X-User-ID` is the `id` of
        the acting `DocumentCustodian`; a custodian may read and act only on
        advances whose `custodian_id` equals `X-User-ID` and on receipts whose
        `custodian_id` equals `X-User-ID`."

        PRD 2.8: "The addressed row belongs to the caller's own aggregate, failing
        with `ERR_RESOURCE_MISMATCH` (404). This applies to exactly ten
        operations: reading one facility, reading a facility's exposure summary,
        reading a facility's ledger entries, reading one advance, listing a
        custodian's receipts, listing an investor's commitments, listing an
        investor's bailee letters, filing a receipt against an advance, curing a
        receipt, and purchasing an advance."

        Design: Corner/rbac/corner_rbac_entity_backed_identities_are_row_scoped
        """
        scenario = fx.setup_funded_dry_advance()
        facility_id = scenario.facility["id"]
        advance_id = scenario.advance["id"]
        custodian_id = scenario.custodian["id"]
        investor_id = scenario.investor["id"]
        borrower = make_borrower_headers(facility_id)
        custodian = make_custodian_headers(custodian_id)
        investor = make_investor_headers(investor_id)

        # A second investor, so the foreign-row arm addresses a real row.
        other_investor = fx.register_investor(
            facility_id,
            approve=False,
            investor_name="Beta Conduit Partners",
            counterparty_rating="B",
        )

        # The panel's receipt was already filed with X-User-ID equal to the
        # custodian's own id, which is the shared custodian operation.
        own_facility = validate_success(api_client.get_facility(facility_id, borrower))
        assert own_facility["id"] == facility_id

        covenant_test = validate_success(
            api_client.create_covenant_test(
                facility_id, make.covenant_test_payload("2026-06-30"), borrower
            ),
            201,
        )
        asserts.assert_covenant_test(covenant_test)
        assert covenant_test["status"] == "PASS"
        assert covenant_test["profitability_variant"] == "ANNUALIZED_QUARTER"
        # 200,000,000 annualised over four quarters with no prior certificate.
        assert covenant_test["profitability_metric_cents"] == 800_000_000
        assert covenant_test["breach_codes"] == []

        own_advance = validate_success(api_client.get_advance(advance_id, custodian))
        assert own_advance["custodian_id"] == custodian_id

        own_receipts, own_receipt_meta = validate_paginated(
            api_client.list_custodian_receipts(custodian_id, custodian)
        )
        assert own_receipt_meta["total_count"] == 1
        assert own_receipts[0]["custodian_id"] == custodian_id

        own_commitments, own_commitment_meta = validate_paginated(
            api_client.list_investor_commitments(investor_id, investor)
        )
        assert own_commitment_meta["total_count"] == 1
        assert own_commitments[0]["id"] == scenario.commitment["id"]

        fx.ship_advance(advance_id, investor_id)
        own_letters, own_letter_meta = validate_paginated(
            api_client.list_advance_bailee_letters(advance_id, investor)
        )
        assert own_letter_meta["total_count"] == 1
        assert own_letters[0]["status"] == "ISSUED"

        purchased = validate_success(
            api_client.purchase_advance(
                advance_id, investor, make.purchase_payload("SETL-2026-0801-A1")
            )
        )
        assert purchased["funding_status"] == "PURCHASED"
        assert purchased["outstanding_balance_cents"] == 0

        # An identity that resolves to no row of the backing entity: 403, and the
        # code is the same whichever of the three entity-backed roles asks.
        for send in (
            lambda h: api_client.get_facility(facility_id, h),
            lambda h: api_client.get_exposure_summary(facility_id, h),
        ):
            validate_error(
                send(make_borrower_headers(NON_EXISTENT_UUID)),
                ApiErrorId.ERR_UNAUTHORIZED,
            )
        validate_error(
            api_client.get_advance(advance_id, make_custodian_headers(NON_EXISTENT_UUID)),
            ApiErrorId.ERR_UNAUTHORIZED,
        )
        validate_error(
            api_client.list_custodian_receipts(
                custodian_id, make_custodian_headers(NON_EXISTENT_UUID)
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
        )
        validate_error(
            api_client.list_investor_commitments(
                investor_id, make_investor_headers(NON_EXISTENT_UUID)
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
        )
        # A well-formed identifier of the wrong entity is still an unknown
        # custodian, so it fails authorisation rather than ownership.
        validate_error(
            api_client.get_advance(advance_id, make_custodian_headers(investor_id)),
            ApiErrorId.ERR_UNAUTHORIZED,
        )
        # This identity resolves; only the ownership does not.
        validate_error(
            api_client.list_investor_commitments(
                investor_id, make_investor_headers(other_investor["id"])
            ),
            ApiErrorId.ERR_RESOURCE_MISMATCH,
        )
        # The scoping rule is never reached when the role is absent from §4.
        validate_error(
            api_client.get_facility(facility_id, custodian),
            ApiErrorId.ERR_UNAUTHORIZED,
        )


class TestFourEyesOnFundApproveAndWaive:
    def test_three_gates_one_code_and_a_null_comparand_that_skips_the_third(self):
        """The same officer is refused his own call and permitted the system's.

        PRD 2.9: "Three gates in the system compare the acting identity against a
        stored originator identity, and all three are identity rules rather than
        role rules — the acting role is authorised in every case, and the request
        still fails."

        PRD 2.8: "`X-User-ID` differs from the wire's `decided_by_user_id`,
        failing with `ERR_DUAL_CONTROL_VIOLATION` (409). The operator who verified
        the wire may not also release it."

        PRD 3.6: "A call in `ISSUED` or `PARTIALLY_CURED` may be waived with a
        supplied `reason`, provided the acting `X-User-ID` differs from the call's
        `issued_by_user_id` — a comparison skipped entirely when that field is
        null, which is exactly the case for every system-issued call."

        PRD 2.8: "The facility has at least one `ProductAdvanceRate` row, failing
        approval with `ERR_NO_ADVANCE_RATES_CONFIGURED` (422)."

        PRD 3.6: "That entry exists purely for audit: it is excluded from both the
        principal projection and the fee projection, so neither
        `outstanding_principal_cents` nor `accrued_fee_balance_cents` moves."

        Design: Corner/rbac/corner_rbac_four_eyes_on_fund_approve_and_waive
        """
        scenario = fx.setup_advance_ready_to_fund()
        facility_id = scenario.facility["id"]
        advance_id = scenario.advance["id"]
        assert scenario.wire["decided_by_user_id"] == "wo_1"

        # Gate 1: the operator who verified the wire may not release it.
        validate_error(
            api_client.fund_advance(advance_id, make_wire_operator_headers("wo_1")),
            ApiErrorId.ERR_DUAL_CONTROL_VIOLATION,
        )
        still_requested = fx.read_advance(advance_id)
        assert still_requested["funding_status"] == "REQUESTED"
        assert still_requested["advance_amount_cents"] == 0
        # The same role, a different person: the rule is about identity.
        funded = validate_success(
            api_client.fund_advance(advance_id, make_wire_operator_headers("wo_2"))
        )
        assert funded["advance_amount_cents"] == 1_960_000_000
        assert funded["funding_status"] == "FUNDED"

        # Gate 2: a facility's creator may not approve it.
        second_facility = fx.book_facility(
            borrower_legal_name="Second Facility For Approval Four Eyes",
            settlement_account_last4="9182",
        )
        fx.add_rate_row(second_facility["id"])
        validate_error(
            api_client.approve_facility(
                second_facility["id"], make_credit_officer_headers("co_1")
            ),
            ApiErrorId.ERR_DUAL_CONTROL_VIOLATION,
        )
        pending = fx.read_facility(second_facility["id"])
        assert pending["status"] == "PENDING_APPROVAL"
        assert pending["approved_by_user_id"] is None
        approved = validate_success(
            api_client.approve_facility(second_facility["id"], SECOND_CREDIT_OFFICER)
        )
        assert approved["status"] == "ACTIVE"
        assert approved["approved_by_user_id"] == "co_2"

        # The gate sits at the very bottom of the ladder, so the cheaper
        # configuration check reports first on an unpriced facility.
        unpriced = fx.book_facility(
            borrower_legal_name="Third Facility Without Any Rates",
            settlement_account_last4="7351",
        )
        validate_error(
            api_client.approve_facility(
                unpriced["id"], make_credit_officer_headers("co_1")
            ),
            ApiErrorId.ERR_NO_ADVANCE_RATES_CONFIGURED,
        )

        # Gate 3: the officer who raised a call by hand may not waive it.
        manual_call = fx.raise_manual_margin_call(facility_id)
        assert manual_call["call_amount_cents"] == 196_000_000
        assert manual_call["issued_by_user_id"] == "co_1"
        validate_error(
            api_client.waive_margin_call(
                manual_call["id"],
                {"reason": "Same officer attempts to waive his own call"},
                make_credit_officer_headers("co_1"),
            ),
            ApiErrorId.ERR_DUAL_CONTROL_VIOLATION,
        )
        unchanged = fx.read_margin_call(manual_call["id"])
        assert unchanged["status"] == "ISSUED"
        assert unchanged["version"] == manual_call["version"]
        waived = fx.waive_margin_call(manual_call["id"])
        assert waived["status"] == "WAIVED"
        assert waived["waived_by_user_id"] == "co_2"

        # Gate 3 inverted: a system-issued call leaves the comparand null.
        fx.mark_to_market(advance_id, 1_900_000_000)
        system_call = fx.first_open_margin_call(facility_id)
        # 1,960,000,000 outstanding less floor(1,900,000,000 * 0.98).
        assert system_call["call_amount_cents"] == 98_000_000
        assert system_call["issued_by_user_id"] is None
        system_waived = validate_success(
            api_client.waive_margin_call(
                system_call["id"],
                {"reason": "Valuation source corrected; the decline was a feed error"},
                make_credit_officer_headers("co_1"),
            )
        )
        assert system_waived["status"] == "WAIVED"
        assert system_waived["waived_by_user_id"] == "co_1"

        # Both waives are audit-only postings.
        waiver_entries, waiver_meta = validate_paginated(
            api_client.list_facility_ledger_entries(
                facility_id, CREDIT_OFFICER, {"entry_type": "MARGIN_CALL_WAIVED"}
            )
        )
        assert waiver_meta["total_count"] == 2
        assert [entry["amount_cents"] for entry in waiver_entries] == [
            196_000_000,
            98_000_000,
        ]
        assert [entry["direction"] for entry in waiver_entries] == ["CREDIT", "CREDIT"]

        summary = fx.read_exposure_summary(facility_id)
        asserts.assert_both_conservation_invariants(summary)
        assert summary["outstanding_principal_cents"] == 1_960_000_000
        assert summary["accrued_fee_balance_cents"] == 0
        assert summary["open_margin_call_count"] == 0
        final = fx.read_facility(facility_id)
        assert final["status"] == "ACTIVE"
        assert final["outstanding_principal_cents"] == 1_960_000_000
        assert final["availability_cents"] == 18_040_000_000
