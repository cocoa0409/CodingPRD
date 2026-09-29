"""Corner behaviour of the clock endpoint and of the collection reads: the startup default instant, the
side effects a single advance carries, the pagination bounds, and the live-state query filters."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    fixtures as fx,
)

BIG_CREDIT = 100_000_000_000


class TestLogicalClockEndpointCorners:
    def test_the_server_starts_on_the_first_of_august_without_being_told(self, api):
        """PRD §3.1: "The startup default is exactly 2026-08-01T00:00:00Z, and the server never falls back
        to real wall-clock time."
        PRD §2.5: "Every timestamp the server writes — a receipt's `released_at_utc`, a gauge's
        `last_gauge_at_utc`, a filter change's `changed_at_utc`, a spill's `reported_at_utc`, the
        `created_at` and `updated_at` of every row — is taken from that clock."
        PRD §2.5: "Time in this system is not wall-clock time."

        Design: Corner/endpoints/startup_default_clock_value
        """
        farm = fx.create_farm()
        fx.issue_permit(farm["id"])
        tank = fx.register_tank(farm["id"], capacity_liters=5_000_000.0,
                                safe_fill_liters=4_000_000.0, density_kg_per_m3=795.0,
                                opening_volume_liters=0.0)

        receipt = fx.record_receipt(tank["id"])

        assert receipt["created_at"].startswith("2026-08-01T00:00:00"), \
            "nothing in this test ever set the clock, and the wall clock is never consulted"
        assert farm["created_at"].startswith("2026-08-01T00:00:00")
        assert tank["created_at"].startswith("2026-08-01T00:00:00")

    def test_one_advance_expires_the_authorization_and_freezes_the_farm(self, api):
        """PRD §2.5: "Two lifecycle transitions are purely time-driven and are evaluated lazily: a fuel
        authorization moves from `ISSUED` to `EXPIRED` once the clock has reached or passed its
        `expires_at_utc`, and an environmental permit moves from `ACTIVE` to `EXPIRED` once the clock has
        reached or passed its `valid_until_utc`."
        PRD §2.5: "Both are evaluated whenever the row (or, for the permit, its farm) is read or referenced,
        and whenever a child mutation recomputes the farm's posture, so a clock advance followed by a read is
        enough to observe the transition."
        PRD §3.1: "Advancing the clock re-evaluates authorization expiry, permit expiry, every asset's
        element life, and every farm's posture in that same request."

        Design: Corner/endpoints/clock_set_returns_the_recomputed_side_effects
        """
        fx.set_clock("2026-08-10T06:00:00Z")
        farm = fx.create_farm()
        permit = fx.issue_permit(farm["id"], valid_from_utc="2026-08-01T00:00:00Z",
                                 valid_until_utc="2026-08-11T00:00:00Z")
        assert permit["status"] == "ACTIVE"
        account = fx.open_account(credit_limit_cents=BIG_CREDIT)
        flight = fx.register_flight(account["id"], stand_code="J01",
                                    scheduled_departure_utc="2026-08-10T08:00:00Z")
        auth = fx.issue_authorization(account["id"], flight["id"],
                                      max_authorized_liters=20_000.0)
        assert auth["status"] == "ISSUED"

        validate_success(api.set_clock("2026-08-11T00:00:00Z", fx.ADMIN))

        assert fx.read_authorization(auth["id"])["status"] == "EXPIRED"
        permits, _meta = validate_paginated(api.list_environmental_permits(farm["id"],
                                                                          fx.ADMIN))
        assert [p["status"] for p in permits] == ["EXPIRED"]
        assert fx.read_farm(farm["id"])["posture"] == "FROZEN", \
            "no intervening request was needed to make any of the three observable"


class TestCollectionReadCorners:
    def test_the_page_defaults_to_ten_and_refuses_a_size_outside_one_to_a_hundred(self, api):
        """PRD §2.3: "Every list endpoint accepts two query parameters. `limit` controls page size: it
        defaults to 10, its minimum accepted value is 1, and its maximum accepted value is 100. `offset`
        controls the starting position: it defaults to 0 and its minimum accepted value is 0. A `limit` or
        `offset` outside those bounds is a field-constraint violation and is rejected with
        `ERR_FIELD_OUT_OF_RANGE`."
        PRD §2.3: "The `meta` object on a list response carries `limit`, `offset`, `total_count` (the total
        number of rows matching the query before pagination) and `has_more` (true when rows remain beyond the
        current page)."
        PRD §4: "Lists uplift tickets, filterable by order, tank, invoice and status."

        Design: Corner/endpoints/pagination_defaults_and_bounds
        """
        fx.set_clock()

        tickets, meta = validate_paginated(api.list_uplift_records(fx.AGENT))
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 0
        assert meta["has_more"] is False
        assert tickets == []

        # both ends of the accepted page-size range are enforced
        validate_error(api.list_uplift_records(fx.AGENT, {"limit": 101}),
                       ApiErrorId.ERR_FIELD_OUT_OF_RANGE, 422)
        validate_error(api.list_uplift_records(fx.AGENT, {"limit": 0}),
                       ApiErrorId.ERR_FIELD_OUT_OF_RANGE, 422)

    def test_a_collection_with_nothing_in_it_is_still_a_collection(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of
        resources."
        PRD §2.3: "The `meta` object on a list response carries `limit`, `offset`, `total_count` (the total
        number of rows matching the query before pagination) and `has_more` (true when rows remain beyond the
        current page)."
        PRD §4: "Lists incidents, filterable by farm, asset, tank and status."

        Design: Corner/endpoints/empty_collection_is_an_empty_array_not_a_404
        """
        fx.set_clock()

        response = api.list_spill_incidents(fx.ENVIRO)
        incidents, meta = validate_paginated(response)

        assert response.json()["response_type"] == "array"
        assert incidents == []
        assert meta["total_count"] == 0
        assert meta["has_more"] is False, \
            "an empty environmental record is a fact worth returning, not a missing resource"

    def test_an_offset_beyond_the_last_row_is_an_empty_page_and_not_a_failure(self, api):
        """PRD §2.3: "`offset` controls the starting position: it defaults to 0 and its minimum accepted
        value is 0."
        PRD §2.3: "The `meta` object on a list response carries `limit`, `offset`, `total_count` (the total
        number of rows matching the query before pagination) and `has_more` (true when rows remain beyond the
        current page)."
        PRD §4: "Lists invoices, filterable by account, superseded invoice and status."

        Design: Corner/endpoints/offset_past_the_end
        """
        env = fx.setup_sequential_uplifts_for_account(
            uplift_liters=(30_000.0, 30_000.0, 40_000.0), credit_limit_cents=BIG_CREDIT)
        account_id = env["account"]["id"]
        fx.set_clock("2026-08-10T09:00:00Z")
        for start, end in (("2026-08-10T06:00:00Z", "2026-08-10T06:30:00Z"),
                           ("2026-08-10T07:00:00Z", "2026-08-10T07:30:00Z"),
                           ("2026-08-10T08:00:00Z", "2026-08-10T08:30:00Z")):
            fx.create_draft_invoice(account_id, period_start_utc=start, period_end_utc=end)

        everything, full_meta = validate_paginated(api.list_invoices(fx.BILLING))
        assert full_meta["total_count"] == 3
        assert len(everything) == 3

        beyond, meta = validate_paginated(api.list_invoices(fx.BILLING, {"offset": 1000}))
        assert beyond == []
        assert meta["total_count"] == 3, "the count still describes the whole matching set"
        assert meta["has_more"] is False


