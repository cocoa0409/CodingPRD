"""Payoff-quote computation, the district-formed precondition, quote-date and expiry
guards, and the optimistic-concurrency version guard.

Covers difficulty instances payoff_immediate_vs_next_call_date,
payoff_quote_blocked_when_district_not_formed, and corner instances
payoff_quote_date_before_issuance_rejected, honor_expired_quote_returns_invalid_quote_state,
payoff_quote_stale_parcel_version_conflict.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
    setup_issued_bond, set_clock, parcel_version, create_payoff_quote,
    create_district, add_parcel,
)

TREAS = TEST_USERS["treasurer_headers"]
AUDIT = TEST_USERS["auditor_headers"]

_P1_P2 = [
    {"apn": "A-1", "owner_name": "O1", "benefit_units": 60},
    {"apn": "A-2", "owner_name": "O2", "benefit_units": 40},
]


def _setup_p1_6m(api, term_years=10):
    _, parcels, _, _ = setup_issued_bond(
        api, parcels=_P1_P2, total_project_cost_cents=10_000_000, roll_method="BENEFIT_UNITS",
        bond={"issuance_date": "2026-07-01T00:00:00Z", "coupon_rate_bps": 500,
              "term_years": term_years, "reserve_fund_pct": 0.10},
    )
    return parcels[0]


# --- dual-variant payoff: IMMEDIATE vs NEXT_CALL_DATE ---

def test_payoff_immediate_prorates_interest_to_quote_date(api):
    """PRD §3.7: "Under IMMEDIATE, interest is prorated to the quote date: it is the
    remaining principal multiplied by the annual rate (coupon_rate_bps divided by 10000),
    multiplied by the 30/360 day count from the bond's issuance_date to the quote_date,
    divided by the 360-day basis, rounded half up." PRD §3.7: "The total_payoff_cents is
    then the remaining principal plus accrued_interest_cents plus prepayment_premium_cents
    minus reserve_credit_cents."

    Design: Difficulty/dual_variant_calc/payoff_immediate_vs_next_call_date
    """
    parcel = _setup_p1_6m(api)
    quote = validate_success(create_payoff_quote(
        api, parcel["id"], "IMMEDIATE", "2026-10-01T00:00:00Z",
        parcel_version(api, parcel["id"]), headers=TREAS), 201)
    assert quote["accrued_interest_cents"] == 75000
    assert quote["total_payoff_cents"] == 5655000


def test_payoff_next_call_date_charges_full_year_interest(api):
    """PRD §3.7: "Under NEXT_CALL_DATE, interest is a full year to the next annual call date:
    it is simply the remaining principal multiplied by the annual rate, rounded half up —
    which for a same-year quote is strictly larger than the immediate proration, so the two
    modes yield different totals."

    Design: Difficulty/dual_variant_calc/payoff_immediate_vs_next_call_date
    """
    parcel = _setup_p1_6m(api)
    quote = validate_success(create_payoff_quote(
        api, parcel["id"], "NEXT_CALL_DATE", "2026-10-01T00:00:00Z",
        parcel_version(api, parcel["id"]), headers=TREAS), 201)
    assert quote["accrued_interest_cents"] == 300000
    assert quote["total_payoff_cents"] == 5880000


# --- payoff-quote gated on district being FORMED ---

def _proposed_district_with_parcel(api):
    district = create_district(api, name="DXF", formation_method="BENEFIT_UNITS",
                               total_project_cost_cents=1_000_000)
    parcel = add_parcel(api, district["id"], apn="XF-1", owner_name="OXF", benefit_units=100)
    return district, parcel


def test_payoff_quote_blocked_when_district_not_formed(api):
    """PRD §3.7: "A quote may be produced only against a parcel that is ACTIVE ... whose
    parent district is FORMED — otherwise ERR_DISTRICT_NOT_FORMED (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/payoff_quote_blocked_when_district_not_formed
    """
    _, parcel = _proposed_district_with_parcel(api)
    validate_error(create_payoff_quote(
        api, parcel["id"], "IMMEDIATE", "2026-08-01T00:00:00Z",
        parcel_version(api, parcel["id"]), headers=TREAS),
        ApiErrorId.ERR_DISTRICT_NOT_FORMED.value)


def test_payoff_quote_blocked_creates_no_quote(api):
    """PRD §3.7: "A newly created `PayoffQuote` starts `QUOTED`". PRD §3.7: "whose parent
    district is `FORMED` — otherwise `ERR_DISTRICT_NOT_FORMED` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/payoff_quote_blocked_when_district_not_formed
    """
    _, parcel = _proposed_district_with_parcel(api)
    create_payoff_quote(api, parcel["id"], "IMMEDIATE", "2026-08-01T00:00:00Z",
                        parcel_version(api, parcel["id"]), headers=TREAS)
    data, _ = validate_paginated(api.list_payoff_quotes(parcel["id"], AUDIT, params={"limit": 100}))
    assert data == []


# --- corner: quote_date before bond issuance ---

def test_payoff_quote_date_before_issuance_rejected(api):
    """PRD §3.7: "only when the quote_date is at or after the bond's issuance_date, since a
    payoff cannot be dated before the bond exists; an earlier quote_date is rejected with
    ERR_QUOTE_DATE_INVALID (HTTP 422)."

    Design: Corner/errors/payoff_quote_date_before_issuance_rejected
    """
    _, parcels, _, _ = setup_issued_bond(
        api, parcels=[{"apn": "ER2-1", "owner_name": "O", "benefit_units": 100}],
        total_project_cost_cents=1_000_000, roll_method="BENEFIT_UNITS", bond={"term_years": 5},
    )
    parcel = parcels[0]
    validate_error(create_payoff_quote(
        api, parcel["id"], "IMMEDIATE", "2026-06-01T00:00:00Z",
        parcel_version(api, parcel["id"]), headers=TREAS),
        ApiErrorId.ERR_QUOTE_DATE_INVALID.value)


# --- corner: honoring an expired quote ---

def test_honor_expired_quote_rejected(api):
    """PRD §3.7: "once the logical clock passes a quote's `valid_until` the quote is lazily
    promoted from `QUOTED` to `EXPIRED`." PRD §3.7: "a quote past its `valid_until` has already
    lazily become `EXPIRED` and is therefore no longer honorable, yielding
    `ERR_INVALID_QUOTE_STATE` (HTTP 409)".

    Design: Corner/state_machines/honor_expired_quote_returns_invalid_quote_state
    """
    _, parcels, _, _ = setup_issued_bond(
        api, parcels=[{"apn": "S5-1", "owner_name": "O", "benefit_units": 100}],
        total_project_cost_cents=500_000, roll_method="BENEFIT_UNITS", bond={"term_years": 5},
    )
    parcel = parcels[0]
    quote = validate_success(create_payoff_quote(
        api, parcel["id"], "IMMEDIATE", "2026-08-01T00:00:00Z",
        parcel_version(api, parcel["id"]), headers=TREAS), 201)
    set_clock(api, "2026-10-01T00:00:00Z")
    validate_error(api.honor_payoff_quote(quote["id"], TREAS),
                   ApiErrorId.ERR_INVALID_QUOTE_STATE.value)


# --- corner: optimistic-concurrency stale parcel version ---

def test_payoff_quote_stale_parcel_version_rejected(api):
    """PRD §2.8: "If `expected_parcel_version` does not equal the parcel's current `version`,
    the request is rejected with `ERR_STALE_PARCEL_VERSION` (HTTP 412)." PRD §3.7: "it
    increments the parcel's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/payoff_quote_stale_parcel_version_conflict
    """
    _, parcels, _, _ = setup_issued_bond(
        api, parcels=[{"apn": "OCC-1", "owner_name": "O", "benefit_units": 100}],
        total_project_cost_cents=1_000_000, roll_method="BENEFIT_UNITS", bond={"term_years": 5},
    )
    parcel = parcels[0]
    pv0 = parcel_version(api, parcel["id"])
    validate_success(create_payoff_quote(
        api, parcel["id"], "IMMEDIATE", "2026-08-01T00:00:00Z", pv0, headers=TREAS), 201)
    # second create still carries the pre-bump version → stale
    validate_error(create_payoff_quote(
        api, parcel["id"], "NEXT_CALL_DATE", "2026-08-01T00:00:00Z", pv0, headers=TREAS),
        ApiErrorId.ERR_STALE_PARCEL_VERSION.value)
