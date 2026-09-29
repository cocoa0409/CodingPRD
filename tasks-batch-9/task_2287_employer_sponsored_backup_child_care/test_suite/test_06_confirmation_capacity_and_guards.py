"""Confirmation: the guard order, seat and buffer admission, and the write set."""

from typing import Any, Dict

import pytest
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_block_seats_reconcile,
    confirm_payload,
    confirm_reservation,
    create_capacity_block,
    create_dependent,
    create_employee,
    create_reservation,
    match_reservation,
    read_capacity_block,
    read_entitlement,
    read_offers_for_reservation,
    read_reservation,
    read_reservation_ledger,
    set_clock,
    set_network_status,
    setup_enrolled_employee,
    setup_provider_with_block,
    validate_error,
    validate_success,
)

NETWORK_ADMIN = TEST_USERS["network_admin"]
CARE_COORDINATOR = TEST_USERS["care_coordinator"]


def _confirm_response(api, reservation_id: str, block_id: str, version: int = None):
    """Raw confirm call, so a refusal can be inspected instead of unwrapped."""
    resolved = version if version is not None else read_capacity_block(api, block_id)["version"]
    return api.confirm_reservation(
        reservation_id, confirm_payload(block_id, resolved), CARE_COORDINATOR
    )


class TestConfirmSideEffects:
    def test_confirmation_mints_a_code_and_closes_the_losing_offer(self, api):
        """One confirm writes the block, the code, the money and the ledger row.

        PRD 3.6: "It sets `matched_capacity_block_id` to the named block and mints a
        `confirmation_code` as the family's care reference."

        Design: Corner/state_machines/corner_confirm_side_effects_mint_code_and_expire_sibling_offers
        """
        world = setup_enrolled_employee(api, dependent_count=1)
        high = setup_provider_with_block(
            api,
            "2026-08-11T08:00:00Z",
            "2026-08-11T18:00:00Z",
            total_slots=4,
            provider_name="Liberty Bell Center",
            owner_user_id="u_pm_hi",
            market_code="MKT-PHL",
            postal_code="19103",
            daily_capacity_slots=4,
        )
        low = setup_provider_with_block(
            api,
            "2026-08-11T08:00:00Z",
            "2026-08-11T18:00:00Z",
            total_slots=1,
            provider_name="Fishtown Small Center",
            owner_user_id="u_pm_lo",
            market_code="MKT-PHL",
            postal_code="19125",
            daily_capacity_slots=1,
        )
        reservation = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            "2026-08-11T09:00:00Z",
            "2026-08-11T15:00:00Z",
            market_code="MKT-PHL",
        )

        matched = match_reservation(api, reservation["id"])
        assert matched["fulfillment_status"] == "OFFERED"
        assert matched["matched_provider_id"] == high["provider"]["id"]

        confirmed = confirm_reservation(
            api, reservation["id"], high["block"]["id"], block_version=high["block"]["version"]
        )
        assert confirmed["fulfillment_status"] == "CONFIRMED"
        assert isinstance(confirmed["confirmation_code"], str)
        assert confirmed["confirmation_code"] != ""
        assert confirmed["matched_capacity_block_id"] == high["block"]["id"]
        assert confirmed["days_charged_provisional"] == pytest.approx(1, abs=0.01)
        assert confirmed["covered_days"] == pytest.approx(1, abs=0.01)
        assert confirmed["overage_days"] == pytest.approx(0, abs=0.01)
        assert confirmed["copay_cents"] == 1500
        assert confirmed["overage_cents"] == 0
        assert confirmed["overage_tier_multiplier"] == pytest.approx(1, abs=0.01)

        offers = read_offers_for_reservation(api, reservation["id"])
        assert len(offers) == 2
        winner = [o for o in offers if o["provider_id"] == high["provider"]["id"]][0]
        loser = [o for o in offers if o["provider_id"] == low["provider"]["id"]][0]
        assert winner["offer_status"] == "SELECTED"
        assert winner["reason_code"] is None
        assert loser["offer_status"] == "EXPIRED"
        assert loser["reason_code"] == "CONFIRMED_ELSEWHERE"

        block = read_capacity_block(api, high["block"]["id"])
        assert block["version"] == high["block"]["version"] + 1
        assert_block_seats_reconcile(block, 1, 0)
        assert block["block_status"] == "OPEN"
        assert_block_seats_reconcile(read_capacity_block(api, low["block"]["id"]), 0, 0)

        ledger = read_reservation_ledger(api, reservation["id"])
        assert len(ledger) == 1
        assert ledger[0]["entry_type"] == "RESERVE"
        assert ledger[0]["days_delta"] == pytest.approx(1, abs=0.01)
        assert ledger[0]["cents_delta"] == 0
        assert ledger[0]["memo"] == "CONFIRM"
        assert read_entitlement(api, world["employee"]["id"])["days_reserved"] == pytest.approx(
            1, abs=0.01
        )


