"""Cross-cutting layers: optimistic concurrency, strike thresholds, counters.

The two version-guarded creates each replay a stale parent version, the vendor
strike ladder is walked across its threshold in both directions of the intake
gate, and the style's requirement counter is driven up and back down again.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_STALE_SESSION_VERSION,
    ERR_STALE_STYLE_VERSION,
    ERR_VENDOR_COORDINATION_HOLD,
)
from test_helpers.test_users import ADMIN, COORDINATOR, PRODUCER


# ─── Optimistic concurrency on the session ─────────────────────────────────

def _a_session_already_carrying_one_booking(api):
    """Return (session_id, stylist_id, version at creation, version after the hold)."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    station = fx.create_station(api)
    provider = fx.create_provider(api)
    photographer = fx.create_photographer(api, minimum_call_hours=0)
    stylist = fx.create_stylist(
        api, full_name="Kip Lund", day_rate_cents=50000, minimum_call_hours=0
    )
    session = fx.create_session(api, station["id"], provider["id"])
    first_version = session["version"]
    fx.create_booking(
        api,
        session["id"],
        photographer["id"],
        expected_session_version=first_version,
    )
    second_version = fx.session_version(api, session["id"])
    return session["id"], stylist["id"], first_version, second_version


def test_a_booking_replaying_the_pre_hold_session_version_is_refused(api):
    """Nothing forbids a second booking; only the version the producer held is stale.

    PRD: "A `POST /studio/talent-bookings` request — creating a `TalentBooking` — requires a non-optional `expected_session_version` field in the request body, carrying the client's last observed `version` of the target `ShootSession`. If that value does not equal the session's current `version`, the request is rejected with `ERR_STALE_SESSION_VERSION` (HTTP 412) and nothing is written."

    Design: Corner/cross-cutting complexity layers/booking_create_carries_the_session_version_it_was_planned_against
    """
    session_id, stylist_id, first_version, _ = _a_session_already_carrying_one_booking(
        api
    )

    validate_error(
        api.create_talent_booking(
            f.booking_payload(
                session_id, stylist_id, first_version, role_on_set="STYLIST"
            ),
            PRODUCER,
        ),
        ERR_STALE_SESSION_VERSION,
        412,
    )

    _, meta = validate_paginated(
        api.list_talent_bookings(
            PRODUCER, {"session_id": session_id, "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 1


def test_the_same_booking_body_with_the_refreshed_version_is_accepted(api):
    """The refreshed read lets the identical body through, and moves the version again.

    PRD: "A successful hold lands in `booking_state` `HELD` with `usage_rights_scope` and `release_document_id` both null, raises the booked person's `booked_minutes_today` by `booked_minutes` and increments that person's `version` by one, and increments the parent session's `version` by one."

    Design: Corner/cross-cutting complexity layers/booking_create_carries_the_session_version_it_was_planned_against
    """
    (
        session_id,
        stylist_id,
        first_version,
        second_version,
    ) = _a_session_already_carrying_one_booking(api)

    booking = validate_success(
        api.create_talent_booking(
            f.booking_payload(
                session_id, stylist_id, second_version, role_on_set="STYLIST"
            ),
            PRODUCER,
        ),
        201,
    )

    assert booking["booking_state"] == "HELD"
    assert second_version > first_version
    assert fx.session_version(api, session_id) > second_version


# ─── Optimistic concurrency on the style ───────────────────────────────────

def _a_style_already_carrying_one_front_item(api):
    """Return (style_id, version before the FRONT item, version after it)."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    vendor = fx.create_vendor(api)
    profile = fx.create_asset_profile(
        api, required_angles=["FRONT", "BACK"], min_on_model_shots=0
    )
    style = fx.create_style(api, vendor["id"], profile["id"])
    first_version = fx.style_version(api, style["id"])
    fx.create_shot_item(
        api,
        style["id"],
        asset_kind="STILL_ANGLE",
        angle_code="FRONT",
        estimated_minutes=30,
        expected_style_version=first_version,
    )
    second_version = fx.style_version(api, style["id"])
    return style["id"], first_version, second_version


def test_a_shot_item_replaying_the_pre_front_style_version_is_refused(api):
    """The BACK angle planned against the version the FRONT angle already moved is stale.

    PRD: "A `POST /studio/shot-list-items` request — creating a `ShotListItem` — requires a non-optional `expected_style_version` field carrying the client's last observed `version` of the target `Style`. If that value does not equal the style's current `version`, the request is rejected with `ERR_STALE_STYLE_VERSION` (HTTP 412) and nothing is written."

    Design: Corner/cross-cutting complexity layers/shot_list_item_create_carries_the_style_version_it_was_planned_against
    """
    style_id, first_version, _ = _a_style_already_carrying_one_front_item(api)

    validate_error(
        api.create_shot_list_item(
            f.shot_item_payload(
                style_id,
                first_version,
                asset_kind="STILL_ANGLE",
                angle_code="BACK",
                estimated_minutes=30,
            ),
            PRODUCER,
        ),
        ERR_STALE_STYLE_VERSION,
        412,
    )

    assert validate_success(api.get_style(style_id, PRODUCER))["required_item_count"] == 1


def test_the_same_shot_item_body_with_the_refreshed_version_is_accepted(api):
    """The second required angle lands planned and takes the counter to two.

    PRD: "A new item lands in `item_state` `PLANNED` with `session_id` null, `live_asset_count` 0 and `allocated_cost_cents` 0, and if its `required` flag is true the parent style's `required_item_count` rises by one; either way the style's `version` increments by one."

    Design: Corner/cross-cutting complexity layers/shot_list_item_create_carries_the_style_version_it_was_planned_against
    """
    style_id, _, second_version = _a_style_already_carrying_one_front_item(api)

    item = validate_success(
        api.create_shot_list_item(
            f.shot_item_payload(
                style_id,
                second_version,
                asset_kind="STILL_ANGLE",
                angle_code="BACK",
                estimated_minutes=30,
            ),
            PRODUCER,
        ),
        201,
    )

    assert item["item_state"] == "PLANNED"
    style = validate_success(api.get_style(style_id, PRODUCER))
    assert style["required_item_count"] == 2
    assert style["version"] > second_version


# ─── The vendor strike ladder and the intake gate ──────────────────────────

def _three_overdue_boxes_and_two_more_at_the_door(api):
    """Vendor NRTH on a one-day service level: three boxes parked, then four days pass."""
    fx.set_clock(api, "2026-08-01T08:00:00Z")
    vendor = fx.create_vendor(api, sample_sla_days=1)
    parked = []
    for index, barcode in enumerate(("SMP-1001", "SMP-1002", "SMP-1003"), start=1):
        sample = fx.create_sample(
            api,
            vendor["id"],
            barcode=barcode,
            declared_style_number=f"TOP100{index}",
        )
        fx.receive_sample(api, sample["id"])
        fx.custody_move(api, sample["id"], "RETURN_PENDING")
        parked.append(sample["id"])
    fx.set_clock(api, "2026-08-05T08:00:00Z")
    waiting = [
        fx.create_sample(
            api,
            vendor["id"],
            barcode=barcode,
            declared_style_number=style_number,
        )["id"]
        for barcode, style_number in (
            ("SMP-1004", "TOP1004"),
            ("SMP-1005", "TOP1005"),
        )
    ]
    return vendor["id"], parked, waiting


def test_a_one_day_service_level_dates_the_box_back_to_the_same_clock_time(api):
    """The due date is exact instant arithmetic on the receipt instant, not midnight.

    PRD: "On success the system stamps `received_at` from the logical clock, derives `due_return_at` by adding the vendor's `sample_sla_days` to `received_at` as exact instant arithmetic (so a 14-day service level received at 09:15 is due back at 09:15 fourteen days later, not at midnight), raises the vendor's `outstanding_sample_count` by one, and increments the vendor's `version` by one."

    Design: Corner/cross-cutting complexity layers/the_third_late_return_puts_the_vendor_on_coordination_hold
    """
    _, parked, _ = _three_overdue_boxes_and_two_more_at_the_door(api)

    sample = validate_success(api.get_sample(parked[0], COORDINATOR))

    assert sample["received_at"] == "2026-08-01T08:00:00.000Z"
    assert sample["due_return_at"] == "2026-08-02T08:00:00.000Z"


def test_a_three_day_overrun_rounds_up_to_three_whole_days_late(api):
    """259,200 seconds of overrun is exactly three whole days, and custody settles.

    PRD: "Custody moves `RETURN_PENDING → RETURNED`, `returned_at` is stamped from the logical clock, and lateness is computed: the overrun is the whole number of seconds from `due_return_at` to `returned_at`, and `return_days_late` is 0 whenever that overrun is zero or negative, and otherwise the overrun divided by the 86,400 seconds in a day and rounded **up** to the next whole day."

    Design: Corner/cross-cutting complexity layers/the_third_late_return_puts_the_vendor_on_coordination_hold
    """
    _, parked, _ = _three_overdue_boxes_and_two_more_at_the_door(api)

    returned = validate_success(
        api.return_sample(parked[0], COORDINATOR, {"condition_note": "creased"})
    )

    assert returned["custody_state"] == "RETURNED"
    assert returned["returned_at"] == "2026-08-05T08:00:00.000Z"
    assert returned["return_days_late"] == 3


def test_two_strikes_leave_the_vendor_one_below_the_hold_threshold(api):
    """The counter is cumulative, and intake is still open at two strikes.

    PRD: "The vendor's `outstanding_sample_count` then falls by one; if `return_days_late` is greater than 0 the vendor also takes a strike, raising `late_return_count` by one; and once `late_return_count` reaches 3 strikes the vendor's `coordination_hold` flips to true, which is what stops any further receipts from that vendor."

    Design: Corner/cross-cutting complexity layers/the_third_late_return_puts_the_vendor_on_coordination_hold
    """
    vendor_id, parked, waiting = _three_overdue_boxes_and_two_more_at_the_door(api)

    validate_success(
        api.return_sample(parked[0], COORDINATOR, {"condition_note": "creased"})
    )
    validate_success(api.return_sample(parked[1], COORDINATOR))

    vendor = validate_success(api.get_vendor(vendor_id, ADMIN))
    assert vendor["late_return_count"] == 2
    assert vendor["coordination_hold"] is False
    received = validate_success(api.receive_sample(waiting[0], COORDINATOR))
    assert received["custody_state"] == "RECEIVED"


def test_the_third_strike_flips_the_coordination_hold(api):
    """Three is the threshold, and the flag moves on the return that reaches it.

    PRD: "The vendor's `outstanding_sample_count` then falls by one; if `return_days_late` is greater than 0 the vendor also takes a strike, raising `late_return_count` by one; and once `late_return_count` reaches 3 strikes the vendor's `coordination_hold` flips to true, which is what stops any further receipts from that vendor."

    Design: Corner/cross-cutting complexity layers/the_third_late_return_puts_the_vendor_on_coordination_hold
    """
    vendor_id, parked, _ = _three_overdue_boxes_and_two_more_at_the_door(api)

    for sample_id in parked:
        validate_success(api.return_sample(sample_id, COORDINATOR))

    vendor = validate_success(api.get_vendor(vendor_id, ADMIN))
    assert vendor["late_return_count"] == 3
    assert vendor["coordination_hold"] is True


def test_intake_from_a_held_vendor_is_refused_and_the_box_stays_expected(api):
    """Once the hold is up the dock door shuts, and the refused box is untouched.

    PRD: "And the shipping vendor must not be on coordination hold — a vendor whose `coordination_hold` is true has its receipts refused outright with `ERR_VENDOR_COORDINATION_HOLD`."

    Design: Corner/cross-cutting complexity layers/the_third_late_return_puts_the_vendor_on_coordination_hold
    """
    _, parked, waiting = _three_overdue_boxes_and_two_more_at_the_door(api)
    for sample_id in parked:
        validate_success(api.return_sample(sample_id, COORDINATOR))

    validate_error(
        api.receive_sample(waiting[1], COORDINATOR),
        ERR_VENDOR_COORDINATION_HOLD,
        409,
    )

    refused = validate_success(api.get_sample(waiting[1], COORDINATOR))
    assert refused["custody_state"] == "EXPECTED"
    assert refused["received_at"] is None


# ─── The style requirement counter, up and back down ───────────────────────

def _a_style_owing_two_angles(api):
    """Style TOP1001 on a profile that asks for FRONT and BACK, no items yet."""
    fx.set_clock(api, "2026-08-03T08:00:00Z")
    vendor = fx.create_vendor(api)
    profile = fx.create_asset_profile(
        api, required_angles=["FRONT", "BACK"], min_on_model_shots=0
    )
    return fx.create_style(api, vendor["id"], profile["id"])["id"]


def _plan_the_two_required_angles(api, style_id):
    """Create the FRONT and BACK required items and return them in that order."""
    front = fx.create_shot_item(
        api,
        style_id,
        asset_kind="STILL_ANGLE",
        angle_code="FRONT",
        estimated_minutes=30,
    )
    back = fx.create_shot_item(
        api,
        style_id,
        asset_kind="STILL_ANGLE",
        angle_code="BACK",
        estimated_minutes=30,
    )
    return front, back


def test_the_requirement_counter_rises_once_per_required_item(api):
    """One required item, then two, tracked on the parent style after each create.

    PRD: "A new item lands in `item_state` `PLANNED` with `session_id` null, `live_asset_count` 0 and `allocated_cost_cents` 0, and if its `required` flag is true the parent style's `required_item_count` rises by one; either way the style's `version` increments by one."

    Design: Corner/cross-cutting complexity layers/style_requirement_counter_reconciles_after_create_and_after_waive
    """
    style_id = _a_style_owing_two_angles(api)

    fx.create_shot_item(
        api,
        style_id,
        asset_kind="STILL_ANGLE",
        angle_code="FRONT",
        estimated_minutes=30,
    )
    assert validate_success(api.get_style(style_id, PRODUCER))["required_item_count"] == 1

    fx.create_shot_item(
        api,
        style_id,
        asset_kind="STILL_ANGLE",
        angle_code="BACK",
        estimated_minutes=30,
    )
    assert validate_success(api.get_style(style_id, PRODUCER))["required_item_count"] == 2


def test_an_item_created_with_required_false_is_not_a_requirement(api):
    """The optional detail shot is planned like any other but is not counted.

    PRD: "A new item lands in `item_state` `PLANNED` with `session_id` null, `live_asset_count` 0 and `allocated_cost_cents` 0, and if its `required` flag is true the parent style's `required_item_count` rises by one; either way the style's `version` increments by one."

    Design: Corner/cross-cutting complexity layers/style_requirement_counter_reconciles_after_create_and_after_waive
    """
    style_id = _a_style_owing_two_angles(api)
    _plan_the_two_required_angles(api, style_id)

    optional = fx.create_shot_item(
        api,
        style_id,
        asset_kind="DETAIL",
        angle_code="FRONT",
        estimated_minutes=15,
        required=False,
    )

    assert optional["required"] is False
    assert optional["item_state"] == "PLANNED"
    assert validate_success(api.get_style(style_id, PRODUCER))["required_item_count"] == 2


def test_waiving_a_required_item_gives_the_counter_back(api):
    """The counter falls to one, the waived item is terminal, its sibling is untouched.

    PRD: "An item that is `PLANNED` or `BLOCKED` may be waived, optionally with a `reason`, moving it to the terminal `WAIVED` state so that it no longer holds up the style's content completion; an item that is `ASSIGNED`, `CAPTURED` or already `WAIVED` cannot be waived and the attempt is refused with `ERR_SHOT_ITEM_NOT_ASSIGNABLE`. When the waived item's `required` flag was true, the style's `required_item_count` falls by one, and the style's `version` increments by one."

    Design: Corner/cross-cutting complexity layers/style_requirement_counter_reconciles_after_create_and_after_waive
    """
    style_id = _a_style_owing_two_angles(api)
    front, back = _plan_the_two_required_angles(api, style_id)
    before = fx.style_version(api, style_id)

    waived = validate_success(
        api.waive_shot_list_item(
            back["id"], PRODUCER, {"reason": "back angle dropped from the brief"}
        )
    )

    assert waived["item_state"] == "WAIVED"
    style = validate_success(api.get_style(style_id, PRODUCER))
    assert style["required_item_count"] == 1
    assert style["version"] > before
    assert validate_success(api.get_shot_list_item(front["id"], PRODUCER))[
        "item_state"
    ] == "PLANNED"


def test_no_amount_of_shot_list_churn_moves_the_delivered_counter(api):
    """Nothing was shot, so the delivered tally has nothing to count.

    PRD: "A style's `delivered_asset_count` is the number of assets belonging to that style's shot-list items whose `asset_state` is `DELIVERED`."

    Design: Corner/cross-cutting complexity layers/style_requirement_counter_reconciles_after_create_and_after_waive
    """
    style_id = _a_style_owing_two_angles(api)
    _, back = _plan_the_two_required_angles(api, style_id)
    fx.create_shot_item(
        api,
        style_id,
        asset_kind="DETAIL",
        angle_code="FRONT",
        estimated_minutes=15,
        required=False,
    )
    fx.waive_item(api, back["id"], reason="back angle dropped from the brief")

    assert validate_success(api.get_style(style_id, PRODUCER))["delivered_asset_count"] == 0
