"""Bed-pool depth tests: half-open bed adjacency vs client-inclusive turnover, capacity
conservation, the pinned recompute-then-promote order, and the double-book/capacity conflict.

Every test translates exactly one instance from the difficulty design index (queue A).
"""
from test_helpers import (
    validate_success, validate_error,
    create_bed_reservation_payload,
    set_clock, new_client, new_shelter_with_beds, new_reservation,
    new_waitlist_entry, shelter_version, get_shelter,
    TEST_USERS,
)

SHELTER = TEST_USERS["shelter_manager_headers"]


# ─── resource_temporal_overlap / overlap_bed_halfopen_adjacency_ok ─────────────
def test_adjacent_window_reuses_same_bed(api):
    """PRD §2.7: "adjacency does not conflict, so a reservation whose exit date equals
    another's entry date may share the same bed because no night is double-occupied."

    Design: Difficulty/resource_temporal_overlap/overlap_bed_halfopen_adjacency_ok
    """
    ca = new_client(full_name="Al A", dob="1990-05-05")
    cb = new_client(full_name="Bo B", dob="1990-06-06")
    shelter, beds = new_shelter_with_beds(("B1",), name="Cedar ES")
    resa = new_reservation(ca["id"], shelter["id"], "2026-03-05", "2026-03-10")

    resb = new_reservation(cb["id"], shelter["id"], "2026-03-10", "2026-03-15")
    assert resb["status"] == "RESERVED"
    assert resb["bed_id"] == resa["bed_id"], "adjacent window must reuse the same bed"


def test_overlapping_window_rejected_at_capacity(api):
    """PRD §3.4: "If no bed qualifies, the request is rejected with `ERR_SHELTER_AT_CAPACITY`."

    Design: Difficulty/resource_temporal_overlap/overlap_bed_halfopen_adjacency_ok
    """
    ca = new_client(full_name="Al A", dob="1990-05-05")
    cc = new_client(full_name="Cy C", dob="1990-07-07")
    shelter, beds = new_shelter_with_beds(("B1",), name="Cedar ES")
    new_reservation(ca["id"], shelter["id"], "2026-03-05", "2026-03-10")

    shv = shelter_version(shelter["id"])
    res = api.create_bed_reservation(create_bed_reservation_payload(
        cc["id"], shelter["id"], "2026-03-08", "2026-03-12", shv), SHELTER)
    validate_error(res, "ERR_SHELTER_AT_CAPACITY", expected_status=409)


# ─── resource_temporal_overlap / overlap_client_inclusive_turnover_conflict ────
def test_client_turnover_day_is_double_booked(api):
    """PRD §3.4: "Unlike bed-to-bed conflict, the client double-booking check treats the
    interval as **inclusive of the turnover day**: if one stay's exit date equals another
    stay's entry date, that shared turnover day is a conflict for the same client even
    though it would have been permissible adjacency for two different clients on one bed."

    Design: Difficulty/resource_temporal_overlap/overlap_client_inclusive_turnover_conflict
    """
    ca = new_client(full_name="Tara Turn", dob="1990-08-08")
    s1, _ = new_shelter_with_beds(("S1B1",), name="Shelter One")
    s2, _ = new_shelter_with_beds(("S2B1",), name="Shelter Two")
    new_reservation(ca["id"], s1["id"], "2026-03-05", "2026-03-10")

    shv2 = shelter_version(s2["id"])
    res = api.create_bed_reservation(create_bed_reservation_payload(
        ca["id"], s2["id"], "2026-03-10", "2026-03-15", shv2), SHELTER)
    validate_error(res, "ERR_CLIENT_DOUBLE_BOOKED", expected_status=409)


def test_turnover_conflict_leaves_first_reservation_intact(api):
    """PRD §3.4: "On reservation creation, if the same client already holds a reservation
    occupying any of the same nights, the request is rejected with `ERR_CLIENT_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/overlap_client_inclusive_turnover_conflict
    """
    ca = new_client(full_name="Tara Turn", dob="1990-08-08")
    s1, _ = new_shelter_with_beds(("S1B1",), name="Shelter One")
    s2, _ = new_shelter_with_beds(("S2B1",), name="Shelter Two")
    res1 = new_reservation(ca["id"], s1["id"], "2026-03-05", "2026-03-10")

    shv2 = shelter_version(s2["id"])
    api.create_bed_reservation(create_bed_reservation_payload(
        ca["id"], s2["id"], "2026-03-10", "2026-03-15", shv2), SHELTER)

    still = validate_success(api.get_bed_reservation(res1["id"], SHELTER), 200)
    assert still["status"] == "RESERVED", "rejected turnover booking must not disturb the held stay"


