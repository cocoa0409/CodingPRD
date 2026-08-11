"""Booking submission: guard ordering (state, schedule, skill gate, staffing,
zone minimum) and the two optimistic-concurrency version checks.

Queue A (Difficulty): cross_entity_state_dependency, priority_pair_validation_conflict.
Queue B (Corner): validations, errors, cross_cutting_layers.
"""
from test_helpers import (
    fixtures as fx,
    validate_success, validate_error,
    assert_booking,
    ApiErrorId,
)

ERR = ApiErrorId


# ─── cross_entity_state_dependency / booking_submit_requires_cart_active ───

def test_submit_with_active_cart_moves_booking_to_pending_deposit(api):
    """PRD §2.9: "A Package, CoffeeCart, TravelZone, AddOn, or InventoryItem
    referenced by a booking creation, a booking submission, an add-on attach, or a
    reservation creation must be in `ACTIVE` status."
    PRD §3.5: "The booking moves from `QUOTE` to `PENDING_DEPOSIT`, and three
    versions increment together: the booking's own `version`, the referenced
    cart's `version`, and the primary barista's `version`."

    With the referenced cart ACTIVE, a guarded submission succeeds and lands in
    PENDING_DEPOSIT with the quote repriced.

    Design: Difficulty/cross_entity_state_dependency/booking_submit_requires_cart_active
    """
    ctx = fx.setup_quote_with_assignment(package_kind="FLAT")
    submitted = fx.submit_quote(ctx, ctx["booking"]["id"])
    assert_booking(submitted)
    assert submitted["status"] == "PENDING_DEPOSIT", submitted
    assert submitted["quoted_total_cents"] == 62000, submitted
    assert submitted["deposit_due_cents"] == 18600, submitted


def test_confirmed_booking_counts_toward_cart_committed_event_count(api):
    """PRD §3.1: "Each cart also exposes `committed_event_count`, a read-only figure
    derived on read: the number of EventBooking rows in `CONFIRMED` or
    `IN_PROGRESS` status that reference the cart."
    PRD §3.6: "the cart's derived `committed_event_count` reflects one more
    committed event"

    The same cart that gates submission derives its committed tally from booking
    status: zero while the booking sits in PENDING_DEPOSIT, one once the deposit
    settles it into CONFIRMED.

    Design: Difficulty/cross_entity_state_dependency/booking_submit_requires_cart_active
    """
    ctx = fx.setup_submitted_booking(package_kind="FLAT")
    cart_mid = validate_success(api.get_cart(ctx["cart"]["id"], fx.OPS), 200)
    assert cart_mid["committed_event_count"] == 0, cart_mid

    fx.pay_deposit(ctx, ctx["booking"]["id"], ctx["booking"]["deposit_due_cents"])
    booking = validate_success(api.get_booking(ctx["booking"]["id"], fx.OPS), 200)
    assert booking["status"] == "CONFIRMED", booking

    cart_after = validate_success(api.get_cart(ctx["cart"]["id"], fx.OPS), 200)
    assert cart_after["committed_event_count"] == 1, cart_after


# ─── priority_pair_validation_conflict / state_vs_fiscal_on_submit ────────

def test_resubmit_with_stale_versions_rejected_invalid_state(api):
    """PRD §3.5: "The guards run in a fixed order: booking state first — anything not
    in `QUOTE` is rejected with `ERR_INVALID_STATE` (HTTP 409) — then catalog
    liveness of the referenced package and cart (`ERR_PACKAGE_NOT_ACTIVE`,
    `ERR_CART_NOT_ACTIVE`), then the cart's schedule, then the add-on skill gate,
    then staffing presence, then the zone minimum, and finally the two
    stale-version checks."

    A second submission against a PENDING_DEPOSIT booking trips the state guard
    before the stale-version check is ever reached — even though the replayed
    OCC tokens are stale, the outcome is ERR_INVALID_STATE, not ERR_STALE_VERSION.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_submit
    """
    ctx = fx.setup_quote_with_assignment(package_kind="FLAT")
    stale_cart_v = ctx["cart"]["version"]
    stale_barista_v = ctx["barista"]["version"]
    first = fx.submit_quote(ctx, ctx["booking"]["id"])
    assert first["status"] == "PENDING_DEPOSIT", first

    res = fx.submit_quote_raw(ctx, ctx["booking"]["id"],
                              stale_cart_v, stale_barista_v)
    err = validate_error(res, ERR.ERR_INVALID_STATE, expected_status=409)
    assert err["error_id"] != ERR.ERR_STALE_VERSION.value


def test_resubmit_with_fresh_versions_still_rejected_invalid_state(api):
    """PRD §3.5: "The guards run in a fixed order: booking state first — anything not
    in `QUOTE` is rejected with `ERR_INVALID_STATE` (HTTP 409) — then catalog
    liveness of the referenced package and cart (`ERR_PACKAGE_NOT_ACTIVE`,
    `ERR_CART_NOT_ACTIVE`), then the cart's schedule, then the add-on skill gate,
    then staffing presence, then the zone minimum, and finally the two
    stale-version checks."

    Even with perfectly current OCC tokens, a booking that already left QUOTE
    cannot be submitted again: state beats every later guard.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_submit
    """
    ctx = fx.setup_submitted_booking(package_kind="FLAT")
    res = fx.submit_quote_raw(
        ctx, ctx["booking"]["id"],
        fx.current_cart_version(ctx["cart"]["id"]),
        fx.current_barista_version(ctx["barista"]["id"]))
    validate_error(res, ERR.ERR_INVALID_STATE, expected_status=409)


