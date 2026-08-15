"""Hazard flags: TTL merge/renew/expiry and stop-level safety cascades.

Covers PRD section 3.5 plus the hazard-related capture gates of sections
2.10 and 3.3.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_iso_instant_equal,
    create_hazard_flag_payload,
    get_hazard_flag,
    get_stop,
    make_field_technician_headers,
    report_hazard,
    run_ops_snapshot,
    set_logical_clock,
    setup_account_with_installed_meter,
    setup_in_progress_route,
    skip_stop_for_hazard_as,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["meter_ops_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestHazardMerge:
    def _merge_scenario(self, api):
        """DOG flag reported at 2026-08-01T09:00, re-reported at
        2026-08-06T09:00. Returns (account, first_flag, merge_response)."""
        set_logical_clock("2026-08-01T09:00:00Z")
        account, _meter = setup_account_with_installed_meter(
            "A-9101", "C20", service_address="61 Poplar St"
        )
        tech = validate_success(
            api.create_field_technician({"display_name": "Tech Eleven"}, ADMIN), 201
        )
        first = validate_success(
            api.report_hazard_flag(
                create_hazard_flag_payload(account["id"], hazard_type="DOG", severity="HIGH"),
                make_field_technician_headers(tech["id"]),
            ),
            201,
        )
        set_logical_clock("2026-08-06T09:00:00Z")
        merge_res = api.report_hazard_flag(
            create_hazard_flag_payload(account["id"], hazard_type="DOG", severity="LOW"),
            make_field_technician_headers(tech["id"]),
        )
        return account, first, merge_res

    def test_hazard_rereport_merges_returns_same_flag(self, api):
        """PRD section 3.5: "Repeat reporting merges rather than duplicates.
        When a report arrives for an account and hazard type that already has
        an `ACTIVE` flag, no second row is created: the existing flag's
        `expires_at` is pushed out to the later of its current `expires_at`
        and thirty days from now, its `renewed_count` is incremented by one,
        and the call returns 200 with the existing flag (a genuinely fresh
        report returns 201)."

        Design: Difficulty/resource_temporal_overlap/hazard_rereport_merges_interval_and_extends_expiry
        """
        account, first, merge_res = self._merge_scenario(api)
        merged = validate_success(merge_res, 200)  # merge returns 200, not 201
        assert merged["id"] == first["id"]
        assert merged["renewed_count"] == 1
        # the merge does not overwrite the original report's severity
        assert merged["severity"] == "HIGH"

        _data, meta = validate_paginated(
            api.list_hazard_flags(DISPATCHER, params={"service_account_id": account["id"]})
        )
        assert meta["total_count"] == 1

    def test_hazard_merge_extends_expiry_to_max(self, api):
        """PRD section 3.5: "Repeat reporting merges rather than duplicates.
        When a report arrives for an account and hazard type that already has
        an `ACTIVE` flag, no second row is created: the existing flag's
        `expires_at` is pushed out to the later of its current `expires_at`
        and thirty days from now, its `renewed_count` is incremented by one,
        and the call returns 200 with the existing flag (a genuinely fresh
        report returns 201)."

        Design: Difficulty/resource_temporal_overlap/hazard_rereport_merges_interval_and_extends_expiry
        """
        _account, first, merge_res = self._merge_scenario(api)
        # 2026-08-01T09:00 + 30 days
        assert_iso_instant_equal(first["expires_at"], "2026-08-31T09:00:00Z")
        merged = validate_success(merge_res, 200)
        # max(2026-08-31T09:00, 2026-08-06T09:00 + 30 days) = 2026-09-05T09:00
        assert_iso_instant_equal(merged["expires_at"], "2026-09-05T09:00:00Z")


class TestHazardExpiryAndRenew:
    def test_hazard_flag_expire_then_renew_rejected(self, api):
        """PRD section 3.5: "Explicit renewal works the same way — renewing an
        `ACTIVE` flag refreshes `expires_at` to thirty days from now (keeping
        the existing `expires_at` if it is later) and increments
        `renewed_count` — but renewing a flag already `EXPIRED` or `CLEARED`
        is rejected with `ERR_HAZARD_FLAG_NOT_ACTIVE` (HTTP 409)."
        PRD section 3.5: "Expiry is the system's act: at each operations
        checkpoint, the sweep examines `ACTIVE` flags in ascending
        `expires_at` order and expires any flag whose `expires_at` is strictly
        earlier than the snapshot instant; a flag whose `expires_at` equals
        the snapshot instant survives it and remains `ACTIVE`."

        Design: Corner/state_machines/hazard_flag_expire_then_renew_rejected
        """
        set_logical_clock("2026-08-01T09:00:00Z")
        account, _meter = setup_account_with_installed_meter(
            "C-0037", "C37", service_address="37 Expire Ln"
        )
        tech = validate_success(
            api.create_field_technician({"display_name": "Expire Tech"}, ADMIN), 201
        )
        flag = report_hazard(account["id"], tech["id"], hazard_type="DOG", severity="HIGH")

        # expires_at 2026-08-31T09:00 is strictly earlier than this snapshot
        run_ops_snapshot("2026-08-31T09:00:01Z")
        assert get_hazard_flag(flag["id"])["flag_status"] == "EXPIRED"

        res = api.renew_hazard_flag(flag["id"], make_field_technician_headers(tech["id"]))
        validate_error(res, ApiErrorId.ERR_HAZARD_FLAG_NOT_ACTIVE.value, 409)

    def test_hazard_expiry_uses_strict_greater_than(self, api):
        """PRD section 3.9: "`ACTIVE` flags are examined in ascending
        `expires_at` order, and each flag whose `expires_at` is strictly
        earlier than `snapshot_at` transitions to `EXPIRED`, firing the
        hazard-skip revert cascade wherever no other active flag remains on
        the account; equality with `snapshot_at` keeps the flag active."

        Design: Corner/calculations/hazard_expiry_uses_strict_greater_than
        """
        set_logical_clock("2026-08-01T09:00:00Z")
        account, _meter = setup_account_with_installed_meter(
            "C-0057", "C57", service_address="57 Ttl Ave"
        )
        tech = validate_success(
            api.create_field_technician({"display_name": "TTL Tech"}, ADMIN), 201
        )
        flag = report_hazard(
            account["id"], tech["id"], hazard_type="CHEMICAL", severity="HIGH"
        )

        # Snapshot exactly at expires_at: the flag survives.
        run_ops_snapshot("2026-08-31T09:00:00Z")
        assert get_hazard_flag(flag["id"])["flag_status"] == "ACTIVE"

        # One second past expires_at: expired.
        run_ops_snapshot("2026-08-31T09:00:01Z")
        assert get_hazard_flag(flag["id"])["flag_status"] == "EXPIRED"


class TestHazardSkipRevertCascade:
    def test_hazard_clear_reverts_skipped_stop_and_second_flag_blocks_revert(self, api):
        """PRD section 3.5: "Resolution releases stranded stops. When a flag
        clears or expires and no other `ACTIVE` hazard flag remains on the
        account, every stop of that account sitting in `SKIPPED_HAZARD` and
        citing this flag reverts to `PENDING` with its `hazard_flag_id`
        cleared to null — provided the stop's route is `ASSIGNED` or
        `IN_PROGRESS`."

        Design: Corner/state_machines/hazard_clear_reverts_skipped_stop_and_second_flag_blocks_revert
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        account, meter = setup_account_with_installed_meter(
            "C-0038", "C38", service_address="38 Revert Ln"
        )
        period, route, stops, tech = setup_in_progress_route(
            "C38",
            "2026-08-01",
            "2026-08-31",
            "2026-08-03",
            "2026-08-07",
            "2026-08-31",
            "2026-08-03",
            open_clock="2026-08-03T08:00:00Z",
            tech_name="Revert Tech",
        )
        stop = stops[0]
        flag_dog = report_hazard(account["id"], tech["id"], hazard_type="DOG", severity="HIGH")
        flag_acc = report_hazard(
            account["id"], tech["id"], hazard_type="ACCESS", severity="LOW"
        )
        skip_stop_for_hazard_as(stop["id"], flag_dog["id"], tech["id"])
        assert get_stop(stop["id"])["stop_status"] == "SKIPPED_HAZARD"

        # Clearing the uncited flag while the cited DOG flag remains ACTIVE:
        # the "no other ACTIVE hazard flag remains" gate fails, so no revert.
        validate_success(api.clear_hazard_flag(flag_acc["id"], DISPATCHER), 200)
        assert get_stop(stop["id"])["stop_status"] == "SKIPPED_HAZARD"

        # Clearing the cited flag with no other ACTIVE flag remaining reverts it.
        validate_success(api.clear_hazard_flag(flag_dog["id"], DISPATCHER), 200)
        stop_after = get_stop(stop["id"])
        assert stop_after["stop_status"] == "PENDING"
        assert stop_after["hazard_flag_id"] is None


