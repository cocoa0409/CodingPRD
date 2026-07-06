"""Compensating-invariant, OCC, derived-field-reconciliation, cascading-side-effect,
FM-channel and immediate-consistency tests.

Covers Difficulty queue (compensating_invariant) and Corner queue (endpoints,
cross_cutting_complexity_layers, consistency_model, errors sections).
"""
from test_helpers import (
    validate_success,
    validate_error,
    make_patron_headers,
    TEST_USERS,
    setup_venue_lot_film,
    setup_scheduled_showtime,
    create_venue,
    create_lot,
    create_film,
    create_showtime,
    create_season_pass,
    create_private_rental,
    make_reservation,
    set_clock,
)

OPERATOR = TEST_USERS["venue_operator_headers"]


# =====================================================================
# Difficulty: compensating_invariant / stall_capacity_conserved_create_then_cancel
# =====================================================================
def test_stall_capacity_conserved_create_then_cancel(api):
    """PRD §3.5: "On cancellation the system releases capacity exactly as the sweep does —
    decrementing `reserved_stall_count` by `stalls_used`, decrementing `reserved_person_count`
    by `occupant_count` for a per-person showtime, and restoring a season-pass redemption
    when one was used."

    Design: Difficulty/compensating_invariant/stall_capacity_conserved_create_then_cancel
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z", stall_count=5)
    st = create_showtime(venue["id"], lot["id"], film["id"], "2026-07-14T02:00:00Z")
    resv = make_reservation(st, "patron-mmm", occupant_count=2)
    mid = validate_success(api.get_showtime(st["id"], OPERATOR))
    assert mid["reserved_stall_count"] == 1
    cancelled = validate_success(
        api.cancel_reservation(resv["id"], resv["version"], make_patron_headers("patron-mmm"))
    )
    assert cancelled["occupancy_status"] == "CANCELLED"
    after = validate_success(api.get_showtime(st["id"], OPERATOR))
    assert after["reserved_stall_count"] == 0, "stall must be credited back on cancel"


def test_stall_count_debited_on_create(api):
    """PRD §2.5: "On a showtime, `reserved_stall_count` is the running number of stalls held
    by reservations whose `occupancy_status` is `CONFIRMED`, `CHECKED_IN`, or `SCANNED` ...
    Both are reconciled on every reservation create, cancel, and no-show sweep."

    Design: Difficulty/compensating_invariant/stall_capacity_conserved_create_then_cancel
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z", stall_count=5)
    st = create_showtime(venue["id"], lot["id"], film["id"], "2026-07-14T03:00:00Z")
    make_reservation(st, "patron-mmm2", occupant_count=2)
    after = validate_success(api.get_showtime(st["id"], OPERATOR))
    assert after["reserved_stall_count"] == 1


# =====================================================================
# Difficulty: compensating_invariant / season_pass_redemptions_conserved_create_then_cancel
# =====================================================================
def test_season_pass_redemptions_conserved_create_then_cancel(api):
    """PRD §3.5: "On cancellation the system releases capacity exactly as the sweep does —
    decrementing `reserved_stall_count` by `stalls_used`, decrementing `reserved_person_count`
    by `occupant_count` for a per-person showtime, and restoring a season-pass redemption
    when one was used — and increments the reservation's `version`."
    PRD §2.5: "On a season pass, `redemptions_used` is the count of reservations created
    against that pass that are currently in occupancy `CONFIRMED`, `CHECKED_IN`, or
    `SCANNED`; it rises and falls as redemptions are made and released."

    Design: Difficulty/compensating_invariant/season_pass_redemptions_conserved_create_then_cancel
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z")
    sp = create_season_pass("patron-nnn", "2026-07-01T00:00:00Z", "2026-07-31T23:59:59Z",
                            tier="GOLD", max_redemptions=3)
    st = create_showtime(venue["id"], lot["id"], film["id"], "2026-07-15T02:00:00Z")
    resv = make_reservation(st, "patron-nnn", occupant_count=2, season_pass_id=sp["id"])
    assert resv["amount_due_cents"] == 0  # single feature, pass covers admission
    mid = validate_success(api.get_season_pass(sp["id"], OPERATOR))
    assert mid["redemptions_used"] == 1
    cancelled = validate_success(
        api.cancel_reservation(resv["id"], resv["version"], make_patron_headers("patron-nnn"))
    )
    assert cancelled["occupancy_status"] == "CANCELLED"
    after = validate_success(api.get_season_pass(sp["id"], OPERATOR))
    assert after["redemptions_used"] == 0, "redemption must be restored on cancel"


def test_season_pass_redemption_incremented_on_create(api):
    """PRD §3.4: "On a successful create, the showtime's `reserved_stall_count` and
    `reserved_person_count` are increased by this reservation's contribution, the showtime's
    `version` is incremented, and if a pass was used its `redemptions_used` rises by one."

    Design: Difficulty/compensating_invariant/season_pass_redemptions_conserved_create_then_cancel
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z")
    sp = create_season_pass("patron-nnn2", "2026-07-01T00:00:00Z", "2026-07-31T23:59:59Z",
                            tier="GOLD", max_redemptions=3)
    st = create_showtime(venue["id"], lot["id"], film["id"], "2026-07-16T02:00:00Z")
    make_reservation(st, "patron-nnn2", occupant_count=2, season_pass_id=sp["id"])
    after = validate_success(api.get_season_pass(sp["id"], OPERATOR))
    assert after["redemptions_used"] == 1


