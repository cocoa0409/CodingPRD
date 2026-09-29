"""Lifecycles that are not a straight line.

A hotel contract can revisit `DRAFT` without bound, counting each return; a
booking carries two independent state axes that advance without disturbing each
other.
"""

from test_helpers import (
    HOUSING_MANAGER_HEADERS,
    NegotiationAction,
    assertions,
    factories as f,
    fixtures as fx,
    get_success_data,
    validate_success,
)

HM = HOUSING_MANAGER_HEADERS


def _twice_revised_env(api) -> fx.Env:
    """A contract that has bounced back to `DRAFT` twice and is sitting at
    `NEGOTIATING` for the third time."""
    env = fx.draft_contract_env(api)
    fx.add_block(env, block_size_rooms=10)
    for action in (
        NegotiationAction.SUBMIT,
        NegotiationAction.REVISE,
        NegotiationAction.SUBMIT,
        NegotiationAction.REVISE,
        NegotiationAction.SUBMIT,
    ):
        headers = HM if action is NegotiationAction.SUBMIT else env.hotel_headers
        env.contract = get_success_data(
            api.negotiate_contract(
                env.contract_id, f.negotiation_payload(action.value), headers
            )
        )
    return env


def _restated_actualization_env(api) -> fx.Env:
    """A booking actualized at 12 room nights and then restated to 15, on an
    invoice that has been issued and awaits its remittance."""
    env = fx.executed_contract_env(api, block_overrides={"block_size_rooms": 5})
    fx.add_team(env)
    fx.add_registration(env)
    fx.add_booking(env, rooms_requested=5)
    fx.submit_rooming_list(
        env,
        entries=[f.rooming_list_entry(index + 1, occupant_count=3) for index in range(5)],
    )
    env.booking = fx.confirm_booking(env)
    fx.close_booking_window(env)
    fx.actualize(env, 12)
    fx.actualize(env, 15)
    fx.create_invoice(env)
    fx.issue_invoice(env)
    return env


class TestContractNegotiationRevisionCycle:
    """`DRAFT → NEGOTIATING → DRAFT` may repeat, and the counter records it."""

    def test_revision_round_counts_each_return_to_draft_before_execution(self, api):
        """Two `REVISE` actions leave `revision_round` at 2, and the contract
        still executes from the third `NEGOTIATING` visit.

        PRD §3.2: "A `REVISE` action returns the contract to `DRAFT` and
        increments `revision_round` by 1; this cycle may repeat without bound, so
        a heavily negotiated contract may pass through `DRAFT → NEGOTIATING →
        DRAFT` many times, with `revision_round` counting exactly how many times
        it has done so."

        Design: Difficulty/non_linear_state_machine/hotel_contract_negotiation_revision_cycle
        """
        env = _twice_revised_env(api)
        assert env.contract["status"] == "NEGOTIATING"
        assert env.contract["revision_round"] == 2

        contract = validate_success(
            api.negotiate_contract(
                env.contract_id,
                f.negotiation_payload(NegotiationAction.COUNTERSIGN.value),
                env.hotel_headers,
            )
        )

        assert contract["status"] == "EXECUTED"
        assert contract["revision_round"] == 2
        assertions.assert_versioned_record(contract)

    def test_countersigning_stamps_the_hotel_and_lifts_the_event_counters(self, api):
        """The countersignature records the acting hotel and takes the event's
        executed count to 1 while the single open block keeps pressure `NORMAL`.

        PRD §3.2: "A `COUNTERSIGN` action moves the contract `NEGOTIATING →
        EXECUTED`, again requiring the tournament to be `OPEN`; it records
        `countersigned_by_hotel_id` as the acting `X-User-ID`, then recomputes
        the tournament's `executed_contract_count` and `sold_out_contract_count`
        and re-derives its `housing_pressure`."

        PRD §3.2: "If the contract has no live blocks at all, `block_posture` is
        `AVAILABLE`."

        PRD §3.2: "`housing_pressure` reads `CONSTRAINED` when
        `executed_contract_count` is at least 1 and `sold_out_contract_count`
        equals `executed_contract_count`; in every other case, including the case
        of no executed contracts at all, it reads `NORMAL`."

        Design: Difficulty/non_linear_state_machine/hotel_contract_negotiation_revision_cycle
        """
        env = _twice_revised_env(api)

        contract = validate_success(
            api.negotiate_contract(
                env.contract_id,
                f.negotiation_payload(NegotiationAction.COUNTERSIGN.value),
                env.hotel_headers,
            )
        )

        assert contract["countersigned_by_hotel_id"] == env.hotel_id
        assert contract["block_posture"] == "AVAILABLE"
        tournament = env.refresh_tournament()
        assert tournament["executed_contract_count"] == 1
        assert tournament["sold_out_contract_count"] == 0
        assert tournament["housing_pressure"] == "NORMAL"
        assert env.refresh_block()["status"] == "OPEN"