class TestConfirmGuardBattery:
    def test_the_guard_band_separates_six_refusals_code_by_code(self, api):
        """Containment, offer status, one-a-day, the fiscal cap, network and same-day.

        PRD 3.6: "Last come the safety gates: the provider must hold a `VALID`
        credential of each of the four required types that does not expire before the
        `care_date` (`ERR_PROVIDER_NOT_CREDENTIALED`); its `network_status` must be
        `CREDENTIALED` or `PROBATION`, with `PENDING`, `SUSPENDED` and
        `DEPROVISIONED` all refused as `ERR_PROVIDER_NOT_IN_NETWORK`; and when the
        `care_date` is the logical clock's own UTC date, the provider's
        `same_day_available` must be true (`ERR_SAME_DAY_UNAVAILABLE`)."

        Design: Corner/errors/corner_confirm_guard_error_battery
        """
        hard_cap = {"overage_billing_enabled": False}
        w1 = setup_enrolled_employee(
            api,
            dependent_count=2,
            employer_overrides=hard_cap,
            plan_overrides={"annual_use_limit_days": 2},
            user_id="u_ee_gb1",
        )
        w2 = setup_enrolled_employee(
            api,
            dependent_count=1,
            employer_overrides=hard_cap,
            plan_overrides={"annual_use_limit_days": 1},
            user_id="u_ee_gb2",
        )
        w3 = setup_enrolled_employee(
            api,
            dependent_count=2,
            employer_overrides=hard_cap,
            plan_overrides={"annual_use_limit_days": 1},
            user_id="u_ee_gb3",
        )

        ok = setup_provider_with_block(
            api,
            "2026-08-07T08:00:00Z",
            "2026-08-07T14:00:00Z",
            total_slots=4,
            provider_name="Reno Same Day Center",
            owner_user_id="u_pm_r1",
            market_code="MKT-RNO",
            postal_code="89501",
            daily_capacity_slots=4,
            same_day_available=True,
        )
        morning = ok["block"]
        evening = create_capacity_block(
            api, ok["provider"]["id"], "2026-08-07T15:00:00Z", "2026-08-07T20:00:00Z", total_slots=4
        )
        next_day = create_capacity_block(
            api, ok["provider"]["id"], "2026-08-08T08:00:00Z", "2026-08-08T18:00:00Z", total_slots=4
        )
        setup_provider_with_block(
            api,
            "2026-08-07T09:00:00Z",
            "2026-08-07T13:00:00Z",
            total_slots=1,
            provider_name="Reno Overflow Center",
            owner_user_id="u_pm_r3",
            market_code="MKT-RNO",
            postal_code="89503",
            daily_capacity_slots=1,
            same_day_available=True,
        )
        no_same_day = setup_provider_with_block(
            api,
            "2026-08-02T08:00:00Z",
            "2026-08-02T18:00:00Z",
            total_slots=4,
            provider_name="Reno Booked Ahead Center",
            owner_user_id="u_pm_r2",
            market_code="MKT-RNO",
            postal_code="89502",
            daily_capacity_slots=4,
            same_day_available=False,
        )

        # A window the matched block covers, confirmed against a block that does not.
        r_out = create_reservation(
            api,
            w1["employee"]["id"],
            [w1["dependent_ids"][0]],
            "2026-08-07T09:00:00Z",
            "2026-08-07T13:00:00Z",
            market_code="MKT-RNO",
        )
        matched = match_reservation(api, r_out["id"])
        assert matched["matched_provider_id"] == ok["provider"]["id"]
        response = _confirm_response(api, r_out["id"], evening["id"], evening["version"])
        validate_error(response, ApiErrorId.ERR_WINDOW_OUTSIDE_BLOCK.value)
        assert response.status_code == 409
        assert read_reservation(api, r_out["id"])["fulfillment_status"] == "OFFERED"

        confirmed = confirm_reservation(api, r_out["id"], morning["id"])
        assert confirmed["fulfillment_status"] == "CONFIRMED"
        assert confirmed["covered_days"] == pytest.approx(1, abs=0.01)

        # A second reservation for the same employee on the same care date.
        r_dup = create_reservation(
            api,
            w1["employee"]["id"],
            [w1["dependent_ids"][1]],
            "2026-08-07T10:00:00Z",
            "2026-08-07T12:00:00Z",
            market_code="MKT-RNO",
        )
        match_reservation(api, r_dup["id"])
        proposed = [
            offer
            for offer in read_offers_for_reservation(api, r_dup["id"])
            if offer["offer_status"] == "PROPOSED"
        ]
        assert len(proposed) == 1
        not_selected = api.reject_offer(
            r_dup["id"],
            {"match_offer_id": proposed[0]["id"], "reason_code": "NOT_SELECTED_OFFER"},
            CARE_COORDINATOR,
        )
        validate_error(not_selected, ApiErrorId.ERR_OFFER_NOT_SELECTED.value)
        assert not_selected.status_code == 409

        duplicate = _confirm_response(api, r_dup["id"], morning["id"])
        validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_CARE_DATE.value)
        assert duplicate.status_code == 409

        # An employer that bought a hard cap refuses the day that would overflow.
        r3a = create_reservation(
            api,
            w3["employee"]["id"],
            [w3["dependent_ids"][0]],
            "2026-08-07T09:00:00Z",
            "2026-08-07T13:00:00Z",
            market_code="MKT-RNO",
        )
        match_reservation(api, r3a["id"])
        assert confirm_reservation(api, r3a["id"], morning["id"])["covered_days"] == pytest.approx(
            1, abs=0.01
        )
        r3b = create_reservation(
            api,
            w3["employee"]["id"],
            [w3["dependent_ids"][1]],
            "2026-08-08T09:00:00Z",
            "2026-08-08T13:00:00Z",
            market_code="MKT-RNO",
        )
        match_reservation(api, r3b["id"])
        overage = _confirm_response(api, r3b["id"], next_day["id"])
        validate_error(overage, ApiErrorId.ERR_OVERAGE_NOT_PERMITTED.value)
        assert overage.status_code == 409

        # Booked a day ahead, confirmed once the clock has reached the care date.
        r_sd = create_reservation(
            api,
            w2["employee"]["id"],
            w2["dependent_ids"],
            "2026-08-02T10:00:00Z",
            "2026-08-02T14:00:00Z",
            market_code="MKT-RNO",
        )
        matched_sd = match_reservation(api, r_sd["id"])
        assert matched_sd["matched_provider_id"] == no_same_day["provider"]["id"]

        set_clock(api, "2026-08-02T06:00:00Z")
        same_day = _confirm_response(api, r_sd["id"], no_same_day["block"]["id"])
        validate_error(same_day, ApiErrorId.ERR_SAME_DAY_UNAVAILABLE.value)
        assert same_day.status_code == 409

        # A suspension between the match and the confirm.
        r_net = create_reservation(
            api,
            w2["employee"]["id"],
            w2["dependent_ids"],
            "2026-08-08T09:00:00Z",
            "2026-08-08T13:00:00Z",
            market_code="MKT-RNO",
        )
        matched_net = match_reservation(api, r_net["id"])
        assert matched_net["matched_provider_id"] == ok["provider"]["id"]
        suspended = set_network_status(
            api, ok["provider"]["id"], "SUSPENDED", reason_code="QA_HOLD"
        )
        assert suspended["network_status"] == "SUSPENDED"

        not_in_network = _confirm_response(api, r_net["id"], next_day["id"])
        validate_error(not_in_network, ApiErrorId.ERR_PROVIDER_NOT_IN_NETWORK.value)
        assert not_in_network.status_code == 409

        # The suspension cascade rewound the confirmed future reservation.
        rewound = read_reservation(api, r_out["id"])
        assert rewound["fulfillment_status"] == "MATCHING"
        assert [row["entry_type"] for row in read_reservation_ledger(api, r_out["id"])] == [
            "RESERVE",
            "RELEASE",
        ]
        assert_block_seats_reconcile(read_capacity_block(api, morning["id"]), 0, 0)


