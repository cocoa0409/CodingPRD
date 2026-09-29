"""Pricing and window boundaries: the exact edge of a duration tier and of the
renewal window.

Both cases are off-by-one probes taken from opposite sides of the same edge — 30
seconds against 31 seconds on the rate-card ladder of PRD §3.3, and 60 whole days
against 61 whole days on the renewal window of PRD §3.8.
"""
from typing import Any, Dict

from test_helpers import (
    CLEARANCE_SUPERVISOR,
    assert_license_money_ledger,
    create_and_execute_license,
    create_archive_with_rate_card,
    create_asset_with_selected_source,
    create_license_payload,
    create_production_in_clearance,
    get_asset,
    get_license,
    get_production,
    renew_license,
    renew_license_payload,
    run_sweep,
    set_clock,
    validate_error,
    validate_success,
)

# The standard card of the PRD §3.3 worked example: base 60000 per 30-second unit, an
# all-media floor of 150000, a festival floor of 40000, every other field defaulted.
_STANDARD_DEAL = {
    "rights_leg": "FOOTAGE",
    "media": "BROADCAST",
    "territory": "WORLD",
    "window_class": "ALL_MEDIA_WINDOW",
    "term_months": 36,
    "term_start_date": "2026-08-15",
    "term_end_date": "2029-08-15",
}

_TWELVE_MONTH_DEAL = {
    "rights_leg": "FOOTAGE",
    "media": "BROADCAST",
    "territory": "WORLD",
    "window_class": "ALL_MEDIA_WINDOW",
    "term_months": 12,
    "term_start_date": "2026-08-15",
    "term_end_date": "2027-08-15",
}


def _setup_thirty_and_thirty_one_second_assets(api) -> Dict[str, Any]:
    """A production in CLEARANCE holding two footage assets one second apart.

    Asset E is exactly 30 seconds, the inclusive tier-1 bound; asset F is 31 seconds,
    one second past it. Both have an AVAILABLE candidate SELECTED at the same archive,
    so a FOOTAGE licence may be opened against either.
    """
    production = create_production_in_clearance(api, title="One Second Apart",
                                                delivery_deadline_date="2027-08-31")
    archive, card = create_archive_with_rate_card(api)
    asset_e, _candidate_e = create_asset_with_selected_source(
        api, production["id"], archive["id"], title="Thirty seconds exactly",
        timecode_in_seconds=0, timecode_out_seconds=30)
    asset_f, _candidate_f = create_asset_with_selected_source(
        api, production["id"], archive["id"], title="Thirty one seconds",
        timecode_in_seconds=0, timecode_out_seconds=31)
    return {
        "production": production,
        "archive": archive,
        "rate_card": card,
        "asset_e": get_asset(api, asset_e["id"]),
        "asset_f": get_asset(api, asset_f["id"]),
    }


def _open_standard_license(api, scenario: Dict[str, Any], asset_key: str):
    return api.create_license(
        create_license_payload(scenario["production"]["id"], scenario[asset_key]["id"],
                               scenario["archive"]["id"], **_STANDARD_DEAL),
        CLEARANCE_SUPERVISOR)


def _setup_active_twelve_month_licence(api) -> Dict[str, Any]:
    """One EXECUTED 12-month FOOTAGE licence activated by a sweep at clock 2026-08-20.

    PRD §3.8 step one activates it because its term_start_date 2026-08-15 falls on or
    before the clock's date, and step two leaves it alone because its term_end_date
    2027-08-15 is still ahead — which is what puts it in the ACTIVE band renewal needs.
    """
    set_clock(api, "2026-08-20T00:00:00Z")
    production = create_production_in_clearance(api, title="Sixty Days",
                                                delivery_deadline_date="2027-05-31")
    archive, card = create_archive_with_rate_card(api)
    asset, candidate = create_asset_with_selected_source(
        api, production["id"], archive["id"], title="Expiring reel")
    license_row = create_and_execute_license(
        api, production["id"], asset["id"], archive["id"], **_TWELVE_MONTH_DEAL)
    sweep = run_sweep(api, production["id"])
    return {
        "production": get_production(api, production["id"]),
        "archive": archive,
        "rate_card": card,
        "asset": asset,
        "source_candidate": candidate,
        "license": get_license(api, license_row["id"]),
        "sweep": sweep,
    }


# ─── boundary_precision_check ────────────────────────────────────────────────
# The inclusive tier-1 duration bound and the all-media fee floor at 30 seconds.


