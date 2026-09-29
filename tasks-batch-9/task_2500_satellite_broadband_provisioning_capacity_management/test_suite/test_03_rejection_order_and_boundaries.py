"""Rejection ordering on activation, and the platform's numeric boundaries.

Every test builds its own world from an empty database through the published
endpoints, then exercises exactly one PRD rule.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    activate_subscription,
    cancel_order,
    create_order,
    create_subscriber,
    create_subscription_payload,
    get_beam,
    get_cell,
    get_cell_version,
    get_order,
    get_subscriber,
    prepare_installed_terminal,
    resolve_outage_payload,
    set_clock,
    setup_active_subscription,
    setup_topology,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00Z"


# ───────────────────────────────────────────────────────────────────────────
# Helpers used only by this module. They compose published endpoints only.
# ───────────────────────────────────────────────────────────────────────────

def _pending_activation_subscription(env, subscriber_index, terminal_index):
    """Bring one account to a PENDING_ACTIVATION subscription on env's cell."""
    subscriber = create_subscriber(
        index=subscriber_index, jurisdiction_code=env["cell"]["jurisdiction_code"]
    )
    order = create_order(subscriber["id"], env["cell"]["id"], env["plan"]["id"])
    terminal = prepare_installed_terminal(subscriber["id"], index=terminal_index)
    subscription = activate_subscription(
        order["id"], terminal["id"], service_cell_id=env["cell"]["id"]
    )
    return {
        "subscriber": subscriber,
        "order": order,
        "terminal": terminal,
        "subscription": subscription,
    }


def _activate(api, order_id, terminal_id, cell_id, headers):
    """Raw activation call carrying a freshly read cell version token."""
    return api.create_subscription(
        create_subscription_payload(
            service_order_id=order_id,
            terminal_id=terminal_id,
            expected_service_cell_version=get_cell_version(cell_id),
        ),
        headers,
    )


def _subscription_count_for_order(api, order_id, headers):
    response = api.list_subscriptions(headers, params={"service_order_id": order_id})
    _data, meta = validate_paginated(response)
    return meta["total_count"]


# ───────────────────────────────────────────────────────────────────────────
# Order state (position 10) against beam headroom (position 36)
# ───────────────────────────────────────────────────────────────────────────

