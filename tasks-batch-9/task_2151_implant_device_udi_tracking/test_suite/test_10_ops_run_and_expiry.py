"""The operational checkpoint: contract expiry, stock sweeps and alerts."""

from test_helpers import (
    IL,
    assert_lot_conservation,
    assert_ops_run_payload,
    assert_same_instant,
    get_case,
    get_catalog_item,
    get_lot,
    get_unit,
    ops_run,
    reserve_unit,
    set_clock,
    setup_scheduled_case,
    setup_stock,
    validate_paginated,
    validate_success,
)

ANCHOR_CATALOG = {
    "device_identifier": "00812345678967",
    "description": "Bioabsorbable Anchor",
    "category": "STANDARD_IMPLANT",
    "list_charge_cents": 120_000,
    "charge_code": "CDM-77200",
    "shelf_life_days": 400,
}


def _expiring_stock_world():
    """One released lot expiring 2026-09-30 holding two owned units; SN-0001 is
    reserved to a SCHEDULED case and SN-0002 is left AVAILABLE."""
    world = setup_stock(
        (90_000, 90_000),
        catalog_overrides=ANCHOR_CATALOG,
        lot_overrides={"lot_number": "L-8801", "expiration_date": "2026-09-30"},
    )
    case = setup_scheduled_case(
        case_number="CASE-9",
        or_room_code="OR-8",
        scheduled_start_utc="2026-09-20T08:00:00Z",
        scheduled_end_utc="2026-09-20T10:00:00Z",
        surgeon_code="SURG-3",
    )["case"]
    reserve_unit(case["id"], world["units"][0]["id"])
    world["case"] = case
    return world


class TestExpirySweepCascade:
    def test_the_sweep_expires_the_lot_and_every_unit_on_it(self, api):
        """PRD §3.11: "The second rule sweeps expired stock in a three-deep cascade.
        Every lot whose `status` is `QUARANTINE` or `AVAILABLE` and whose expiry
        instant — its `expiration_date` at 23:59:59.999Z — is at or before the
        logical clock moves to `EXPIRED` and adds one to `expired_lot_count`. For
        each unit on such a lot, a unit in `QUARANTINED` or `AVAILABLE` moves to
        `EXPIRED` with `expired_at_utc` stamped from the logical clock and adds one
        to `expired_unit_count`."
        PRD §3.11: "Each swept lot then has its `on_hand_qty` and `consumed_qty`
        re-derived, which in turn re-derives the catalog item's
        `on_hand_available_qty`."

        Design: Difficulty/transitive_cascade/ops_run_expiry_three_hop_cascade
        """
        world = _expiring_stock_world()
        set_clock("2026-10-01T00:00:00Z")

        report = ops_run()
        assert_ops_run_payload(report)
        assert report["expired_lot_count"] == 1
        assert report["expired_unit_count"] == 2
        assert report["expired_agreement_count"] == 0
        assert report["rotation_alert_count"] == 0
        assert report["ops_run_index"] == 1

        lot = get_lot(world["lot"]["id"])
        assert lot["status"] == "EXPIRED"
        assert lot["received_qty"] == 2
        assert lot["on_hand_qty"] == 0
        assert lot["consumed_qty"] == 2
        assert_lot_conservation(lot)
        assert get_catalog_item(world["catalog_item"]["id"])["on_hand_available_qty"] == 0

    def test_a_reserved_unit_is_detached_and_its_case_is_blocked(self, api):
        """PRD §3.11: "A unit in `RESERVED` is treated differently but is **not**
        spared: it is first detached from its case by clearing `reserved_case_id`,
        then moved to `EXPIRED` with `expired_at_utc` stamped and counted in
        `expired_unit_count` too, and the detachment adds one to
        `detached_reservation_count` and increments that case's
        `blocked_reservation_count` by one, which in turn re-derives that case's
        `readiness_status` to `BLOCKED_RESERVATION`."

        Design: Difficulty/transitive_cascade/ops_run_expiry_three_hop_cascade
        """
        world = _expiring_stock_world()
        set_clock("2026-10-01T00:00:00Z")

        report = ops_run()
        assert report["detached_reservation_count"] == 1

        detached = get_unit(world["units"][0]["id"])
        assert detached["custody_state"] == "EXPIRED"
        assert detached["reserved_case_id"] is None
        assert get_unit(world["units"][1]["id"])["custody_state"] == "EXPIRED"

        case = get_case(world["case"]["id"])
        assert case["blocked_reservation_count"] == 1
        assert case["readiness_status"] == "BLOCKED_RESERVATION"


