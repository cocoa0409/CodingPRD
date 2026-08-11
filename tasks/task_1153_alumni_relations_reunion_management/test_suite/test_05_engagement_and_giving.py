"""Engagement scoring and giving propensity: constants, threshold bands,
the persisted-vs-provisional split, and the recency window (PRD §3.7)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_record,
    register_and_confirm,
    setup_open_event,
    setup_active_campaign,
    create_pledge_as_alumni,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]


def _open_event_for_scoring(api):
    return setup_open_event(
        event_overrides={"event_date": "2026-09-01T18:00:00Z"},
        tier_overrides={
            "name": "GA", "base_price_cents": 1000, "capacity": 0,
            "sales_start": "2026-05-01T00:00:00Z", "sales_end": "2026-09-01T00:00:00Z",
        },
        clock_iso="2026-06-01T00:00:00Z",
    )


def _confirm_n(api, event_id, tier_id, alumni_id, n):
    for _ in range(n):
        register_and_confirm(event_id, tier_id, alumni_id)


# ---------------------------------------------------------------------------
# Score constants and cap
# ---------------------------------------------------------------------------

def test_engagement_score_constants_and_cap(api):
    """PRD §3.7: "Event points come from the count of the alumnus's
    registrations with `payment_status` of `CONFIRMED` or `CHECKED_IN` —
    cancelled and refunded registrations never count — at 25 points each,
    capped at 100 points" and "event participation contributes at a weight of
    0.50". Two confirmed registrations yield 50 event points and a score of
    0.50 * 50 = 25.00.
    PRD §3.7: "a score of at least 30.00 but below 70.00 is `MEDIUM`", so
    25.00 is `LOW`.

    Design: Corner/calculations/engagement_score_constants_and_cap
    """
    ctx = _open_event_for_scoring(api)
    alum = create_record(full_name="CalcAlum", primary_email="calcalum@x.com")
    _confirm_n(api, ctx["event"]["id"], ctx["tier"]["id"], alum["id"], 2)

    record = validate_success(api.get_record(alum["id"], STAFF))
    assert float(record["engagement_score"]) == pytest.approx(25.00, abs=0.001)
    assert record["engagement_tier"] == "LOW"


# ---------------------------------------------------------------------------
# Tier threshold boundary
# ---------------------------------------------------------------------------

def test_engagement_score_50_from_four_confirmed_registrations(api):
    """PRD §3.7: "Event points ... at 25 points each, capped at 100 points"
    and the weighted blend "event participation contributes at a weight of
    0.50": four confirmed registrations saturate event points at 100 and
    yield a score of 0.50 * 100 = 50.00.

    Design: Difficulty/boundary_precision_check/engagement_tier_boundary_70_is_high
    """
    ctx = _open_event_for_scoring(api)
    alum = create_record(full_name="Boundary Alum", primary_email="boundary@x.com")
    _confirm_n(api, ctx["event"]["id"], ctx["tier"]["id"], alum["id"], 4)

    record = validate_success(api.get_record(alum["id"], STAFF))
    assert float(record["engagement_score"]) == pytest.approx(50.00, abs=0.001)


def test_engagement_tier_medium_at_50_below_high_threshold(api):
    """PRD §3.7: "the `engagement_tier` is re-derived from inclusive
    thresholds: a score of at least 70.00 is `HIGH`, a score of at least
    30.00 but below 70.00 is `MEDIUM`, and anything below 30.00 is `LOW`.
    Exactly 70.00 is therefore `HIGH` and exactly 30.00 is `MEDIUM`." A score
    of 50.00 sits strictly inside the MEDIUM band.

    Design: Difficulty/boundary_precision_check/engagement_tier_boundary_70_is_high
    """
    ctx = _open_event_for_scoring(api)
    alum = create_record(full_name="Boundary Alum", primary_email="boundary2@x.com")
    _confirm_n(api, ctx["event"]["id"], ctx["tier"]["id"], alum["id"], 4)

    record = validate_success(api.get_record(alum["id"], STAFF))
    assert float(record["engagement_score"]) == pytest.approx(50.00, abs=0.001)
    assert record["engagement_tier"] == "MEDIUM"


# ---------------------------------------------------------------------------
# Persisted FINAL score ignores still-PLEDGED pledges
# ---------------------------------------------------------------------------

def _campaign_with_unfulfilled_pledge(api, amount_cents=10000000):
    ctx = setup_active_campaign(
        event_overrides={"event_date": "2026-08-10T18:00:00Z"},
        campaign_overrides={"goal_cents": 1000000, "matching_multiplier_bps": 0},
    )
    validate_success(api.set_clock("2026-06-01T00:00:00Z", STAFF))
    donor = create_record(full_name="Donor Two", primary_email="donor2@x.com")
    pledge = create_pledge_as_alumni(ctx["campaign"]["id"], donor["id"], amount_cents)
    return ctx, donor, pledge


def test_unfulfilled_pledge_leaves_persisted_score_at_zero(api):
    """PRD §3.7: "the persisted variant counts only fulfilled pledges and
    non-cancelled registrations" and the score "recomputes and persists
    whenever ... one of their pledges is fulfilled" — pledge creation is not
    a persist trigger, so a still-PLEDGED pledge leaves the stored
    `engagement_score` at 0.00 even though "the provisional score is greater
    than or equal to the persisted one".

    Design: Difficulty/dual_variant_calc/engagement_score_provisional_vs_final_on_unfulfilled_pledge
    """
    _ctx, donor, pledge = _campaign_with_unfulfilled_pledge(api)
    assert pledge["status"] == "PLEDGED"

    record = validate_success(api.get_record(donor["id"], STAFF))
    assert float(record["engagement_score"]) == pytest.approx(0.00, abs=0.001)
    assert record["engagement_tier"] == "LOW"


def test_unfulfilled_pledge_leaves_lifetime_giving_at_zero(api):
    """PRD §3.6: fulfillment "adds `amount_cents` to the pledgor's
    `lifetime_giving_cents`" — and only fulfillment does — so a pledge still
    in `PLEDGED` contributes nothing to `lifetime_giving_cents`.

    Design: Difficulty/dual_variant_calc/engagement_score_provisional_vs_final_on_unfulfilled_pledge
    """
    _ctx, donor, pledge = _campaign_with_unfulfilled_pledge(api)
    record = validate_success(api.get_record(donor["id"], STAFF))
    assert record["lifetime_giving_cents"] == 0
    assert float(record["giving_propensity"]) == pytest.approx(0.00, abs=0.001)


# ---------------------------------------------------------------------------
# Propensity recency window
# ---------------------------------------------------------------------------

def test_giving_propensity_recency_window(api):
    """PRD §3.7: "A recency bonus of 0.15 is added when the alumnus has any
    pledge in `FULFILLED` whose fulfillment falls within the 365 days
    preceding the current logical clock, and 0 otherwise. A capacity factor
    is added equal to `lifetime_giving_cents` divided by one million cents
    and multiplied by 0.25, capped at 0.25" and "The propensity is the base
    factor weighted at 0.7, plus the recency bonus, plus the capacity factor,
    capped at 1.00 and rounded half-up to two decimals. A pledge lapse also
    triggers a propensity recompute on its own."

    Design: Corner/calculations/giving_propensity_recency_window
    """
    ctx = setup_active_campaign(
        event_overrides={"event_date": "2026-08-10T18:00:00Z"},
        campaign_overrides={"goal_cents": 10000000, "matching_multiplier_bps": 0},
    )
    validate_success(api.set_clock("2026-06-01T00:00:00Z", STAFF))
    donor = create_record(full_name="PDn", primary_email="pdn@x.com")

    pledge1 = create_pledge_as_alumni(ctx["campaign"]["id"], donor["id"], 100000)
    validate_success(api.fulfill_pledge(pledge1["id"], STAFF))

    # Just fulfilled (inside the recency window):
    # score = 0.30 * min(100, $1000 -> 100 pts) = 30.00;
    # propensity = 0.7*0.30 + 0.15 + min(0.25, 0.025) = 0.385 -> 0.39.
    record = validate_success(api.get_record(donor["id"], STAFF))
    assert float(record["engagement_score"]) == pytest.approx(30.00, abs=0.001)
    assert float(record["giving_propensity"]) == pytest.approx(0.39, abs=0.001)

    # Move the clock 400 days past fulfillment; a lapse triggers recompute.
    pledge2 = create_pledge_as_alumni(ctx["campaign"]["id"], donor["id"], 100)
    validate_success(api.set_clock("2027-07-06T00:00:00Z", STAFF))
    validate_success(api.lapse_pledge(pledge2["id"], STAFF))

    # Recency window elapsed: propensity = 0.7*0.30 + 0 + 0.025 = 0.235 -> 0.24.
    record = validate_success(api.get_record(donor["id"], STAFF))
    assert float(record["giving_propensity"]) == pytest.approx(0.24, abs=0.001)