# ─── priority_pair_validation_conflict / temporal_vs_fiscal_on_submit ─────

def _setup_double_booking_and_low_subtotal(new_event_start, new_event_end):
    """A CONFIRMED booking occupies CART-A 2026-05-10 10:00-12:00. A new QUOTE
    booking on the same cart uses an 8000-cent package against a zone with a
    10000-cent subtotal minimum, so the cart-schedule guard and the zone-minimum
    guard are both armed whenever the windows collide."""
    ctx = fx.setup_base_catalog(package_kind="FLAT")
    other = fx.create_quote_booking(ctx, event_start="2026-05-10T10:00:00Z",
                                    event_end="2026-05-10T12:00:00Z")
    fx.offer_primary_assignment(ctx, other["id"])
    other = fx.submit_quote(ctx, other["id"])
    fx.pay_deposit(ctx, other["id"], other["deposit_due_cents"])

    ctx["package"] = fx.create_flat_package(flat_price_cents=8000, max_guests=20)
    ctx["zone"] = fx.create_travel_zone(max_distance_km=60, banded_fee_cents=15000,
                                        per_km_rate_cents=300,
                                        min_booking_subtotal_cents=10000)
    new_booking = fx.create_quote_booking(
        ctx, event_start=new_event_start, event_end=new_event_end,
        guest_count=10, distance_km=40)
    fx.offer_primary_assignment(ctx, new_booking["id"])
    return ctx, new_booking


def test_submit_with_cart_conflict_and_low_subtotal_reports_cart_conflict(api):
    """PRD §3.5: "The guards run in a fixed order: booking state first — anything not
    in `QUOTE` is rejected with `ERR_INVALID_STATE` (HTTP 409) — then catalog
    liveness of the referenced package and cart (`ERR_PACKAGE_NOT_ACTIVE`,
    `ERR_CART_NOT_ACTIVE`), then the cart's schedule, then the add-on skill gate,
    then staffing presence, then the zone minimum, and finally the two
    stale-version checks."

    With the cart's schedule violated (buffered collision with the CONFIRMED
    booking) and the subtotal below the zone minimum at the same time, the
    earlier cart-schedule guard surfaces ERR_CART_DOUBLE_BOOKED, not
    ERR_SUBTOTAL_BELOW_ZONE_MINIMUM.

    Design: Difficulty/priority_pair_validation_conflict/temporal_vs_fiscal_on_submit
    """
    ctx, booking = _setup_double_booking_and_low_subtotal(
        "2026-05-10T11:00:00Z", "2026-05-10T12:00:00Z")
    res = fx.submit_quote_raw(
        ctx, booking["id"],
        fx.current_cart_version(ctx["cart"]["id"]),
        fx.current_barista_version(ctx["barista"]["id"]))
    err = validate_error(res, ERR.ERR_CART_DOUBLE_BOOKED, expected_status=409)
    assert err["error_id"] != ERR.ERR_SUBTOTAL_BELOW_ZONE_MINIMUM.value


def test_submit_with_low_subtotal_alone_reports_zone_minimum(api):
    """PRD §3.5: "The guards run in a fixed order: booking state first — anything not
    in `QUOTE` is rejected with `ERR_INVALID_STATE` (HTTP 409) — then catalog
    liveness of the referenced package and cart (`ERR_PACKAGE_NOT_ACTIVE`,
    `ERR_CART_NOT_ACTIVE`), then the cart's schedule, then the add-on skill gate,
    then staffing presence, then the zone minimum, and finally the two
    stale-version checks."
    PRD §3.3: "Before any fee arithmetic runs, the zone's tier gate is evaluated: if
    the freshly computed `quoted_subtotal_cents` falls short of the zone's
    `min_booking_subtotal_cents`, the quote is rejected with
    `ERR_SUBTOTAL_BELOW_ZONE_MINIMUM` (HTTP 422)."

    The same low-subtotal booking on a window that clears the cart's buffered
    schedule sails past the temporal guard and is stopped by the zone minimum —
    proving both guards were armed in the paired scenario.

    Design: Difficulty/priority_pair_validation_conflict/temporal_vs_fiscal_on_submit
    """
    ctx, booking = _setup_double_booking_and_low_subtotal(
        "2026-05-12T11:00:00Z", "2026-05-12T12:00:00Z")
    res = fx.submit_quote_raw(
        ctx, booking["id"],
        fx.current_cart_version(ctx["cart"]["id"]),
        fx.current_barista_version(ctx["barista"]["id"]))
    validate_error(res, ERR.ERR_SUBTOTAL_BELOW_ZONE_MINIMUM, expected_status=422)