class TestStaleCapacityBlockVersion:
    def test_a_stale_block_token_is_a_412_even_with_seats_to_spare(self, api):
        """Three of four seats free, and the second confirm still fails.

        PRD 2.6: "If that value differs from the block's current `version`, the
        confirmation is rejected with `ERR_STALE_CAPACITY_BLOCK_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/corner_stale_capacity_block_version_blocks_second_confirm_then_retry_succeeds
        """
        world = setup_enrolled_employee(api, dependent_count=1, user_id="u_ee_ob1")
        second_employee = create_employee(
            api, world["employer"]["id"], world["plan"]["id"], user_id="u_ee_ob2"
        )
        second_dependent = create_dependent(api, second_employee["id"])
        bundle = setup_provider_with_block(
            api,
            "2026-08-11T08:00:00Z",
            "2026-08-11T18:00:00Z",
            total_slots=4,
            provider_name="Minneapolis Center",
            owner_user_id="u_pm_ms",
            market_code="MKT-MSP",
            postal_code="55401",
            daily_capacity_slots=4,
            max_concurrent_assignments=3,
        )
        block_id = bundle["block"]["id"]

        r1 = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            "2026-08-11T09:00:00Z",
            "2026-08-11T15:00:00Z",
            market_code="MKT-MSP",
        )
        r2 = create_reservation(
            api,
            second_employee["id"],
            [second_dependent["id"]],
            "2026-08-11T09:00:00Z",
            "2026-08-11T15:00:00Z",
            market_code="MKT-MSP",
        )
        match_reservation(api, r1["id"])
        match_reservation(api, r2["id"])

        # Both clients hold the same read of the block.
        shared_read = read_capacity_block(api, block_id)
        assert shared_read["version"] == 1
        assert shared_read["total_slots"] == 4

        first = confirm_reservation(api, r1["id"], block_id, block_version=shared_read["version"])
        assert first["fulfillment_status"] == "CONFIRMED"

        after_first = read_capacity_block(api, block_id)
        assert after_first["version"] == 2
        assert_block_seats_reconcile(after_first, 1, 0)
        free_seats = (
            after_first["total_slots"] - after_first["reserved_slots"] - after_first["committed_slots"]
        )
        assert free_seats == 3

        stale = _confirm_response(api, r2["id"], block_id, shared_read["version"])
        validate_error(stale, ApiErrorId.ERR_STALE_CAPACITY_BLOCK_VERSION.value)
        assert stale.status_code == 412

        mid = read_reservation(api, r2["id"])
        assert mid["fulfillment_status"] == "OFFERED"
        assert mid["matched_capacity_block_id"] is None

    def test_re_reading_the_block_lets_the_retry_take_its_own_seat(self, api):
        """Two confirms, two seats, no double count and no lost seat.

        PRD 2.6: "The `version` field returned when reading a capacity block is
        precisely the value a confirming caller is expected to echo back."

        Design: Corner/complexity_layers/corner_stale_capacity_block_version_blocks_second_confirm_then_retry_succeeds
        """
        world = setup_enrolled_employee(api, dependent_count=1, user_id="u_ee_ob1")
        second_employee = create_employee(
            api, world["employer"]["id"], world["plan"]["id"], user_id="u_ee_ob2"
        )
        second_dependent = create_dependent(api, second_employee["id"])
        bundle = setup_provider_with_block(
            api,
            "2026-08-11T08:00:00Z",
            "2026-08-11T18:00:00Z",
            total_slots=4,
            provider_name="Minneapolis Center",
            owner_user_id="u_pm_ms",
            market_code="MKT-MSP",
            postal_code="55401",
            daily_capacity_slots=4,
            max_concurrent_assignments=3,
        )
        block_id = bundle["block"]["id"]

        r1 = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            "2026-08-11T09:00:00Z",
            "2026-08-11T15:00:00Z",
            market_code="MKT-MSP",
        )
        r2 = create_reservation(
            api,
            second_employee["id"],
            [second_dependent["id"]],
            "2026-08-11T09:00:00Z",
            "2026-08-11T15:00:00Z",
            market_code="MKT-MSP",
        )
        match_reservation(api, r1["id"])
        match_reservation(api, r2["id"])

        confirm_reservation(api, r1["id"], block_id, block_version=1)
        validate_error(
            _confirm_response(api, r2["id"], block_id, 1),
            ApiErrorId.ERR_STALE_CAPACITY_BLOCK_VERSION.value,
        )

        refreshed = read_capacity_block(api, block_id)
        retry = confirm_reservation(api, r2["id"], block_id, block_version=refreshed["version"])
        assert retry["fulfillment_status"] == "CONFIRMED"
        assert retry["covered_days"] == pytest.approx(1, abs=0.01)

        final = read_capacity_block(api, block_id)
        assert final["version"] == 3
        assert_block_seats_reconcile(final, 2, 0)
        assert final["total_slots"] - final["reserved_slots"] - final["committed_slots"] == 2
        assert final["block_status"] == "OPEN"


