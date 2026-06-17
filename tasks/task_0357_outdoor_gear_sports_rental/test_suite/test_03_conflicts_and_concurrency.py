"""Booking conflicts (window overlap, lesson-slot capacity), validation precedence,
unit availability, and optimistic concurrency on reservation create / dispute.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId, TEST_USERS, make_renter_headers,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["shop_admin_headers"]
AGENT = TEST_USERS["rental_agent_headers"]


# ===========================================================================
# Queue A — resource_temporal_overlap
# ===========================================================================

def test_lesson_slot_capacity_closed_interval_touch_collides(api):
    """PRD §3.4: "A lesson slot is treated as a closed interval — both `slot_start_at`
    and `slot_end_at` are inclusive boundaries."
    PRD §3.4: "**Slot capacity** is enforced by counting the existing non-cancelled
    `ReservationAddOn` lines for the same `addon_id` whose closed slot interval
    intersects the requested closed interval; because the interval is closed, two slots
    that merely touch at an endpoint do intersect. If admitting the new booking would
    push that occupancy plus one above the add-on's `capacity_per_slot`, the attach is
    rejected with `ERR_SLOT_FULL`."

    Design: Difficulty/resource_temporal_overlap/lesson_slot_capacity_closed_interval_touch_collides
    """
    fx.set_clock("2026-05-15T07:00:00Z")
    gt = fx.create_gear_type(category="SKI", name="Lesson Ski", size_label="160cm")
    rc = fx.create_rate_card(gt["id"])
    unit1 = fx.create_gear_unit(gt["id"], rc["id"], asset_tag="SKI-6")
    unit2 = fx.create_gear_unit(gt["id"], rc["id"], asset_tag="SKI-7")
    ao = fx.create_addon(kind="LESSON", category="SKI", name="Private Ski Lesson",
                         price_cents=5000, capacity_per_slot=1)
    cust = fx.create_customer(actor=AGENT, email="lou@x.com", skill_level="INTERMEDIATE")

    res1 = fx.create_reservation(cust["id"], unit1["id"], unit1["version"],
                                 "2026-05-15T10:00:00Z", "2026-05-15T12:00:00Z", actor=AGENT)
    get_success_data(api.attach_addon(res1["id"], {
        "addon_id": ao["id"], "slot_start_at": "2026-05-15T10:00:00Z",
        "slot_end_at": "2026-05-15T11:00:00Z"}, AGENT))

    res2 = fx.create_reservation(cust["id"], unit2["id"], unit2["version"],
                                 "2026-05-15T11:00:00Z", "2026-05-15T13:00:00Z", actor=AGENT)
    # Requested slot [11:00,12:00] touches the held [10:00,11:00] at 11:00 -> collides.
    resp = api.attach_addon(res2["id"], {
        "addon_id": ao["id"], "slot_start_at": "2026-05-15T11:00:00Z",
        "slot_end_at": "2026-05-15T12:00:00Z"}, AGENT)
    validate_error(resp, ApiErrorId.ERR_SLOT_FULL.value)


# ===========================================================================
# Queue A — priority_pair_validation_conflict
# ===========================================================================

def test_settle_disputed_assessment_returns_assessment_disputed(api):
    """PRD §3.8: "It is gated on the assessment having `status` `ASSESSED` and the unit
    being in `INSPECTING`; if the assessment is `DISPUTED`, settlement is refused with
    `ERR_ASSESSMENT_DISPUTED`."
    PRD §2.9: "Twelfth, the dispute-blocks-settlement rule (`ERR_ASSESSMENT_DISPUTED`,
    409). A failing check at any tier surfaces its own error and masks all
    lower-priority checks."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_settle_disputed_before_anything_else
    """
    s = fx.setup_disputed_assessment(category="SKI", clock="2026-05-07T08:00:00Z",
                                     pickup_at="2026-05-07T08:00:00Z",
                                     due_at="2026-05-07T10:00:00Z",
                                     return_clock="2026-05-07T09:30:00Z",
                                     checkin_rating="DAMAGED", asset_tag="SKI-3")
    # Reservation is RETURNED (valid state for settle) but assessment is DISPUTED.
    resp = api.settle_reservation(s["reservation"]["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_DISPUTED.value)


def test_confirm_beginner_without_lesson_returns_lesson_required(api):
    """PRD §3.5: "If the gear type sets `requires_lesson_for_beginner` and the renter's
    `skill_level` is `BEGINNER`, the reservation must already carry at least one
    `LESSON` add-on line; absent it, confirmation is rejected with
    `ERR_LESSON_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_lesson_required_before_availability_check
    """
    fx.set_clock("2026-05-08T08:00:00Z")
    gt = fx.create_gear_type(category="SKI", name="Beginner Pkg", size_label="150cm",
                             requires_lesson_for_beginner=True)
    rc = fx.create_rate_card(gt["id"])
    unit = fx.create_gear_unit(gt["id"], rc["id"], asset_tag="SKI-4")
    cust = fx.create_customer(actor="RENTER", full_name="Fay Lund", email="fay@x.com",
                              skill_level="BEGINNER")
    res = fx.create_reservation(cust["id"], unit["id"], unit["version"],
                                "2026-05-08T08:00:00Z", "2026-05-08T10:00:00Z", actor="RENTER")
    resp = api.confirm_reservation(res["id"], make_renter_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_LESSON_REQUIRED.value)


# ===========================================================================
# Queue B — validations (corner)
# ===========================================================================

def test_reserve_pickup_after_due_returns_validation(api):
    """PRD §2.9: "first, payload well-formedness — required fields present, enums and
    types valid, every cents value non-negative, and on a reservation `pickup_at`
    strictly earlier than `due_at` — failing which the request is rejected with
    `ERR_VALIDATION` at HTTP 400."

    Design: Corner/validations/reserve_pickup_after_due_returns_validation
    """
    fx.set_clock("2026-06-13T08:00:00Z")
    s = fx.setup_catalog(category="KAYAK", asset_tag="INV-1",
                         customer_overrides={"email": "dot@x.com", "skill_level": "EXPERT"})
    resp = api.create_reservation(
        {"customer_id": s["customer"]["id"], "gear_unit_id": s["gear_unit"]["id"],
         "pickup_at": "2026-06-13T12:00:00Z", "due_at": "2026-06-13T10:00:00Z",
         "expected_gear_unit_version": s["gear_unit"]["version"]}, AGENT)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_reserve_non_available_unit_returns_unit_not_available(api):
    """PRD §3.3: "A reservation may only be created when the unit's `availability` reads
    `AVAILABLE`, and when the unit's gear type and rate card are both `active`;
    otherwise the create is rejected with `ERR_UNIT_NOT_AVAILABLE`."

    Design: Corner/validations/reserve_non_available_unit_returns_unit_not_available
    """
    fx.set_clock("2026-06-14T08:00:00Z")
    s = fx.setup_catalog(category="KAYAK", asset_tag="UNA-1",
                         customer_overrides={"email": "eve@x.com", "skill_level": "EXPERT"})
    cust_id = s["customer"]["id"]
    gu_id = s["gear_unit"]["id"]
    # First reservation moves the unit to RESERVED.
    fx.create_reservation(cust_id, gu_id, s["gear_unit"]["version"],
                          "2026-06-14T08:00:00Z", "2026-06-14T10:00:00Z", actor=AGENT)
    unit_now = validate_success(api.get_gear_unit(gu_id, AGENT))
    # Second reservation on a NON-overlapping window: blocked by availability, not overlap.
    resp = api.create_reservation(
        {"customer_id": cust_id, "gear_unit_id": gu_id,
         "pickup_at": "2026-06-14T18:00:00Z", "due_at": "2026-06-14T20:00:00Z",
         "expected_gear_unit_version": unit_now["version"]}, AGENT)
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_AVAILABLE.value)


# ===========================================================================
# Queue B — errors / cross_cutting (OCC)
# ===========================================================================

def test_occ_stale_unit_version_rejected(api):
    """PRD §2.8: "Creating a reservation targets a `GearUnit` as its concurrency
    parent: the create request must carry `expected_gear_unit_version`, a non-optional
    field whose value is the `version` of the gear unit the client last observed. If
    that value does not equal the gear unit's current `version` ... the create is
    rejected with `ERR_STALE_VERSION` at HTTP 412"

    Design: Corner/errors/occ_stale_unit_version_rejected
    """
    fx.set_clock("2026-06-17T08:00:00Z")
    s = fx.setup_catalog(category="KAYAK", asset_tag="OCC-1",
                         customer_overrides={"email": "hua@x.com", "skill_level": "EXPERT"})
    cust_id = s["customer"]["id"]
    gu_id = s["gear_unit"]["id"]
    stale_version = s["gear_unit"]["version"]
    # First reservation then cancel advances the unit's version past stale_version.
    res1 = fx.create_reservation(cust_id, gu_id, stale_version,
                                 "2026-06-17T08:00:00Z", "2026-06-17T10:00:00Z", actor=AGENT)
    fx.cancel_reservation(res1["id"], actor=AGENT)
    # Replay the pre-advance version.
    resp = api.create_reservation(
        {"customer_id": cust_id, "gear_unit_id": gu_id,
         "pickup_at": "2026-06-18T08:00:00Z", "due_at": "2026-06-18T10:00:00Z",
         "expected_gear_unit_version": stale_version}, AGENT)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_gear_unit_version_increments_on_reservation_create(api):
    """PRD §3.3: "the unit transitions from `AVAILABLE` to `RESERVED`, with its
    `active_reservation_id` set to the new reservation and its `version` incremented."
    PRD §2.4: "The `version` starts at 1 when the resource is created and increases by
    exactly 1 on every mutation"

    Design: Corner/cross_cutting_complexity_layers/gear_unit_version_increments_on_each_reservation_create
    """
    fx.set_clock("2026-06-21T08:00:00Z")
    s = fx.setup_catalog(category="KAYAK", asset_tag="VER-1",
                         customer_overrides={"email": "jay@x.com", "skill_level": "EXPERT"})
    assert s["gear_unit"]["version"] == 1
    fx.create_reservation(s["customer"]["id"], s["gear_unit"]["id"], s["gear_unit"]["version"],
                          "2026-06-21T08:00:00Z", "2026-06-21T10:00:00Z", actor=AGENT)
    unit = validate_success(api.get_gear_unit(s["gear_unit"]["id"], AGENT))
    assert unit["version"] == 2


def test_dispute_stale_assessment_version_rejected(api):
    """PRD §2.8: "Disputing a damage assessment targets the `DamageAssessment` as its
    concurrency parent: the dispute request must carry `expected_damage_assessment_version`
    matching that assessment's current `version`, and a mismatch ... is rejected with
    `ERR_STALE_VERSION` at HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/dispute_stale_assessment_version_rejected
    """
    s = fx.setup_returned_reservation(category="SKI", clock="2026-06-22T08:00:00Z",
                                      pickup_at="2026-06-22T08:00:00Z",
                                      due_at="2026-06-22T10:00:00Z",
                                      return_clock="2026-06-22T09:30:00Z",
                                      checkin_rating="DAMAGED",
                                      reservation_overrides={"damage_waiver_opted": False},
                                      customer_overrides={"email": "kit@x.com", "skill_level": "EXPERT"},
                                      asset_tag="DAS-1")
    assessment = fx.get_assessment_for_reservation(s["reservation"]["id"])
    cust_id = s["customer"]["id"]
    # Send current version minus 1 (stale).
    resp = api.dispute_damage_assessment(
        assessment["id"], {"expected_damage_assessment_version": assessment["version"] - 1},
        make_renter_headers(cust_id))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
