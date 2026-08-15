"""Kit return/settle workflow, the auto-created shortage case, and pause
window/cancellation guards (PRD 3.7, 3.8)."""
from test_helpers import (
    ApiErrorId,
    create_pause,
    kit_event,
    read_customer,
    setup_active_subscription,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _client
from test_helpers.fixtures import ADMIN, BILLING


class TestKitReturnAndSettle:
    def test_kit_settle_blocked_until_cases_closed(self, api):
        """PRD 3.8: "and the shortage — `item_count` minus `items_returned_count` —
        when positive, auto-creates an `OPEN` lost-item case of type `LOST` for the
        shortage count with `first_issued_date` set to the kit's creation date, and
        moves the shortage units from `checked_out_units` to `lost_units`."
        PRD 3.8: "Settling the kit requires every lost-item case of the subscription
        to be `SETTLED` or `WAIVED` (`ERR_INVALID_STATE` otherwise) and moves the kit
        `RETURNED` → `SETTLED` — the gate that §3.2's termination checks."
        PRD 3.8: "For `LOST`, the schedule is size-based replacement cost — `NEWBORN`
        250 cents, `SMALL` 275, `MEDIUM` 300, `LARGE` 325, `XL` 350 — depreciated by
        age: the item count times the replacement cost times the full amount when the
        items are at most 90 days old, 60 percent when the age is 91 through 180 days,
        and 30 percent at 181 days or older, rounded half-up to whole cents."

        Design: Corner/state_machines/kit_settle_blocked_until_cases_closed
        """
        ctx = setup_active_subscription()
        sub_id = ctx["subscription"]["id"]
        kit_id = ctx["kit"]["id"]
        assert ctx["kit"]["item_count"] == 88  # quota 80 + 10 percent reserve

        kit = kit_event(kit_id, "RETURN", items_returned_count=80)
        assert kit["status"] == "RETURNED"
        assert kit["items_returned_count"] == 80

        cases = validate_success(
            _client.list_cases(ADMIN, params={"subscription_id": sub_id})
        )
        assert len(cases) == 1, "the shortage of 8 must auto-create exactly one case"
        case = cases[0]
        assert case["case_type"] == "LOST"
        assert case["item_count"] == 8
        assert case["status"] == "OPEN"

        blocked = _client.kit_event(kit_id, {"event_type": "SETTLE"}, ADMIN)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE.value)

        charged = validate_success(
            _client.case_event(case["id"], {"event_type": "CHARGE"}, BILLING)
        )
        assert charged["charge_cents"] == 2400, (
            f"8 MEDIUM items at age 0 charge 8 x 300 = 2400, got {charged['charge_cents']}"
        )
        validate_success(_client.case_event(case["id"], {"event_type": "SETTLE"}, BILLING))

        settled = kit_event(kit_id, "SETTLE")
        assert settled["status"] == "SETTLED"

        customer = read_customer(ctx["customer"]["id"])
        assert customer["deposit_held_cents"] == 15600, (
            f"18000 - 2400 applied = 15600 held, got {customer['deposit_held_cents']}"
        )

    def test_kit_return_count_mismatch_rejected(self, api):
        """PRD 3.8: "A `PlatformAdmin` or `PlantOperator` returns an issued kit with
        `items_returned_count`, which must not exceed the kit's `item_count`
        (`ERR_RETURN_COUNT_MISMATCH`)."

        Design: Corner/validations/kit_return_count_mismatch_rejected
        """
        ctx = setup_active_subscription()
        kit_id = ctx["kit"]["id"]
        assert ctx["kit"]["item_count"] == 88

        response = _client.kit_event(
            kit_id, {"event_type": "RETURN", "items_returned_count": 89}, ADMIN
        )
        validate_error(response, ApiErrorId.ERR_RETURN_COUNT_MISMATCH.value)

        kit = validate_success(_client.get_kit(kit_id, ADMIN))
        assert kit["status"] == "ISSUED", "a rejected RETURN leaves the kit ISSUED"


class TestPauseGuards:
    def test_pause_cancel_then_terminal_lock(self, api):
        """PRD 3.7: "Cancelling a `SCHEDULED` pause — open to the owning `Customer`
        or a `PlatformAdmin` — moves it to the terminal `CANCELLED` state and likewise
        increments the subscription's `version` by one, the OCC pair to creation."
        PRD 2.10: "Terminal-state guard — an event or action attempted on a resource
        already in a terminal state is `ERR_ALREADY_TERMINAL` (409)."

        Design: Corner/state_machines/pause_cancel_then_terminal_lock
        """
        ctx = setup_active_subscription()
        sub_id = ctx["subscription"]["id"]
        pause = create_pause(
            sub_id, "2026-08-05", "2026-08-10",
            ctx["subscription_version"], ctx["customer_headers"],
        )

        cancelled = validate_success(_client.cancel_pause(pause["id"], ctx["customer_headers"]))
        assert cancelled["status"] == "CANCELLED"

        response = _client.cancel_pause(pause["id"], ADMIN)
        validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL.value)

    def test_pause_window_invalid_rejected(self, api):
        """PRD 3.7: "Window shape: `end_date` must be after `start_date` and the span
        must not exceed 28 days, else `ERR_PAUSE_WINDOW_INVALID`."

        Design: Corner/validations/pause_window_invalid_rejected
        """
        ctx = setup_active_subscription()
        response = _client.create_pause(
            {
                "subscription_id": ctx["subscription"]["id"],
                "start_date": "2026-08-10",
                "end_date": "2026-08-06",
                "expected_subscription_version": ctx["subscription_version"],
            },
            ctx["customer_headers"],
        )
        validate_error(response, ApiErrorId.ERR_PAUSE_WINDOW_INVALID.value)
