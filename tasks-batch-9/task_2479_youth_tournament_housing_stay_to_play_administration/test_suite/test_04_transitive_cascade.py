"""Single writes whose consequences travel four links.

One confirmation walks registration → block → contract → tournament; one
clearing remittance walks invoice → bookings → block → contract.
"""

from test_helpers import (
    HOUSING_MANAGER_HEADERS,
    assertions,
    factories as f,
    fixtures as fx,
    validate_success,
)

HM = HOUSING_MANAGER_HEADERS


def _ready_to_confirm_env(api) -> fx.Env:
    """A five-room booking on the event's only five-room block, waiting to be
    confirmed so that the whole confirm chain fires at once."""
    env = fx.executed_contract_env(
        api,
        block_overrides={"block_size_rooms": 5},
        contract_overrides={"attrition_threshold_pct": 0.8},
    )
    fx.add_team(env)
    fx.add_registration(env)
    fx.add_booking(env, rooms_requested=5)
    env.booking = fx.submit_rooming_list(
        env,
        entries=[f.rooming_list_entry(index + 1, occupant_count=3) for index in range(5)],
    )
    return env


def _released_block_awaiting_payment_env(api) -> fx.Env:
    """An issued invoice over a released block, one remittance away from
    settling the block and closing the contract."""
    env = fx.executed_contract_env(api)
    fx.add_team(env)
    fx.add_registration(env)
    fx.add_booking(env, rooms_requested=6)
    env.booking = fx.submit_rooming_list(
        env,
        entries=[f.rooming_list_entry(index + 1, occupant_count=2) for index in range(6)],
    )
    env.booking = fx.confirm_booking(env)
    fx.close_booking_window(env)

    fx.set_clock(api, "2026-08-26T00:00:00Z")
    env.block = validate_success(api.release_room_block(env.block_id, HM))

    fx.actualize(env, 18)
    fx.create_invoice(env)
    fx.issue_invoice(env)
    return env


class TestConfirmChainDepthFour:
    """One confirmation, four links of recomputation."""

    def test_confirming_rehouses_the_registration_and_restricts_the_block(self, api):
        """The first two links: the team reads compliant against its pooled floor
        of four, and the block fills to a utilization of 1.0 and flips
        `RESTRICTED`.

        PRD §3.4: "The first link recomputes the registration's
        `committed_rooms` and re-derives its `status` per the compliance rules of
        §3.3, refreshing `compliance_evaluated_at`; the registration's own
        `updated_at` is refreshed and its `version` incremented by 1."

        PRD §3.3: "Otherwise, if `committed_rooms` is greater than or equal to
        `effective_required_rooms`, the registration is `HOUSING_COMPLIANT`; the
        comparison is inclusive, so a team that has committed exactly its
        effective requirement is compliant."

        PRD §3.4: "While a block's `status` is `OPEN` or `RESTRICTED`, it reads
        `RESTRICTED` whenever `utilization_pct` is at or above 0.90 — ninety
        percent of the held rooms committed — and `OPEN` otherwise."

        Design: Difficulty/transitive_cascade/cascade_confirm_depth_four_booking_to_housing_pressure
        """
        env = _ready_to_confirm_env(api)

        booking = validate_success(api.confirm_booking(env.booking_id, HM))

        assert booking["booking_status"] == "CONFIRMED"
        registration = env.refresh_registration()
        assert registration["committed_rooms"] == 5
        assert registration["effective_required_rooms"] == 4
        assert registration["status"] == "HOUSING_COMPLIANT"
        block = env.refresh_block()
        assert block["rooms_committed"] == 5
        assert block["rooms_available"] == 0
        assert block["utilization_pct"] == 1.0
        assert block["status"] == "RESTRICTED"
        assertions.assert_block_inventory_conserved(block)

    def test_confirming_carries_sold_out_up_to_the_event_pressure_indicator(self, api):
        """The third and fourth links: the contract reads `SOLD_OUT` and the
        tournament, whose only executed contract that is, reads `CONSTRAINED`.

        PRD §3.2: "If every live block is `RESTRICTED`, it is `SOLD_OUT`."

        PRD §3.2: "A tournament's `housing_pressure` then aggregates upward:
        `executed_contract_count` is the number of its contracts whose `status`
        is `EXECUTED` or `CLOSED`, and `sold_out_contract_count` is the number of
        those same contracts whose `block_posture` is `SOLD_OUT`."

        PRD §3.4: "The fourth link recomputes the tournament's
        `sold_out_contract_count` and its `housing_pressure`, which may move from
        `NORMAL` to `CONSTRAINED`."

        Design: Difficulty/transitive_cascade/cascade_confirm_depth_four_booking_to_housing_pressure
        """
        env = _ready_to_confirm_env(api)

        validate_success(api.confirm_booking(env.booking_id, HM))

        assert env.refresh_contract()["block_posture"] == "SOLD_OUT"
        tournament = env.refresh_tournament()
        assert tournament["executed_contract_count"] == 1
        assert tournament["sold_out_contract_count"] == 1
        assert tournament["housing_pressure"] == "CONSTRAINED"


