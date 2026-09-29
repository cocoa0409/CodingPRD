"""State-machine contracts: initial states, legal hops, refused hops, cascades.

Every entity here carries its own status axis with its own error code, and the
advance carries two axes at once, so a trigger that is legal on one axis may be
refused by the other.
"""

import pytest

from test_helpers import (
    COLLATERAL_ANALYST,
    CREDIT_OFFICER,
    SECOND_CREDIT_OFFICER,
    WIRE_OPERATOR,
    ApiErrorId,
    api_client,
    make_borrower_headers,
    make_custodian_headers,
    make_investor_headers,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as asserts
from test_helpers import factories as make
from test_helpers import fixtures as fx


# ─── Initial states of all seven machines ─────────────────────────────────────

class TestInitialStates:
    def test_every_machine_reports_its_own_declared_birth_state(self):
        """The custodian is born approved and the advance is born into two states.

        PRD 3.3: "A created advance is off-balance-sheet. Its `funding_status` is
        `REQUESTED` and its `custody_status` is `PENDING_RECEIPT` — the two axes
        of the parallel state machine, which evolve independently of each other
        from this point on."

        Design: Corner/state_machines/corner_sm_initial_states_across_every_machine
        """
        fx.set_clock("2026-08-01T00:00:00Z")

        # A facility is born pending, and only a second officer can approve it.
        facility = fx.book_facility()
        assert facility["status"] == "PENDING_APPROVAL"
        fx.add_rate_row(facility["id"])
        fx.approve_facility(facility["id"])

        # There is no custodian approval endpoint at all, only a suspension.
        custodian = fx.register_custodian(facility["id"])
        asserts.assert_custodian(custodian)
        assert custodian["status"] == "APPROVED"

        investor = fx.register_investor(facility["id"], approve=False)
        assert investor["status"] == "PENDING_APPROVAL"
        validate_success(api_client.approve_investor(investor["id"], CREDIT_OFFICER))

        commitment = fx.record_commitment(facility["id"], investor["id"])
        advance = fx.book_advance(
            facility["id"], custodian["id"], investor_commitment_id=commitment["id"]
        )

        booked = fx.read_advance(advance["id"])
        asserts.assert_advance(booked)
        assert booked["funding_status"] == "REQUESTED"
        assert booked["custody_status"] == "PENDING_RECEIPT"
        # An unfunded advance never accrues dwell.
        assert booked["dwell_days"] == 0
        assert booked["is_aged"] is False

        wires, meta = validate_paginated(
            api_client.list_advance_wire_instructions(advance["id"], WIRE_OPERATOR)
        )
        assert meta["total_count"] == 1
        asserts.assert_wire_instruction(wires[0])
        assert wires[0]["status"] == "PENDING_VERIFICATION"
        assert wires[0]["decided_by_user_id"] is None
        assert wires[0]["block_reason"] is None

        fresh = fx.read_commitment(commitment["id"])
        asserts.assert_commitment(fresh)
        assert fresh["status"] == "OPEN"
        assert fresh["allocated_amount_cents"] == 0
        assert fresh["settled_amount_cents"] == 0
        assert fresh["remaining_amount_cents"] == 5_000_000_000


# ─── Legal hops on the counterparty list ─────────────────────────────────────

class TestInvestorApproval:
    def test_approving_a_counterparty_writes_only_the_counterparty_row(self):
        """The stamp lands on the investor; the facility is not a party to it.

        PRD 3.2: "Moving an investor from `PENDING_APPROVAL` to `APPROVED` is a
        `CreditOfficer` act; it is permitted while the owning facility is in
        `PENDING_APPROVAL`, `ACTIVE` or `RESTRICTED`, and it sets `approved_at`
        to the logical clock and increments the investor's `version`."

        Design: Corner/state_machines/corner_sm_investor_pending_to_approved_valid_transition
        """
        scenario = fx.setup_facility_panel(
            with_commitment=False, investor_overrides={"approve": False}
        )
        assert scenario.investor["status"] == "PENDING_APPROVAL"
        assert scenario.investor["version"] == 1
        facility_version_before = fx.facility_version(scenario.facility["id"])

        approved = validate_success(
            api_client.approve_investor(scenario.investor["id"], CREDIT_OFFICER)
        )
        asserts.assert_investor(approved)
        assert approved["status"] == "APPROVED"
        asserts.assert_instant(approved["approved_at"], "2026-08-01T00:00:00Z")
        assert approved["version"] == 2
        assert approved["exposure_cents"] == 0
        assert approved["concentration_limit_pct"] == pytest.approx(0.60, abs=1e-6)

        # Approving a counterparty is not a facility write.
        facility = fx.read_facility(scenario.facility["id"])
        assert facility["version"] == facility_version_before
        assert facility["status"] == "ACTIVE"

        _rows, meta = validate_paginated(
            api_client.list_facility_investors(
                scenario.facility["id"], CREDIT_OFFICER, {"status": "APPROVED"}
            )
        )
        assert meta["total_count"] == 1


# ─── Preconditions guarding REQUESTED → FUNDED ───────────────────────────────

class TestFundingPreconditions:
    def test_a_pending_wire_blocks_funding_until_it_is_verified(self):
        """Every other precondition holds; the wire alone refuses the release.

        PRD 2.8: "The advance's wire instruction is `VERIFIED`, failing funding
        with `ERR_WIRE_NOT_VERIFIED` (409). No advance funds on an unverified or
        blocked wire, whatever the collateral looks like."

        Design: Corner/state_machines/corner_sm_fund_requires_verified_wire_precondition
        """
        scenario = fx.setup_requested_advance()
        fx.file_receipt(scenario.advance["id"], scenario.custodian["id"])
        assert scenario.wire["status"] == "PENDING_VERIFICATION"

        validate_error(
            api_client.fund_advance(scenario.advance["id"], COLLATERAL_ANALYST),
            ApiErrorId.ERR_WIRE_NOT_VERIFIED,
        )

        refused = fx.read_advance(scenario.advance["id"])
        assert refused["funding_status"] == "REQUESTED"
        assert refused["advance_amount_cents"] == 0

        _entries, meta = validate_paginated(
            api_client.list_advance_ledger_entries(
                scenario.advance["id"], CREDIT_OFFICER
            )
        )
        assert meta["total_count"] == 0

        facility = fx.read_facility(scenario.facility["id"])
        assert facility["outstanding_principal_cents"] == 0
        assert facility["availability_cents"] == 20_000_000_000

        # The identical call succeeds once the wire desk has verified the wire.
        fx.verify_wire(scenario.wire["id"])
        funded = validate_success(
            api_client.fund_advance(scenario.advance["id"], COLLATERAL_ANALYST)
        )
        asserts.assert_advance(funded)
        assert funded["funding_status"] == "FUNDED"
        assert funded["advance_amount_cents"] == 1_960_000_000
        assert fx.wire_for_advance(scenario.advance["id"])["status"] == "RELEASED"


# ─── Refused hops on each axis ───────────────────────────────────────────────

class TestPurchaseFromFunded:
    def test_the_state_defect_outranks_the_missing_bailee_letter(self):
        """Purchase is defined only from `SHIPPED`, so the state code wins.

        PRD 2.8: "`funding_status` permits the trigger: `REQUESTED` for funding;
        `FUNDED` or `SHIPPED` for shipment, valuation, repurchase and raising a
        repurchase demand; `SHIPPED` for purchase; and `REQUESTED`, `FUNDED` or
        `SHIPPED` for filing a receipt."

        Design: Corner/state_machines/corner_sm_purchase_from_funded_is_an_invalid_transition
        """
        scenario = fx.setup_funded_dry_advance()

        # Both priority 11 and priority 23 are genuinely violated here.
        _letters, meta = validate_paginated(
            api_client.list_advance_bailee_letters(
                scenario.advance["id"], CREDIT_OFFICER
            )
        )
        assert meta["total_count"] == 0

        validate_error(
            api_client.purchase_advance(
                scenario.advance["id"],
                make_investor_headers(scenario.investor["id"]),
                make.purchase_payload("WIRE-IN-20260801-01"),
            ),
            ApiErrorId.ERR_ADVANCE_INVALID_STATE,
        )

        held = fx.read_advance(scenario.advance["id"])
        assert held["funding_status"] == "FUNDED"
        assert held["purchased_at"] is None
        # No INVESTOR_PROCEEDS entry was written.
        assert held["outstanding_balance_cents"] == 1_960_000_000

        # PRD 2.8 priority 12: a cure requires the custody axis to be in
        # `RECEIVED_EXCEPTION`, and this receipt was filed clear.
        validate_error(
            api_client.cure_receipt(
                scenario.receipt["id"],
                make.receipt_cure_payload(["UNSIGNED_ASSIGNMENT"]),
                make_custodian_headers(scenario.custodian["id"]),
            ),
            ApiErrorId.ERR_CUSTODY_INVALID_STATE,
        )

        receipts = fx.advance_receipts(scenario.advance["id"])
        assert len(receipts) == 1
        assert receipts[0]["status"] == "CLEAR"


class TestPurchasedAdvanceLockdown:
    def test_four_further_triggers_all_fail_from_the_terminal_state(self):
        """`PURCHASED` accepts nothing, and the refusals write nothing.

        PRD 2.8: "`PURCHASED`, `REPURCHASED` and `REJECTED` are terminal on the
        funding axis, so every one of those triggers fails from those three
        states."

        Design: Corner/state_machines/corner_sm_purchased_advance_is_locked_down
        """
        scenario = fx.setup_purchased_advance(
            ship_clock_utc=None, purchase_clock_utc=None
        )

        settled = scenario.advance
        assert settled["funding_status"] == "PURCHASED"
        assert settled["custody_status"] == "RELEASED_TO_INVESTOR"
        assert settled["outstanding_balance_cents"] == 0
        asserts.assert_instant(settled["purchased_at"], "2026-08-01T00:00:00Z")

        letters = fx.advance_bailee_letters(scenario.advance["id"])
        assert len(letters) == 1
        assert letters[0]["status"] == "HONORED"

        version_before = fx.advance_version(scenario.advance["id"])

        validate_error(
            api_client.ship_advance(
                scenario.advance["id"],
                make.ship_payload(scenario.investor["id"]),
                COLLATERAL_ANALYST,
            ),
            ApiErrorId.ERR_ADVANCE_INVALID_STATE,
        )
        validate_error(
            api_client.purchase_advance(
                scenario.advance["id"],
                make_investor_headers(scenario.investor["id"]),
                make.purchase_payload("WIRE-IN-20260801-78"),
            ),
            ApiErrorId.ERR_ADVANCE_INVALID_STATE,
        )
        validate_error(
            api_client.repurchase_advance(
                scenario.advance["id"],
                make.repurchase_payload(1_960_000_000),
                make_borrower_headers(scenario.facility["id"]),
            ),
            ApiErrorId.ERR_ADVANCE_INVALID_STATE,
        )
        validate_error(
            api_client.create_repurchase_demand(
                scenario.advance["id"],
                make.repurchase_demand_payload("DWELL_EXCEEDED"),
                CREDIT_OFFICER,
            ),
            ApiErrorId.ERR_ADVANCE_INVALID_STATE,
        )

        assert fx.advance_version(scenario.advance["id"]) == version_before

        entries, meta = validate_paginated(
            api_client.list_advance_ledger_entries(
                scenario.advance["id"], CREDIT_OFFICER
            )
        )
        assert meta["total_count"] == 2
        asserts.assert_entry_types_in_order(
            entries, [("ADVANCE_FUNDED", "DEBIT"), ("INVESTOR_PROCEEDS", "CREDIT")]
        )
        assert [entry["amount_cents"] for entry in entries] == [
            1_960_000_000,
            1_960_000_000,
        ]

        _demands, demand_meta = validate_paginated(
            api_client.list_advance_repurchase_demands(
                scenario.advance["id"], CREDIT_OFFICER
            )
        )
        assert demand_meta["total_count"] == 0

        facility = fx.read_facility(scenario.facility["id"])
        assert facility["outstanding_principal_cents"] == 0
        assert facility["availability_cents"] == 20_000_000_000


class TestRepeatedLifecycleTriggers:
    def test_each_entity_refuses_its_second_stamp_with_its_own_code(self):
        """None of the three lifecycle stamps is idempotent.

        PRD 2.8: "The addressed facility is in the state its trigger requires:
        `PENDING_APPROVAL` for approval, `ACTIVE` or `RESTRICTED` for suspension,
        `SUSPENDED` for reinstatement, and `PENDING_APPROVAL` for adding a
        product advance rate. Failure is `ERR_FACILITY_INVALID_STATE` (409).
        Re-approving an already `ACTIVE` facility is not idempotent — it is an
        error."

        Design: Corner/state_machines/corner_sm_repeated_lifecycle_trigger_is_rejected
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        facility = fx.book_facility()
        fx.add_rate_row(facility["id"])
        fx.approve_facility(facility["id"])
        custodian = fx.register_custodian(facility["id"])
        investor = fx.register_investor(facility["id"])
        suspended = fx.suspend_custodian(custodian["id"], reason="Vault audit finding")
        assert suspended["status"] == "SUSPENDED"
        version_after_approve = fx.facility_version(facility["id"])

        validate_error(
            api_client.approve_facility(facility["id"], SECOND_CREDIT_OFFICER),
            ApiErrorId.ERR_FACILITY_INVALID_STATE,
        )
        validate_error(
            api_client.approve_investor(investor["id"], CREDIT_OFFICER),
            ApiErrorId.ERR_INVESTOR_INVALID_STATE,
        )
        validate_error(
            api_client.suspend_custodian(
                custodian["id"],
                {"reason": "Vault audit finding restated"},
                CREDIT_OFFICER,
            ),
            ApiErrorId.ERR_CUSTODIAN_INVALID_STATE,
        )

        # The rejected retries did not bump any OCC token or re-stamp any field.
        reread = fx.read_facility(facility["id"])
        assert reread["status"] == "ACTIVE"
        assert reread["version"] == version_after_approve
        assert reread["approved_by_user_id"] == "co_2"
        asserts.assert_instant(reread["approved_at"], "2026-08-01T00:00:00Z")

        held_investor = fx.read_investor(investor["id"])
        assert held_investor["status"] == "APPROVED"
        assert held_investor["version"] == 2

        held_custodian = validate_success(
            api_client.get_custodian(custodian["id"], CREDIT_OFFICER)
        )
        assert held_custodian["status"] == "SUSPENDED"
        assert held_custodian["version"] == 2


# ─── Side effects the transitions must execute ───────────────────────────────

class TestFundingSideEffectSynchronisation:
    def test_one_debit_drives_the_rollup_the_allocation_and_the_exposure(self):
        """A single wet funding must leave eight figures mutually consistent.

        PRD 3.3: "One ledger entry of type `ADVANCE_FUNDED` and direction
        `DEBIT` is appended for `advance_amount_cents`, attributed to this
        advance, which is what makes `outstanding_principal_cents`,
        `availability_cents`, `wet_outstanding_cents`, `aged_outstanding_cents`
        and `scratch_and_dent_outstanding_cents` move."

        Design: Corner/state_machines/corner_sm_fund_ledger_sync_reconciles_facility_rollup
        """
        scenario = fx.setup_advance_ready_to_fund(
            advance_overrides={
                "funding_type": "WET",
                "loan_amount_cents": 1_000_000_000,
                "note_rate": 0.0625,
            },
            callback_reference="CB-950",
            file_clear_receipt=False,
        )
        funded = fx.fund_advance(scenario.advance["id"])

        # 1,000,000,000 * (0.98 - 0.02) — the wet haircut drops the rate to 0.96.
        asserts.assert_advance(funded)
        assert funded["funding_status"] == "FUNDED"
        assert funded["custody_status"] == "PENDING_RECEIPT"
        assert funded["advance_amount_cents"] == 960_000_000
        asserts.assert_instant(
            funded["wet_receipt_deadline_at"], "2026-08-03T00:00:00Z"
        )
        assert funded["effective_advance_rate"] == pytest.approx(0.96, abs=1e-6)
        assert funded["eligible_collateral_value_cents"] == 960_000_000
        assert funded["required_paydown_cents"] == 0

        entries, meta = validate_paginated(
            api_client.list_facility_ledger_entries(
                scenario.facility["id"], CREDIT_OFFICER
            )
        )
        assert meta["total_count"] == 1
        asserts.assert_ledger_entry(entries[0])
        assert entries[0]["entry_type"] == "ADVANCE_FUNDED"
        assert entries[0]["direction"] == "DEBIT"
        assert entries[0]["amount_cents"] == 960_000_000

        summary = fx.read_exposure_summary(scenario.facility["id"])
        assert summary["outstanding_principal_cents"] == 960_000_000
        assert summary["availability_cents"] == 19_040_000_000
        assert summary["wet_outstanding_cents"] == 960_000_000
        assert summary["aged_outstanding_cents"] == 0
        assert summary["scratch_and_dent_outstanding_cents"] == 0
        assert summary["ledger_debit_total_cents"] == 960_000_000
        assert summary["ledger_credit_total_cents"] == 0
        assert summary["advance_outstanding_sum_cents"] == 960_000_000
        asserts.assert_both_conservation_invariants(summary)
        asserts.assert_availability_projection(summary)

        commitment = fx.read_commitment(scenario.commitment["id"])
        assert commitment["allocated_amount_cents"] == 960_000_000
        assert commitment["remaining_amount_cents"] == 4_040_000_000
        assert commitment["status"] == "PARTIALLY_ALLOCATED"

        assert fx.read_investor(scenario.investor["id"])["exposure_cents"] == (
            960_000_000
        )
        exposures = summary["investor_exposures"]
        assert len(exposures) == 1
        assert exposures[0]["investor_id"] == scenario.investor["id"]
        assert exposures[0]["exposure_cents"] == 960_000_000


class TestCovenantWaiverCompensation:
    def test_the_waiver_undoes_all_three_downstream_effects_of_the_breach(self):
        """Compensation rather than deletion: the prior stays, the call goes.

        PRD 3.8: "The waiver moves the test to `WAIVED`, stamps
        `waived_by_user_id`, sets the facility's `last_covenant_status` to
        `WAIVED`, resets `consecutive_breach_count` to zero, and moves every
        `COVENANT_BREACH` margin call of the facility still in `ISSUED` or
        `PARTIALLY_CURED` to `WAIVED`."

        Design: Corner/state_machines/corner_sm_covenant_waiver_compensates_the_breach_cascade
        """
        scenario = fx.setup_funded_dry_advance()

        breach = fx.certify_covenants(
            scenario.facility["id"],
            "2026-06-30",
            tangible_net_worth_cents=1_400_000_000,
            liquidity_cents=600_000_000,
            net_income_cents=30_000_000,
        )
        asserts.assert_covenant_test(breach)
        # 30,000,000 * 4 clears the 100,000,000 floor with no priors on file.
        assert breach["profitability_variant"] == "ANNUALIZED_QUARTER"
        assert breach["profitability_metric_cents"] == 120_000_000
        assert breach["breach_codes"] == ["NET_WORTH"]
        assert breach["status"] == "BREACH"

        calls = fx.facility_margin_calls(
            scenario.facility["id"], {"trigger_reason": "COVENANT_BREACH"}
        )
        assert len(calls) == 1
        # floor(1,960,000,000 * 0.10) — one tenth of outstanding principal.
        assert calls[0]["call_amount_cents"] == 196_000_000
        assert calls[0]["advance_id"] is None
        assert calls[0]["status"] == "ISSUED"

        restricted = fx.read_facility(scenario.facility["id"])
        assert restricted["status"] == "RESTRICTED"
        assert restricted["consecutive_breach_count"] == 1
        assert restricted["last_covenant_status"] == "BREACH"
        assert restricted["open_margin_call_count"] == 1

        waived = fx.waive_covenant_test(
            breach["id"], reason="Sponsor equity injection closed 2026-08-01"
        )
        assert waived["status"] == "WAIVED"
        assert waived["waived_by_user_id"] == "co_1"
        assert fx.read_margin_call(calls[0]["id"])["status"] == "WAIVED"

        restored = fx.read_facility(scenario.facility["id"])
        assert restored["status"] == "ACTIVE"
        assert restored["consecutive_breach_count"] == 0
        assert restored["last_covenant_status"] == "WAIVED"
        assert restored["open_margin_call_count"] == 0
        # The informational entry enters neither ledger sum.
        assert restored["outstanding_principal_cents"] == 1_960_000_000

        entries, meta = validate_paginated(
            api_client.list_facility_ledger_entries(
                scenario.facility["id"], CREDIT_OFFICER
            )
        )
        # PRD 3.8 compresses this cascade to "moves every `COVENANT_BREACH`
        # margin call of the facility still in `ISSUED` or `PARTIALLY_CURED` to
        # `WAIVED`" and names no ledger posting, so whether the cascade also
        # appends the audit-only entry that PRD 3.6 pins to the margin-call
        # waiver endpoint is not determined here. What is determined is that
        # nothing balance-moving is written: PRD 2.6 says the `MARGIN_CALL_WAIVED`
        # entry "is purely informational and moves neither balance".
        assert entries[0]["entry_type"] == "ADVANCE_FUNDED"
        assert entries[0]["direction"] == "DEBIT"
        assert [entry["entry_type"] for entry in entries] in (
            ["ADVANCE_FUNDED"],
            ["ADVANCE_FUNDED", "MARGIN_CALL_WAIVED"],
        )
        assert meta["total_count"] == len(entries)
        for entry in entries[1:]:
            assert entry["direction"] == "CREDIT"
            assert entry["amount_cents"] == 196_000_000

        _tests, test_meta = validate_paginated(
            api_client.list_covenant_tests(scenario.facility["id"], CREDIT_OFFICER)
        )
        assert test_meta["total_count"] == 1


class TestBaileeExpiryFanOut:
    def test_one_aging_run_expires_the_letter_and_demands_the_repurchase(self):
        """Four independent effects, each reported in its own counter.

        PRD 3.9: "Third, every bailee letter still in `ISSUED` whose `expires_at`
        the logical clock has reached or passed moves to `EXPIRED`, and each such
        letter whose advance is still `SHIPPED` also produces a repurchase demand
        with a `reason` of `BAILEE_EXPIRED`, `raised_at` at the clock and
        `deadline_at` ten days later."

        Design: Corner/state_machines/corner_sm_bailee_expiry_raises_repurchase_demand
        """
        scenario = fx.setup_shipped_advance()
        asserts.assert_instant(
            scenario.bailee_letter["expires_at"], "2026-08-31T00:00:00Z"
        )

        fx.set_clock("2026-09-05T00:00:00Z")
        run = fx.run_aging(scenario.facility["id"])
        asserts.assert_aging_run_summary(run)
        assert run["accrual_days"] == 35
        # 16,673,611 of advance interest plus 4,384,722 of unused-line fee.
        assert run["fee_accrual_cents"] == 21_058_333
        assert run["advances_evaluated"] == 1
        assert run["margin_calls_issued"] == 1
        assert run["bailee_letters_expired"] == 1
        assert run["repurchase_demands_raised"] == 1
        assert run["receipts_overdue"] == 0
        assert run["curtailed_advance_ids"] == [scenario.advance["id"]]

        aged = fx.read_advance(scenario.advance["id"])
        assert aged["dwell_days"] == 35
        assert aged["is_aged"] is True
        # 0.98 less one 0.005 step for the five days past the thirty-day limit.
        assert aged["effective_advance_rate"] == pytest.approx(0.975, abs=1e-6)
        assert aged["eligible_collateral_value_cents"] == 1_950_000_000
        assert aged["required_paydown_cents"] == 10_000_000
        # Expiry of the letter does not unwind the shipment.
        assert aged["funding_status"] == "SHIPPED"

        calls = fx.advance_margin_calls(scenario.advance["id"])
        assert len(calls) == 1
        asserts.assert_margin_call(calls[0])
        assert calls[0]["trigger_reason"] == "DWELL_EXCEEDED"
        assert calls[0]["status"] == "ISSUED"
        assert calls[0]["call_amount_cents"] == 10_000_000
        asserts.assert_instant(calls[0]["cure_deadline_at"], "2026-09-07T00:00:00Z")

        letters = fx.advance_bailee_letters(scenario.advance["id"])
        assert len(letters) == 1
        assert letters[0]["status"] == "EXPIRED"

        demands, meta = validate_paginated(
            api_client.list_advance_repurchase_demands(
                scenario.advance["id"], CREDIT_OFFICER
            )
        )
        assert meta["total_count"] == 1
        asserts.assert_repurchase_demand(demands[0])
        assert demands[0]["status"] == "OPEN"
        assert demands[0]["reason"] == "BAILEE_EXPIRED"
        assert demands[0]["demand_amount_cents"] == 1_960_000_000
        asserts.assert_instant(demands[0]["deadline_at"], "2026-09-15T00:00:00Z")

        # The margin call restricts the facility; the open demand alone would not.
        facility = fx.read_facility(scenario.facility["id"])
        assert facility["status"] == "RESTRICTED"
        assert facility["open_margin_call_count"] == 1
        assert facility["aged_outstanding_cents"] == 1_960_000_000


class TestMarginCallDefaultCascade:
    def test_the_default_suspends_the_line_and_rejects_the_sibling_advance(self):
        """The suspension bubbles two levels down, to the advance and its wire.

        PRD 3.9: "Sixth, every margin call in `ISSUED` or `PARTIALLY_CURED`
        whose `cure_deadline_at` the clock has reached or passed moves to the
        terminal `DEFAULTED`, and a `RESTRICTED` facility then moves to
        `SUSPENDED`."

        Design: Corner/state_machines/corner_sm_margin_call_default_bubbles_facility_to_suspended
        """
        scenario = fx.setup_funded_dry_advance()

        sibling = fx.book_advance(
            scenario.facility["id"],
            scenario.custodian["id"],
            investor_commitment_id=scenario.commitment["id"],
            loan_amount_cents=300_000_000,
            note_rate=0.0700,
        )
        sibling_wire = fx.wire_for_advance(sibling["id"])
        assert sibling_wire["status"] == "PENDING_VERIFICATION"

        fx.mark_to_market(scenario.advance["id"], 1_900_000_000)
        call = fx.first_open_margin_call(scenario.facility["id"])
        assert call["trigger_reason"] == "VALUATION_DECLINE"
        # 1,960,000,000 less floor(1,900,000,000 * 0.98).
        assert call["call_amount_cents"] == 98_000_000
        asserts.assert_instant(call["cure_deadline_at"], "2026-08-03T00:00:00Z")
        assert fx.read_facility(scenario.facility["id"])["status"] == "RESTRICTED"
        assert fx.read_advance(sibling["id"])["funding_status"] == "REQUESTED"

        fx.set_clock("2026-08-04T00:00:00Z")
        run = fx.run_aging(scenario.facility["id"])
        # The dwell step issues nothing: the advance already has an open call.
        assert run["margin_calls_issued"] == 0
        assert run["accrual_days"] == 3
        # 1,429,167 of advance interest plus 375,833 of unused-line fee.
        assert run["fee_accrual_cents"] == 1_805_000

        assert fx.read_margin_call(call["id"])["status"] == "DEFAULTED"

        facility = fx.read_facility(scenario.facility["id"])
        assert facility["status"] == "SUSPENDED"
        # A rejected advance never posted a ledger entry.
        assert facility["outstanding_principal_cents"] == 1_960_000_000

        rejected = fx.read_advance(sibling["id"])
        assert rejected["funding_status"] == "REJECTED"
        assert rejected["rejected_reason"] == "FACILITY_SUSPENDED"

        blocked = fx.wire_for_advance(sibling["id"])
        assert blocked["status"] == "BLOCKED"
        assert blocked["block_reason"] == "FACILITY_SUSPENDED"
        assert blocked["decided_by_user_id"] is None

        _entries, meta = validate_paginated(
            api_client.list_advance_ledger_entries(sibling["id"], CREDIT_OFFICER)
        )
        assert meta["total_count"] == 0


class TestCommitmentWithdrawalCascade:
    def test_a_requested_advance_is_skipped_by_the_cascade_yet_unfundable(self):
        """The cascade only reaches advances that are `FUNDED` or `SHIPPED`.

        PRD 3.2: "The withdrawal cascade mirrors hops two through four of
        investor suspension: every advance pointing at the commitment whose
        `funding_status` is `FUNDED` or `SHIPPED` is re-valued at the orphan
        rate, each such advance whose `required_paydown_cents` is strictly
        positive receives a `COMMITMENT_WITHDRAWN` margin call, and the first
        such call moves an `ACTIVE` facility to `RESTRICTED`."

        Design: Corner/state_machines/corner_sm_commitment_withdraw_cascade_skips_unfunded_advances
        """
        scenario = fx.setup_advance_ready_to_fund()
        assert scenario.advance["funding_status"] == "REQUESTED"
        assert scenario.wire["status"] == "VERIFIED"

        withdrawn = validate_success(
            api_client.withdraw_commitment(
                scenario.commitment["id"],
                {"reason": "Investor exited the CONFORMING program"},
                make_investor_headers(scenario.investor["id"]),
            )
        )
        asserts.assert_commitment(withdrawn)
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["allocated_amount_cents"] == 0
        assert withdrawn["remaining_amount_cents"] == 0

        # Nothing was in FUNDED or SHIPPED, so the cascade had nothing to value.
        _calls, meta = validate_paginated(
            api_client.list_facility_margin_calls(
                scenario.facility["id"], CREDIT_OFFICER
            )
        )
        assert meta["total_count"] == 0

        facility = fx.read_facility(scenario.facility["id"])
        assert facility["status"] == "ACTIVE"
        assert facility["open_margin_call_count"] == 0

        # A merely requested advance is never valued.
        assert fx.read_advance(scenario.advance["id"])["required_paydown_cents"] == 0

        # The commitment is no longer live and its remaining capacity is zero,
        # so funding against it is refused.
        validate_error_is_one_of(
            api_client.fund_advance(scenario.advance["id"], COLLATERAL_ANALYST),
            [
                ApiErrorId.ERR_COMMITMENT_NOT_ACTIVE,
                ApiErrorId.ERR_COMMITMENT_CAPACITY_EXCEEDED,
            ],
        )

        assert fx.read_advance(scenario.advance["id"])["funding_status"] == "REQUESTED"
        assert fx.facility_ledger(scenario.facility["id"]) == []
        # Withdrawing a commitment does not suspend its investor.
        assert fx.read_investor(scenario.investor["id"])["status"] == "APPROVED"


def _only_demand_of(advance_id):
    """The advance's single repurchase demand, read back fresh."""
    demands, meta = validate_paginated(
        api_client.list_advance_repurchase_demands(advance_id, CREDIT_OFFICER)
    )
    assert meta["total_count"] == 1
    return demands[0]


class TestDemandEscalationRoundTrip:
    def test_the_cure_window_is_inviolable_and_the_repurchase_reverses_it(self):
        """One day early the escalation is a 409; on the deadline it is a 200.

        PRD 3.7: "That ten-day window is the borrower's, and it is inviolable: a
        `CreditOfficer` may escalate a demand only once it is still `OPEN` **and**
        the logical clock has reached or passed its own `deadline_at`, and both
        halves of that condition surface the same
        `ERR_REPURCHASE_DEMAND_NOT_OPEN`."

        Design: Corner/state_machines/corner_sm_demand_escalation_and_repurchase_round_trip
        """
        scenario = fx.setup_funded_dry_advance()
        demand = fx.raise_repurchase_demand(
            scenario.advance["id"], reason="INELIGIBLE_PRODUCT"
        )
        asserts.assert_repurchase_demand(demand)
        assert demand["status"] == "OPEN"
        assert demand["demand_amount_cents"] == 1_960_000_000
        asserts.assert_instant(demand["deadline_at"], "2026-08-11T00:00:00Z")

        fx.set_clock("2026-08-10T00:00:00Z")
        validate_error(
            api_client.escalate_repurchase_demand(demand["id"], CREDIT_OFFICER),
            ApiErrorId.ERR_REPURCHASE_DEMAND_NOT_OPEN,
        )
        assert _only_demand_of(scenario.advance["id"])["status"] == "OPEN"

        # The deadline comparison is inclusive.
        fx.set_clock("2026-08-11T00:00:00Z")
        escalated = validate_success(
            api_client.escalate_repurchase_demand(demand["id"], CREDIT_OFFICER)
        )
        assert escalated["status"] == "ESCALATED"

        restricted = fx.read_facility(scenario.facility["id"])
        assert restricted["status"] == "RESTRICTED"
        assert restricted["escalated_demand_count"] == 1

        repurchased = validate_success(
            api_client.repurchase_advance(
                scenario.advance["id"],
                make.repurchase_payload(1_960_000_000),
                make_borrower_headers(scenario.facility["id"]),
            )
        )
        assert repurchased["funding_status"] == "REPURCHASED"
        assert repurchased["outstanding_balance_cents"] == 0

        assert _only_demand_of(scenario.advance["id"])["status"] == "SATISFIED"

        # The compensating decrement re-opens the line.
        restored = fx.read_facility(scenario.facility["id"])
        assert restored["escalated_demand_count"] == 0
        assert restored["status"] == "ACTIVE"
        assert restored["outstanding_principal_cents"] == 0
        assert restored["availability_cents"] == 20_000_000_000

        entries, meta = validate_paginated(
            api_client.list_advance_ledger_entries(
                scenario.advance["id"], CREDIT_OFFICER
            )
        )
        assert meta["total_count"] == 2
        asserts.assert_entry_types_in_order(
            entries, [("ADVANCE_FUNDED", "DEBIT"), ("REPURCHASE", "CREDIT")]
        )

        # `SATISFIED` is terminal, so the third escalation fails as well.
        validate_error(
            api_client.escalate_repurchase_demand(demand["id"], CREDIT_OFFICER),
            ApiErrorId.ERR_REPURCHASE_DEMAND_NOT_OPEN,
        )
