"""License pricing (tiered + seasonal), loyalty earn/reverse, void refunds, and
the age/season sale guards.

Difficulty instances (queue A) get >=2 tests each; corner instances (queue B) get >=1.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    set_clock, new_customer, new_license_type, issue_license,
    TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]
MANAGER = TEST_USERS["manager_headers"]

TIERED_LT = dict(
    base_price_cents=4000, youth_max_age=15, youth_price_cents=1000,
    senior_min_age=65, senior_price_cents=2000, peak_surcharge_cents=500,
    peak_start_month=6, peak_end_month=8, min_age=0,
    season_start_date="2026-01-01", season_end_date="2026-12-31", validity_days=365,
)


# ─── Difficulty: combinatorial_formula / license_price_adult_tier_plus_peak_surcharge_mode_a
def test_adult_tier_plus_peak_surcharge_price(api):
    """PRD §3.3: "otherwise the adult base_price_cents applies."
    PRD §3.3: "if the type has a peak window and the calendar month of valid_from is at or
    after peak_start_month and at or before peak_end_month, the peak_surcharge_cents is added;
    otherwise nothing is added. The price_paid_cents is the selected tier price plus the
    surcharge, in whole cents."

    Design: Difficulty/combinatorial_formula/license_price_adult_tier_plus_peak_surcharge_mode_a
    """
    set_clock("2026-07-10T00:00:00Z")
    cust = new_customer(date_of_birth="1986-01-01")  # age 40 on 2026-07-10
    lt = new_license_type(**TIERED_LT)
    sale = validate_success(api.create_license_sale(
        {"customer_id": cust["id"], "license_type_id": lt["id"]}, CLERK), 201)
    assert sale["price_paid_cents"] == 4500


def test_adult_peak_price_selects_base_not_youth_or_senior(api):
    """PRD §3.3: "if the type has a youth tier and the age is at or below youth_max_age, the
    youth price applies; otherwise if the type has a senior tier and the age is at or above
    senior_min_age, the senior price applies; otherwise the adult base_price_cents applies."

    Design: Difficulty/combinatorial_formula/license_price_adult_tier_plus_peak_surcharge_mode_a
    """
    set_clock("2026-07-10T00:00:00Z")
    cust = new_customer(date_of_birth="1986-01-01")
    lt = new_license_type(**TIERED_LT)
    sale = issue_license(cust["id"], lt["id"])
    # 40 is neither <=15 (youth 1000) nor >=65 (senior 2000): base 4000 + July peak 500.
    assert sale["price_paid_cents"] == 4500
    fetched = get_success_data(api.get_license_sale(sale["id"], CLERK))
    assert fetched["price_paid_cents"] == 4500


# ─── Corner: calculations / license_price_youth_tier_selected
def test_youth_tier_selected_no_peak(api):
    """PRD §3.3: "if the type has a youth tier and the age is at or below youth_max_age, the
    youth price applies"

    Design: Corner/calculations/license_price_youth_tier_selected
    """
    set_clock("2026-03-10T00:00:00Z")  # March: outside peak months 6-8
    cust = new_customer(date_of_birth="2016-01-01")  # age 10
    lt = new_license_type(**TIERED_LT)
    sale = issue_license(cust["id"], lt["id"])
    assert sale["price_paid_cents"] == 1000


# ─── Difficulty: compensating_invariant / loyalty_points_conserved_license_issue_then_void
def test_license_issue_credits_points(api):
    """PRD §3.3: "At issue the sale earns loyalty points equal to the price paid divided by
    100 and rounded down to a whole number of dollars, at a rate of one point per whole
    dollar. Those points_earned are added to the customer's loyalty_points_balance and to
    their lifetime_points_earned, and the tier is recomputed."

    Design: Difficulty/compensating_invariant/loyalty_points_conserved_license_issue_then_void
    """
    set_clock("2026-07-10T00:00:00Z")
    cust = new_customer(date_of_birth="1980-01-01")
    lt = new_license_type(base_price_cents=3000)
    sale = issue_license(cust["id"], lt["id"])
    assert sale["points_earned"] == 30
    refreshed = get_success_data(api.get_customer(cust["id"], CLERK))
    assert refreshed["loyalty_points_balance"] == 30
    assert refreshed["lifetime_points_earned"] == 30


def test_void_within_grace_reverses_points_and_full_refund(api):
    """PRD §3.3: "the previously credited `points_earned` are subtracted from both
    `loyalty_points_balance` and `lifetime_points_earned`, and the tier is recomputed."
    PRD §3.3: "If elapsed days is at most 7, the refund is the full `price_paid_cents`."

    Design: Difficulty/compensating_invariant/loyalty_points_conserved_license_issue_then_void
    """
    set_clock("2026-07-10T00:00:00Z")
    cust = new_customer(date_of_birth="1980-01-01")
    lt = new_license_type(base_price_cents=3000)
    sale = issue_license(cust["id"], lt["id"])
    voided = validate_success(api.void_license_sale(sale["id"], CLERK), 200)
    assert voided["status"] == "VOIDED"
    assert voided["refund_amount_cents"] == 3000
    refreshed = get_success_data(api.get_customer(cust["id"], CLERK))
    assert refreshed["loyalty_points_balance"] == 0
    assert refreshed["lifetime_points_earned"] == 0


# ─── Corner: calculations / license_void_prorated_after_grace
def test_void_after_grace_prorated_refund(api):
    """PRD §3.3: "Otherwise the license is prorated: remaining days are validity_days minus
    elapsed days but never below zero, and the refund is price_paid_cents multiplied by
    remaining days divided by validity_days, rounded half up to whole cents."

    Design: Corner/calculations/license_void_prorated_after_grace
    """
    set_clock("2026-07-10T00:00:00Z")
    cust = new_customer(date_of_birth="1986-01-01")
    lt = new_license_type(base_price_cents=4000, peak_surcharge_cents=500,
                          peak_start_month=6, peak_end_month=8, validity_days=365)
    sale = issue_license(cust["id"], lt["id"])  # priced 4500 (adult + peak)
    set_clock("2026-08-20T00:00:00Z")  # 41 days after valid_from
    voided = validate_success(api.void_license_sale(sale["id"], CLERK), 200)
    # round(4500 * (365 - 41) / 365) = round(3994.52) = 3995
    assert voided["refund_amount_cents"] == 3995


# ─── Corner: state_machines / void_already_voided_license_returns_already_voided
def test_void_already_voided_rejected(api):
    """PRD §3.3: "A clerk or manager may void an active sale (ACTIVE → VOIDED); voiding one
    that is already voided is refused with ERR_ALREADY_VOIDED."

    Design: Corner/state_machines/void_already_voided_license_returns_already_voided
    """
    set_clock("2026-07-10T00:00:00Z")
    cust = new_customer(date_of_birth="1980-01-01")
    lt = new_license_type(base_price_cents=3000)
    sale = issue_license(cust["id"], lt["id"])
    validate_success(api.void_license_sale(sale["id"], CLERK), 200)
    res = api.void_license_sale(sale["id"], CLERK)
    validate_error(res, "ERR_ALREADY_VOIDED", 409)


# ─── Corner: validations / license_sale_out_of_season_alone_rejected
def test_out_of_season_sale_rejected(api):
    """PRD §3.3: "The logical clock's date must also fall on or after season_start_date and
    on or before season_end_date; a sale attempted outside that window is refused with
    ERR_LICENSE_OUT_OF_SEASON (HTTP 422)."

    Design: Corner/validations/license_sale_out_of_season_alone_rejected
    """
    set_clock("2026-07-10T00:00:00Z")  # before season start
    cust = new_customer(date_of_birth="1986-01-01")  # age 40 clears min_age 16
    lt = new_license_type(base_price_cents=5000, min_age=16,
                          season_start_date="2026-08-01", season_end_date="2026-12-31")
    res = api.create_license_sale({"customer_id": cust["id"], "license_type_id": lt["id"]}, CLERK)
    validate_error(res, "ERR_LICENSE_OUT_OF_SEASON", 422)


# ─── Difficulty: priority_pair_validation_conflict / license_age_safety_beats_out_of_season
def test_age_requirement_beats_out_of_season(api):
    """PRD §2.9: "the checks are evaluated in a fixed priority order so that the returned
    error is deterministic."
    PRD §2.9: "the domain-specific business rules run — age requirement, season window,
    guide and angler schedule conflicts, license-held requirement, seat capacity, ..."
    PRD §3.3: "if the customer is too young the sale is refused with
    ERR_AGE_REQUIREMENT_NOT_MET (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/license_age_safety_beats_out_of_season
    """
    set_clock("2026-07-10T00:00:00Z")  # before season AND
    cust = new_customer(date_of_birth="2014-01-01")  # age 12 < min_age 16
    lt = new_license_type(base_price_cents=5000, min_age=16,
                          season_start_date="2026-08-01", season_end_date="2026-12-31")
    res = api.create_license_sale({"customer_id": cust["id"], "license_type_id": lt["id"]}, CLERK)
    validate_error(res, "ERR_AGE_REQUIREMENT_NOT_MET", 422)


def test_age_and_season_both_fail_no_sale_persisted(api):
    """PRD §2.9: "the domain-specific business rules run — age requirement, season window,
    guide and angler schedule conflicts, license-held requirement, seat capacity, ..."
    PRD §3.3: "if the customer is too young the sale is refused with
    ERR_AGE_REQUIREMENT_NOT_MET (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/license_age_safety_beats_out_of_season
    """
    set_clock("2026-07-10T00:00:00Z")
    cust = new_customer(date_of_birth="2014-01-01")
    lt = new_license_type(base_price_cents=5000, min_age=16,
                          season_start_date="2026-08-01", season_end_date="2026-12-31")
    res = api.create_license_sale({"customer_id": cust["id"], "license_type_id": lt["id"]}, CLERK)
    validate_error(res, "ERR_AGE_REQUIREMENT_NOT_MET", 422)
    data, meta = validate_paginated(
        api.list_license_sales(CLERK, params={"customer_id": cust["id"]}))
    assert meta["total_count"] == 0