class TestImmediateReadConsistency:
    def test_the_confirm_response_and_the_next_reads_already_agree(self, api):
        """No derived figure lags the write that produced it.

        PRD 3.6: "It appends one `UsageLedgerEntry` of type `RESERVE` whose
        `days_delta` is the positive `days_charged_provisional`, whose `cents_delta`
        is zero and whose `memo` is `CONFIRM`."

        Design: Corner/consistency_model/corner_confirm_response_and_immediate_reads_agree_within_one_request
        """
        world = setup_enrolled_employee(
            api,
            dependent_count=1,
            plan_overrides={"annual_use_limit_days": 10, "copay_center_cents_per_day": 1500},
            user_id="u_ee_ir1",
        )
        bundle = setup_provider_with_block(
            api,
            "2026-08-11T08:00:00Z",
            "2026-08-11T18:00:00Z",
            total_slots=4,
            provider_name="Saint Louis Center",
            owner_user_id="u_pm_sl",
            market_code="MKT-STL",
            postal_code="63101",
            daily_capacity_slots=4,
            max_concurrent_assignments=3,
        )
        reservation = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            "2026-08-11T09:00:00Z",
            "2026-08-11T15:00:00Z",
            market_code="MKT-STL",
        )
        matched = match_reservation(api, reservation["id"])
        assert matched["fulfillment_status"] == "OFFERED"

        confirmed = confirm_reservation(api, reservation["id"], bundle["block"]["id"])
        assert confirmed["fulfillment_status"] == "CONFIRMED"
        assert confirmed["billing_status"] == "NOT_BILLABLE"
        assert confirmed["covered_days"] == pytest.approx(1, abs=0.01)
        assert confirmed["copay_cents"] == 1500
        assert confirmed["overage_cents"] == 0
        assert confirmed["confirmation_code"]

        block = read_capacity_block(api, bundle["block"]["id"])
        assert_block_seats_reconcile(block, 1, 0)
        assert block["total_slots"] == 4
        assert block["version"] == 2

        entitlement = read_entitlement(api, world["employee"]["id"])
        assert entitlement["days_used"] == pytest.approx(0, abs=0.01)
        assert entitlement["days_reserved"] == pytest.approx(1, abs=0.01)
        assert entitlement["days_remaining"] == pytest.approx(9, abs=0.01)
        assert entitlement["overage_days_projected"] == pytest.approx(0, abs=0.01)

        ledger = read_reservation_ledger(api, reservation["id"])
        assert len(ledger) == 1
        assert ledger[0]["entry_type"] == "RESERVE"
        assert ledger[0]["days_delta"] == pytest.approx(1, abs=0.01)
        assert ledger[0]["cents_delta"] == 0

        # The reservation read agrees with the response it was written by.
        echoed = read_reservation(api, reservation["id"])
        assert echoed["confirmation_code"] == confirmed["confirmation_code"]
        assert echoed["matched_capacity_block_id"] == bundle["block"]["id"]
        assert echoed["copay_cents"] == confirmed["copay_cents"]


