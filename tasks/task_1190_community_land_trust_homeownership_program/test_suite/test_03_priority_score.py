"""Waitlist priority scoring — multi-input non-linear formula."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_program_payload,
    create_waitlist_entry_payload,
    get_success_data,
    setup_eligible_household,
    setup_program,
)


def _is():
    return TEST_USERS["intake_specialist_headers"]


def _pa():
    return TEST_USERS["platform_admin_headers"]


def test_priority_score_need_component_at_creation():
    """PRD §3.6: "The need score is one minus the household's `ami_pct`,
    multiplied by 1000, and rounded to the nearest integer — lower AMI yields
    a higher need score."
    PRD §3.6: "The age score is the integer number of days since the entry's
    `created_at`, capped at 365 days (one year)."
    PRD §3.6: "The stored score does not include the bedroom-size-match bonus;
    that bonus of 50 points is added only at match evaluation time when the
    absolute difference between the unit's bedrooms and the household's size
    is at most 1."

    Design: Difficulty/combinatorial_formula/priority_score_multi_input_nonlinear
    """
    prog = setup_program(name="P-PS1")
    # ami_pct = 0.6 → need_score = round((1 - 0.6) * 1000) = 400
    # At creation (age 0 days), age_score = 0.
    hh, _, _ = setup_eligible_household(
        prog["id"], verified_income_cents=6_000_000, household_size=4
    )
    entry = get_success_data(
        api_client.create_waitlist_entry(
            prog["id"],
            hh["id"],
            create_waitlist_entry_payload(desired_bedrooms=3, max_price_cents=50_000_000),
            _is(),
        )
    )
    assert entry["priority_score"] == 400, (
        f"At creation, priority_score == need_score (age 0). Expected 400, got "
        f"{entry['priority_score']}"
    )


def test_priority_score_age_component_capped_at_365():
    """PRD §3.6: "The age score is the integer number of days since the entry's
    `created_at`, capped at 365 days (one year)."

    Design: Difficulty/combinatorial_formula/priority_score_multi_input_nonlinear
    """
    prog = setup_program(name="P-PS2")
    pa = _pa()

    # Build household at clock=2025-03-28 — 399 days before 2026-05-01.
    get_success_data(api_client.set_clock("2025-03-28T00:00:00Z", pa))
    hh, _, _ = setup_eligible_household(
        prog["id"], verified_income_cents=6_000_000, household_size=4
    )
    entry = get_success_data(
        api_client.create_waitlist_entry(
            prog["id"],
            hh["id"],
            create_waitlist_entry_payload(desired_bedrooms=3, max_price_cents=50_000_000),
            _is(),
        )
    )
    # priority_score at creation time uses age=0
    assert entry["priority_score"] == 400
    entry_id = entry["id"]

    # Advance clock 399 days; the stored priority_score refreshes daily.
    get_success_data(api_client.set_clock("2026-05-01T00:00:00Z", pa))
    refreshed = get_success_data(
        api_client.get_waitlist_entry(prog["id"], entry_id, _is())
    )
    # After 399 days, age_score = min(399, 365) = 365; stored = 400 + 365 = 765.
    # The design says the stored score caps age at 365.
    assert refreshed["priority_score"] == 765, (
        f"After 399 days, priority_score should be need(400)+age_capped(365)=765; "
        f"got {refreshed['priority_score']}"
    )


def test_priority_score_size_match_bonus_applied_at_match_time_not_stored():
    """PRD §3.6: "The stored score does not include the bedroom-size-match
    bonus; that bonus of 50 points is added only at match evaluation time when
    the absolute difference between the unit's bedrooms and the household's
    size is at most 1."
    PRD §3.5: "Each candidate is ranked by an effective score: the entry's
    stored `priority_score`, plus a bonus of 50 if the absolute difference
    between the unit's `bedrooms` and the household's `household_size` is at
    most 1. The candidate with the highest effective score wins; ties are
    broken by the entry's `created_at` ascending (earliest first)."

    Design: Difficulty/combinatorial_formula/priority_score_multi_input_nonlinear
    """
    prog = setup_program(name="P-PS3")
    pa = _pa()

    # Seller on active lease with 3-bedroom unit.
    from test_helpers import (
        create_lease_payload,
        create_unit_payload,
        create_resale_listing_payload,
    )
    from test_helpers import TEST_USERS as TU

    pga = TU["program_admin_headers"]
    lm = TU["lease_manager_headers"]

    unit = get_success_data(
        api_client.create_unit(
            prog["id"], create_unit_payload(address="1 S St", bedrooms=3), pga
        )
    )
    hh_s, _, _ = setup_eligible_household(
        prog["id"], verified_income_cents=7_000_000, household_size=4, legal_name="Seller"
    )
    lease_s = get_success_data(
        api_client.create_lease(
            prog["id"],
            unit["id"],
            create_lease_payload(household_id=hh_s["id"]),
            lm,
        )
    )
    unit_now = get_success_data(api_client.get_unit(prog["id"], unit["id"], lm))
    get_success_data(
        api_client.activate_lease(
            prog["id"],
            unit["id"],
            lease_s["id"],
            {"expected_unit_version": unit_now["version"]},
            lm,
        )
    )

    # Buyer (household_size 4, |3-4|=1 → +50 bonus at match time).
    hh_b, _, _ = setup_eligible_household(
        prog["id"], verified_income_cents=6_000_000, household_size=4, legal_name="Buyer"
    )
    entry_b = get_success_data(
        api_client.create_waitlist_entry(
            prog["id"],
            hh_b["id"],
            create_waitlist_entry_payload(desired_bedrooms=3, max_price_cents=50_000_000),
            _is(),
        )
    )
    # Stored score excludes the size bonus.
    assert entry_b["priority_score"] == 400

    listing = get_success_data(
        api_client.create_resale_listing(
            prog["id"],
            unit["id"],
            create_resale_listing_payload(
                seller_lease_id=lease_s["id"], appraisal_at_listing_cents=25_000_000
            ),
            lm,
        )
    )
    listing_now = get_success_data(
        api_client.get_resale_listing(prog["id"], unit["id"], listing["id"], lm)
    )
    matched = get_success_data(
        api_client.run_matching(
            prog["id"],
            unit["id"],
            listing["id"],
            {"expected_listing_version": listing_now["version"]},
            lm,
        )
    )
    assert matched["matched_waitlist_entry_id"] == entry_b["id"]
    assert matched["buyer_household_id"] == hh_b["id"]