class TestOrderStateOutranksBeamHeadroom:
    """Activation naming a CANCELLED order on a beam with no headroom left."""

    def test_cancelled_order_reports_order_state_not_beam_oversubscribed(
        self, api, agent_headers
    ):
        """A CANCELLED order and a projected ratio of 6.0 against a limit of 4.0
        both fail; the order-state check sits at position 10 and beam headroom at
        position 36, so the order-state error is the one returned.

        PRD §2.11: "Checks are evaluated in the following order and the first failure wins."
        PRD §2.11: "10. **Order state** — `order_state` permits the requested action; cancellation requires `RESERVED` or `WAITLISTED`, activation requires `RESERVED`. `ERR_ORDER_STATE_INVALID`, 409. `POST /satellite-broadband/service-orders/{id}/cancel` and `POST /satellite-broadband/subscriptions`."
        PRD §2.11: "36. **Beam headroom** — the projected `oversubscription_ratio` does not exceed the beam's `oversubscription_limit`; exact equality is admitted. `ERR_BEAM_OVERSUBSCRIBED`, 409. `POST /satellite-broadband/subscriptions` and `POST /satellite-broadband/subscriptions/{id}/plan-change`."

        Design: Difficulty/priority_pair_validation_conflict/order_state_conflict_outranks_beam_oversubscription_on_activation
        """
        env = setup_topology(
            max_active_terminals=3,
            forward_capacity_mbps=100,
            oversubscription_limit=4.0,
            committed_rate_mbps=200,
            priority_tier="PRIORITY_1",
            clock=CLOCK_START,
        )
        # Two PENDING_ACTIVATION subscriptions: weighted_sold_mbps 400.0, ratio 4.0.
        _pending_activation_subscription(env, subscriber_index=1, terminal_index=1)
        _pending_activation_subscription(env, subscriber_index=2, terminal_index=2)

        beam_before = get_beam(env["beam"]["id"])
        assert beam_before["oversubscription_ratio"] == pytest.approx(4.0, abs=0.001), (
            "precondition: the beam must sit exactly on its limit before the trigger"
        )

        third = create_subscriber(index=3, jurisdiction_code=env["cell"]["jurisdiction_code"])
        order = create_order(third["id"], env["cell"]["id"], env["plan"]["id"])
        cancel_order(order["id"], cancel_reason="customer deferred install")
        terminal = prepare_installed_terminal(third["id"], index=3)

        response = _activate(
            api, order["id"], terminal["id"], env["cell"]["id"], agent_headers
        )
        validate_error(response, ApiErrorId.ERR_ORDER_STATE_INVALID, 409)

        assert get_order(order["id"])["order_state"] == "CANCELLED", (
            "the refused activation must leave the cancelled order cancelled"
        )
        beam_after = get_beam(env["beam"]["id"])
        assert beam_after["oversubscription_ratio"] == pytest.approx(4.0, abs=0.001), (
            "a refused activation must not move the beam's sold-megabit ratio"
        )
        assert get_cell(env["cell"]["id"])["committed_terminal_count"] == 2, (
            "a refused activation must not commit a cell slot"
        )
        assert _subscription_count_for_order(api, order["id"], agent_headers) == 0, (
            "no subscription may exist for an order whose activation was refused"
        )

    def test_reserved_order_over_the_limit_reports_beam_oversubscribed(
        self, api, agent_headers
    ):
        """With the order-state check satisfied, the same beam arithmetic is what
        rejects: a projected ratio of 6.0 exceeds the limit of 4.0, so position 36
        fires on its own.

        PRD §2.11: "36. **Beam headroom** — the projected `oversubscription_ratio` does not exceed the beam's `oversubscription_limit`; exact equality is admitted. `ERR_BEAM_OVERSUBSCRIBED`, 409. `POST /satellite-broadband/subscriptions` and `POST /satellite-broadband/subscriptions/{id}/plan-change`."
        PRD §3.5: "A projected ratio strictly greater than `oversubscription_limit` is refused; a projected ratio exactly equal to the limit is admitted."

        Design: Difficulty/priority_pair_validation_conflict/order_state_conflict_outranks_beam_oversubscription_on_activation
        """
        env = setup_topology(
            max_active_terminals=3,
            forward_capacity_mbps=100,
            oversubscription_limit=4.0,
            committed_rate_mbps=200,
            priority_tier="PRIORITY_1",
            clock=CLOCK_START,
        )
        _pending_activation_subscription(env, subscriber_index=1, terminal_index=1)
        _pending_activation_subscription(env, subscriber_index=2, terminal_index=2)

        third = create_subscriber(index=3, jurisdiction_code=env["cell"]["jurisdiction_code"])
        order = create_order(third["id"], env["cell"]["id"], env["plan"]["id"])
        assert order["order_state"] == "RESERVED", (
            "precondition: the third order must hold a live reservation"
        )
        terminal = prepare_installed_terminal(third["id"], index=3)

        response = _activate(
            api, order["id"], terminal["id"], env["cell"]["id"], agent_headers
        )
        validate_error(response, ApiErrorId.ERR_BEAM_OVERSUBSCRIBED, 409)

        assert get_order(order["id"])["order_state"] == "RESERVED", (
            "a refused activation must leave the reservation intact"
        )
        assert _subscription_count_for_order(api, order["id"], agent_headers) == 0, (
            "no subscription may exist for an order whose activation was refused"
        )


# ───────────────────────────────────────────────────────────────────────────
# Terminal custody (position 16) against jurisdiction (position 23)
# ───────────────────────────────────────────────────────────────────────────

