"""Two multi-level cascades from two different triggers.

One retime detaches a slot and the consequences travel five links to a filing
rejection and a reversed accrual. One coordinator approval transfers a series
away and the consequences travel four links to a resync flag on a submission
that keeps its status and its charge.
"""

import pytest

from test_helpers import (
    api_client,
    assert_charge_ledger_matches_submissions,
    assert_score_matches_counters,
    assert_timestamp_equals,
    make_partner_carrier_headers,
    propose_transaction,
    read_holding,
    read_leg,
    read_submission,
    read_version,
    retime_leg,
    setup_monday_series_schedule,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

COORDINATOR = TEST_USERS["slot_coordinator_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
AGENT = TEST_USERS["filing_agent_headers"]


def _filed_four_monday_series():
    """Four Monday legs of a five-week series, expedited-filed and
    acknowledged."""
    return setup_monday_series_schedule(
        leg_count=4,
        series_weeks=5,
        validate=True,
        submission={"change_window": "EXPEDITED"},
        transmit=True,
        acknowledge="ACCEPT",
    )


def _retime_the_last_monday(world):
    return retime_leg(
        world["carrier"]["id"],
        world["legs"][3]["id"],
        "2026-11-23T10:00:00.000Z",
        "2026-11-23T11:00:00.000Z",
    )


class TestRetimeCascadesToFilingRejection:
    """PATCH one leg; five links later a filing has been rejected."""

    def test_the_retimed_leg_detaches_and_the_series_falls_below_the_threshold(self):
        """Links one to three: leg detached, series recomputed, risk flag
        flipped.

        PRD §3.4: "Because the slot identifiers were nulled, each detached
        series recomputes `attached_operations` and `utilization_pct_as_filed`.
        Because those fell, any such series still `HELD` with at least one
        remaining attached operation whose `utilization_pct_as_filed` is now
        below 80.00 percent flips `at_risk_of_loss` to true."

        Design: Difficulty/transitive_cascade/retiming_a_filed_leg_cascades_five_levels_to_filing_submission_rejection
        """
        world = _filed_four_monday_series()

        leg = _retime_the_last_monday(world)
        assert leg["status"] == "REFILE_REQUIRED"
        assert_timestamp_equals(leg["dep_utc"], "2026-11-23T10:00:00Z", "dep_utc")
        assert leg["departure_slot_holding_id"] is None
        assert leg["arrival_slot_holding_id"] is None

        holding = read_holding(world["holding"]["id"], COORDINATOR)
        assert holding["attached_operations"] == 3
        assert holding["utilization_pct_as_filed"] == pytest.approx(60.00, abs=0.01)
        assert holding["at_risk_of_loss"] is True
        assert holding["holding_status"] == "HELD"

    def test_the_version_blocks_on_the_single_at_risk_series(self):
        """Link four: two counters move and the posture becomes BLOCKED.

        PRD §3.7: "It is `BLOCKED` when `at_risk_slot_count` is at least 1 **or**
        the score is strictly below 60.00."

        Design: Difficulty/transitive_cascade/retiming_a_filed_leg_cascades_five_levels_to_filing_submission_rejection
        """
        world = _filed_four_monday_series()
        _retime_the_last_monday(world)

        version = read_version(world["version"]["id"], world["planner"])
        assert version["at_risk_slot_count"] == 1
        assert version["unslotted_leg_count"] == 1
        assert version["schedule_compliance_score"] == pytest.approx(77.00, abs=0.01)
        assert version["compliance_state"] == "BLOCKED"
        assert_score_matches_counters(version)

    def test_the_block_rejects_the_acknowledged_filing_and_reverses_the_charge(self):
        """Link five: the acknowledged submission is internally rejected.

        PRD §3.8: "a submission already in `ACKNOWLEDGED` is rejected by the
        cascade that fires when its version enters `compliance_state`
        `BLOCKED`. In that case `rejection_reason` is set to the literal
        `SCHEDULE_BLOCKED`, distinguishing an internally-forced rejection from a
        downstream one, and `total_charge_cents` is subtracted back off
        `filing_charge_accrued_cents`"

        Design: Difficulty/transitive_cascade/retiming_a_filed_leg_cascades_five_levels_to_filing_submission_rejection
        """
        world = _filed_four_monday_series()
        submission_id = world["submission"]["id"]
        assert world["submission"]["total_charge_cents"] == 22815

        _retime_the_last_monday(world)

        submission = read_submission(submission_id, AGENT)
        assert submission["status"] == "REJECTED"
        assert submission["rejection_reason"] == "SCHEDULE_BLOCKED"

        version = read_version(world["version"]["id"], world["planner"])
        assert version["filing_charge_accrued_cents"] == 0
        assert version["filing_status"] == "VALIDATED"
        assert_charge_ledger_matches_submissions(version, [submission])

    def test_the_filed_legs_step_back_but_the_retimed_one_is_skipped(self):
        """The conditional part of the cascade touches only the FILED legs.

        PRD §3.4: "and the version's remaining `FILED` legs move back to
        `SLOT_BACKED`."

        Design: Difficulty/transitive_cascade/retiming_a_filed_leg_cascades_five_levels_to_filing_submission_rejection
        """
        world = _filed_four_monday_series()
        planner = world["planner"]
        _retime_the_last_monday(world)

        for leg in world["legs"][:3]:
            assert read_leg(leg["id"], planner)["status"] == "SLOT_BACKED"
        assert read_leg(world["legs"][3]["id"], planner)["status"] == "REFILE_REQUIRED"

        # The as-operated variant never entered this cascade: no record exists.
        holding = read_holding(world["holding"]["id"], COORDINATOR)
        assert holding["credited_operations"] == 0
        assert holding["utilization_pct"] == pytest.approx(0.00, abs=0.01)

    def test_an_unbooked_retime_raises_no_passenger_obligation(self):
        """Zero booked passengers means the passenger fan-out does not fire.

        PRD §3.4: "when the leg's booked load across all three cabins is greater
        than zero and the magnitude of the retime reaches 30 minutes, a passenger
        notification obligation with `trigger_kind` `RETIME` is raised, and the
        leg's `open_obligation_count` increments."

        Design: Difficulty/transitive_cascade/retiming_a_filed_leg_cascades_five_levels_to_filing_submission_rejection
        """
        world = _filed_four_monday_series()
        leg = _retime_the_last_monday(world)
        assert leg["booked_first"] == 0
        assert leg["booked_business"] == 0
        assert leg["booked_economy"] == 0
        assert leg["open_obligation_count"] == 0

        rows, meta = validate_paginated(
            api_client.list_notification_obligations(
                OFFICER, params={"flight_leg_id": world["legs"][3]["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert rows == []


def _acknowledged_two_monday_series():
    """A two-week series with both Mondays attached, filed on OAG and
    acknowledged."""
    world = setup_monday_series_schedule(
        leg_count=2,
        series_weeks=2,
        version_label="W26-T1",
        flight_number="HX601",
        with_partner=True,
        validate=True,
        submission={"distribution_system": "OAG", "change_window": "STANDARD"},
        transmit=True,
        acknowledge="ACCEPT",
    )
    world["counterparty"] = make_partner_carrier_headers(world["partner"]["id"])
    return world


def _approve_transfer_of_the_series(world):
    holding = read_holding(world["holding"]["id"], COORDINATOR)
    transaction = propose_transaction(
        carrier_id=world["carrier"]["id"],
        counterparty_carrier_id=world["partner"]["id"],
        offered_slot_holding_id=holding["id"],
        expected_slot_holding_version=holding["version"],
        kind="TRANSFER",
        response_deadline_utc="2026-08-20T23:59:59.000Z",
    )
    validate_success(
        api_client.respond_slot_transaction(
            transaction["id"], {"decision": "ACCEPT"}, world["counterparty"]
        )
    )
    return validate_success(
        api_client.approve_slot_transaction(
            transaction["id"], {"decision": "APPROVE"}, COORDINATOR
        )
    )


class TestTransferApprovalCascadesToResyncFlag:
    """Approve one transfer; four links later a submission needs re-filing."""

    def test_approval_transfers_the_series_out_and_strands_both_legs(self):
        """Links one and two: the series leaves the carrier and its legs
        detach.

        PRD §3.6: "Every leg attached to a holding that changed carrier - and on
        an exchange that is legs on **both** sides - whose `status` is
        `SLOT_BACKED` or `FILED` moves to `REFILE_REQUIRED` with the referencing
        slot identifier nulled."

        Design: Difficulty/transitive_cascade/approving_a_slot_transfer_cascades_four_levels_to_codeshare_resync_flag
        """
        world = _acknowledged_two_monday_series()
        planner = world["planner"]

        transaction = _approve_transfer_of_the_series(world)
        assert transaction["status"] == "EXECUTED"

        original = read_holding(world["holding"]["id"], COORDINATOR)
        assert original["holding_status"] == "TRANSFERRED_OUT"
        assert original["attached_operations"] == 0
        assert original["retains_historic_precedence"] is False

        successor = read_holding(
            transaction["successor_slot_holding_id"], COORDINATOR
        )
        assert successor["carrier_id"] == world["partner"]["id"]
        assert successor["historic_predecessor_holding_id"] == world["holding"]["id"]

        for leg in world["legs"]:
            detached = read_leg(leg["id"], planner)
            assert detached["status"] == "REFILE_REQUIRED"
            assert detached["departure_slot_holding_id"] is None

    def test_two_unslotted_legs_warn_the_version_without_any_at_risk_series(self):
        """Link three: 16.00 of penalty and a WARNED posture, not a BLOCKED
        one.

        PRD §3.5: "`at_risk_of_loss` is true exactly when the series is still
        `HELD`, `attached_operations` is at least 1, and
        `utilization_pct_as_filed` is strictly below 80.00."

        Design: Difficulty/transitive_cascade/approving_a_slot_transfer_cascades_four_levels_to_codeshare_resync_flag
        """
        world = _acknowledged_two_monday_series()
        _approve_transfer_of_the_series(world)

        version = read_version(world["version"]["id"], world["planner"])
        assert version["unslotted_leg_count"] == 2
        assert version["at_risk_slot_count"] == 0
        assert version["schedule_compliance_score"] == pytest.approx(84.00, abs=0.01)
        assert version["compliance_state"] == "WARNED"
        assert_score_matches_counters(version)

    def test_the_warning_flags_resync_and_reverses_nothing(self):
        """Link four: the acknowledged filing keeps its status and its charge.

        PRD §3.7: "Moving into `WARNED` from `CLEAN` sets `resync_required` to
        true on every filing submission of the version whose `status` is
        `ACKNOWLEDGED`; the submission itself **stays** `ACKNOWLEDGED`, because
        the distribution systems did accept what they were sent - it is simply no
        longer what the airline intends to fly."

        Design: Difficulty/transitive_cascade/approving_a_slot_transfer_cascades_four_levels_to_codeshare_resync_flag
        """
        world = _acknowledged_two_monday_series()
        submission_id = world["submission"]["id"]
        assert world["submission"]["total_charge_cents"] == 8450
        assert world["submission"]["resync_required"] is False

        _approve_transfer_of_the_series(world)

        submission = read_submission(submission_id, AGENT)
        assert submission["resync_required"] is True
        assert submission["status"] == "ACKNOWLEDGED"

        version = read_version(world["version"]["id"], world["planner"])
        assert version["filing_charge_accrued_cents"] == 8450
        assert version["filing_status"] == "FILED"
        assert_charge_ledger_matches_submissions(version, [submission])
