"""Lifecycle transitions across the contract, site, device, ticket and removal machines.

Every suite here drives one machine from a state the platform itself created,
then reconciles the transition's declared effects: the state that results, the
version bump that pays for it, the cross-entity cascade it fires, and the
rejection that guards the transitions which do not exist.
"""

import datetime

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_contract,
    add_cost_tier,
    advance_device_to,
    api_client,
    assert_device_dimensions,
    assert_fields,
    billing_period_payload,
    create_contract,
    create_device,
    create_site,
    create_ticket,
    device_payload,
    dispatch_payload,
    dispatch_ticket,
    fetch_contract,
    fetch_device,
    fetch_removal_order,
    fetch_service_ticket,
    fetch_site,
    fetch_technician,
    get_success_data,
    list_orders_for_device,
    make_customer_admin_headers,
    make_field_technician_headers,
    make_fleet_ops_headers,
    meter_read_payload,
    resolve_ticket_payload,
    secure_release_config_payload,
    service_contract_payload,
    set_clock,
    setup_dispatched_ticket,
    setup_print_environment,
    setup_removal_order,
    site_payload,
    submit_automated_read,
    suspend_payload,
    validate_error,
    validate_success,
)

AM = TEST_USERS["account_manager_headers"]
BA = TEST_USERS["billing_analyst_headers"]
OPS = TEST_USERS["fleet_ops_headers"]

MONO_RATE = 9_375
PERIOD_START = "2026-08-01T00:00:00Z"
PERIOD_END = "2026-09-01T00:00:00Z"

# The wind-down day: the order is raised on 10 August for collection on 15 August.
REMOVAL_REQUEST_CLOCK = "2026-08-10T08:00:00Z"
COLLECTION_INSTANT = "2026-08-15T09:00:00Z"

# The consumables day: both readings cover 1-5 August and are captured on the 5th.
SUPPLY_CLOCK = "2026-08-05T00:00:00Z"

# One service day: the ticket opens at 08:00 and the onsite window runs 13:00-15:00.
TICKET_OPENED_AT = "2026-08-10T08:00:00Z"
RESPOND_BY_STANDARD = "2026-08-11T08:00:00Z"
WINDOW_START = "2026-08-10T13:00:00Z"
WINDOW_END = "2026-08-10T15:00:00Z"
SECOND_WINDOW_START = "2026-08-10T16:00:00Z"
SECOND_WINDOW_END = "2026-08-10T17:00:00Z"
ARRIVAL_CLOCK = "2026-08-10T13:00:00Z"


