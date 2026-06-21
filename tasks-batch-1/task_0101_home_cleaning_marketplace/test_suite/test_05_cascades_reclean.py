"""Cascade and guarantee tests: series-cancel -> booking-cancel -> ledger-refund
depth-3 cascade, reclean scheduling spawning an assigned 0-priced booking, the
tip-attach payout conservation, and tip/reclean corner cases.
"""
from test_helpers import (
    get_success_data, validate_success, validate_error, ApiErrorId,
    make_customer_headers, make_cleaner_headers,
    setup_series_with_one_occurrence, setup_reclean_requested,
    setup_completed_booking,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _ledger_for(api, booking_id, kind=None):
    params = {"booking_id": booking_id}
    if kind:
        params["kind"] = kind
    return api.list_ledger_entries(ADMIN, params=params).json()["data"]


def _payout_for(api, booking_id):
    payouts = api.list_cleaner_payouts(ADMIN, params={"booking_id": booking_id}).json()["data"]
    assert len(payouts) == 1, f"Expected exactly one payout for {booking_id}, got {len(payouts)}"
    return payouts[0]


# ===========================================================================
# Queue A — Rule 4: transitive_cascade
# ===========================================================================
def test_series_cancel_cascades_to_booking_cancel_and_refund(api):
    """PRD §3.4: "Cancellation cascades: every child booking still in `SCHEDULED`
    or `RESCHEDULED` is cancelled, and each such child cancellation runs its own
    refund-and-fee settlement transitively as in §3.5"
    PRD §2.9: "When a booking is cancelled, the refund credits the full
    `quoted_price_cents` back"

    Cancelling a WEEKLY series with one generated SCHEDULED STUDIO booking (6000,
    far from start) cancels the child and writes a REFUND of 6000.

    Design: Difficulty/transitive_cascade/series_cancel_cascades_to_booking_cancel_to_ledger_refund
    """
    world = setup_series_with_one_occurrence(
        home_size="STUDIO", cadence="WEEKLY", first_occurrence_date="2026-06-20T09:00:00Z"
    )
    series = world["series"]
    child = world["booking"]
    assert child["status"] == "SCHEDULED"
    cust_hdr = make_customer_headers(world["customer"]["id"])
    cancelled_series = validate_success(api.cancel_series(series["id"], cust_hdr))
    assert cancelled_series["status"] == "CANCELLED"

    child_after = validate_success(api.get_booking(child["id"], cust_hdr))
    assert child_after["status"] == "CANCELLED", \
        f"Expected child booking CANCELLED via cascade, got {child_after['status']}"
    refunds = _ledger_for(api, child["id"], "REFUND")
    assert any(e["amount_cents"] == 6000 for e in refunds), \
        f"Expected a REFUND of 6000 from the cascaded cancel, got {refunds}"


def test_schedule_reclean_spawns_assigned_zero_priced_booking(api):
    """PRD §3.7: "The spawned booking carries `reclean_of_booking_id` pointing at
    the original, sets `is_reclean` to true, pins `quoted_price_cents` to 0,
    copies the original's `cleaner_id` (re-running assignment pinned to that
    original cleaner), and starts in `SCHEDULED`"
    PRD §3.7: "A `PlatformAdmin` then schedules the free re-clean against a
    `RECLEAN_REQUESTED` booking, which moves that booking to the terminal
    `RECLEAN_SCHEDULED` state and spawns a brand-new booking."

    Scheduling a reclean moves the original to RECLEAN_SCHEDULED and spawns a new
    is_reclean booking pinned to the original cleaner, priced 0.

    Design: Difficulty/transitive_cascade/schedule_reclean_spawns_booking_and_assigns_cleaner
    """
    world = setup_reclean_requested(home_size="TWO_BR", add_ons=("DEEP_CLEAN",), supplies_provided_by="CLEANER")
    original = world["booking"]
    assert original["status"] == "RECLEAN_REQUESTED"
    spawned = validate_success(
        api.schedule_reclean(original["id"], {"scheduled_start": "2026-06-13T09:00:00Z"}, ADMIN)
    )
    assert spawned["is_reclean"] is True, "spawned booking must have is_reclean true"
    assert spawned["reclean_of_booking_id"] == original["id"], \
        f"Expected reclean_of_booking_id {original['id']}, got {spawned['reclean_of_booking_id']}"
    assert spawned["cleaner_id"] == world["cleaner"]["id"], \
        f"Expected spawned cleaner_id {world['cleaner']['id']}, got {spawned['cleaner_id']}"
    assert spawned["quoted_price_cents"] == 0, \
        f"Expected reclean priced 0, got {spawned['quoted_price_cents']}"

    original_after = validate_success(api.get_booking(original["id"], ADMIN))
    assert original_after["status"] == "RECLEAN_SCHEDULED", \
        f"Expected original RECLEAN_SCHEDULED, got {original_after['status']}"


def test_series_cancel_sets_terminal_state_and_nulls_next_date(api):
    """PRD §3.4: "A customer may cancel a series that is in either `ACTIVE` or
    `PAUSED`, moving it to the terminal `CANCELLED` state."
    PRD §3.4: "Cancellation also sets the series' `next_occurrence_date` to null
    and increments the series `version`."

    The cascade root: cancelling the series moves it to CANCELLED and nulls
    next_occurrence_date.

    Design: Difficulty/transitive_cascade/series_cancel_cascades_to_booking_cancel_to_ledger_refund
    """
    world = setup_series_with_one_occurrence(
        home_size="STUDIO", cadence="WEEKLY", first_occurrence_date="2026-06-20T09:00:00Z"
    )
    cust_hdr = make_customer_headers(world["customer"]["id"])
    cancelled = validate_success(api.cancel_series(world["series"]["id"], cust_hdr))
    assert cancelled["status"] == "CANCELLED", f"Expected CANCELLED, got {cancelled['status']}"
    assert cancelled["next_occurrence_date"] is None, \
        f"Expected next_occurrence_date null after cancel, got {cancelled['next_occurrence_date']}"


def test_schedule_reclean_writes_zero_valued_reclean_credit_marker(api):
    """PRD §3.7: "its creation writes a `RECLEAN_CREDIT` ledger entry valued at 0
    as a marker, with no customer charge."
    PRD §2.9: "`RECLEAN_CREDIT` (a zero-valued marker that records a guarantee
    re-clean carries no customer charge)"

    The transitive ledger side effect of spawning the reclean booking: a
    RECLEAN_CREDIT entry valued 0 keyed to the new reclean booking.

    Design: Difficulty/transitive_cascade/schedule_reclean_spawns_booking_and_assigns_cleaner
    """
    world = setup_reclean_requested(home_size="TWO_BR", add_ons=("DEEP_CLEAN",), supplies_provided_by="CLEANER")
    spawned = validate_success(
        api.schedule_reclean(world["booking"]["id"], {"scheduled_start": "2026-06-13T09:00:00Z"}, ADMIN)
    )
    credits = _ledger_for(api, spawned["id"], "RECLEAN_CREDIT")
    assert len(credits) == 1, f"Expected one RECLEAN_CREDIT marker for the reclean booking, got {credits}"
    assert credits[0]["amount_cents"] == 0, \
        f"Expected RECLEAN_CREDIT amount_cents 0, got {credits[0]['amount_cents']}"


# ===========================================================================
# Queue A — Rule 9: compensating_invariant (tip-attach payout conservation)
# ===========================================================================
def test_tip_attach_conserves_payout_total(api):
    """PRD §3.7: "Creating the tip recomputes the booking's existing
    `CleanerPayout`: the payout's `tip_cents` is set to the tip's `amount_cents`
    and its `total_cents` becomes `base_payout_cents` plus the new `tip_cents`."

    After completing an 18000 booking (base_payout 12600) and tipping 2000, the
    payout's total_cents equals 14600 exactly.

    Design: Difficulty/compensating_invariant/tip_attach_conserves_payout_total_against_tip
    """
    world = setup_completed_booking(
        home_size="TWO_BR", add_ons=("DEEP_CLEAN",), supplies_provided_by="CLEANER", rating=5
    )
    booking = world["booking"]
    payout_before = _payout_for(api, booking["id"])
    assert payout_before["base_payout_cents"] == 12600
    cust_hdr = make_customer_headers(world["customer"]["id"])
    get_success_data(api.create_tip(
        {"booking_id": booking["id"], "customer_id": world["customer"]["id"], "amount_cents": 2000}, cust_hdr
    ))
    payout_after = _payout_for(api, booking["id"])
    assert payout_after["base_payout_cents"] == 12600
    assert payout_after["tip_cents"] == 2000, f"Expected tip_cents 2000, got {payout_after['tip_cents']}"
    assert payout_after["total_cents"] == 14600, \
        f"Expected total_cents 14600 (12600 + 2000), got {payout_after['total_cents']}"


def test_completion_payout_total_equals_base_plus_zero_tip(api):
    """PRD §3.7: "a `tip_cents` of 0, and a `total_cents` equal to
    `base_payout_cents` plus `tip_cents`."

    A completed 18000 booking with no tip has base_payout_cents 12600, tip_cents
    0, total_cents 12600 — the payout total conserves base plus zero tip.

    Design: Difficulty/compensating_invariant/tip_attach_conserves_payout_total_against_tip
    """
    world = setup_completed_booking(
        home_size="TWO_BR", add_ons=("DEEP_CLEAN",), supplies_provided_by="CLEANER", rating=5
    )
    payout = _payout_for(api, world["booking"]["id"])
    assert payout["base_payout_cents"] == 12600
    assert payout["tip_cents"] == 0, f"Expected tip_cents 0 before any tip, got {payout['tip_cents']}"
    assert payout["total_cents"] == 12600, \
        f"Expected total_cents 12600 (12600 + 0), got {payout['total_cents']}"


# ===========================================================================
# Queue B — Corner: endpoints (rating recorded on complete)
# ===========================================================================
def test_rating_on_complete_updates_cleaner_counters(api):
    """PRD §3.7: "Completion may carry an optional `rating` from the
    customer-facing star scale; when present it folds into the cleaner's
    `rating_sum` and `rating_count`."
    PRD §3.7: "completion also increments the customer's `lifetime_booking_count`
    by one and the cleaner's `completed_job_count` by one"

    Completing with rating=4 sets the cleaner's rating_sum to 4, rating_count to
    1, and completed_job_count to 1.

    Design: Corner/endpoints/rate_recorded_on_complete_updates_cleaner_rating
    """
    world = setup_completed_booking(home_size="STUDIO", add_ons=(), supplies_provided_by="CUSTOMER", rating=4)
    cleaner = validate_success(api.get_cleaner(world["cleaner"]["id"], ADMIN))
    assert cleaner["rating_sum"] == 4, f"Expected rating_sum 4, got {cleaner['rating_sum']}"
    assert cleaner["rating_count"] == 1, f"Expected rating_count 1, got {cleaner['rating_count']}"
    assert cleaner["completed_job_count"] == 1, \
        f"Expected completed_job_count 1, got {cleaner['completed_job_count']}"


# ===========================================================================
# Queue B — Corner: errors (tip permissibility)
# ===========================================================================
def test_second_tip_on_same_booking_rejected(api):
    """PRD §3.7: "A tip is permitted only on a `COMPLETED` booking, only by the
    booking's owning customer, and at most once per booking — a tip on a
    non-completed booking, by a non-owner, or a second tip on the same booking is
    rejected with `ERR_TIP_NOT_ALLOWED`."

    A second POST /tips for the same booking_id -> ERR_TIP_NOT_ALLOWED.

    Design: Corner/errors/second_tip_on_same_booking_returns_tip_not_allowed
    """
    world = setup_completed_booking(home_size="STUDIO", add_ons=(), supplies_provided_by="CUSTOMER", rating=5)
    cust = world["customer"]
    cust_hdr = make_customer_headers(cust["id"])
    get_success_data(api.create_tip(
        {"booking_id": world["booking"]["id"], "customer_id": cust["id"], "amount_cents": 1000}, cust_hdr
    ))
    validate_error(
        api.create_tip(
            {"booking_id": world["booking"]["id"], "customer_id": cust["id"], "amount_cents": 1000}, cust_hdr
        ),
        ApiErrorId.ERR_TIP_NOT_ALLOWED.value,
    )


def test_tip_on_non_completed_booking_rejected(api):
    """PRD §3.7: "a tip on a non-completed booking, by a non-owner, or a second
    tip on the same booking is rejected with `ERR_TIP_NOT_ALLOWED`."

    A tip on a still-SCHEDULED booking -> ERR_TIP_NOT_ALLOWED.

    Design: Corner/errors/tip_on_non_completed_booking_returns_tip_not_allowed
    """
    from test_helpers import setup_booking_world, create_one_time_booking
    world = setup_booking_world(home_size="STUDIO", loyalty_count=0)
    cust = world["customer"]
    cust_hdr = make_customer_headers(cust["id"])
    booking = create_one_time_booking(
        world, scheduled_start="2026-06-10T09:00:00Z", cleaner_id=world["cleaner"]["id"]
    )
    assert booking["status"] == "SCHEDULED"
    validate_error(
        api.create_tip(
            {"booking_id": booking["id"], "customer_id": cust["id"], "amount_cents": 1000}, cust_hdr
        ),
        ApiErrorId.ERR_TIP_NOT_ALLOWED.value,
    )
