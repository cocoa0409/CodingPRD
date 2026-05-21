"""Security: cross-visitor ownership, SQL injection, mass assignment,
missing auth.

Covers PRD §2.1 (ownership checks; ERR_FORBIDDEN on cross-visitor
ops), §2.4 (computed fields not accepted from input).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    build_user_headers,
    create_campground_reservation,
    create_park,
    create_park_payload,
    create_timed_entry,
    create_visitor,
    create_visitor_with_wallet,
    create_visitor_payload,
    date_to_local_str,
    make_visitor_headers,
    setup_park_with_campground,
    validate_error,
    validate_success,
)


SQL_INJECTION_PAYLOADS = [
    "'; DROP TABLE parks; --",
    "' OR '1'='1",
    "' UNION SELECT * FROM visitors--",
    "1; DELETE FROM campgrounds; --",
]
SQL_ERROR_PATTERNS = [
    "sql syntax", "sqlstate", "database error",
    "sqlite", "pg_", "mysql_",
]


@pytest.mark.parametrize("injection", SQL_INJECTION_PAYLOADS)
def test_sql_injection_park_name(api, park_admin_headers, injection):
    """PRD §3.2: name is a string field; the API must not pass it to
    SQL unsafely. We assert no 5xx and no SQL error fingerprint leaks.
    """
    resp = api.create_park(
        create_park_payload(name=injection), park_admin_headers,
    )
    assert resp.status_code < 500, (
        f"SQL-injection payload must not cause 500; got {resp.status_code}"
    )
    body = resp.text.lower()
    for pat in SQL_ERROR_PATTERNS:
        assert pat not in body, (
            f"SQL error fingerprint {pat!r} leaked in response: {resp.text}"
        )


def test_mass_assignment_ignored_on_park(api, park_admin_headers):
    """PRD §2.4 + §3.2: computed fields (status) and audit fields (id,
    created_at, version) are server-managed. Posting an explicit status
    must not override the OPEN initial value per PRD §3.2: "A newly
    created park starts in the OPEN status."
    """
    payload = create_park_payload()
    payload["status"] = "FROZEN"
    payload["version"] = 9999
    payload["id"] = NON_EXISTENT_UUID
    resp = api.create_park(payload, park_admin_headers)
    park = validate_success(resp, 201)
    assert park["status"] == "OPEN", (
        f"PRD §3.2: created park must start OPEN regardless of input "
        f"status; got {park['status']!r}"
    )
    assert park["id"] != NON_EXISTENT_UUID
    assert park["version"] == 1


def test_mass_assignment_ignored_on_visitor(api,
                                            system_operator_headers):
    """PRD §3.1: wallet_balance_cents and lottery_strikes are computed
    fields that begin at 0 — input must not seed them."""
    payload = create_visitor_payload()
    payload["wallet_balance_cents"] = 999_999
    payload["lottery_strikes"] = 2
    resp = api.create_visitor(payload, system_operator_headers)
    v = validate_success(resp, 201)
    assert v["wallet_balance_cents"] == 0
    assert v["lottery_strikes"] == 0


class TestOwnership:

    def test_visitor_cannot_cancel_other_visitors_timed_entry(self, api):
        """PRD §2.1: "confirm/cancel/accept/decline actions on a
        resource owned by another visitor are rejected with
        ERR_FORBIDDEN."
        """
        park = create_park()
        v1 = create_visitor_with_wallet(wallet_cents=5_000)
        v2 = create_visitor_with_wallet(wallet_cents=5_000)
        r = create_timed_entry(
            park["id"], v1,
            entry_date_local=date_to_local_str(
                date.today() + timedelta(days=5),
            ),
            window_start_local="09:00",
        )
        resp = api.cancel_timed_entry(
            park["id"], r["id"], make_visitor_headers(v2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_visitor_cannot_confirm_other_visitors_campground(self, api):
        """PRD §2.1: ownership applies to confirm as well."""
        park, c = setup_park_with_campground()
        v1 = create_visitor_with_wallet(wallet_cents=20_000)
        v2 = create_visitor_with_wallet(wallet_cents=20_000)
        r = create_campground_reservation(
            c["id"], v1,
            site_kind="STANDARD", party_size=2,
            check_in_date_local=date_to_local_str(
                date.today() + timedelta(days=30),
            ),
            check_out_date_local=date_to_local_str(
                date.today() + timedelta(days=32),
            ),
        )
        resp = api.confirm_campground_reservation(
            c["id"], r["id"], make_visitor_headers(v2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_visitor_cannot_read_other_visitors_ledger(self, api):
        """PRD §2.1: "Ownership checks on any resource that references
        a visitor (a campground reservation, ... an America the
        Beautiful Pass, a ledger entry) compare the resource's
        visitor_id to X-User-ID".
        """
        v1 = create_visitor()
        v2 = create_visitor()
        resp = api.list_visitor_ledger(
            v1["id"], make_visitor_headers(v2["id"]),
        )
        # PRD §2.1 names ERR_FORBIDDEN for the ownership violation.
        body = resp.json()
        err = body.get("data", {}).get("error_id")
        assert err == ApiErrorId.ERR_FORBIDDEN.value, (
            f"cross-visitor ledger read should be ERR_FORBIDDEN; got {err!r}"
        )


class TestRBACEnforcement:

    @pytest.mark.parametrize("role", ["Visitor", "ParkRanger"])
    def test_only_park_admin_can_provision_park(self, api, role):
        """PRD §4: "POST /parks ... ParkAdmin" (only)."""
        headers = build_user_headers(f"u-{role.lower()}", role)
        resp = api.create_park(create_park_payload(), headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_park_admin_cannot_check_in_visitor(self, api):
        """PRD §4: "POST /parks/{park_id}/timed-entry/{id}/check-in ...
        ParkRanger" (only)."""
        from test_helpers import setup_confirmed_timed_entry
        park, v, r = setup_confirmed_timed_entry(days_out=5)
        resp = api.check_in_timed_entry(
            park["id"], r["id"], TEST_USERS["park_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