class TestRemitChainDepthFour:
    """One clearing remittance, four links of recomputation."""

    def test_clearing_the_invoice_collects_the_booking_and_settles_the_block(self, api):
        """The first three links: the invoice reads `PAID`, the booking's money
        axis reaches `COLLECTED`, and the released block reaches `SETTLED` with
        its fourteen unsold rooms still recorded.

        PRD §3.8: "The first link sets `collected_cents` to `total_due_cents` and
        `outstanding_cents` to 0."

        PRD §3.8: "The third link, caused by the second, re-evaluates the
        `RELEASED → SETTLED` transition of each affected block: a released block
        settles once at least one booking on it is not `CANCELLED` and every one
        of its non-cancelled bookings has a `rebate_status` of `COLLECTED`,
        `SHORT_PAID` or `WRITTEN_OFF`."

        PRD §2.12: "Once the block's `status` is `RELEASED` or `SETTLED`, its
        `rooms_committed` and `rooms_released_unsold` sum to exactly
        `block_size_rooms`, and its `rooms_available` is 0."

        Design: Difficulty/transitive_cascade/cascade_remit_depth_four_invoice_to_contract_closed
        """
        env = _released_block_awaiting_payment_env(api)
        assert env.invoice["total_due_cents"] == 16200

        invoice = validate_success(
            api.remit_invoice(env.invoice_id, f.remit_payload(16200), env.hotel_headers)
        )

        assert invoice["status"] == "PAID"
        assert invoice["collected_cents"] == 16200
        assert invoice["outstanding_cents"] == 0
        booking = env.refresh_booking()
        assert booking["rebate_status"] == "COLLECTED"
        assert booking["booking_status"] == "CHECKED_OUT"
        block = env.refresh_block()
        assert block["status"] == "SETTLED"
        assert block["rooms_committed"] == 6
        assert block["rooms_released_unsold"] == 14
        assert block["rooms_available"] == 0
        assertions.assert_block_inventory_conserved(block)

    def test_the_contract_closes_but_the_event_will_not_settle_without_a_payout(
        self, api
    ):
        """The fourth link closes the contract once its only block has settled,
        and the event stays at `RECONCILING` because no distribution exists yet.

        PRD §3.8: "The fourth link, caused by the third, re-evaluates the
        contract's own `EXECUTED → CLOSED` transition, which fires once every
        block of the contract has settled."

        PRD §3.8: "Evaluated only while `posture` is `RECONCILING`, the event
        moves to `SETTLED` when every rebate invoice reachable through any of its
        hotel contracts has a `status` of `PAID` or `WRITTEN_OFF`, **and** at
        least one revenue distribution exists for the event, **and** every one of
        those distributions has a `status` of `PAID`."

        Design: Difficulty/transitive_cascade/cascade_remit_depth_four_invoice_to_contract_closed
        """
        env = _released_block_awaiting_payment_env(api)

        validate_success(
            api.remit_invoice(env.invoice_id, f.remit_payload(16200), env.hotel_headers)
        )

        assert env.refresh_contract()["status"] == "CLOSED"
        assert env.refresh_tournament()["posture"] == "RECONCILING"
