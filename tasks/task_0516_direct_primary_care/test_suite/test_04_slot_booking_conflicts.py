"""Visit-slot capacity semantics, member double-booking, the annual-physical
timing gate, and the slot-availability-beats-physical-not-due precedence.
PRD §3.5, §3.14.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_active_member, create_slot, book_visit,
    make_member_headers, ApiErrorId, ADMIN,
)


def _fresh_active_member_same_provider(provider, practice, clock=None):
    """Register + activate another member on the given provider/practice."""
    from test_helpers import (register_member, assign_pcp_manual,
                              get_membership_for, charge_membership)
    member = register_member(practice["id"])
    assign_pcp_manual(member["id"], provider["id"])
    membership = get_membership_for(member["id"])
    charge_membership(member["id"], membership["id"], membership["member_share_cents"], "SUCCEEDED")
    return get_success_data(api_client.get_member(member["id"], ADMIN))


def test_in_person_slot_single_occupancy(api):
    """PRD §3.5: "The slot must not be exhausted: an `IN_PERSON` slot must have a
    `booked_count` of zero, and a `VIRTUAL` slot must have a `booked_count` strictly
    below its `virtual_capacity`; the slot's `starts_at` must precede its
    `ends_at`. A booking against an exhausted slot is rejected with
    `ERR_SLOT_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/in_person_slot_single_occupancy_capacity
    """
    ctx = setup_active_member()
    slot = create_slot(ctx["provider"]["id"], "IN_PERSON",
                       "2026-06-05T09:00:00Z", "2026-06-05T09:30:00Z")
    book_visit(ctx["member"]["id"], slot["id"], "SAME_DAY", slot["version"])

    m2 = _fresh_active_member_same_provider(ctx["provider"], ctx["practice"])
    slot_after = validate_success(api_client.get_visit_slot(slot["id"], ADMIN), 200)
    from test_helpers import create_visit_payload
    res = api_client.create_visit(
        create_visit_payload(m2["id"], slot["id"], "SAME_DAY", slot_after["version"]),
        make_member_headers(m2["id"]))
    validate_error(res, ApiErrorId.ERR_SLOT_UNAVAILABLE.value)


def test_in_person_slot_reaches_full_after_one_booking(api):
    """PRD §3.5: "An `IN_PERSON` slot is exclusive — it admits one visit per
    interval — whereas a `VIRTUAL` slot permits aggregate double-booking up to
    `virtual_capacity`."
    PRD §3.5: "The derived `slot_state` is `OPEN` while `booked_count` is below the
    slot's effective capacity and `FULL` once `booked_count` equals it."

    Design: Difficulty/resource_temporal_overlap/in_person_slot_single_occupancy_capacity
    """
    ctx = setup_active_member()
    slot = create_slot(ctx["provider"]["id"], "IN_PERSON",
                       "2026-06-06T09:00:00Z", "2026-06-06T09:30:00Z")
    assert slot["slot_state"] == "OPEN"
    book_visit(ctx["member"]["id"], slot["id"], "SAME_DAY", slot["version"])
    slot_after = validate_success(api_client.get_visit_slot(slot["id"], ADMIN), 200)
    assert slot_after["booked_count"] == 1
    assert slot_after["slot_state"] == "FULL"


def test_member_double_booked_on_overlapping_slot(api):
    """PRD §3.5: "A member may not hold two visits in `BOOKED` or `CHECKED_IN`
    status whose slot intervals overlap, where intervals are treated as half-open
    from `starts_at` inclusive to `ends_at` exclusive; an overlapping booking is
    rejected with `ERR_MEMBER_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/member_double_booked_half_open_overlap_adjacent_ok
    """
    ctx = setup_active_member()
    slot_a = create_slot(ctx["provider"]["id"], "VIRTUAL",
                         "2026-06-05T09:00:00Z", "2026-06-05T10:00:00Z", virtual_capacity=5)
    slot_b = create_slot(ctx["provider"]["id"], "VIRTUAL",
                         "2026-06-05T09:30:00Z", "2026-06-05T10:30:00Z", virtual_capacity=5)
    book_visit(ctx["member"]["id"], slot_a["id"], "VIRTUAL", slot_a["version"])

    from test_helpers import create_visit_payload
    res = api_client.create_visit(
        create_visit_payload(ctx["member"]["id"], slot_b["id"], "VIRTUAL", slot_b["version"]),
        make_member_headers(ctx["member"]["id"]))
    validate_error(res, ApiErrorId.ERR_MEMBER_DOUBLE_BOOKED.value)


def test_member_adjacent_slot_booking_allowed(api):
    """PRD §3.5: "A member may not hold two visits in `BOOKED` or `CHECKED_IN`
    status whose slot intervals overlap, where intervals are treated as half-open
    from `starts_at` inclusive to `ends_at` exclusive."

    Design: Difficulty/resource_temporal_overlap/member_double_booked_half_open_overlap_adjacent_ok
    """
    ctx = setup_active_member()
    slot_a = create_slot(ctx["provider"]["id"], "VIRTUAL",
                         "2026-06-05T09:00:00Z", "2026-06-05T10:00:00Z", virtual_capacity=5)
    slot_c = create_slot(ctx["provider"]["id"], "VIRTUAL",
                         "2026-06-05T10:00:00Z", "2026-06-05T11:00:00Z", virtual_capacity=5)
    book_visit(ctx["member"]["id"], slot_a["id"], "VIRTUAL", slot_a["version"])
    # C starts exactly where A ends; half-open intervals do not overlap.
    visit_c = book_visit(ctx["member"]["id"], slot_c["id"], "VIRTUAL", slot_c["version"])
    assert visit_c["clinical_status"] == "BOOKED"


def test_virtual_slot_accepts_below_capacity(api):
    """PRD §3.5: "a `VIRTUAL` slot must have a `booked_count` strictly below its
    `virtual_capacity`."

    Design: Difficulty/boundary_precision_check/virtual_slot_capacity_strict_less_than_boundary
    """
    ctx = setup_active_member()
    slot = create_slot(ctx["provider"]["id"], "VIRTUAL",
                       "2026-06-05T09:00:00Z", "2026-06-05T09:30:00Z", virtual_capacity=2)
    # booked_count 0 -> 1, still < 2: second booking by another member succeeds.
    book_visit(ctx["member"]["id"], slot["id"], "VIRTUAL", slot["version"])
    m2 = _fresh_active_member_same_provider(ctx["provider"], ctx["practice"])
    slot_v1 = validate_success(api_client.get_visit_slot(slot["id"], ADMIN), 200)["version"]
    visit2 = book_visit(m2["id"], slot["id"], "VIRTUAL", slot_v1)
    assert visit2["clinical_status"] == "BOOKED"


def test_virtual_slot_rejects_at_capacity(api):
    """PRD §3.5: "a `VIRTUAL` slot permits aggregate double-booking up to
    `virtual_capacity`."
    PRD §3.5: "A booking against an exhausted slot is rejected with
    `ERR_SLOT_UNAVAILABLE`."

    Design: Difficulty/boundary_precision_check/virtual_slot_capacity_strict_less_than_boundary
    """
    ctx = setup_active_member()
    slot = create_slot(ctx["provider"]["id"], "VIRTUAL",
                       "2026-06-05T09:00:00Z", "2026-06-05T09:30:00Z", virtual_capacity=2)
    book_visit(ctx["member"]["id"], slot["id"], "VIRTUAL", slot["version"])
    m2 = _fresh_active_member_same_provider(ctx["provider"], ctx["practice"])
    slot_v1 = validate_success(api_client.get_visit_slot(slot["id"], ADMIN), 200)["version"]
    book_visit(m2["id"], slot["id"], "VIRTUAL", slot_v1)  # booked_count -> 2 (FULL)

    m3 = _fresh_active_member_same_provider(ctx["provider"], ctx["practice"])
    slot_full = validate_success(api_client.get_visit_slot(slot["id"], ADMIN), 200)
    assert slot_full["booked_count"] == 2
    assert slot_full["slot_state"] == "FULL"
    from test_helpers import create_visit_payload
    res = api_client.create_visit(
        create_visit_payload(m3["id"], slot["id"], "VIRTUAL", slot_full["version"]),
        make_member_headers(m3["id"]))
    validate_error(res, ApiErrorId.ERR_SLOT_UNAVAILABLE.value)


def test_slot_full_beats_physical_not_due(api):
    """PRD §3.14: "Only after these structural checks do the domain-specific
    business rules apply — cross-entity eligibility (`ERR_MEMBER_NOT_ELIGIBLE`),
    slot availability (`ERR_SLOT_UNAVAILABLE`), member double-booking
    (`ERR_MEMBER_DOUBLE_BOOKED`), annual-physical timing (`ERR_PHYSICAL_NOT_DUE`),
    panel capacity (`ERR_NO_PANEL_CAPACITY`), seat limits (`ERR_SEAT_LIMIT_REACHED`),
    empty care plans (`ERR_CARE_PLAN_EMPTY`), expired referrals
    (`ERR_REFERRAL_EXPIRED`), charge-amount agreement (`ERR_AMOUNT_MISMATCH`), and
    PCP-before-activation (`ERR_PCP_REQUIRED`) — each evaluated within the workflow
    it guards as described above."

    Design: Difficulty/priority_pair_validation_conflict/visit_slot_full_beats_physical_not_due
    """
    # m2 gets a future annual_physical_due_on (a completed ANNUAL_PHYSICAL advances
    # it +365 days), so an immediate ANNUAL_PHYSICAL booking is NOT yet due. m1 then
    # fills the only remaining IN_PERSON slot (FULL). m2 books an ANNUAL_PHYSICAL
    # into that FULL slot: both ERR_SLOT_UNAVAILABLE and ERR_PHYSICAL_NOT_DUE are
    # live, but §3.14 lists slot availability before annual-physical timing, so
    # ERR_SLOT_UNAVAILABLE wins.
    from test_helpers import create_visit_payload, complete_visit_payload, make_provider_headers
    ctx = setup_active_member()
    prov_h = make_provider_headers(ctx["provider"]["id"])
    m2 = _fresh_active_member_same_provider(ctx["provider"], ctx["practice"])

    # Give m2 a completed ANNUAL_PHYSICAL so its annual_physical_due_on is in the future.
    phys_slot = create_slot(ctx["provider"]["id"], "IN_PERSON",
                            "2026-06-03T09:00:00Z", "2026-06-03T10:00:00Z")
    phys_visit = book_visit(m2["id"], phys_slot["id"], "ANNUAL_PHYSICAL", phys_slot["version"])
    get_success_data(api_client.check_in_visit(phys_visit["id"], prov_h))
    get_success_data(api_client.complete_visit(phys_visit["id"], complete_visit_payload([]), prov_h))
    m2_after = validate_success(api_client.get_member(m2["id"], ADMIN), 200)
    assert m2_after["annual_physical_due_on"] is not None

    # Fill the contested slot with m1's booking.
    slot = create_slot(ctx["provider"]["id"], "IN_PERSON",
                       "2026-06-05T09:00:00Z", "2026-06-05T10:00:00Z")
    book_visit(ctx["member"]["id"], slot["id"], "SAME_DAY", slot["version"])
    slot_after = validate_success(api_client.get_visit_slot(slot["id"], ADMIN), 200)

    res = api_client.create_visit(
        create_visit_payload(m2["id"], slot["id"], "ANNUAL_PHYSICAL", slot_after["version"]),
        make_member_headers(m2["id"]))
    validate_error(res, ApiErrorId.ERR_SLOT_UNAVAILABLE.value)


def test_physical_not_due_alone_when_slot_available(api):
    """PRD §3.5: "booking an annual physical before it is due is rejected with
    `ERR_PHYSICAL_NOT_DUE`."

    Design: Difficulty/priority_pair_validation_conflict/visit_slot_full_beats_physical_not_due
    """
    # Isolated lower-priority face: the member's annual_physical_due_on is in the
    # future and the slot is OPEN, so only ERR_PHYSICAL_NOT_DUE can fire.
    from test_helpers import create_visit_payload, complete_visit_payload, make_provider_headers
    ctx = setup_active_member()
    prov_h = make_provider_headers(ctx["provider"]["id"])
    phys_slot = create_slot(ctx["provider"]["id"], "IN_PERSON",
                            "2026-06-03T09:00:00Z", "2026-06-03T10:00:00Z")
    phys_visit = book_visit(ctx["member"]["id"], phys_slot["id"], "ANNUAL_PHYSICAL", phys_slot["version"])
    get_success_data(api_client.check_in_visit(phys_visit["id"], prov_h))
    get_success_data(api_client.complete_visit(phys_visit["id"], complete_visit_payload([]), prov_h))
    member = validate_success(api_client.get_member(ctx["member"]["id"], ADMIN), 200)
    assert member["annual_physical_due_on"] is not None

    open_slot = create_slot(ctx["provider"]["id"], "IN_PERSON",
                            "2026-06-05T09:00:00Z", "2026-06-05T10:00:00Z")
    res = api_client.create_visit(
        create_visit_payload(ctx["member"]["id"], open_slot["id"], "ANNUAL_PHYSICAL", open_slot["version"]),
        make_member_headers(ctx["member"]["id"]))
    validate_error(res, ApiErrorId.ERR_PHYSICAL_NOT_DUE.value)
