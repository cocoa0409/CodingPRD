"""Optimistic concurrency and racy operations (PRD §2.5)."""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock,
    api_client,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    bind_card_payload,
    bind_vehicle_to_card,
    create_card,
    create_session_payload,
    create_vehicle,
    make_driver_headers,
    open_session,
    recharge_card_payload,
    run_race,
    setup_basic_session_scenario,
    setup_lot_zone_spaces,
    setup_session_with_storedvalue_card,
    TEST_USERS,
    unique_external_ref,
    unique_holder_ref,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# §2.5 — Two drivers gate-in to the same FREE space
# ===========================================================================
class TestSpaceRaceAtGateIn:
    def test_two_gate_ins_same_space_exactly_one_wins(self, api):
        """PRD §2.5: 'When two drivers simultaneously gate-in to the same
        FREE space, the first writer to assign Space.current_session_id
        wins and the loser is rejected with ERR_SPACE_OCCUPIED.'"""
        advance_clock("2026-10-01T08:00:00.000Z")
        lot, zone, spaces = setup_lot_zone_spaces(space_count=1)
        v1 = create_vehicle()
        v2 = create_vehicle()
        space_id = spaces[0]["id"]
        gate_a = TEST_USERS["gate_headers"]
        gate_b = TEST_USERS["gate_headers_alt"]

        results = run_race(
            lambda: api.create_session(
                lot["id"],
                create_session_payload(vehicle_id=v1["id"], space_id=space_id),
                gate_a,
            ),
            lambda: api.create_session(
                lot["id"],
                create_session_payload(vehicle_id=v2["id"], space_id=space_id),
                gate_b,
            ),
        )
        outcome = assert_exactly_one_succeeds(*results)
        # Verify the loser's error_id matches PRD's named error.
        loser_resp = outcome["failures"][0]
        loser_body = loser_resp.json()
        assert loser_body["data"]["error_id"] == "ERR_SPACE_OCCUPIED", (
            f"PRD §2.5: loser must be rejected with ERR_SPACE_OCCUPIED, "
            f"got {loser_body['data']['error_id']}"
        )


# ===========================================================================
# §2.5 — Two MONTHLY bindings on the same vehicle
# ===========================================================================
class TestVehicleAlreadyBoundRace:
    def test_two_monthly_bindings_on_one_vehicle(self, api, operator_headers):
        """PRD §2.5: 'When two operators attempt to bind the same Vehicle
        to two different MONTHLY cards simultaneously, exactly one binding
        edge is admitted and the loser is rejected with
        ERR_VEHICLE_ALREADY_BOUND.'"""
        v = create_vehicle()
        a = create_card(card_type="MONTHLY", monthly_fee_cents=1000)
        b = create_card(card_type="MONTHLY", monthly_fee_cents=1000)
        results = run_race(
            lambda: api.bind_card(
                a["id"], bind_card_payload(vehicle_id=v["id"]),
                TEST_USERS["operator_headers"],
            ),
            lambda: api.bind_card(
                b["id"], bind_card_payload(vehicle_id=v["id"]),
                TEST_USERS["operator_headers_alt"],
            ),
        )
        outcome = assert_exactly_one_succeeds(*results)
        loser_resp = outcome["failures"][0]
        loser_body = loser_resp.json()
        assert loser_body["data"]["error_id"] == "ERR_VEHICLE_ALREADY_BOUND", (
            f"PRD §2.5: loser must be rejected with ERR_VEHICLE_ALREADY_BOUND, "
            f"got {loser_body['data']['error_id']}"
        )


