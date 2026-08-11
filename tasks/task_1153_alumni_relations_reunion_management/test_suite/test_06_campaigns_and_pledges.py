"""Milestone gift campaigns and pledges: validation gates, per-pledge
matching-credit rounding, and the event-cancellation cascade (PRD §3.6)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    assert_pledge,
    assert_campaign,
    create_record,
    create_event,
    setup_active_campaign,
    setup_open_event,
    create_pledge_as_alumni,
    make_alumni_headers,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]
DIRECTOR = TEST_USERS["director_headers"]


# ---------------------------------------------------------------------------
# Corner validation gates
# ---------------------------------------------------------------------------

def test_pledge_amount_below_minimum_rejected(api):
    """PRD §3.6: "Creating one names the `alumni_id` and an `amount_cents` of
    at least 100 (else `ERR_AMOUNT_TOO_SMALL`)".

    Design: Corner/validations/pledge_amount_below_minimum_rejected
    """
    ctx = setup_active_campaign(
        event_overrides={"event_date": "2026-08-10T18:00:00Z"},
    )
    donor = create_record(full_name="MDn", primary_email="mdn@x.com")
    resp = api.create_pledge(
        ctx["campaign"]["id"],
        {"alumni_id": donor["id"], "amount_cents": 50},
        make_alumni_headers(donor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AMOUNT_TOO_SMALL)


def test_campaign_activate_on_non_milestone_year_rejected(api):
    """PRD §3.3: "At scheduling time the server computes `milestone_year` as
    the current year minus the `class_year`" (2026 - 2003 = 23), and
    PRD §3.6: "the linked event's `milestone_year` must be positive and
    divisible by five (else `ERR_NOT_MILESTONE_YEAR`)".

    Design: Corner/validations/campaign_activate_on_non_milestone_year_rejected
    """
    # Event created while the logical clock reads the 2026 startup default.
    event = create_event(class_year=2003, title="Non-milestone",
                         event_date="2026-08-10T18:00:00Z")
    resp = api.create_campaign(
        event["id"], {"name": "F", "goal_cents": 100000, "matching_multiplier_bps": 0},
        STAFF,
    )
    campaign = validate_success(resp, 201)

    resp = api.activate_campaign(campaign["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_NOT_MILESTONE_YEAR)

    campaign = validate_success(api.get_campaign(campaign["id"], STAFF))
    assert campaign["status"] == "DRAFT"


def test_write_off_requires_closed_campaign(api):
    """PRD §3.6: "a director may write off a pledge — `PLEDGED →
    WRITTEN_OFF` — but only once the parent campaign is `CLOSED`
    (`ERR_CAMPAIGN_NOT_CLOSED`)".

    Design: Corner/validations/write_off_requires_closed_campaign
    """
    ctx = setup_active_campaign(
        event_overrides={"event_date": "2026-08-10T18:00:00Z"},
    )
    donor = create_record(full_name="ODn", primary_email="odn@x.com")
    pledge = create_pledge_as_alumni(ctx["campaign"]["id"], donor["id"], 5000)

    resp = api.write_off_pledge(pledge["id"], DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_CLOSED)

    row = validate_success(api.get_pledge(pledge["id"], STAFF))
    assert row["status"] == "PLEDGED"


def test_campaign_close_blocked_by_outstanding_pledges(api):
    """PRD §3.6: "Closing a campaign, `ACTIVE → CLOSED`, requires that no
    pledge remain in `PLEDGED` (`ERR_PLEDGES_OUTSTANDING`)."

    Design: Corner/state_machines/campaign_close_blocked_by_outstanding_pledges
    """
    ctx = setup_active_campaign(
        event_overrides={"event_date": "2026-08-10T18:00:00Z"},
    )
    donor = create_record(full_name="CDn", primary_email="cdn@x.com")
    create_pledge_as_alumni(ctx["campaign"]["id"], donor["id"], 5000)

    resp = api.close_campaign(ctx["campaign"]["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_PLEDGES_OUTSTANDING)

    campaign = validate_success(api.get_campaign(ctx["campaign"]["id"], STAFF))
    assert campaign["status"] == "ACTIVE"


def test_invalid_from_transition_pledge_fulfill_on_lapsed(api):
    """PRD §3.6: fulfillment is "the `PLEDGED → FULFILLED` transition", and
    PRD §2.10: "**State** — the target resource is in a valid from-state for
    the requested transition (`ERR_INVALID_STATE`, all action endpoints)." A
    LAPSED pledge is no longer in PLEDGED.

    Design: Corner/state_machines/invalid_from_transition_pledge_fulfill_on_lapsed
    """
    ctx = setup_active_campaign(
        event_overrides={"event_date": "2026-08-10T18:00:00Z"},
    )
    donor = create_record(full_name="Dn", primary_email="dnx@x.com")
    pledge = create_pledge_as_alumni(ctx["campaign"]["id"], donor["id"], 5000)
    lapsed = validate_success(api.lapse_pledge(pledge["id"], STAFF))
    assert lapsed["status"] == "LAPSED"

    resp = api.fulfill_pledge(pledge["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Per-pledge matching-credit rounding
# ---------------------------------------------------------------------------

def _matched_campaign_with_two_fulfilled_pledges(api):
    """Campaign at 5000 bps; two donors each pledge and fulfill 155 cents."""
    ctx = setup_active_campaign(
        event_overrides={"event_date": "2026-08-10T18:00:00Z"},
        campaign_overrides={"goal_cents": 100000, "matching_multiplier_bps": 5000},
    )
    validate_success(api.set_clock("2026-06-01T00:00:00Z", STAFF))
    donor_a = create_record(full_name="Donor A", primary_email="donora@x.com")
    donor_b = create_record(full_name="Donor B", primary_email="donorb@x.com")
    pledge_a = create_pledge_as_alumni(ctx["campaign"]["id"], donor_a["id"], 155)
    pledge_b = create_pledge_as_alumni(ctx["campaign"]["id"], donor_b["id"], 155)
    fulfilled_a = validate_success(api.fulfill_pledge(pledge_a["id"], STAFF))
    fulfilled_b = validate_success(api.fulfill_pledge(pledge_b["id"], STAFF))
    return ctx, fulfilled_a, fulfilled_b


def test_matching_credit_rounded_per_pledge(api):
    """PRD §3.6: "the pledge's own `matched_credit_cents` is computed as
    `amount_cents` scaled by `matching_multiplier_bps` divided by 10000,
    rounded half-up to whole cents — rounding happens per pledge": 155 *
    5000 / 10000 = 77.5 rounds half-up to 78 on each pledge.

    Design: Difficulty/combinatorial_formula/campaign_matching_credit_per_pledge_rounding
    """
    _ctx, fulfilled_a, fulfilled_b = _matched_campaign_with_two_fulfilled_pledges(api)
    assert_pledge(fulfilled_a)
    assert_pledge(fulfilled_b)
    assert fulfilled_a["matched_credit_cents"] == 78
    assert fulfilled_b["matched_credit_cents"] == 78


def test_campaign_matched_total_sums_per_pledge_credits(api):
    """PRD §3.6: "the campaign's `matched_credit_cents` is the sum of these
    per-pledge rounded credits over fulfilled pledges; summing first and
    rounding once is explicitly not how the campaign total is built." Two
    per-pledge credits of 78 sum to 156 (sum-then-round of 155 would give
    155).

    Design: Difficulty/combinatorial_formula/campaign_matching_credit_per_pledge_rounding
    """
    ctx, _a, _b = _matched_campaign_with_two_fulfilled_pledges(api)
    campaign = validate_success(api.get_campaign(ctx["campaign"]["id"], STAFF))
    assert_campaign(campaign)
    assert campaign["matched_credit_cents"] == 156
    assert campaign["fulfilled_total_cents"] == 310


# ---------------------------------------------------------------------------
# Event cancellation cascade through campaign to pledges
# ---------------------------------------------------------------------------

def _open_event_with_active_campaign_and_pledge(api):
    """Event OPEN_FOR_REGISTRATION with an ACTIVE campaign and one PLEDGED
    pledge of 200000 cents."""
    ctx = setup_open_event(
        event_overrides={"event_date": "2026-08-10T18:00:00Z"},
        tier_overrides={
            "name": "GA", "base_price_cents": 5000, "capacity": 0,
            "sales_start": "2026-05-01T00:00:00Z", "sales_end": "2026-08-10T00:00:00Z",
        },
        clock_iso="2026-06-01T00:00:00Z",
    )
    resp = api.create_campaign(
        ctx["event"]["id"],
        {"name": "Fund", "goal_cents": 1000000, "matching_multiplier_bps": 0},
        STAFF,
    )
    campaign = validate_success(resp, 201)
    campaign = validate_success(api.activate_campaign(campaign["id"], STAFF))
    donor = create_record(full_name="Donor D", primary_email="donord@x.com")
    pledge = create_pledge_as_alumni(campaign["id"], donor["id"], 200000)
    ctx["campaign"] = campaign
    ctx["donor"] = donor
    ctx["pledge"] = pledge
    return ctx


def test_event_cancel_abandons_campaign_and_lapses_pledges(api):
    """PRD §3.6: "A campaign is abandoned only by the system, when its linked
    reunion event is cancelled: `ACTIVE → ABANDONED` lapses every `PLEDGED`
    pledge". PRD §3.3: "From `OPEN_FOR_REGISTRATION` it does far more ... a
    linked campaign in `ACTIVE` is abandoned and each of its `PLEDGED`
    pledges lapses".

    Design: Difficulty/transitive_cascade/event_cancel_cascade_depth3_to_propensity
    """
    ctx = _open_event_with_active_campaign_and_pledge(api)

    event = validate_success(api.cancel_event(ctx["event"]["id"], DIRECTOR))
    assert event["status"] == "CANCELLED"

    campaign = validate_success(api.get_campaign(ctx["campaign"]["id"], STAFF))
    assert campaign["status"] == "ABANDONED"

    pledge = validate_success(api.get_pledge(ctx["pledge"]["id"], STAFF))
    assert pledge["status"] == "LAPSED"


def test_event_cancel_lapse_decrements_pledged_total_without_giving(api):
    """PRD §3.3: "each of its `PLEDGED` pledges lapses (each lapse itself
    decrementing the campaign's `pledged_total_cents` and triggering a
    `giving_propensity` recompute on the pledgor's record)"; PRD §3.6:
    fulfillment — not a lapse — "adds `amount_cents` to the pledgor's
    `lifetime_giving_cents`", so a lapsed-never-fulfilled pledge leaves
    lifetime giving at zero.

    Design: Difficulty/transitive_cascade/event_cancel_cascade_depth3_to_propensity
    """
    ctx = _open_event_with_active_campaign_and_pledge(api)
    campaign = validate_success(api.get_campaign(ctx["campaign"]["id"], STAFF))
    assert campaign["pledged_total_cents"] == 200000

    validate_success(api.cancel_event(ctx["event"]["id"], DIRECTOR))

    campaign = validate_success(api.get_campaign(ctx["campaign"]["id"], STAFF))
    assert campaign["pledged_total_cents"] == 0
    donor = validate_success(api.get_record(ctx["donor"]["id"], STAFF))
    assert donor["lifetime_giving_cents"] == 0
    assert float(donor["giving_propensity"]) == pytest.approx(0.00, abs=0.001)
