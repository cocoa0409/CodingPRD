"""Add-on attachment referential rules and experience-slot aggregate capacity.

Covers difficulty queue A (resource temporal/aggregate overlap on a slot) and
corner queue B (add-on/experience attachment validations).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_host_headers, make_guest_headers,
    attach_add_on_payload,
)
import test_helpers.fixtures as fx


# ---------------------------------------------- corner: add-on not offered
def test_attach_foreign_addon_rejected(api):
    """PRD §3.5: "the add-on must belong to the booking's listing and be `ACTIVE`,
    else `ERR_ADDON_NOT_OFFERED` (HTTP 400)"

    Design: Corner/validations/attach_retired_or_foreign_addon_rejected
    """
    env = fx.setup_listed_listing(min_nights=1, cleaning_fee_cents=0,
                                  permit_type="CAMPING", rate_end="2026-08-01T00:00:00Z")
    # A second listing owned by the same host carries the foreign add-on.
    l2 = fx.create_listing(env["host"]["id"], site_type="CABIN", max_guests=4,
                           base_nightly_rate_cents=20000)
    foreign = fx.create_add_on(env["host"]["id"], l2["id"], name="Foreign Firewood",
                               category="AMENITY", pricing_unit="PER_STAY",
                               price_cents=1000)
    booking = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                                 "2026-07-10T00:00:00Z", "2026-07-12T00:00:00Z")
    resp = api.attach_add_on(booking["id"], attach_add_on_payload(foreign["id"]),
                             make_guest_headers(env["guest"]["id"]))
    validate_error(resp, "ERR_ADDON_NOT_OFFERED")


def test_experience_addon_missing_slot_rejected(api):
    """PRD §3.5: "an `EXPERIENCE` line must reference an `experience_slot_id` and
    an `AMENITY` line must not, else `ERR_EXPERIENCE_SLOT_REQUIRED` (HTTP 400)"

    Design: Corner/validations/experience_addon_missing_slot_rejected
    """
    env = fx.setup_listed_listing(site_type="TREEHOUSE", min_nights=1,
                                  cleaning_fee_cents=0, permit_type="SPECIAL_USE",
                                  rate_end="2026-08-01T00:00:00Z")
    exp = fx.create_add_on(env["host"]["id"], env["listing"]["id"], name="Kayak Tour",
                           category="EXPERIENCE", pricing_unit="PER_GUEST",
                           price_cents=4000)
    booking = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                                 "2026-07-10T00:00:00Z", "2026-07-12T00:00:00Z")
    resp = api.attach_add_on(booking["id"],
                             attach_add_on_payload(exp["id"], participant_count=2),
                             make_guest_headers(env["guest"]["id"]))
    validate_error(resp, "ERR_EXPERIENCE_SLOT_REQUIRED")


def test_experience_slot_date_outside_stay_rejected(api):
    """PRD §3.5: "the slot's `slot_date` must fall within the booking's stay
    interval from `check_in` up to but not including `check_out`, else
    `ERR_SLOT_DATE_OUT_OF_RANGE` (HTTP 400)"

    Design: Corner/validations/experience_slot_date_outside_stay_rejected
    """
    env = fx.setup_listed_listing(site_type="TREEHOUSE", min_nights=1,
                                  cleaning_fee_cents=0, permit_type="SPECIAL_USE",
                                  rate_end="2026-08-01T00:00:00Z")
    exp = fx.create_add_on(env["host"]["id"], env["listing"]["id"], name="Stargazing",
                           category="EXPERIENCE", pricing_unit="PER_GUEST",
                           price_cents=2000)
    slot = fx.create_slot(env["host"]["id"], exp["id"], "2026-07-20T00:00:00Z", 6)
    booking = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                                 "2026-07-10T00:00:00Z", "2026-07-12T00:00:00Z")
    resp = api.attach_add_on(
        booking["id"],
        attach_add_on_payload(exp["id"], experience_slot_id=slot["id"],
                              participant_count=2),
        make_guest_headers(env["guest"]["id"]),
    )
    validate_error(resp, "ERR_SLOT_DATE_OUT_OF_RANGE")


def test_experience_slot_belongs_to_other_addon_rejected(api):
    """PRD §3.5: "a referenced experience slot must belong to the referenced
    add-on, else `ERR_ADDON_LISTING_MISMATCH` (HTTP 400)"

    Design: Corner/entities/addon_slot_mismatch_covered_note
    """
    env = fx.setup_listed_listing(site_type="TREEHOUSE", min_nights=1,
                                  cleaning_fee_cents=0, permit_type="SPECIAL_USE",
                                  rate_end="2026-08-01T00:00:00Z")
    exp_x = fx.create_add_on(env["host"]["id"], env["listing"]["id"], name="Exp X",
                             category="EXPERIENCE", pricing_unit="PER_GUEST",
                             price_cents=3000)
    exp_y = fx.create_add_on(env["host"]["id"], env["listing"]["id"], name="Exp Y",
                             category="EXPERIENCE", pricing_unit="PER_GUEST",
                             price_cents=3000)
    y_slot = fx.create_slot(env["host"]["id"], exp_y["id"], "2026-07-11T00:00:00Z", 6)
    booking = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                                 "2026-07-10T00:00:00Z", "2026-07-13T00:00:00Z")
    resp = api.attach_add_on(
        booking["id"],
        attach_add_on_payload(exp_x["id"], experience_slot_id=y_slot["id"],
                              participant_count=2),
        make_guest_headers(env["guest"]["id"]),
    )
    validate_error(resp, "ERR_ADDON_LISTING_MISMATCH")


# ------------------- difficulty: resource_temporal_overlap (8b) slot capacity
def test_slot_reserved_participants_reflects_first_booking(api):
    """PRD §3.4: "Each slot tracks `reserved_participants`, which starts at 0 and
    is defined as the sum of `participant_count` across every add-on line that
    references this slot on bookings currently in `REQUESTED`, `CONFIRMED`,
    `CHECKED_IN`, or `COMPLETED` status."

    Design: Difficulty/resource_temporal_overlap/experience_slot_aggregate_capacity
    """
    env = fx.setup_listed_listing(site_type="TREEHOUSE", max_guests=6, min_nights=1,
                                  cleaning_fee_cents=0, cancellation_policy="FLEXIBLE",
                                  permit_type="SPECIAL_USE", rate_end="2026-08-01T00:00:00Z")
    hike = fx.create_add_on(env["host"]["id"], env["listing"]["id"], name="Guided Hike",
                            category="EXPERIENCE", pricing_unit="PER_GUEST",
                            price_cents=3000)
    slot = fx.create_slot(env["host"]["id"], hike["id"], "2026-07-11T00:00:00Z", 4)
    b1 = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                            "2026-07-10T00:00:00Z", "2026-07-13T00:00:00Z", guest_count=4)
    api.attach_add_on(
        b1["id"],
        attach_add_on_payload(hike["id"], experience_slot_id=slot["id"],
                              participant_count=3),
        make_guest_headers(env["guest"]["id"]),
    )
    slots = get_success_data(api.list_slots(hike["id"], make_host_headers(env["host"]["id"])))
    this_slot = next(s for s in slots if s["id"] == slot["id"])
    assert this_slot["reserved_participants"] == 3


def test_slot_capacity_exceeded_across_bookings_rejected(api):
    """PRD §3.5: "the slot's `reserved_participants` plus the new
    `participant_count` must not exceed the slot's `max_participants`, else
    `ERR_SLOT_CAPACITY_EXCEEDED` (HTTP 409)"

    Slot max 4; first booking reserves 3; a second booking's +2 would total 5 > 4.

    Design: Difficulty/resource_temporal_overlap/experience_slot_aggregate_capacity
    """
    env = fx.setup_listed_listing(site_type="TREEHOUSE", max_guests=6, min_nights=1,
                                  cleaning_fee_cents=0, cancellation_policy="FLEXIBLE",
                                  permit_type="SPECIAL_USE", rate_end="2026-08-01T00:00:00Z")
    hike = fx.create_add_on(env["host"]["id"], env["listing"]["id"], name="Guided Hike",
                            category="EXPERIENCE", pricing_unit="PER_GUEST",
                            price_cents=3000)
    slot = fx.create_slot(env["host"]["id"], hike["id"], "2026-07-11T00:00:00Z", 4)
    gh = make_guest_headers(env["guest"]["id"])
    b1 = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                            "2026-07-10T00:00:00Z", "2026-07-13T00:00:00Z", guest_count=4)
    api.attach_add_on(
        b1["id"],
        attach_add_on_payload(hike["id"], experience_slot_id=slot["id"],
                              participant_count=3), gh)
    b2 = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                            "2026-07-10T00:00:00Z", "2026-07-13T00:00:00Z", guest_count=4)
    resp = api.attach_add_on(
        b2["id"],
        attach_add_on_payload(hike["id"], experience_slot_id=slot["id"],
                              participant_count=2), gh)
    validate_error(resp, "ERR_SLOT_CAPACITY_EXCEEDED")
