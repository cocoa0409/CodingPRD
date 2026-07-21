"""Lessons, coach scheduling, rentals, asset scheduling, and fees.

Difficulty instances: rental_parallel_fulfillment_payment_dimensions,
coach_lesson_buffer_overlap_semantics, rental_asset_adjacency_allowed_overlap_rejected,
rental_checkout_requires_linked_lesson_scheduled. Corner instances:
rental_fee_ceils_partial_day, rental_late_fee_and_deposit_capture,
lesson_end_before_start_returns_invalid_request, lesson_cancel_after_completed_terminal_lockdown.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
)
import test_helpers as th

SM = TEST_USERS["shop_manager_headers"]
SA = TEST_USERS["sales_associate_headers"]


# --------------------------------------------------------------------------- #
# Difficulty: rental parallel fulfillment × payment dimensions
# --------------------------------------------------------------------------- #
def _softtop_rental(api):
    prod, asset = th.create_rentable_product_and_asset(
        api,
        product_overrides={"sku": "SB-1", "name": "Softtop", "category": "SURFBOARD",
                           "unit_price_cents": 50000, "rental_day_rate_cents": 2000},
        asset_overrides={"asset_tag": "SB-A1"},
    )
    customer = th.create_customer(api, email="rent@x.com", full_name="Rent Rex")
    rental = th.create_rental(api, customer["id"], asset["id"],
                              start_at="2026-07-02T00:00:00Z", end_at="2026-07-05T00:00:00Z",
                              deposit_cents=5000)
    return prod, asset, customer, rental


def test_checkout_advances_fulfillment_only_payment_unchanged(api):
    """PRD §3.4: "On checkout the fulfillment moves from `RESERVED` to `PICKED_UP` while the payment dimension stays `DEPOSIT_HELD`, and the rental asset moves from `RESERVED` to `OUT`."

    Design: Difficulty/non_linear_state_machine/rental_parallel_fulfillment_payment_dimensions
    """
    prod, asset, customer, rental = _softtop_rental(api)
    assert rental["fulfillment_status"] == "RESERVED"
    assert rental["payment_status"] == "DEPOSIT_HELD"
    resp = api.checkout_rental(rental["id"], SA)
    data = validate_success(resp, expected_status=200)
    assert data["fulfillment_status"] == "PICKED_UP"
    assert data["payment_status"] == "DEPOSIT_HELD"


def test_ontime_return_refunds_deposit_independently(api):
    """PRD §3.4: "Fulfillment then moves from `PICKED_UP` to `RETURNED`. The payment dimension resolves independently: it becomes `DEPOSIT_CAPTURED` when the computed `late_fee_cents` is greater than zero, and `DEPOSIT_REFUNDED` when it is zero."

    Design: Difficulty/non_linear_state_machine/rental_parallel_fulfillment_payment_dimensions
    """
    prod, asset, customer, rental = _softtop_rental(api)
    validate_success(api.checkout_rental(rental["id"], SA))
    # Clock stays at default 2026-07-01 (before end 07-05) so the return is on time.
    resp = api.return_rental(rental["id"], SA)
    data = validate_success(resp, expected_status=200)
    assert data["fulfillment_status"] == "RETURNED"
    assert data["payment_status"] == "DEPOSIT_REFUNDED"
    assert data["late_fee_cents"] == 0


# --------------------------------------------------------------------------- #
# Difficulty: coach scheduling buffer / overlap semantics (15-min buffer)
# --------------------------------------------------------------------------- #
def _coach_with_lesson(api):
    coach = th.create_coach(api, name="Coach C", discipline="SURF")
    customer = th.create_customer(api, email="ov1@x.com", full_name="Over One")
    th.create_scheduled_lesson(api, coach["id"], customer["id"], discipline="SURF",
                               start_at="2026-07-08T10:00:00Z", end_at="2026-07-08T11:00:00Z")
    return coach, customer


def test_lesson_within_setup_buffer_rejected(api):
    """PRD §3.3: "A new lesson is refused with `ERR_COACH_UNAVAILABLE` when it collides with an existing `SCHEDULED` lesson on the same coach — that is, when the new lesson's window overlaps an existing one, or when the two are not separated by at least the setup buffer of 15 minutes (a new lesson whose `start_at` falls earlier than an existing lesson's `end_at` plus that 15-minute buffer, and whose interval collides with the buffered window, is rejected)."

    Design: Difficulty/resource_temporal_overlap/coach_lesson_buffer_overlap_semantics
    """
    coach, customer = _coach_with_lesson(api)
    # Prior ends 11:00; a lesson starting 11:10 is only 10 min later (< 15-min buffer).
    resp = api.create_lesson(
        {"coach_id": coach["id"], "customer_id": customer["id"], "discipline": "SURF",
         "start_at": "2026-07-08T11:10:00Z", "end_at": "2026-07-08T11:40:00Z"}, SA)
    validate_error(resp, ApiErrorId.ERR_COACH_UNAVAILABLE.value)


def test_lesson_exactly_at_buffer_edge_accepted(api):
    """PRD §3.3: "A new lesson is refused with `ERR_COACH_UNAVAILABLE` when it collides with an existing `SCHEDULED` lesson on the same coach — that is, when the new lesson's window overlaps an existing one, or when the two are not separated by at least the setup buffer of 15 minutes (a new lesson whose `start_at` falls earlier than an existing lesson's `end_at` plus that 15-minute buffer, and whose interval collides with the buffered window, is rejected)."

    Design: Difficulty/resource_temporal_overlap/coach_lesson_buffer_overlap_semantics
    """
    coach, customer = _coach_with_lesson(api)
    # Prior ends 11:00; a lesson starting exactly 11:15 (= end + 15-min buffer) is accepted.
    resp = api.create_lesson(
        {"coach_id": coach["id"], "customer_id": customer["id"], "discipline": "SURF",
         "start_at": "2026-07-08T11:15:00Z", "end_at": "2026-07-08T11:45:00Z"}, SA)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SCHEDULED"


# --------------------------------------------------------------------------- #
# Difficulty: rental asset adjacency allowed / overlap rejected (no buffer)
# --------------------------------------------------------------------------- #
def _asset_with_rental(api):
    prod, asset = th.create_rentable_product_and_asset(
        api,
        product_overrides={"sku": "SB-2", "name": "Longboard", "category": "SURFBOARD",
                           "unit_price_cents": 60000, "rental_day_rate_cents": 2500},
        asset_overrides={"asset_tag": "SB-2A"},
    )
    customer = th.create_customer(api, email="ov2@x.com", full_name="Over Two")
    th.create_rental(api, customer["id"], asset["id"],
                     start_at="2026-07-02T00:00:00Z", end_at="2026-07-04T00:00:00Z", deposit_cents=5000)
    return asset, customer


def test_overlapping_rental_on_asset_rejected(api):
    """PRD §3.4: "A new rental is refused with `ERR_ASSET_UNAVAILABLE` if its window overlaps an existing non-terminal rental — one whose fulfillment is `RESERVED` or `PICKED_UP` — on the same asset."

    Design: Difficulty/resource_temporal_overlap/rental_asset_adjacency_allowed_overlap_rejected
    """
    asset, customer = _asset_with_rental(api)
    # Window [07-03, 07-05) overlaps the existing [07-02, 07-04).
    resp = api.create_rental(
        {"customer_id": customer["id"], "rental_asset_id": asset["id"],
         "start_at": "2026-07-03T00:00:00Z", "end_at": "2026-07-05T00:00:00Z", "deposit_cents": 5000}, SA)
    validate_error(resp, ApiErrorId.ERR_ASSET_UNAVAILABLE.value)


def test_adjacent_rental_on_asset_accepted(api):
    """PRD §3.4: "Overlap uses the same half-open convention `[start_at, end_at)`, so exact adjacency is permitted: a new rental whose `start_at` equals an existing rental's `end_at` is accepted, and no separation buffer is applied between rentals on an asset."

    Design: Difficulty/resource_temporal_overlap/rental_asset_adjacency_allowed_overlap_rejected
    """
    asset, customer = _asset_with_rental(api)
    # Window [07-04, 07-06) starts exactly at the prior rental's end 07-04.
    resp = api.create_rental(
        {"customer_id": customer["id"], "rental_asset_id": asset["id"],
         "start_at": "2026-07-04T00:00:00Z", "end_at": "2026-07-06T00:00:00Z", "deposit_cents": 5000}, SA)
    data = validate_success(resp, expected_status=201)
    assert data["fulfillment_status"] == "RESERVED"


# --------------------------------------------------------------------------- #
# Difficulty: rental checkout requires linked lesson SCHEDULED
# --------------------------------------------------------------------------- #
def test_checkout_with_completed_linked_lesson_rejected(api):
    """PRD §3.4: "Additionally, if the rental carries a `lesson_id`, the linked lesson must currently be `SCHEDULED`; if it is not, checkout is refused with `ERR_LESSON_NOT_SCHEDULED`."

    Design: Difficulty/cross_entity_state_dependency/rental_checkout_requires_linked_lesson_scheduled
    """
    coach = th.create_coach(api, name="Coach B", discipline="SKATE")
    customer = th.create_customer(api, email="ce1@x.com", full_name="Cross One")
    lesson = th.create_scheduled_lesson(api, coach["id"], customer["id"], discipline="SKATE",
                                        start_at="2026-07-06T10:00:00Z", end_at="2026-07-06T11:00:00Z")
    prod, asset = th.create_rentable_product_and_asset(
        api,
        product_overrides={"sku": "DECK-R", "name": "Deck R", "category": "COMPLETE",
                           "unit_price_cents": 12000, "rental_day_rate_cents": 1000},
        asset_overrides={"asset_tag": "DECK-RA1"},
    )
    rental = th.create_rental(api, customer["id"], asset["id"], lesson_id=lesson["id"],
                              start_at="2026-07-06T00:00:00Z", end_at="2026-07-07T00:00:00Z", deposit_cents=2000)
    validate_success(api.complete_lesson(lesson["id"], {"outcome": "COMPLETED"}, SA))
    resp = api.checkout_rental(rental["id"], SA)
    validate_error(resp, ApiErrorId.ERR_LESSON_NOT_SCHEDULED.value)
    reread = validate_success(api.get_rental(rental["id"], SA))
    assert reread["fulfillment_status"] == "RESERVED"


def test_checkout_with_scheduled_linked_lesson_succeeds(api):
    """PRD §3.4: "Additionally, if the rental carries a `lesson_id`, the linked lesson must currently be `SCHEDULED`; if it is not, checkout is refused with `ERR_LESSON_NOT_SCHEDULED`."

    Design: Difficulty/cross_entity_state_dependency/rental_checkout_requires_linked_lesson_scheduled
    """
    coach = th.create_coach(api, name="Coach B2", discipline="SKATE")
    customer = th.create_customer(api, email="ce1b@x.com", full_name="Cross Two")
    lesson = th.create_scheduled_lesson(api, coach["id"], customer["id"], discipline="SKATE",
                                        start_at="2026-07-06T10:00:00Z", end_at="2026-07-06T11:00:00Z")
    prod, asset = th.create_rentable_product_and_asset(
        api,
        product_overrides={"sku": "DECK-R2", "name": "Deck R2", "category": "COMPLETE",
                           "unit_price_cents": 12000, "rental_day_rate_cents": 1000},
        asset_overrides={"asset_tag": "DECK-RA2"},
    )
    rental = th.create_rental(api, customer["id"], asset["id"], lesson_id=lesson["id"],
                              start_at="2026-07-06T00:00:00Z", end_at="2026-07-07T00:00:00Z", deposit_cents=2000)
    resp = api.checkout_rental(rental["id"], SA)
    data = validate_success(resp, expected_status=200)
    assert data["fulfillment_status"] == "PICKED_UP"


# --------------------------------------------------------------------------- #
# Corner: rental fee ceils partial day
# --------------------------------------------------------------------------- #
def test_rental_fee_ceils_partial_day(api):
    """PRD §3.4: "The day count is obtained by taking the elapsed time from `start_at` to `end_at` in seconds, dividing by 86400, and rounding up to the next whole day, so any partial day counts as a full day; the resulting `rental_fee_cents` is stored at creation."

    Design: Corner/calculations/rental_fee_ceils_partial_day
    """
    prod, asset = th.create_rentable_product_and_asset(
        api,
        product_overrides={"sku": "SB-3", "name": "Foamie", "category": "SURFBOARD",
                           "unit_price_cents": 40000, "rental_day_rate_cents": 2000},
        asset_overrides={"asset_tag": "SB-3A"},
    )
    customer = th.create_customer(api, email="rf@x.com", full_name="Ren Fee")
    # 07-02T00 -> 07-03T06 is 1.25 days -> ceils to 2 days * 2000 = 4000.
    resp = api.create_rental(
        {"customer_id": customer["id"], "rental_asset_id": asset["id"],
         "start_at": "2026-07-02T00:00:00Z", "end_at": "2026-07-03T06:00:00Z", "deposit_cents": 4000}, SA)
    data = validate_success(resp, expected_status=201)
    assert data["rental_fee_cents"] == 4000


# --------------------------------------------------------------------------- #
# Corner: late fee + deposit capture (clock-driven)
# --------------------------------------------------------------------------- #
def test_late_return_computes_late_fee_and_captures_deposit(api):
    """PRD §3.4: "otherwise the number of late days is the elapsed time from `end_at` to `returned_at` in seconds divided by 86400 and rounded up to a whole day, multiplied by a late fee of 1000 cents per day."
    PRD §3.4: "The payment dimension resolves independently: it becomes `DEPOSIT_CAPTURED` when the computed `late_fee_cents` is greater than zero, and `DEPOSIT_REFUNDED` when it is zero."

    Design: Corner/calculations/rental_late_fee_and_deposit_capture
    """
    prod, asset = th.create_rentable_product_and_asset(
        api,
        product_overrides={"sku": "SB-4", "name": "Fish", "category": "SURFBOARD",
                           "unit_price_cents": 45000, "rental_day_rate_cents": 1500},
        asset_overrides={"asset_tag": "SB-4A"},
    )
    customer = th.create_customer(api, email="lf@x.com", full_name="Late Fee")
    rental = th.create_rental(api, customer["id"], asset["id"],
                              start_at="2026-07-02T00:00:00Z", end_at="2026-07-03T00:00:00Z", deposit_cents=5000)
    validate_success(api.checkout_rental(rental["id"], SA))
    th.set_clock(api, "2026-07-05T00:00:00Z")  # 2 days after end 07-03
    resp = api.return_rental(rental["id"], SA)
    data = validate_success(resp, expected_status=200)
    assert data["late_fee_cents"] == 2000
    assert data["payment_status"] == "DEPOSIT_CAPTURED"


# --------------------------------------------------------------------------- #
# Corner: lesson end <= start -> validation
# --------------------------------------------------------------------------- #
def test_lesson_end_before_start_returns_validation(api):
    """PRD §3.3: "the `start_at` and `end_at` bounding the session (ISO 8601 UTC, with `end_at` required to be strictly after `start_at`)."
    PRD §2.10: "an `end_at` that is not strictly greater than `start_at` ... is always reported as `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/validations/lesson_end_before_start_returns_invalid_request
    """
    coach = th.create_coach(api, name="Coach E", discipline="SKATE")
    customer = th.create_customer(api, email="tr@x.com", full_name="Time Range")
    resp = api.create_lesson(
        {"coach_id": coach["id"], "customer_id": customer["id"], "discipline": "SKATE",
         "start_at": "2026-07-08T11:00:00Z", "end_at": "2026-07-08T10:00:00Z"}, SA)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# --------------------------------------------------------------------------- #
# Corner: cancel a COMPLETED lesson -> invalid state (terminal lockdown)
# --------------------------------------------------------------------------- #
def test_cancel_completed_lesson_returns_invalid_state(api):
    """PRD §3.3: "Any of these three closures requires the lesson to currently be `SCHEDULED`; attempting them from any other state is rejected with `ERR_LESSON_INVALID_STATE`."

    Design: Corner/state_machines/lesson_cancel_after_completed_terminal_lockdown
    """
    coach = th.create_coach(api, name="Coach D", discipline="SURF")
    customer = th.create_customer(api, email="sm2@x.com", full_name="SM Two")
    lesson = th.create_scheduled_lesson(api, coach["id"], customer["id"], discipline="SURF",
                                        start_at="2026-07-09T10:00:00Z", end_at="2026-07-09T11:00:00Z")
    validate_success(api.complete_lesson(lesson["id"], {"outcome": "COMPLETED"}, SA))
    resp = api.cancel_lesson(lesson["id"], SA)
    validate_error(resp, ApiErrorId.ERR_LESSON_INVALID_STATE.value)
    reread = validate_success(api.get_lesson(lesson["id"], SA))
    assert reread["status"] == "COMPLETED"
