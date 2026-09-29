"""The credential-revoke withdrawal cascade and the pinned nightly maintenance sweep."""

from typing import Any, Dict

import pytest
from test_helpers import (
    TEST_USERS,
    add_all_credentials,
    add_credential,
    assert_ledger_memos,
    assert_ledger_sequence,
    assert_maintenance_counters,
    confirm_reservation,
    create_capacity_block,
    create_provider,
    create_reservation,
    match_reservation,
    read_capacity_block,
    read_employee,
    read_entitlement,
    read_provider,
    read_provider_credentials,
    read_reservation,
    read_reservation_ledger,
    revoke_credential_payload,
    run_credential_review,
    set_clock,
    setup_confirmed_reservation,
    setup_enrolled_employee,
    validate_success,
)

NETWORK_ADMIN = TEST_USERS["network_admin"]

CASCADE_PLAN = {"annual_use_limit_days": 10, "copay_center_cents_per_day": 1500}
SWEEP_PLAN = {
    "annual_use_limit_days": 10,
    "copay_center_cents_per_day": 1500,
    "no_show_charge_cents": 12000,
}


class TestCredentialRevokeCascade:
    """One revoke, four consequences: credential, provider, reservation, ledger and block."""

    @staticmethod
    def _withdrawn_world(api) -> Dict[str, Any]:
        world = setup_confirmed_reservation(
            api,
            care_start_utc="2026-08-10T09:00:00Z",
            care_end_utc="2026-08-10T15:00:00Z",
            block_start_utc="2026-08-10T08:00:00Z",
            block_end_utc="2026-08-10T18:00:00Z",
            market_code="MKT-SEA",
            total_slots=4,
            dependent_count=2,
            plan_overrides=dict(CASCADE_PLAN),
        )
        world["block_before"] = read_capacity_block(api, world["block"]["id"])
        world["revoked_credential"] = validate_success(
            api.revoke_credential(
                world["credentials"]["CPR"]["id"],
                revoke_credential_payload(revoked_reason_code="CPR_CERTIFICATION_LAPSED"),
                NETWORK_ADMIN,
            )
        )
        return world

    def test_revoking_a_required_credential_suspends_the_provider(self, api):
        """Levels one and two: the credential turns REVOKED and the posture follows.

        PRD 3.3: "a `network_admin` revoking a required credential, the nightly
        maintenance sweep detecting that a required credential has lapsed, a
        `network_admin` naming `SUSPENDED` as `target_status`, or a substantiated
        incident carrying a `qa_action` of `SUSPENSION`."

        Design: Difficulty/transitive_cascade/credential_revoke_cascades_credential_provider_reservation_ledger_block
        """
        world = self._withdrawn_world(api)

        assert world["reservation"]["days_charged_provisional"] == pytest.approx(2, abs=0.01)
        assert world["reservation"]["copay_cents"] == 3000
        assert world["block_before"]["reserved_slots"] == 2

        assert world["revoked_credential"]["status"] == "REVOKED"
        assert world["revoked_credential"]["revoked_reason_code"] == "CPR_CERTIFICATION_LAPSED"

        provider = read_provider(api, world["provider"]["id"])
        assert provider["network_status"] == "SUSPENDED"

        credentials = read_provider_credentials(api, world["provider"]["id"])
        by_type = {row["credential_type"]: row for row in credentials}
        assert by_type["CPR"]["status"] == "REVOKED"
        assert by_type["LICENSE"]["status"] == "VALID"

    def test_the_withdrawn_reservation_is_rewound_to_matching(self, api):
        """Level three: every provisional charge field goes back to its intake value.

        PRD 3.3: "clears `matched_provider_id`, `matched_capacity_block_id` and
        `confirmation_code` to null; resets `days_charged_provisional`, `covered_days`,
        `overage_days`, `copay_cents` and `overage_cents` to 0 and
        `overage_tier_multiplier` to 1; leaves `billing_status` untouched at
        `NOT_BILLABLE`"

        Design: Difficulty/transitive_cascade/credential_revoke_cascades_credential_provider_reservation_ledger_block
        """
        world = self._withdrawn_world(api)

        reservation = read_reservation(api, world["reservation"]["id"])
        assert reservation["fulfillment_status"] == "MATCHING"
        assert reservation["matched_provider_id"] is None
        assert reservation["matched_capacity_block_id"] is None
        assert reservation["confirmation_code"] is None
        assert reservation["days_charged_provisional"] == pytest.approx(0, abs=0.01)
        assert reservation["covered_days"] == pytest.approx(0, abs=0.01)
        assert reservation["overage_days"] == pytest.approx(0, abs=0.01)
        assert reservation["copay_cents"] == 0
        assert reservation["overage_cents"] == 0
        assert reservation["overage_tier_multiplier"] == pytest.approx(1, abs=0.01)
        assert reservation["billing_status"] == "NOT_BILLABLE"

    def test_the_withdrawal_never_bars_the_provider_from_a_later_offer(self, api):
        """The exclusion list stays empty, unlike a rejected offer.

        PRD 3.3: "does **not** append the withdrawn provider to `excluded_provider_ids`,
        so the same provider may legitimately be offered again if it returns to the
        network before the care date."

        Design: Difficulty/transitive_cascade/credential_revoke_cascades_credential_provider_reservation_ledger_block
        """
        world = self._withdrawn_world(api)

        reservation = read_reservation(api, world["reservation"]["id"])
        assert reservation["excluded_provider_ids"] == []

    def test_level_four_releases_the_days_and_the_seats(self, api):
        """A single appended RELEASE row hands back both the days and the block seats.

        PRD 3.3: "That per-reservation move appends a `UsageLedgerEntry` of type
        `RELEASE` whose `days_delta` is the negation of `days_charged_provisional`, with
        `cents_delta` zero and `memo` `PROVIDER_WITHDRAWN`"

        Design: Difficulty/transitive_cascade/credential_revoke_cascades_credential_provider_reservation_ledger_block
        """
        world = self._withdrawn_world(api)

        ledger = read_reservation_ledger(api, world["reservation"]["id"])
        assert_ledger_sequence(ledger, ["RESERVE", "RELEASE"])
        assert_ledger_memos(ledger, ["CONFIRM", "PROVIDER_WITHDRAWN"])
        assert ledger[0]["days_delta"] == pytest.approx(2, abs=0.01)
        assert ledger[1]["days_delta"] == pytest.approx(-2, abs=0.01)
        assert all(row["cents_delta"] == 0 for row in ledger)

        employee = read_employee(api, world["employee"]["id"])
        assert employee["entitlement_days_reserved"] == pytest.approx(0, abs=0.01)
        assert employee["entitlement_days_used"] == pytest.approx(0, abs=0.01)

        block = read_capacity_block(api, world["block"]["id"])
        assert block["reserved_slots"] == 0
        assert block["block_status"] == "OPEN"
        assert block["version"] == world["block_before"]["version"] + 1


