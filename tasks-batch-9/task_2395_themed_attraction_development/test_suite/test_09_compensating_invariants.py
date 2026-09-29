"""What one action adds, its compensating twin takes back exactly."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_segment,
    open_project,
    post_change_order,
    project_version,
    propose_segment,
    read_budget_position,
    read_capacity_summary,
    read_ledger,
    read_project,
    register_ride_system,
    retire_segment,
    reverse_entry,
    select_ride,
    setup_program_with_approved_package,
    validate_error,
    validate_success,
)

OWNER = TEST_USERS["owner_rep_headers"]
DESIGNER = TEST_USERS["creative_director_headers"]

CHANGE_ORDER_MEMO = "Owner-directed scenic upgrade to the finale chamber"
REVERSAL_REASON = "Upgrade descoped by the owner before release for construction"


class TestLedgerReversalConservesTheCommittedCost:
    """Three rows stand, and the committed cost is back where it began."""

    def _programme_with_a_reversed_change_order(self):
        ctx = setup_program_with_approved_package()
        ctx["change_order"] = post_change_order(ctx["project"]["id"], 200000000,
                                                memo=CHANGE_ORDER_MEMO)
        ctx["after_change_order"] = read_project(ctx["project"]["id"])
        ctx["reversal"] = reverse_entry(ctx["change_order"]["id"], ctx["project"]["id"],
                                       reason=REVERSAL_REASON)
        return ctx

    def test_the_reversal_twin_restores_the_committed_cost_exactly(self, api):
        """The reversal marks the original's `reversed` flag true, then mints a new entry with `entry_kind` `REVERSAL`, an `amount_cents` equal to the negation of the original's `amount_cents`, a `reversal_of_sequence_no` equal to the original's `sequence_no`, and its own freshly minted `sequence_no`; the new entry — not the original — is what the response returns.

        Because the pair sums to zero, the recomputation restores the pre-entry
        committed cost exactly, and the programme's `version` advances by one.

        The change order carried the committed cost to 3280000000 and the programme to
        RESTRICTED; its compensating twin brings both back — 3080000000 and OPEN —
        while the ledger keeps all three rows.

        Design: Difficulty/compensating_invariant/ledger_reversal_restores_committed_cost_and_posture_without_drift
        """
        ctx = self._programme_with_a_reversed_change_order()

        original = validate_success(
            api.get_ledger_entry(ctx["change_order"]["id"], OWNER))
        programme = read_project(ctx["project"]["id"])
        budget = read_budget_position(ctx["project"]["id"])
        rows, meta = read_ledger(ctx["project"]["id"])

        assert ctx["change_order"]["sequence_no"] == 2
        assert ctx["after_change_order"]["committed_cost_cents"] == 3280000000
        assert ctx["after_change_order"]["readiness_posture"] == "RESTRICTED"
        assert ctx["reversal"]["entry_kind"] == "REVERSAL"
        assert ctx["reversal"]["amount_cents"] == -200000000
        assert ctx["reversal"]["sequence_no"] == 3
        assert ctx["reversal"]["reversal_of_sequence_no"] == 2
        assert original["reversed"] is True
        assert original["amount_cents"] == 200000000
        assert programme["committed_cost_cents"] == 3080000000
        assert programme["forecast_cost_cents"] == 3080000000
        assert programme["readiness_posture"] == "OPEN"
        assert budget["headroom_cents"] == 520000000
        assert len(rows) == 3
        assert meta["total_count"] == 3
        assert sum(row["amount_cents"] for row in rows) == 3080000000

    def test_the_same_entry_cannot_be_compensated_twice(self, api):
        """The target must not already have been reversed and must not itself be a `REVERSAL`; either condition is refused with `ERR_LEDGER_ENTRY_ALREADY_REVERSED`.

        No status filter is applied — an entry whose `reversed` flag is true still
        contributes its original amount, and its `REVERSAL` twin contributes the
        negation — and no rounding occurs, because every input is already a whole
        number of cents.

        A second compensation would drive the committed cost below the sum the ledger
        actually records, so it is refused and the three rows stand untouched.

        Design: Difficulty/compensating_invariant/ledger_reversal_restores_committed_cost_and_posture_without_drift
        """
        ctx = self._programme_with_a_reversed_change_order()

        response = api.reverse_ledger_entry(
            ctx["change_order"]["id"],
            {"reason": "Attempt to compensate the same entry twice",
             "expected_project_version": project_version(ctx["project"]["id"])},
            OWNER,
        )

        validate_error(response, ApiErrorId.ERR_LEDGER_ENTRY_ALREADY_REVERSED.value)
        programme = read_project(ctx["project"]["id"])
        rows, meta = read_ledger(ctx["project"]["id"])
        assert programme["committed_cost_cents"] == 3080000000
        assert len(rows) == 3
        assert meta["total_count"] == 3


class TestQueueRetirementConservesTheQueueTotal:
    """96 guests in, 96 guests out, and no double decrement."""

    def _programme_with_two_accepted_segments(self):
        project = open_project()
        ride = register_ride_system(project["id"])
        select_ride(ride["id"], project["id"])
        standard = propose_segment(project["id"], segment_label="Switchback A",
                                   length_meters=120, width_meters=2.4,
                                   routing_type="STANDARD", position_index=1)
        accessible = propose_segment(project["id"], segment_label="Accessible Return",
                                     length_meters=72, width_meters=2.0,
                                     routing_type="ACCESSIBLE", position_index=2)
        ctx = {"project": project, "ride_system": ride}
        ctx["standard_segment"] = accept_segment(standard["id"], project["id"])
        ctx["accessible_segment"] = accept_segment(accessible["id"], project["id"])
        ctx["after_accepts"] = read_project(project["id"])
        return ctx

    def test_retiring_the_accessible_run_subtracts_exactly_what_accepting_it_added(self, api):
        """Retirement is the compensating action: an `ACCEPTED` segment moves to the terminal `RETIRED`, again requiring an unfrozen posture and a matching `expected_project_version`, and its `capacity_guests` is subtracted from `queue_capacity_total_guests`, with the programme's `version` advancing.

        Four queue figures are derived from the accepted set — segments that are
        `PROPOSED` or `RETIRED` contribute to none of them.

        The 443-guest switchback and the 96-guest accessible return made a 539-guest
        queue; retiring the accessible run takes the total back to 443 and the
        accessible share back to 0.00, while the retired row keeps its own 96.

        Design: Difficulty/compensating_invariant/queue_retire_restores_queue_capacity_total_without_drift
        """
        ctx = self._programme_with_two_accepted_segments()

        retired = retire_segment(ctx["accessible_segment"]["id"], ctx["project"]["id"])

        standard = validate_success(
            api.get_queue_segment(ctx["standard_segment"]["id"], DESIGNER))
        programme = read_project(ctx["project"]["id"])
        summary = read_capacity_summary(ctx["project"]["id"])

        assert ctx["after_accepts"]["queue_capacity_total_guests"] == 539
        assert retired["status"] == "RETIRED"
        assert retired["capacity_guests"] == 96
        assert standard["status"] == "ACCEPTED"
        assert standard["capacity_guests"] == 443
        assert programme["queue_capacity_total_guests"] == 443
        assert summary["queue_capacity_total_guests"] == 443
        assert summary["accessible_capacity_guests"] == 0
        assert float(summary["accessible_share_pct"]) == 0.00
        assert float(summary["posted_wait_minutes"]) == 22.5

    def test_a_retired_run_cannot_be_retired_a_second_time(self, api):
        """A segment in the wrong source status for either action is refused with `ERR_QUEUE_SEGMENT_STATE_INVALID`.

        A segment's `capacity_guests` is its `length_meters` multiplied by its
        `width_meters`, divided by the per-guest area for its routing class, and
        rounded down to a whole guest; the area is carried as an exact decimal.

        RETIRED is terminal, so the compensation cannot be applied twice and the
        running total cannot drift below the accepted set it stands for.

        Design: Difficulty/compensating_invariant/queue_retire_restores_queue_capacity_total_without_drift
        """
        ctx = self._programme_with_two_accepted_segments()
        retire_segment(ctx["accessible_segment"]["id"], ctx["project"]["id"])

        response = api.retire_queue_segment(
            ctx["accessible_segment"]["id"],
            {"expected_project_version": project_version(ctx["project"]["id"])},
            OWNER,
        )

        validate_error(response, ApiErrorId.ERR_QUEUE_SEGMENT_STATE_INVALID.value)
        segment = validate_success(
            api.get_queue_segment(ctx["accessible_segment"]["id"], DESIGNER))
        assert segment["status"] == "RETIRED"
        assert segment["capacity_guests"] == 96
        assert read_project(ctx["project"]["id"])["queue_capacity_total_guests"] == 443