class TestTerminalCustodyOutranksJurisdiction:
    """Activation binding somebody else's dish for an out-of-jurisdiction account."""

    def test_foreign_terminal_reports_custody_not_jurisdiction(self, api, agent_headers):
        """The activation both binds subscriber A's terminal to subscriber B's order
        and places a US-NV account on a US-CA cell. Custody sits at position 16 and
        jurisdiction at position 23, so the custody error wins despite both being 422.

        PRD §2.11: "Checks are evaluated in the following order and the first failure wins."
        PRD §2.11: "16. **Terminal custody** — at activation the terminal's `subscriber_id` equals the order's `subscriber_id`; at transfer `new_subscriber_id` differs from the terminal's current `subscriber_id`. `ERR_TERMINAL_SUBSCRIBER_MISMATCH`, 422. `POST /satellite-broadband/subscriptions` and `POST /satellite-broadband/terminals/{id}/transfer`."
        PRD §2.11: "23. **Jurisdiction** — at activation the subscriber's `jurisdiction_code` equals the cell's `jurisdiction_code`; at roaming approval a governing licence exists for `target_jurisdiction_code`. `ERR_JURISDICTION_NOT_PERMITTED`, 422. `POST /satellite-broadband/subscriptions` and `POST /satellite-broadband/roaming-authorizations/{id}/decide`."

        Design: Difficulty/priority_pair_validation_conflict/terminal_ownership_mismatch_outranks_jurisdiction_restriction_on_activation
        """
        env = setup_topology(
            max_active_terminals=2,
            jurisdiction_code="US-CA",
            committed_rate_mbps=200,
            priority_tier="PRIORITY_1",
            clock=CLOCK_START,
        )
        owner = create_subscriber(index=1, jurisdiction_code="US-CA")
        owned_terminal = prepare_installed_terminal(owner["id"], index=1)
        assert owned_terminal["terminal_state"] == "INSTALLED", (
            "precondition: the bound terminal must be installed so position 15 passes"
        )

        outsider = create_subscriber(index=2, jurisdiction_code="US-NV")
        order = create_order(outsider["id"], env["cell"]["id"], env["plan"]["id"])
        assert order["order_state"] == "RESERVED", (
            "precondition: the activating order must hold a live reservation"
        )

        response = _activate(
            api, order["id"], owned_terminal["id"], env["cell"]["id"], agent_headers
        )
        validate_error(response, ApiErrorId.ERR_TERMINAL_SUBSCRIBER_MISMATCH, 422)

        assert get_order(order["id"])["order_state"] == "RESERVED", (
            "a refused activation must leave the reservation intact"
        )
        terminal_after = api.get_terminal(owned_terminal["id"], agent_headers)
        terminal_after = validate_success(terminal_after)
        assert terminal_after["subscriber_id"] == owner["id"], (
            "a refused activation must not move terminal custody"
        )
        assert terminal_after["terminal_state"] == "INSTALLED", (
            "a refused activation must not move the terminal's logistics state"
        )
        assert get_cell(env["cell"]["id"])["committed_terminal_count"] == 0, (
            "a refused activation must not commit a cell slot"
        )
        assert _subscription_count_for_order(api, order["id"], agent_headers) == 0, (
            "no subscription may exist for an order whose activation was refused"
        )

    def test_own_terminal_out_of_jurisdiction_reports_jurisdiction(self, api, agent_headers):
        """With custody satisfied — the account activates its own installed terminal —
        the jurisdiction check at position 23 is what rejects a US-NV account on a
        US-CA cell.

        PRD §2.11: "23. **Jurisdiction** — at activation the subscriber's `jurisdiction_code` equals the cell's `jurisdiction_code`; at roaming approval a governing licence exists for `target_jurisdiction_code`. `ERR_JURISDICTION_NOT_PERMITTED`, 422. `POST /satellite-broadband/subscriptions` and `POST /satellite-broadband/roaming-authorizations/{id}/decide`."
        PRD §3.5: "The subscriber's `jurisdiction_code` must equal the activating cell's `jurisdiction_code`, or the attempt is refused with `ERR_JURISDICTION_NOT_PERMITTED`."

        Design: Difficulty/priority_pair_validation_conflict/terminal_ownership_mismatch_outranks_jurisdiction_restriction_on_activation
        """
        env = setup_topology(
            max_active_terminals=2,
            jurisdiction_code="US-CA",
            committed_rate_mbps=200,
            priority_tier="PRIORITY_1",
            clock=CLOCK_START,
        )
        outsider = create_subscriber(index=2, jurisdiction_code="US-NV")
        order = create_order(outsider["id"], env["cell"]["id"], env["plan"]["id"])
        own_terminal = prepare_installed_terminal(outsider["id"], index=2)

        response = _activate(
            api, order["id"], own_terminal["id"], env["cell"]["id"], agent_headers
        )
        validate_error(response, ApiErrorId.ERR_JURISDICTION_NOT_PERMITTED, 422)

        assert get_order(order["id"])["order_state"] == "RESERVED", (
            "a refused activation must leave the reservation intact"
        )
        assert get_cell(env["cell"]["id"])["committed_terminal_count"] == 0, (
            "a refused activation must not commit a cell slot"
        )
        assert _subscription_count_for_order(api, order["id"], agent_headers) == 0, (
            "no subscription may exist for an order whose activation was refused"
        )