class TestNightlyMaintenanceSweep:
    """One sweep at 2026-08-16T00:00:00Z fires every clock-driven edge exactly once."""

    @staticmethod
    def _sweep_world(api) -> Dict[str, Any]:
        world = setup_enrolled_employee(api, plan_overrides=dict(SWEEP_PLAN))
        provider = create_provider(
            api, provider_name="Sweep Order Center", market_code="MKT-CMH", postal_code="43215"
        )
        license_credential = add_credential(
            api, provider["id"], "LICENSE", expires_on="2026-08-15"
        )
        add_all_credentials(
            api,
            provider["id"],
            expires_on="2027-06-30",
            types=["BACKGROUND_CHECK", "CPR", "INSURANCE"],
        )
        reviewed = run_credential_review(api, provider["id"])
        assert reviewed["network_status"] == "CREDENTIALED"

        served_block = create_capacity_block(
            api, provider["id"], "2026-08-05T08:00:00Z", "2026-08-05T18:00:00Z", total_slots=4
        )

        # PRD 3.5 candidate filter: a provider only survives when, for each required
        # type, it holds a VALID credential whose expires_on is on or after the
        # reservation's care_date.  The lapsing provider above can therefore never be
        # offered the 2026-08-30 window, so the offer that must survive the sweep is
        # published by a second, fully credentialed provider in the same market.
        late_provider = create_provider(
            api, provider_name="Sweep Late Center", market_code="MKT-CMH", postal_code="43215"
        )
        add_all_credentials(api, late_provider["id"], expires_on="2027-06-30")
        assert run_credential_review(api, late_provider["id"])["network_status"] == "CREDENTIALED"
        late_block = create_capacity_block(
            api, late_provider["id"], "2026-08-30T08:00:00Z", "2026-08-30T18:00:00Z", total_slots=4
        )

        no_show_bound = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            "2026-08-05T09:00:00Z",
            "2026-08-05T15:00:00Z",
            market_code="MKT-CMH",
        )
        match_reservation(api, no_show_bound["id"])
        no_show_bound = confirm_reservation(api, no_show_bound["id"], served_block["id"])

        stale_intake = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            "2026-08-10T09:00:00Z",
            "2026-08-10T15:00:00Z",
            market_code="MKT-CMH",
        )
        offered = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            "2026-08-30T09:00:00Z",
            "2026-08-30T15:00:00Z",
            market_code="MKT-CMH",
        )
        # PRD 3.5: offer_expires_at is the clock at generation plus 48 hours, capped at
        # care_start_utc.  Matching from 2026-08-15 therefore leaves this offer alive
        # through the 2026-08-16 sweep, so the one offer step four expires is the
        # stale batch generated back at 2026-08-01.
        set_clock(api, "2026-08-15T00:00:00Z")
        offered = match_reservation(api, offered["id"])
        assert offered["fulfillment_status"] == "OFFERED"

        set_clock(api, "2026-08-16T00:00:00Z")
        world.update(
            {
                "provider": provider,
                "late_provider": late_provider,
                "license_credential": license_credential,
                "served_block": served_block,
                "late_block": late_block,
                "no_show_bound": no_show_bound,
                "stale_intake": stale_intake,
                "offered": offered,
            }
        )
        return world

    def test_one_sweep_fires_each_of_the_six_steps_exactly_once(self, api):
        """Step two sees step one's expiry, and step four sees step three's survivors.

        PRD 3.9: "Step two suspends every provider that, after step one, no longer holds
        a `VALID` credential of all four required types and whose `network_status` is
        `CREDENTIALED` or `PROBATION`, each such suspension running its full withdrawal
        cascade over that provider's future confirmed reservations."

        Design: Corner/endpoints/corner_daily_maintenance_sweeps_six_steps_in_pinned_order
        """
        world = self._sweep_world(api)

        counters = validate_success(api.run_daily_maintenance(NETWORK_ADMIN))
        assert_maintenance_counters(counters)
        assert counters["credentials_expired"] == 1
        assert counters["providers_suspended"] == 1
        assert counters["reservations_unfulfilled"] == 1
        assert counters["offers_expired"] == 1
        assert counters["blocks_closed"] == 1
        assert counters["reservations_no_showed"] == 1
        assert counters["reservations_withdrawn"] == 0

        credentials = {
            row["credential_type"]: row
            for row in read_provider_credentials(api, world["provider"]["id"])
        }
        assert credentials["LICENSE"]["status"] == "EXPIRED"
        assert read_provider(api, world["provider"]["id"])["network_status"] == "SUSPENDED"

        stale = read_reservation(api, world["stale_intake"]["id"])
        assert stale["fulfillment_status"] == "UNFULFILLED"
        assert stale["unfulfilled_reason_code"] == "CARE_WINDOW_ELAPSED"

        missed = read_reservation(api, world["no_show_bound"]["id"])
        assert missed["fulfillment_status"] == "NO_SHOW"
        assert missed["billing_status"] == "ACCRUED"
        assert missed["penalty_cents"] == 12000
        assert missed["covered_days"] == pytest.approx(1, abs=0.01)

        assert read_capacity_block(api, world["served_block"]["id"])["block_status"] == "CLOSED"
        assert read_capacity_block(api, world["late_block"]["id"])["block_status"] == "OPEN"

    def test_a_second_identical_sweep_changes_nothing(self, api):
        """Every clock-driven edge has already fired, so all seven counters read zero.

        PRD 3.9: "The sweep reports what it did through seven counters:
        `credentials_expired`, `providers_suspended`, `reservations_unfulfilled`,
        `offers_expired`, `blocks_closed`, `reservations_no_showed` and
        `reservations_withdrawn`."

        Design: Corner/endpoints/corner_daily_maintenance_sweeps_six_steps_in_pinned_order
        """
        world = self._sweep_world(api)
        validate_success(api.run_daily_maintenance(NETWORK_ADMIN))

        again = validate_success(api.run_daily_maintenance(NETWORK_ADMIN))
        assert_maintenance_counters(again)
        assert all(value == 0 for value in again.values())

        projection = read_entitlement(api, world["employee"]["id"])
        assert projection["days_used"] == pytest.approx(1, abs=0.01)
        assert projection["days_reserved"] == pytest.approx(0, abs=0.01)
        assert projection["no_show_strike_count"] == 1
        assert projection["eligibility_status"] == "ELIGIBLE"

        still_offered = read_reservation(api, world["offered"]["id"])
        assert still_offered["fulfillment_status"] == "OFFERED"
