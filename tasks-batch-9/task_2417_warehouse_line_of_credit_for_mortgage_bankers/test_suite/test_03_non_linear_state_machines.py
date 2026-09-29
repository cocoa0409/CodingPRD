"""State machines that are not simple ladders.

The facility posture cycles, the wire decision forks into two entirely
different consequence sets, and an advance tracks money and documents on two
axes that move independently.
"""

import pytest

from test_helpers import CREDIT_OFFICER, WIRE_OPERATOR, api_client, validate_paginated
from test_helpers import assertions as asserts
from test_helpers import fixtures as fx


# ─── The facility posture cycle ────────────────────────────────────────────────

def _walk_the_facility_through_a_full_cycle():
    """RESTRICTED, back to ACTIVE, out to SUSPENDED, back, and RESTRICTED again."""
    scenario = fx.setup_funded_dry_advance()
    walk = [fx.read_facility(scenario.facility["id"])["status"]]

    scenario.advance = fx.mark_to_market(scenario.advance["id"], 1_900_000_000)
    scenario.first_call = fx.first_open_margin_call(scenario.facility["id"])
    walk.append(fx.read_facility(scenario.facility["id"])["status"])

    fx.waive_margin_call(
        scenario.first_call["id"],
        reason="Investor re-bid at par; shortfall resolved",
        officer_user_id="co_1",
    )
    walk.append(fx.read_facility(scenario.facility["id"])["status"])

    fx.suspend_facility(
        scenario.facility["id"], reason="Annual audit finding pending resolution"
    )
    walk.append(fx.read_facility(scenario.facility["id"])["status"])

    fx.reinstate_facility(scenario.facility["id"])
    walk.append(fx.read_facility(scenario.facility["id"])["status"])

    scenario.advance = fx.mark_to_market(scenario.advance["id"], 1_800_000_000)
    walk.append(fx.read_facility(scenario.facility["id"])["status"])

    scenario.walk = walk
    scenario.facility = fx.read_facility(scenario.facility["id"])
    scenario.calls = fx.facility_margin_calls(scenario.facility["id"])
    return scenario


class TestFacilityPostureCycle:
    def test_the_posture_returns_to_restricted_after_a_full_round_trip(self):
        """The posture graph has no terminal state and genuinely cycles.

        PRD 3.8: "That closes a genuine cycle — the same facility may traverse
        `ACTIVE`, `RESTRICTED` and back any number of times."

        Design: Difficulty/non_linear_state_machine/non_linear_facility_status_cycle_reentry
        """
        scenario = _walk_the_facility_through_a_full_cycle()

        assert scenario.walk == [
            "ACTIVE",
            "RESTRICTED",
            "ACTIVE",
            "SUSPENDED",
            "ACTIVE",
            "RESTRICTED",
        ]
        assert scenario.facility["status"] == "RESTRICTED"
        assert scenario.facility["open_margin_call_count"] == 1

    def test_the_second_entry_sizes_its_call_from_the_new_valuation(self):
        """Re-entry is a fresh computation, not a replay of the waived call.

        PRD 3.6: "If the recomputed `required_paydown_cents` is strictly positive
        **and** the advance has no margin call currently in `ISSUED` or
        `PARTIALLY_CURED`, a margin call is issued with `trigger_reason` of
        `VALUATION_DECLINE`, status `ISSUED`, and `call_amount_cents`
        snapshotted at this instant, and an `ACTIVE` facility moves to
        `RESTRICTED`."

        Design: Difficulty/non_linear_state_machine/non_linear_facility_status_cycle_reentry
        """
        scenario = _walk_the_facility_through_a_full_cycle()

        assert len(scenario.calls) == 2
        for call in scenario.calls:
            asserts.assert_margin_call(call)
            assert call["trigger_reason"] == "VALUATION_DECLINE"

        by_id = {call["id"]: call for call in scenario.calls}
        first = by_id[scenario.first_call["id"]]
        second = next(
            call for call in scenario.calls if call["id"] != first["id"]
        )

        # 1,960,000,000 outstanding against floor(1,900,000,000 * 0.98).
        assert first["call_amount_cents"] == 98_000_000
        assert first["status"] == "WAIVED"

        # 1,960,000,000 outstanding against floor(1,800,000,000 * 0.98).
        assert scenario.advance["eligible_collateral_value_cents"] == 1_764_000_000
        assert scenario.advance["required_paydown_cents"] == 196_000_000
        assert second["call_amount_cents"] == 196_000_000
        assert second["status"] == "ISSUED"


# ─── The wire decision fork ───────────────────────────────────────────────────