# ───────────────────────────────────────────────────────────────────────────
# The beam-headroom boundary: projected ratio exactly on the limit
# ───────────────────────────────────────────────────────────────────────────

class TestProjectedRatioOnTheOversubscriptionLimit:
    """Exact equality with `oversubscription_limit` is admitted, not refused."""

    def test_projected_ratio_exactly_on_the_limit_is_admitted(self, api, agent_headers):
        """One 200 Mbps PRIORITY_1 subscription rides a 100 Mbps beam limited at 4.0,
        so a second activation projects 400.0 / 100 = 4.0 — exactly the limit. The
        activation must succeed and leave the beam CONSTRAINED.

        PRD §3.5: "A projected ratio strictly greater than `oversubscription_limit` is refused; a projected ratio exactly equal to the limit is admitted."
        PRD §2.8: "Dividing that by `forward_capacity_mbps` and rounding half up to 4 decimal places gives `oversubscription_ratio`."
        PRD §2.8: "A beam that is exactly at its limit is `CONSTRAINED`, not `SATURATED`."
        PRD §3.5: "On success a subscription record is created and lands in four independent state dimensions at once: `service_state` `PENDING_ACTIVATION`, `authorization_state` `UNAUTHORIZED`, `priority_state` `PRIORITY` and `disclosure_ack_state` `PENDING_ACK`."
        PRD §3.3: "Otherwise, with no free slots, it is `WAITLIST_ONLY` when the cell's `waitlist_depth` is strictly below 3, and `CLOSED` when `waitlist_depth` has reached 3 or more."

        Design: Difficulty/boundary_precision_check/activation_admitted_when_projected_ratio_lands_exactly_on_oversubscription_limit
        """
        env = setup_topology(
            max_active_terminals=2,
            forward_capacity_mbps=100,
            oversubscription_limit=4.0,
            committed_rate_mbps=200,
            priority_tier="PRIORITY_1",
            clock=CLOCK_START,
        )
        _pending_activation_subscription(env, subscriber_index=1, terminal_index=1)

        second = create_subscriber(index=2, jurisdiction_code=env["cell"]["jurisdiction_code"])
        order = create_order(second["id"], env["cell"]["id"], env["plan"]["id"])
        terminal = prepare_installed_terminal(second["id"], index=2)

        response = _activate(
            api, order["id"], terminal["id"], env["cell"]["id"], agent_headers
        )
        subscription = validate_success(response, 201)

        assert subscription["service_state"] == "PENDING_ACTIVATION"
        assert subscription["authorization_state"] == "UNAUTHORIZED"
        assert subscription["priority_state"] == "PRIORITY"
        assert subscription["disclosure_ack_state"] == "PENDING_ACK"

        beam = get_beam(env["beam"]["id"])
        assert beam["weighted_sold_mbps"] == pytest.approx(400.0, abs=0.001), (
            f"two 200 Mbps PRIORITY_1 subscriptions weigh 400.0, got "
            f"{beam['weighted_sold_mbps']}"
        )
        assert beam["oversubscription_ratio"] == pytest.approx(4.0, abs=0.001), (
            f"400.0 / 100 is 4.0, got {beam['oversubscription_ratio']}"
        )
        assert beam["capacity_state"] == "CONSTRAINED", (
            f"a ratio exactly on the limit bands as CONSTRAINED, got "
            f"{beam['capacity_state']}"
        )

        cell = get_cell(env["cell"]["id"])
        assert cell["committed_terminal_count"] == 2
        assert cell["free_slot_count"] == 0
        assert cell["availability_state"] == "WAITLIST_ONLY", (
            f"no free slot and a waitlist depth below 3 advertises WAITLIST_ONLY, got "
            f"{cell['availability_state']}"
        )

    @pytest.mark.parametrize(
        "oversubscription_limit,expect_admitted",
        [
            (4.01, True),   # projected 4.0 sits just below the limit
            (3.99, False),  # projected 4.0 sits just above the limit
        ],
        ids=["just_below_the_limit", "just_above_the_limit"],
    )
    def test_projected_ratio_either_side_of_the_limit(
        self, api, agent_headers, oversubscription_limit, expect_admitted
    ):
        """The same projected ratio of 4.0 is admitted under a limit of 4.01 and
        refused under a limit of 3.99, bracketing the exact-equality case.

        PRD §3.5: "A projected ratio strictly greater than `oversubscription_limit` is refused; a projected ratio exactly equal to the limit is admitted."
        PRD §3.5: "The projected ratio is the beam's current `weighted_sold_mbps` plus that added contribution, divided by the beam's `forward_capacity_mbps`, rounded half up to 4 decimal places."

        Design: Difficulty/boundary_precision_check/activation_admitted_when_projected_ratio_lands_exactly_on_oversubscription_limit
        """
        env = setup_topology(
            max_active_terminals=2,
            forward_capacity_mbps=100,
            oversubscription_limit=oversubscription_limit,
            committed_rate_mbps=200,
            priority_tier="PRIORITY_1",
            clock=CLOCK_START,
        )
        _pending_activation_subscription(env, subscriber_index=1, terminal_index=1)

        second = create_subscriber(index=2, jurisdiction_code=env["cell"]["jurisdiction_code"])
        order = create_order(second["id"], env["cell"]["id"], env["plan"]["id"])
        terminal = prepare_installed_terminal(second["id"], index=2)

        response = _activate(
            api, order["id"], terminal["id"], env["cell"]["id"], agent_headers
        )

        if expect_admitted:
            validate_success(response, 201)
            beam = get_beam(env["beam"]["id"])
            assert beam["oversubscription_ratio"] == pytest.approx(4.0, abs=0.001), (
                f"400.0 / 100 is 4.0, got {beam['oversubscription_ratio']}"
            )
        else:
            validate_error(response, ApiErrorId.ERR_BEAM_OVERSUBSCRIBED, 409)
            beam = get_beam(env["beam"]["id"])
            assert beam["oversubscription_ratio"] == pytest.approx(2.0, abs=0.001), (
                f"a refused activation leaves the ratio at 2.0, got "
                f"{beam['oversubscription_ratio']}"
            )
            assert _subscription_count_for_order(api, order["id"], agent_headers) == 0, (
                "no subscription may exist for an order whose activation was refused"
            )


