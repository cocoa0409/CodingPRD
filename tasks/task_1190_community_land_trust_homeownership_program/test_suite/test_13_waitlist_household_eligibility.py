"""Waitlist match requires buyer household ELIGIBLE at match time."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_waitlist_entry_payload,
    get_success_data,
    setup_eligible_household,
    setup_listed_resale,
    setup_program,
    validate_error,
)


def _is():
    return TEST_USERS["intake_specialist_headers"]


def _lm():
    return TEST_USERS["lease_manager_headers"]


def _pa():
    return TEST_USERS["platform_admin_headers"]


def test_match_with_only_ineligible_buyer_returns_no_eligible_buyer():
    """PRD §3.5: "The candidate pool is every `WaitlistEntry` whose status is
    `ACTIVE`, whose household is `ELIGIBLE` (and whose household's
    `education_completed_at` is non-null), whose `max_price_cents` is at
    least the listing's `asking_price_cents`, and whose `desired_bedrooms` is
    at most the unit's `bedrooms`. ... If the filtered pool is empty, the
    run is rejected with `ERR_NO_ELIGIBLE_BUYER` and the listing remains
    `OPEN`."

    Design: Difficulty/cross_entity_state_dependency/waitlist_match_requires_household_eligible
    """
    prog = setup_program(name="P-WL1")
    _, unit, _, _, listing = setup_listed_resale(prog["id"])

    # Buyer certified long in the past → eligibility lapses after 24 months.
    # Build the buyer entry while ELIGIBLE, then let the eligibility expire.
    pa = _pa()
    get_success_data(api_client.set_clock("2024-01-01T00:00:00Z", pa))
    hh_b, _, _ = setup_eligible_household(
        prog["id"], verified_income_cents=6_000_000, household_size=4, legal_name="Buyer"
    )
    entry = get_success_data(
        api_client.create_waitlist_entry(
            prog["id"],
            hh_b["id"],
            create_waitlist_entry_payload(desired_bedrooms=3, max_price_cents=50_000_000),
            _is(),
        )
    )
    # Advance clock > 24 months so eligibility lapses to EXPIRED.
    get_success_data(api_client.set_clock("2026-02-15T00:00:00Z", pa))
    hh_after = get_success_data(api_client.get_household(prog["id"], hh_b["id"], _lm()))
    assert hh_after["eligibility_status"] == "EXPIRED"

    listing_now = get_success_data(
        api_client.get_resale_listing(prog["id"], unit["id"], listing["id"], _lm())
    )
    resp = api_client.run_matching(
        prog["id"],
        unit["id"],
        listing["id"],
        {"expected_listing_version": listing_now["version"]},
        _lm(),
    )
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_BUYER.value)

    listing_after = get_success_data(
        api_client.get_resale_listing(prog["id"], unit["id"], listing["id"], _lm())
    )
    assert listing_after["status"] == "OPEN"


def test_match_with_eligible_buyer_succeeds():
    """PRD §3.5: "A successful match moves the chosen entry to `MATCHED` with
    `matched_at` set to now, `matched_unit_id` set to the listing's unit, and
    `match_rank_at_match` set to the entry's rank among active entries at
    match time (1 = highest priority)."

    Design: Difficulty/cross_entity_state_dependency/waitlist_match_requires_household_eligible
    """
    prog = setup_program(name="P-WL2")
    _, unit, _, _, listing = setup_listed_resale(prog["id"])

    hh_b, _, _ = setup_eligible_household(
        prog["id"], verified_income_cents=6_000_000, household_size=4, legal_name="Buyer"
    )
    entry = get_success_data(
        api_client.create_waitlist_entry(
            prog["id"],
            hh_b["id"],
            create_waitlist_entry_payload(desired_bedrooms=3, max_price_cents=50_000_000),
            _is(),
        )
    )

    listing_now = get_success_data(
        api_client.get_resale_listing(prog["id"], unit["id"], listing["id"], _lm())
    )
    matched = get_success_data(
        api_client.run_matching(
            prog["id"],
            unit["id"],
            listing["id"],
            {"expected_listing_version": listing_now["version"]},
            _lm(),
        )
    )
    assert matched["status"] == "MATCHED"
    assert matched["matched_waitlist_entry_id"] == entry["id"]
    assert matched["buyer_household_id"] == hh_b["id"]