# =====================================================================
# Corner: endpoints / fm_channel_waterfall_first_free
# =====================================================================
def test_fm_channel_waterfall_first_free(api):
    """PRD §3.9: "The assigned `frequency` is the first entry of the venue's
    `fm_channel_pool`, in list order, that is not already assigned to a time-overlapping
    showtime of the same venue."

    Design: Corner/endpoints/fm_channel_waterfall_first_free
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z",
                                            fm_channel_pool=["87.9", "88.1"])
    st = create_showtime(venue["id"], lot["id"], film["id"], "2026-08-14T02:00:00Z")
    fm = validate_success(api.assign_fm_channel(st["id"], OPERATOR), expected_status=201)
    assert fm["frequency"] == "87.9"
    assert fm["status"] == "ACTIVE"


# =====================================================================
# Corner: endpoints / fm_channel_exhausted_single_pool_overlap
# =====================================================================
def test_fm_channel_exhausted_single_pool_overlap(api):
    """PRD §3.9: "If every frequency in the pool is occupied by a time-overlapping showtime,
    the assignment is rejected with `ERR_NO_FM_CHANNEL` (HTTP 409)."

    Design: Corner/endpoints/fm_channel_exhausted_single_pool_overlap
    """
    venue = create_venue(name="VC28", fm_channel_pool=["87.9"])
    lotA = create_lot(venue["id"], name="LA", stall_count=10, person_capacity=100)
    lotB = create_lot(venue["id"], name="LB", stall_count=10, person_capacity=100)
    film = create_film(title="F", runtime_minutes=120, rating="PG")
    set_clock("2026-06-01T00:00:00Z")
    stA = create_showtime(venue["id"], lotA["id"], film["id"], "2026-08-15T02:00:00Z")
    validate_success(api.assign_fm_channel(stA["id"], OPERATOR), expected_status=201)
    stB = create_showtime(venue["id"], lotB["id"], film["id"], "2026-08-15T03:00:00Z")
    res = api.assign_fm_channel(stB["id"], OPERATOR)
    validate_error(res, "ERR_NO_FM_CHANNEL")


# =====================================================================
# Corner: errors / error_stale_version_reservation_create_triggerable
# =====================================================================
def test_stale_version_reservation_create(api):
    """PRD §2.6: "Because a successful reservation create itself advances the showtime's
    `version` (through the count reconciliation in §2.5), two strictly sequential creates that
    both carry the same observed showtime `version` cannot both bind the last remaining stall:
    the first advances the version, and the second — still carrying the now-superseded value —
    is rejected as stale."

    Design: Corner/errors/error_stale_version_reservation_create_triggerable
    """
    venue, lot, film, st = setup_scheduled_showtime(
        clock="2026-06-01T00:00:00Z", start_utc="2026-08-17T02:00:00Z"
    )
    observed_version = st["version"]
    make_reservation(st, "patron-s1", occupant_count=2)  # advances showtime.version
    # Second create still carries the pre-first-create version -> stale.
    res = api.create_reservation(
        {"showtime_id": st["id"], "patron_id": "patron-s2", "occupant_count": 2,
         "expected_showtime_version": observed_version},
        make_patron_headers("patron-s2"),
    )
    validate_error(res, "ERR_STALE_VERSION")


# =====================================================================
# Corner: cross_cutting_complexity_layers / occ_rental_approve_stale_version
# =====================================================================
def test_occ_rental_approve_stale_version(api):
    """PRD §2.6: "Approving a private rental requires `expected_private_rental_version`,
    carrying the `version` of the rental the client last read; if the rental's `version` has
    advanced since — for example because another operator already acted on it — the approval
    is rejected with `ERR_STALE_VERSION` (HTTP 412) before the interval-overlap check runs."

    Design: Corner/cross_cutting_complexity_layers/occ_rental_approve_stale_version
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z")
    rental = create_private_rental(
        venue["id"], lot["id"], "org-occ", "2026-08-20T02:00:00Z", "2026-08-20T05:00:00Z",
        flat_venue_fee_cents=100000, per_hour_cents=10000,
    )
    stale_version = rental["version"] - 1
    res = api.approve_private_rental(rental["id"], stale_version, OPERATOR)
    validate_error(res, "ERR_STALE_VERSION")