class TestBookingParallelAxesIndependence:
    """`booking_status` and `rebate_status` advance without disturbing each
    other."""

    def test_the_money_axis_reaches_collected_while_the_reservation_axis_stays_put(
        self, api
    ):
        """Remitting the invoice in full moves the booking to `COLLECTED` and
        leaves `booking_status` frozen at `CHECKED_OUT`.

        PRD §3.7: "The **money axis**, `rebate_status`, runs `NOT_DUE → ACCRUED →
        INVOICED` and then to one of `COLLECTED`, `SHORT_PAID` or `WRITTEN_OFF`,
        and every one of its transitions is system-driven and leaves
        `booking_status` untouched."

        PRD §3.8: "The second link, caused by the first, moves every booking
        whose block belongs to this contract and whose `rebate_status` is
        `INVOICED` from `INVOICED` to `COLLECTED`, again without touching
        `booking_status`."

        Design: Difficulty/non_linear_state_machine/booking_parallel_axes_independence
        """
        env = _restated_actualization_env(api)
        assert env.invoice["total_due_cents"] == 13500

        invoice = validate_success(
            api.remit_invoice(env.invoice_id, f.remit_payload(13500), env.hotel_headers)
        )

        assert invoice["status"] == "PAID"
        assert invoice["collected_cents"] == 13500
        assert invoice["outstanding_cents"] == 0
        assertions.assert_rebate_ledger_conserved(invoice)
        booking = env.refresh_booking()
        assert booking["rebate_status"] == "COLLECTED"
        assert booking["booking_status"] == "CHECKED_OUT"
        assert env.refresh_tournament()["posture"] == "RECONCILING"

    def test_a_later_report_restates_the_room_nights_instead_of_adding_to_them(
        self, api
    ):
        """A second report of 15 replaces the first report's 12 rather than
        summing to 27, and the reservation axis does not move a second time.

        PRD §3.7: "The booking's `actualized_room_nights` is always taken from
        the report with the **greatest** `sequence_no`, and is 0 while no report
        exists."

        PRD §3.7: "Each subsequent report is an `ACCRUED → ACCRUED` self-loop:
        `actualized_room_nights` is re-derived from the greatest `sequence_no`
        and `rebate_accrued_cents` is recomputed, while `booking_status` stays
        frozen at `CHECKED_OUT`."

        PRD §3.7: "Under `PER_ROOM_NIGHT_FLAT`, the line is
        `actualized_room_nights` multiplied by the contract's
        `rebate_flat_cents_per_room_night`."

        Design: Difficulty/non_linear_state_machine/booking_parallel_axes_independence
        """
        env = _restated_actualization_env(api)

        booking = env.refresh_booking()

        assert booking["actualized_room_nights"] == 15
        assert booking["rebate_accrued_cents"] == 13500
        assert booking["booking_status"] == "CHECKED_OUT"
        assert booking["rebate_status"] == "INVOICED"
        assert env.invoice["invoiced_room_nights"] == 15