def _fork_two_wires_one_verified_one_blocked():
    """One advance funds through a verified wire; its sibling is blocked dead."""
    scenario = fx.setup_requested_advance()
    fx.file_receipt(scenario.advance["id"], scenario.custodian["id"])

    blocked = fx.book_advance(
        scenario.facility["id"],
        scenario.custodian["id"],
        investor_commitment_id=scenario.commitment["id"],
        loan_amount_cents=500_000_000,
        note_rate=0.0700,
        funding_type="WET",
        payee_name="Cascade Settlement Services",
        payee_routing_last4="0055",
    )

    fx.verify_wire(scenario.wire["id"], "CB-401")
    scenario.advance = fx.fund_advance(scenario.advance["id"])
    scenario.wire = fx.wire_for_advance(scenario.advance["id"])

    scenario.blocked_wire = fx.block_wire(fx.wire_for_advance(blocked["id"])["id"])
    scenario.blocked_advance = fx.read_advance(blocked["id"])

    scenario.facility = fx.read_facility(scenario.facility["id"])
    scenario.commitment = fx.read_commitment(scenario.commitment["id"])
    return scenario


class TestWireDecisionBranchDivergence:
    def test_a_verified_wire_releases_and_mints_exactly_one_funding_debit(self):
        """Verification leaves the advance fundable and the wire terminal.

        PRD 3.3: "One ledger entry of type `ADVANCE_FUNDED` and direction
        `DEBIT` is appended for `advance_amount_cents`, attributed to this
        advance, which is what makes `outstanding_principal_cents`,
        `availability_cents`, `wet_outstanding_cents`, `aged_outstanding_cents`
        and `scratch_and_dent_outstanding_cents` move."

        Design: Difficulty/non_linear_state_machine/non_linear_wire_verification_branch_divergence
        """
        scenario = _fork_two_wires_one_verified_one_blocked()

        asserts.assert_wire_instruction(scenario.wire)
        assert scenario.wire["status"] == "RELEASED"
        assert scenario.wire["decided_by_user_id"] == "wo_1"
        assert scenario.wire["callback_reference"] == "CB-401"

        assert scenario.advance["funding_status"] == "FUNDED"
        assert scenario.advance["advance_amount_cents"] == 1_960_000_000

        entries, meta = validate_paginated(
            api_client.list_advance_ledger_entries(
                scenario.advance["id"], CREDIT_OFFICER
            )
        )
        assert meta["total_count"] == 1
        asserts.assert_entry_types_in_order(entries, [("ADVANCE_FUNDED", "DEBIT")])
        assert entries[0]["amount_cents"] == 1_960_000_000

        assert scenario.facility["outstanding_principal_cents"] == 1_960_000_000
        assert scenario.commitment["allocated_amount_cents"] == 1_960_000_000

    def test_a_blocked_wire_terminates_its_advance_and_writes_nothing(self):
        """The other fork moves money nowhere at all.

        PRD 3.3: "Where a verification leaves the advance fundable, a block
        terminates it: `REJECTED` is terminal on the funding axis, no ledger
        entry is written, and `outstanding_principal_cents` never moves."

        Design: Difficulty/non_linear_state_machine/non_linear_wire_verification_branch_divergence
        """
        scenario = _fork_two_wires_one_verified_one_blocked()

        asserts.assert_wire_instruction(scenario.blocked_wire)
        assert scenario.blocked_wire["status"] == "BLOCKED"
        # The default reason for an operator-initiated block.
        assert scenario.blocked_wire["block_reason"] == "OPERATOR_BLOCK"
        assert scenario.blocked_wire["decided_by_user_id"] == "wo_1"

        assert scenario.blocked_advance["funding_status"] == "REJECTED"
        assert scenario.blocked_advance["rejected_reason"] == "WIRE_BLOCKED"
        assert scenario.blocked_advance["outstanding_balance_cents"] == 0

        _entries, meta = validate_paginated(
            api_client.list_advance_ledger_entries(
                scenario.blocked_advance["id"], CREDIT_OFFICER
            )
        )
        assert meta["total_count"] == 0

        # Only the funded sibling shows up in the rollup or the allocation.
        assert scenario.facility["outstanding_principal_cents"] == 1_960_000_000
        assert scenario.commitment["allocated_amount_cents"] == 1_960_000_000


# ─── The two independent advance axes ─────────────────────────────────────────

def _move_the_custody_axis_while_funding_stands_still():
    """Exception, cure and finally release, all under a single FUNDED advance."""
    scenario = fx.setup_funded_wet_advance()

    scenario.receipt = fx.file_receipt(
        scenario.advance["id"],
        scenario.custodian["id"],
        document_types=["NOTE", "MORTGAGE"],
        exception_codes=["MISSING_NOTE", "UNSIGNED_ASSIGNMENT"],
    )
    scenario.advance_on_exception = fx.read_advance(scenario.advance["id"])
    scenario.facility_on_exception = fx.read_facility(scenario.facility["id"])
    scenario.exception_calls = [
        call
        for call in fx.advance_margin_calls(scenario.advance["id"])
        if call["trigger_reason"] == "CUSTODY_EXCEPTION"
    ]

    scenario.receipt = fx.cure_receipt(
        scenario.receipt["id"],
        scenario.custodian["id"],
        ["MISSING_NOTE", "UNSIGNED_ASSIGNMENT"],
    )
    scenario.advance_on_cure = fx.read_advance(scenario.advance["id"])
    scenario.facility_on_cure = fx.read_facility(scenario.facility["id"])
    scenario.call_after_cure = fx.read_margin_call(scenario.exception_calls[0]["id"])

    fx.set_clock("2026-08-05T00:00:00Z")
    fx.ship_advance(scenario.advance["id"], scenario.investor["id"])
    scenario.bailee_letter = fx.advance_bailee_letters(scenario.advance["id"])[-1]
    scenario.advance_on_shipment = fx.read_advance(scenario.advance["id"])
    return scenario