class TestBlockProviderMismatchPrecedence:
    """A block belonging to the wrong provider is caught before any capacity gate."""

    @staticmethod
    def _two_provider_world(api) -> Dict[str, Any]:
        world = setup_enrolled_employee(
            api, dependent_count=2, plan_overrides={"annual_use_limit_days": 10}
        )
        roomy = setup_provider_with_block(
            api,
            "2026-08-10T08:00:00Z",
            "2026-08-10T18:00:00Z",
            total_slots=4,
            provider_name="Midtown Roomy Center",
            owner_user_id="u_pm_na",
            market_code="MKT-NYC",
            postal_code="10018",
            daily_capacity_slots=4,
        )
        tight = setup_provider_with_block(
            api,
            "2026-08-10T08:00:00Z",
            "2026-08-10T18:00:00Z",
            total_slots=1,
            provider_name="Midtown Tight Center",
            owner_user_id="u_pm_nb",
            market_code="MKT-NYC",
            postal_code="10019",
            daily_capacity_slots=1,
        )
        reservation = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            "2026-08-10T09:00:00Z",
            "2026-08-10T15:00:00Z",
            market_code="MKT-NYC",
        )
        world.update({"roomy": roomy, "tight": tight, "reservation": reservation})
        return world

    def test_the_wrong_provider_wins_over_the_one_seat_shortfall(self, api):
        """Two seats needed against a one-seat block, and the mismatch still fires.

        PRD 3.6: "Then the block must belong to the provider named by
        `matched_provider_id` (`ERR_BLOCK_PROVIDER_MISMATCH`) and its `service_date`
        must equal the reservation's `care_date`."

        Design: Difficulty/error_precedence_ordering/confirm_block_mismatch_beats_capacity_exhausted
        """
        world = self._two_provider_world(api)
        reservation_id = world["reservation"]["id"]

        matched = match_reservation(api, reservation_id)
        assert matched["matched_provider_id"] == world["roomy"]["provider"]["id"]
        assert matched["required_seats"] == 2

        foreign_block = world["tight"]["block"]
        response = _confirm_response(
            api, reservation_id, foreign_block["id"], foreign_block["version"]
        )
        body = validate_error(response, ApiErrorId.ERR_BLOCK_PROVIDER_MISMATCH.value)
        assert response.status_code == 409
        assert body["error_id"] != ApiErrorId.ERR_CAPACITY_EXHAUSTED.value
        assert body["error_id"] != ApiErrorId.ERR_BLOCK_NOT_OPEN.value

        after = read_reservation(api, reservation_id)
        assert after["fulfillment_status"] == "OFFERED"
        assert after["matched_capacity_block_id"] is None
        assert after["confirmation_code"] is None

        untouched = read_capacity_block(api, foreign_block["id"])
        assert_block_seats_reconcile(untouched, 0, 0)
        assert untouched["block_status"] == "OPEN"
        assert read_entitlement(api, world["employee"]["id"])["days_reserved"] == pytest.approx(
            0, abs=0.01
        )

    def test_the_matched_block_then_takes_both_seats_and_both_days(self, api):
        """The refusal cost nothing: the right block still admits two dependents.

        PRD 3.6: "For centre-based care, the days charged equal `dependent_count`:
        one entitlement day per dependent per care date."

        Design: Difficulty/error_precedence_ordering/confirm_block_mismatch_beats_capacity_exhausted
        """
        world = self._two_provider_world(api)
        reservation_id = world["reservation"]["id"]
        match_reservation(api, reservation_id)

        validate_error(
            _confirm_response(
                api, reservation_id, world["tight"]["block"]["id"], world["tight"]["block"]["version"]
            ),
            ApiErrorId.ERR_BLOCK_PROVIDER_MISMATCH.value,
        )

        own_block = world["roomy"]["block"]
        confirmed = confirm_reservation(
            api, reservation_id, own_block["id"], block_version=own_block["version"]
        )
        assert confirmed["fulfillment_status"] == "CONFIRMED"
        assert confirmed["days_charged_provisional"] == pytest.approx(2, abs=0.01)
        assert confirmed["covered_days"] == pytest.approx(2, abs=0.01)
        assert confirmed["copay_cents"] == 3000

        block = read_capacity_block(api, own_block["id"])
        assert_block_seats_reconcile(block, 2, 0)
        assert block["version"] == own_block["version"] + 1
        assert read_entitlement(api, world["employee"]["id"])["days_reserved"] == pytest.approx(
            2, abs=0.01
        )
        # The one-seat block of the other provider never moved.
        assert_block_seats_reconcile(read_capacity_block(api, world["tight"]["block"]["id"]), 0, 0)


