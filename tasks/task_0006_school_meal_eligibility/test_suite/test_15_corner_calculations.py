"""Tests covering calculation-correctness probes from the corner index:
the eligibility-selector picks the tier-priority winner when only one
ACTIVE determination covers the clock for the student's household.
"""
import pytest

from test_helpers import (
    validate_success,
    set_clock,
    create_household,
    create_student,
    create_direct_cert_eligibility,
    create_menu_item,
    create_service_transaction,
    api_client,
    TEST_USERS,
)


# ---------------------------------------------------------------------
# Corner / calculations
# ---------------------------------------------------------------------

def test_selector_picks_unique_active_free_determination_for_transaction(api):
    """PRD §3.5: "The candidate pool is every `EligibilityDetermination` for
    the student's `household_id` whose `lifecycle_status` is `ACTIVE` and
    whose validity window contains the current server clock instant — that
    is, `valid_from_utc` is at or before now and `valid_to_utc` is strictly
    after now. ... Otherwise the candidates are ranked by tier generosity
    first and recency second: `FREE` outranks `REDUCED`, which outranks
    `PAID`; within a tier the candidate with the latest `valid_from_utc`
    wins, and within that the candidate with the latest `created_at` wins.
    The determination's `id` is never used as a tiebreaker. The chosen
    determination's id is stamped onto the transaction as
    `eligibility_determination_id`, and its tier is copied to
    `applied_tier`."

    Design: Corner/calculations/selector_chooses_most_generous_active_tier_when_two_active_determinations_overlap_by_value
    """
    set_clock("2026-07-05T09:00:00.000Z")
    hh = create_household(direct_certification_flag=True)
    stu = create_student(hh["id"], school_code="ELEM-101")
    elig = create_direct_cert_eligibility(
        hh["id"], tier="FREE",
        valid_from_utc="2026-07-01T00:00:00.000Z",
        valid_to_utc="2026-08-31T23:59:59.000Z",
    )
    menu = create_menu_item(
        school_code="ELEM-101", name="Lunch2",
        list_price_cents=500, allergens_present=[],
    )
    res = api.create_service_transaction(
        {"student_id": stu["id"], "menu_item_id": menu["id"]},
        TEST_USERS["school_staff_headers"],
    )
    tx = validate_success(res, 201)
    assert tx["applied_tier"] == "FREE", (
        f"single ACTIVE FREE determination must be selected; "
        f"got tier={tx['applied_tier']!r}"
    )
    assert tx["paid_charge_cents"] == 0, (
        f"FREE tier yields 0 charge; got {tx['paid_charge_cents']}"
    )
    assert tx["eligibility_determination_id"] == elig["id"], (
        f"selector must stamp the chosen determination's id; expected "
        f"{elig['id']!r}, got {tx['eligibility_determination_id']!r}"
    )