class TestExpiryInstantBoundary:
    def test_one_millisecond_before_the_expiry_instant_sweeps_nothing(self, api):
        """PRD §3.2: "That calendar date is not itself an instant, and the
        distinction matters for every expiry comparison in this document: **the
        expiry instant of a lot is its `expiration_date` at 23:59:59.999Z**, so a
        lot dated for today is still good for the whole of today."
        PRD §3.11: "The third rule is a rotation alert and mutates nothing:
        `rotation_alert_count` is the number of device units whose `custody_state` is
        `AVAILABLE` and whose lot's expiry instant falls at or after the logical
        clock and at or before the logical clock plus 45 days — the stock that ought
        to be moved to the front of the shelf before it is written off."

        Design: Difficulty/boundary_precision_check/lot_expiry_end_of_day_instant_boundary_on_ops_run
        """
        world = setup_stock(
            (90_000,),
            catalog_overrides=ANCHOR_CATALOG,
            lot_overrides={"lot_number": "L-8801", "expiration_date": "2026-09-30"},
        )

        set_clock("2026-09-30T23:59:59.998Z")
        report = ops_run()
        assert report["expired_lot_count"] == 0
        assert report["expired_unit_count"] == 0
        assert report["rotation_alert_count"] == 1
        assert report["ops_run_index"] == 1

        assert get_lot(world["lot"]["id"])["status"] == "AVAILABLE"
        assert get_unit(world["units"][0]["id"])["custody_state"] == "AVAILABLE"

    def test_the_expiry_instant_itself_sweeps_the_lot_and_stamps_the_unit(self, api):
        """PRD §3.11: "Every lot whose `status` is `QUARANTINE` or `AVAILABLE` and
        whose expiry instant — its `expiration_date` at 23:59:59.999Z — is at or
        before the logical clock moves to `EXPIRED` and adds one to
        `expired_lot_count`. For each unit on such a lot, a unit in `QUARANTINED` or
        `AVAILABLE` moves to `EXPIRED` with `expired_at_utc` stamped from the
        logical clock and adds one to `expired_unit_count`."
        PRD §3.11: "The response reports all eight figures — `ops_run_index`,
        `expired_agreement_count`, `expired_lot_count`, `expired_unit_count`,
        `detached_reservation_count`, `rotation_alert_count`,
        `escalated_notification_count` and `overdue_submission_count` — where
        `ops_run_index` is the number of checkpoints executed so far in this
        server's life, so that the very first one answers 1."

        Design: Difficulty/boundary_precision_check/lot_expiry_end_of_day_instant_boundary_on_ops_run
        """
        world = setup_stock(
            (90_000,),
            catalog_overrides=ANCHOR_CATALOG,
            lot_overrides={"lot_number": "L-8801", "expiration_date": "2026-09-30"},
        )

        set_clock("2026-09-30T23:59:59.998Z")
        ops_run()

        set_clock("2026-09-30T23:59:59.999Z")
        report = ops_run()
        assert report["expired_lot_count"] == 1
        assert report["expired_unit_count"] == 1
        assert report["ops_run_index"] == 2

        assert get_lot(world["lot"]["id"])["status"] == "EXPIRED"
        unit = get_unit(world["units"][0]["id"])
        assert unit["custody_state"] == "EXPIRED"
        assert_same_instant(
            unit["expired_at_utc"], "2026-09-30T23:59:59.999Z", "expired_at_utc"
        )


class TestQuietCheckpoint:
    def test_the_epoch_counter_advances_on_an_empty_system(self, api):
        """PRD §3.11: "The response reports all eight figures — `ops_run_index`,
        `expired_agreement_count`, `expired_lot_count`, `expired_unit_count`,
        `detached_reservation_count`, `rotation_alert_count`,
        `escalated_notification_count` and `overdue_submission_count` — where
        `ops_run_index` is the number of checkpoints executed so far in this
        server's life, so that the very first one answers 1."
        PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
        `total_count` and `has_more`, where `total_count` is the number of rows
        matching the filters before pagination is applied and `has_more` is true
        when rows remain beyond the current window."

        Design: Corner/endpoints/ops_run_index_increments_and_reports_zero_counts_on_a_quiet_system
        """
        rows, meta = validate_paginated(api.list_vendors(IL, {"limit": 10, "offset": 0}))
        assert rows == []
        assert meta["total_count"] == 0
        assert meta["has_more"] is False

        first = validate_success(api.create_ops_run(IL), 200)
        assert_ops_run_payload(first)
        assert first["ops_run_index"] == 1
        for key in (
            "expired_agreement_count",
            "expired_lot_count",
            "expired_unit_count",
            "detached_reservation_count",
            "rotation_alert_count",
            "escalated_notification_count",
            "overdue_submission_count",
        ):
            assert first[key] == 0, f"{key} must be 0 on a quiet system"

        second = validate_success(api.create_ops_run(IL), 200)
        assert second["ops_run_index"] == 2
        for key in (
            "expired_agreement_count",
            "expired_lot_count",
            "expired_unit_count",
            "detached_reservation_count",
            "rotation_alert_count",
            "escalated_notification_count",
            "overdue_submission_count",
        ):
            assert second[key] == 0
