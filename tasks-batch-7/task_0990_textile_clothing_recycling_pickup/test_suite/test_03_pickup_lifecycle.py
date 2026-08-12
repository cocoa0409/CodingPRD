"""Pickup lifecycle: cancel/no-show/rebook cycle, reschedule OCC and caps,
route-day capacity boundaries."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_resident_headers, make_driver_headers,
    new_zone, new_resident, new_delivered_kit, new_pickup, route_pickup,
    collect_pickup, no_show_pickup, rebook_pickup, read_pickup,
    create_pickup_payload, reschedule_pickup_payload, route_pickup_payload,
)

OP = TEST_USERS["zone_operator_headers"]


def test_cancel_cancelled_pickup_rejected(api):
    """PRD §3.3: "Cancellation is permitted while the pickup is in `SCHEDULED` or
    `ROUTED` and is rejected with `ERR_INVALID_STATE` from any other status."
    PRD §3.3: "`CANCELLED` and `SETTLED` are the terminal states of a pickup."

    Design: Corner/state_machines/cancel_cancelled_pickup_rejected
    """
    zone = new_zone("Zone SM3")
    resident = new_resident(zone["id"], "Vic V", "vic@x.com")
    pickup = new_pickup(resident["id"], bags_claimed=2)

    first = validate_success(
        api_client.cancel_pickup(pickup["id"], make_resident_headers(resident["id"]))
    )
    assert first["status"] == "CANCELLED"

    resp = api_client.cancel_pickup(pickup["id"], make_resident_headers(resident["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_mark_no_show_from_scheduled_rejected(api):
    """PRD §2.1: "for an already-routed pickup the assigned driver's id is
    significant, and mark-collected or mark-no-show require `X-User-ID` to equal
    the pickup's stored `driver_id`; for pickups that have not yet been routed,
    any `Driver` may attempt the operation, and the request proceeds to the state
    check."
    PRD §3.3: "The driver marks the pickup, transitioning it from `ROUTED` to
    `NO_SHOW` and clearing `driver_id` and `service_date` back to null."

    Design: Corner/state_machines/mark_no_show_from_scheduled_rejected
    """
    zone = new_zone("Zone SM4")
    resident = new_resident(zone["id"], "Wes W", "wes@x.com")
    pickup = new_pickup(resident["id"], bags_claimed=2)

    resp = api_client.mark_no_show(pickup["id"], make_driver_headers("drv-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert read_pickup(pickup["id"])["status"] == "SCHEDULED"


class TestNoShowRebookCycle:
    def test_no_show_then_rebook_reenters_scheduled(self, api):
        """PRD §3.3: "The driver marks the pickup, transitioning it from `ROUTED`
        to `NO_SHOW` and clearing `driver_id` and `service_date` back to null."
        PRD §3.3: "On success the pickup returns to `SCHEDULED` and its
        `rebook_count` increments by one. The `SCHEDULED → ROUTED → NO_SHOW →
        SCHEDULED` cycle is therefore a bounded loop, capped at two rebooks per
        pickup."

        Design: Difficulty/non_linear_state_machine/pickup_no_show_rebook_cycle
        """
        zone = new_zone("Zone NL1")
        resident = new_resident(zone["id"], "Cora Coy", "cora@x.com")
        new_delivered_kit(resident["id"], "BAG")
        pickup = new_pickup(resident["id"], bags_claimed=5)
        assert pickup["status"] == "SCHEDULED"
        route_pickup(pickup["id"], "drv-1", "2026-05-10")

        ns = no_show_pickup(pickup["id"], "drv-1")
        assert ns["status"] == "NO_SHOW"
        assert ns["driver_id"] is None, "no-show must clear driver_id"
        assert ns["service_date"] is None, "no-show must clear service_date"

        rb = rebook_pickup(
            pickup["id"], resident["id"],
            "2026-05-11T10:00:00Z", "2026-05-11T12:00:00Z",
        )
        assert rb["status"] == "SCHEDULED", "rebook re-enters SCHEDULED on the cycle edge"
        assert rb["rebook_count"] == 1

    def test_cycle_completes_through_second_route_and_collection(self, api):
        """PRD §3.3: "Once routed, the assigned driver either collects the load or
        marks the resident a no-show."
        PRD §3.3: "On success the pickup transitions from `ROUTED` to `COLLECTED`,
        a new `WeightTicket` is created with `source_type` set to `PICKUP_REQUEST`,
        `source_id` set to the pickup's `id`, and `status` set to `PROVISIONAL`"

        Design: Difficulty/non_linear_state_machine/pickup_no_show_rebook_cycle
        """
        zone = new_zone("Zone NL1")
        resident = new_resident(zone["id"], "Cora Coy", "cora@x.com")
        kit = new_delivered_kit(resident["id"], "BAG")
        pickup = new_pickup(resident["id"], bags_claimed=5)
        route_pickup(pickup["id"], "drv-1", "2026-05-10")
        no_show_pickup(pickup["id"], "drv-1")
        rebook_pickup(pickup["id"], resident["id"],
                      "2026-05-11T10:00:00Z", "2026-05-11T12:00:00Z")

        rerouted = route_pickup(pickup["id"], "drv-2", "2026-05-11")
        assert rerouted["status"] == "ROUTED"
        assert rerouted["driver_id"] == "drv-2"

        ticket = collect_pickup(pickup["id"], "drv-2", 30.0)
        assert ticket["status"] == "PROVISIONAL"
        assert ticket["source_type"] == "PICKUP_REQUEST"
        assert ticket["source_id"] == pickup["id"]
        assert read_pickup(pickup["id"])["status"] == "COLLECTED"
        # collection auto-retires the resident's delivered kits
        kits, _ = validate_paginated(api_client.list_resident_bag_kits(resident["id"], OP))
        assert all(k["status"] == "RETIRED" for k in kits if k["id"] == kit["id"])


def test_rebook_limit_third_rebook_rejected(api):
    """PRD §3.3: "From `NO_SHOW` the resident may rebook by supplying a fresh
    `window_start` and `window_end`. The rebook requires the resident to be
    `ACTIVE` (otherwise `ERR_RESIDENT_SUSPENDED`), requires the `rebook_count` to
    still be below the hard cap of 2 (otherwise `ERR_REBOOK_LIMIT_REACHED`), and
    applies the same shape, recency, and buffered-overlap window checks as a
    reschedule."

    Design: Corner/state_machines/rebook_limit_third_rebook_rejected
    """
    zone = new_zone("Zone SM10")
    resident = new_resident(zone["id"], "Abby A", "abby@x.com")
    pickup = new_pickup(resident["id"], bags_claimed=2)

    route_pickup(pickup["id"], "drv-1", "2026-05-10")
    no_show_pickup(pickup["id"], "drv-1")
    rb1 = rebook_pickup(pickup["id"], resident["id"],
                        "2026-05-11T10:00:00Z", "2026-05-11T12:00:00Z")
    assert rb1["rebook_count"] == 1

    route_pickup(pickup["id"], "drv-1", "2026-05-11")
    no_show_pickup(pickup["id"], "drv-1")
    rb2 = rebook_pickup(pickup["id"], resident["id"],
                        "2026-05-12T10:00:00Z", "2026-05-12T12:00:00Z")
    assert rb2["rebook_count"] == 2

    route_pickup(pickup["id"], "drv-1", "2026-05-12")
    no_show_pickup(pickup["id"], "drv-1")
    resp = api_client.rebook_pickup(
        pickup["id"],
        {"window_start": "2026-05-13T10:00:00Z", "window_end": "2026-05-13T12:00:00Z"},
        make_resident_headers(resident["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REBOOK_LIMIT_REACHED)
    assert read_pickup(pickup["id"])["status"] == "NO_SHOW"


class TestReschedule:
    def test_reschedule_limit_fourth_rejected(self, api):
        """PRD §3.3: "The pickup's `reschedule_count` must still be below the hard
        cap of 3 — otherwise the reschedule is rejected with
        `ERR_RESCHEDULE_LIMIT_REACHED`. On success the server replaces the window,
        increments `reschedule_count` by one, and increments `version` by one."

        Design: Corner/state_machines/reschedule_limit_fourth_rejected
        """
        zone = new_zone("Zone SM11")
        resident = new_resident(zone["id"], "Bart B", "bart@x.com")
        pickup = new_pickup(resident["id"], bags_claimed=2)

        version = pickup["version"]
        for day in ("2026-05-11", "2026-05-12", "2026-05-13"):
            payload = reschedule_pickup_payload(
                version,
                window_start=f"{day}T10:00:00Z", window_end=f"{day}T12:00:00Z",
            )
            updated = validate_success(
                api_client.reschedule_pickup(pickup["id"], payload, make_resident_headers(resident["id"]))
            )
            assert updated["version"] == version + 1
            version = updated["version"]

        assert updated["reschedule_count"] == 3

        payload = reschedule_pickup_payload(
            version, window_start="2026-05-14T10:00:00Z", window_end="2026-05-14T12:00:00Z"
        )
        resp = api_client.reschedule_pickup(pickup["id"], payload, make_resident_headers(resident["id"]))
        validate_error(resp, ApiErrorId.ERR_RESCHEDULE_LIMIT_REACHED)
        final = read_pickup(pickup["id"])
        assert final["status"] == "SCHEDULED"
        assert final["window_start"].startswith("2026-05-13"), "window stays at the last successful reschedule"

    def test_reschedule_with_stale_version_returns_412(self, api):
        """PRD §2.7: "A reschedule of a `PickupRequest` must carry
        `expected_pickup_version` equal to the pickup's current `version`. The
        reschedule legitimately supersedes the prior schedule, so a client holding
        a stale version would silently discard the newer window; the server instead
        rejects the request with `ERR_STALE_VERSION` (HTTP 412). A successful
        reschedule increments the pickup's `version` by one and refreshes
        `updated_at`."

        Design: Corner/cross_cutting_layers/reschedule_with_stale_version_returns_412
        """
        zone = new_zone("Zone XL1")
        resident = new_resident(zone["id"], "Ann A", "ann@x.com")
        pickup = new_pickup(resident["id"], bags_claimed=2)
        v1 = pickup["version"]

        payload = reschedule_pickup_payload(
            v1, window_start="2026-05-11T10:00:00Z", window_end="2026-05-11T12:00:00Z"
        )
        updated = validate_success(
            api_client.reschedule_pickup(pickup["id"], payload, make_resident_headers(resident["id"]))
        )
        assert updated["version"] == v1 + 1
        assert updated["reschedule_count"] == 1

        stale = reschedule_pickup_payload(
            v1, window_start="2026-05-12T10:00:00Z", window_end="2026-05-12T12:00:00Z"
        )
        resp = api_client.reschedule_pickup(pickup["id"], stale, make_resident_headers(resident["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        final = read_pickup(pickup["id"])
        assert final["window_start"].startswith("2026-05-11"), "stale reschedule must not move the window"
        assert final["reschedule_count"] == 1


class TestRouteDayCapacity:
    def test_exactly_800_kg_admitted(self, api):
        """PRD §3.3: "Routing enforces route-day vehicle capacity: the sum of
        `est_weight_kg` over every pickup already in `ROUTED` for the same
        `driver_id` and `service_date`, plus the `est_weight_kg` of the pickup
        being routed, must not exceed 800.0 kilograms. A total of exactly 800.0
        is permitted; anything strictly greater is rejected with
        `ERR_ROUTE_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/route_day_capacity_exact_800_admitted
        """
        zone = new_zone("Zone BP2")
        resident = new_resident(zone["id"], "Ivy Iles", "ivy@x.com")
        pa = new_pickup(resident["id"], "2026-05-10T08:00:00Z", "2026-05-10T10:00:00Z", 120)
        pb = new_pickup(resident["id"], "2026-05-10T12:30:00Z", "2026-05-10T14:00:00Z", 80)
        assert pa["est_weight_kg"] == pytest.approx(480.0)
        assert pb["est_weight_kg"] == pytest.approx(320.0)

        route_pickup(pa["id"], "drv-1", "2026-05-10")
        rb = route_pickup(pb["id"], "drv-1", "2026-05-10")
        assert rb["status"] == "ROUTED", "480.0 + 320.0 == 800.0 exactly must be admitted"

    def test_one_bag_over_800_rejected(self, api):
        """PRD §3.3: "A total of exactly 800.0 is permitted; anything strictly
        greater is rejected with `ERR_ROUTE_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/route_day_capacity_exact_800_admitted
        """
        zone = new_zone("Zone BP2")
        resident = new_resident(zone["id"], "Ivy Iles", "ivy@x.com")
        pa = new_pickup(resident["id"], "2026-05-10T08:00:00Z", "2026-05-10T10:00:00Z", 120)
        pb = new_pickup(resident["id"], "2026-05-10T12:30:00Z", "2026-05-10T14:00:00Z", 80)
        pc = new_pickup(resident["id"], "2026-05-10T15:00:00Z", "2026-05-10T16:00:00Z", 1)
        route_pickup(pa["id"], "drv-1", "2026-05-10")
        route_pickup(pb["id"], "drv-1", "2026-05-10")

        resp = api_client.route_pickup(pc["id"], route_pickup_payload(), OP)
        validate_error(resp, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED)
        assert read_pickup(pc["id"])["status"] == "SCHEDULED", "rejected route leaves the pickup SCHEDULED"

    def test_next_day_is_a_fresh_capacity_pool(self, api):
        """PRD §3.3: "Routing enforces route-day vehicle capacity: the sum of
        `est_weight_kg` over every pickup already in `ROUTED` for the same
        `driver_id` and `service_date`, plus the `est_weight_kg` of the pickup
        being routed, must not exceed 800.0 kilograms."

        Design: Difficulty/resource_temporal_overlap/driver_route_day_aggregate_capacity_partition
        """
        zone = new_zone("Zone TO2")
        resident = new_resident(zone["id"], "Mona Mew", "mona@x.com")
        pa = new_pickup(resident["id"], "2026-05-10T08:00:00Z", "2026-05-10T10:00:00Z", 195)
        pb = new_pickup(resident["id"], "2026-05-11T10:00:00Z", "2026-05-11T12:00:00Z", 100)

        ra = route_pickup(pa["id"], "drv-1", "2026-05-10")
        assert ra["status"] == "ROUTED", "780.0 <= 800.0 on 2026-05-10"
        rb = route_pickup(pb["id"], "drv-1", "2026-05-11")
        assert rb["status"] == "ROUTED", "2026-05-11 is a fresh daily pool for the same driver"

    def test_same_day_overflow_rejected(self, api):
        """PRD §3.3: "Routing enforces route-day vehicle capacity: the sum of
        `est_weight_kg` over every pickup already in `ROUTED` for the same
        `driver_id` and `service_date`, plus the `est_weight_kg` of the pickup
        being routed, must not exceed 800.0 kilograms. A total of exactly 800.0
        is permitted; anything strictly greater is rejected with
        `ERR_ROUTE_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/driver_route_day_aggregate_capacity_partition
        """
        zone = new_zone("Zone TO2")
        resident = new_resident(zone["id"], "Mona Mew", "mona@x.com")
        pa = new_pickup(resident["id"], "2026-05-10T08:00:00Z", "2026-05-10T10:00:00Z", 195)
        pc = new_pickup(resident["id"], "2026-05-10T12:30:00Z", "2026-05-10T14:00:00Z", 10)
        route_pickup(pa["id"], "drv-1", "2026-05-10")

        resp = api_client.route_pickup(
            pc["id"], route_pickup_payload(driver_id="drv-1", service_date="2026-05-10"), OP
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED)
