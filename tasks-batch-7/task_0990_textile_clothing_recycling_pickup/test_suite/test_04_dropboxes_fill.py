"""Drop boxes: fill readings (append-only), posture thresholds, collection cycle."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    new_zone, new_dropbox, post_reading, read_dropbox, collect_box,
    create_fill_reading_payload, mark_collected_payload,
    DEFAULT_CLOCK_ISO,
)

OP = TEST_USERS["zone_operator_headers"]
SENSOR = TEST_USERS["sensor_gateway_headers"]
DRV = TEST_USERS["driver_headers"]


def test_fill_reading_immutable_event_shape(api):
    """PRD §2.4: "`FillReading` is the deliberate exception. A fill reading is an
    append-only event sourced from a sensor and is never mutated after ingestion.
    It carries only `id` and `created_at`; `updated_at` and `version` are absent
    from this entity and the API never returns them on a fill-reading payload."
    PRD §3.4: "a fill of at least 85.0 transitions the box to
    `FULL_PENDING_COLLECTION`, a fill of at least 50.0 but below 85.0 places it at
    `FILLING`, and anything below 50.0 returns it to `OK`."

    Design: Corner/entities/fill_reading_immutable_event_shape
    """
    zone = new_zone("Zone E5")
    box = new_dropbox(zone["id"], "Box-1", "Depot")

    resp = api_client.create_fill_reading(
        box["id"], create_fill_reading_payload(fill_pct=20.0, recorded_at="2026-05-01T06:00:00Z"),
        SENSOR,
    )
    reading = validate_success(resp, 201)
    assert reading["id"] and reading["created_at"]
    assert "version" not in reading, "fill readings never carry version"
    assert "updated_at" not in reading, "fill readings never carry updated_at"

    box = read_dropbox(box["id"])
    assert box["fill_pct"] == pytest.approx(20.0)
    assert box["posture"] == "OK"


def test_fill_pct_out_of_range_rejected(api):
    """PRD §3.4: "The `fill_pct` must lie between 0 and 100 inclusive; anything
    else is rejected as `ERR_INVALID_REQUEST`."
    PRD §3.4: "a fill of at least 85.0 transitions the box to
    `FULL_PENDING_COLLECTION`"

    Design: Corner/entities/fill_pct_out_of_range_rejected
    """
    zone = new_zone("Zone E7")
    box = new_dropbox(zone["id"], "Box-2", "Depot")

    resp = api_client.create_fill_reading(
        box["id"], create_fill_reading_payload(fill_pct=100.5, recorded_at="2026-05-01T06:00:00Z"),
        SENSOR,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    ok = validate_success(api_client.create_fill_reading(
        box["id"], create_fill_reading_payload(fill_pct=100.0, recorded_at="2026-05-01T07:00:00Z"),
        SENSOR,
    ), 201)
    assert ok["fill_pct"] == pytest.approx(100.0)
    assert read_dropbox(box["id"])["posture"] == "FULL_PENDING_COLLECTION"


class TestFillThreshold85:
    def test_84_99_stays_filling(self, api):
        """PRD §3.4: "The boundary at 85.0 is inclusive — exactly 85.0 flips the
        box to `FULL_PENDING_COLLECTION`, while 84.99 does not — and the same
        applies to the 50.0 boundary."

        Design: Difficulty/boundary_precision_check/dropbox_fill_threshold_85_inclusive
        """
        zone = new_zone("Zone BP1")
        box = new_dropbox(zone["id"], "Box-17", "Maple St")
        assert box["posture"] == "OK"

        post_reading(box["id"], 84.99, "2026-05-02T00:00:00Z")
        box = read_dropbox(box["id"])
        assert box["fill_pct"] == pytest.approx(84.99)
        assert box["posture"] == "FILLING", "84.99 is below the inclusive 85.0 boundary"

    def test_exactly_85_flips_to_full_pending_collection(self, api):
        """PRD §3.4: "The boundary at 85.0 is inclusive — exactly 85.0 flips the
        box to `FULL_PENDING_COLLECTION`, while 84.99 does not — and the same
        applies to the 50.0 boundary."

        Design: Difficulty/boundary_precision_check/dropbox_fill_threshold_85_inclusive
        """
        zone = new_zone("Zone BP1")
        box = new_dropbox(zone["id"], "Box-17", "Maple St")
        post_reading(box["id"], 84.99, "2026-05-02T00:00:00Z")
        post_reading(box["id"], 85.0, "2026-05-02T01:00:00Z")
        box = read_dropbox(box["id"])
        assert box["fill_pct"] == pytest.approx(85.0)
        assert box["posture"] == "FULL_PENDING_COLLECTION", "exactly 85.0 crosses the inclusive boundary"


def test_dropbox_fill_collect_cycle_returns_ok(api):
    """PRD §3.4: "On success the box's `fill_pct` resets to 0, its `posture`
    returns to `OK`, its `last_collected_at` is set to the current logical clock,
    and a new `WeightTicket` is created with `source_type` set to `DROPBOX`,
    `source_id` set to the box's `id`, `status` set to `PROVISIONAL`, and
    `projected_credit_cents` computed per the provisional variant described in
    §3.5."
    PRD §2.10: "The server starts with the logical clock fixed at exactly
    `2026-05-01T00:00:00Z`, and the clock never falls back to wall-clock time
    thereafter."

    Design: Corner/state_machines/dropbox_fill_collect_cycle_returns_ok
    """
    zone = new_zone("Zone SM8")
    box = new_dropbox(zone["id"], "Box-9", "Mall lot")
    post_reading(box["id"], 90.0, "2026-05-01T06:00:00Z")
    assert read_dropbox(box["id"])["posture"] == "FULL_PENDING_COLLECTION"

    ticket = collect_box(box["id"], 55.0)
    assert ticket["source_type"] == "DROPBOX"
    assert ticket["source_id"] == box["id"]
    assert ticket["status"] == "PROVISIONAL"

    box = read_dropbox(box["id"])
    assert box["posture"] == "OK"
    assert box["fill_pct"] == pytest.approx(0)
    assert box["last_collected_at"] is not None and box["last_collected_at"].startswith(
        "2026-05-01T00:00:00"
    ), f"last_collected_at must read the default logical clock, got {box['last_collected_at']}"


def test_collection_from_ok_box_rejected(api):
    """PRD §3.4: "The server rejects the call with `ERR_DROPBOX_NOT_FULL` if the
    box's posture is not `FULL_PENDING_COLLECTION`."

    Design: Corner/state_machines/collection_from_ok_box_rejected
    """
    zone = new_zone("Zone SM9")
    box = new_dropbox(zone["id"], "Box-10", "Library")

    resp = api_client.create_dropbox_collection(
        box["id"], mark_collected_payload(provisional_weight_kg=10.0), DRV
    )
    validate_error(resp, ApiErrorId.ERR_DROPBOX_NOT_FULL)

    tickets, meta = validate_paginated(api_client.list_dropbox_weight_tickets(box["id"], OP))
    assert tickets == [] and meta["total_count"] == 0, "no ticket may be created by the rejected collection"
