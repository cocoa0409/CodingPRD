"""Waitlist lifecycle: joins, promotion ranking, offers, claims, declines,
offer expiry, and the ops sweep."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_link,
    assert_instant,
    assert_waitlist_entry,
    book_slot,
    create_booking_payload,
    create_waitlist_entry_payload,
    get_success_data,
    guardian_headers,
    read_window,
    scenario_offer_cycle,
    set_clock,
    setup_family_with_students,
    setup_offered_entry,
    setup_window_at_stage,
    add_family,
    add_student,
    run_ops,
    validate_error,
    validate_success,
)


def test_duplicate_waitlist_entry_rejected(api):
    """PRD 3.6: "At most one entry in `WAITING` or `OFFERED` status may exist
    per student-teacher-window combination, and no entry may be created at all
    when a `CONFIRMED` booking already exists for that student-teacher pair in
    that window — either situation is rejected with
    `ERR_DUPLICATE_WAITLIST_ENTRY`."

    Design: Corner/validations/duplicate_waitlist_entry_rejected
    """
    ctx = setup_window_at_stage("BOOKING_OPEN")
    teacher_id = ctx["teachers"][0]["id"]
    party = setup_family_with_students(ctx, 1)
    get_success_data(api.create_waitlist_entry(
        create_waitlist_entry_payload(ctx["window"]["id"], party["students"][0]["id"],
                                      teacher_id, "EITHER"),
        party["guardian"],
    ))

    response = api.create_waitlist_entry(
        create_waitlist_entry_payload(ctx["window"]["id"], party["students"][0]["id"],
                                      teacher_id, "VIRTUAL"),
        party["guardian"],
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_WAITLIST_ENTRY, 409)


def test_claim_waiting_entry_rejected(api):
    """PRD 3.6: "The entry must be `OFFERED` (otherwise `ERR_NO_ACTIVE_OFFER`),
    the logical clock must be on or before `offer_expires_at` — the deadline is
    inclusive, so a claim at exactly the expiry instant succeeds and a strictly
    later one is rejected with `ERR_OFFER_EXPIRED` — and a guardian caller must
    own the entry's family."

    Design: Corner/state_machines/claim_waiting_entry_rejected
    """
    ctx = setup_window_at_stage("BOOKING_OPEN")
    teacher_id = ctx["teachers"][0]["id"]
    party = setup_family_with_students(ctx, 1)
    entry = get_success_data(api.create_waitlist_entry(
        create_waitlist_entry_payload(ctx["window"]["id"], party["students"][0]["id"],
                                      teacher_id, "EITHER"),
        party["guardian"],
    ))
    assert entry["status"] == "WAITING"

    response = api.claim_offer(entry["id"], {"channel": "IN_PERSON"}, party["guardian"])
    validate_error(response, ApiErrorId.ERR_NO_ACTIVE_OFFER, 409)


def test_withdraw_claimed_entry_rejected(api):
    """PRD 3.6: "A successful claim creates the booking in `CONFIRMED` status,
    moves the slot from `HELD` to `BOOKED`, moves the entry from `OFFERED` to
    `CLAIMED` — a terminal state — and recomputes compactness and window
    counters."
    PRD 3.6: "Withdrawal is the family's or staff's explicit exit: an entry in
    `WAITING` or `OFFERED` moves to `WITHDRAWN` (an offered withdrawal releases
    its `HELD` slot to `OPEN` and re-runs promotion), optionally carrying a
    free-text `reason`, and the window's `waitlist_waiting_count` is
    recomputed."

    Design: Corner/state_machines/withdraw_claimed_entry_rejected
    """
    ctx = setup_offered_entry()
    claimed = validate_success(api.claim_offer(
        ctx["entry"]["id"], {"channel": "IN_PERSON"}, ctx["second_guardian"]
    ), 201)
    assert claimed["status"] == "CONFIRMED"

    response = api.withdraw_entry(ctx["entry"]["id"], {}, ctx["second_guardian"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)


def test_waitlist_priority_score_computed_and_refreshed(api, front_office_headers):
    """PRD 3.6: "It starts from a base of 100 points. A link flagged
    `required_conference` adds 50 points. Sibling presence adds 15 points per
    sibling of the student — another student with the same `family_id` — who
    holds a `CONFIRMED` booking in the same window, counting at most two
    siblings for a maximum of 30 points. Attendance risk subtracts 10 points
    per whole point of the family's `attendance_risk_strict`, with the strict
    score rounded down to a whole number and capped at five points, a maximum
    penalty of 50. Patience adds 5 points per full 24-hour period elapsed
    between the entry's `created_at` and the logical clock, capped at four
    periods for a maximum of 20 points."
    PRD 3.6: "The score is recomputed at entry creation, at every ops
    checkpoint, when a sibling booking is confirmed, and when the family's risk
    changes."

    Design: Corner/calculations/waitlist_priority_score_computed_and_refreshed
    """
    ctx = setup_window_at_stage(
        "BOOKING_OPEN",
        window_overrides={"name": "Sec", "format": "SECONDARY"},
        teacher_specs=[
            {"full_name": "T1", "grade_band": "SECONDARY", "subjects": ["math"]},
            {"full_name": "T2", "grade_band": "SECONDARY", "subjects": ["eng"]},
        ],
    )
    t1, t2 = ctx["teachers"]
    family = add_family()
    st_x = add_student(family["id"], full_name="X", grade_level=9)
    st_y = add_student(family["id"], full_name="Y", grade_level=11)
    add_link(st_x["id"], t1["id"], required_conference=True)
    add_link(st_y["id"], t2["id"])
    guardian = guardian_headers(family)

    set_clock("2026-09-10T00:00:00Z")
    t2_slot0 = ctx["teacher_slots"][t2["id"]][0]
    book_slot(t2_slot0["id"], st_y["id"], guardian)

    entry = get_success_data(api.create_waitlist_entry(
        create_waitlist_entry_payload(ctx["window"]["id"], st_x["id"], t1["id"], "EITHER"),
        guardian,
    ))
    assert_waitlist_entry(entry)
    # 100 base + 50 required + 15 * min(1 sibling confirmed, 2) = 165.00.
    assert entry["priority_score"] == pytest.approx(165.00, abs=0.01)

    # 50 hours later the patience term adds 5 * floor(50/24) = 10.
    set_clock("2026-09-12T02:00:00Z")
    run_ops(ctx["window"]["id"])
    refreshed = validate_success(api.get_waitlist_entry(entry["id"], front_office_headers))
    assert refreshed["priority_score"] == pytest.approx(175.00, abs=0.01)


def test_promotion_tie_break_created_at_asc(api, front_office_headers):
    """PRD 3.6: "Candidates are ranked by `priority_score` descending, ties
    broken by `created_at` ascending, and final ties by the entry's
    `created_seq` — a server-assigned, strictly increasing global creation
    sequence."
    PRD 3.6: "An offer moves the entry from `WAITING` to `OFFERED` and the slot
    from `OPEN` to `HELD` in the same sweep."

    Design: Corner/calculations/promotion_tie_break_created_at_asc
    """
    ctx = setup_window_at_stage("BOOKING_OPEN")
    teacher_id = ctx["teachers"][0]["id"]
    slot0 = ctx["teacher_slots"][teacher_id][0]

    first = setup_family_with_students(ctx, 1)
    incumbent = book_slot(slot0["id"], first["students"][0]["id"], first["guardian"])

    set_clock("2026-09-05T09:00:00Z")
    second = setup_family_with_students(ctx, 1, grade_levels=[4])
    entry_early = get_success_data(api.create_waitlist_entry(
        create_waitlist_entry_payload(ctx["window"]["id"], second["students"][0]["id"],
                                      teacher_id, "EITHER"),
        second["guardian"],
    ))
    set_clock("2026-09-05T10:00:00Z")
    third = setup_family_with_students(ctx, 1, grade_levels=[5])
    entry_late = get_success_data(api.create_waitlist_entry(
        create_waitlist_entry_payload(ctx["window"]["id"], third["students"][0]["id"],
                                      teacher_id, "EITHER"),
        third["guardian"],
    ))

    # Both entries score 100.00; the earlier created_at wins the freed slot.
    get_success_data(api.cancel_booking(incumbent["id"], {}, first["guardian"]))

    early_after = validate_success(api.get_waitlist_entry(entry_early["id"], front_office_headers))
    late_after = validate_success(api.get_waitlist_entry(entry_late["id"], front_office_headers))
    assert early_after["status"] == "OFFERED"
    assert early_after["offered_slot_id"] == slot0["id"]
    assert late_after["status"] == "WAITING"
    slot_after = validate_success(api.get_slot(slot0["id"], front_office_headers))
    assert slot_after["status"] == "HELD"


def test_promotion_skips_declining_entry_for_same_slot(api, front_office_headers):
    """PRD 3.6: "Either way, the declined slot is appended to
    `declined_slot_ids`, `offered_slot_id` and `offer_expires_at` are cleared,
    and the slot moves from `HELD` back to `OPEN` with the promotion sweep
    re-run — the declining entry is ineligible for that same slot ever again,
    so the sweep necessarily considers other candidates."
    PRD 3.6: "Its candidate pool is the `WAITING` entries whose `teacher_id`
    and `window_id` match the slot, excluding any entry whose
    `declined_slot_ids` already contains this slot, and requiring channel
    compatibility: an `EITHER` preference is compatible with any slot, an
    `IN_PERSON` preference requires the slot's `channel_allowed` to be
    `IN_PERSON` or `EITHER`, and a `VIRTUAL` preference likewise requires
    `VIRTUAL` or `EITHER`."

    Design: Corner/calculations/promotion_skips_declining_entry_for_same_slot
    """
    ctx = setup_window_at_stage(
        "BOOKING_OPEN",
        window_overrides={"name": "Sec", "format": "SECONDARY"},
        teacher_specs=[{"full_name": "T1", "grade_band": "SECONDARY", "subjects": ["math"]}],
    )
    teacher_id = ctx["teachers"][0]["id"]
    slot0 = ctx["teacher_slots"][teacher_id][0]

    first = setup_family_with_students(ctx, 1, grade_levels=[9])
    incumbent = book_slot(slot0["id"], first["students"][0]["id"], first["guardian"])

    # Entry E1 carries a required-conference link (score 150.00); E2 is plain
    # (score 100.00), so E1 ranks first and takes the initial offer.
    second = setup_family_with_students(ctx, 1, grade_levels=[10],
                                        link_overrides={"required_conference": True})
    entry_high = get_success_data(api.create_waitlist_entry(
        create_waitlist_entry_payload(ctx["window"]["id"], second["students"][0]["id"],
                                      teacher_id, "EITHER"),
        second["guardian"],
    ))
    third = setup_family_with_students(ctx, 1, grade_levels=[11])
    entry_low = get_success_data(api.create_waitlist_entry(
        create_waitlist_entry_payload(ctx["window"]["id"], third["students"][0]["id"],
                                      teacher_id, "EITHER"),
        third["guardian"],
    ))

    get_success_data(api.cancel_booking(incumbent["id"], {}, first["guardian"]))
    offered = validate_success(api.get_waitlist_entry(entry_high["id"], front_office_headers))
    assert offered["status"] == "OFFERED"
    assert offered["offered_slot_id"] == slot0["id"]

    get_success_data(api.decline_offer(entry_high["id"], second["guardian"]))

    high_after = validate_success(api.get_waitlist_entry(entry_high["id"], front_office_headers))
    assert high_after["status"] == "WAITING"
    assert slot0["id"] in high_after["declined_slot_ids"]

    # The re-run skips the declining entry and offers the same slot to E2.
    low_after = validate_success(api.get_waitlist_entry(entry_low["id"], front_office_headers))
    assert low_after["status"] == "OFFERED"
    assert low_after["offered_slot_id"] == slot0["id"]


def test_offer_claim_at_exact_expiry_succeeds(api):
    """PRD 3.6: "The entry must be `OFFERED` (otherwise `ERR_NO_ACTIVE_OFFER`),
    the logical clock must be on or before `offer_expires_at` — the deadline is
    inclusive, so a claim at exactly the expiry instant succeeds and a strictly
    later one is rejected with `ERR_OFFER_EXPIRED` — and a guardian caller must
    own the entry's family."
    PRD 3.6: "A successful claim creates the booking in `CONFIRMED` status,
    moves the slot from `HELD` to `BOOKED`, moves the entry from `OFFERED` to
    `CLAIMED` — a terminal state — and recomputes compactness and window
    counters. Because claim creates a new booking resource, it answers with the
    creation status code."

    Design: Difficulty/boundary_precision_check/offer_claim_at_exact_expiry_succeeds
    """
    ctx = setup_offered_entry(channel_pref="IN_PERSON",
                              offer_clock="2026-09-10T10:00:00Z")
    entry = validate_success(api.get_waitlist_entry(ctx["entry"]["id"], ctx["second_guardian"]))
    assert entry["status"] == "OFFERED"
    # Offer TTL 24h from the 2026-09-10T10:00Z offer lands at 2026-09-11T10:00Z.
    assert_instant(entry["offer_expires_at"], "2026-09-11T10:00:00Z", "offer_expires_at")

    set_clock("2026-09-11T10:00:00Z")
    booking = validate_success(api.claim_offer(
        ctx["entry"]["id"], {"channel": "IN_PERSON"}, ctx["second_guardian"]
    ), 201)
    assert booking["status"] == "CONFIRMED"
    assert booking["slot_id"] == ctx["slot0"]["id"]

    entry_after = validate_success(
        api.get_waitlist_entry(ctx["entry"]["id"], ctx["second_guardian"]))
    assert entry_after["status"] == "CLAIMED"
    slot_after = validate_success(api.get_slot(ctx["slot0"]["id"], ctx["second_guardian"]))
    assert slot_after["status"] == "BOOKED"


def test_offer_state_snapshot_before_boundary_claim(api, front_office_headers):
    """PRD 3.6: "An offer moves the entry from `WAITING` to `OFFERED` and the
    slot from `OPEN` to `HELD` in the same sweep. The entry records the slot as
    its `offered_slot_id`, sets `offer_expires_at` to the logical clock plus
    the window's `waitlist_offer_ttl_hours`, and increments `offers_made_count`
    by one."

    Design: Difficulty/boundary_precision_check/offer_claim_at_exact_expiry_succeeds
    """
    ctx = setup_offered_entry(channel_pref="IN_PERSON",
                              offer_clock="2026-09-10T10:00:00Z")
    entry = validate_success(api.get_waitlist_entry(ctx["entry"]["id"], front_office_headers))
    assert_waitlist_entry(entry)
    assert entry["status"] == "OFFERED"
    assert entry["offers_made_count"] == 1
    assert entry["offered_slot_id"] == ctx["slot0"]["id"]
    assert_instant(entry["offer_expires_at"], "2026-09-11T10:00:00Z", "offer_expires_at")

    slot = validate_success(api.get_slot(ctx["slot0"]["id"], front_office_headers))
    assert slot["status"] == "HELD"

    # Claiming at the exact deadline converts the held slot into a booking.
    set_clock("2026-09-11T10:00:00Z")
    booking = validate_success(api.claim_offer(
        ctx["entry"]["id"], {"channel": "IN_PERSON"}, ctx["second_guardian"]
    ), 201)
    assert booking["status"] == "CONFIRMED"
    window_after = read_window(ctx["window"]["id"])
    assert window_after["slots_held_count"] == 0
    assert window_after["slots_booked_count"] == 1


def test_expired_offer_claim_rejected(api):
    """PRD 3.6: "The entry must be `OFFERED` (otherwise `ERR_NO_ACTIVE_OFFER`),
    the logical clock must be on or before `offer_expires_at` — the deadline is
    inclusive, so a claim at exactly the expiry instant succeeds and a strictly
    later one is rejected with `ERR_OFFER_EXPIRED` — and a guardian caller must
    own the entry's family."

    Design: Corner/validations/expired_offer_claim_rejected
    """
    ctx = setup_offered_entry(offer_clock="2026-09-10T10:00:00Z")
    # One second strictly past the 2026-09-11T10:00:00Z expiry.
    set_clock("2026-09-11T10:00:01Z")

    response = api.claim_offer(ctx["entry"]["id"], {"channel": "IN_PERSON"},
                               ctx["second_guardian"])
    validate_error(response, ApiErrorId.ERR_OFFER_EXPIRED, 422)

    entry = validate_success(
        api.get_waitlist_entry(ctx["entry"]["id"], ctx["second_guardian"]))
    assert entry["status"] == "OFFERED"


def test_ops_sweep_expires_offer_and_releases_slot(api, front_office_headers):
    """PRD 3.8: "First, offer expiry: every `OFFERED` waitlist entry whose
    `offer_expires_at` is strictly before the logical clock follows the decline
    path of §3.6 — back to `WAITING` while `offers_made_count` is below 2, to
    `EXHAUSTED` at 2 — with the released slot returned to `OPEN` and the
    promotion sweep re-run."
    PRD 3.8: "The ops checkpoint is the administrator's batched housekeeping
    run over a window. It increments the window's `ops_run_index` by one and
    performs three sweeps."

    Design: Corner/validations/ops_sweep_expires_offer_and_releases_slot
    """
    ctx = setup_offered_entry(offer_clock="2026-09-10T10:00:00Z")
    set_clock("2026-09-12T00:00:00Z")

    window_after = run_ops(ctx["window"]["id"])
    assert window_after["ops_run_index"] == 1

    entry = validate_success(
        api.get_waitlist_entry(ctx["entry"]["id"], front_office_headers))
    assert_waitlist_entry(entry)
    assert entry["status"] == "WAITING"
    assert entry["offers_made_count"] == 1
    assert entry["offered_slot_id"] is None
    assert ctx["slot0"]["id"] in entry["declined_slot_ids"]

    # The re-run sweep skips the only candidate for the slot it declined.
    slot = validate_success(api.get_slot(ctx["slot0"]["id"], front_office_headers))
    assert slot["status"] == "OPEN"


def test_offer_cycle_first_decline_returns_to_waiting(api, front_office_headers):
    """PRD 3.6: "When an `OFFERED` entry is declined by the family or by staff
    — or when the ops checkpoint finds `offer_expires_at` strictly before the
    logical clock — the entry's fate depends on how many offers it has already
    consumed: while `offers_made_count` is below 2 the entry returns to
    `WAITING`, but at exactly 2 offers the entry moves to `EXHAUSTED` instead."

    Design: Difficulty/non_linear_state_machine/waitlist_offer_cycle_to_exhausted
    """
    ctx = scenario_offer_cycle()
    teacher_id = ctx["teachers"][0]["id"]
    slots = ctx["teacher_slots"][teacher_id]
    entry_id = ctx["entry"]["id"]

    get_success_data(api.cancel_booking(ctx["booking_a1"]["id"], {},
                                        ctx["party_a"]["guardian"]))
    offered = validate_success(api.get_waitlist_entry(entry_id, front_office_headers))
    assert offered["status"] == "OFFERED"
    assert offered["offers_made_count"] == 1
    assert offered["offered_slot_id"] == slots[0]["id"]

    declined = validate_success(api.decline_offer(entry_id, ctx["party_b"]["guardian"]))
    assert declined["status"] == "WAITING"
    assert slots[0]["id"] in declined["declined_slot_ids"]

    slot0 = validate_success(api.get_slot(slots[0]["id"], front_office_headers))
    assert slot0["status"] == "OPEN"


def test_offer_cycle_second_decline_exhausts_entry(api, front_office_headers):
    """PRD 3.6: "When an `OFFERED` entry is declined by the family or by staff
    — or when the ops checkpoint finds `offer_expires_at` strictly before the
    logical clock — the entry's fate depends on how many offers it has already
    consumed: while `offers_made_count` is below 2 the entry returns to
    `WAITING`, but at exactly 2 offers the entry moves to `EXHAUSTED` instead."

    Design: Difficulty/non_linear_state_machine/waitlist_offer_cycle_to_exhausted
    """
    ctx = scenario_offer_cycle()
    teacher_id = ctx["teachers"][0]["id"]
    slots = ctx["teacher_slots"][teacher_id]
    entry_id = ctx["entry"]["id"]

    # First offer/decline cycle on slot 0.
    get_success_data(api.cancel_booking(ctx["booking_a1"]["id"], {},
                                        ctx["party_a"]["guardian"]))
    get_success_data(api.decline_offer(entry_id, ctx["party_b"]["guardian"]))

    # Second cycle: the next freed slot is offered (the declined one is
    # excluded), and the second decline exhausts the entry.
    get_success_data(api.cancel_booking(ctx["booking_a2"]["id"], {},
                                        ctx["party_a"]["guardian"]))
    offered = validate_success(api.get_waitlist_entry(entry_id, front_office_headers))
    assert offered["status"] == "OFFERED"
    assert offered["offers_made_count"] == 2
    assert offered["offered_slot_id"] == slots[1]["id"]

    exhausted = validate_success(api.decline_offer(entry_id, ctx["party_b"]["guardian"]))
    assert exhausted["status"] == "EXHAUSTED"

    for slot in (slots[0], slots[1]):
        current = validate_success(api.get_slot(slot["id"], front_office_headers))
        assert current["status"] == "OPEN"
