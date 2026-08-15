"""Moratorium protection gate: temperature/season boundaries, certificate-driven
cascades, and shutoff-order synchronization."""
from test_helpers import (
    api_client, validate_success, validate_paginated,
    ApiErrorId, assert_date_eq,
    setup_delinquent_account, create_shutoff_order, create_certificate,
    set_clock, run_sweep, get_account,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
CSR = TEST_USERS["csr_headers"]


class TestColdMoratoriumBoundaryExactly32F:
    def _eligible_account(self, api):
        """Aged 120000 arrearage; at clock 2026-09-15 the account is DELINQUENT
        and shutoff-eligible, with no certificates and no open order."""
        account = setup_delinquent_account(
            arrearage_cents=120_000, service_address="42 Boundary Blvd")
        set_clock("2026-09-15T00:00:00Z")
        return account

    def test_exactly_32f_triggers_weather_moratorium(self, api):
        """PRD §3.6: "An account qualifies for `WEATHER_MORATORIUM` when no covering
        medical certificate exists and either the clock date falls in the winter
        season — from November 1 up to but not including April 1, UTC — or the
        current sweep's weather inputs cross a threshold: `observed_low_f` at or
        below 32 degrees Fahrenheit (exactly 32 triggers), or
        `observed_heat_index_f` at or above 95 (exactly 95 triggers)."

        Design: Difficulty/boundary_precision_check/cold_moratorium_boundary_exactly_32f
        """
        account = self._eligible_account(api)
        sweep = run_sweep({"observed_low_f": 32})
        assert sweep["orders_created"] == 0
        read = get_account(account["id"])
        assert read["protection_status"] == "WEATHER_MORATORIUM"

    def test_33f_does_not_protect_and_auto_creates_order(self, api):
        """PRD §3.6: "`observed_low_f` at or below 32 degrees Fahrenheit (exactly
        32 triggers)".
        PRD §3.9: "it auto-creates a `SCHEDULED` order with `origin` of `AUTO` —
        `scheduled_date` set 15 days out from the clock date — only when the
        account is `CONNECTED`, stands `DELINQUENT` or `SEVERELY_DELINQUENT`,
        carries an arrearage of at least 10000 cents, is `UNPROTECTED`, holds no
        kept-current `ACTIVE` DPA, and has no open order".

        Design: Difficulty/boundary_precision_check/cold_moratorium_boundary_exactly_32f
        """
        account = self._eligible_account(api)
        run_sweep({"observed_low_f": 32})
        sweep = run_sweep({"observed_low_f": 33})
        assert sweep["orders_created"] == 1
        read = get_account(account["id"])
        assert read["protection_status"] == "UNPROTECTED"
        assert read["service_status"] == "DISCONNECT_PENDING"


class TestCertificateExpiryCascade:
    def _scenario(self, api):
        """Account 150000 aged; certificate window [2026-09-10, 2026-10-10)
        registered at clock 2026-09-15; clock advanced to 2026-10-10 so the
        half-open window no longer covers the clock date."""
        account = setup_delinquent_account(
            arrearage_cents=150_000, service_address="21 Cascade Way")
        set_clock("2026-09-15T00:00:00Z")
        cert = create_certificate(account["id"], "2026-09-10",
                                  physician_name="Dr. A", physician_license_number="L-1")
        set_clock("2026-10-10T00:00:00Z")
        return account, cert

    def test_sweep_expires_certificate_and_clears_protection(self, api):
        """PRD §3.6: "The certificate is born `ACTIVE` with an `effective_to`
        exactly 30 days after `effective_from`, and its coverage window is
        half-open: it covers every clock date from `effective_from` up to but not
        including `effective_to`."
        PRD §3.6: "the daily sweep expires a certificate once the clock date reaches
        its `effective_to`, moving it to `EXPIRED`."

        Design: Difficulty/transitive_cascade/certificate_expiry_cascade
        """
        account, cert = self._scenario(api)
        sweep = run_sweep()
        assert sweep["certificates_expired"] == 1
        expired = validate_success(api.get_certificate(cert["id"], ADMIN), 200)
        assert expired["status"] == "EXPIRED"
        read = get_account(account["id"])
        assert read["protection_status"] == "UNPROTECTED"

    def test_unprotected_sweep_auto_creates_order_and_pends_account(self, api):
        """PRD §3.9: "it auto-creates a `SCHEDULED` order with `origin` of `AUTO` —
        `scheduled_date` set 15 days out from the clock date — only when the
        account is `CONNECTED`, stands `DELINQUENT` or `SEVERELY_DELINQUENT`,
        carries an arrearage of at least 10000 cents, is `UNPROTECTED`, holds no
        kept-current `ACTIVE` DPA, and has no open order".
        PRD §3.7: "A created order stands `SCHEDULED` with `origin` of `MANUAL`
        (orders the sweep creates carry `AUTO`), and its creation moves the
        account's `service_status` from `CONNECTED` to `DISCONNECT_PENDING`".

        Design: Difficulty/transitive_cascade/certificate_expiry_cascade
        """
        account, _cert = self._scenario(api)
        sweep = run_sweep()
        assert sweep["orders_created"] == 1
        rows, meta = validate_paginated(
            api.list_shutoff_orders(ADMIN, params={"account_id": account["id"]}))
        assert meta["total_count"] == 1
        order = rows[0]
        assert order["status"] == "SCHEDULED"
        assert order["origin"] == "AUTO"
        assert_date_eq(order["scheduled_date"], "2026-10-25", "scheduled_date")
        assert get_account(account["id"])["service_status"] == "DISCONNECT_PENDING"


def test_order_block_unblock_cycle_via_sweep(api):
    """PRD §2.10: "an order in `SCHEDULED` flips to `BLOCKED` when protection
    arises, and a `BLOCKED` order returns to `SCHEDULED` when protection clears."
    PRD §3.6: "every transition of `protection_status` synchronizes any open order
    — `SCHEDULED` to `BLOCKED` with `blocked_reason` set to `WEATHER` or `MEDICAL`
    as protection arises, `BLOCKED` back to `SCHEDULED` with `blocked_reason`
    cleared to null as it clears".

    Design: Corner/state_machines/order_block_unblock_cycle_via_sweep
    """
    account = setup_delinquent_account(
        arrearage_cents=120_000, service_address="9 Block Blvd")
    set_clock("2026-09-15T00:00:00Z")
    order = create_shutoff_order(account["id"], "2026-09-30")

    sweep = run_sweep({"observed_low_f": 30})
    assert sweep["orders_blocked"] == 1
    blocked = validate_success(api.get_shutoff_order(order["id"], ADMIN), 200)
    assert blocked["status"] == "BLOCKED"
    assert blocked["blocked_reason"] == "WEATHER"

    sweep = run_sweep({"observed_low_f": 40})
    assert sweep["orders_unblocked"] == 1
    cleared = validate_success(api.get_shutoff_order(order["id"], ADMIN), 200)
    assert cleared["status"] == "SCHEDULED"
    assert cleared["blocked_reason"] is None


def test_certificate_revoke_unblocks_order(api):
    """PRD §3.6: "A certificate covering the clock date places its account under
    `MEDICAL_MORATORIUM` protection via the gate of §2.10; registration recomputes
    the gate immediately, which may block an open shutoff order on the spot."
    PRD §3.6: "Both revocation and expiry recompute the protection gate; when no
    other protection remains, an open `BLOCKED` order returns to `SCHEDULED`."

    Design: Corner/state_machines/certificate_revoke_unblocks_order
    """
    account = setup_delinquent_account(
        arrearage_cents=120_000, service_address="13 Revoke Rd")
    set_clock("2026-09-15T00:00:00Z")
    order = create_shutoff_order(account["id"], "2026-09-30")
    cert = create_certificate(account["id"], "2026-09-10",
                              physician_name="Dr. R", physician_license_number="L-9")
    blocked = validate_success(api.get_shutoff_order(order["id"], ADMIN), 200)
    assert blocked["status"] == "BLOCKED"
    assert blocked["blocked_reason"] == "MEDICAL"

    revoked = validate_success(api.revoke_certificate(cert["id"], ADMIN), 200)
    assert revoked["status"] == "REVOKED"
    unblocked = validate_success(api.get_shutoff_order(order["id"], ADMIN), 200)
    assert unblocked["status"] == "SCHEDULED"
    assert unblocked["blocked_reason"] is None
    assert get_account(account["id"])["protection_status"] == "UNPROTECTED"


def test_heat_index_boundary_95(api):
    """PRD §3.6: "`observed_low_f` at or below 32 degrees Fahrenheit (exactly 32
    triggers), or `observed_heat_index_f` at or above 95 (exactly 95 triggers)."

    Design: Corner/calculations/heat_index_boundary_95
    """
    account = setup_delinquent_account(
        arrearage_cents=120_000, service_address="25 Heat Hwy")
    set_clock("2026-09-15T00:00:00Z")
    sweep = run_sweep({"observed_heat_index_f": 95})
    assert sweep["orders_created"] == 0
    assert get_account(account["id"])["protection_status"] == "WEATHER_MORATORIUM"
    sweep = run_sweep({"observed_heat_index_f": 94})
    assert sweep["orders_created"] == 1
    assert get_account(account["id"])["protection_status"] == "UNPROTECTED"


def test_winter_season_half_open_window(api):
    """PRD §3.6: "either the clock date falls in the winter season — from
    November 1 up to but not including April 1, UTC".
    PRD §3.9: "it auto-creates a `SCHEDULED` order with `origin` of `AUTO` —
    `scheduled_date` set 15 days out from the clock date".

    Design: Corner/calculations/winter_season_half_open_window
    """
    account = setup_delinquent_account(
        arrearage_cents=120_000, service_address="26 Winter Way")
    set_clock("2026-11-01T00:00:00Z")  # winter start, inclusive
    sweep = run_sweep()
    assert sweep["orders_created"] == 0
    assert get_account(account["id"])["protection_status"] == "WEATHER_MORATORIUM"

    set_clock("2027-04-01T00:00:00Z")  # April 1 is outside the half-open window
    sweep = run_sweep()
    assert sweep["orders_created"] == 1
    read = get_account(account["id"])
    assert read["protection_status"] == "UNPROTECTED"
    assert read["service_status"] == "DISCONNECT_PENDING"
    rows, _meta = validate_paginated(
        api.list_shutoff_orders(ADMIN, params={"account_id": account["id"]}))
    assert_date_eq(rows[0]["scheduled_date"], "2027-04-16", "scheduled_date")
