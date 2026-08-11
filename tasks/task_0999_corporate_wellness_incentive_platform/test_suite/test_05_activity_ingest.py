"""Device-sync ingestion: conversion, daily cap, dual-view balances, idempotency
(PRD §2.8, §3.5)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_activity_event_payload,
    make_employee_headers,
    post_activity,
    setup_active_enrollment,
    validate_error,
    validate_paginated,
    validate_success,
)

BA = TEST_USERS["benefits_admin_headers"]


def _employee(ctx):
    return make_employee_headers(ctx["employee"]["id"])


class TestProvisionalVsSettledBalances:
    """Difficulty instance: the same accepted event is counted by the provisional
    view (PROVISIONAL or POSTED) but not by the settled view (POSTED only)."""

    def test_accepted_event_grants_provisional_not_settled(self, api):
        """PRD §2.8: "The `points_balance_settled` sums the `points_delta` of entries
        in `POSTED` status only... The `points_balance_provisional` sums entries in
        either `PROVISIONAL` or `POSTED` status..."
        PRD §3.5: "for `STEPS`, the quantity divided by 1000 rounded down to a whole
        number..."

        Design: Difficulty/dual_variant_calc/provisional_vs_settled_points_balance
        """
        ctx = setup_active_enrollment()
        enr_id = ctx["enrollment"]["id"]

        event = validate_success(
            api.create_activity_event(
                create_activity_event_payload(enr_id, "evt-1", quantity=100000),
                _employee(ctx),
            ),
            201,
        )
        assert event["points_granted"] == 100

        after = validate_success(api.get_enrollment(enr_id, BA), 200)
        assert after["points_balance_provisional"] == 100, (
            "provisional view counts the PROVISIONAL EARNED entry"
        )
        assert after["points_balance_settled"] == 0, (
            "settled view counts POSTED entries only; nothing is finalized yet"
        )

    def test_accepted_event_creates_provisional_earned_entry(self, api):
        """PRD §3.5: "Acceptance then creates an `EARNED` PointsLedgerEntry in
        `PROVISIONAL` status carrying the granted delta and the event's id as
        `source_activity_event_id`, recomputes both enrollment balances..."
        PRD §3.5: "The ledger entries sourced from a single activity event — zero
        or one of them — can be read back through the event's ledger listing."

        Design: Difficulty/dual_variant_calc/provisional_vs_settled_points_balance
        """
        ctx = setup_active_enrollment()
        enr_id = ctx["enrollment"]["id"]

        event = post_activity(enr_id, ctx["employee"]["id"], "evt-1", quantity=100000)

        entries, meta = validate_paginated(
            api.list_activity_event_points_ledger_entries(event["id"], BA)
        )
        assert meta["total_count"] == 1
        entry = entries[0]
        assert entry["kind"] == "EARNED"
        assert entry["status"] == "PROVISIONAL"
        assert entry["points_delta"] == 100
        assert entry["source_activity_event_id"] == event["id"]


class TestPointsConversion:
    def test_activity_points_floor_division_subunit(self, api):
        """PRD §3.5: "for `STEPS`, the quantity divided by 1000 rounded down to a
        whole number..."
        PRD §2.9: "Points are integers as well, and every division in points
        conversion rounds down to a whole number."

        Design: Corner/calculations/activity_points_floor_division_subunit
        """
        ctx = setup_active_enrollment()
        enr_id = ctx["enrollment"]["id"]

        event = validate_success(
            api.create_activity_event(
                create_activity_event_payload(enr_id, "evt-sub", quantity=999),
                _employee(ctx),
            ),
            201,
        )
        assert event["points_granted"] == 0, "floor(999/1000) == 0"

        after = validate_success(api.get_enrollment(enr_id, BA), 200)
        assert after["points_balance_provisional"] == 0

    def test_activity_daily_cap_clamps_second_event(self, api):
        """PRD §3.5: "No member may be granted more than 100 points per UTC calendar
        day of `occurred_at`: taking the day total as the sum of `points_granted`
        across the enrollment's already-accepted events on that calendar date —
        accumulated in ingestion order — the event's `points_granted` is the
        smaller of its raw conversion and the remaining daily headroom, where
        headroom is 100 minus the day total and never below zero."

        Design: Corner/calculations/activity_daily_cap_clamps_second_event
        """
        ctx = setup_active_enrollment()
        enr_id = ctx["enrollment"]["id"]
        post_activity(
            enr_id, ctx["employee"]["id"], "evt-a",
            quantity=100000, occurred_at="2026-04-15T08:00:00Z",
        )

        second = validate_success(
            api.create_activity_event(
                create_activity_event_payload(
                    enr_id, "evt-b", quantity=50000,
                    occurred_at="2026-04-15T18:00:00Z",
                ),
                _employee(ctx),
            ),
            201,
        )
        assert second["points_granted"] == 0, (
            "day total already 100 == daily cap; headroom is 0 so raw 50 clamps to 0"
        )

        after = validate_success(api.get_enrollment(enr_id, BA), 200)
        assert after["points_balance_provisional"] == 100


class TestEventWindow:
    def test_event_outside_plan_year_rejected(self, api):
        """PRD §3.5: "The occurrence must fall inside the program's plan year and not
        in the future (otherwise `ERR_EVENT_OUTSIDE_WINDOW`)."

        Design: Corner/validations/event_outside_plan_year_rejected
        """
        ctx = setup_active_enrollment()
        res = api.create_activity_event(
            create_activity_event_payload(
                ctx["enrollment"]["id"], "evt-old", quantity=5000,
                occurred_at="2025-11-15T10:00:00Z",
            ),
            _employee(ctx),
        )
        validate_error(res, ApiErrorId.ERR_EVENT_OUTSIDE_WINDOW, expected_status=422)


class TestIngestIdempotency:
    def test_event_idempotent_replay_returns_existing(self, api):
        """PRD §3.5: "an identical replay of an already-accepted event returns 200
        with the existing event and creates no new ledger entry..."
        PRD §4: "an idempotent replay of an already-accepted activity event also
        returns `200 OK` carrying the existing event."

        Design: Corner/cross_cutting_layers/event_idempotent_replay_returns_existing
        """
        ctx = setup_active_enrollment()
        enr_id = ctx["enrollment"]["id"]
        payload = create_activity_event_payload(enr_id, "evt-dup", quantity=100000)
        first = post_activity(enr_id, ctx["employee"]["id"], "evt-dup", quantity=100000)

        replay = validate_success(api.create_activity_event(payload, _employee(ctx)), 200)
        assert replay["id"] == first["id"], "replay must return the original event id"

        entries, meta = validate_paginated(
            api.list_enrollment_points_ledger_entries(enr_id, BA)
        )
        assert meta["total_count"] == 1, "no second ledger entry may be created"
        after = validate_success(api.get_enrollment(enr_id, BA), 200)
        assert after["points_balance_provisional"] == 100

    def test_event_duplicate_key_conflict_rejected(self, api):
        """PRD §3.5: "the same key carrying a different `quantity`, `occurred_at`,
        or `activity_type` is rejected with `ERR_DUPLICATE_EVENT`."

        Design: Corner/cross_cutting_layers/event_duplicate_key_conflict_rejected
        """
        ctx = setup_active_enrollment()
        enr_id = ctx["enrollment"]["id"]
        post_activity(enr_id, ctx["employee"]["id"], "evt-dup", quantity=100000)

        res = api.create_activity_event(
            create_activity_event_payload(enr_id, "evt-dup", quantity=60000),
            _employee(ctx),
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_EVENT, expected_status=409)

        after = validate_success(api.get_enrollment(enr_id, BA), 200)
        assert after["points_balance_provisional"] == 100, (
            "a rejected duplicate must not change the balance"
        )