class TestCentreSeatAggregation:
    """A centre block constrains the seat sum only, never the interval layout."""

    @staticmethod
    def _three_reservation_world(api) -> Dict[str, Any]:
        world = setup_enrolled_employee(
            api, dependent_count=1, plan_overrides={"annual_use_limit_days": 10}, user_id="u_ee_ch1"
        )
        second = create_employee(
            api, world["employer"]["id"], world["plan"]["id"], user_id="u_ee_ch2"
        )
        third = create_employee(
            api, world["employer"]["id"], world["plan"]["id"], user_id="u_ee_ch3"
        )
        d2 = create_dependent(api, second["id"])
        d3a = create_dependent(api, third["id"])
        d3b = create_dependent(api, third["id"])

        bundle = setup_provider_with_block(
            api,
            "2026-08-10T08:00:00Z",
            "2026-08-10T18:00:00Z",
            total_slots=3,
            provider_name="Loop Learning Center",
            owner_user_id="u_pm_chi",
            market_code="MKT-CHI",
            postal_code="60601",
            daily_capacity_slots=3,
        )
        reservations = {
            "a": create_reservation(
                api,
                world["employee"]["id"],
                world["dependent_ids"],
                "2026-08-10T09:00:00Z",
                "2026-08-10T12:00:00Z",
                market_code="MKT-CHI",
            ),
            "b": create_reservation(
                api,
                second["id"],
                [d2["id"]],
                "2026-08-10T12:00:00Z",
                "2026-08-10T15:00:00Z",
                market_code="MKT-CHI",
            ),
            "c": create_reservation(
                api,
                third["id"],
                [d3a["id"], d3b["id"]],
                "2026-08-10T09:00:00Z",
                "2026-08-10T12:00:00Z",
                market_code="MKT-CHI",
            ),
        }
        # Every reservation reaches OFFERED before any seat is consumed.
        for reservation in reservations.values():
            assert match_reservation(api, reservation["id"])["fulfillment_status"] == "OFFERED"

        world.update(
            {
                "block": bundle["block"],
                "reservations": reservations,
                "third_employee": third,
            }
        )
        return world

    def test_two_touching_windows_both_hold_their_own_seat(self, api):
        """Nine to twelve and twelve to three coexist inside one three-seat block.

        PRD 3.3: "Only the seat *sum* is constrained, and the interval is half-open,
        so two reservations whose windows merely touch — one ending at exactly the
        instant the other begins — coexist freely."

        Design: Difficulty/resource_temporal_overlap/center_block_counts_touching_windows_as_aggregate_seats
        """
        world = self._three_reservation_world(api)
        block_id = world["block"]["id"]

        first = confirm_reservation(api, world["reservations"]["a"]["id"], block_id)
        assert first["fulfillment_status"] == "CONFIRMED"
        after_first = read_capacity_block(api, block_id)
        assert_block_seats_reconcile(after_first, 1, 0)

        second = confirm_reservation(api, world["reservations"]["b"]["id"], block_id)
        assert second["fulfillment_status"] == "CONFIRMED"
        after_second = read_capacity_block(api, block_id)
        assert_block_seats_reconcile(after_second, 2, 0)
        assert after_second["block_status"] == "OPEN"
        assert after_second["total_slots"] == 3

        # The windows touch at exactly 12:00Z and neither displaced the other.
        assert read_reservation(api, world["reservations"]["a"]["id"])["care_end_utc"].startswith(
            "2026-08-10T12:00:00"
        )
        assert read_reservation(api, world["reservations"]["b"]["id"])["care_start_utc"].startswith(
            "2026-08-10T12:00:00"
        )

    def test_a_two_seat_request_against_one_free_seat_is_exhausted(self, api):
        """Seats needed is the dependent count, not the reservation count.

        PRD 3.3: "For `CENTER_BASED`, the seats needed are the reservation's
        `dependent_count` and the seats available are `total_slots` less
        `reserved_slots` less `committed_slots`; admission requires availability to
        be at least the seats needed, and a shortfall is `ERR_CAPACITY_EXHAUSTED`."

        Design: Difficulty/resource_temporal_overlap/center_block_counts_touching_windows_as_aggregate_seats
        """
        world = self._three_reservation_world(api)
        block_id = world["block"]["id"]
        third = world["reservations"]["c"]
        assert third["required_seats"] == 2

        confirm_reservation(api, world["reservations"]["a"]["id"], block_id)
        confirm_reservation(api, world["reservations"]["b"]["id"], block_id)
        before = read_capacity_block(api, block_id)

        response = _confirm_response(api, third["id"], block_id, before["version"])
        validate_error(response, ApiErrorId.ERR_CAPACITY_EXHAUSTED.value)
        assert response.status_code == 409

        after = read_capacity_block(api, block_id)
        assert after["version"] == before["version"]
        assert_block_seats_reconcile(after, 2, 0)
        assert after["total_slots"] == 3

        refused = read_reservation(api, third["id"])
        assert refused["fulfillment_status"] == "OFFERED"
        assert refused["matched_capacity_block_id"] is None
        assert read_entitlement(api, world["third_employee"]["id"])[
            "days_reserved"
        ] == pytest.approx(0, abs=0.01)

        for key in ("a", "b"):
            assert (
                read_reservation(api, world["reservations"][key]["id"])["fulfillment_status"]
                == "CONFIRMED"
            )


