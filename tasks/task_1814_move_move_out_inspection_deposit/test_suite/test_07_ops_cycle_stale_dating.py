"""Daily ops cycle: stale-dating cascade and the strictly-greater threshold."""
import test_helpers as th
from test_helpers import (
    api_client,
    get_disbursement,
    get_success_data,
    get_tenancy,
    make_manager_admin_headers,
    make_property_manager_headers,
    setup_refund_sent,
    validate_success,
)

ADMIN = make_manager_admin_headers()
PM = make_property_manager_headers()


class TestDailyCycleStaleDatingCascade:
    def test_stale_flip_releases_reservation(self):
        """PRD §2.5: "When a `ManagerAdmin` triggers the daily cycle, the
        system examines every disbursement still in `SENT` status and flips
        each one whose `sent_at` plus the governing jurisdiction's
        `stale_check_days` falls strictly before the logical clock — equality
        alone does not stale-date a check — to `STALE_DATED`, voiding the
        uncashed check. Each flip releases that disbursement's reservation:
        the owning tenancy's `reserved_cents` is decremented by the check
        amount and its `balance_remaining_cents` is recomputed. The sweep
        response reports how many checks were voided as `stale_dated_count`
        and lists their identifiers as `stale_dated_disbursement_ids`."

        SENT at 2026-08-10, stale_check_days 180 => threshold 2027-02-06; at
        clock 2027-02-20 the cycle flips the check: count 1, status
        STALE_DATED, reserved 0, balance back to 149,337.

        Design: Difficulty/transitive_cascade/daily_cycle_stale_dating_cascade_depth2
        """
        ctx = setup_refund_sent()
        disb = ctx["disbursement"]
        ten_id = ctx["tenancy"]["id"]
        ten_reserved = get_tenancy(ten_id)
        assert ten_reserved["reserved_cents"] == 149_337
        assert ten_reserved["balance_remaining_cents"] == 0

        api_client.set_clock({"to_iso8601": "2027-02-20T00:00:00Z"}, ADMIN)
        cycle = validate_success(api_client.run_daily_cycle(ADMIN))
        assert cycle["stale_dated_count"] == 1, (
            f"exactly one check is stale, got {cycle['stale_dated_count']}"
        )
        assert disb["id"] in cycle["stale_dated_disbursement_ids"]
        assert get_disbursement(disb["id"])["status"] == "STALE_DATED"
        ten = get_tenancy(ten_id)
        assert ten["reserved_cents"] == 0
        assert ten["balance_remaining_cents"] == 149_337, (
            f"the flip releases the reservation: 200000 + 9337 - 60000 = 149337, "
            f"got {ten['balance_remaining_cents']}"
        )

    def test_flip_is_caused_by_cycle_not_disbursement_call(self):
        """PRD §2.5: "The daily operational checkpoint is an explicit,
        admin-driven sweep rather than a background timer." and "Each flip
        releases that disbursement's reservation: the owning tenancy's
        `reserved_cents` is decremented by the check amount and its
        `balance_remaining_cents` is recomputed."

        Before the cycle runs (clock already past the threshold) the check is
        still SENT and reserved still held; only the explicit cycle flips it.

        Design: Difficulty/transitive_cascade/daily_cycle_stale_dating_cascade_depth2
        """
        ctx = setup_refund_sent()
        disb = ctx["disbursement"]
        ten_id = ctx["tenancy"]["id"]
        api_client.set_clock({"to_iso8601": "2027-02-20T00:00:00Z"}, ADMIN)
        # No cycle yet: nothing flips by itself.
        assert get_disbursement(disb["id"])["status"] == "SENT"
        assert get_tenancy(ten_id)["reserved_cents"] == 149_337
        validate_success(api_client.run_daily_cycle(ADMIN))
        assert get_disbursement(disb["id"])["status"] == "STALE_DATED"
        assert get_tenancy(ten_id)["balance_remaining_cents"] == 149_337


class TestStaleThresholdBoundary:
    def test_exact_threshold_day_not_stale_next_day_stale(self):
        """PRD §2.5: "flips each one whose `sent_at` plus the governing
        jurisdiction's `stale_check_days` falls strictly before the logical
        clock — equality alone does not stale-date a check".

        sent_at 2026-08-10 + 180 days = 2027-02-06: at exactly that clock the
        cycle flips nothing; one day later (2027-02-07) it flips the check
        and releases the 149,337c reservation.

        Design: Corner/complexity_layers/stale_check_exact_threshold_day_not_stale
        """
        ctx = setup_refund_sent()
        disb = ctx["disbursement"]
        ten_id = ctx["tenancy"]["id"]

        api_client.set_clock({"to_iso8601": "2027-02-06T00:00:00Z"}, ADMIN)
        cycle0 = validate_success(api_client.run_daily_cycle(ADMIN))
        assert cycle0["stale_dated_count"] == 0, (
            "exactly at sent_at + stale_check_days must NOT stale-date "
            "(strictly-greater rule)"
        )
        assert get_disbursement(disb["id"])["status"] == "SENT"

        api_client.set_clock({"to_iso8601": "2027-02-07T00:00:00Z"}, ADMIN)
        cycle1 = validate_success(api_client.run_daily_cycle(ADMIN))
        assert cycle1["stale_dated_count"] == 1
        assert get_disbursement(disb["id"])["status"] == "STALE_DATED"
        ten = get_tenancy(ten_id)
        assert ten["reserved_cents"] == 0
        assert ten["balance_remaining_cents"] == 149_337