def _parse_instant(value):
    """Parse an ISO 8601 UTC instant, tolerating either Z or a numeric offset."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_instant(data, field, expected):
    """Assert a stamped instant equals ``expected``, whatever its rendering precision."""
    assert field in data, f"response is missing field '{field}': {data}"
    assert _parse_instant(data[field]) == _parse_instant(expected), (
        f"expected {field} to be the instant {expected}, got {data[field]!r}"
    )


class TestDeclaredInitialStates:
    """Freshly created records sit at the entry state of their own machine."""

    def test_contract_site_and_device_are_created_at_their_entry_states(self, api):
        """A brand new contract, site and asset each land on their declared first state.

        PRD: "Four further inputs are optional and default when omitted: `response_sla_hours_critical` defaults to 4 hours and must lie between 1 and 72; `response_sla_hours_standard` defaults to a full day at 24 hours and must lie between 1 and 168; `labor_rate_cents_per_hour` defaults to 9,500 cents — $95 an hour — and must be zero or greater; and `early_termination_fee_cents` defaults to 0 and must be zero or greater. A newly created contract's `status` is `DRAFT`."
        PRD: "A new site starts with `secure_release_state` at `UNCONFIGURED`, `release_method` at `NONE` and `open_toner_units` at 0."
        PRD: "A freshly recorded asset lands at `lifecycle_state` `ASSESSED` and `supply_state` `SUPPLY_OK`, with `toner_level_pct` at 100."

        Design: Corner/state_machines/initial_state_new_records_start_in_their_declared_initial_states
        """
        contract = validate_success(
            api.create_service_contract(service_contract_payload(customer_name="Larkin Mfg"), AM),
            201,
        )
        assert_fields(contract, status="DRAFT")

        site = validate_success(
            api.create_site(site_payload(contract["id"], name="Plant 1"), AM),
            201,
        )
        assert_fields(
            site,
            secure_release_state="UNCONFIGURED",
            release_method="NONE",
            open_toner_units=0,
        )

        device = validate_success(
            api.create_device(device_payload(contract["id"], site["id"]), OPS),
            201,
        )
        assert_fields(device, toner_level_pct=100)
        assert_device_dimensions(device, "ASSESSED", "SUPPLY_OK")

    def test_new_billing_period_opens_with_zeroed_counters_and_null_totals(self, api):
        """A period begins OPEN, unswept, exception-free and unpriced.

        PRD: "A new period has `status` `OPEN`, a `sweep_run_count` of 0, an `exception_open_count` of 0, and both `provisional_total_cents` and `final_total_cents` null."

        Design: Corner/state_machines/initial_state_new_records_start_in_their_declared_initial_states
        """
        contract = create_contract(customer_name="Larkin Mfg")

        period = validate_success(
            api.create_billing_period(
                billing_period_payload(
                    contract["id"], period_start=PERIOD_START, period_end=PERIOD_END
                ),
                BA,
            ),
            201,
        )

        assert_fields(
            period,
            status="OPEN",
            sweep_run_count=0,
            exception_open_count=0,
            provisional_total_cents=None,
            final_total_cents=None,
        )


def _draft_contract_with_one_mono_asset(mono_tiers):
    """A DRAFT contract, one site and one mono-only asset left at ASSESSED."""
    contract = create_contract(customer_name="Larkin Mfg")
    for tier_index, from_page, to_page, rate in mono_tiers:
        add_cost_tier(
            contract["id"],
            page_class="MONO",
            tier_index=tier_index,
            from_page=from_page,
            to_page=to_page,
            rate_micro_dollars_per_page=rate,
        )
    site = create_site(contract["id"], name="Plant 1")
    device = create_device(contract["id"], site["id"], color_capable=False)
    return contract, site, device


class TestContractActivation:
    """`DRAFT → ACTIVE` and the rate-card precondition that guards it."""

    def test_activation_succeeds_once_the_mono_ladder_opens_at_page_one(self, api):
        """A complete mono-only rate card unlocks the contract without touching the fleet.

        PRD: "Activation moves the contract `DRAFT → ACTIVE`. It requires a `MONO` rate-card row at `tier_index` 1 whose `from_page` is 1, and — only when at least one device of the contract has `color_capable` set true — an equivalent `COLOR` row at `tier_index` 1 with `from_page` 1."
        PRD: "On success the contract's `version` increases by 1."
        PRD: "`active_device_count` is the number of that contract's devices whose `lifecycle_state` is `PLACED`, `NETWORKED`, `ACTIVE` or `SERVICE_HOLD` — assessed-but-unplaced, retrieved and removed assets are excluded."

        Design: Corner/state_machines/valid_transition_contract_draft_to_active_once_the_rate_card_is_complete
        """
        contract, _site, device = _draft_contract_with_one_mono_asset(((1, 1, None, MONO_RATE),))
        assert contract["version"] == 1

        activated = validate_success(api.activate_service_contract(contract["id"], AM), 200)

        assert_fields(activated, status="ACTIVE", version=2, active_device_count=0)
        assert_device_dimensions(fetch_device(device["id"]), "ASSESSED", "SUPPLY_OK")

    def test_activation_is_rejected_when_the_mono_ladder_never_opens_at_page_one(self, api):
        """A ladder whose only row sits at tier 2 fails the rate-card completeness test.

        PRD: "A contract that fails either test is rejected with `ERR_RATE_CARD_INCOMPLETE`; a contract that is not in `DRAFT` when activation is attempted is rejected with `ERR_CONTRACT_INVALID_STATE`."
        PRD: "It requires a `MONO` rate-card row at `tier_index` 1 whose `from_page` is 1, and — only when at least one device of the contract has `color_capable` set true — an equivalent `COLOR` row at `tier_index` 1 with `from_page` 1."

        Design: Corner/state_machines/precondition_enforcement_activation_without_a_mono_tier_one_row_is_rejected
        """
        contract, _site, _device = _draft_contract_with_one_mono_asset(((2, 501, None, MONO_RATE),))

        response = api.activate_service_contract(contract["id"], AM)

        validate_error(response, ApiErrorId.ERR_RATE_CARD_INCOMPLETE)
        assert_fields(fetch_contract(contract["id"]), status="DRAFT", version=1)


class TestDeviceTransitionsThatDoNotExist:
    """An asset already in billable service cannot re-enter the intake walk."""

    @pytest.mark.parametrize("move", ["place", "network_integrate"])
    def test_intake_moves_are_refused_on_an_already_active_asset(self, api, move):
        """Placement and network integration have no edge leaving `ACTIVE`.

        PRD: "Attempting any of these three moves from the wrong `lifecycle_state` — placing an already-active asset, activating an asset that is still merely `ASSESSED` — reports `ERR_DEVICE_INVALID_STATE`."
        PRD: "The `lifecycle_state` dimension tracks placement and decommissioning and takes one of `ASSESSED`, `PLACED`, `NETWORKED`, `ACTIVE`, `SERVICE_HOLD`, `RETRIEVED` or `REMOVED`, starting at `ASSESSED` and terminating at `REMOVED`."

        Design: Corner/state_machines/invalid_transitions_place_and_network_integration_on_an_active_device_are_rejected
        """
        env = setup_print_environment(site={"name": "Plant 1"}, device_stage="ACTIVE")
        device_id = env["device_id"]
        tech_headers = make_field_technician_headers(env["technician_id"])
        assert_device_dimensions(fetch_device(device_id), "ACTIVE", "SUPPLY_OK")

        if move == "place":
            response = api.place_device(device_id, tech_headers)
        else:
            response = api.network_integrate_device(device_id, tech_headers)

        validate_error(response, ApiErrorId.ERR_DEVICE_INVALID_STATE)
        assert_device_dimensions(fetch_device(device_id), "ACTIVE", "SUPPLY_OK")
        assert_fields(fetch_contract(env["contract_id"]), active_device_count=1)


class TestTicketCancellationIsNotRepeatable:
    """Cancel is a transition, not an idempotent instruction."""

    def test_second_cancel_of_the_same_ticket_is_refused(self, api):
        """The first cancel moves OPEN to CANCELLED; the identical replay is rejected.

        PRD: "A `CustomerAdmin` — again constrained to the site that owns the device, on pain of `ERR_SITE_OWNERSHIP_REQUIRED` — may cancel a ticket whose `status` is `OPEN`, `DISPATCHED` or `PARTS_HOLD`, performing `OPEN → CANCELLED`, `DISPATCHED → CANCELLED` or `PARTS_HOLD → CANCELLED` with identical effects in all three cases; a ticket already `ONSITE`, `RESOLVED` or `CANCELLED` reports `ERR_TICKET_INVALID_STATE`."
        PRD: "Both `RESOLVED` and `CANCELLED` are terminal ticket states."

        Design: Corner/state_machines/idempotency_second_cancel_of_the_same_ticket_is_rejected
        """
        env = setup_print_environment(site={"name": "Plant 1"}, clock=TICKET_OPENED_AT)
        site_headers = make_customer_admin_headers(env["site_id"])
        ticket = create_ticket(env["device_id"], env["site_id"])
        assert_fields(ticket, status="OPEN", version=1)

        cancelled = validate_success(api.cancel_service_ticket(ticket["id"], site_headers), 200)
        assert_fields(cancelled, status="CANCELLED", version=2)

        replay = api.cancel_service_ticket(ticket["id"], site_headers)

        validate_error(replay, ApiErrorId.ERR_TICKET_INVALID_STATE)
        assert_fields(fetch_service_ticket(ticket["id"]), status="CANCELLED", version=2)
        assert_device_dimensions(fetch_device(env["device_id"]), "ACTIVE", "SUPPLY_OK")


def _resolved_ticket_environment(labor_hours=2):
    """A dispatched ticket walked to ONSITE at 13:00 and resolved for `labor_hours`."""
    env = setup_dispatched_ticket(
        site={"name": "Plant 1"},
        clock=TICKET_OPENED_AT,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )
    tech_headers = make_field_technician_headers(env["technician_id"])
    set_clock(ARRIVAL_CLOCK)
    get_success_data(api_client.arrive_onsite(env["ticket_id"], tech_headers))
    env["ticket"] = get_success_data(
        api_client.resolve_service_ticket(
            env["ticket_id"], resolve_ticket_payload(labor_hours), tech_headers
        )
    )
    env["tech_headers"] = tech_headers
    env["site_headers"] = make_customer_admin_headers(env["site_id"])
    return env


class TestResolvedTicketIsLockedDown:
    """`RESOLVED` is terminal: no further ticket transition may leave it."""

    def test_resolution_writes_the_terminal_service_numbers(self):
        """Two labour hours on a BASIC contract, resolved inside the response window.

        PRD: "Second, `labor_cents`: exactly 0 whenever the contract's `included_service_scope` is `FULL`, and otherwise the reported `labor_hours` **rounded up to a whole number of hours first** and then multiplied by the contract's `labor_rate_cents_per_hour` — the rounding happens before the multiplication, never after."
        PRD: "First, `hours_late`: the number of hours between `respond_by` and `responded_at`, rounded up to a whole hour, floored at zero so that a ticket resolved on or before its deadline records exactly 0."

        Design: Corner/state_machines/terminal_state_lockdown_resolved_ticket_rejects_resolve_arrive_and_cancel
        """
        env = _resolved_ticket_environment(labor_hours=2)

        assert_fields(
            env["ticket"],
            status="RESOLVED",
            labor_hours=2,
            labor_cents=19_000,
            hours_late=0,
            sla_credit_cents=0,
        )

    @pytest.mark.parametrize("move", ["resolve", "arrive_onsite", "cancel"])
    def test_every_further_transition_is_refused_from_resolved(self, api, move):
        """Resolve, arrive and cancel all have no edge leaving the terminal state.

        PRD: "Both `RESOLVED` and `CANCELLED` are terminal ticket states."
        PRD: "Attempting resolution on a ticket that never reached `ONSITE` reports `ERR_TICKET_INVALID_STATE`."
        PRD: "The target resource is in a state from which the requested transition exists — otherwise `ERR_CONTRACT_INVALID_STATE`, `ERR_DEVICE_INVALID_STATE`, `ERR_READ_INVALID_STATE`, `ERR_PERIOD_INVALID_STATE`, `ERR_ORDER_INVALID_STATE`, `ERR_TICKET_INVALID_STATE`, `ERR_REVIEW_ALREADY_APPROVED` or `ERR_REMOVAL_INVALID_STATE` (all 409)."

        Design: Corner/state_machines/terminal_state_lockdown_resolved_ticket_rejects_resolve_arrive_and_cancel
        """
        env = _resolved_ticket_environment(labor_hours=2)
        ticket_id = env["ticket_id"]
        resting_version = env["ticket"]["version"]

        if move == "resolve":
            response = api.resolve_service_ticket(
                ticket_id, resolve_ticket_payload(1.0), env["tech_headers"]
            )
        elif move == "arrive_onsite":
            response = api.arrive_onsite(ticket_id, env["tech_headers"])
        else:
            response = api.cancel_service_ticket(ticket_id, env["site_headers"])

        validate_error(response, ApiErrorId.ERR_TICKET_INVALID_STATE)
        assert_fields(fetch_service_ticket(ticket_id), status="RESOLVED", version=resting_version)


class TestDispatchSideEffects:
    """One dispatch call writes the window, the assignment and the device hold."""

    def test_dispatch_stamps_the_window_and_holds_the_device(self, api):
        """`OPEN → DISPATCHED` reserves the slot, loads the technician and freezes the asset.

        PRD: "Successful dispatch performs `OPEN → DISPATCHED`, writes `assigned_technician_id` from the supplied `technician_id`, recomputes the technician's `open_dispatch_count` upward, increments the ticket's `version`, and cascades onto the hardware: when the ticket's device has a `lifecycle_state` of `ACTIVE`, that device moves `ACTIVE → SERVICE_HOLD` and its own `version` increments."
        PRD: "A `FleetOpsController` dispatches the ticket by naming a `technician_id` and reserving an onsite slot with `window_start` and `window_end`, which are written onto the ticket."
        PRD: "Each technician exposes a derived `open_dispatch_count`: the number of tickets assigned to them whose `status` is `DISPATCHED`, `PARTS_HOLD` or `ONSITE`."

        Design: Corner/state_machines/side_effect_execution_dispatch_stamps_the_window_and_holds_the_device
        """
        env = setup_print_environment(site={"name": "Plant 1"}, clock=TICKET_OPENED_AT)
        ticket = create_ticket(env["device_id"], env["site_id"], severity="STANDARD")
        assert_fields(fetch_technician(env["technician_id"]), open_dispatch_count=0)

        dispatched = validate_success(
            api.dispatch_service_ticket(
                ticket["id"],
                dispatch_payload(env["technician_id"], WINDOW_START, WINDOW_END),
                OPS,
            ),
            200,
        )

        assert_fields(
            dispatched,
            status="DISPATCHED",
            assigned_technician_id=env["technician_id"],
            parts_hold_hours=0,
            version=2,
        )
        _assert_instant(dispatched, "window_start", WINDOW_START)
        _assert_instant(dispatched, "window_end", WINDOW_END)
        _assert_instant(dispatched, "opened_at", TICKET_OPENED_AT)
        _assert_instant(dispatched, "respond_by", RESPOND_BY_STANDARD)
        assert_fields(fetch_technician(env["technician_id"]), open_dispatch_count=1)
        assert_device_dimensions(fetch_device(env["device_id"]), "SERVICE_HOLD", "SUPPLY_OK")

    def test_ticket_creation_stamps_the_standard_response_deadline(self):
        """A STANDARD ticket's deadline is the open instant plus the contract's 24 hours.

        PRD: "The new ticket has `status` `OPEN`, a null `assigned_technician_id`, a null `window_start` and `window_end` until a dispatch reserves them, a null `hold_started_at` and `responded_at`, a `parts_hold_hours`, `hours_late`, `labor_hours`, `labor_cents` and `sla_credit_cents` of 0, `opened_at` stamped from the logical clock, and — this is the response-time commitment made concrete — a `respond_by` deadline computed as `opened_at` plus the contract's `response_sla_hours_critical` hours when `severity` is `CRITICAL`, or plus the contract's `response_sla_hours_standard` hours when `severity` is `STANDARD`."

        Design: Corner/state_machines/side_effect_execution_dispatch_stamps_the_window_and_holds_the_device
        """
        env = setup_print_environment(site={"name": "Plant 1"}, clock=TICKET_OPENED_AT)

        ticket = create_ticket(env["device_id"], env["site_id"], severity="STANDARD")

        assert_fields(
            ticket,
            status="OPEN",
            assigned_technician_id=None,
            window_start=None,
            window_end=None,
            parts_hold_hours=0,
        )
        _assert_instant(ticket, "opened_at", TICKET_OPENED_AT)
        _assert_instant(ticket, "respond_by", RESPOND_BY_STANDARD)


class TestResolutionReturnsTheDeviceToService:
    """Resolution is the other half of the `ACTIVE → SERVICE_HOLD → ACTIVE` cycle."""

    def test_resolve_returns_the_held_device_and_unloads_the_technician(self, api):
        """`ONSITE → RESOLVED` releases the hold and clears the technician's open work.

        PRD: "Resolution performs `ONSITE → RESOLVED`, stamps `responded_at` from the logical clock, recomputes the technician's `open_dispatch_count` downward, increments the ticket's `version`, and cascades onto the hardware: when the device's `lifecycle_state` is `SERVICE_HOLD` it returns `SERVICE_HOLD → ACTIVE` with its own `version` increment, making `ACTIVE → SERVICE_HOLD → ACTIVE` a cycle that repeats once per dispatched ticket."
        PRD: "Second, `labor_cents`: exactly 0 whenever the contract's `included_service_scope` is `FULL`, and otherwise the reported `labor_hours` **rounded up to a whole number of hours first** and then multiplied by the contract's `labor_rate_cents_per_hour` — the rounding happens before the multiplication, never after."

        Design: Corner/state_machines/cross_entity_resolve_returns_the_device_from_service_hold_to_active
        """
        env = setup_dispatched_ticket(
            site={"name": "Plant 1"},
            clock=TICKET_OPENED_AT,
            window_start=WINDOW_START,
            window_end=WINDOW_END,
        )
        assert_device_dimensions(fetch_device(env["device_id"]), "SERVICE_HOLD", "SUPPLY_OK")
        set_clock(ARRIVAL_CLOCK)
        get_success_data(api.arrive_onsite(env["ticket_id"], env["tech_headers"]))

        resolved = validate_success(
            api.resolve_service_ticket(
                env["ticket_id"], resolve_ticket_payload(2.4), env["tech_headers"]
            ),
            200,
        )

        assert_fields(
            resolved,
            status="RESOLVED",
            hours_late=0,
            labor_cents=28_500,
            sla_credit_cents=0,
        )
        _assert_instant(resolved, "responded_at", ARRIVAL_CLOCK)
        assert_device_dimensions(fetch_device(env["device_id"]), "ACTIVE", "SUPPLY_OK")
        assert_fields(fetch_technician(env["technician_id"]), open_dispatch_count=0)


class TestCancellationReleasesTheHoldConditionally:
    """Two dispatched tickets on one device: only the last cancel frees the hardware."""

    @staticmethod
    def _two_dispatched_tickets_on_one_device():
        env = setup_print_environment(site={"name": "Plant 1"}, clock=TICKET_OPENED_AT)
        first = create_ticket(env["device_id"], env["site_id"])
        second = create_ticket(env["device_id"], env["site_id"])
        env["first_ticket"] = dispatch_ticket(
            first["id"], env["technician_id"], WINDOW_START, WINDOW_END
        )
        env["second_ticket"] = dispatch_ticket(
            second["id"], env["technician_id"], SECOND_WINDOW_START, SECOND_WINDOW_END
        )
        return env

    def test_first_cancel_leaves_the_device_on_service_hold(self, api):
        """One ticket still DISPATCHED means the compensating device move is withheld.

        PRD: "Cancellation retains `assigned_technician_id` for audit rather than nulling it, recomputes the technician's `open_dispatch_count` downward, increments the ticket's `version`, and compensates the hardware: when the device sits in `SERVICE_HOLD` **and** no other ticket of that device remains in `DISPATCHED`, `PARTS_HOLD` or `ONSITE`, the device returns `SERVICE_HOLD → ACTIVE`."
        PRD: "Each technician exposes a derived `open_dispatch_count`: the number of tickets assigned to them whose `status` is `DISPATCHED`, `PARTS_HOLD` or `ONSITE`."

        Design: Corner/state_machines/conditional_cascade_cancel_releases_service_hold_only_when_no_other_ticket_is_open
        """
        env = self._two_dispatched_tickets_on_one_device()
        assert_device_dimensions(fetch_device(env["device_id"]), "SERVICE_HOLD", "SUPPLY_OK")
        assert_fields(fetch_technician(env["technician_id"]), open_dispatch_count=2)

        cancelled = validate_success(
            api.cancel_service_ticket(env["first_ticket"]["id"], env["site_headers"]), 200
        )

        assert_fields(
            cancelled,
            status="CANCELLED",
            assigned_technician_id=env["technician_id"],
        )
        assert_device_dimensions(fetch_device(env["device_id"]), "SERVICE_HOLD", "SUPPLY_OK")
        assert_fields(fetch_technician(env["technician_id"]), open_dispatch_count=1)

    def test_second_cancel_returns_the_device_to_active(self, api):
        """With no in-flight ticket left, cancellation walks the device back to service.

        PRD: "Cancellation retains `assigned_technician_id` for audit rather than nulling it, recomputes the technician's `open_dispatch_count` downward, increments the ticket's `version`, and compensates the hardware: when the device sits in `SERVICE_HOLD` **and** no other ticket of that device remains in `DISPATCHED`, `PARTS_HOLD` or `ONSITE`, the device returns `SERVICE_HOLD → ACTIVE`."
        PRD: "No locker stock is consumed or returned by a cancellation, because stock only ever moves at arrival."

        Design: Corner/state_machines/conditional_cascade_cancel_releases_service_hold_only_when_no_other_ticket_is_open
        """
        env = self._two_dispatched_tickets_on_one_device()
        get_success_data(api.cancel_service_ticket(env["first_ticket"]["id"], env["site_headers"]))

        cancelled = validate_success(
            api.cancel_service_ticket(env["second_ticket"]["id"], env["site_headers"]), 200
        )

        assert_fields(
            cancelled,
            status="CANCELLED",
            assigned_technician_id=env["technician_id"],
        )
        assert_device_dimensions(fetch_device(env["device_id"]), "ACTIVE", "SUPPLY_OK")
        assert_fields(fetch_technician(env["technician_id"]), open_dispatch_count=0)


class TestCollectionRetrievesOnlyCoveredDevices:
    """A removal order reaches down to the in-service fleet and no further."""

    @staticmethod
    def _mixed_fleet_with_scheduled_removal():
        """Three assets — ACTIVE, PLACED and still ASSESSED — under a scheduled removal."""
        env = setup_print_environment(
            site={"name": "Plant 1"},
            devices=3,
            device_stage="ASSESSED",
            clock=REMOVAL_REQUEST_CLOCK,
        )
        first, second, third = env["device_ids"]
        advance_device_to(first, env["technician_id"], stage="ACTIVE")
        advance_device_to(second, env["technician_id"], stage="PLACED")
        env["order"] = setup_removal_order(
            env["contract_id"], COLLECTION_INSTANT, stage="SCHEDULED"
        )
        env["in_service_device_ids"] = [first, second]
        env["untouched_device_id"] = third
        return env

    def test_removal_request_stamps_only_the_in_service_assets(self):
        """Coverage is decided at request time from the four in-service lifecycle states.

        PRD: "It simultaneously drives the contract `ACTIVE → TERMINATING` with a contract `version` increment, and stamps `removal_order_id` onto every device of that contract whose `lifecycle_state` is `PLACED`, `NETWORKED`, `ACTIVE` or `SERVICE_HOLD`."
        PRD: "Those stamped devices are the order's **covered devices**, and `device_count` is derived as the number of devices carrying that order's identifier."

        Design: Corner/state_machines/cascade_down_collect_retrieves_only_the_covered_in_service_devices
        """
        env = self._mixed_fleet_with_scheduled_removal()
        order_id = env["order"]["id"]

        assert_fields(env["order"], status="SCHEDULED", device_count=2)
        assert_fields(fetch_contract(env["contract_id"]), status="TERMINATING")
        for device_id in env["in_service_device_ids"]:
            assert_fields(fetch_device(device_id), removal_order_id=order_id)
        assert_fields(fetch_device(env["untouched_device_id"]), removal_order_id=None)

    def test_collection_retrieves_the_covered_devices_and_leaves_the_rest(self, api):
        """`SCHEDULED → COLLECTED` walks both covered assets to RETRIEVED only.

        PRD: "Collection transitions every covered device to `RETRIEVED` — `PLACED → RETRIEVED`, `NETWORKED → RETRIEVED`, `ACTIVE → RETRIEVED` or `SERVICE_HOLD → RETRIEVED`, each incrementing that device's `version`, with the `SERVICE_HOLD` case additionally requiring that no in-flight ticket remains for that device — recomputes the order's `device_count`, and increments the order's `version`."
        PRD: "A `FieldTechnician` then records physical collection, driving `SCHEDULED → COLLECTED`."

        Design: Corner/state_machines/cascade_down_collect_retrieves_only_the_covered_in_service_devices
        """
        env = self._mixed_fleet_with_scheduled_removal()
        order_id = env["order"]["id"]
        set_clock(COLLECTION_INSTANT)

        collected = validate_success(
            api.collect_removal_order(order_id, env["tech_headers"]), 200
        )

        assert_fields(collected, status="COLLECTED", device_count=2)
        for device_id in env["in_service_device_ids"]:
            device = fetch_device(device_id)
            assert_device_dimensions(device, "RETRIEVED", "SUPPLY_OK")
            assert_fields(device, removal_order_id=order_id)
        untouched = fetch_device(env["untouched_device_id"])
        assert_device_dimensions(untouched, "ASSESSED", "SUPPLY_OK")
        assert_fields(untouched, removal_order_id=None)
        assert_fields(fetch_removal_order(order_id), status="COLLECTED", device_count=2)


class TestSecureReleaseProbeCycle:
    """`CONFIGURED → FAILED → CONFIGURED` is a routine, repeatable path."""

    def test_repeated_probes_cycle_the_site_and_never_block_each_other(self, api):
        """Five probes walk PENDING_VALIDATION, FAILED, CONFIGURED, FAILED and CONFIGURED again.

        PRD: "It writes `release_method`, writes `network_vlan_tag` only when one was supplied, sets `secure_release_state` to `PENDING_VALIDATION`, and increments the site's `version` by 1."
        PRD: "It writes both `release_method` and `network_vlan_tag` onto the site, sets `secure_release_state` to `CONFIGURED`, and increments the site's `version` by 1."
        PRD: "It also cascades onto the fleet: every device at that site whose `lifecycle_state` is `NETWORKED` has `secure_release_enrolled` set to true and its own `version` incremented by 1."
        PRD: "`probe_result` of `FAIL` drives the site to `FAILED` regardless of which method was named. It sets `secure_release_state` to `FAILED` and increments the site's `version` by 1."
        PRD: "Because re-validation after a network change is a routine event, `CONFIGURED → FAILED → CONFIGURED` and `UNCONFIGURED → PENDING_VALIDATION` followed later by a passing probe are all permitted paths."

        Design: Corner/state_machines/cyclic_site_release_config_cycles_configured_failed_configured
        """
        env = setup_print_environment(
            site={"name": "Plant 1"}, probe_result=None, device_stage="NETWORKED"
        )
        site_id = env["site_id"]
        site_headers = make_customer_admin_headers(site_id)
        assert_fields(fetch_site(site_id), secure_release_state="UNCONFIGURED", version=1)

        deferred = validate_success(
            api.configure_secure_release(
                site_id,
                secure_release_config_payload(release_method="PIN", probe_result="DEFERRED"),
                site_headers,
            ),
            200,
        )
        assert_fields(
            deferred, secure_release_state="PENDING_VALIDATION", release_method="PIN", version=2
        )

        failed = validate_success(
            api.configure_secure_release(
                site_id,
                secure_release_config_payload(release_method="PIN", probe_result="FAIL"),
                site_headers,
            ),
            200,
        )
        assert_fields(failed, secure_release_state="FAILED", version=3)

        configured = validate_success(
            api.configure_secure_release(
                site_id,
                secure_release_config_payload(
                    release_method="PIN", probe_result="PASS", network_vlan_tag=2002
                ),
                site_headers,
            ),
            200,
        )
        assert_fields(
            configured,
            secure_release_state="CONFIGURED",
            release_method="PIN",
            network_vlan_tag=2002,
            version=4,
        )
        assert_fields(fetch_device(env["device_id"]), secure_release_enrolled=True)

        refailed = validate_success(
            api.configure_secure_release(
                site_id,
                secure_release_config_payload(release_method="PIN", probe_result="FAIL"),
                site_headers,
            ),
            200,
        )
        assert_fields(refailed, secure_release_state="FAILED", version=5)

        reconfigured = validate_success(
            api.configure_secure_release(
                site_id,
                secure_release_config_payload(
                    release_method="PIN", probe_result="PASS", network_vlan_tag=2002
                ),
                site_headers,
            ),
            200,
        )
        assert_fields(
            reconfigured,
            secure_release_state="CONFIGURED",
            release_method="PIN",
            network_vlan_tag=2002,
            version=6,
        )
        assert_device_dimensions(fetch_device(env["device_id"]), "NETWORKED", "SUPPLY_OK")
        assert_fields(fetch_device(env["device_id"]), secure_release_enrolled=True)


class TestContractSuspensionCycle:
    """`ACTIVE → SUSPENDED → ACTIVE` twice over, on a fleet-free contract."""

    def test_two_suspension_cycles_accumulate_the_counter_and_retain_the_last_reason(self, api):
        """Each pass adds one to `suspension_count`, and the reason survives the resume.

        PRD: "The move `ACTIVE → SUSPENDED` copies that reason into `suspension_reason`, adds 1 to `suspension_count` and increments the contract's `version`."
        PRD: "Resuming performs `SUSPENDED → ACTIVE`, deliberately **retaining** `suspension_reason` for audit rather than resetting it to `NONE`, and increments `version`."
        PRD: "The pair `ACTIVE → SUSPENDED → ACTIVE` is a genuine cycle that may repeat indefinitely, with `suspension_count` accumulating across every pass."
        PRD: "Alongside those, `suspension_reason` is a system-maintained enumeration that begins at `NONE` and thereafter takes one of `NONPAYMENT`, `DISPUTE` or `CUSTOMER_REQUEST`."

        Design: Corner/state_machines/cyclic_contract_suspend_resume_accumulates_the_suspension_counter
        """
        contract = create_contract(customer_name="Larkin Mfg")
        add_cost_tier(contract["id"], page_class="MONO", tier_index=1, from_page=1)
        contract_id = contract["id"]
        activated = activate_contract(contract_id)
        assert_fields(activated, status="ACTIVE", version=2, suspension_reason="NONE",
                      suspension_count=0)

        suspended = validate_success(
            api.suspend_service_contract(contract_id, suspend_payload("DISPUTE"), AM), 200
        )
        assert_fields(
            suspended,
            status="SUSPENDED",
            suspension_reason="DISPUTE",
            suspension_count=1,
            version=3,
        )

        resumed = validate_success(api.resume_service_contract(contract_id, AM), 200)
        assert_fields(
            resumed,
            status="ACTIVE",
            suspension_reason="DISPUTE",
            suspension_count=1,
            version=4,
        )

        resuspended = validate_success(
            api.suspend_service_contract(contract_id, suspend_payload("NONPAYMENT"), AM), 200
        )
        assert_fields(
            resuspended,
            status="SUSPENDED",
            suspension_reason="NONPAYMENT",
            suspension_count=2,
            version=5,
        )

        reresumed = validate_success(api.resume_service_contract(contract_id, AM), 200)
        assert_fields(
            reresumed,
            status="ACTIVE",
            suspension_reason="NONPAYMENT",
            suspension_count=2,
            version=6,
        )
        assert_fields(
            fetch_contract(contract_id),
            status="ACTIVE",
            suspension_count=2,
            suspension_reason="NONPAYMENT",
            version=6,
        )


class TestSiteCapPushesTheSecondDeviceIntoSupplyBlocked:
    """A one-unit site cap consumed by the first asset blocks the second one's order."""

    @staticmethod
    def _capped_site_with_one_open_auto_order():
        env = setup_print_environment(
            site={"name": "Plant 1", "toner_unit_cap": 1},
            devices=2,
            period=(PERIOD_START, PERIOD_END),
            clock=SUPPLY_CLOCK,
        )
        first, second = env["device_ids"]
        env["first_read"] = submit_automated_read(
            first,
            env["period_id"],
            mono_meter=5_000,
            toner_level_pct=10,
            coverage_start=PERIOD_START,
            coverage_end=SUPPLY_CLOCK,
        )
        env["first_device_id"] = first
        env["second_device_id"] = second
        return env

    def test_first_low_read_consumes_the_single_permitted_unit(self):
        """The site's only unit of headroom goes to the first device's automatic order.

        PRD: "When an accepted reading leaves a device's `toner_level_pct` at or below 15 and the device's `supply_state` is `SUPPLY_OK`, the supply dimension moves `SUPPLY_OK → SUPPLY_LOW` and the device's `version` increments."
        PRD: "When both hold, the supply dimension moves `SUPPLY_LOW → SUPPLY_ORDERED` and a cartridge order is created with `trigger_source` `AUTO_THRESHOLD`, a `quantity` of exactly 1, a `unit_price_cents` of 8,900 — the provider's standard automatic-replenishment unit price of $89 per cartridge — and a `part_type` chosen from the device and the reading: `TONER_COLOR` when the device is `color_capable` **and** the accepted reading's `color_delta` is greater than zero, and `TONER_BLACK` in every other case."

        Design: Corner/state_machines/valid_transition_site_cap_pushes_the_second_device_into_supply_blocked
        """
        env = self._capped_site_with_one_open_auto_order()

        assert_device_dimensions(
            fetch_device(env["first_device_id"]), "ACTIVE", "SUPPLY_ORDERED"
        )
        orders = list_orders_for_device(env["first_device_id"])
        assert len(orders) == 1, f"expected exactly one automatic order, got {orders}"
        assert_fields(
            orders[0],
            trigger_source="AUTO_THRESHOLD",
            quantity=1,
            unit_price_cents=8_900,
            part_type="TONER_BLACK",
            status="ORDERED",
        )
        assert_fields(fetch_site(env["site_id"]), open_toner_units=1)
        assert_fields(fetch_contract(env["contract_id"]), consumables_committed_cents=8_900)

    def test_second_low_read_is_accepted_but_its_replenishment_is_suppressed(self, api):
        """The cap breach sends the supply dimension to SUPPLY_BLOCKED with no order at all.

        PRD: "When either condition fails — an open order already exists, or one more unit would breach the site cap — replenishment is **suppressed** rather than forced through: the supply dimension moves `SUPPLY_LOW → SUPPLY_BLOCKED`, no cartridge order is created at all, and the device's `version` increments."
        PRD: "The reading itself still becomes `ACCEPTED` in the ordinary way; only the replenishment is withheld."
        PRD: "Two conditions must both hold: the device must have **no** cartridge order currently in `ORDERED` status — the ceiling is exactly one open order per device — and the hosting site's `open_toner_units` plus one unit must not exceed the site's `toner_unit_cap`."
        PRD: "Otherwise the reading is `ACCEPTED`, and `mono_delta` and `color_delta` are written with the two candidate values."

        Design: Corner/state_machines/valid_transition_site_cap_pushes_the_second_device_into_supply_blocked
        """
        env = self._capped_site_with_one_open_auto_order()
        second = env["second_device_id"]

        reading = validate_success(
            api.submit_automated_meter_read(
                meter_read_payload(
                    second,
                    env["period_id"],
                    mono_meter=4_000,
                    color_meter=0,
                    toner_level_pct=12,
                    coverage_start=PERIOD_START,
                    coverage_end=SUPPLY_CLOCK,
                ),
                make_fleet_ops_headers("ops-1"),
            ),
            201,
        )

        assert_fields(
            reading,
            status="ACCEPTED",
            mono_delta=4_000,
            color_delta=0,
            exception_reason="NONE",
        )
        device = fetch_device(second)
        assert_device_dimensions(device, "ACTIVE", "SUPPLY_BLOCKED")
        assert_fields(device, toner_level_pct=12)
        assert list_orders_for_device(second) == [], (
            "the blocked device must carry no cartridge order at all"
        )
        assert_fields(fetch_site(env["site_id"]), open_toner_units=1)
        assert_fields(fetch_contract(env["contract_id"]), consumables_committed_cents=8_900)