# =====================================================================
# Corner: cross_cutting_complexity_layers / reserved_person_count_reconciled_on_create
# =====================================================================
def test_reserved_person_count_reconciled_on_create(api):
    """PRD §2.5: "`reserved_person_count` is the running sum of `occupant_count` over those
    same reservations for a per-person showtime. Both are reconciled on every reservation
    create, cancel, and no-show sweep."

    Design: Corner/cross_cutting_complexity_layers/reserved_person_count_reconciled_on_create
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z", person_capacity=50)
    st = create_showtime(venue["id"], lot["id"], film["id"], "2026-08-21T02:00:00Z",
                         pricing_mode="PER_PERSON", base_price_cents=900)
    resv = make_reservation(st, "patron-rp", occupant_count=3)
    assert resv["stalls_used"] == 0
    after = validate_success(api.get_showtime(st["id"], OPERATOR))
    assert after["reserved_person_count"] == 3


# =====================================================================
# Corner: cross_cutting_complexity_layers / rental_approve_closes_lot_reopens_on_cancel
# =====================================================================
def test_rental_approve_closes_lot_reopens_on_cancel(api):
    """PRD §3.7: "On approval the system sets the lot's `status` to `CLOSED`, marking it
    exclusively held, and increments the rental's `version`."
    PRD §3.7: "An `APPROVED` rental may later be cancelled by a `VenueOperator`, advancing
    `status` to `CANCELLED` and setting the held lot's `status` back to `OPEN`, releasing the
    exclusive hold."

    Design: Corner/cross_cutting_complexity_layers/rental_approve_closes_lot_reopens_on_cancel
    """
    venue, lot, film = setup_venue_lot_film(clock="2026-06-01T00:00:00Z")
    rental = create_private_rental(
        venue["id"], lot["id"], "org-c", "2026-08-22T02:00:00Z", "2026-08-22T05:00:00Z",
        flat_venue_fee_cents=100000, per_hour_cents=10000,
    )
    approved = validate_success(
        api.approve_private_rental(rental["id"], rental["version"], OPERATOR)
    )
    lot_closed = validate_success(api.get_lot(lot["id"], OPERATOR))
    assert lot_closed["status"] == "CLOSED"
    cancelled = validate_success(api.cancel_private_rental(approved["id"], OPERATOR))
    assert cancelled["status"] == "CANCELLED"
    lot_open = validate_success(api.get_lot(lot["id"], OPERATOR))
    assert lot_open["status"] == "OPEN"


# =====================================================================
# Corner: consistency_model / reservation_create_reflects_capacity_immediately
# =====================================================================
def test_reservation_create_reflects_capacity_immediately(api):
    """PRD §2.5: "Both are reconciled on every reservation create, cancel, and no-show
    sweep."
    PRD §3.4: "On a successful create, the showtime's `reserved_stall_count` and
    `reserved_person_count` are increased by this reservation's contribution."

    Design: Corner/consistency_model/reservation_create_reflects_capacity_immediately
    """
    venue, lot, film, st = setup_scheduled_showtime(
        clock="2026-06-01T00:00:00Z", start_utc="2026-08-23T02:00:00Z"
    )
    make_reservation(st, "patron-im", occupant_count=2)
    after = validate_success(api.get_showtime(st["id"], OPERATOR))
    assert after["reserved_stall_count"] == 1
