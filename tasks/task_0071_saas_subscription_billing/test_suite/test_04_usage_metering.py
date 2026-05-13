"""Usage ingestion: idempotency, late-arrival window, quota tracking.

PRD §3.7.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    PA,
    advance_clock,
    get_subscription,
    ingest_usage,
    ingest_usage_payload,
    list_usage,
    make_tenant_admin_headers,
    setup_active_subscription,
    unique_idempotency_key,
    validate_error,
    validate_success,
)


# ===========================================================================
# Usage ingestion (PRD §3.7)
# ===========================================================================
class TestUsageIngestion:

    # DELETED: test_ingest_usage_increments_quota_consumed
    # Per PRD-First unique-derivability check: PRD §3.7 says
    #   'The subscription's quota_consumed[metric] is incremented by
    #    quantity' (metric values per §3.7 are API_CALL, STORAGE_GB, ...)
    # while PRD §2.12, §3.5, and §3.9 use lowercase-plural keys
    # ('api_calls', 'seats', etc.) for the same map. PRD §3.1 explicitly
    # names included_quotas keys as 'api_calls', 'storage_gb', etc. —
    # which §3.9's bill total calculation pairs with quota_consumed under
    # the same key. A faithful PRD reader could therefore store this map
    # under either casing scheme; the rule is not uniquely determined.

    def test_negative_quantity_rejected(self, api):
        """PRD §3.7: 'negative quantities are rejected with
        ERR_INVALID_USAGE_QUANTITY.'"""
        tenant, _pkg, sub = setup_active_subscription()
        res = api.ingest_usage(
            tenant["id"], sub["id"],
            ingest_usage_payload(metric="API_CALL", quantity=-1),
            make_tenant_admin_headers(tenant["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_USAGE_QUANTITY.value)

    def test_idempotent_replay_returns_existing_record(self, api):
        """PRD §3.7: 'submitting the same key with an identical body
        returns the originally persisted record with HTTP 201.'"""
        tenant, _pkg, sub = setup_active_subscription()
        sub_fresh = get_subscription(tenant, sub)
        key = unique_idempotency_key()
        payload = ingest_usage_payload(
            idempotency_key=key, metric="API_CALL", quantity=5,
            event_timestamp=sub_fresh["cycle_start"],
        )
        headers = make_tenant_admin_headers(tenant["id"])
        first = api.ingest_usage(tenant["id"], sub["id"], payload, headers)
        data_first = validate_success(first, 201)
        # Identical payload re-submission
        second = api.ingest_usage(tenant["id"], sub["id"], payload, headers)
        data_second = validate_success(second, 201)
        assert data_first["id"] == data_second["id"], (
            "PRD §3.7: identical replay must return the originally "
            "persisted record."
        )

    def test_conflicting_idempotency_key_rejected(self, api):
        """PRD §3.7: 'a conflicting body yields
        ERR_DUPLICATE_USAGE_IDEMPOTENCY_KEY.'"""
        tenant, _pkg, sub = setup_active_subscription()
        sub_fresh = get_subscription(tenant, sub)
        key = unique_idempotency_key()
        headers = make_tenant_admin_headers(tenant["id"])
        first_payload = ingest_usage_payload(
            idempotency_key=key, metric="API_CALL", quantity=10,
            event_timestamp=sub_fresh["cycle_start"],
        )
        validate_success(api.ingest_usage(
            tenant["id"], sub["id"], first_payload, headers,
        ), 201)
        # Conflicting body: same key, different quantity
        conflicting_payload = ingest_usage_payload(
            idempotency_key=key, metric="API_CALL", quantity=999,
            event_timestamp=sub_fresh["cycle_start"],
        )
        res = api.ingest_usage(
            tenant["id"], sub["id"], conflicting_payload, headers,
        )
        validate_error(
            res, ApiErrorId.ERR_DUPLICATE_USAGE_IDEMPOTENCY_KEY.value,
        )


# ===========================================================================
# Late-arrival window (PRD §3.7)
# ===========================================================================
class TestLateArrivalWindow:

    def test_event_older_than_seven_day_window_rejected(self, api):
        """PRD §3.7: 'The window for accepting late-arriving events is
        seven days: an event_timestamp earlier than the current
        cycle_start minus seven days is rejected with
        ERR_USAGE_TOO_LATE.'"""
        tenant, _pkg, sub = setup_active_subscription()
        sub_fresh = get_subscription(tenant, sub)
        cycle_start = sub_fresh["cycle_start"]
        # 8 days before cycle_start — clearly outside the 7-day window.
        from datetime import datetime, timedelta, timezone
        cs = datetime.fromisoformat(cycle_start.replace("Z", "+00:00"))
        too_early = cs - timedelta(days=8)
        too_early_iso = too_early.strftime(
            "%Y-%m-%dT%H:%M:%S.") + f"{too_early.microsecond // 1000:03d}Z"
        res = api.ingest_usage(
            tenant["id"], sub["id"],
            ingest_usage_payload(
                metric="API_CALL", quantity=1,
                event_timestamp=too_early_iso,
            ),
            make_tenant_admin_headers(tenant["id"]),
        )
        validate_error(res, ApiErrorId.ERR_USAGE_TOO_LATE.value)
