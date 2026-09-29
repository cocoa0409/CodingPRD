"""Inclusive thresholds and zero-cardinality aggregates, pinned from both sides."""

import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import assert_field_values, assert_row_count
from test_helpers.fixtures import (
    create_active_credential,
    create_holder,
    create_profile,
    open_address_change,
    set_clock,
)
from test_helpers.test_users import ADMIN, PRIVACY_AUDITOR


def _lost_handset_world(api):
    """An ACTIVE credential whose handset is reported lost at the clock epoch."""
    profile = create_profile(api, revocation_freshness_seconds=300)
    bundle = create_active_credential(api, profile=profile)
    validate_success(api.report_device_lost(bundle["device"]["id"], ADMIN))
    return bundle


class TestRevocationFreshnessIsInclusiveAtTheProfileWindow:
    """A staleness of exactly the profile window is still fresh."""

    @pytest.mark.parametrize(
        "probe_instant,expected_staleness,expected_freshness",
        [
            ("2026-08-01T00:04:59Z", 299, True),
            ("2026-08-01T00:05:00Z", 300, True),
            ("2026-08-01T00:05:01Z", 301, False),
        ],
    )
    def test_freshness_flips_only_after_the_window_is_passed(
        self, api, probe_instant, expected_staleness, expected_freshness
    ):
        """299 and 300 seconds are fresh; 301 seconds is not.

        PRD 3.6: "an `is_fresh` verdict that is true when `staleness_seconds` is
        at most the profile's `revocation_freshness_seconds` - the comparison is
        inclusive, so a staleness of exactly 300 seconds against the default
        profile is still fresh."

        Design: Difficulty/boundary_precision_check/revocation_freshness_inclusive_at_exactly_300_seconds
        """
        bundle = _lost_handset_world(api)
        set_clock(api, probe_instant)

        reading = validate_success(
            api.get_revocation_status(bundle["credential"]["id"], PRIVACY_AUDITOR)
        )
        assert reading["staleness_seconds"] == expected_staleness
        assert reading["is_fresh"] is expected_freshness

    def test_the_replayed_entry_identity_is_stable_across_the_boundary(self, api):
        """Only the freshness verdict moves with the clock; the replayed status,
        the newest sequence and its effective instant do not.

        PRD 3.6: "The credential's revocation-status read reports the replayed
        `status`, the `entry_sequence` of the newest entry (zero when there are
        none), that entry's `effective_at`, a `staleness_seconds` measuring the
        whole seconds elapsed from that entry's `effective_at` to the current
        logical instant with any fraction discarded"

        Design: Difficulty/boundary_precision_check/revocation_freshness_inclusive_at_exactly_300_seconds
        """
        bundle = _lost_handset_world(api)

        for probe in (
            "2026-08-01T00:04:59Z",
            "2026-08-01T00:05:00Z",
            "2026-08-01T00:05:01Z",
        ):
            set_clock(api, probe)
            reading = validate_success(
                api.get_revocation_status(bundle["credential"]["id"], PRIVACY_AUDITOR)
            )
            assert_field_values(
                reading,
                {
                    "status": "SUSPENDED",
                    "entry_sequence": 1,
                    "effective_at": "2026-08-01T00:00:00Z",
                },
            )


class TestUpdateOrderWithNoChildrenClosesImmediately:
    """Zero deliveries is a first-class COMPLETED outcome, not an open order."""

    def test_order_is_completed_and_stamped_inside_the_same_request(self, api):
        """An address change for a holder with no live credential returns an
        order already COMPLETED with closed_at set.

        PRD 3.5: "an address change for a resident who holds no credential in
        `ACTIVE` or `SUSPENDED` still produces a real order, which the rollup
        immediately closes as `COMPLETED` inside the very same request, with
        `closed_at` set. The order transitions `OPEN` -> `COMPLETED` before the
        client ever sees it."

        Design: Difficulty/boundary_precision_check/update_order_with_zero_deliveries_closes_completed_immediately
        """
        create_profile(api)
        holder = create_holder(api)

        order = open_address_change(
            api,
            holder["id"],
            address_line1="402 Birch Lane",
            city="Waverly",
            state_code="NE",
            postal_code="68462",
        )
        assert_field_values(
            order,
            {
                "status": "COMPLETED",
                "delivery_count": 0,
                "delivered_count": 0,
                "failed_count": 0,
                "closed_at": "2026-08-01T00:00:00Z",
            },
        )

    def test_no_delivery_row_exists_and_the_address_version_advanced(self, api):
        """The empty order pins the holder's post-increment address version and
        opened no children at all.

        PRD 3.5: "`target_address_version` is what each order pins so that a
        delivery landing later cannot claim to have synced data it never
        carried. For an address change it is the holder's `address_version`
        **after** the increment"

        Design: Difficulty/boundary_precision_check/update_order_with_zero_deliveries_closes_completed_immediately
        """
        create_profile(api)
        holder = create_holder(api)

        order = open_address_change(api, holder["id"])
        assert order["target_address_version"] == 2

        assert_row_count(api.list_order_deliveries(order["id"], ADMIN), 0)
        refreshed = validate_success(api.get_holder(holder["id"], ADMIN))
        assert refreshed["address_version"] == 2
