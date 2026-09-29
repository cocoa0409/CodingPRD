"""Three conserved quantities, each driven out and back with zero drift.

A monetary ledger in cents, a discrete allocation count of operations, and an
outstanding-obligation counter. In every case the compensating write must return
the quantity to exactly its prior value, and the stored amount that funded the
reversal must never be recomputed on the way back.
"""

import pytest

from test_helpers import (
    acknowledge_submission,
    api_client,
    assert_charge_ledger_matches_submissions,
    assert_timestamp_equals,
    attach_slot,
    cancel_leg,
    dispatch_obligation,
    queue_submission,
    raise_obligation,
    read_holding,
    read_leg,
    read_obligation,
    read_version,
    setup_booked_leg,
    setup_monday_series_schedule,
    transmit_submission,
    validate_paginated,
    TEST_USERS,
)

COORDINATOR = TEST_USERS["slot_coordinator_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


# ─── Conserved quantity 1: the filing charge ledger, in cents ─────────────

def _queued_expedited_filing():
    """A clean four-leg version with one EXPEDITED submission still QUEUED."""
    return setup_monday_series_schedule(
        leg_count=4,
        series_weeks=5,
        version_label="W26-L9",
        validate=True,
        submission={"distribution_system": "IATA_SSIM", "change_window": "EXPEDITED"},
    )


class TestFilingChargeLedgerReturnsToZero:
    """Transmit adds 22815; a downstream rejection subtracts the same 22815."""

    def test_a_queued_submission_priced_but_not_yet_on_the_ledger(self):
        """The sum over TRANSMITTED and ACKNOWLEDGED submissions is still
        empty.

        PRD §3.8: "a version's `filing_charge_accrued_cents` always equals the
        sum of `total_charge_cents` over its submissions whose `status` is
        `TRANSMITTED` or `ACKNOWLEDGED`, and no other."

        Design: Difficulty/compensating_invariant/filing_charge_ledger_returns_to_exactly_zero_after_transmit_then_rejection
        """
        world = _queued_expedited_filing()
        submission = world["submission"]

        assert submission["status"] == "QUEUED"
        assert submission["base_charge_subtotal_cents"] == 16900
        assert submission["expedite_rate_pct"] == pytest.approx(35.00, abs=0.01)
        assert submission["expedite_fee_cents"] == 5915
        assert submission["total_charge_cents"] == 22815

        version = read_version(world["version"]["id"], world["planner"])
        assert version["filing_charge_accrued_cents"] == 0
        assert version["filing_charge_budget_cents"] == 100000
        assert_charge_ledger_matches_submissions(version, [submission])

    def test_transmission_moves_the_stored_total_onto_the_ledger(self):
        """The ledger takes exactly the submission's own stored total.

        PRD §3.8: "A successful transmission moves the submission `QUEUED →
        TRANSMITTED`, stamps `transmitted_by_user_id` with the acting user and
        `transmitted_at_utc` with the logical clock, adds `total_charge_cents` to
        the version's `filing_charge_accrued_cents`, moves the version
        `VALIDATED → FILED`, and moves every one of that version's `SLOT_BACKED`
        legs to `FILED`."

        Design: Difficulty/compensating_invariant/filing_charge_ledger_returns_to_exactly_zero_after_transmit_then_rejection
        """
        world = _queued_expedited_filing()
        transmitted = transmit_submission(world["submission"]["id"])
        assert transmitted["status"] == "TRANSMITTED"

        version = read_version(world["version"]["id"], world["planner"])
        assert version["filing_charge_accrued_cents"] == 22815
        assert version["filing_status"] == "FILED"
        assert_charge_ledger_matches_submissions(version, [transmitted])

        for leg in world["legs"]:
            assert read_leg(leg["id"], world["planner"])["status"] == "FILED"

    def test_a_downstream_rejection_returns_the_ledger_to_exactly_zero(self):
        """Not one cent of drift, and the stored charge is not rewritten.

        PRD §3.8: "**subtracts** `total_charge_cents` back off the version's
        `filing_charge_accrued_cents` so the ledger returns exactly to its
        pre-transmit value with no drift, moves the version `FILED → VALIDATED`,
        and moves every `FILED` leg of that version back to `SLOT_BACKED`"

        Design: Difficulty/compensating_invariant/filing_charge_ledger_returns_to_exactly_zero_after_transmit_then_rejection
        """
        world = _queued_expedited_filing()
        transmit_submission(world["submission"]["id"])

        rejected = acknowledge_submission(
            world["submission"]["id"],
            outcome="REJECT",
            rejection_reason="SSIM_SEGMENT_SYNTAX",
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "SSIM_SEGMENT_SYNTAX"
        assert rejected["total_charge_cents"] == 22815

        version = read_version(world["version"]["id"], world["planner"])
        assert version["filing_charge_accrued_cents"] == 0
        assert version["filing_status"] == "VALIDATED"
        assert_charge_ledger_matches_submissions(version, [rejected])

        for leg in world["legs"]:
            assert read_leg(leg["id"], world["planner"])["status"] == "SLOT_BACKED"

    def test_the_restored_budget_funds_the_identical_filing_again(self):
        """With the ledger at zero the same 22815 fits under the same budget.

        PRD §3.8: "the version's `filing_charge_accrued_cents` plus this
        submission's `total_charge_cents` must be no greater than its
        `filing_charge_budget_cents`, or it fails with
        `ERR_FILING_CHARGE_BUDGET_EXCEEDED`, which is the one payment-related
        status in the catalogue."

        Design: Difficulty/compensating_invariant/filing_charge_ledger_returns_to_exactly_zero_after_transmit_then_rejection
        """
        world = _queued_expedited_filing()
        transmit_submission(world["submission"]["id"])
        acknowledge_submission(
            world["submission"]["id"],
            outcome="REJECT",
            rejection_reason="SSIM_SEGMENT_SYNTAX",
        )

        replacement = queue_submission(
            world["version"]["id"], change_window="EXPEDITED"
        )
        assert replacement["total_charge_cents"] == 22815
        replacement = transmit_submission(replacement["id"])
        assert replacement["status"] == "TRANSMITTED"

        version = read_version(world["version"]["id"], world["planner"])
        assert version["filing_charge_accrued_cents"] == 22815
        assert version["filing_charge_budget_cents"] == 100000

        # A filing reversal never touched the slot side of the world.
        holding = read_holding(world["holding"]["id"], COORDINATOR)
        assert holding["attached_operations"] == 4
        assert holding["utilization_pct_as_filed"] == pytest.approx(80.00, abs=0.01)


# ─── Conserved quantity 2: attached operations, a discrete allocation ─────

def _three_of_four_mondays_attached():
    """Four assigned Monday legs, only the first three slot-backed."""
    return setup_monday_series_schedule(
        leg_count=4, series_weeks=5, attach_count=3, version_label="W26-C9"
    )


class TestAttachedOperationsIsConserved:
    """3 -> 4 -> 3, with the derived percentage walking 60.00 -> 80.00 ->
    60.00."""

    def test_the_partly_attached_series_starts_at_risk(self):
        """Three of five planned operations is 60.00 percent and blocks the
        plan.

        PRD §2.6: "`attached_operations` on a slot series always equals the
        number of flight legs whose `status` is not `CANCELLED` and which
        reference that series through either `departure_slot_holding_id` or
        `arrival_slot_holding_id`. Attaching raises it; detaching, retiming and
        cancelling lower it back."

        Design: Difficulty/compensating_invariant/attached_operations_count_is_conserved_across_attach_then_cancel
        """
        world = _three_of_four_mondays_attached()

        holding = read_holding(world["holding"]["id"], COORDINATOR)
        assert holding["planned_operations"] == 5
        assert holding["attached_operations"] == 3
        assert holding["utilization_pct_as_filed"] == pytest.approx(60.00, abs=0.01)
        assert holding["at_risk_of_loss"] is True

        version = read_version(world["version"]["id"], world["planner"])
        assert version["unslotted_leg_count"] == 1
        assert version["at_risk_slot_count"] == 1
        assert version["schedule_compliance_score"] == pytest.approx(77.00, abs=0.01)
        assert version["compliance_state"] == "BLOCKED"

    def test_attaching_the_fourth_operation_clears_the_risk(self):
        """The count rises to 4 and the percentage reaches the threshold
        exactly.

        PRD §3.5: "`at_risk_of_loss` is true exactly when the series is still
        `HELD`, `attached_operations` is at least 1, and
        `utilization_pct_as_filed` is strictly below 80.00."

        Design: Difficulty/compensating_invariant/attached_operations_count_is_conserved_across_attach_then_cancel
        """
        world = _three_of_four_mondays_attached()

        attached = attach_slot(
            world["carrier"]["id"],
            world["legs"][3]["id"],
            world["holding"]["id"],
            "DEPARTURE",
        )
        assert attached["status"] == "SLOT_BACKED"

        holding = read_holding(world["holding"]["id"], COORDINATOR)
        assert holding["attached_operations"] == 4
        assert holding["utilization_pct_as_filed"] == pytest.approx(80.00, abs=0.01)
        assert holding["at_risk_of_loss"] is False

        version = read_version(world["version"]["id"], world["planner"])
        assert version["unslotted_leg_count"] == 0
        assert version["at_risk_slot_count"] == 0
        assert version["schedule_compliance_score"] == pytest.approx(100.00, abs=0.01)
        assert version["compliance_state"] == "CLEAN"

    def test_cancelling_that_leg_returns_the_count_to_exactly_three(self):
        """A cancelled leg leaves the attached set, so the count walks back.

        PRD §3.4: "That detachment is the exact compensation of the attachment,
        returning `attached_operations` to its pre-attach value with no drift."

        Design: Difficulty/compensating_invariant/attached_operations_count_is_conserved_across_attach_then_cancel
        """
        world = _three_of_four_mondays_attached()
        attach_slot(
            world["carrier"]["id"],
            world["legs"][3]["id"],
            world["holding"]["id"],
            "DEPARTURE",
        )

        cancelled = cancel_leg(
            world["carrier"]["id"], world["legs"][3]["id"], "DEMAND_SHORTFALL"
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_reason"] == "DEMAND_SHORTFALL"
        assert cancelled["departure_slot_holding_id"] is None

        holding = read_holding(world["holding"]["id"], COORDINATOR)
        assert holding["attached_operations"] == 3
        assert holding["utilization_pct_as_filed"] == pytest.approx(60.00, abs=0.01)
        assert holding["at_risk_of_loss"] is True

    def test_the_cancelled_leg_stays_on_the_manifest_but_not_in_the_counters(self):
        """`leg_count` keeps it while every other counter drops it.

        PRD §3.4: "`leg_count` is the number of legs whose
        `schedule_version_id` is this version **including cancelled ones** - a
        cancelled leg stays on the version's manifest, so this counter only ever
        rises."

        Design: Difficulty/compensating_invariant/attached_operations_count_is_conserved_across_attach_then_cancel
        """
        world = _three_of_four_mondays_attached()
        attach_slot(
            world["carrier"]["id"],
            world["legs"][3]["id"],
            world["holding"]["id"],
            "DEPARTURE",
        )
        cancel_leg(world["carrier"]["id"], world["legs"][3]["id"], "DEMAND_SHORTFALL")

        version = read_version(world["version"]["id"], world["planner"])
        assert version["leg_count"] == 4
        assert version["unslotted_leg_count"] == 0
        assert version["at_risk_slot_count"] == 1
        assert version["schedule_compliance_score"] == pytest.approx(85.00, abs=0.01)
        assert version["compliance_state"] == "BLOCKED"

        # Only the as-filed variant ever moved: nothing was ever operated.
        holding = read_holding(world["holding"]["id"], COORDINATOR)
        assert holding["credited_operations"] == 0
        assert holding["utilization_pct"] == pytest.approx(0.00, abs=0.01)


# ─── Conserved quantity 3: outstanding obligations on a leg ───────────────

class TestOpenObligationCountIsConserved:
    """0 -> 1 -> 0 while the obligation row itself survives, frozen."""

    def test_raising_an_advisory_obligation_opens_exactly_one(self):
        """The counter rises to 1 and the compensation is frozen on the row.

        PRD §3.9: "Every new obligation starts in `status` `PENDING` with
        `dispatched_channel`, `regulator_reference` and `waiver_reason` null and
        `late_dispatch` false, and increments the leg's `open_obligation_count`."

        Design: Difficulty/compensating_invariant/open_obligation_count_is_conserved_across_create_then_dispatch
        """
        world = setup_booked_leg(version_label="W26-N9")
        assert world["leg"]["open_obligation_count"] == 0

        obligation = raise_obligation(
            world["leg"]["id"], trigger_kind="RETIME", change_magnitude_minutes=45
        )
        assert obligation["status"] == "PENDING"
        assert obligation["obligation_tier"] == "ADVISORY"
        assert obligation["booked_total"] == 51
        assert obligation["booked_first"] == 3
        assert obligation["booked_business"] == 7
        assert obligation["booked_economy"] == 41
        assert obligation["compensation_cents"] == 561132
        assert obligation["late_dispatch"] is False
        assert_timestamp_equals(
            obligation["notify_deadline_utc"],
            "2026-08-04T00:00:00Z",
            "notify_deadline_utc",
        )

        leg = read_leg(world["leg"]["id"], world["planner"])
        assert leg["open_obligation_count"] == 1

    def test_dispatching_the_notice_returns_the_counter_to_exactly_zero(self):
        """The compensating exit lowers the counter and freezes the amount.

        PRD §3.9: "On success `status` moves `PENDING → DISPATCHED`,
        `dispatched_channel` and `regulator_reference` are recorded,
        `late_dispatch` is set to true exactly when `current_utc` is strictly
        after `notify_deadline_utc` - a dispatch at the deadline instant is on
        time - and the leg's `open_obligation_count` decreases by 1."

        Design: Difficulty/compensating_invariant/open_obligation_count_is_conserved_across_create_then_dispatch
        """
        world = setup_booked_leg(version_label="W26-N9")
        obligation = raise_obligation(
            world["leg"]["id"], trigger_kind="RETIME", change_magnitude_minutes=45
        )

        dispatched = dispatch_obligation(obligation["id"], channel="EMAIL")
        assert dispatched["status"] == "DISPATCHED"
        assert dispatched["dispatched_channel"] == "EMAIL"
        assert dispatched["late_dispatch"] is False
        assert dispatched["compensation_cents"] == 561132

        leg = read_leg(world["leg"]["id"], world["planner"])
        assert leg["open_obligation_count"] == 0

    def test_the_row_was_transitioned_rather_than_deleted(self):
        """The counter counts only PENDING rows, so the survivor is invisible to
        it.

        PRD §3.9: "a leg's `open_obligation_count` always equals the number of
        its obligations still in `PENDING`."

        Design: Difficulty/compensating_invariant/open_obligation_count_is_conserved_across_create_then_dispatch
        """
        world = setup_booked_leg(version_label="W26-N9")
        obligation = raise_obligation(
            world["leg"]["id"], trigger_kind="RETIME", change_magnitude_minutes=45
        )
        dispatch_obligation(obligation["id"], channel="EMAIL")

        rows, meta = validate_paginated(
            api_client.list_notification_obligations(
                OFFICER, params={"flight_leg_id": world["leg"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["id"] == obligation["id"]
        assert rows[0]["status"] == "DISPATCHED"

        survivor = read_obligation(obligation["id"], OFFICER)
        assert survivor["compensation_cents"] == 561132
        assert survivor["status"] == "DISPATCHED"