def test_thirty_second_asset_stays_in_tier_one_and_takes_the_fee_floor(api):
    """PRD §3.3: "the duration tier is selected from the asset's `duration_seconds`
    against the card's inclusive upper bounds: a duration less than or equal to
    `tier1_max_seconds` takes a rate multiplier of exactly 1.00, so a duration equal to
    the tier-1 bound stays in tier 1". With one billable unit, the tier-1 multiplier of
    1.00, the broadcast multiplier of 1.15, the world multiplier of 1.50 and a term
    factor of 1.40, the raw product is 144900 cents, and PRD §3.3 then applies the
    floor: "only then is `rate_card_fee_cents` taken as the larger of that rounded
    product and the window's fee floor", which for an `ALL_MEDIA_WINDOW` licence is
    `minimum_fee_cents` of 150000.

    Design: Difficulty/boundary_precision_check/duration_tier_one_inclusive_boundary_and_fee_floor_at_thirty_seconds
    """
    scenario = _setup_thirty_and_thirty_one_second_assets(api)
    assert scenario["asset_e"]["duration_seconds"] == 30

    response = _open_standard_license(api, scenario, "asset_e")
    license_row = validate_success(response, 201)

    assert license_row["billable_units"] == 1, (
        "PRD §3.3: 30 seconds divided by 30 and rounded up is one billable unit")
    assert license_row["rate_card_fee_cents"] == 150000, (
        "the raw product of 144900 falls below the all-media floor, so the floor is the fee")
    assert license_row["rate_card_fee_cents"] != 144900, (
        "PRD §3.3 forbids ignoring the fee floor")
    assert license_row["current_proposed_fee_cents"] == 150000, (
        "PRD §3.3: current_proposed_fee_cents initialises to that same rate-card figure")
    assert license_row["status"] == "DRAFT"


def test_thirty_one_second_asset_takes_two_units_and_the_tier_two_multiplier(api):
    """PRD §3.3: "a duration greater than `tier1_max_seconds` but less than or equal to
    `tier2_max_seconds` takes `tier2_rate_multiplier`", and "the billable unit count is
    the asset's `duration_seconds` divided by 30 seconds per billable unit and rounded
    up to a whole number". One second past the tier-1 bound therefore bills two units at
    the 1.25 tier-2 multiplier: 60000 * 2 * 1.25 * 1.15 * 1.50 * 1.40 * 1.00 is 362250
    cents, which clears the 150000 floor outright.

    Design: Difficulty/boundary_precision_check/duration_tier_one_inclusive_boundary_and_fee_floor_at_thirty_seconds
    """
    scenario = _setup_thirty_and_thirty_one_second_assets(api)
    assert scenario["asset_f"]["duration_seconds"] == 31

    response = _open_standard_license(api, scenario, "asset_f")
    license_row = validate_success(response, 201)

    assert license_row["billable_units"] == 2, (
        "PRD §3.3: 31 seconds divided by 30 and rounded up is two billable units")
    assert license_row["rate_card_fee_cents"] == 362250
    assert license_row["current_proposed_fee_cents"] == 362250
    assert license_row["status"] == "DRAFT"


def test_one_extra_second_moves_both_the_unit_count_and_the_duration_tier(api):
    """The two sides of the boundary priced side by side on the same rate card. PRD
    §3.3: "the duration tier is selected from the asset's `duration_seconds` against the
    card's inclusive upper bounds: a duration less than or equal to `tier1_max_seconds`
    takes a rate multiplier of exactly 1.00, so a duration equal to the tier-1 bound
    stays in tier 1; a duration greater than `tier1_max_seconds` but less than or equal
    to `tier2_max_seconds` takes `tier2_rate_multiplier`". One extra second moves the
    billable unit count from 1 to 2 and the tier multiplier from 1.00 to 1.25, taking
    the fee from the 150000 floor to 362250.

    Design: Difficulty/boundary_precision_check/duration_tier_one_inclusive_boundary_and_fee_floor_at_thirty_seconds
    """
    scenario = _setup_thirty_and_thirty_one_second_assets(api)

    license_e = validate_success(_open_standard_license(api, scenario, "asset_e"), 201)
    license_f = validate_success(_open_standard_license(api, scenario, "asset_f"), 201)

    assert (license_e["billable_units"], license_f["billable_units"]) == (1, 2)
    assert license_e["rate_card_fee_cents"] == 150000
    assert license_f["rate_card_fee_cents"] == 362250
    assert license_f["rate_card_fee_cents"] - license_e["rate_card_fee_cents"] == 212250
    assert license_e["rate_card_id"] == scenario["rate_card"]["id"]
    assert license_f["rate_card_id"] == scenario["rate_card"]["id"]


# The renewal window: 60 whole days is inside, 61 whole days is outside.


