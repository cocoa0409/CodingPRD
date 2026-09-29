"""Counters that must add up again after value moves out and back.

The escrow ledger's funded / balance / disbursed identity across a payment and
its rescission, and a segment's committed crew released by completion and by
cancellation.
"""

from test_helpers import assert_escrow_conservation, assert_timestamp_equals
from test_helpers import fixtures as fx


class TestEscrowLedgerConservation:
    """funded always equals balance plus disbursed, at every step."""

    def test_rescission_returns_the_ledger_to_its_pre_payment_shape(self, api):
        """PRD §3.8: "Rescission zeroes `paid_amount_cents`, restores the project's
        escrow balance and reduces its disbursed total by the rescinded amount, and
        moves the tract `PAID → RESCINDED`."

        Design: Difficulty/compensating_invariant/escrow_conservation_restored_by_payment_rescission
        """
        ctx = fx.setup_issued_certificate(api)
        fx.setup_paid_tract(api, ctx)
        fx.rescind_payment(api, ctx, "tract1")

        project = fx.read_project(api, ctx)
        assert project["escrow_funded_cents"] == 600000000, (
            "Rescission returns value to the balance without unfunding the deposit, got "
            f"{project['escrow_funded_cents']}"
        )
        assert project["escrow_balance_cents"] == 600000000, (
            "The whole deposit is available again, got "
            f"{project['escrow_balance_cents']}"
        )
        assert project["escrow_disbursed_cents"] == 0, (
            f"Nothing remains disbursed, got {project['escrow_disbursed_cents']}"
        )
        assert_escrow_conservation(project)
        assert project["easement_committed_cents"] == 4163406, (
            "Commitment tracks the AGREED tract, not the cash, got "
            f"{project['easement_committed_cents']}"
        )

        tract = fx.read_tract(api, ctx["tract1"])
        assert tract["payment_status"] == "RESCINDED", (
            f"The payment dimension moves PAID -> RESCINDED, got {tract['payment_status']}"
        )
        assert tract["paid_amount_cents"] == 0, (
            f"The paid figure is zeroed, got {tract['paid_amount_cents']}"
        )
        assert tract["acquisition_status"] == "AGREED", (
            "The acquisition dimension is untouched by the cash movement, got "
            f"{tract['acquisition_status']}"
        )

    def test_the_ledger_balances_after_every_step_of_the_payment_cycle(self, api):
        """PRD §2.9: "A conservation invariant holds after every single operation:
        the funded total always equals the undisbursed balance plus the disbursed
        total."

        Design: Difficulty/compensating_invariant/escrow_conservation_restored_by_payment_rescission
        """
        ctx = fx.setup_issued_certificate(api)
        fx.setup_agreed_tract(api, ctx)

        project = fx.read_project(api, ctx)
        assert_escrow_conservation(project)
        assert project["escrow_funded_cents"] == 0, (
            f"A project starts with an empty ledger, got {project['escrow_funded_cents']}"
        )

        fx.fund_escrow(api, ctx, amount_cents=600_000_000)
        project = fx.read_project(api, ctx)
        assert_escrow_conservation(project)
        assert project["escrow_balance_cents"] == 600000000, (
            "The deposit lands wholly in the balance, got "
            f"{project['escrow_balance_cents']}"
        )

        fx.pay_tract(api, ctx, "tract1")
        project = fx.read_project(api, ctx)
        assert_escrow_conservation(project)
        assert project["escrow_balance_cents"] == 595836594, (
            "600000000 less the 4163406 disbursement is 595836594 cents, got "
            f"{project['escrow_balance_cents']}"
        )
        assert project["escrow_disbursed_cents"] == 4163406, (
            f"The disbursed total picks up the payment, got "
            f"{project['escrow_disbursed_cents']}"
        )

        fx.rescind_payment(api, ctx, "tract1")
        project = fx.read_project(api, ctx)
        assert_escrow_conservation(project)
        assert project["escrow_balance_cents"] == 600000000, (
            f"The rescission moves the value back, got {project['escrow_balance_cents']}"
        )

        tract = fx.pay_tract(api, ctx, "tract1", payment_reference="WIRE-2")
        assert tract["payment_status"] == "PAID", (
            f"A rescinded tract can be paid again, got {tract['payment_status']}"
        )
        project = fx.read_project(api, ctx)
        assert_escrow_conservation(project)
        assert project["escrow_balance_cents"] == 595836594, (
            "The second payment debits the ledger afresh, got "
            f"{project['escrow_balance_cents']}"
        )
        assert project["escrow_disbursed_cents"] == 4163406, (
            "The cycle ends where the first payment left it, got "
            f"{project['escrow_disbursed_cents']}"
        )
        assert project["easement_committed_cents"] == 4163406, (
            "The commitment roll-up never moved throughout the cycle, got "
            f"{project['easement_committed_cents']}"
        )