# ─── compensating_invariant / comp_bed_capacity_conserved_reserve_cancel ───────
def test_reserve_then_cancel_restores_available_beds(api):
    """PRD §2.7: "Its `available_beds` is the number of `ACTIVE` beds that have no
    `RESERVED` or `CHECKED_IN` reservation covering the current logical-clock date."
    PRD §3.4: "Cancelling a `RESERVED` reservation moves it to `CANCELLED`, freeing its
    window on the assigned bed, incrementing `Shelter.version`, recomputing `available_beds`,
    and evaluating waitlist promotion."

    Design: Difficulty/compensating_invariant/comp_bed_capacity_conserved_reserve_cancel
    """
    set_clock("2026-03-07T00:00:00Z")
    ca = new_client(full_name="Cap Client", dob="1990-09-09")
    shelter, _ = new_shelter_with_beds(("B1",), name="Holly ES")
    res = new_reservation(ca["id"], shelter["id"], "2026-03-05", "2026-03-20")

    validate_success(api.cancel_reservation(res["id"], SHELTER), 200)
    after = get_shelter(shelter["id"])
    assert after["available_beds"] == 1, "cancel must restore the single free bed"


def test_reserve_then_cancel_conserves_total_beds(api):
    """PRD §2.7: "Its `total_beds` is the number of `Bed` rows under the shelter across all
    statuses."

    Design: Difficulty/compensating_invariant/comp_bed_capacity_conserved_reserve_cancel
    """
    set_clock("2026-03-07T00:00:00Z")
    ca = new_client(full_name="Cap Client", dob="1990-09-09")
    shelter, _ = new_shelter_with_beds(("B1",), name="Holly ES")
    res = new_reservation(ca["id"], shelter["id"], "2026-03-05", "2026-03-20")

    validate_success(api.cancel_reservation(res["id"], SHELTER), 200)
    after = get_shelter(shelter["id"])
    assert after["total_beds"] == 1, "total_beds is unaffected by reservation churn"


# ─── combinatorial_formula / comb_bed_availability_promotion_order ─────────────
def test_cancel_promotes_top_waitlist_entry(api):
    """PRD §3.5: "The chosen entry moves `WAITING → PROMOTED`, and a fresh `RESERVED`
    reservation is minted for it with a server-assigned bed; the entry's
    `promoted_reservation_id` records that new reservation's `id`."

    Design: Difficulty/combinatorial_formula/comb_bed_availability_promotion_order
    """
    set_clock("2026-03-07T00:00:00Z")
    ca = new_client(full_name="Amy A", dob="1991-04-04")
    cb = new_client(full_name="Ben B", dob="1992-05-05")
    shelter, _ = new_shelter_with_beds(("B1",), name="Oak ES")
    resa = new_reservation(ca["id"], shelter["id"], "2026-03-05", "2026-03-20")
    wlb = new_waitlist_entry(shelter["id"], cb["id"], "2026-03-06", "2026-03-19")

    validate_success(api.cancel_reservation(resa["id"], SHELTER), 200)
    promoted = validate_success(api.get_waitlist_entry(wlb["id"], SHELTER), 200)
    assert promoted["status"] == "PROMOTED"
    assert promoted["promoted_reservation_id"] is not None


def test_promotion_reconsumes_capacity_back_to_zero(api):
    """PRD §2.7: "then run waitlist promotion against that freshly recomputed picture, never
    against a pre-mutation snapshot; and finally, if a promotion mints a new reservation,
    apply the first two steps again for that new reservation."

    Design: Difficulty/combinatorial_formula/comb_bed_availability_promotion_order
    """
    set_clock("2026-03-07T00:00:00Z")
    ca = new_client(full_name="Amy A", dob="1991-04-04")
    cb = new_client(full_name="Ben B", dob="1992-05-05")
    shelter, _ = new_shelter_with_beds(("B1",), name="Oak ES")
    resa = new_reservation(ca["id"], shelter["id"], "2026-03-05", "2026-03-20")
    new_waitlist_entry(shelter["id"], cb["id"], "2026-03-06", "2026-03-19")

    validate_success(api.cancel_reservation(resa["id"], SHELTER), 200)
    after = get_shelter(shelter["id"])
    assert after["available_beds"] == 0, "the promoted reservation re-consumes the freed bed"


