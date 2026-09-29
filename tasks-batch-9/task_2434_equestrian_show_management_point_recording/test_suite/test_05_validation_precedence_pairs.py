"""Requests that break two rules at once, and which of the two the ladder reports."""

from test_helpers import api_client, validate_error, validate_success
from test_helpers.factories import (
    create_class_entry_payload,
    create_official_assignment_payload,
)
from test_helpers.fixtures import (
    approve_license,
    book_slot,
    build_approved_show,
    build_entry,
    card_official,
    create_class,
    create_division,
    create_horse,
    create_official,
    create_rider,
    create_ring,
    create_show,
    get_class,
    get_official,
    open_class,
)
from test_helpers.test_users import TEST_USERS, make_exhibitor_headers

STALE_COGGINS_DRAWN_ON = "2025-06-01T00:00:00Z"


def _planned_class_and_stale_coggins_entry():
    """An APPROVED show whose class was never opened, plus an entry whose horse is out of date."""
    ctx = build_approved_show(open_classes=False)
    rider = create_rider()
    horse = create_horse(coggins_drawn_on=STALE_COGGINS_DRAWN_ON)
    row = build_entry(ctx["show_id"], rider["id"], horse["id"])
    ctx.update(row)
    ctx["horse"] = horse
    return ctx


def _two_rings_two_disciplines_and_two_judges():
    """A LOCAL show with a HUNTER slot on Ring A and a JUMPER slot on Ring B, 10 minutes apart."""
    show = create_show()
    ring_a = create_ring(show["id"], name="Ring A")
    ring_b = create_ring(show["id"], name="Ring B")
    hunter_division = create_division(
        show["id"],
        name="Open Hunter",
        discipline="HUNTER",
        min_jump_height_cm=80,
        max_jump_height_cm=100,
        division_share_bp=3000,
        jumpoff_enabled=False,
    )
    hunter_class = create_class(
        hunter_division["id"],
        class_number=201,
        name="Open Hunter 0.90m",
        jump_height_cm=90,
        class_share_bp=1000,
    )
    jumper_division = create_division(show["id"])
    jumper_class = create_class(jumper_division["id"])
    approve_license(show["id"])
    open_class(hunter_class["id"])
    open_class(jumper_class["id"])

    hunter_slot = book_slot(ring_a["id"], hunter_class["id"], "2026-09-10T14:00:00Z")
    jumper_slot = book_slot(ring_b["id"], jumper_class["id"], "2026-09-10T14:30:00Z")

    hunter_only = create_official(license_roles=["JUDGE"], licensed_disciplines=["HUNTER"])
    dual_licensed = create_official(
        license_roles=["JUDGE"], licensed_disciplines=["HUNTER", "JUMPER"]
    )
    return {
        "hunter_slot": hunter_slot,
        "jumper_slot": jumper_slot,
        "hunter_only": hunter_only,
        "dual_licensed": dual_licensed,
    }


def test_closed_class_state_outranks_the_expired_coggins_on_the_same_request():
    """The class was never opened and the horse's Coggins lapsed on 2026-06-01, before the show
    starts, so one request violates a band-9 state rule and a band-11 safety rule at once. The
    ladder reports the state rule: ERR_CLASS_NOT_OPEN, alone, with no trace of the Coggins
    objection anywhere in the envelope, and no class entry is created.

    PRD §2.12: "When more than one rule would reject a request, the earlier rule in the following ladder wins, and its error is the one returned."
    PRD §2.12: "The ordering is normative: a request that violates several rules must report the first violation in this sequence, not the most specific one and not the last one evaluated."
    PRD §3.5: "The class must be `OPEN`, otherwise `ERR_CLASS_NOT_OPEN`."
    PRD §3.4: "The service derives `coggins_expires_on` as `coggins_drawn_on` plus 365 days, and sets `eligibility_status` to `ELIGIBLE`."
    PRD §3.5: "Creation recomputes the class's `entry_count`, `confirmed_entry_count` and `point_eligible`, and increments the class's `version`."

    Design: Difficulty/priority_pair_validation_conflict/class_not_open_outranks_coggins_expired
    """
    ctx = _planned_class_and_stale_coggins_entry()

    assert ctx["horse"]["coggins_expires_on"] == "2026-06-01T00:00:00Z"
    assert ctx["horse"]["eligibility_status"] == "ELIGIBLE"
    assert get_class(ctx["class_id"])["status"] == "PLANNED"

    response = api_client.create_class_entry(
        create_class_entry_payload(ctx["entry_id"], ctx["class_id"]),
        make_exhibitor_headers(ctx["rider_id"]),
    )
    error = validate_error(response, "ERR_CLASS_NOT_OPEN", 409)

    assert error["error_id"] == "ERR_CLASS_NOT_OPEN"
    assert "ERR_COGGINS_EXPIRED" not in response.text

    assert get_class(ctx["class_id"])["entry_count"] == 0


