"""Venue rental and donation/conservancy tests: buffered venue overlap on
confirm, conservancy fund compensating reversal on void, and the rental/fund/
donation state-machine corners.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_garden,
    create_venue,
    create_rental,
    confirm_rental,
    create_conservancy_fund,
    create_donation,
    setup_open_fund,
)

RENTAL = TEST_USERS["rental_coordinator_headers"]
DEV = TEST_USERS["development_officer_headers"]


# =============================================================================
# resource_temporal_overlap — venue buffer overlap on confirm
# =============================================================================
def test_venue_confirm_collides_within_buffer(api):
    """PRD §3.6: "there must be no existing `CONFIRMED` rental on the same venue
    whose window, widened by the venue's buffer on each side — from its
    `starts_at` minus the buffer to its `ends_at` plus the buffer — overlaps this
    rental's window. A collision is rejected with `ERR_VENUE_DOUBLE_BOOKED`."

    Rental A 10:00-13:30 CONFIRMED on a 60-min-buffer venue; rental B 14:00-15:00
    starts inside A's [13:30, 14:30] buffer tail -> confirm B rejected.

    Design: Difficulty/resource_temporal_overlap/rto_venue_buffer_overlap_on_confirm
    """
    garden = create_garden(name="Oleander Oasis")
    venue = create_venue(garden["id"], name="Lily Pavilion", hourly_rate_cents=20000, buffer_minutes=60)
    rental_a = create_rental(garden["id"], venue["id"], "2026-05-01T10:00:00Z", "2026-05-01T13:30:00Z")
    confirmed_a = confirm_rental(rental_a["id"])
    assert confirmed_a["status"] == "CONFIRMED"
    rental_b = create_rental(garden["id"], venue["id"], "2026-05-01T14:00:00Z", "2026-05-01T15:00:00Z")
    resp = api.confirm_rental(rental_b["id"], RENTAL)
    validate_error(resp, ApiErrorId.ERR_VENUE_DOUBLE_BOOKED.value, expected_status=409)
    rental_b_after = validate_success(api.get_rental(rental_b["id"], RENTAL))
    assert rental_b_after["status"] == "REQUESTED", "rejected confirm leaves rental B in REQUESTED"


def test_venue_confirm_outside_buffer_succeeds(api):
    """PRD §3.6: "Confirmation moves `REQUESTED` to `CONFIRMED`, but only after a
    venue-overlap check". PRD §3.6: "A confirmed rental occupies the venue for
    overlap purposes."

    Rental A 10:00-13:30 CONFIRMED (60-min buffer ends 14:30); rental B
    15:00-16:00 starts after the buffer tail -> confirm B succeeds (the
    non-colliding side of the buffered-overlap boundary).

    Design: Difficulty/resource_temporal_overlap/rto_venue_buffer_overlap_on_confirm
    """
    garden = create_garden(name="Oleander Oasis Clear")
    venue = create_venue(garden["id"], name="Lily Pavilion", hourly_rate_cents=20000, buffer_minutes=60)
    rental_a = create_rental(garden["id"], venue["id"], "2026-05-01T10:00:00Z", "2026-05-01T13:30:00Z")
    confirm_rental(rental_a["id"])
    rental_b = create_rental(garden["id"], venue["id"], "2026-05-01T15:00:00Z", "2026-05-01T16:00:00Z")
    confirmed_b = validate_success(api.confirm_rental(rental_b["id"], RENTAL))
    assert confirmed_b["status"] == "CONFIRMED", "a rental beyond the buffer tail confirms cleanly"


# =============================================================================
# compensating_invariant — conservancy fund conserved on record then void
# =============================================================================
def test_void_conservancy_donation_reverses_pledge_and_match(api):
    """PRD §3.7: "When the voided gift was designated `CONSERVANCY`, the reversal
    subtracts that donation's `amount_cents` from the fund's
    `pledged_total_cents` and subtracts the exact match this donation had
    contributed from the fund's `matched_total_cents`, conserving both running
    totals".

    A 30000 CONSERVANCY gift (ratio 0.5, cap 10000) sets pledged 30000 / matched
    10000; voiding it returns both to 0.

    Design: Difficulty/compensating_invariant/ci_conservancy_fund_conserved_on_record_then_void
    """
    garden, fund = setup_open_fund(match_ratio=0.5, match_cap_cents=10000)
    donation = create_donation(garden["id"], amount_cents=30000, designation="CONSERVANCY")
    pre = validate_success(api.get_conservancy_fund(fund["id"], DEV))
    assert pre["pledged_total_cents"] == 30000
    assert pre["matched_total_cents"] == 10000
    voided = validate_success(api.void_donation(donation["id"], DEV))
    assert voided["status"] == "VOIDED"
    post = validate_success(api.get_conservancy_fund(fund["id"], DEV))
    assert post["pledged_total_cents"] == 0, f"pledged must reverse to 0, got {post['pledged_total_cents']}"
    assert post["matched_total_cents"] == 0, f"matched must reverse to 0, got {post['matched_total_cents']}"


def test_conservancy_fund_totals_conserved_under_record_void_cycle(api):
    """PRD §3.7: "conserving both running totals so that the fund reflects only
    its live, un-voided gifts." PRD §3.7: "Regardless of match, the donation's
    `amount_cents` is added to the fund's `pledged_total_cents`, and the applied
    match is added to `matched_total_cents`."

    The conserved quantities (pledged + matched, a fund-ledger pair) return to
    their pre-donation values after a record-then-void cycle.

    Design: Difficulty/compensating_invariant/ci_conservancy_fund_conserved_on_record_then_void
    """
    garden, fund = setup_open_fund(match_ratio=0.5, match_cap_cents=10000)
    assert fund["pledged_total_cents"] == 0 and fund["matched_total_cents"] == 0
    donation = create_donation(garden["id"], amount_cents=30000, designation="CONSERVANCY")
    validate_success(api.void_donation(donation["id"], DEV))
    post = validate_success(api.get_conservancy_fund(fund["id"], DEV))
    assert post["pledged_total_cents"] == fund["pledged_total_cents"], "pledged conserved across the cycle"
    assert post["matched_total_cents"] == fund["matched_total_cents"], "matched conserved across the cycle"


# =============================================================================
# Corner: state_machines / errors — rental, fund, donation, campaign
# =============================================================================
def test_confirm_rejected_rental_returns_invalid_state(api):
    """PRD §3.6: "Confirming, rejecting, or cancelling a rental not in the
    required source state yields `ERR_INVALID_STATE`; only `REQUESTED` may be
    confirmed or rejected."

    A REJECTED (terminal) rental cannot be confirmed.

    Design: Corner/state_machines/reject_then_confirm_rejected_rental_returns_invalid_state
    """
    garden = create_garden(name="Daffodil Dell")
    venue = create_venue(garden["id"], name="Fern Room", hourly_rate_cents=20000)
    rental = create_rental(garden["id"], venue["id"], "2026-05-03T10:00:00Z", "2026-05-03T11:00:00Z")
    validate_success(api.reject_rental(rental["id"], RENTAL))
    resp = api.confirm_rental(rental["id"], RENTAL)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_second_conservancy_fund_for_garden_rejected(api):
    """PRD §3.7: "Each garden may hold at most one conservancy fund... A second
    attempt to create a fund for a garden that already has one is rejected with
    `ERR_FUND_ALREADY_EXISTS`."

    A second create-fund on the same garden is rejected.

    Design: Corner/errors/fund_already_exists_on_second_create
    """
    garden = create_garden(name="Ulex Uplands")
    create_conservancy_fund(garden["id"], match_ratio=0.5, match_cap_cents=10000)
    resp = api.create_conservancy_fund(
        {"garden_id": garden["id"], "match_ratio": 0.25, "match_cap_cents": 5000}, DEV,
    )
    validate_error(resp, ApiErrorId.ERR_FUND_ALREADY_EXISTS.value, expected_status=409)


def test_void_already_voided_donation_rejected(api):
    """PRD §3.7: "A `DevelopmentOfficer` voids a `RECORDED` donation, moving its
    `status` to the terminal `VOIDED`; voiding an already-`VOIDED` donation
    yields `ERR_DONATION_VOIDED`."

    A second void on a VOIDED donation is rejected.

    Design: Corner/errors/donation_void_already_voided_returns_donation_voided
    """
    garden = create_garden(name="Viola Vista")
    donation = create_donation(garden["id"], amount_cents=5000, designation="GENERAL")
    validate_success(api.void_donation(donation["id"], DEV))
    resp = api.void_donation(donation["id"], DEV)
    validate_error(resp, ApiErrorId.ERR_DONATION_VOIDED.value, expected_status=409)


def test_close_already_closed_campaign_rejected(api):
    """PRD §3.7: "A `DevelopmentOfficer` closes the campaign, moving
    `campaign_status` from `OPEN` to `CLOSED`... closing an already-`CLOSED`
    campaign yields `ERR_CAMPAIGN_CLOSED`."

    A second close on a CLOSED campaign is rejected.

    Design: Corner/state_machines/close_already_closed_campaign_returns_campaign_closed
    """
    garden = create_garden(name="Edelweiss Estate")
    fund = create_conservancy_fund(garden["id"], match_ratio=0.5, match_cap_cents=10000)
    validate_success(api.close_campaign(fund["id"], DEV))
    resp = api.close_campaign(fund["id"], DEV)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_CLOSED.value, expected_status=409)
