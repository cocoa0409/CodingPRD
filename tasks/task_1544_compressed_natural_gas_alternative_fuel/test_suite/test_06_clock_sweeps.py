"""Logical-clock epoch sweeps (PRD §2.5): hold timeouts, policy expiry, window
lapse, backup expiry, contract expiry, inspection overdue, and the daily usage
rollover."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_compressor,
    authorize_and_complete,
    authorize_session,
    authorize_session_ok,
    complete_inspection,
    create_active_contract,
    create_active_station,
    create_backup,
    create_fleet_account,
    create_fleet_card,
    create_inspection,
    create_pricing_policy,
    create_station,
    create_window,
    get_account,
    make_fleet_account_manager_headers,
    make_fleet_driver_headers,
    set_clock,
    setup_fueling_ready,
    validate_error,
    validate_success,
)


class TestHoldTimeoutSweep:
    def test_clock_sweep_session_timeout_voids_with_hold_release(
        self, api, station_manager_headers
    ):
        """PRD §2.5: "Any fueling session that has remained
        AUTHORIZED for thirty minutes since its `authorized_at` timestamp is
        voided with `void_reason` TIMEOUT, releasing any hold it carried."

        Design: Corner/state_machines/clock_sweep_session_timeout_voids_with_hold_release
        """
        env = setup_fueling_ready(
            station_name="TO", station_code="ST-TO", credit_limit_cents=100000,
            daily_gge_limit=100.0,
        )
        # Authorize at the default clock 2026-08-01T00:00:00Z.
        sess = authorize_session_ok(
            env["card"]["id"], env["dispenser"]["id"], "CR-TO1", 20.0
        )
        set_clock("2026-08-01T00:31:00Z")
        after = validate_success(
            api.get_fueling_session(sess["id"], station_manager_headers), 200
        )
        assert after["status"] == "VOIDED"
        assert after["void_reason"] == "TIMEOUT", "31 minutes > 30-minute hold timeout"
        assert get_account(env["account"]["id"])["outstanding_balance_cents"] == 0, (
            "hold 5780 released by the sweep"
        )


class TestPolicyExpirySweep:
    def test_clock_sweep_policy_expiry_blocks_pricing(self, api, network_operator_headers):
        """PRD §2.5: "Any ACTIVE pricing policy whose
        `effective_to` has passed moves to EXPIRED."
        PRD §3.4: "At most one such policy can exist, since creation supersedes
        same-key predecessors; if none matches, authorization fails with
        `ERR_NO_ACTIVE_PRICE` (HTTP 422)."

        Design: Corner/state_machines/clock_sweep_policy_expiry_blocks_pricing
        """
        env = create_active_station(station_name="Exp", station_code="ST-EXP")
        policy = create_pricing_policy(
            env["station"]["id"], effective_to="2026-08-10T00:00:00Z"
        )
        account = create_fleet_account(account_name="Exp Co", credit_limit_cents=100000)
        card = create_fleet_card(account["id"], daily_gge_limit=100.0)

        set_clock("2026-08-11T00:00:00Z")
        policy_after = validate_success(
            api.get_pricing_policy(policy["id"], network_operator_headers), 200
        )
        assert policy_after["status"] == "EXPIRED"
        resp = authorize_session(card["id"], env["dispensers"][0]["id"], "CR-EX1", 5.0)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_PRICE, 422)


class TestWindowLapseSweep:
    def test_clock_sweep_window_lapses_and_rejects_start(self, api, station_manager_headers):
        """PRD §2.5: "Any maintenance window still SCHEDULED once
        its `ends_at` has passed moves to LAPSED."
        PRD §3.6: "Starting a window requires it to be SCHEDULED, else
        `ERR_WINDOW_NOT_STARTABLE` (HTTP 409), and the logical now must fall
        within the window — on or after `starts_at` and strictly before
        `ends_at` — else `ERR_WINDOW_NOT_IN_TIME_RANGE` (HTTP 409)."

        Design: Corner/state_machines/clock_sweep_window_lapses_and_rejects_start
        """
        station = create_station(station_name="Lapse", station_code="ST-LAPSE")
        compressor = add_compressor(station["id"])
        window = create_window(
            station["id"],
            compressor_id=compressor["id"],
            starts_at="2026-08-05T10:00:00Z",
            ends_at="2026-08-05T12:00:00Z",
        )
        set_clock("2026-08-06T00:00:00Z")
        after = validate_success(
            api.get_maintenance_window(window["id"], station_manager_headers), 200
        )
        assert after["status"] == "LAPSED"
        resp = api.start_maintenance_window(window["id"], station_manager_headers)
        validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_STARTABLE, 409)


class TestContractExpirySweep:
    def test_clock_sweep_contract_expires_after_end_month(self, api, network_operator_headers):
        """PRD §2.5: "Any ACTIVE supply contract whose
        `end_month` is strictly earlier than the current calendar month moves
        to EXPIRED."

        Design: Corner/state_machines/clock_sweep_contract_expires_after_end_month
        """
        set_clock("2026-07-15T00:00:00Z")
        env = create_active_station(
            station_name="CExp", station_code="ST-CEXP", access_mode="PRIVATE"
        )
        account = create_fleet_account(account_name="CExp Co", credit_limit_cents=100000)
        contract = create_active_contract(
            account["id"],
            env["station"]["id"],
            committed_monthly_gge=50.0,
            start_month="2026-07",
            end_month="2026-07",
        )
        set_clock("2026-08-02T00:00:00Z")
        after = validate_success(
            api.get_supply_contract(contract["id"], network_operator_headers), 200
        )
        assert after["status"] == "EXPIRED"


class TestBackupExpirySweep:
    def test_clock_sweep_backup_expires_and_rejects_activate(
        self, api, station_manager_headers
    ):
        """PRD §2.5: "Any backup fueling arrangement in RESERVED
        or ACTIVATED status whose `available_until` has passed moves to
        EXPIRED, freezing its accumulated usage."
        PRD §3.6: "Activation moves an arrangement from RESERVED to ACTIVATED
        and requires the logical now to lie within the availability window —
        on or after `available_from` and on or before `available_until`, both
        ends inclusive for this check alone; a RESERVED violation is
        `ERR_BACKUP_NOT_ACTIVATABLE` and an out-of-window attempt is
        `ERR_BACKUP_NOT_IN_WINDOW` (both HTTP 409)."

        Design: Corner/state_machines/clock_sweep_backup_expires_and_rejects_activate
        """
        station = create_station(station_name="BExp", station_code="ST-BEXP")
        backup = create_backup(
            station["id"],
            partner_station_code="ST-PB",
            available_from="2026-08-02T00:00:00Z",
            available_until="2026-08-03T00:00:00Z",
            committed_gge=500,
        )
        set_clock("2026-08-04T00:00:00Z")
        after = validate_success(
            api.get_backup_arrangement(backup["id"], station_manager_headers), 200
        )
        assert after["status"] == "EXPIRED"
        resp = api.activate_backup_arrangement(backup["id"], station_manager_headers)
        validate_error(resp, ApiErrorId.ERR_BACKUP_NOT_ACTIVATABLE, 409)


class TestDailyUsageRolloverSweep:
    def test_clock_sweep_card_daily_usage_resets(self, api):
        """PRD §2.5: "Any fleet card whose
        `current_day_date` is earlier than the current UTC date has its
        `current_day_gge` reset to zero and its `current_day_date` set to the
        current date."
        PRD §2.5: "Any COMPLETED fueling session whose
        `completed_at` month is strictly earlier than the current calendar
        month moves to SETTLED and is stamped with `settled_at`."

        Design: Corner/state_machines/clock_sweep_card_daily_usage_resets
        """
        env = setup_fueling_ready(
            station_name="Daily", station_code="ST-DAILY", credit_limit_cents=100000,
            daily_gge_limit=100.0,
        )
        session = authorize_and_complete(
            env["card"]["id"], env["dispenser"]["id"], "CR-DA1", 25.0
        )
        assert session["status"] == "COMPLETED"
        set_clock("2026-08-03T00:00:00Z")
        card = validate_success(
            api.get_fleet_card(
                env["card"]["id"],
                make_fleet_account_manager_headers(env["account"]["id"]),
            ),
            200,
        )
        assert card["current_day_gge"] == pytest.approx(0, abs=1e-9)
        assert card["current_day_date"] == "2026-08-03"
        after = validate_success(
            api.get_fueling_session(
                session["id"], make_fleet_driver_headers(env["card"]["id"])
            ),
            200,
        )
        assert after["status"] == "COMPLETED", (
            "same-month sessions are not settled by a day rollover"
        )


class TestInspectionOverdueSweep:
    def test_clock_sweep_inspection_overdue_allows_late_completion(
        self, api, station_manager_headers
    ):
        """PRD §2.5: "Any SCHEDULED safety inspection whose
        `scheduled_for` has passed moves to OVERDUE."
        PRD §3.7: "A `StationManager` completes an inspection that is SCHEDULED
        or OVERDUE — any other state draws `ERR_INSPECTION_NOT_COMPLETABLE`
        (HTTP 409) — supplying a `result` of PASS, PASS_WITH_DEFICIENCIES, or
        FAIL plus optional `findings` text; the system stamps `performed_by`
        with the caller's `X-User-ID` and `completed_at` with the logical now."

        Design: Corner/state_machines/clock_sweep_inspection_overdue_allows_late_completion
        """
        station = create_station(station_name="OD", station_code="ST-OD")
        inspection = create_inspection(
            station["id"], scheduled_for="2026-08-02T10:00:00Z"
        )
        set_clock("2026-08-03T00:00:00Z")
        after = validate_success(
            api.get_safety_inspection(inspection["id"], station_manager_headers), 200
        )
        assert after["status"] == "OVERDUE", "sweep marked it"
        completed = complete_inspection(inspection["id"], "PASS", "sm-200")
        assert completed["status"] == "COMPLETED", (
            "late completion from OVERDUE is allowed"
        )