def test_the_outranked_coggins_rule_fires_once_the_class_is_open():
    """Opening the class removes the band-9 objection and nothing else. The identical request
    now surfaces the band-11 safety rule that was live all along — ERR_COGGINS_EXPIRED, because
    the certificate expired before the show's start instant — and the class still admits nobody.

    PRD §2.12: "Safety, welfare and licence-sufficiency rules (rider membership, Coggins validity, horse eligibility, official licence coverage, footing safety, veterinary coverage, the required-officials matrix, the welfare strike limit) — in that internal order."
    PRD §3.5: "The horse's `coggins_expires_on` must still be at or after the show's `start_utc` and its `eligibility_status` must still be `ELIGIBLE`, failing which `ERR_COGGINS_EXPIRED` and `ERR_HORSE_SUSPENDED` respectively."
    PRD §3.5: "The Coggins and eligibility checks are not unique to verification: both are re-run whenever the entry is added to a class, with the same two error codes."

    Design: Difficulty/priority_pair_validation_conflict/class_not_open_outranks_coggins_expired
    """
    ctx = _planned_class_and_stale_coggins_entry()
    validate_error(
        api_client.create_class_entry(
            create_class_entry_payload(ctx["entry_id"], ctx["class_id"]),
            make_exhibitor_headers(ctx["rider_id"]),
        ),
        "ERR_CLASS_NOT_OPEN",
        409,
    )

    opened = open_class(ctx["class_id"])
    assert opened["status"] == "OPEN"

    validate_error(
        api_client.create_class_entry(
            create_class_entry_payload(ctx["entry_id"], ctx["class_id"]),
            make_exhibitor_headers(ctx["rider_id"]),
        ),
        "ERR_COGGINS_EXPIRED",
        422,
    )

    assert get_class(ctx["class_id"])["entry_count"] == 0


