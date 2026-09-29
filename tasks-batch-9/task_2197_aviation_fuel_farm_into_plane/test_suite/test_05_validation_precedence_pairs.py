"""Requests that break two rules at once: the band order in the validation ladder decides which
error identifier the caller sees."""
import pytest

from test_helpers import validate_success, validate_error, ApiErrorId, fixtures as fx


class TestSafetyBeatsLedgerOnAuthorize:
    @staticmethod
    def _quarantined_thin_tank_order():
        env = fx.setup_truck_order(target_state="REQUESTED", requested_uplift_liters=20_000.0,
                                   max_authorized_liters=20_000.0,
                                   opening_volume_liters=5_000.0,
                                   account_overrides={"base_price_cents_per_liter": 62.00,
                                                      "credit_limit_cents": 100_000_000},
                                   permit_overrides={"max_daily_throughput_liters": 400000.0})
        validate_success(fx.api_client.quarantine_tank(
            env["tank"]["id"], fx.INSPECTOR_A, {"reason": "surveillance sample off-spec"}))
        return env

    def test_quarantined_source_tank_outranks_insufficient_volume(self, api):
        """PRD §2.10: "Then the source-tank quality guard (`ERR_TANK_QUARANTINED`) on order
        authorization, fuelling start and uplift posting; then the sample-verdict guard
        (`ERR_SAMPLE_VERDICT_FAIL`) on receipt verdicts; then the water-bottom guard
        (`ERR_WATER_BOTTOM_EXCEEDED`) on tank quality release and tank service-status changes; then
        the re-test ceiling (`ERR_RETEST_LIMIT_REACHED`) on receipt sampling; then asset
        serviceability (`ERR_ASSET_NOT_SERVICEABLE`) on order assignment, fuelling start and uplift
        posting; then spill reportability (`ERR_SPILL_NOT_REPORTABLE`) on spill escalation; then the
        empty-result guard (`ERR_EMPTY_TEST_RESULT_SET`) on posting laboratory results."
        PRD §2.10: "**Fiscal and ledger checks, evaluated last.** Safe fill
        (`ERR_SAFE_FILL_EXCEEDED`) on the receipt verdict; then permit daily throughput
        (`ERR_PERMIT_THROUGHPUT_EXCEEDED`) on the receipt verdict and on uplift posting; then tank
        volume sufficiency (`ERR_INSUFFICIENT_TANK_VOLUME`) on order authorization and uplift
        posting; then the credit check (`ERR_CREDIT_LIMIT_EXCEEDED`) on order authorization; then the
        authorization ceiling (`ERR_UPLIFT_EXCEEDS_AUTHORIZATION`) on uplift posting and order
        completion; and finally the payment bounds check (`ERR_PAYMENT_EXCEEDS_BALANCE`) on recording
        a payment."
        PRD §2.10: "The practical reading is that structural problems always beat business problems,
        business-state problems beat safety problems, and safety problems beat money problems."

        Design: Difficulty/priority_pair_validation_conflict/tank_quarantined_beats_insufficient_tank_volume_on_authorize
        """
        env = self._quarantined_thin_tank_order()
        tank = fx.read_tank(env["tank"]["id"])
        assert tank["quality_status"] == "QUARANTINED"
        assert tank["available_volume_liters"] == pytest.approx(4500.00, abs=0.005), \
            "the volume gate would also have rejected 20,000 liters"

        validate_error(api.authorize_order(env["order"]["id"], fx.AGENT),
                       ApiErrorId.ERR_TANK_QUARANTINED, 409)

    def test_the_rejected_authorization_reserves_nothing(self, api):
        """PRD §3.6: "The source tank must be `RELEASED` on quality and `IN_SERVICE` on service —
        anything else is `ERR_TANK_QUARANTINED` — and its `available_volume_liters` must be at least
        the order's `requested_uplift_liters`, or `ERR_INSUFFICIENT_TANK_VOLUME`."
        PRD §3.6: "On success the order's reservation amount is computed, the requested volume is
        added to the tank's `reserved_volume_liters` and its `available_volume_liters` drops by the
        same amount, the account's accrual exposure is recomputed, and the order's, tank's and
        account's `version` each rise by one."

        Design: Difficulty/priority_pair_validation_conflict/tank_quarantined_beats_insufficient_tank_volume_on_authorize
        """
        env = self._quarantined_thin_tank_order()
        validate_error(api.authorize_order(env["order"]["id"], fx.AGENT),
                       ApiErrorId.ERR_TANK_QUARANTINED, 409)

        order = fx.read_order(env["order"]["id"])
        assert order["status"] == "REQUESTED"
        assert order["reserved_amount_cents"] == 0
        assert fx.read_tank(env["tank"]["id"])["reserved_volume_liters"] == \
            pytest.approx(0.00, abs=0.005)
        assert fx.read_account(env["account"]["id"])["accrual_exposure_cents"] == 0


