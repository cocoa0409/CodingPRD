"""Validation precedence, boundary precision, cross-entity state dependency, and chair /
sanitation temporal overlap tests.

Design queue A (Difficulty): priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency, resource_temporal_overlap.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error, ApiErrorId,
    TEST_USERS, make_lash_tech_headers,
    create_appointment_payload, create_patch_test_payload,
)
from test_helpers.fixtures import (
    SM, FD, set_clock, create_studio, create_service_type, create_plan, create_tech,
    create_member, create_membership, sanitize_tech, get_membership, get_appointment,
)


# ──────────────────────────────────────────────────────────────────────────
# priority_pair_validation_conflict / patch_test_safety_before_fill_temporal
# ──────────────────────────────────────────────────────────────────────────
def test_patch_test_safety_wins_over_fill_too_soon():
    """PRD §2.10: "the patch-test safety check seventh (`ERR_NO_VALID_PATCH_TEST`, HTTP 422);
    the fill-timing window eighth (`ERR_FILL_REQUIRES_PRIOR_FULL_SET`, `ERR_FILL_TOO_SOON`, or
    `ERR_FILL_WINDOW_EXPIRED`, all HTTP 422)".

    Design: Difficulty/priority_pair_validation_conflict/patch_test_safety_before_fill_temporal
    """
    studio = create_studio(name="Glow")
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    fill = create_service_type(studio["id"], code="FILL", name="Fill", duration_minutes=60,
                              base_price_cents=6000, credit_cost=1, category="STANDARD",
                              requires_patch_test=True)
    tech = create_tech(studio["id"], full_name="Mara", skill_level=3, station_number=1)
    sanitize_tech(tech["id"], "2026-06-03T00:00:00Z")
    member = create_member(studio["id"])
    # Build a COMPLETED FULL_SET anchor at 2026-06-01 (member has NO patch test).
    set_clock("2026-06-01T09:00:00Z")
    full_appt = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-01T10:00:00Z"), FD))
    set_clock("2026-06-01T12:30:00Z")
    get_success_data(api_client.complete_appointment(full_appt["id"],
                                                     make_lash_tech_headers(full_appt["lash_tech_id"])))
    set_clock("2026-06-02T09:00:00Z")
    # FILL at 2026-06-03 is gap 2 days (< 5, too soon) AND requires a patch test (none exists).
    resp = api_client.create_appointment(
        create_appointment_payload(member["id"], fill["id"], "2026-06-03T10:00:00Z"), FD)
    validate_error(resp, ApiErrorId.ERR_NO_VALID_PATCH_TEST)


def test_fill_too_soon_surfaces_once_patch_test_gate_passes():
    """PRD §2.10: "the patch-test safety check seventh (`ERR_NO_VALID_PATCH_TEST`, HTTP 422);
    the fill-timing window eighth (`ERR_FILL_REQUIRES_PRIOR_FULL_SET`, `ERR_FILL_TOO_SOON`, or
    `ERR_FILL_WINDOW_EXPIRED`, all HTTP 422)".
    PRD §3.6: "A gap of fewer than 5 days is too soon and is rejected with
    `ERR_FILL_TOO_SOON`".

    Design: Difficulty/priority_pair_validation_conflict/patch_test_safety_before_fill_temporal
    """
    studio = create_studio(name="Glow")
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    fill = create_service_type(studio["id"], code="FILL", name="Fill", duration_minutes=60,
                              base_price_cents=6000, credit_cost=1, category="STANDARD",
                              requires_patch_test=True)
    tech = create_tech(studio["id"], full_name="Mara", skill_level=3, station_number=1)
    sanitize_tech(tech["id"], "2026-06-03T00:00:00Z")
    member = create_member(studio["id"])
    # Give a VALID patch test so the pri-7 gate passes; pri-8 (too soon) must then surface.
    get_success_data(api_client.create_patch_test(
        create_patch_test_payload(member["id"], "2026-06-01T00:00:00Z", consent_signed=True), FD))
    set_clock("2026-06-01T09:00:00Z")
    full_appt = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-01T10:00:00Z"), FD))
    set_clock("2026-06-01T12:30:00Z")
    get_success_data(api_client.complete_appointment(full_appt["id"],
                                                     make_lash_tech_headers(full_appt["lash_tech_id"])))
    set_clock("2026-06-02T09:00:00Z")
    # gap from anchor 2026-06-01T10:00 to 2026-06-03T10:00 is 2 days (< 5).
    resp = api_client.create_appointment(
        create_appointment_payload(member["id"], fill["id"], "2026-06-03T10:00:00Z"), FD)
    validate_error(resp, ApiErrorId.ERR_FILL_TOO_SOON)


# ──────────────────────────────────────────────────────────────────────────
# priority_pair_validation_conflict / membership_state_before_insufficient_credits
# ──────────────────────────────────────────────────────────────────────────
def test_membership_not_bookable_wins_over_insufficient_credits():
    """PRD §2.10: "the membership-bookable state eleventh (`ERR_MEMBERSHIP_NOT_BOOKABLE`, HTTP
    409); the optimistic-concurrency version check twelfth (`ERR_STALE_MEMBERSHIP_VERSION`,
    HTTP 412); the sufficient-credits check thirteenth (`ERR_INSUFFICIENT_CREDITS`, HTTP 402)".

    Design: Difficulty/priority_pair_validation_conflict/membership_state_before_insufficient_credits
    """
    studio = create_studio(name="Glow")
    plan = create_plan(studio["id"], tier="ESSENTIAL", monthly_credit_allotment=4, monthly_fee_cents=6900)
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    tech = create_tech(studio["id"], full_name="Mara", skill_level=3, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T09:00:00Z")
    member = create_member(studio["id"])
    ms = create_membership(member["id"], plan["id"], initial_credits=0)
    ms_after_flag = validate_success(api_client.flag_past_due(ms["id"], SM))
    set_clock("2026-06-10T10:00:00Z")
    # PAST_DUE (state) + 0 credits (fiscal): state wins.
    resp = api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T20:00:00Z",
                                   pay_with_credits=True, membership_id=ms["id"],
                                   expected_membership_version=ms_after_flag["version"]), FD)
    validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_BOOKABLE)


def test_insufficient_credits_surfaces_when_membership_active():
    """PRD §2.10: "the sufficient-credits check thirteenth (`ERR_INSUFFICIENT_CREDITS`, HTTP
    402)".
    PRD §3.5: "if the available balance is less than the required amount the booking is
    rejected with `ERR_INSUFFICIENT_CREDITS` (HTTP 402) and nothing is appended".

    Design: Difficulty/priority_pair_validation_conflict/membership_state_before_insufficient_credits
    """
    studio = create_studio(name="Glow")
    plan = create_plan(studio["id"], tier="ESSENTIAL", monthly_credit_allotment=4, monthly_fee_cents=6900)
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    tech = create_tech(studio["id"], full_name="Mara", skill_level=3, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T09:00:00Z")
    member = create_member(studio["id"])
    # ACTIVE membership (pri-11 passes) with 0 credits (< cost 4) -> only the fiscal gate fails.
    ms = create_membership(member["id"], plan["id"], initial_credits=0)
    set_clock("2026-06-10T10:00:00Z")
    resp = api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T20:00:00Z",
                                   pay_with_credits=True, membership_id=ms["id"],
                                   expected_membership_version=ms["version"]), FD)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDITS)


# ──────────────────────────────────────────────────────────────────────────
# boundary_precision_check / fill_gap_exactly_five_days_passes
# ──────────────────────────────────────────────────────────────────────────
def _setup_fill_anchor(fill_sanitize_at):
    """Member with COMPLETED FULL_SET anchor at 2026-06-01T10:00:00Z and a sanitized tech
    covering the FILL date. Returns (member, fill_service_id)."""
    studio = create_studio(name="Glow")
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    fill = create_service_type(studio["id"], code="FILL", name="Fill", duration_minutes=60,
                              base_price_cents=6000, credit_cost=1, category="STANDARD",
                              requires_patch_test=False)
    tech = create_tech(studio["id"], full_name="Mara", skill_level=3, station_number=1)
    sanitize_tech(tech["id"], "2026-06-01T09:00:00Z")
    sanitize_tech(tech["id"], fill_sanitize_at)
    member = create_member(studio["id"])
    set_clock("2026-06-01T09:00:00Z")
    full_appt = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-01T10:00:00Z"), FD))
    set_clock("2026-06-01T12:30:00Z")
    get_success_data(api_client.complete_appointment(full_appt["id"],
                                                     make_lash_tech_headers(full_appt["lash_tech_id"])))
    return member, fill["id"]


def test_fill_at_exactly_five_day_gap_is_accepted():
    """PRD §3.6: "A gap of fewer than 5 days is too soon and is rejected with
    `ERR_FILL_TOO_SOON`; a gap that is exactly 5 days or more satisfies the lower bound."

    Design: Difficulty/boundary_precision_check/fill_gap_exactly_five_days_passes
    """
    member, fill_id = _setup_fill_anchor("2026-06-06T09:00:00Z")
    set_clock("2026-06-05T09:00:00Z")
    # anchor 2026-06-01T10:00; FILL 2026-06-06T10:00 => gap exactly 5 days.
    appt = validate_success(api_client.create_appointment(
        create_appointment_payload(member["id"], fill_id, "2026-06-06T10:00:00Z"), FD),
        expected_status=201)
    assert appt["status"] == "BOOKED"
    assert appt["start_utc"][:19] == "2026-06-06T10:00:00", \
        f"FILL booked at gap-5 start, got {appt['start_utc']}"


def test_fill_below_five_day_gap_rejected_too_soon():
    """PRD §3.6: "A gap of fewer than 5 days is too soon and is rejected with
    `ERR_FILL_TOO_SOON`; a gap that is exactly 5 days or more satisfies the lower bound."

    Design: Difficulty/boundary_precision_check/fill_gap_exactly_five_days_passes
    """
    member, fill_id = _setup_fill_anchor("2026-06-05T09:00:00Z")
    set_clock("2026-06-04T09:00:00Z")
    # anchor 2026-06-01T10:00; FILL 2026-06-05T10:00 => gap exactly 4 days (< 5).
    resp = api_client.create_appointment(
        create_appointment_payload(member["id"], fill_id, "2026-06-05T10:00:00Z"), FD)
    validate_error(resp, ApiErrorId.ERR_FILL_TOO_SOON)


# ──────────────────────────────────────────────────────────────────────────
# boundary_precision_check / empty_tech_pool_returns_no_tech_available
# ──────────────────────────────────────────────────────────────────────────
def test_off_duty_only_tech_yields_no_tech_available():
    """PRD §3.7: "If the candidate pool is empty the booking is rejected with
    `ERR_NO_TECH_AVAILABLE`."

    Design: Difficulty/boundary_precision_check/empty_tech_pool_returns_no_tech_available
    """
    studio = create_studio(name="Glow")
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    tech = create_tech(studio["id"], full_name="Mara", skill_level=3, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T09:00:00Z")
    get_success_data(api_client.set_lash_tech_status(tech["id"], "OFF_DUTY", SM))
    member = create_member(studio["id"])
    set_clock("2026-06-10T10:00:00Z")
    resp = api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T20:00:00Z"), FD)
    validate_error(resp, ApiErrorId.ERR_NO_TECH_AVAILABLE)


def test_studio_with_no_techs_yields_no_tech_available():
    """PRD §3.7: "The candidate pool for a booking is every `LashTech` in the appointment's
    studio that is `AVAILABLE` ... If the candidate pool is empty the booking is rejected with
    `ERR_NO_TECH_AVAILABLE`."

    Design: Difficulty/boundary_precision_check/empty_tech_pool_returns_no_tech_available
    """
    studio = create_studio(name="Glow")
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    member = create_member(studio["id"])  # studio has zero techs at all
    set_clock("2026-06-10T10:00:00Z")
    resp = api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T20:00:00Z"), FD)
    validate_error(resp, ApiErrorId.ERR_NO_TECH_AVAILABLE)


# ──────────────────────────────────────────────────────────────────────────
# cross_entity_state_dependency / credit_booking_requires_membership_active
# ──────────────────────────────────────────────────────────────────────────
def test_credit_booking_against_suspended_membership_rejected():
    """PRD §3.5: "The membership named by `membership_id` must be `ACTIVE` — a `PAST_DUE`,
    `SUSPENDED`, or `CANCELLED` membership blocks a credit booking and is rejected with
    `ERR_MEMBERSHIP_NOT_BOOKABLE`."

    Design: Difficulty/cross_entity_state_dependency/credit_booking_requires_membership_active
    """
    studio = create_studio(name="Glow", noshow_strike_threshold=3)
    plan = create_plan(studio["id"], tier="PREMIER", monthly_credit_allotment=8, monthly_fee_cents=9900)
    tint = create_service_type(studio["id"], code="TINT", name="Tint", duration_minutes=30,
                              base_price_cents=4000, credit_cost=2, category="STANDARD",
                              requires_patch_test=False)
    tech = create_tech(studio["id"], full_name="Mara", skill_level=2, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T00:00:00Z")
    sanitize_tech(tech["id"], "2026-06-20T06:00:00Z")
    member = create_member(studio["id"])
    ms = create_membership(member["id"], plan["id"], initial_credits=8)
    set_clock("2026-06-10T09:00:00Z")
    for s in ["2026-06-10T07:00:00Z", "2026-06-10T07:30:00Z", "2026-06-10T08:00:00Z"]:
        a = get_success_data(api_client.create_appointment(
            create_appointment_payload(member["id"], tint["id"], s), FD))
        get_success_data(api_client.mark_no_show(a["id"], FD))
    assert get_membership(ms["id"])["status"] == "SUSPENDED"
    ms_v = get_membership(ms["id"])["version"]
    resp = api_client.create_appointment(
        create_appointment_payload(member["id"], tint["id"], "2026-06-20T10:00:00Z",
                                   pay_with_credits=True, membership_id=ms["id"],
                                   expected_membership_version=ms_v), FD)
    validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_BOOKABLE)


def test_credit_booking_against_cancelled_membership_rejected():
    """PRD §3.5: "The membership named by `membership_id` must be `ACTIVE` — a `PAST_DUE`,
    `SUSPENDED`, or `CANCELLED` membership blocks a credit booking and is rejected with
    `ERR_MEMBERSHIP_NOT_BOOKABLE`."

    Design: Difficulty/cross_entity_state_dependency/credit_booking_requires_membership_active
    """
    studio = create_studio(name="Glow")
    plan = create_plan(studio["id"], tier="PREMIER", monthly_credit_allotment=8, monthly_fee_cents=9900)
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    tech = create_tech(studio["id"], full_name="Mara", skill_level=3, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T09:00:00Z")
    member = create_member(studio["id"])
    ms = create_membership(member["id"], plan["id"], initial_credits=8)
    cancelled = validate_success(api_client.cancel_membership(ms["id"], SM))
    set_clock("2026-06-10T10:00:00Z")
    resp = api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T20:00:00Z",
                                   pay_with_credits=True, membership_id=ms["id"],
                                   expected_membership_version=cancelled["version"]), FD)
    validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_BOOKABLE)


# ──────────────────────────────────────────────────────────────────────────
# cross_entity_state_dependency / booking_requires_sanitized_station
# ──────────────────────────────────────────────────────────────────────────
def test_booking_with_unsanitized_only_tech_rejected():
    """PRD §3.5: "a candidate whose `station_sanitized_through_utc` is null or earlier than
    `start_utc` is ineligible, and if the gate is the reason no technician can host the
    appointment the rejection is `ERR_STATION_NOT_SANITIZED`".

    Design: Difficulty/cross_entity_state_dependency/booking_requires_sanitized_station
    """
    studio = create_studio(name="Glow")
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    create_tech(studio["id"], full_name="Mara", skill_level=3, station_number=1)  # NO sanitation log
    member = create_member(studio["id"])
    set_clock("2026-06-10T10:00:00Z")
    resp = api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T20:00:00Z"), FD)
    validate_error(resp, ApiErrorId.ERR_STATION_NOT_SANITIZED)


def test_booking_after_station_window_lapses_rejected():
    """PRD §3.5: "a candidate whose `station_sanitized_through_utc` is null or earlier than
    `start_utc` is ineligible, and if the gate is the reason no technician can host the
    appointment the rejection is `ERR_STATION_NOT_SANITIZED`".

    Design: Difficulty/cross_entity_state_dependency/booking_requires_sanitized_station
    """
    studio = create_studio(name="Glow")
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    tech = create_tech(studio["id"], full_name="Mara", skill_level=3, station_number=1)
    # sanitized at 08:00 -> valid through 20:00; an appt starting at 21:00 is past the window.
    sanitize_tech(tech["id"], "2026-06-10T08:00:00Z")
    member = create_member(studio["id"])
    set_clock("2026-06-09T10:00:00Z")
    resp = api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T21:00:00Z"), FD)
    validate_error(resp, ApiErrorId.ERR_STATION_NOT_SANITIZED)


# ──────────────────────────────────────────────────────────────────────────
# resource_temporal_overlap / chair_half_open_overlap_rejected_adjacent_allowed
# ──────────────────────────────────────────────────────────────────────────
def _setup_one_tech_first_appt():
    """One tech sanitized through far future; FULL_SET 120 min; first appt 10:00-12:00."""
    studio = create_studio(name="Glow")
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    tech = create_tech(studio["id"], full_name="Mara", skill_level=3, station_number=1)
    sanitize_tech(tech["id"], "2026-06-10T13:30:00Z")
    member = create_member(studio["id"])
    set_clock("2026-06-09T10:00:00Z")
    appt1 = get_success_data(api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T10:00:00Z"), FD))
    return member, full_st, tech, appt1


def test_chair_overlap_rejected_half_open():
    """PRD §3.7: "Two appointments on the same technician conflict when their half-open
    intervals — from `start_utc` up to but not including `end_utc` — overlap ... If the
    candidate pool is empty the booking is rejected with `ERR_NO_TECH_AVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/chair_half_open_overlap_rejected_adjacent_allowed
    """
    member, full_st, tech, appt1 = _setup_one_tech_first_appt()
    assert appt1["end_utc"][:19] == "2026-06-10T12:00:00"
    # 11:30 start overlaps [10:00, 12:00) on the only tech.
    resp = api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T11:30:00Z"), FD)
    validate_error(resp, ApiErrorId.ERR_NO_TECH_AVAILABLE)


def test_chair_adjacent_appointment_allowed():
    """PRD §3.7: "Back-to-back appointments where one's `end_utc` equals the next's
    `start_utc` are allowed with no buffer between them."

    Design: Difficulty/resource_temporal_overlap/chair_half_open_overlap_rejected_adjacent_allowed
    """
    member, full_st, tech, appt1 = _setup_one_tech_first_appt()
    # 12:00 start == appt1.end_utc; adjacency is allowed.
    appt2 = validate_success(api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T12:00:00Z"), FD),
        expected_status=201)
    assert appt2["status"] == "BOOKED"
    assert appt2["lash_tech_id"] == tech["id"], \
        f"adjacent appt assigned to the same tech, got {appt2['lash_tech_id']}"


# ──────────────────────────────────────────────────────────────────────────
# resource_temporal_overlap / sanitation_closed_interval_boundary_inclusive
# ──────────────────────────────────────────────────────────────────────────
def test_sanitation_closed_interval_start_at_valid_through_is_covered():
    """PRD §3.2: "A sanitation log covers the **closed** interval running from
    `sanitized_at_utc` through `valid_through_utc` inclusive — an appointment that begins
    exactly at `valid_through_utc` is still considered covered."

    Design: Difficulty/resource_temporal_overlap/sanitation_closed_interval_boundary_inclusive
    """
    studio = create_studio(name="Glow")
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    tech = create_tech(studio["id"], full_name="Mara", skill_level=3, station_number=1)
    log = sanitize_tech(tech["id"], "2026-06-10T08:00:00Z")  # valid_through 2026-06-10T20:00:00Z
    member = create_member(studio["id"])
    set_clock("2026-06-09T10:00:00Z")
    assert log["valid_through_utc"][:19] == "2026-06-10T20:00:00", \
        f"valid_through = sanitized + 12h, got {log['valid_through_utc']}"
    # start exactly at valid_through_utc is covered (closed interval).
    appt = validate_success(api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T20:00:00Z"), FD),
        expected_status=201)
    assert appt["status"] == "BOOKED"
    assert appt["lash_tech_id"] == tech["id"]


def test_sanitation_closed_interval_one_second_past_is_uncovered():
    """PRD §3.2: "A sanitation log covers the **closed** interval running from
    `sanitized_at_utc` through `valid_through_utc` inclusive". PRD §3.5: "a candidate whose
    `station_sanitized_through_utc` is null or earlier than `start_utc` is ineligible, and if
    the gate is the reason no technician can host the appointment the rejection is
    `ERR_STATION_NOT_SANITIZED`".

    Design: Difficulty/resource_temporal_overlap/sanitation_closed_interval_boundary_inclusive
    """
    studio = create_studio(name="Glow")
    full_st = create_service_type(studio["id"], code="FULL_SET", name="Full Set",
                                  duration_minutes=120, base_price_cents=12000, credit_cost=4,
                                  category="PREMIUM", requires_patch_test=False)
    tech = create_tech(studio["id"], full_name="Mara", skill_level=3, station_number=1)
    log = sanitize_tech(tech["id"], "2026-06-10T08:00:00Z")  # valid_through 2026-06-10T20:00:00Z
    member = create_member(studio["id"])
    set_clock("2026-06-09T10:00:00Z")
    assert log["valid_through_utc"][:19] == "2026-06-10T20:00:00"
    # one second past valid_through_utc falls outside the closed interval.
    resp = api_client.create_appointment(
        create_appointment_payload(member["id"], full_st["id"], "2026-06-10T20:00:01Z"), FD)
    validate_error(resp, ApiErrorId.ERR_STATION_NOT_SANITIZED)
