"""Interop policy tests — creation, lookup precedence, ambiguous-row
escape.

PRD §2.9 and §3.7 govern interop policies.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    assert_interop_policy,
    create_interop_policy_payload,
    create_account,
    create_and_bind_transponder,
    create_vehicle,
    ingest_toll_event,
    setup_account_with_bound_transponder,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Creation — PRD §3.7
# ---------------------------------------------------------------------------
def test_interop_policy_create_succeeds(api):
    """PRD §3.7: "Each row carries a `home_agency` and a
    `gantry_agency` chosen from the four agency codes, a `surcharge_bps`
    between 0 and 5000 inclusive defaulting to 0, and a `discount_bps`
    between 0 and 5000 inclusive defaulting to 0."

    Claim: a fresh InteropPolicy returns the supplied agency codes and
    bps values.
    """
    res = api.create_interop_policy(
        create_interop_policy_payload(
            home_agency="NY_EZPASS", gantry_agency="NJ_EZPASS",
            surcharge_bps=300, discount_bps=100,
        ),
        TEST_USERS["agency_admin_headers"],
    )
    data = validate_success(res, expected_status=201)
    assert_interop_policy(data)
    assert data["home_agency"] == "NY_EZPASS"
    assert data["gantry_agency"] == "NJ_EZPASS"
    assert data["surcharge_bps"] == 300
    assert data["discount_bps"] == 100


def test_interop_policy_defaults(api):
    """PRD §3.7: "a `surcharge_bps` between 0 and 5000 inclusive
    defaulting to 0, and a `discount_bps` between 0 and 5000 inclusive
    defaulting to 0."

    Claim: omitting surcharge_bps and discount_bps → both default to 0.
    """
    res = api.create_interop_policy(
        {"home_agency": "PA_TURNPIKE", "gantry_agency": "FL_SUNPASS"},
        TEST_USERS["agency_admin_headers"],
    )
    data = validate_success(res, expected_status=201)
    assert data["surcharge_bps"] == 0
    assert data["discount_bps"] == 0


def test_interop_policy_list(api):
    """PRD §3.7: "Listing accepts optional `home_agency` and
    `gantry_agency` filters in addition to the usual pagination
    parameters."

    Claim: GET /interop-policies returns a paginated list.
    """
    api.create_interop_policy(
        create_interop_policy_payload(
            home_agency="FL_SUNPASS", gantry_agency="PA_TURNPIKE",
            surcharge_bps=10, discount_bps=5,
        ),
        TEST_USERS["agency_admin_headers"],
    )
    res = api.list_interop_policies(TEST_USERS["agency_admin_headers"])
    data, meta = validate_paginated(res)
    assert isinstance(data, list)
    assert meta["total_count"] >= 1


# ---------------------------------------------------------------------------
# Lookup multiplicity — PRD §2.9
# ---------------------------------------------------------------------------
def test_interop_policy_ambiguous_raises_error(api):
    """PRD §2.9: "If more than one `InteropPolicy` row matches the
    `(home_agency, gantry_agency)` pair, the system uses the row with
    the most recent `created_at`, but the request that produced the
    lookup is rejected with `ERR_INTEROP_POLICY_AMBIGUOUS` so the
    operator is notified of the data condition."

    Claim: with two policies on the same (home, gantry) pair, a
    cross-agency toll-event ingest returns 422 with
    ERR_INTEROP_POLICY_AMBIGUOUS.
    """
    # Two policies on the same (home, gantry) pair.
    api.create_interop_policy(
        create_interop_policy_payload(
            home_agency="NY_EZPASS", gantry_agency="NJ_EZPASS",
            surcharge_bps=100, discount_bps=0,
        ),
        TEST_USERS["agency_admin_headers"],
    )
    api.create_interop_policy(
        create_interop_policy_payload(
            home_agency="NY_EZPASS", gantry_agency="NJ_EZPASS",
            surcharge_bps=500, discount_bps=200,
        ),
        TEST_USERS["agency_admin_headers"],
    )

    a, v, t = setup_account_with_bound_transponder(
        home_agency_code="NY_EZPASS", balance_cents=10000,
    )
    res = api.create_toll_event(
        {"gantry_id": "AMB", "agency_code": "NJ_EZPASS",
         "base_rate_cents": 200,
         "read_at": "2026-05-20T12:00:00.000Z",
         "transponder_serial": t["serial_number"]},
        TEST_USERS["gantry_operator_headers"],
    )
    assert res.status_code == 422
    body = res.json()
    assert body["data"]["error_id"] == "ERR_INTEROP_POLICY_AMBIGUOUS"


# ---------------------------------------------------------------------------
# Empty policy set — PRD §2.9
# ---------------------------------------------------------------------------
def test_interop_no_policy_rows_falls_back_to_zero_adjust(api):
    """PRD §2.9: "When the two differ, the server consults
    `InteropPolicy` rows keyed by `(home_agency, gantry_agency)` and
    applies a surcharge expressed in basis points (`surcharge_bps`)
    and a discount expressed in basis points (`discount_bps`); the
    algorithm uses the *net* of the two — surcharge minus discount —
    applied as a fraction of `gross_toll_cents`".

    Claim: a cross-agency toll with NO InteropPolicy rows for the
    (home, gantry) pair has interop_adjust = 0 — net == gross.

    (Verifies the empty-collection fallback documented in §2.9: with
    no matching row, no adjustment is applied.)
    """
    # Build cross-agency: home=NY_EZPASS, gantry=FL_SUNPASS — leave no
    # policy row in place.
    a, v, t = setup_account_with_bound_transponder(
        home_agency_code="NY_EZPASS", balance_cents=10000,
    )
    data = ingest_toll_event(
        gantry_id="G2", agency_code="FL_SUNPASS", base_rate_cents=300,
        transponder_serial=t["serial_number"],
    )
    assert data["gross_toll_cents"] == 300
    assert data["net_toll_cents"] == 300