class TestStateBeatsWindowOnStart:
    @staticmethod
    def _authorized_order_past_its_window():
        env = fx.setup_truck_order(
            target_state="AUTHORIZED", requested_uplift_liters=20_000.0,
            max_authorized_liters=20_000.0,
            flight_overrides={"scheduled_departure_utc": "2026-08-10T12:00:00Z"},
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000},
            permit_overrides={"max_daily_throughput_liters": 400000.0})
        fx.set_clock("2026-08-10T09:00:00Z")
        return env

    def test_never_assigned_order_reports_its_state_not_the_lapsed_window(self, api):
        """PRD §2.10: "Only then are the per-machine from-state guards evaluated:
        `ERR_INVALID_RECEIPT_STATE` on receipt sampling, verdict and rejection;
        `ERR_INVALID_ORDER_STATE` on order authorize, assign, unassign, start, uplift posting,
        complete, abort and cancel; `ERR_INVALID_TANK_STATE` on tank service-status changes, quality
        release, quarantine and tank sampling; `ERR_INVALID_ASSET_STATE` on asset status changes and
        filter changes; `ERR_INVALID_SPILL_STATE` on spill escalate, contain, remediate and close;
        `ERR_INVALID_INVOICE_STATE` on invoice issue, dispute, dispute resolution, void and payment;
        and `ERR_INVALID_RUN_STATE` on reconciliation measure and post."
        PRD §2.10: "Then tank isolation conflict (`ERR_TANK_ISOLATION_CONFLICT`) on tank
        service-status changes; then fuelling-window membership (`ERR_OUTSIDE_FUELING_WINDOW`) on
        fuelling start and uplift posting; then reconciliation period elapse
        (`ERR_PERIOD_NOT_ELAPSED`) followed by measurement-set completeness
        (`ERR_MEASUREMENT_SET_INCOMPLETE`), both on posting measurements; then the variance override
        requirement (`ERR_VARIANCE_OVERRIDE_REQUIRED`) on posting a run; then the at-least-one-ticket
        rule (`ERR_NO_UPLIFT_RECORDED`) on order completion; then the empty-sweep rule
        (`ERR_NOTHING_TO_SWEEP`) on invoice creation; then the dispute ceiling
        (`ERR_DISPUTE_LIMIT_REACHED`) on raising a dispute."

        Design: Difficulty/priority_pair_validation_conflict/invalid_order_state_beats_outside_fueling_window_on_start
        """
        env = self._authorized_order_past_its_window()
        validate_error(api.start_order(env["order"]["id"], fx.AGENT),
                       ApiErrorId.ERR_INVALID_ORDER_STATE, 409)

    def test_the_reservation_survives_the_rejected_start(self, api):
        """PRD §3.6: "The logical clock must be at or after `window_start_utc` and strictly before
        `window_end_utc`, or the start is refused with `ERR_OUTSIDE_FUELING_WINDOW`."
        PRD §3.4: "The `reserved_volume_liters` is the sum of `requested_uplift_liters` over every
        order on this tank whose `status` is `AUTHORIZED`, `ASSIGNED` or `FUELING`, rounded half up
        to two decimals."

        Design: Difficulty/priority_pair_validation_conflict/invalid_order_state_beats_outside_fueling_window_on_start
        """
        env = self._authorized_order_past_its_window()
        validate_error(api.start_order(env["order"]["id"], fx.AGENT),
                       ApiErrorId.ERR_INVALID_ORDER_STATE, 409)

        order = fx.read_order(env["order"]["id"])
        assert order["status"] == "AUTHORIZED"
        assert order["fueling_asset_id"] is None
        assert fx.read_tank(env["tank"]["id"])["reserved_volume_liters"] == \
            pytest.approx(20000.00, abs=0.005), \
            "the reservation taken at authorization is untouched by the rejected start"


