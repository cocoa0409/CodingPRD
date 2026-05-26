"""Tests covering the daily-topup-cap boundary on the topup endpoint."""
import pytest

from test_helpers import (
    validate_error,
    validate_success,
    set_clock,
    create_household,
    resolve_parent_account_id,
    api_client,
    TEST_USERS,
    make_parent_headers,
)


# ---------------------------------------------------------------------
# Difficulty rule 6 / instance 2 — topup cap boundary at exactly $200.
# ---------------------------------------------------------------------

def test_topup_at_exact_daily_cap_succeeds(api):
    """PRD §3.6: "The cap check then compares the sum of
    `daily_topup_total_cents` and the requested `amount_cents` against the
    constant `DAILY_TOPUP_CAP_CENTS` of 20,000 cents ($200) per UTC calendar
    day. If the sum would exceed the cap, the top-up is rejected with
    `ERR_TOPUP_CAP_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/topup_cap_boundary_at_exact_200_dollars
    """
    set_clock("2026-04-11T00:00:00.000Z")
    hh = create_household(
        family_size=2, annual_income_cents=3_000_000,
        address_state="CA", direct_certification_flag=False,
    )
    pa_id = resolve_parent_account_id(hh["id"])
    # First topup at exactly the cap — must succeed (0 + 20000 == 20000, not > cap).
    res = api.topup_parent_account(
        pa_id,
        {"amount_cents": 20000, "idempotency_key": "cap-1"},
        make_parent_headers(hh["id"]),
    )
    data = validate_success(res, 201)
    assert data["amount_cents"] == 20000, (
        f"entry amount must match request; got {data['amount_cents']}"
    )


def test_topup_one_cent_over_cap_rejects(api):
    """PRD §3.6: "If the sum would exceed the cap, the top-up is rejected
    with `ERR_TOPUP_CAP_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/topup_cap_boundary_at_exact_200_dollars
    """
    set_clock("2026-04-11T00:00:00.000Z")
    hh = create_household(
        family_size=2, annual_income_cents=3_000_000,
        address_state="CA", direct_certification_flag=False,
    )
    pa_id = resolve_parent_account_id(hh["id"])
    # First topup at exactly cap.
    first = api.topup_parent_account(
        pa_id,
        {"amount_cents": 20000, "idempotency_key": "cap-A"},
        make_parent_headers(hh["id"]),
    )
    validate_success(first, 201)
    # Second topup of 1 cent same day — 20000 + 1 > 20000 → reject.
    res = api.topup_parent_account(
        pa_id,
        {"amount_cents": 1, "idempotency_key": "cap-B"},
        make_parent_headers(hh["id"]),
    )
    validate_error(res, "ERR_TOPUP_CAP_EXCEEDED", expected_status=422)
