"""Fraud holds: placement gates, the release block, customer confirmation
outcomes, and the lazily enforced 24-hour lapse."""
from test_helpers import (
    ApiErrorId,
    assert_fraud_hold,
    confirm_fraud_hold,
    create_approved_wire,
    get_customer,
    get_wire,
    list_wire_fraud_holds,
    place_fraud_hold,
    release_wire,
    set_clock,
    setup_wire_room,
    validate_error,
    validate_success,
    wire_version,
)
from test_helpers import TEST_USERS

OPERATOR = TEST_USERS["wire_operator_headers"]
FRAUD_ANALYST = TEST_USERS["fraud_analyst_headers"]
ADMIN = TEST_USERS["wire_ops_admin_headers"]


class TestHoldBlocksRelease:
    def test_fraud_hold_blocks_release_then_legitimate_clear_restores(self, api):
        """PRD §3.8: "The placement names a `reason_code` — one of
        `ACCOUNT_TAKEOVER`, `VELOCITY`, `MULE_SUSPECT`, or `PHISHING` — and an
        analyst `note`; it stamps the wire's `hold_reason_code` to
        `FRAUD_HOLD`"
        PRD §3.5: "the wire must carry no hold — `hold_reason_code` must be
        null — else `ERR_WIRE_ON_HOLD`"
        PRD §3.8: "`LEGITIMATE` clears the hold: it moves to `CLEARED` with
        `resolution` `CUSTOMER_CONFIRMED`, the wire's `hold_reason_code`
        returns to null, and the wire remains `APPROVED`, eligible again for
        release"

        A held wire cannot release; a LEGITIMATE confirmation clears the hold
        and the same release then succeeds.

        Design: Corner/state_machines/fraud_hold_blocks_release_then_legitimate_clear_restores
        """
        room = setup_wire_room(business_date="2026-08-28")
        wire = create_approved_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-08-28",
            100000)
        hold = place_fraud_hold(wire["id"], reason_code="VELOCITY",
                                note="unusual burst")
        assert_fraud_hold(hold)
        assert hold["status"] == "OPEN"

        held = get_wire(wire["id"])
        assert held["hold_reason_code"] == "FRAUD_HOLD"

        resp = api.release_wire(
            wire["id"], {"expected_wire_version": wire_version(wire["id"])},
            OPERATOR)
        validate_error(resp, ApiErrorId.ERR_WIRE_ON_HOLD)

        cleared = confirm_fraud_hold(hold["id"], confirmation="LEGITIMATE")
        assert cleared["status"] == "CLEARED"
        assert cleared["resolution"] == "CUSTOMER_CONFIRMED"

        restored = get_wire(wire["id"])
        assert restored["hold_reason_code"] is None
        assert restored["status"] == "APPROVED"

        released = release_wire(wire["id"])
        assert released["status"] == "EXECUTED"


class TestHoldWindowLapse:
    def test_fraud_hold_window_lapse_auto_confirms_and_freezes(self, api):
        """PRD §3.8: "At or after `expires_at`, an `OPEN` hold auto-resolves
        as `CONFIRMED_FRAUD` with `resolution` `AUTO_LAPSED`, evaluated lazily
        on any access to the hold or its wire per §2.5. The auto-lapse carries
        the full confirmation compensation: the wire is cancelled and the
        ordering customer is frozen."

        The hold is placed at the startup clock (expires 24h later); at the
        deadline instant a bare read resolves the hold, cancels the wire, and
        freezes the customer — no decision call was made.

        Design: Corner/state_machines/fraud_hold_window_lapse_auto_confirms_and_freezes
        """
        room = setup_wire_room(business_date="2026-08-31")
        wire = create_approved_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-08-31",
            100000)
        hold = place_fraud_hold(wire["id"], reason_code="PHISHING",
                                note="suspected phish")
        assert hold["confirmation_window_hours"] == 24

        set_clock("2026-08-02T00:00:00Z")  # exactly expires_at

        hold_after = validate_success(api.get_fraud_hold(hold["id"], FRAUD_ANALYST), 200)
        assert_fraud_hold(hold_after)
        assert hold_after["status"] == "CONFIRMED_FRAUD"
        assert hold_after["resolution"] == "AUTO_LAPSED"

        wire_after = get_wire(wire["id"])
        assert wire_after["status"] == "CANCELLED"

        customer_after = get_customer(room["customer"]["id"])
        assert customer_after["status"] == "FROZEN"
        assert customer_after["frozen_at"] is not None


class TestHoldPlacementRoleGate:
    def test_fraud_hold_place_forbidden_for_operator(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint — including disposition-tier mismatches on sanctions hits,
        where the permitted role depends on the hit's current state — is
        rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: POST /wire-ops/wires/{id}/fraud-holds is authorized for
        `FraudAnalyst` only.

        The WireOperator cannot place a fraud hold; none exists afterwards.

        Design: Corner/rbac/fraud_hold_place_forbidden_for_operator
        """
        room = setup_wire_room(business_date="2026-10-02")
        wire = create_approved_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-10-02",
            100000)

        resp = api.place_fraud_hold(
            wire["id"], {"reason_code": "VELOCITY", "note": "operator overreach"},
            OPERATOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        holds = list_wire_fraud_holds(wire["id"])
        assert holds == [], f"no fraud hold may exist, got {len(holds)}"
