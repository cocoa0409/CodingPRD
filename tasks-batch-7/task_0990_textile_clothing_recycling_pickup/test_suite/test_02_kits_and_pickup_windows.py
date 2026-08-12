"""Bag-kit lifecycle and limits; pickup window shape, recency, conflict geometry;
computed est weight; list pagination envelope; read-after-write consistency."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_resident_headers,
    new_zone, new_resident, order_kit, dispatch_kit, deliver_kit, new_pickup,
    create_pickup_payload,
)

OP = TEST_USERS["zone_operator_headers"]
DRV = TEST_USERS["driver_headers"]


class TestBagKitLifecycle:
    def test_kit_full_lifecycle_valid_transitions(self, api):
        """PRD §3.2: "A `ZoneOperator` dispatches the kit, transitioning it from
        `REQUESTED` to `DISPATCHED`. A `Driver` confirms hand-off by marking it
        delivered, transitioning it from `DISPATCHED` to `DELIVERED`. Either the
        owning resident or a `ZoneOperator` can retire a delivered kit, moving it
        from `DELIVERED` to `RETIRED`"

        Design: Corner/state_machines/kit_full_lifecycle_valid_transitions
        """
        zone = new_zone("Zone SM1")
        resident = new_resident(zone["id"], "Tess T", "tess@x.com")
        kit = order_kit(resident["id"], "BIN")
        assert kit["status"] == "REQUESTED"

        kit = validate_success(api_client.dispatch_bag_kit(kit["id"], OP))
        assert kit["status"] == "DISPATCHED"

        kit = validate_success(api_client.deliver_bag_kit(kit["id"], DRV))
        assert kit["status"] == "DELIVERED"

        kit = validate_success(
            api_client.retire_bag_kit(kit["id"], make_resident_headers(resident["id"]))
        )
        assert kit["status"] == "RETIRED"

    def test_kit_deliver_from_requested_rejected(self, api):
        """PRD §3.2: "Each step requires the kit to be in the expected prior state
        and is otherwise rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/kit_deliver_from_requested_rejected
        """
        zone = new_zone("Zone SM2")
        resident = new_resident(zone["id"], "Uma U", "uma@x.com")
        kit = order_kit(resident["id"], "BAG")

        resp = api_client.deliver_bag_kit(kit["id"], DRV)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        kits, _ = validate_paginated(api_client.list_resident_bag_kits(resident["id"], OP))
        assert kits[0]["status"] == "REQUESTED", "kit must remain REQUESTED after the rejected deliver"

    def test_kit_limit_third_active_rejected(self, api):
        """PRD §3.2: "The resident must be `ACTIVE` and may have at most one other
        kit still in flight: the count of the resident's kits currently in
        `REQUESTED`, `DISPATCHED`, or `DELIVERED` must remain below two, otherwise
        the order is rejected with `ERR_KIT_LIMIT_EXCEEDED`."

        Design: Corner/validations/kit_limit_third_active_rejected
        """
        zone = new_zone("Zone V3")
        resident = new_resident(zone["id"], "Joy J", "joy@x.com")
        order_kit(resident["id"], "BAG")
        kit2 = order_kit(resident["id"], "BIN")
        dispatch_kit(kit2["id"])

        resp = api_client.order_bag_kit(
            resident["id"], {"kit_type": "BAG"}, make_resident_headers(resident["id"])
        )
        validate_error(resp, ApiErrorId.ERR_KIT_LIMIT_EXCEEDED)


class TestPickupCreation:
    def test_pickup_est_weight_computed_not_input(self, api):
        """PRD §3.3: "The server derives `est_weight_kg` by multiplying
        `bags_claimed` by 4.0 — four kilograms per bag, exact to one decimal
        place — and uses this estimate for route-day capacity planning."
        PRD §3.3: "The new pickup starts in `SCHEDULED` with `reschedule_count`
        and `rebook_count` both at 0, and with `driver_id` and `service_date` unset."

        Design: Corner/entities/pickup_est_weight_computed_not_input
        """
        zone = new_zone("Zone E2")
        resident = new_resident(zone["id"], "Pia Pell", "pia@x.com")
        pickup = new_pickup(
            resident["id"], "2026-05-10T10:00:00Z", "2026-05-10T12:00:00Z", 7
        )
        assert pickup["est_weight_kg"] == pytest.approx(28.0), (
            f"7 bags * 4.0 kg = 28.0, got {pickup['est_weight_kg']}"
        )
        assert pickup["status"] == "SCHEDULED"
        assert pickup["reschedule_count"] == 0 and pickup["rebook_count"] == 0
        assert pickup["driver_id"] is None and pickup["service_date"] is None

    def test_immediate_read_after_write_consistency(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.3: "The server derives `est_weight_kg` by multiplying `bags_claimed`
        by 4.0 — four kilograms per bag, exact to one decimal place — and uses
        this estimate for route-day capacity planning."

        Design: Corner/consistency_model/immediate_read_after_write_consistency
        """
        zone = new_zone("Zone CM1")
        resident = new_resident(zone["id"], "Bo B", "bo@x.com")
        created = new_pickup(resident["id"], bags_claimed=7)
        assert created["est_weight_kg"] == pytest.approx(28.0)
        assert created["status"] == "SCHEDULED"

        fetched = get_success_data(api_client.get_pickup_request(created["id"], OP))
        assert fetched["est_weight_kg"] == pytest.approx(28.0)
        assert fetched["status"] == "SCHEDULED"

    def test_create_pickup_missing_required_returns_invalid_request(self, api):
        """PRD §3.3: "A resident schedules a `PickupRequest` against their own
        record, supplying `resident_id` (which must equal their `X-User-ID`), a
        `window_start` and `window_end` defining the pickup window in ISO 8601
        UTC, and `bags_claimed`, the number of bags or bins they intend to leave
        out."
        PRD §2.11: "The order is: (1) authentication of the headers, (2) role
        authorization and entity-backed ownership, (3) request well-formedness
        (required fields present, no undeclared fields, types and enum membership
        and numeric ranges valid)"

        Design: Corner/entities/create_pickup_missing_required_returns_invalid_request
        """
        zone = new_zone("Zone E3")
        resident = new_resident(zone["id"], "Quinn Q", "quinn@x.com")
        payload = {
            "resident_id": resident["id"],
            "window_start": "2026-05-10T10:00:00Z",
            "window_end": "2026-05-10T12:00:00Z",
        }
        resp = api_client.create_pickup_request(payload, make_resident_headers(resident["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_pickup_extra_field_rejected(self, api):
        """PRD §2.11: "The order is: (1) authentication of the headers, (2) role
        authorization and entity-backed ownership, (3) request well-formedness
        (required fields present, no undeclared fields, types and enum membership
        and numeric ranges valid)"
        PRD §3.3: "The new pickup starts in `SCHEDULED` with `reschedule_count`
        and `rebook_count` both at 0, and with `driver_id` and `service_date` unset."

        Design: Corner/entities/create_pickup_extra_field_rejected
        """
        zone = new_zone("Zone E6")
        resident = new_resident(zone["id"], "Rosa R", "rosa@x.com")
        payload = create_pickup_payload(resident["id"], bags_claimed=2)
        payload["driver_id"] = "drv-x"  # system-managed field, not client input
        resp = api_client.create_pickup_request(payload, make_resident_headers(resident["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_window_in_past_rejected(self, api):
        """PRD §3.3: "The `window_start` must not be earlier than the current
        logical clock; otherwise the create is rejected with `ERR_WINDOW_IN_PAST`
        (HTTP 422)."
        PRD §2.10: "The server starts with the logical clock fixed at exactly
        `2026-05-01T00:00:00Z`, and the clock never falls back to wall-clock time
        thereafter."

        Design: Corner/validations/window_in_past_rejected
        """
        zone = new_zone("Zone V1")
        resident = new_resident(zone["id"], "Hal H", "hal@x.com")
        payload = create_pickup_payload(
            resident["id"],
            window_start="2026-04-01T10:00:00Z", window_end="2026-04-01T12:00:00Z",
            bags_claimed=2,
        )
        resp = api_client.create_pickup_request(payload, make_resident_headers(resident["id"]))
        validate_error(resp, ApiErrorId.ERR_WINDOW_IN_PAST)

    def test_window_too_short_rejected(self, api):
        """PRD §3.3: "The window's duration must be at least 60 minutes and at
        most 240 minutes; a window whose `window_end` is not after `window_start`,
        or whose length falls outside that range, is rejected with
        `ERR_INVALID_WINDOW` (HTTP 422)."

        Design: Corner/validations/window_too_short_rejected
        """
        zone = new_zone("Zone V2")
        resident = new_resident(zone["id"], "Ira I", "ira@x.com")
        payload = create_pickup_payload(
            resident["id"],
            window_start="2026-05-10T10:00:00Z", window_end="2026-05-10T10:30:00Z",
            bags_claimed=2,
        )
        resp = api_client.create_pickup_request(payload, make_resident_headers(resident["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)


class TestWindowBuffer:
    def test_exact_thirty_minute_gap_permitted(self, api):
        """PRD §3.3: "A gap of exactly thirty minutes between two windows is
        permitted and does not constitute a conflict; anything tighter is
        rejected with `ERR_PICKUP_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/resident_window_thirty_minute_buffer
        """
        zone = new_zone("Zone TO1")
        resident = new_resident(zone["id"], "Lena Loh", "lena@x.com")
        new_pickup(resident["id"], "2026-05-10T10:00:00Z", "2026-05-10T12:00:00Z", 2)

        resp = api_client.create_pickup_request(
            create_pickup_payload(
                resident["id"],
                window_start="2026-05-10T12:30:00Z", window_end="2026-05-10T14:00:00Z",
                bags_claimed=2,
            ),
            make_resident_headers(resident["id"]),
        )
        p2 = validate_success(resp, 201)
        assert p2["status"] == "SCHEDULED", "gap of exactly 30 minutes must be admitted"

    def test_twenty_nine_minute_gap_conflicts(self, api):
        """PRD §3.3: "The window must also not conflict with any of the resident's
        other pickups currently in `SCHEDULED` or `ROUTED`: a conflict exists when
        the new window's start is earlier than the existing window's end plus a
        thirty-minute buffer AND the existing window's start is earlier than the
        new window's end plus the same thirty-minute buffer. A gap of exactly
        thirty minutes between two windows is permitted and does not constitute a
        conflict; anything tighter is rejected with `ERR_PICKUP_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/resident_window_thirty_minute_buffer
        """
        zone = new_zone("Zone TO1")
        resident = new_resident(zone["id"], "Lena Loh", "lena@x.com")
        new_pickup(resident["id"], "2026-05-10T10:00:00Z", "2026-05-10T12:00:00Z", 2)
        new_pickup(resident["id"], "2026-05-10T12:30:00Z", "2026-05-10T14:00:00Z", 2)

        resp = api_client.create_pickup_request(
            create_pickup_payload(
                resident["id"],
                window_start="2026-05-10T12:29:00Z", window_end="2026-05-10T13:29:00Z",
                bags_claimed=2,
            ),
            make_resident_headers(resident["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PICKUP_WINDOW_CONFLICT)


def test_list_pagination_defaults_envelope(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return and defaults to 10 when omitted; the minimum accepted value is 1 and
    the maximum accepted value is 100. The `offset` parameter specifies the number
    of items to skip before collecting the page and defaults to 0."
    PRD §2.3: "Paginated responses include `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the success envelope."

    Design: Corner/endpoints/list_pagination_defaults_envelope
    """
    zone = new_zone("Zone EP1")
    resident = new_resident(zone["id"], "Pat P", "pat@x.com")
    new_pickup(resident["id"], "2026-05-10T10:00:00Z", "2026-05-10T12:00:00Z", 1)
    new_pickup(resident["id"], "2026-05-11T10:00:00Z", "2026-05-11T12:00:00Z", 2)

    data, meta = validate_paginated(api_client.list_resident_pickup_requests(resident["id"], OP))
    assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']}"
    assert meta["offset"] == 0
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert isinstance(data, list) and len(data) == 2