def test_sixty_one_whole_days_from_term_end_is_outside_the_renewal_window(api):
    """PRD §2.12 rung 40: "The whole-day distance from the clock's date to
    `term_end_date` is between 0 and 60 inclusive — otherwise
    `ERR_OUTSIDE_RENEWAL_WINDOW`. Applies to licence renewal." At clock 2027-06-15 the
    term_end_date of 2027-08-15 is 61 whole days ahead, so the renewal is refused and
    nothing about the licence or the ledger moves.

    Design: Difficulty/boundary_precision_check/renewal_window_sixty_versus_sixty_one_whole_days
    """
    scenario = _setup_active_twelve_month_licence(api)
    license_id = scenario["license"]["id"]
    production_id = scenario["production"]["id"]

    sweep = scenario["sweep"]
    assert sweep["sweep_epoch"] == 1
    assert license_id in sweep["activated_license_ids"]
    assert sweep["expired_license_ids"] == []
    assert scenario["license"]["status"] == "ACTIVE"
    assert scenario["license"]["rate_card_fee_cents"] == 258750
    assert scenario["license"]["executed_fee_cents"] == 258750
    assert scenario["production"]["committed_fee_cents"] == 258750

    set_clock(api, "2027-06-15T00:00:00Z")
    response = api.renew_license(license_id, renew_license_payload(24), CLEARANCE_SUPERVISOR)
    validate_error(response, "ERR_OUTSIDE_RENEWAL_WINDOW")

    after = get_license(api, license_id)
    assert after["term_months"] == 12, "the rejected renewal must not extend the term"
    assert after["term_end_date"] == "2027-08-15"
    assert after["status"] == "ACTIVE"
    assert after["rate_card_fee_cents"] == 258750
    assert after["executed_fee_cents"] == 258750
    assert get_production(api, production_id)["committed_fee_cents"] == 258750


def test_exactly_sixty_whole_days_from_term_end_is_inside_the_renewal_window(api):
    """PRD §3.8: "the renewal window must be open, meaning the whole-day distance from
    the clock's date to `term_end_date` is between 0 and 60 inclusive, and a licence
    more than 60 whole days from its end date is refused with
    `ERR_OUTSIDE_RENEWAL_WINDOW` (HTTP 409)". At clock 2027-06-16 the term_end_date of
    2027-08-15 is exactly 60 whole days ahead, so the renewal is accepted: PRD §3.8
    then extends `term_months` by `additional_term_months`, advances `term_end_date` by
    that many calendar months, re-runs rate-card pricing against the extended term and
    adds the renewal delta to both `executed_fee_cents` and `committed_fee_cents`.

    Design: Difficulty/boundary_precision_check/renewal_window_sixty_versus_sixty_one_whole_days
    """
    scenario = _setup_active_twelve_month_licence(api)
    license_id = scenario["license"]["id"]
    production_id = scenario["production"]["id"]
    assert scenario["license"]["status"] == "ACTIVE"

    set_clock(api, "2027-06-16T00:00:00Z")
    renewed = renew_license(api, license_id, 24)

    assert renewed["term_months"] == 36
    assert renewed["term_end_date"] == "2029-08-15"
    assert renewed["status"] == "ACTIVE"
    assert renewed["rate_card_fee_cents"] == 362250, (
        "pricing re-run against the extended 36-month term lifts the term factor to 1.40")
    assert renewed["executed_fee_cents"] == 362250, (
        "258750 plus the renewal delta of 103500")
    assert get_production(api, production_id)["committed_fee_cents"] == 362250
    assert_license_money_ledger(api, production_id, CLEARANCE_SUPERVISOR)


def test_the_renewal_window_edge_tested_from_both_sides_of_the_same_licence(api):
    """The same licence refused one day and renewed the next. PRD §2.12 rung 40: "The
    whole-day distance from the clock's date to `term_end_date` is between 0 and 60
    inclusive — otherwise `ERR_OUTSIDE_RENEWAL_WINDOW`. Applies to licence renewal."
    2027-06-15 is 61 whole days from the 2027-08-15 term end and is refused; the very
    next day is exactly 60 whole days out and is accepted.

    Design: Difficulty/boundary_precision_check/renewal_window_sixty_versus_sixty_one_whole_days
    """
    scenario = _setup_active_twelve_month_licence(api)
    license_id = scenario["license"]["id"]
    production_id = scenario["production"]["id"]
    version_before = scenario["license"]["version"]

    set_clock(api, "2027-06-15T00:00:00Z")
    refused = api.renew_license(license_id, renew_license_payload(24), CLEARANCE_SUPERVISOR)
    validate_error(refused, "ERR_OUTSIDE_RENEWAL_WINDOW")
    untouched = get_license(api, license_id)
    assert untouched["term_months"] == 12
    assert untouched["term_end_date"] == "2027-08-15"
    assert untouched["version"] == version_before, (
        "a rejected renewal must not advance the licence's version")

    set_clock(api, "2027-06-16T00:00:00Z")
    accepted = validate_success(
        api.renew_license(license_id, renew_license_payload(24), CLEARANCE_SUPERVISOR), 200)
    assert accepted["term_months"] == 36
    assert accepted["term_end_date"] == "2029-08-15"
    assert accepted["rate_card_fee_cents"] == 362250
    assert accepted["executed_fee_cents"] == 362250
    assert accepted["version"] > version_before
    assert get_production(api, production_id)["committed_fee_cents"] == 362250