# ───────────────────────────────────────────────────────────────────────────
# The promotion routine's empty-pool edge
# ───────────────────────────────────────────────────────────────────────────

class TestCancelWithEmptyWaitlist:
    """Cancelling a reservation with nobody waiting simply leaves the slot free."""

    def test_cancel_with_empty_waitlist_promotes_nothing(self, api, agent_headers):
        """The only order on a one-slot cell is cancelled while `waitlist_depth` is 0,
        so the promotion routine finds no eligible order: nothing is promoted, no error
        is raised, and the released slot settles as one free slot.

        PRD §3.3: "Cancelling from `RESERVED` moves the order `RESERVED → CANCELLED`, clears `reservation_expires_at` back to empty, drops the cell's `reserved_slot_count` by 1 to release the slot, and then runs the promotion routine on that cell, so a cancellation typically hands the slot straight to the top-ranked waitlisted order and moves that order's subscriber from `WAITLISTED` to `PROSPECT`."
        PRD §3.3: "If no eligible order exists, nothing happens: no promotion occurs, no error is raised, and the freed slot simply stays free."
        PRD §3.3: "The free slot figure is the cell's `max_active_terminals` less the number of subscriptions occupying slots less the number of orders in `RESERVED`, floored at 0 so it is never negative."
        PRD §3.3: "Otherwise it is `AVAILABLE` when the free slot figure is at least 1."

        Design: Difficulty/boundary_precision_check/cancel_with_empty_waitlist_promotes_nothing_and_leaves_the_slot_free
        """
        env = setup_topology(
            max_active_terminals=1,
            committed_rate_mbps=200,
            priority_tier="PRIORITY_1",
            clock=CLOCK_START,
        )
        subscriber = create_subscriber(index=1, jurisdiction_code=env["cell"]["jurisdiction_code"])
        order = create_order(subscriber["id"], env["cell"]["id"], env["plan"]["id"])
        assert order["order_state"] == "RESERVED", (
            "precondition: the only order on the cell must hold the single slot"
        )
        assert get_cell(env["cell"]["id"])["waitlist_depth"] == 0, (
            "precondition: the promotion pool must be empty"
        )

        response = api.cancel_service_order(
            order["id"], {"cancel_reason": "customer withdrew"}, agent_headers
        )
        cancelled = validate_success(response, 200)

        assert cancelled["order_state"] == "CANCELLED"
        assert cancelled["cancel_reason"] == "customer withdrew"
        assert not cancelled.get("reservation_expires_at"), (
            f"cancellation clears reservation_expires_at back to empty, got "
            f"{cancelled.get('reservation_expires_at')!r}"
        )
        assert not cancelled.get("promoted_at"), (
            f"no promotion ran, so promoted_at must stay empty, got "
            f"{cancelled.get('promoted_at')!r}"
        )

        cell = get_cell(env["cell"]["id"])
        assert cell["reserved_slot_count"] == 0, "the cancelled hold releases its slot"
        assert cell["committed_terminal_count"] == 0
        assert cell["free_slot_count"] == 1, (
            f"1 - 0 - 0 leaves one free slot, got {cell['free_slot_count']}"
        )
        assert cell["waitlist_depth"] == 0, "no order was ever waitlisted on this cell"
        assert cell["availability_state"] == "AVAILABLE", (
            f"one free slot advertises AVAILABLE, got {cell['availability_state']}"
        )
        assert get_subscriber(subscriber["id"])["account_state"] == "PROSPECT", (
            "the cancelling subscriber stays a prospect"
        )

    def test_cancel_with_one_waitlisted_order_promotes_it(self, api, agent_headers):
        """The non-empty counterpart of the same edge: with `waitlist_depth` at 1 the
        released slot is handed to the waiting order rather than left free.

        PRD §3.3: "Cancelling from `RESERVED` moves the order `RESERVED → CANCELLED`, clears `reservation_expires_at` back to empty, drops the cell's `reserved_slot_count` by 1 to release the slot, and then runs the promotion routine on that cell, so a cancellation typically hands the slot straight to the top-ranked waitlisted order and moves that order's subscriber from `WAITLISTED` to `PROSPECT`."
        PRD §3.3: "While the cell has at least one free slot and at least one eligible order remains, the top-ranked order is promoted `WAITLISTED → RESERVED`, its `reservation_expires_at` is set to the logical clock's current instant plus 72 hours, its `promoted_at` is stamped with that same instant, and its subscriber's `account_state` moves from `WAITLISTED` back to `PROSPECT`."

        Design: Difficulty/boundary_precision_check/cancel_with_empty_waitlist_promotes_nothing_and_leaves_the_slot_free
        """
        env = setup_topology(
            max_active_terminals=1,
            committed_rate_mbps=200,
            priority_tier="PRIORITY_1",
            clock=CLOCK_START,
        )
        holder = create_subscriber(index=1, jurisdiction_code=env["cell"]["jurisdiction_code"])
        held_order = create_order(holder["id"], env["cell"]["id"], env["plan"]["id"])
        assert held_order["order_state"] == "RESERVED", (
            "precondition: the first order must take the single slot"
        )

        waiter = create_subscriber(index=2, jurisdiction_code=env["cell"]["jurisdiction_code"])
        waiting_order = create_order(waiter["id"], env["cell"]["id"], env["plan"]["id"])
        assert waiting_order["order_state"] == "WAITLISTED", (
            "precondition: the second order must land on the waitlist"
        )
        assert get_cell(env["cell"]["id"])["waitlist_depth"] == 1, (
            "precondition: the promotion pool must hold exactly one order"
        )

        cancel_order(held_order["id"], cancel_reason="customer withdrew")

        promoted = get_order(waiting_order["id"])
        assert promoted["order_state"] == "RESERVED", (
            f"the waiting order must be promoted to RESERVED, got {promoted['order_state']}"
        )
        assert promoted["promoted_at"], "a promoted order carries a promoted_at stamp"
        assert promoted["reservation_expires_at"].startswith("2026-08-04T00:00:00"), (
            f"the clock stood at {CLOCK_START}, so the new hold expires 72 hours later, "
            f"got {promoted['reservation_expires_at']!r}"
        )
        assert get_subscriber(waiter["id"])["account_state"] == "PROSPECT", (
            "a promoted order's subscriber returns from WAITLISTED to PROSPECT"
        )

        cell = get_cell(env["cell"]["id"])
        assert cell["reserved_slot_count"] == 1, "the promoted order takes the freed slot"
        assert cell["free_slot_count"] == 0
        assert cell["waitlist_depth"] == 0, "the waitlist emptied when its order was promoted"