class TestInHomeTravelBuffer:
    """One caregiver, a sixty-minute buffer and an exact boundary."""

    @staticmethod
    def _three_visit_world(api) -> Dict[str, Any]:
        world = setup_enrolled_employee(
            api,
            dependent_count=1,
            plan_overrides={"annual_use_limit_days": 20, "in_home_min_billable_hours": 4},
            user_id="u_ee_ih1",
        )
        second = create_employee(
            api, world["employer"]["id"], world["plan"]["id"], user_id="u_ee_ih2"
        )
        third = create_employee(
            api, world["employer"]["id"], world["plan"]["id"], user_id="u_ee_ih3"
        )
        d2 = create_dependent(api, second["id"])
        d3 = create_dependent(api, third["id"])

        bundle = setup_provider_with_block(
            api,
            "2026-08-10T06:00:00Z",
            "2026-08-10T23:00:00Z",
            total_slots=1,
            provider_name="Dallas Home Aides",
            owner_user_id="u_pm_dfw",
            market_code="MKT-DFW",
            postal_code="75201",
            care_mode="IN_HOME",
            daily_capacity_slots=1,
            max_concurrent_assignments=1,
        )
        visits = {
            "a": create_reservation(
                api,
                world["employee"]["id"],
                world["dependent_ids"],
                "2026-08-10T09:00:00Z",
                "2026-08-10T12:00:00Z",
                market_code="MKT-DFW",
                requested_care_mode="IN_HOME",
            ),
            "b": create_reservation(
                api,
                second["id"],
                [d2["id"]],
                "2026-08-10T12:59:00Z",
                "2026-08-10T15:00:00Z",
                market_code="MKT-DFW",
                requested_care_mode="IN_HOME",
            ),
            "c": create_reservation(
                api,
                third["id"],
                [d3["id"]],
                "2026-08-10T13:00:00Z",
                "2026-08-10T15:00:00Z",
                market_code="MKT-DFW",
                requested_care_mode="IN_HOME",
            ),
        }
        for visit in visits.values():
            assert match_reservation(api, visit["id"])["fulfillment_status"] == "OFFERED"

        world.update(
            {"block": bundle["block"], "visits": visits, "second_employee": second}
        )
        return world

    def test_a_fifty_nine_minute_gap_conflicts_with_the_booked_visit(self, api):
        """12:59Z falls strictly inside 12:00Z plus the sixty-minute buffer.

        PRD 3.3: "A previously booked reservation of the same provider, other than
        the one being admitted and with `fulfillment_status` `CONFIRMED` or
        `IN_SERVICE`, conflicts with the candidate exactly when the candidate's
        `care_start_utc` falls strictly before that reservation's `care_end_utc`
        advanced by the sixty-minute buffer **and** that reservation's
        `care_start_utc` falls strictly before the candidate's `care_end_utc`
        advanced by the same buffer."

        Design: Difficulty/resource_temporal_overlap/in_home_caregiver_buffer_rejects_59_minute_gap_admits_60
        """
        world = self._three_visit_world(api)
        block_id = world["block"]["id"]

        first = confirm_reservation(api, world["visits"]["a"]["id"], block_id)
        assert first["fulfillment_status"] == "CONFIRMED"
        assert first["required_seats"] == 1
        after_first = read_capacity_block(api, block_id)
        assert_block_seats_reconcile(after_first, 1, 0)
        assert after_first["block_status"] == "OPEN"

        response = _confirm_response(
            api, world["visits"]["b"]["id"], block_id, after_first["version"]
        )
        validate_error(response, ApiErrorId.ERR_CAREGIVER_WINDOW_CONFLICT.value)
        assert response.status_code == 409

        refused = read_reservation(api, world["visits"]["b"]["id"])
        assert refused["fulfillment_status"] == "OFFERED"
        assert refused["matched_capacity_block_id"] is None
        assert read_entitlement(api, world["second_employee"]["id"])[
            "days_reserved"
        ] == pytest.approx(0, abs=0.01)

    def test_a_sixty_minute_gap_is_admitted_and_total_slots_is_ignored(self, api):
        """13:00Z is exactly the boundary, and the one-slot block still admits it.

        PRD 3.3: "The buffer boundary is exact: a gap of precisely sixty minutes
        between two visits does not conflict, while a gap one minute shorter does."

        Design: Difficulty/resource_temporal_overlap/in_home_caregiver_buffer_rejects_59_minute_gap_admits_60
        """
        world = self._three_visit_world(api)
        block_id = world["block"]["id"]

        confirm_reservation(api, world["visits"]["a"]["id"], block_id)
        after_first = read_capacity_block(api, block_id)

        validate_error(
            _confirm_response(api, world["visits"]["b"]["id"], block_id, after_first["version"]),
            ApiErrorId.ERR_CAREGIVER_WINDOW_CONFLICT.value,
        )

        admitted = confirm_reservation(
            api, world["visits"]["c"]["id"], block_id, block_version=after_first["version"]
        )
        assert admitted["fulfillment_status"] == "CONFIRMED"
        assert admitted["billable_hours_provisional"] == pytest.approx(4.00, abs=0.01)
        assert admitted["days_charged_provisional"] == pytest.approx(1, abs=0.01)

        final = read_capacity_block(api, block_id)
        assert final["version"] == after_first["version"] + 1
        assert_block_seats_reconcile(final, 2, 0)
        assert final["total_slots"] == 1
        assert final["block_status"] == "OPEN"

        # The rejected middle visit is still waiting, unpriced.
        middle = read_reservation(api, world["visits"]["b"]["id"])
        assert middle["fulfillment_status"] == "OFFERED"
        assert middle["copay_cents"] == 0
        assert validate_success(api.get_reservation(world["visits"]["a"]["id"], CARE_COORDINATOR))[
            "fulfillment_status"
        ] == "CONFIRMED"
