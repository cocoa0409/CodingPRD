"""Shutoff orders: creation guard chain, execution guards, payment-triggered
cancellation cascade, and reconnect precondition."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, assert_date_eq,
    create_account, charge_arrearage, setup_delinquent_account,
    setup_disconnected_account, create_shutoff_order, create_certificate,
    create_dpa, create_and_activate_dpa, pay, set_clock, run_sweep, get_account,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
CSR = TEST_USERS["csr_headers"]
FIELDCREW = TEST_USERS["fieldcrew_headers"]


class TestPaymentActivatesDpaCancelsShutoff:
    def _scenario(self, api):
        """Account 120000 (aged); manual order SCHEDULED for 2026-09-30 at clock
        2026-09-15; DRAFT DPA n=4 (no enrollment; down 12000) on the account."""
        account = setup_delinquent_account(
            arrearage_cents=120_000, service_address="22 Cascade Way")
        set_clock("2026-09-15T00:00:00Z")
        order = create_shutoff_order(account["id"], "2026-09-30")
        dpa = create_dpa(account["id"], installment_count=4)
        return account, order, dpa

    def test_down_payment_completion_activates_dpa(self, api):
        """PRD §3.5: "Second, the down payment of a `DRAFT` agreement on the
        account: up to the shortfall between `down_payment_required_cents` and
        `down_payment_received_cents`, and completing the down payment activates
        the DPA as §3.4 describes."
        PRD §3.4: "Activation stamps `activated_on` with the clock date and sets
        `first_installment_due_on` thirty days later".

        Design: Difficulty/transitive_cascade/payment_activates_dpa_cancels_shutoff
        """
        account, _order, dpa = self._scenario(api)
        payment = pay(account["id"], 12_000, tender_type="MONEY_ORDER")
        assert payment["applied_breakdown"]["down_payment_cents"] == 12_000
        assert payment["dpa_id"] == dpa["id"]
        after = validate_success(api.get_dpa(dpa["id"], CSR), 200)
        assert after["status"] == "ACTIVE"
        assert_date_eq(after["activated_on"], "2026-09-15", "activated_on")
        assert_date_eq(after["first_installment_due_on"], "2026-10-15",
                       "first_installment_due_on")

    def test_activation_cancels_open_order_and_restores_connected(self, api):
        """PRD §3.4: "Activation is also protective: any open shutoff order on the
        account auto-cancels, because a kept-current `ACTIVE` DPA is incompatible
        with disconnection, and when no open order remains the account's
        `service_status` returns from `DISCONNECT_PENDING` to `CONNECTED`."

        Design: Difficulty/transitive_cascade/payment_activates_dpa_cancels_shutoff
        """
        account, order, dpa = self._scenario(api)
        pay(account["id"], 12_000, tender_type="MONEY_ORDER")
        order_after = validate_success(api.get_shutoff_order(order["id"], CSR), 200)
        assert order_after["status"] == "CANCELLED"
        account = get_account(account["id"])
        assert account["service_status"] == "CONNECTED"
        assert account["arrearage_balance_cents"] == 108_000  # 120000 - 12000


class TestShutoffCreateStateBeatsMoratoriumSafety:
    def _disconnected_in_winter(self, api):
        """Account DISCONNECTED via an executed order; clock advanced into the
        winter season and swept, so protection is WEATHER_MORATORIUM."""
        account, _order = setup_disconnected_account(
            arrearage_cents=120_000, service_address="31 Priority Pl")
        set_clock("2026-11-15T00:00:00Z")
        run_sweep()
        return get_account(account["id"])

    def test_state_error_wins_over_moratorium(self, api):
        """PRD §3.7: "Manual creation runs its validation chain in this order. The
        account must not already be `DISCONNECTED` — `CONNECTED` and even
        `DISCONNECT_PENDING` pass this check, the latter case being caught by the
        duplicate-order rule below — else `ERR_ACCOUNT_NOT_CONNECTED` (HTTP 409).
        Then the safety gates: an `ACTIVE` medical certificate covering the clock
        date blocks creation with `ERR_SHUTOFF_BLOCKED_BY_MEDICAL` (HTTP 422), and
        an account standing in `WEATHER_MORATORIUM` blocks it with
        `ERR_SHUTOFF_BLOCKED_BY_MORATORIUM` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/shutoff_create_state_beats_moratorium_safety
        """
        account = self._disconnected_in_winter(api)
        assert account["service_status"] == "DISCONNECTED"
        assert account["protection_status"] == "WEATHER_MORATORIUM"
        resp = api.create_shutoff_order(
            {"account_id": account["id"], "scheduled_date": "2026-11-30"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_CONNECTED)
        assert resp.status_code == 409, (
            "the state-category error carries 409, not the safety category's 422")

    def test_rejected_create_leaves_no_open_order(self, api):
        """PRD §3.7: "The account must not already be `DISCONNECTED` — `CONNECTED`
        and even `DISCONNECT_PENDING` pass this check, the latter case being caught
        by the duplicate-order rule below — else `ERR_ACCOUNT_NOT_CONNECTED`
        (HTTP 409)."
        PRD §2.8: "Validation on every request proceeds through a fixed global
        pipeline; a failure at any stage surfaces that stage's error and masks
        nothing later."

        Design: Difficulty/priority_pair_validation_conflict/shutoff_create_state_beats_moratorium_safety
        """
        account = self._disconnected_in_winter(api)
        resp = api.create_shutoff_order(
            {"account_id": account["id"], "scheduled_date": "2026-11-30"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_CONNECTED)
        rows, _meta = validate_paginated(
            api.list_shutoff_orders(ADMIN, params={"account_id": account["id"]}))
        open_orders = [o for o in rows if o["status"] in ("SCHEDULED", "BLOCKED")]
        assert open_orders == [], "a rejected creation must not leave an open order"
        assert get_account(account["id"])["service_status"] == "DISCONNECTED"


class TestShutoffBlockedByMedicalCertificate:
    def _protected_account(self, api):
        account = setup_delinquent_account(
            arrearage_cents=120_000, service_address="51 Cross St")
        set_clock("2026-09-15T00:00:00Z")
        create_certificate(account["id"], "2026-09-01",
                           condition_class="LIFE_THREATENING",
                           physician_name="Dr. B", physician_license_number="L-2")
        return account

    def test_create_rejected_by_covering_certificate(self, api):
        """PRD §3.7: "Then the safety gates: an `ACTIVE` medical certificate
        covering the clock date blocks creation with `ERR_SHUTOFF_BLOCKED_BY_MEDICAL`
        (HTTP 422)".

        Design: Difficulty/cross_entity_state_dependency/shutoff_create_blocked_by_active_medical_certificate
        """
        account = self._protected_account(api)
        resp = api.create_shutoff_order(
            {"account_id": account["id"], "scheduled_date": "2026-09-30"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_SHUTOFF_BLOCKED_BY_MEDICAL)

    def test_certificate_puts_account_under_medical_moratorium(self, api):
        """PRD §3.6: "A certificate covering the clock date places its account
        under `MEDICAL_MORATORIUM` protection via the gate of §2.10; registration
        recomputes the gate immediately, which may block an open shutoff order on
        the spot."

        Design: Difficulty/cross_entity_state_dependency/shutoff_create_blocked_by_active_medical_certificate
        """
        account = self._protected_account(api)
        read = get_account(account["id"])
        assert read["protection_status"] == "MEDICAL_MORATORIUM"
        assert read["service_status"] == "CONNECTED"
        rows, meta = validate_paginated(
            api.list_shutoff_orders(ADMIN, params={"account_id": account["id"]}))
        assert meta["total_count"] == 0


def test_notice_period_boundary_15_days(api):
    """PRD §3.7: "The notice period follows: `scheduled_date` must be at least 15
    days after the clock date, else `ERR_NOTICE_PERIOD_TOO_SHORT` (HTTP 422)."

    Design: Corner/validations/notice_period_boundary_15_days
    """
    account = setup_delinquent_account(
        arrearage_cents=120_000, service_address="31 Notice Ln")
    set_clock("2026-09-15T00:00:00Z")
    short = api.create_shutoff_order(
        {"account_id": account["id"], "scheduled_date": "2026-09-29"}, ADMIN)
    validate_error(short, ApiErrorId.ERR_NOTICE_PERIOD_TOO_SHORT)
    exact = api.create_shutoff_order(
        {"account_id": account["id"], "scheduled_date": "2026-09-30"}, ADMIN)
    data = validate_success(exact, 201)
    assert data["status"] == "SCHEDULED", "exactly 15 days out is accepted"


def test_not_shutoff_eligible_low_balance(api):
    """PRD §3.7: "Finally, eligibility: the account must stand `DELINQUENT` or
    `SEVERELY_DELINQUENT` with an arrearage of at least 10000 cents ($100.00),
    else `ERR_NOT_SHUTOFF_ELIGIBLE` (HTTP 422)."

    Design: Corner/validations/not_shutoff_eligible_low_balance
    """
    account = setup_delinquent_account(
        arrearage_cents=5_000, service_address="38 Lowbal Ln")
    set_clock("2026-09-10T00:00:00Z")  # age 40 days -> DELINQUENT, balance < 10000
    assert get_account(account["id"])["delinquency_tier"] == "DELINQUENT"
    resp = api.create_shutoff_order(
        {"account_id": account["id"], "scheduled_date": "2026-09-25"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_SHUTOFF_ELIGIBLE)


def test_execute_before_scheduled_date_rejected(api):
    """PRD §3.7: "The crew executes only an order still `SCHEDULED` whose
    `scheduled_date` has been reached by the clock date — anything else fails with
    `ERR_ORDER_NOT_EXECUTABLE` (HTTP 409) — and only while the account stands in
    `DISCONNECT_PENDING`."

    Design: Corner/validations/execute_before_scheduled_date_rejected
    """
    account = setup_delinquent_account(
        arrearage_cents=120_000, service_address="39 Early Exe")
    set_clock("2026-09-15T00:00:00Z")
    order = create_shutoff_order(account["id"], "2026-09-30")
    set_clock("2026-09-20T00:00:00Z")
    resp = api.execute_shutoff_order(order["id"], FIELDCREW)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_EXECUTABLE)
    stayed = validate_success(api.get_shutoff_order(order["id"], ADMIN), 200)
    assert stayed["status"] == "SCHEDULED"
    assert get_account(account["id"])["service_status"] == "DISCONNECT_PENDING"


def test_order_create_blocked_by_kept_current_dpa(api):
    """PRD §3.7: "Next, a kept-current `ACTIVE` DPA — one with every due
    installment settled — blocks creation with `ERR_DPA_KEPT_CURRENT` (HTTP 422)."

    Design: Corner/validations/order_create_blocked_by_kept_current_dpa
    """
    account = setup_delinquent_account(
        arrearage_cents=120_000, service_address="40 Keptcurrent Ct")
    set_clock("2026-09-15T00:00:00Z")
    dpa = create_and_activate_dpa(account["id"], installment_count=4)
    assert dpa["status"] == "ACTIVE"  # first installment due 2026-10-15, none due
    resp = api.create_shutoff_order(
        {"account_id": account["id"], "scheduled_date": "2026-09-30"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DPA_KEPT_CURRENT)
    assert get_account(account["id"])["service_status"] == "CONNECTED"


def test_weather_moratorium_blocks_manual_order_create(api):
    """PRD §3.7: "Then the safety gates: an `ACTIVE` medical certificate covering
    the clock date blocks creation with `ERR_SHUTOFF_BLOCKED_BY_MEDICAL`
    (HTTP 422), and an account standing in `WEATHER_MORATORIUM` blocks it with
    `ERR_SHUTOFF_BLOCKED_BY_MORATORIUM` (HTTP 422)."

    Design: Corner/validations/weather_moratorium_blocks_manual_order_create
    """
    account = setup_delinquent_account(
        arrearage_cents=120_000, service_address="41 Moratorium Mews")
    set_clock("2026-09-15T00:00:00Z")
    run_sweep({"observed_low_f": 30})
    assert get_account(account["id"])["protection_status"] == "WEATHER_MORATORIUM"
    resp = api.create_shutoff_order(
        {"account_id": account["id"], "scheduled_date": "2026-09-30"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_SHUTOFF_BLOCKED_BY_MORATORIUM)


def test_execute_blocked_order_rejected(api):
    """PRD §3.7: "The crew executes only an order still `SCHEDULED` whose
    `scheduled_date` has been reached by the clock date — anything else fails with
    `ERR_ORDER_NOT_EXECUTABLE` (HTTP 409)".
    PRD §3.7: "Protection is re-checked at execution time, not assumed from
    creation".

    Design: Corner/validations/execute_blocked_order_rejected
    """
    account = setup_delinquent_account(
        arrearage_cents=120_000, service_address="44 Blocked Exe")
    set_clock("2026-09-15T00:00:00Z")
    order = create_shutoff_order(account["id"], "2026-09-30")
    run_sweep({"observed_low_f": 30})  # protection arises; order BLOCKED
    set_clock("2026-09-30T00:00:00Z")
    resp = api.execute_shutoff_order(order["id"], FIELDCREW)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_EXECUTABLE)
    stayed = validate_success(api.get_shutoff_order(order["id"], ADMIN), 200)
    assert stayed["status"] == "BLOCKED"
    assert stayed["blocked_reason"] == "WEATHER"
    assert get_account(account["id"])["service_status"] == "DISCONNECT_PENDING"


def test_open_shutoff_order_exists_rejected(api):
    """PRD §3.7: "Then capacity: an account already carrying an open order —
    `SCHEDULED` or `BLOCKED` — rejects a second with
    `ERR_OPEN_SHUTOFF_ORDER_EXISTS` (HTTP 422)."

    Design: Corner/validations/open_shutoff_order_exists_rejected
    """
    account = setup_delinquent_account(
        arrearage_cents=120_000, service_address="45 Duporder Dr")
    set_clock("2026-09-15T00:00:00Z")
    create_shutoff_order(account["id"], "2026-09-30")
    resp = api.create_shutoff_order(
        {"account_id": account["id"], "scheduled_date": "2026-10-05"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_OPEN_SHUTOFF_ORDER_EXISTS)
    rows, meta = validate_paginated(
        api.list_shutoff_orders(ADMIN, params={"account_id": account["id"]}))
    open_orders = [o for o in rows if o["status"] in ("SCHEDULED", "BLOCKED")]
    assert len(open_orders) == 1, "exactly one open order remains"


def test_reconnect_on_connected_account_rejected(api):
    """PRD §3.7: "Reconnection, again by the `FieldCrew`, first requires the
    account to be `DISCONNECTED`, else `ERR_ACCOUNT_NOT_DISCONNECTED` (HTTP 409)."

    Design: Corner/validations/reconnect_on_connected_account_rejected
    """
    account = create_account(service_address="43 Reconnect Rd")
    resp = api.reconnect_account(account["id"], {}, FIELDCREW)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_DISCONNECTED)