class TestSkipHazardGate:
    def test_skip_hazard_with_cleared_flag_rejected(self, api):
        """PRD section 3.3: "Skipping for hazard moves a `PENDING` stop to
        `SKIPPED_HAZARD` citing a `hazard_flag_id`; that flag must be an
        `ACTIVE` hazard flag on this stop's own account, or the skip is
        rejected with `ERR_SKIP_REQUIRES_ACTIVE_HAZARD` (HTTP 409) — citing
        another account's flag fails the same way."

        Design: Corner/validations/skip_hazard_with_cleared_flag_rejected
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        account, meter = setup_account_with_installed_meter(
            "C-0083", "C83", service_address="83 Skip Rd"
        )
        tech = validate_success(
            api.create_field_technician({"display_name": "Skip Tech"}, ADMIN), 201
        )
        flag = report_hazard(account["id"], tech["id"], hazard_type="DOG", severity="LOW")
        validate_success(api.clear_hazard_flag(flag["id"], DISPATCHER), 200)

        period, route, stops, tech2 = setup_in_progress_route(
            "C83",
            "2026-08-01",
            "2026-08-31",
            "2026-08-03",
            "2026-08-07",
            "2026-08-31",
            "2026-08-03",
            open_clock="2026-08-03T08:00:00Z",
            tech_name="Skip Tech",
        )
        stop = stops[0]
        res = api.skip_hazard(
            stop["id"],
            {"hazard_flag_id": flag["id"]},
            make_field_technician_headers(tech2["id"]),
        )
        validate_error(res, ApiErrorId.ERR_SKIP_REQUIRES_ACTIVE_HAZARD.value, 409)
        assert get_stop(stop["id"])["stop_status"] == "PENDING"