def test_licence_insufficiency_outranks_the_travel_gap_collision_it_shares_a_request_with():
    """A HUNTER-only judge already carded on the 13:30-14:20 Ring A occupancy is offered the
    14:00-14:50 Ring B occupancy. That single card breaks two rules: the judge is not licensed
    for JUMPER (band 11) and the two closed windows collide across rings once the 20-minute
    travel gap is applied (band 13). The first check in the carding order answers, so the
    refusal is ERR_OFFICIAL_LICENSE_INSUFFICIENT and not ERR_OFFICIAL_TIME_CONFLICT, and the
    rejected card leaves the load ledger at its existing 50 minutes.

    PRD §3.6: "Four checks guard the card, and they run in this order."
    PRD §3.6: "First, licence sufficiency: the requested `official_role` must be a member of the official's `license_roles`; the discipline of the booked class's division must be a member of the official's `licensed_disciplines`; the official's `license_level` must be at least the minimum the show's `competition_level` demands — grade 1 for `LOCAL`, grade 2 for `REGIONAL`, grade 3 for `NATIONAL` and grade 4 for `PREMIER`; and the occupancy's `start_utc` must fall strictly before the official's `license_expires_on`, so an assignment beginning exactly at expiry is refused."
    PRD §3.6: "Any of those four failures is `ERR_OFFICIAL_LICENSE_INSUFFICIENT`."
    PRD §2.12: "Temporal rules (entry window, slot containment in the show window, ring overlap geometry, official overlap geometry) — in that internal order."
    PRD §3.6: "A new assignment has `status` of `ACTIVE`, and the official's `assigned_minutes` is increased by the whole minutes from the occupancy's `warmup_start_utc` to its `end_utc`; the official's `version` increments."

    Design: Difficulty/priority_pair_validation_conflict/official_license_outranks_time_conflict
    """
    ctx = _two_rings_two_disciplines_and_two_judges()
    hunter_only_id = ctx["hunter_only"]["id"]

    assert ctx["hunter_slot"]["end_utc"] == "2026-09-10T14:20:00Z"
    assert ctx["hunter_slot"]["warmup_start_utc"] == "2026-09-10T13:30:00Z"
    assert ctx["jumper_slot"]["end_utc"] == "2026-09-10T14:50:00Z"
    assert ctx["jumper_slot"]["warmup_start_utc"] == "2026-09-10T14:00:00Z"

    card_official(hunter_only_id, ctx["hunter_slot"]["id"], "JUDGE")
    assert get_official(hunter_only_id)["assigned_minutes"] == 50

    response = api_client.create_official_assignment(
        create_official_assignment_payload(hunter_only_id, ctx["jumper_slot"]["id"], "JUDGE"),
        TEST_USERS["show_secretary_headers"],
    )
    validate_error(response, "ERR_OFFICIAL_LICENSE_INSUFFICIENT", 422)
    assert "ERR_OFFICIAL_TIME_CONFLICT" not in response.text

    assert get_official(hunter_only_id)["assigned_minutes"] == 50

    body = api_client.list_official_assignments(
        TEST_USERS["show_secretary_headers"], params={"official_id": hunter_only_id}
    ).json()
    assert len(body["data"]) == 1
    assert body["data"][0]["status"] == "ACTIVE"
    assert body["data"][0]["slot_id"] == ctx["hunter_slot"]["id"]


def test_removing_the_licence_objection_exposes_the_travel_gap_collision():
    """The dual-licensed judge takes the Ring A occupancy cleanly, then is offered the same Ring
    B occupancy that produced the licence refusal for the HUNTER-only judge. With band 11
    satisfied, band 13 answers: 14:00 is at or before 14:20 plus the 20-minute cross-ring gap,
    and 13:30 is at or before 14:50 plus the same gap, so the closed windows collide and the
    card is refused with ERR_OFFICIAL_TIME_CONFLICT. The refused card adds no minutes.

    PRD §3.6: "The official's occupancy of an assignment runs on a *closed* interval from the assigned occupancy's `warmup_start_utc` to its `end_utc` — the supervised warm-up window counts as occupied time."
    PRD §3.6: "A required travel gap widens the comparison: zero minutes when the two occupancies are on the same ring, and 20 minutes when they are on different rings."
    PRD §3.6: "The candidate collides with an existing assignment when the candidate's `warmup_start_utc` is at or before the existing occupancy's `end_utc` advanced by the required gap, *and* the existing occupancy's `warmup_start_utc` is at or before the candidate's `end_utc` advanced by the required gap."
    PRD §3.6: "Any collision is `ERR_OFFICIAL_TIME_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/official_license_outranks_time_conflict
    """
    ctx = _two_rings_two_disciplines_and_two_judges()
    dual_id = ctx["dual_licensed"]["id"]

    accepted = validate_success(
        api_client.create_official_assignment(
            create_official_assignment_payload(dual_id, ctx["hunter_slot"]["id"], "JUDGE"),
            TEST_USERS["show_secretary_headers"],
        ),
        201,
    )
    assert accepted["status"] == "ACTIVE"
    assert get_official(dual_id)["assigned_minutes"] == 50

    validate_error(
        api_client.create_official_assignment(
            create_official_assignment_payload(dual_id, ctx["jumper_slot"]["id"], "JUDGE"),
            TEST_USERS["show_secretary_headers"],
        ),
        "ERR_OFFICIAL_TIME_CONFLICT",
        409,
    )

    assert get_official(dual_id)["assigned_minutes"] == 50
