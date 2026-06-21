"""Business validations, temporal overlap, payment/backup constraints, and
validation-ordering conflicts.

Covers Difficulty rules priority_pair_validation_conflict, resource_temporal_overlap
(blackout), boundary_precision_check (empty backup pool), plus the corner
validations and errors sections. PRD §2.6, §2.8, §3.2, §3.3, §3.6, §3.8, §3.11.
"""
import pytest

from test_helpers import validate_success, validate_error, ApiErrorId, fixtures as fx

AGENT = fx.AGENT
ADMIN = fx.ADMIN


# =====================================================================
# Difficulty/priority_pair_validation_conflict
# =====================================================================
def test_settle_on_hold_booking_returns_invalid_state_not_balance(api):
    """PRD §2.8: "Only after a request is known to be authentic, authorized, owned,
    referentially sound, and well-formed do the domain-specific business rules run:
    package-active checks, state-transition legality (`ERR_INVALID_STATE`), the
    booking-version concurrency check (`ERR_STALE_BOOKING_VERSION`), and then the
    temporal, capacity, backup, and fiscal rules."
    PRD §3.8: "Settlement is legal only from `PERFORMED` and only when the booking's
    `balance_due_cents` is zero or below"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_settle_wrong_state_and_balance
    """
    cat, held = fx.create_held_booking(contracted_set_minutes=120)
    resp = api.settle_booking(held["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    after = validate_success(api.get_booking(held["id"], AGENT))
    assert after["status"] == "HOLD"


def test_settle_on_confirmed_booking_returns_invalid_state(api):
    """PRD §3.8: "Settlement is legal only from `PERFORMED` and only when the booking's
    `balance_due_cents` is zero or below"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_settle_wrong_state_and_balance
    """
    cat = fx.setup_home_catalogue()
    cat2, confirmed, ct_id, dep = fx.create_confirmed_booking(cat, deposit_cents=62500,
                                                              contracted_set_minutes=120)
    # CONFIRMED, not PERFORMED, and balance still outstanding -> state error wins.
    resp = api.settle_booking(confirmed["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_capture_missing_payment_returns_not_found_before_state(api):
    """PRD §2.8: "After authorization comes existence: path-referenced resources
    (`ERR_NOT_FOUND`), then body foreign-key references
    (`ERR_REFERENCED_ENTITY_NOT_FOUND`)."
    PRD §2.6: "Path-referenced resources are validated left to right: the leftmost
    identifier in the path is resolved first, and the first one that does not resolve
    to an existing row yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_capture_missing_payment
    """
    fx.set_clock()
    resp = api.capture_payment("00000000-0000-4000-8000-000000000000", AGENT)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_void_missing_payment_returns_not_found_before_state(api):
    """PRD §2.6: "the leftmost identifier in the path is resolved first, and the first
    one that does not resolve to an existing row yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_capture_missing_payment
    """
    fx.set_clock()
    resp = api.void_payment("00000000-0000-4000-8000-000000000000", AGENT)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# =====================================================================
# Difficulty/boundary_precision_check (empty collection)
# =====================================================================
def test_promote_with_empty_backup_pool_rejected(api):
    """PRD §3.11: "if the booking has no accepted backup at all, it is rejected with
    `ERR_NO_ELIGIBLE_BACKUP` (HTTP 409)."

    PRD §2.8 orders body foreign-key existence (`ERR_REFERENCED_ENTITY_NOT_FOUND`)
    *before* the backup business rule, so the targeted `backup_assignment_id` must
    resolve to an existing row on this booking for the no-accepted-backup rule to be
    reached. We offer then decline a backup, leaving the booking with a resolving
    assignment id but no ACCEPTED backup at all.

    Design: Difficulty/boundary_precision_check/empty_backup_pool_promote_rejected
    """
    cat = fx.setup_home_catalogue()
    backup = fx.create_performer(cat["zhome_id"], stage_name="Backup",
                                 base_set_rate_cents=180000)
    cat2, confirmed, ct_id, dep = fx.create_confirmed_booking(cat, deposit_cents=62500)
    ba = fx.offer_backup(confirmed["id"], backup["id"], rank=1)
    # Decline the only offer -> no ACCEPTED backup remains, but the id resolves.
    validate_success(api.decline_backup(ba["id"], fx.make_performer_headers(backup["id"])))
    pre = validate_success(api.get_booking(confirmed["id"], AGENT))

    resp = api.promote_backup(confirmed["id"], ba["id"], pre["version"], AGENT)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_BACKUP.value)

    after = validate_success(api.get_booking(confirmed["id"], AGENT))
    assert after["status"] == "CONFIRMED"


def test_promote_with_only_offered_backup_rejected(api):
    """PRD §3.11: "if the booking has no accepted backup at all, it is rejected with
    `ERR_NO_ELIGIBLE_BACKUP` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/empty_backup_pool_promote_rejected
    """
    cat = fx.setup_home_catalogue()
    backup = fx.create_performer(cat["zhome_id"], stage_name="Backup", base_set_rate_cents=180000)
    cat2, confirmed, ct_id, dep = fx.create_confirmed_booking(cat, deposit_cents=62500)
    ba = fx.offer_backup(confirmed["id"], backup["id"], rank=1)  # OFFERED, never accepted
    pre = validate_success(api.get_booking(confirmed["id"], AGENT))

    resp = api.promote_backup(confirmed["id"], ba["id"], pre["version"], AGENT)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_BACKUP.value)


# =====================================================================
# Difficulty/resource_temporal_overlap (blackout half-open)
# =====================================================================
def test_blackout_window_overlap_rejected_half_open(api):
    """PRD §3.2: "A new blackout window may not overlap an existing window of the same
    performer under half-open semantics — that is, two windows overlap when the start
    of one is strictly before the end of the other and the start of that other is
    strictly before the end of the first. An overlapping window is rejected with
    `ERR_BLACKOUT_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/blackout_overlap_half_open_on_performer
    """
    fx.set_clock()
    zhome = fx.create_home_zone()
    perf = fx.create_performer(zhome["id"])
    fx.create_blackout(perf["id"], start_utc="2026-08-01T10:00:00Z",
                       end_utc="2026-08-01T14:00:00Z", reason="rec")

    resp = api.create_blackout(
        perf["id"],
        {"start_utc": "2026-08-01T12:00:00Z", "end_utc": "2026-08-01T18:00:00Z", "reason": "overlap"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_BLACKOUT_OVERLAP.value)


def test_blackout_window_adjacent_does_not_collide(api):
    """PRD §3.2: "A new blackout window may not overlap an existing window of the same
    performer under half-open semantics — that is, two windows overlap when the start of
    one is strictly before the end of the other and the start of that other is strictly
    before the end of the first."

    Design: Difficulty/resource_temporal_overlap/blackout_overlap_half_open_on_performer
    """
    fx.set_clock()
    zhome = fx.create_home_zone()
    perf = fx.create_performer(zhome["id"])
    fx.create_blackout(perf["id"], start_utc="2026-08-01T10:00:00Z",
                       end_utc="2026-08-01T14:00:00Z")
    # New window starts exactly at the prior window's end -> not strictly before -> no overlap.
    resp = api.create_blackout(
        perf["id"],
        {"start_utc": "2026-08-01T14:00:00Z", "end_utc": "2026-08-01T18:00:00Z"},
        ADMIN,
    )
    validate_success(resp, expected_status=201)


# =====================================================================
# Corner/validations
# =====================================================================
def test_booking_create_event_in_past_rejected(api):
    """PRD §3.3: "The `event_start_utc` must be strictly after the current clock; an
    event at or before the present is rejected with `ERR_EVENT_IN_PAST` (HTTP 422)."

    Design: Corner/validations/booking_create_event_in_past_rejected
    """
    cat = fx.setup_home_catalogue()
    resp = api.create_booking(
        fx.F.create_booking_payload(
            client_id=cat["cli_id"], performer_id=cat["perf_id"], package_id=cat["pkg_id"],
            event_zone_id=cat["zhome_id"], event_start_utc="2026-01-01T00:00:00Z",
            event_miles_from_home=0, contracted_set_minutes=120,
        ),
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_EVENT_IN_PAST.value)


def test_booking_create_set_too_short_rejected(api):
    """PRD §3.3: "if supplied, it must be at least the package's `included_set_minutes`,
    otherwise the create is rejected with `ERR_SET_TOO_SHORT` (HTTP 422)."

    Design: Corner/validations/booking_create_set_too_short_rejected
    """
    cat = fx.setup_home_catalogue()
    resp = api.create_booking(
        fx.F.create_booking_payload(
            client_id=cat["cli_id"], performer_id=cat["perf_id"], package_id=cat["pkg_id"],
            event_zone_id=cat["zhome_id"], event_start_utc="2026-08-01T20:00:00Z",
            event_miles_from_home=0, contracted_set_minutes=90,
        ),
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_SET_TOO_SHORT.value)


def test_booking_create_on_retired_package_rejected(api):
    """PRD §3.3: "The selected package must be `ACTIVE` at create time; referencing a
    `RETIRED` package is rejected with `ERR_PACKAGE_RETIRED` (HTTP 409)."

    Design: Corner/validations/booking_create_on_retired_package_rejected
    """
    fx.set_clock()
    zhome = fx.create_home_zone()
    pkg = fx.create_package()
    fx.get_success_data(api.retire_package(pkg["id"], ADMIN))
    perf = fx.create_performer(zhome["id"])
    cli = fx.create_client()

    resp = api.create_booking(
        fx.F.create_booking_payload(
            client_id=cli["id"], performer_id=perf["id"], package_id=pkg["id"],
            event_zone_id=zhome["id"], event_start_utc="2026-08-01T20:00:00Z",
            event_miles_from_home=0, contracted_set_minutes=120,
        ),
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_PACKAGE_RETIRED.value)


def test_hold_blocked_by_blackout_window(api):
    """PRD §3.3: "The event's start instant must not fall inside any blackout window of
    that performer — that is, the start must not lie at or after a window's `start_utc`
    and strictly before its `end_utc`; a violation is rejected with
    `ERR_PERFORMER_BLACKED_OUT` (HTTP 409)."

    Design: Corner/validations/hold_blocked_by_blackout_window
    """
    fx.set_clock()
    zhome = fx.create_home_zone()
    pkg = fx.create_package()
    perf = fx.create_performer(zhome["id"])
    fx.create_blackout(perf["id"], start_utc="2026-08-01T18:00:00Z",
                       end_utc="2026-08-01T22:00:00Z")
    cli = fx.create_client()
    bk = fx.create_booking(
        {"zhome_id": zhome["id"], "pkg_id": pkg["id"], "perf_id": perf["id"], "cli_id": cli["id"]},
        event_zone_id=zhome["id"], event_start_utc="2026-08-01T20:00:00Z", contracted_set_minutes=120,
    )

    resp = api.hold_booking(bk["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_PERFORMER_BLACKED_OUT.value)


def test_capture_overpayment_rejected(api):
    """PRD §3.6: "the captured amount must not exceed the booking's outstanding
    `balance_due_cents`, and an over-capture is rejected with `ERR_OVERPAYMENT`
    (HTTP 409)."

    Design: Corner/validations/capture_overpayment_rejected
    """
    cat, held = fx.create_held_booking(contracted_set_minutes=120)
    pay = fx.create_payment(held["id"], kind="BALANCE", amount_cents=300000)
    resp = api.capture_payment(pay["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT.value)


def test_backup_offer_to_active_performer_rejected(api):
    """PRD §3.11: "A candidate may not be the booking's current active performer;
    offering the active performer as their own backup is rejected with
    `ERR_BACKUP_IS_PRIMARY` (HTTP 409)."

    Design: Corner/validations/backup_offer_to_primary_rejected
    """
    cat, held = fx.create_held_booking(contracted_set_minutes=120)
    resp = api.create_backup_assignment(
        held["id"], {"candidate_performer_id": cat["perf_id"], "rank": 1}, AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_BACKUP_IS_PRIMARY.value)


def test_pagination_limit_out_of_range_rejected(api):
    """PRD §2.3: "A request whose `limit` falls below 1 or above 100, or whose `offset`
    is negative, is rejected with `ERR_VALIDATION_LIMIT` (HTTP 422)"

    Design: Corner/validations/pagination_limit_out_of_range_rejected
    """
    resp = api.list_bookings(AGENT, params={"limit": 500})
    validate_error(resp, ApiErrorId.ERR_VALIDATION_LIMIT.value)


# =====================================================================
# Corner/errors
# =====================================================================
def test_settle_with_outstanding_balance_rejected(api):
    """PRD §3.8: "attempting to settle with a positive outstanding balance is rejected
    with `ERR_BALANCE_OUTSTANDING` (HTTP 409)."

    Design: Corner/errors/settle_with_outstanding_balance_rejected
    """
    cat = fx.setup_home_catalogue()
    cat2, confirmed, ct_id, dep = fx.create_confirmed_booking(cat, deposit_cents=62500,
                                                              contracted_set_minutes=120)
    # only deposit captured -> balance still outstanding after performing
    performed = fx.advance_to_performed(confirmed["id"], actual_set_minutes=120)

    resp = api.settle_booking(performed["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_BALANCE_OUTSTANDING.value)


def test_promote_non_lowest_rank_backup_rejected(api):
    """PRD §3.11: "If the assignment the caller targeted is not that lowest-rank
    eligible one, the request is rejected with `ERR_NOT_LOWEST_RANK_BACKUP` (HTTP 409)"

    Design: Corner/errors/promote_non_lowest_rank_backup_rejected
    """
    s = fx.setup_confirmed_with_two_accepted_backups()
    booking = s["booking"]
    resp = api.promote_backup(booking["id"], s["ba2"]["id"], s["version_pre_promote"], AGENT)
    validate_error(resp, ApiErrorId.ERR_NOT_LOWEST_RANK_BACKUP.value)
