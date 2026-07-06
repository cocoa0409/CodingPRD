"""Calculation corners: estimated haircut, ROI floor/null, in-cap and quarter-hour overage."""
from test_helpers import (
    validate_success,
    create_client,
    create_campaign,
    setup_campaign_with_media_list,
    create_coverage,
    setup_open_period,
    log_time_entry,
    TEST_USERS,
)

AM = TEST_USERS["account_manager_headers"]
MS = TEST_USERS["media_specialist_headers"]


def test_estimated_media_value_haircut_stored_at_logging(api):
    """PRD §3.9: "The **estimated** variant, computed at logging and stored as
    `estimated_media_value_cents`, applies a provisional haircut: it multiplies the raw
    value by 0.8 and rounds half-up to whole cents."

    STANDARD / TRADE(80000) / MUV 0 (reach 1.0) / DA 0 (auth 1.0) / NEGATIVE(0.25) /
    PASSING(0.3): raw = 80000*1.0*1.0*0.25*0.3*1.0 = 6000; estimated = round(6000*0.8) = 4800.

    Design: Corner/calculations/estimated_media_value_haircut_at_logging
    """
    scn = setup_campaign_with_media_list(
        client_overrides={"account_tier": "STANDARD"},
        outlet_overrides={"tier": "TRADE", "monthly_unique_visitors": 0, "domain_authority": 0},
    )
    cov = create_coverage(scn["campaign"]["id"], scn["journalist"]["id"],
                          sentiment="NEGATIVE", prominence="PASSING", headline="Tiny Clip")
    assert cov["estimated_media_value_cents"] == 4800, \
        f"estimated should be 4800, got {cov['estimated_media_value_cents']}"
    assert cov["media_value_cents"] == 0, "media_value_cents is 0 until VERIFIED"
    assert cov["status"] == "DRAFT"


def test_roi_floor_applies_when_cost_below_floor(api):
    """PRD §3.10: "Third, form the denominator as the larger of that cost basis and a floor of
    100000 cents, so the system never divides by zero and the ratio is defined even before
    any time is logged. Fourth, the ratio is the earned value minus the cost basis, divided
    by that denominator, rounded half-up to four decimal places."

    earned=4050000, cost=0 -> denom=max(0,100000)=100000 -> roi=(4050000-0)/100000=40.5000.

    Design: Corner/calculations/campaign_roi_floor_applies_when_cost_below_floor
    """
    scn = setup_campaign_with_media_list(
        client_overrides={"account_tier": "ENTERPRISE"},
        outlet_overrides={"tier": "NATIONAL", "monthly_unique_visitors": 2000000, "domain_authority": 80},
    )
    cov = create_coverage(scn["campaign"]["id"], scn["journalist"]["id"],
                          sentiment="POSITIVE", prominence="FEATURE")
    validate_success(api.verify_coverage(cov["id"], MS))

    campaign = validate_success(api.get_campaign(scn["campaign"]["id"], AM))
    assert campaign["earned_media_value_cents"] == 4050000
    assert campaign["cost_basis_cents"] == 0
    assert campaign["roi_ratio"] == 40.5, f"roi should be 40.5000, got {campaign['roi_ratio']}"


def test_roi_null_when_no_verified_coverage(api):
    """PRD §3.10: "As a special case, if the earned value is zero — no coverage has yet been
    verified — the `roi_ratio` is null rather than a computed number."

    Design: Corner/calculations/campaign_roi_null_when_no_verified_coverage
    """
    client = create_client()
    campaign = create_campaign(client["id"])
    fetched = validate_success(api.get_campaign(campaign["id"], AM))
    assert fetched["roi_ratio"] is None, "roi_ratio must be null with no verified coverage"
    assert fetched["earned_media_value_cents"] == 0


def test_in_cap_time_entry_has_zero_cost(api):
    """PRD §3.11: "the entry's overage hours are its `billable_hours` minus that remaining
    room, but never less than zero; and the entry's real overage amount in cents is its
    overage hours multiplied by the snapshotted overage rate."

    A single 40.0h entry against cap=40 has zero overage, so its cost_cents is 0 and the
    period provisional total stays 0.

    Design: Corner/calculations/time_entry_in_cap_hours_cost_zero_boundary
    """
    client, period = setup_open_period(
        monthly_hours_cap=40, overage_rate_cents=15000, period_month="2026-06")
    entry = log_time_entry(period["id"], 40.0, staff_id="staff-c", work_type="STRATEGY")
    assert entry["cost_cents"] == 0, "in-cap hours must cost 0 cents"
    p = validate_success(api.get_retainer_period(period["id"], AM))
    assert p["hours_consumed"] == 40.0
    assert p["provisional_total_cents"] == 0


def test_quarter_hour_overage_cost_rounds_half_up(api):
    """PRD §3.11: "the entry's overage hours are its `billable_hours` minus that remaining
    room, but never less than zero; and the entry's real overage amount in cents is its
    overage hours multiplied by the snapshotted overage rate."
    PRD §3.11: "At logging time, an entry's own `cost_cents` is set to that round-half-up of
    its real overage amount."

    40.25h against cap=40 -> overage 0.25h -> cost = round(0.25*15000) = 3750.

    Design: Corner/calculations/time_entry_quarter_hour_overage_cost
    """
    client, period = setup_open_period(
        monthly_hours_cap=40, overage_rate_cents=15000, period_month="2026-07")
    entry = log_time_entry(period["id"], 40.25, staff_id="staff-d", work_type="WRITING")
    assert entry["cost_cents"] == 3750, f"overage cost should be 3750, got {entry['cost_cents']}"
    p = validate_success(api.get_retainer_period(period["id"], AM))
    assert p["provisional_total_cents"] == 3750