# ─── Corner/validations: add-on skill gate and staffing presence ──────────

def test_submit_with_latte_art_addon_but_uncertified_barista_rejected(api):
    """PRD §3.5: "The skill gate then inspects every attached add-on: for each add-on
    whose `requires_latte_art_cert` is true, at least one of the booking's
    assignments in `OFFERED`, `ACCEPTED`, or `CONFIRMED` must point to a
    `latte_art_certified` barista; for each add-on whose `requires_lead_barista`
    is true, at least one such assignment must point to a barista whose
    `skill_level` is `LEAD`. A shortfall on either front is rejected with
    `ERR_ADDON_SKILL_MISSING` (HTTP 422)."

    A booking carrying a latte-art add-on whose only assigned barista lacks the
    certification cannot be submitted.

    Design: Corner/validations/addon_skill_gate_latte_art_cert_required
    """
    ctx = fx.setup_base_catalog(
        package_kind="FLAT",
        barista_overrides={"skill_level": "JUNIOR", "latte_art_certified": False,
                           "hourly_rate_cents": 2000})
    addon = fx.create_addon(price_cents=8000, requires_latte_art_cert=True,
                            requires_lead_barista=False)
    booking = fx.create_quote_booking(ctx)
    fx.attach_addon(ctx, booking["id"], addon["id"])
    fx.offer_primary_assignment(ctx, booking["id"])

    res = fx.submit_quote_raw(
        ctx, booking["id"],
        fx.current_cart_version(ctx["cart"]["id"]),
        fx.current_barista_version(ctx["barista"]["id"]))
    validate_error(res, ERR.ERR_ADDON_SKILL_MISSING, expected_status=422)


def test_submit_without_any_assignment_rejected(api):
    """PRD §3.5: "Staffing presence requires at least one assignment in any
    non-terminal status, failing as `ERR_NO_BARISTA_ASSIGNED` (HTTP 422)."

    A booking with zero BaristaAssignment rows cannot be submitted.

    Design: Corner/validations/submit_with_no_barista_rejected
    """
    ctx = fx.setup_base_catalog(package_kind="FLAT")
    booking = fx.create_quote_booking(ctx)
    res = fx.submit_quote_raw(
        ctx, booking["id"],
        fx.current_cart_version(ctx["cart"]["id"]),
        fx.current_barista_version(ctx["barista"]["id"]))
    validate_error(res, ERR.ERR_NO_BARISTA_ASSIGNED, expected_status=422)


# ─── Corner/errors + cross_cutting_layers: optimistic concurrency ─────────

def test_submit_with_stale_cart_version_rejected(api):
    """PRD §2.7: "If the cart's current `version` has advanced beyond what the client
    observed — for instance because another booking was confirmed against the same
    cart, legitimately reducing that cart's effective availability — the submission
    is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    A client who captured the cart's version before another submission bumped it
    is rejected as stale.

    Design: Corner/errors/err_stale_version_on_submit
    """
    ctx = fx.setup_base_catalog(package_kind="FLAT")
    observed_cart_v = ctx["cart"]["version"]
    observed_barista_v = ctx["barista"]["version"]

    first = fx.create_quote_booking(ctx, event_start="2026-05-10T10:00:00Z",
                                    event_end="2026-05-10T12:00:00Z")
    fx.offer_primary_assignment(ctx, first["id"])
    fx.submit_quote(ctx, first["id"])  # bumps cart and barista versions

    second = fx.create_quote_booking(ctx, event_start="2026-05-12T10:00:00Z",
                                     event_end="2026-05-12T12:00:00Z")
    fx.offer_primary_assignment(ctx, second["id"])
    res = fx.submit_quote_raw(ctx, second["id"],
                              observed_cart_v, observed_barista_v)
    validate_error(res, ERR.ERR_STALE_VERSION, expected_status=412)


def test_submit_with_current_versions_succeeds_and_bumps_versions(api):
    """PRD §3.5: "The booking moves from `QUOTE` to `PENDING_DEPOSIT`, and three
    versions increment together: the booking's own `version`, the referenced
    cart's `version`, and the primary barista's `version`."

    A submission carrying the versions the client actually observed succeeds and
    advances the cart version (and the primary barista's) by exactly one.

    Design: Corner/cross_cutting_layers/occ_correct_version_succeeds_and_bumps
    """
    ctx = fx.setup_quote_with_assignment(package_kind="FLAT")
    cart_v0 = fx.current_cart_version(ctx["cart"]["id"])
    barista_v0 = fx.current_barista_version(ctx["barista"]["id"])
    booking_v0 = ctx["booking"]["version"]

    submitted = fx.submit_quote(ctx, ctx["booking"]["id"])
    assert submitted["status"] == "PENDING_DEPOSIT", submitted
    assert submitted["version"] == booking_v0 + 1, submitted

    cart_after = validate_success(api.get_cart(ctx["cart"]["id"], fx.OPS), 200)
    assert cart_after["version"] == cart_v0 + 1, cart_after
    barista_after = validate_success(api.get_barista(ctx["barista"]["id"], fx.OPS), 200)
    assert barista_after["version"] == barista_v0 + 1, barista_after