class TestQueryFilterCorners:
    def test_the_asset_filter_reflects_the_current_assignment_and_not_its_history(self, api):
        """PRD §4: "Lists orders, filterable by flight, authorization, tank, asset, pit and status."
        PRD §3.6: "Unassigning, `ASSIGNED → AUTHORIZED`, clears both the `fueling_asset_id` and the
        `hydrant_pit_id` to null, raises `unassign_count` by one, and ends the order's pit occupancy for its
        window — but it deliberately leaves the tank's `reserved_volume_liters` untouched, because the volume
        reservation belongs to the authorised state, not to the assignment."
        PRD §2.4: "Derived figures are also refreshed on read, so a client never sees a stale computed
        value."

        Design: Corner/endpoints/filter_by_a_nullable_fk
        """
        env = fx.setup_truck_order(target_state="ASSIGNED",
                                   account_overrides={"credit_limit_cents": BIG_CREDIT})
        order_id, asset_id = env["order"]["id"], env["truck"]["id"]

        assigned, _meta = validate_paginated(api.list_fueling_orders(
            fx.AGENT, {"fueling_asset_id": asset_id}))
        assert [o["id"] for o in assigned] == [order_id]

        validate_success(api.unassign_order(order_id, fx.AGENT))

        after, meta = validate_paginated(api.list_fueling_orders(
            fx.AGENT, {"fueling_asset_id": asset_id}))
        assert after == []
        assert meta["total_count"] == 0, \
            "the order still exists, but its asset reference is null again"
        assert fx.read_order(order_id)["unassign_count"] == 1

    def test_a_status_filter_and_a_parent_filter_narrow_the_same_result(self, api):
        """PRD §4: "Lists uplift tickets, filterable by order, tank, invoice and status."
        PRD §3.6: "**Abort**, `FUELING → ABORTED`, carries an `abort_reason` of `SPILL`, `QUALITY_HOLD`,
        `AIRCRAFT_RELEASE` or `EQUIPMENT_FAILURE`, and compensates everything: every `POSTED` ticket on the
        order becomes `VOIDED` with `voided_reason` `ORDER_ABORTED` and its `net_liters` are credited back to
        the tank's `book_volume_liters`; the requested volume is subtracted from the tank's
        `reserved_volume_liters`; for truck delivery the asset's `onboard_volume_liters` recomputes to 0.0 as
        the voided tickets leave the posted set, so the sum of tank book volume and on-board volume returns
        to exactly its pre-fuelling value; the authorization is driven `ISSUED → VOIDED` with `voided_reason`
        `ORDER_CANCELLED`; pit occupancy ends; and the account's accrual exposure returns to its
        pre-authorization value."

        Design: Corner/endpoints/filter_by_status_combines_with_the_fk_filter
        """
        env = fx.setup_fueling_order_with_uplift(
            meter_end_liters=20_000.0, requested_uplift_liters=20_000.0,
            max_authorized_liters=20_000.0,
            account_overrides={"credit_limit_cents": BIG_CREDIT})
        order_id, ticket_id = env["order"]["id"], env["uplift"]["id"]
        fx.abort_order(order_id, abort_reason="EQUIPMENT_FAILURE")
        assert fx.read_uplift(ticket_id)["status"] == "VOIDED"

        voided, meta = validate_paginated(api.list_uplift_records(
            fx.AGENT, {"fueling_order_id": order_id, "status": "VOIDED"}))
        assert [t["id"] for t in voided] == [ticket_id]
        assert meta["total_count"] == 1

        posted, _posted_meta = validate_paginated(api.list_uplift_records(
            fx.AGENT, {"fueling_order_id": order_id, "status": "POSTED"}))
        assert posted == [], "the two filters combine with AND"