# ===========================================================================
# §2.5 — OCC on Card (recharge vs auto-pay)
# ===========================================================================
class TestCardOptimisticConcurrency:
    def test_stale_version_on_card_mutation_rejected(self, api, operator_headers):
        """PRD §2.5: 'When a recharge and an auto-pay debit on the same
        Card collide, the second writer to arrive with a stale version is
        rejected with ERR_VERSION_CONFLICT.'

        The PRD's optimistic-concurrency rule is: 'Mutations on versioned
        resources may include the resource's current version either in the
        request body or via an If-Match header. When supplied, the server
        compares the supplied value against the live version of the target
        resource: a match permits the operation to proceed and increments
        version by one; a mismatch rejects the request with
        ERR_VERSION_CONFLICT.'

        Test the precondition explicitly: provide a stale If-Match value
        on a recharge against a card whose version is already higher.
        """
        card = create_card(card_type="STORED_VALUE")
        # Bump the card's version by suspending then reactivating once.
        api.suspend_card(card["id"], operator_headers)
        api.reactivate_card(card["id"], operator_headers)
        # The card's version is now > 1. Issue a recharge with stale
        # version=1 via If-Match header; PRD §2.5 demands ERR_VERSION_CONFLICT.
        stale_headers = dict(operator_headers)
        stale_headers["If-Match"] = "1"
        res = api.recharge_card(
            card["id"],
            recharge_card_payload(
                amount_cents=1000, external_ref=unique_external_ref()
            ),
            stale_headers,
        )
        validate_error(res, "ERR_VERSION_CONFLICT")


# ===========================================================================
# §2.5 — Driver-pay vs Operator-waive on the same Session
# ===========================================================================
class TestPayWaiveRace:
    def test_pay_and_waive_exactly_one_succeeds(self, api):
        """PRD §2.5: 'When a Driver initiates a session payment while an
        Operator waives the same session at the same instant, exactly one
        payment-status transition wins and the loser is rejected with
        ERR_INVALID_STATE.'"""
        scen = setup_session_with_storedvalue_card(
            base_iso="2026-10-05T10:00:00.000Z",
            free_minutes=0, hourly_rate_cents=400,
            initial_balance_cents=5000,
        )
        # exit + advance clock so final_fee=400 is pinned
        advance_clock("2026-10-05T11:00:00.000Z")
        api.exit_session(scen["session"]["id"], TEST_USERS["gate_headers"])

        from test_helpers import pay_session_payload, waive_session_payload
        driver_headers = make_driver_headers(scen["vehicle"]["id"])
        operator_headers = TEST_USERS["operator_headers"]
        results = run_race(
            lambda: api.pay_session(
                scen["session"]["id"],
                pay_session_payload(card_id=scen["card"]["id"]),
                driver_headers,
            ),
            lambda: api.waive_session(
                scen["session"]["id"],
                waive_session_payload(reason="ops decision"),
                operator_headers,
            ),
        )
        outcome = assert_exactly_one_succeeds(*results)
        loser_resp = outcome["failures"][0]
        loser_body = loser_resp.json()
        assert loser_body["data"]["error_id"] == "ERR_INVALID_STATE", (
            f"PRD §2.5: loser must be rejected with ERR_INVALID_STATE, "
            f"got {loser_body['data']['error_id']}"
        )


# ===========================================================================
# §2.5 — Idempotency on external_ref
# ===========================================================================
class TestExternalRefIdempotency:
    def test_duplicate_external_ref_payment_rejected(self, api, operator_headers):
        """PRD §2.5: 'Idempotency keys carried via external_ref on Payment
        writes are unique once present; a duplicate yields
        ERR_DUPLICATE_EXTERNAL_REF.'"""
        card = create_card(card_type="STORED_VALUE")
        ref = unique_external_ref("idem")
        first = api.recharge_card(
            card["id"], recharge_card_payload(amount_cents=1000, external_ref=ref),
            operator_headers,
        )
        validate_success(first, expected_status=200)
        second = api.recharge_card(
            card["id"], recharge_card_payload(amount_cents=2000, external_ref=ref),
            operator_headers,
        )
        validate_error(second, "ERR_DUPLICATE_EXTERNAL_REF")