class TestCrewSlotConservation:
    """Crew slots taken by a schedule are given back by completion and cancellation."""

    def test_completion_and_cancellation_return_every_committed_crew_slot(self, api):
        """PRD §3.9: "once every activity on the segment has reached `COMPLETE` or
        `CANCELLED` and at least one of them reached `COMPLETE`, the segment moves
        `ACTIVE → COMPLETE` with its committed crew count set to zero."

        Design: Difficulty/compensating_invariant/crew_slot_conservation_across_completion_and_cancellation
        """
        ctx = fx.setup_construction_ready(api)
        fx.setup_started_activity(api, ctx)
        fx.schedule_activity(
            api, ctx, key="act4", crew_count=3, activity_kind="FOUNDATION",
            window_start_at="2027-08-05T00:00:00Z",
            window_end_at="2027-08-10T00:00:00Z",
        )
        fx.set_clock(api, "2027-08-12T00:00:00Z")
        fx.complete_activity(api, ctx, "act1")
        fx.cancel_activity(api, ctx, "act4")

        segment = fx.read_segment(api, ctx["seg1"])
        assert segment["committed_crew_count"] == 0, (
            "Every crew slot the two activities took has been released, got "
            f"{segment['committed_crew_count']}"
        )
        assert segment["construction_state"] == "COMPLETE", (
            "One activity completed and the queue is empty, so the segment bubbles "
            f"ACTIVE -> COMPLETE, got {segment['construction_state']}"
        )
        completed = fx.read_activity(api, ctx["act1"])
        assert completed["status"] == "COMPLETE", (
            f"The worked activity is COMPLETE, got {completed['status']}"
        )
        assert_timestamp_equals(
            completed["completed_at"], "2027-08-12T00:00:00Z", "completed_at"
        )
        assert fx.read_activity(api, ctx["act4"])["status"] == "CANCELLED", (
            "The unstarted activity is CANCELLED"
        )
        certificate = fx.read_certificate(api, ctx["cert"])
        assert certificate["posture"] == "ACTIVE", (
            f"Releasing crew does not disturb the posture, got {certificate['posture']}"
        )
        assert certificate["status"] == "ISSUED", (
            "The certificate is still ISSUED until closeout, got "
            f"{certificate['status']}"
        )

    def test_the_crew_counter_steps_down_one_release_at_a_time(self, api):
        """PRD §3.9: "**Completion** — with an optional `completion_note` — moves an
        activity `IN_PROGRESS → COMPLETE`, stamps `completed_at`, and reduces the
        segment's `committed_crew_count` by that activity's crew count."

        Design: Difficulty/compensating_invariant/crew_slot_conservation_across_completion_and_cancellation
        """
        ctx = fx.setup_construction_ready(api)
        fx.setup_started_activity(api, ctx)
        fx.schedule_activity(
            api, ctx, key="act4", crew_count=3, activity_kind="FOUNDATION",
            window_start_at="2027-08-05T00:00:00Z",
            window_end_at="2027-08-10T00:00:00Z",
        )

        segment = fx.read_segment(api, ctx["seg1"])
        assert segment["committed_crew_count"] == 9, (
            f"Six working plus three scheduled is nine, got "
            f"{segment['committed_crew_count']}"
        )

        fx.set_clock(api, "2027-08-12T00:00:00Z")
        fx.complete_activity(api, ctx, "act1")
        segment = fx.read_segment(api, ctx["seg1"])
        assert segment["committed_crew_count"] == 3, (
            f"Completion gives back exactly its own six, got "
            f"{segment['committed_crew_count']}"
        )
        assert segment["construction_state"] == "ACTIVE", (
            "A scheduled activity still sits on the segment, so it does not bubble to "
            f"COMPLETE yet, got {segment['construction_state']}"
        )

        fx.cancel_activity(api, ctx, "act4")
        segment = fx.read_segment(api, ctx["seg1"])
        assert segment["committed_crew_count"] == 0, (
            f"The cancellation releases the last three, got "
            f"{segment['committed_crew_count']}"
        )
        assert segment["construction_state"] == "COMPLETE", (
            "The cancellation is the event that empties the queue, got "
            f"{segment['construction_state']}"
        )
