"""Conserved ledger quantities — drift-free reversal on retract and void."""
from test_helpers import (
    validate_success,
    setup_campaign_with_media_list,
    create_coverage,
    setup_open_period,
    log_time_entry,
    TEST_USERS,
)

AM = TEST_USERS["account_manager_headers"]
MS = TEST_USERS["media_specialist_headers"]


# =========================================================================== #
# compensating_invariant / coverage_verify_retract_conserves_earned_media_value
# =========================================================================== #

def test_verify_then_retract_returns_earned_media_to_zero(api):
    """PRD §3.8: "exactly the clip's frozen `media_value_cents` is subtracted back from the
    campaign's `earned_media_value_cents` and from the client's
    `lifetime_earned_media_cents`, the clip's `media_value_cents` is reset to zero, and the
    campaign's `roi_ratio` is recomputed."

    Verify credits 4050000 to both ledgers; retract debits exactly that, returning the
    campaign's earned_media_value_cents and the client's lifetime to 0 with zero drift.

    Design: Difficulty/compensating_invariant/coverage_verify_retract_conserves_earned_media_value
    """
    scn = setup_campaign_with_media_list(
        client_overrides={"account_tier": "ENTERPRISE"},
        outlet_overrides={"tier": "NATIONAL", "monthly_unique_visitors": 2000000, "domain_authority": 80},
    )
    cov = create_coverage(scn["campaign"]["id"], scn["journalist"]["id"],
                          sentiment="POSITIVE", prominence="FEATURE")
    validate_success(api.verify_coverage(cov["id"], MS))

    # ledger credited
    camp_mid = validate_success(api.get_campaign(scn["campaign"]["id"], AM))
    assert camp_mid["earned_media_value_cents"] == 4050000

    retracted = validate_success(api.retract_coverage(cov["id"], MS))
    assert retracted["status"] == "RETRACTED"
    assert retracted["media_value_cents"] == 0, "retract resets media_value_cents to 0"

    campaign = validate_success(api.get_campaign(scn["campaign"]["id"], AM))
    client = validate_success(api.get_client(scn["client"]["id"], AM))
    assert campaign["earned_media_value_cents"] == 0, "earned media must return to 0 after retract"
    assert client["lifetime_earned_media_cents"] == 0, "client lifetime must return to 0 after retract"


def test_retract_one_of_two_verified_leaves_exact_remainder(api):
    """PRD §2.9: "a retainer period's `hours_consumed` is the sum of billable hours of its
    non-void time entries. Every event that contributes to one of these balances has an
    exactly equal and opposite reversal: retracting a verified clip subtracts back precisely
    the amount it added, and voiding a time entry subtracts back precisely the hours it
    added."

    Two verified clips of 4050000 each (earned 8100000); retracting one leaves exactly
    4050000 — the surviving clip's value, re-derived from the VERIFIED set.

    Design: Difficulty/compensating_invariant/coverage_verify_retract_conserves_earned_media_value
    """
    scn = setup_campaign_with_media_list(
        client_overrides={"account_tier": "ENTERPRISE"},
        outlet_overrides={"tier": "NATIONAL", "monthly_unique_visitors": 2000000, "domain_authority": 80},
    )
    cov1 = create_coverage(scn["campaign"]["id"], scn["journalist"]["id"],
                           sentiment="POSITIVE", prominence="FEATURE", headline="Clip 1")
    cov2 = create_coverage(scn["campaign"]["id"], scn["journalist"]["id"],
                           sentiment="POSITIVE", prominence="FEATURE", headline="Clip 2")
    validate_success(api.verify_coverage(cov1["id"], MS))
    validate_success(api.verify_coverage(cov2["id"], MS))

    campaign = validate_success(api.get_campaign(scn["campaign"]["id"], AM))
    assert campaign["earned_media_value_cents"] == 8100000

    validate_success(api.retract_coverage(cov1["id"], MS))
    campaign = validate_success(api.get_campaign(scn["campaign"]["id"], AM))
    client = validate_success(api.get_client(scn["client"]["id"], AM))
    assert campaign["earned_media_value_cents"] == 4050000, "must equal the one surviving VERIFIED clip"
    assert client["lifetime_earned_media_cents"] == 4050000


# =========================================================================== #
# compensating_invariant / time_entry_log_void_conserves_hours_consumed
# =========================================================================== #

def test_log_then_void_returns_hours_consumed_to_zero(api):
    """PRD §3.11: "voiding subtracts that entry's `billable_hours` back out of the period's
    `hours_consumed` and recomputes the period's `provisional_total_cents` and the
    campaign's `cost_basis_cents`, preserving the conserved-hours invariant."

    Logging a 5.0h entry sets hours_consumed to 5.0; voiding it subtracts exactly 5.0,
    returning hours_consumed to 0 and provisional_total_cents to 0.

    Design: Difficulty/compensating_invariant/time_entry_log_void_conserves_hours_consumed
    """
    client, period = setup_open_period(
        monthly_hours_cap=40, overage_rate_cents=15000, period_month="2026-05")
    entry = log_time_entry(period["id"], 5.0, work_type="MONITORING")

    period_mid = validate_success(api.get_retainer_period(period["id"], AM))
    assert period_mid["hours_consumed"] == 5.0

    voided = validate_success(api.void_time_entry(entry["id"], AM))
    assert voided["status"] == "VOID"

    period_after = validate_success(api.get_retainer_period(period["id"], AM))
    assert period_after["hours_consumed"] == 0, "hours_consumed must return to 0 after void"
    assert period_after["provisional_total_cents"] == 0, "provisional total must return to 0 after void"


def test_void_one_of_two_entries_leaves_exact_remaining_hours(api):
    """PRD §2.9: "a retainer period's `hours_consumed` is the sum of billable hours of its
    non-void time entries. Every event that contributes to one of these balances has an
    exactly equal and opposite reversal: retracting a verified clip subtracts back precisely
    the amount it added, and voiding a time entry subtracts back precisely the hours it
    added."

    Two entries 5.0h + 3.0h (hours_consumed 8.0); voiding the 5.0h leaves exactly 3.0 —
    re-derived from the surviving non-void entry.

    Design: Difficulty/compensating_invariant/time_entry_log_void_conserves_hours_consumed
    """
    client, period = setup_open_period(
        monthly_hours_cap=40, overage_rate_cents=15000, period_month="2026-06")
    e1 = log_time_entry(period["id"], 5.0, work_type="MONITORING")
    log_time_entry(period["id"], 3.0, work_type="WRITING")

    period_mid = validate_success(api.get_retainer_period(period["id"], AM))
    assert period_mid["hours_consumed"] == 8.0

    validate_success(api.void_time_entry(e1["id"], AM))
    period_after = validate_success(api.get_retainer_period(period["id"], AM))
    assert period_after["hours_consumed"] == 3.0, "only the surviving non-void entry's hours remain"