# ───────────────────────────────────────────────────────────────────────────
# The service-level outage floor: exactly thirty whole minutes
# ───────────────────────────────────────────────────────────────────────────

class TestOutageCreditEligibilityFloor:
    """`credit_eligible` turns true at exactly 30 whole outage minutes."""

    def test_exactly_thirty_minutes_is_eligible_and_drafts_one_credit(
        self, api, agent_headers, netops_headers
    ):
        """A 30-minute EQUIPMENT_FAILURE / FULL_OUTAGE lands exactly on the floor, so
        the event is credit eligible and drafts one credit at 9900 x 30 / 43200 x 1.0
        = 6.875 cents, rounded half up to 7 cents.

        PRD §3.8: "Resolution moves the event `OPEN → RESOLVED` and computes `outage_minutes` as the number of whole minutes between `started_at` and `ended_at`, discarding any partial minute."
        PRD §3.8: "It then computes `credit_eligible`, which is true only when the `cause` is anything other than `PLANNED_MAINTENANCE` **and** `outage_minutes` is at least 30 — a shorter blip is beneath the service-level floor."
        PRD §3.8: "Take the plan's `monthly_fee_cents`, multiply it by the event's `outage_minutes` divided by a nominal billing month of 43,200 minutes — thirty days of minutes — then multiply by the multiplier."
        PRD §3.8: "Each drafted credit's `provisional_credit_cents` is computed by the provisional rule below, and each affected subscriber's `pending_credit_cents` is increased by that amount."
        PRD §3.8: "The event's `generated_credit_count` records how many credits were created."

        Design: Difficulty/boundary_precision_check/outage_credit_eligibility_triggers_at_exactly_thirty_outage_minutes
        """
        env = setup_active_subscription(
            max_active_terminals=1,
            monthly_fee_cents=9900,
            committed_rate_mbps=200,
            priority_tier="PRIORITY_1",
            clock=CLOCK_START,
        )
        assert env["subscription"]["service_state"] == "ACTIVE", (
            "precondition: only an ACTIVE, authorised subscription is affected"
        )

        set_clock("2026-08-02T01:00:00Z")
        event = validate_success(
            api.create_outage_event(
                {
                    "beam_id": env["beam"]["id"],
                    "cause": "EQUIPMENT_FAILURE",
                    "severity": "FULL_OUTAGE",
                    "started_at": "2026-08-02T00:00:00Z",
                },
                netops_headers,
            ),
            201,
        )

        resolved = validate_success(
            api.resolve_outage_event(
                event["id"], resolve_outage_payload(ended_at="2026-08-02T00:30:00Z"),
                netops_headers,
            ),
            200,
        )

        assert resolved["event_state"] == "RESOLVED"
        assert resolved["outage_minutes"] == 30, (
            f"00:00:00 to 00:30:00 is 30 whole minutes, got {resolved['outage_minutes']}"
        )
        assert resolved["credit_eligible"] is True, (
            "30 minutes meets the service-level floor of at least 30 minutes"
        )
        assert resolved["generated_credit_count"] == 1, (
            f"one affected subscription drafts one credit, got "
            f"{resolved['generated_credit_count']}"
        )

        credits, meta = validate_paginated(
            api.list_outage_credits(agent_headers, params={"outage_event_id": event["id"]})
        )
        assert meta["total_count"] == 1, (
            f"exactly one credit row was drafted, got {meta['total_count']}"
        )
        credit = credits[0]
        assert credit["credit_state"] == "DRAFT"
        assert credit["subscription_id"] == env["subscription"]["id"]
        assert credit["provisional_credit_cents"] == 7, (
            f"9900 * 30 / 43200 * 1.0 is 6.875 cents, rounded half up to 7, got "
            f"{credit['provisional_credit_cents']}"
        )
        assert not credit.get("final_credit_cents"), (
            "a DRAFT credit carries no final amount yet"
        )

        subscriber = get_subscriber(env["subscriber"]["id"])
        assert subscriber["pending_credit_cents"] == 7, (
            f"the drafted provisional amount enters pending_credit_cents, got "
            f"{subscriber['pending_credit_cents']}"
        )
        assert subscriber["credit_balance_cents"] == 0, (
            "nothing has been approved, so the balance is untouched"
        )

    @pytest.mark.parametrize(
        "ended_at,expected_minutes,expect_eligible,expected_credit_count",
        [
            ("2026-08-02T00:29:00Z", 29, False, 0),
            ("2026-08-02T00:31:00Z", 31, True, 1),
        ],
        ids=["one_minute_below_the_floor", "one_minute_above_the_floor"],
    )
    def test_either_side_of_the_thirty_minute_floor(
        self,
        api,
        agent_headers,
        netops_headers,
        ended_at,
        expected_minutes,
        expect_eligible,
        expected_credit_count,
    ):
        """29 whole minutes falls beneath the floor — ineligible, with no credit rows
        drafted at all — while 31 whole minutes clears it, bracketing the exact
        30-minute case.

        PRD §3.8: "It then computes `credit_eligible`, which is true only when the `cause` is anything other than `PLANNED_MAINTENANCE` **and** `outage_minutes` is at least 30 — a shorter blip is beneath the service-level floor."
        PRD §3.8: "Credit rows are then drafted, and the gate on drafting is subtly different from the gate on eligibility: **rows are created whenever `outage_minutes` is at least 30, regardless of cause.**"
        PRD §3.8: "When `outage_minutes` is below 30, no credit rows are created at all and `generated_credit_count` stays 0."

        Design: Difficulty/boundary_precision_check/outage_credit_eligibility_triggers_at_exactly_thirty_outage_minutes
        """
        env = setup_active_subscription(
            max_active_terminals=1,
            monthly_fee_cents=9900,
            committed_rate_mbps=200,
            priority_tier="PRIORITY_1",
            clock=CLOCK_START,
        )

        set_clock("2026-08-02T01:00:00Z")
        event = validate_success(
            api.create_outage_event(
                {
                    "beam_id": env["beam"]["id"],
                    "cause": "EQUIPMENT_FAILURE",
                    "severity": "FULL_OUTAGE",
                    "started_at": "2026-08-02T00:00:00Z",
                },
                netops_headers,
            ),
            201,
        )

        resolved = validate_success(
            api.resolve_outage_event(
                event["id"], resolve_outage_payload(ended_at=ended_at), netops_headers
            ),
            200,
        )

        assert resolved["outage_minutes"] == expected_minutes, (
            f"expected {expected_minutes} whole minutes, got {resolved['outage_minutes']}"
        )
        assert resolved["credit_eligible"] is expect_eligible, (
            f"eligibility at {expected_minutes} minutes should be {expect_eligible}, got "
            f"{resolved['credit_eligible']}"
        )
        assert resolved["generated_credit_count"] == expected_credit_count, (
            f"expected {expected_credit_count} drafted credits, got "
            f"{resolved['generated_credit_count']}"
        )

        _credits, meta = validate_paginated(
            api.list_outage_credits(agent_headers, params={"outage_event_id": event["id"]})
        )
        assert meta["total_count"] == expected_credit_count, (
            f"expected {expected_credit_count} credit rows for the event, got "
            f"{meta['total_count']}"
        )