class TestAdvanceParallelAxes:
    def test_the_custody_axis_moves_twice_while_funding_stays_funded(self):
        """Document defects and their cure never touch the money axis.

        PRD 3.6: "The third step is the document-exception haircut: when
        `custody_status` is `RECEIVED_EXCEPTION`, a further 0.05 is subtracted."

        Design: Difficulty/non_linear_state_machine/non_linear_advance_parallel_funding_and_custody_axes
        """
        scenario = _move_the_custody_axis_while_funding_stands_still()

        on_exception = scenario.advance_on_exception
        assert on_exception["funding_status"] == "FUNDED"
        assert on_exception["custody_status"] == "RECEIVED_EXCEPTION"
        # The file is in hand, so the wet haircut lifts and only the 0.05
        # document-exception haircut applies.
        assert on_exception["effective_advance_rate"] == pytest.approx(0.93, abs=1e-6)
        assert on_exception["eligible_collateral_value_cents"] == 1_860_000_000
        assert on_exception["required_paydown_cents"] == 60_000_000
        assert scenario.facility_on_exception["status"] == "RESTRICTED"

        assert len(scenario.exception_calls) == 1
        call = scenario.exception_calls[0]
        assert call["status"] == "ISSUED"
        assert call["call_amount_cents"] == 60_000_000
        assert call["advance_id"] == scenario.advance["id"]

        on_cure = scenario.advance_on_cure
        assert on_cure["funding_status"] == "FUNDED"
        assert on_cure["custody_status"] == "EXCEPTION_CURED"
        assert on_cure["effective_advance_rate"] == pytest.approx(0.98, abs=1e-6)
        assert on_cure["eligible_collateral_value_cents"] == 1_960_000_000
        assert on_cure["required_paydown_cents"] == 0

        assert scenario.receipt["status"] == "CURED"
        assert sorted(scenario.receipt["cured_exception_codes"]) == [
            "MISSING_NOTE",
            "UNSIGNED_ASSIGNMENT",
        ]
        assert scenario.call_after_cure["status"] == "CURED"
        assert scenario.facility_on_cure["status"] == "ACTIVE"

    def test_shipment_is_the_one_trigger_that_moves_both_axes_at_once(self):
        """Only the release to the investor couples money and documents.

        PRD 3.7: "A successful shipment moves the funding axis `FUNDED →
        SHIPPED` and stamps `shipped_at` with the logical clock, while the
        custody axis moves from `RECEIVED_CLEAR` or `EXCEPTION_CURED` to the
        terminal `RELEASED_TO_INVESTOR`."

        Design: Difficulty/non_linear_state_machine/non_linear_advance_parallel_funding_and_custody_axes
        """
        scenario = _move_the_custody_axis_while_funding_stands_still()
        advance = scenario.advance_on_shipment

        assert advance["funding_status"] == "SHIPPED"
        assert advance["custody_status"] == "RELEASED_TO_INVESTOR"
        asserts.assert_instant(advance["shipped_at"], "2026-08-05T00:00:00Z")

        letter = scenario.bailee_letter
        asserts.assert_bailee_letter(letter)
        assert letter["status"] == "ISSUED"
        assert letter["bailee_period_days"] == 30
        asserts.assert_instant(letter["effective_from"], "2026-08-05T00:00:00Z")
        asserts.assert_instant(letter["expires_at"], "2026-09-04T00:00:00Z")

        # Shipment moves documents rather than money.
        assert advance["outstanding_balance_cents"] == 1_920_000_000

    def test_the_wire_axis_is_already_terminal_before_either_axis_moves(self):
        """The wire finished its own life at funding and never re-enters play.

        PRD 3.3: "The wire moves `VERIFIED → RELEASED`, which is terminal for
        it."

        Design: Difficulty/non_linear_state_machine/non_linear_advance_parallel_funding_and_custody_axes
        """
        scenario = _move_the_custody_axis_while_funding_stands_still()
        wires, meta = validate_paginated(
            api_client.list_advance_wire_instructions(
                scenario.advance["id"], WIRE_OPERATOR
            )
        )
        assert meta["total_count"] == 1
        assert wires[0]["status"] == "RELEASED"