class TestRedeemabilityBeatsCreditOnAuthorize:
    @staticmethod
    def _lapsed_authorization_over_credit():
        env = fx.setup_truck_order(
            target_state="REQUESTED", requested_uplift_liters=20_000.0,
            max_authorized_liters=20_000.0,
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000, "tax_exempt": False},
            flight_overrides={"scheduled_departure_utc": "2026-08-10T08:00:00Z"},
            permit_overrides={"max_daily_throughput_liters": 400000.0})
        fx.set_clock("2026-08-10T10:30:00Z")
        return env

    def test_lapsed_authorization_outranks_the_credit_ceiling(self, api):
        """PRD §2.10: "**Referential business checks.** The quoted authorization code must match
        character for character (`ERR_AUTH_CODE_MISMATCH`) — checked on both fuelling order creation
        and order authorization — and then the authorization must still be redeemable
        (`ERR_AUTHORIZATION_NOT_REDEEMABLE`) on order authorization."
        PRD §3.6: "The quoted authorization must be `ISSUED` and the logical clock must be strictly
        before its `expires_at_utc`, or the request fails with `ERR_AUTHORIZATION_NOT_REDEEMABLE`."
        PRD §3.5: "The `expires_at_utc` is set to the flight's scheduled departure plus 2 hours, and
        the authorization opens in `ISSUED` with `voided_reason` null."

        Design: Difficulty/priority_pair_validation_conflict/authorization_not_redeemable_beats_credit_limit_exceeded
        """
        env = self._lapsed_authorization_over_credit()
        validate_error(api.authorize_order(env["order"]["id"], fx.AGENT),
                       ApiErrorId.ERR_AUTHORIZATION_NOT_REDEEMABLE, 409)

    def test_the_authorization_lapsed_lazily_and_nothing_was_reserved(self, api):
        """PRD §3.5: "It becomes `EXPIRED` by the system once the logical clock has reached or passed
        its `expires_at_utc`; this is evaluated lazily whenever the authorization is read or
        referenced after a clock advance, and an expired authorization can no longer authorise an
        order."
        PRD §3.6: "The airline account's `status` must be `ACTIVE` and the accrual-basis exposure,
        including this order's freshly computed `reserved_amount_cents`, must not exceed the
        account's `credit_limit_cents`; failure either way is `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402),
        which is also how a `CREDIT_HOLD` account is refused."

        Design: Difficulty/priority_pair_validation_conflict/authorization_not_redeemable_beats_credit_limit_exceeded
        """
        env = self._lapsed_authorization_over_credit()
        validate_error(api.authorize_order(env["order"]["id"], fx.AGENT),
                       ApiErrorId.ERR_AUTHORIZATION_NOT_REDEEMABLE, 409)

        assert fx.read_authorization(env["auth"]["id"])["status"] == "EXPIRED"
        assert fx.read_order(env["order"]["id"])["status"] == "REQUESTED"
        account = fx.read_account(env["account"]["id"])
        assert account["accrual_exposure_cents"] == 0
        assert account["status"] == "ACTIVE", \
            "a refused authorization does not put the account on credit hold"
