"""Insurer creation and the simulated clock (PRD §2.6, §3.10)."""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_insurer,
    create_insurer_payload,
    advance_clock_to,
    advance_clock_by,
    get_insurer,
    assert_insurer,
)


class TestInsurerCreation:
    def test_create_insurer_initializes_clock_to_zero(self, api):
        """PRD §2.6: "On insurer creation, the system initialises both
        now_epoch_ms and total_outstanding_reserve_cents to zero."

        Claim: POST /insurers yields now_epoch_ms == 0 and
        total_outstanding_reserve_cents == 0.
        """
        resp = api.create_insurer(
            create_insurer_payload(name="Demo Insurer", currency="EUR"),
            TEST_USERS["claims_admin_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_insurer(data)
        assert data["now_epoch_ms"] == 0, \
            f"now_epoch_ms must initialise to 0, got {data['now_epoch_ms']}"
        assert data["total_outstanding_reserve_cents"] == 0
        assert data["currency"] == "EUR"
        assert data["name"] == "Demo Insurer"

    def test_get_insurer_returns_same_state(self, api):
        """PRD §2.6: "The root tenant entity is the insurer itself, created
        with a display name and a currency (the ISO-4217 code)."

        Claim: GET /insurers/{id} returns the persisted insurer with the
        creation-time fields preserved.
        """
        created = create_insurer(name="Roundtrip", currency="USD")
        resp = api.get_insurer(created["id"], TEST_USERS["claims_admin_headers"])
        data = validate_success(resp)
        assert data["id"] == created["id"]
        assert data["currency"] == "USD"


class TestClockAdvance:
    def test_advance_clock_by_delta_increments_now(self, api):
        """PRD §2.6: "The simulated clock is Insurer.now_epoch_ms ... only
        advances when a ClaimsAdmin calls the test-clock advance capability
        with either delta_ms (a non-negative increment) or to_epoch_ms (an
        absolute target)."

        Claim: POST /_clock/advance with delta_ms=1000 advances now_epoch_ms
        from 0 to 1000.
        """
        insurer = create_insurer()
        advance_clock_by(insurer["id"], 1000)
        after = get_insurer(insurer["id"])
        assert after["now_epoch_ms"] == 1000, \
            f"clock must advance by delta_ms; got {after['now_epoch_ms']}"

    def test_advance_clock_to_absolute_target(self, api):
        """PRD §2.6: "delta_ms (a non-negative increment) or to_epoch_ms (an
        absolute target). No other operation moves the clock."

        Claim: POST /_clock/advance with to_epoch_ms=5000 sets
        Insurer.now_epoch_ms exactly to 5000.
        """
        insurer = create_insurer()
        advance_clock_to(insurer["id"], 5000)
        after = get_insurer(insurer["id"])
        assert after["now_epoch_ms"] == 5000

    def test_negative_delta_rejected(self, api):
        """PRD §2.6: "delta_ms (a non-negative increment) ...".

        Claim: a negative delta_ms is rejected as invalid input.
        """
        insurer = create_insurer()
        resp = api.advance_clock(
            insurer["id"], {"delta_ms": -1},
            TEST_USERS["claims_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