# ─── boundary_precision_check / bnd_waitlist_promotion_empty_pool ──────────────
def test_cancel_with_empty_waitlist_marks_cancelled(api):
    """PRD §3.4: "Cancelling a `RESERVED` reservation moves it to `CANCELLED`, freeing its
    window on the assigned bed, incrementing `Shelter.version`, recomputing `available_beds`,
    and evaluating waitlist promotion."

    Design: Difficulty/boundary_precision_check/bnd_waitlist_promotion_empty_pool
    """
    set_clock("2026-03-07T00:00:00Z")
    ca = new_client(full_name="Solo A", dob="1990-02-02")
    shelter, _ = new_shelter_with_beds(("B1",), name="Ash ES")
    res = new_reservation(ca["id"], shelter["id"], "2026-03-05", "2026-03-20")

    cancelled = validate_success(api.cancel_reservation(res["id"], SHELTER), 200)
    assert cancelled["status"] == "CANCELLED"


def test_cancel_with_empty_waitlist_leaves_bed_free(api):
    """PRD §3.5: "If no candidate qualifies — no waiting entry can be served by a currently
    free, non-overlapping bed — no promotion occurs and the freed capacity simply remains
    available."

    Design: Difficulty/boundary_precision_check/bnd_waitlist_promotion_empty_pool
    """
    set_clock("2026-03-07T00:00:00Z")
    ca = new_client(full_name="Solo A", dob="1990-02-02")
    shelter, _ = new_shelter_with_beds(("B1",), name="Ash ES")
    res = new_reservation(ca["id"], shelter["id"], "2026-03-05", "2026-03-20")

    validate_success(api.cancel_reservation(res["id"], SHELTER), 200)
    after = get_shelter(shelter["id"])
    assert after["available_beds"] == 1, "with no waitlist candidate the bed stays free"


# ─── priority_pair_validation_conflict / pconf_client_doublebook_over_capacity ─
def test_double_book_over_capacity_reports_double_booked(api):
    """PRD §2.5: "Note that on reservation creation four business rules stack in this exact
    order after well-formedness: the stale-version check (rule 6), then the client
    double-booking check (rule 10), then the capacity-availability check (rule 14). A stale
    shelter view is therefore reported before a double-booking conflict, and both are
    reported before the pool is found to be full."

    Design: Difficulty/priority_pair_validation_conflict/pconf_client_doublebook_over_capacity
    """
    ca = new_client(full_name="Dora Dbl", dob="1990-11-11")
    shelter, _ = new_shelter_with_beds(("B1",), name="Fir ES")
    new_reservation(ca["id"], shelter["id"], "2026-03-05", "2026-03-20")

    shv = shelter_version(shelter["id"])
    res = api.create_bed_reservation(create_bed_reservation_payload(
        ca["id"], shelter["id"], "2026-03-06", "2026-03-19", shv), SHELTER)
    validate_error(res, "ERR_CLIENT_DOUBLE_BOOKED", expected_status=409)


def test_double_book_conflict_keeps_first_reservation_reserved(api):
    """PRD §2.5: "the client double-booking check (rule 10), then the capacity-availability
    check (rule 14)."

    Design: Difficulty/priority_pair_validation_conflict/pconf_client_doublebook_over_capacity
    """
    ca = new_client(full_name="Dora Dbl", dob="1990-11-11")
    shelter, _ = new_shelter_with_beds(("B1",), name="Fir ES")
    resa = new_reservation(ca["id"], shelter["id"], "2026-03-05", "2026-03-20")

    shv = shelter_version(shelter["id"])
    api.create_bed_reservation(create_bed_reservation_payload(
        ca["id"], shelter["id"], "2026-03-06", "2026-03-19", shv), SHELTER)

    still = validate_success(api.get_bed_reservation(resa["id"], SHELTER), 200)
    assert still["status"] == "RESERVED"
